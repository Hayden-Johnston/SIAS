# Rules round 4: bounded policy exemption (0102)

Added one strength-0.75 feature: a second-person subject followed by an explicit
exemption from policy obligations. Each gap permits at most four intervening words,
following the existing override window. Thresholds stay at 0.75. README describes
the added behavior; synthetic tests cover all three exemption forms, channel
carriers, base64, exact window boundaries and near misses. No dependencies added;
pi's benign test files are unchanged. Quoted discussions containing the exact cue
can still trigger this lexical rule.

Selection used `rules-0090/dev-after/manifest.json` with the miss-analysis CLI:
485 misses among 700 attacks in 1,533 rows. All are annotated `novel`: 194 document,
97 each direct, email and tool-output. Predefined candidate patterns examined dev
misses and dev benign rows programmatically, emitting counts/IDs only. Policy
exemption and warning suppression had incremental matches; the single policy
feature was selected and narrowed to require a second-person subject. It adds ten
catches from two jackhhao source groups: four document and two each direct, email
and tool-output. No raw payload was inspected or printed. Rules and tests were
frozen before held-out scoring; no held-out miss export or subsequent tuning.

## Measurements

All rate intervals are two-sided 95% Wilson intervals. Rates and deltas below are
percentages and percentage points respectively. Because this adds a max-score
feature, verdict changes are monotone. Delta intervals use Wilson intervals for
paired gains / class denominator; there are no losses. These row-wise intervals
do not account for correlated synthetic carrier variants.

| Metric | Before count / n; rate [CI] | After count / n; rate [CI] | Delta [CI], points |
|---|---|---|---|
| Dev recall | 215/700; 30.714 [27.410, 34.229] | 225/700; 32.143 [28.789, 35.692] | +1.429 [0.778, 2.610] |
| Dev FP | 0/833; 0 [0, 0.4590] | unchanged | 0 [0, 0.4590] |
| Held-out recall | 2555/5320; 48.026 [46.686, 49.370] | unchanged | 0 [0, 0.07216] |
| Held-out FP | 0/4381; 0 [0, 0.08761] | unchanged | 0 [0, 0.08761] |
| Held-out-only family recall | 2490/5000; 49.800 [48.415, 51.186] | unchanged | 0 [0, 0.07677] |

Family check compares dataset family metadata: `Lakera/gandalf_ignore_instructions`
is absent from dev and supplies the 5,000 held-out-only attacks (also the novel
`override` technique slice). Its 4,000 synthetic benign controls remain unflagged:
0/4000, FPR 0% [0, 0.09594%], paired delta 0 points [0, 0.09594]. No improvement
on held-out or the unseen family was measured. Dev attacks comprise 265 deepset
and 435 jackhhao rows; held-out has 85 deepset, 235 jackhhao and 5,000 Gandalf.
All labels remain `evaluator_approved: false`; these are exploratory source labels
and synthetic carriers, not independent approved real-world traffic.

`fp_audit.audit` reran on before/after full rules configs for both splits. The
gate compares flagged IDs to ticket 0091's existing full-rules audit baseline:
all rules and fused lists remain empty, overall and by channel/source. No extra
benign flags; fusion here contains only rules, with threshold 0.75. This does not
re-evaluate the separate sampled multi-stage fusion or establish the target FPR.

Mean cached scoring latency per row: dev 2.566 → 2.654 ms; held-out
2.218 → 2.301 ms. Baseline timings are historical round-3 measurements, so this
is not a controlled performance comparison. Local artifacts occupy about 8.6 MB;
cache format and model storage are unchanged. No inference, network requests,
model-server, container or GPU operations were performed.

## Reproduction and provenance

Local artifacts under the storage root's `runs/rules-0102/` include
`dev-misses.json`, `select.py`, `selection.json`, `rules-before.py`, `evaluate.py`,
before/after replay configs, caches, audit outputs and `summary.json`. Selection
reads dev only; evaluation reuses round-3 baseline caches and re-scores frozen
splits with current rules. Audit uses iteration 7's matching scoring split manifest.

```sh
uv run python -m data_processing.misses \
  "$STORAGE_ROOT/runs/rules-0090/dev-after/manifest.json" \
  "$STORAGE_ROOT/runs/rules-0102/dev-misses.json"
uv run python "$STORAGE_ROOT/runs/rules-0102/select.py"
uv run python "$STORAGE_ROOT/runs/rules-0102/evaluate.py"
uv run pytest -q
uv run ruff check
```

Scores reproduce; measured timings and resulting cache/run hashes can vary.
No corpus, cache or raw payload is committed.

- Dev dataset SHA-256: `ed14740f4b18429a034dbd58b0f6da6c66e5afdbc69d4c15846f127ca1c69380`.
- Held-out dataset SHA-256: `d774f068ab7058fb5727a11e09833e286c71e5e04d493ff9ea4d6e5ac215d14b`.
- Before scorer SHA-256: `1ce264aab1b300c8b37d5f23b5d002114ce05b71908a5d84ff892f4de1a4b69d`.
- Frozen scorer SHA-256: `a394109cf71f63a021d574012fb6c2580182c918da8b6be8f3ab2e54fe96d87f`.

Targeted rules tests: 183 passed, nine existing expected failures. Full-suite,
lint and staged secret-scan results are recorded in the ticket log.
