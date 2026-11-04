# CPU evaluator launch and teardown (ticket 0034)

Added `ops/servers.py` with `up|down|status evaluator`, a local JSON config and a
public example. This gives the proxy/operator a standalone lifecycle command for
one CPU llama.cpp evaluator without changing the candidate-evaluation workflow.
No dependencies were added.

The script accepts no other sets or extra launch options. It refuses port 8099
and all GPU allocations, including protected GPUs 2-6 and reserved GPUs 0-1.
It fixes CPU flags, clears GPU visibility and removes inherited `LLAMA_ARG_*`
overrides. Host, port, binary, model and storage location come from config;
only loopback hosts are accepted.

A storage-directory lock serializes lifecycle commands. PID records include
process start ticks, command and boot identity. Shutdown verifies that identity
and uses a Linux pidfd to avoid signaling a reused PID. It sends SIGTERM only to
the recorded process, retaining ownership on a ten-second timeout. There is no
port-based, name-based or process-group teardown. `status` checks process
existence; HTTP readiness is not measured. Launch catches immediate failures
with a 0.1-second observation interval, not a model-loading readiness wait.

Validation used only a synthetic executable that records arguments/environment
and sleeps. Sixteen tests cover idempotent launch, shutdown, an unrelated live
process, stale PID identity, CPU enforcement despite inherited overrides,
protected port/GPU rejection, failed launch and CLI dispatch. The full suite
passed: **261 passed, 1 skipped, 48 subtests passed**. `uv run ruff check` passed.

No real model server or container was started, stopped or inspected for this
change. Detection, false positives and inference latency are unchanged and were
not measured. Storage adds one lock, one small PID JSON record while running,
and an append-only server output log; log growth is not capped. CPU/RAM use and
real-model startup/shutdown latency remain unmeasured.
