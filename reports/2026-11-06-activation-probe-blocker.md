# Scheduled activation probe investigation (ticket 0095)

Iteration 8 reports `probe: not available` because the scheduled local configuration
omits `activation_probe`. This is expected fallback behavior, not a failed capture
inside the iteration. `ops/iterate.py` only consumes exported dev/heldout score caches,
with a shared probe version, threshold and per-file SHA-256. It never loads an
activation index, selects a layer, captures hidden states or trains a probe.

The separate `data_processing.probe` exporter needs a schema-v2 `index.json` and
append-only `index.jsonl`, matching safetensors shards, an explicit captured layer,
and a scoring dataset beside `dev.jsonl` and `split_manifest.json`. The manifest must
pin the training dev checksum/count; both labels must be present. Every training and
scoring ID needs a shard. Only dev labels train the probe. Both exported caches must
cover the exact augmented scoring samples used by the iteration.

## Evidence and missing artifacts

A recursive filename inventory of the SIAS storage root on 2026-11-06, including
hidden iteration directories, found **zero** activation indexes, safetensors shards
or probe-named exports. The `activations/` directory is empty. Ticket 0024 delivered
the capture implementation and a synthetic 100-prompt tiny-random-model benchmark;
its [report](2026-11-04-activation-capture.md) explicitly says the benchmark was
removed. It did not leave production activations for scheduled scoring.

Iteration 8's completion and split manifests identify these available inputs:

| Input | Records | Labels (benign / attack) |
|---|---:|---:|
| Original dev training split | 413 | 273 / 140 |
| Augmented full dev scoring split | 1,533 | 833 / 700 |
| Augmented full heldout scoring split | 9,701 | 4,381 / 5,320 |
| Capped validation scoring sample | 25 | 15 / 10 |
| Capped heldout scoring sample | 25 | 8 / 17 |

An ID-only union of original dev plus the two scoring samples contains **455 unique
IDs**. This is the minimum capture for the existing exporter using original dev
training and sample-only exports. Capturing only the 50 sampled rows is insufficient
for that training set. The augmented directory's per-file manifests do not replace
the exporter's required sibling dev split manifest; the operator recipe stages
original dev and its manifest beside separately named scoring samples.

User-owned follow-up **0101** records the exact local checkpoint directory, missing
artifacts, and CPU capture/export commands. It requires an operator-selected pinned
HF checkpoint, uses layer 0 as an untuned baseline, fp16 pooled states with no
per-token subset, a 512-token cap and the existing 20 GiB disk guard. The operator
must return both cache summaries with matching versions and checksums to Claude for
scheduled configuration. No checkpoint quality or optimal layer is assumed.

## Changes, verification and limits

Scheduled settings remain unchanged until real caches exist. No model server,
container, inference, capture or GPU operation was performed. No payload text was
displayed; inspection used code, aggregate manifests, filenames and projected IDs.
Added regression assertions that an omitted probe setting reports unavailable and
fuses only rules and Maya in the existing synthetic replay test.

No runtime behavior changed. Detection, false positives and inference latency were
not remeasured; no improvement is claimed. Investigation created no activation or
score-cache storage. Training on dev makes dev probe scores in-sample, source labels
remain unapproved, and exported zero latency excludes capture/training. Captured
inputs beyond 512 tokens are truncated. Sample-only caches must be revalidated if
the iteration's sampled IDs change.

There is no global replay-only dry-run flag in `iterate.py`; red-team replay-only
does not disable classifier inference. Adding probe caches changes iteration
identity. A future verification must forbid model-client calls and fail on missing
caches rather than invoke a normal iteration assuming it is offline. This ticket
takes the acceptance path of documenting missing artifacts in a user-owned ticket.

Validation: `uv run pytest -q` passed (708 passed, 1 skipped, 9 xfailed,
64 subtests); `uv run ruff check` and `git diff --check` passed. The staged
diff was reviewed and scanned for private keys and common credential patterns.
