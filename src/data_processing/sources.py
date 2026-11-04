"""Load approved local source snapshots through the schema v2 normalizer.

No downloads, inference, evaluator approval, or payload output. See docs/datasets.md.
"""

import argparse
import csv
import gzip
import hashlib
import json
import os
import tempfile
from pathlib import Path

from data_processing.normalize import (
    adapt_record,
    canonical_json,
    normalize,
    utc_timestamp,
)

SOURCES = {
    "deepset": ("deepset/prompt-injections", "Apache-2.0"),
    "jackhhao": ("jackhhao/jailbreak-classification", "Apache-2.0"),
    "trustair": ("TrustAIRLab/in-the-wild-jailbreak-prompts", "MIT"),
    "gandalf": ("Lakera/gandalf_ignore_instructions", "MIT"),
    "spml": ("reshabhs/SPML_Chatbot_Prompt_Injection", "MIT"),
    "llmail": ("microsoft/llmail-inject-challenge", "MIT"),
    "jbb": ("JailbreakBench/JBB-Behaviors", "MIT"),
    "dolly": ("databricks/databricks-dolly-15k", "CC-BY-SA-3.0"),
    "oasst2": ("OpenAssistant/oasst2", "Apache-2.0"),
}


def read_rows(path):
    """Read local CSV, Parquet, JSONL (optionally gzipped), or LLMail JSON."""
    if path.suffix == ".parquet":
        # Already a dependency of datasets; no online dataset loader is used.
        import pyarrow.parquet as pq

        for batch in pq.ParquetFile(path).iter_batches():
            yield from batch.to_pylist()
    else:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8", newline="") as reader:
            if path.suffix == ".csv":
                yield from csv.DictReader(reader)
            elif path.suffix == ".json":
                data = json.load(reader)
                if not isinstance(data, dict):
                    raise ValueError("LLMail JSON must be a prompt-to-annotation object")
                for text, annotation in data.items():
                    yield {"text": text, "annotation": annotation}
            else:
                for line in reader:
                    yield json.loads(line)


def oasst_paths(node, messages=()):
    """Emit root-to-leaf conversations; omit branches marked deleted or rejected."""
    if node["deleted"] or node["review_result"] is not True:
        return
    role = {"prompter": "user", "assistant": "assistant"}[node["role"]]
    messages = (*messages, {"role": role, "content": node["text"]})
    if not node["replies"]:
        yield node["message_id"], canonical_json(messages)
    for reply in node["replies"]:
        yield from oasst_paths(reply, messages)


def convert(source, row):
    """Yield text, integer label, optional family and group, and stated technique."""
    family = group = None
    technique = "novel"
    if source == "deepset":
        text, label = row["text"], row["label"]
    elif source == "jackhhao":
        text, label = row["prompt"], {"benign": 0, "jailbreak": 1}[row["type"]]
    elif source == "trustair":
        if type(row["jailbreak"]) is not bool:
            raise ValueError("jailbreak must be boolean")
        text, label = row["prompt"], int(row["jailbreak"])
        # Community is the source's family annotation, not a technique inferred from text.
        family = row.get("community") or row.get("community_name")
        if family and label:
            technique = "named_jailbreak"
            group = str(row["community_id"])
    elif source == "spml":
        text, label = row["User Prompt"], {"0": 0, "1": 1}[row["Prompt injection"]]
        if not text.strip():
            return
    elif source == "llmail":
        # A failed objective is still an attack. Only explicit attack-attempt labels qualify.
        attempt = row["annotation"]["attack_attempt"]
        if attempt is not True and attempt != "True":
            return
        text, label = row["text"], 1
    elif source == "dolly":
        text = row["instruction"]
        if row["context"]:
            text += "\n\n" + row["context"]
        label = 0
    elif source == "oasst2":
        for leaf, text in oasst_paths(row["prompt"]):
            yield text, 0, "benign-chat", row["message_tree_id"], "novel", leaf
        return
    else:
        raise ValueError("JBB behaviors are red-team seeds only, never scored rows")
    yield text, label, family, group, technique, None


