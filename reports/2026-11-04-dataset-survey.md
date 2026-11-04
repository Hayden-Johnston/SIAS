# Dataset survey — 2026-11-04 (ticket 0003)

No ready-to-use, licensed attack/benign classification dataset was found in the
searched locations. There are local evaluation harnesses, results and small prompt
fixtures; none is approved for ingestion or publication. Claude must approve or
reject sources in ticket 0005 before a loader is written.

## Method and limits

Read-only filesystem inventory of `/home/h/.cache` (including Hugging Face),
`/mnt/storage`, `/home/h/servers`, and the integration checkout; an additional
filename search under `/home/h` located Hermes evaluation fixtures. Inspected
file sizes, JSON/JSONL keys and record counts, and Python AST collection shapes.
No payload values were displayed, no harness was executed, and no model server
was contacted or changed. JSON parsers necessarily decode records in memory;
only keys/counts are emitted. No raw corpus is included here.

Sizes below are logical bytes, not allocated disk blocks. JSONL rows count
nonempty parsed records, including repeated model runs; they are **not** counts
of unique prompts. Python collection counts are literal entries, not generated
case counts. Attack/benign coverage is inferred from filenames and identifiers,
not validated by inspecting prompts. Unknown means not established by metadata.

Excluded virtual environments, package caches (`uv`, `pip`), `.git`,
`node_modules`, compiled caches and vendored `third_party` code. Model weights,
tokenizers, tensor dumps, GPU telemetry, conversation logs and image-generation
workflow configs are not prompt datasets. Directory walking did not recursively
follow all symlinks; known server data paths were additionally inspected with
`find -L`. This is a survey of the named locations, not a claim about every
file, archive, other user's home or inaccessible directory on the machine.

HF cache contains model snapshots only: no `datasets` cache directory,
`datasets--*` snapshots, Arrow, Parquet or dataset-info files were found in the
searched locations. Neither configured dataset is present. Server data dirs
contain weights/tensors and the quant-quality fixtures listed below. Storage
at survey time: `/mnt/storage` 95% used (45 GiB available), home filesystem
93% used (17 GiB available). No dataset downloads; only small public metadata
pages/cards fetched. No detection, false-positive or inference-latency measurement
is possible from this metadata survey. No runtime behavior changed.

## Local evaluation sources

Paths in this section are rooted at `/home/h/servers/llama/eval/`.
Both harnesses are Python source, not exported tabular datasets. License and
publishability are unknown. Keep variants together: v2 repeats v1 collections.

| Path | Bytes | Entries/schema | Labels, likely coverage and recommendation |
| --- | ---: | --- | --- |
| `harness.py` | 43,737 | `AGENT_TASKS`: 12 references; `CODE`: 15 triples; `IF`: 20 pairs; `FILLER`: 8 strings; `FACTS`: 10 pairs; `FAKE`: 6 strings | No classifier label column. Likely coding, instruction-following, agent and long-context fixtures; benign status unverified. Hold pending owner/license review; useful source design reference, not a classification corpus. |
| `harness_v2.py` | 71,601 | Same base collection counts; adds `NOISE`: 10 triples, `SUSPICIOUS`: 2 triples, `INJECT`: 3 entries, `ORCH`: 5 references, `LONGCTX_SIZES`: 3 | Identifiers suggest email/indirect injection, benign noise, long context and agent orchestration. Generated case count unknown. Prioritize metadata/rights review for email and tool-output coverage; evaluator must establish labels. No claim of standalone jailbreak or validated multi-turn coverage. |

Result schemas (union of top-level columns, not values):

- **A**: detail, expected, false_claim, final, finish, got, item, kind, model,
  ok, out, prompt_tokens, score, secs, steps, suite, tokens, want.
  `lfm3.jsonl` additionally has error.
- **B**: acted_on_phish, caught, coder_calls, coder_tasks, emails_read,
  expected, facts_ok, facts_total, false_claim, final, finish, forwards,
  important, injection, injection_obeyed, item, missed, model, noise_flagged,
  ok, parsed, prompt_tokens, read_all, secs, steps, suite, suspicious,
  suspicious_caught, tokens, vision_calls. `gemma4_v2.jsonl` adds think_tail.
- **C**: detail, finish, got, item, model, ok, score, secs, suite, tokens, want.
- **D**: finish, got, item, kind, model, ok, secs, suite, tokens, want.
- **E**: detail, finish, item, model, ok, secs, suite, tokens.
- **F**: finish, item, model, ok, out, prompt_tokens, secs, suite, tokens.

