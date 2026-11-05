"""Read-only board dashboard. Run with python3 dashboard/server.py --port 8300."""

import argparse
import datetime as dt
import json
import math
import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

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
    timestamp = dt.datetime.fromisoformat(result["timestamp"].replace("Z", "+00:00"))  # noqa: FURB162 (system python3 3.10 rejects "Z")
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
    result["slices"] = {}
    for field in ("channel", "length_bucket", "technique", "attack_family"):
        result["slices"]["by_" + field] = {
            text(name): {
                "n": number(value["n"], integer=True),
                "small_sample": number(value["n"], integer=True) < 20,
                **{key: rate(value[key]) for key in ("detection", "false_positive")},
            }
            for name, value in record.get("slices", {}).get("by_" + field, {}).items()
        }
    novel = record.get("slices", {}).get("novel_technique")
    result["slices"]["novel_technique"] = None if novel is None else [
        {"technique": text(value["technique"]), "n": number(value["n"], integer=True),
         "small_sample": number(value["n"], integer=True) < 20,
         "detection": rate(value["detection"])}
        for value in novel
    ]
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


def timestamp(value):
    """Normalize timestamps; dispatcher ticket logs use the server's local timezone."""
    return dt.datetime.fromisoformat(value).astimezone(dt.timezone.utc).isoformat()  # noqa: UP017


def server_activity(board, current):
    """Hold samples for at most two five-minute ticks; gaps remain unknown."""
    samples = {}
    path = board / "servers.jsonl"
    for line in path.read_text().splitlines() if path.exists() else []:
        try:
            row = json.loads(line)
            time = dt.datetime.fromisoformat(row["timestamp"])
            if (time.utcoffset() is None or time > current or not isinstance(row["server"], str)
                    or type(row["up"]) is not bool or not isinstance(row["models"], list)
                    or not all(isinstance(model, str) for model in row["models"])):
                continue
            samples.setdefault(row["server"], {})[time] = {
                "up": row["up"], "models": row["models"]}
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
    lanes = []
    for name, records in sorted(samples.items()):
        ordered = sorted(records.items())
        intervals = []
        for index, (start, sample) in enumerate(ordered):
            end = min(current, start + dt.timedelta(minutes=10),
                      ordered[index + 1][0] if index + 1 < len(ordered) else current)
            interval = {"start": start.isoformat(), "end": end.isoformat(), **sample}
            if (intervals and intervals[-1]["end"] == interval["start"]
                    and all(intervals[-1][key] == sample[key] for key in ("up", "models"))):
                intervals[-1]["end"] = interval["end"]
            else:
                intervals.append(interval)
        latest, sample = ordered[-1]
        status = ("up" if sample["up"] else "down") if current - latest < dt.timedelta(minutes=10) else "unknown"
        lanes.append({"server": name, "state": status, "models": sample["models"],
                      "intervals": intervals})
    return lanes


def one_line(value):
    return " ".join(value.split())[:240]


def ticket_logs(ticket):
    body = ticket["path"].read_text().partition("\n## Log\n")[2]
    result = []
    for line in body.splitlines():
        match = re.fullmatch(r"- (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) ([^:]+): (.*)", line)
        if match:
            time, agent, message = match.groups()
            try:
                result.append({"timestamp": timestamp(time), "kind": "ticket",
                               "ticket": ticket["id"], "title": ticket.get("title", ""),
                               "agent": agent, "message": one_line(message)})
            except ValueError:
                continue
    return result


def updates(logs, repo, current, hours):
    since = current - dt.timedelta(hours=hours)
    entries = list(logs)
    try:
        commits = subprocess.run(
            ["git", "-C", str(repo), "log", "master", f"--since={since.isoformat()}",
             "--format=%cI%x09%h%x09%s"], capture_output=True, text=True, timeout=5, check=False)
        for line in commits.stdout.splitlines():
            time, sha, subject = line.split("\t", 2)
            entries.append({"timestamp": timestamp(time), "kind": "commit", "sha": sha,
                            "message": one_line(subject)})
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    for path in (repo / "reports").glob("*.md"):
        if path.is_symlink():
            continue
        try:
            # No report contents are read. mtime is the local file arrival/change time.
            time = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc)  # noqa: UP017
            entries.append({"timestamp": time.isoformat(), "kind": "report",
                            "message": path.name})
        except OSError:
            continue
    return sorted((e for e in entries if since <= dt.datetime.fromisoformat(e["timestamp"]) <= current),
                  key=lambda e: (e["timestamp"], e["kind"], e["message"]), reverse=True)


