"""Aggregate-only ablation loading and HTTP projection."""

import json
from pathlib import Path
from urllib.request import urlopen

import pytest
from test_dashboard import dashboard
from test_dashboard import endpoint as endpoint  # noqa: PLC0414 -- shared pytest fixture

from data_processing.run import rate


def sample_ablation():
    full = {"tp": 2, "fn": 0, "fp": 1, "tn": 1,
            "detection": rate(2, 2), "false_positive": rate(1, 2)}
    removed = {"tp": 1, "fn": 1, "fp": 0, "tn": 2,
               "detection": rate(1, 2), "false_positive": rate(0, 2)}
    return {"schema_version": 1, "held_out": {"evaluator_approved": False},
            "full": {"held_out_metrics": full},
            "removed_stages": {"rules": {"held_out_metrics": removed,
                "delta_vs_full": {"detection": -0.5, "false_positive": -0.5}}},
            "text": "DO NOT EXPOSE", "inputs": "DO NOT OPEN"}


def test_ablation_loader_only_reads_aggregate(tmp_path, monkeypatch):
    path = tmp_path / "stage-ablation.json"
    record = sample_ablation()
    path.write_text(json.dumps(record))
    original = Path.read_text
    reads = []

    def read(self, *args, **kwargs):
        reads.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    result = dashboard.stage_ablation(tmp_path)
    assert reads == [path]
    assert result["full"] == record["full"]["held_out_metrics"]
    assert result["removed_stages"]["rules"]["delta_vs_full"] == {
        "detection": -0.5, "false_positive": -0.5}
    assert result["evaluator_approved"] is False
    assert "DO NOT" not in json.dumps(result)
    path.unlink()
    path.symlink_to(tmp_path / "payloads.jsonl")
    assert dashboard.stage_ablation(tmp_path) is None
    assert reads == [path]


@pytest.mark.parametrize("content", [None, "{", "[]", '{"schema_version":2}',
    json.dumps({**sample_ablation(), "full": {}}),
    json.dumps({**sample_ablation(), "removed_stages": {
        "rules": {"delta_vs_full": {"detection": float("nan")}}}})])
def test_ablation_empty_or_invalid(tmp_path, content):
    if content is not None:
        (tmp_path / "stage-ablation.json").write_text(content)
    assert dashboard.stage_ablation(tmp_path) is None


def test_ablation_undefined_rates_and_deltas(tmp_path):
    record = sample_ablation()
    for fit in [record["full"], *record["removed_stages"].values()]:
        fit["held_out_metrics"].update(tp=0, fn=0, detection=rate(0, 0))
    record["removed_stages"]["rules"]["delta_vs_full"]["detection"] = None
    (tmp_path / "stage-ablation.json").write_text(json.dumps(record))
    result = dashboard.stage_ablation(tmp_path)
    assert result["full"]["detection"]["value"] is None
    assert result["removed_stages"]["rules"]["delta_vs_full"]["detection"] is None


def test_ablation_http(endpoint):
    root, url = endpoint
    runs = root / "runs"
    runs.mkdir()
    (runs / "stage-ablation.json").write_text(json.dumps(sample_ablation()))
    with urlopen(url + "/api/state") as response:
        result = json.load(response)["ablation"]
    assert result == dashboard.stage_ablation(runs)
