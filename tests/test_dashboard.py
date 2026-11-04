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
    server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.handler(tmp_path, tmp_path / "runs"))
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


def synthetic_manifest(index=0):
    from data_processing.run import rate

    return {
        "schema_version": 1, "status": "complete", "run_id": f"run-{index}",
        "timestamp": f"2026-11-04T{index:02d}:00:00Z", "iteration": index,
        "pipeline_version": f"pipeline-{index}", "dataset_sha256": "a" * 64,
        "evaluation_split": "held_out", "records": 20, "evaluator_approved": False,
        "metrics": {"tp": 8, "fp": 1, "fn": 2, "tn": 9,
                    "detection": rate(8, 10), "false_positive": rate(1, 10)},
        "attack_distribution": {"synthetic-family": 10},
        "stages": [{"name": "rule", "version": "v1", "reached": 20, "caught": 9,
                    "passed": 11, "cached_latency_ms_total": 40,
                    "cached_latency_ms_mean": 2, "cache": "DO NOT EXPOSE"}],
        "results_file": "DO NOT EXPOSE", "text": "DO NOT EXPOSE",
    }


def write_manifest(runs, index=0, record=None):
    directory = runs / f"run-{index}"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "manifest.json"
    path.write_text(json.dumps(synthetic_manifest(index) if record is None else record))
    return path


def test_metrics_projection_order_and_only_manifest_reads(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    for index in (0, 2, 1):
        path = write_manifest(runs, index)
        (path.parent / "results.jsonl").symlink_to(tmp_path / "missing")
    # A manifest symlink and a run-directory symlink must not expose other inputs.
    (runs / "linked").symlink_to(runs / "run-0", target_is_directory=True)
    (runs / "linked-manifest").mkdir()
    (runs / "linked-manifest" / "manifest.json").symlink_to(runs / "run-0" / "manifest.json")
    read_text = Path.read_text
    opened = []

    def read_manifest(path, *args, **kwargs):
        assert path.name == "manifest.json"
        opened.append(path)
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_manifest)
    metrics = dashboard.run_metrics(runs)
    assert len(opened) == 3
    assert [run["run_id"] for run in metrics] == ["run-2", "run-1", "run-0"]
    assert metrics[0]["metrics"] == synthetic_manifest()["metrics"]
    assert metrics[0]["stages"][0]["passed"] == 11
    assert metrics[0]["stages"][0]["cached_latency_ms_mean"] == 2
    assert metrics[0]["attack_distribution"] == {"synthetic-family": 10}
    assert "DO NOT EXPOSE" not in json.dumps(metrics)


@pytest.mark.parametrize("record", [
    None, [], {}, {**synthetic_manifest(), "schema_version": 2},
    {**synthetic_manifest(), "status": "running"},
    {**synthetic_manifest(), "timestamp": "no date"},
    {**synthetic_manifest(), "timestamp": "2026-11-04T00:00:00"},
    {**synthetic_manifest(), "metrics": {}},
    {**synthetic_manifest(), "records": float("nan")},
    {**synthetic_manifest(), "stages": [None]},
    {**synthetic_manifest(), "attack_distribution": []},
])
def test_bad_manifests_are_skipped(tmp_path, record):
    path = write_manifest(tmp_path)
    path.write_text(json.dumps(record))
    write_manifest(tmp_path, 1)
    assert [run["run_id"] for run in dashboard.run_metrics(tmp_path)] == ["run-1"]
    path.write_bytes(b'{"partial":')
    assert len(dashboard.run_metrics(tmp_path)) == 1
    path.write_bytes(b'\xff')
    assert len(dashboard.run_metrics(tmp_path)) == 1


def test_empty_rates_and_zero_reached_stage(tmp_path):
    from data_processing.run import rate

    record = synthetic_manifest()
    record["metrics"] = dict.fromkeys(("tp", "fp", "fn", "tn"), 0)
    record["metrics"].update(detection=rate(0, 0), false_positive=rate(0, 0))
    record["records"] = 0
    record["stages"][0].update(reached=0, caught=0, passed=0,
                                cached_latency_ms_total=0, cached_latency_ms_mean=None)
    write_manifest(tmp_path, record=record)
    result = dashboard.run_metrics(tmp_path)[0]
    assert result["metrics"]["detection"]["value"] is None
    assert result["metrics"]["false_positive"]["ci95"] == [None, None]
    assert result["stages"][0]["cached_latency_ms_mean"] is None


def test_configured_runs_http_and_static_assets(tmp_path):
    runs = tmp_path / "configured-runs"
    for index in range(3):
        write_manifest(runs, index)
    server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.handler(tmp_path / "board", runs))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urlopen(base + "/api/state") as response:
            state = json.load(response)
        assert len(state["metrics"]) == 3
        with urlopen(base) as response:
            page = response.read().decode()
        for name in ("metrics-history", "detection-chart", "fp-chart", "selected-run", "stages"):
            assert f'id="{name}"' in page
        with urlopen(base + "/metrics.js") as response:
            assert response.headers["Content-Type"] == "text/javascript; charset=utf-8"
            assert "function renderMetrics" in response.read().decode()
        with pytest.raises(HTTPError):
            urlopen(base + "/runs/run-0/results.jsonl")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_perfect_detection_and_no_false_positives_are_not_skipped(tmp_path):
    from data_processing.run import rate

    record = synthetic_manifest()
    record['metrics'] = {'tp': 300000, 'fp': 0, 'fn': 0, 'tn': 15000,
                         'detection': rate(300000, 300000),
                         'false_positive': rate(0, 15000)}
    write_manifest(tmp_path, record=record)
    assert dashboard.run_metrics(tmp_path)[0]['metrics'] == record['metrics']