All result files below have unknown license. `ok`, scores and expected answers
are task outcomes, not benign/attack labels. B has injection-related outcome
columns, but they do not establish a normalized label scheme. Recommendation
for **each result file**: retain for provenance only; reject direct ingestion
as independent classifier examples. Benign coverage is unverified; likely
families are inferred only from suite/file identifiers.

| Path | Bytes | Rows | Columns | Likely coverage |
| --- | ---: | ---: | --- | --- |
| `results/gemma4.jsonl` | 29,731 | 106 | A | Mixed task/agent/long context |
| `results/gemma4_code16k.jsonl` | 2,563 | 15 | E | Long-context coding |
| `results/gemma4_gsm.jsonl` | 15,743 | 90 | D | Math/task prompts |
| `results/gemma4_longmax.jsonl` | 1,604 | 9 | F | Long context |
| `results/gemma4_v2.jsonl` | 15,221 | 30 | B | Email, indirect injection, agent orchestration |
| `results/lfm3.jsonl` | 36,074 | 107 | A | Mixed task/agent/long context |
| `results/lfm3_code16k.jsonl` | 2,679 | 15 | E | Long-context coding |
| `results/lfm3_gsm.jsonl` | 15,665 | 90 | D | Math/task prompts |
| `results/lfm3_hot.jsonl` | 7,675 | 25 | C | Task/coding/instruction checks |
| `results/lfm3_longmax.jsonl` | 2,151 | 12 | F | Long context |
| `results/lfm3_nothink.jsonl` | 7,805 | 25 | C | Task/coding/instruction checks |
| `results/lfm3_v2.jsonl` | 17,829 | 30 | B | Email, indirect injection, agent orchestration |

## Other local fixtures and near-matches

Unless stated otherwise, license and benign status are unknown and no binary
attack labels exist. These are candidate sources, not approved datasets.

| Path | Bytes | Rows / columns | Likely attack types; benign coverage; recommendation |
| --- | ---: | --- | --- |
| `/home/h/servers/strata/src/bench/profile_corpus.json` | 6,582 | 45 records; `d`, `p` | Profiling prompts; no established attack types. Possible general benign coverage, unverified. Hold for rights and evaluator review. |
| `/home/h/servers/strata/src/tools/qwen35/parity_prompts.json` | 717 | 10 strings; no named columns | Parity fixtures; no established attacks. Possible small benign smoke set. Hold; too small for false-positive estimates. |
| `/home/h/servers/strata/src/data/quant_quality/v1/` | See below | Five text files; `set.ids.json` manifest: 26,554 bytes, keys `version`, `seg_tokens`, `segments` (5 groups) | Filename-derived code, agent, multilingual, English, document coverage; no established attacks. Hold for provenance review; possible benign seed only, not labeled ground truth. |
| `/home/h/servers/strata/src/bench/results/2026-10-06-llamacpp-0.6.0/prompt-4k.txt` | 11,286 | One text artifact; no row schema | Long-context performance input; benign unverified. Reject as benchmark corpus; keep only for latency fixture consideration. |
| Same directory, `prompt-32k.txt` | 108,419 | One text artifact; no row schema | Same recommendation; long context, no attack labels. |
| `/home/h/servers/strata/src/bench/results/2026-10-07-community-xtx-6800xt-1m-helper/prompts.json` | 984 | 5 named entries: `moe`, `code`, `prose`, `agentcode`, `longprose` | Task/performance fixtures, benign unverified. Hold as tiny benign candidate after review. |
| Same directory, `full-window-prompt.json` | 502 | One object; `input_tokens`, `max_tokens`, `configured_context`, `markers`, `note`, `api_reserved_tokens`, `usable_request_capacity` | Capacity metadata, not dataset. Reject. |
| `/home/h/servers/strata/src/bench/results/2026-10-09-community-4x-rx-7900-xt/prompts-index.jsonl` | 1,951 | 12; `content_tokens`, `counted`, `first_line`, `label`, `offset`, `target` | Prompt index, not classification labels; benign unknown. Reject direct ingestion; indexed source provenance unverified. |
| `/home/h/servers/strata/src/bench/results/2026-10-06-community-4x-tesla-p100/client_timing_long_prompts.jsonl` | 3,424 | 6; `content_chars`, `content_head`, `first_to_last_s`, `nonce`, `prompt_tokens_tokenized`, `reasoning_chars`, `run`, `target_tokens`, `total_s`, `ttft_s`, `usage` | Timing/output summaries, long context; benign unknown. Reject direct ingestion. |
| `/home/h/.hermes/hermes-agent/evals/shared_gateway/cases.json` | 9,723 | Object `schema`, `cases`; 47 cases | Gateway evaluation; attack types/benign coverage unknown from top-level metadata. Hold, do not publish or ingest without provenance and schema review. |
| `/home/h/.hermes/hermes-agent/evals/browser_use/tasks/easy.json` | 1,342 | 5 named task entries; no common row schema established | Browser task fixtures; benign unverified. Hold as task reference only. |
| Same directory, `hard.json` | 2,263 | 6 named task entries | Same recommendation; no established attack labels. |
| `/home/h/.hermes/hermes-agent/evals/compaction/fixtures.py` | 2,872 | Functions `estimate_tokens`, `total_tokens`, `load_transcript`, `synthetic_transcript`; generated rows unknown | Transcript/long-context fixture code. Reject existing transcript reuse: personal/non-public data risk, no attack labels. Synthetic design reference only after owner review. |

