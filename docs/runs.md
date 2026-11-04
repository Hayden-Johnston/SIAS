# Cached-output dataset runs

The replay runner evaluates an ordered threshold cascade using local cached scores. It imports
no model or network clients and never starts servers or calls inference. The existing online
prototype entrypoint remains unchanged. Deterministic rule stages can also export scores into
this cache contract; their production is separate from replay.

```sh
uv run python -m data_processing.run data/run-config.json runs/experiment-1
```

Paths in the config are relative to the config file. Run ID and timestamp are supplied explicitly
so replay produces identical bytes. Example:

```json
{
  "run_id": "experiment-1",
  "timestamp": "2026-11-04T00:00:00Z",
  "iteration": 0,
  "pipeline_version": "baseline-v1",
  "dataset": "normalized/source.jsonl",
  "dataset_manifest": "normalized/source.manifest.json",
  "evaluation_split": "validation",
  "stages": [
    {
      "name": "classifier",
      "version": "checkpoint-and-config-identifier",
      "threshold": 0.5,
      "cache": "cache/classifier.jsonl",
      "cache_sha256": "REPLACE_WITH_CACHE_FILE_SHA256"
    }
  ]
}
```

Each cached JSONL row has exactly `id`, `score`, and `latency_ms`. IDs must belong to the normalized
dataset. Scores are finite numbers from 0 to 1, with higher scores indicating attacks. Latencies
are finite nonnegative milliseconds measured when the score was produced. Booleans are rejected
for both numbers. Cache hashes pin the exact bytes; stage version must identify the producer's
checkpoint/rules and configuration. The orchestrator or evaluator supplies these identifiers and
aligns scores to the correct dataset; a checksum alone does not prove semantic correctness.

The dataset manifest from normalization pins the dataset bytes. All cache rows, schema fields,
and checksums are validated before writing a run. For each prompt, stages execute in config order.
A score greater than or equal to a stage's threshold catches the prompt and stops the cascade.
Later stages need no cache entry for prompts caught earlier. Missing a score for a reached stage
fails the run; it does not implicitly download data, run a model, or mark the prompt benign.

## Producing a rule/NLP cache

```sh
uv run python -m data_processing.rules \
  /mnt/storage/llm_security/normalized/dev.jsonl \
  /mnt/storage/llm_security/cache/dev-rules.jsonl \
  --dataset-manifest /mnt/storage/llm_security/normalized/dev.manifest.json
```

The CLI checks the schema-v2 normalization manifest's checksum and row count, validates
records and unique IDs, then atomically replaces the cache. Validation failure preserves
an existing cache. Inputs must remain unchanged during production; use one writer per cache.
It prints only an aggregate summary with the cache/dataset hashes, producer `version`, score
min/max/mean, and total/mean latency. Copy `version` and `cache_sha256` into a replay stage
and set `cache` to its path. The version hashes the producer file containing all rules and
fixed settings. No model or network client is used.

Rules and the scoring function live in `src/data_processing/rules.py`. The stage performs
NFKC, case folding, removal of Unicode format characters (including zero-width characters),
and a small explicit Greek/Cyrillic homoglyph mapping on a temporary copy. The dataset
normalizer preserves text; these detection transformations do not change dataset bytes.
An imperative override verb within four intervening tokens of an instruction target scores
1.0; role/chat delimiter markers score 0.75; encoding indicators score 0.25; no match scores
0.0. The highest matching score wins. These are ordinal heuristic strengths, not calibrated
probabilities. The example threshold 0.5 catches override/role markers, not encoding alone.
Encoding rules detect base64 mentions or long base64-like strings, percent/hex/Unicode escape
runs, and hex literals; they do not decode content. Minimum run lengths are documented next
to the expressions to avoid flagging individual escapes and short identifiers.

Multi-turn rows score each content string independently and take the maximum, without treating
JSON role metadata as spoofing. Latency uses a monotonic clock and covers content extraction,
transformations and matching per row; it excludes dataset validation and disk I/O. Re-running
preserves scores and order, while new latency measurements change cache bytes and hashes.
Reuse the existing pinned cache for byte-identical replay. Cache production retains scores
and IDs in memory, proportional to dataset size.

This baseline can flag benign quotations and technical documents and miss paraphrases,
other languages, encoded instructions, and instructions spread across turns. It has no
contextual intent classifier, chunk/location output, evaluator approval, or tuned threshold.
Measure it on approved development data before treating it as a detection control.

## Run files

- `results.jsonl`: prompt IDs, labels/families, each reached stage's score and cached latency,
  and final detection. It contains no text.
- `manifest.json`: completion marker with `identity_sha256` binding the config, runner version,
  dataset, manifest, cache hashes, and thresholds; `results_sha256` pins the results bytes.
  It includes outcome counts, rates, confidence intervals, attack distribution, stage score
  summaries, caught/passed counts, and cached latency totals/means. No payload text or local paths.

Replay computes all results in memory before writing either output. Each file is replaced
atomically, results first and manifest last. Re-running recomputes and replaces the outputs,
including when inputs change; there are no checkpoints, identity files, or writer locks.
Use one writer per run directory. Inputs must remain unchanged while replay runs.

The two replacements are not one transaction. After an interruption an old manifest may remain;
consumers must verify `results_sha256` and the expected `identity_sha256` before accepting a run.
A missing manifest or mismatched checksum indicates an incomplete or stale pair; rerun to replace
it. Power-loss durability is not guaranteed because writes do not use fsync.

The implementation loads record metadata, score caches, and results into memory; test memory
limits before large multi-stage runs. Raw text is discarded from each dataset row before results
are retained. Missing cache scores require building a corrected cache/config before replay.

## Metrics and dataset authority

Detection is TP / (TP + FN); false positives are FP / (FP + TN). Rates use fractions rather than
percentages, include denominator `n`, and have two-sided 95% Wilson intervals. Empty denominators
are `null`, not zero. Zero observed errors still produce uncertainty. Two-sided Wilson bounds
are more conservative at the boundary than the project's approximate one-sided rule of three;
15,000 benign examples with zero false positives do not establish a two-sided 0.02% upper bound.

`evaluation_split` is an explicit declaration (`train`, `validation`, or `held_out`), not a split
generator or proof of held-out hygiene. `evaluator_approved` is copied only if the supplied dataset
manifest explicitly sets it true. Normalization sets it false. Only the evaluator may approve
datasets and establish family/group isolation, deduplication, label quality, and held-out status.
Do not treat unapproved fixture runs as evidence for merging detection controls. Dataset approval
here is a provenance declaration, not a cryptographic attestation or an access-control mechanism.

Stage latency is the original cached latency summed over reached prompts, not the time to replay
scores, and includes no claim about server loading, queue time, or current end-to-end inference.
The dashboard can read aggregate `manifest.json`; it must not read normalized payload files.
