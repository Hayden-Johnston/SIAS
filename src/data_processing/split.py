"""Assign normalized v2 rows to train/dev/test/heldout splits deterministically.

Near-duplicate deduplication is out of scope; see docs/datasets.md.
"""

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

from data_processing.normalize import canonical_json

SPLIT_VERSION = 2

SPLITS = ("train", "dev", "test", "heldout")


def _hash_to_split(name, proportions):
    """Hash a group to a split, sharing the test allocation with heldout."""
    digest = int.from_bytes(hashlib.sha256(name.encode("utf-8")).digest()[:4], "big")
    bucket = digest % 100
    cumulative = 0
    for split in SPLITS:
        weight = proportions[split] if split in ("train", "dev") else proportions["test"] / 2
        cumulative += weight * 100
        if bucket < cumulative:
            return split
    return "heldout"


def validate_split_config(config):
    """Validate a split config dict. Returns (heldout_families, proportions)."""
    if not isinstance(config, dict) or set(config) - {"heldout_families", "proportions"}:
        raise ValueError("split config accepts only heldout_families and proportions")
    heldout = config.get("heldout_families", [])
    if not isinstance(heldout, list) or any(not isinstance(f, str) or not f for f in heldout):
        raise ValueError("heldout_families must be a list of nonempty strings")
    proportions = config.get("proportions")
    if not isinstance(proportions, dict) or set(proportions) != {"train", "dev", "test"}:
        raise ValueError("proportions must have exactly train, dev, test keys")
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not (0 < v <= 1) for v in proportions.values()):
        raise ValueError("proportions must be numbers in (0, 1]")
    if abs(sum(proportions.values()) - 1.0) > 1e-9:
        raise ValueError("proportions must sum to 1")
    return heldout, proportions


def _verify_checksum(path, expected):
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError("input checksum does not match manifest output_sha256")


def split(input_path, manifest_path, config, output_dir):
    """Assign normalized rows to splits. Returns the split manifest dict.

    Rows are split by group_id, preserving variants together.
    Reserved attack families are assigned to the heldout split explicitly.
    A group_id that spans multiple families is an error.
    """
    input_path, manifest_path, output_dir = Path(input_path), Path(manifest_path), Path(output_dir)

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise ValueError("invalid manifest JSON or UTF-8") from None
    _verify_checksum(input_path, manifest["output_sha256"])

    heldout_families, proportions = validate_split_config(config)

    rows = []
    with input_path.open("rb") as f:
        for line_number, line in enumerate(f, 1):
            try:
                row = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeError):
                raise ValueError(f"line {line_number}: invalid JSON or UTF-8") from None
            rows.append(row)

    # A group_id must never span multiple attack families.
    group_families = {}
    for row in rows:
        gid, fam = row["group_id"], row["attack_family"]
        if gid in group_families and group_families[gid] != fam:
            raise ValueError("group_id spans multiple attack families")
        group_families[gid] = fam

    # Assign each row to a split.
    split_rows = {s: [] for s in SPLITS}
    for row in rows:
        if row["label"] == 1 and row["attack_family"] in heldout_families:
            split_name = "heldout"
        else:
            split_name = _hash_to_split(row["group_id"], proportions)
        split_rows[split_name].append(row)

    # Write one JSONL per split.
    output_dir.mkdir(parents=True, exist_ok=True)
    split_hashes = {}
    for split_name in SPLITS:
        out_path = output_dir / f"{split_name}.jsonl"
        h = hashlib.sha256()
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=output_dir, delete=False) as writer:
                temp_path = Path(writer.name)
                for row in split_rows[split_name]:
                    encoded = (canonical_json(row) + "\n").encode("utf-8")
                    writer.write(encoded)
                    h.update(encoded)
            os.replace(temp_path, out_path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        split_hashes[split_name] = h.hexdigest()

    # Build manifest with counts per split; no text.
    result = {
        "schema_version": 2,
        "split_version": SPLIT_VERSION,
        "input_sha256": manifest["output_sha256"],
        "config_sha256": hashlib.sha256(canonical_json(config).encode()).hexdigest(),
        "splits": {},
        "evaluator_approved": False,
    }
    for split_name in SPLITS:
        result["splits"][split_name] = {
            "records": len(split_rows[split_name]),
            "output_sha256": split_hashes[split_name],
            "labels": dict(Counter(str(r["label"]) for r in split_rows[split_name])),
            "channels": dict(Counter(r["channel"] for r in split_rows[split_name])),
            "techniques": dict(Counter(t for r in split_rows[split_name] for t in r["techniques"])),
            "attack_families": dict(Counter(r["attack_family"] for r in split_rows[split_name])),
        }

    # Write manifest last as the completion marker.
    manifest_out = output_dir / "split_manifest.json"
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=output_dir, delete=False) as writer:
            temp_path = Path(writer.name)
            writer.write((canonical_json(result) + "\n").encode("utf-8"))
        os.replace(temp_path, manifest_out)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        try:
            config = json.loads(args.config.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError):
            raise ValueError("invalid config JSON or UTF-8") from None
        result = split(args.input, args.manifest, config, args.output_dir)
    except ValueError as error:
        parser.exit(2, f"split failed: {error}\n")
    except OSError:
        parser.exit(2, "split failed: file operation failed\n")
    print(canonical_json(result))


if __name__ == "__main__":
    main()
