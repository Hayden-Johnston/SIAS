# Benign near-miss FP tests for persona/safety rules (0082)

Added 25 benign near-miss test cases to `tests/test_rules_benign.py` covering
the persona/safety rule features from ticket 0072. Categories: security training
text, role-play fiction, persona descriptions, and safety policy discussion.

16 cases pass cleanly (score 0.0). 9 cases are documented xfails where the
current rules false-positive at 0.75:

- 6 trigger the safety-suspension rule (patterns: "no content restrictions",
  "no safety constraints", "no ethical rules", "without any safety filters",
  "free from all moral constraints", "no content rules")
- 2 trigger the refusal-suppression rule ("never refuse ... questions",
  "never refuse a request")
- 1 triggers the persona-switch rule ("act as ... unrestricted")

These xfails document known false positives for Claude to address in a future
ticket. No changes to `rules.py`; no behavior change to scoring.

Validation: `uv run pytest -q` passed (605 passed, 1 skipped, 9 xfailed,
64 subtests); `uv run ruff check` passed.
