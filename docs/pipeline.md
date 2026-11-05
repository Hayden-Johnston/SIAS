# Pipeline, metrics, Phase 3

## Target

**99.999% attack detection with under 0.02% false positives.** Not expected at first. First goal: hit
these numbers consistently on the held-out set. Then improve each iteration, add detection of novel
attacks, and reduce rules where better classifier weights allow.

## Stages (order decided by measurement, not assumption)

normalize (unicode, homoglyphs, zero-width, common encodings) -> NLP and regex -> activation probe ->
system one models (Clef, Laya, Mica, d1, plus decision models found in the inventory).
Jev is out of scope until later.

- NLP is expected to matter more than regex. Use both to avoid extra inference passes.
- Decide how a long prompt or context is broken down so attacks can be located.
- Log per-stage scores in the run manifest.
- A control change merges only if held-out detection improves and false positives stay low.

## CPU model score cache

`data_processing.model_stage` classifies original-text chunks using an already running CPU
llama.cpp OpenAI-compatible endpoint. The operator must select a non-GLM checkpoint with at most
4 billion parameters and ensure the server uses CPU only. Model ID and declared parameter count
are validated locally; they do not prove the server's weights or device placement. No server
is started, stopped or reconfigured. Loopback HTTP endpoints ending in `/v1` are required;
port 8099 is refused. There is no fallback to Maya.

Create a local config (for example, `data/model-stage.json`):

```json
{
  "model": "PINNED_NON_GLM_CHECKPOINT_ID",
  "parameter_count": 2000000000,
  "base_url": "http://localhost:8081/v1",
  "chunk_chars": 4096,
  "overlap_chars": 512
}
```

These window sizes are examples, not tuned defaults. Use the exact checkpoint ID served by the
operator, and a window size that fits its context including the classifier instruction and chat
template. Requests use temperature 0, an eight-token output budget, and disabled thinking via
`chat_template_kwargs.enable_thinking`. Only an exact stripped `0` (benign) or `1` (attack)
is accepted. Scores are binary judgments, not calibrated probabilities. Oversized inputs are not
truncated; server errors and invalid output fail cache export.

`MODEL_STAGE_URL` from the environment or `.env` overrides `base_url`; `base_url` may be omitted
when that variable is set. `MODEL_STAGE_API_KEY` supplies optional authentication. Environment
variables take precedence over `.env`. `--env-file` selects a different dotenv file. Maya settings
and credentials are never used for the explicit classifier endpoint.

```sh
uv run python -m data_processing.model_stage data/dev.jsonl caches/dev-model.jsonl \
  --dataset-manifest data/dev.manifest.json --config data/model-stage.json \
  --queue caches/dev-model.sqlite

# Export the same scores and measured latencies without inference; a missing response fails.
uv run python -m data_processing.model_stage data/dev.jsonl caches/dev-model.jsonl \
  --dataset-manifest data/dev.manifest.json --config data/model-stage.json \
  --queue caches/dev-model.sqlite --replay-only
```

Dataset schema, manifest checksum/count and unique IDs are checked before inference. Each turn
uses the runner's end-aligned windows; chunks never cross turns. Empty turns get one chunk;
empty conversations get none. JSON role metadata is excluded. The persistent queue hashes the
checkpoint, classifier instruction, chunk text and generation settings, reusing identical chunks
across rows/positions. Completed responses resume without another request; an interrupted HTTP
call can repeat. Use one writer and a dedicated queue for each endpoint/workload. Its request and
response text must stay local and outside git. No payload text is printed or exported into score
caches. Export replaces the output atomically only after every required response is valid.

The CLI prints an aggregate summary with `version`, `cache_sha256`, record/entry counts, window
settings, score min/max/mean and cached latency totals/means. Add an optional stage to the
`stages` list in your existing [run config](runs.md), using the returned version/hash:

```json
{
  "name": "cpu-classifier",
  "version": "REPLACE_WITH_RETURNED_VERSION",
  "threshold": 0.5,
  "cache": "../caches/dev-model.jsonl",
  "cache_sha256": "REPLACE_WITH_RETURNED_CACHE_SHA256",
  "chunk_chars": 4096,
  "overlap_chars": 512
}
```

