# Dashboard updates feed and blocker alerts

Ticket 0026 makes project activity and work needing attention visible without asking an agent.
Updates is now the default page; it merges ticket log lines, local master commit subjects/short
SHAs, and report filenames. The default 48-hour window expands in 48-hour steps. All visible times
use Pacific time. The existing page, polling endpoint and stdlib server are retained.

A persistent banner links to the Alerts page and previews the three newest alerts. Sources are
blocked tickets, unfinished user tickets, recent failed/unknown-exit runs, failure cooldowns, STOP,
a two-hour gap in run starts with ready agent tickets, and exhausted worker push attempts. The
only dispatcher change appends metadata to alerts.jsonl after all push attempts fail. Browser
notifications are opt-in, remembered locally and emitted for new IDs after the first refresh.
No dependencies were added. No model/server/container operations or inference were performed.

## Verification and measured effect

- `uv run pytest -q`: 186 passed, one optional browser module skipped, 48 subtests passed.
- `uv run ruff check`: passed.
- Optional Playwright suite: all three tests passed, including empty views, page routing, feed
  expansion, safe text rendering, notification opt-in/persistence/deduplication and existing charts.
  Chromium needed existing temporary shared libraries; the initial launch without them failed.
- Synthetic tests cover blocked/user alerts, null and nonzero exits, 24-hour cutoff, cooldown expiry
  and running precedence, stall threshold/dependencies, STOP, push exhaustion and successful retries,
  merged feed ordering and wider windows. Private fixture bodies, report contents and push stderr
  are excluded from the response.
- 100 sequential `state()` calls with an empty temporary board, absent metrics directory and this
  checkout's master/reports: median 3.25 ms, maximum 4.61 ms (local `perf_counter` measurement).
  This measures the small-board endpoint builder, not browser latency or large-board performance.
- Detection and false-positive metrics are unchanged. Existing polling remains 15 seconds.
  Storage grows by one small JSON line per exhausted worker push; there is no new cache or service.

## Limits

Ticket files do not record status transition timestamps: alert times use the latest log or creation
date. Ticket logs use the dispatcher's local timezone because the source omits offsets. Reports use
file modification times (arrival/change in this checkout), so checkout or edits can move them in the
feed. Report contents are never opened. With no run history, ready-ticket creation anchors the stall
clock. Push-failure lines persist until an operator removes them; later pushes do not resolve them.
Browser notifications require permission and browser support, and only work while the tab is open.
