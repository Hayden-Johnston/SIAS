import json
import shutil
import subprocess
import sys
from collections import namedtuple
from unittest.mock import patch

import pytest

from data_processing.activations import (
    DEFAULT_MODEL,
    capture_activations,
    load_model_and_tokenizer,
)
from data_processing.normalize import normalize
from data_processing.run import digest

torch = pytest.importorskip("torch")
safetensors_torch = pytest.importorskip("safetensors.torch")
from safetensors import safe_open

DiskUsage = namedtuple("DiskUsage", ["total", "used", "free"])


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
        {"id": "benign-1", "body": "Summarize the quarterly weather report for coastal towns."},
        {"id": "benign-2", "body": "List three common vegetables grown in a summer garden."},
        {"id": "benign-3", "body": "Explain how bicycles use gears to climb steep hills."},
        {"id": "benign-4", "body": "Write a short thank-you note for a birthday book gift."},
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


def test_shapes_dtype_and_shard_metadata(tiny_lm, synthetic_dataset):
    model, tokenizer = tiny_lm
    data, manifest, out_dir = synthetic_dataset
    summary = capture_activations(
        data,
        out_dir,
        dataset_manifest=manifest,
        model=model,
        tokenizer=tokenizer,
        per_token_count=1,
        seed=7,
        min_free_bytes=0,
    )
    assert summary["status"] == "complete"
    assert summary["records"] == 4
    assert summary["captured"] == 4
    assert summary["skipped"] == 0
    assert summary["per_token_count"] == 1
    assert summary["dtype"] == "float16"
    assert summary["layers"] == [0]

    index = json.loads((out_dir / "index.json").read_text(encoding="utf-8"))
    hidden_size = int(model.config.hidden_size)
    per_token_seen = 0

    for prompt_id, entry in index["shards"].items():
        assert entry["model_identity"] == index["model_identity"]
        assert entry["tokenizer_version"] == index["tokenizer_version"]
        assert entry["layers"] == [0]
        assert entry["dtype"] == "float16"
        shard_path = out_dir / entry["file"]
        assert shard_path.is_file()
        assert digest(shard_path) == entry["sha256"]

        tensors = safetensors_torch.load_file(str(shard_path))
        assert tensors["last_token"].dtype == torch.float16
        assert tensors["mean_pooled"].dtype == torch.float16
        assert tensors["last_token"].shape == (1, hidden_size)
        assert tensors["mean_pooled"].shape == (1, hidden_size)

        with safe_open(str(shard_path), framework="pt") as handle:
            meta = handle.metadata()
        assert meta["prompt_id"] == prompt_id
        assert json.loads(meta["model_identity"]) == index["model_identity"]
        assert meta["tokenizer_version"] == index["tokenizer_version"]
        assert json.loads(meta["layers"]) == [0]
        assert meta["dtype"] == "float16"

        if entry["has_per_token"]:
            per_token_seen += 1
            assert "per_token" in tensors
            assert tensors["per_token"].dtype == torch.float16
            assert tensors["per_token"].shape == (1, entry["token_count"], hidden_size)
            assert torch.equal(tensors["last_token"], tensors["per_token"][:, -1, :])
        else:
            assert "per_token" not in tensors

    assert per_token_seen == 1


def test_layer_selection_and_truncation(tiny_lm, synthetic_dataset):
    model, tokenizer = tiny_lm
    data, _, out_dir = synthetic_dataset
    num_layers = int(model.config.num_hidden_layers)
    hidden_size = int(model.config.hidden_size)
    all_layers = list(range(num_layers))

    summary = capture_activations(
        data,
        out_dir,
        model=model,
        tokenizer=tokenizer,
        layers=all_layers,
        max_tokens=4,
        per_token_fraction=1.0,
        min_free_bytes=0,
    )
    assert summary["layers"] == all_layers
    assert summary["truncated_count"] == 4

    index = json.loads((out_dir / "index.json").read_text(encoding="utf-8"))
    for entry in index["shards"].values():
        assert entry["truncated"] is True
        assert entry["token_count"] == 4
        assert entry["raw_token_count"] > 4
        shard_path = out_dir / entry["file"]
        tensors = safetensors_torch.load_file(str(shard_path))
        assert tensors["last_token"].shape == (num_layers, hidden_size)
        assert tensors["mean_pooled"].shape == (num_layers, hidden_size)
        assert tensors["per_token"].shape == (num_layers, 4, hidden_size)
        with safe_open(str(shard_path), framework="pt") as handle:
            assert handle.metadata()["truncated"] == "true"

    with pytest.raises(ValueError, match="layers"):
        capture_activations(
            data,
            out_dir / "bad",
            model=model,
            tokenizer=tokenizer,
            layers=[num_layers + 5],
            min_free_bytes=0,
        )


