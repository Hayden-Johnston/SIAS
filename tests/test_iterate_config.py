"""Unit tests for iterate.py config parsing and lock handling."""

import fcntl
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('iterate', Path(__file__).parents[1] / 'ops/iterate.py')
iterate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(iterate)

EXAMPLE = Path(__file__).parents[1] / 'iterate.example.json'

REQUIRED = {'sources', 'split', 'sample_cap', 'model', 'max_tokens',
            'pipeline_version', 'rule_threshold', 'model_threshold'}


def valid_config():
    return {
        'sources': [{'source': 'deepset', 'inputs': ['raw.jsonl'],
                     'revision': 'abc', 'timestamp': '2026-11-04T00:00:00Z'}],
        'split': {'heldout_families': ['deepset/prompt-injections'],
                  'proportions': {'train': 0.7, 'dev': 0.15, 'test': 0.15}},
        'sample_cap': 4, 'model': 'fixture', 'max_tokens': 16,
        'pipeline_version': 'v1', 'rule_threshold': 0.75, 'model_threshold': 0.5,
    }


def write_config(tmp_path, config):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    return path


def test_example_config_is_valid():
    config = json.loads(EXAMPLE.read_text())
    assert REQUIRED <= set(config)
    assert set(config) - REQUIRED - {'red_team', 'augment', 'fusion_fpr_cap'} == set()
    assert config.get('augment', True) is True
    assert config['fusion_fpr_cap'] == 0.0002
    assert isinstance(config['sources'], list) and config['sources']
    assert isinstance(config['sample_cap'], int) and config['sample_cap'] >= 1
    assert isinstance(config['max_tokens'], int) and config['max_tokens'] >= 1
    assert isinstance(config['model'], str) and config['model'].strip()
    assert isinstance(config['pipeline_version'], str) and config['pipeline_version'].strip()
    assert isinstance(config['rule_threshold'], (int, float))
    assert isinstance(config['model_threshold'], (int, float))
    # red_team defaults to disabled
    rt = config.get('red_team', {'enabled': False})
    assert rt['enabled'] is False


def test_example_sample_cap_fits_cpu_tick_budget():
    # Iteration 8: dev + held-out cached CPU seconds for 25 records per split.
    # Reserve half of a 300-second tick for other CPU jobs; see the cap report.
    seconds_per_cap = (522.8178502860828 + 132.40112292100093) / 25
    cap = json.loads(EXAMPLE.read_text())['sample_cap']
    assert cap * seconds_per_cap <= 150
    assert (cap + 1) * seconds_per_cap > 150


@pytest.mark.parametrize('key', sorted(REQUIRED))
def test_missing_required_key(tmp_path, key):
    config = valid_config()
    del config[key]
    path = write_config(tmp_path, config)
    with pytest.raises(ValueError, match='exactly the documented fields'):
        iterate.iterate(path, data=tmp_path / 'data', reports=tmp_path / 'reports')


def test_unknown_top_level_key(tmp_path):
    config = valid_config()
    config['bogus'] = 1
    path = write_config(tmp_path, config)
    with pytest.raises(ValueError, match='exactly the documented fields'):
        iterate.iterate(path, data=tmp_path / 'data', reports=tmp_path / 'reports')


def test_config_not_dict(tmp_path):
    path = write_config(tmp_path, [1, 2, 3])
    with pytest.raises(ValueError, match='exactly the documented fields'):
        iterate.iterate(path, data=tmp_path / 'data', reports=tmp_path / 'reports')


@pytest.mark.parametrize('key,bad', [
    ('sample_cap', 'not_an_int'),
    ('sample_cap', -1),
    ('sample_cap', 0),
    ('max_tokens', 'not_an_int'),
    ('max_tokens', 0),
    ('model', ''),
    ('model', 42),
    ('pipeline_version', ''),
    ('rule_threshold', 'high'),
    ('model_threshold', -0.5),
    ('sources', 'not_a_list'),
    ('sources', []),
])
def test_bad_field_type(tmp_path, key, bad):
    config = valid_config()
    config[key] = bad
    path = write_config(tmp_path, config)
    with pytest.raises(ValueError):
        iterate.iterate(path, data=tmp_path / 'data', reports=tmp_path / 'reports')


def test_sample_cap_above_max(tmp_path):
    config = valid_config()
    config['sample_cap'] = 26
    path = write_config(tmp_path, config)
    with pytest.raises(ValueError, match='at most 25'):
        iterate.iterate(path, data=tmp_path / 'data', reports=tmp_path / 'reports')


def test_invalid_source_entry(tmp_path):
    config = valid_config()
    config['sources'] = [{'source': 'unknown_source', 'inputs': ['x'],
                          'revision': 'r', 'timestamp': 't'}]
    path = write_config(tmp_path, config)
    with pytest.raises(ValueError, match='invalid source config'):
        iterate.iterate(path, data=tmp_path / 'data', reports=tmp_path / 'reports')


