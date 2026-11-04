"""Score a normalized dataset with local rules and write a replay score cache."""

import argparse
import json
import re
import unicodedata
from pathlib import Path
from time import perf_counter_ns

from data_processing.normalize import canonical_json, validate_record
from data_processing.run import atomic_write, digest, load_json, read_rows

# Limited visual substitutions, not a complete confusables implementation.
HOMOGLYPHS = str.maketrans(dict(zip("аеорсухіјкмтαοερικ", "aeopcyxijkmtaoepik", strict=True)))

# Scores are ordinal heuristic strengths, not calibrated probabilities. The maximum
# matching rule wins: repetition cannot inflate a weak encoding signal into a catch.
# Override: imperative verb followed by an instruction target within four tokens.
# This is a small token/proximity feature, with no parser or model dependency.
RULES = (
    (1.0, re.compile(
        r"\b(?:ignore|disregard|forget|override|bypass)\b"
        r"(?:\W+\w+){0,4}\W+(?:instructions?|rules?|polic(?:y|ies)|guidelines?|prompts?)\b"
    )),
    (0.75, re.compile(
        r"<\|(?:im_start|im_end|system|assistant|user|eot_id|start_header_id|end_header_id)\|>"
        r"|\[/?inst\]|<<?/?sys>>?|</?(?:system|assistant|developer)>"
        r"|(?:^|\n)\s*(?:system|developer|assistant)\s*:"
    )),
    # Encoding is suspicious but also common in benign technical material.
    # Require 32 base64 characters (eight blocks), eight escapes/percent bytes,
    # or sixteen hex bytes. Detect only; never execute or recursively decode.
    (0.25, re.compile(
        r"\bbase64\b|(?<![a-z0-9+/])[a-z0-9+/]{32,}={0,2}(?![a-z0-9+/=])"
        r"|(?:%[0-9a-f]{2}){8,}|(?:\\x[0-9a-f]{2}){8,}"
        r"|(?:\\u[0-9a-f]{4}){8,}|\b0x[0-9a-f]{32,}\b"
    )),
)


def score(text):
    """Return a deterministic [0, 1] score; preserve the stored dataset text."""
    text = unicodedata.normalize("NFKC", text).casefold().translate(HOMOGLYPHS)
    text = "".join(char for char in text if unicodedata.category(char) != "Cf")
    return max((weight for weight, pattern in RULES if pattern.search(text)), default=0.0)


def write_cache(dataset, dataset_manifest, output):
    """Validate before replacing a cache; report aggregates without payload text.

    Inputs must remain unchanged during production. Memory scales with row count.
    Reproduction preserves scores; measured latencies and cache hashes can change.
    """
    dataset, dataset_manifest, output = map(Path, (dataset, dataset_manifest, output))
    if len({path.resolve() for path in (dataset, dataset_manifest, output)}) != 3:
        raise ValueError("dataset, manifest, and output must be distinct paths")
    manifest = load_json(dataset_manifest)
    dataset_hash = digest(dataset)
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != 2
            or manifest.get("output_sha256") != dataset_hash):
        raise ValueError("dataset manifest version/checksum mismatch; schema version 2 required")
    ids, entries = set(), []
    for line, row in read_rows(dataset):
        try:
            row = validate_record(row)
        except ValueError as error:
            raise ValueError(f"dataset line {line}: {error}") from None
        if row["id"] in ids:
            raise ValueError("duplicate dataset id")
        ids.add(row["id"])
        start = perf_counter_ns()
        # Score content independently; JSON role metadata is not a spoofing marker.
        texts = ([message["content"] for message in json.loads(row["text"])]
                 if row["channel"] == "multi_turn" else [row["text"]])
        value = max(map(score, texts), default=0.0)
        latency = (perf_counter_ns() - start) / 1_000_000
        entries.append({"id": row["id"], "score": value, "latency_ms": latency})
    if manifest.get("records") != len(entries):
        raise ValueError("dataset manifest record count mismatch")
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(output, "".join(canonical_json(row) + "\n" for row in entries).encode("utf-8"))
    total = sum(row["latency_ms"] for row in entries)
    return {
        "version": "rules-sha256-" + digest(__file__),
        "dataset_sha256": dataset_hash, "cache_sha256": digest(output),
        "records": len(entries),
        "score_summary": {
            "min": min((row["score"] for row in entries), default=None),
            "max": max((row["score"] for row in entries), default=None),
            "mean": sum(row["score"] for row in entries) / len(entries) if entries else None,
        },
        "latency_ms_total": total,
        "latency_ms_mean": total / len(entries) if entries else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = write_cache(args.dataset, args.dataset_manifest, args.output)
    except ValueError as error:
        parser.exit(2, f"rule scoring failed: {error}\n")
    except OSError:
        parser.exit(2, "rule scoring failed: file operation failed\n")
    print(canonical_json(result))


if __name__ == "__main__":
    main()
