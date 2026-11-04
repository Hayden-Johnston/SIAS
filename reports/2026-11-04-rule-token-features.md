# Rule token features: negative result; chunk cache export retained

Ticket 0028. **Do not merge these detection weights on the current evidence.**
Validation and held-out detection did not improve, and validation false positives increased.
Claude rejected the feature changes on 2026-11-04: the final implementation retains only
optional chunk cache export and restores the baseline scorer. Features are deferred until
evaluator-approved validation data exists. No tuning followed this measurement.
The measurements below document the rejected candidate, not the final implementation.

## Change

The rejected candidate added three named, deterministic CPU token features without
dependencies or inference:
`role_override` (0.9), `assistant_refusal_suppression` (0.75), and
`instruction_density` (0.25). Their clause boundaries, token distances, verb lists and weights
were explicit in the candidate source (commit `f1d0846`). Existing regex scores remained.
Maximum strength wins; repetition and weak features cannot accumulate into a catch.
Density remains weak because ordinary benign task lists are directive-heavy.

Added optional `chunk_chars`/`overlap_chars` arguments and CLI flags. The scorer uses the
runner's windows and emits its existing `(id, turn, start)` cache contract, slicing original
text before normalization. Row-cache callers remain compatible. The producer file hash
versions all feature changes; runner schema and chunk coordinates did not change.
`ops/iterate.py` was not modified. README and cache documentation describe the new options.

## Measurement

Frozen features, threshold 0.75 (the existing scheduled rule threshold), windows 4096 characters,
overlap 512. Both versions scored identical chunks; the baseline uses the old `score` function
inside the new chunk writer. Thus this compares features without confounding window changes.
Scores were produced locally and evaluated by `data_processing.run.replay`; no model or server
was used. Four runs are stored under `$SIAS_DATA/runs/rules-0028/`, with configs, pinned caches,
results, manifests, split manifests and aggregate `summary.json`.

Sources, in order: deepset, dolly, gandalf, jackhhao, llmail, oasst2, spml, from the local
normalized snapshots recorded in `reports/dataset-manifests/2026-11-04-*.json`. Split config:
`{"heldout_families":["jackhhao/jailbreak-classification"],"proportions":{"train":0.7,"dev":0.15,"test":0.15}}`.
The held-out family matches the existing iteration setup. Each source was split separately
using `split.py`; corresponding dev/heldout files were concatenated in source order and
normalized for replay. No sampling or text inspection occurred.
TrustAIR was excluded before scoring: its source contains 23 group IDs spanning multiple
families, rejected by the split tool. No labels/groups were repaired or approved here.

Validation has 13,337 rows: 1,000 direct attacks, all Gandalf, and 12,337 benign rows
(9,245 multi-turn OASST2, 2,325 Dolly, 494 SPML, 211 Jackhhao, 62 deepset).
Held-out has 653 direct Jackhhao attacks and **no benign rows**, so its FP rate is undefined.
Family assignment is deterministic; neither split was used to tune this candidate. These
source-label datasets have `evaluator_approved: false`; near duplicates and label quality
are unresolved, and these intervals do not establish population performance. No measured
source attack has known spans, so location accuracy is only covered by synthetic tests.

Rates below are percentages with two-sided 95% Wilson intervals from the replay manifests.

| Split / version | Detection (TP / attacks) | False positives (FP / benign) |
|---|---|---|
| Validation before | 49.70% (497/1000), [46.6082%, 52.7941%] | 0.008106% (1/12337), [0.001431%, 0.045903%] |
| Validation after | 49.70% (497/1000), [46.6082%, 52.7941%] | 0.016211% (2/12337), [0.004446%, 0.059095%] |
| Held-out before | 18.6830% (122/653), [15.8797%, 21.8526%] | undefined (n=0) |
| Held-out after | 18.6830% (122/653), [15.8797%, 21.8526%] | undefined (n=0) |

The extra validation false positive is a regression even though the small difference does
not establish a statistically significant FP increase. Neither detection comparison improves,
so the merge gate fails independently of how “material” FP worsening is interpreted.
Both validation FP upper bounds exceed the project's 0.02% target.

| Split / version | Cache entries | Mean scoring ms/chunk | Total scoring ms | Cache bytes |
|---|---:|---:|---:|---:|
| validation-before | 36731 | 0.177768 | 6529.613 | 4421011 |
| validation-after | 36731 | 0.218514 | 8026.251 | 4423978 |
| held_out-before | 731 | 0.921301 | 673.471 | 92949 |
| held_out-after | 731 | 1.095258 | 800.634 | 92954 |

One serial before/after measurement, without timing confidence intervals; latency covers
chunk slicing, Unicode transformations and scoring, excluding validation and I/O.
Validation scoring increased about 23%; held-out scoring increased about 19%.
Memory scales with cache entries and row IDs. Cache sizes include measured latencies and
will vary on regeneration; replay of pinned cache bytes is deterministic.

Dataset SHA-256:

