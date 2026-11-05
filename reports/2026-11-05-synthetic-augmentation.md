# Synthetic channel and long-context augmentation (ticket 0047)

Added an offline schema-v2 augmentation command. It retains originals and adds document, email,
tool-output and padded-document variants plus matched benign controls per attack. A seed/ID hash
chooses insertion position; exact Unicode spans recover the full original attack text. Attack
techniques, family and group are preserved. Output manifests pin the source split, record checksums
and aggregate channel/length counts, and explicitly withhold evaluator approval.

The command requires an existing split and verifies its checksum and count. Long-context padding
uses only benign text from that input split; missing benign padding is an error. No inference or
server operations occur. Controls preserve the source family/group to remain associated with it;
outputs must not be re-split. New rows are marked synthetic and nonpublishable. Documentation and
README describe this workflow and its limits. Coverage now reads exact attack channel and length
counts when supplied, retaining its previous conservative behavior for old manifests.

## Measured effect

Synthetic Unicode marker fixture, seed 17, using the same split/normalizer workflow as the tests:

| Measure | Result |
|---|---:|
| Input rows | 2 (one attack, one benign) |
| Output rows | 10 (five attack, five benign) |
| Attack channels: direct / document / email / tool_output | 1 / 2 / 1 / 1 |
| Attack rows >=8192 characters | 1 |
| Input / output / output-manifest bytes | 598 / 22374 / 671 |
| One local augmentation call | 1.78 ms |

The timing is a single tiny fixture measurement, not a throughput benchmark. Memory grows with
input and output size. Both long attack/control rows exceed 8192 characters. That threshold is
specific to augmentation/coverage; scoring runs keep their existing separate length buckets.
Tests verify byte-for-byte replay, Unicode span recovery, all three insertion positions, controls,
family/group and pinned split preservation, missing benign rejection, checksum validation, CLI
operation and nonzero coverage. Invalid bytes in another split do not affect augmentation.

No detection, false-positive or location accuracy effect was measured. Synthetic wrapping supplies
channel/length fixtures, not evidence of real-world attack validity. Labels and controls still need
independent evaluator review; provenance declarations do not authorize publication.

## Validation

`uv run pytest -q`: 391 passed, 1 skipped, 53 subtests passed. The final focused
augmentation/coverage run, including two additional split/position tests: 8 passed.
`uv run ruff check`: passed. Staged changes were reviewed and scanned for secret patterns.
