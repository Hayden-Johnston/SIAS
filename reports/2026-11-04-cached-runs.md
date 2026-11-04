# Manifest-driven cached runs and metrics

## Change and reason

Added `src/data_processing/run.py`: a local replay command for ordered threshold cascades with
normalized dataset input, explicitly versioned/pinned score caches, a resumable per-prompt score
journal, and an aggregate completion manifest. Configuration supplies run identity and timestamp;
identical inputs replay byte-identically. No model clients, downloads, servers, or inference are
used. The existing online prototype and metrics entrypoints are unchanged.

Input hashes, schema, finite score/latency ranges, IDs, and stage names are validated. A checkpoint
identity rejects changed config/data/caches; complete journal entries must match pinned inputs.
Only an incomplete final line is removed after interruption. An OS advisory lock prevents multiple
writers. Missing reached-stage scores fail without producing a complete manifest.

Per-stage scores live in the journal linked/checksummed by the manifest. Stage aggregates include
score min/max/mean, caught/passed counts, reached samples, and original cached latency. Overall
metrics record TP/FP/FN/TN, detection/false-positive rates, sample counts, two-sided 95% Wilson
intervals, and attack-family distribution. Empty denominators are null. Zero observed errors do
not become claims of certainty. Dataset approval is explicit provenance, never inferred from runs.

## Verification and measured effect

`PYTHONPATH=src python3 -m unittest discover -s tests -v`: 29 synthetic-fixture tests pass across
normalization and runs. Run tests cover cascade outcomes, inclusive thresholds, stage latency,
deterministic replay, interruption recovery, checkpoint corruption, changed input/config refusal,
missing/invalid/duplicate scores, writer exclusion, output/input collisions, CLI output, and
known Wilson interval values and zero-error bounds. `git diff --check` passes.

One local replay of 10,000 generated records took 0.282455 seconds; validating/replaying the
completed run took 0.244746 seconds. Journal size was 1,483,890 bytes; aggregate manifest was 994
bytes. Measurements use `time.perf_counter` around replay, excluding fixture generation and
normalization. Fixtures used alternating labels `i % 2`, IDs `fixture-{i}`, groups `group-{i}`,
text `Synthetic fixture {i}`, source/label source `synthetic`, family `fixture` for label 1 and
`benign` otherwise, variant `plain`, license `CC0-1.0`, publication `no`, timestamp
`2026-11-04T00:00:00Z`. Cached scores were 0.9 for label 1, 0.1 otherwise; latency was 2 ms.
Run ID `synthetic-benchmark`, pipeline/stage version `fixture-v1`, stage name `fixture`, threshold
0.5, iteration 0, evaluation split `validation`. This measures orchestration only; these synthetic
scores are not model detection evidence. All fixture files were temporary and removed.

Real attack detection, false positives, and inference latency: not measured. No held-out evaluation
or control change has been merged. No raw corpus was inspected, and no servers were changed.

## Limits and integration

Requires Linux advisory locks. Journals flush per row but do not fsync per row, so process
interruption is supported without a power-loss durability guarantee. Memory scales with dataset
metadata and stage caches. Replay verifies completed work and is not constant time. Dataset split,
approval, and producer version fields are declarations requiring evaluator/orchestrator authority;
hashes detect byte changes, not incorrect provenance. Readers must validate manifest identity and
result checksum. Cached latency excludes server load and queue time.

Usage and exact file contracts are in `docs/runs.md`. Work is on `codex` in
`/tmp/llm-security-codex` for owner review/merge, following the dataset-normalization commit.
The dashboard should consume only aggregate manifests. Evaluator hygiene and inference/cache
production remain separate owners/stages.
