import json

import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "LOG_PATH", str(tmp_path / "requests.jsonl"))
    monkeypatch.setattr(server, "API_KEY", None)
    return TestClient(server.app)


TOOLS = [{"type": "function", "function": {"name": "bash", "description": "run", "parameters": {"type": "object"}}}]


def body(messages, tools=None, **extra):
    b = {"model": server.MODEL, "messages": messages, "stream": False}
    if tools is not None:
        b["tools"] = tools
    b.update(extra)
    return b


def test_models_lists_mock_model(client):
    r = client.get("/v1/models")
    assert r.status_code == 200
    assert [m["id"] for m in r.json()["data"]] == [server.MODEL]


def test_classify_scenarios():
    user = {"role": "user", "content": "hi"}
    assert server.classify([user], None) == "text"
    assert server.classify([user], []) == "text"
    assert server.classify([user], TOOLS) == "tool_call"
    after_tool = [user, {"role": "assistant", "tool_calls": []}, {"role": "tool", "tool_call_id": "x", "content": "out"}]
    assert server.classify(after_tool, TOOLS) == "final"
    second_turn = after_tool + [{"role": "assistant", "content": "done"}, {"role": "user", "content": "again"}]
    assert server.classify(second_turn, TOOLS) == "tool_call"


def test_text_scenario_without_tools(client):
    r = client.post("/v1/chat/completions", json=body([{"role": "user", "content": "title please"}]))
    assert r.status_code == 200
    choice = r.json()["choices"][0]
    assert choice["message"]["content"] == server.TEXT_REPLY
    assert choice["finish_reason"] == "stop"
    assert "tool_calls" not in choice["message"]


