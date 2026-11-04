# Append-only activation index (ticket 0025)

Activation capture now keeps a small schema-version-2 `index.json` header/summary and
appends one canonical JSON record to `index.jsonl` after writing each shard. The header
is written only at start and finish. This removes the previous quadratic index write
volume while preserving CLI arguments, identity refusal, shard checksum validation,
deterministic sampling/output, and disk-limit stop/resume. The disk check now includes
the pending JSONL record as well as the shard. Removed the unused safetensors save import.

Each append uses one unbuffered append write followed by `fsync`. On process interruption,
resume discards an unterminated final record and recaptures that shard; malformed complete
records are refused. Old schema-version-1 indexes are converted once after validation.
The header reports `in_progress` during capture; resume uses JSONL records, not potentially
stale header counts. `index_sha256` covers both files via the SHA-256 of their canonical
JSON digest array. One writer per output directory is required.

## Measurement

CPU capture using `hf-internal-testing/tiny-random-LlamaForCausalLM`, 100 synthetic benign
prompts, IDs `benign-0000` through `benign-0099`, each containing the same short gardening
sentence (8 words), default layer step/dtype/token cap/seed and 5% per-token sampling.
No server or container was started. Temporary output was removed after measuring.

| Measurement | Bytes per prompt |
|---|---:|
| Shards, mean | 774.80 |
| JSONL records, mean | 608.00 |
| Total final storage, including 510-byte header | 1,387.90 |
| Total index bytes written, including start and finish headers | 618.21 |
| Previous implementation's reconstructed index bytes written | 32,558.13 |

All 100 appended records measured exactly 608 bytes. Header writes totaled 1,021 bytes.
The previous write volume was reconstructed from the same records using the old combined
index format after each shard and once at completion: about 52.7 times the new volume.
Capture took 4.9126 seconds including cached model/tokenizer load; this is a single CPU
run, not a latency comparison. Storage and append size depend on IDs and metadata sizes,
not on the number of previously captured prompts. Detection and false-positive rates
are unaffected and were not measured.

## Validation and limits

Installed with `uv sync --extra activations`. `uv run pytest -q`: **157 passed, 1 skipped,
39 subtests passed**. `uv run ruff check`: **passed**. Activation tests run with the extra
installed, covering existing behavior plus constant actual bytes written across 1,000
appends, no per-shard header rewrites, interrupted append recovery, and legacy migration.

Resume still reads the index and validates every existing shard checksum, so resume time
and in-memory metadata remain linear in shard count. Atomic shard replacement retains the
existing implementation; power-loss durability of the entire directory is not guaranteed.
