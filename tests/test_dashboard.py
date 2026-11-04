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
    assert state["running"] == state["history"] == state["metrics"] == state["alerts"] == []
    with urlopen(url) as response:
        page = response.read().decode()
    assert 'id="board"' in page
    assert 'id="history"' in page
    assert "setInterval(refresh, 15000)" in page


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
    assert state["activity"]["runs"][0]["title"] == "Ticket doing"
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


def test_slice_projection_and_older_manifests(tmp_path):
    from data_processing.run import sliced_metrics

    record = synthetic_manifest()
    assert dashboard.manifest_fields(record)["slices"]["by_technique"] == {}
    record["slices"] = sliced_metrics([
        {"label": 1, "detected": True, "channel": "direct", "length_bucket": "0-4096",
         "techniques": ["novel", "encoding"], "attack_family": "synthetic-family"},
    ])
    record["slices"]["by_technique"]["novel"]["text"] = "DO NOT EXPOSE"
    write_manifest(tmp_path, record=record)
    result = dashboard.run_metrics(tmp_path)[0]
    group = result["slices"]["by_technique"]["novel"]
    assert group["n"] == 1 and group["small_sample"] is True
    assert group["detection"] == record["slices"]["by_technique"]["novel"]["detection"]
    assert group["false_positive"]["value"] is None
    assert "DO NOT EXPOSE" not in json.dumps(result)


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


def test_activity_intervals_and_states(tmp_path):
    import datetime as dt

    current = dt.datetime.fromisoformat("2026-11-04T12:00:00+00:00")
    (tmp_path / "running").mkdir()
    def run(agent, start, end=None, exit=0):
        return {"agent": agent, "mode": "work", "ticket": "0020",
                "start": f"2026-11-04T{start}+00:00",
                **({"end": f"2026-11-04T{end}+00:00", "exit": exit} if end else {})}
    history = [run("codex", "11:50:00", "11:58:00"),
               run("pi", "08:00:00", "08:30:00"),
               run("claude", "11:00:00", "11:30:00", 1),
               run("future-agent", "09:00:00", "09:01:00"),
               run("future-agent", "10:00:00", "10:01:00", 2)]
    (tmp_path / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in history)
                                         + '\nnull\n[]\n{"partial":')
    (tmp_path / "running" / "future-agent.json").write_text(
        json.dumps(run("future-agent", "11:40:00")))
    data = dashboard.state(tmp_path, tmp_path / "runs", current)["activity"]
    agents = {a["agent"]: a for a in data["agents"]}
    assert agents["codex"]["state"] == "resting"
    assert agents["codex"]["until"] == "2026-11-04T12:03:00+00:00"
    assert agents["claude"]["state"] == "resting"
    assert agents["claude"]["until"] == "2026-11-04T13:30:00+00:00"
    assert agents["pi"]["state"] == "idle"
    assert agents["future-agent"]["state"] == "running"
    assert agents["future-agent"]["elapsed"] == 1200
    assert len(data["runs"]) == 6
    assert data["runs"][0]["duration"] == 480
    assert data["runs"][4]["exit"] == 2
    assert data["runs"][-1]["end"] is None
    assert data["runs"][0]["title"] == ""
    # A completed record can briefly coexist with its running file.
    (tmp_path / "running" / "codex.json").write_text(json.dumps(history[0]))
    assert len(dashboard.state(tmp_path, tmp_path / "runs", current)["activity"]["runs"]) == 6


def test_shared_dispatch_cap_boundary(monkeypatch):
    import datetime as dt

    current = dt.datetime.fromisoformat("2026-11-04T12:00:00+00:00")
    monkeypatch.setitem(dashboard.dispatch.MAX_RUNS_PER_WINDOW, "codex", 2)
    history = [{"agent": "codex", "mode": "work", "ticket": "0020",
                "start": f"2026-11-04T{hour}:00:00+00:00",
                "end": f"2026-11-04T{hour}:10:00+00:00", "exit": 0}
               for hour in ("08", "09")]
    status, until = dashboard.dispatch.agent_pause("codex", history, current)
    assert status == "capped"
    assert dashboard.activity(history, [], {}, current)["agents"][0]["state"] == "capped"
    assert until == current + dt.timedelta(hours=1)
    assert dashboard.dispatch.agent_pause("codex", history, until) == ("idle", None)
    assert dashboard.dispatch.agent_pause("unknown", [], current) == ("idle", None)


