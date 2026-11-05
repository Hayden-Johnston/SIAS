# Mixed-class development and held-out splits

Ticket 0056 changes splitting from whole non-reserved attack families to SHA-256
assignment by `group_id`, for attacks and benign rows alike. Variants stay together;
reserved attack families still appear only in heldout. The existing three-key config
is unchanged: its test allocation is shared equally between test and heldout.
The manifest records split version 2. The existing iterate.py producer-code hash
will create a new iteration automatically; no scheduler or live config was edited.

This fixes undefined development detection and held-out false-positive rates.
Non-reserved families now span splits, so dev measures new groups of familiar
families. Overall held-out detection mixes familiar and reserved novel families;
per-family metrics distinguish them. Near-duplicate detection is still out of scope.
README and dataset documentation describe these limits and hash bucket rounding.

## Offline measurement

Re-loaded the three pinned snapshots in the live iteration config, normalized them,
and split them without inference. Only aggregate manifests were inspected.
Comparison with the iteration 4 split manifest:

| Split | Previous attacks | Previous benign | New attacks | New benign |
|---|---:|---:|---:|---:|
| train | 916 | 1190 | 646 | 1190 |
| dev | 0 | 273 | 140 | 273 |
| test | 0 | 259 | 66 | 134 |
| heldout | 1000 | 0 | 1064 | 125 |

All 3,638 rows remain present. Detection and FP denominators are now positive in
every split. All 1,000 reserved-family attacks remain exclusively in heldout;
64 familiar-family attacks also enter heldout. Repeating the split produced
identical manifests and byte-identical JSONL files. Local validation artifacts live
under the storage root's `validation/0056/`, outside git.

No classifier calls, model server operations or full scheduled iteration were run.
Detection quality, false-positive rates, latency and storage were not benchmarked;
this measurement establishes class coverage and deterministic assignment only.
Labels remain exploratory, not evaluator-approved.

Validation: `uv run pytest -q` passed (424 passed, 1 skipped, 64 subtests);
`uv run ruff check` passed. Tests cover reserved-family isolation, both classes in
all four splits from one non-reserved family, variant-group integrity, append
stability and byte-identical replay. Staged diff review and secret-pattern scan
passed.
