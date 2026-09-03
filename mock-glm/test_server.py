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
