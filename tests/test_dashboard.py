import importlib.util
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

spec = importlib.util.spec_from_file_location(
    "dashboard_server", Path(__file__).parents[1] / "dashboard" / "server.py"
)
dashboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dashboard)


@pytest.fixture
def endpoint(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.handler(tmp_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield tmp_path, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join()


def test_empty_board(endpoint):
    _, url = endpoint
    with urlopen(url + "/api/state") as response:
        state = json.load(response)
        assert response.headers["Content-Type"] == "application/json"
    assert state["counts"] == dict.fromkeys(dashboard.STATUSES, 0)
    assert state["running"] == state["history"] == state["metrics"] == []
    with urlopen(url) as response:
        page = response.read().decode()
    assert 'id="board"' in page
    assert 'id="history"' in page
    assert "setInterval(refresh, 30000)" in page


def test_all_statuses_running_and_history(endpoint):
    board, url = endpoint
    (board / "tickets").mkdir()
    (board / "running").mkdir()
    for index, status in enumerate(dashboard.STATUSES):
        (board / "tickets" / f"{index:04d}-test.md").write_text(
            f"id: {index:04d}\ntitle: Ticket {status}\nowner: codex\npriority: 1\n"
            f"status: {status}\n---\nPRIVATE BODY MUST NOT BE EXPOSED\n"
        )
    run = {"agent": "codex", "mode": "work", "ticket": "0001",
           "start": "2026-11-04T10:00:00+00:00", "pid": 123, "name": "private"}
    (board / "running" / "codex.json").write_text(json.dumps(run))
    (board / "running" / "partial.json").write_text('{"agent":')
    (board / "runs.jsonl").write_text(
        json.dumps({**run, "end": "2026-11-04T10:01:30+00:00", "exit": 0})
        + '\n{"partial":\n'
    )
    # A payload file is outside the explicit board inputs and must never be opened.
    (board / "payloads.jsonl").symlink_to(board / "nonexistent")
    with urlopen(url + "/api/state") as response:
        raw = response.read().decode()
    state = json.loads(raw)
    assert state["counts"] == dict.fromkeys(dashboard.STATUSES, 1)
    assert state["running"][0]["agent"] == "codex"
    assert state["running"][0]["ticket"] == "0001"
    assert state["history"][0]["duration"] == 90
    assert state["history"][0]["exit"] == 0
    assert "PRIVATE" not in raw and "private" not in raw and '"pid"' not in raw
    assert set(state["columns"]["todo"][0]) == {"id", "title", "owner", "priority"}
    with pytest.raises(HTTPError) as error:
        urlopen(url + "/../board/payloads.jsonl")
    assert error.value.code == 404