def test_source_missing_key(tmp_path):
    config = valid_config()
    config['sources'] = [{'source': 'deepset', 'inputs': ['x'], 'revision': 'r'}]
    path = write_config(tmp_path, config)
    with pytest.raises(ValueError, match='invalid source config'):
        iterate.iterate(path, data=tmp_path / 'data', reports=tmp_path / 'reports')


def test_red_team_not_dict(tmp_path):
    config = valid_config()
    config['red_team'] = 'enabled'
    path = write_config(tmp_path, config)
    with pytest.raises(ValueError, match='boolean enabled field'):
        iterate.iterate(path, data=tmp_path / 'data', reports=tmp_path / 'reports')


def test_red_team_enabled_missing_fields(tmp_path):
    config = valid_config()
    config['red_team'] = {'enabled': True}
    path = write_config(tmp_path, config)
    with pytest.raises(ValueError, match='documented fields'):
        iterate.iterate(path, data=tmp_path / 'data', reports=tmp_path / 'reports')


def test_red_team_unknown_field(tmp_path):
    config = valid_config()
    config['red_team'] = {'enabled': False, 'bogus': 1}
    path = write_config(tmp_path, config)
    with pytest.raises(ValueError, match='documented fields'):
        iterate.iterate(path, data=tmp_path / 'data', reports=tmp_path / 'reports')


def test_red_team_enabled_bad_counts(tmp_path):
    config = valid_config()
    config['red_team'] = {'enabled': True, 'groups': 0, 'max_tokens': 128,
                          'carrier_chars': 8192, 'replay_only': False,
                          'binary': 'b', 'inventory': 'i'}
    path = write_config(tmp_path, config)
    with pytest.raises(ValueError, match='invalid red_team count'):
        iterate.iterate(path, data=tmp_path / 'data', reports=tmp_path / 'reports')


def test_red_team_enabled_bad_replay_only(tmp_path):
    config = valid_config()
    config['red_team'] = {'enabled': True, 'groups': 1, 'max_tokens': 128,
                          'carrier_chars': 0, 'replay_only': 'yes',
                          'binary': 'b', 'inventory': 'i'}
    path = write_config(tmp_path, config)
    with pytest.raises(ValueError, match='replay_only must be boolean'):
        iterate.iterate(path, data=tmp_path / 'data', reports=tmp_path / 'reports')


def test_red_team_enabled_empty_path(tmp_path):
    config = valid_config()
    config['red_team'] = {'enabled': True, 'groups': 1, 'max_tokens': 128,
                          'carrier_chars': 0, 'replay_only': False,
                          'binary': '', 'inventory': 'i'}
    path = write_config(tmp_path, config)
    with pytest.raises(ValueError, match='nonempty strings'):
        iterate.iterate(path, data=tmp_path / 'data', reports=tmp_path / 'reports')


def test_split_config_invalid(tmp_path):
    config = valid_config()
    config['split'] = {'proportions': {'train': 0.7, 'dev': 0.15}}  # missing test
    path = write_config(tmp_path, config)
    with pytest.raises(ValueError, match='proportions'):
        iterate.iterate(path, data=tmp_path / 'data', reports=tmp_path / 'reports')