def test_resume_skips_done_ids_and_is_deterministic(tiny_lm, synthetic_dataset, tmp_path):
    model, tokenizer = tiny_lm
    data, _, out_dir = synthetic_dataset
    partial_data = tmp_path / "partial.jsonl"
    lines = data.read_text(encoding="utf-8").splitlines(keepends=True)
    partial_data.write_text("".join(lines[:2]), encoding="utf-8")

    first = capture_activations(
        partial_data,
        out_dir,
        model=model,
        tokenizer=tokenizer,
        per_token_count=2,
        seed=42,
        min_free_bytes=0,
    )
    assert first["captured"] == 2
    assert first["skipped"] == 0
    assert first["records"] == 2
    shard_1_path = out_dir / "shards/benign-1.safetensors"
    shard_1_bytes = shard_1_path.read_bytes()

    with patch.object(model, "forward", wraps=model.forward) as spy_forward:
        resumed = capture_activations(
            data,
            out_dir,
            model=model,
            tokenizer=tokenizer,
            per_token_count=2,
            seed=42,
            min_free_bytes=0,
        )
        assert spy_forward.call_count == 2

    assert resumed["captured"] == 2
    assert resumed["skipped"] == 2
    assert resumed["records"] == 4
    assert shard_1_path.read_bytes() == shard_1_bytes

    index_before_rerun = (out_dir / "index.json").read_bytes()
    with patch.object(model, "forward", wraps=model.forward) as spy_forward:
        rerun = capture_activations(
            data,
            out_dir,
            model=model,
            tokenizer=tokenizer,
            per_token_count=2,
            seed=42,
            min_free_bytes=0,
        )
        assert spy_forward.call_count == 0
    assert rerun["captured"] == 0
    assert rerun["skipped"] == 4
    assert (out_dir / "index.json").read_bytes() == index_before_rerun

    # Interrupted run on the same dataset followed by resume gives byte-identical output to a fresh run.
    resumed_same_dir = tmp_path / "resumed_same"
    limit = 1024 * 1024
    usages = iter([
        DiskUsage(limit * 2, 0, limit * 2),
        DiskUsage(limit * 2, 0, limit * 2),
        DiskUsage(limit * 2, 0, limit * 2),
        DiskUsage(limit * 2, 0, limit * 2),
        DiskUsage(limit * 2, 0, limit * 2),
        DiskUsage(limit * 2, 0, limit - 1),
    ])
    with patch("data_processing.activations.shutil.disk_usage", side_effect=lambda _: next(usages)):
        part = capture_activations(
            data,
            resumed_same_dir,
            model=model,
            tokenizer=tokenizer,
            per_token_count=2,
            seed=42,
            min_free_bytes=limit,
        )
    assert part["captured"] == 2
    capture_activations(
        data,
        resumed_same_dir,
        model=model,
        tokenizer=tokenizer,
        per_token_count=2,
        seed=42,
        min_free_bytes=0,
    )
    fresh_dir = tmp_path / "fresh"
    capture_activations(
        data,
        fresh_dir,
        model=model,
        tokenizer=tokenizer,
        per_token_count=2,
        seed=42,
        min_free_bytes=0,
    )
    assert (fresh_dir / "index.json").read_bytes() == (resumed_same_dir / "index.json").read_bytes()
    for name in ("benign-1", "benign-2", "benign-3", "benign-4"):
        assert (fresh_dir / f"shards/{name}.safetensors").read_bytes() == (
            resumed_same_dir / f"shards/{name}.safetensors"
        ).read_bytes()


