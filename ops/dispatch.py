"""Kanban board and agent dispatcher.

Tickets are files in board/tickets/NNNN-slug.md: `key: value` header lines, a `---` line, then the
body. Cron runs `dispatch.py tick` every few minutes; a tick starts the owner of each ready ticket
(one run per agent at a time), sends finished worker output (Codex, pi) to Claude for review, and starts
a Claude planning run when a worker is running out of work. Touch board/STOP to pause all dispatching.

Usage: dispatch.py tick | list | new OWNER PRIORITY TITLE [DEPENDS...] | set ID KEY VALUE | log ID AGENT MSG
"""

import datetime as dt
import fcntl
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

REPO = Path(__file__).resolve().parents[1]  # integration checkout, always on master
BOARD = REPO / "board"
TICKETS = BOARD / "tickets"
RUNNING = BOARD / "running"
LOGS = BOARD / "logs"
RUNS = BOARD / "runs.jsonl"
PROMPTS = REPO / "ops" / "prompts"
WT = REPO.parent / "llm_security-wt"
# Workers implement tickets in their own clones, whose git dirs live outside the checkout because
# Codex's sandbox makes any .git inside its workspace read-only. Each worker works on a branch named
# after itself. pi (local Qwen model on the second host) runs in a Docker sandbox (ops/pi/Dockerfile).
WORKERS = ("codex", "pi")
PI_AGENT_DIR = WT / "pi-agent"  # pi config (models.json) and uv caches for the container
DATA = Path("/mnt/storage/llm_security")  # raw data, caches and runs (docs/infrastructure.md)

OWNERS = {"claude", *WORKERS, "user"}
STATUSES = {"todo", "doing", "review", "done", "blocked"}
RUN_TIMEOUT = "3h"  # longer runs are assumed stuck
# Budget: both agents are on $20 plans, so runs are few, spaced out, and use cheaper settings.
# Plan usage resets on rolling 5-hour windows; cap runs per window so a burst can't exhaust one.
# Interactive Claude sessions share Claude's window, so Claude gets fewer dispatched runs.
WINDOW = dt.timedelta(hours=5)
# pi runs on a local model and costs no plan tokens; its cap only guards against runaway loops.
# Caps are loose: usage checked 2026-11-04 showed large headroom; the window cap still stops runaway loops.
MAX_RUNS_PER_WINDOW = {"claude": 12, "codex": 15, "pi": 30}
MIN_GAP = {"claude": dt.timedelta(minutes=5), "codex": dt.timedelta(minutes=5), "pi": dt.timedelta(0)}
FAIL_COOLDOWN = dt.timedelta(hours=2)  # after a failed run (often a usage limit), wait before retrying
PIPELINE_INTERVAL = dt.timedelta(hours=6)
PLAN_INTERVAL = dt.timedelta(hours=3)  # at most one planning run per 3 hours
IDLE_PLAN_INTERVAL = dt.timedelta(minutes=30)  # sooner when a worker has nothing ready
PUSH_TRIES = 5  # GitHub SSH rejected ~half of connections on 2026-11-04
MIN_QUEUE = 2  # plan more work when a worker has fewer ready tickets than this
ENV = {**os.environ, "PATH": f"{Path.home()}/.local/bin:/usr/local/bin:/usr/bin:/bin"}


def dotenv(key):
    """One value from the repo's .env (cron does not load it)."""
    for line in (REPO / ".env").read_text().splitlines():
        name, _, value = line.partition("=")
        if name.strip() == key:
            return value.strip()
    return ""


def now():
    return dt.datetime.now().astimezone()


def read(path):
    head = path.read_text().partition("\n---\n")[0]
    fields = dict(line.split(": ", 1) for line in head.splitlines() if ": " in line)
    fields["depends"] = fields.get("depends", "").split()
    fields["path"] = path
    return fields


def tickets(directory=None):
    return [read(p) for p in sorted((directory or TICKETS).glob("*.md"))]


