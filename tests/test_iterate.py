"""Iteration integration tests use synthetic data and a fake queued classifier."""

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import ClassVar

import pytest

from llm_proxy import ProxyError

spec = importlib.util.spec_from_file_location('iterate', Path(__file__).parents[1] / 'ops/iterate.py')
iterate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(iterate)


class FakeClient:
    calls = 0
    batches: ClassVar[list[int]] = []
    status = 'done'
    content = '0'

    def __init__(self, *args, **kwargs):
        pass

    def submit_batch(self, model, prompts, **params):
        type(self).batches.append(len(prompts))
        return list(range(len(prompts)))

    def drain(self):
        type(self).calls += 1

    def result(self, key):
        return {'status': self.status, 'response': {'choices': [{'message': {'content': self.content}}]},
                'latency_seconds': 0.01}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(iterate, 'Client', FakeClient)
    FakeClient.calls, FakeClient.status, FakeClient.content = 0, 'done', '0'
    FakeClient.batches = []
    raw = tmp_path / 'raw.jsonl'
    raw.write_text(''.join(json.dumps({'text': f'synthetic fixture {i}', 'label': i % 2}) + '\n'
                           for i in range(100)))
    config = {'sources': [{'source': 'deepset', 'inputs': ['raw.jsonl'],
                           'revision': 'abc123', 'timestamp': '2026-11-04T00:00:00Z'}],
              'split': {'heldout_families': ['deepset/prompt-injections'],
                        'proportions': {'train': 0.1, 'dev': 0.8, 'test': 0.1}},
              'sample_cap': 4, 'model': 'fixture-v1', 'max_tokens': 16,
              'pipeline_version': 'fixture-v1', 'rule_threshold': 0.75, 'model_threshold': 0.5}
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    return path, tmp_path / 'data', tmp_path / 'reports'


def run(setup):
    config, data, reports = setup
    return iterate.iterate(config, data=data, reports=reports)


def test_complete_replay_dashboard_and_source_change(setup, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        'dashboard_server', Path(__file__).parents[1] / 'dashboard/server.py')
    dashboard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dashboard)
    run_metrics = dashboard.run_metrics

    first = run(setup)
    _, data, reports = setup
    metrics = run_metrics(data / 'runs')
    assert len(metrics) == 4
    assert {m['evaluation_split'] for m in metrics} == {'validation', 'held_out'}
    work = next(data.glob('runs/.iterations/*/state.json')).parent
    for m in metrics:
        name = m['stages'][0]['name']
        source_split = 'dev' if m['evaluation_split'] == 'validation' else 'heldout'
        full_count = first['split_counts'][source_split]['records']
        full_count += first['augmentation']['splits'][source_split]['records']
        assert full_count > 4
        assert m['records'] == (full_count if name == 'rules' else 4)
        assert m['stages'][0]['reached'] == m['records']
        assert not m['evaluator_approved']
        assert sum(m['metrics'][k] for k in ('tp', 'fp', 'fn', 'tn')) == m['records']
        if name == 'maya':
            rows = [r for _, r in iterate.read_rows(work / 'augmented' / f'{source_split}.jsonl')]
            expected = sorted(rows, key=lambda r: hashlib.sha256(r['id'].encode()).hexdigest())[:4]
            actual = [r for _, r in iterate.read_rows(work / f"{m['evaluation_split']}-maya.jsonl")]
            assert actual == expected
    assert FakeClient.batches == [4, 4]
    before = {p: p.read_bytes() for p in data.rglob('*') if p.is_file()}
    monkeypatch.setattr(iterate.rules, 'write_cache', lambda *a: pytest.fail('rescored rules'))
    monkeypatch.setattr(iterate.augment, 'augment', lambda *a, **k: pytest.fail('reaugmented'))
    assert run(setup) == first
    assert all(p.read_bytes() == value for p, value in before.items())
    assert FakeClient.calls == 2
    # Resume after losing the final checkpoint must also use only saved stage caches.
    (work / 'complete.json').unlink()
    monkeypatch.setattr(iterate, 'Client', lambda *a, **k: pytest.fail('inference on resume'))
    assert run(setup) == first
    assert all(p.read_bytes() == value for p, value in before.items())
    assert len(list(reports.glob('*.md'))) == 1
    monkeypatch.undo()
    monkeypatch.setattr(iterate, 'Client', FakeClient)
    raw = setup[0].parent / 'raw.jsonl'
    with raw.open('a') as writer:
        writer.write(json.dumps({'text': 'synthetic extra', 'label': 0}) + '\n')
    second = run(setup)
    assert second['iteration'] == 2
    assert len(run_metrics(data / 'runs')) == 8


