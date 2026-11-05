# Coverage-directed generation

Ticket 0069 adds an offline feed from aggregate coverage to the existing cached generator.
`ops/coverage.py --targets-output FILE` sums attack marginals across selected manifests and
exports channel/technique pairs touching a GAP (zero) or LOW (1–19) marginal. UNKNOWN channels
do not establish gaps. Joint channel/technique counts are unavailable, so this does not claim
measured joint coverage. Inputs must be disjoint to avoid double counting.

`data_processing.generate --coverage FILE --max N` sorts and deduplicates those targets,
visits each at most once, and caps requests at N (`--groups` remains supported). The canonical
target list participates in the run ID. Empty targets return a zero-request plan with no client
construction, cache writes, or candidate files. The default taxonomy/seed cycle is unchanged.
Usage and limitations are documented in `docs/datasets.md`.

## Measured effect and validation

- The nine checked-in source manifests export 42 targets out of 48 possible pairs.
- An offline dry-run with `--max 10` plans 10 requests / 40 candidate records, with no inference
  or output/cache writes. Each request still produces three attack variants and one hard negative.
- Fake-client tests verify GAP/LOW selection, UNKNOWN exclusion, summed counts, lexical ordering,
  deduplication, caps, empty targets, input validation and replay after target reordering.
- No detection, false-positive or inference-latency improvement is claimed. No new dataset was
  generated or approved, and no server was started, stopped or changed.
- `uv run pytest -q`: 502 passed, 1 skipped, 64 subtests passed (66.23 s).
- `uv run ruff check`: passed. Staged diff reviewed and changed files scanned with
  detect-secrets 1.5.0; no findings.
