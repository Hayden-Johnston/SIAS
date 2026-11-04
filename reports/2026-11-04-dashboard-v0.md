# Dashboard v0

Added a read-only stdlib HTTP server and static page for the dispatcher board. Five status columns
show only ticket id, title, owner and priority, alongside active agents and newest-first agent run
history. History duration is calculated from dispatcher timestamps. Metrics are a placeholder.
The page refreshes every 30 seconds, uses one system typeface, and supports light and dark themes.
The systemd user unit is provided but has not been installed or started.

The dispatcher ticket reader now accepts an optional ticket directory, preserving its default behavior
while allowing temporary-board tests and the dashboard's `--board` option. No payloads, agent logs,
run manifests or model servers are accessed. Two existing Ruff findings were corrected: a missing
blank line and an extra `self` argument on a static method (callers already pass only optional context).

Validation: `uv run pytest -q`: 5 passed (1.12 s); `uv run ruff check`: all checks passed.
HTTP tests cover missing/empty boards, all five statuses and counts, a running agent, a completed run
with a measured 90-second duration, partial JSON writes, field filtering, static page delivery and
rejection of arbitrary file paths. Browser layout/theme rendering was not visually verified because
no browser is available in this environment. Detection, false positives and model latency are unchanged;
no inference was run. No persistent dashboard storage is added; operational scale latency is unmeasured.
