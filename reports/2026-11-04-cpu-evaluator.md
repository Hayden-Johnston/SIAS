# CPU candidate evaluator

Ticket 0018 adds `python -m data_processing.evaluate`. It verifies a candidate checksum and
schema before inference, requests independent label/channel/technique predictions, and admits
only exact matches to a normalized dataset with `label_source: evaluator`. IDs, text, spans and
publication declarations stay unchanged. The aggregate completion manifest includes approval
rate, rejected count, per-field disagreements, HTTP latency and dataset checksum. Per-field
counts can overlap. This measures model agreement, not ground-truth labeling accuracy.

The selected inventory checkpoint is Qwen3.5-2B Q4_K_S (1,217,757,440 bytes), independent of the
GLM generator. A loopback llama.cpp child uses `--device none`, zero GPU layers, a 16,384-token
context, four CPU threads and one slot. Requests disable thinking through the chat-template
parameters so the short response budget is reserved for JSON labels. GPU visibility is cleared.
Only this child is terminated, including on inference/startup errors. The existing servers and containers are untouched.
Inputs exceeding the context fail instead of being silently shortened.

The queue persists responses under a run keyed by input, code, checkpoint and binary hashes.
A complete replay starts no server. Failed jobs stop before draining; malformed labels produce
no completion manifest. The local queue contains text and must not be committed. No dependencies
were added. Publication approval, span validation and integration into scheduled iterations are
outside this change.

## Validation

Fake-model tests cover agreement and overlapping disagreements, retained provenance, byte-identical
replay, checksum and duplicate-ID rejection before submission, empty input, invalid output,
refusals, CPU launch arguments, startup failure, and shutdown on success/failure.

Final checks: `uv run pytest -q` passed 219 tests (1 skipped, 48 subtests);
`uv run ruff check` passed. Staged changes were reviewed and scanned for private keys,
common credential formats and credential assignments before commit.

A live CPU smoke run used the four harmless synthetic strings from the evaluator test fixture,
with generator-provisional labels (three attack variants and one benign row, all direct).
No generated attack corpus was available locally. The run approved 0/4 (0%); disagreements
were label 3, channel 4 and techniques 3. The model classified all four as document content.
This exposes a channel-classification limitation on these tiny fixtures; it does not establish
accuracy on generated attacks. Fake-model coverage separately proves agreeing rows are admitted
(3/4 approved, with one rejection disagreeing on all three fields).

Measured live results:

| Measurement | Result |
|---|---:|
| Wall time including load, inference and teardown | 20.57 s |
| Cached HTTP inference time, four requests | 14.84 s |
| Peak child RSS | 2,329,476 KiB (2.22 GiB) |
| Replay wall time including weight hashing | 0.80 s |
| Final run dataset, manifest and queue files | 78,935 bytes |

The child endpoint was unreachable after drain; replay returned the identical manifest with
server startup forbidden. Detection rates, false positives and long-context quality were not
measured. The initial smoke checks correctly rejected empty responses (thinking consumed the
budget) and an unexpected JSON field. Final requests disable thinking and use JSON-schema
constrained decoding; strict validation remains in place.

Live run ID: `4e0c64fe874fdc2540981e71df87e8c19ca4b2e980fc67c6bb98bf29cd69325f`.
The manifest pins input/code/weight/binary SHA-256 digests. The local llama.cpp source archive was
`llama-9dcf84e5a.tar.gz` (SHA-256
`bb0a5ceaf66f0b2d44c5d7b2d62b2c2eaab5f015642116a35d8edeeeab775ada`); the binary reports
0.4.0-dev, build 0, commit unknown, GNU 11.4.0.
It was built with CMake Release, HIP/CUDA/Vulkan disabled, tests/examples disabled, and
OpenSSL/CURL disabled; target `llama-server`, build parallelism 2. Build artifacts and local
smoke queues remain outside Git. No existing server or container was stopped or restarted.
