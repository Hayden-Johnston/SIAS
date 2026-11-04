# Datasets

## Schema (one for every source, public and generated)

id, text, label, label source, attack family, pair/variant group id, variant type (plain, paraphrase,
obfuscated), source, license, publishable (yes/no), timestamp. Each source gets a loader into this
schema.

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
  may be published.
