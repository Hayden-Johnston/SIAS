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
The existing prototype `DataHandler` is unchanged; it still uses its original online loader.

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

- `attack_family` stays the split unit: a specific family (a named jailbreak, one generator template,
  one public source's category), finer than a technique. Benign rows use a benign family name, for
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

## Splits and hygiene

- Split by **attack family**, not randomly. All variants of a pair stay in the same split.
- Assignment is deterministic: a split config lists held-out attack families explicitly; other attack
  families and all benign `group_id`s are assigned by a hash of the name, so adding data never moves
  existing rows. Each split reports its counts by channel and technique, so a gap (no `email` attacks
  in held-out, say) is visible before any number is quoted.
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

Attack rows are assigned by `attack_family`; benign rows by `group_id`. Held-out families go to the
`heldout` split. Other families and benign groups are assigned by SHA-256 of the name to train/dev/test
according to the proportions. A `group_id` that spans multiple `attack_family` values is an error.

Outputs: `train.jsonl`, `dev.jsonl`, `test.jsonl`, `heldout.jsonl`, and `split_manifest.json` in the
output directory. The manifest contains per-split counts by label, channel, technique, and family, plus
checksums. It contains no text. The command is deterministic and byte-identical on replay.
