# Deterministic family-based split assignment

## Change and reason

Added `src/data_processing/split.py` to assign normalized v2 rows to train/dev/test/heldout splits.
Attack rows are split by `attack_family`; benign rows by `group_id`. Assignment is deterministic via
SHA-256 of the name, so adding data never moves existing rows. Held-out attack families are listed
explicitly in a small JSON config. A `group_id` that spans multiple families is an error.

Outputs are one JSONL per split plus a manifest with per-split counts by label, channel, technique,
and family. The manifest contains no text. The command verifies the input checksum against the
normalizer manifest before proceeding.

Near-duplicate deduplication is out of scope for this command; it is a separate step.

## Validation and measured effect

`uv run pytest -q`: 64 tests pass (12 new split tests). `uv run ruff check`: clean.

Test coverage includes: held-out family assignment, group integrity (all variants in the same
family/group share a split), stability when rows are appended (no existing row moves), byte-identical
replay, checksum verification, manifest content (no text, correct counts), empty input, config
validation, and proportion distribution.

No model, network, or dataset download was used. No detection, false-positive, or latency
measurement applies; this is dataset infrastructure.

## Integration

Branch `pi`, based on `origin/master`. No model server was started, stopped, or configured.
No raw corpus was inspected. `docs/datasets.md` updated with the split command and CLI.
