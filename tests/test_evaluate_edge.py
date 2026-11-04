"""Edge-case tests for evaluate.py: empty input, invalid labels, cache reuse, missing fields."""

import json

import pytest

from data_processing import evaluate as module
from data_processing.normalize import canonical_json, normalize


class FakeClient:
    def __init__(self, values):
        self.values = values
        self.jobs = {}
        self.drain_calls = 0

    def submit_batch(self, model, prompts, **params):
        keys = [canonical_json([model, p, params]) for p in prompts]
        for key in keys:
            self.jobs.setdefault(key, {'status': 'pending'})
        return keys

    def result(self, key):
        return self.jobs[key]

    def drain(self):
        for job, value in zip(self.jobs.values(), self.values, strict=True):
            if job['status'] == 'pending':
                self.drain_calls += 1
                job.update(status='done', latency_seconds=0, response={
                    'choices': [{'message': {'content': json.dumps(value)}}]})


@pytest.fixture
def candidates(tmp_path):
    """Two valid attack rows and one benign row, normalized."""
    rows = [
        {'id': 'a1', 'text': 'attack one', 'label': 1, 'label_source': 'gen',
         'attack_family': 'fam', 'group_id': 'g1', 'variant_type': 'plain',
         'source': 's', 'license': 'l', 'publishable': 'no',
         'timestamp': '2026-11-04T00:00:00Z', 'channel': 'direct',
         'techniques': ['novel'], 'spans': [[0, 0, 10]]},
        {'id': 'a2', 'text': 'attack two', 'label': 1, 'label_source': 'gen',
         'attack_family': 'fam', 'group_id': 'g2', 'variant_type': 'paraphrase',
         'source': 's', 'license': 'l', 'publishable': 'no',
         'timestamp': '2026-11-04T00:00:00Z', 'channel': 'email',
         'techniques': ['novel'], 'spans': [[0, 0, 10]]},
        {'id': 'b1', 'text': 'benign text', 'label': 0, 'label_source': 'gen',
         'attack_family': 'benign', 'group_id': 'g3', 'variant_type': 'plain',
         'source': 's', 'license': 'l', 'publishable': 'no',
         'timestamp': '2026-11-04T00:00:00Z', 'channel': 'direct',
         'techniques': [], 'spans': []},
    ]
    raw = tmp_path / 'raw.jsonl'
    source = tmp_path / 'source.jsonl'
    manifest = tmp_path / 'source.manifest.json'
    raw.write_text(''.join(canonical_json(r) + '\n' for r in rows))
    normalize(raw, source, manifest)
    labels = [{'label': r['label'], 'channel': r['channel'], 'techniques': r['techniques']}
              for r in rows]
    return source, manifest, labels


def test_empty_candidate_list(tmp_path):
    raw = tmp_path / 'raw.jsonl'
    source = tmp_path / 'source.jsonl'
    manifest = tmp_path / 'source.manifest.json'
    raw.write_bytes(b'')
    normalize(raw, source, manifest)
    client = FakeClient([])
    result = module.evaluate(source, manifest, tmp_path / 'out', client=client)
    assert result['records'] == 0
    assert result['evaluator']['approval_rate'] is None
    assert result['evaluator']['approved'] == 0
    assert client.drain_calls == 0


def test_invalid_label_evaluator_returns_none(tmp_path, candidates):
    source, manifest, _ = candidates
    # Evaluator returns JSON null instead of an object.
    client = FakeClient([None, None, None])
    with pytest.raises(ValueError, match='invalid evaluator'):
        module.evaluate(source, manifest, tmp_path / 'out', client=client)
    assert not list((tmp_path / 'out').rglob('manifest.json'))


def test_cached_response_reuse(tmp_path, candidates):
    source, manifest, labels = candidates
    client = FakeClient(labels)
    result1 = module.evaluate(source, manifest, tmp_path / 'out', client=client)
    calls_after_first = client.drain_calls
    result2 = module.evaluate(source, manifest, tmp_path / 'out', client=client)
    assert result1 == result2
    # Second call reuses cached done results; no additional drain needed.
    assert client.drain_calls == calls_after_first


def test_taxonomy_triple_missing_channel(tmp_path, candidates):
    source, manifest, labels = candidates
    # Evaluator returns a triple missing the 'channel' field.
    bad = {'label': 1, 'techniques': ['novel']}
    client = FakeClient([bad, labels[1], labels[2]])
    with pytest.raises(ValueError, match='invalid evaluator'):
        module.evaluate(source, manifest, tmp_path / 'out', client=client)
    assert not list((tmp_path / 'out').rglob('manifest.json'))


def test_taxonomy_triple_extra_field(tmp_path, candidates):
    source, manifest, labels = candidates
    # Evaluator returns a triple with an unexpected extra field.
    bad = {'label': 1, 'channel': 'direct', 'techniques': ['novel'], 'extra': 'x'}
    client = FakeClient([bad, labels[1], labels[2]])
    with pytest.raises(ValueError, match='invalid evaluator'):
        module.evaluate(source, manifest, tmp_path / 'out', client=client)
    assert not list((tmp_path / 'out').rglob('manifest.json'))
