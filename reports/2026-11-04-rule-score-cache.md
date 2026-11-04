# Rule/NLP score cache

Added `data_processing.rules`: a standard-library scoring function, readable rules,
and a CLI producing the existing replay cache contract. Dataset schema, checksum,
row count, and unique IDs are checked before replacing a cache. Output contains
only IDs, scores, and measured milliseconds; CLI diagnostics contain no payload text.
The producer version is the SHA-256 of its source file, covering all fixed rules/settings.

The ticket referred to Unicode normalization in `normalize.py`; inspection showed
that it deliberately preserves text. This stage therefore applies NFKC, case folding,
format-character removal, and a limited explicit homoglyph mapping on a temporary copy.
Token/proximity override phrases score 1.0, spoofed role/delimiter markers 0.75,
and encoding indicators 0.25. Maximum matching strength wins; these are uncalibrated
heuristics. Multi-turn content is scored separately, then aggregated by maximum.
The existing online prototype remains unchanged.

## Validation and measurements

`uv run pytest -q`: **84 passed, 39 subtests passed**.
`uv run ruff check`: **passed**.
The 33 added tests cover synthetic rule positives/negatives, Unicode obfuscation,
weak-signal repetition, a long benign fixture, multi-turn content, empty datasets,
cache schema/latency, deterministic scores and cache bytes with a fixed clock,
replay compatibility, invalid-input preservation, input/output alias protection,
and CLI success/error output without payload text.

No development dataset manifests were present under `/mnt/storage/llm_security`
when checked. No raw corpus was inspected. A temporary synthetic measurement used
the four rows from `tests/test_rules.py::dataset`, repeated in order 2,500 times,
with `id` and `group_id` replaced by the decimal row index (0 through 9,999).
It normalized those rows, produced a cache, and replayed a single rule stage at
threshold 0.5, with evaluation split declared `validation` and approval false.
Temporary files lived under the storage root and were removed after measurement.

| Measurement | One local run |
|---|---:|
| Rows reached / caught / passed | 10,000 / 5,000 / 5,000 |
| Scores min / max / mean | 0 / 1 / 0.5 |
| Scoring latency total / mean per row | 140.731 ms / 0.014073 ms |
| Cache production wall time (validation and I/O included) | 0.371507 s |
| Cache size | 473,880 bytes |
| TP / FP / FN / TN | 5,000 / 0 / 0 / 5,000 |

Replay reported detection 1.0 (n=5,000, two-sided Wilson 95% interval
[0.9992322981, 1]) and false positives 0.0 (n=5,000, interval
[0, 0.0007677019]). The attack distribution was 5,000 rows in synthetic family
`fixture`, drawn from two templates; benign rows likewise used two templates.
These repeated fixtures are not independent samples. The intervals demonstrate
runner output only and do not support population or held-out detection claims.
Latency covers content extraction, transformations and matching; it excludes
validation and disk I/O. Cache hashes change when latency is remeasured.

## Limits

This is pipeline infrastructure with an initial deterministic baseline, not evidence
of improved detection on approved data. Quoted instructions and technical material
can trigger false positives. Paraphrases, other languages, encoded content and
instructions distributed across turns can be missed. There is no decoding, intent
classifier, chunk/location output, threshold tuning, or evaluator approval.
Memory scales with record count. No model/network inference or server lifecycle
actions were needed.