def write_ticket(board, tid, status, owner='codex', created='2026-11-04', logs=''):
    (board / 'tickets').mkdir(exist_ok=True)
    (board / 'tickets' / f'{tid}-test.md').write_text(
        f'id: {tid}\ntitle: Ticket {tid}\nowner: {owner}\nstatus: {status}\n'
        f'priority: 1\ndepends: \ncreated: {created}\n---\n'
        '## Spec\nPRIVATE BODY\n- 2026-11-04 10:00 spec: PRIVATE FAKE LOG\n'
        f'## Log\n{logs}')


def test_alert_derivation(tmp_path):
    import datetime as dt

    current = dt.datetime.fromisoformat('2026-11-04T12:00:00+00:00')
    write_ticket(tmp_path, '0001', 'blocked', logs='- 2026-11-04 10:00 codex: Need decision\n')
    write_ticket(tmp_path, '0002', 'todo', 'user')
    write_ticket(tmp_path, '0003', 'done', 'user')
    write_ticket(tmp_path, '0004', 'todo')
    runs = [
        {'agent': 'codex', 'mode': 'work', 'ticket': '0001',
         'start': '2026-11-04T08:00:00+00:00', 'end': '2026-11-04T08:30:00+00:00', 'exit': 1},
        {'agent': 'pi', 'mode': 'work', 'ticket': '0001',
         'start': '2026-11-04T09:00:00+00:00', 'end': '2026-11-04T11:00:00+00:00', 'exit': None},
        {'agent': 'claude', 'mode': 'plan', 'ticket': '-',
         'start': '2026-11-02T08:00:00+00:00', 'end': '2026-11-02T08:30:00+00:00', 'exit': 1},
    ]
    (tmp_path / 'runs.jsonl').write_text('\n'.join(json.dumps(r) for r in runs))
    (tmp_path / 'alerts.jsonl').write_text(json.dumps({
        'kind': 'push failure', 'timestamp': '2026-11-04T11:30:00+00:00', 'agent': 'codex',
        'stderr': 'PRIVATE ERROR'}) + '\nnull\n{"partial":')
    data = dashboard.state(tmp_path, tmp_path / 'runs', current, repo=tmp_path)
    alerts = data['alerts']
    assert [a['kind'] for a in alerts].count('failed run') == 2
    assert [a['message'] for a in alerts if a['kind'] == 'failure cooldown'] == ['pi']
    assert next(a for a in alerts if a['kind'] == 'blocked')['message'] == 'Need decision'
    assert next(a for a in alerts if a['kind'] == 'user action')['ticket'] == '0002'
    assert any(a['kind'] == 'stall' for a in alerts)
    assert alerts[0]['kind'] == 'push failure'
    assert 'PRIVATE' not in json.dumps(data)
    (tmp_path / 'STOP').touch()
    assert any(a['id'] == 'stop' for a in dashboard.state(
        tmp_path, tmp_path / 'runs', current, repo=tmp_path)['alerts'])
    # A recent run clears the stall, and active agents are not in failure cooldown.
    (tmp_path / 'running').mkdir()
    (tmp_path / 'running' / 'pi.json').write_text(json.dumps({
        **runs[1], 'start': '2026-11-04T11:50:00+00:00', 'end': None}))
    alerts = dashboard.state(tmp_path, tmp_path / 'runs', current, repo=tmp_path)['alerts']
    assert not any(a['kind'] in ('stall', 'failure cooldown') for a in alerts)


def test_stall_needs_ready_tickets_and_two_hours(tmp_path):
    import datetime as dt

    current = dt.datetime.fromisoformat('2026-11-04T12:00:00+00:00')
    write_ticket(tmp_path, '0001', 'todo', created='2026-11-04T11:00:00+00:00')
    assert not dashboard.state(tmp_path, tmp_path / 'runs', current, repo=tmp_path)['alerts']
    current += dt.timedelta(hours=1)
    assert dashboard.state(tmp_path, tmp_path / 'runs', current, repo=tmp_path)['alerts'][0]['kind'] == 'stall'
    path = next((tmp_path / 'tickets').glob('*.md'))
    path.write_text(path.read_text().replace('depends: \n', 'depends: 9999\n'))
    assert not dashboard.state(tmp_path, tmp_path / 'runs', current, repo=tmp_path)['alerts']


