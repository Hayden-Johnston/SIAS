# SIAS: self-improving agentic security

**Layered prompt-injection and jailbreak detection for local models, measured by an automated red team.**

SIAS is *self-improving* in two ways. A red team of local models keeps generating new attacks, and
the defenses are re-scored against them every iteration. Development itself is also agentic: AI agents
plan, build and review most of the changes, and every change is held to the same held-out metrics.

Prompt injection is the top risk in the OWASP Top 10 for LLM applications. A successful injection
puts agentic systems at risk of data exposure and unwanted actions. This project builds a
drop-in detection pipeline for local inference (llama.cpp, ollama, Hugging Face): cheap,
deterministic rules first, then activation probes and small classifier models. A red-team loop
keeps generating new attacks to test it.

| | |
|---|---|
| **Target** | 99.999% attack detection with under 0.02% false positives on a held-out set |
| **Scope** | Prompt-level attacks only: no malware, exploit code or anything beyond prompts |
| **Runs on** | One local rig (AMD GPUs, ROCm). No cloud inference in the pipeline |
| **Status** | Phase 1 infrastructure. Scheduled full-split rules and sampled model scoring available |

![SIAS architecture: orchestrator agents direct a red team of open-weight models that builds prompt-injection and jailbreak datasets, which iteratively improve the security controls](docs/images/architecture.png)

## What it detects

Attacks are described along two independent axes so the results show exactly where the gaps are.

- **Channel**: where the text reaches the model. Direct single-shot prompts, multi-turn chat,
  documents and other indirect content, email, tool and web output, code comments. Long context is
  measured separately as a length bucket within any channel.
- **Technique**: how the attack works. Instruction override, role-play and personas,
  encoding and obfuscation, delimiter spoofing, payload splitting, many-shot, named public
  jailbreaks, and novel attacks.

The benign set deliberately includes hard negatives, such as a security article that quotes an
attack. Full taxonomy and schema: [docs/datasets.md](docs/datasets.md).

## How it works

**Prompt or context → normalize** (unicode, homoglyphs, zero-width, encodings) **→ rules and NLP →
activation probe → system-one classifier models → verdict**

