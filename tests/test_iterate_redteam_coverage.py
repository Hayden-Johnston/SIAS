"""Unit tests for red_team.coverage wiring in iterate.py."""

import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('iterate', Path(__file__).parents[1] / 'ops/iterate.py')
iterate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(iterate)


class FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    def submit_batch(self, model, prompts, **params):
        return list(range(len(prompts)))

    def drain(self):
        pass

    def result(self, key):
        return {'status': 'done', 'response': {'choices': [{'message': {'content': '0'}}]},
                'latency_seconds': 0.01}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(iterate, 'Client', FakeClient)
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


def enable_red_team(setup, **overrides):
    path = setup[0]
    binary, inventory = path.parent / 'binary', path.parent / 'inventory'
    binary.write_bytes(b'fake binary')
    inventory.write_text('{}')
    config = json.loads(path.read_text())
    config['red_team'] = {'enabled': True, 'groups': 1, 'max_tokens': 128,
                          'carrier_chars': 0, 'replay_only': False,
                          'binary': 'binary', 'inventory': 'inventory'} | overrides
    path.write_text(json.dumps(config))


def test_empty_targets_is_noop(setup, monkeypatch):
    coverage = setup[0].parent / 'coverage.json'
    coverage.write_text(json.dumps({'targets': []}))
    enable_red_team(setup, groups=10, coverage='coverage.json')
    plans = []
    real_generate = iterate.generate.generate

    def plan(*args, **kwargs):
        result = real_generate(*args, **kwargs, dry_run=True)
        plans.append(result)
        if result['groups']:
            raise iterate.generate.GenerationUnavailable('Maya unreachable')
        return result

    monkeypatch.setattr(iterate.generate, 'generate', plan)
    result = iterate.iterate(setup[0], data=setup[1], reports=setup[2])
    assert result['red_team'] == {
        'status': 'no coverage targets', 'generated': 0, 'approved': 0, 'approval_rate': None}
    assert plans[0]['groups'] == 0


def test_groups_cap_limits_requests(setup, monkeypatch):
    coverage = setup[0].parent / 'coverage.json'
    coverage.write_text(json.dumps({'targets': [
        {'channel': 'direct', 'technique': 'override'},
        {'channel': 'email', 'technique': 'roleplay'}]}))
    enable_red_team(setup, groups=30, coverage='coverage.json')
    plans = []
    real_generate = iterate.generate.generate

    def plan(*args, **kwargs):
        result = real_generate(*args, **kwargs, dry_run=True)
        plans.append(result)
        raise iterate.generate.GenerationUnavailable('Maya unreachable')

    monkeypatch.setattr(iterate.generate, 'generate', plan)
    iterate.iterate(setup[0], data=setup[1], reports=setup[2])
    assert plans[0]['groups'] == 2
    assert plans[0]['expected_records'] == 8


def test_missing_coverage_file_gives_clear_error(setup):
    enable_red_team(setup, coverage='nonexistent.json')
    with pytest.raises(FileNotFoundError):
        iterate.iterate(setup[0], data=setup[1], reports=setup[2])


def test_identity_changes_when_targets_content_changes(setup, monkeypatch):
    coverage = setup[0].parent / 'coverage.json'
    coverage.write_text(json.dumps({'targets': [
        {'channel': 'direct', 'technique': 'override'}]}))
    enable_red_team(setup, groups=10, coverage='coverage.json')

    def plan(*args, **kwargs):
        raise iterate.generate.GenerationUnavailable('Maya unreachable')

    monkeypatch.setattr(iterate.generate, 'generate', plan)
    first = iterate.iterate(setup[0], data=setup[1], reports=setup[2])

    coverage.write_text(json.dumps({'targets': [
        {'channel': 'email', 'technique': 'roleplay'}]}))
    second = iterate.iterate(setup[0], data=setup[1], reports=setup[2])

    assert second['identity_sha256'] != first['identity_sha256']
    assert second['iteration'] == first['iteration'] + 1
