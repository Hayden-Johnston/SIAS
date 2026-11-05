# Dev-miss rule features (ticket 0072)

The miss exporter now accepts complete `validation` runs as well as `held_out`,
preserving the supplied split in its IDs-only output. Validation miss IDs and
technique/channel counts selected the rule work; no raw corpus text or held-out
miss IDs were inspected. No inference, server operations or dependencies were added.

Selection used `iteration-000006-validation-rules`: 1,533 rows, 700 attacks,
585 misses. Ranked by decreasing count, then technique/channel lexically:

| Technique | Channel | Misses |
|---|---|---:|
| novel | document | 234 |
| novel | direct | 117 |
| novel | email | 117 |
| novel | tool_output | 117 |

The first three joint groups are the targets. There are **not three distinct
annotated techniques**: every dev attack is labeled `novel` (unspecified).
Tool output ties with direct/email and benefits from the same content features.
No technique labels were inferred or changed.

Two regex features score 0.75, matching the existing delimiter feature strength:
a bounded persona switch naming an unconstrained role, and safety suspension or
refusal suppression tied to constraint/request nouns. Persona proximity allows
eight intervening tokens to cover short role descriptions; refusal suppression
retains the existing override feature's four-token window. Safety suspension
allows only one optional determiner before its constraint phrase. Tests exercise
these limits and ordinary role requests, safety vocabulary and benign refusals.
Aggregate candidate checks used dev misses only. A prompt-disclosure candidate
had no incremental dev matches and was omitted. Rules were frozen before held-out
scoring; a subsequent literal-apostrophe correction was rescored without changing
any verdicts. Existing Unicode/encoding views and max aggregation are unchanged.

## Measured effect

All rates below use the runner's 95% Wilson intervals, shown as percentages.
Both stage and fusion thresholds stay at 0.75 and 0.5 respectively, as in the
baseline config; the new features cross both thresholds. Same datasets before/after.

| Split / metric | Before: count, rate [CI] | After: count, rate [CI] |
|---|---|---|
| Dev detection | 115/700, 16.43% [13.87, 19.36] | 155/700, 22.14% [19.22, 25.37] |
| Dev FPR | 0/833, 0.00% [0.00, 0.46] | 0/833, 0.00% [0.00, 0.46] |
| Held-out detection | 2515/5320, 47.27% [45.94, 48.62] | 2530/5320, 47.56% [46.22, 48.90] |
| Held-out FPR | 0/4381, 0.00% [0.00, 0.08761] | 0/4381, 0.00% [0.00, 0.08761] |

Dev detection gains 5.71 percentage points; held-out gains 0.282 points.
Dev confusion counts `(TP, FN, FP, TN)` change from `(115, 585, 0, 833)` to
`(155, 545, 0, 833)`; held-out changes from `(2515, 2805, 0, 4381)` to
`(2530, 2790, 0, 4381)`.

| Target dev group | Before recall [CI] | After recall [CI] |
|---|---|---|
| novel / document | 46/280, 16.43% [12.55, 21.22] | 62/280, 22.14% [17.67, 27.36] |
| novel / direct | 23/140, 16.43% [11.20, 23.45] | 31/140, 22.14% [16.06, 29.71] |
| novel / email | 23/140, 16.43% [11.20, 23.45] | 31/140, 22.14% [16.06, 29.71] |

Dev attack distribution: deepset 265, jackhhao 435. Held-out: Gandalf 5,000,
deepset 85, jackhhao 235. Counts include original attacks and four synthetic
carrier variants per attack; thus the 40 additional dev catches represent eight
originals, and 15 held-out catches represent three originals. These variants are
correlated, so row-wise Wilson intervals overstate independent evidence. All
labels remain `evaluator_approved: false`; `novel` does not establish a novel
technique. Neither these sample sizes nor these labels establish the target FPR
or generalization to real document/email attacks.

Mean recorded scoring time per row: dev 2.215 ms before / 2.264 ms after;
held-out 1.9854 ms before / 1.9855 ms after. The baseline timings are historical
cache measurements and the new timings are one local pass, not a controlled
latency benchmark. Held-out cache storage is about 1.05 MB before and after;
the cache schema is unchanged. No inference or model storage was needed.

## Reproduction and validation

Artifacts are under the local storage root's `runs/rules-0072/`: `dev-misses.json`,
`dev-after-config.json`, `heldout-after-config.json`, score caches, replay outputs,
`summary.json` and `evaluate.py`. The helper only scores/replays existing local
data and prints aggregate metrics. With `RUNS` set to that root's `runs` directory:

```sh
uv run python -m data_processing.misses \
  "$RUNS/iteration-000006-validation-rules/manifest.json" \
  "$RUNS/rules-0072/dev-misses.json"
uv run python "$RUNS/rules-0072/evaluate.py"
uv run pytest -q
uv run ruff check
```

The helper reuses iteration 6 configs from checkpoint
`b7028b944025c9d8c140a89fdea932f94f5a7abe527d5ee68c090951a9006eb1`,
updates only run IDs and cache path/hash/version, and compares to the frozen
`iteration-000006-{validation,held_out}-rules` manifests. Re-scoring preserves
verdicts; measured latency, score-cache hashes and replay identities can vary.

Pinned identities:

- Baseline scorer SHA-256: `784ce5ab53cd714bc37f8d8c308e82954d81046858676bc7ffb962f48732bde4`.
- New scorer SHA-256: `3586c8d236823125dc2114991d20a4eacf61fd7f6725d0b3ded327ece606a2f9`.
- Dev dataset SHA-256: `ed14740f4b18429a034dbd58b0f6da6c66e5afdbc69d4c15846f127ca1c69380`.
- Held-out dataset SHA-256: `d774f068ab7058fb5727a11e09833e286c71e5e04d493ff9ea4d6e5ac215d14b`.
- Dev miss source manifest SHA-256: `66023b17963a6224b1c2e71470c480731673e90ce2d5bfef70de789d216b7bd8`.

Targeted rules/misses/benign suite: 111 passed. Full suite and lint results are
recorded in the ticket log. New tests cover both exporter splits, deterministic
IDs-only CLI output, invalid split rejection, encoded feature activation and
bounded benign controls; ticket 0041's 30 benign sentences remain below threshold.
