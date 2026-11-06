# CPU classifier effect: scheduled iteration 8

Replay-only ablation confirms **zero observed held-out detection and FPR delta**
with versus without `cpu-classifier`. Both fits select Maya weight 0.5 and rules
weight 0; the full fit assigns the CPU classifier weight 0. The classifier adds
132,401.123 ms of cached stage work across the 25 held-out records despite its
zero fusion weight. This is a small exploratory sample, not evidence of general
classifier effectiveness or ineffectiveness.

The source is [iteration 8](2026-11-05-iteration-000008.md), timestamp
`2026-11-05T22:00:01.893274+00:00`, pipeline `end-to-end-v0`. It is the first
completed scheduled iteration with CPU classifier caches. No production code,
configuration, dataset, threshold or model was changed for this report.

## Method and reproducibility

The ticket calls the tool `ops/ablation.py`; its implemented entry point is
`data_processing.ablation`. Run against iteration 8's existing checkpoint configs
(set `ITERATION_DIR` to that checkpoint and `RUNS_DIR` to the runs directory):

```sh
uv run python -m data_processing.ablation \
  "$ITERATION_DIR/validation-fused-run.json" \
  "$ITERATION_DIR/held_out-fused-run.json" \
  --fpr-cap 0.0002 --output "$RUNS_DIR/classifier-effect-0089/stage-ablation.json"
```

The tool validates pinned dataset/cache checksums and refits full fusion and each
stage removal on dev only, using weights `{0, 0.5, 1}`, max fusion, threshold 0.5,
and observed dev FPR cap 0.0002. All fits finish before held-out evaluation.
The comparison below uses `full` and `removed_stages.cpu-classifier` on identical
samples: dev 25 records (10 attacks, 15 benign), held-out 25 (17 attacks, 8 benign).
Replay output contains aggregates only; no payloads were inspected or printed.
No inference or server lifecycle operations were performed.

Pinned replay identities:

- Dev: `42539448ae086be896570ad96497237cf3eb8eb2e9421fd3ec7630c2e1422623`
- Held-out: `ecff42995a464084b42d52e1d564bec603b175302add6f33e4d87c6e4028cefb`
- Ablation JSON SHA-256: `92f61564b0ad378e2d6dbafa313ccd3e7ea97ced3bde57a4f336752c35882c0a`

## Counts and rates

Intervals below are 95% Wilson intervals for each rate.

| Split / fit | TP | FN | FP | TN | Detection (95% CI) | FPR (95% CI) |
|---|---:|---:|---:|---:|---|---|
| Dev, with CPU | 7 | 3 | 0 | 15 | 7/10 = 70.00% (39.68–89.22%) | 0/15 = 0% (0–20.39%) |
| Dev, without CPU | 7 | 3 | 0 | 15 | 7/10 = 70.00% (39.68–89.22%) | 0/15 = 0% (0–20.39%) |
| Held-out, with CPU | 12 | 5 | 0 | 8 | 12/17 = 70.59% (46.87–86.72%) | 0/8 = 0% (0–32.44%) |
| Held-out, without CPU | 12 | 5 | 0 | 8 | 12/17 = 70.59% (46.87–86.72%) | 0/8 = 0% (0–32.44%) |

Held-out **with minus without**: TP/FN/FP/TN deltas all 0; detection and FPR
deltas both **0.00 percentage points**. The ablation JSON uses the opposite sign
(removed minus full), also zero here. Deltas are point estimates; Wilson intervals
above are not confidence intervals for the paired deltas.

The CPU stage alone detected 0/10 dev attacks (0%, CI 0–27.75%) and 2/17
held-out attacks (11.76%, CI 3.29–34.34%), with 0/15 dev false positives
(CI 0–20.39%) and 0/8 held-out false positives (CI 0–32.44%). Its silent dev
scores explain the zero fitted weight; held-out scores did not select weights.

## Cached classifier latency

Totals were summed from the pinned CPU chunk caches and checked against the
`cpu-classifier` entries in the fused run manifests. Means per record sum all
chunks for each record; means per chunk use cache entry counts.

| Split | Records | Chunks | Total (ms) | Mean per record (ms) | Mean per chunk (ms) |
|---|---:|---:|---:|---:|---:|
| Dev | 25 | 37 | 522,817.850 | 20,912.714 | 14,130.212 |
| Held-out | 25 | 27 | 132,401.123 | 5,296.045 | 4,903.745 |

Held-out summed cached stage latency rises from 1,528,635.972 ms without CPU
to 1,661,037.095 ms with CPU, a difference of 132,401.123 ms. Dev rises from
3,927,393.491 to 4,450,211.341 ms, a difference of 522,817.850 ms. Replay
evaluates every configured stage, including zero-weight stages. These numbers
describe original cached classifier work, including all chunk positions; they
are neither replay wall time nor a fresh end-to-end CPU benchmark. Repeated
chunks may reuse original request latency. No new model/cache storage was needed;
the only measurement artifact added locally is aggregate ablation JSON.

## Limits and validation

Both input manifests declare `evaluator_approved: false`; these are exploratory
source labels with synthetic augmentation. The deterministic capped sample is
not a full-split result. Fifteen of the 17 held-out attacks are from the reserved
Gandalf family. Eight benign held-out records with no false positives still allow
an FPR up to 32.44% at the reported confidence level, far above the 0.02% target.
This report does not justify changing classifier settings using held-out data.

Added a synthetic three-stage ablation regression covering a chunk classifier
that is silent on dev but fires on held-out attacks or benign records. It checks
that dev fitting keeps its weight zero and removal preserves held-out metrics
and deltas. No new dependencies or runtime behavior were added.

Validation: repeated ablation replay produced identical JSON bytes;
`uv run pytest -q` passed (708 passed, 1 skipped, 9 xfailed, 64 subtests);
`uv run ruff check` passed. Staged diff review and secret-pattern scan passed.
