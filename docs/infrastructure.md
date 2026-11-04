# Phase 1: infrastructure (in this order)

1. **Dataset schema and normalization** (see `datasets.md`).
2. **Server launch and teardown.** Simple scripts to bring up and shut down named sets of servers,
   including Maya Q1 and Q2 and the ComfyUI workers. Enforce the GPU rules in `rig.md`. The proxy calls
   these.
3. **Proxy.** Routes requests to all model servers by model name and applies the scheduling rules. If
   the model is not loaded: queue, group by model, start once, drain. Reuse existing proxy code in the
   repo if present.
4. **Activation capture** (HF transformers, LLMs only; see policy below).
5. **Dataset run workflow** that does not depend on inference: manifest driven, resumable, replayable
   from cached model outputs, writes a run manifest with scores per stage.
6. **Dashboard** (`dashboard.md`), starting with run history and the queue view once manifests exist.

## Activation capture policy (storage is limited)

- Save per prompt: last-token and mean-pooled hidden states, every 3rd layer, fp16. Per-token states
  only for a small sampled subset.
- Shard files keyed by prompt id with an index. Record model hash, tokenizer version, layer list and
  dtype with each shard. Activations from a different checkpoint are not comparable.
- Check free space before a run and stop at a configured limit.
- Sizing: ~180 KB per prompt per position across all layers at fp16 for a 4B-class model.