def test_resume_after_interrupted_model_cache(setup):
    FakeClient.status = 'pending'
    with pytest.raises(ProxyError, match='incomplete'):
        run(setup)
    assert not list(setup[1].glob('runs/iteration-*-maya/manifest.json'))
    rule = next(setup[1].glob('runs/.iterations/*/validation-rules-scores.jsonl'))
    before = rule.read_bytes()
    FakeClient.status = 'done'
    result = run(setup)
    assert result['iteration'] == 1
    assert rule.read_bytes() == before


def test_failed_request_stops_before_drain(setup):
    FakeClient.status = 'failed'
    with pytest.raises(ProxyError, match='operator review'):
        run(setup)
    assert FakeClient.calls == 0
    assert not list(setup[1].glob('runs/iteration-*-maya/manifest.json'))


def test_invalid_classifier_output_never_becomes_benign(setup):
    FakeClient.content = 'synthetic invalid response'
    run(setup)
    sidecars = list(setup[1].rglob('*-maya-scores.invalid.json'))
    assert sidecars and all(json.loads(p.read_text())['invalid_outputs'] > 0 for p in sidecars)
    for cache in setup[1].rglob('*-maya-scores.jsonl'):
        assert all(json.loads(line)['score'] == 1 for line in cache.read_text().splitlines())


@pytest.mark.parametrize('cap', [0, -1, True])
def test_invalid_cap(setup, cap):
    config = json.loads(setup[0].read_text())
    config['sample_cap'] = cap
    setup[0].write_text(json.dumps(config))
    with pytest.raises(ValueError, match='positive integer'):
        run(setup)


def enable_red_team(setup, **overrides):
    path = setup[0]
    binary, inventory = path.parent / 'binary', path.parent / 'inventory'
    binary.write_bytes(b'fake binary')
    inventory.write_text('{}')
    config = json.loads(path.read_text())
    config['red_team'] = {'enabled': True, 'groups': 1, 'max_tokens': 128,
                          'carrier_chars': 0, 'replay_only': False,
                          'binary': 'binary', 'inventory': 'inventory'} | overrides
    config['split']['heldout_families'].append('generator-v1-code_comment-delimiter_spoof')
    path.write_text(json.dumps(config))


def test_red_team_off_never_generates(setup, monkeypatch):
    monkeypatch.setattr(iterate.generate, 'generate', lambda *a, **k: pytest.fail('generated'))
    assert run(setup)['red_team'] == {
        'status': 'off', 'generated': 0, 'approved': 0, 'approval_rate': None}


