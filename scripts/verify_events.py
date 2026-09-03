#!/usr/bin/env python3
"""`opencode run --format json` 출력(jsonl)을 단정한다.

usage: verify_events.py <events.jsonl> [--live]
  기본:   bash tool_use(completed, 출력에 GLM_MOCK_TOOL_OK) 와 GLM_MOCK_DONE 텍스트가 있어야 한다.
  --live: completed tool_use 1개 이상, text 1개 이상이면 된다 (실서버는 마커를 모른다).
  공통:   error 이벤트가 없어야 한다.
"""
import json
import sys


def output_text(state: dict) -> str:
    out = state.get("output")
    if isinstance(out, str):
        return out
    content = state.get("content")
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def main() -> int:
    path = sys.argv[1]
    live = "--live" in sys.argv[2:]
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    tool_uses = [e for e in events if e.get("type") == "tool_use"]
    texts = [e for e in events if e.get("type") == "text"]
    errors = [e for e in events if e.get("type") == "error"]
    completed = [e for e in tool_uses if (e.get("part") or {}).get("state", {}).get("status") == "completed"]

    problems = []
    if live:
        if not completed:
            problems.append("no completed tool_use event")
        if not texts:
            problems.append("no text event")
    else:
        ok = [e for e in completed if e["part"].get("tool") == "bash" and "GLM_MOCK_TOOL_OK" in output_text(e["part"]["state"])]
        if not ok:
            problems.append("no completed bash tool_use whose output contains GLM_MOCK_TOOL_OK")
        if not any("GLM_MOCK_DONE" in ((e.get("part") or {}).get("text") or "") for e in texts):
            problems.append("no text event containing GLM_MOCK_DONE")
    if errors:
        problems.append("error event: " + json.dumps(errors[0], ensure_ascii=False)[:300])
    if not events:
        problems.append("no JSON events parsed")

    if problems:
        for p in problems:
            print("events: " + p, file=sys.stderr)
        return 1
    print(f"events ok: {len(tool_uses)} tool_use, {len(texts)} text, {len(events)} total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
