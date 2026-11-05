# Fixed-fusion threshold calibration

Added `data_processing.calibrate`, a replay-only CLI following the sweep's deterministic
JSON/atomic-output conventions. It takes completed validation and held-out run manifests
and verified sibling results, avoiding normalized datasets and payload text. Unlike the
weight sweep, it preserves weights and calibrates only the fused-score threshold.
No dependencies, inference or server operations were added.

For each observed dev FPR cap, the first disallowed benign score determines the
threshold: the next representable float above it, respecting inclusive detection and
tied scores. This is the lowest feasible threshold and therefore maximizes dev recall.
Both choices finish before held-out results are opened. JSON contains aggregate counts,
Wilson intervals, channel metrics, thresholds, weights, checksums and approval flags;
no row IDs, paths or payloads. README and pipeline docs describe usage and limits.

## Measured operating points

Replayed iteration 7's validation-fused and held_out-fused completed runs. The committed
[aggregate JSON](2026-11-05-fusion-calibration.json) pins the input checksums. Fixed
weights were `maya: 0.5, rules: 0`. Both splits have 25 scored rows. These are capped
samples, with inherited source/synthetic labels (`evaluator_approved: false`).

| Dev FPR cap | Threshold | Dev recall | Dev FP/benign | Held-out recall | Held-out FP/benign |
|---|---|---|---|---|---|
| 1% | 5e-324 | 7/10 (70%) | 0/15 | 12/17 (70.59%) | 0/8 |
| 0.1% | 5e-324 | 7/10 (70%) | 0/15 | 12/17 (70.59%) | 0/8 |

The threshold is the next float above zero: benign dev scores were all zero, so both
caps require zero observed false positives. This has the same decisions on these binary
weighted scores as the previous 0.5 threshold: detection and FPR changes are zero.
Dev benign granularity is 1/15 = 6.67%, too coarse for either cap, especially 0.1%.
This is an empirical operating point, not evidence of a population FPR below either cap.
Held-out recall's 95% Wilson interval is 46.87–86.72%; held-out FPR's is 0–32.44%.
Dev recall's interval is 39.68–89.22%; dev FPR's is 0–20.39%.

Held-out channel recall (same for both thresholds):

| Channel | Detected/attacks | Recall | 95% Wilson interval |
|---|---|---|---|
| direct | 4/6 | 66.67% | 30.00–90.32% |
| document | 2/3 | 66.67% | 20.77–93.85% |
| email | 6/7 | 85.71% | 48.69–97.43% |
| tool_output | 0/1 | 0% | 0–79.35% |

Unrepresented channels remain unmeasured. No new latency benchmark was performed;
calibration performs no inference. Storage adds only the aggregate JSON artifact.
Runtime sorts dev benign scores once and scans dev/held-out rows for two thresholds.

Tests cover nonzero FP allowances, tied scores, inclusive boundaries, insufficient
samples, held-out independence/read ordering, deterministic CLI output, empty classes,
invalid manifests/results, mismatched weights and input overwrite protection.

Validation: `uv run pytest -q` passed (703 passed, 1 skipped, 9 xfailed,
64 subtests); `uv run ruff check` passed. Staged diff review and secret/private-address
pattern scan passed.
