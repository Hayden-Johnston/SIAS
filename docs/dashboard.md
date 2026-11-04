# Dashboard

Local web front end, read-only over run manifests, reports and proxy state. Small: a static page plus
a thin JSON endpoint; no heavy framework unless the repo already uses one.

## Data rule

No raw payload text, ever. The dashboard shows aggregates only (counts, rates, attack-family names,
stage names). Its code must not read payload files.

## Views

- **Jobs and queue:** per model and server: queued, running, finished, loaded or unloaded, GPU
  assignment.
- **Run history:** table of runs with timestamp, iteration, pipeline version, dataset, key metrics, and
  a link to the run's report.
- **Improvement time series:** detection rate and false-positive rate against time, with an
  annotation at each iteration or pipeline change, confidence bands, and dashed target lines
  (99.999%, 0.02%). Use a log or zoomed axis; differences are tiny near the target.
- **Outcome pie chart:** true positives, false positives, false negatives and true negatives for a
  selected run, with counts. Most useful before the targets are met. Keep it afterwards.
- **Change log:** what changed per iteration (software, infrastructure, model, pipeline), from
  `reports/`.
- **Per-stage view:** how many prompts each stage caught or passed, and latency per stage.

## Look

Clean and quiet. One static page with hash-routed views, generous spacing, one typeface, readable at a glance.
Same color for the same metric across every chart; fixed semantic colors for TP, FP, FN, TN that are
color-blind safe. Label lines directly instead of relying on legends. Light and dark themes.
No 3D, gradients, or rainbow palettes.

## Board dashboard v0

Run `python3 dashboard/server.py` from the checkout (stdlib only). It binds to `0.0.0.0:8300`;
use `--port` to change the port and `--board /path/to/board` to inspect another board.
Open `/` for the page or `/api/state` for JSON. The page refreshes every 15 seconds and follows the
system theme, with a button to switch themes. It shows ticket headers, running agent records and
completed agent history and aggregate run metrics. Duration is measured in seconds from the
recorded start and end timestamps. Missing board files produce empty views; incomplete JSON records
are skipped until the next refresh. Agent logs and payload files are never opened.

`ops/sias-dashboard.service` is a systemd user unit for an integration checkout at
`%h/llm_security`; installation and startup are left to the integrator.


## Run metrics

Use `--runs /path/to/runs` to change the default `/mnt/storage/llm_security/runs`.
Each immediate child directory may contain one `manifest.json` from `data_processing.run`.
Only complete schema-version-1 manifests are shown, newest first; malformed or unsupported files
are skipped. Run-directory and manifest symlinks are skipped. No datasets, result files, score
caches or report files are opened. The JSON endpoint projects only the fields used by the views.

Run history shows a shortened dataset SHA-256 (full hash on hover) and evaluation split (the runner
does not record a dataset name), counts, rates, 95% confidence intervals and sample sizes. Each run links to its aggregate
report on the page: attack distribution, evaluator approval, an outcome pie with fixed Okabe–Ito
colors (TP blue, FP orange, FN vermilion, TN green), and per-stage reached/caught/passed counts and
cached latency in milliseconds. Report selection survives refreshes when new runs arrive.

Time series use actual manifest timestamps, iteration/pipeline annotations and the manifest's 95%
confidence bands. Detection uses a logarithmic distance from 100%, and false positives a logarithmic
rate; the dashed targets are 99.999% and 0.02%. Zero errors and interval bounds are clipped at
0.00001% error for plotting only; table values remain exact to five decimal places in percent.
Undefined rates remain undefined. These are dataset/split measurements, not claims of general
performance. Dense annotation labels may overlap with many runs.

Browser regression checks are optional, keeping runtime dependencies stdlib-only:
`uv run --with playwright python -m playwright install chromium`, then
`uv run --with playwright pytest -q tests/test_dashboard_browser.py` (Chromium system libraries
must be available). The regular suite tests synthetic manifest projection and HTTP routes.

## Pages and agent activity

The persistent navigation opens `#board` (tickets), `#activity` (agent timeline and history),
`#runs` (manifest history and selected aggregate report), and `#metrics` (improvement charts).
Reloading a deep link preserves the view. All displayed timestamps use America/Los_Angeles with
PST/PDT labels, independent of browser and server timezone; files and API timestamps keep their
recorded timezone.

Activity reads only run metadata from `board/runs.jsonl`, `board/running/*.json` and ticket headers.
Each discovered agent gets a directly labeled lane and a stable color, including future agent names.
Bars show ticket/mode at their start, completed exit markers (ok or failed), and hover details with
ticket title, duration and exit code. Running bars extend to the latest refresh time.
The live window follows the last six hours; Earlier/Later pan by half a window, zoom buttons change
its width (15 minutes to one year), and Live resets it. History windows stay fixed on refresh.
Active hours count the union of each agent's intervals clipped to the visible window.

State lines show running ticket and minutes, resting, capped until a Pacific timestamp, or idle.
The dispatcher and dashboard share pause calculations, including minimum gaps, failed-run cooldowns
and rolling run caps. Running records take precedence. State reflects dispatcher records, not a
process probe, and can lag until dispatch reaps a finished process. No server lanes are built yet;
those can be added alongside the agent chart later. Dense start tags can overlap at wide zoom levels.
