import importlib.util
import json
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


def test_dotenv(tmp_path, monkeypatch):
    monkeypatch.setattr(dispatch, "REPO", tmp_path)
    (tmp_path / ".env").write_text("A=1\nB = two\nno_equals_here\n")
    assert dispatch.dotenv("A") == "1"
    assert dispatch.dotenv("B") == "two"
    assert dispatch.dotenv("C") == ""


def test_resting_after_recent_or_failed_run(tmp_path, monkeypatch):
    runs = tmp_path / "runs.jsonl"
    monkeypatch.setattr(dispatch, "RUNS", runs)
    assert not dispatch.resting("codex")
    ago = lambda **kw: (dispatch.now() - dispatch.dt.timedelta(**kw)).isoformat()
    runs.write_text(f'{{"agent": "codex", "end": "{ago(minutes=40)}", "exit": 0}}\n')
    assert not dispatch.resting("codex")
    runs.write_text(f'{{"agent": "codex", "end": "{ago(minutes=40)}", "exit": 1}}\n')
    assert dispatch.resting("codex")


def test_pipeline_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(dispatch, 'REPO', tmp_path)
    monkeypatch.setattr(dispatch, 'BOARD', tmp_path)
    monkeypatch.setattr(dispatch, 'tickets', list)
    monkeypatch.setattr(dispatch, 'reap', lambda a: a != 'pipeline')
    launched = []
    monkeypatch.setattr(dispatch, 'launch', lambda *args: launched.append(args))
    history = []
    monkeypatch.setattr(dispatch, 'runs', lambda: history)
    dispatch.tick()
    assert not launched  # no local config
    (tmp_path / 'iterate.local.json').write_text('{}')
    dispatch.tick()
    assert launched == [('pipeline', 'iterate', None)]
    launched.clear()
    history.append({'agent': 'pipeline', 'start': dispatch.now().isoformat(),
                    'end': dispatch.now().isoformat(), 'exit': 0})
    dispatch.tick()
    assert not launched
    history[0]['start'] = (dispatch.now() - dispatch.dt.timedelta(hours=6)).isoformat()
    dispatch.tick()
    assert len(launched) == 1
    launched.clear()
    (tmp_path / 'STOP').touch()
    dispatch.tick()
    assert not launched


def test_pipeline_launch_has_no_agent_or_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(dispatch, 'REPO', tmp_path)
    monkeypatch.setattr(dispatch, 'LOGS', tmp_path)
    monkeypatch.setattr(dispatch, 'RUNNING', tmp_path)
    commands = []

    class Process:
        pid = 123

    def popen(cmd, **kwargs):
        commands.append(cmd)
        return Process()

    monkeypatch.setattr(dispatch.subprocess, 'Popen', popen)
    dispatch.launch('pipeline', 'iterate', None)
    assert commands[0][-4:] == ['uv', 'run', 'python', 'ops/iterate.py']
    assert json.loads((tmp_path / 'pipeline.json').read_text())['agent'] == 'pipeline'


def test_pipeline_reap_is_counted_before_scheduling(tmp_path, monkeypatch):
    monkeypatch.setattr(dispatch, 'REPO', tmp_path)
    monkeypatch.setattr(dispatch, 'BOARD', tmp_path)
    monkeypatch.setattr(dispatch, 'tickets', list)
    (tmp_path / 'iterate.local.json').write_text('{}')
    history, launched = [], []
    monkeypatch.setattr(dispatch, 'runs', lambda: history)
    monkeypatch.setattr(dispatch, 'launch', lambda *args: launched.append(args))

    def reap(agent):
        if agent == 'pipeline':
            history.append({'agent': 'pipeline', 'start': dispatch.now().isoformat(),
                            'end': dispatch.now().isoformat(), 'exit': 0})
            return False
        return True

    monkeypatch.setattr(dispatch, 'reap', reap)
    dispatch.tick()
    assert not launched
