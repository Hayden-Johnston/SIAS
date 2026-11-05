import json
import subprocess
import sys
from unittest.mock import patch

import pytest

from data_processing import run, sweep
from data_processing.normalize import normalize


def config(root, split, scores):
    root.mkdir(exist_ok=True)
    source = root / "source.jsonl"
    source.write_text("".join(json.dumps({
        "id": str(i), "text": "Synthetic fixture text", "label": label,
        "channel": "direct", "techniques": ["novel"] if label else [],
        "spans": None if label else [], "label_source": "synthetic",
        "attack_family": "fixture" if label else "benign", "group_id": str(i),
        "variant_type": "plain", "source": "synthetic", "license": "CC0-1.0",
        "publishable": "no", "timestamp": "2026-11-05T00:00:00Z",
    }) + "\n" for i, label in enumerate([1, 1, 0, 0])))
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


@pytest.fixture
def configs(tmp_path):
    return (config(tmp_path / "dev", "validation", [[1, 0, 0.1, 0], [0, 1, 0.9, 0]]),
            config(tmp_path / "held", "held_out", [[1, 0, 0, 0], [0, 1, 1, 0]]))


def update(path, **fields):
    data = json.loads(path.read_text())
    data.update(fields)
    path.write_text(json.dumps(data))


def test_choice_heldout_delta_and_deterministic_cli(configs, tmp_path):
    dev, held = configs
    output = tmp_path / "out" / "sweep.json"
    result = sweep.sweep(dev, held, 0, output)
    # b=0.5 keeps its attack (inclusive threshold), suppressing its dev false positive.
    assert result["dev"]["weights"] == {"a": 0.5, "b": 0.5}
    assert result["dev"]["metrics"]["detection"] == run.rate(2, 2)
    assert result["dev"]["metrics"]["false_positive"] == run.rate(0, 2)
    assert result["held_out"]["metrics"]["false_positive"] == run.rate(1, 2)
    assert result["held_out"]["delta_vs_all_ones"] == {"detection": 0, "false_positive": 0}
    before = output.read_bytes()
    assert sweep.sweep(dev, held, 0, output) == result
    assert output.read_bytes() == before
    cli = subprocess.run([sys.executable, "-m", "data_processing.sweep", str(dev), str(held),
                          "--fpr-cap", "0", "--output", str(output)],
                         capture_output=True, text=True, check=True)
    assert json.loads(cli.stdout) == result
    assert "Synthetic fixture text" not in cli.stdout + cli.stderr
    assert output.read_bytes() == before


def test_heldout_never_used_for_selection(configs):
    dev, held = configs
    original_prepare, original_evaluate = run.prepare, run.evaluate
    events = []

    def prepare(path):
        events.append(path)
        return original_prepare(path)

    def evaluate(*args, **kwargs):
        events.append("score")
        return original_evaluate(*args, **kwargs)

    with (patch.object(run, "prepare", side_effect=prepare),
          patch.object(run, "evaluate", side_effect=evaluate)):
        before = sweep.sweep(dev, held, 0)
    # Four dev rows for each of nine grid points, before opening held-out.
    assert events == [dev] + ["score"] * 36 + [held] + ["score"] * 8
    config(held.parent, "held_out", [[0, 0, 1, 1], [0, 0, 1, 1]])
    after = sweep.sweep(dev, held, 0)
    assert before["dev"] == after["dev"]
    assert before["held_out"]["metrics"] != after["held_out"]["metrics"]


def test_lower_weight_tie_break_and_delta(tmp_path):
    scores = [[0.8, 0.8, 0, 0], [0.8, 0.8, 0.9, 0]]
    dev = config(tmp_path / "dev", "validation", scores)
    held = config(tmp_path / "held", "held_out", scores)
    result = sweep.sweep(dev, held, 0)
    assert result["dev"]["weights"] == {"a": 1, "b": 0}
    assert result["held_out"]["delta_vs_all_ones"]["false_positive"] == -0.5
    # Equal total weights prefer the alphabetically earlier stage's lower weight.
    config(dev.parent, "validation", [scores[0], scores[0]])
    result = sweep.sweep(dev, held, 0)
    assert result["dev"]["weights"] == {"a": 0, "b": 1}


