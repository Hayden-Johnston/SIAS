# Datasets

## Base schema fields (one for every source, public and generated)

Every row contains these base fields plus the three version 2 fields below:

| Field | Contract |
|---|---|
| `id` | Nonempty string; unique in a file. Generated SHA-256 of mapped record if omitted by adapter. |
| `text` | Nonempty string, preserved exactly, including whitespace and Unicode. |
| `label` | Integer `0` for benign or `1` for attack; booleans are rejected. |
| `label_source` | Nonempty string recording the origin of the label. |
| `attack_family` | Nonempty family name; use an explicit benign family for benign rows. |
| `group_id` | Nonempty pair/variant group identifier. |
| `variant_type` | `plain`, `paraphrase`, or `obfuscated`. |
| `source` | Nonempty source identifier/citation. |
| `license` | Nonempty license/provenance declaration; not inferred by the tool. |
| `publishable` | Literal `yes` or `no`; supplied explicitly, never inferred. |
| `timestamp` | ISO 8601 with timezone, canonicalized to UTC. No wall-clock default. |

Unknown or missing canonical fields, missing mapped source keys, duplicate IDs, invalid JSON,
and invalid UTF-8 fail with line numbers and field names, without printing source text.
Inputs must be one JSON object per line. Blank lines are errors; an empty file is valid.
Record order is preserved. Generated IDs depend on the mapped record, not its position in the file.

The output and aggregate manifest are byte-identical on replay with identical input/configuration.
The manifest records version, source/mapping/output SHA-256, record counts, label/family/variant
counts, publication counts, and `evaluator_approved: false`. It contains no text or local paths.
Each file is replaced atomically after validation. The manifest is written last as the completion
marker; readers must verify its output checksum. A crash between replacements may leave an output
with an old manifest; re-running repairs the pair. Concurrent writes to the same outputs are unsupported.
The normalizer keeps an ID set in memory to reject collisions; memory use grows with record count.

This command normalizes the data schema. It does not perform detection-stage Unicode or encoding
transformations, classify prompts, approve labels, deduplicate near matches, or assign splits.

## Attack taxonomy and schema version 2

Version 1 records one free-text `attack_family`. That cannot answer "which delivery channels and
techniques do we miss?" or "where in a long context is the attack?". Version 2 adds three fields and
keeps every base-field contract above. Version 1 files are rejected. The normalizer still accepts only one version per file; the
manifest records `schema_version: 2` and adds `channels` and `techniques` counts.

| Field | Contract |
|---|---|
| `channel` | One value from the channel table. Applies to benign rows too (a benign email is `email`). |
| `techniques` | Sorted, unique list of values from the technique table. Empty if and only if `label` is `0`. |
| `spans` | Where the attack is: list of `[turn, start, end]`, or `null` when unknown. Must be `[]` for benign rows. |

**Channel**: where the text reaches the model. One per row.

| Value | Meaning |
|---|---|
| `direct` | A single user message. |
| `multi_turn` | A conversation; the attack is built up or split across user turns. |
| `document` | Pasted or retrieved document content (RAG, file upload). |
| `email` | An email body or headers the model reads on someone's behalf. |
| `tool_output` | Tool call results, web pages, search results, API responses. |
| `code_comment` | Comments, docstrings or strings inside code the model reads. |

Long context is not a channel: a long email and a long document are both long context, and a channel
field cannot hold both. Length is derived from `text` at report time and bucketed there, so results can
be cut by channel and by length independently.

**Technique**: how the attack works. Many attacks combine techniques, so this is a list.

| Value | Meaning |
|---|---|
| `override` | Tells the model to ignore, replace or reveal its instructions. |
| `roleplay` | Persona, fiction or hypothetical framing to step outside the rules. |
| `encoding` | Encoded, obfuscated or translated text: base64, ciphers, homoglyphs, zero-width, other languages. |
| `delimiter_spoof` | Fake system/role markers, chat-template tokens or end-of-data delimiters. |
| `payload_split` | The instruction is split into parts that are harmless alone (variables, turns, documents). |
| `many_shot` | Many fabricated example exchanges that prime compliance. |
| `named_jailbreak` | A known published jailbreak; `attack_family` holds its name. |
| `novel` | None of the above. The evaluator reviews `novel` rows; a recurring pattern becomes a new value in a schema version bump. |

Rules that tie the fields together:

