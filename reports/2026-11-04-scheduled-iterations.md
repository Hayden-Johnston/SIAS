# Scheduled end-to-end iterations (ticket 0019)

Added `ops/iterate.py` and a six-hour `pipeline` dispatcher worker. The worker runs Python directly,
without an agent prompt, and shares the dispatcher's timeout, logs, running-state and STOP behavior.
It is enabled by an orchestrator-owned, gitignored `iterate.local.json`; the example and README
list its explicit source snapshots, split policy, cap, model ID, generation limit and thresholds.
The integration configuration is deliberately left to Claude as required by AGENTS.md.

The script hashes ordered source bytes, configuration and producer code. A new identity receives a
monotonic iteration number; identical reruns reuse it. An exclusive nonblocking lock prevents
concurrent writers. Loader/normalizer/split outputs, deterministic hash-selected samples, rule
caches and model caches checkpoint separately. A crash resumes the same number and timestamp.
Model requests use the persistent proxy queue; committed responses replay without inference.
Rules preserve their original measured latencies on resume. Completed iterations are no-ops.

Both validation (`dev`) and held-out (`heldout`) runs evaluate the same capped dataset at both
stages. No default score is supplied for unsampled or failed model requests. The classifier uses
whole stored text, temperature zero, and exact binary output validation; its model/cache version
includes the configured token budget. Failed persisted requests stop before draining more jobs.
Replay stays inference-free. Numbered flat run directories match the dashboard's manifest reader;
the script also writes one dated aggregate report per iteration and a local completion summary
with full split counts and the per-split cap.

No dependencies, model lifecycle actions, server/container operations, red-team generation or
label approval were added. This ticket's Maya classifier is an exploratory baseline, not the
independent evaluator or a tuned decision model. Results retain `evaluator_approved: false`.
The served ID must identify the checkpoint; operators must bump the pipeline version if weights
change behind a reused ID. Source labels, small samples and conservative source-wide families
cannot establish the project's population targets. Held-out splits can contain no benign rows
under the existing splitter; undefined rates remain null.

## Validation

- Synthetic integration tests exercise both split manifests through the current dashboard reader,
  capped counts, byte-identical reruns without rule scoring/inference, source refresh to the next
  iteration, interrupted model scoring/resume, permanent failure before drain, invalid classifier
  output and invalid caps. Dispatcher tests exercise six-hour timing, absent configuration,
  STOP, prompt-free subprocess launch, and accounting for just-reaped runs before scheduling.
- `uv run pytest -q`: 180 passed, 1 optional browser test skipped, 48 subtests passed.
- `uv run ruff check`: passed.

## Live smoke measurements

Used the already loaded `glm-5.3-flash` through the proxy, with 128 output tokens maximum,
temperature zero and a cap of two rows per split. The pinned JackHhao snapshot produced 1,976
normalized rows: 927 train, 211 dev (benign), 185 test (benign), and 653 heldout (attacks).
Heldout was explicitly the source-wide attack family. This smoke configuration intentionally
bounds inference; it is not a balanced validation design or a meaningful estimate of generalization.

Four requests completed in four HTTP attempts, 366.186 seconds cumulative HTTP latency (91.547
seconds/request). No refusals or retries occurred. Validation: TN=2, FP=0, with FP Wilson 95% CI
[0, 0.657620]; detection undefined (no attacks). Held-out: TP=2, FN=0, with detection Wilson 95% CI
[0.342380, 1]; FP undefined (no benign rows). Both stages' cached latency and reached/caught counts
are in the run manifests; these are not end-to-end wall-clock latency benchmarks.

The initial smoke used iteration 1. After the final producer-code adjustment, iteration 2 refreshed
local artifacts and reused the four cached responses in 0.433 seconds without additional HTTP
attempts. Its immediate identical rerun took 0.00318 seconds, preserved every run/checkpoint byte,
and retained four total HTTP attempts. The two iterations and checkpoints occupied 26,129,983
logical bytes; the queue occupied 24,576 bytes, excluding lock files and filesystem overhead.
The script's dated per-iteration aggregate reports are committed alongside this report.

A temporary instance of the current dashboard served `/api/state` with HTTP 200 and all four live
run manifests (two splits per iteration), then shut down. The existing service on port 8300 still
returned an empty metrics list for the same manifests. Its loaded deployment needs investigation
or reload by the integrator; it was not restarted here. No model server was started/stopped.

Staged changes were reviewed and scanned with detect-secrets 1.5.0; no findings.