@pytest.mark.parametrize("cap", [-1, 1.1, True, float("nan"), float("inf")])
def test_invalid_cap(configs, cap):
    with pytest.raises(ValueError, match="FPR cap"):
        sweep.sweep(*configs, cap)


def test_invalid_splits_and_mismatched_settings(configs):
    dev, held = configs
    update(dev, evaluation_split="train")
    with pytest.raises(ValueError, match="dev config"):
        sweep.sweep(dev, held, 0)
    update(dev, evaluation_split="validation")
    update(held, evaluation_split="validation")
    with pytest.raises(ValueError, match="held-out config"):
        sweep.sweep(dev, held, 0)
    update(held, evaluation_split="held_out", fusion={"threshold": 0.6})
    with pytest.raises(ValueError, match="must match"):
        sweep.sweep(dev, held, 0)


def test_no_feasible_choice_and_missing_scores_preserve_output(configs, tmp_path):
    dev, held = configs
    output = tmp_path / "out.json"
    output.write_text("previous")
    for path in configs:
        update(path, fusion={"threshold": 0})
    with pytest.raises(ValueError, match="no weights"):
        sweep.sweep(dev, held, 0, output)
    update(dev, fusion={})
    cache = held.parent / "b.jsonl"
    cache.write_text("")
    data = json.loads(held.read_text())
    data["stages"][1]["cache_sha256"] = run.digest(cache)
    update(held, stages=data["stages"], fusion={})
    with pytest.raises(ValueError, match="missing required cached score"):
        sweep.sweep(dev, held, 0, output)
    assert output.read_text() == "previous"


def test_cannot_overwrite_inputs(configs):
    dev, held = configs
    before = dev.read_bytes()
    with pytest.raises(ValueError, match="must not overwrite"):
        sweep.sweep(dev, held, 0, dev)
    assert dev.read_bytes() == before


def test_chunk_caches_use_runner_scoring(configs):
    for path in configs:
        data = json.loads(path.read_text())
        for stage in data["stages"]:
            stage.update(chunk_chars=100, overlap_chars=0)
            cache = path.parent / stage["cache"]
            entries = [json.loads(line) | {"turn": 0, "start": 0}
                       for line in cache.read_text().splitlines()]
            cache.write_text("".join(json.dumps(entry) + "\n" for entry in entries))
            stage["cache_sha256"] = run.digest(cache)
        update(path, stages=data["stages"])
    result = sweep.sweep(*configs, 0)
    assert result["dev"]["weights"] == {"a": 0.5, "b": 0.5}
    assert result["dev"]["metrics"]["detection"] == run.rate(2, 2)


def test_dev_requires_both_classes_and_multiple_stages(configs):
    dev, held = configs
    data = json.loads(dev.read_text())
    update(dev, stages=data["stages"][:1])
    with pytest.raises(ValueError, match="multiple stages"):
        sweep.sweep(dev, held, 0)
    update(dev, stages=data["stages"])
    dataset = dev.parent / "dataset.jsonl"
    rows = [json.loads(line) for line in dataset.read_text().splitlines()][:2]
    dataset.write_text("".join(json.dumps(row) + "\n" for row in rows))
    manifest = dev.parent / "manifest.json"
    update(manifest, records=2, output_sha256=run.digest(dataset))
    # Keep caches consistent with the reduced dataset.
    for stage in data["stages"]:
        cache = dev.parent / stage["cache"]
        cache.write_text("\n".join(cache.read_text().splitlines()[:2]) + "\n")
        stage["cache_sha256"] = run.digest(cache)
    update(dev, stages=data["stages"])
    with pytest.raises(ValueError, match="both attack and benign"):
        sweep.sweep(dev, held, 0)
