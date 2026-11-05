"""Calibrate fixed fused scores on dev, then report held-out counts without inference."""

import argparse
import math
from pathlib import Path

from data_processing import run
from data_processing.normalize import CHANNELS, canonical_json


def load_results(path, split):
    path = Path(path)
    manifest = run.load_json(path)
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != 1
            or manifest.get("status") != "complete"
            or manifest.get("evaluation_split") != split):
        raise ValueError(f"a complete {split} run manifest is required")
    if manifest.get("results_file") != "results.jsonl":
        raise ValueError("run results_file must be results.jsonl")
    results_path = path.parent / "results.jsonl"
    if run.digest(results_path) != manifest.get("results_sha256"):
        raise ValueError("run results checksum mismatch")
    fusion = manifest.get("fusion", {})
    weights = fusion.get("weights") if isinstance(fusion, dict) else None
    stages = manifest.get("stages")
    if (not isinstance(fusion, dict) or fusion.get("method") != "max"
            or not isinstance(weights, dict) or not weights
            or not isinstance(stages, list) or not stages
            or any(not isinstance(stage, dict) or not isinstance(stage.get("name"), str)
                   or not isinstance(stage.get("version"), str) for stage in stages)
            or len({stage["name"] for stage in stages}) != len(stages)
            or set(weights) != {stage["name"] for stage in stages}):
        raise ValueError("max fusion weights and stage versions are required")
    for weight in weights.values():
        run.number(weight, "fusion weight", 1)
    rows, seen = [], set()
    for _, row in run.read_rows(results_path):
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
                or not row["id"].strip() or row["id"] in seen
                or type(row.get("label")) is not int or row["label"] not in (0, 1)
                or not isinstance(row.get("channel"), str) or row["channel"] not in CHANNELS):
            raise ValueError("invalid run result metadata or duplicate ID")
        seen.add(row["id"])
        rows.append({"label": row["label"], "channel": row["channel"],
                     "fused_score": run.number(row.get("fused_score"), "fused score", 1)})
    if type(manifest.get("records")) is not int or manifest["records"] != len(rows):
        raise ValueError("run record count mismatch")
    signature = (weights, sorted((s["name"], s["version"]) for s in stages))
    provenance = {"manifest_sha256": run.digest(path),
                  "results_sha256": manifest["results_sha256"],
                  "evaluator_approved": manifest.get("evaluator_approved") is True}
    return rows, signature, provenance, {path.resolve(), results_path.resolve()}


def measured(rows, threshold):
    results = [row | {"detected": row["fused_score"] >= threshold} for row in rows]
    return {"metrics": run.metrics(results), "by_channel": {
        channel: run.metrics(row for row in results if row["channel"] == channel)
        for channel in sorted({row["channel"] for row in rows})}}


def calibrate(dev_manifest, held_out_manifest, output=None):
    rows, signature, dev, inputs = load_results(dev_manifest, "validation")
    if {row["label"] for row in rows} != {0, 1}:
        raise ValueError("dev requires both attack and benign rows")
    benign = sorted((row["fused_score"] for row in rows if row["label"] == 0), reverse=True)
    points = []
    for denominator in (100, 1000):
        # With inclusive detection, the first disallowed benign score must be excluded.
        # nextafter gives the lowest representable threshold, including tied scores.
        threshold = math.nextafter(benign[len(benign) // denominator], math.inf)
        points.append({
            "fpr_cap": 1 / denominator, "threshold": threshold,
            "dev_benign": len(benign), "dev_fpr_resolution": 1 / len(benign),
            "too_few_dev_benign": len(benign) < denominator,
            "dev": measured(rows, threshold),
        })
    # Both choices are frozen before any held-out input is opened.
    held_rows, held_signature, held, held_inputs = load_results(held_out_manifest, "held_out")
    if signature != held_signature:
        raise ValueError("dev and held-out fusion weights and stage versions must match")
    for point in points:
        point["held_out"] = measured(held_rows, point["threshold"])
    result = {"schema_version": 1, "dev": dev, "held_out": held,
              "weights": signature[0], "operating_points": points}
    if output is not None:
        output = Path(output)
        if output.resolve() in inputs | held_inputs:
            raise ValueError("calibration output must not overwrite input files")
        output.parent.mkdir(parents=True, exist_ok=True)
        run.atomic_write(output, (canonical_json(result) + "\n").encode("utf-8"))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dev_manifest", type=Path)
    parser.add_argument("held_out_manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = calibrate(args.dev_manifest, args.held_out_manifest, args.output)
    except ValueError as error:
        parser.exit(2, f"calibration failed: {error}\n")
    except OSError:
        parser.exit(2, "calibration failed: file operation failed\n")
    print(canonical_json(result))


if __name__ == "__main__":
    main()
