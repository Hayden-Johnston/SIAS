# Rules round 3: bounded indirect-channel refusal suppression (0090)

Added one strength-0.75 rule to `src/data_processing/rules.py`: an explicit
prohibition (`never`, `do not`, `don't`, `must not`) on saying, telling or mentioning
capability refusals (`cannot`, `can't`, `unable`), within four intervening words.
Thresholds and scoring interfaces are unchanged. No dependencies were added.
Synthetic tests cover email, tool-result and document carriers, encoded cues,
the four-word boundary and ordinary benign near misses. Requests to omit apologies
alone do not trigger this rule. Like existing lexical rules, it cannot distinguish
quoted security discussion containing the exact cue from an instruction.

Selection used only the round-2 full dev replay's miss manifest: 490 missed attacks
among 700, with 196 document and 98 each email, tool-output and direct misses.
The latest scheduled full dev run (iteration 7) uses the same dataset and older
rules; round 2 supplies the current-rule baseline. Email, tool-output and document
all tie for recall. Programmatic predefined-pattern checks emitted counts/IDs only;
no raw payload was inspected or printed. Narrow mode-activation and safety-disregard
candidates added no catches. The selected feature adds one email, one tool-output,
two document and one direct detection, all from **one source group** in the familiar
jackhhao family. The rule remains channel-independent, matching the existing API.
Rules and tests were frozen before held-out scoring; held-out misses were not exported
or used for selection. There were no subsequent rule revisions.

## Measurements

All intervals are two-sided 95% Wilson intervals, in percent. Full augmented splits
use source labels and synthetic controls (`evaluator_approved: false`). Related
variants are not independent; row-level intervals do not account for that dependence.

| Attack slice | Before detected/attacks (recall; CI) | After detected/attacks (recall; CI) |
|---|---|---|
| Dev email | 42/140 (30.00%; 23.03–38.04%) | 43/140 (30.71%; 23.67–38.79%) |
| Dev tool_output | 42/140 (30.00%; 23.03–38.04%) | 43/140 (30.71%; 23.67–38.79%) |
| Dev document | 84/280 (30.00%; 24.93–35.61%) | 86/280 (30.71%; 25.60–36.35%) |
| Dev direct | 42/140 (30.00%; 23.03–38.04%) | 43/140 (30.71%; 23.67–38.79%) |
| Dev all | 210/700 (30.00%; 26.72–33.50%) | 215/700 (30.71%; 27.41–34.23%) |
| Held-out all | 2555/5320 (48.03%; 46.69–49.37%) | unchanged |
| Held-out override / Gandalf family | 2490/5000 (49.80%; 48.41–51.19%) | unchanged |

The Gandalf family is absent from dev, as is its `override` technique. Both refer
to the same held-out rows here. Replay includes split provenance and populates the
novel-technique slice. **No held-out or novel-family improvement was measured.**
This change recovers a narrow dev cue only; it does not demonstrate generalization.

Dev FP remains 0/833 (0%; CI 0–0.4590%); held-out FP remains 0/4381
(0%; CI 0–0.0876%). This sample cannot establish the 0.02% FPR target.
The nine previously documented benign-test expected failures remain unchanged.
Mean cached scoring latency per row: dev 2.664 → 2.566 ms, held-out
2.374 → 2.218 ms. Baseline timings are reused from round 2, so these differences
are not controlled performance measurements. Local artifacts occupy about 8.5 MB.
No inference, model-server, container or GPU operations were performed.

## Reproduction

Local artifacts under the storage root's `runs/rules-0090/` contain `dev-misses.json`,
`select.py`, `selection.json`, `rules-before.py`, `evaluate.py`, before/after configs,
score caches, replay runs and `summary.json`. The selection script reads dev only
and writes counts and IDs. The evaluation script reuses round-2 baseline caches
and re-scores both frozen splits with the new rules, without inference:

```sh
uv run python "$STORAGE_ROOT/runs/rules-0090/select.py"
uv run python "$STORAGE_ROOT/runs/rules-0090/evaluate.py"
```

Scores reproduce; measured latencies and resulting hashes can change.
No datasets or score caches are committed.

- Dev dataset SHA-256: `ed14740f4b18429a034dbd58b0f6da6c66e5afdbc69d4c15846f127ca1c69380`.
- Held-out dataset SHA-256: `d774f068ab7058fb5727a11e09833e286c71e5e04d493ff9ea4d6e5ac215d14b`.
- Before rules SHA-256: `6fb9e63ba812f6574ff1a6c9ad45e1ef34f094a02035ffea092ba4115e3743bd`.
- After rules SHA-256: `1ce264aab1b300c8b37d5f23b5d002114ce05b71908a5d84ff892f4de1a4b69d`.
- Summary SHA-256: `ad72725bc26c7284ce6a168e8fcc79f2d11924f2dbce896166fcbeeae45572d8`.

Validation: `uv run pytest -q` passed (676 passed, 1 skipped, 9 expected failures,
64 subtests; 103.25 seconds). `uv run ruff check` passed. Staged diff reviewed,
whitespace checked and scanned for credential patterns before commit.
