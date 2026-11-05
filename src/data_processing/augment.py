"""Add synthetic carriers to one pinned dataset split, without inference."""

import argparse
import hashlib
from collections import Counter
from pathlib import Path

from data_processing.normalize import canonical_json, validate_record
from data_processing.run import atomic_write, digest, load_json, read_rows
from data_processing.split import SPLITS

# Long-context augmentation uses at least 8 Ki Unicode characters of benign padding.
LONG_CHARS = 8192
TEMPLATES = {
    "document": ("Project notes\n\n", "\n\nEnd of project notes."),
    "email": ("Subject: Weekly project summary\n\nHello team,\n", "\nRegards,\nProject team"),
    "tool_output": ("Search results\n\n", "\n\nEnd of search results."),
}
BENIGN_NOTE = "The project review is scheduled for next week."


def _variants(row, padding, padding_licenses, seed):
    position = int(hashlib.sha256(canonical_json([row["id"], seed]).encode()).hexdigest(), 16) % 3
    for kind in (*TEMPLATES, "long_context"):
        channel = "document" if kind == "long_context" else kind
        before, after = TEMPLATES[channel]
        carrier = padding if kind == "long_context" else BENIGN_NOTE + "\n"
        offset = (0, len(carrier) // 2, len(carrier))[position]
        prefix, suffix = before + carrier[:offset] + "\n", "\n" + carrier[offset:] + after
        for label in (1, 0):
            embedded = row["text"] if label else BENIGN_NOTE
            result = row | {
                "text": prefix + embedded + suffix,
                "label": label,
                "label_source": "synthetic-augmentation",
                "source": f"augmented:{kind}",
                "channel": channel,
                "techniques": row["techniques"] if label else [],
                "spans": [[0, len(prefix), len(prefix) + len(embedded)]] if label else [],
                "variant_type": row["variant_type"] if label else "plain",
                "publishable": "no",
            }
            if kind == "long_context":
                result["license"] = canonical_json(sorted({row["license"], *padding_licenses}))
            result.pop("id")
            result["id"] = hashlib.sha256(canonical_json([seed, row["id"], result]).encode()).hexdigest()
            yield validate_record(result)


def augment(input_path, output_path, dataset_manifest, seed):
    """Retain originals and add four attack/control pairs per attack.

    Input must be one split from split.py, or an output with a pinned split.
    Splits remain file-level metadata; never re-split the output.
    """
    input_path, output_path, dataset_manifest = map(Path, (input_path, output_path, dataset_manifest))
    manifest_path = output_path.with_suffix(".manifest.json")
    if len({p.resolve() for p in (input_path, output_path, dataset_manifest, manifest_path)}) != 4:
        raise ValueError("input, output, dataset manifest and output manifest must be distinct")
    manifest = load_json(dataset_manifest)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 2:
        raise ValueError("schema version 2 manifest required")
    split = input_path.stem if "splits" in manifest else manifest.get("split")
    if split not in SPLITS:
        raise ValueError("input must have a pinned split; use split.py first")
    metadata = manifest.get("splits", {}).get(split, {}) if "splits" in manifest else manifest
    input_hash = digest(input_path)
    if metadata.get("output_sha256") != input_hash:
        raise ValueError("input checksum does not match split manifest")
    rows, ids = [], set()
    for number, raw in read_rows(input_path):
        try:
            row = validate_record(raw)
            if row["id"] in ids:
                raise ValueError("duplicate id")
        except ValueError as error:
            raise ValueError(f"line {number}: {error}") from None
        ids.add(row["id"])
        rows.append(row)
    if metadata.get("records") != len(rows):
        raise ValueError("input record count does not match manifest")
    benign = [row for row in rows if row["label"] == 0]
    if any(row["label"] for row in rows) and not benign:
        raise ValueError("long-context augmentation requires benign rows in the same split")
    # Repeat the same-split pool in input order, truncating only the benign padding.
    pool = "\n\n".join(row["text"] for row in benign)
    padding = ((pool + "\n\n") * (LONG_CHARS // (len(pool) + 2) + 1))[:LONG_CHARS]
    padding_licenses = {r["license"] for r in benign}
    output_rows = list(rows)
    for row in rows:
        if row["label"]:
            for variant in _variants(row, padding, padding_licenses, seed):
                if variant["id"] in ids:
                    raise ValueError("duplicate augmented id")
                ids.add(variant["id"])
                output_rows.append(variant)
    content = "".join(canonical_json(row) + "\n" for row in output_rows).encode("utf-8")
    attacks = [row for row in output_rows if row["label"]]
    result = {
        "schema_version": 2, "augmenter_version": 1, "seed": seed, "split": split,
        "input_sha256": input_hash, "dataset_manifest_sha256": digest(dataset_manifest),
        "output_sha256": hashlib.sha256(content).hexdigest(), "records": len(output_rows),
        "labels": dict(Counter(str(r["label"]) for r in output_rows)),
        "channels": dict(Counter(r["channel"] for r in output_rows)),
        "attack_channels": dict(Counter(r["channel"] for r in attacks)),
        "techniques": dict(Counter(t for r in output_rows for t in r["techniques"])),
        "attack_families": dict(Counter(r["attack_family"] for r in output_rows)),
        "lengths": dict(Counter("8192+" if len(r["text"]) >= LONG_CHARS else "0-8191" for r in output_rows)),
        "attack_lengths": dict(Counter("8192+" if len(r["text"]) >= LONG_CHARS else "0-8191" for r in attacks)),
        "evaluator_approved": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(output_path, content)
    atomic_write(manifest_path, (canonical_json(result) + "\n").encode("utf-8"))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    try:
        result = augment(args.input, args.output, args.dataset_manifest, args.seed)
    except ValueError as error:
        parser.exit(2, f"augmentation failed: {error}\n")
    except OSError:
        parser.exit(2, "augmentation failed: file operation failed\n")
    print(canonical_json(result))


if __name__ == "__main__":
    main()
