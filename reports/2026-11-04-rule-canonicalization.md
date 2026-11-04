# Rule canonicalization (ticket 0036)

Added `canonicalize(text)` in `rules.py`, keeping the existing producer-file hash
sufficient to version the scorer. NFKC, format-control removal (including zero-width
and bidi controls), case folding and the existing limited homoglyph table now
surround one nonrecursive decoding pass. Supported spans are standard padded or
unpadded base64, contiguous hex with optional `0x`, and explicitly marked `rot13:`
text through the end of its line. Minimum candidates are two base64 quartets or
four hex bytes. Only printable UTF-8 text, allowing newline/tab/carriage return,
replaces an encoded span. Invalid/binary data remains unchanged. No execution,
inference, dependencies or server operations were added.

Rules score both original and canonical views and retain the maximum, preserving
weak original encoding signals. Chunking still happens on original text before
canonicalization; dataset text, spans and cache coordinates are untouched.
Tests cover encoded chunk location replay, malformed/nonprintable data, benign
controls, case-sensitive base64, nonrecursive decoding and maximum-score behavior.
README already describes normalization before rules and requires no change.

Measured against baseline `8eef778` on synthetic fixtures only:

| Variant | Baseline score | New score |
|---|---:|---:|
| Zero-width/bidi split keyword | 1.0 | 1.0 |
| Cyrillic homoglyph | 1.0 | 1.0 |
| Base64 padded / unpadded | 0.25 / 0.25 | 1.0 / 1.0 |
| Bare / prefixed hex | 0.25 / 0.25 | 1.0 / 1.0 |
| Marked ROT13 | 0.0 | 1.0 |

These seven variants use the benign sentence in
`test_canonical_scoring_raises_obfuscated_keyword_score`; they test rule activation,
not attack detection accuracy. The first four plain benign controls in
`test_benign_and_invalid_encodings_unchanged` scored zero before and after.
No held-out detection or population false-positive improvement is established;
decoding can expose rule phrases in benign encoded material too.

Local timing used those seven variants plus four controls, 1,000 sequential loops
per repeat, five repeats, median elapsed time divided by 11,000 scores:
16.28 microseconds/text before, 35.16 after (about 2.16 times baseline).
Reproduce using `timeit.repeat` over the listed fixtures, loading baseline `score`
from `git show 8eef778:src/data_processing/rules.py` and current `score` separately.
This short-text microbenchmark excludes I/O; it is not a dataset latency estimate.
Cache fields and storage layout remain unchanged; no dataset cache size was measured.

Verification: `uv run pytest -q` and `uv run ruff check` (final results recorded in
the ticket log). Targeted rules suite: 65 passed.
