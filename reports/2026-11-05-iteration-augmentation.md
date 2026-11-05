# Scheduled split augmentation (ticket 0057)

The iteration now calls the existing offline augmenter independently on train, dev, test and
heldout after normalization and splitting, as approved in the ticket. It never re-splits augmented
rows. A boolean `augment` config option defaults to true; false retains original-only scoring.
Seed 0 fixes insertion positions and IDs. The augmenter code hash participates in iteration
identity, and completed per-split manifests checkpoint augmentation for resume.

Rules score all augmented dev/heldout rows; Maya samples the expanded splits with the existing
hash selection and unchanged cap of at most 25 per split. Completion manifests and dated iteration
reports record added counts per channel and split. Original split counts remain separately
available; augmented manifests retain exact length counts. Synthetic labels remain unapproved,
and augmentation fails if an attack-containing split has no benign padding rows.

On the 100-row synthetic integration fixture (50 attacks), augmentation adds 400 rows: 200 document,
100 email and 100 tool-output rows. The document additions include 50 long-context attacks and
50 matched long-context controls. Reserved-family attacks and all their additions stay heldout:
rules score 451 heldout rows instead of 51, with 41 dev rows unchanged. The fake classifier still
receives four rows per split. Across all four splits, JSONL storage grows from 54,490 to 1,185,630
bytes; original split files are also retained. This is fixture storage, not a production estimate.

Tests cover independent regeneration of identical dataset/manifest bytes, completed replay and
resume without reaugmentation or inference, original group/family/split preservation with and
without reserved families, added channel counts, config validation, disabled augmentation, and
failure without same-split benign padding. No real model calls or server operations were used.
Detection quality, real false positives and model latency were not measured; synthetic fixtures
and fake classifier outputs cannot establish them.

Validation: `uv run pytest -q` passes (450 passed, one skipped, 64 subtests passed), and
`uv run ruff check` passes. The example-config test accepts the new key and asserts the enabled
default, as authorized in the ticket. Aggregate manifests and file sizes from the integration
fixture confirm the counts and storage measurements above.
