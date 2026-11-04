# Datasets

## Schema, version 1 (one for every source, public and generated)

Every row contains exactly these fields:

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
- Dedupe near-duplicates before splitting.
- Keep a held-out set that is never used for tuning.
- The evaluator approves items into datasets and tracks label source. Only datasets marked publishable
  may be published; a row's `publishable: yes` alone is not approval.
