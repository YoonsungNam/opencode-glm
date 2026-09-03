#!/usr/bin/env python3
"""mock 요청 로그(requests.jsonl)에서 이번 실행분을 단정한다.

usage: verify_mocklog.py <requests.jsonl> <skip_lines>
  - scenario=tool_call 요청: stream=true, tools 에 bash 포함, params 에 'thinking' 없음,
    params.model == glm-5.3-flash, params.stream_options.include_usage == true
  - scenario=final 요청이 1개 이상
"""
import json
import sys

EXPECTED_MODEL = "glm-5.3-flash"


def main() -> int:
    path, skip = sys.argv[1], int(sys.argv[2])
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()[skip:]
    entries = [json.loads(l) for l in lines if l.strip()]
    tool_calls = [e for e in entries if e.get("scenario") == "tool_call"]
    finals = [e for e in entries if e.get("scenario") == "final"]

    problems = []
    if not tool_calls:
        problems.append("no tool_call request logged")
    else:
        e = tool_calls[0]
        p = e.get("params") or {}
        if e.get("stream") is not True:
            problems.append("tool_call request was not streamed")
        if "bash" not in (e.get("tool_names") or []):
            problems.append("bash tool not offered in request")
        if "thinking" in p:
            problems.append("Z.AI-only 'thinking' param present (provider id must not contain 'zai')")
        if p.get("model") != EXPECTED_MODEL:
            problems.append(f"model sent was {p.get('model')!r}, expected {EXPECTED_MODEL!r}")
        if not (p.get("stream_options") or {}).get("include_usage"):
            problems.append("stream_options.include_usage not set")
    if not finals:
        problems.append("no final request (after tool result) logged")

    if problems:
        for msg in problems:
            print("mocklog: " + msg, file=sys.stderr)
        return 1
    print(f"mocklog ok: {len(entries)} requests this run ({len(tool_calls)} tool_call, {len(finals)} final)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
