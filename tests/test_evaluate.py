import json
from contextlib import contextmanager

import pytest

from data_processing import evaluate as module
from data_processing.generate import records
from data_processing.normalize import canonical_json, normalize
from llm_proxy import ProxyError


class FakeClient:
    def __init__(self, values):
        self.values, self.jobs, self.calls = values, {}, 0

    def submit_batch(self, model, prompts, **params):
        assert params['chat_template_kwargs'] == {'enable_thinking': False}
        keys = [canonical_json([model, p, params]) for p in prompts]
        for key in keys:
            self.jobs.setdefault(key, {'status': 'pending'})
        return keys

    def result(self, key):
        return self.jobs[key]

    def drain(self):
        for job, value in zip(self.jobs.values(), self.values, strict=True):
            if job['status'] == 'pending':
                self.calls += 1
                job.update(status='done', latency_seconds=0.25, response={
                    'choices': [{'message': {'content': json.dumps(value)}}]})


@pytest.fixture
def candidates(tmp_path):
    reply = {'response': {'choices': [{'message': {'content': json.dumps({
        'plain': 'blueberry', 'paraphrase': 'a blueberry', 'obfuscated': 'Ymx1ZWJlcnJ5',
        'hard_negative': 'An article discusses blueberries.'})}}]}}
    rows = list(records(reply, {'id': 'fixture', 'channel': 'direct', 'technique': 'override'},
                        '2026-11-04T00:00:00Z', 'synthetic', 0))
    raw, source, manifest = [tmp_path / name for name in ('raw', 'source', 'manifest')]
    raw.write_text(''.join(canonical_json(row) + '\n' for row in rows))
    normalize(raw, source, manifest)
    labels = [{field: row[field] for field in ('label', 'channel', 'techniques')} for row in rows]
    return source, manifest, labels


def test_agreement_counts_provenance_and_replay(tmp_path, candidates, capsys):
    source, manifest, labels = candidates
    labels[1] = {'label': 0, 'channel': 'email', 'techniques': []}
    client = FakeClient(labels)
    result = module.evaluate(source, manifest, tmp_path / 'out', client=client)
    evaluator = result['evaluator']
    assert evaluator['candidates'] == 4
    assert evaluator['approved'] == 3 and evaluator['rejected'] == 1
    assert evaluator['approval_rate'] == 0.75
    assert evaluator['disagreements'] == {'label': 1, 'channel': 1, 'techniques': 1}
    assert evaluator['http_latency_seconds'] == 1
    assert result['evaluator_approved'] is True
    output = tmp_path / 'out' / evaluator['run_id']
    approved = [json.loads(line) for line in (output / 'approved.jsonl').read_text().splitlines()]
    assert all(row['label_source'] == 'evaluator' and row['publishable'] == 'no' for row in approved)
    assert len(approved) == 3
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    assert module.evaluate(source, manifest, tmp_path / 'out', client=client) == result
    assert client.calls == 4
    assert before == {p.name: p.read_bytes() for p in output.iterdir()}
    assert capsys.readouterr().out == ''
    assert 'blueberry' not in canonical_json(result)


def test_checksum_before_inference(tmp_path, candidates):
    source, manifest, labels = candidates
    source.write_text('private malformed fixture')
    client = FakeClient(labels)
    with pytest.raises(ValueError, match='checksum'):
        module.evaluate(source, manifest, tmp_path / 'out', client=client)
    assert client.jobs == {}


@pytest.mark.parametrize('bad', [None, {}, {'label': True, 'channel': 'direct', 'techniques': []},
    {'label': 1, 'channel': 'direct', 'techniques': []},
    {'label': 1, 'channel': 'unknown', 'techniques': ['novel']},
    {'label': 1, 'channel': 'direct', 'techniques': ['novel', 'novel']},
    {'label': 0, 'channel': 'direct', 'techniques': ['novel']},
    {'label': 1, 'channel': 'direct', 'techniques': ['private malformed fixture']}])
def test_bad_labels_no_completion(tmp_path, candidates, bad):
    source, manifest, labels = candidates
    labels[0] = bad
    with pytest.raises(ValueError, match='invalid evaluator') as exc:
        module.evaluate(source, manifest, tmp_path / 'out', client=FakeClient(labels))
    assert 'private malformed fixture' not in str(exc.value)
    assert not list((tmp_path / 'out').rglob('manifest.json'))


