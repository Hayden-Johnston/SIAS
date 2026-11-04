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
This uses the existing optional chunk-stage contract without adding inference to the runner or
changing `ops/iterate.py`. Replay needs only the exported score cache and dataset/config; it
reports detection, false positives and location with sample sizes and 95% Wilson intervals.
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