def test_red_team_approval_split_resume_and_replay(setup, monkeypatch, capsys):
    from test_evaluate import FakeClient as Evaluator
    from test_generate import FakeClient as Generator

    enable_red_team(setup)
    generator = Generator()
    monkeypatch.setattr(iterate, 'Client', lambda path, **k:
                        generator if path.name == 'generator.sqlite' else FakeClient())
    real_evaluate = iterate.evaluate.evaluate
    evaluations = []

    def evaluate(source, manifest, output, **kwargs):
        # Only synthetic fixtures are read; labels agree except for one benign prediction.
        labels = [{key: row[key] for key in ('label', 'channel', 'techniques')}
                  for _, row in iterate.read_rows(source)]
        labels[0] = {'label': 0, 'channel': 'direct', 'techniques': []}
        client = Evaluator(labels)
        evaluations.append(client)
        return real_evaluate(source, manifest, output, client=client)

    monkeypatch.setattr(iterate.evaluate, 'evaluate', evaluate)
    # Interrupt scoring after the approved rows and family splits are checkpointed.
    FakeClient.status = 'failed'
    with pytest.raises(ProxyError):
        run(setup)
    FakeClient.status = 'done'
    result = run(setup)
    summary = result['red_team']
    assert summary['generated'] == 4 and summary['approved'] == 3
    assert summary['approval_rate'] == 3 / 4
    assert generator.calls == 1 and max(generator.batches) == 1
    assert len(evaluations) == 1
    work = next(setup[1].glob('runs/.iterations/*/state.json')).parent
    generated = json.loads((work / 'generated/split_manifest.json').read_text())
    assert sum(s['records'] for s in generated['splits'].values()) == 3
    assert generated['splits']['heldout']['records'] == 2
    rows = [r for _, r in iterate.read_rows(work / 'dataset.jsonl')]
    approved = [r for r in rows if r['label_source'] == 'evaluator']
    assert len(approved) == 3
    assert all(r['publishable'] == 'no' for r in approved)
    before = {p: p.read_bytes() for root in setup[1:] for p in root.rglob('*') if p.is_file()}
    assert run(setup) == result
    assert all(p.read_bytes() == value for p, value in before.items())
    assert generator.calls == 1 and len(evaluations) == 1
    report = next(setup[2].glob('*.md')).read_text()
    assert 'generated 4, approved 3; approval rate 0.75' in report
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('replay_only', [False, True])
def test_red_team_unavailable_skips_cleanly(setup, monkeypatch, capsys, replay_only):
    from test_generate import FakeClient as Generator

    enable_red_team(setup, replay_only=replay_only)
    client = Generator()
    def down():
        for job in client.jobs.values():
            job['error'] = 'transport_error'
        raise ProxyError('synthetic transport error')
    client.drain = down
    monkeypatch.setattr(iterate, 'Client', lambda path, **k:
                        client if path.name == 'generator.sqlite' else FakeClient())
    monkeypatch.setattr(iterate.evaluate, 'evaluate', lambda *a, **k: pytest.fail('evaluated'))
    result = run(setup)
    expected = 'replay-only cache miss' if replay_only else 'Maya unreachable'
    assert result['red_team']['status'] == expected
    assert result['red_team']['approved'] == 0
    assert len(result['runs']) == 4
    assert 'red-team round skipped: ' + expected in capsys.readouterr().out


def test_red_team_refusal_stops_iteration(setup, monkeypatch):
    from test_generate import FakeClient as Generator

    enable_red_team(setup)
    client = Generator()
    def refuse():
        raise ProxyError('refusal')
    client.drain = refuse
    monkeypatch.setattr(iterate, 'Client', lambda *a, **k: client)
    with pytest.raises(ProxyError, match='refusal'):
        run(setup)
    assert not list(setup[1].rglob('complete.json'))
    assert client.batches == [1]


def test_cap_above_budget_rejected_before_inference(setup):
    config = json.loads(setup[0].read_text())
    config['sample_cap'] = 26
    setup[0].write_text(json.dumps(config))
    with pytest.raises(ValueError, match='at most 25'):
        run(setup)
    assert FakeClient.calls == 0


def test_max_cap_limits_total_classifier_prompts(setup):
    config = json.loads(setup[0].read_text())
    config['sample_cap'] = 25
    setup[0].write_text(json.dumps(config))
    run(setup)
    assert FakeClient.batches == [25, 25]


