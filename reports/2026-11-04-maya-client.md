# Queued, cached Maya chat client

Implemented ticket 0016 with a small synchronous `llm_proxy.Client` API:
`submit_batch`, `drain`, and `result`. One SQLite file persists the FIFO queue,
request bodies, cache outputs, attempt counts, sanitized errors and cumulative
HTTP attempt latency. Cache keys include the model, message hash and all generation
parameters. A file lock serializes drainers using the same database. No dependencies
were added and no server lifecycle actions were taken.

The client reads the API base URL and credential from `.env` or the environment.
Transport errors, 429 and 5xx responses use bounded exponential backoff. Exhausted
transient failures remain pending for an explicit later drain; permanent failures
and explicit refusals become failed and stop the current drain. Completed jobs are
replayed without HTTP. A crash before committing a response can repeat inference;
this is not an exactly-once server protocol. Separate database files do not share a
concurrency limit, and model checkpoint identity must be reflected in the model ID.
Streaming is unsupported.

## Measurements

- Fake HTTP server tests verify persistence, key sensitivity and canonicalization,
  FIFO order, duplicate suppression, replay without HTTP, retries/backoff, permanent
  failure/refusal handling and two concurrent drainers. Transport failure and `.env`
  behavior are also tested. All fixtures are synthetic benign chat messages.
- One live benign chat completion succeeded against the already running Maya:
  one HTTP attempt, one choice, 10.8803 seconds of HTTP latency. The immediate cached
  drain completed zero new jobs. No model output or credentials are included here.
- The smoke SQLite file occupied 12,288 bytes for one request and response, excluding
  filesystem overhead and its empty lock file. It lives outside the repository.
- Detection and false-positive rates are unchanged/unmeasured: this ticket adds an
  inference client, not a detector. The single live call is a connectivity check,
  not a latency benchmark.

Validation: `uv run pytest -q` passed (144 passed, 1 skipped, 39 subtests passed);
`uv run ruff check` passed. Nine client tests cover the behavior above.
