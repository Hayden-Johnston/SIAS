# Iteration rules on full splits, Maya on samples

Ticket 0043 separates scoring datasets without changing either classifier or thresholds.
Previously both stages ran as a cascade on the same capped dataset. Rules now score every dev
and heldout row before model scoring starts. Maya retains the existing SHA-256 ID selection;
`sample_cap` is restricted to 1–25 per split, at most 50 classifier prompts per iteration.
Optional red-team generation retains its separate budget.

Four independent stage/split runs replace two sampled cascade runs. Each manifest's record count,
metrics, confidence intervals and reached count refer only to its own dataset. Dashboard Metrics
already accepts these manifests; no dashboard or generic replay-runner changes were needed.
These metrics do not estimate a combined cascade. Rule caches remain checkpointed, model requests
retain their existing cache keys, and identical completed iterations return without inference.
README, run documentation and the example config describe the new behavior.

## Measured effect

The exact live configuration uses deepset, jackhhao and Gandalf, cap 25, rule threshold 0.75.
An isolated validation run used those pinned local snapshots and a copy of the shared queue,
with inference disabled. Both full-split rule manifests were accepted by `dashboard.run_metrics`.
The previous sampled-rule outcomes below were computed from the same full rule scores using
the unchanged hash selection.

| Split | Previous rule sample | Full rule rows | TP | FP | FN | TN | Cached rule latency total / mean |
|---|---:|---:|---:|---:|---:|---:|---|
| Dev / validation | 25 (25 TN) | 273 | 0 | 0 | 0 | 273 | 50.664 / 0.186 ms |
| Heldout | 25 (13 TP, 12 FN) | 1,000 | 497 | 0 | 503 | 0 | 43.685 / 0.044 ms |

Rules cover 1,273 rows instead of 50. Heldout detection is 49.7%, n=1,000,
95% Wilson interval 46.61–52.79%. Dev false positives are 0%, n=273, interval
approximately 0–1.39%. Dev contains no attacks; heldout contains no benign rows.
These are unapproved source-label measurements, not evidence of improved detection quality.
The full rule caches occupy 29,363 and 107,385 bytes. Latencies measure cached rule scoring,
not model inference or end-to-end replay. No new model latency measurement was made.

## Validation and remaining live check

Tests cover full rule counts, sampled Maya counts, independent metric denominators, all four
manifests through the dashboard reader, deterministic hash selection, the 50-prompt classifier
limit, interrupted scoring, and byte-identical reruns without inference. Removing only the final
completion checkpoint also resumes from stage caches without inference or rescoring rules.

The shared storage iteration lock was held by an existing runner, whose Maya queue contained
4 done and 23 pending requests at validation time. No shared runner, queue, model server or
container was changed. The isolated cache-only validation stopped at missing Maya responses;
no model scores were fabricated and no new inference was performed. The complete live-config
Maya/dashboard acceptance check remains blocked until the existing runner releases its lock
and the required responses are available. Synthetic integration tests verify all four manifests,
including two Maya samples of 25 rows, but do not replace that live check.

Validation: `uv run pytest -q` and `uv run ruff check` (results recorded in the ticket log).
