import json
import subprocess
import sys

import pytest
from test_sweep import config, update

from data_processing import fp_audit, run


@pytest.fixture
def inputs(tmp_path):
    path = config(tmp_path, "validation", [[1, 1, 0.75, 0.74], [1, 1, 0, 1]])
    data = json.loads(path.read_text())
    data["stages"][0].update(name="rules", threshold=0.75)
    update(path, stages=data["stages"], fusion={"threshold": 0.5, "weights": {"rules": 0}})
    dataset = tmp_path / "dataset.jsonl"
    rows = [json.loads(line) for line in dataset.read_text().splitlines()]
    rows[2].update(source="first", channel="email")
    rows[3].update(source="second", channel="document")
    dataset.write_text("".join(json.dumps(row) + "\n" for row in rows))
    update(tmp_path / "manifest.json", output_sha256=run.digest(dataset))
    split = tmp_path / "split_manifest.json"
    split.write_text(json.dumps({"schema_version": 2, "splits": {
        "dev": {"records": 4, "output_sha256": run.digest(dataset)}}}))
    return path, split, tmp_path / "out" / "fp.json"


def test_counts_slices_boundary_weights_and_deterministic_cli(inputs):
    path, split, output = inputs
    result = fp_audit.audit(*inputs)
    assert result["records"] == 4
    for name, flagged, channel, source in [("rules", "2", "email", "first"),
                                           ("fused", "3", "document", "second")]:
        measured = result[name]
        assert measured["ids"] == [flagged]
        assert measured["benign"] == 2
        assert measured["fp"] == 1
        assert measured["false_positive"] == run.rate(1, 2)
        assert measured["by_channel"][channel] == fp_audit.summary(
            [{"id": flagged}], {flagged})
        assert measured["by_source"][source]["fp"] == 1
        assert sum(group["benign"] for group in measured["by_source"].values()) == 2
    assert result["rules_threshold"] == 0.75
    assert result["fusion"] == {"threshold": 0.5, "weights": {"rules": 0, "b": 1}}
    before = output.read_bytes()
    cli = subprocess.run([sys.executable, "-m", "data_processing.fp_audit",
                          str(path), str(split), str(output)],
                         capture_output=True, text=True, check=True)
    assert json.loads(cli.stdout) == result
    assert output.read_bytes() == before
    assert "Synthetic fixture text" not in cli.stdout + cli.stderr + output.read_text()
    assert set(result["rules"]) == {"benign", "fp", "false_positive", "ids",
                                    "by_channel", "by_source"}


@pytest.mark.parametrize("fault", ["checksum", "count", "version", "missing", "rules", "cache"])
def test_invalid_inputs_preserve_output(inputs, fault):
    path, split, output = inputs
    if fault in {"checksum", "count", "missing"}:
        entry = json.loads(split.read_text())["splits"]["dev"]
        if fault == "checksum":
            entry["output_sha256"] = "wrong"
        elif fault == "count":
            entry["records"] = 5
        update(split, splits={"dev": entry} if fault != "missing" else {})
    elif fault == "version":
        update(split, schema_version=1)
    else:
        data = json.loads(path.read_text())
        if fault == "rules":
            data["stages"][0]["name"] = "other"
            data["fusion"]["weights"] = {}
        else:
            cache = path.parent / data["stages"][0]["cache"]
            cache.write_text("")
            data["stages"][0]["cache_sha256"] = run.digest(cache)
        update(path, **data)
    output.parent.mkdir()
    output.write_text("previous")
    with pytest.raises(ValueError):
        fp_audit.audit(*inputs)
    assert output.read_text() == "previous"


def test_input_overwrite_rejected(inputs):
    path, split, _ = inputs
    for target in (path, split, path.parent / "dataset.jsonl", path.parent / "a.jsonl"):
        before = target.read_bytes()
        with pytest.raises(ValueError, match="must not overwrite"):
            fp_audit.audit(path, split, target)
        assert target.read_bytes() == before


def test_single_channel(tmp_path):
    path = config(tmp_path, "validation", [[1, 1, 0.75, 0.74], [1, 1, 0, 1]])
    data = json.loads(path.read_text())
    data["stages"][0].update(name="rules", threshold=0.75)
    update(path, stages=data["stages"], fusion={"threshold": 0.5, "weights": {"rules": 0}})
    dataset = tmp_path / "dataset.jsonl"
    rows = [json.loads(line) for line in dataset.read_text().splitlines()]
    for row in rows:
        if row["label"] == 0:
            row.update(channel="email", source="first")
    dataset.write_text("".join(json.dumps(row) + "\n" for row in rows))
    update(tmp_path / "manifest.json", output_sha256=run.digest(dataset))
    split = tmp_path / "split_manifest.json"
    split.write_text(json.dumps({"schema_version": 2, "splits": {
        "dev": {"records": 4, "output_sha256": run.digest(dataset)}}}))
    output = tmp_path / "out" / "fp.json"
    result = fp_audit.audit(path, split, output)
    for name in ("rules", "fused"):
        assert set(result[name]["by_channel"]) == {"email"}
        assert result[name]["by_channel"]["email"]["benign"] == 2


def test_heldout_chunks_zero_threshold_and_no_benign(inputs):
    path, split, _output = inputs
    data = json.loads(path.read_text())
    for stage in data["stages"]:
        stage.update(chunk_chars=100, overlap_chars=0)
        cache = path.parent / stage["cache"]
        entries = [json.loads(line) | {"turn": 0, "start": 0}
                   for line in cache.read_text().splitlines()]
        cache.write_text("".join(json.dumps(entry) + "\n" for entry in entries))
        stage["cache_sha256"] = run.digest(cache)
    update(path, stages=data["stages"], evaluation_split="held_out",
           fusion={"threshold": 0, "weights": {"rules": 0, "b": 0}})
    entry = json.loads(split.read_text())["splits"]["dev"]
    update(split, splits={"heldout": entry})
    result = fp_audit.audit(*inputs)
    assert result["fused"]["ids"] == ["2", "3"]
    assert result["rules"]["ids"] == ["2"]
    dataset = path.parent / "dataset.jsonl"
    dataset.write_text("\n".join(dataset.read_text().splitlines()[:2]) + "\n")
    update(path.parent / "manifest.json", records=2, output_sha256=run.digest(dataset))
    update(split, splits={"heldout": {"records": 2, "output_sha256": run.digest(dataset)}})
    for stage in data["stages"]:
        cache = path.parent / stage["cache"]
        cache.write_text("\n".join(cache.read_text().splitlines()[:2]) + "\n")
        stage["cache_sha256"] = run.digest(cache)
    update(path, stages=data["stages"])
    result = fp_audit.audit(*inputs)
    assert result["fused"] == {"benign": 0, "fp": 0, "ids": [],
                               "false_positive": run.rate(0, 0),
                               "by_channel": {}, "by_source": {}}
