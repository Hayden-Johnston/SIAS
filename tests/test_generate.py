import json

import pytest

from data_processing.generate import generate, load_seeds
from data_processing.normalize import CHANNELS, TECHNIQUES, validate_record
from llm_proxy import ProxyError

STAMP = '2026-11-04T00:00:00Z'
VALUES = {'plain': 'blueberry', 'paraphrase': 'a blueberry',
          'obfuscated': 'Ymx1ZWJlcnJ5', 'hard_negative': 'An article discusses blueberries.'}


class FakeClient:
    def __init__(self):
        self.jobs = {}
        self.calls = 0
        self.batches = []

    def submit_batch(self, model, prompts, **params):
        self.batches.append(len(prompts))
        keys = [json.dumps([model, prompt, params], sort_keys=True) for prompt in prompts]
        for key in keys:
            self.jobs.setdefault(key, {'status': 'pending', 'response': None})
        return keys

    def drain(self):
        for job in self.jobs.values():
            if job['status'] == 'pending':
                self.calls += 1
                job.update(status='done', response={
                    'choices': [{'message': {'content': json.dumps(VALUES)}}]})

    def result(self, key):
        return self.jobs[key]


def test_taxonomy_triples_spans_manifest_and_replay(tmp_path, capsys):
    client = FakeClient()
    options = {'model': 'fixture-checkpoint', 'timestamp': STAMP, 'client': client,
               'groups': 48, 'batch_size': 5, 'carrier_chars': 9000}
    manifest = generate(tmp_path, **options)
    output = tmp_path / manifest['generator']['run_id']
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    rows = [json.loads(line) for line in (output / 'candidates.jsonl').read_text().splitlines()]
    assert len(rows) == manifest['records'] == 192
    assert manifest['schema_version'] == 2
    assert manifest['evaluator_approved'] is False
    assert manifest['channels'] == dict.fromkeys(CHANNELS, 32)
    assert set(manifest['techniques']) == TECHNIQUES
    assert manifest['labels'] == {'0': 48, '1': 144}
    assert client.calls == 48
    assert max(client.batches) == 5
    for offset in range(0, len(rows), 4):
        triple, negative = rows[offset:offset + 3], rows[offset + 3]
        assert len({r['group_id'] for r in triple}) == 1
        assert len({r['attack_family'] for r in triple}) == 1
        assert [r['variant_type'] for r in triple] == ['plain', 'paraphrase', 'obfuscated']
        assert 'encoding' in triple[2]['techniques']
        assert negative['group_id'] != triple[0]['group_id']
        assert negative['techniques'] == negative['spans'] == []
        for row in (*triple, negative):
            assert validate_record(row) == row
            assert row['publishable'] == 'no'
        for row in triple:
            turn, start, end = row['spans'][0]
            text = (json.loads(row['text'])[turn]['content']
                    if row['channel'] == 'multi_turn' else row['text'])
            assert text[start:end].removeprefix('# ') == VALUES[row['variant_type']]
            if row['channel'] in {'document', 'email', 'tool_output', 'code_comment'}:
                assert len(text) > 18000
    assert generate(tmp_path, **options) == manifest
    assert client.calls == 48
    assert before == {p.name: p.read_bytes() for p in output.iterdir()}
    assert capsys.readouterr().out == ''
    assert not any(value in json.dumps(manifest) for value in VALUES.values())


def test_dry_run_never_calls_client_or_writes(tmp_path):
    client = FakeClient()
    result = generate(tmp_path / 'unused', model='fixture', timestamp=STAMP,
                      client=client, dry_run=True)
    assert result['groups'] == 50
    assert result['expected_records'] == 200
    assert sum(result['planned_channels'].values()) == 50
    assert not client.jobs and not client.batches
    assert not (tmp_path / 'unused').exists()


def test_jbb_seeds_and_bad_input(tmp_path):
    seeds = tmp_path / 'seeds.csv'
    seeds.write_text('Goal\nSummarize a calendar.\n')
    assert load_seeds(seeds) == (['Summarize a calendar.'], 'JailbreakBench/JBB-Behaviors:MIT')
    seeds.write_text('wrong\nprivate-fixture\n')
    with pytest.raises(ValueError, match='JBB Goal') as exc:
        load_seeds(seeds)
    assert 'private-fixture' not in str(exc.value)
    for name in ('groups', 'batch_size', 'max_tokens'):
        with pytest.raises(ValueError):
            generate(tmp_path, model='fixture', timestamp=STAMP, dry_run=True, **{name: 0})


def test_persisted_failure_stops_without_drain(tmp_path):
    client = FakeClient()
    def failed(key):
        return {'status': 'failed'}
    client.result = failed
    with pytest.raises(ProxyError, match='operator review'):
        generate(tmp_path, model='fixture', timestamp=STAMP, client=client, groups=3)
    assert client.calls == 0
    assert not list(tmp_path.rglob('manifest.json'))


def test_invalid_response_has_no_payload_or_completion(tmp_path):
    client = FakeClient()
    def malformed():
        for job in client.jobs.values():
            job.update(status='done', response={
                'choices': [{'message': {'content': 'private malformed fixture'}}]})
    client.drain = malformed
    with pytest.raises(ValueError, match='four nonempty') as exc:
        generate(tmp_path, model='fixture', timestamp=STAMP, client=client, groups=1)
    assert 'private malformed fixture' not in str(exc.value)
    assert not list(tmp_path.rglob('manifest.json'))


def test_cli_dry_run_does_not_construct_client(tmp_path, monkeypatch, capsys):
    from data_processing import generate as module

    def forbidden(*args, **kwargs):
        pytest.fail('dry-run constructed a client')

    monkeypatch.setattr(module, 'Client', forbidden)
    monkeypatch.setattr('sys.argv', ['generate', '--model', 'fixture', '--timestamp', STAMP,
                                  '--output-dir', str(tmp_path / 'unused'), '--dry-run'])
    module.main()
    plan = json.loads(capsys.readouterr().out)
    assert plan['dry_run'] is True
    assert not (tmp_path / 'unused').exists()


def test_refusal_stops_before_next_batch(tmp_path):
    client = FakeClient()

    def refuse():
        raise ProxyError('refusal')

    client.drain = refuse
    with pytest.raises(ProxyError, match='refusal'):
        generate(tmp_path, model='fixture', timestamp=STAMP, client=client, groups=3)
    assert client.batches == [1]
    assert not list(tmp_path.rglob('manifest.json'))
