# Small scheduled red-team round (ticket 0096)

The iteration's optional `red_team.coverage` path now feeds the GAP/LOW target JSON from
`ops/coverage.py` into the existing generator. Paths resolve relative to the iteration config;
target contents join the iteration identity. Omitting coverage retains the taxonomy cycle.
Empty targets checkpoint `no coverage targets` without invoking the evaluator. Maya transport
failures retain the existing checkpointed skip, including when resuming an interrupted iteration.
Generation still uses the cached client with batch/concurrency 1 and no Maya lifecycle operations.

The example config sets a cap of 30 triples and references `coverage-targets.json`, while keeping
its opt-in switch off. Thirty groups bound work to 30 serial generation requests, 90 attack
variants and 30 hard negatives (at most 120 evaluator inputs before filtering). This is a small
initial budget rather than a throughput measurement; slow generation should not consume an
unbounded scheduled iteration. Generation remains capped independently of the existing 50-prompt
Maya classification budget.

## Scheduled config handoff

A replacement scheduled config, coverage export and minimal validated evaluator inventory are
prepared outside git under the storage root's `ticket-0096/` directory. The replacement preserves
the live source, split and classifier settings, enables `red_team`, sets `groups: 30`, and uses
absolute paths for coverage, the existing CPU evaluator binary and the prepared inventory.
Classifier config paths are also absolute so relocating this prepared file preserves resolution.
The original scheduled config's evaluator inventory path is missing; the replacement inventory
pins the already configured Qwen checkpoint and its measured size (1,217,757,440 bytes).

**Activation is blocked:** the integration checkout's live `iterate.local.json` lies outside this
worker's writable roots. Claude must review and apply the prepared config to that checkout. The
live config remains unchanged and red-team generation remains disabled there. No scheduler was
run, and no model server, container or GPU allocation was changed.

## Measured effect and validation

An offline dry-run against the nine checked-in source manifests exported 42 GAP/LOW targets and
planned 30 requests / 120 candidate rows. These are marginal coverage gaps, not measured joint
channel/technique gaps. No candidates were generated or approved. Detection, false positives,
inference latency and runtime storage growth were not measured; no improvement is claimed.

Fake-client tests cover targeted approval and split/replay behavior, the 30-group cap, changed
coverage creating a new iteration, empty targets avoiding evaluation, and transport/replay-only
skips persisting across interrupted-iteration resume.

Validation: `uv run pytest -q` passed (710 passed, 1 skipped, 9 xfailed, 64 subtests;
107.78 seconds). `uv run ruff check` passed. The focused iteration suite passed all 50 tests.
Staged changes were reviewed and scanned with detect-secrets 1.5.0; no findings.
