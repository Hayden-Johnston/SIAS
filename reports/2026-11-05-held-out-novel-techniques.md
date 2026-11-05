# Held-out techniques absent from development

Ticket 0048 adds `slices.novel_technique` to replay manifests and a separate table
beside the existing Metrics slice table. Each entry reports the technique, fused
TPR (`detection`), two-sided 95% Wilson interval, denominator `n`, and
`small_sample` when n < 20. The purpose is to distinguish techniques absent from
dev from the broader technique results, independently of the taxonomy label `novel`.

For an existing held-out replay config, add:

```json
"split_manifest": "splits/split_manifest.json"
```

The path is relative to the run config and points to the schema-v2 aggregate
manifest produced by `data_processing.split`. Its `splits.heldout.output_sha256`
must match the evaluated dataset checksum. Its `splits.dev.techniques` supplies
development counts; missing technique keys mean zero, while missing/invalid dev
counts fail validation. No dev payload file is opened. The entire split manifest
hash is included in run identity, and runner version advances to 5. The input is
protected against output overwrite, like other run inputs.

The slice is a sorted list of held-out techniques with zero dev rows. An empty
list means no unseen techniques were observed. Without the optional input,
`novel_technique` is null; old manifests and non-held-out runs display an
unavailable comparison. Configuring the input on a non-held-out run fails.
Multi-technique rows count once per matching technique even if another technique
on the row was seen in dev. Counts overlap; benign rows never contribute.
Existing technique slices retain all observed techniques for comparison.

Measured synthetic fixture: with `novel` seen in dev and `encoding` absent, the
encoding slice reports 1/1 detected (TPR 1.0, Wilson interval approximately
[0.207, 1.0], n=1, small sample). When both techniques are absent, encoding remains
1/1 and novel reports 1/2 (TPR 0.5, interval approximately [0.095, 0.905], n=2).
When both are seen, the slice is empty. Tests also cover n=19/20, deterministic
replay, identity changes, invalid counts, checksum mismatch, and dashboard field
projection without extraneous text.

Validation: `uv run pytest -q` passed (393 tests, 1 skipped, 57 subtests);
`uv run ruff check` passed. Optional Playwright browser tests were attempted but
all five could not launch Chromium because `libatk-1.0.so.0` is unavailable.
The browser test for slices now checks populated, empty and unavailable novel
technique states; these assertions still need execution on a browser-capable host.

No inference or server lifecycle actions were performed. Detection decisions,
false positives and cached stage latency are unchanged. No real-data detection
improvement or replay latency benchmark is claimed. Storage adds one compact
entry per unseen technique, reusing existing rate calculations. Dev counts are
trusted aggregate declarations, not proof of split hygiene. The checksum check
requires the complete held-out dataset matching that split manifest; existing
sampled iteration runs are not automatically wired to this optional input.
`augment.py` and `iterate.py` are unchanged.