def find(tid):
    matches = list(TICKETS.glob(f"{int(tid):04d}-*.md"))
    if not matches:
        sys.exit(f"no ticket {tid}")
    return matches[0]


def set_field(tid, key, value):
    if key == "status" and value not in STATUSES:
        sys.exit(f"status must be one of {sorted(STATUSES)}")
    if key == "owner" and value not in OWNERS:
        sys.exit(f"owner must be one of {sorted(OWNERS)}")
    path = find(tid)
    head, _, body = path.read_text().partition("\n---\n")
    lines = [ln for ln in head.splitlines() if not ln.startswith(f"{key}: ")] + [f"{key}: {value}"]
    order = ["id", "title", "owner", "status", "priority", "depends", "created"]
    lines.sort(key=lambda ln: order.index(ln.split(": ")[0]) if ln.split(": ")[0] in order else 99)
    path.write_text("\n".join(lines) + "\n---\n" + body)


def log(tid, agent, msg):
    with find(tid).open("a") as f:
        f.write(f"- {now():%Y-%m-%d %H:%M} {agent}: {msg}\n")


def new(owner, priority, title, depends):
    if owner not in OWNERS:
        sys.exit(f"owner must be one of {sorted(OWNERS)}")
    TICKETS.mkdir(parents=True, exist_ok=True)
    ids = [int(p.name[:4]) for p in TICKETS.glob("*.md")]
    tid = max(ids, default=0) + 1
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40]
    path = TICKETS / f"{tid:04d}-{slug}.md"
    path.write_text(
        f"id: {tid:04d}\ntitle: {title}\nowner: {owner}\nstatus: todo\npriority: {int(priority)}\n"
        f"depends: {' '.join(f'{int(d):04d}' for d in depends)}\ncreated: {now():%Y-%m-%d}\n---\n"
        "## Spec\n\n## Acceptance\n\n## Log\n"
    )
    print(path)


def ready(t, by_id):
    return t["status"] == "todo" and all(by_id.get(d, {}).get("status") == "done" for d in t["depends"])


def pick(ts, owner):
    by_id = {t["id"]: t for t in ts}
    cands = [t for t in ts if t["owner"] == owner and ready(t, by_id)]
    return min(cands, key=lambda t: (int(t["priority"]), t["id"]), default=None)


def runs():
    if not RUNS.exists():
        return []
    return [json.loads(line) for line in RUNS.read_text().splitlines() if line]


