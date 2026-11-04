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

Clean and quiet. One page with tabs or sections, generous spacing, one typeface, readable at a glance.
Same color for the same metric across every chart; fixed semantic colors for TP, FP, FN, TN that are
color-blind safe. Label lines directly instead of relying on legends. Light and dark themes.
No 3D, gradients, or rainbow palettes.

## Board dashboard v0

Run `python3 dashboard/server.py` from the checkout (stdlib only). It binds to `0.0.0.0:8300`;
use `--port` to change the port and `--board /path/to/board` to inspect another board.
Open `/` for the page or `/api/state` for JSON. The page refreshes every 30 seconds and follows the
system theme, with a button to switch themes. It shows ticket headers, running agent records and
completed agent history; run metrics remain a placeholder. Duration is measured in seconds from the
recorded start and end timestamps. Missing board files produce empty views; incomplete JSON records
are skipped until the next refresh. Agent logs and payload files are never opened.

`ops/sias-dashboard.service` is a systemd user unit for an integration checkout at
`%h/llm_security`; installation and startup are left to the integrator.
