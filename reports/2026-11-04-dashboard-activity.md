# Dashboard pages and live agent activity — 2026-11-04

Ticket 0020 adds persistent hash navigation for Board, Activity, Runs and Metrics. Activity shows
one stable-colored lane per discovered agent, ticket/mode start tags, completion status markers,
metadata tooltips, current dispatcher state and active hours in the selected window. The six-hour
live window follows each 15-second refresh; pan/zoom preserve a historical window until Live is
selected. All displayed timestamps use Pacific PST/PDT regardless of browser timezone.

The dashboard imports shared dispatcher pause calculations rather than copying scheduling constants.
The dispatcher uses that same helper for rolling caps and cooldown eligibility; no scheduling
limits change. Unknown agents work without configuration. Metadata projection rejects incomplete
intervals and avoids double-counting a run during the dispatcher's append/unlink transition.
No new runtime dependencies, persisted data, inference or model-server operations are required.
Server lanes remain deferred to ticket 0023.

Validation and measured effect:

- `uv run pytest -q`: 107 passed, 1 optional browser module skipped, 39 subtests passed.
- `uv run ruff check`: passed.
- Optional Chromium suite: 2 passed in 18.50 s. Checks cover empty views and reloadable deep links, manifest report selection,
  Pacific PST/PDT in a Tokyo browser, timeline bars, failed exits, running-bar growth, active hours,
  pan, zoom and Live reset. Browser libraries and Chromium are supplied from temporary directories.
- Synthetic API fixtures cover gaps, failed runs, a live run, a future agent, title projection,
  deduplication, and running/resting/capped/idle states including the exact cap-expiry boundary.
- Refresh interval falls from 30 to 15 seconds (twice the polling frequency); the same metadata files
  are read. No dashboard latency benchmark or detection/false-positive change is claimed.
- Synthetic browser intervals measure 2.00 active hours across two one-hour runs separated by a gap;
  extending the running interval by an hour grows its bar at the next render.

Limits: state follows dispatcher records and can lag process completion until reaping. The endpoint
still reads full metadata history; no large-history performance claim is made. Dense start tags can
overlap when zoomed out; short runs remain visible as at least one SVG unit. No payloads or agent
logs are read or served.
