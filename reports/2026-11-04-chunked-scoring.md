# Chunked cached scoring and location (ticket 0011)

Added optional per-stage character windows to cached replay. Windows stay within turns,
advance deterministically and align the last window to the turn end. Chunk caches use
`(id, turn, start)`; each reached row requires every chunk, takes its maximum score and
sums cached latency. Existing row caches remain supported. No inference or dependencies
were added.

Chunk stages record their window settings and location rates overall, by channel and by
fixed character-length bucket, with sample sizes and two-sided 95% Wilson intervals.
Location means the highest-scoring chunk intersects a known span, independently of the
detection threshold. Ties choose the earliest turn/start. Statistics and counts of spans
longer than overlap cover reached rows; unknown spans are excluded from location rates.
Results contain metadata and the selected coordinates, never payload text. Runner identity
version is now 2. `docs/runs.md` documents the cache contract and denominator choices.

Measured on synthetic fixtures only:

- Single-chunk conversion preserves all row detection/false-positive metrics and existing
  stage score, count and latency summaries exactly.
- The boundary/multi-turn fixture locates 1 of 2 known-span attacks: 0.5, Wilson CI
  approximately [0.0945, 0.9055]. Multi-turn/short: 1/1; email/long: 0/1. One span is longer
  than the configured overlap. Benign and unknown-span rows do not enter location rates.
- Its 3,422 cached chunks sum to 6,844 ms of supplied synthetic latency. This is cache
  accounting, not a performance measurement. Reordering cache lines preserves result bytes;
  replay with identical inputs preserves both output files byte for byte.
- Missing chunks preserve previous outputs; invalid coordinates, duplicate chunk keys and
  invalid window settings fail validation. An unreached stage needs no chunk scores.
- `uv run pytest -q`: 105 passed, 1 skipped, 39 subtests passed.
- `uv run ruff check`: passed.

No real dataset detection, false-positive, inference latency or storage benchmark was run.
Memory still scales with dataset metadata, caches and results; chunk caches grow with the
number of windows. Location measurements are per stage, so later cascade stages describe
only the rows they reach. Window sizes and length bands have not been tuned on approved data.
