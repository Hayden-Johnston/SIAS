# Optional cached activation probe in iterations (ticket 0059)

`ops/iterate.py` accepts an optional `activation_probe` object with a shared version and
threshold plus dev/heldout cache paths and checksums. Both files must exist: the existing
weight sweep requires the same stages on dev and held-out. Otherwise the report says
`probe: not available` and fusion continues with rules and Maya. Present cache checksum
mismatches fail before classifier inference. Cache availability participates in iteration
identity, so adding a missing file creates a new iteration rather than returning an old result.

Existing probe exports are filtered to the deterministic capped Maya samples and included as
`activation-probe` in the existing dev-only fusion sweep. Missing sampled scores fail without
fabricating scores. Full-split rules scoring and the classifier request budget are unchanged.
Reports and fusion summaries name the configured fusion stages, including stages selected with
zero weight. No capture, training, model server operations, activation imports or dependencies
were added. README and pipeline documentation describe the opt-in configuration.

## Measured effect and limits

A synthetic integration fixture with 25 sampled dev rows and 10 held-out rows uses manually
assigned label-matching probe scores and a fake classifier. Rules + Maya yielded TP=0, FN=5,
FP=0, TN=5; adding the fixture probe yielded TP=5, FN=0, FP=0, TN=5. Dev selected weights
`activation-probe=0.5, maya=0, rules=0`. Held-out detection was 5/5 (95% Wilson interval
0.5655–1), false positives 0/5 (0–0.4345). These deliberately ideal scores test integration;
no real probe or approved dataset was evaluated and no detection-quality improvement is claimed.

The two additional sampled score caches occupied 3,465 bytes in that fixture. Storage scales
with sampled IDs, with at most 25 per split; external exports remain untouched. Probe latency
is the export's zero placeholder: capture, training and real scoring latency are unmeasured.
Probe training on dev also makes dev probe metrics in-sample, as before. Replay after deleting
only the completion checkpoint was byte-identical and made no classifier calls.

Tests cover both caches present, either/both missing, newly available cache identity, report
stage names, invalid configuration, checksum mismatch before inference, missing sampled scores,
and deterministic replay. All fixtures are synthetic and require no model servers.

Validation: `uv run pytest -q` passed (494 passed, 1 skipped, 64 subtests);
`uv run ruff check` and `git diff --check` passed.