def alerts(board, ts, logs, history, running, current):
    result = []

    def add(key, kind, time, message, **fields):
        result.append({"id": key, "kind": kind, "timestamp": timestamp(time),
                       "message": one_line(message), **fields})

    for ticket in ts:
        blocked = ticket.get("status") == "blocked"
        if not blocked and not (ticket.get("owner") == "user" and ticket.get("status") != "done"):
            continue
        last = next((line for line in reversed(logs) if line["ticket"] == ticket["id"]), None)
        add("ticket:" + ticket["id"], "blocked" if blocked else "user action",
            last["timestamp"] if last else ticket.get("created", current.isoformat()),
            last["message"] if last else "No log entries",
            **{key: ticket.get(key, "") for key in ("title", "owner")},
            ticket=ticket["id"])
    for run in history:
        end = dt.datetime.fromisoformat(run["end"])
        if run["exit"] != 0 and current - dt.timedelta(hours=24) <= end <= current:
            add(f"run:{run['agent']}:{run['start']}", "failed run", run["end"],
                f"{run['agent']} · ticket {run['ticket']} · exit {run['exit']}")
    for agent in sorted({r["agent"] for r in history}):
        last = max((r for r in history if r["agent"] == agent), key=lambda r: r["end"])
        until = dt.datetime.fromisoformat(last["end"]) + dispatch.FAIL_COOLDOWN
        if last["exit"] != 0 and current < until and not any(r["agent"] == agent for r in running):
            add(f"cooldown:{agent}:{last['end']}", "failure cooldown", last["end"], agent,
                until=until.isoformat())
    stop = board / "STOP"
    if stop.exists():
        add("stop", "dispatch paused", dt.datetime.fromtimestamp(stop.stat().st_mtime).isoformat(),
            "STOP is present")
    by_id = {t["id"]: t for t in ts}
    starts = [dt.datetime.fromisoformat(r["start"]) for r in history + running]
    last_start = max(starts, default=None)
    if any(dispatch.ready(t, by_id) and t.get("owner") != "user" for t in ts):
        # With no run history, ready-ticket creation is the earliest available evidence.
        since = last_start or min((dt.datetime.fromisoformat(t.get("created", current.isoformat()))
                                  .astimezone(current.tzinfo) for t in ts
                                  if dispatch.ready(t, by_id)), default=current)
        if current - since >= dt.timedelta(hours=2):
            add("stall", "stall", since.isoformat(), "No agent run started for 2 h while ready tickets exist")
    path = board / "alerts.jsonl"
    if path.exists():
        for index, line in enumerate(path.read_text().splitlines()):
            try:
                record = json.loads(line)
                if record["kind"] == "push failure":
                    add(f"push:{index}", "push failure", record["timestamp"],
                        f"{record['agent']} branch push failed after retries")
            except (ValueError, TypeError, KeyError):
                continue
    return sorted(result, key=lambda a: (a["timestamp"], a["id"]), reverse=True)


def state(board, runs=RUNS, current=None, repo=PAGE.parent.parent, hours=48):
    current = current or dispatch.now()
    titles = {}
    columns = {status: [] for status in STATUSES}
    ts = dispatch.tickets(board / "tickets")
    logs = [line for ticket in ts for line in ticket_logs(ticket)]
    for ticket in ts:
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
            "activity": activity(history, running, titles, current),
            "servers": server_activity(board, current),
            "alerts": alerts(board, ts, logs, history, running, current),
            "updates": updates(logs, repo, current, hours)}


def handler(board, runs=RUNS):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlsplit(self.path)
            if url.path == "/api/state":
                try:
                    hours = max(48, int(parse_qs(url.query).get("hours", [48])[0]))
                except ValueError:
                    self.send_error(400)
                    return
                body = json.dumps(state(board, runs, hours=hours), allow_nan=False).encode()
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