@pytest.mark.parametrize('reserved', [True, False])
def test_augmentation_preserves_source_groups_families_and_splits(setup, reserved):
    if not reserved:
        config = json.loads(setup[0].read_text())
        config['split']['heldout_families'] = []
        setup[0].write_text(json.dumps(config))
    result = run(setup)
    assert result['augmentation']['enabled'] is True
    work = next(setup[1].glob('runs/.iterations/*/state.json')).parent
    seen_groups = {}
    for name in iterate.split.SPLITS:
        originals = [r for _, r in iterate.read_rows(work / 'splits' / f'{name}.jsonl')]
        rows = [r for _, r in iterate.read_rows(work / 'augmented' / f'{name}.jsonl')]
        assert rows[:len(originals)] == originals
        attacks = {r['group_id']: r for r in originals if r['label']}
        count = len(attacks)
        assert result['augmentation']['splits'][name] == {
            'records': 8 * count,
            'channels': {'document': 4 * count, 'email': 2 * count, 'tool_output': 2 * count}
            if count else {},
        }
        for row in rows:
            group = row['group_id']
            assert seen_groups.setdefault(group, name) == name
            if row['source'].startswith('augmented:'):
                assert row['attack_family'] == attacks[group]['attack_family']
                assert row['label_source'] == 'synthetic-augmentation'
                assert row['publishable'] == 'no'
                if reserved:
                    assert name == 'heldout'
        # Regeneration from the original split reproduces both dataset and manifest bytes.
        regenerated = work / 'regenerated' / f'{name}.jsonl'
        iterate.augment.augment(work / 'splits' / f'{name}.jsonl', regenerated,
                                work / 'splits/split_manifest.json', seed=0)
        assert regenerated.read_bytes() == (work / 'augmented' / regenerated.name).read_bytes()
        assert regenerated.with_suffix('.manifest.json').read_bytes() == (
            work / 'augmented' / f'{name}.manifest.json').read_bytes()
    assert 'Synthetic augmentation' in next(setup[2].glob('*.md')).read_text()


def test_augmentation_disabled(setup, monkeypatch):
    config = json.loads(setup[0].read_text())
    config['augment'] = False
    setup[0].write_text(json.dumps(config))
    monkeypatch.setattr(iterate.augment, 'augment', lambda *a, **k: pytest.fail('augmented'))
    result = run(setup)
    assert result['augmentation'] == {'enabled': False, 'splits': {}}
    work = next(setup[1].glob('runs/.iterations/*/state.json')).parent
    assert not (work / 'augmented').exists()
    for source_split, evaluation in [('dev', 'validation'), ('heldout', 'held_out')]:
        assert (work / 'splits' / f'{source_split}.jsonl').read_bytes() == (
            work / f'{evaluation}-rules.jsonl').read_bytes()


@pytest.mark.parametrize('value', [0, 1, 'true', None, {}])
def test_invalid_augmentation_option(setup, value):
    config = json.loads(setup[0].read_text())
    config['augment'] = value
    setup[0].write_text(json.dumps(config))
    with pytest.raises(ValueError, match='augment must be boolean'):
        run(setup)
    assert FakeClient.calls == 0


def test_augmentation_cannot_borrow_padding_from_other_splits(setup):
    raw = setup[0].parent / 'raw.jsonl'
    raw.write_text(json.dumps({'text': 'synthetic attack fixture', 'label': 1}) + '\n')
    with pytest.raises(ValueError, match='benign rows in the same split'):
        run(setup)
    assert FakeClient.calls == 0
    assert not list(setup[1].rglob('complete.json'))


