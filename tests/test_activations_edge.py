"""Edge-case tests for data_processing/activations.py: empty shards, bad layer lists,
append-only index growth, and missing shard files."""

import json

import pytest

from data_processing.activations import (
    capture_activations,
    load_model_and_tokenizer,
    select_layers,
    validate_existing_index,
)
from data_processing.normalize import normalize
from data_processing.run import atomic_write, canonical_json

torch = pytest.importorskip("torch")

from data_processing.activations import DEFAULT_MODEL


def _make_identity():
    return {
        "repo_id": "test/model",
        "commit_hash": "abc123",
        "weights_sha256": "f" * 64,
    }


def _make_entry(prompt_id, file_path, sha256, identity, tok_version, layers, dtype):
    return {
        "id": prompt_id,
        "file": file_path,
        "sha256": sha256,
        "bytes": 100,
        "token_count": 10,
        "raw_token_count": 10,
        "truncated": False,
        "has_per_token": False,
        "model_identity": identity,
        "tokenizer_version": tok_version,
        "layers": layers,
        "dtype": dtype,
    }


def _write_index_v2(out_dir, identity, tok_version, layers, dtype, entries):
    """Write a schema_version 2 index and its jsonl entries."""
    index = {
        "schema_version": 2,
        "status": "complete",
        "model_identity": identity,
        "tokenizer_version": tok_version,
        "layers": layers,
        "dtype": dtype,
        "hidden_size": 32,
        "max_tokens": 512,
        "records": len(entries),
        "truncated_count": 0,
        "per_token_count": 0,
    }
    atomic_write(out_dir / "index.json", (canonical_json(index) + "\n").encode("utf-8"))
    entries_path = out_dir / "index.jsonl"
    data = b"".join((canonical_json(e) + "\n").encode("utf-8") for e in entries)
    atomic_write(entries_path, data)


# --- select_layers: invalid and duplicate layer lists ---


def test_select_layers_empty_list_raises():
    with pytest.raises(ValueError, match="layers"):
        select_layers(10, layers=[])


def test_select_layers_duplicate_indices_raises():
    with pytest.raises(ValueError, match="layers"):
        select_layers(10, layers=[0, 2, 2])


def test_select_layers_non_integer_element_raises():
    with pytest.raises(ValueError, match="layers"):
        select_layers(10, layers=[0, "2"])


def test_select_layers_negative_index_raises():
    with pytest.raises(ValueError, match="layers"):
        select_layers(10, layers=[-1])


def test_select_layers_out_of_bounds_raises():
    with pytest.raises(ValueError, match="layers"):
        select_layers(10, layers=[10])


def test_select_layers_valid_returns_sorted():
    assert select_layers(10, layers=[5, 1, 3]) == [1, 3, 5]


# --- Empty shard file (0 bytes) is rejected ---


def test_validate_existing_index_rejects_empty_shard_file(tmp_path):
    identity = _make_identity()
    tok_version = "tok-v1"
    layers = [0]
    dtype = "float16"
    entry = _make_entry("p1", "shards/p1.safetensors", "a" * 64, identity, tok_version, layers, dtype)
    _write_index_v2(tmp_path, identity, tok_version, layers, dtype, [entry])
    # Create the shard file with 0 bytes (empty).
    (tmp_path / "shards").mkdir()
    (tmp_path / "shards" / "p1.safetensors").write_bytes(b"")

    with pytest.raises(ValueError, match="missing or checksum mismatch"):
        validate_existing_index(
            tmp_path / "index.json", tmp_path, identity, tok_version, layers, dtype
        )


# --- Missing shard file is rejected ---


def test_validate_existing_index_rejects_missing_shard_file(tmp_path):
    identity = _make_identity()
    tok_version = "tok-v1"
    layers = [0]
    dtype = "float16"
    entry = _make_entry("p1", "shards/p1.safetensors", "a" * 64, identity, tok_version, layers, dtype)
    _write_index_v2(tmp_path, identity, tok_version, layers, dtype, [entry])
    # Create the shards directory but NOT the shard file.
    (tmp_path / "shards").mkdir()

    with pytest.raises(ValueError, match="missing or checksum mismatch"):
        validate_existing_index(
            tmp_path / "index.json", tmp_path, identity, tok_version, layers, dtype
        )


# --- Append-only index growth across two captures ---


@pytest.fixture(scope="module")
def tiny_lm():
    try:
        return load_model_and_tokenizer(DEFAULT_MODEL, device="cpu")
    except (OSError, ValueError, RuntimeError) as exc:
        pytest.skip(f"tiny model unavailable: {exc}")


@pytest.fixture
def synthetic_dataset(tmp_path):
    source = tmp_path / "source.jsonl"
    data = tmp_path / "dataset.jsonl"
    manifest = tmp_path / "dataset.manifest.json"
    rows = [
        {"id": "p1", "body": "Hello world one."},
        {"id": "p2", "body": "Hello world two."},
        {"id": "p3", "body": "Hello world three."},
    ]
    mapping = {
        "fields": {"id": "id", "text": "body"},
        "defaults": {
            "label": 0,
            "label_source": "synthetic-fixture",
            "attack_family": "benign",
            "group_id": "synthetic-group",
            "variant_type": "plain",
            "channel": "direct",
            "techniques": [],
            "spans": [],
            "source": "synthetic-fixture",
            "license": "CC0-1.0",
            "publishable": "no",
            "timestamp": "2026-11-04T00:00:00Z",
        },
    }
    source.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    normalize(source, data, manifest, mapping)
    return data, manifest, tmp_path / "activations"


def test_index_jsonl_is_append_only_across_two_captures(tiny_lm, synthetic_dataset, tmp_path):
    model, tokenizer = tiny_lm
    data, _, out_dir = synthetic_dataset
    kwargs = {"model": model, "tokenizer": tokenizer, "min_free_bytes": 0}

    # First capture: 2 rows.
    partial = tmp_path / "partial.jsonl"
    lines = data.read_text(encoding="utf-8").splitlines(keepends=True)
    partial.write_text("".join(lines[:2]), encoding="utf-8")
    capture_activations(partial, out_dir, **kwargs)
    first_bytes = (out_dir / "index.jsonl").read_bytes()
    assert len(first_bytes) > 0

    # Second capture: full 3-row dataset into the same directory.
    capture_activations(data, out_dir, **kwargs)
    second_bytes = (out_dir / "index.jsonl").read_bytes()

    # The file must be strictly longer and the first capture's bytes must be a prefix.
    assert len(second_bytes) > len(first_bytes)
    assert second_bytes.startswith(first_bytes)

    # Exactly 3 total entries.
    entries = [json.loads(line) for line in second_bytes.decode().splitlines()]
    assert len(entries) == 3
    assert [e["id"] for e in entries] == ["p1", "p2", "p3"]