@pytest.mark.parametrize('failure', [False, True, 'persisted'])
def test_managed_server_stops_and_replay_skips_start(tmp_path, candidates, monkeypatch, failure):
    source, manifest, labels = candidates
    client = FakeClient(labels)
    binary = tmp_path / 'binary'
    binary.write_bytes(b'fixture')
    monkeypatch.setattr(module, 'inventory_model', lambda path: binary)
    monkeypatch.setattr(module, 'Client', lambda *args, **kwargs: client)
    events = []

    @contextmanager
    def server(*args):
        events.append('start')
        try:
            yield 'http://fixture/v1'
        finally:
            events.append('stop')

    if failure:
        def fail():
            raise ProxyError('refusal')
        if failure == 'persisted':
            client.result = lambda key: {'status': 'failed'}
        else:
            client.drain = fail
        with pytest.raises(ProxyError):
            module.evaluate(source, manifest, tmp_path / 'out', binary=binary, server_factory=server)
        assert events == ([] if failure == 'persisted' else ['start', 'stop'])
        assert not list((tmp_path / 'out').rglob('manifest.json'))
    else:
        result = module.evaluate(source, manifest, tmp_path / 'out', binary=binary,
                                 server_factory=server)
        assert events == ['start', 'stop']
        assert client.calls == 4
        assert module.evaluate(source, manifest, tmp_path / 'out', binary=binary,
                               server_factory=server) == result
        assert events == ['start', 'stop']


def test_cpu_server_flags_and_teardown(monkeypatch):
    events = []

    class Process:
        def poll(self):
            return None

        def terminate(self):
            events.append('terminate')

        def wait(self, timeout=None):
            events.append('wait')

    def popen(args, **kwargs):
        assert args[args.index('--n-gpu-layers') + 1] == '0'
        assert args[args.index('--device') + 1] == 'none'
        assert args[args.index('--host') + 1] == '127.0.0.1'
        assert '--no-context-shift' in args
        assert kwargs['env']['ROCR_VISIBLE_DEVICES'] == ''
        return Process()

    class Http:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url):
            return type('Response', (), {'is_success': True})()

    monkeypatch.setattr(module.subprocess, 'Popen', popen)
    monkeypatch.setattr(module.httpx, 'Client', Http)
    with pytest.raises(RuntimeError), module.cpu_server('binary', 'model', 'id'):
        raise RuntimeError('fixture')
    assert events == ['terminate', 'wait']


def test_refusal_response():
    with pytest.raises(ProxyError, match='refusal'):
        module.prediction({'response': {'choices': [{'message': {'refusal': 'fixture'}}]}})


def test_duplicate_ids_before_submission(tmp_path, candidates):
    source, manifest, labels = candidates
    source.write_bytes(source.read_bytes() * 2)
    manifest.write_text(json.dumps({'output_sha256': module.sha256(source)}))
    client = FakeClient(labels)
    with pytest.raises(ValueError, match='duplicate id'):
        module.evaluate(source, manifest, tmp_path / 'out', client=client)
    assert client.jobs == {}


def test_empty_candidates_do_not_drain(tmp_path, candidates):
    source, manifest, _ = candidates
    source.write_bytes(b'')
    manifest.write_text(json.dumps({'output_sha256': module.sha256(source)}))
    client = FakeClient([])
    client.drain = lambda: pytest.fail('empty queue drained')
    result = module.evaluate(source, manifest, tmp_path / 'out', client=client)
    assert result['records'] == 0
    assert result['evaluator']['approval_rate'] is None


def test_server_start_failure_still_reaps_child(monkeypatch):
    events = []

    class Process:
        def poll(self):
            return 1

        def terminate(self):
            pytest.fail('already exited')

    monkeypatch.setattr(module.subprocess, 'Popen', lambda *args, **kwargs: Process())
    with (pytest.raises(ProxyError, match='did not become ready'),
          module.cpu_server('binary', 'model', 'id')):
        events.append('ready')
    assert events == []
