# CPU model chunk score cache

Ticket 0033 adds a standalone model-stage cache producer for an already running CPU llama.cpp
endpoint. It validates a declared non-GLM checkpoint of at most 4B parameters, requires explicit
loopback endpoint configuration, refuses port 8099, and never manages servers. The operator remains
responsible for verifying actual model size and CPU placement.

The producer uses the existing persistent chat queue for deterministic model/instruction/text/
generation-setting keys. A small optional endpoint/authentication argument in `llm_proxy.Client`
avoids using Maya settings or credentials for classifier requests. Existing Maya callers retain
their defaults. Chunk coordinates and exported fields match the rule cache and replay runner;
no runner schema change, inference path or `ops/iterate.py` change is needed. README and pipeline
documentation explain adding the optional stage, resuming, and replay-only export.

Synthetic HTTP-stub measurements:

- Two unique chunks require two requests initially; repeated export and replay-only export require
  zero additional calls and preserve score-cache bytes, hashes and cached latency.
- An interruption during the second request leaves the first completed response intact. Resume
  makes one call, repeating only the interrupted request. Independent queues produce identical keys.
- A four-entry multi-turn fixture (empty turn plus three identical full-width chunks) requires
  two requests because duplicate chunk text shares a cached response.
- Replay of one synthetic attack and one benign row reports TP=1, TN=1, FP=FN=0. Detection is
  1/1 with a 95% Wilson interval approximately [0.206549, 1]; false positives are 0/1 with interval
  [0, 0.793451]. The known attack location is found. These are plumbing tests, not model quality
  measurements, evaluator approval, or evidence toward the detection targets.

Tests also cover model/prompt/text key changes, configuration and dataset validation before HTTP,
environment precedence, credential isolation, invalid labels, persisted refusal handling,
replay-only cache misses, multi-turn coordinates, empty input, and aggregate-only CLI output.

Validation: `uv run pytest -q` passed (283 passed, 1 skipped, 48 subtests passed);
`uv run ruff check` passed.

No real inference or server lifecycle changes were performed, and no production datasets were read.
CPU inference latency,
real detection and false-positive rates, and production storage growth are unmeasured. Storage
consists of a local SQLite request/response queue and one JSONL entry per chunk; replay reads only
exported scores. Latency reports preserve measured HTTP time from the original cached requests,
reused for duplicate chunks, rather than measuring export or replay time.
