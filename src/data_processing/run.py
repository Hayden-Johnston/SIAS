"""Replay a threshold cascade from local cached scores, without inference."""

import argparse
import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from pathlib import Path
from statistics import NormalDist

from data_processing.normalize import canonical_json, utc_timestamp, validate_record


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as reader:
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise ValueError("invalid JSON or UTF-8") from None


def read_rows(path):
    with Path(path).open("r", encoding="utf-8") as reader:
        try:
            for number, line in enumerate(reader, 1):
                try:
                    row = json.loads(line)
                except ValueError:
                    raise ValueError(f"line {number}: invalid JSON") from None
                yield number, row
        except UnicodeError:
            raise ValueError("invalid UTF-8") from None


def atomic_write(path, content):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as writer:
            temporary = Path(writer.name)
            writer.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def rate(successes, total):
    """Two-sided 95% Wilson interval; undefined rates stay null, never zero."""
    if total == 0:
        return {"value": None, "n": 0, "ci95": [None, None], "method": "wilson"}
    z = NormalDist().inv_cdf(0.975)
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return {"value": p, "n": total, "ci95": [max(0, center - half), min(1, center + half)],
            "method": "wilson"}


def metrics(results):
    counts = Counter({"tp": 0, "fp": 0, "fn": 0, "tn": 0})
    for row in results:
        counts[{(1, True): "tp", (0, True): "fp", (1, False): "fn", (0, False): "tn"}[
            row["label"], row["detected"]]] += 1
    return dict(counts) | {
        "detection": rate(counts["tp"], counts["tp"] + counts["fn"]),
        "false_positive": rate(counts["fp"], counts["fp"] + counts["tn"]),
    }


def number(value, name, maximum=None):
    if (type(value) not in (int, float) or not math.isfinite(value) or value < 0
            or (maximum is not None and value > maximum)):
        raise ValueError(f"{name} must be a finite number in the allowed range")
    return value


def prepare(config_path):
    """Validate the manifest, dataset, and pinned caches before touching a run."""
    config_path = Path(config_path)
    config = load_json(config_path)
    required = {"run_id", "timestamp", "iteration", "pipeline_version", "dataset",
                "dataset_manifest", "evaluation_split", "stages"}
    if not isinstance(config, dict) or set(config) != required:
        raise ValueError("run config must contain exactly the documented fields")
    for field in required - {"iteration", "stages"}:
        if not isinstance(config[field], str) or not config[field].strip():
            raise ValueError(f"{field} must be a nonempty string")
    if type(config["iteration"]) is not int or config["iteration"] < 0:
        raise ValueError("iteration must be a nonnegative integer")
    config["timestamp"] = utc_timestamp(config["timestamp"], "run timestamp")
    if config["evaluation_split"] not in {"train", "validation", "held_out"}:
        raise ValueError("evaluation_split must be train, validation, or held_out")
    if not isinstance(config["stages"], list) or not config["stages"]:
        raise ValueError("stages must be a nonempty list")
    base = config_path.resolve().parent
    dataset_path = base / config["dataset"]
    dataset_manifest_path = base / config["dataset_manifest"]
    dataset_manifest = load_json(dataset_manifest_path)
    if (not isinstance(dataset_manifest, dict) or dataset_manifest.get("schema_version") != 2
            or dataset_manifest.get("output_sha256") != digest(dataset_path)):
        raise ValueError("dataset manifest version/checksum mismatch; schema version 2 required")
    rows, ids = [], set()
    for line, row in read_rows(dataset_path):
        try:
            row = validate_record(row)
        except ValueError as error:
            raise ValueError(f"dataset line {line}: {error}") from None
        if row["id"] in ids:
            raise ValueError("duplicate dataset id")
        ids.add(row["id"])
        # Discard payload text before retaining results or reporting.
        rows.append({key: row[key] for key in ("id", "label", "attack_family")})
    if dataset_manifest.get("records") != len(rows):
        raise ValueError("dataset manifest record count mismatch")
    stages, cache_paths, names = [], [], set()
    for stage in config["stages"]:
        fields = {"name", "version", "threshold", "cache", "cache_sha256"}
        if not isinstance(stage, dict) or set(stage) != fields:
            raise ValueError("stage must contain exactly the documented fields")
        for field in fields - {"threshold"}:
            if not isinstance(stage[field], str) or not stage[field].strip():
                raise ValueError(f"stage {field} must be a nonempty string")
        if stage["name"] in names:
            raise ValueError("duplicate stage name")
        names.add(stage["name"])
        number(stage["threshold"], "threshold", 1)
        cache_path = base / stage["cache"]
        if digest(cache_path) != stage["cache_sha256"]:
            raise ValueError("cache checksum mismatch")
        cache_paths.append(cache_path.resolve())
        cache = {}
        for line, entry in read_rows(cache_path):
            if not isinstance(entry, dict) or set(entry) != {"id", "score", "latency_ms"}:
                raise ValueError(f"cache line {line}: invalid fields")
            if not isinstance(entry["id"], str) or entry["id"] not in ids:
                raise ValueError(f"cache line {line}: unknown dataset id")
            if entry["id"] in cache:
                raise ValueError(f"cache line {line}: duplicate id")
            number(entry["score"], "score", 1)
            number(entry["latency_ms"], "latency_ms")
            cache[entry["id"]] = entry
        stages.append((stage, cache))
    identity = {
        "runner_version": 1, "config": config,
        "dataset_sha256": dataset_manifest["output_sha256"],
        "dataset_manifest_sha256": digest(dataset_manifest_path),
    }
    identity_hash = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    inputs = {config_path.resolve(), dataset_path.resolve(), dataset_manifest_path.resolve(), *cache_paths}
    return config, dataset_manifest, rows, stages, identity_hash, inputs


