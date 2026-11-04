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


def windows(length, chunk_chars, overlap_chars):
    """End-aligned windows in turn order, including one window for an empty turn."""
    last = max(0, length - chunk_chars)
    starts = list(range(0, last, chunk_chars - overlap_chars)) + [last]
    return [(start, min(start + chunk_chars, length)) for start in starts]


def length_bucket(length):
    # Character counts: short (4 Ki), medium (16 Ki), and long contexts.
    return "0-4096" if length <= 4096 else "4097-16384" if length <= 16384 else "16385+"


def location_metrics(rows):
    known = [row for row in rows if row["located"] is not None]

    def summary(group):
        return rate(sum(row["located"] for row in group), len(group))

    return {"overall": summary(known), **{
        "by_" + field: {value: summary([row for row in known if row[field] == value])
                        for value in sorted({row[field] for row in known})}
        for field in ("channel", "length_bucket")
    }}


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
    row_by_id = {}
    for line, row in read_rows(dataset_path):
        try:
            row = validate_record(row)
        except ValueError as error:
            raise ValueError(f"dataset line {line}: {error}") from None
        if row["id"] in ids:
            raise ValueError("duplicate dataset id")
        ids.add(row["id"])
        # Discard payload text before retaining results or reporting.
        turns = ([message["content"] for message in json.loads(row["text"])]
                 if row["channel"] == "multi_turn" else [row["text"]])
        metadata = {key: row[key] for key in ("id", "label", "attack_family", "channel", "spans")}
        metadata["turn_lengths"] = [len(turn) for turn in turns]
        metadata["length_bucket"] = length_bucket(sum(metadata["turn_lengths"]))
        rows.append(metadata)
        row_by_id[row["id"]] = metadata
    if dataset_manifest.get("records") != len(rows):
        raise ValueError("dataset manifest record count mismatch")
    stages, cache_paths, names = [], [], set()
    for stage in config["stages"]:
        fields = {"name", "version", "threshold", "cache", "cache_sha256"}
        chunk_fields = {"chunk_chars", "overlap_chars"}
        if not isinstance(stage, dict) or set(stage) not in (fields, fields | chunk_fields):
            raise ValueError("stage must contain exactly the documented fields")
        if "chunk_chars" in stage and (
                type(stage["chunk_chars"]) is not int or stage["chunk_chars"] <= 0
                or type(stage["overlap_chars"]) is not int
                or not 0 <= stage["overlap_chars"] < stage["chunk_chars"]):
            raise ValueError("require integer chunk_chars > overlap_chars >= 0")
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
            entry_fields = {"id", "score", "latency_ms"}
            if "chunk_chars" in stage:
                entry_fields |= {"turn", "start"}
            if not isinstance(entry, dict) or set(entry) != entry_fields:
                raise ValueError(f"cache line {line}: invalid fields")
            if not isinstance(entry["id"], str) or entry["id"] not in ids:
                raise ValueError(f"cache line {line}: unknown dataset id")
            key = entry["id"]
            if "chunk_chars" in stage:
                lengths = row_by_id[key]["turn_lengths"]
                turn, start = entry["turn"], entry["start"]
                if (type(turn) is not int or type(start) is not int
                        or not 0 <= turn < len(lengths)
                        or not (start == max(0, lengths[turn] - stage["chunk_chars"])
                                or (0 <= start < lengths[turn] - stage["chunk_chars"]
                                    and start % (stage["chunk_chars"] - stage["overlap_chars"]) == 0))):
                    raise ValueError(f"cache line {line}: invalid chunk coordinates")
                key = (key, turn, start)
            if key in cache:
                raise ValueError(f"cache line {line}: duplicate id/chunk")
            number(entry["score"], "score", 1)
            number(entry["latency_ms"], "latency_ms")
            cache[key] = entry
        stages.append((stage, cache))
    identity = {
        "runner_version": 2, "config": config,
        "dataset_sha256": dataset_manifest["output_sha256"],
        "dataset_manifest_sha256": digest(dataset_manifest_path),
    }
    identity_hash = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    inputs = {config_path.resolve(), dataset_path.resolve(), dataset_manifest_path.resolve(), *cache_paths}
    return config, dataset_manifest, rows, stages, identity_hash, inputs


def evaluate(row, stages):
    scores, detected = [], False
    for stage, cache in stages:
        if "chunk_chars" in stage:
            chunks = [(turn, start, end)
                      for turn, length in enumerate(row["turn_lengths"])
                      for start, end in windows(length, stage["chunk_chars"], stage["overlap_chars"])]
            keys = [(row["id"], turn, start) for turn, start, _ in chunks]
        else:
            keys = [row["id"]]
        if any(key not in cache for key in keys):
            raise ValueError("missing required cached score; run inference separately")
        entries = [cache[key] for key in keys]
        best = max(range(len(entries)), key=lambda index: entries[index]["score"])
        score = entries[best]["score"]
        detected = score >= stage["threshold"]
        result = {"stage": stage["name"], "score": score,
                  "latency_ms": sum(entry["latency_ms"] for entry in entries), "detected": detected}
        if "chunk_chars" in stage:
            turn, start, end = chunks[best]
            result["best_chunk"] = [turn, start, end]
            result["located"] = (any(t == turn and start < b and a < end
                                     for t, a, b in row["spans"])
                                 if row["label"] == 1 and row["spans"] is not None else None)
            result["spans_longer_than_overlap"] = sum(
                b - a > stage["overlap_chars"] for _, a, b in (row["spans"] or []))
        scores.append(result)
        if detected:
            break
    metadata = {key: value for key, value in row.items() if key not in {"spans", "turn_lengths"}}
    return metadata | {"detected": detected, "stages": scores}


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
        location = {}
        if "chunk_chars" in stage:
            location = {"chunk_chars": stage["chunk_chars"], "overlap_chars": stage["overlap_chars"],
                        "location": location_metrics([
                            entry | {"channel": row["channel"], "length_bucket": row["length_bucket"]}
                            for row in results for entry in row["stages"]
                            if entry["stage"] == stage["name"]]),
                        "spans_longer_than_overlap": sum(
                            entry["spans_longer_than_overlap"] for entry in reached)}
        stage_results.append(location | {"name": stage["name"], "version": stage["version"],
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
