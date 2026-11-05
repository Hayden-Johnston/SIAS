# Rules round 2: bounded dev residual features (0078)

## Change and selection

Claude's 2026-11-05 ticket decision permits the remaining `novel/tool_output` group
and residual misses in the three groups targeted by 0072, with at most three features.
Only runtime code in `src/data_processing/rules.py` changes; no new dependencies.
Tests extend `tests/test_rules.py`; pi's benign test file is unchanged.

Miss analysis used the latest full dev run, `iteration-000007-validation-rules`:
manifest SHA-256 `c49e86f6ee3b429d2a4f384a8977c88f36a99ca827862fe4ff8b5fbf89eaef94`.
It has the same dataset and rule version as `rules-0072/dev-after`; missed IDs match
exactly. `data_processing.misses` exported 545 misses among 700 attacks (1,533 rows):
218 document and 109 each direct, email and tool-output, all annotated `novel`.

Predefined regex sub-patterns ran over dev misses programmatically, emitting only
counts and IDs. No raw payload text was inspected or printed. Three features were
selected and frozen before opening held-out scoring inputs:

- Persona identity phrasing: add identity/simulation verbs, requiring an adjacent
  unconstrained adjective plus a model/persona noun, or DAN. Adds 10 dev catches.
- Constraint absence: require a second-person subject within four intervening words
  of the absence cue, then a constraint noun within three words. Adds 30 catches.
- Universal request compliance: require a compliance verb and universal quantifier
  plus request noun within four intervening words. Adds 15 catches.

These counts are disjoint on this dev run. All features retain strength 0.75;
thresholds remain 0.75. An initial broader persona candidate failed the synthetic
benign grammar-discussion test; tightening it preceded held-out scoring.
The new tests cover literal and encoded positives, ordinary benign requests,
adjacent nouns and token-window limits. Existing benign near-miss false positives
remain documented as nine expected failures in pi's benign tests.

## Measured effect

All intervals below are two-sided 95% Wilson intervals, percentages. Runs use full
augmented splits, source labels and synthetic controls, `evaluator_approved: false`.
Counts include related channel variants; intervals treat rows as observations and
do not correct for their dependence. These are exploratory measurements.

| Attack slice | Before detected / attacks (recall; CI) | After detected / attacks (recall; CI) |
|---|---|---|
| Dev, all novel | 155/700 (22.14%; 19.22–25.37%) | 210/700 (30.00%; 26.72–33.50%) |
| Dev novel/tool_output | 31/140 (22.14%; 16.06–29.71%) | 42/140 (30.00%; 23.03–38.04%) |
| Dev novel/document | 62/280 (22.14%; 17.67–27.36%) | 84/280 (30.00%; 24.93–35.61%) |
| Dev novel/direct | 31/140 (22.14%; 16.06–29.71%) | 42/140 (30.00%; 23.03–38.04%) |
| Dev novel/email | 31/140 (22.14%; 16.06–29.71%) | 42/140 (30.00%; 23.03–38.04%) |
| Held-out, all | 2530/5320 (47.56%; 46.22–48.90%) | 2555/5320 (48.03%; 46.69–49.37%) |
| Novel-technique override / Gandalf family | 2490/5000 (49.80%; 48.41–51.19%) | 2490/5000 (49.80%; 48.41–51.19%) |

The `override` technique and `Lakera/gandalf_ignore_instructions` family are absent
from dev. Both identify the same 5,000 held-out attack rows here. Supplying iteration
7's `held_out-rules-split.json` populates `slices.novel_technique` in both baseline
and changed replay manifests. Dev's slice is null by runner contract (split
provenance is supported only for held-out runs). Generalization recall is unchanged;
all 25 additional held-out detections belong to the familiar jackhhao family.
No held-out misses selected or revised rules, and no held-out miss export was made.

Dev FP stays 0/833 (0%; CI 0–0.4590%). Held-out FP stays 0/4,381
(0%; CI 0–0.0876%). This sample cannot establish the 0.02% FPR target.
Mean cached CPU scoring latency per row: dev 2.349 → 2.664 ms;
held-out 2.023 → 2.374 ms. Baseline timing comes from iteration 7, so this is
an indicative comparison across runs, not a controlled benchmark.
Local artifacts occupy about 8.6 MB, including replay results, score caches,
selection counts and a baseline source copy. No dataset or cache is added to git.
No inference, server or GPU operations were performed.

## Reproduction and provenance

Artifacts under the storage root's `runs/rules-0078/` include:
`latest-dev-misses.json`, `dev-clusters.json`, `selected-dev-features.json`,
`final-feature-counts.json`, `evaluate.py`, before/after configs and runs, and
`summary.json`. `cluster.py` and `select.py` retain the dev-only selection procedure;
`rules-before.py` pins the baseline implementation. Re-run the miss export with
`uv run python -m data_processing.misses` against the iteration-7 dev manifest.
Run `uv run python "$STORAGE_ROOT/runs/rules-0078/evaluate.py"` to regenerate
CPU caches and replays from the pinned local iteration-7 inputs. Scores reproduce;
new measured timings and cache/manifest hashes can differ.

- Dev dataset SHA-256: `ed14740f4b18429a034dbd58b0f6da6c66e5afdbc69d4c15846f127ca1c69380`.
- Held-out dataset SHA-256: `d774f068ab7058fb5727a11e09833e286c71e5e04d493ff9ea4d6e5ac215d14b`.
- Before rules SHA-256: `3586c8d236823125dc2114991d20a4eacf61fd7f6725d0b3ded327ece606a2f9`.
- After rules SHA-256: `6fb9e63ba812f6574ff1a6c9ad45e1ef34f094a02035ffea092ba4115e3743bd`.
- Summary SHA-256: `fb1890ed9e41a7a8a9e71cae19844f3715a93141f0b78cb6df0883785c10a1ca`.

Validation: `uv run pytest -q` passes (648 passed, 1 skipped, 9 expected failures,
64 subtests; 109.69 seconds); `uv run ruff check` passes. Staged diff reviewed and
scanned for credential patterns before commit.
