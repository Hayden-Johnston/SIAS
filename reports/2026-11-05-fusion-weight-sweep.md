# Replay-only fusion weight sweep

Added `data_processing.sweep` to select fusion weights from `{0, 0.5, 1}` on
validation caches, maximizing observed TPR under a required observed FPR cap.
Ties minimize total weight, then the weight tuple in sorted stage-name order.
The selected weights and an all-ones baseline are evaluated on held-out caches
only after selection. The script reuses runner validation, scoring, metrics and
atomic writes; JSON includes Wilson intervals, input identities and rate deltas.
No dependencies, inference or server lifecycle operations were added.

Synthetic measurements (two attacks and two benign rows per split):

- Complementary dev stages select weights `(0.5, 0.5)` with TPR 1 and FPR 0.
  Held-out TPR is 1 and FPR 0.5, demonstrating the dev cap is no held-out guarantee.
- A redundant noisy stage is suppressed with weights `(1, 0)`, retaining held-out
  TPR 1 while reducing FPR from 0.5 to 0 (delta -0.5).
- Repeated API and CLI calls produce identical JSON bytes. Tests instrument the
  runner to verify all nine dev candidates finish before any held-out read,
  followed by exactly two held-out evaluations (chosen and baseline).

These fixtures establish replay and selection behavior, not real-world detection
quality. No production datasets were scored; latency and storage effects were not
benchmarked. The sweep requires only existing datasets/caches and writes one
aggregate JSON file when requested. Runtime grows as `3 ** stage_count`.

Validation: `uv run pytest -q` passed (424 passed, 1 skipped, 64 subtests);
`uv run ruff check` passed. Staged diff review and secret-pattern scan passed.
