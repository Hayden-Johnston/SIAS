# Agent board and dispatcher

## What changed

- `ops/dispatch.py`: file-per-ticket kanban board (`board/tickets/`, gitignored local state) and a
  cron-driven dispatcher. A tick starts the owner of each ready ticket (one run per agent), sends Codex
  work in `review` to Claude, and starts a Claude planning run when Codex has under 2 ready tickets or
  a ticket is blocked (at most hourly). Daily run caps per agent; `board/STOP` pauses everything.
- `ops/prompts/`: the prompt each run gets, with hard rules (never stop Maya, no raw payloads, no
  server start/stop unless the ticket says so, stop on usage-policy refusals).
- Codex works in a separate clone (`../llm_security-wt/codex`) whose git dir lives outside the
  checkout, because Codex's sandbox makes any `.git` inside its workspace read-only. Verified: Codex
  committed from its sandbox in that layout and failed with a git worktree. The dispatcher pushes
  Codex's branch (sandbox has no SSH key). Claude reviews, merges to master and pushes.
- AGENTS.md: board replaces TASKS.md; Claude is architect/integrator, Codex implementer; Maya rule.
- `docs/rig.md` is gitignored: it lists internal IPs. `config.json` on master still does (ticket 0006).
- `src/llm_security/__init__.py` added so `uv sync` builds the package.

## Why

The user wants continuous progress without intervention, visible on a dashboard.

## Measured effect

Dispatcher unit tests: 3 pass. No detection, latency or storage change. Disk headroom is the main
infrastructure risk: / has 18 GB free, /mnt/storage 43 GB.
