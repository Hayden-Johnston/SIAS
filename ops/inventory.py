#!/usr/bin/env python3
"""Read-only local rig snapshot. Run: python3 ops/inventory.py.

Only metadata is read; no model loading or server lifecycle commands are used.
Listening means a TCP socket exists, not that a model is healthy. INI entries
are available presets, not evidence of a loaded model or physical GPU mapping.
"""

import configparser
import json
import os
import re
import socket
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def parse_gpus(text):
    return [
        {"index": int(key[4:]), "vram_total_bytes": int(value["VRAM Total Memory (B)"]),
         "vram_used_bytes": int(value["VRAM Total Used Memory (B)"])}
        for key, value in sorted(json.loads(text).items()) if re.fullmatch(r"card\d+", key)
    ]


def parse_df(text):
    volumes = []
    for line in text.splitlines()[1:]:
        fields = line.split(maxsplit=5)
        if len(fields) == 6:
            device, total, used, free, percent, mount = fields
            volumes.append({"device": device, "total_bytes": int(total), "used_bytes": int(used),
                                "free_bytes": int(free), "used_percent": int(percent.rstrip('%')),
                                "mount": mount})
    return volumes


def parse_ss(text):
    listeners = []
    for line in text.splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) >= 5 and fields[0] == "LISTEN":
            host, port = fields[3].rsplit(":", 1)
            listeners.append({"host": host.strip("[]"), "port": int(port),
                              "process": fields[5] if len(fields) > 5 else None})
    return listeners


def parse_docker(text):
    # Deliberately omit commands, labels and environment: they can contain keys.
    return [{key.lower(): row.get(key, "") for key in ("Names", "Image", "Status", "Ports")}
            for line in text.splitlines() if line.strip() for row in [json.loads(line)]]


def parse_config(text):
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(text)
    defaults = dict(config["*"]) if config.has_section("*") else {}
    models = []
    for section in config.sections():
        values = defaults | dict(config[section])
        if section == "*" or "model" not in values:
            continue
        model = Path(values["model"]).name
        quant = re.search(r"(?i)(IQ\d+_[A-Z0-9_]+|Q\d+_[A-Z0-9_]+|BF16|F16|F32)(?=\.|$)", model)
        models.append({"name": section, "model": model,
                       "quant": quant[0].upper() if quant else None,
                       "ctx": int(values["ctx-size"]) if "ctx-size" in values else None,
                       "gpus": values.get("device"),
                       "port": int(values["port"]) if "port" in values else None})
    return models


def run(command, errors):
    try:
        return subprocess.run(command, capture_output=True, text=True, check=True,
                              timeout=5, env=os.environ | {"LC_ALL": "C"}).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        errors.append({"source": command[0], "error": type(exc).__name__})
        return None


def maya_status():
    key = os.environ.get("MAYA_API_KEY")
    if not key:
        return {"status": "skipped", "reason": "MAYA_API_KEY unset"}
    # Local only; never store the key or arbitrary response/error text.
    request = Request("http://127.0.0.1:8099/v1/models",
                      headers={"Authorization": f"Bearer {key}"})
    try:
        with urlopen(request, timeout=3) as response:
            body = json.load(response)
        return {"status": "up", "models": [row["id"] for row in body.get("data", [])]}
    except HTTPError as exc:
        return {"status": "http_error", "http_status": exc.code}
    except (URLError, OSError, ValueError, KeyError, TypeError):
        return {"status": "down"}


def disk_models(root, deadline, errors):
    """Count physical files once per model (HF snapshots link into blobs)."""
    models = []
    if not root.exists():
        errors.append({"source": str(root), "error": "missing"})
        return models
    # GGUF files are individual models; HF cache repositories aggregate all revisions.
    hf = root.name == "huggingface"
    def walk_error(exc):
        errors.append({"source": str(root), "error": type(exc).__name__})

    for directory, dirs, files in os.walk(root, onerror=walk_error):
        dirs.sort()
        if time.monotonic() >= deadline:
            errors.append({"source": str(root), "error": "scan_deadline"})
            break
        if hf:
            for name in list(dirs):
                if name.startswith("models--"):
                    path = Path(directory) / name
                    size = 0
                    seen = set()
                    for subdir, _, entries in os.walk(path, onerror=walk_error):
                        if time.monotonic() >= deadline:
                            errors.append({"source": str(root), "error": "scan_deadline"})
                            return models
                        for entry in entries:
                            try:
                                stat = (Path(subdir) / entry).stat()
                                identity = (stat.st_dev, stat.st_ino)
                                if identity not in seen:
                                    seen.add(identity)
                                    size += stat.st_size
                            except OSError as exc:
                                walk_error(exc)
                    models.append({"name": str(path.relative_to(root)), "size_bytes": size})
                    dirs.remove(name)
        else:
            for name in sorted(files):
                if name.lower().endswith(".gguf"):
                    path = Path(directory) / name
                    try:
                        models.append({"name": str(path.relative_to(root)),
                                       "size_bytes": path.stat().st_size})
                    except OSError as exc:
                        walk_error(exc)
    return models


def collect():
    started = time.monotonic()
    errors = []
    result = {"created": datetime.now(UTC).isoformat(), "host": socket.gethostname(),
              "errors": errors}
    for name, command, parser in [
        ("gpus", ["rocm-smi", "--showmeminfo", "vram", "--json"], parse_gpus),
        ("storage", ["df", "-B1", "-P"], parse_df),
        ("listeners", ["ss", "-ltnpH"], parse_ss),
        ("containers", ["docker", "ps", "--format", "{{json .}}"], parse_docker),
    ]:
        text = run(command, errors)
        result[name] = None
        if text is not None:
            try:
                result[name] = parser(text)
            except (ValueError, KeyError, TypeError) as exc:
                errors.append({"source": name, "error": type(exc).__name__})
    result["presets"] = []
    for path in sorted((Path.home() / "servers/llama/configs").glob("*.ini")):
        try:
            result["presets"].append({"config": path.name, "models": parse_config(path.read_text())})
        except (OSError, ValueError, configparser.Error) as exc:
            errors.append({"source": path.name, "error": type(exc).__name__})
    ports = {row["port"] for row in result["listeners"] or []}
    result["servers"] = [
        {"port": port, "status": ("unknown" if result["listeners"] is None else
                                  "listening" if port in ports else "down")}
        for port in range(8081, 8086)
    ]
    result["maya"] = maya_status()
    result["models"] = [
        {"root": str(root), "entries": disk_models(root, started + 50, errors)}
        for root in (Path("/mnt/storage/llama/models"), Path.home() / ".cache/huggingface")
    ]
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


def main():
    result = collect()
    output = ROOT / "data/inventory.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"GPUs: {len(result['gpus'] or [])}; containers: {len(result['containers'] or [])}; "
          f"Maya: {result['maya']['status']}")
    print("Servers: " + ", ".join(f"{s['port']} {s['status']}" for s in result['servers']))
    for volume in result['storage'] or []:
        if volume['mount'] in ('/', '/mnt/storage'):
            print(f"{volume['mount']}: {volume['used_percent']}% used, "
                  f"{volume['free_bytes'] / 2**30:.1f} GiB free")
    print(f"Models: {sum(len(row['entries']) for row in result['models'])}; "
          f"errors: {len(result['errors'])}; elapsed: {result['elapsed_seconds']}s")
    print(f"Snapshot: {output}")


if __name__ == "__main__":
    main()
