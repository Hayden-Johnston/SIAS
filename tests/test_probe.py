import json
import subprocess
import sys

import pytest

from data_processing.normalize import canonical_json
from data_processing.probe import write_cache
from data_processing.run import digest, replay

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")
safetensors = pytest.importorskip("safetensors.torch")


def write_json(path, value):
    path.write_text(canonical_json(value) + "\n")


def write_rows(path, rows):
    path.write_text("".join(canonical_json(row) + "\n" for row in rows))


@pytest.fixture
def fixture(tmp_path):
    identity = {"model_identity": {"repo_id": "synthetic", "commit_hash": "fixture",
                                   "weights_sha256": "0" * 64},
                "tokenizer_version": "synthetic-v1", "layers": [0, 3], "dtype": "float16"}
    root = tmp_path / "activation"
    root.mkdir()
    write_json(root / "index.json", {"schema_version": 2, "hidden_size": 2, **identity})
    entries = []
    for i, value in enumerate([-2, -1, 1, 2, -3, 3]):
        key = str(i)
        shard = root / f"{key}.safetensors"
        metadata = {field: canonical_json(v) if field in ("model_identity", "layers") else v
                    for field, v in identity.items()}
        safetensors.save_file({"last_token": torch.tensor([[0, 0], [value, value]],
                                                         dtype=torch.float16)},
                              str(shard), metadata={"prompt_id": key, **metadata})
        entries.append({"id": key, "file": shard.name, "sha256": digest(shard), **identity})
    write_rows(root / "index.jsonl", entries)
    rows = [{"id": str(i), "text": "Synthetic fixture text", "label": int(i in [2, 3, 5]),
             "label_source": "synthetic", "attack_family": "fixture" if i in [2, 3, 5] else "benign",
             "group_id": str(i), "variant_type": "plain", "channel": "direct",
             "techniques": ["novel"] if i in [2, 3, 5] else [], "spans": None if i in [2, 3, 5] else [],
             "source": "synthetic", "license": "CC0-1.0", "publishable": "no",
             "timestamp": "2026-11-05T00:00:00Z"} for i in range(6)]
    write_rows(tmp_path / "dev.jsonl", rows[:4])
    write_rows(tmp_path / "heldout.jsonl", rows[4:])
    write_json(tmp_path / "split_manifest.json", {"schema_version": 2, "splits": {
        "dev": {"output_sha256": digest(tmp_path / "dev.jsonl"), "records": 4}}})
    return root / "index.json", tmp_path / "heldout.jsonl", tmp_path / "cache.jsonl"


def test_deterministic_cli_and_replay(fixture, tmp_path):
    index, dataset, cache = fixture
    first = write_cache(index, dataset, cache, layer=3)
    before = cache.read_bytes()
    assert first == write_cache(index.with_suffix(".jsonl"), dataset, cache, layer=3)
    assert before == cache.read_bytes()
    entries = list(map(json.loads, cache.read_text().splitlines()))
    assert [row["id"] for row in entries] == ["4", "5"]
    assert entries[0]["score"] < 0.5 < entries[1]["score"]
    assert all(set(row) == {"id", "score", "latency_ms"} for row in entries)
    assert "Synthetic fixture text" not in canonical_json(first) + cache.read_text()
    cli = subprocess.run([sys.executable, "-m", "data_processing.probe", str(index), str(dataset),
                          str(cache), "--layer", "3", "--train-split", "dev"],
                         check=False, capture_output=True, text=True)
    assert cli.returncode == 0, cli.stderr
    assert json.loads(cli.stdout) == first
    assert cache.read_bytes() == before
    write_json(tmp_path / "dataset.manifest.json", {"schema_version": 2, "records": 2,
                                                   "output_sha256": digest(dataset)})
    config = {"run_id": "probe-fixture", "timestamp": "2026-11-05T00:00:00Z", "iteration": 0,
              "pipeline_version": "fixture", "dataset": dataset.name,
              "dataset_manifest": "dataset.manifest.json", "evaluation_split": "held_out",
              "stages": [{"name": "probe", "version": first["version"], "threshold": 0.5,
                          "cache": cache.name, "cache_sha256": first["cache_sha256"]}]}
    write_json(tmp_path / "config.json", config)
    result = replay(tmp_path / "config.json", tmp_path / "run")
    assert result["metrics"]["tp"] == result["metrics"]["tn"] == 1
    assert result["metrics"]["fp"] == result["metrics"]["fn"] == 0
    # Scoring labels never influence fitting or scores.
    rows = list(map(json.loads, dataset.read_text().splitlines()))
    for row in rows:
        row.update(label=0, techniques=[], spans=[])
    write_rows(dataset, rows)
    second = write_cache(index, dataset, cache, layer=3)
    assert second["version"] == first["version"]
    assert cache.read_bytes() == before


