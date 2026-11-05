"""Export held-out missed attack IDs from a completed replay run, without inference."""

import argparse
from collections import defaultdict
from pathlib import Path

from data_processing import run
from data_processing.normalize import CHANNELS, TECHNIQUES, canonical_json


def misses(manifest_path, output):
    manifest_path, output = Path(manifest_path), Path(output)
    manifest = run.load_json(manifest_path)
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != 1
            or manifest.get("status") != "complete"
            or manifest.get("evaluation_split") != "held_out"):
        raise ValueError("a complete held_out run manifest is required")
    if manifest.get("results_file") != "results.jsonl":
        raise ValueError("run results_file must be results.jsonl")
    results_path = manifest_path.parent / "results.jsonl"
    if output.resolve() in {manifest_path.resolve(), results_path.resolve()}:
        raise ValueError("misses output must not overwrite input files")
    if run.digest(results_path) != manifest.get("results_sha256"):
        raise ValueError("run results checksum mismatch")
    fusion = manifest.get("fusion")
    if not isinstance(fusion, dict) or "threshold" not in fusion:
        raise ValueError("run fusion threshold is required")
    threshold = run.number(fusion["threshold"], "fusion threshold", 1)
    groups = defaultdict(list)
    ids, seen = [], set()
    attacks = 0
    for _, row in run.read_rows(results_path):
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
                or not row["id"].strip() or row["id"] in seen
                or type(row.get("label")) is not int or row["label"] not in (0, 1)
                or not isinstance(row.get("channel"), str) or row["channel"] not in CHANNELS
                or not isinstance(row.get("techniques"), list)
                or any(not isinstance(item, str) or item not in TECHNIQUES
                       for item in row["techniques"])
                or len(set(row["techniques"])) != len(row["techniques"])):
            raise ValueError("invalid run result metadata or duplicate ID")
        seen.add(row["id"])
        score = run.number(row.get("fused_score"), "fused score", 1)
        if row["label"] == 1:
            attacks += 1
            if score < threshold:
                ids.append(row["id"])
                for technique in row["techniques"]:
                    groups[technique, row["channel"]].append(row["id"])
    if type(manifest.get("records")) is not int or manifest["records"] != len(seen):
        raise ValueError("run record count mismatch")
    result = {
        "schema_version": 1, "evaluation_split": "held_out",
        "manifest_sha256": run.digest(manifest_path),
        "results_sha256": manifest["results_sha256"], "threshold": threshold,
        "evaluator_approved": manifest.get("evaluator_approved") is True,
        "records": len(seen), "attacks": attacks, "missed": len(ids), "ids": sorted(ids),
        "groups": [{"technique": technique, "channel": channel,
                    "count": len(values), "ids": sorted(values)}
                   for (technique, channel), values in sorted(groups.items())],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    run.atomic_write(output, (canonical_json(result) + "\n").encode("utf-8"))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        result = misses(args.manifest, args.output)
    except ValueError as error:
        parser.exit(2, f"miss analysis failed: {error}\n")
    except OSError:
        parser.exit(2, "miss analysis failed: file operation failed\n")
    print(canonical_json(result))


if __name__ == "__main__":
    main()
