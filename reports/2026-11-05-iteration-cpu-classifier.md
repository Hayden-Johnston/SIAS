# Optional CPU classifier caches in scheduled iterations

Ticket: 0071.

`ops/iterate.py` accepts optional `cpu_classifier` settings for version, threshold,
chunk windows and checksummed dev/heldout caches exported by `data_processing.model_stage`.
The existing probe validation/filtering path now handles both optional stages. Both split caches
must exist before a stage joins the dev-only fusion sweep and held-out replay. Missing CPU
caches produce `cpu-classifier: not available`; reports name the stages actually fused and
completion manifests record availability. Availability and cache contents affect iteration
identity. No CPU classifier inference or server lifecycle operations were added.

README and pipeline documentation describe configuration and cache requirements. Full-split
caches are filtered to sampled IDs while preserving every chunk; existing replay validation
rejects incomplete chunks. Rules still cover full splits; fusion still covers only Maya's
capped sample. An available activation probe can participate alongside the CPU classifier.

Synthetic integration fixtures exercise perfect label-derived chunk scores, obtaining fused
held-out detection 1 and false-positive rate 0, with Wilson intervals and counts in their
run manifests. These fixtures verify plumbing, not real classifier quality. Chunk latency is
preserved from the supplied cache (2 ms per fixture chunk); no inference latency benchmark,
production detection improvement or storage benchmark was measured. Restoring missing cache
files creates a new iteration; replay after removing the completion checkpoint reproduces
outputs without calling a model client. No datasets or model weights changed.

Validation: `uv run pytest -q` passed (532 passed, 1 skipped, 64 subtests passed);
`uv run ruff check` passed. Staged-file secret pattern scan and diff review passed.
