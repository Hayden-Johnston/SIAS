# Dashboard recall by technique and channel

Ticket 0073 adds a Recall navigation page (`#recall`) for the latest complete run manifest.
It follows new runs on refresh and displays technique/channel attack counts, detected and missed
counts, detection rates and existing 95% Wilson intervals. Attack denominators below 20 are
flagged, including benign-only channels with undefined recall. Techniques may overlap.
Empty run directories and manifests without slices show explicit empty messages.

The existing manifest loader now projects slice TP/FN counts as well as rates. No payload,
result, dataset or cache files are opened. README and dashboard documentation describe the page.
No dependencies or model/server operations were added.

Measured with synthetic manifest fixtures: 14 detections and 6 misses among 20 attacks display
70% recall with the manifest Wilson interval; a one-attack channel retains its small-sample flag,
and a benign-only channel retains undefined recall. Loader checks verify newest-run ordering,
aggregate-only projection and manifest-only reads. Browser checks cover empty state, counts,
interval formatting, navigation/deep links and switching to a new latest manifest without slices.

Validation: `uv run pytest -q` passed (579 tests, 1 optional browser module skipped,
64 subtests). `uv run ruff check` passed. The optional Playwright suite passed all 6 tests
using cached Chromium and locally available browser libraries.

Detection and false-positive behavior, model latency and on-disk run storage are unchanged;
this change displays existing measurements. Dashboard latency was not benchmarked.