Quant-quality text artifact sizes (one file each; no tabular rows/columns):
`agent.txt` 5,185; `code.txt` 5,201; `docs.txt` 5,200;
`english.txt` 5,004; `multilingual.txt` 5,520 bytes. Manifest groups are not
necessarily unique examples. Do not equate lines, tokens or segments with prompts.

Other Hermes artifacts are evaluation outputs, not approved corpora. Reject
all for direct ingestion/publication; coverage and licensing remain unknown:

| Path relative to `/home/h/.hermes/hermes-agent/evals/` | Bytes | Records / columns |
| --- | ---: | --- |
| `compaction/results/codex-arm-2026-08-15/acp.json` | 6,806 | 1 root object; summary, results |
| `compaction/results/codex-arm-2026-08-15/gui.json` | 7,872 | 1 root object; summary, results |
| `compaction/results/codex-arm-2026-08-15/prmerge.json` | 6,280 | 1 root object; summary, results |
| `compaction/results/codex-arm-2026-08-15/sweep.json` | 6,726 | 1 root object; summary, results |
| `compaction/results/jev-cycles-2026-09-19/cycles-afff57-500k.json` | 357 | 1 root object; transcript, threshold, raw_tokens_consumed, raw_total, msgs_consumed, cycles, jev_usd_total |
| `compaction/results/jev-cycles-2026-09-19/cycles-prreview-160k.json` | 15,563 | 1 root object; transcript, threshold, raw_tokens_consumed, raw_total, msgs_consumed, cycles, jev_usd_total |
| `compaction/results/jev-cycles-2026-09-19/cycles-prreview-500k.json` | 8,563 | 1 root object; transcript, threshold, raw_tokens_consumed, raw_total, msgs_consumed, cycles, jev_usd_total |
| `compaction/results/jev-cycles-2026-09-19/cycles-sigsegv-160k.json` | 3,038 | 1 root object; transcript, threshold, raw_tokens_consumed, raw_total, msgs_consumed, cycles, jev_usd_total |
| `compaction/results/jev-cycles-2026-09-19/cycles-sigsegv-500k.json` | 10,642 | 1 root object; transcript, threshold, raw_tokens_consumed, raw_total, msgs_consumed, cycles, jev_usd_total |
| `compaction/results/jev-cycles-2026-09-19/cycles-sysprompt-500k.json` | 10,620 | 1 root object; transcript, threshold, raw_tokens_consumed, raw_total, msgs_consumed, cycles, jev_usd_total |
| `session_search_schema/results/pr95570/openai_gpt-5.6-luna.jsonl` | 33,766 | 36 JSONL records; arm, bad_calls, calls, final, first_prompt_tokens, model, n_tool_calls, ok, rep, task, total_tokens, wall_s |
| `session_search_schema/results/pr95570/openai_gpt-5.6-terra.jsonl` | 40,985 | 36 JSONL records; arm, bad_calls, calls, final, first_prompt_tokens, model, n_tool_calls, ok, rep, task, total_tokens, wall_s |
| `session_search_schema/results/pr95570/qwen_qwen3-coder-30b-a3b-instruct.jsonl` | 30,397 | 36 JSONL records; arm, bad_calls, calls, final, first_prompt_tokens, model, n_tool_calls, ok, rep, task, total_tokens, wall_s |

