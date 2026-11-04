# Dashboard run metrics

Ticket 0015 replaces the metrics placeholder with manifest-driven run history, detection and
false-positive time series, an outcome pie, and per-stage caught/passed counts and cached latency.
`--runs` defaults to `/mnt/storage/llm_security/runs`; only immediate child `manifest.json` files
are read. Complete schema-version-1 manifests are projected onto aggregate fields, malformed files
are skipped, and run-directory/manifest symlinks are ignored. Results, datasets, caches and report
files are never opened. Board behavior is preserved. No model servers or deployed services changed.

Run history identifies datasets by shortened hash and split, because manifests do not include a
name. Full hashes are available on hover. Each run links to its aggregate report on the page rather
than an external report file. Rates include sample sizes, 95% manifest confidence intervals,
evaluator approval and attack distribution. Outcome colors use the fixed Okabe–Ito palette.
Stage latency is explicitly labeled cached scoring latency, not replay or dashboard execution time.

The charts use timestamps, iteration/pipeline annotations, confidence bands and dashed targets
(99.999% detection and 0.02% false positives). Detection uses log distance from 100%; false positives
use log rate. Plotting clips zero errors/interval bounds at 0.00001% error while preserving reported
values in tables. Undefined rates stay undefined. A boundary regression test covers Wilson intervals
whose floating-point upper endpoint is just below a valid 100% estimate. Labels may overlap with
many runs; small screens can scroll the charts. Dataset/split changes are visible but not normalized
away; these charts do not establish generalization across attack distributions.

Validation:

- `uv run pytest -q`: 99 passed, 1 optional browser test skipped, 39 subtests passed (3.07 s).
- `uv run ruff check`: all checks passed.
- Staged diff reviewed; `detect-secrets scan --all-files` on all seven changed files: no findings.
- Chromium: optional `tests/test_dashboard_browser.py` passed (1.72 s), covering zero/several runs,
  CI charts, selection surviving new runs, themes, mobile overflow, undefined rates, a single pie
  outcome and escaped labels, with no JavaScript errors. Browser and missing shared libraries were
  downloaded/extracted under `/tmp`; no project runtime dependencies were added. Reproduce using
  the commands in `docs/dashboard.md` with Chromium's system libraries available.
- Synthetic HTTP/filesystem tests cover aggregate-only projection, configured roots, chronological
  ordering, missing/partial/unsupported manifests, symlinks, empty denominators, stage latency and
  rejection of arbitrary result-file routes. No real run data or payloads were used.

Measured effect: three synthetic manifests took median 0.270 ms to project over 100 warm reads;
their projected JSON was 2,241 bytes. This excludes HTTP/browser time and is not an operational-scale
benchmark. No persistent dashboard storage is added. Detection, false positives and model inference
latency are unchanged; no inference was performed.