Each stage scores a prompt from 0 to 1. A prompt is flagged at the first stage whose score crosses
its threshold, so most traffic never reaches a model. Stage order is decided by measurement.
Long inputs are split into chunks so the pipeline can also report *where* an attack sits.
The CPU rule scorer exports row caches or optional chunk caches for location measurements
([usage](docs/runs.md)).
An optional CPU llama.cpp classifier exports the same chunk-cache format through an already
running local endpoint ([setup and replay](docs/pipeline.md#cpu-model-score-cache)).

Every run is **deterministic and replayable**. Model outputs are cached once. Scoring runs replay
those caches against a pinned dataset and write a manifest with counts, rates, confidence intervals,
per-stage latency, and chunk location rates. Replay evaluates every stage on every row and
reports independent stage metrics alongside max-fused detection and false positives; optional
weights and a fusion threshold live in the run JSON config. Complete stage caches are required
([fusion settings](docs/pipeline.md#replay-stage-fusion)). See [docs/runs.md](docs/runs.md).
Run manifests and dashboard Metrics also break down fused detection and false positives by
channel, length, technique and attack family, keeping small samples visible with a warning.

### The red-team loop

1. A local **generator** model (GLM) writes candidate attacks in plain, paraphrased and obfuscated forms.
2. An **evaluator** model from a different family labels the candidates and approves them into the dataset.
3. Reserved attack families go only to held-out; other attacks and benign groups are hash-split.
4. The **pipeline** is scored on it and the metrics go to the dashboard.
5. Agents change rules, thresholds or models, and the next iteration starts.

Reserved families never appear in train/dev/test. Other families can span splits, with variants of
one attack kept together by group. Held-out metrics mix familiar and novel families; per-family
metrics separate them. See the [split trade-off](docs/datasets.md#splits-and-hygiene).

## Measuring honestly

Every rate is reported with its sample size, a confidence interval, and the attack distribution it
applies to. The targets are deliberately strict. Claiming a 0.02% false-positive rate at 95%
confidence needs roughly 15,000 benign held-out prompts with no false positives. Claiming 99.999%
detection needs roughly 300,000 attacks with no misses. Until the dataset is that large, the
dashboard shows how far the evidence actually reaches. Details: [docs/pipeline.md](docs/pipeline.md).

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run pytest -q                      # tests
uv run ruff check                     # lint

# Normalize a local JSONL source into the shared schema (no network, no inference)
uv run python -m data_processing.normalize source.jsonl out.jsonl --manifest out.manifest.json

# Capture hidden-state activations (needs `uv sync --extra activations`; CPU, resumable)
# Writes per-prompt shards, an append-only index.jsonl, and an index.json summary
uv run python -m data_processing.activations out.jsonl activations/dev --dataset-manifest out.manifest.json

# Load an approved local snapshot (source names and selection rules: docs/datasets.md)
uv run python -m data_processing.sources deepset data/raw/train.parquet \
  --output data/normalized/deepset.jsonl --manifest data/normalized/deepset.manifest.json \
  --revision SNAPSHOT_COMMIT --timestamp 2026-11-04T00:00:00Z

# Replay a scored run from cached stage outputs
uv run python -m data_processing.run data/run-config.json runs/experiment-1

# Read-only inventory of GPUs, storage, model servers and models on disk
uv run python ops/inventory.py

# Dashboard (updates, blocker alerts, board, agent/server timelines and metrics; Pacific times) on http://localhost:8300
python3 dashboard/server.py --port 8300
```

Local settings live in files git ignores. Copy `config.example.json` to `config.local.json`
and put API keys in `.env`. Copy `servers.example.json` to `servers.local.json` and
set the local status URLs to enable five-minute server uptime sampling in dispatcher ticks.
The dashboard Activity page shows server up/down lanes alongside agent activity; no inference
or server lifecycle operations are performed. See [docs/dashboard.md](docs/dashboard.md).

### CPU evaluator lifecycle

The proxy/operator can manage one CPU llama.cpp evaluator with `ops/servers.py`.
Copy `evaluator.example.json` to gitignored `evaluator.local.json` and set the CPU
binary, non-GLM model, loopback host, port and storage directory. Relative paths resolve
from the config file. Linux with `/proc` and pidfd support is required.

```sh
python3 ops/servers.py up evaluator
python3 ops/servers.py status evaluator
python3 ops/servers.py down evaluator
# Each command also accepts --config /path/to/evaluator.local.json
```

Only the `evaluator` set is supported. GPU allocations are rejected (including protected
GPUs 2-6 and reserved GPUs 0-1), and port 8099 is always refused. The command fixes
`--device none` and zero GPU layers, hides GPU devices, and removes inherited
`LLAMA_ARG_*` overrides. It uses a 16,384-token context, four threads and one request
slot, matching the candidate evaluator. Use a trusted CPU llama-server binary.
Agents must leave lifecycle commands to the proxy/operator.

Repeated `up` reuses the recorded process. `down` sends SIGTERM only through a PID handle
after checking the recorded process start time and command; it never stops existing servers
by port, name or process group. PID records, a lock and append-only output log live under
`storage_dir`. A ten-second shutdown timeout retains the PID record for operator review.
`status` reports process existence, not HTTP health or model readiness; `up` only checks for
immediate launch failure. This standalone script does not change the candidate evaluator's
existing temporary child-server workflow or manage Maya.

### Queued model calls

`llm_proxy.Client` reads `MAYA_URL` (OpenAI API base URL ending in `/v1`) and
`MAYA_API_KEY` from `.env`, with environment variables taking precedence. It only sends chat
requests to an already running server by default. CPU evaluator startup is opt-in.

```python
from llm_proxy import Client

client = Client("caches/chat.sqlite")
keys = client.submit_batch(
    "served-model-id",
    [[{"role": "user", "content": "Say hello."}]],
    temperature=0, max_tokens=32,
)
client.drain()
output = client.result(keys[0])
```

Use one database per endpoint/routing configuration: drainers sharing it serialize HTTP
calls at concurrency 1.
Submission persists immediately; duplicate model, messages and generation parameters reuse the
same key. `drain()` processes pending jobs in submission order and returns the number completed.
`result(key)` returns status (`pending`, `done`, `failed`), response, attempts, error code and
cumulative HTTP latency in seconds (excluding backoff), or `None` for an unknown key.
Completed results replay without inference. Pin the model ID to the checkpoint when reusing a cache.

Transport errors, HTTP 429 and HTTP 5xx retry up to three attempts per drain with 1s then 2s
backoff; exhausted jobs remain pending for a later drain. Other HTTP errors, malformed responses
and explicit refusals are marked failed and raise `ProxyError`, stopping the drain without retrying
that job. A crash during an HTTP call can repeat that call on resume. Streaming is unsupported.
The database contains request and response text: keep it local and outside git.

From a source checkout, opt into evaluator routing with
`Client("caches/judge.sqlite", model_sets={"served-model-id": "evaluator"},
server_config="evaluator.local.json")`. The config defaults to the checkout's
`evaluator.local.json`, using the same format as `ops/servers.py`. Other models retain
the client's normal endpoint. Managed queues drain requests grouped by model, preserving
submission order within each group and processing groups in first-submitted order.
The proxy checks the evaluator's `/health`, calls `ops/servers.py up evaluator` once
per model per drain if needed, then waits up to the client timeout for readiness before
sending chat calls. Startup commands have the same timeout. Healthy and fully cached
queues need no startup. Evaluator requests never inherit Maya credentials.

Only the CPU `evaluator` set is startable; other sets, GPU allocations and port 8099
are refused. Configuration, startup and readiness errors fail every pending request for
that model with a `server_*` error and raise `ProxyError`; other models remain pending.
The proxy never shuts down a server or manages Maya's lifecycle.

### Scheduled iterations

Copy `iterate.example.json` to gitignored `iterate.local.json`. Set the ordered local snapshot
paths, pinned revisions/timestamps, held-out families, model checkpoint ID, sample cap and stage
thresholds. Then run:

```sh
uv run python ops/iterate.py                 # defaults to iterate.local.json
```

The iteration refreshes source loaders and family splits when inputs, configuration or producer
code change. Offline synthetic augmentation defaults on (`"augment": false` disables it): after
normalization and splitting, each split independently gains document, email, tool-output and
long-context attack/control pairs with fixed seed 0. Source families/groups and split assignments
are preserved; padding comes only from benign rows in that split. An attack-containing split
without benign rows fails. Added row counts per channel/split appear in the iteration completion
manifest and report; labels remain synthetic and unapproved.
Rules score every augmented dev (validation) and heldout row. The queued Maya classifier scores
only a deterministic hash-selected sample of each split: `sample_cap` is 1–25 per split, at most
50 classifier prompts per iteration. Each stage/split gets a separate numbered run manifest under
the configured data directory's `runs/`, visible in dashboard Metrics, and a dated report in
`reports/`. Rules retain full-split metrics; Maya and fused rules+Maya rates apply only to
the capped sample. Fusion reuses cached scores, selecting weights on the dev sample with the
existing `{0, 0.5, 1}` sweep at threshold 0.5 and observed `fusion_fpr_cap` (default 0.0002).
If dev lacks either class, fusion is reported unavailable. The report includes counts and 95%
Wilson intervals, technique slices, and held-out techniques absent from the full scoring dev
split (including augmentation). It states held-out detection/FPR deltas against the single stage
with highest detection on the same sample (ties: lower FPR, then name). This comparator is
descriptive; held-out never selects fusion weights. Small samples cannot establish the target FPR.
Labels are exploratory source labels (`evaluator_approved: false`); no model scores are fabricated
for unsampled rows. Full split counts and the cap are recorded in
`runs/.iterations/*/complete.json`.

Optional `activation_probe` settings add precomputed dev/heldout probe score caches to the same
sampled fusion ([configuration](docs/pipeline.md#optional-iteration-activation-probe)). Both caches
must exist; otherwise the report says `probe: not available` and fusion uses rules + Maya.
The iteration never captures activations or trains a probe. Reports name the stages fused.

An optional `red_team` section (see `iterate.example.json`) enables a capped generation and
CPU evaluator round before splitting. It defaults off. Set `enabled: true`, `groups` (each request
produces three variants and one hard negative), `max_tokens`, `carrier_chars`, `replay_only`,
and local evaluator `binary`/`inventory` paths, resolved relative to the config. Generation uses
the pinned `model`, safe seeds, cached Maya calls and batch/concurrency 1. Only evaluator-approved
rows (`label_source: evaluator`) join the normalized dataset; a separate `generated/` directory
keeps their train/dev/test/heldout splits under the iteration checkpoint, using the same family
assignment. Mixed source/generated run metrics remain `evaluator_approved: false`.

Maya transport failures or replay-only generation cache misses log a skip and continue with source
data. Skips are checkpointed for that iteration; changing config creates a new iteration. Refusals
and permanent failures stop the iteration. The round starts a CPU-only evaluator child when needed,
never manages Maya, and reports generated/approved counts and approval rate without payload text.
`replay_only` applies to generation; uncached evaluation and classifier stages still need inference.

Identical inputs/configuration/code reuse the iteration number and caches, including measured
latencies. Interrupted iterations resume checkpoints; completed model responses replay without
inference. Classification requires an exact `0` or `1`; missing/invalid scores fail the run.
Persisted failed requests stop before further inference and need operator review. Use a checkpoint
specific served model ID and bump `pipeline_version` when the underlying weights change. This
baseline classifies whole stored text; chunking and evaluator ingestion are
separate workflows.

The existing `ops/dispatch.py tick` launches a token-free `pipeline` worker at most every six hours
when `iterate.local.json` exists in the integration checkout. It uses the existing timeout/log/reap
mechanism, respects `board/STOP`, and never starts or stops a model server. The orchestrator owns
that local configuration. `--config` and `--data` override the script's config and storage root;
the dashboard must use the corresponding `--runs` directory. Local queue/cache files contain text
and stay outside git.

### Red-team candidate generation

Generate unapproved schema-v2 triples and one quoted-attack hard negative per group:

```sh
# Offline plan: no cache writes or inference
uv run python -m data_processing.generate --model PINNED_CHECKPOINT \
  --timestamp 2026-11-04T00:00:00Z --dry-run

# Use the same arguments without --dry-run to call the already running Maya server.
# --groups 50 --batch-size 1 --max-tokens 2048 are the small default request budget.
```

Outputs live under the storage root's `candidates/<run-id>/`: candidate JSONL and an aggregate
manifest with channel/technique counts and checksum. The command prints aggregates only.
`--output-dir` overrides the candidates root; keep it outside git. The dedicated cached queue
replays completed requests on resume. Each run has its own queue to keep draining within the
configured group budget. Use one generator process per output root.
Persisted failed requests stop for operator review; malformed output also stops without a completion
manifest. No model server lifecycle operations are performed.

The generator cycles deterministically through the schema's channel/technique product, then through
seeds. `--seeds` accepts a local JBB snapshot with a `Goal` column; without it, three benign-safe
marker/style/topic goals are used. There is no automatic download or snapshot discovery.
`--carrier-chars` defaults to 8192 benign characters on each side of indirect content, with known
insertion spans. Multi-turn candidates use a fixed benign exchange followed by the generated user
turn. Labels and techniques are generation requests, pending independent evaluator validation;
all candidates have `publishable: no` and `evaluator_approved: false`.

### Candidate evaluation

Evaluate a completed candidate file using the inventory's non-GLM Qwen3.5 2B Q4 checkpoint:

```sh
uv run python -m data_processing.evaluate candidates.jsonl --manifest candidate-manifest.json \
  --binary /path/to/cpu/llama-server
```

Use a current CPU llama.cpp build with Qwen3.5 support. The evaluator starts its own loopback
server only for pending requests, with GPU layers disabled and `--device none`, a 16,384-token
context, four CPU threads and one request at a time. Requests disable thinking in the chat template.
It stops that child after draining, including on errors. It never manages existing servers. Inputs exceeding the context fail without approval;
there is no truncation. The selected 1.22 GB checkpoint leaves room within the roughly 10 GB RAM
budget. `--inventory` selects a local inventory file.

Outputs live under the storage root's `evaluated/<run-id>/` (`--output-dir` overrides the root).
Only exact agreement on attack label, channel and technique set admits a row to `approved.jsonl`,
with `label_source: evaluator`. IDs, spans and publication declarations are preserved; evaluation
does not authorize publication. The completion manifest includes the approved dataset checksum,
approval rate and separate disagreement counts (a rejected row may disagree on multiple fields).
This is model agreement, not measured labeling accuracy or span validation.

The dedicated local queue caches every response. Replay uses pinned input, evaluator code, weights
and server binary hashes, and starts no server when all responses are cached. Interrupted runs
resume pending calls; failures/refusals stop for operator review. Malformed labels cannot produce
a completion manifest. Commands print aggregate manifests only; queue files contain text and must
stay outside git. Use one evaluator writer per output root.

## Repository layout

| Path | Contents |
|---|---|
| `src/data_processing/` | Dataset schema, normalization, activation capture, replayable scored runs, metrics |
| `src/llm_security/` | Detection pipeline and stages |
| `src/llm_proxy/` | Client and queue for local model servers |
| `dashboard/` | Read-only web dashboard (stdlib server, single page) |
| `ops/` | Board and agent dispatcher, rig inventory, service files |
| `docs/` | Design: datasets, pipeline, runs, infrastructure, dashboard |
| `reports/` | One dated report per change set: what changed, why, measured effect |
| `tests/` | Unit tests with synthetic fixtures |

## How this project is built

Development runs largely unattended, with a human owner setting direction.

- **Claude Code** is the architect and integrator. It writes tickets, reviews and verifies every
  change, and is the only agent that merges to `master`.
- **Codex** and **pi** implement tickets, each on its own branch in its own clone. pi runs a local
  27B model in a Docker sandbox, so mechanical work costs no subscription tokens.
- **Local models** do the bulk work: generating attacks, labeling and evaluating data, and
  classifying prompts. They also act as targets.
- A **kanban board** of ticket files and a cron-driven dispatcher
  ([ops/dispatch.py](ops/dispatch.py)) start the right agent when a ticket becomes ready. They send
  finished work to review and keep agent usage within plan limits.

Frontier agents never handle raw attack payloads. They work from manifests, counts and IDs. The
dashboard shows aggregates only. Agent instructions: [AGENTS.md](AGENTS.md).

## Datasets

Public sources approved so far. The dataset cards were checked on 2026-11-04 and the full decision
log is in [reports/2026-11-04-dataset-approvals.md](reports/2026-11-04-dataset-approvals.md).

| Dataset | License | Role |
|---|---|---|
| [deepset/prompt-injections](https://huggingface.co/datasets/deepset/prompt-injections) | Apache-2.0 | direct injections and benign |
| [jackhhao/jailbreak-classification](https://huggingface.co/datasets/jackhhao/jailbreak-classification) | Apache-2.0 | jailbreaks and benign |
| [TrustAIRLab/in-the-wild-jailbreak-prompts](https://huggingface.co/datasets/TrustAIRLab/in-the-wild-jailbreak-prompts) | MIT | named real-world jailbreaks |
| [Lakera/gandalf_ignore_instructions](https://huggingface.co/datasets/Lakera/gandalf_ignore_instructions) | MIT | direct overrides |
| [reshabhs/SPML_Chatbot_Prompt_Injection](https://huggingface.co/datasets/reshabhs/SPML_Chatbot_Prompt_Injection) | MIT | attacks on system-prompted chatbots |
| [microsoft/llmail-inject-challenge](https://huggingface.co/datasets/microsoft/llmail-inject-challenge) | MIT | email (indirect) injection |
| [JailbreakBench/JBB-Behaviors](https://huggingface.co/datasets/JailbreakBench/JBB-Behaviors) | MIT | red-team seeds only |
| [databricks/databricks-dolly-15k](https://huggingface.co/datasets/databricks/databricks-dolly-15k) | CC-BY-SA-3.0 | benign instructions |
| [OpenAssistant/oasst2](https://huggingface.co/datasets/OpenAssistant/oasst2) | Apache-2.0 | benign multi-turn |

Local loaders and measured import counts for these sources are documented in
[reports/2026-11-04-source-loaders.md](reports/2026-11-04-source-loaders.md).
JBB is catalogued as seeds only and contributes no scored rows. Imports still require evaluator review.

No public source covers long context, documents, tool output, code comments or hard negatives well.
Offline [synthetic augmentation](docs/datasets.md#synthetic-channel-and-long-context-augmentation)
can add document, email, tool-output and long-context fixtures within an existing split. These are
not real-world attacks. Synthetic and red-team rows must be approved by the evaluator. Generated
data is published only after review.

Offline [taxonomy coverage](reports/2026-11-04-dataset-coverage.md) from the approved source
manifests shows no document, tool-output, code-comment or multi-turn attack rows, and no explicit
roleplay, encoding, delimiter-spoof, payload-split or many-shot annotations. Long-context coverage
is unknown in those source manifests; augmentation manifests record exact attack length counts.
All source rows still await evaluator approval; `novel` includes unspecified techniques. Refresh the table without reading payloads:

```sh
python3 ops/coverage.py
# Select other aggregate manifests and optionally save the Markdown table:
python3 ops/coverage.py source.manifest.json --output reports/coverage.md
```

## Roadmap

1. **Infrastructure:** schema and normalization, replayable runs, dashboard, model client and
   queue, red-team generator and evaluator, scheduled iterations. *In progress.*
2. **Pipeline:** tune the stage order, rules, thresholds and models against the held-out set. A
   change merges only if held-out detection improves and false positives stay low.
3. **Weight-space work:** use captured activations for probes, steering, and possibly weight edits
   that consolidate the rule set. Every edit is judged by the same held-out metrics.

## AI use

Up to commit `41f3c80`, the code was mostly written by hand, with function-sized suggestions from
Claude Code and Codex reviewed as they were generated. Later commits are mostly AI-generated:
Claude Code and Codex write them under the owner's direction, and Claude Code reviews and tests them
before they merge.
