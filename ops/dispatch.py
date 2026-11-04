"""Kanban board and agent dispatcher.

Tickets are files in board/tickets/NNNN-slug.md: `key: value` header lines, a `---` line, then the
body. Cron runs `dispatch.py tick` every few minutes; a tick starts the owner of each ready ticket
(one run per agent at a time), sends finished Codex work to Claude for review, and starts a Claude
planning run when Codex is running out of work. Touch board/STOP to pause all dispatching.

Usage: dispatch.py tick | list | new OWNER PRIORITY TITLE [DEPENDS...] | set ID KEY VALUE | log ID AGENT MSG
"""

import datetime as dt
import fcntl
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]  # integration checkout, always on master
BOARD = REPO / "board"
TICKETS = BOARD / "tickets"
RUNNING = BOARD / "running"
LOGS = BOARD / "logs"
RUNS = BOARD / "runs.jsonl"
PROMPTS = REPO / "ops" / "prompts"
WT = REPO.parent / "llm_security-wt"
CODEX_CLONE = WT / "codex"  # separate clone: Codex's sandbox can't write a .git inside its workspace
CODEX_GITDIR = WT / "codex-gitdir"
DATA = Path("/mnt/storage/llm_security")  # raw data, caches and runs (docs/infrastructure.md)

OWNERS = {"claude", "codex", "user"}
STATUSES = {"todo", "doing", "review", "done", "blocked"}
RUN_TIMEOUT = "3h"  # longer runs are assumed stuck
# Budget: both agents are on $20 plans, so runs are few, spaced out, and use cheaper settings.
MAX_RUNS_PER_DAY = {"claude": 8, "codex": 12}
MIN_GAP = dt.timedelta(minutes=30)  # rest between an agent's runs
FAIL_COOLDOWN = dt.timedelta(hours=2)  # after a failed run (often a usage limit), wait before retrying
PLAN_INTERVAL = dt.timedelta(hours=3)  # at most one planning run per 3 hours
MIN_CODEX_QUEUE = 2  # plan more work when Codex has fewer ready tickets than this
ENV = {**os.environ, "PATH": f"{Path.home()}/.local/bin:/usr/local/bin:/usr/bin:/bin"}


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
    prompt = (PROMPTS / f"{agent}-{mode}.md").read_text()
    prompt = prompt.replace("$TICKET", str(ticket["path"]) if ticket else "").replace("$REPO", str(REPO))
    prompt = prompt.replace("$WT", str(WT))
    if agent == "codex":
        cmd = ["codex", "exec", "-c", 'model_reasoning_effort="medium"', "-s", "workspace-write", "-c", "sandbox_workspace_write.network_access=true",
               "--add-dir", str(CODEX_GITDIR), "--add-dir", str(BOARD), "--add-dir", str(DATA), "--add-dir", str(Path.home() / ".cache" / "uv"),
               "-C", str(CODEX_CLONE), prompt]
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
    if agent == "codex":  # publish Codex's branch; the sandbox has no SSH key
        subprocess.run(["git", "-C", str(CODEX_CLONE), "push", "-q", "--force-with-lease", "github", "codex"],
                       env=ENV, check=False)  # a failed push retries after the next run
    return False


def resting(agent):
    done = [r for r in runs() if r["agent"] == agent]
    if not done:
        return False
    last = max(done, key=lambda r: r["end"])
    wait = MIN_GAP if last["exit"] == 0 else FAIL_COOLDOWN
    return now() - dt.datetime.fromisoformat(last["end"]) < wait


def tick():
    if (BOARD / "STOP").exists():
        return
    ts = tickets()
    today = [r for r in runs() if r["start"][:10] == f"{now():%Y-%m-%d}"]
    capped = {a for a, cap in MAX_RUNS_PER_DAY.items() if sum(r["agent"] == a for r in today) >= cap}
    capped |= {a for a in MAX_RUNS_PER_DAY if resting(a)}

    if not reap("codex") and "codex" not in capped:
        t = pick(ts, "codex")
        if t:
            launch("codex", "work", t)

    if not reap("claude") and "claude" not in capped:
        ts = tickets()
        review = [t for t in ts if t["status"] == "review"]
        if review:
            return launch("claude", "review", min(review, key=lambda t: t["id"]))
        t = pick(ts, "claude")
        if t:
            return launch("claude", "work", t)
        by_id = {t["id"]: t for t in ts}
        codex_ready = sum(t["owner"] == "codex" and ready(t, by_id) for t in ts)
        stuck = any(t["status"] == "blocked" and t["owner"] != "user" for t in ts)
        plans = [dt.datetime.fromisoformat(r["start"]) for r in runs() if r["mode"] == "plan"]
        if (codex_ready < MIN_CODEX_QUEUE or stuck) and (not plans or now() - max(plans) > PLAN_INTERVAL):
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
