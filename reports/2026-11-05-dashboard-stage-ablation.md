# Dashboard stage ablation

Ticket 0080 adds an Ablation navigation page (`#ablation`). It reads the existing
`data_processing.ablation` output at `stage-ablation.json` in the dashboard runs directory.
The full fit and sorted leave-one-stage-out fits show held-out confusion counts,
detection/FPR with denominators and 95% Wilson intervals, and signed percentage-point
deltas versus full. The page explains dev refitting, point-estimate deltas and held-out
reporting limits, and shows the inherited evaluator approval flag. Undefined values
remain undefined. Missing, malformed, unsupported or symlinked files show an empty state.

The loader projects displayed aggregate fields only and never follows input references.
Existing manifest number/rate validation is shared with the ablation loader. No new
runtime dependencies, inference or server lifecycle operations were added. README and
dashboard documentation describe the file location and view.

Synthetic measurements: full detection 2/2 and FPR 1/2 versus a removed-stage fit with
detection 1/2 and FPR 0/2 display -50 percentage points for both deltas. Loader tests
cover aggregate-only reads/projection, absent/invalid input, symlinks and undefined
rates/deltas. Browser checks cover the empty state, counts, interval/delta formatting,
deep links, refresh, undefined values and literal stage-name rendering.

Validation: `uv run pytest -q` passed (618 tests, 1 optional browser module skipped,
64 subtests). `uv run ruff check` passed. The separate optional Playwright suite
passed all 7 tests using cached Chromium and local browser libraries. The initial
browser invocation lacked a browser in the default cache; setting the existing cache
and library paths resolved it. A detect-secrets scan of changed files found no secrets.
Detection/FPR behavior, model latency and stored run artifacts are unchanged; this
view displays existing measurements. Dashboard latency was not benchmarked.
