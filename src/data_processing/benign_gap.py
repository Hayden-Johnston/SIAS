"""Count benign source-pool rows from aggregate manifests, without payloads or inference."""

import argparse
import json
from pathlib import Path

from data_processing.normalize import CHANNELS, canonical_json

# docs/pipeline.md, Statistics: approximate zero-FP sample size at 95% confidence.
TARGET = 15_000


def report(paths):
    sources = {}
    for path in paths:
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
        source = manifest["loader"]["source"]
        if source in sources:
            raise ValueError("duplicate source manifest")
        benign, attacks = (manifest["labels"].get(label, 0) for label in ("0", "1"))
        channels = {}
        for channel in sorted(CHANNELS):
            total = manifest["channels"].get(channel, 0)
            # Marginal channel counts include attacks. Preserve ambiguity as null.
            lower, upper = max(0, total - attacks), min(total, benign)
            channels[channel] = lower if lower == upper else None
        sources[source] = {
            "benign": benign, "by_channel": channels,
            "evaluator_approved": manifest.get("evaluator_approved") is True,
        }
    total = sum(source["benign"] for source in sources.values())
    channels = {}
    for channel in sorted(CHANNELS):
        counts = [source["by_channel"][channel] for source in sources.values()]
        channels[channel] = None if None in counts else sum(counts)
    return {
        "target_heldout_benign": TARGET,
        "source_pool_benign": total,
        "source_pool_gap_to_target": max(0, TARGET - total),
        "evaluator_approved_source_pool_benign": sum(
            source["benign"] for source in sources.values() if source["evaluator_approved"]),
        "heldout_benign": None, "heldout_gap_to_target": None,
        "by_channel": channels, "by_source": sources,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifests", nargs="*", type=Path,
                        help="disjoint source manifests (default: checked-in approved sources)")
    parser.add_argument("--output", type=Path, help="also save the counts JSON")
    args = parser.parse_args()
    paths = args.manifests or sorted(
        (Path(__file__).resolve().parents[2] / "reports/dataset-manifests").glob("*.json"))
    if args.output and args.output.resolve() in {path.resolve() for path in paths}:
        parser.error("output must not overwrite an input manifest")
    try:
        result = canonical_json(report(paths)) + "\n"
        if args.output:
            args.output.write_text(result, encoding="utf-8")
    except (ValueError, KeyError, TypeError):
        parser.exit(2, "Benign gap report failed: invalid source manifest\n")
    except OSError:
        parser.exit(2, "Benign gap report failed: file operation failed\n")
    print(result, end="")


if __name__ == "__main__":
    main()
