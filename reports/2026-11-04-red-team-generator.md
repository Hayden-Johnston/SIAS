# Red-team taxonomy generator (ticket 0017)

Added `data_processing.generate`, using the existing queued Maya client and schema-v2
normalizer, without dependencies or server lifecycle operations. Each one-shot request asks
for plain/paraphrased/obfuscated siblings and a benign quoted-attack hard negative. It cycles
through the channel/technique product, wraps indirect candidates in deterministic benign
carriers, and records exact insertion spans. Multi-turn uses a fixed benign exchange and a
final generated user turn. Obfuscated candidates include the encoding technique.

The default budget is 50 requests, submitted in batches of one, with 2048 maximum output
tokens per request. Indirect carriers add 8192 benign characters on each side. The default
seeds are three harmless marker/style/topic goals; an explicit local JBB Goal snapshot can
replace them. No automatic download or dataset discovery occurs. Outputs and the dedicated
queue stay under the local candidates storage root, outside git.

Input/configuration/code hashes identify runs. Cached completions replay without inference;
interrupted runs rebuild output from cached requests. The manifest is written last and
contains counts and an output checksum, never payload text or local paths. Candidate labels
and requested techniques are provisional, publication is disabled, and evaluator approval
remains false. Refusals and persisted failed requests stop without retry by this command;
transport retries remain the existing client's behavior. Use one writer per root. Each
run has its own queue so draining stays within the configured group budget.

## Measurement and limits

- Fake-client run: 48 channel/technique combinations, 48 model calls, 192 records (144 attack
  variants, 48 hard negatives), all six channels and eight techniques. Each channel has 32 rows.
- Replaying identical inputs produces byte-identical candidate and manifest files with zero
  additional fake inference calls. All rows pass the shared schema validator, including spans.
- Offline CLI dry-run: default 50 groups, 200 planned records; no client/cache/output creation.
- Seven generator tests cover taxonomy counts, sibling grouping, spans, long carriers, JBB
  seed parsing, budget validation, offline dry-run, invalid responses, and stop-on-failure.
- No live inference or raw dataset inspection performed. Detection, false-positive rates,
  model quality, inference latency and production storage growth are not measured here.
  Insertion spans locate generated content; they do not independently certify attack semantics.

Validation: `uv run pytest -q` passed (193 tests, one skipped, 48 subtests), and
`uv run ruff check` passed. Changed files were scanned with detect-secrets 1.5.0
and the staged diff reviewed before commit.
