# Detect malicious requests
Prompt injection is number one of the top ten OWASP LLM security risks in 2026 and a concern for any inference provider. A successful prompt injection attempt puts client agentic systems at risk of data exposure or worse.
I built this as a drop-in pipeline to detect malicious prompts using deterministic rules alongside classifier models like Jev, Laya, and Clef.

# Benchmarking and training
The first phase of this project is testing different combinations of rules and classifiers for detection.  The goal is to detect 100% of malicious prompts while minimizing false positives.  To optimize the pipeline around this goal, open source datasets will be used alongside synthetic data from a variety of model families.  Beyond benchmarking, a future goal of this project is fine tuning local classifiers for security.  This will be explored once sufficient data has been gathered and validated.

# AI policy
All generated code is function or line sized and reviewed at time of generation.  Most code is hand written with selections from Claude code and Codex.

# Local prototype configuration
Copy `config.example.json` to `config.local.json` and replace the placeholder endpoint, model,
and dataset with your local settings. `config.local.json` is ignored by git and stores the run
counter. Provider entries map an endpoint to `[model, API_KEY_ENV_VAR]`; put the corresponding
key value in `.env`, which is also ignored. Run the prototype from the repository root with
`uv run llm-security`.
