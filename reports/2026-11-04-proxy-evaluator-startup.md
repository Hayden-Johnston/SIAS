# Proxy evaluator startup (ticket 0038)

The persistent proxy now accepts an optional model-to-server-set mapping and evaluator
configuration path. Mapped models route to the configured CPU evaluator without Maya
credentials. Unmapped models retain the existing endpoint and retry behavior.

Managed queues group requests by model in first-submitted group order. Before draining
a group, the proxy checks `/health`; if unavailable, it invokes `ops/servers.py up evaluator`
once and waits for readiness. Startup is serialized by the existing queue lock; the
lifecycle script also serializes process ownership across databases. Completed cache
entries require neither startup nor inference. No shutdown operation was added.

Only the evaluator set is allowed. The proxy rejects all GPU allocations and port 8099
before any health request or lifecycle command; the existing lifecycle script independently
validates its full config before launching. Startup/configuration errors fail all pending
requests for the affected model, preserve unrelated pending work and stop the drain.
This prevents repeated startup attempts for each queued request after a shared failure.

Measured with synthetic HTTP replies and a stub lifecycle command: two distinct requests
for one model produce one `up evaluator` call and two chat calls, including with two
concurrent drainers. An already healthy endpoint produces zero startup calls. Command
failure and readiness timeout each fail both queued requests with zero chat attempts.
Tests cover Maya-set refusal, protected port refusal and each GPU index 0–6.

Validation: `uv run pytest -q`: 327 passed, 1 skipped, 53 subtests passed in 38.43 seconds;
`uv run ruff check`: passed. The model-stage HTTP stub observes request headers as well as client defaults,
matching HTTPX's behavior when credentials are selected per request.

No real model server was started, stopped or modified. No inference, detection, false-positive,
production latency or storage measurements were performed; HTTP attempt latency retains
its prior meaning and excludes startup/readiness time. Routing requires a source checkout
containing `ops/servers.py`. No dependencies or queue schema changes were added.
