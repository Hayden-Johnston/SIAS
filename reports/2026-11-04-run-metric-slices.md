# Run metrics by technique and attack family

Ticket 0044 adds fused detection metrics by channel, length bucket, schema-v2 technique
and attack family to run manifests and dashboard Metrics. Each slice includes confusion
counts, total rows, detection and false-positive denominators, and 95% Wilson intervals.
Slices below 20 rows are flagged rather than omitted. Multi-technique rows contribute once
per technique; benign rows contribute no technique, leaving technique false positives undefined.
Empty datasets produce empty maps. Older manifests remain readable without slices.

The runner retains technique metadata without payload text and advances its identity version
to 4. No new dependencies, inference, model lifecycle operations or changes to iterate.py.
Existing completed iteration manifests need a separate replay to gain slices.

On the four-row synthetic replay fixture, detection and false positives remain 0.5 (n=2 each),
with TP/FP/FN/TN all 1. It produces one channel, one length, one technique and two family
slices. The serialized slice object occupies 1,321 bytes; one local replay took 1.54 ms.
This is a small fixture observation, not a latency benchmark or evidence of detection quality.
Cached scoring latency is unchanged. No real dataset payloads were inspected.

Validation: `uv run pytest -q` passed (336 tests, 1 optional browser module skipped,
53 subtests); `uv run ruff check` passed. Added tests cover multi-technique and empty
technique lists, empty slices, the 19/20-row boundary, Wilson denominators, aggregate-only
dashboard projection and older manifests. An optional browser regression test covers
rendering, selection persistence, older manifests and escaped labels. The optional browser
suite could not launch Chromium because the environment lacks `libatk-1.0.so.0`; browser
rendering remains unverified here.
