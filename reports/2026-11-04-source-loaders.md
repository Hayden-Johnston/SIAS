# Approved source loaders (ticket 0012)

Added one local-only loader command for the nine approved sources. It converts source labels,
composite instructions and conversation trees, then uses the existing schema v2 normalizer.
Gandalf uses a flat JSON mapping; the other sources use small conversion functions.
No new dependencies, model inference, downloads in the loader, or raw rows in git. README and
`docs/datasets.md` describe the command, selection and replay contracts.

## Measured imports

Pinned Hugging Face snapshots were downloaded after rechecking the top-level card license against
0005. All nine matched. Raw storage (including cards and download receipts): 561,494,113 bytes,
within the 10 GB budget. Normalized JSONL: 356,204,897 bytes, stored outside git. Aggregate manifests
are in [dataset-manifests](dataset-manifests/), one per source, including exact revisions, raw-file
checksums, output checksums, and counts by label, channel, technique and family.

| Source | Raw rows/trees | Scored rows | Benign | Attack | Exact duplicates | Excluded |
|---|---:|---:|---:|---:|---:|---:|
| deepset | 662 | 662 | 399 | 263 | 0 | 0 |
| jackhhao | 1,998 | 1,976 | 1,323 | 653 | 22 | 0 |
| trustair | 15,140 | 14,563 | 13,199 | 1,364 | 577 | 0 |
| gandalf | 1,000 | 1,000 | 0 | 1,000 | 0 | 0 |
| spml | 16,012 | 15,917 | 3,376 | 12,541 | 94 | 1 |
| llmail | 160,741 | 50,000 | 0 | 50,000 | 0 | 110,741 |
| jbb | 200 | 0 | 0 | 0 | 0 | 0 |
| dolly | 15,011 | 14,824 | 14,824 | 0 | 187 | 0 |
| oasst2 | 13,854 | 62,065 | 62,065 | 0 | 0 | 4 |

LLMail contributes 50,000 `email` attacks, all `novel`. OASST2 contributes 62,065 `multi_turn`
benign conversation paths, with each source tree kept in one group. Other scored rows are `direct`.
Gandalf contributes 1,000 explicitly sourced `override` attacks. TrustAIR contributes 388 attacks
with named source communities (`named_jailbreak`), and 976 attacks without that annotation
(`novel`). Other attacks use `novel`; no source supplies spans, so attack spans are `null`.
Benign techniques/spans are empty. All manifests retain `evaluator_approved: false`.

## Snapshot selection and limits

- Deepset and Gandalf: all data Parquet files, supplied in repository filename order.
- JackHhao: `default/jailbreak_dataset_full.csv` only; overlapping balanced/train/test copies omitted.
- TrustAIR: December 2023 jailbreak and regular Parquet snapshots only; earlier overlapping releases omitted.
- SPML: the single CSV; one empty user prompt excluded. Only the user prompt is scored.
- LLMail: `data/labelled_unique_submissions_phase1.json`, in file insertion order. Only explicit
  boolean `true` / string `True` attack-attempt annotations qualify; first 50,000 unique accepted
  rows retained. False, ambiguous annotations and rows beyond the cap are excluded, not labelled
  benign. Objective success is not used as the attack label.
- JBB: harmful and benign behavior CSVs (200 seeds). The manifest catalogs inputs and emits zero
  scored rows; the loader never turns behaviors into attacks. Raw seeds remain available locally.
- Dolly: original JSONL; instruction plus context, without the answer.
- OASST2: `2023-11-05_oasst2_ready.trees.jsonl.gz`; reviewed/undeleted root-to-leaf paths only.
  Four roots yield no qualifying path. Rejected/deleted branches are omitted without splicing.

The source-level benign approvals are assumptions from 0005, not independent safety labels.
Exact mapped duplicates are collapsed; no semantic deduplication, cross-source hygiene, conflicting
label resolution or split assignment is claimed. Attack families without source annotations remain
source-wide, conservatively preventing unsupported claims about family generalization.

Deepset's top-level card still declares the approved Apache-2.0 license; its nested `dataset_info`
contains `cc-by-4.0`. The loader records the approved top-level declaration. This inconsistency
needs resolution before publishing the derived corpus; this change publishes aggregate manifests only.

## Validation and effect

Synthetic fixtures exercise all nine source roles, label rejection, unknown spans, source-derived
techniques, tree grouping/turn preservation, CSV/Parquet/gzip input, deterministic replay, exact
duplicates, conflicting source ID rejection, raw checksums, the LLMail cap and failures without payload output or replacing outputs.
`uv run pytest -q`: 135 passed, 1 skipped, 39 subtests passed. `uv run ruff check`: passed.

All nine downloaded snapshots also replayed with byte-identical JSONL and manifests;
the complete local replay took 40.82 seconds (no inference).

No detection stage or scored experiment changed. Detection rate, false positives and inference
latency were not measured. This change establishes reproducible input counts and provenance;
it does not approve rows for evaluation or publication.
