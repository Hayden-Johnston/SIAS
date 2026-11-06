# Benign corpus gap (ticket 0103, 2026-11-06)

Added `data_processing.benign_gap`, an offline aggregate-manifest counter. No downloads,
payload reads, inference, dependencies or server operations. Counts are grouped by pinned
source citation and channel, including zero channels. Mixed attack/benign channel marginals
produce `null` when the benign count cannot be inferred exactly. Repeated source citations
are rejected; callers must select disjoint snapshots to avoid cross-source double counting.

Reproduce the checked-in [counts JSON](2026-11-06-benign-gap.json):

```sh
uv run python -m data_processing.benign_gap --output reports/2026-11-06-benign-gap.json
```

## Measured pool and target

The nine checked-in approved-source manifests contain **95,186 benign rows**:

| Source | Benign rows | Channel |
|---|---:|---|
| deepset | 399 | direct |
| jackhhao | 1,323 | direct |
| TrustAIR | 13,199 | direct |
| SPML | 3,376 | direct |
| Dolly | 14,824 | direct |
| OASST2 | 62,065 | multi_turn |
| Gandalf | 0 | direct |
| LLMail | 0 | email |
| JBB (seeds only) | 0 | none |

Totals: direct **33,121**, multi-turn **62,065**; document, email, tool output and code
comment each **0**. The LLMail loader selects attacks only. Hard negatives are not a channel
and the aggregate manifests do not identify their benign subtype; their count is unknown.

The [Statistics target](../docs/pipeline.md#statistics) is approximately **15,000 benign
held-out prompts with zero false positives** for the stated 95% confidence claim. The unsplit
source pool exceeds that number by 80,186 rows (pool gap: zero), but all nine manifests have
`evaluator_approved: false`. Evaluator-approved source-pool benign rows: **0**. These manifests
supply no held-out allocation, so held-out benign count and gap remain **unknown**, not zero.
No achieved FPR confidence claim follows from these counts. OASST2 paths share tree groups;
row totals are not independent-group counts. Cross-source and near-duplicate hygiene remain
necessary before selecting a held-out corpus. There is no prescribed per-channel quota in the
target; the zero channels expose missing coverage, not six separate 15,000-row requirements.

## Candidate benign sources to acquire

These are acquisition proposals, not newly approved sources. No data was downloaded or generated.

- **Hard negatives:** independently reviewed security explanations and original examples that
  quote instruction overrides, role markers and encoding in an explanatory context. Existing
  generator hard negatives are another candidate, pending evaluator approval and deduplication;
  the manifests here do not count them.
- **Documents:** project-owned documentation and purpose-written retrieval documents, with clean
  provenance and varied lengths. Synthetic augmentation controls can exercise document structure,
  but do not substitute for independently reviewed natural documents.
- **Email:** purpose-written benign correspondence with fictional participants and no personal
  data, including headers, replies and quoted discussions. LLMail attack submissions must not be
  relabeled benign based on attack failure or lack of annotation.
- **Tool output:** project-owned API fixtures, command-help output and retrieval/search fixtures,
  including structured JSON and quoted instructions. Record provenance and evaluator decisions;
  avoid credentials or real user records.

Prioritize the empty indirect channels and explicit hard negatives, preserve groups through
splitting, and reserve held-out rows before tuning. Review rights, labels and leakage before
admission. Expanding Dolly/OASST2 alone cannot fill those channel gaps.

## Validation and effect

Tests cover channel/source totals, approval separation, ambiguous marginals, empty/attack-only
inputs, target saturation, duplicate source rejection, deterministic CLI replay, output/input
collision protection, and failures without exporting manifest contents. Detection, false positives
and inference latency are unchanged and were not measured. The JSON stores only aggregate
counts and source citations, with no row IDs or payload text.

Validation: `uv run pytest -q` — 760 passed, 1 skipped, 9 xfailed, 64 subtests passed
(108.59 seconds). `uv run ruff check` — passed. The checked-in JSON reproduces byte for byte
from the nine source manifests. Staged diff review and a pattern-based secret scan passed.