def test_fused_sample_sweep_slices_and_replay(setup, monkeypatch):
    from data_processing.run import rate

    config = json.loads(setup[0].read_text())
    config['split']['heldout_families'] = []
    config['sample_cap'] = 25
    config['fusion_fpr_cap'] = 0
    setup[0].write_text(json.dumps(config))
    result = run(setup)
    summary = result['fusion']
    assert summary['status'] == 'complete'
    assert summary['dev']['weights'] == {'maya': 0, 'rules': 0}
    assert summary['held_out_delta_vs_best_single'] == {'detection': 0, 'false_positive': 0}
    work = next(setup[1].glob('runs/.iterations/*/state.json')).parent
    fused = json.loads((setup[1] / 'runs/iteration-000001-held_out-fused/manifest.json').read_text())
    assert fused['records'] <= 25
    assert fused['iteration_fusion'] == summary
    n = fused['metrics']['detection']['n']
    assert n > 0
    assert fused['metrics']['detection'] == rate(0, n)
    assert fused['slices']['novel_technique'] == []
    assert fused['slices']['by_technique']['novel']['detection'] == rate(0, n)
    # Same sampled IDs and original measured latencies, no new rule scoring.
    full = {r['id']: r for _, r in iterate.read_rows(work / 'held_out-rules-scores.jsonl')}
    subset = [r for _, r in iterate.read_rows(work / 'held_out-sample-rules-scores.jsonl')]
    assert len(subset) == fused['records']
    assert all(r == full[r['id']] for r in subset)
    assert FakeClient.batches == [25, fused['records']]
    report = next(setup[2].glob('*.md')).read_text()
    assert 'held_out_delta_vs_best_single' in report and 'ci95' in report
    # Removing only the final checkpoint must replay byte-identically with no inference.
    before = {p: p.read_bytes() for p in setup[1].rglob('*') if p.is_file()}
    (work / 'complete.json').unlink()
    monkeypatch.setattr(iterate, 'Client', lambda *a, **k: pytest.fail('inference on replay'))
    monkeypatch.setattr(iterate.rules, 'write_cache', lambda *a: pytest.fail('rule rescoring'))
    assert run(setup) == result
    assert all(p.read_bytes() == value for p, value in before.items())


def test_iteration_novel_techniques_use_full_dev_and_bind_held_checksum(setup):
    result = run(setup)
    assert result['fusion']['status'].startswith('unavailable:')
    manifests = [json.loads(p.read_text()) for p in setup[1].glob('runs/iteration-*/manifest.json')]
    for m in manifests:
        if m['evaluation_split'] == 'held_out':
            assert {g['technique'] for g in m['slices']['novel_technique']} == set(
                m['slices']['by_technique'])
            for group in m['slices']['novel_technique']:
                assert group['detection']['n'] == group['n']
                assert group['detection']['method'] == 'wilson'
    work = next(setup[1].glob('runs/.iterations/*/state.json')).parent
    provenance = json.loads((work / 'held_out-maya-split.json').read_text())
    assert provenance['splits']['dev'] == json.loads((work / 'validation-rules.json').read_text())
    assert provenance['splits']['heldout']['output_sha256'] == iterate.digest(work / 'held_out-maya.jsonl')


@pytest.mark.parametrize('cap', [-1, 1.1, True, None])
def test_invalid_fusion_fpr_cap_before_inference(setup, cap):
    config = json.loads(setup[0].read_text())
    config['fusion_fpr_cap'] = cap
    setup[0].write_text(json.dumps(config))
    with pytest.raises(ValueError, match='fusion FPR cap'):
        run(setup)
    assert FakeClient.calls == 0