def test_second_flock_fails(tmp_path):
    runs = tmp_path / 'runs'
    runs.mkdir()
    lock_path = runs / '.iterate.lock'
    lock_path.touch()
    with lock_path.open('a') as lock1:
        fcntl.flock(lock1, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError), lock_path.open('a') as lock2:
            fcntl.flock(lock2, fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.mark.parametrize('probe', [
    None, {},
    {'version': '', 'threshold': 0.5, 'dev': {}, 'heldout': {}},
    {'version': 'v1', 'threshold': True, 'dev': {}, 'heldout': {}},
    {'version': 'v1', 'threshold': 0.5, 'dev': 'cache.jsonl', 'heldout': {}},
    {'version': 'v1', 'threshold': 0.5, 'dev': {'cache': '', 'cache_sha256': 'hash'}, 'heldout': {}},
])
def test_invalid_probe_config_before_inference(tmp_path, probe):
    config = valid_config()
    config['activation_probe'] = probe
    path = write_config(tmp_path, config)
    with pytest.raises(ValueError, match='activation_probe'):
        iterate.iterate(path, data=tmp_path / 'data', reports=tmp_path / 'reports')


@pytest.mark.parametrize('cpu', [
    None, {},
    {'version': '', 'threshold': 0.5, 'chunk_chars': 12, 'overlap_chars': 4, 'dev': {}, 'heldout': {}},
    {'version': 'v1', 'threshold': True, 'chunk_chars': 12, 'overlap_chars': 4, 'dev': {}, 'heldout': {}},
    {'version': 'v1', 'threshold': 0.5, 'chunk_chars': 0, 'overlap_chars': 0, 'dev': {}, 'heldout': {}},
    {'version': 'v1', 'threshold': 0.5, 'chunk_chars': 12, 'overlap_chars': 12, 'dev': {}, 'heldout': {}},
    {'version': 'v1', 'threshold': 0.5, 'chunk_chars': True, 'overlap_chars': 4, 'dev': {}, 'heldout': {}},
    {'version': 'v1', 'threshold': 0.5, 'chunk_chars': 12, 'overlap_chars': 4, 'dev': 'x', 'heldout': {}},
    {'version': 'v1', 'threshold': 0.5, 'chunk_chars': 12, 'overlap_chars': 4,
     'dev': {'cache': '', 'cache_sha256': 'h'}, 'heldout': {}},
    # missing chunk_chars/overlap_chars
    {'version': 'v1', 'threshold': 0.5, 'dev': {}, 'heldout': {}},
])
def test_invalid_cpu_classifier_config_before_inference(tmp_path, cpu):
    config = valid_config()
    config['cpu_classifier'] = cpu
    path = write_config(tmp_path, config)
    with pytest.raises(ValueError):
        iterate.iterate(path, data=tmp_path / 'data', reports=tmp_path / 'reports')


class _Sentinel(Exception):
    pass


def _assert_config_validation_passed(tmp_path, config, monkeypatch):
    """Write config and source, run iterate, assert no config ValueError is raised."""
    config = config | {'augment': False}
    (tmp_path / 'raw.jsonl').write_text(
        ''.join(json.dumps({'text': f'fixture {i}', 'label': i % 2}) + '\n' for i in range(10)))
    path = write_config(tmp_path, config)
    monkeypatch.setattr(iterate, 'Client', lambda *a, **k: (_ for _ in ()).throw(_Sentinel()))
    with pytest.raises(_Sentinel):
        iterate.iterate(path, data=tmp_path / 'data', reports=tmp_path / 'reports')


def test_absent_optional_stages_pass_config_validation(tmp_path, monkeypatch):
    _assert_config_validation_passed(tmp_path, valid_config(), monkeypatch)


def test_optional_stage_missing_caches_pass_config_validation(tmp_path, monkeypatch):
    # Caches referenced but not on disk: stage is "not available", not an error.
    config = valid_config()
    config['activation_probe'] = {
        'version': 'v1', 'threshold': 0.5,
        'dev': {'cache': 'nonexistent-dev.jsonl', 'cache_sha256': 'abc'},
        'heldout': {'cache': 'nonexistent-heldout.jsonl', 'cache_sha256': 'def'}}
    config['cpu_classifier'] = {
        'version': 'v1', 'threshold': 0.5, 'chunk_chars': 12, 'overlap_chars': 4,
        'dev': {'cache': 'nonexistent-dev.jsonl', 'cache_sha256': 'abc'},
        'heldout': {'cache': 'nonexistent-heldout.jsonl', 'cache_sha256': 'def'}}
    _assert_config_validation_passed(tmp_path, config, monkeypatch)


@pytest.mark.parametrize('option', [None, {}, True,
    {'config': '', 'server_config': 'server.json', 'threshold': 0.5},
    {'config': 'model.json', 'server_config': 'server.json', 'threshold': True},
])
def test_invalid_cpu_classifier_run_before_inference(tmp_path, option):
    config = valid_config() | {'cpu_classifier_run': option}
    with pytest.raises(ValueError, match='cpu_classifier_run'):
        iterate.iterate(write_config(tmp_path, config), data=tmp_path / 'data')


@pytest.fixture
def cpu_iteration(tmp_path, monkeypatch):
    import httpx
    from test_iterate import FakeClient

    from llm_proxy import Client

    config = valid_config() | {'augment': False, 'sample_cap': 25,
                              'cpu_classifier_run': {
                                  'config': 'model.json', 'server_config': 'server.json',
                                  'threshold': 0.5}}
    config['split']['heldout_families'] = []
    (tmp_path / 'raw.jsonl').write_text(''.join(
        json.dumps({'text': f'synthetic fixture {i}', 'label': i % 2}) + '\n'
        for i in range(100)))
    (tmp_path / 'model.json').write_text(json.dumps({
        'model': 'qwen-fixture', 'parameter_count': 2_000_000_000,
        'chunk_chars': 32, 'overlap_chars': 4, 'base_url': 'http://localhost:8081/v1'}))
    (tmp_path / 'server.json').write_text(json.dumps({'evaluator': {
        'host': 'localhost', 'port': 8081, 'gpus': []}}))
    for name in ('MODEL_STAGE_URL', 'MODEL_STAGE_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(iterate, 'Client', lambda *a, **k:
                        Client(*a, **k) if 'model_sets' in k else FakeClient())
    calls, starts = [], []
    ready = [False]

    def get(self, url, **kwargs):
        assert url == 'http://localhost:8081/health'
        return httpx.Response(200 if ready[0] else 503)

    def start(command, **kwargs):
        assert command[2:4] == ['up', 'evaluator']
        assert command[-1] == str(tmp_path / 'server.json')
        starts.append(command)
        ready[0] = True

    def post(self, url, *, content, headers):
        assert url == 'http://localhost:8081/v1/chat/completions'
        assert 'Authorization' not in headers
        request = json.loads(content)
        assert request['model'] == 'qwen-fixture'
        assert request['max_tokens'] == 8
        calls.append(request)
        index = int(request['messages'][1]['content'].split()[-1])
        return httpx.Response(200, json={'choices': [{'message': {'content': str(index % 2)}}]})

    monkeypatch.setattr(httpx.Client, 'get', get)
    monkeypatch.setattr(httpx.Client, 'post', post)
    monkeypatch.setattr('llm_proxy.proxy.subprocess.run', start)
    return write_config(tmp_path, config), tmp_path / 'data', tmp_path / 'reports', calls, starts


def test_cpu_iteration_sample_counts_fusion_and_offline_replay(cpu_iteration, monkeypatch):
    config, data, reports, calls, starts = cpu_iteration
    result = iterate.iterate(config, data=data, reports=reports)
    assert len(starts) == 1
    assert 0 < len(calls) <= 50
    assert result['fusion']['stages'] == ['rules', 'cpu-classifier', 'maya']
    assert result['fusion']['fused_metrics']['detection']['value'] == 1
    assert result['fusion']['fused_metrics']['false_positive']['value'] == 0
    baseline = result['fusion']['without_cpu_classifier']
    assert baseline['stages'] == ['rules', 'maya']
    assert baseline['fused_metrics']['detection']['value'] == 0
    work = next(data.glob('runs/.iterations/*/state.json')).parent
    for evaluation in ('validation', 'held_out'):
        summary = result['cpu_classifier_counts'][evaluation]
        assert 0 < summary['records'] <= 25
        assert summary['entries'] == summary['records']
        assert summary['latency_ms_total'] > 0
        maya_ids = {r['id'] for _, r in iterate.read_rows(work / f'{evaluation}-maya.jsonl')}
        cpu_ids = {r['id'] for _, r in iterate.read_rows(
            work / f'{evaluation}-cpu-classifier-scores.jsonl')}
        assert maya_ids == cpu_ids
    assert 'without_cpu_classifier' in next(reports.glob('*.md')).read_text()
    # Re-export from the SQLite response cache, with no HTTP or lifecycle operations.
    (work / 'complete.json').unlink()
    for path in work.glob('*-cpu-classifier-scores.*'):
        path.unlink()
    monkeypatch.setattr(iterate, 'Client', lambda *a, **k: pytest.fail('new inference'))
    monkeypatch.setattr('httpx.Client.get', lambda *a, **k: pytest.fail('server health check'))
    monkeypatch.setattr('httpx.Client.post', lambda *a, **k: pytest.fail('HTTP request'))
    assert iterate.iterate(config, data=data, reports=reports) == result


def test_cpu_iteration_refusal_stops_and_persisted_failure_blocks(cpu_iteration, monkeypatch):
    import httpx

    from llm_proxy import ProxyError

    config, data, reports, _calls, starts = cpu_iteration
    monkeypatch.setattr(httpx.Client, 'post', lambda *a, **k: httpx.Response(
        200, json={'choices': [{'message': {'refusal': 'synthetic refusal'}}]}))
    with pytest.raises(ProxyError):
        iterate.iterate(config, data=data, reports=reports)
    assert len(starts) == 1
    assert not list(data.rglob('complete.json'))
    monkeypatch.setattr(iterate, 'Client', lambda *a, **k: pytest.fail('drained after refusal'))
    with pytest.raises(ProxyError, match='failed request'):
        iterate.iterate(config, data=data, reports=reports)


def test_cpu_iteration_option_omitted_keeps_existing_workflow(cpu_iteration, monkeypatch):
    config, data, reports, calls, starts = cpu_iteration
    settings = json.loads(config.read_text())
    del settings['cpu_classifier_run']
    config.write_text(json.dumps(settings))
    monkeypatch.setattr(iterate.model_stage, 'write_cache',
                        lambda *a, **k: pytest.fail('CPU classifier called while off'))
    result = iterate.iterate(config, data=data, reports=reports)
    assert not calls and not starts
    assert 'cpu_classifier_counts' not in result
    assert 'without_cpu_classifier' not in result['fusion']
    assert result['fusion']['stages'] == ['rules', 'maya']
