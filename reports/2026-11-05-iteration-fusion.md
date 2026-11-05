# Iteration fusion and technique slices

Ticket 0058 adds replay-only rules+Maya fusion to scheduled iterations. Existing full-split
rules and capped Maya runs remain available. Two additional fused runs use exactly the Maya
sample IDs; rules scores and measured latencies are copied from the full caches. No extra
inference or server operations are introduced.

The existing sweep selects weights from {0, 0.5, 1} on dev only, at fusion threshold 0.5,
maximizing observed detection within `fusion_fpr_cap` (default 0.0002, the pipeline FPR target).
A dev sample without both classes explicitly reports fusion and its held-out comparison
unavailable. Sampling is unchanged: no resampling to obtain favorable labels. Held-out is never
used to choose weights. The descriptive comparator is the single stage with highest held-out
detection on the same sample, then lowest FPR, then name. Both detection and FPR deltas are
reported alongside the underlying counts, denominators and Wilson intervals.

Reports now include overall and technique metrics with counts and 95% Wilson intervals,
and novel-technique slices using the existing runner. Each held-out run pins an aggregate
manifest combining its scored dataset checksum and full scoring-dev technique counts,
including augmentation. This avoids declaring techniques novel merely because the capped dev
sample missed them. Multi-technique rows occur in multiple slices; n < 20 is flagged.
Single-stage run fusion thresholds now match their configured stage thresholds, so reported
single-stage verdicts honor those settings.

Synthetic four-row fixture: selected weights rules=0.5, Maya=0.5; fused detection 2/2
(1.0, Wilson 95% CI [0.3424, 1.0]) versus best single 1/2 (0.5, [0.0945, 0.9055]),
held-out detection delta +0.5. Fused and best-single FPR are both 0/2
(0, [0, 0.6576]); FPR delta 0. These are fixture checks, not real-world quality claims.
No production dataset or raw payloads were inspected. Small capped samples cannot establish
the target FPR. Live latency was not measured; replay retains original cached latency.
Storage adds two small rule subset caches, provenance/config/sweep JSON and, when selectable,
two sample-sized replay runs. The classifier budget remains at most 50 prompts per iteration.

Validation covers complementary cached scores, missing scores failing without inference,
novel/all-seen technique slices, invalid FPR caps, unchanged sample IDs and latencies, and
byte-identical replay after deleting the final checkpoint.

`uv run pytest -q`: 457 passed, 1 skipped, 64 subtests passed.
`uv run ruff check`: passed. Staged diff reviewed; secret/private-IP pattern scan found no findings.
