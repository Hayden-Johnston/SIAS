import json
import sqlite3

import httpx
import pytest

from data_processing import model_stage
from data_processing.normalize import normalize
from data_processing.run import digest, replay, windows
from llm_proxy import ProxyError


@pytest.fixture
def stage(tmp_path, monkeypatch):
    for name in ('MODEL_STAGE_URL', 'MODEL_STAGE_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    source = tmp_path / 'source.jsonl'
    rows = []
    for index, label in enumerate([1, 0]):
        rows.append({
            'id': str(index), 'text': 'fixture A' if label else 'fixture B', 'label': label,
            'label_source': 'synthetic', 'attack_family': 'fixture' if label else 'benign',
            'group_id': str(index), 'variant_type': 'plain', 'source': 'synthetic',
            'license': 'CC0-1.0', 'publishable': 'no', 'timestamp': '2026-11-04T00:00:00Z',
            'channel': 'direct', 'techniques': ['novel'] if label else [],
            'spans': [[0, 0, 9]] if label else [],
        })
    source.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    data, manifest = tmp_path / 'data.jsonl', tmp_path / 'manifest.json'
    normalize(source, data, manifest)
    config = tmp_path / 'model.json'
    config.write_text(json.dumps({'model': 'qwen-fixture-pinned', 'parameter_count': 2_000_000_000,
                                  'base_url': 'http://127.0.0.1:8081/v1',
                                  'chunk_chars': 32, 'overlap_chars': 4}))
    calls, replies = [], []

    def post(self, url, *, content, headers):
        request = json.loads(content)
        calls.append((url, self.headers.get('Authorization'), request))
        if replies:
            response = replies.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        text = request['messages'][1]['content']
        return httpx.Response(200, json={'choices': [{'message': {
            'content': '1' if text == 'fixture A' else '0'}}]})

    monkeypatch.setattr(httpx.Client, 'post', post)
    kwargs = {'config_path': config, 'queue_path': tmp_path / 'queue.sqlite',
              'env_file': tmp_path / '.env'}
    return data, manifest, tmp_path / 'scores.jsonl', kwargs, calls, replies


def produce(stage, **options):
    data, manifest, output, kwargs, _, _ = stage
    return model_stage.write_cache(data, manifest, output, **(kwargs | options))


def test_cache_hit_no_http_and_replay_wilson(stage, monkeypatch):
    data, manifest, output, _, calls, _ = stage
    monkeypatch.setenv('MAYA_API_KEY', 'must-not-forward')
    first = produce(stage)
    assert len(calls) == 2
    assert calls[0][0] == 'http://127.0.0.1:8081/v1/chat/completions'
    assert calls[0][1] is None
    assert calls[0][2]['chat_template_kwargs'] == {'enable_thinking': False}
    before = output.read_bytes()
    assert produce(stage) == first
    assert produce(stage, replay_only=True) == first
    assert output.read_bytes() == before
    assert len(calls) == 2
    config = {
        'run_id': 'cpu-model-fixture', 'timestamp': '2026-11-04T00:00:00Z', 'iteration': 0,
        'pipeline_version': 'fixture', 'dataset': data.name, 'dataset_manifest': manifest.name,
        'evaluation_split': 'validation', 'stages': [{
            'name': 'cpu-classifier', 'version': first['version'], 'threshold': 0.5,
            'cache': output.name, 'cache_sha256': first['cache_sha256'],
            'chunk_chars': 32, 'overlap_chars': 4}],
    }
    run_config = data.parent / 'run.json'
    run_config.write_text(json.dumps(config))
    result = replay(run_config, data.parent / 'run')
    assert result['metrics']['tp'] == result['metrics']['tn'] == 1
    assert result['metrics']['detection']['method'] == 'wilson'
    assert result['metrics']['detection']['ci95'][0] == pytest.approx(0.2065493144)
    assert result['metrics']['false_positive']['ci95'][1] == pytest.approx(0.7934506856)
    assert result['stages'][0]['location']['overall']['value'] == 1
    assert result['stages'][0]['cached_latency_ms_total'] == first['latency_ms_total']
    assert len(calls) == 2


def test_interrupted_requests_resume_and_keys_are_deterministic(stage):
    _, _, output, kwargs, calls, replies = stage
    output.write_bytes(b'previous cache')
    replies.extend([httpx.Response(200, json={'choices': [{'message': {'content': '1'}}]}),
                    RuntimeError('simulated interruption')])
    with pytest.raises(RuntimeError, match='interruption'):
        produce(stage)
    assert len(calls) == 2
    assert output.read_bytes() == b'previous cache'
    with sqlite3.connect(kwargs['queue_path']) as db:
        before = db.execute('SELECT key FROM jobs ORDER BY rowid').fetchall()
    produce(stage)
    assert len(calls) == 3  # Only the interrupted request repeats.
    with sqlite3.connect(kwargs['queue_path']) as db:
        assert db.execute('SELECT key FROM jobs ORDER BY rowid').fetchall() == before
    produce(stage, queue_path=output.parent / 'fresh.sqlite')
    with sqlite3.connect(output.parent / 'fresh.sqlite') as db:
        assert db.execute('SELECT key FROM jobs ORDER BY rowid').fetchall() == before


def test_replay_only_miss_preserves_output(stage):
    _, _, output, _, calls, _ = stage
    output.write_bytes(b'previous cache')
    with pytest.raises(ValueError, match='cache miss'):
        produce(stage, replay_only=True)
    assert not calls
    assert output.read_bytes() == b'previous cache'


@pytest.mark.parametrize('response', [
    {'choices': [{'message': {'content': '0.5'}}]},
    {'choices': [{'message': {'content': None}}]},
    {'choices': [{'message': {'content': '1', 'refusal': 'fixture'}}]},
])
def test_invalid_or_refused_response_never_exports(stage, response):
    _, _, output, _, calls, replies = stage
    output.write_bytes(b'previous cache')
    replies.append(httpx.Response(200, json=response))
    with pytest.raises((ValueError, ProxyError)):
        produce(stage)
    assert output.read_bytes() == b'previous cache'
    count = len(calls)
    with pytest.raises((ValueError, ProxyError)):
        produce(stage)
    assert len(calls) == count


@pytest.mark.parametrize('change', [
    {'model': 'GLM-fixture'}, {'parameter_count': 4_000_000_001},
    {'parameter_count': True}, {'overlap_chars': 32}, {'chunk_chars': False},
    {'base_url': 'http://127.0.0.1:8099/v1'}, {'base_url': 'https://example.com/v1'},
    {'base_url': 'http://127.0.0.1:bad/v1'},
])
def test_invalid_config_before_inference(stage, change):
    _, _, _, kwargs, calls, _ = stage
    path = kwargs['config_path']
    path.write_text(json.dumps(json.loads(path.read_text()) | change))
    with pytest.raises(ValueError):
        produce(stage)
    assert not calls


def test_environment_and_model_prompt_text_affect_keys(stage, monkeypatch):
    data, manifest, _, kwargs, calls, _ = stage
    kwargs['env_file'].write_text('MODEL_STAGE_URL=http://localhost:8082/v1\n')
    monkeypatch.setenv('MODEL_STAGE_URL', 'http://localhost:8083/v1')
    monkeypatch.setenv('MODEL_STAGE_API_KEY', 'fixture-key')
    produce(stage)
    assert calls[0][:2] == ('http://localhost:8083/v1/chat/completions', 'Bearer fixture-key')
    config = json.loads(kwargs['config_path'].read_text())
    config['model'] = 'other-pinned'
    kwargs['config_path'].write_text(json.dumps(config))
    produce(stage)
    monkeypatch.setattr(model_stage, 'INSTRUCTION', model_stage.INSTRUCTION + ' Fixture.')
    produce(stage)
    rows = [json.loads(line) for line in data.read_text().splitlines()]
    rows[0]['text'] = 'changed fixture'
    data.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    metadata = json.loads(manifest.read_text())
    metadata['output_sha256'] = digest(data)
    manifest.write_text(json.dumps(metadata))
    produce(stage)
    assert len(calls) == 7  # 2 original, 2 model, 2 prompt, 1 changed text.


def test_multiturn_end_alignment_deduplication_and_empty_turn(stage):
    data, manifest, output, _, calls, _ = stage
    row = json.loads(data.read_text().splitlines()[0])
    row.update(channel='multi_turn', spans=None, text=json.dumps([
        {'role': 'user', 'content': ''}, {'role': 'assistant', 'content': 'x' * 75}]))
    source = data.parent / 'source.jsonl'
    source.write_text(json.dumps(row) + '\n')
    normalize(source, data, manifest)
    summary = produce(stage)
    entries = [json.loads(line) for line in output.read_text().splitlines()]
    assert [(row['turn'], row['start']) for row in entries] == [(0, 0)] + [
        (1, start) for start, _ in windows(75, 32, 4)]
    assert summary['entries'] == 4
    assert len(calls) == 2  # Three identical x chunks share one cached request.
    assert all(set(row) == {'id', 'turn', 'start', 'score', 'latency_ms'} for row in entries)


@pytest.mark.parametrize('damage', ['count', 'checksum', 'duplicate'])
def test_invalid_dataset_before_inference(stage, damage):
    data, manifest, _, _, calls, _ = stage
    metadata = json.loads(manifest.read_text())
    if damage == 'count':
        metadata['records'] += 1
    else:
        data.write_bytes(data.read_bytes() * 2)
        if damage == 'duplicate':
            metadata['output_sha256'] = digest(data)
    manifest.write_text(json.dumps(metadata))
    with pytest.raises(ValueError):
        produce(stage)
    assert not calls


def test_cli_aggregate_output_and_replay_only_failure(stage, monkeypatch, capsys):
    data, manifest, output, kwargs, calls, _ = stage
    args = ['model_stage', str(data), str(output), '--dataset-manifest', str(manifest),
            '--config', str(kwargs['config_path']), '--queue', str(kwargs['queue_path']),
            '--env-file', str(kwargs['env_file'])]
    monkeypatch.setattr('sys.argv', args)
    model_stage.main()
    captured = capsys.readouterr()
    assert json.loads(captured.out)['records'] == 2
    assert 'fixture A' not in captured.out + captured.err
    monkeypatch.setattr('sys.argv', args + ['--replay-only'])
    model_stage.main()
    assert len(calls) == 2
    kwargs['queue_path'].unlink()
    with pytest.raises(SystemExit) as error:
        model_stage.main()
    assert error.value.code == 2
    assert 'cache miss' in capsys.readouterr().err
    assert len(calls) == 2


@pytest.mark.parametrize('text', [None, '[]'])
def test_empty_inputs(stage, text):
    data, manifest, output, _, calls, _ = stage
    row = json.loads(data.read_text().splitlines()[0])
    row.update(channel='multi_turn', text=text, spans=None)
    source = data.parent / 'source.jsonl'
    source.write_text(json.dumps(row) + '\n' if text else '')
    normalize(source, data, manifest)
    summary = produce(stage)
    assert summary['records'] == (1 if text else 0)
    assert summary['entries'] == summary['latency_ms_total'] == 0
    assert summary['score_summary'] == {'min': None, 'max': None, 'mean': None}
    assert output.read_bytes() == b''
    assert not calls
