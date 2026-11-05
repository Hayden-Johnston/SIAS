"""Select fusion weights on dev caches, then report held-out metrics without inference."""

import argparse
from itertools import product
from pathlib import Path

from data_processing import run
from data_processing.normalize import canonical_json


def sweep(dev_config, held_out_config, fpr_cap, output=None):
    fpr_cap = float(run.number(fpr_cap, "FPR cap", 1))
    dev, dev_manifest, rows, stages, dev_identity, inputs, _ = run.prepare(dev_config)
    if dev["evaluation_split"] != "validation":
        raise ValueError("dev config must use evaluation_split validation")
    if len(stages) < 2:
        raise ValueError("sweep requires multiple stages")
    if {row["label"] for row in rows} != {0, 1}:
        raise ValueError("dev requires both attack and benign rows")
    names = sorted(stage["name"] for stage, _ in stages)
    threshold = dev.get("fusion", {}).get("threshold", 0.5)

    def score(rows, stages, weights):
        return run.metrics(run.evaluate(row, stages, {"threshold": threshold, "weights": weights})
                           for row in rows)

    best = None
    for values in product((0, 0.5, 1), repeat=len(names)):
        weights = dict(zip(names, values))
        measured = score(rows, stages, weights)
        if measured["false_positive"]["value"] <= fpr_cap:
            key = (-measured["detection"]["value"], sum(values), values)
            if best is None or key < best[0]:
                best = key, weights, measured
    if best is None:
        raise ValueError("no weights satisfy the dev FPR cap")
    _, chosen, dev_metrics = best

    # Held-out inputs are opened only after the dev choice is final.
    held, held_manifest, rows, held_stages, held_identity, held_inputs, _ = run.prepare(
        held_out_config)
    if held["evaluation_split"] != "held_out":
        raise ValueError("held-out config must use evaluation_split held_out")

    def stage_settings(stages):
        return sorted(
            [{key: value for key, value in stage.items() if key not in {"cache", "cache_sha256"}}
             for stage, _ in stages], key=lambda stage: stage["name"])

    if (stage_settings(stages) != stage_settings(held_stages)
            or held.get("fusion", {}).get("threshold", 0.5) != threshold):
        raise ValueError("dev and held-out stage settings and fusion threshold must match")
    held_metrics = score(rows, held_stages, chosen)
    baseline = score(rows, held_stages, dict.fromkeys(names, 1))
    result = {
        "schema_version": 1, "fpr_cap": fpr_cap, "threshold": threshold,
        "grid": [0, 0.5, 1], "candidates": 3 ** len(names),
        "dev": {"identity_sha256": dev_identity, "weights": chosen, "metrics": dev_metrics,
                "evaluator_approved": dev_manifest.get("evaluator_approved") is True},
        "held_out": {"identity_sha256": held_identity, "metrics": held_metrics,
                     "evaluator_approved": held_manifest.get("evaluator_approved") is True,
                     "all_ones_metrics": baseline,
                     "delta_vs_all_ones": {
                         metric: (held_metrics[metric]["value"] - baseline[metric]["value"]
                                  if held_metrics[metric]["value"] is not None else None)
                         for metric in ("detection", "false_positive")}},
    }
    if output is not None:
        output = Path(output)
        if output.resolve() in inputs | held_inputs:
            raise ValueError("sweep output must not overwrite input files")
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
        result = sweep(args.dev_config, args.held_out_config, args.fpr_cap, args.output)
    except ValueError as error:
        parser.exit(2, f"sweep failed: {error}\n")
    except OSError:
        parser.exit(2, "sweep failed: file operation failed\n")
    print(canonical_json(result))


if __name__ == "__main__":
    main()