Then run `uv run python -m data_processing.run data/run-config.json runs/cpu-model`.
This uses the existing optional chunk-stage contract without adding inference to the runner.
For iteration fusion, use the optional `cpu_classifier` settings documented below. Replay needs
only the exported score cache and dataset/config; it reports detection, false positives and
location with sample sizes and 95% Wilson intervals.
The stage version pins producer code, checkpoint, declared size, instruction and generation
settings; windows are pinned in the run config. Changing weights behind a served alias cannot be
detected: use checkpoint-specific IDs. Reusing cached requests preserves original HTTP latency
(including retries, excluding backoff); identical chunks reuse that latency at every position.
This is not replay latency or a new end-to-end CPU benchmark.

The shared queue retries transport errors, 429 and 5xx responses up to three attempts per drain.
Permanent HTTP errors, malformed responses and explicit refusals are persisted failures and stop
the drain; a subsequent invocation stops before more inference if a required request has failed.
Invalid classifier labels also prevent export and remain cached for operator review. A complete
cache replays without inference, including when the endpoint is offline. Detection quality and
false positives still require measurement on approved held-out data; synthetic tests establish
cache/replay behavior only.

## Replay stage fusion

The replay runner evaluates all configured stages on every row, without inference. Each row's
`fused_score` is `max(weight[name] * stage_score)`; weights default to 1 and must be finite
numbers in [0, 1]. Chunk stages first take their maximum chunk score. Fusion flags scores
**greater than or equal to** its threshold (default 0.5). These scores are heuristic strengths,
not calibrated probabilities. Optional settings go in the existing run JSON config:

```json
"fusion": {"threshold": 0.5, "weights": {"cpu-classifier": 0.8}}
```

Only configured stage names may appear in `weights`; omitted names keep weight 1. Each stage's
existing `threshold` controls its independent verdict and metrics, without changing its raw score
or the fusion threshold. Set stage thresholds in the `stages` array. A zero weight contributes
zero, so a fusion threshold of zero flags every row, including rows with only zero scores.

The manifest records each stage's `metrics` and `fusion.metrics`, with confusion counts,
detection and false-positive rates, denominators and 95% Wilson intervals. Top-level `metrics`
are the fused metrics. `evaluation_split: "held_out"` declares these as held-out results; the
runner also supports train and validation runs and does not establish split hygiene or approval.
Use approved held-out data to measure detection improvements; synthetic tests prove replay
behavior only. Fusion settings are pinned in the run identity (runner version 5).

Every stage now requires a complete cache for the supplied dataset, including rows caught by
another stage. Missing scores fail before output replacement; no model calls fill gaps. Older
sparse cascade caches must be completed separately before replay. `reached`, score summaries,
chunk location and cached latency now cover all rows; latency sums describe cached stage work,
not an early-exit cascade or replay runtime. An empty conversation has no chunks, stage score 0,
zero cached latency and null location. Fusion never compares chunk coordinates across stages.

## Replay-only fusion weight sweep

```sh
uv run python -m data_processing.sweep data/dev-run.json data/heldout-run.json \
  --fpr-cap 0.0002 --output runs/fusion-sweep.json
```

Supply normal run configs with multiple stages: dev uses `evaluation_split: "validation"`,
held-out uses `"held_out"`. Stage names, versions, thresholds and chunk settings must match,
as must the fusion threshold (default 0.5); cache paths/checksums differ by split. Existing
fusion weights are ignored. Complete caches are required, with no inference or server operations.

The script tries `{0, 0.5, 1}` per stage on dev only, maximizing observed detection subject to
observed FPR <= `--fpr-cap` (a fraction, not a percentage or CI upper bound). Ties prefer the
lowest total weight, then lexicographically lower weights in sorted stage-name order. Dev must
contain attacks and benign rows; no feasible choice fails without replacing output. Grid size
is `3 ** stage_count`, so keep the stage count small.

Only after selection does it read held-out inputs and evaluate the chosen weights once, plus an
all-ones baseline. Printed JSON and optional atomic output contain dev weights/metrics, input
identities, approval flags, held-out confusion counts/rates with 95% Wilson intervals, and rate
deltas (chosen minus all-ones). Undefined held-out rates and deltas are null. Repeated identical
inputs produce identical output. Split declarations do not prove family/group separation: use
properly separated, approved splits, and do not tune by repeatedly inspecting held-out results.

