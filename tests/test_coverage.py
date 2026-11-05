import importlib.util
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "ops/coverage.py"
spec = importlib.util.spec_from_file_location("dataset_coverage", SCRIPT)
coverage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coverage)


def test_manifest_only_cli(tmp_path):
    manifest = tmp_path / "fixture.json"
    manifest.write_text(json.dumps({
        "labels": {"0": 50, "1": 20}, "channels": {"direct": 70},
        "techniques": {"named_jailbreak": 19, "novel": 20},
        "evaluator_approved": False,
    }))
    output = tmp_path / "report.md"
    command = [sys.executable, str(SCRIPT), str(manifest), "--output", str(output)]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=True)
    assert result.stdout == output.read_text()
    assert "| fixture | 20 | no |" in result.stdout
    assert "| fixture | 20 | 0 GAP | 0 GAP | 0 GAP | 0 GAP | 0 GAP | ? UNKNOWN |" in result.stdout
    assert "19 LOW | 20 |" in result.stdout
    assert subprocess.check_output(command, cwd=tmp_path, text=True) == result.stdout


def test_mixed_channels_and_benign_only():
    manifest = {"labels": {"0": 50, "1": 20}, "channels": {"direct": 60, "email": 10}}
    assert coverage.channel_attacks(manifest, "direct") is None
    assert coverage.channel_attacks(manifest, "email") is None
    assert coverage.channel_attacks(manifest, "document") == 0
    manifest["labels"] = {"1": 70}
    assert coverage.channel_attacks(manifest, "direct") == 60
    manifest["labels"] = {"0": 70}
    assert coverage.channel_attacks(manifest, "direct") == 0


def test_thresholds_and_empty_manifest(tmp_path):
    assert [coverage.cell(n) for n in (0, 1, 19, 20, None)] == [
        "0 GAP", "1 LOW", "19 LOW", "20", "? UNKNOWN"]
    manifest = tmp_path / "empty.json"
    manifest.write_text(json.dumps({"labels": {}, "channels": {}, "techniques": {}}))
    result = coverage.report([manifest])
    assert "| empty | 0 | no |" in result
    assert "| empty |" + " 0 GAP |" * 7 in result