def test_tiny_fusion_fixture_complementary_scores_and_missing_cache(tmp_path, monkeypatch):
    from test_sweep import config

    from data_processing.run import rate

    configs = {}
    for evaluation in ('validation', 'held_out'):
        path = config(tmp_path / evaluation, evaluation, [[1, 0, 0, 0], [0, 1, 0.9, 0]])
        original = json.loads(path.read_text())
        for name, stage in zip(('rules', 'maya'), original['stages']):
            stage = stage | {'name': name, 'cache': str(path.parent / stage['cache'])}
            configs[f'{evaluation}-{name}'] = original | {
                'run_id': evaluation + '-' + name, 'stages': [stage],
                'dataset': str(path.parent / 'dataset.jsonl'),
                'dataset_manifest': str(path.parent / 'manifest.json')}
    monkeypatch.setattr(iterate, 'Client', lambda *a, **k: pytest.fail('inference'))
    result = iterate.fused_runs(tmp_path, tmp_path / 'runs', configs, 0)
    assert result['dev']['weights'] == {'maya': 0.5, 'rules': 0.5}
    assert result['fused_metrics']['detection'] == rate(2, 2)
    assert result['single_metrics']['detection'] == rate(1, 2)
    assert result['fused_metrics']['false_positive'] == rate(0, 2)
    assert result['held_out_delta_vs_best_single'] == {'detection': 0.5, 'false_positive': 0}
    before = {p: p.read_bytes() for p in (tmp_path / 'runs').rglob('*') if p.is_file()}
    assert iterate.fused_runs(tmp_path, tmp_path / 'runs', configs, 0) == result
    assert all(p.read_bytes() == value for p, value in before.items())
    cache = Path(configs['held_out-rules']['stages'][0]['cache'])
    cache.write_text('')
    with pytest.raises(ValueError, match='missing required cached score'):
        iterate.fused_runs(tmp_path, tmp_path / 'runs', configs, 0)
    assert all(p.read_bytes() == value for p, value in before.items())


def configure_probe(setup):
    # Build caches from synthetic full scoring splits, as an external probe export would.
    run(setup)
    work = next(setup[1].glob('runs/.iterations/*/state.json')).parent
    probe = {'version': 'synthetic-probe-v1', 'threshold': 0.5}
    for source_split, evaluation in [('dev', 'validation'), ('heldout', 'held_out')]:
        cache = setup[0].parent / f'{source_split}-probe.jsonl'
        iterate.atomic_write(cache, ''.join(iterate.canonical_json({
            'id': row['id'], 'score': row['label'], 'latency_ms': 0}) + '\n'
            for _, row in iterate.read_rows(work / f'{evaluation}-rules.jsonl')).encode())
        probe[source_split] = {'cache': cache.name, 'cache_sha256': iterate.digest(cache)}
    config = json.loads(setup[0].read_text())
    config['activation_probe'] = probe
    setup[0].write_text(json.dumps(config))
    return probe


def test_probe_fusion_from_full_cache_and_replay(setup, monkeypatch):
    config = json.loads(setup[0].read_text())
    config['split']['heldout_families'] = []
    config['sample_cap'] = 25
    setup[0].write_text(json.dumps(config))
    configure_probe(setup)
    result = run(setup)
    assert result['probe'] == 'available'
    assert result['fusion']['stages'] == ['rules', 'activation-probe', 'maya']
    assert result['fusion']['dev']['weights'] == {'activation-probe': 0.5, 'maya': 0, 'rules': 0}
    assert result['fusion']['fused_metrics']['detection']['value'] == 1
    assert result['fusion']['fused_metrics']['false_positive']['value'] == 0
    fused = json.loads((setup[1] / 'runs/iteration-000002-held_out-fused/manifest.json').read_text())
    assert fused['records'] <= 25
    assert fused['stages'][1]['name'] == 'activation-probe'
    assert fused['stages'][1]['cached_latency_ms_total'] == 0
    report = (setup[2] / f"{result['timestamp'][:10]}-iteration-000002.md").read_text()
    assert 'probe: available' in report
    assert 'Fused rules + activation-probe + maya (same capped sample)' in report
    before = {p: p.read_bytes() for p in setup[1].rglob('*') if p.is_file()}
    checkpoint = next(p for p in setup[1].rglob('complete.json')
                      if json.loads(p.read_text())['iteration'] == 2)
    checkpoint.unlink()
    monkeypatch.setattr(iterate, 'Client', lambda *a, **k: pytest.fail('inference on replay'))
    assert run(setup) == result
    assert all(p.read_bytes() == value for p, value in before.items())


