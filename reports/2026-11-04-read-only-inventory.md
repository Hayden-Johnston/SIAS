# Read-only rig inventory

Added `ops/inventory.py` to capture local GPU VRAM, volume headroom, TCP listeners,
running containers, llama.cpp INI model presets and model file/cache sizes. It writes
`data/inventory.json` and prints a short summary. All of `data/` is now ignored because
inventory includes local host and path details. No server or container lifecycle actions
are performed. Maya is queried only when `MAYA_API_KEY` is set; keys and response error
bodies are never saved.

Measured on 2026-11-04: snapshot completed in 0.516 seconds with exit 0 and no collection
errors. Seven GPUs were found, each with about 12 GiB VRAM; GPUs 2–6 had about 11.7 GiB
used each. No Docker containers were running and ports 8081–8085 were down. Port 8099
was listening; Maya's authenticated query was skipped because its key was unset.
Six INI files were read and 46 model entries were found across the two requested roots.

Storage headroom: `/` was 93% used with 16.8 GiB available; `/mnt/storage` was 95% used
with 44.7 GiB available. Both remain above 90% utilization. No storage was reclaimed.
Detection rates and false positives are unaffected; this change performs no inference.

Limits: this is a local snapshot, not a remote-host survey. A listener is not a health
check. INI presets do not prove which model is loaded; device indices are the config's
logical devices, not verified physical assignments. HF repository sizes count unique
inodes across blobs and snapshot links, include all cached revisions and metadata,
and are logical bytes rather than allocated disk blocks. GGUF entries are file sizes,
so split models appear as separate files. Missing commands and inaccessible sources are
recorded as errors; unavailable listener evidence gives unknown server status. External
commands have five-second timeouts, Maya has a three-second socket timeout, and disk
walks stop at a 50-second overall budget between directories; blocked filesystem I/O
can exceed that budget.

Validation: 13 unit tests passed, including fixture parser tests, missing commands,
down servers, Maya skipping/failure and HF symlink deduplication. Ruff passed.
