# Dataset schema and local normalization

## Change and reason

Added a standard-library local JSONL normalizer under `src/data_processing/normalize.py` and
documented the schema and CLI in `docs/datasets.md`. A small field/default mapping is the source
adapter. Existing prototype online loading and model code are unchanged. The new command can run
without installing the project's model/network dependencies.

All required fields are explicit. Text is preserved; timezone stamps are canonicalized to UTC;
missing source IDs are derived deterministically from mapped records. Invalid records and duplicate
IDs fail without displaying payload values. Outputs are staged and replaced after validation;
an aggregate manifest with checksums is the completion marker. Evaluator approval remains false.
Expanded ignore rules for local data, environment variants, raw corpora, and activation files.

## Validation and measured effect

`PYTHONPATH=src python3 -m unittest discover -s tests -v`: 10 synthetic-fixture tests pass. Coverage
includes byte-identical replay, source/output checksums, exact Unicode/line-ending preservation,
mapping and deterministic IDs, schema validation, duplicate IDs, UTF-8/JSON failure, existing-output
preservation on validation failures, and CLI diagnostics without input text.

A single local run over 10,000 generated benign fixture records took 0.272287 seconds using
`time.perf_counter`, producing 2,646,670 bytes of JSONL and a 452-byte manifest. The fixture assigned
`fixture-{i}` IDs, `group-{i}` groups, text `Synthetic benign fixture {i}`, label 0, label source/source
`synthetic`, family `benign`, variant `plain`, license `CC0-1.0`, publication `no`, timestamp
`2026-11-04T00:00:00Z`, for i from 0 through 9,999. Input was written by `json.dumps` plus newline.
Timing covers normalization and output writes only; no model, network, or dataset download was used.
This is one local measurement, not a throughput guarantee.

Detection, false positives, and inference latency: not measured. This is schema infrastructure,
not a control change or a claim against held-out detection targets. Fixture files were temporary
and removed. Memory scales with the ID set. Near-duplicate resolution, evaluator approval,
family/group split enforcement, and held-out selection remain evaluator gates, not implemented
by this normalization command. A crash between the two atomic file replacements can leave an old
manifest; checksum verification and replay are required before downstream consumption.

## Integration

Work is based on prototype commit 41f3c80, branch `codex` in `/tmp/llm-security-codex`, because the
shared checkout's Git metadata is read-only in this session. Claude may fetch that local branch
and review/merge. No model server was started, stopped, or configured. No raw corpus was inspected.
