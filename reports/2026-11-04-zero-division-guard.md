# 2026-11-04: Guard zero division in measure_results

## What changed

`measure_results` in `src/data_processing/measurements.py` now returns `None` for undefined
rates instead of raising `ZeroDivisionError`. A `_safe_div` helper returns `None` when the
denominator is zero. `average_time_ms` is `0` for empty input.

## Why

Empty result sets, all-benign runs, and all-attack runs are valid inputs. The previous
behavior made `measure_all` crash on any run directory containing such a batch, blocking
the rest of the pipeline.

## Measured effect

- No change to defined metrics (all existing tests pass unchanged).
- Previously crashing inputs now produce JSON-serializable output with `null` for undefined rates.
- 221 tests pass, 0 new.
