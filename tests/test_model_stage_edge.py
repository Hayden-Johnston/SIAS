"""Edge-case tests for model_stage.py chunking/windowing not covered by test_model_stage.py."""

import json

import httpx
import pytest

from data_processing import model_stage
from data_processing.normalize import normalize


@pytest.fixture
def stage(tmp_path, monkeypatch):
    for name in ('MODEL_STAGE_URL', 'MODEL_STAGE_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    source = tmp_path / 'source.jsonl'
    row = {
        'id': '0', 'text': 'x', 'label': 0, 'label_source': 'synthetic',
        'attack_family': 'benign', 'group_id': '0', 'variant_type': 'plain',
        'source': 'synthetic', 'license': 'CC0-1.0', 'publishable': 'no',
        'timestamp': '2026-11-05T00:00:00Z', 'channel': 'direct',
        'techniques': [], 'spans': [],
    }
    source.write_text(json.dumps(row) + '\n')
    data, manifest = tmp_path / 'data.jsonl', tmp_path / 'manifest.json'
    normalize(source, data, manifest)
    config = tmp_path / 'model.json'
    config.write_text(json.dumps({'model': 'qwen-fixture-pinned', 'parameter_count': 2_000_000_000,
                                  'base_url': 'http://127.0.0.1:8081/v1',
                                  'chunk_chars': 32, 'overlap_chars': 4}))
    monkeypatch.setattr(httpx.Client, 'post',
                        lambda self, url, *, content, headers: httpx.Response(
                            200, json={'choices': [{'message': {'content': '0'}}]}))
    kwargs = {'config_path': config, 'queue_path': tmp_path / 'queue.sqlite',
              'env_file': tmp_path / '.env'}
    return data, manifest, tmp_path / 'scores.jsonl', kwargs


def _set_text(data, manifest, text, channel='direct'):
    row = {
        'id': '0', 'text': text, 'label': 0, 'label_source': 'synthetic',
        'attack_family': 'benign', 'group_id': '0', 'variant_type': 'plain',
        'source': 'synthetic', 'license': 'CC0-1.0', 'publishable': 'no',
        'timestamp': '2026-11-05T00:00:00Z', 'channel': channel,
        'techniques': [], 'spans': [],
    }
    source = data.parent / 'source.jsonl'
    source.write_text(json.dumps(row) + '\n')
    normalize(source, data, manifest)


def test_text_shorter_than_chunk_gives_one_chunk(stage):
    data, manifest, output, kwargs = stage
    _set_text(data, manifest, 'a' * 10)  # 10 < 32 (chunk_chars)
    summary = model_stage.write_cache(data, manifest, output, **kwargs)
    entries = [json.loads(line) for line in output.read_text().splitlines()]
    assert summary['entries'] == 1
    assert entries[0]['turn'] == 0 and entries[0]['start'] == 0


def test_text_exactly_chunk_chars_gives_one_chunk(stage):
    data, manifest, output, kwargs = stage
    _set_text(data, manifest, 'b' * 32)  # exactly 32 == chunk_chars
    summary = model_stage.write_cache(data, manifest, output, **kwargs)
    entries = [json.loads(line) for line in output.read_text().splitlines()]
    assert summary['entries'] == 1
    assert entries[0]['turn'] == 0 and entries[0]['start'] == 0


def test_chunks_never_cross_turns(stage):
    data, manifest, output, kwargs = stage
    turns = [
        {'role': 'user', 'content': 'A' * 50},
        {'role': 'assistant', 'content': 'B' * 50},
    ]
    _set_text(data, manifest, json.dumps(turns), channel='multi_turn')
    summary = model_stage.write_cache(data, manifest, output, **kwargs)
    entries = [json.loads(line) for line in output.read_text().splitlines()]
    assert summary['entries'] == len(entries)
    # Each chunk's [start, start+chunk_chars) must fit within its turn's text length.
    for entry in entries:
        turn_text = turns[entry['turn']]['content']
        assert entry['start'] + 32 <= len(turn_text), (
            f"chunk start={entry['start']} exceeds turn {entry['turn']} length {len(turn_text)}")
