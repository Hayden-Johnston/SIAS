# Server uptime sampling and lanes

Ticket 0023 adds concurrent metadata-only HTTP GET sampling to dispatcher ticks, enabled by
`servers.local.json` in the integration checkout. The example lists five local llama.cpp endpoints,
a second-host router placeholder and Maya health. Hosts stay in ignored local configuration.
Each endpoint has a one-second socket timeout and a 64 KiB response cap. Only timestamp, configured
name, availability and advertised loaded model IDs are appended to `board/servers.jsonl`.
Router entries explicitly marked unloaded are excluded. Health-only endpoints need not expose
models. No inference or server/container lifecycle operations were performed. No new dependencies.

The Activity page adds a second chart sharing the agent timeline's pan, zoom and live window.
Server lanes label up/down intervals and show model IDs and Pacific timestamps on hover. Equal
adjacent samples merge; samples expire after ten minutes, leaving unknown gaps rather than
implying uninterrupted uptime. Invalid/partial records and future timestamps are skipped.
The dashboard projects only metadata and never reads status URLs, response bodies or local config.
README and dashboard docs describe setup and the sampled availability semantics.

Measured effect using seven synthetic endpoints that each consume their full one-second timeout:
**1.002 seconds per tick**, below the three-second acceptance limit. The synthetic seven-record
append was 693 bytes (about 195 KiB/day at five-minute intervals, excluding models and varying
name lengths). History is append-only; no automatic retention. Socket timeouts do not bound DNS
resolution, so numeric local addresses are recommended. HTTP failures, including authorization
errors, count as down. Availability is not an inference health guarantee. No operational server
uptime claims were made; local configuration/deployment remains with the integrator.
Detection, false positives and inference latency are unchanged; no model calls or payload reads.

Validation:

- `uv run pytest -q`: 201 passed, 1 optional browser module skipped, 48 subtests passed.
- `uv run ruff check`: all checks passed.
- Optional Playwright suite: 4 passed, including server bars, model/status tooltips and shared
  zoom/pan/live controls without agent runs; no JavaScript errors. Chromium and required shared
  libraries were supplied under a temporary directory, with no runtime dependency changes.
- Synthetic tests cover loaded/unloaded model filtering, health-only responses, transport timeouts,
  seven simultaneous failures, repeated append, STOP, chronological lane merging, model changes,
  stale gaps and metadata projection. No real server was probed for these measurements.
