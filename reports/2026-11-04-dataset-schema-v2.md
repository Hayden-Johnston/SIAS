# Dataset schema version 2

Ticket 0009 implements channel, technique and location metadata in the local normalizer.
The fixed vocabularies live in the module. Techniques are validated as unique and sorted on output;
obfuscated attacks require encoding. Multi-turn JSON messages and Unicode character spans are
validated, including turn bounds, ordering, overlap and rejection of boolean offsets. Benign rows
require empty techniques and spans. Mapping adapters support the new fields and null span defaults.

Normalized manifests now declare schema version 2 and count rows by channel and technique (one row
can contribute to multiple technique counts). The replay reader requires version 2; version 1
records receive an explicit rejection. Documentation and its benign mapping example now reflect v2.

Validation: `uv run pytest -q` passed 50 tests and 39 subtests; `uv run ruff check` passed.
Synthetic direct and multi-turn normalization replays produce byte-identical JSONL and manifests.
The multi-turn fixture contributes one multi_turn channel count and one count each for encoding
and roleplay, with three valid spans across two user turns. Tests also cover malformed metadata,
version 1 rejection, null span defaults, and cached scoring replay with v2 datasets.

No real corpus or model was used. Detection, false positives and inference latency were not measured;
scoring behavior is unchanged. Output storage increases by the three per-row metadata fields and two
manifest count objects; corpus storage and normalization performance were not benchmarked.
