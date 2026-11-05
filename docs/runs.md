# Cached-output dataset runs

The replay runner evaluates independent stages and max fusion using local cached scores. It imports
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
and checksums are validated before writing a run. For each prompt, all stages are evaluated in config order.
Each stage uses its own threshold for independent metrics. Max fusion uses a separate threshold
(default 0.5) and optional weights; see [fusion settings](pipeline.md#replay-stage-fusion).
Every stage needs scores for every prompt. Missing a score
fails the run; it does not implicitly download data, run a model, or mark the prompt benign.

## Chunk caches and location

A stage may add both `"chunk_chars": 4096` and `"overlap_chars": 512` (example sizes,
not tuned defaults). Both must be integers with `chunk_chars > overlap_chars >= 0`.
Omitting both keeps the existing row-cache contract, including rule/NLP caches.
A chunk stage instead requires exactly `id`, `turn`, `start`, `score`, `latency_ms` per
cache entry. Coordinates are Python Unicode character offsets into the original turn;
non-multi-turn rows use turn 0. Chunk ends are derived, not stored in the cache.

Each turn advances by `chunk_chars - overlap_chars`, with the final window aligned to
the turn end, without duplicate starts. A short or empty turn has one window at start 0.
No chunk crosses turns. Every chunk of a row must have a score, even if an early
chunk exceeds the threshold. Unknown coordinates and duplicate keys fail validation.
All stages need complete caches. The row's stage score
is its maximum chunk score; stage latency sums all that row's chunk latencies.
Single-chunk scores therefore preserve the existing row detection metrics.

Results include channel and length bucket, plus each chunk stage's `best_chunk`
`[turn, start, end]`, `located`, and `spans_longer_than_overlap`. Tied scores select the
first chunk in turn/start order, independent of cache line order. `located` is true when
the best chunk intersects any known span, even below the detection threshold. It is null
for benign rows and attacks with unknown spans. Text, turn lengths and source spans are
not written to results.

Each chunk stage in the manifest records both window settings, location rates overall,
`by_channel` and `by_length_bucket`, and a count of spans longer than its overlap. These
statistics cover **all rows**; the location denominator is attack rows with
non-null spans (including an empty known list, which cannot be located). Each rate uses
the same Wilson interval and sample size contract as detection. Only observed location
groups are included. Row-cache stages have no location statistics. Location is reported
per stage so scores from different classifiers are never compared.

Length buckets are `0-4096`, `4097-16384`, and `16385+` Unicode characters: fixed short,
medium and long bands at 4 Ki and 16 Ki characters, independent of stage window sizes.
For multi-turn rows, length sums message content lengths and excludes JSON/role metadata.
The manifest identity binds window configuration and runner version 3. Replay still uses
only supplied caches and never performs inference.

## Producing a rule/NLP cache

```sh
uv run python -m data_processing.rules \
  data/normalized/dev.jsonl \
  data/cache/dev-rules.jsonl \
  --dataset-manifest data/normalized/dev.manifest.json
```

The CLI checks the schema-v2 normalization manifest's checksum and row count, validates
records and unique IDs, then atomically replaces the cache. Validation failure preserves
an existing cache. Inputs must remain unchanged during production; use one writer per cache.
It prints only an aggregate summary with the cache/dataset hashes, producer `version`, score
min/max/mean, and total/mean latency. Copy `version` and `cache_sha256` into a replay stage
and set `cache` to its path. The version hashes the producer file containing all rules and
fixed settings. Window sizes are pinned separately in the replay stage configuration.
No model or network client is used.

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
and IDs in memory, proportional to cache entries and dataset row count.

For chunk/location output, pass both `--chunk-chars 4096 --overlap-chars 512` (example sizes)
and add the same settings to the replay stage. These are optional, with no implicit defaults;
omitting both preserves the row-cache schema and callers. Chunk output uses the existing
`id`, `turn`, `start`, `score`, `latency_ms` contract and the runner's end-aligned windows.
Each chunk is sliced in original Unicode coordinates before scoring transformations. The CLI
summary's `records` counts dataset rows; `entries` counts cache entries. Score and latency
summaries describe entries. Chunk latency measures slicing and scoring, excluding turn extraction.
There are no entries for an empty multi-turn conversation. The producer hash changes when
the implementation changes; cache field names and runner version remain compatible.

This stage can flag benign quotations and technical documents and miss paraphrases,
other languages, encoded instructions, and instructions spread across turns. It has no
contextual intent classifier, evaluator approval, or tuned threshold.
Measure it on approved development data before treating it as a detection control.

## Run files

- `results.jsonl`: prompt IDs, labels/families, each stage's score and cached latency,
  the `fused_score`, and final fused detection. It contains no text.
- `manifest.json`: completion marker with `identity_sha256` binding the config, runner version,
  dataset, manifest, cache hashes, thresholds, and chunk settings; `results_sha256` pins the results bytes.
  It includes outcome counts, rates, confidence intervals, attack distribution, stage score
  summaries, independent per-stage and fused metrics, fusion settings, caught/passed counts,
  and cached latency totals/means. No payload text or local paths.

Replay computes all results in memory before writing either output. Each file is replaced
atomically, results first and manifest last. Re-running recomputes and replaces the outputs,
including when inputs change; there are no checkpoints, identity files, or writer locks.
Use one writer per run directory. Inputs must remain unchanged while replay runs.

The two replacements are not one transaction. After an interruption an old manifest may remain;
consumers must verify `results_sha256` and the expected `identity_sha256` before accepting a run.
A missing manifest or mismatched checksum indicates an incomplete or stale pair; rerun to replace
it. Power-loss durability is not guaranteed because writes do not use fsync.

The implementation loads record metadata, score caches, and results into memory; test memory
limits before large multi-stage runs. Only turn lengths and span coordinates are retained from
each dataset row; payload text is discarded before scoring. Missing cache scores require building a corrected cache/config before replay.

## Metrics and dataset authority

Run manifests include `slices.by_channel`, `by_length_bucket`, `by_technique` and
`by_attack_family` for fused verdicts. Each observed slice has confusion counts, detection and
false-positive rates with 95% Wilson intervals and denominator `n`, plus total row count `n`
and `small_sample: true` when that count is below 20. Undefined rates stay null.
Multi-technique rows contribute once to each matching technique; slice counts overlap.
Benign rows have empty technique lists and contribute no technique slice, so technique
false-positive rates are undefined. Empty datasets have empty slice maps.
Dashboard Metrics shows these aggregates for a selected run; older manifests remain readable
with no slices. Replay runner version 4 pins the added metadata and metrics in run identity.

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

Stage latency is the original cached latency summed over all prompts (all chunks for chunk
stages), not the time to replay scores, and includes no claim about server loading, queue time, or current end-to-end inference.
The dashboard can read aggregate `manifest.json`; it must not read normalized payload files.

## Scheduled iteration stage counts

`ops/iterate.py` writes four independent runs per iteration: `validation-rules`,
`validation-maya`, `held_out-rules`, and `held_out-maya` (prefixed with the iteration number).
Rules cover every row of each split; Maya covers only the first `sample_cap` rows ordered by
SHA-256 of row ID. The cap must be 1–25 per split, so classification uses at most 50 prompts
per iteration. Optional red-team generation has its own configured budget.
Each manifest's `records`, stage `reached`, rates and intervals describe its own dataset.
These runs compare stages independently; they do not estimate a combined cascade's performance.
Dashboard Metrics reads all four manifests without reading payloads.

Completed rule caches and model responses are reused after interruption. Identical completed
iterations return their checkpoint without inference or rewriting measured latencies. The generic
replay runner remains inference-free and needs no changes for these single-stage runs.
