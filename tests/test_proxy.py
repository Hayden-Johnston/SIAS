import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from llm_proxy import Client, ProxyError

MESSAGES = [{"role": "user", "content": "Say hello."}]
OUTPUT = {"choices": [{"message": {"role": "assistant", "content": "Hello."}}]}


@pytest.fixture
def server(monkeypatch):
    calls, replies = [], []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append((self.path, self.headers.get("Authorization"),
                          json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            status, body = replies.pop(0) if replies else (200, OUTPUT)
            time.sleep(0.01)
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *args):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever)
    thread.start()
    monkeypatch.setenv("MAYA_URL", f"http://127.0.0.1:{http.server_port}/v1/")
    monkeypatch.setenv("MAYA_API_KEY", "fixture-key")
    yield calls, replies
    http.shutdown()
    http.server_close()
    thread.join()


def test_persistent_queue_cache_and_keys(tmp_path, server):
    calls, _ = server
    path = tmp_path / "cache.sqlite"
    client = Client(path)
    key, duplicate = client.submit_batch("test", [MESSAGES, MESSAGES], temperature=0, max_tokens=8)
    assert key == duplicate
    assert client.result(key)["status"] == "pending"
    assert client.result("unknown") is None
    # Parameter order is immaterial; all request content affects the key.
    assert client.submit_batch("test", [MESSAGES], max_tokens=8, temperature=0) == [key]
    other = client.submit_batch("other", [MESSAGES], max_tokens=8, temperature=0)[0]
    changed = client.submit_batch("test", [MESSAGES], max_tokens=9, temperature=0)[0]
    prompt = client.submit_batch("test", [[{"role": "user", "content": "Hi."}]],
                                 max_tokens=8, temperature=0)[0]
    assert len({key, other, changed, prompt}) == 4
    resumed = Client(path)
    assert resumed.drain() == 4
    assert [call[2]["model"] for call in calls] == ["test", "other", "test", "test"]
    assert calls[0] == ("/v1/chat/completions", "Bearer fixture-key",
                        {"model": "test", "messages": MESSAGES, "max_tokens": 8, "temperature": 0})
    result = resumed.result(key)
    assert result["response"] == OUTPUT
    assert result["status"] == "done"
    assert result["latency_seconds"] > 0
    assert result["attempts"] == 1
    resumed.submit_batch("test", [MESSAGES], temperature=0, max_tokens=8)
    assert Client(path).drain() == 0
    assert len(calls) == 4
    assert Client(path).result(key) == result
    assert b"fixture-key" not in path.read_bytes()


def test_retries_backoff_and_resume(tmp_path, server, monkeypatch):
    calls, replies = server
    replies.extend([(503, {}), (429, {}), (200, OUTPUT)])
    sleeps = []
    # Patch only proxy's time reference; the fake server still sleeps normally.
    from types import SimpleNamespace

    from llm_proxy import proxy
    monkeypatch.setattr(proxy, "time", SimpleNamespace(monotonic=time.monotonic,
                                                      sleep=sleeps.append))
    client = Client(tmp_path / "cache.sqlite", backoff=0.25)
    key = client.submit_batch("test", [MESSAGES])[0]
    assert client.drain() == 1
    assert sleeps == [0.25, 0.5]
    assert client.result(key)["attempts"] == 3
    key = client.submit_batch("test", [MESSAGES], temperature=1)[0]
    replies.extend([(500, {})] * 3)
    with pytest.raises(ProxyError, match="http_500"):
        client.drain()
    assert client.result(key)["status"] == "pending"
    assert client.result(key)["attempts"] == 3
    assert Client(client.path).drain() == 1
    assert client.result(key)["attempts"] == 4
    assert len(calls) == 7


@pytest.mark.parametrize("status,body,error", [
    (401, {"error": "private server detail"}, "http_401"),
    (400, {"error": {"code": "content_policy_violation"}}, "http_400"),
    (200, {"choices": [{"message": {"refusal": "refused"}}]}, "refusal"),
    (200, {}, "invalid_response"),
])
def test_permanent_failure_stops_drain(tmp_path, server, status, body, error):
    calls, replies = server
    replies.append((status, body))
    client = Client(tmp_path / "cache.sqlite", backoff=0)
    first, second = client.submit_batch("test", [MESSAGES, MESSAGES + MESSAGES])
    with pytest.raises(ProxyError, match=error) as exc:
        client.drain()
    assert "private server detail" not in str(exc.value)
    assert len(calls) == 1
    assert client.result(first)["status"] == "failed"
    assert client.result(first)["response"] is None
    assert client.result(second)["status"] == "pending"


def test_concurrent_drainers_serialize(tmp_path, server):
    calls, _ = server
    path = tmp_path / "cache.sqlite"
    clients = [Client(path), Client(path)]
    clients[0].submit_batch("test", [MESSAGES, MESSAGES + MESSAGES])
    with ThreadPoolExecutor(2) as pool:
        assert sum(pool.map(lambda client: client.drain(), clients)) == 2
    assert len(calls) == 2


def test_dotenv_and_validation(tmp_path, monkeypatch):
    monkeypatch.delenv("MAYA_URL", raising=False)
    monkeypatch.delenv("MAYA_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("MAYA_URL=http://localhost:1234/v1\nMAYA_API_KEY=fixture-key\n")
    client = Client(tmp_path / "cache.sqlite", env_file=env)
    assert client.url == "http://localhost:1234/v1"
    assert client.key == "fixture-key"
    monkeypatch.setenv("MAYA_API_KEY", "override-fixture")
    assert Client(client.path, env_file=env).key == "override-fixture"
    for params in ({"stream": True}, {"messages": []}):
        with pytest.raises(ValueError):
            client.submit_batch("test", [MESSAGES], **params)
    with pytest.raises(ValueError):
        Client(client.path, attempts=0)


def test_transport_failure_is_pending(tmp_path, server, monkeypatch):
    import httpx

    def fail(*args, **kwargs):
        raise httpx.ConnectError("private transport detail")

    monkeypatch.setattr(httpx.Client, "post", fail)
    client = Client(tmp_path / "cache.sqlite", attempts=2, backoff=0)
    key = client.submit_batch("test", [MESSAGES])[0]
    with pytest.raises(ProxyError, match="transport_error"):
        client.drain()
    assert client.result(key)["status"] == "pending"
    assert client.result(key)["attempts"] == 2
    assert client.result(key)["error"] == "transport_error"