@pytest.mark.parametrize('missing', [('dev',), ('heldout',), ('dev', 'heldout')])
def test_missing_probe_cache_falls_back_and_availability_changes_identity(setup, missing):
    probe = configure_probe(setup)
    saved = {}
    for name in missing:
        path = setup[0].parent / probe[name]['cache']
        saved[path] = path.read_bytes()
        path.unlink()
    result = run(setup)
    assert result['probe'] == 'not available'
    assert result['fusion']['stages'] == ['rules', 'maya']
    report = (setup[2] / f"{result['timestamp'][:10]}-iteration-000002.md").read_text()
    assert 'probe: not available' in report
    assert 'Fused rules + maya' in report
    for path, contents in saved.items():
        path.write_bytes(contents)
    available = run(setup)
    assert available['iteration'] == 3
    assert available['probe'] == 'available'
    assert available['identity_sha256'] != result['identity_sha256']


def test_corrupt_probe_cache_fails_before_inference(setup):
    probe = configure_probe(setup)
    (setup[0].parent / probe['dev']['cache']).write_text('')
    FakeClient.calls = 0
    with pytest.raises(ValueError, match='activation_probe cache checksum mismatch'):
        run(setup)
    assert FakeClient.calls == 0


def test_incomplete_probe_cache_does_not_fabricate_scores(setup):
    config = json.loads(setup[0].read_text())
    config['split']['heldout_families'] = []
    config['sample_cap'] = 25
    setup[0].write_text(json.dumps(config))
    probe = configure_probe(setup)
    path = setup[0].parent / probe['dev']['cache']
    path.write_text('')
    config = json.loads(setup[0].read_text())
    config['activation_probe']['dev']['cache_sha256'] = iterate.digest(path)
    setup[0].write_text(json.dumps(config))
    with pytest.raises(ValueError, match='missing required cached score'):
        run(setup)
    assert not list(setup[1].glob('runs/iteration-000002-*-fused/manifest.json'))


def configure_cpu_classifier(setup):
    run(setup)
    work = next(setup[1].glob('runs/.iterations/*/state.json')).parent
    stage = {'version': 'synthetic-cpu-v1', 'threshold': 0.5,
             'chunk_chars': 12, 'overlap_chars': 4}
    from data_processing.run import windows

    for source_split, evaluation in [('dev', 'validation'), ('heldout', 'held_out')]:
        cache = setup[0].parent / f'{source_split}-cpu.jsonl'
        entries = [
            {'id': row['id'], 'turn': 0, 'start': start, 'score': row['label'], 'latency_ms': 2}
            for _, row in iterate.read_rows(work / f'{evaluation}-rules.jsonl')
            for start, _ in windows(len(row['text']), 12, 4)
        ]
        iterate.atomic_write(cache, ''.join(iterate.canonical_json(e) + '\n' for e in entries).encode())
        stage[source_split] = {'cache': cache.name, 'cache_sha256': iterate.digest(cache)}
    config = json.loads(setup[0].read_text())
    config['cpu_classifier'] = stage
    setup[0].write_text(json.dumps(config))
    return stage