## Held-out miss analysis

```sh
uv run python -m data_processing.misses runs/heldout/manifest.json runs/heldout/misses.json
```

This replay-only script reads a complete `held_out` run manifest and its sibling
`results.jsonl`, verifying the results checksum and record count before writing. It needs
no dataset, model, network or server operations. Misses are attack rows whose cached
`fused_score` is strictly below the manifest's fusion threshold; equality is detected.
Weights and chunk maxima are already reflected in that score.

The atomic JSON output and printed JSON contain sorted missed `ids`, unique total
`missed`, `attacks` and `records` counts, and `groups` of `{technique, channel, count, ids}`.
Multi-technique misses appear in each matching group, so group counts can overlap;
misses with no techniques appear only in the global IDs/count. Output copies no payload
text, messages, model responses or paths. Manifest/results checksums, threshold and the
evaluator approval flag record provenance. Identical inputs produce identical bytes;
invalid inputs preserve an existing output. Use one writer with frozen run inputs.

The held-out declaration and approval flag are inherited, not independently verified.
IDs describe only rows scored by that run, which may be a capped sample. Use this for
reporting gaps; repeatedly tuning against these IDs compromises held-out measurement.

## Statistics

Report confidence intervals and sample sizes with every rate, and state the attack distribution the
numbers apply to. Rule of thumb: claiming a 0.02% false-positive rate at 95% confidence needs about
15,000 benign held-out prompts with no false positives; 99.999% detection needs about 300,000 attacks
with no misses.

## Phase 3 (not before the pipeline is good)

Weight-space programming and fine-tuning, using Phase 1 activation data, to potentially consolidate
the rule set. Order: probes, activation steering, weight edits. Judge every edit by the same held-out
metrics. Treat downloaded checkpoints as untrusted.

## Optional iteration red team

`ops/iterate.py` accepts the optional `red_team` settings in `iterate.example.json` (default off).
Before source splitting, it generates capped taxonomy triples and hard negatives via the cached
Maya client at concurrency 1, then calls the existing CPU llama.cpp evaluator. Only agreeing rows
with `label_source: evaluator` are appended to the normalized data. Generated rows also have a
separate `generated/` split directory; both datasets use `split.py` family/group assignments, so
variants stay together and held-out families remain held out. Source labels remain unapproved.

The dated iteration report and completion manifest include generated/approved counts and approval
rate. These measure evaluator agreement, not detection improvement. Generation cache misses in
`replay_only` mode and Maya transport failures are checkpointed skips; refusals fail the iteration.
Completed rounds resume without regeneration or reevaluation. Generation replay-only mode does not
disable inference in other stages. No Maya lifecycle operations are performed.

## Offline activation probe cache

With `uv sync --extra activations`, train a CPU NumPy logistic probe without inference:

```sh
uv run python -m data_processing.probe activations/index.json data/splits/heldout.jsonl \
  caches/heldout-probe.jsonl --layer 3 --train-split dev
```

`INDEX` accepts the capture's schema-v2 `index.json` or `index.jsonl`. `DATASET` is the
normalized JSONL to score; its directory must also contain `dev.jsonl` and the
`split_manifest.json` produced by `data_processing.split`. The dev checksum/count are verified;
only dev labels train the probe, and every training/scoring ID needs an activation. Missing IDs
fail export. Use a frozen index while training. All indexed shard checksums and model identity,
tokenizer version, layers and dtype must agree, including safetensors metadata. Only the selected
layer's `last_token` vectors are used; capture truncation still applies.

Training standardizes features using dev means/stds, then performs 2,000 full-batch logistic
updates with coefficient L2 penalty 0.01 and a curvature-bounded step. Zero initialization and
no sampling remove randomness; repeated runs in the same numerical environment reproduce cache
bytes. These are baseline settings, not tuned quality claims. Memory scales with the selected
training/scoring vectors. Test/heldout training is refused. A dataset scored on dev is an in-sample
measurement; detection and false positives need separate approved held-out evaluation.

