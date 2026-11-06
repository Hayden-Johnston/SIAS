# Classifier sample cap from iteration 8

Choose `sample_cap: 5` per split. The example and worker-local configuration now
use that cap; the allowed range remains 1–25. The active integration configuration
still needs the same one-field edit by Claude: it is outside this worker's writable
sandbox. No inference, dataset reads or server lifecycle operations were performed.

## Numbers and budget

Inputs are iteration 8's validation and held-out fused `manifest.json` files and
its completion manifest's `cpu_classifier_counts`, summarized in
[the classifier-effect report](2026-11-06-classifier-effect.md). Each split has 25
records. Dev used 37 chunks and 522.817850 seconds; held-out used 27 chunks and
132.401123 seconds. These are cached HTTP latency sums for CPU inference, not
process CPU-seconds or a fresh wall-clock benchmark. Dev's 14.130 seconds/chunk
is materially slower than held-out's 4.904 seconds/chunk.

Budget the CPU classifier at **150 seconds per iteration**, half a five-minute
dispatcher tick, reserving the other half for other CPU work. With the measured
chunk mix, projected seconds at cap C are
`C * (522.817850 + 132.401123) / 25 = C * 26.208759` across both splits.

| Cap per split | Projected CPU classifier seconds | Worst-case 95% Wilson width, if n = cap (percentage points) |
|---:|---:|---:|
| 5 | 131.04 | 65.92 |
| 10 | 262.09 | 52.68 |
| 25 (previous) | 655.22 | 36.50 |
| 50 (above supported limit) | 1,310.44 | 26.71 |
| 100 (above supported limit) | 2,620.88 | 19.23 |

Five is the largest integer cap fitting 150 seconds; six projects 157.25 seconds.
The estimate falls by 524.18 seconds (80%) from cap 25, with 18.96 seconds of
headroom inside the CPU budget. Linear scaling assumes unchanged latency and
chunk mix; deterministic hash selection does not guarantee that mix. This is a
planning budget, not an enforced deadline or proof against starvation. The four
configured CPU evaluator threads remain unchanged; no concurrency was increased.

The dispatcher checks every five minutes but launches a pipeline at most every
six hours with a three-hour timeout. Maya's measured cached latency separately
projects to 1,091.19 seconds at cap 5, and full-split rules used 25.35 seconds.
Thus the whole iteration is not expected to finish within a tick. Red-team
generation is off in the active configuration. Changing the sample creates a
new iteration identity; unchanged completed calls can still reuse queue caches.

## Confidence limits and reproduction

Wilson full-width bound at denominator n is `z / sqrt(n + z*z)` with
`z = NormalDist().inv_cdf(0.975)`, attained at proportion 0.5 (an upper bound
when that fraction is impossible for odd n). The table uses n equal to the cap
only to show the best available sample denominator, not to promise that precision
for detection or FPR. Rates use attack and benign denominators separately.

Iteration 8 held-out had 17 attacks and 8 benign records. At the same mix, cap 5
would have roughly 3 attacks and 2 benign records: worst-case width bounds of
74.93 and 81.09 percentage points. Even zero false positives in two benign rows
gives a 95% Wilson interval of 0–65.76%. Actual counts and widths depend on the
selected sample and verdicts; either class could be absent. No detection or FPR
improvement is claimed. Exploratory labels and synthetic rows remain unapproved.

The latency budget cannot deliver useful confidence intervals at these measured
speeds. Larger statistical studies require a separate time budget; the selected
scheduled cap prioritizes the CPU budget over statistical precision. Storage should
decrease with fewer sampled rows/chunks, but bytes were not measured.

Reproduce the table without inference by loading the three aggregate manifests,
checking the two `cpu-classifier.cached_latency_ms_total` values against
`cpu_classifier_counts`, dividing their sum by 1,000 and 25, and multiplying by
each cap. The config regression checks that the example cap fits 150 seconds and
the next integer exceeds it. No new runtime code or dependencies were added.

Validation: `uv run pytest -q` passed (711 passed, 1 skipped, 9 xfailed,
64 subtests); `uv run ruff check` passed. Staged diff review, whitespace check
and secret-pattern scan passed; no dedicated secret scanner was installed.
