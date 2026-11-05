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
