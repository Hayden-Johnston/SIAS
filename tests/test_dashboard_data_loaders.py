"""Unit tests for dashboard data loaders: argument parsing, empty-input, missing-path."""

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

spec = importlib.util.spec_from_file_location(
    "dashboard_server", Path(__file__).parents[1] / "dashboard" / "server.py"
)
dashboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dashboard)


# --- Argument parsing ---

def test_main_parses_defaults(monkeypatch):
    """main() uses default port, board, and runs when no args are given."""
    monkeypatch.setattr(sys, "argv", ["server.py"])
    captured = {}

    def fake_handler(board, runs):
        captured["board"] = board
        captured["runs"] = runs
        return object

    with patch.object(dashboard, "handler", side_effect=fake_handler), \
         patch.object(dashboard, "ThreadingHTTPServer") as mock_server:
        mock_server.return_value.__enter__.return_value = mock_server
        dashboard.main()
    address = mock_server.call_args[0][0]
    assert address == ("0.0.0.0", 8300)
    assert captured["board"] == dashboard.dispatch.BOARD
    assert captured["runs"] == dashboard.RUNS


def test_main_parses_custom_args(monkeypatch, tmp_path):
    """main() respects --port, --board, and --runs."""
    board = tmp_path / "myboard"
    runs = tmp_path / "myruns"
    monkeypatch.setattr(sys, "argv", [
        "server.py", "--port", "9999", "--board", str(board), "--runs", str(runs)
    ])
    captured = {}

    def fake_handler(b, r):
        captured["board"] = b
        captured["runs"] = r
        return object

    with patch.object(dashboard, "handler", side_effect=fake_handler), \
         patch.object(dashboard, "ThreadingHTTPServer") as mock_server:
        mock_server.return_value.__enter__.return_value = mock_server
        dashboard.main()
    address = mock_server.call_args[0][0]
    assert address == ("0.0.0.0", 9999)
    assert captured["board"] == board
    assert captured["runs"] == runs


def test_main_port_type_error(monkeypatch):
    """A non-integer port causes argparse to exit with code 2."""
    monkeypatch.setattr(sys, "argv", ["server.py", "--port", "not_a_number"])
    with pytest.raises(SystemExit) as exc:
        dashboard.main()
    assert exc.value.code == 2


# --- Empty-input behavior ---

def test_state_empty_path(tmp_path):
    """state() on a completely empty directory returns empty structures."""
    current = dt.datetime.fromisoformat("2026-11-05T00:00:00+00:00")
    result = dashboard.state(tmp_path, tmp_path / "nonexistent-runs", current, repo=tmp_path)
    assert result["counts"] == dict.fromkeys(dashboard.STATUSES, 0)
    assert result["running"] == []
    assert result["history"] == []
    assert result["metrics"] == []
    assert result["alerts"] == []
    assert result["updates"] == []
    assert result["servers"] == []
    assert result["activity"]["agents"] == []
    assert result["activity"]["runs"] == []


def test_state_no_tickets_dir(tmp_path):
    """state() handles a missing tickets/ subdirectory gracefully."""
    current = dt.datetime.fromisoformat("2026-11-05T00:00:00+00:00")
    # Only create running/ but not tickets/
    (tmp_path / "running").mkdir()
    result = dashboard.state(tmp_path, tmp_path / "runs", current, repo=tmp_path)
    assert result["counts"] == dict.fromkeys(dashboard.STATUSES, 0)


def test_state_no_running_dir(tmp_path):
    """state() handles a missing running/ subdirectory gracefully."""
    current = dt.datetime.fromisoformat("2026-11-05T00:00:00+00:00")
    (tmp_path / "tickets").mkdir()
    result = dashboard.state(tmp_path, tmp_path / "runs", current, repo=tmp_path)
    assert result["running"] == []


def test_run_metrics_missing_directory(tmp_path):
    """run_metrics() returns an empty list when the runs directory does not exist."""
    assert dashboard.run_metrics(tmp_path / "does-not-exist") == []


def test_run_metrics_empty_directory(tmp_path):
    """run_metrics() returns an empty list for an empty runs directory."""
    runs = tmp_path / "runs"
    runs.mkdir()
    assert dashboard.run_metrics(runs) == []


def test_server_activity_missing_file(tmp_path):
    """server_activity() returns an empty list when servers.jsonl is absent."""
    current = dt.datetime.fromisoformat("2026-11-05T00:00:00+00:00")
    assert dashboard.server_activity(tmp_path, current) == []


# --- Missing-path behavior (partial board) ---

def test_state_missing_runs_jsonl(tmp_path):
    """state() works when runs.jsonl is absent (no history)."""
    current = dt.datetime.fromisoformat("2026-11-05T00:00:00+00:00")
    (tmp_path / "tickets").mkdir()
    (tmp_path / "running").mkdir()
    result = dashboard.state(tmp_path, tmp_path / "runs", current, repo=tmp_path)
    assert result["history"] == []


def test_state_missing_servers_jsonl(tmp_path):
    """state() works when servers.jsonl is absent."""
    current = dt.datetime.fromisoformat("2026-11-05T00:00:00+00:00")
    (tmp_path / "tickets").mkdir()
    (tmp_path / "running").mkdir()
    result = dashboard.state(tmp_path, tmp_path / "runs", current, repo=tmp_path)
    assert result["servers"] == []


def test_state_missing_alerts_jsonl(tmp_path):
    """state() works when alerts.jsonl is absent (no push-failure alerts)."""
    current = dt.datetime.fromisoformat("2026-11-05T00:00:00+00:00")
    (tmp_path / "tickets").mkdir()
    (tmp_path / "running").mkdir()
    result = dashboard.state(tmp_path, tmp_path / "runs", current, repo=tmp_path)
    assert result["alerts"] == []


def test_updates_missing_repo(tmp_path):
    """updates() returns an empty list when the repo path does not exist."""
    current = dt.datetime.fromisoformat("2026-11-05T00:00:00+00:00")
    assert dashboard.updates([], tmp_path / "no-such-repo", current, 48) == []


def test_updates_missing_reports_dir(tmp_path):
    """updates() handles a repo without a reports/ directory."""
    current = dt.datetime.fromisoformat("2026-11-05T00:00:00+00:00")
    # tmp_path exists but has no reports/ subdirectory and no git repo
    assert dashboard.updates([], tmp_path, current, 48) == []
