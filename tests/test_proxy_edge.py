"""Edge-case tests for llm_proxy/proxy.py: cache hits, drain order, port-8099 refusal, error caching."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import httpx
import pytest

from llm_proxy import Client, ProxyError

MESSAGES = [{"role": "user", "content": "Say hello."}]
OUTPUT = {"choices": [{"message": {"role": "assistant", "content": "Hello."}}]}


@pytest.fixture
def server(monkeypatch):
    calls, replies = [], []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            status, body = replies.pop(0) if replies else (200, OUTPUT)
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *args):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever)
    thread.start()
    monkeypatch.setenv("MAYA_URL", f"http://127.0.0.1:{http.server_port}/v1")
    monkeypatch.setenv("MAYA_API_KEY", "k")
    yield calls, replies
    http.shutdown()
    http.server_close()
    thread.join()


def test_duplicate_request_hits_cache(tmp_path, server):
    """A second submit of identical content reuses the key and makes no extra HTTP call."""
    calls, _ = server
    client = Client(tmp_path / "c.sqlite")
    key1 = client.submit_batch("m", [MESSAGES], temperature=0)[0]
    key2 = client.submit_batch("m", [MESSAGES], temperature=0)[0]
    assert key1 == key2
    assert client.drain() == 1
    assert len(calls) == 1
    # Resubmit after drain: no new row, no new call.
    key3 = client.submit_batch("m", [MESSAGES], temperature=0)[0]
    assert key3 == key1
    assert Client(client.path).drain() == 0
    assert len(calls) == 1
    assert client.result(key1)["status"] == "done"
    assert client.result(key1)["response"] == OUTPUT


@pytest.fixture
def managed_client(tmp_path, server, monkeypatch):
    """Client with model_sets configured to use the test server as evaluator."""
    port = urlsplit(os.environ["MAYA_URL"]).port
    config = tmp_path / "eval.json"
    config.write_text(json.dumps({"evaluator": {"host": "127.0.0.1", "port": port,
                                                 "gpus": [], "binary": "x", "model": "x"}}))
    stub = tmp_path / "stub.py"
    stub.write_text("pass")
    client = Client(tmp_path / "m.sqlite", model_sets={"a": "evaluator", "b": "evaluator"},
                    server_config=config, timeout=5)
    client.server_script = stub
    monkeypatch.setattr(httpx.Client, "get", lambda *a, **kw: httpx.Response(200))
    return client


def test_drain_order_groups_by_model(tmp_path, server, managed_client):
    """With model_sets, drain groups all jobs for one model before moving to the next."""
    calls, _ = server
    client = managed_client
    # Interleave submissions: a, b, a, b
    client.submit_batch("a", [MESSAGES])
    client.submit_batch("b", [MESSAGES + MESSAGES])
    client.submit_batch("a", [MESSAGES + MESSAGES])
    client.submit_batch("b", [MESSAGES])
    client.drain()
    models = [c["model"] for c in calls]
    # Jobs are grouped by model: all of one model, then all of the other.
    assert models == ["a", "a", "b", "b"] or models == ["b", "b", "a", "a"]


def test_port_8099_lifecycle_refused(tmp_path, server):
    """Evaluator config with port 8099 is refused before any subprocess call."""
    _calls, _ = server
    config = tmp_path / "eval.json"
    config.write_text(json.dumps({"evaluator": {"host": "127.0.0.1", "port": 8099,
                                                 "gpus": [], "binary": "x", "model": "x"}}))
    marker = tmp_path / "started"
    stub = tmp_path / "stub.py"
    stub.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    client = Client(tmp_path / "c.sqlite", model_sets={"judge": "evaluator"},
                    server_config=config, timeout=5)
    client.server_script = stub
    keys = client.submit_batch("judge", [MESSAGES, MESSAGES + MESSAGES])
    with pytest.raises(ProxyError, match="server_set_refused"):
        client.drain()
    assert not marker.exists(), "subprocess must not be spawned for port 8099"
    assert server[0] == []
    for key in keys:
        assert client.result(key)["status"] == "failed"
        assert client.result(key)["error"] == "server_set_refused"


def test_error_response_not_cached(tmp_path, server):
    """A failed job stores no response body; the key yields response=None."""
    _calls, replies = server
    replies.append((400, {"error": "bad request"}))
    client = Client(tmp_path / "c.sqlite", backoff=0)
    key = client.submit_batch("m", [MESSAGES])[0]
    with pytest.raises(ProxyError, match="http_400"):
        client.drain()
    result = client.result(key)
    assert result["status"] == "failed"
    assert result["response"] is None
    assert result["error"] == "http_400"
    # The raw server body must not leak into the stored result.
    assert "bad request" not in json.dumps(result)
