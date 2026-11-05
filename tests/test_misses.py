import json
import subprocess
import sys

import pytest

from data_processing import misses, run


@pytest.fixture
def fixture(tmp_path):
    rows = [
        {"id": "z", "label": 1, "channel": "direct", "techniques": ["novel", "encoding"],
         "fused_score": 0.1},
        {"id": "a", "label": 1, "channel": "direct", "techniques": ["novel"],
         "fused_score": 0.49},
        {"id": "e", "label": 1, "channel": "email", "techniques": ["novel"],
         "fused_score": 0},
        {"id": "boundary", "label": 1, "channel": "direct", "techniques": ["encoding"],
         "fused_score": 0.5},
        {"id": "benign", "label": 0, "channel": "direct", "techniques": [],
         "fused_score": 0},
    ]
    results = tmp_path / "results.jsonl"
    results.write_text("".join(json.dumps(row) + "\n" for row in rows))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": 1, "status": "complete", "evaluation_split": "held_out",
        "results_file": "results.jsonl", "results_sha256": run.digest(results),
        "records": len(rows), "fusion": {"threshold": 0.5}, "evaluator_approved": False,
    }))
    return manifest, tmp_path / "out" / "misses.json"


def update(path, **fields):
    path.write_text(json.dumps(json.loads(path.read_text()) | fields))


@pytest.mark.parametrize("split", ["validation", "held_out"])
def test_groups_counts_and_deterministic_cli(fixture, split):
    manifest, output = fixture
    update(manifest, evaluation_split=split)
    result = misses.misses(manifest, output)
    assert result["evaluation_split"] == split
    assert result["records"] == 5
    assert result["attacks"] == 4
    assert result["missed"] == 3
    assert result["ids"] == ["a", "e", "z"]
    assert result["groups"] == [
        {"technique": "encoding", "channel": "direct", "count": 1, "ids": ["z"]},
        {"technique": "novel", "channel": "direct", "count": 2, "ids": ["a", "z"]},
        {"technique": "novel", "channel": "email", "count": 1, "ids": ["e"]},
    ]
    assert result["evaluator_approved"] is False
    before = output.read_bytes()
    assert misses.misses(manifest, output) == result
    cli = subprocess.run([sys.executable, "-m", "data_processing.misses", str(manifest),
                          str(output)], capture_output=True, text=True, check=True)
    assert json.loads(cli.stdout) == result
    assert output.read_bytes() == before


def test_output_allowlist_and_unknown_fields_not_copied(fixture):
    manifest, output = fixture
    results = manifest.parent / "results.jsonl"
    rows = [json.loads(line) | {"text": "Synthetic fixture text", "messages": [],
                              "stages": [{"response": "Synthetic fixture response"}]}
            for line in results.read_text().splitlines()]
    results.write_text("".join(json.dumps(row) + "\n" for row in rows))
    update(manifest, results_sha256=run.digest(results), text="Synthetic manifest text")
    result = misses.misses(manifest, output)
    assert set(result) == {"schema_version", "evaluation_split", "manifest_sha256",
                           "results_sha256", "threshold", "evaluator_approved", "records",
                           "attacks", "missed", "ids", "groups"}
    assert all(set(group) == {"technique", "channel", "count", "ids"}
               for group in result["groups"])
    assert "Synthetic" not in output.read_text()


@pytest.mark.parametrize("fields, message", [
    ({"evaluation_split": "train"}, "validation or held_out"),
    ({"evaluation_split": "unknown"}, "validation or held_out"),
    ({"status": "incomplete"}, "complete"),
    ({"results_file": "other.jsonl"}, "results_file"),
    ({"results_sha256": "wrong"}, "checksum"),
    ({"records": 10}, "record count"),
    ({"fusion": {}}, "threshold"),
    ({"fusion": {"threshold": float("nan")}}, "threshold"),
])
def test_invalid_manifest_preserves_output(fixture, fields, message):
    manifest, output = fixture
    output.parent.mkdir()
    output.write_text("previous")
    update(manifest, **fields)
    with pytest.raises(ValueError, match=message):
        misses.misses(manifest, output)
    assert output.read_text() == "previous"


@pytest.mark.parametrize("change", [
    {"id": "a"}, {"label": True}, {"channel": "unknown"},
    {"techniques": ["novel", "novel"]}, {"techniques": ["unknown"]},
    {"fused_score": None}, {"fused_score": -0.1},
])
def test_invalid_results(fixture, change):
    manifest, output = fixture
    results = manifest.parent / "results.jsonl"
    rows = [json.loads(line) for line in results.read_text().splitlines()]
    rows[0].update(change)
    results.write_text("".join(json.dumps(row) + "\n" for row in rows))
    update(manifest, results_sha256=run.digest(results))
    with pytest.raises(ValueError):
        misses.misses(manifest, output)
    assert not output.exists()


def test_empty_and_no_misses(fixture):
    manifest, output = fixture
    update(manifest, fusion={"threshold": 0})
    result = misses.misses(manifest, output)
    assert result["missed"] == 0
    assert result["ids"] == result["groups"] == []
    results = manifest.parent / "results.jsonl"
    results.write_text("")
    update(manifest, records=0, results_sha256=run.digest(results))
    result = misses.misses(manifest, output)
    assert result["records"] == result["attacks"] == result["missed"] == 0


def test_cannot_overwrite_inputs(fixture):
    manifest, _ = fixture
    for path in (manifest, manifest.parent / "results.jsonl"):
        before = path.read_bytes()
        with pytest.raises(ValueError, match="must not overwrite"):
            misses.misses(manifest, path)
        assert path.read_bytes() == before
