# Optional iteration generation and approval round

Ticket 0027 adds an opt-in `red_team` config section to `ops/iterate.py`; omitted or disabled
settings preserve source-only scoring. It reuses the generator with safe seeds, the configured
pinned Maya model, a configurable request cap, and batch/concurrency 1, followed by the existing
CPU llama.cpp evaluator. No new dependencies or Maya lifecycle operations were added.

Only evaluator-approved records are appended to the normalized dataset, retaining
`label_source: evaluator` and `publishable: no`. A separate generated subset is split with the
same family/group configuration as the combined dataset. Mixed-source scoring manifests remain
`evaluator_approved: false`. Reports and completion manifests add generated/approved counts and
approval rate, without payload text.

Generation transport failures and replay-only cache misses become logged, checkpointed skips.
Permanent failures and refusals still stop the iteration. Completed rounds resume without repeating
generation/evaluation; replay-only generation never drains pending inference. Other stages still
require inference when their caches are absent. An unavailable Maya can therefore still prevent
uncached classifier scoring after generation is skipped. Changing config starts a new iteration;
a skipped round is not retried within its completed iteration.

Measured with synthetic fake clients: one generation request yielded 4 candidates, 3 approved
(75% agreement), 1 rejected; the 2 approved attack variants stayed in their designated held-out
family. Resume reused the round, and completed iteration artifacts and reports were byte-identical
on replay. Generation replay from cached replies was also byte-identical with no inference drain.
Off, transport failure, replay-only cache miss and refusal paths are covered.

Validation: `uv run pytest -q`: 225 passed, 1 skipped, 48 subtests passed;
`uv run ruff check`: passed. No live generation or evaluator inference was run, and no model server
was started or stopped. Detection, false-positive changes, live latency and storage growth were not
measured; approval agreement in synthetic fixtures is not evidence of detection improvement.