@pytest.mark.parametrize("field,value", [("model_identity", {}), ("tokenizer_version", "other"),
                                         ("layers", [0]), ("dtype", "float32")])
def test_index_identity_mismatch(fixture, field, value):
    index, dataset, cache = fixture
    entries = list(map(json.loads, index.with_suffix(".jsonl").read_text().splitlines()))
    entries[-1][field] = value
    write_rows(index.with_suffix(".jsonl"), entries)
    with pytest.raises(ValueError, match=f"shard {field} mismatch"):
        write_cache(index, dataset, cache, layer=3)
    assert not cache.exists()


def test_shard_metadata_and_checksum(fixture):
    index, dataset, cache = fixture
    shard = index.parent / "5.safetensors"
    tensors = safetensors.load_file(str(shard))
    safetensors.save_file(tensors, str(shard), metadata={"prompt_id": "5"})
    with pytest.raises(ValueError, match="checksum"):
        write_cache(index, dataset, cache, layer=3)
    entries = list(map(json.loads, index.with_suffix(".jsonl").read_text().splitlines()))
    entries[-1]["sha256"] = digest(shard)
    write_rows(index.with_suffix(".jsonl"), entries)
    with pytest.raises(ValueError, match="metadata identity"):
        write_cache(index, dataset, cache, layer=3)


@pytest.mark.parametrize("missing", ["0", "5"])
def test_missing_ids_and_atomic_output(fixture, missing):
    index, dataset, cache = fixture
    cache.write_text("previous cache\n")
    entries = list(map(json.loads, index.with_suffix(".jsonl").read_text().splitlines()))
    write_rows(index.with_suffix(".jsonl"), [row for row in entries if row["id"] != missing])
    with pytest.raises(ValueError, match='missing activation ids: \\["' + missing + '"\\]'):
        write_cache(index, dataset, cache, layer=3)
    assert cache.read_text() == "previous cache\n"


def test_layer_version_and_training_validation(fixture):
    index, dataset, cache = fixture
    first = write_cache(index, dataset, cache, layer=3)
    assert write_cache(index, dataset, cache, layer=0)["version"] != first["version"]
    with pytest.raises(ValueError, match="layer"):
        write_cache(index, dataset, cache, layer=2)
    with pytest.raises(ValueError, match="train-split"):
        write_cache(index, dataset, cache, layer=3, train_split="heldout")
    with pytest.raises(ValueError, match="overwrite"):
        write_cache(index, dataset, index, layer=3)
    train = dataset.parent / "dev.jsonl"
    train.write_text(train.read_text().replace("Synthetic fixture text", "Changed fixture text"))
    with pytest.raises(ValueError, match="checksum/count"):
        write_cache(index, dataset, cache, layer=3)


def test_incomplete_append_is_not_committed(fixture):
    index, dataset, cache = fixture
    first = write_cache(index, dataset, cache, layer=3)
    with index.with_suffix(".jsonl").open("ab") as writer:
        writer.write(b'{"id":')
    assert write_cache(index, dataset, cache, layer=3) == first
