# Prototype local configuration and packaging

Moved the tracked prototype configuration to ignored `config.local.json` and supplied
`config.example.json` with placeholder endpoint, model, dataset, and key environment-variable
name. Key values remain in ignored `.env`. The CLI reads and increments the local configuration;
README documents setup. Existing local settings were preserved in this checkout.

Configured uv_build to include `llm_security`, `data_processing`, and `llm_proxy`, with explicit
package markers for the latter two. No inference logic or server lifecycle behavior changed.

Validation: `uv run pytest -q` passed (16 tests); `uv run ruff check` passed.
`uv run python -c 'import llm_security.pipeline'` succeeded. `uv build --wheel` succeeded;
archive inspection confirmed all three packages. Tests stub dataset loading and pipeline execution
and verify local config selection, run-counter persistence, and missing-config failure.
Tracked IPv4 matches after removing the old config are only loopback and wildcard bind addresses.
No model servers or datasets were contacted. Detection, false positives, and inference latency
were not measured because this change only affects configuration and packaging.

This removes configuration from the current tree, not from existing git history.