def launch(agent, mode, ticket):
    start = now()
    tid = ticket["id"] if ticket else "-"
    name = f"{start:%Y%m%d-%H%M%S}-{agent}-{mode}-{tid}"
    if agent != "pipeline":
        prompt = (PROMPTS / ("worker-work.md" if agent in WORKERS else f"{agent}-{mode}.md")).read_text()
        subs = {"$TICKET": str(ticket["path"]) if ticket else "", "$REPO": str(REPO), "$WT": str(WT), "$AGENT": agent,
                "$OWNER": ticket["owner"] if ticket else ""}
        for key, value in subs.items():
            prompt = prompt.replace(key, value)
    clone, gitdir = WT / agent, WT / f"{agent}-gitdir"
    if agent == "pipeline":
        cmd = ["uv", "run", "python", "ops/iterate.py"]
    elif agent == "codex":
        cmd = ["codex", "exec", "-c", 'model_reasoning_effort="medium"', "-s", "workspace-write", "-c", "sandbox_workspace_write.network_access=true",
               "--add-dir", str(gitdir), "--add-dir", str(BOARD), "--add-dir", str(DATA), "--add-dir", str(Path.home() / ".cache" / "uv"),
               "-C", str(clone), prompt]
    elif agent == "pi":  # mounts are the whole world it sees: no Docker socket, no Maya key
        mounts = [f"{REPO}:{REPO}:ro", f"{BOARD}:{BOARD}", f"{DATA}:{DATA}", f"{clone}:{clone}", f"{gitdir}:{gitdir}",
                  f"{PI_AGENT_DIR}:{PI_AGENT_DIR}"]
        cmd = ["docker", "run", "--rm", "--name", f"sias-pi-{tid}", "--user", f"{os.getuid()}:{os.getgid()}",
               "-e", "HOME=/tmp", "-e", f"PI_CODING_AGENT_DIR={PI_AGENT_DIR}", "-e", f"UV_CACHE_DIR={PI_AGENT_DIR}/uv-cache",
               "-e", f"UV_PYTHON_INSTALL_DIR={PI_AGENT_DIR}/uv-python", "-e", f"LLAMA_API_KEY={dotenv('LLAMA_API_KEY')}",
               *[a for m in mounts for a in ("-v", m)], "-w", str(clone), "sias-pi:1",
               "pi", "-p", "--no-session", "--model", "rig/swift-1.5-27b", "--thinking", "low", prompt]
    else:
        cmd = ["claude", "-p", prompt, "--model", "sonnet", "--effort", "medium", "--permission-mode", "auto", "--add-dir", str(WT)]  # --add-dir is variadic
    exit_file = LOGS / f"{name}.exit"
    shell = 'timeout "$0" "$@"; echo $? > "$EXIT_FILE"'
    with (LOGS / f"{name}.log").open("w") as out:
        proc = subprocess.Popen(["sh", "-c", shell, RUN_TIMEOUT, *cmd], cwd=REPO, stdout=out,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
                                env={**ENV, "EXIT_FILE": str(exit_file)})
    state = {"agent": agent, "mode": mode, "ticket": tid, "start": start.isoformat(), "pid": proc.pid, "name": name}
    (RUNNING / f"{agent}.json").write_text(json.dumps(state))
    if ticket and mode == "work":
        set_field(tid, "status", "doing")


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def reap(agent):
    """Return True if the agent is still busy. Record finished runs."""
    state_file = RUNNING / f"{agent}.json"
    if not state_file.exists():
        return False
    state = json.loads(state_file.read_text())
    if alive(state["pid"]):
        return True
    exit_file = LOGS / f"{state['name']}.exit"
    code = int(exit_file.read_text()) if exit_file.exists() else None
    with RUNS.open("a") as f:
        f.write(json.dumps({**state, "end": now().isoformat(), "exit": code}) + "\n")
    state_file.unlink()
    tid = state["ticket"]
    if tid != "-":
        status = read(find(tid))["status"]
        if (state["mode"] == "work" and status == "doing") or (state["mode"] == "review" and status == "review"):
            set_field(tid, "status", "blocked")
            log(tid, "dispatch", f"{state['mode']} run ended (exit {code}) without a status change; "
                                 f"see board/logs/{state['name']}.log")
    if agent in WORKERS:  # publish the worker's branch; sandboxes have no SSH key
        push = ["git", "-C", str(WT / agent), "push", "-q", "--force-with-lease", "github", agent]
        for _ in range(PUSH_TRIES):  # GitHub SSH intermittently rejects the key; later runs retry too
            if subprocess.run(push, env=ENV, check=False, capture_output=True).returncode == 0:
                break
        else:
            with (BOARD / "alerts.jsonl").open("a") as f:
                f.write(json.dumps({"kind": "push failure", "timestamp": now().isoformat(),
                                    "agent": agent}) + "\n")
    return False


def rest_until(agent, history):
    done = [r for r in history if r["agent"] == agent]
    if not done:
        return None
    last = max(done, key=lambda r: r["end"])
    wait = MIN_GAP.get(agent, dt.timedelta(0)) if last["exit"] == 0 else FAIL_COOLDOWN
    return dt.datetime.fromisoformat(last["end"]) + wait


def agent_pause(agent, history, current):
    """Dispatch eligibility, shared with the read-only dashboard."""
    recent = sorted(dt.datetime.fromisoformat(r["start"]) for r in history
                    if r["agent"] == agent
                    and current - dt.datetime.fromisoformat(r["start"]) < WINDOW)
    cap = MAX_RUNS_PER_WINDOW.get(agent)
    until = recent[-cap] + WINDOW if cap and len(recent) >= cap else None
    rest = rest_until(agent, history)
    if until and until > current:
        return "capped", max(until, rest) if rest else until
    if rest and rest > current:
        return "resting", rest
    return "idle", None


