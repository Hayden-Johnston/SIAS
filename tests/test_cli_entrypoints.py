"""CLI entry-point tests: argparse errors and missing paths for sources.py and coverage.py."""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parents[1]
COVERAGE = REPO / "ops" / "coverage.py"


def run_sources(*args):
    return subprocess.run(
        [sys.executable, "-m", "data_processing.sources", *args],
        check=False, cwd=REPO, capture_output=True, text=True,
    )


def run_coverage(*args):
    return subprocess.run(
        [sys.executable, str(COVERAGE), *args],
        check=False, cwd=REPO, capture_output=True, text=True,
    )


def test_sources_missing_required_args():
    result = run_sources()
    assert result.returncode == 2
    assert "usage:" in result.stderr
    assert "the following arguments are required" in result.stderr


def test_sources_invalid_source_choice():
    result = run_sources(
        "badsource", "input.jsonl",
        "--output", "/tmp/out", "--manifest", "/tmp/m",
        "--revision", "abc", "--timestamp", "2026-11-04T00:00:00Z",
    )
    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_sources_nonexistent_input_path(tmp_path):
    result = run_sources(
        "deepset", str(tmp_path / "nonexistent.jsonl"),
        "--output", str(tmp_path / "out.jsonl"),
        "--manifest", str(tmp_path / "manifest.json"),
        "--revision", "abc123", "--timestamp", "2026-11-04T00:00:00Z",
    )
    assert result.returncode == 2
    assert "source loading failed" in result.stderr


def test_coverage_nonexistent_manifest(tmp_path):
    result = run_coverage(str(tmp_path / "nonexistent.json"))
    assert result.returncode != 0
    assert "FileNotFoundError" in result.stderr
