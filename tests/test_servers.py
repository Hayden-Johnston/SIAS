import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('servers', Path(__file__).parents[1] / 'ops/servers.py')
servers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(servers)


@pytest.fixture
def configured(tmp_path):
    stub = tmp_path / 'llama-stub'
    stub.write_text(f'#!{sys.executable}\n' + '''import json, os, sys, time
from pathlib import Path
Path(sys.argv[sys.argv.index('--model') + 1]).write_text(json.dumps({
    'args': sys.argv[1:], 'env': dict(os.environ)}))
time.sleep(60)
''')
    stub.chmod(0o700)
    config = {'storage_dir': 'state', 'evaluator': {
        'binary': str(stub), 'model': 'launch.json', 'host': '127.0.0.1',
        'port': 8086, 'gpus': []}}
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    yield path, config
    pidfile = tmp_path / 'state/evaluator.pid.json'
    record = json.loads(pidfile.read_text()) if pidfile.exists() else None
    servers.manage('down', path)
    if record:
        try:
            os.waitpid(record['pid'], os.WNOHANG)
        except ChildProcessError:
            pass


def test_lifecycle_idempotent_cpu_only(configured, monkeypatch):
    path, _ = configured
    monkeypatch.setenv('LLAMA_ARG_N_GPU_LAYERS', '99')
    monkeypatch.setenv('LLAMA_ARG_PORT', '8099')
    monkeypatch.setenv('HIP_VISIBLE_DEVICES', '2,3,4,5,6')
    assert servers.manage('status', path) == 'down'
    assert servers.manage('down', path) == 'down'
    assert servers.manage('up', path) == 'up'
    pidfile = path.parent / 'state/evaluator.pid.json'
    first = pidfile.read_text()
    assert servers.manage('up', path) == 'up'
    assert pidfile.read_text() == first
    assert servers.manage('status', path) == 'up'
    capture = path.parent / 'launch.json'
    deadline = time.monotonic() + 5
    while not capture.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    launch = json.loads(capture.read_text())
    args = launch['args']
    assert args[args.index('--device') + 1] == 'none'
    assert args[args.index('--n-gpu-layers') + 1] == '0'
    assert args[args.index('--port') + 1] == '8086'
    for key in ('CUDA_VISIBLE_DEVICES', 'HIP_VISIBLE_DEVICES', 'ROCR_VISIBLE_DEVICES'):
        assert launch['env'][key] == ''
    assert not any(key.startswith('LLAMA_ARG_') for key in launch['env'])
    assert servers.manage('down', path) == 'down'
    assert servers.identity(json.loads(first)['pid']) is None
    os.waitpid(json.loads(first)['pid'], 0)
    assert not pidfile.exists()
    assert servers.manage('down', path) == 'down'


def test_down_preserves_unrelated_process_and_reused_pid(configured):
    path, _ = configured
    with subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']) as other:
        try:
            servers.manage('up', path)
            own = json.loads((path.parent / 'state/evaluator.pid.json').read_text())
            assert servers.manage('down', path) == 'down'
            os.waitpid(own['pid'], 0)
            assert other.poll() is None
            # A stale record that now points at an unrelated live PID cannot authorize a kill.
            pidfile = path.parent / 'state/evaluator.pid.json'
            pidfile.write_text(json.dumps({'pid': other.pid, 'identity': {
                'start': '0', 'command': 'stale'}}))
            assert servers.manage('status', path) == 'down'
            assert servers.manage('down', path) == 'down'
            assert other.poll() is None
        finally:
            other.terminate()


@pytest.mark.parametrize('field,value', [('port', 8099), ('port', '8099'), ('port', 0),
                                        *[('gpus', [gpu]) for gpu in range(7)],
                                        ('host', 'remote.example'), ('args', ['--port', '8099'])])
def test_reject_unsafe_config_without_launch(tmp_path, field, value, monkeypatch):
    config = {'storage_dir': 'state', 'evaluator': {
        'binary': 'unused', 'model': 'unused', 'host': '127.0.0.1', 'port': 8086, 'gpus': []}}
    config['evaluator'][field] = value
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))

    def forbidden(*args, **kwargs):
        pytest.fail('unsafe configuration must not launch or signal')

    monkeypatch.setattr(servers.subprocess, 'Popen', forbidden)
    monkeypatch.setattr(servers.os, 'pidfd_open', forbidden)
    for action in ('up', 'down', 'status'):
        with pytest.raises(ValueError):
            servers.manage(action, path)
    assert not (tmp_path / 'state').exists()


def test_failed_launch_leaves_no_pidfile(configured):
    path, config = configured
    stub = Path(config['evaluator']['binary'])
    stub.write_text(f'#!{sys.executable}\nraise SystemExit(1)\n')
    with pytest.raises(RuntimeError, match='exited on launch'):
        servers.manage('up', path)
    assert not (path.parent / 'state/evaluator.pid.json').exists()


def test_cli_status_and_unknown_set(configured):
    path, _ = configured
    script = Path(servers.__file__)
    result = subprocess.run([sys.executable, str(script), 'status', 'evaluator',
                             '--config', str(path)], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert result.stdout.strip() == 'evaluator: down'
    result = subprocess.run([sys.executable, str(script), 'down', 'maya',
                             '--config', str(path)], capture_output=True, text=True, check=False)
    assert result.returncode != 0


@pytest.mark.parametrize('argv,expected_code', [
    ([], 2),
    (['status'], 2),
    (['reboot', 'evaluator'], 2),
    (['status', 'evaluator', '--config'], 2),
])
def test_cli_arg_parsing(argv, expected_code):
    script = Path(servers.__file__)
    result = subprocess.run([sys.executable, str(script)] + argv,
                            capture_output=True, text=True, check=False)
    assert result.returncode == expected_code


def test_cli_missing_config_file(tmp_path):
    script = Path(servers.__file__)
    missing = tmp_path / 'nonexistent.json'
    result = subprocess.run([sys.executable, str(script), 'status', 'evaluator',
                             '--config', str(missing)], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert 'No such file' in result.stderr


def test_cli_empty_config_file(tmp_path):
    script = Path(servers.__file__)
    path = tmp_path / 'config.json'
    path.write_text('')
    result = subprocess.run([sys.executable, str(script), 'status', 'evaluator',
                             '--config', str(path)], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert result.stderr.strip() != ''


def test_cli_config_missing_keys(tmp_path):
    script = Path(servers.__file__)
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({}))
    result = subprocess.run([sys.executable, str(script), 'status', 'evaluator',
                             '--config', str(path)], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert 'storage_dir' in result.stderr