def evaluate(row, stages):
    scores, detected = [], False
    for stage, cache in stages:
        if row["id"] not in cache:
            raise ValueError("missing required cached score; run inference separately")
        entry = cache[row["id"]]
        detected = entry["score"] >= stage["threshold"]
        scores.append({"stage": stage["name"], "score": entry["score"],
                       "latency_ms": entry["latency_ms"], "detected": detected})
        if detected:
            break
    return row | {"detected": detected, "stages": scores}


def replay(config_path, run_directory):
    config, dataset_manifest, rows, stages, identity, inputs = prepare(config_path)
    root = Path(run_directory)
    outputs = [root / name for name in ("results.jsonl", "manifest.json")]
    if inputs & {path.resolve() for path in outputs}:
        raise ValueError("run outputs must not overwrite input files")
    results = [evaluate(row, stages) for row in rows]
    results_bytes = "".join(canonical_json(row) + "\n" for row in results).encode("utf-8")
    results_path, manifest_path = outputs
    stage_results = []
    for stage, _ in stages:
        reached = [entry for row in results for entry in row["stages"]
                   if entry["stage"] == stage["name"]]
        latency = sum(entry["latency_ms"] for entry in reached)
        stage_results.append({"name": stage["name"], "version": stage["version"],
                              "threshold": stage["threshold"], "reached": len(reached),
                              "caught": sum(entry["detected"] for entry in reached),
                              "passed": sum(not entry["detected"] for entry in reached),
                              "score_summary": {
                                  "min": min((entry["score"] for entry in reached), default=None),
                                  "max": max((entry["score"] for entry in reached), default=None),
                                  "mean": sum(entry["score"] for entry in reached) / len(reached)
                                  if reached else None,
                              },
                              "cached_latency_ms_total": latency,
                              "cached_latency_ms_mean": latency / len(reached) if reached else None})
    manifest = {
        "schema_version": 1, "identity_sha256": identity, "status": "complete",
        "run_id": config["run_id"], "timestamp": config["timestamp"],
        "iteration": config["iteration"], "pipeline_version": config["pipeline_version"],
        "dataset_sha256": dataset_manifest["output_sha256"],
        "evaluation_split": config["evaluation_split"],
        "evaluator_approved": dataset_manifest.get("evaluator_approved") is True,
        "records": len(results), "metrics": metrics(results),
        "attack_distribution": dict(Counter(row["attack_family"] for row in rows if row["label"] == 1)),
        "stages": stage_results, "results_file": "results.jsonl",
        "results_sha256": hashlib.sha256(results_bytes).hexdigest(),
    }
    root.mkdir(parents=True, exist_ok=True)
    atomic_write(results_path, results_bytes)
    atomic_write(manifest_path, (canonical_json(manifest) + "\n").encode("utf-8"))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("run_directory", type=Path)
    args = parser.parse_args()
    try:
        result = replay(args.config, args.run_directory)
    except ValueError as error:
        parser.exit(2, f"replay failed: {error}\n")
    except OSError:
        parser.exit(2, "replay failed: file operation failed\n")
    print(canonical_json(result))


if __name__ == "__main__":
    main()
