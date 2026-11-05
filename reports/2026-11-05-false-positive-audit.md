# False-positive audit from cached rules and fusion (0091)

Added `data_processing.fp_audit`, following the existing ablation module convention.
It validates a replay config, pinned caches and matching split manifest, evaluates
benign rows at the configured rules/fusion thresholds and weights, and writes atomic,
deterministic JSON with counts, Wilson intervals and sorted flagged IDs overall and
by channel/source. No payloads or responses are exported. No dependencies, inference,
network requests, server, container or GPU operations were added. README and pipeline
documentation describe the command and limits. Existing scoring behavior is unchanged.

## Measurements

Existing round-3 rules caches use threshold 0.75. Existing iteration-7 fusion caches
use threshold 0.5 and weights `rules: 0, maya: 0.5`; the sampled rules cache predates
round 3. Full rules and sampled fusion are different populations, not a paired comparison.
Labels are source labels plus synthetic augmentation controls, with evaluator approval
false. Related variants are not independent; row-level Wilson intervals do not model
that dependence. All rates below are percentages with two-sided 95% Wilson intervals.

| Population | Records | FP / benign | FPR (95% CI) |
|---|---:|---:|---|
| dev rules | 1533 | 0/833 | 0% (0–0.4590%) |
| dev fused | 25 | 0/15 | 0% (0–20.3883%) |
| heldout rules | 9701 | 0/4381 | 0% (0–0.0876%) |
| heldout fused | 25 | 0/8 | 0% (0–32.4408%) |

Every represented channel/source group also has zero FP and an empty flagged-ID list.
The following tables give benign denominators and CI upper bounds (lower bounds round
to zero). Sources use the exact pinned citation in JSON; abbreviated names appear here.

| Channel | Dev rules n (upper %) | Held-out rules n (upper %) | Dev fused n (upper %) | Held-out fused n (upper %) |
|---|---:|---:|---:|---:|
| direct | 273 (1.3876) | 125 (2.9815) | 6 (39.0334) | absent |
| document | 280 (1.3534) | 2128 (0.1802) | 3 (56.1497) | 1 (79.3451) |
| email | 140 (2.6706) | 1064 (0.3597) | 4 (48.9891) | 3 (56.1497) |
| tool_output | 140 (2.6706) | 1064 (0.3597) | 2 (65.7620) | 4 (48.9891) |

| Source | Dev rules n (upper %) | Held-out rules n (upper %) | Dev fused n (upper %) | Held-out fused n (upper %) |
|---|---:|---:|---:|---:|
| augmented:document | 140 (2.6706) | 1064 (0.3597) | absent | absent |
| augmented:email | 140 (2.6706) | 1064 (0.3597) | 4 (48.9891) | 3 (56.1497) |
| augmented:long_context | 140 (2.6706) | 1064 (0.3597) | 3 (56.1497) | 1 (79.3451) |
| augmented:tool_output | 140 (2.6706) | 1064 (0.3597) | 2 (65.7620) | 4 (48.9891) |
| deepset | 62 (5.8344) | 35 (9.8901) | 2 (65.7620) | absent |
| jackhhao | 211 (1.7880) | 90 (4.0936) | 4 (48.9891) | absent |

These samples do not establish the 0.02% FPR target. Synthetic controls are not
independently judged benign traffic. Detection and scoring latency are unchanged;
replay runtime was not benchmarked. The four audit JSONs occupy
13,626 bytes.

## Reproduction and validation

Local outputs are under the storage root at `runs/fp-audit-0091/`.
Full rules inputs are `runs/rules-0090/{dev,heldout}-after-config.json`, paired
with iteration 7’s `held_out-rules-split.json`. Sampled fusion inputs are iteration
7’s `{validation,held_out}-fused-run.json`. Its held-out provenance manifest contains
full dev counts for novelty metrics, so `sample-split.json` was assembled from the
existing `validation-maya.json` and `held_out-maya.json` metadata under `splits.dev`
and `splits.heldout` (schema version 2), pinning the actual scoring populations.

Run each config/manifest pair with:

```sh
uv run python -m data_processing.fp_audit RUN_CONFIG SPLIT_MANIFEST OUTPUT_JSON
```

Each audit was run twice and produced identical bytes. Tests cover nonzero FP
grouping, attack exclusion, threshold equality, zero weights/threshold, chunk caches,
no benign rows, checksum/count/cache failures, atomic output preservation, input
overwrite prevention, API/CLI byte equality and payload omission.

Validation: `uv run pytest -q` passed (685 passed, 1 skipped, 9 expected failures,
64 subtests; 103.19 seconds). `uv run ruff check` passed. Staged diff reviewed,
whitespace checked and scanned for credential patterns before commit.