- `attack_family` identifies reserved held-out families: a specific family (a named jailbreak,
  one generator template, one public source's category), finer than a technique. Benign rows use a benign family name, for
  example `benign-chat` or `benign-quoted-attack` for security text that quotes an attack.
- `techniques` describes the attack as it appears in this row's text. An `obfuscated` attack variant
  therefore includes `encoding`; its `plain` sibling in the same `group_id` may not.
- Hard negatives (benign text that quotes or discusses an attack) are `label: 0`, `techniques: []`,
  `spans: []`. The label describes whether the text attacks the model reading it.
- Public sources rarely say which techniques an item uses or where it is. Their loader must map what the
  source states and use `novel` and `spans: null` otherwise; it must not guess. The evaluator may
  refine these fields later and records that in `label_source`.

**Multi-turn text.** For `channel: multi_turn`, `text` is a JSON array of
`{"role": "user" | "assistant", "content": string}` objects, compact and in order. All other channels
use plain text. Keeping one `text` field keeps hashing, IDs and normalization unchanged.

**Spans.** `turn` is the index into the message array for `multi_turn` rows and `0` otherwise.
`start` and `end` are Python string (Unicode code point) offsets into that turn's text, end exclusive,
with `0 <= start < end <= len`. Spans are sorted and do not overlap. A short direct attack that is the
whole text is `[[0, 0, len(text)]]`. Generators know where they inserted an attack and must record it;
an attack row with `null` spans is excluded from location metrics, not from detection metrics.

## Long contexts: chunking and location

Chunking is part of a scoring run, not of the dataset. Datasets keep the full text and spans; chunks
are derived from them deterministically, so no chunk files are stored and a run can be replayed.

- Each turn is chunked on its own; a chunk never crosses a turn boundary.
- Chunks are fixed windows of `chunk_chars` characters that advance by `chunk_chars - overlap_chars`.
  The last window is aligned to the end of the turn. Turns no longer than `chunk_chars` are one chunk.
  Both values are per-stage run configuration recorded in the run manifest, chosen to fit the stage
  model's input limit and tuned by measurement in `docs/pipeline.md`.
- A chunk is positive if it intersects any span. A span longer than `overlap_chars` is not guaranteed to fit
  entirely in one chunk; the run manifest reports how many such spans there are.
- Row score is the maximum chunk score, so row-level detection and false-positive metrics are
  unchanged for rows that fit in one chunk with the same cached score. Chunk scores are cached per
  `(row id, turn, start)` with the existing per-row score cache.
- Location: an attack row is located if its highest-scoring chunk is positive. Location rate is
  reported over attack rows with known spans, by channel and length bucket.

## Normalizing a source

Normalize local JSONL without downloading data, contacting a model, or changing text:

```sh
uv run python -m data_processing.normalize \
  data/raw/source.jsonl data/normalized/source.jsonl \
  --manifest data/normalized/source.manifest.json --mapping source-mapping.json
```

Omit `--mapping` when the source already uses the canonical schema. Each source adapter is a
small JSON file with `fields` (canonical field to source key) and `defaults` (literal provenance).
Example for a source with `body` and integer `class` fields:

```json
{
  "fields": {"text": "body", "label": "class"},
  "defaults": {
    "label_source": "synthetic-fixture",
    "attack_family": "benign",
    "group_id": "synthetic-group",
    "variant_type": "plain",
    "channel": "direct",
    "techniques": [],
    "spans": [],
    "source": "synthetic-fixture",
    "license": "CC0-1.0",
    "publishable": "no",
    "timestamp": "2026-11-04T00:00:00Z"
  }
}
```

This is an example for synthetic benign fixtures, not provenance to apply to real sources.
Map `id`, family, group, and variant fields from the source when available. If the source has
noninteger labels or a nested schema, convert those explicitly in a source loader before this
command; ambiguous label coercion is rejected.

Raw corpora, environment files, normalized local data, and activation shards are ignored by Git.
The command prints only its aggregate manifest. Frontier agents and dashboards use manifests and
reports; do not inspect or display raw prompt corpora.

## Generation

- Red team produces pairs or triples: plain, paraphrased and obfuscated forms of one attack.
- Cover many attack families: direct override, role-play, encoded payloads, indirect via documents,
  delimiter spoofing, and others.
- Include a large benign set, including benign text that looks like an attack (for example a security
  article quoting one).
- Mix in public datasets and record their citations for the write-up.

To target coverage gaps using aggregate manifests only:

```sh
python3 ops/coverage.py source.manifest.json --targets-output coverage-targets.json
uv run python -m data_processing.generate --model PINNED_CHECKPOINT \
  --timestamp 2026-11-05T00:00:00Z --coverage coverage-targets.json --max 10 --dry-run
```

Coverage sums attack counts across the explicitly selected manifests. Select disjoint datasets
to avoid double counting. A channel/technique pair is selected when either marginal is GAP (zero)
or LOW (1–19); ambiguous channel counts are UNKNOWN and do not establish a gap. These are
**marginal gaps, not measured joint channel/technique counts**. Long-context gaps are not selected:
the generator's existing carrier setting controls length. The JSON contains only `targets`, a list
of objects with `channel` and `technique`; an empty manifest selection produces no targets.

With `--coverage`, generation visits each selected pair once in lexical channel/technique order,
removes duplicates, and stops at `--max` (an alias for `--groups`, default 50). Each request produces
three attack variants and one hard negative, still requiring evaluator approval. An empty target
list returns a zero-request plan without constructing a client or writing output. The target list
participates in the run ID; reordering the JSON does not change replay. Without `--coverage`, the
existing taxonomy/seed cycle is unchanged. Remove `--dry-run` to use the already running endpoint;
neither coverage export nor dry-run needs inference or server operations.

## Splits and hygiene

- Reserved **attack families** appear only in heldout, never in train/dev/test.
- Other attacks and benign rows are assigned by a deterministic hash of `group_id`, keeping all
  variants of a pair together. Adding data never moves existing groups. This permits both classes
  in every evaluation split when enough groups are available; check the manifest counts.
- Leakage trade-off: non-reserved families can occur across train/dev/test/heldout. Dev metrics
  therefore measure new groups within familiar families, not family generalization. Overall held-out
  metrics mix familiar and reserved novel families; use per-family metrics to assess novelty.
  Near duplicates across groups can still leak. Each split reports channel and technique counts
  so coverage gaps remain visible.
- Near-duplicate deduplication is a separate step and is out of scope for the split command.
- Keep a held-out set that is never used for tuning.
- The evaluator approves items into datasets and tracks label source. Only datasets marked publishable
  may be published; a row's `publishable: yes` alone is not approval.

### Splitting

Split a normalized file into train/dev/test/heldout JSONL files:

```sh
uv run python -m data_processing.split \
  data/normalized/source.jsonl \
  --manifest data/normalized/source.manifest.json \
  --config split_config.json \
  --output-dir data/splits/
```

The split config is a small JSON file:

```json
{
  "heldout_families": ["family-a", "family-b"],
  "proportions": {"train": 0.7, "dev": 0.15, "test": 0.15}
}
```

Reserved attack families go to `heldout`. All other rows are assigned by SHA-256 of `group_id`.
The existing three-key proportions remain supported: train and dev retain their configured shares;
the test share is divided equally between test and heldout. For the example above, hash buckets
allocate 70% train, 15% dev, 7.5% test and 7.5% heldout, before adding reserved attacks to heldout.
The first four SHA-256 bytes modulo 100 select a bucket, so proportions resolve to whole percent
buckets (the example's effective test/heldout shares are 8%/7%). Tiny datasets need not contain both
classes in every split. A `group_id` spanning multiple `attack_family` values is an error.
The manifest records `split_version: 2`; iterate.py also hashes the split producer code, so this
change starts a new iteration without changing the live config.

Outputs: `train.jsonl`, `dev.jsonl`, `test.jsonl`, `heldout.jsonl`, and `split_manifest.json` in the
output directory. The manifest contains per-split counts by label, channel, technique, and family, plus
checksums. It contains no text. The command is deterministic and byte-identical on replay.

## Approved source loaders

`data_processing.sources` reads local snapshots only (CSV, Parquet, JSONL, gzipped JSONL,
and LLMail's prompt-to-annotation JSON). It passes converted rows through `normalize.py`.
No model or online dataset loader runs. Download only the approved snapshots, checking the
card license against the approval report first. Supply their pinned revision and snapshot time:

```sh
uv run python -m data_processing.sources deepset data/raw/train.parquet data/raw/test.parquet \
  --output data/normalized/deepset.jsonl --manifest data/normalized/deepset.manifest.json \
  --revision SNAPSHOT_COMMIT --timestamp 2026-11-04T00:00:00Z
```

Input file order is explicit and participates in replay. Revisions and timestamps are supplied,
never guessed; timestamps record the snapshot, not the original prompt creation time. Citations
point to the source snapshot; license and publication declarations follow ticket 0005.

| Source name | Conversion and selection |
|---|---|
| `deepset` | `text`, integer `label` |
| `jackhhao` | `prompt`, explicit `type` (`benign` / `jailbreak`); use the full default CSV once, not overlapping train/test copies |
| `trustair` | `prompt`, boolean `jailbreak`; source community names become families and `named_jailbreak`, otherwise `novel`; use December snapshots once |
| `gandalf` | `text`; the source explicitly contains ignore-instruction attacks (`override`) |
| `spml` | `User Prompt`, explicit `Prompt injection` (`0` / `1`); empty user prompts excluded; system prompts are task context, not the attack text |
| `llmail` | labelled JSON keys are email texts; only boolean `true` or string `True` in `attack_attempt` qualifies; first 50,000 unique qualifying rows in input order; other annotations excluded |
| `dolly` | benign instruction plus nonempty context separated by two newlines; answers excluded |
| `oasst2` | ready tree JSONL; each reviewed, undeleted root-to-leaf path becomes a compact user/assistant array; all paths in one tree share a group |
| `jbb` | catalogues seed counts/checksums; emits an empty scored JSONL, never labels behaviors as attacks |

LLMail uses `email`; OASST2 uses `multi_turn`; other approved sources use their direct prompt
channel. Unannotated attack techniques are `novel` and spans are unknown (`null`); benign rows
have empty techniques and spans. No text-based technique guessing occurs. Source-level benign
approvals are not independent evaluator labels.

Gandalf uses a flat JSON mapping in `src/data_processing/source_mappings/`, merged with the
explicit snapshot provenance. It keeps the source-wide family/group. Other sources need small
conversions for labels, grouping or nested text. Loaders derive other missing groups from text
hashes, use source families where present, and collapse
identical mapped records while reporting duplicate counts. Near duplicates, cross-source
duplicates, conflicting labels and original train/test splits are not resolved here. Group hashing
and reserved-family splits remain a separate step. OASST2 branches containing rejected/deleted nodes are omitted,
not spliced into shorter conversations.

Manifests add loader version, pinned citation, ordered raw-file SHA-256 values, input-row,
duplicate and excluded counts, and the source role. The normalizer's `source_sha256` hashes
the converted intermediate JSONL; `loader.raw_sha256` hashes the original files. Manifests
contain aggregates only and retain `evaluator_approved: false`. The output checksum remains
the completion check. To replay, use the same files, order, loader version, revision and timestamp.

## Synthetic channel and long-context augmentation

After splitting, augment **one split at a time**, offline:

```sh
uv run python -m data_processing.augment data/splits/train.jsonl data/augmented/train.jsonl \
  --dataset-manifest data/splits/split_manifest.json --seed 47
python3 ops/coverage.py data/augmented/train.manifest.json
```

The input filename selects its entry in `split_manifest.json`; checksum, schema-v2 rows,
unique IDs and record count are validated before output is replaced. A single-dataset manifest
with `split` (`train`, `dev`, `test`, `heldout`) and matching checksum/count is also accepted.
An unsplit normalization manifest is rejected: run the split command first.

Original rows remain in order. Each attack gets four synthetic variants: fixed document, email
and tool-output carriers, and a long-context document. Each variant also gets a benign control
with a fixed project note replacing the attack. `source` is `augmented:<kind>` (`long_context`
for the padded variant). SHA-256 of source ID and seed selects start/middle/end insertion;
IDs are deterministic hashes. Spans cover the entire original `text` exactly, in Unicode character
offsets, including serialized multi-turn text when present. Techniques are copied for attacks;
controls have empty techniques/spans. Family and group remain tied to the source attack, including
controls, and the manifest pins their existing split. **Do not re-split augmented output.**

Long variants use 8192 characters of padding drawn from benign rows in the same input file,
repeated in input order and truncated only in the padding. They never read another split.
An attack-containing split without benign rows fails rather than borrowing across splits.
Both padded attacks and their controls exceed 8192 characters. This is a synthetic character
length threshold, not a model token budget or the scoring run's separate length buckets.

The output manifest (`OUT` with suffix `.manifest.json`) is written last, contains no text or
paths, and includes seed, split, input/manifest/output checksums, totals by label/channel/technique/
family, `lengths` and exact `attack_channels`/`attack_lengths`. Length keys are `0-8191` and `8192+`.
`coverage.py` uses these exact attack counts; older manifests retain UNKNOWN where needed.
Files are replaced atomically individually; verify the output checksum before use. Concurrent
writers are unsupported. Rows and output are held in memory.

These are synthetic fixtures, **not real-world channel attacks or evidence of detection quality**.
Labels use `synthetic-augmentation`, evaluator approval is false, and new rows are nonpublishable.
Embedded provenance declarations are retained, with padding license declarations listed for long
variants; augmentation supplies no new publication rights. Independent evaluator review is still
required. The benign controls are structurally matched controls, not independently judged negatives.
