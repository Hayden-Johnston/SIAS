#!/usr/bin/env python3
"""Report taxonomy coverage from explicitly selected aggregate dataset manifests."""

import argparse
import json
from pathlib import Path

CHANNELS = (
    ("Single-shot", "direct"),
    ("Multi-turn", "multi_turn"),
    ("Document", "document"),
    ("Email", "email"),
    ("Tool output", "tool_output"),
    ("Code comment", "code_comment"),
)
TECHNIQUES = (
    ("Override", "override"),
    ("Roleplay", "roleplay"),
    ("Encoding", "encoding"),
    ("Delimiter spoof", "delimiter_spoof"),
    ("Payload split", "payload_split"),
    ("Many-shot", "many_shot"),
    ("Known jailbreak", "named_jailbreak"),
    ("Novel / unspecified", "novel"),
)


def cell(count):
    if count is None:
        return "? UNKNOWN"
    if count == 0:
        return "0 GAP"
    if count < 20:
        return f"{count} LOW"
    return str(count)


def channel_attacks(manifest, channel):
    """Channel totals include benign rows; only report an exact attack count."""
    count = manifest["channels"].get(channel, 0)
    attacks = manifest["labels"].get("1", 0)
    benign = manifest["labels"].get("0", 0)
    lower, upper = max(0, count - benign), min(count, attacks)
    return lower if lower == upper else None


def report(paths):
    datasets = [(path.stem, json.loads(path.read_text(encoding="utf-8"))) for path in paths]
    lines = [
        "# Dataset taxonomy coverage",
        "",
        "Counts are attack rows, from aggregate manifests only; no payloads or inference.",
        "GAP = zero; LOW = fewer than 20 rows; UNKNOWN = not derivable from the manifest.",
        "Source approval does not imply evaluator approval or permission to publish.",
        "Channel totals include benign rows: ambiguous attack counts are UNKNOWN.",
        "Long context is a length property; these manifests contain no length counts.",
        "Novel / unspecified is the loader's fallback, not proof of a novel jailbreak.",
        "Technique columns overlap; do not sum them.",
        "",
        "| Dataset | Attack rows | Evaluator approved |",
        "|---|---:|---|",
    ]
    for name, manifest in datasets:
        approved = "yes" if manifest.get("evaluator_approved") is True else "no"
        lines.append(f"| {name} | {manifest['labels'].get('1', 0)} | {approved} |")
    for heading, columns in (("Channels and length", (*CHANNELS, ("Long context", None))),
                             ("Techniques", TECHNIQUES)):
        lines.extend(["", f"## {heading}", "",
                      "| Dataset | " + " | ".join(title for title, _ in columns) + " |",
                      "|---|" + "---:|" * len(columns)])
        for name, manifest in datasets:
            counts = []
            for _, key in columns:
                if heading == "Techniques":
                    count = manifest["techniques"].get(key, 0)
                elif key is None:
                    count = None if manifest["labels"].get("1", 0) else 0
                else:
                    count = channel_attacks(manifest, key)
                counts.append(cell(count))
            lines.append(f"| {name} | " + " | ".join(counts) + " |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifests", nargs="*", type=Path,
                        help="aggregate manifests (default: checked-in approved source manifests)")
    parser.add_argument("--output", type=Path, help="also write the Markdown report to this path")
    args = parser.parse_args()
    paths = args.manifests or sorted(
        (Path(__file__).resolve().parents[1] / "reports/dataset-manifests").glob("*.json"))
    result = report(paths)
    if args.output:
        args.output.write_text(result, encoding="utf-8")
    print(result, end="")


if __name__ == "__main__":
    main()
