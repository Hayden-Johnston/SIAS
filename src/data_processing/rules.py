"""Score a normalized dataset with local rules and write a replay score cache."""

import argparse
import json
import re
import unicodedata
from pathlib import Path
from time import perf_counter_ns

from data_processing.normalize import canonical_json, validate_record
from data_processing.run import atomic_write, digest, load_json, read_rows, windows

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


# Ordinal feature weights, not probabilities; max aggregation prevents weak
# features or repeated directives from accumulating into a strong detection.
FEATURE_WEIGHTS = {"role_override": 0.9, "assistant_refusal_suppression": 0.75,
                   "instruction_density": 0.25}
OVERRIDE_VERBS = {"ignore", "disregard", "forget", "override", "bypass", "discard",
                  "replace", "suspend"}
ROLE_WORDS = {"system", "developer", "assistant"}
DIRECTIVE_VERBS = OVERRIDE_VERBS | {"reveal", "output", "respond", "print", "follow"}


def feature_scores(text):
    """Named token features on normalized text, bounded to a sentence/line."""
    found = set()
    clauses = [re.findall(r"\b\w+\b", part) for part in re.split(r"[.!?;\n]+", text)]
    clauses = [tokens for tokens in clauses if tokens]
    directives = 0
    for tokens in clauses:
        # Only clause-initial imperatives, optionally preceded by please/now.
        start = 1 if tokens[0] in {"please", "now"} else 0
        if start == len(tokens):
            continue
        verb = tokens[start]
        directives += verb in DIRECTIVE_VERBS
        # Six following tokens permit modifiers, without spanning sentences.
        if ((verb in OVERRIDE_VERBS or tokens[start:start + 2] == ["set", "aside"])
                and ROLE_WORDS.intersection(tokens[start + 1:start + 7])):
            found.add("role_override")
        for index, token in enumerate(tokens):
            # An explicit assistant reference within eight preceding tokens,
            # followed by a second-person obligation to suppress refusal.
            if (token == "you" and "assistant" in tokens[max(0, index - 8):index]
                    and tokens[index + 1:index + 2] in (["must"], ["shall"])
                    and tokens[index + 2:index + 3] in (["not"], ["never"])
                    and "refuse" in tokens[index + 3:index + 6]):
                found.add("assistant_refusal_suppression")
    # Three directive clauses and at least half the clauses prevent one request from
    # registering as dense. Still weak: benign task lists often meet this test.
    if directives >= 3 and directives / len(clauses) >= 0.5:
        found.add("instruction_density")
    return {name: FEATURE_WEIGHTS[name] for name in sorted(found)}


def score(text):
    """Return a deterministic [0, 1] score; preserve the stored dataset text."""
    text = unicodedata.normalize("NFKC", text).casefold().translate(HOMOGLYPHS)
    text = "".join(char for char in text if unicodedata.category(char) != "Cf")
    return max([weight for weight, pattern in RULES if pattern.search(text)]
               + list(feature_scores(text).values()), default=0.0)


def write_cache(dataset, dataset_manifest, output, *, chunk_chars=None, overlap_chars=None):
    """Validate before replacing a cache; report aggregates without payload text.

    Inputs must remain unchanged during production. Memory scales with row count.
    Reproduction preserves scores; measured latencies and cache hashes can change.
    """
    dataset, dataset_manifest, output = map(Path, (dataset, dataset_manifest, output))
    chunked = chunk_chars is not None or overlap_chars is not None
    if chunked and (type(chunk_chars) is not int or type(overlap_chars) is not int
                    or not 0 <= overlap_chars < chunk_chars):
        raise ValueError("require integer chunk_chars > overlap_chars >= 0")
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
        # Score content independently; JSON role metadata is not a spoofing marker.
        start = perf_counter_ns()
        texts = ([message["content"] for message in json.loads(row["text"])]
                 if row["channel"] == "multi_turn" else [row["text"]])
        if chunked:
            for turn, text in enumerate(texts):
                for offset, end in windows(len(text), chunk_chars, overlap_chars):
                    start = perf_counter_ns()
                    value = score(text[offset:end])
                    latency = (perf_counter_ns() - start) / 1_000_000
                    entries.append({"id": row["id"], "turn": turn, "start": offset,
                                    "score": value, "latency_ms": latency})
        else:
            value = max(map(score, texts), default=0.0)
            latency = (perf_counter_ns() - start) / 1_000_000
            entries.append({"id": row["id"], "score": value, "latency_ms": latency})
    if manifest.get("records") != len(ids):
        raise ValueError("dataset manifest record count mismatch")
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(output, "".join(canonical_json(row) + "\n" for row in entries).encode("utf-8"))
    total = sum(row["latency_ms"] for row in entries)
    return {
        "version": "rules-sha256-" + digest(__file__),
        "dataset_sha256": dataset_hash, "cache_sha256": digest(output),
        "records": len(ids), "entries": len(entries),
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
    parser.add_argument("--chunk-chars", type=int)
    parser.add_argument("--overlap-chars", type=int)
    args = parser.parse_args()
    try:
        result = write_cache(args.dataset, args.dataset_manifest, args.output,
                             chunk_chars=args.chunk_chars, overlap_chars=args.overlap_chars)
    except ValueError as error:
        parser.exit(2, f"rule scoring failed: {error}\n")
    except OSError:
        parser.exit(2, "rule scoring failed: file operation failed\n")
    print(canonical_json(result))


if __name__ == "__main__":
    main()
