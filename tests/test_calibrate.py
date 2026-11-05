import json
import math
import subprocess
import sys
from unittest.mock import patch

import pytest

from data_processing import calibrate, run


def manifest(root, split, scores):
    root.mkdir(exist_ok=True)
    rows = [{"id": str(i), "label": label, "channel": channel, "fused_score": score}
            for i, (label, channel, score) in enumerate(scores)]
    results = root / "results.jsonl"
    results.write_text("".join(json.dumps(row) + "\n" for row in rows))
    path = root / "manifest.json"
    path.write_text(json.dumps({
        "schema_version": 1, "status": "complete", "evaluation_split": split,
        "results_file": "results.jsonl", "results_sha256": run.digest(results),
        "records": len(rows), "fusion": {"method": "max", "weights": {"a": 0.5}},
        "stages": [{"name": "a", "version": "fixture-v1"}], "evaluator_approved": False,
    }))
    return path


@pytest.fixture
def configs(tmp_path):
    scores = [(1, "direct", 0.5), (1, "email", 0.2), (0, "direct", 0.2)]
    return (manifest(tmp_path / "dev", "validation", scores),
            manifest(tmp_path / "held", "held_out", scores))


def test_deterministic_cli_counts_and_channels(configs, tmp_path):
    output = tmp_path / "out.json"
    result = calibrate.calibrate(*configs, output)
    for point in result["operating_points"]:
        assert point["threshold"] == math.nextafter(0.2, math.inf)
        assert point["too_few_dev_benign"] is True
        assert point["dev_fpr_resolution"] == 1
        assert point["dev"]["metrics"]["detection"] == run.rate(1, 2)
        assert point["held_out"]["metrics"]["false_positive"] == run.rate(0, 1)
        assert point["held_out"]["by_channel"]["email"]["detection"] == run.rate(0, 1)
        assert point["held_out"]["by_channel"]["email"]["false_positive"] == run.rate(0, 0)
    before = output.read_bytes()
    cli = subprocess.run([sys.executable, "-m", "data_processing.calibrate",
                          *map(str, configs), "--output", str(output)],
                         capture_output=True, text=True, check=True)
    assert json.loads(cli.stdout) == result
    assert output.read_bytes() == before
    assert '"id"' not in cli.stdout


def test_nonzero_caps_ties_and_inclusive_boundary(tmp_path):
    # Ten tied benign scores at 0.8 fit 1%, but not 0.1%.
    scores = ([(0, "direct", 0.8)] * 10 + [(0, "direct", 0.2)] * 990
              + [(1, "email", math.nextafter(0.2, math.inf)), (1, "email", 0.8)])
    dev = manifest(tmp_path / "dev", "validation", scores)
    held = manifest(tmp_path / "held", "held_out", scores)
    low, high = calibrate.calibrate(dev, held)["operating_points"]
    assert low["threshold"] == math.nextafter(0.2, math.inf)
    assert low["dev"]["metrics"]["fp"] == 10
    assert low["dev"]["metrics"]["tp"] == 2
    assert high["threshold"] == math.nextafter(0.8, math.inf)
    assert high["dev"]["metrics"]["fp"] == high["dev"]["metrics"]["tp"] == 0
    assert high["too_few_dev_benign"] is False


def test_all_dev_choices_before_heldout_and_heldout_independence(configs):
    original = calibrate.load_results
    events = []

    def load(path, split):
        events.append(split)
        return original(path, split)

    original_measured = calibrate.measured

    def measured(*args):
        events.append("measure")
        return original_measured(*args)

    with (patch.object(calibrate, "load_results", side_effect=load),
          patch.object(calibrate, "measured", side_effect=measured)):
        before = calibrate.calibrate(*configs)
    assert events == ["validation", "measure", "measure", "held_out", "measure", "measure"]
    manifest(configs[1].parent, "held_out", [(0, "direct", 1)])
    after = calibrate.calibrate(*configs)
    for left, right in zip(before["operating_points"], after["operating_points"]):
        assert left["threshold"] == right["threshold"]
        assert left["dev"] == right["dev"]
        assert right["held_out"]["metrics"]["detection"] == run.rate(0, 0)


@pytest.mark.parametrize("fields", [
    {"status": "incomplete"}, {"evaluation_split": "held_out"},
    {"results_file": "other.jsonl"}, {"results_sha256": "bad"}, {"records": 999},
    {"fusion": None}, {"fusion": {"method": "max", "weights": {"a": True}}},
    {"stages": []},
])
def test_invalid_manifest_preserves_output(configs, tmp_path, fields):
    dev, held = configs
    dev.write_text(json.dumps(json.loads(dev.read_text()) | fields))
    output = tmp_path / "out.json"
    output.write_text("previous")
    with pytest.raises(ValueError):
        calibrate.calibrate(dev, held, output)
    assert output.read_text() == "previous"


@pytest.mark.parametrize("change", [
    {"id": "1"}, {"label": True}, {"channel": "unknown"},
    {"fused_score": float("nan")}, {"fused_score": 1.1},
])
def test_invalid_results(configs, change):
    dev, held = configs
    results = dev.parent / "results.jsonl"
    rows = [json.loads(line) for line in results.read_text().splitlines()]
    rows[0].update(change)
    results.write_text("".join(json.dumps(row) + "\n" for row in rows))
    dev.write_text(json.dumps(json.loads(dev.read_text()) | {"results_sha256": run.digest(results)}))
    with pytest.raises(ValueError):
        calibrate.calibrate(dev, held)


def test_no_feasible_in_range_threshold_and_missing_classes(configs):
    dev, held = configs
    manifest(dev.parent, "validation", [(0, "direct", 1), (1, "direct", 1)])
    result = calibrate.calibrate(dev, held)
    assert result["operating_points"][0]["threshold"] == math.nextafter(1, math.inf)
    assert result["operating_points"][0]["dev"]["metrics"]["tp"] == 0
    manifest(dev.parent, "validation", [(0, "direct", 0)])
    with pytest.raises(ValueError, match="both attack and benign"):
        calibrate.calibrate(dev, held)


def test_mismatch_and_overwrite_protection(configs):
    dev, held = configs
    for path in (*configs, dev.parent / "results.jsonl", held.parent / "results.jsonl"):
        before = path.read_bytes()
        with pytest.raises(ValueError, match="overwrite"):
            calibrate.calibrate(dev, held, path)
        assert path.read_bytes() == before
    data = json.loads(held.read_text())
    data["fusion"]["weights"]["a"] = 1
    held.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="must match"):
        calibrate.calibrate(dev, held)