The CLI prints an aggregate summary, including a version hashing learned weights, standardization,
layer, activation identity, producer code and dev checksum. Save it alongside the cache. The cache
contains only `id`, `score`, `latency_ms`; no text. Latency is zero as an explicitly unmeasured
placeholder, excluding capture and training. Put the returned `version` and `cache_sha256` into a
regular row stage in the [run config](runs.md), with `name: "activation-probe"`, a chosen threshold
(for example 0.5), and the cache path; omit chunk settings. Replay needs no activation shards,
ML extras or model server. Probe scores are not calibrated probabilities or location estimates.

## Optional iteration activation probe

Add `activation_probe` to the local `ops/iterate.py` config to include existing probe exports:

```json
"activation_probe": {
  "version": "REPLACE_WITH_PROBE_VERSION",
  "threshold": 0.5,
  "dev": {
    "cache": "caches/dev-probe.jsonl",
    "cache_sha256": "REPLACE_WITH_DEV_CACHE_SHA256"
  },
  "heldout": {
    "cache": "caches/heldout-probe.jsonl",
    "cache_sha256": "REPLACE_WITH_HELDOUT_CACHE_SHA256"
  }
}
```

Paths resolve relative to the iteration config. Use caches from the same frozen probe (the shared
`version`) for the exact scoring splits, including augmentation when enabled. Full-split caches
are filtered to the deterministic Maya sample; caches containing just those sampled IDs also work.
Every sampled ID needs a score. Present files with incorrect checksums, invalid sampled entries or
missing sampled scores fail; no scores are fabricated or inferred. Extra rows outside the sample
are ignored. Export caches separately with `data_processing.probe`; the iteration never captures
activations or trains a probe and needs no activation extras to replay.

Both files must exist to add `activation-probe`: dev weight selection and held-out evaluation
require identical stages. If the setting is omitted or either file is absent, fusion with the remaining stages
continues and the report says `probe: not available`. Configured cache contents and availability
participate in iteration identity, so adding a previously missing cache creates a new iteration.
The report and completion manifest name the fusion stages and record probe availability.
Fusion still uses the existing dev-only weight sweep and the same capped samples; full-split
rules metrics remain separate. Zero probe latency is unmeasured and excludes capture/training.
Probe training on dev makes dev probe metrics in-sample; this integration does not change that
limitation or establish held-out detection quality.

## Optional iteration CPU classifier

Add `cpu_classifier` to the local `ops/iterate.py` config to fuse existing
`data_processing.model_stage` exports:

```json
"cpu_classifier": {
  "version": "REPLACE_WITH_MODEL_STAGE_VERSION",
  "threshold": 0.5,
  "chunk_chars": 4096,
  "overlap_chars": 512,
  "dev": {
    "cache": "caches/dev-model.jsonl",
    "cache_sha256": "REPLACE_WITH_DEV_CACHE_SHA256"
  },
  "heldout": {
    "cache": "caches/heldout-model.jsonl",
    "cache_sha256": "REPLACE_WITH_HELDOUT_CACHE_SHA256"
  }
}
```

Use the returned shared version and exact window settings from the CPU model exports. Paths
resolve relative to the iteration config. Caches must cover the exact scoring splits (including
augmentation when enabled), or at least every chunk of every deterministic Maya sample row.
Full-split caches are filtered by sampled ID, retaining all chunks. Replay uses each row's maximum
chunk score and preserves cached latency and location metrics. Invalid sampled entries, missing
chunks or incorrect checksums fail; no scores are fabricated or inferred.

Both files must exist to include `cpu-classifier` in dev weight selection and held-out evaluation.
If the setting is omitted or either cache is absent, the report says `cpu-classifier: not available`
and fusion continues with rules, Maya and any available activation probe. Configured cache hashes
and availability participate in iteration identity; adding a missing cache creates a new iteration.
Reports name all fused stages, and the completion manifest records `cpu_classifier` availability.
The existing dev-only weight sweep and capped sample are unchanged. The iteration never calls the
CPU endpoint or starts a server; export caches separately. The existing Maya sample stage may
still need inference. Cached latency is original classifier work, not replay time or a new CPU
benchmark. This integration establishes no held-out detection quality by itself.
