#!/usr/bin/env python3
"""Manage only the configured CPU evaluator; Linux /proc and pidfds are required."""

import argparse
import fcntl
import json
import os
import select
import signal
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_config(path):
    config = json.loads(path.read_text())
    if set(config) != {'storage_dir', 'evaluator'}:
        raise ValueError('configure only storage_dir and evaluator')
    server = config['evaluator']
    if set(server) != {'binary', 'model', 'host', 'port', 'gpus'}:
        raise ValueError('evaluator requires binary, model, host, port and gpus')
    if server['gpus'] != []:
        raise ValueError('CPU evaluator requires gpus=[]; GPUs 2-6 are protected')
    port = server['port']
    if type(port) is not int or not 1 <= port <= 65535 or port == 8099:
        raise ValueError('invalid port; Maya port 8099 is protected')
    if server['host'] not in ('127.0.0.1', '::1', 'localhost'):
        raise ValueError('evaluator host must be loopback')
    for key in ('binary', 'model'):
        server[key] = str((path.parent / server[key]).resolve())
    storage = (path.parent / config['storage_dir']).resolve()
    command = [server['binary'], '--model', server['model'],
               '--host', server['host'], '--port', str(port),
               '--device', 'none', '--n-gpu-layers', '0', '--ctx-size', '16384',
               '--threads', '4', '--parallel', '1', '--no-webui']
    return storage, command


def identity(pid):
    """Start tick and command distinguish an exited child from a reused PID."""
    try:
        proc = Path('/proc') / str(pid)
        fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
        if fields[0] == 'Z':
            return None
        return {'start': fields[19], 'command': (proc / 'cmdline').read_bytes().hex(),
                'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    except FileNotFoundError:
        return None


def owned_process(record):
    pid = record['pid']
    if type(pid) is not int or pid <= 1:
        raise ValueError('invalid recorded PID')
    try:
        fd = os.pidfd_open(pid)
    except ProcessLookupError:
        return None
    if identity(pid) != record['identity']:
        os.close(fd)
        return None
    return fd


def manage(action, config_path):
    storage, command = load_config(config_path)
    storage.mkdir(parents=True, exist_ok=True)
    pidfile = storage / 'evaluator.pid.json'
    # Serializes concurrent launch/teardown invocations, including stale PID cleanup.
    with (storage / 'evaluator.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        record = json.loads(pidfile.read_text()) if pidfile.exists() else None
        fd = owned_process(record) if record else None
        if fd is not None:
            try:
                if action == 'down':
                    signal.pidfd_send_signal(fd, signal.SIGTERM)
                    # Wait for exit before removing ownership; never escalate to a group kill.
                    if not select.select([fd], [], [], 10)[0]:
                        raise RuntimeError('evaluator did not stop; PID record retained')
                    pidfile.unlink()
                    return 'down'
                return 'up'
            finally:
                os.close(fd)
        if action != 'status':
            pidfile.unlink(missing_ok=True)
        if action != 'up':
            return 'down'
        env = {key: value for key, value in os.environ.items()
               if not key.startswith('LLAMA_ARG_')}
        env.update(CUDA_VISIBLE_DEVICES='', HIP_VISIBLE_DEVICES='', ROCR_VISIBLE_DEVICES='')
        with (storage / 'evaluator.log').open('ab') as log:
            process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=log, start_new_session=True)
        try:
            time.sleep(0.1)  # Catch immediate launch errors; this is not a health check.
            if process.poll() is not None:
                raise RuntimeError('evaluator exited on launch; inspect evaluator.log')
            record = {'pid': process.pid, 'identity': identity(process.pid)}
            pidfile.write_text(json.dumps(record) + '\n')
        except BaseException:
            if process.poll() is None:
                process.terminate()
            process.wait()
            raise
        return 'up'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('up', 'down', 'status'))
    parser.add_argument('set', choices=('evaluator',))
    parser.add_argument('--config', type=Path, default=ROOT / 'evaluator.local.json')
    args = parser.parse_args()
    try:
        print(f'evaluator: {manage(args.action, args.config.resolve())}')
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