@pytest.mark.parametrize("mismatch", ["model_identity", "tokenizer_version", "layers", "dtype"])
def test_index_identity_mismatch_is_refused(tiny_lm, synthetic_dataset, mismatch):
    model, tokenizer = tiny_lm
    data, _, out_dir = synthetic_dataset
    capture_activations(
        data,
        out_dir,
        model=model,
        tokenizer=tokenizer,
        layer_step=3,
        dtype="fp16",
        min_free_bytes=0,
    )
    index_path = out_dir / "index.json"
    before = index_path.read_bytes()

    kwargs = {
        "model": model,
        "tokenizer": tokenizer,
        "layer_step": 3,
        "dtype": "fp16",
        "min_free_bytes": 0,
    }
    if mismatch == "model_identity":
        kwargs["model_identity"] = {
            "repo_id": "other/model",
            "commit_hash": "0" * 40,
            "weights_sha256": "f" * 64,
        }
    elif mismatch == "tokenizer_version":
        kwargs["tokenizer_version"] = "other-tokenizer-v0"
    elif mismatch == "layers":
        kwargs["layers"] = [0, 1]
    elif mismatch == "dtype":
        kwargs["dtype"] = "fp32"

    with pytest.raises(ValueError, match=f"index {mismatch} mismatch"):
        capture_activations(data, out_dir, **kwargs)
    assert index_path.read_bytes() == before


def test_disk_limit_stops_run_cleanly(tiny_lm, synthetic_dataset):
    model, tokenizer = tiny_lm
    data, _, out_dir = synthetic_dataset
    limit = 20 * 1024 ** 3

    # Stop before starting when free space is already below the limit.
    with patch("data_processing.activations.shutil.disk_usage", return_value=DiskUsage(limit * 2, limit + 10, limit - 1)):
        stopped = capture_activations(
            data,
            out_dir,
            model=model,
            tokenizer=tokenizer,
            min_free_bytes=limit,
        )
    assert stopped["status"] == "stopped_disk_limit"
    assert stopped["stopped_disk_limit"] is True
    assert stopped["captured"] == 0
    assert stopped["records"] == 0
    assert stopped["remaining"] == 4

    # Allow exactly the first shard (initial check, pre-shard-1 check, post-serialize-1 check),
    # then drop below limit before the second shard.
    usages = iter([
        DiskUsage(limit * 2, 0, limit + 1024 * 1024),
        DiskUsage(limit * 2, 0, limit + 1024 * 1024),
        DiskUsage(limit * 2, 0, limit + 1024 * 1024),
        DiskUsage(limit * 2, 0, limit - 1),
    ])
    with patch("data_processing.activations.shutil.disk_usage", side_effect=lambda _: next(usages)):
        mid = capture_activations(
            data,
            out_dir,
            model=model,
            tokenizer=tokenizer,
            min_free_bytes=limit,
        )
    assert mid["status"] == "stopped_disk_limit"
    assert mid["stopped_disk_limit"] is True
    assert mid["captured"] == 1
    assert mid["records"] == 1
    assert mid["remaining"] == 3
    index = json.loads((out_dir / "index.json").read_text(encoding="utf-8"))
    assert index["status"] == "stopped_disk_limit"
    assert list(index["shards"]) == ["benign-1"]

    # Resume once disk space is available again.
    completed = capture_activations(
        data,
        out_dir,
        model=model,
        tokenizer=tokenizer,
        min_free_bytes=0,
    )
    assert completed["status"] == "complete"
    assert completed["stopped_disk_limit"] is False
    assert completed["captured"] == 3
    assert completed["skipped"] == 1
    assert completed["records"] == 4
    assert completed["remaining"] == 0
    shutil.rmtree(out_dir)


def test_cli_outputs_only_aggregates_without_payload_text(tiny_lm, synthetic_dataset):
    data, manifest, out_dir = synthetic_dataset
    command = [
        sys.executable, "-m", "data_processing.activations",
        str(data), str(out_dir),
        "--dataset-manifest", str(manifest),
        "--model", DEFAULT_MODEL,
        "--per-token-count", "1",
        "--min-free-bytes", "0",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    summary = json.loads(result.stdout)
    assert summary["records"] == 4
    assert summary["status"] == "complete"
    assert "quarterly weather report" not in result.stdout + result.stderr

    # Corrupt dataset and ensure error output never leaks payload text.
    data.write_text("PRIVATE_BENIGN_SENTINEL\n", encoding="utf-8")
    failed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert failed.returncode == 2
    assert "PRIVATE_BENIGN_SENTINEL" not in failed.stdout + failed.stderr
    assert "Traceback" not in failed.stderr
