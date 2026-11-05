# Optional CPU classifier scoring in iterations

Ticket 0079 adds `cpu_classifier_run` to `ops/iterate.py`. Omit it to retain the
existing workflow, including the optional precomputed `cpu_classifier` caches.
The two classifier settings are mutually exclusive. Example local setting:

```json
"cpu_classifier_run": {
  "config": "model-stage.local.json",
  "server_config": "evaluator.local.json",
  "threshold": 0.5
}
```

Both paths resolve relative to the iteration config. `config` uses the existing
`data_processing.model_stage` settings: pinned non-GLM checkpoint, declared
parameter count, chunk size/overlap and a loopback `/v1` base URL. `server_config`
uses the existing `ops/servers.py` evaluator configuration. Actual pending calls
route exclusively through that configuration's CPU evaluator endpoint; the model
stage's base URL is validated but never called directly by the exporter.

The exporter runs replay-only, submitting deterministic chunk requests into an
iteration-local SQLite queue. On a cache miss, the existing proxy drains that
queue with the checkpoint mapped to `evaluator`. The proxy alone checks readiness
and invokes `ops/servers.py up evaluator` when needed. There are no shutdown calls
or Maya lifecycle changes. Export then replays the completed responses. Refusals,
persisted failures and invalid labels stop the iteration without completion.

CPU scoring uses exactly the existing deterministic capped Maya datasets (at most
25 rows per split). Long rows can require multiple chunk calls; the row cap is
not a chunk request cap. The completion manifest records row/chunk counts, cache
hashes and original cached latency. The existing dev-only sweep fits fusion with
the classifier, plus a separate fusion without it, on the same samples. Both
have numbered run manifests with independent stage metrics, confusion counts and
Wilson intervals; the iteration summary nests the comparator under
`fusion.without_cpu_classifier`. Available activation probes participate in both.

Model settings, evaluator config and producer code participate in iteration
identity. Score/summary checkpoints and the response queue support resume; even
re-exporting after removing the score/summary checkpoints requires no HTTP when
responses are cached. Cached latency measures original request work, not replay.

## Measured synthetic validation

A deterministic synthetic fixture scored 14 dev rows (8 attacks, 6 benign) and
4 held-out rows (2 attacks, 2 benign), each with one chunk. The fake CPU endpoint
returned the fixture labels; fake Maya returned benign. This validates wiring,
not model quality. Held-out fusion with CPU detected 2/2 attacks (100%, Wilson
95% CI 34.24–100%) with 0/2 false positives (0%, CI 0–65.76%). Fusion without CPU
detected 0/2 (0%, CI 0–65.76%) with the same false positives.

One observed mocked-HTTP run recorded 1.702 ms total dev CPU latency and 0.395 ms
held-out latency. These are test transport timings, **not CPU inference latency**.
Replay reproduced the recorded summaries with HTTP and managed draining disabled.
The fixture requested evaluator startup once; no real server was started. Actual
local-model detection, false positives, latency and storage cost remain unmeasured.
Storage adds a local request/response queue, score/summary caches and two comparator
run directories. No datasets or payload text are committed.

Validation: full `uv run pytest -q` passed (608 passed, 1 skipped, 64 subtests
passed). After adding the explicit option-omitted regression, config tests passed
(60 tests). `uv run ruff check` passed. Staged diff review and secret-pattern scan
passed before commit.
