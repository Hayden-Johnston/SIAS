import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("dispatch", Path(__file__).parents[1] / "ops" / "dispatch.py")
dispatch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dispatch)


@pytest.fixture
def board(tmp_path, monkeypatch):
    monkeypatch.setattr(dispatch, "TICKETS", tmp_path)
    return tmp_path


def test_new_set_log_roundtrip(board):
    dispatch.new("codex", "2", "Dataset schema", [])
    dispatch.set_field("1", "status", "review")
    dispatch.log("1", "codex", "done, tests pass")
    t = dispatch.read(next(board.glob("0001-*.md")))
    assert (t["id"], t["owner"], t["status"], t["priority"]) == ("0001", "codex", "review", "2")
    assert "codex: done, tests pass" in t["path"].read_text()


def test_pick_respects_dependencies_and_priority(board):
    dispatch.new("codex", "1", "a", [])
    dispatch.new("codex", "1", "b", ["1"])
    dispatch.new("codex", "3", "c", [])
    assert dispatch.pick(dispatch.tickets(), "codex")["id"] == "0001"
    dispatch.set_field("1", "status", "done")
    assert dispatch.pick(dispatch.tickets(), "codex")["id"] == "0002"
    assert dispatch.pick(dispatch.tickets(), "claude") is None


def test_rejects_unknown_status(board):
    dispatch.new("claude", "1", "x", [])
    with pytest.raises(SystemExit):
        dispatch.set_field("1", "status", "wip")