- Validation: `05e95ac9a96603174f8a6f2bccef39a79f9b8421c1ebbeb55ccde5ec3a51bf79`
- Held-out: `60c333460b257a2cfcd97516135cc00249c6f390d23194de93815fee218ad833`

Producer SHA-256:

- Before: `80e37cbc00d72bfd5c09abf80acdfb42b4a26f96eb99b320c244e27f2a0a806b`
- After: `250c7e7e5434b5bfc11f8b9f03bfc9c606bc7d665b099b640c655c40837d28ca`

## Reproduction

Set `SIAS_DATA` to the storage root containing the pinned normalized snapshots. The following
rebuilds the same splits/caches and replays all four comparisons, printing aggregates only.
It does not inspect corpus text interactively. Baseline source comes from the integration
commit used for this ticket; candidate source is pinned before feature removal. Timing and
cache hashes will differ.

```sh
git show 65e326c:src/data_processing/rules.py > /tmp/sias-0028-baseline.py
git show f1d0846:src/data_processing/rules.py > /tmp/sias-0028-candidate.py
uv run python - <<'PY'
import importlib.util
import os
import json
from pathlib import Path
from data_processing import normalize, run, split

root = Path(os.environ['SIAS_DATA'])
work = root / 'runs/rules-0028'
work.mkdir(exist_ok=True)
config = {'heldout_families': ['jackhhao/jailbreak-classification'],
          'proportions': {'train': .7, 'dev': .15, 'test': .15}}
(work / 'split-config.json').write_text(json.dumps(config))
paths = []
for name in ('deepset', 'dolly', 'gandalf', 'jackhhao', 'llmail', 'oasst2', 'spml'):
    data = root / 'normalized' / f'{name}.jsonl'
    manifest = data.with_suffix('.manifest.json')
    split.split(data, manifest, config, work / name)
    paths.append(work / name)
for name, filename in [('validation', 'dev.jsonl'), ('held_out', 'heldout.jsonl')]:
    combined = work / f'{name}-source.jsonl'
    with combined.open('wb') as writer:
        for path in paths:
            writer.write((path / filename).read_bytes())
    normalize.normalize(combined, work / f'{name}.jsonl', work / f'{name}.manifest.json')

spec = importlib.util.spec_from_file_location('baseline', '/tmp/sias-0028-baseline.py')
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)
spec = importlib.util.spec_from_file_location('candidate', '/tmp/sias-0028-candidate.py')
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)
current_score = rules.score
summary = {}
for name in ('validation', 'held_out'):
    for version, scoring in [('before', baseline.score), ('after', current_score)]:
        rules.score = scoring
        cache = work / f'{name}-{version}-cache.jsonl'
        metadata = rules.write_cache(work / f'{name}.jsonl', work / f'{name}.manifest.json', cache,
                                     chunk_chars=4096, overlap_chars=512)
        metadata['version'] = 'rules-sha256-' + run.digest(baseline.__file__ if version == 'before' else rules.__file__)
        run_config = {
            'run_id': f'rules-0028-{name}-{version}', 'timestamp': '2026-11-04T00:00:00Z',
            'iteration': 0, 'pipeline_version': f'rules-0028-{version}',
            'dataset': f'{name}.jsonl', 'dataset_manifest': f'{name}.manifest.json',
            'evaluation_split': name, 'stages': [{
                'name': 'rules', 'version': metadata['version'], 'threshold': .75,
                'cache': cache.name, 'cache_sha256': metadata['cache_sha256'],
                'chunk_chars': 4096, 'overlap_chars': 512}]}
        config_path = work / f'{name}-{version}-config.json'
        config_path.write_text(json.dumps(run_config))
        result = run.replay(config_path, work / f'{name}-{version}')
        summary[f'{name}-{version}'] = {'cache': metadata, 'manifest': result}
        print(json.dumps({'run': result['run_id'], 'metrics': result['metrics'],
                          'latency_ms_mean_per_chunk': metadata['latency_ms_mean']}), flush=True)
(work / 'summary.json').write_text(json.dumps(summary, indent=2))
PY
```

## Final scope and verification

Per Claude's ticket decision, the feature code, feature tests and feature usage documentation
were removed. `score()` matches the integration baseline exactly (verified by AST comparison). Only optional chunk export,
its tests and documentation remain, alongside this negative result. Row-cache callers retain
their existing fields and scoring; the aggregate summary additionally counts cache entries.
The producer file hash versions the implementation; no runner/cache schema change is needed.
Chunking is opt-in and can change detection at window boundaries; no detection improvement
is claimed for enabling it. The baseline rows in the tables above measure the retained scorer
with these window settings. Existing row-mode latency and storage were not re-benchmarked.

Tests cover original-turn chunk coordinates, empty turns/conversations/datasets, location
replay, cache latency totals, CLI flags and invalid-window preservation. The held-out aggregate
must not be used as a tuning target. No inference or server lifecycle operations were needed.

Final verification: `uv run pytest -q`: **245 passed, 1 skipped, 48 subtests passed**;
`uv run ruff check`: **passed**.
