# Offline activation logistic probe (ticket 0052)

Added `data_processing.probe` to train a deterministic CPU logistic-regression probe from
schema-v2 activation shards and export the existing row-stage replay cache. No inference,
capture, server operations, new dependencies or runner changes are needed. The activation
extra supplies NumPy, PyTorch and safetensors.

The scoring JSONL's sibling `dev.jsonl` supplies training IDs/labels; the split manifest pins
its checksum and count. Other scoring labels never enter training. Shard checksums and
model/tokenizer/layer/dtype identities are checked against both the index and tensor metadata.
Missing IDs fail before cache replacement. Incomplete final index appends are uncommitted,
as in capture resume. Schema-v1 combined indexes must first be migrated by the capture workflow.

Training uses dev-only standardization, zero initialization, 2,000 full-batch gradient updates,
a curvature-bounded step and L2 coefficient penalty 0.01. These are explicit baseline settings.
The printed version hashes weights, preprocessing, selected layer, identity, producer and dev
checksum. Caches contain only IDs, scores and zero latency placeholders. Save the CLI summary
for provenance. Numerical reproducibility is within the same dependency/platform environment;
there is no stochastic sampling. Replay requires only the exported cache.

## Measured effect and limits

Synthetic fixture: four dev vectors, two disjoint scoring vectors, two features at layer 3
of a two-layer shard. Scores were 0.0002654091 and 0.9997345909; replay at threshold 0.5
had TP=1, TN=1, FP=0, FN=0. Detection 1/1 and false positives 0/1 are synthetic correctness
checks, with no evidence of real-world detection quality or generalization. No approved
held-out dataset was evaluated and no quality improvement is claimed.

One local warm-import training/export took 0.0406 seconds and produced a 108-byte cache.
This tiny-fixture observation is not a production latency benchmark. Cached latency is
explicitly unmeasured (zero), excludes capture/training, and must not be interpreted as speed.
Storage grows by one row per scoring ID; existing shards are untouched. Memory retains the
selected training/scoring vectors and the training matrix.

Tests cover deterministic API/CLI output, replay integration, scoring-label independence,
identity and checksum rejection, missing training/scoring IDs, layer-sensitive versions,
dev manifest validation, input overwrite protection, and partial append handling.

Validation: `uv run pytest -q` passed (410 passed, 1 skipped, 64 subtests);
`uv run ruff check` passed. All new probe tests use synthetic tensors.
