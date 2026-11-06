import json
import subprocess
import sys

import pytest

from data_processing.benign_gap import report


def manifest(tmp_path, name, benign, attacks, channels, approved=False):
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps({
        "loader": {"source": name}, "labels": {"0": benign, "1": attacks},
        "channels": channels, "evaluator_approved": approved,
    }))
    return path


def test_counts_approval_and_target(tmp_path):
    a = manifest(tmp_path, "a", 20, 10, {"direct": 30})
    b = manifest(tmp_path, "b", 5, 0, {"email": 5}, approved=True)
    result = report([a, b])
    assert result["source_pool_benign"] == 25
    assert result["source_pool_gap_to_target"] == 14975
    assert result["evaluator_approved_source_pool_benign"] == 5
    assert result["heldout_benign"] is None
    assert result["heldout_gap_to_target"] is None
    assert result["by_channel"] == {
        "direct": 20, "email": 5, "document": 0, "multi_turn": 0,
        "tool_output": 0, "code_comment": 0,
    }
    assert result["by_source"]["a"]["benign"] == 20
    assert report([b, a]) == result
    with pytest.raises(ValueError, match="duplicate source"):
        report([a, a])


def test_ambiguous_marginals_empty_and_above_target(tmp_path):
    a = manifest(tmp_path, "mixed", 20, 10, {"direct": 15, "email": 15})
    b = manifest(tmp_path, "benign", 15001, 0, {"direct": 15001})
    result = report([a, b])
    assert result["by_channel"]["direct"] is None
    assert result["by_channel"]["email"] is None
    assert result["by_channel"]["document"] == 0
    assert result["source_pool_gap_to_target"] == 0
    assert result["heldout_gap_to_target"] is None
    assert report([])["source_pool_gap_to_target"] == 15000
    assert report([])["by_channel"]["direct"] == 0
    attacks = manifest(tmp_path, "attacks", 0, 10, {"email": 10})
    assert report([attacks])["by_channel"]["email"] == 0


def test_cli_replay_and_errors(tmp_path):
    path = manifest(tmp_path, "fixture", 3, 2, {"direct": 5})
    output = tmp_path / "counts.json"
    command = [sys.executable, "-m", "data_processing.benign_gap", str(path),
               "--output", str(output)]
    first = subprocess.run(command, capture_output=True, text=True, check=True)
    assert first.stdout == output.read_text()
    assert subprocess.check_output(command, text=True) == first.stdout
    assert json.loads(first.stdout) == report([path])
    before = path.read_bytes()
    failed = subprocess.run(command[:-1] + [str(path)], capture_output=True, text=True, check=False)
    assert failed.returncode == 2
    assert path.read_bytes() == before
    path.write_text('{"payload": "PRIVATE_SENTINEL"}')
    failed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert failed.returncode == 2
    assert "PRIVATE_SENTINEL" not in failed.stdout + failed.stderr
    assert output.read_text() == first.stdout
