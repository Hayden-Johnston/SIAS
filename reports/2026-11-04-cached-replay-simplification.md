# Cached-score replay simplification (0008)

Replay now computes results in memory and atomically replaces results.jsonl followed by
manifest.json. Removed the checkpoint journal, per-row flush/revalidation, lock, and identity
file. The manifest retains identity_sha256 and results_sha256; consumers must check both
against expected inputs/results to detect stale outputs after an interrupted replacement.
Changed inputs can reuse a directory. Validation/evaluation failures preserve existing outputs.
Timezone parsing is shared with normalization through utc_timestamp in normalize.py.

run.py decreased from 278 to 237 lines. Fresh runs create two files instead of four. Existing
synthetic fixture results and manifest were captured before the change and compared afterward:
both are byte-identical. The four-row fixture still has TP/FP/FN/TN = 1/1/1/1, detection and
false-positive rates 0.5 (n=2 each), and cached stage latency totals of 8 and 6 ms. These are
synthetic checks, not detection-quality evidence. Replay latency and peak memory were not
benchmarked; all results and their serialized bytes now reside in memory.

Validation: uv run pytest -q (44 passed, 16 subtests passed); uv run ruff check passed.
Tests cover deterministic output, changed-input replacement, missing-score preservation,
and a failed manifest replacement leaving a checksum-detectable stale pair with no temporary
files. Resume-only tests were removed. No model inference or server operations were performed.