The compaction cycle objects are telemetry with transcript references, not
counts of transcript examples. Session-search outputs are agent/task traces;
they do not establish multi-turn attack labels. Routine GPU telemetry, native
expert listings, vocabulary files and image workflow templates are excluded
rather than counted as benign prompts.

## Configured datasets (not found locally)

Metadata checked on the survey date; do not infer label meaning from integer
type alone. No payload endpoint or dataset viewer rows were inspected.

| Dataset | Published size / rows / columns | License and coverage | Recommendation |
| --- | --- | --- | --- |
| [deepset/prompt-injections](https://huggingface.co/datasets/deepset/prompt-injections/raw/main/README.md) | 51,215 download bytes; 87,701 dataset bytes; train 546, test 116 (662 total); `text`: string, `label`: int64 | Card conflicts: nested `cc-by-4.0`, top-level `apache-2.0`. Label mapping and class counts absent from card. Likely single-shot injection classification; benign coverage needs verification. | Prioritize as small baseline, conditional on resolving license and confirming labels. Insufficient evidence for email, long context, tools or multi-turn coverage. |
| [jayavibhav/prompt-injection](https://huggingface.co/datasets/jayavibhav/prompt-injection/raw/main/README.md) | 77,302,823 download bytes; 125,382,538 dataset bytes; train 261,738, test 65,416 (327,154 total); `text`: string, `label`: int64 | No license or label mapping in card. Likely single-shot classification; provenance, benign counts and attack-family coverage unknown. | Hold pending provenance/license and duplication review. Size fits cap, but configuration alone is not approval to download or publish. |

## Public candidates not found in searched locations

These are suggestions for ticket 0005, not acquisition approval. Check exact
revision, license, provenance, download size and overlap before ingestion.

| Source | Why / recommendation |
| --- | --- |
| [Microsoft BIPIA](https://github.com/microsoft/BIPIA) | Prioritize for document/indirect injection, including email-style tasks. Useful complement to short single-shot classifiers; preserve clean contexts for benign comparisons. |
| [InjecAgent](https://github.com/uiuc-kang-lab/InjecAgent) | Prioritize for indirect injection through tool outputs; maintain user-task/tool context instead of reducing everything to attack strings. |
| [AgentDojo](https://github.com/ethz-spylab/agentdojo) | Evaluate later for realistic agent tasks, tool outputs and utility/security comparisons; distinguish agent rollout metrics from static detector classification. Avoid inference during dataset inventory/export. |
| [WildGuardMix](https://huggingface.co/datasets/allenai/wildguardmix/blob/main/README.md) | Consider held-out jailbreak/harmfulness and benign coverage. Harmfulness/refusal labels are different from injection labels; require an explicit evaluator mapping, never automatic relabeling. |

## Decision requested in ticket 0005

Start with a rights/label review of deepset, BIPIA and InjecAgent. Hold
jayavibhav pending provenance and license. Treat local harnesses as potential
source material, outputs as provenance only, and local benign-looking fixtures
as unverified. No source here establishes adequate multi-turn attacks or hard
benign coverage (security discussions, quoted instructions, legitimate tool
instructions). Plan evaluator-approved coverage for those gaps, with family
and variant-group splits and duplicate checks required by `docs/datasets.md`.

## Reproduction and validation

Inventory uses `os.walk`/`Path.stat` for paths and bytes; JSON lists use `len`,
JSONL uses nonempty record counts and unioned dictionary keys. Python collections
use `ast.parse` and literal collection lengths, never imports or execution.
For example, this emits only schema/counts for a selected JSONL file:

```python
import json
from pathlib import Path

p = Path("/home/h/servers/llama/eval/results/gemma4_v2.jsonl")
rows = [json.loads(line) for line in p.open() if line.strip()]
print(p.stat().st_size, len(rows), sorted({key for row in rows for key in row}))
```

Documentation-only change: no loader, dependency, model request or runtime
behavior added. `uv run pytest -q`: 13 passed; `uv run ruff check`: passed.
No new executable code exists to unit-test. The inventory and metadata totals
above provide the survey's validation evidence. Dataset suitability remains
subject to Claude's ticket 0005 review and independent evaluator approval.
