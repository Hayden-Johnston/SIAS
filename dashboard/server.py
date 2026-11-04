"""Read-only board dashboard. Run with python3 dashboard/server.py --port 8300."""

import argparse
import datetime as dt
import json
import math
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ops import dispatch

STATUSES = ("todo", "doing", "review", "blocked", "done")
PAGE = Path(__file__).with_name("index.html")
RUNS = Path("/mnt/storage/llm_security/runs")


def manifest_fields(record):
    """Project only documented aggregate fields; reject partial/unsupported manifests."""
    def text(value):
        if not isinstance(value, str):
            raise TypeError("expected text")
        return value

    def number(value, integer=False, nullable=False):
        if value is None and nullable:
            return None
        if (type(value) not in ((int,) if integer else (int, float))
                or not math.isfinite(value) or value < 0):
            raise ValueError("expected nonnegative number")
        return value

    def rate(value):
        n = number(value["n"], integer=True)
        bounds = value["ci95"]
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise ValueError("expected interval")
        estimate, low, high = [number(v, nullable=n == 0)
                               for v in (value["value"], *bounds)]
        # Wilson endpoints can round just inside a 0% or 100% point estimate.
        if n and not (0 <= estimate <= 1 and 0 <= low <= high <= 1):
            raise ValueError("invalid interval")
        if not n and (estimate, low, high) != (None, None, None):
            raise ValueError("empty rate must be undefined")
        return {"value": estimate, "n": n, "ci95": [low, high],
                "method": text(value["method"])}

    if record["schema_version"] != 1 or record["status"] != "complete":
        raise ValueError("unsupported or incomplete manifest")
    result = {key: text(record[key]) for key in
              ("run_id", "timestamp", "pipeline_version", "dataset_sha256", "evaluation_split")}
    timestamp = dt.datetime.fromisoformat(result["timestamp"])
    if timestamp.utcoffset() is None:
        raise ValueError("timestamp needs timezone")
    result["timestamp"] = timestamp.astimezone(dt.timezone.utc).isoformat()  # noqa: UP017 (system python3 is 3.10)
    result["iteration"] = number(record["iteration"], integer=True)
    result["records"] = number(record["records"], integer=True)
    result["evaluator_approved"] = record["evaluator_approved"] is True
    result["metrics"] = {key: number(record["metrics"][key], integer=True)
                         for key in ("tp", "fp", "fn", "tn")}
    result["metrics"].update({key: rate(record["metrics"][key])
                              for key in ("detection", "false_positive")})
    result["attack_distribution"] = {text(key): number(value, integer=True)
                                     for key, value in record["attack_distribution"].items()}
    result["stages"] = []
    for stage in record["stages"]:
        result["stages"].append({
            "name": text(stage["name"]), "version": text(stage["version"]),
            **{key: number(stage[key], integer=True) for key in ("reached", "caught", "passed")},
            "cached_latency_ms_total": number(stage["cached_latency_ms_total"]),
            "cached_latency_ms_mean": number(stage["cached_latency_ms_mean"], nullable=True),
        })
    return result


def run_metrics(runs):
    result = []
    for path in sorted(runs.glob("*/manifest.json")):
        # Never follow manifest or run-directory symlinks into payloads/other inputs.
        if path.is_symlink() or path.parent.is_symlink():
            continue
        try:
            result.append(manifest_fields(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
            continue  # partial writes and unsupported manifests do not break the board
    return sorted(result, key=lambda run: (run["timestamp"], run["run_id"]), reverse=True)


def run_fields(record):
    result = {key: record.get(key) for key in ("agent", "mode", "ticket", "start", "end", "exit")}
    if not all(isinstance(result[key], str) for key in ("agent", "mode", "ticket", "start")):
        raise ValueError("incomplete run")
    start = dt.datetime.fromisoformat(result["start"])
    end = dt.datetime.fromisoformat(result["end"]) if result["end"] else None
    if start.utcoffset() is None or (end and (end.utcoffset() is None or end < start)):
        raise ValueError("invalid run interval")
    result["duration"] = (end - start).total_seconds() if end else None
    return result


def activity(history, running, titles, current):
    agents = []
    for agent in sorted({r["agent"] for r in history + running}):
        live = next((r for r in running if r["agent"] == agent), None)
        status, until = dispatch.agent_pause(agent, history, current)
        agents.append({"agent": agent, "state": "running" if live else status,
                       "until": until.isoformat() if until and not live else None,
                       "ticket": live["ticket"] if live else None,
                       "elapsed": max(0, (current - dt.datetime.fromisoformat(live["start"]))
                                      .total_seconds()) if live else None})
    # A dispatcher append/unlink can briefly leave the same run in both files.
    completed = {(r["agent"], r["start"]) for r in history}
    intervals = history + [r for r in running if (r["agent"], r["start"]) not in completed]
    return {"now": current.isoformat(), "agents": agents,
            "runs": [{**r, "title": titles.get(r["ticket"], "")} for r in intervals]}


def state(board, runs=RUNS, current=None):
    current = current or dispatch.now()
    titles = {}
    columns = {status: [] for status in STATUSES}
    for ticket in dispatch.tickets(board / "tickets"):
        titles[ticket.get("id")] = ticket.get("title", "")
        if ticket.get("status") in columns:
            columns[ticket["status"]].append(
                {key: ticket.get(key, "") for key in ("id", "title", "owner", "priority")}
            )
    running = []
    for path in sorted((board / "running").glob("*.json")):
        try:
            running.append(run_fields(json.loads(path.read_text())))
        except (OSError, ValueError, TypeError, AttributeError):  # dispatcher may be writing this file
            continue
    history = []
    path = board / "runs.jsonl"
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                record = run_fields(json.loads(line))
                if record["end"]:
                    history.append(record)
            except (ValueError, TypeError, AttributeError):  # tolerate an incomplete append
                continue
    return {"columns": columns, "counts": {k: len(v) for k, v in columns.items()},
            "running": running, "history": history[::-1], "metrics": run_metrics(runs),
            "activity": activity(history, running, titles, current)}


def handler(board, runs=RUNS):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/state":
                body = json.dumps(state(board, runs), allow_nan=False).encode()
                content_type = "application/json"
            elif self.path in ("/", "/index.html"):
                body = PAGE.read_bytes()
                content_type = "text/html; charset=utf-8"
            elif self.path in ("/metrics.js", "/activity.js"):
                body = PAGE.with_name(self.path[1:]).read_bytes()
                content_type = "text/javascript; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8300)
    parser.add_argument("--board", type=Path, default=dispatch.BOARD)
    parser.add_argument("--runs", type=Path, default=RUNS)
    args = parser.parse_args()
    with ThreadingHTTPServer(("0.0.0.0", args.port), handler(args.board, args.runs)) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
