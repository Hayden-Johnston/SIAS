"""Persistent chat queue and cache; no server lifecycle management."""

import fcntl
import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
from dotenv import dotenv_values


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


class ProxyError(RuntimeError):
    """A request failed. Error messages omit server bodies and credentials."""


class Client:
    """Explicit base_url/api_key select another server without inheriting Maya credentials."""

    def __init__(self, path, *, env_file=".env", timeout=300, attempts=3, backoff=1,
                 base_url=None, api_key=None):
        if attempts < 1 or backoff < 0 or timeout <= 0:
            raise ValueError("Invalid retry or timeout settings")
        settings = dotenv_values(env_file) | os.environ
        self.url = (base_url if base_url is not None else
                    settings.get("MAYA_URL", "http://127.0.0.1:8099/v1")).rstrip("/")
        self.key = api_key if base_url is not None else settings.get("MAYA_API_KEY")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.timeout, self.attempts, self.backoff = timeout, attempts, backoff
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                key TEXT PRIMARY KEY, request TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', response TEXT,
                latency_seconds REAL, attempts INTEGER NOT NULL DEFAULT 0, error TEXT
            )""")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def submit_batch(self, model, prompts, **params):
        """Queue lists of chat messages; return cache keys in input order.

        All generation parameters participate in the key. Streaming is unsupported.
        """
        if not model or {"model", "messages", "stream"} & params.keys():
            raise ValueError("Supply a model, message lists, and non-streaming parameters")
        keys = []
        with self._db() as db:
            for messages in prompts:
                request = _json({"model": model, "messages": messages, **params})
                prompt_hash = hashlib.sha256(_json(messages).encode()).hexdigest()
                key = hashlib.sha256(_json([model, prompt_hash, params]).encode()).hexdigest()
                db.execute("INSERT OR IGNORE INTO jobs (key, request) VALUES (?, ?)",
                           (key, request))
                keys.append(key)
        return keys

    def result(self, key):
        """Return status, output, HTTP attempt latency and attempts; None for unknown keys."""
        with self._db() as db:
            row = db.execute("""SELECT status, response, latency_seconds, attempts, error
                                FROM jobs WHERE key = ?""", (key,)).fetchone()
        if row is None:
            return None
        return {"status": row[0], "response": json.loads(row[1]) if row[1] else None,
                "latency_seconds": row[2], "attempts": row[3], "error": row[4]}

    def drain(self):
        """Complete pending jobs FIFO, serially across drainers using this database.

        Transient errors remain pending after exhaustion; a later drain can retry.
        Permanent errors/refusals are marked failed and stop this drain. A crash can
        repeat an in-flight HTTP request, but committed outputs are never requested again.
        """
        completed = 0
        with open(str(self.path) + ".lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
            with httpx.Client(timeout=self.timeout, headers=headers, trust_env=False) as http:
                while True:
                    with self._db() as db:
                        job = db.execute("""SELECT key, request FROM jobs
                                            WHERE status = 'pending' ORDER BY rowid LIMIT 1""").fetchone()
                    if job is None:
                        return completed
                    key, request = job
                    for attempt in range(self.attempts):
                        started = time.monotonic()
                        response, error, retry = None, None, False
                        try:
                            reply = http.post(self.url + "/chat/completions",
                                              content=request, headers={"Content-Type": "application/json"})
                            if reply.is_success:
                                response = reply.json()
                                choices = response.get("choices", [])
                                if not choices or not isinstance(choices[0].get("message"), dict):
                                    error = "invalid_response"
                                elif any(c["message"].get("refusal") for c in choices):
                                    error = "refusal"
                            else:
                                error = f"http_{reply.status_code}"
                                retry = reply.status_code == 429 or reply.status_code >= 500
                        except httpx.TransportError:
                            error, retry = "transport_error", True
                        except (ValueError, TypeError, KeyError, AttributeError):
                            error = "invalid_response"
                        latency = time.monotonic() - started
                        with self._db() as db:
                            db.execute("""UPDATE jobs SET status = ?, response = ?,
                                latency_seconds = coalesce(latency_seconds, 0) + ?,
                                attempts = attempts + 1, error = ? WHERE key = ?""",
                                ("pending" if error and retry else "failed" if error else "done",
                                 _json(response) if not error else None, latency, error, key))
                        if not error:
                            completed += 1
                            break
                        if not retry or attempt + 1 == self.attempts:
                            raise ProxyError(f"{key}: {error}")
                        time.sleep(self.backoff * 2**attempt)
