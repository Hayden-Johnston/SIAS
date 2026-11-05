"""Audit benign false positives by channel and source from pinned caches, without inference."""

import argparse
from pathlib import Path

from data_processing import run
from data_processing.normalize import canonical_json


def summary(rows, detected):
    ids = sorted(row["id"] for row in rows if row["id"] in detected)
    return {"benign": len(rows), "fp": len(ids), "false_positive": run.rate(len(ids), len(rows)),
            "ids": ids}


def audit(config_path, split_manifest_path, output):
    config_path, split_manifest_path, output = map(
        Path, (config_path, split_manifest_path, output))
    config, manifest, rows, stages, identity, inputs, _ = run.prepare(config_path)
    split_name = {"validation": "dev", "held_out": "heldout"}.get(config["evaluation_split"])
    if split_name is None:
        raise ValueError("audit requires a validation or held_out run")
    split_manifest = run.load_json(split_manifest_path)
    if (not isinstance(split_manifest, dict) or split_manifest.get("schema_version") != 2
            or not isinstance(split_manifest.get("splits"), dict)):
        raise ValueError("invalid split manifest")
    split = split_manifest["splits"].get(split_name)
    if (not isinstance(split, dict) or split.get("output_sha256") != manifest["output_sha256"]
            or type(split.get("records")) is not int or split["records"] != len(rows)):
        raise ValueError("split manifest checksum or record count mismatch")
    if output.resolve() in inputs | {split_manifest_path.resolve()}:
        raise ValueError("audit output must not overwrite input files")
    rules = [stage for stage, _ in stages if stage["name"] == "rules"]
    if not rules:
        raise ValueError("audit requires a stage named rules")

    # The runner discards source metadata. Read only benign IDs/sources for the join;
    # never retain or export dataset text, messages or model responses.
    sources = {row["id"]: row["source"]
               for _, row in run.read_rows(config_path.resolve().parent / config["dataset"])
               if row["label"] == 0}
    benign = [row | {"source": sources[row["id"]]} for row in rows if row["label"] == 0]
    flagged = {"rules": set(), "fused": set()}
    for row in benign:
        scored = run.evaluate(row, stages, config.get("fusion"))
        if scored["detected"]:
            flagged["fused"].add(row["id"])
        if next(stage["detected"] for stage in scored["stages"] if stage["stage"] == "rules"):
            flagged["rules"].add(row["id"])
    result = {
        "schema_version": 1, "evaluation_split": config["evaluation_split"],
        "identity_sha256": identity, "split_manifest_sha256": run.digest(split_manifest_path),
        "evaluator_approved": manifest.get("evaluator_approved") is True,
        "records": len(rows), "rules_threshold": rules[0]["threshold"],
        "fusion": {"threshold": config.get("fusion", {}).get("threshold", 0.5),
                   "weights": {stage["name"]: config.get("fusion", {}).get("weights", {}).get(
                       stage["name"], 1) for stage, _ in stages}},
    }
    for name, ids in flagged.items():
        result[name] = summary(benign, ids) | {
            "by_" + field: {
                value: summary([row for row in benign if row[field] == value], ids)
                for value in sorted({row[field] for row in benign})}
            for field in ("channel", "source")}
    output.parent.mkdir(parents=True, exist_ok=True)
    run.atomic_write(output, (canonical_json(result) + "\n").encode("utf-8"))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("split_manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        result = audit(args.config, args.split_manifest, args.output)
    except ValueError as error:
        parser.exit(2, f"FP audit failed: {error}\n")
    except OSError:
        parser.exit(2, "FP audit failed: file operation failed\n")
    print(canonical_json(result))


if __name__ == "__main__":
    main()
