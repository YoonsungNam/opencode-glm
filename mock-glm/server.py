"""vLLM 호환(OpenAI chat/completions) mock GLM 서버.

결정론적 시나리오:
  - tools 있음 + 마지막 user 이후 tool 결과 없음 -> reasoning + bash tool_call (finish_reason=tool_calls)
  - 마지막 user 이후 tool 결과 있음            -> 도구 결과를 인용한 최종 텍스트 + GLM_MOCK_DONE
  - tools 없음                                 -> "GLM mock reply"
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

MODEL = os.environ.get("MOCK_MODEL", "glm-5.3-flash")
API_KEY: str | None = os.environ.get("MOCK_API_KEY") or None
LOG_PATH = os.environ.get("MOCK_LOG", "logs/requests.jsonl")

TOOL_OK = "GLM_MOCK_TOOL_OK"
DONE = "GLM_MOCK_DONE"
TEXT_REPLY = "GLM mock reply"
REASONING = ["요청을 확인하기 위해 ", "셸 명령을 실행합니다."]

app = FastAPI(title="mock-glm")
_counter = 0


def _next_id() -> str:
    global _counter
    _counter += 1
    return f"chatcmpl-mock-{_counter}"


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def classify(messages: list[dict], tools: list | None) -> str:
    if not tools:
        return "text"
    last_user = -1
    for i, m in enumerate(messages):
        if m.get("role") == "user":
            last_user = i
    if any(m.get("role") == "tool" for m in messages[last_user + 1 :]):
        return "final"
    return "tool_call"


def build_reply(scenario: str, messages: list[dict]) -> dict:
    if scenario == "tool_call":
        return {
            "reasoning": list(REASONING),
            "tool_call": {"id": "call_mock_1", "name": "bash", "arguments": json.dumps({"command": f"echo {TOOL_OK}"})},
            "text": [],
            "finish": "tool_calls",
        }
    if scenario == "final":
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        excerpt = content_text(tool_msgs[-1].get("content")).strip()[:80] if tool_msgs else ""
        return {"reasoning": [], "tool_call": None, "text": [f"도구 실행 결과: {excerpt}\n", DONE], "finish": "stop"}
    return {"reasoning": [], "tool_call": None, "text": [TEXT_REPLY], "finish": "stop"}


def usage_for(messages: list[dict], reply: dict) -> dict:
    prompt_chars = 0
    for m in messages:
        prompt_chars += len(content_text(m.get("content")))
        for tc in m.get("tool_calls") or []:
            prompt_chars += len(((tc.get("function") or {}).get("arguments")) or "")
    completion_chars = sum(len(t) for t in reply["reasoning"]) + sum(len(t) for t in reply["text"])
    if reply["tool_call"]:
        completion_chars += len(reply["tool_call"]["arguments"])
    prompt = prompt_chars // 4
    completion = max(1, completion_chars // 4)
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}


def log_request(entry: dict) -> None:
    directory = os.path.dirname(LOG_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def auth_status(authorization: str | None) -> str:
    if not authorization:
        return "missing"
    if API_KEY is not None and authorization != f"Bearer {API_KEY}":
        return "bad"
    return "ok"


def error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": {"message": message, "type": "invalid_request_error"}}, status_code=status)


def completion_json(reply: dict, usage: dict) -> dict:
    text = "".join(reply["text"])
    message: dict[str, Any] = {"role": "assistant", "content": text if text else None}
    if reply["reasoning"]:
        message["reasoning_content"] = "".join(reply["reasoning"])
    if reply["tool_call"]:
        tc = reply["tool_call"]
        message["tool_calls"] = [{"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}]
    return {
        "id": _next_id(),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL,
        "choices": [{"index": 0, "message": message, "finish_reason": reply["finish"]}],
        "usage": usage,
    }


@app.get("/v1/models")
async def models() -> dict:
    return {"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "vllm"}]}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    auth = auth_status(request.headers.get("authorization"))
    if API_KEY is not None and auth != "ok":
        return error(401, "invalid api key")
    try:
        payload = json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return error(400, "invalid json")
    if not isinstance(payload, dict):
        return error(400, "invalid json")
    if payload.get("model") != MODEL:
        return error(404, "model not found")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        return error(400, "messages required")
    tools = payload.get("tools") or []
    stream = bool(payload.get("stream", False))

    scenario = classify(messages, tools)
    reply = build_reply(scenario, messages)
    usage = usage_for(messages, reply)

    log_request(
        {
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "scenario": scenario,
            "model": payload.get("model"),
            "stream": stream,
            "n_messages": len(messages),
            "roles": [m.get("role") for m in messages],
            "system_chars": sum(len(content_text(m.get("content"))) for m in messages if m.get("role") == "system"),
            "tool_names": [((t.get("function") or {}).get("name")) for t in tools if isinstance(t, dict)],
            "params": {k: v for k, v in payload.items() if k not in ("messages", "tools")},
            "auth": auth,
        }
    )

    return JSONResponse(completion_json(reply, usage))
