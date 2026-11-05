# Maya classifier: fail closed on non-binary output

Scheduled iterations 3 and 4 aborted in the Maya stage: of 27 cached responses, one was a single
character other than `0`/`1`, and `ops/iterate.py` treated any such output as fatal. One bad answer
should not discard a whole iteration, and a classifier knocked off its output format by the text it
is classifying is itself a signal of injection.

Change: any output other than exactly `0` or `1` is scored `1` (attack, fail closed) and counted in a
`*-maya-scores.invalid.json` sidecar; the iteration report prints the count. Cache rows keep the
`{id, score, latency_ms}` shape, so `run.py` is unchanged. Cached responses are reused; no extra
inference. Tests: the invalid-output test now asserts fail-closed scoring and the count.
