"""Score a normalized dataset with local rules and write a replay score cache."""

import argparse
import base64
import codecs
import json
import re
import unicodedata
from pathlib import Path
from time import perf_counter_ns

from data_processing.normalize import canonical_json, validate_record
from data_processing.run import atomic_write, digest, load_json, read_rows, windows

# Limited visual substitutions, not a complete confusables implementation.
HOMOGLYPHS = str.maketrans(dict(zip("аеорсухіјкмтαοερικ", "aeopcyxijkmtaoepik", strict=True)))

# At least four hex bytes or two base64 quartets; ROT13 needs an explicit
# marker because ordinary words are also valid ROT13. Match once, not recursively.
ENCODED = re.compile(
    r"\b(?i:rot13):[ \t]*(?P<rot13>[^\n]+)"
    r"|(?<!\w)(?:0[xX])?(?P<hex>(?:[0-9a-fA-F]{2}){4,})(?!\w)"
    r"|(?<![\w+/])(?P<base64>[A-Za-z0-9+/]{8,}={0,2})(?![\w+/=])"
)


def _normalize_unicode(text):
    text = unicodedata.normalize("NFKC", text)
    return "".join(char for char in text if unicodedata.category(char) != "Cf")


def canonicalize(text):
    """Fold Unicode and decode printable UTF-8 spans once; never execute text.

    Hex is contiguous, optionally prefixed by 0x; base64 is standard, padded
    or unpadded. A rot13: marker covers the remainder of its line. This view
    is only for scoring: offsets must always come from the original text.
    """
    def decode(match):
        try:
            if match.lastgroup == "rot13":
                decoded = codecs.decode(match["rot13"], "rot_13")
            elif match.lastgroup == "hex":
                decoded = bytes.fromhex(match["hex"]).decode("utf-8")
            else:
                value = match["base64"]
                decoded = base64.b64decode(value + "=" * (-len(value) % 4),
                                           validate=True).decode("utf-8")
        except ValueError:
            return match[0]
        return (decoded if decoded and all(c.isprintable() or c in "\n\r\t" for c in decoded)
                else match[0])

    text = ENCODED.sub(decode, _normalize_unicode(text))
    return _normalize_unicode(text).casefold().translate(HOMOGLYPHS)

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
    # Dev misses: a persona switch must name an unconstrained role; ordinary
    # role requests (teacher, editor, etc.) are not enough. Reuse the delimiter
    # rule's strength: these are explicit instruction cues, not probabilities.
    (0.75, re.compile(
        r"\b(?:act as|pretend (?:to be|you are)|you are now)\b"
        r"(?:\W+\w+){0,8}\W+"
        r"(?:unrestricted|unfiltered|uncensored|amoral|immoral|dan|jailbroken)\b"
        # Round-2 identity phrasing requires an adjacent model/persona noun
        # (or DAN), so learning about unrestricted grammars is not a switch.
        r"|\b(?:you are|pretend|roleplay|simulate|behave as)\s+"
        r"(?:to be\s+)?(?:an?\s+)?"
        r"(?:(?:unrestricted|unfiltered|uncensored|amoral|immoral|jailbroken)\s+"
        r"(?:assistant|ai|model|chatbot|persona)|dan)\b"
    )),
    # Bound safety-suspension cues to a constraint noun, and refusal suppression
    # to a request noun, so isolated safety vocabulary does not trigger a catch.
    (0.75, re.compile(
        r"\b(?:no|without|not bound by|free from)(?:\s+(?:any|all|the|such))?\s+"
        r"(?:ethical|moral|safety|content)\s+"
        r"(?:constraints?|restrictions?|guidelines?|filters?|rules?|limits?)\b"
        r"|\b(?:never|do not|don't)\s+(?:refuse|decline|reject)\b"
        r"(?:\W+\w+){0,4}\W+(?:requests?|questions?|commands?|instructions?|answers?)\b"
    )),
    # Round-2 dev residuals: require a second-person subject near absent
    # constraints, or universal compliance near a request noun. The short
    # token windows keep unrelated vocabulary from combining across a document.
    (0.75, re.compile(
        r"\b(?:you|your (?:answers?|responses?))\b(?:\W+\w+){0,4}\W+"
        r"(?:no|without|not subject to|not limited by|not restricted by)\b"
        r"(?:\W+\w+){0,3}\W+"
        r"(?:restrictions?|limitations?|constraints?|filters?|censorship)\b"
    )),
    (0.75, re.compile(
        r"\b(?:always|must|will)\s+(?:answer|respond to|comply with|fulfill|obey)\b"
        r"(?:\W+\w+){0,4}\W+(?:all|any|every)\s+"
        r"(?:requests?|questions?|commands?|instructions?)\b"
    )),
    # Round-3 indirect-channel dev misses: suppression of capability refusals.
    # Keep the refusal cue within four words of an explicit prohibition;
    # ordinary requests to omit apologies are not enough.
    (0.75, re.compile(
        r"\b(?:never|do not|don't|must not)\s+(?:say|tell|mention)\b"
        r"(?:\W+\w+){0,4}\W+(?:cannot|can't|unable)\b"
    )),
    # Round-4 dev misses: second-person exemption from policy obligations.
    # Bound both gaps to four words; policy discussion alone is insufficient.
    (0.75, re.compile(
        r"\byou\b(?:\W+\w+){0,4}\W+(?:not|no longer)\s+"
        r"(?:bound by|subject to|required to follow)\b"
        r"(?:\W+\w+){0,4}\W+(?:polic(?:y|ies)|guidelines?|rules?)\b"
    )),
    # Encoding is suspicious but also common in benign technical material.
    # Require 32 base64 characters (eight blocks), eight escapes/percent bytes,
    # or sixteen hex bytes. This weak signal also applies to undecodable data.
    (0.25, re.compile(
        r"\bbase64\b|(?<![a-z0-9+/])[a-z0-9+/]{32,}={0,2}(?![a-z0-9+/=])"
        r"|(?:%[0-9a-f]{2}){8,}|(?:\\x[0-9a-f]{2}){8,}"
        r"|(?:\\u[0-9a-f]{4}){8,}|\b0x[0-9a-f]{32,}\b"
    )),
)


def score(text):
    """Return a deterministic [0, 1] score; preserve the stored dataset text."""
    return max((weight for candidate in (text.casefold(), canonicalize(text))
                for weight, pattern in RULES if pattern.search(candidate)), default=0.0)


def write_cache(dataset, dataset_manifest, output, *, chunk_chars=None, overlap_chars=None):
    """Validate before replacing a cache; report aggregates without payload text.

    Inputs must remain unchanged during production. Memory scales with cache entries and row count.
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
