# Replay stage fusion — 2026-11-04

Ticket 0037 adds deterministic max fusion to the cached-score runner. Every stage now evaluates
all dataset rows so its independent detection and false-positive rates can be compared with
fusion on the same split. The optional run-config `fusion` object sets a threshold (default 0.5)
and per-stage weights (default 1, range 0–1). Existing stage thresholds govern independent
verdicts. Results include `fused_score`; the manifest includes stage metrics and `fusion.metrics`
with confusion counts, denominators and 95% Wilson intervals. Top-level metrics describe fusion.
Existing runner metrics are reused; the legacy percentage/rounding measurements API is unchanged.
Runner identity version is 3 and binds all fusion settings.

Complete caches are required: earlier detections no longer skip later stage scores. Missing
entries fail before replacing output. Empty conversations have chunk-stage score zero and no
location. No inference, model client, dependency or server lifecycle changes were introduced.
README, pipeline and run documentation explain the full-cache requirement and metric semantics.

## Measured effect and limits

Synthetic fixture: two attacks and two benign rows, two stages, threshold 0.5. Stage one detects
1/2 attacks with 0/2 false positives; stage two detects 0/2 with 1/2 false positives. Default max
fusion detects 1/2 with 1/2 false positives. Weighting stage two by 0.5 retains 1/2 detection and
reduces observed false positives to 0/2. These tiny, unapproved fixtures establish calculation
behavior only; no claim of held-out quality improvement or calibrated scores is made.

Each stage now covers four rows rather than four/three reached rows in the old fixture cascade.
At 2 ms cached latency per score, stage totals are 8/8 ms rather than 8/6 ms. These are cached
measurements, not a replay runtime benchmark. Outputs retain no text; storage adds one fused
score per row, per-stage metric summaries and fusion settings. No production storage or latency
benchmark was performed. Repeated default and weighted runs produce byte-identical outputs.

## Validation

- `uv run pytest -q`: 313 passed, 1 skipped, 53 subtests passed.
- `uv run ruff check`: passed.
- Tests cover max/weighted fusion, inclusive thresholds, independent thresholds, complete caches,
  invalid settings, empty conversations, identity changes and deterministic replay.
- Staged diff reviewed and changed files scanned with detect-secrets; no findings.