@pytest.mark.parametrize('with_probe', [False, True])
def test_cpu_classifier_chunk_fusion_and_replay(setup, monkeypatch, with_probe):
    config = json.loads(setup[0].read_text())
    config['split']['heldout_families'] = []
    config['sample_cap'] = 25
    setup[0].write_text(json.dumps(config))
    if with_probe:
        configure_probe(setup)
    configure_cpu_classifier(setup)
    result = run(setup)
    names = ['rules', *(['activation-probe'] if with_probe else []), 'cpu-classifier', 'maya']
    assert result['cpu_classifier'] == 'available'
    assert result['fusion']['stages'] == names
    assert result['fusion']['fused_metrics']['detection']['value'] == 1
    assert result['fusion']['fused_metrics']['false_positive']['value'] == 0
    fused = json.loads((setup[1] / 'runs' /
                       f"iteration-{result['iteration']:06d}-held_out-fused/manifest.json").read_text())
    cpu = next(s for s in fused['stages'] if s['name'] == 'cpu-classifier')
    assert cpu['cached_latency_ms_total'] > 0
    assert cpu['chunk_chars'] == 12
    report = next(p for p in setup[2].glob('*.md') if f"{result['iteration']:06d}" in p.name)
    assert 'cpu-classifier: available' in report.read_text()
    assert 'Fused ' + ' + '.join(names) + ' (same capped sample)' in report.read_text()
    before = {p: p.read_bytes() for p in setup[1].rglob('*') if p.is_file()}
    checkpoint = next(p for p in setup[1].rglob('complete.json')
                      if json.loads(p.read_text())['iteration'] == result['iteration'])
    checkpoint.unlink()
    monkeypatch.setattr(iterate, 'Client', lambda *a, **k: pytest.fail('inference on replay'))
    assert run(setup) == result
    assert all(p.read_bytes() == value for p, value in before.items())


@pytest.mark.parametrize('missing', [('dev',), ('heldout',), ('dev', 'heldout')])
def test_missing_cpu_classifier_cache_and_new_availability(setup, missing):
    stage = configure_cpu_classifier(setup)
    saved = {}
    for name in missing:
        path = setup[0].parent / stage[name]['cache']
        saved[path] = path.read_bytes()
        path.unlink()
    result = run(setup)
    assert result['cpu_classifier'] == 'not available'
    assert result['fusion']['stages'] == ['rules', 'maya']
    report = next(p for p in setup[2].glob('*.md') if '000002' in p.name)
    assert 'cpu-classifier: not available' in report.read_text()
    for path, contents in saved.items():
        path.write_bytes(contents)
    available = run(setup)
    assert available['iteration'] == 3
    assert available['cpu_classifier'] == 'available'
    assert available['identity_sha256'] != result['identity_sha256']


def test_corrupt_cpu_classifier_cache_fails_before_inference(setup):
    stage = configure_cpu_classifier(setup)
    (setup[0].parent / stage['dev']['cache']).write_text('')
    FakeClient.calls = 0
    with pytest.raises(ValueError, match='cpu_classifier cache checksum mismatch'):
        run(setup)
    assert FakeClient.calls == 0


def test_missing_cpu_classifier_chunk_fails_without_fabrication(setup):
    config = json.loads(setup[0].read_text())
    config['split']['heldout_families'] = []
    config['sample_cap'] = 25
    setup[0].write_text(json.dumps(config))
    stage = configure_cpu_classifier(setup)
    path = setup[0].parent / stage['dev']['cache']
    path.write_text('')
    config = json.loads(setup[0].read_text())
    config['cpu_classifier']['dev']['cache_sha256'] = iterate.digest(path)
    setup[0].write_text(json.dumps(config))
    with pytest.raises(ValueError, match='missing required cached score'):
        run(setup)
    assert not list(setup[1].glob('runs/iteration-000002-*-fused/manifest.json'))


@pytest.mark.parametrize('chunk,overlap', [(0, 0), (12, 12), (12, -1), (True, 0), (12, 1.5)])
def test_invalid_cpu_classifier_windows_before_inference(setup, chunk, overlap):
    configure_cpu_classifier(setup)
    config = json.loads(setup[0].read_text())
    config['cpu_classifier'].update(chunk_chars=chunk, overlap_chars=overlap)
    setup[0].write_text(json.dumps(config))
    FakeClient.calls = 0
    with pytest.raises(ValueError, match='chunk_chars > overlap_chars'):
        run(setup)
    assert FakeClient.calls == 0
