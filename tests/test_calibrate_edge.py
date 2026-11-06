"""Edge cases for calibrate.py: no benign in dev, all-tied scores, unreachable FPR, determinism."""

import json
import math

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


def test_no_benign_in_dev_raises(tmp_path):
    """Dev with only attack rows must raise ValueError."""
    dev = manifest(tmp_path / "dev", "validation", [(1, "direct", 0.9)])
    held = manifest(tmp_path / "held", "held_out", [(1, "direct", 0.9), (0, "direct", 0.1)])
    with pytest.raises(ValueError, match="both attack and benign"):
        calibrate.calibrate(dev, held)


def test_all_scores_tied(tmp_path):
    """When all fused scores are identical, threshold is nextafter(score, inf) and nothing is detected."""
    scores = [(1, "direct", 0.5)] * 10 + [(0, "direct", 0.5)] * 10
    dev = manifest(tmp_path / "dev", "validation", scores)
    held = manifest(tmp_path / "held", "held_out", scores)
    result = calibrate.calibrate(dev, held)
    for point in result["operating_points"]:
        assert point["threshold"] == math.nextafter(0.5, math.inf)
        assert point["dev"]["metrics"]["tp"] == 0
        assert point["dev"]["metrics"]["fp"] == 0
        assert point["held_out"]["metrics"]["tp"] == 0
        assert point["held_out"]["metrics"]["fp"] == 0


def test_target_fpr_unreachable(tmp_path):
    """With fewer benign rows than the denominator, the target FPR cap is unreachable."""
    # 50 benign rows: 50 < 100, so 1% cap is unreachable.
    scores = [(0, "direct", 0.5)] * 50 + [(1, "email", 0.9)] * 50
    dev = manifest(tmp_path / "dev", "validation", scores)
    held = manifest(tmp_path / "held", "held_out", scores)
    result = calibrate.calibrate(dev, held)
    for point in result["operating_points"]:
        assert point["too_few_dev_benign"] is True
        assert point["dev"]["metrics"]["fp"] == 0
        assert point["dev"]["metrics"]["detection"]["value"] == 1.0


def test_byte_identical_output_on_repeated_runs(tmp_path):
    """Two runs with the same inputs produce byte-identical output files."""
    scores = [(1, "direct", 0.8), (1, "email", 0.6), (0, "direct", 0.3), (0, "email", 0.1)]
    dev = manifest(tmp_path / "dev", "validation", scores)
    held = manifest(tmp_path / "held", "held_out", scores)
    out1 = tmp_path / "out1.json"
    out2 = tmp_path / "out2.json"
    calibrate.calibrate(dev, held, out1)
    calibrate.calibrate(dev, held, out2)
    assert out1.read_bytes() == out2.read_bytes()
