"""Iteration integration tests use synthetic data and a fake queued classifier."""

import importlib.util
import json
from pathlib import Path

import pytest

from llm_proxy import ProxyError

spec = importlib.util.spec_from_file_location('iterate', Path(__file__).parents[1] / 'ops/iterate.py')
iterate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(iterate)


class FakeClient:
    calls = 0
    status = 'done'
    content = '0'

    def __init__(self, *args, **kwargs):
        pass

    def submit_batch(self, model, prompts, **params):
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
    assert len(metrics) == 2
    assert {m['evaluation_split'] for m in metrics} == {'validation', 'held_out'}
    assert all(m['records'] == 4 and not m['evaluator_approved'] for m in metrics)
    before = {p: p.read_bytes() for p in data.rglob('*') if p.is_file()}
    monkeypatch.setattr(iterate.rules, 'write_cache', lambda *a: pytest.fail('rescored rules'))
    assert run(setup) == first
    assert all(p.read_bytes() == value for p, value in before.items())
    assert FakeClient.calls == 2
    assert len(list(reports.glob('*.md'))) == 1
    monkeypatch.undo()
    monkeypatch.setattr(iterate, 'Client', FakeClient)
    raw = setup[0].parent / 'raw.jsonl'
    with raw.open('a') as writer:
        writer.write(json.dumps({'text': 'synthetic extra', 'label': 0}) + '\n')
    second = run(setup)
    assert second['iteration'] == 2
    assert len(run_metrics(data / 'runs')) == 4


def test_resume_after_interrupted_model_cache(setup):
    FakeClient.status = 'pending'
    with pytest.raises(ProxyError, match='incomplete'):
        run(setup)
    assert not list(setup[1].glob('runs/iteration-*/manifest.json'))
    rule = next(setup[1].glob('runs/.iterations/*/validation-rules.jsonl'))
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
    assert not list(setup[1].glob('runs/iteration-*/manifest.json'))


def test_invalid_classifier_output_never_becomes_benign(setup):
    FakeClient.content = 'synthetic invalid response'
    with pytest.raises(ValueError, match='exactly 0 or 1'):
        run(setup)
    assert not list(setup[1].glob('runs/iteration-*/manifest.json'))


@pytest.mark.parametrize('cap', [0, -1, True])
def test_invalid_cap(setup, cap):
    config = json.loads(setup[0].read_text())
    config['sample_cap'] = cap
    setup[0].write_text(json.dumps(config))
    with pytest.raises(ValueError, match='positive integer'):
        run(setup)
