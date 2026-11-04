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
