"""Read-only board dashboard. Run with python3 dashboard/server.py --port 8300."""

import argparse
import datetime as dt
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ops import dispatch

STATUSES = ("todo", "doing", "review", "blocked", "done")
PAGE = Path(__file__).with_name("index.html")


def run_fields(record):
    result = {key: record.get(key) for key in ("agent", "mode", "ticket", "start", "exit")}
    result["duration"] = None
    try:
        result["duration"] = (
            dt.datetime.fromisoformat(record["end"]) - dt.datetime.fromisoformat(record["start"])
        ).total_seconds()
    except (KeyError, ValueError, TypeError):
        pass
    return result


def state(board):
    columns = {status: [] for status in STATUSES}
    for ticket in dispatch.tickets(board / "tickets"):
        if ticket.get("status") in columns:
            columns[ticket["status"]].append(
                {key: ticket.get(key, "") for key in ("id", "title", "owner", "priority")}
            )
    running = []
    for path in sorted((board / "running").glob("*.json")):
        try:
            running.append(run_fields(json.loads(path.read_text())))
        except (OSError, ValueError):  # dispatcher may be writing this file
            continue
    history = []
    path = board / "runs.jsonl"
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                history.append(run_fields(json.loads(line)))
            except ValueError:  # tolerate an incomplete append
                continue
    return {"columns": columns, "counts": {k: len(v) for k, v in columns.items()},
            "running": running, "history": history[::-1], "metrics": []}


def handler(board):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/state":
                body = json.dumps(state(board)).encode()
                content_type = "application/json"
            elif self.path in ("/", "/index.html"):
                body = PAGE.read_bytes()
                content_type = "text/html; charset=utf-8"
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
    args = parser.parse_args()
    with ThreadingHTTPServer(("0.0.0.0", args.port), handler(args.board)) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
