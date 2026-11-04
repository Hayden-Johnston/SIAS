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
        assert full_count > 4
        assert m['records'] == (full_count if name == 'rules' else 4)
        assert m['stages'][0]['reached'] == m['records']
        assert not m['evaluator_approved']
        assert sum(m['metrics'][k] for k in ('tp', 'fp', 'fn', 'tn')) == m['records']
        if name == 'maya':
            rows = [r for _, r in iterate.read_rows(work / 'splits' / f'{source_split}.jsonl')]
            expected = sorted(rows, key=lambda r: hashlib.sha256(r['id'].encode()).hexdigest())[:4]
            actual = [r for _, r in iterate.read_rows(work / f"{m['evaluation_split']}-maya.jsonl")]
            assert actual == expected
    assert FakeClient.batches == [4, 4]
    before = {p: p.read_bytes() for p in data.rglob('*') if p.is_file()}
    monkeypatch.setattr(iterate.rules, 'write_cache', lambda *a: pytest.fail('rescored rules'))
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
    with pytest.raises(ValueError, match='exactly 0 or 1'):
        run(setup)
    assert not list(setup[1].glob('runs/iteration-*-maya/manifest.json'))


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
    FakeClient.content = 'invalid synthetic classifier output'
    with pytest.raises(ValueError):
        run(setup)
    FakeClient.content = '0'
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
