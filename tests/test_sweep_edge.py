"""Edge-case tests for sweep.py: empty dev, single stage, ties, determinism, missing cache."""

import json

import pytest

from data_processing import run, sweep
from data_processing.normalize import normalize


def make_config(root, split, scores, n_rows=4):
    """Create a minimal valid sweep config under root with two stages."""
    root.mkdir(exist_ok=True)
    source = root / "source.jsonl"
    source.write_text("".join(json.dumps({
        "id": str(i), "text": "Synthetic fixture text", "label": 1 if i < 2 else 0,
        "channel": "direct", "techniques": ["novel"] if i < 2 else [],
        "spans": None if i < 2 else [], "label_source": "synthetic",
        "attack_family": "fixture" if i < 2 else "benign", "group_id": str(i),
        "variant_type": "plain", "source": "synthetic", "license": "CC0-1.0",
        "publishable": "no", "timestamp": "2026-11-05T00:00:00Z",
    }) + "\n" for i in range(n_rows)))
    normalize(source, root / "dataset.jsonl", root / "manifest.json")
    stages = []
    for name, values in zip(["a", "b"], scores):
        cache = root / f"{name}.jsonl"
        cache.write_text("".join(json.dumps({"id": str(i), "score": value, "latency_ms": 1})
                                 + "\n" for i, value in enumerate(values)))
        stages.append({"name": name, "version": "fixture-v1", "threshold": 0.5,
                       "cache": cache.name, "cache_sha256": run.digest(cache)})
    path = root / "config.json"
    path.write_text(json.dumps({
        "run_id": split, "timestamp": "2026-11-05T00:00:00Z", "iteration": 0,
        "pipeline_version": "fixture-v1", "dataset": "dataset.jsonl",
        "dataset_manifest": "manifest.json", "evaluation_split": split, "stages": stages,
    }))
    return path


def test_empty_dev_scores(tmp_path):
    """Sweep with zero dev rows raises a clear error about missing labels."""
    root = tmp_path / "dev"
    root.mkdir()
    source = root / "source.jsonl"
    source.write_text("")
    normalize(source, root / "dataset.jsonl", root / "manifest.json")
    stages = []
    for name in ("a", "b"):
        cache = root / f"{name}.jsonl"
        cache.write_text("")
        stages.append({"name": name, "version": "fixture-v1", "threshold": 0.5,
                       "cache": cache.name, "cache_sha256": run.digest(cache)})
    config = root / "config.json"
    config.write_text(json.dumps({
        "run_id": "validation", "timestamp": "2026-11-05T00:00:00Z", "iteration": 0,
        "pipeline_version": "fixture-v1", "dataset": "dataset.jsonl",
        "dataset_manifest": "manifest.json", "evaluation_split": "validation",
        "stages": stages,
    }))
    held = make_config(tmp_path / "held", "held_out", [[1, 0, 0, 0], [0, 1, 1, 0]])
    with pytest.raises(ValueError, match="both attack and benign"):
        sweep.sweep(config, held, 0)


def test_single_stage(tmp_path):
    """Sweep with only one stage raises a clear error."""
    dev = make_config(tmp_path / "dev", "validation", [[1, 0, 0.1, 0], [0, 1, 0.9, 0]])
    held = make_config(tmp_path / "held", "held_out", [[1, 0, 0, 0], [0, 1, 1, 0]])
    data = json.loads(dev.read_text())
    data["stages"] = data["stages"][:1]
    dev.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="multiple stages"):
        sweep.sweep(dev, held, 0)


def test_tied_weights_deterministic_break(tmp_path):
    """When multiple weight combos tie on detection and sum, the break is deterministic."""
    # Identical scores for both stages: (1,0) and (0,1) tie on detection and weight sum.
    scores = [[0.8, 0.8, 0, 0], [0.8, 0.8, 0, 0]]
    dev = make_config(tmp_path / "dev", "validation", scores)
    held = make_config(tmp_path / "held", "held_out", scores)
    result = sweep.sweep(dev, held, 0)
    # (0, 1) < (1, 0) lexicographically, so a=0, b=1 is chosen.
    assert result["dev"]["weights"] == {"a": 0, "b": 1}
    # Rerun confirms determinism.
    again = sweep.sweep(dev, held, 0)
    assert again["dev"]["weights"] == result["dev"]["weights"]


def test_identical_output_on_rerun(tmp_path):
    """Two consecutive sweep calls produce byte-identical output files."""
    dev = make_config(tmp_path / "dev", "validation", [[1, 0, 0.1, 0], [0, 1, 0.9, 0]])
    held = make_config(tmp_path / "held", "held_out", [[1, 0, 0, 0], [0, 1, 1, 0]])
    output = tmp_path / "out" / "sweep.json"
    result1 = sweep.sweep(dev, held, 0, output)
    bytes1 = output.read_bytes()
    result2 = sweep.sweep(dev, held, 0, output)
    bytes2 = output.read_bytes()
    assert result1 == result2
    assert bytes1 == bytes2


def test_missing_stage_cache_fails(tmp_path):
    """A missing cache file raises FileNotFoundError naming the file."""
    dev = make_config(tmp_path / "dev", "validation", [[1, 0, 0.1, 0], [0, 1, 0.9, 0]])
    held = make_config(tmp_path / "held", "held_out", [[1, 0, 0, 0], [0, 1, 1, 0]])
    cache = dev.parent / "a.jsonl"
    cache.unlink()
    with pytest.raises(FileNotFoundError, match="a\\.jsonl"):
        sweep.sweep(dev, held, 0)
