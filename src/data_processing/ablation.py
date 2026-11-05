"""Refit fusion after removing each stage; report held-out deltas without inference."""

import argparse
from pathlib import Path

from data_processing import run
from data_processing.normalize import canonical_json
from data_processing.sweep import score, select_weights, stage_settings


def ablation(dev_config, held_out_config, fpr_cap, output=None):
    fpr_cap = float(run.number(fpr_cap, "FPR cap", 1))
    dev, dev_manifest, rows, stages, dev_identity, inputs, _ = run.prepare(dev_config)
    if dev["evaluation_split"] != "validation":
        raise ValueError("dev config must use evaluation_split validation")
    if len(stages) < 2:
        raise ValueError("ablation requires multiple stages")
    if {row["label"] for row in rows} != {0, 1}:
        raise ValueError("dev requires both attack and benign rows")
    names = sorted(stage["name"] for stage, _ in stages)
    threshold = dev.get("fusion", {}).get("threshold", 0.5)
    choices = {}
    for removed in [None, *names]:
        remaining = [(stage, cache) for stage, cache in stages if stage["name"] != removed]
        weights, measured = select_weights(rows, remaining, threshold, fpr_cap)
        choices[removed] = {"weights": weights, "dev_metrics": measured}

    # Freeze every dev fit before opening any held-out inputs.
    held, held_manifest, rows, held_stages, held_identity, held_inputs, _ = run.prepare(
        held_out_config)
    if held["evaluation_split"] != "held_out":
        raise ValueError("held-out config must use evaluation_split held_out")
    if (stage_settings(stages) != stage_settings(held_stages)
            or held.get("fusion", {}).get("threshold", 0.5) != threshold):
        raise ValueError("dev and held-out stage settings and fusion threshold must match")
    for removed, choice in choices.items():
        remaining = [(stage, cache) for stage, cache in held_stages if stage["name"] != removed]
        choice["held_out_metrics"] = score(rows, remaining, threshold, choice["weights"])
    baseline = choices.pop(None)
    for choice in choices.values():
        choice["delta_vs_full"] = {
            metric: (choice["held_out_metrics"][metric]["value"]
                     - baseline["held_out_metrics"][metric]["value"]
                     if choice["held_out_metrics"][metric]["value"] is not None else None)
            for metric in ("detection", "false_positive")}
    result = {
        "schema_version": 1, "fpr_cap": fpr_cap, "threshold": threshold, "grid": [0, 0.5, 1],
        "dev": {"identity_sha256": dev_identity,
                "evaluator_approved": dev_manifest.get("evaluator_approved") is True},
        "held_out": {"identity_sha256": held_identity,
                     "evaluator_approved": held_manifest.get("evaluator_approved") is True},
        "full": baseline, "removed_stages": choices,
    }
    if output is not None:
        output = Path(output)
        if output.resolve() in inputs | held_inputs:
            raise ValueError("ablation output must not overwrite input files")
        output.parent.mkdir(parents=True, exist_ok=True)
        run.atomic_write(output, (canonical_json(result) + "\n").encode("utf-8"))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dev_config", type=Path)
    parser.add_argument("held_out_config", type=Path)
    parser.add_argument("--fpr-cap", type=float, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = ablation(args.dev_config, args.held_out_config, args.fpr_cap, args.output)
    except ValueError as error:
        parser.exit(2, f"ablation failed: {error}\n")
    except OSError:
        parser.exit(2, "ablation failed: file operation failed\n")
    print(canonical_json(result))


if __name__ == "__main__":
    main()
