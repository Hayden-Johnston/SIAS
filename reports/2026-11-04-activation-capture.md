# Activation capture CLI and safetensors shards

Added `data_processing.activations` (Phase 1, step 4) to capture hidden states from a
Hugging Face `transformers` causal LM on normalized JSONL datasets. Added the optional
`activations` dependency group (`torch`, `transformers`, `safetensors`) to `pyproject.toml`,
pinned `torch` to the PyTorch CPU wheel index (`pytorch-cpu`) so core installs stay light
and no GPU packages are pulled, and documented CLI usage in `docs/infrastructure.md` and
`README.md`.

Each prompt is tokenized on CPU by default, truncated at `--max-tokens` (default `512`)
with truncation recorded in both the shard header and `index.json`, and run through the
model with `output_hidden_states=True`. Every 3rd transformer layer (`--layer-step 3`, or
explicit `--layers`) is extracted in `fp16` (`--dtype`):
- `last_token`: shape `(num_selected_layers, hidden_size)`
- `mean_pooled`: shape `(num_selected_layers, hidden_size)` (averaged in `fp32`, stored as `fp16`)
- `per_token`: shape `(num_selected_layers, token_count, hidden_size)`, stored only for a
  deterministic seeded subset (`--per-token-fraction`, default `0.05`, or `--per-token-count`,
  seeded by `--seed`).

Shards (`shards/<id>.safetensors`) and `index.json` are serialized deterministically (sorted
header keys, sorted metadata keys, and canonical tensor offset layout) and written atomically
via temporary files and `os.replace`. Both the shard `.safetensors` metadata header and the
index record `model_identity` (`repo_id`, `commit_hash`, `weights_sha256`),
`tokenizer_version`, `layers`, and `dtype`. Re-running skips prompt IDs already in
`index.json` and refuses to append if any identity field differs. Free disk space on the
output volume is checked before starting and before writing each shard, stopping cleanly
(`"status": "stopped_disk_limit"`) when free space would fall below `--min-free-gb`
(default `20` GiB).

## Validation and measurements

`uv run pytest -q`: **93 passed, 39 subtests passed**.
`uv run ruff check`: **passed**.

The 9 added tests in `tests/test_activations.py` (including 4 parametrized mismatch cases)
use synthetic benign fixtures and `hf-internal-testing/tiny-random-LlamaForCausalLM`
(2 hidden layers, hidden size 16), covering tensor shapes and `fp16` dtype, shard and index
metadata, custom layer selection, prompt truncation tracking, resume skipping completed IDs,
byte-for-byte determinism across fresh and resumed runs, refusal on `model_identity`,
`tokenizer_version`, `layers`, or `dtype` mismatch, clean stop and resume across the disk
space limit, and CLI output hygiene without payload text leakage.

A synthetic benchmark of 100 benign prompts (mean `23.4` tokens, `layer_step=3` selecting
layer `[0]`, `dtype=fp16`, `per_token_fraction=0.05` sampling 5 prompts) was run on CPU
under `/mnt/storage/llm_security/activations/` and removed after measurement:

| Measurement (`tiny-random-LlamaForCausalLM`, 100 prompts) | Value |
|---|---:|
| Model + tokenizer load from local HF cache | 4.7315 s |
| Total capture wall time (including atomic shard + index writes) | 7.8320 s |
| Seconds per prompt / milliseconds per prompt | 0.07832 s / 78.32 ms |
| Pooled-only shard size (`last_token` + `mean_pooled` + header) | 752.0 bytes / prompt |
| Sampled `per_token` shard size (mean 23.4 tokens + header) | 1,579.2 bytes / prompt |
| Mean shard bytes per prompt (95 pooled-only + 5 with `per_token`) | 793.36 bytes / prompt |
| `index.json` size across 100 prompts | 62,721 bytes (627.21 bytes / prompt) |
| Total bytes per prompt (shards + `index.json`) | 1,420.57 bytes / prompt |

### Estimate for a 4B-class model

For a typical 4B-class causal LM (`36` transformer layers, `hidden_size = 2560`) at `fp16`
(2 bytes/element):
- **All 36 layers**: `36 * 2560 * 2 = 184,320` bytes (`180 KiB`) per token position.
- **Every 3rd layer (`12` layers)**: `12 * 2560 * 2 = 61,440` bytes (`60 KiB`) per token position.
- **Pooled-only shard (`last_token` + `mean_pooled`)**: `2 * 61,440 = 122,880` bytes (`120 KiB`)
  of tensor data, or **~123.6 KB/prompt** on disk including the `.safetensors` header (~124.2 KB
  with the `index.json` entry).
- **Sampled `per_token` shard**: adds `T * 61,440` bytes; at a mean prompt length of `T = 128`
  tokens this is **~7.99 MB/prompt** (`7,987,200` tensor bytes), and at the `--max-tokens 512`
  cap it is **~31.58 MB/prompt** (`31,580,160` tensor bytes).
- **Expected average storage (`per_token_fraction = 0.05`)**: at `T = 128` mean tokens,
  `123.6 KB + 0.05 * 7.86 MB ≈ 517 KB/prompt` (~5.17 GB per 10,000 prompts).
- **CPU latency estimate**: ~0.5–2.0 s/prompt at ~128 tokens and ~2–6 s/prompt at 512 tokens
  on CPU, scaling linearly with token count and model FLOPs.

## Limits

Prompts are processed sequentially (batch size 1) on CPU to avoid padding artifacts in
mean-pooled states and to respect the rig GPU reservation rules. `index.json` is rewritten
atomically as shards complete, which is simple and safe for dataset runs of thousands of
prompts but scales linearly in index write I/O with total shard count. No probe training or
detection stage integration is included in this step.
