import json
import subprocess
import sys
from unittest.mock import patch

import pytest
from test_sweep import config, update

from data_processing import ablation, run


@pytest.fixture
def configs(tmp_path):
    scores = [[1, 0, 0, 0], [0, 0.8, 0, 0]]
    return (config(tmp_path / "dev", "validation", scores),
            config(tmp_path / "held", "held_out", [[1, 0, 1, 0], scores[1]]))


def test_refits_deltas_counts_intervals_and_cli(configs, tmp_path):
    dev, held = configs
    output = tmp_path / "out" / "ablation.json"
    result = ablation.ablation(dev, held, 0, output)
    assert result["full"]["weights"] == {"a": 0.5, "b": 1}
    assert result["full"]["held_out_metrics"]["detection"] == run.rate(2, 2)
    without_a = result["removed_stages"]["a"]
    assert without_a["weights"] == {"b": 1}
    assert without_a["dev_metrics"]["detection"] == run.rate(1, 2)
    assert without_a["held_out_metrics"] == {
        "tp": 1, "fn": 1, "fp": 0, "tn": 2,
        "detection": run.rate(1, 2), "false_positive": run.rate(0, 2)}
    assert without_a["delta_vs_full"] == {"detection": -0.5, "false_positive": -0.5}
    assert result["removed_stages"]["b"]["delta_vs_full"] == {
        "detection": -0.5, "false_positive": 0}
    before = output.read_bytes()
    cli = subprocess.run([sys.executable, "-m", "data_processing.ablation", str(dev), str(held),
                          "--fpr-cap", "0", "--output", str(output)],
                         capture_output=True, text=True, check=True)
    assert json.loads(cli.stdout) == result
    assert output.read_bytes() == before
    assert "Synthetic fixture text" not in cli.stdout + cli.stderr


def test_all_fits_before_heldout_and_refit_can_reactivate_stage(tmp_path):
    scores = [[0.8, 0.8, 0, 0], [0.8, 0.8, 0, 0]]
    dev = config(tmp_path / "dev", "validation", scores)
    held = config(tmp_path / "held", "held_out", scores)
    original_prepare, original_select = run.prepare, ablation.select_weights
    events = []

    def prepare(path):
        events.append(path)
        return original_prepare(path)

    def select(*args):
        events.append("fit")
        return original_select(*args)

    with (patch.object(run, "prepare", side_effect=prepare),
          patch.object(ablation, "select_weights", side_effect=select)):
        before = ablation.ablation(dev, held, 0)
    assert events == [dev, "fit", "fit", "fit", held]
    assert before["full"]["weights"] == {"a": 0, "b": 1}
    assert before["removed_stages"]["b"]["weights"] == {"a": 1}
    assert before["removed_stages"]["b"]["delta_vs_full"]["detection"] == 0
    config(held.parent, "held_out", [[0, 0, 1, 1], [0, 0, 1, 1]])
    after = ablation.ablation(dev, held, 0)
    assert before["full"]["weights"] == after["full"]["weights"]
    for name in ("a", "b"):
        assert before["removed_stages"][name]["weights"] == after["removed_stages"][name]["weights"]


@pytest.mark.parametrize("fault", ["split", "settings", "missing", "cap", "single", "infeasible"])
def test_invalid_inputs_preserve_output(configs, tmp_path, fault):
    dev, held = configs
    cap = 0
    if fault == "split":
        update(dev, evaluation_split="train")
    elif fault == "settings":
        update(held, fusion={"threshold": 0.7})
    elif fault == "missing":
        cache = held.parent / "b.jsonl"
        cache.write_text("")
        data = json.loads(held.read_text())
        data["stages"][1]["cache_sha256"] = run.digest(cache)
        update(held, stages=data["stages"])
    elif fault == "cap":
        cap = float("nan")
    elif fault == "single":
        update(dev, stages=json.loads(dev.read_text())["stages"][:1])
    else:
        update(dev, fusion={"threshold": 0})
    output = tmp_path / "output.json"
    output.write_text("previous")
    with pytest.raises(ValueError):
        ablation.ablation(dev, held, cap, output)
    assert output.read_text() == "previous"


def test_input_overwrite_rejected(configs):
    dev, held = configs
    before = dev.read_bytes()
    with pytest.raises(ValueError, match="must not overwrite"):
        ablation.ablation(dev, held, 0, dev)
    assert dev.read_bytes() == before


def test_undefined_heldout_rate(configs):
    dev, held = configs
    data = json.loads(held.read_text())
    dataset = held.parent / "dataset.jsonl"
    dataset.write_text("\n".join(dataset.read_text().splitlines()[2:]) + "\n")
    update(held.parent / "manifest.json", records=2, output_sha256=run.digest(dataset))
    for stage in data["stages"]:
        cache = held.parent / stage["cache"]
        cache.write_text("\n".join(cache.read_text().splitlines()[2:]) + "\n")
        stage["cache_sha256"] = run.digest(cache)
    update(held, stages=data["stages"])
    result = ablation.ablation(dev, held, 0)
    assert result["full"]["held_out_metrics"]["detection"] == run.rate(0, 0)
    for choice in result["removed_stages"].values():
        assert choice["held_out_metrics"]["detection"] == run.rate(0, 0)
        assert choice["delta_vs_full"]["detection"] is None
