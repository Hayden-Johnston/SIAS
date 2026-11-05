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

The Metrics page includes a run selector and fused metrics by channel, length bucket, technique
and attack family. It shows total slice counts, each rate's denominator and 95% Wilson interval,
and flags slices with fewer than 20 rows. Technique slices overlap and exclude benign rows;
undefined false-positive rates stay undefined. Older manifests show no slice metrics until replayed.

The `#recall` page follows the latest complete run on every refresh and shows technique and channel
attack counts, detected/missed counts and detection with 95% Wilson intervals. Its n<20 flag uses
the attack denominator, including in channels with benign rows. Benign-only channels have undefined
recall. Empty directories and older manifests without slices show an explicit empty message.

Use `--runs /path/to/runs` to point at a runs directory (the default is configured in the server code).
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
`#runs` (manifest history and selected aggregate report), `#metrics` (improvement charts),
`#recall` (latest technique/channel detection), and `#ablation` (stage removal comparisons).
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
process probe, and can lag until dispatch reaps a finished process. Dense start tags can overlap at wide zoom levels.

## Updates and alerts

`#updates` is the default page. It merges ticket `## Log` lines, local `master` commit subjects
and short SHAs, and report filenames, newest first. The window starts at 48 hours; Load more adds
48 hours and preserves that window on refresh. `/api/state?hours=96` requests the same expanded
window. Messages are flattened and limited to 240 characters. Report contents and ticket specs
are never returned. Report timestamps use file modification time (local arrival/change, which can
change on checkout); commits use committer time. Ticket logs have no timezone in their source, so
are interpreted in the server's local timezone, matching the dispatcher that writes them, then
shown in Pacific time.

Every page has a banner with the alert count and the three newest items, linking to `#alerts`.
Alerts include blocked tickets, unfinished user tickets, failed or unknown-exit runs completed
within 24 hours, failure cooldowns, STOP, and no run starts for two hours with ready agent tickets.
A ready ticket must have all dependencies done; user actions alone do not trigger a stall. With no
run history, ticket creation supplies the stall clock. Ticket alert times use the latest log or
creation date: the board does not record status transition times. Cooldowns clear when an agent is
running or its latest failure cooldown expires.

The dispatcher's only new write is a metadata-only line in `board/alerts.jsonl` when all worker push
attempts fail. Those alerts remain visible until the operator removes the corresponding lines;
no automatic resolution is inferred from later pushes. Failed push stderr is never stored here.

The Alerts page offers opt-in browser notifications, remembered in localStorage. After the first
successful refresh, newly appearing alert IDs notify once while the tab is open; existing alerts on
page load do not notify. Permission must be granted by the browser (usually requiring localhost or
HTTPS). Notifications may be unavailable on browsers that require a service worker. No background
notification service is installed.


## Server uptime

Copy `servers.example.json` to gitignored `servers.local.json` in the integration checkout and
replace the example second-host address with its local address. This is the single endpoint list:
five llama.cpp `/v1/models` endpoints, the second host router's `/v1/models`, and Maya `/health`.
The orchestrator owns this configuration. Use status-only URLs that require no authentication;
no credentials or arbitrary headers are stored. Prefer numeric local addresses to avoid DNS delays.
No config means no sampling. `board/STOP` pauses sampling along with dispatching.

Each `ops/dispatch.py tick` probes the configured endpoints concurrently using stdlib HTTP GETs
with one-second socket timeouts and a 64 KiB response cap. HTTP 200 means up; HTTP errors and
transport failures mean down (including authorization failures). This is endpoint availability,
not a guarantee that inference will succeed. Model IDs are captured from OpenAI-style model lists;
router presets with a status other than loaded are excluded. Health-only responses can leave the
model unknown. No inference, load, unload, or server/container lifecycle requests are made.

Only timestamp, configured display name, up/down and model IDs are appended to local
`board/servers.jsonl`; URLs and response/error bodies are discarded. The dashboard reads this
metadata file without probing servers or opening the local config. The Activity page's second
chart shares the agent chart's Live, pan and zoom controls, with directly labeled server lanes,
green up bars, vermilion down bars and model/time hover details in Pacific time. Samples extend to
the next sample or ten minutes, whichever comes first, and merge when status/model agree.
Longer gaps remain blank and the current state becomes unknown after ten minutes. This is sampled
history, not continuous uptime measurement. Partial/invalid records and future samples are skipped.
The append-only history has no automatic retention policy.

## Stage ablation

The `#ablation` page reads `stage-ablation.json` directly from the `--runs` directory,
matching the output example in [pipeline.md](pipeline.md#replay-only-stage-ablation).
It shows the full fit and each leave-one-stage-out fit: held-out TP/FN/FP/TN counts,
detection and FPR with denominators and 95% Wilson intervals, and deltas versus full
in percentage points. Undefined rates/deltas display as a dash; full has no delta.
Weights are refitted on dev for each removal. Deltas describe the refitted system and
are point estimates without confidence intervals. Held-out results are for reporting,
not repeated tuning; the inherited held-out evaluator approval flag remains visible.

The file refreshes with the rest of the dashboard. Missing, malformed, unsupported or
symlinked files show an explicit empty state. The endpoint projects only displayed
aggregate fields; it never follows input references or opens datasets, caches or payloads.