def source_records(source, row, defaults, mapping):
    """Apply flat mappings or source-specific structure conversion."""
    if mapping is not None:
        yield adapt_record(row, mapping["fields"], defaults | mapping["defaults"])
        return
    name = SOURCES[source][0]
    for text, label, family, group, technique, leaf in convert(source, row):
        identity = hashlib.sha256(text.encode("utf-8")).hexdigest()
        record = defaults | {
            "text": text, "label": label,
            "attack_family": family or (name if label else "benign-" + source),
            "group_id": name + ":" + (group or identity),
            "techniques": [technique] if label else [],
            "spans": None if label else [],
        }
        if source == "llmail":
            record["label_source"] = name + ":attack_attempt=True"
        if leaf:
            record["id"] = name + ":" + leaf
        record = adapt_record({}, {}, record)
        yield record


def load_source(source, inputs, output, manifest, *, revision, timestamp):
    """Normalize a pinned snapshot, keeping only aggregates in the manifest.

    Identical mapped records are collapsed (counts reported); near-duplicate removal
    and label review remain evaluator work. LLMail is capped at 50,000 accepted rows.
    """
    inputs = [Path(path) for path in inputs]
    output, manifest = Path(output), Path(manifest)
    paths = [*inputs, output, manifest]
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("inputs, output, and manifest must be distinct paths")
    if not revision or not revision.isalnum():
        raise ValueError("revision must be an explicit snapshot identifier")
    timestamp = utc_timestamp(timestamp)
    name, license = SOURCES[source]
    citation = f"https://huggingface.co/datasets/{name}/tree/{revision}"
    defaults = {
        "source": citation, "license": license, "publishable": "yes",
        "timestamp": timestamp, "label_source": name + ":source-label",
        "variant_type": "plain",
        "channel": {"llmail": "email", "oasst2": "multi_turn"}.get(source, "direct"),
    }
    mapping = None
    if source == "gandalf":
        mapping = json.loads(
            Path(__file__).with_name("source_mappings").joinpath("gandalf.json").read_text()
        )
    manifest.parent.mkdir(parents=True, exist_ok=True)
    seen = {}
    counts = {"input_rows": 0, "duplicates": 0, "excluded": 0}
    hashes = []
    with tempfile.TemporaryDirectory(dir=manifest.parent) as directory:
        intermediate = Path(directory) / "adapted.jsonl"
        temporary_manifest = Path(directory) / "manifest.json"
        with intermediate.open("w", encoding="utf-8") as writer:
            for path in inputs:
                digest = hashlib.sha256()
                with path.open("rb") as reader:
                    while chunk := reader.read(1024 * 1024):
                        digest.update(chunk)
                hashes.append(digest.hexdigest())
                try:
                    for row in read_rows(path):
                        counts["input_rows"] += 1
                        if source == "jbb":
                            # Catalog seed inputs without assigning detection labels or exporting text.
                            continue
                        converted = False
                        for record in source_records(source, row, defaults, mapping):
                            converted = True
                            encoded = canonical_json(record) + "\n"
                            signature = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
                            if record["id"] in seen:
                                if seen[record["id"]] != signature:
                                    raise ValueError("conflicting source id")
                                counts["duplicates"] += 1
                                continue
                            if source == "llmail" and len(seen) >= 50_000:
                                counts["excluded"] += 1
                                continue
                            seen[record["id"]] = signature
                            writer.write(encoded)
                        if not converted:
                            counts["excluded"] += 1
                except (ValueError, KeyError, TypeError, UnicodeError):
                    # External values and parser exception messages can contain payload text.
                    raise ValueError(
                        f"input {len(hashes)}: invalid source fields or format"
                    ) from None
        result = normalize(intermediate, output, temporary_manifest)
        result["loader"] = {
            "version": 1, "source": citation, "raw_sha256": hashes, **counts,
            "role": "red_team_seeds_only" if source == "jbb" else "detection",
        }
        temporary_manifest.write_text(canonical_json(result) + "\n", encoding="utf-8")
        os.replace(temporary_manifest, manifest)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=SOURCES)
    parser.add_argument("inputs", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--timestamp", required=True, help="snapshot time, ISO 8601 with timezone")
    args = parser.parse_args()
    try:
        result = load_source(args.source, args.inputs, args.output, args.manifest,
                             revision=args.revision, timestamp=args.timestamp)
    except ValueError as error:
        parser.exit(2, f"source loading failed: {error}\n")
    except OSError:
        parser.exit(2, "source loading failed: file operation failed\n")
    print(canonical_json(result))


if __name__ == "__main__":
    main()
