"""Edge-case tests for probe.py: single-class dev, missing shard, determinism, identity mismatch."""

import json

import pytest

from data_processing.normalize import canonical_json
from data_processing.probe import write_cache
from data_processing.run import digest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")
safetensors = pytest.importorskip("safetensors.torch")


def write_json(path, value):
    path.write_text(canonical_json(value) + "\n")


def write_rows(path, rows):
    path.write_text("".join(canonical_json(row) + "\n" for row in rows))


def make_row(i, label):
    return {
        "id": str(i), "text": "Synthetic fixture text", "label": label,
        "label_source": "synthetic",
        "attack_family": "fixture" if label else "benign",
        "group_id": str(i), "variant_type": "plain", "channel": "direct",
        "techniques": ["novel"] if label else [],
        "spans": None if label else [],
        "source": "synthetic", "license": "CC0-1.0", "publishable": "no",
        "timestamp": "2026-11-05T00:00:00Z",
    }


@pytest.fixture
def fixture(tmp_path):
    """Build a minimal two-class activation fixture in tmp_path."""
    identity = {
        "model_identity": {"repo_id": "synthetic", "commit_hash": "fixture",
                           "weights_sha256": "0" * 64},
        "tokenizer_version": "synthetic-v1", "layers": [0, 3], "dtype": "float16",
    }
    root = tmp_path / "activation"
    root.mkdir()
    write_json(root / "index.json", {"schema_version": 2, "hidden_size": 2, **identity})
    entries = []
    for i, value in enumerate([-2, -1, 1, 2, -3, 3]):
        key = str(i)
        shard = root / f"{key}.safetensors"
        metadata = {
            field: canonical_json(v) if field in ("model_identity", "layers") else v
            for field, v in identity.items()
        }
        safetensors.save_file(
            {"last_token": torch.tensor([[0, 0], [value, value]], dtype=torch.float16)},
            str(shard), metadata={"prompt_id": key, **metadata},
        )
        entries.append({"id": key, "file": shard.name, "sha256": digest(shard), **identity})
    write_rows(root / "index.jsonl", entries)
    # dev: two of each class; heldout: one of each
    write_rows(tmp_path / "dev.jsonl", [make_row(i, int(i in (1, 3))) for i in range(4)])
    write_rows(tmp_path / "heldout.jsonl", [make_row(4, 0), make_row(5, 1)])
    write_json(tmp_path / "split_manifest.json", {
        "schema_version": 2,
        "splits": {"dev": {"output_sha256": digest(tmp_path / "dev.jsonl"), "records": 4}},
    })
    return root / "index.json", tmp_path / "heldout.jsonl", tmp_path / "cache.jsonl"


def test_single_class_dev_raises(fixture):
    """A dev set with only one label must produce a clear error."""
    index, dataset, cache = fixture
    dev = fixture[0].parent.parent / "dev.jsonl"
    write_rows(dev, [make_row(i, 0) for i in range(4)])
    write_json(fixture[0].parent.parent / "split_manifest.json", {
        "schema_version": 2,
        "splits": {"dev": {"output_sha256": digest(dev), "records": 4}},
    })
    with pytest.raises(ValueError, match="both labels"):
        write_cache(index, dataset, cache, layer=3)
    assert not cache.exists()


def test_missing_shard_file_raises(fixture, tmp_path):
    """A shard file that is absent from disk must raise, not silently skip."""
    index, dataset, cache = fixture
    shard = index.parent / "3.safetensors"
    shard.unlink()
    with pytest.raises((ValueError, OSError)):
        write_cache(index, dataset, cache, layer=3)
    assert not cache.exists()


def test_determinism_across_two_runs(fixture):
    """Two identical runs must produce byte-identical caches with equal scores."""
    index, dataset, cache = fixture
    first = write_cache(index, dataset, cache, layer=3)
    first_bytes = cache.read_bytes()
    first_rows = list(map(json.loads, first_bytes.decode().splitlines()))
    second = write_cache(index, dataset, cache, layer=3)
    second_bytes = cache.read_bytes()
    second_rows = list(map(json.loads, second_bytes.decode().splitlines()))
    assert first == second
    assert first_bytes == second_bytes
    for a, b in zip(first_rows, second_rows):
        assert a["score"] == b["score"]


def test_identity_mismatch_refused(fixture):
    """An entry whose identity field differs from the index header must be refused."""
    index, dataset, cache = fixture
    entries = list(map(json.loads, index.with_suffix(".jsonl").read_text().splitlines()))
    entries[0]["tokenizer_version"] = "tampered"
    write_rows(index.with_suffix(".jsonl"), entries)
    with pytest.raises(ValueError, match="shard tokenizer_version mismatch"):
        write_cache(index, dataset, cache, layer=3)
    assert not cache.exists()
