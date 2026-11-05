# Replay-only leave-one-stage-out fusion report

Added `data_processing.ablation` beside the fusion sweep. It refits the full fusion
and each stage removal using validation caches, the existing `{0, 0.5, 1}` grid,
observed FPR cap and deterministic tie-breaking. All fits finish before held-out
inputs are read. Sweep scoring, selection and stage-setting comparison are shared
without changing sweep behavior. No dependencies, inference or server operations
were added.

JSON records full and removed-stage weights, dev and held-out confusion counts,
rates with denominators and 95% Wilson intervals, input identities and approval
flags. Held-out deltas are removed-stage fit minus full fit; these are point
estimates with null for undefined rates. Output is atomic and cannot overwrite
inputs. README and pipeline documentation describe the command and limits.

Synthetic measurements (two attacks and two benign rows per split):

- Complementary stages fit full weights `(0.5, 1)` with dev detection 1 and FPR 0.
  Held-out detection is 1 and FPR 0.5. Removing stage a gives detection 0.5 and
  FPR 0: both deltas are -0.5. Removing b gives detection 0.5 and FPR 0.5:
  detection delta -0.5, FPR delta 0.
- Identical stages fit `(0, 1)`; removing b refits a to weight 1, preserving
  detection. This verifies refitting rather than simply deleting a fitted weight.
- Repeated API/CLI runs produce identical JSON bytes. Tests verify all dev fits
  precede any held-out read, held-out changes preserve fitted weights, undefined
  rates stay null, and invalid inputs preserve existing output.

These are replay correctness measurements, not real-world detection evidence.
No production datasets were read or scored. Latency and storage were not
benchmarked; the only new artifact is an optional aggregate JSON file. Dev work
is `3 ** stage_count + stage_count * 3 ** (stage_count - 1)` grid candidates.

Validation: `uv run pytest -q` passed (589 passed, 1 skipped, 64 subtests);
`uv run ruff check` passed. Staged diff review and secret-pattern scan passed.
