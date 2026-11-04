"""Edge-case tests for generate.py: invalid params, missing fields, cache reuse."""

import json

import pytest

from data_processing.generate import GenerationUnavailable, generate
from data_processing.normalize import canonical_json

STAMP = '2026-11-04T00:00:00Z'
VALUES = {'plain': 'blueberry', 'paraphrase': 'a blueberry',
          'obfuscated': 'Ymx1ZWJlcnJ5', 'hard_negative': 'An article discusses blueberries.'}


class FakeClient:
    def __init__(self, value=None):
        self.value = value if value is not None else VALUES
        self.jobs = {}
        self.drain_calls = 0
        self.batches = []

    def submit_batch(self, model, prompts, **params):
        self.batches.append(len(prompts))
        keys = [canonical_json([model, p, params]) for p in prompts]
        for key in keys:
            self.jobs.setdefault(key, {'status': 'pending'})
        return keys

    def result(self, key):
        return self.jobs[key]

    def drain(self):
        for job in self.jobs.values():
            if job['status'] == 'pending':
                self.drain_calls += 1
                job.update(status='done', response={
                    'choices': [{'message': {'content': json.dumps(self.value)}}]})


def test_zero_groups_rejected(tmp_path):
    with pytest.raises(ValueError, match='groups'):
        generate(tmp_path, model='fixture', timestamp=STAMP, groups=0)


def test_negative_carrier_chars_rejected(tmp_path):
    with pytest.raises(ValueError, match='carrier_chars'):
        generate(tmp_path, model='fixture', timestamp=STAMP, carrier_chars=-1)


def test_missing_obfuscated_field(tmp_path):
    # Response missing the 'obfuscated' variant.
    bad = {'plain': 'x', 'paraphrase': 'y', 'hard_negative': 'z'}
    client = FakeClient(value=bad)
    with pytest.raises(ValueError, match='four nonempty'):
        generate(tmp_path, model='fixture', timestamp=STAMP, client=client, groups=1)
    assert not list(tmp_path.rglob('manifest.json'))


def test_missing_hard_negative_field(tmp_path):
    # Response missing the 'hard_negative' field.
    bad = {'plain': 'x', 'paraphrase': 'y', 'obfuscated': 'z'}
    client = FakeClient(value=bad)
    with pytest.raises(ValueError, match='four nonempty'):
        generate(tmp_path, model='fixture', timestamp=STAMP, client=client, groups=1)
    assert not list(tmp_path.rglob('manifest.json'))


def test_extra_field_in_response(tmp_path):
    # Response has an unexpected fifth field.
    bad = {**VALUES, 'surprise': 'w'}
    client = FakeClient(value=bad)
    with pytest.raises(ValueError, match='four nonempty'):
        generate(tmp_path, model='fixture', timestamp=STAMP, client=client, groups=1)
    assert not list(tmp_path.rglob('manifest.json'))


def test_cached_response_reuse_replay_only(tmp_path):
    client = FakeClient()
    options = {'model': 'fixture', 'timestamp': STAMP, 'client': client, 'groups': 2}
    result = generate(tmp_path, **options)
    # Replay: all responses are now done; drain must not be called.
    client.drain = lambda: pytest.fail('replay drained queue')
    result2 = generate(tmp_path, **options, replay_only=True)
    assert result == result2
    assert client.drain_calls == 2  # only from the first call


def test_replay_only_cache_miss_raises(tmp_path):
    client = FakeClient()
    # No drain, so responses stay pending.
    with pytest.raises(GenerationUnavailable, match='replay-only'):
        generate(tmp_path, model='fixture', timestamp=STAMP,
                 client=client, groups=1, replay_only=True)
    assert client.drain_calls == 0