def test_updates_merge_order_and_window(tmp_path, monkeypatch):
    import datetime as dt
    import os
    import subprocess

    current = dt.datetime.fromisoformat('2026-11-04T12:00:00+00:00')
    monkeypatch.setenv('TZ', 'UTC')
    write_ticket(tmp_path, '0001', 'done', logs=(
        '- 2026-11-04 10:00 codex: ' + 'long ' * 100 + '\n'
        '- 2026-11-01 10:00 pi: Older entry\n'
        '- malformed\n'))
    subprocess.run(['git', 'init', '-q', '-b', 'master', str(tmp_path)], check=True)
    subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.name=Test',
                    '-c', 'user.email=test@example.invalid', 'commit', '-q', '--allow-empty',
                    '-m', 'Synthetic change'], check=True, env={**os.environ,
                    'GIT_AUTHOR_DATE': '2026-11-04T11:00:00Z',
                    'GIT_COMMITTER_DATE': '2026-11-04T11:00:00Z'})
    (tmp_path / 'reports').mkdir()
    report = tmp_path / 'reports' / '2026-11-04-test.md'
    report.write_text('PRIVATE REPORT CONTENT')
    time = dt.datetime.fromisoformat('2026-11-04T09:00:00+00:00').timestamp()
    os.utime(report, (time, time))
    (tmp_path / 'reports' / 'symlink.md').symlink_to(report)
    logs = dashboard.ticket_logs(dashboard.dispatch.tickets(tmp_path / 'tickets')[0])
    feed = dashboard.updates(logs, tmp_path, current, 48)
    assert [e['kind'] for e in feed] == ['commit', 'ticket', 'report']
    assert feed[0]['message'] == 'Synthetic change' and len(feed[0]['sha']) >= 7
    assert len(feed[1]['message']) == 240
    assert 'PRIVATE' not in json.dumps(feed)
    assert len(dashboard.updates(logs, tmp_path, current, 96)) == 4
    assert dashboard.updates([], tmp_path / 'missing', current, 48) == []


def test_server_lanes_samples_gaps_and_projection(tmp_path):
    import datetime as dt

    current = dt.datetime.fromisoformat('2026-11-04T12:30:00Z')
    assert dashboard.server_activity(tmp_path, current) == []

    def sample(minute, up=True, models=None, server='llama'):
        return {'timestamp': f'2026-11-04T12:{minute:02}:00Z', 'server': server,
                'up': up, 'models': models or [], 'url': 'PRIVATE', 'body': 'PRIVATE'}

    rows = [sample(0), sample(5), sample(10, models=['model-a']),
            sample(15, False), sample(30, server='Maya'), sample(59),
            sample(0, server='stale'), {**sample(20), 'up': 'yes'},
            {**sample(20), 'models': 'bad'}, {**sample(20), 'timestamp': '2026-11-04'},
            None]
    (tmp_path / 'servers.jsonl').write_text(
        '\n'.join(json.dumps(row) for row in reversed(rows)) + '\n{"partial":')
    lanes = dashboard.state(tmp_path, current=current)['servers']
    assert [lane['server'] for lane in lanes] == ['Maya', 'llama', 'stale']
    assert [lane['state'] for lane in lanes] == ['up', 'unknown', 'unknown']
    intervals = lanes[1]['intervals']
    assert len(intervals) == 3
    assert [(row['start'][14:19], row['end'][14:19]) for row in intervals] == [
        ('00:00', '10:00'), ('10:00', '15:00'), ('15:00', '25:00')]
    assert intervals[1]['models'] == ['model-a']
    assert not intervals[2]['up']
    assert 'PRIVATE' not in json.dumps(lanes)
    assert dashboard.server_activity(tmp_path, current + dt.timedelta(minutes=1))[1]['state'] == 'unknown'
