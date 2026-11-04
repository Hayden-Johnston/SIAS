# Dataset taxonomy coverage

Counts are attack rows, from aggregate manifests only; no payloads or inference.
GAP = zero; LOW = fewer than 20 rows; UNKNOWN = not derivable from the manifest.
Source approval does not imply evaluator approval or permission to publish.
Channel totals include benign rows: ambiguous attack counts are UNKNOWN.
Long context is a length property; these manifests contain no length counts.
Novel / unspecified is the loader's fallback, not proof of a novel jailbreak.
Technique columns overlap; do not sum them.

| Dataset | Attack rows | Evaluator approved |
|---|---:|---|
| 2026-11-04-deepset | 263 | no |
| 2026-11-04-dolly | 0 | no |
| 2026-11-04-gandalf | 1000 | no |
| 2026-11-04-jackhhao | 653 | no |
| 2026-11-04-jbb | 0 | no |
| 2026-11-04-llmail | 50000 | no |
| 2026-11-04-oasst2 | 0 | no |
| 2026-11-04-spml | 12541 | no |
| 2026-11-04-trustair | 1364 | no |

## Channels and length

| Dataset | Single-shot | Multi-turn | Document | Email | Tool output | Code comment | Long context |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-11-04-deepset | 263 | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | ? UNKNOWN |
| 2026-11-04-dolly | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP |
| 2026-11-04-gandalf | 1000 | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | ? UNKNOWN |
| 2026-11-04-jackhhao | 653 | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | ? UNKNOWN |
| 2026-11-04-jbb | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP |
| 2026-11-04-llmail | 0 GAP | 0 GAP | 0 GAP | 50000 | 0 GAP | 0 GAP | ? UNKNOWN |
| 2026-11-04-oasst2 | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP |
| 2026-11-04-spml | 12541 | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | ? UNKNOWN |
| 2026-11-04-trustair | 1364 | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | ? UNKNOWN |

## Techniques

| Dataset | Override | Roleplay | Encoding | Delimiter spoof | Payload split | Many-shot | Known jailbreak | Novel / unspecified |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-11-04-deepset | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 263 |
| 2026-11-04-dolly | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP |
| 2026-11-04-gandalf | 1000 | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP |
| 2026-11-04-jackhhao | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 653 |
| 2026-11-04-jbb | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP |
| 2026-11-04-llmail | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 50000 |
| 2026-11-04-oasst2 | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP |
| 2026-11-04-spml | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 12541 |
| 2026-11-04-trustair | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 388 | 976 |

## Change and measured effect (ticket 0045)

Added `ops/coverage.py`, a stdlib-only, offline Markdown report over explicitly selected
aggregate manifests (default: the nine checked-in approved source snapshots). It prints to
stdout and optionally writes the same result with `--output`. No dataset, queue, model,
server or network access is needed. README documents the command and observed gaps.

The snapshots contain 65,821 attack rows: 15,821 single-shot and 50,000 email. There are
zero document, tool-output, code-comment or multi-turn attack rows. Technique annotations
cover 1,000 override, 388 known jailbreak and 64,433 novel/unspecified rows; all other
technique cells are zero. No nonzero cell is below 20 in these snapshots. Long-context
attack counts cannot be established from these manifests. Dolly and OASST2 are benign-only;
JBB contributes seeds, not scored attacks. None of these manifests has evaluator approval.

These are source-label aggregates, not independently validated taxonomy or labeling accuracy.
Detection, false positives and inference latency are unchanged and were not measured.
Storage adds only the script, tests and this aggregate report; no payload copies are created.

Reproduce the tables with `python3 ops/coverage.py`; to regenerate this report's tables,
use `--output` with a separate destination (the change notes here are maintained manually).

Validation: `uv run pytest -q`: 339 passed, 1 skipped, 53 subtests passed in 37.41s.
`uv run ruff check`: passed. Synthetic fixtures cover manifest-only CLI execution from an
unrelated directory, deterministic replay, output-file equality, zero/<20/20 thresholds,
benign-only/empty inputs and ambiguous mixed-channel counts. Staged diff review and a
pattern-based secret scan found no secrets.
