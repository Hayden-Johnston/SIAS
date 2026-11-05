# Held-out missed attack IDs

Added `data_processing.misses` to export an IDs-only miss manifest from an existing
held-out run manifest and its checksum-pinned results. It uses cached fused scores
and the recorded fusion threshold, with no inference, dataset reads or changes to
the iteration workflow. Output is atomic and deterministic, with provenance hashes,
approval flag, total counts, sorted missed IDs and technique/channel groups. Unknown
input fields are never copied. Invalid metadata, checksums or counts fail before output
replacement; input files cannot be overwritten.

Synthetic measurement: five scored rows contain four attacks and one benign row.
At threshold 0.5, three attacks are missed; an attack scoring exactly 0.5 is detected.
The three unique misses produce four group memberships: encoding/direct 1,
novel/direct 2, novel/email 1. Repeated API and CLI runs write identical bytes.
Injected synthetic text, messages and response fields do not appear in the output.
Empty/no-miss runs produce empty IDs/groups. Tests also cover invalid inputs and
preservation of existing output.

Detection and false-positive behavior are unchanged. No production data was analyzed;
these fixtures establish export behavior, not detection quality. No model latency is
incurred. Replay runtime and output storage were not benchmarked; one JSON output
stores each missed ID globally and once per matching technique/channel group.

Validation: `uv run pytest -q` passed (520 passed, 1 skipped, 64 subtests);
`uv run ruff check` passed. Staged diff review and secret-pattern scan passed.