def resting(agent):
    until = rest_until(agent, runs())
    return until is not None and now() < until


def server_sample(server):
    """One metadata GET; never request inference or persist URLs/response bodies."""
    result = {"server": server["name"], "up": False, "models": []}
    try:
        with urlopen(server["url"], timeout=1) as response:
            body = response.read(65536)  # status metadata only; cap oversized responses
            result["up"] = response.status == 200
        try:
            data = json.loads(body)
            result["models"] = [row["id"] for row in data.get("data", [])
                                if isinstance(row.get("id"), str)
                                and row.get("status", {"value": "loaded"}).get("value") == "loaded"]
        except (ValueError, TypeError, AttributeError):
            pass  # health-only endpoints need not advertise a model
    except (OSError, URLError, ValueError):
        pass
    return result


def sample_servers():
    path = REPO / "servers.local.json"
    if not path.exists():
        return
    servers = json.loads(path.read_text())
    if not servers:
        return
    # Probe all endpoints concurrently: seven unreachable servers cost one timeout, not seven.
    timestamp = now().isoformat()
    with ThreadPoolExecutor(max_workers=len(servers)) as pool:
        samples = list(pool.map(server_sample, servers))
    with (BOARD / "servers.jsonl").open("a") as output:
        for sample in samples:
            output.write(json.dumps({"timestamp": timestamp, **sample}) + "\n")


def tick():
    if (BOARD / "STOP").exists():
        return
    sample_servers()
    pipeline_busy = reap("pipeline")
    history, current = runs(), now()
    pipeline_runs = [dt.datetime.fromisoformat(r["start"]) for r in history if r["agent"] == "pipeline"]
    if (not pipeline_busy and (REPO / "iterate.local.json").exists()
            and (not pipeline_runs or current - max(pipeline_runs) >= PIPELINE_INTERVAL)):
        launch("pipeline", "iterate", None)
    ts = tickets()
    capped = {a for a in MAX_RUNS_PER_WINDOW if agent_pause(a, history, current)[0] != "idle"}

    for worker in WORKERS:
        if not reap(worker) and worker not in capped:
            t = pick(ts, worker)
            if t:
                launch(worker, "work", t)

    if not reap("claude") and "claude" not in capped:
        ts = tickets()
        review = [t for t in ts if t["status"] == "review"]
        if review:
            return launch("claude", "review", min(review, key=lambda t: t["id"]))
        t = pick(ts, "claude")
        if t:
            return launch("claude", "work", t)
        by_id = {t["id"]: t for t in ts}
        queues = [sum(t["owner"] == w and ready(t, by_id) for t in ts) for w in WORKERS]
        starved = min(queues) < MIN_QUEUE
        stuck = any(t["status"] == "blocked" and t["owner"] != "user" for t in ts)
        plans = [dt.datetime.fromisoformat(r["start"]) for r in runs() if r["mode"] == "plan"]
        interval = IDLE_PLAN_INTERVAL if min(queues) == 0 else PLAN_INTERVAL
        if (starved or stuck) and (not plans or now() - max(plans) > interval):
            launch("claude", "plan", None)


def main():
    for d in (TICKETS, RUNNING, LOGS):
        d.mkdir(parents=True, exist_ok=True)
    args = sys.argv[1:] or ["tick"]
    cmd = args[0]
    if cmd == "tick":
        with (BOARD / ".lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            tick()
    elif cmd == "list":
        for t in tickets():
            print(f"{t['id']}  {t['status']:<8}{t['owner']:<7}p{t['priority']}  {t['title']}"
                  + (f"  (after {' '.join(t['depends'])})" if t["depends"] else ""))
    elif cmd == "new":
        new(args[1], args[2], args[3], args[4:])
    elif cmd == "set":
        set_field(args[1], args[2], args[3])
    elif cmd == "log":
        log(args[1], args[2], args[3])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
