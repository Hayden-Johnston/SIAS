"""Validate and normalize local JSONL sources without inference or network access."""

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

FIELDS = {
    "id", "text", "label", "label_source", "attack_family", "group_id",
    "variant_type", "source", "license", "publishable", "timestamp",
}
VARIANTS = {"plain", "paraphrase", "obfuscated"}


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def utc_timestamp(value, name="timestamp"):
    """Parse a timezone-aware ISO 8601 timestamp and return canonical UTC."""
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{name} must be ISO 8601 with timezone") from None
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return stamp.astimezone(UTC).isoformat().replace("+00:00", "Z")


def validate_record(record):
    """Return a canonical record; errors name fields, never include payload values.

    Text is preserved exactly. Unicode/encoding transformations belong in scored
    detection stages, where their effect can be measured separately.
    """
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise ValueError("record must contain exactly the schema fields")
    result = dict(record)
    for field in FIELDS - {"label"}:
        if not isinstance(result[field], str) or not result[field].strip():
            raise ValueError(f"{field} must be a nonempty string")
    if type(result["label"]) is not int or result["label"] not in (0, 1):
        raise ValueError("label must be integer 0 (benign) or 1 (attack)")
    if result["variant_type"] not in VARIANTS:
        raise ValueError("variant_type must be plain, paraphrase, or obfuscated")
    if result["publishable"] not in {"yes", "no"}:
        raise ValueError("publishable must be yes or no")
    result["timestamp"] = utc_timestamp(result["timestamp"])
    return result


def validate_mapping(mapping):
    """A source adapter maps canonical field names to flat source keys/defaults."""
    if not isinstance(mapping, dict) or set(mapping) - {"fields", "defaults"}:
        raise ValueError("mapping accepts only fields and defaults")
    fields, defaults = mapping.get("fields", {}), mapping.get("defaults", {})
    if not isinstance(fields, dict) or not isinstance(defaults, dict):
        raise ValueError("fields and defaults must be objects")  # noqa: TRY004 - invalid external JSON value
    if (set(fields) | set(defaults)) - FIELDS:
        raise ValueError("mapping contains unknown schema fields")
    if set(fields) & set(defaults):
        raise ValueError("a field cannot have both a mapping and a default")
    if any(not isinstance(key, str) or not key for key in fields.values()):
        raise ValueError("source field names must be nonempty strings")
    required = FIELDS - {"id"}
    if not required <= set(fields) | set(defaults):
        raise ValueError("mapping must supply all schema fields except optional id")
    return fields, defaults


def adapt_record(row, fields, defaults):
    if not isinstance(row, dict):
        raise ValueError("source row must be an object")  # noqa: TRY004 - invalid external JSON value
    record = dict(defaults)
    for field, source_key in fields.items():
        if source_key not in row:
            raise ValueError(f"source row is missing mapped field {field}")
        record[field] = row[source_key]
    if "id" not in record:
        # Provenance participates in identity; source order and wall clock do not.
        record["id"] = hashlib.sha256(canonical_json(record).encode("utf-8")).hexdigest()
    return validate_record(record)


def normalize(source, output, manifest, mapping=None):
    """Write canonical JSONL and an aggregate manifest, replacing files on success.

    The manifest is the completion marker and contains the output checksum. A
    reader must verify it before using the output. No evaluator approval is implied.
    """
    source, output, manifest = map(Path, (source, output, manifest))
    if len({path.resolve() for path in (source, output, manifest)}) != 3:
        raise ValueError("source, output, and manifest must be distinct paths")
    fields, defaults = validate_mapping(mapping) if mapping is not None else (None, None)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    ids = set()
    labels, families, variants, publication = (Counter() for _ in range(4))
    source_hash, output_hash = hashlib.sha256(), hashlib.sha256()
    output_temp = manifest_temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as writer:
            output_temp = Path(writer.name)
            with source.open("rb") as reader:
                for line_number, line in enumerate(reader, 1):
                    source_hash.update(line)
                    try:
                        row = json.loads(line.decode("utf-8"))
                    except (ValueError, UnicodeError):
                        raise ValueError(f"line {line_number}: invalid JSON or UTF-8") from None
                    try:
                        record = (
                            adapt_record(row, fields, defaults)
                            if fields is not None else validate_record(row)
                        )
                        if record["id"] in ids:
                            raise ValueError("duplicate id; evaluator must resolve duplicates")
                    except ValueError as error:
                        raise ValueError(f"line {line_number}: {error}") from None
                    ids.add(record["id"])
                    labels[str(record["label"])] += 1
                    families[record["attack_family"]] += 1
                    variants[record["variant_type"]] += 1
                    publication[record["publishable"]] += 1
                    encoded = (canonical_json(record) + "\n").encode("utf-8")
                    writer.write(encoded)
                    output_hash.update(encoded)
        result = {
            "schema_version": 1,
            "normalizer_version": 1,
            "source_sha256": source_hash.hexdigest(),
            "mapping_sha256": hashlib.sha256(canonical_json(mapping).encode()).hexdigest(),
            "output_sha256": output_hash.hexdigest(),
            "records": len(ids),
            "labels": dict(labels),
            "attack_families": dict(families),
            "variant_types": dict(variants),
            "publishable": dict(publication),
            "evaluator_approved": False,
        }
        with tempfile.NamedTemporaryFile(dir=manifest.parent, delete=False) as writer:
            manifest_temp = Path(writer.name)
            writer.write((canonical_json(result) + "\n").encode("utf-8"))
        os.replace(output_temp, output)
        os.replace(manifest_temp, manifest)
        return result
    finally:
        for path in (output_temp, manifest_temp):
            if path is not None:
                path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--mapping", type=Path)
    args = parser.parse_args()
    try:
        mapping = None
        if args.mapping:
            if args.mapping.resolve() in {args.output.resolve(), args.manifest.resolve()}:
                raise ValueError("mapping must not be an output path")
            try:
                mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError):
                raise ValueError("invalid mapping JSON or UTF-8") from None
        result = normalize(args.source, args.output, args.manifest, mapping)
    except ValueError as error:
        parser.exit(2, f"normalization failed: {error}\n")
    except OSError:
        parser.exit(2, "normalization failed: file operation failed\n")
    print(canonical_json(result))


if __name__ == "__main__":
    main()