def test_tool_call_scenario_non_stream(client):
    r = client.post("/v1/chat/completions", json=body([{"role": "user", "content": "smoke"}], TOOLS))
    assert r.status_code == 200
    data = r.json()
    choice = data["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    msg = choice["message"]
    assert msg["reasoning_content"] == "".join(server.REASONING)
    call = msg["tool_calls"][0]
    assert call["id"] == "call_mock_1"
    assert call["type"] == "function"
    assert call["function"]["name"] == "bash"
    assert json.loads(call["function"]["arguments"]) == {"command": f"echo {server.TOOL_OK}"}
    assert data["usage"]["total_tokens"] == data["usage"]["prompt_tokens"] + data["usage"]["completion_tokens"]


def test_final_scenario_after_tool_result(client):
    messages = [
        {"role": "user", "content": "smoke"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_mock_1", "type": "function", "function": {"name": "bash", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_mock_1", "content": "GLM_MOCK_TOOL_OK\n"},
    ]
    r = client.post("/v1/chat/completions", json=body(messages, TOOLS))
    assert r.status_code == 200
    choice = r.json()["choices"][0]
    assert choice["finish_reason"] == "stop"
    assert choice["message"]["content"].startswith("도구 실행 결과: GLM_MOCK_TOOL_OK")
    assert choice["message"]["content"].endswith(server.DONE)


def test_request_is_logged(client, tmp_path):
    client.post("/v1/chat/completions", json=body([{"role": "system", "content": "sys"}, {"role": "user", "content": "smoke"}], TOOLS, temperature=1.0))
    lines = (tmp_path / "requests.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["scenario"] == "tool_call"
    assert entry["stream"] is False
    assert entry["roles"] == ["system", "user"]
    assert entry["system_chars"] == 3
    assert entry["tool_names"] == ["bash"]
    assert entry["auth"] == "missing"
    assert "messages" not in entry["params"] and "tools" not in entry["params"]
    assert entry["params"]["temperature"] == 1.0
    assert entry["params"]["model"] == server.MODEL


def test_unknown_model_is_404(client):
    r = client.post("/v1/chat/completions", json={"model": "other", "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "model not found"


def test_invalid_json_is_400(client):
    r = client.post("/v1/chat/completions", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "invalid json"


def test_missing_messages_is_400(client):
    r = client.post("/v1/chat/completions", json={"model": server.MODEL})
    assert r.status_code == 400


def sse_events(response):
    events = []
    for line in response.iter_lines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: "):]
        events.append(payload if payload == "[DONE]" else json.loads(payload))
    return events


def test_stream_tool_call_chunk_order(client):
    b = body([{"role": "user", "content": "smoke"}], TOOLS, stream=True, stream_options={"include_usage": True})
    with client.stream("POST", "/v1/chat/completions", json=b) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = sse_events(r)
    assert events[-1] == "[DONE]"
    chunks = events[:-1]
    assert all(c["object"] == "chat.completion.chunk" and c["model"] == server.MODEL for c in chunks)
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    reasoning = "".join(c["choices"][0]["delta"].get("reasoning_content", "") for c in chunks if c["choices"])
    assert reasoning == "".join(server.REASONING)
    tool_deltas = [c["choices"][0]["delta"]["tool_calls"][0] for c in chunks if c["choices"] and "tool_calls" in c["choices"][0]["delta"]]
    assert tool_deltas[0]["index"] == 0
    assert tool_deltas[0]["id"] == "call_mock_1"
    assert tool_deltas[0]["type"] == "function"
    assert tool_deltas[0]["function"]["name"] == "bash"
    arguments = "".join(d["function"].get("arguments", "") for d in tool_deltas)
    assert json.loads(arguments) == {"command": f"echo {server.TOOL_OK}"}
    finish = [c["choices"][0]["finish_reason"] for c in chunks if c["choices"] and c["choices"][0]["finish_reason"]]
    assert finish == ["tool_calls"]
    usage_chunks = [c for c in chunks if c["choices"] == []]
    assert len(usage_chunks) == 1
    assert usage_chunks[0]["usage"]["total_tokens"] > 0
    assert chunks[-1] is usage_chunks[0]


def test_stream_without_include_usage_has_no_usage_chunk(client):
    b = body([{"role": "user", "content": "smoke"}], TOOLS, stream=True)
    with client.stream("POST", "/v1/chat/completions", json=b) as r:
        events = sse_events(r)
    assert events[-1] == "[DONE]"
    assert all(c["choices"] for c in events[:-1])
    assert events[-2]["choices"][0]["finish_reason"] == "tool_calls"


def test_stream_final_text(client):
    messages = [
        {"role": "user", "content": "smoke"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_mock_1", "type": "function", "function": {"name": "bash", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_mock_1", "content": "GLM_MOCK_TOOL_OK\n"},
    ]
    with client.stream("POST", "/v1/chat/completions", json=body(messages, TOOLS, stream=True)) as r:
        events = sse_events(r)
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in events[:-1] if c["choices"])
    assert text.startswith("도구 실행 결과: GLM_MOCK_TOOL_OK")
    assert text.endswith(server.DONE)


def test_stream_request_logged_with_stream_true(client, tmp_path):
    b = body([{"role": "user", "content": "smoke"}], TOOLS, stream=True, stream_options={"include_usage": True})
    with client.stream("POST", "/v1/chat/completions", json=b) as r:
        sse_events(r)
    entry = json.loads((tmp_path / "requests.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert entry["stream"] is True
    assert entry["params"]["stream_options"] == {"include_usage": True}


def test_api_key_enforced_when_configured(client, monkeypatch):
    monkeypatch.setattr(server, "API_KEY", "secret")
    b = body([{"role": "user", "content": "x"}])
    assert client.post("/v1/chat/completions", json=b).status_code == 401
    assert client.post("/v1/chat/completions", json=b, headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = client.post("/v1/chat/completions", json=b, headers={"Authorization": "Bearer secret"})
    assert ok.status_code == 200
    assert client.get("/v1/models").status_code == 200


def test_auth_status_logged(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "API_KEY", "secret")
    client.post("/v1/chat/completions", json=body([{"role": "user", "content": "x"}]), headers={"Authorization": "Bearer secret"})
    entry = json.loads((tmp_path / "requests.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert entry["auth"] == "ok"
