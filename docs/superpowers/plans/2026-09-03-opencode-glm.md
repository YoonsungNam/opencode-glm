# opencode ↔ 사내 GLM(vLLM) 연결 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** opencode v1.18.27을 고정 설치하고, vLLM 호환 mock GLM 서버(`glm-5.3-flash`)에 custom provider로 연결해 tool calling까지 자동 검증되는 PoC 리포를 만든다.

**Architecture:** `bin/opencode-glm` 래퍼가 오프라인 플래그와 `OPENCODE_CONFIG`를 설정하고 `.bin/opencode`(GitHub Releases prebuilt v1.18.27)를 실행한다. `config/opencode.json`은 `company-glm` custom provider(`@ai-sdk/openai-compatible`)로 `http://127.0.0.1:8000/v1`에 붙는다. `mock-glm/server.py`(FastAPI)가 vLLM의 OpenAI 호환 API를 결정론적으로 흉내 내고, `scripts/verify.sh`가 `opencode run --format json`으로 tool call → 최종 답변 흐름을 단정한다.

**Tech Stack:** bash(`set -euo pipefail`), Python 3.10 시스템 인터프리터(FastAPI 0.139.0, uvicorn 0.50.0, httpx 0.28.1, pytest 9.0.2 기설치, 추가 pip 설치 없음), curl, tar, sha256sum, git.

**Spec:** `docs/superpowers/specs/2026-09-03-opencode-glm-design.md`

## Global Constraints

- opencode 버전은 `1.18.27` 고정. 설치 자산은 `opencode-linux-x64.tar.gz`(x86_64+AVX2), sha256 `4af5494f9433f59db8c1e344198f0ee72a50c06ec009fb4a8aeab4c2d4abd702`. tarball 안에는 루트에 `opencode` 실행 파일 하나만 있다.
- provider ID는 `company-glm` 고정. ID에 `zai`/`zhipuai` 문자열을 넣지 않는다 (opencode가 Z.AI 전용 `thinking` 파라미터를 주입함).
- 모델 키는 `glm-5.3-flash` 고정. 표시 이름 `GLM-5.3-Flash (on-prem)`.
- mock 마커 문자열: tool 출력 `GLM_MOCK_TOOL_OK`, 최종 답변 `GLM_MOCK_DONE`, 도구 없는 요청 답변 `GLM mock reply`.
- 모든 bash 스크립트는 `#!/usr/bin/env bash` + `set -euo pipefail`. 리포 루트는 스크립트 위치 기준으로 계산한다.
- 이 PC에는 GPU·docker·bun이 없다. 인터넷은 된다 (GitHub 접근 가능).
- 참고 클론 `/home/mini/github/opencode`는 읽기 전용. 빌드하지 않고 `v1.18.27` 태그만 체크아웃한다.
- 커밋 메시지는 한국어 요약 + 아래 트레일러 두 줄로 끝낸다:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01SSznsrf2rp77wmjcB8kLmL
  ```
- 리포에는 `.gitignore`(`.bin/ dist/ logs/ __pycache__/ *.pyc .pytest_cache/ .venv/`)와 스펙 문서가 이미 커밋돼 있다.

---

## File Structure

| 경로 | 책임 |
|---|---|
| `config/opencode.json` | custom provider, 기본 모델, share/autoupdate 비활성, provider allow-list |
| `config/opencode.env` | `OPENCODE_DISABLE_*` 플래그 (래퍼가 source) |
| `bin/opencode-glm` | env 로드 → `OPENCODE_CONFIG` 절대경로 지정 → `.bin/opencode` exec |
| `scripts/install-opencode.sh` | 고정 버전 tarball 다운로드/오프라인 반입, 체크섬·버전 검증, `.bin/` 설치 |
| `scripts/checksums.txt` | `<sha256>  v<버전>/<자산명>` 한 줄씩 |
| `mock-glm/server.py` | FastAPI: `/v1/models`, `/v1/chat/completions`(스트리밍/비스트리밍), 시나리오 판정, 인증, 요청 로그 |
| `mock-glm/test_server.py` | pytest (TestClient) |
| `mock-glm/requirements.txt` | 핀 고정 의존성 목록 (문서용, 이 PC엔 이미 설치됨) |
| `scripts/mock.sh` | mock 서버 start/stop/status |
| `scripts/verify.sh` | 엔드투엔드 스모크 (mock 기동 → 버전 → 모델 목록 → run → 로그 단정) |
| `scripts/verify_events.py` | `run --format json` 이벤트 단정 |
| `scripts/verify_mocklog.py` | mock 요청 로그 단정 |
| `README.md` | 빠른 시작 |
| `docs/runbook-onprem.md` | 사내 반입·배포·vLLM 설정 런북 |

---

### Task 1: 설정 파일과 래퍼 스크립트

**Files:**
- Create: `config/opencode.json`
- Create: `config/opencode.env`
- Create: `bin/opencode-glm`

**Interfaces:**
- Consumes: 없음
- Produces: `bin/opencode-glm [opencode args...]` — 환경변수 `OPENCODE_GLM_BIN`(기본 `<repo>/.bin/opencode`)의 바이너리를 exec. 바이너리 없으면 exit 1. `OPENCODE_CONFIG`는 항상 `<repo>/config/opencode.json` 절대경로.

- [ ] **Step 1: git 사용자 설정 확인**

```bash
cd /home/mini/github/opencode-glm
git config user.name >/dev/null 2>&1 || git config user.name "mini"
git config user.email >/dev/null 2>&1 || git config user.email "sammynam29@gmail.com"
git log --oneline -1
```
Expected: 최근 커밋 `docs: glm-shim 대응 관계를 결정 사항에 추가`가 보인다.

- [ ] **Step 2: config/opencode.json 작성**

```bash
mkdir -p config bin
cat > config/opencode.json <<'EOF'
{
  "$schema": "https://opencode.ai/config.json",
  "share": "disabled",
  "autoupdate": false,
  "model": "company-glm/glm-5.3-flash",
  "small_model": "company-glm/glm-5.3-flash",
  "enabled_providers": ["company-glm"],
  "provider": {
    "company-glm": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Company GLM (vLLM)",
      "options": {
        "baseURL": "http://127.0.0.1:8000/v1",
        "apiKey": "{env:GLM_API_KEY}",
        "timeout": 600000
      },
      "models": {
        "glm-5.3-flash": {
          "name": "GLM-5.3-Flash (on-prem)",
          "family": "glm",
          "reasoning": true,
          "tool_call": true,
          "attachment": false,
          "temperature": true,
          "interleaved": { "field": "reasoning_content" },
          "limit": { "context": 131072, "output": 32768 },
          "modalities": { "input": ["text"], "output": ["text"] }
        }
      }
    }
  },
  "experimental": {
    "policies": [
      { "effect": "deny", "action": "provider.use", "resource": "*" },
      { "effect": "allow", "action": "provider.use", "resource": "company-glm" }
    ]
  }
}
EOF
python3 -m json.tool config/opencode.json >/dev/null && echo "json ok"
```
Expected: `json ok`.

`enabled_providers`는 스펙의 policies에 더한 보강이다. 스파이크에서 policies만으로는 `opencode models` 목록에 내장 `opencode/*` 무료 모델이 계속 보였고, `enabled_providers: ["company-glm"]`을 추가하면 `company-glm/glm-5.3-flash`만 남는 것을 확인했다.

- [ ] **Step 3: config/opencode.env 작성**

```bash
cat > config/opencode.env <<'EOF'
# bin/opencode-glm 이 `set -a; source` 로 읽는다.
# OPENCODE_CONFIG 는 래퍼가 항상 리포 절대경로로 덮어쓴다 (아래 값은 문서용).
OPENCODE_CONFIG=./config/opencode.json
# 폐쇄망 하드닝: 업데이트 체크(api.github.com), models.dev 갱신, LSP 자동 다운로드 차단
OPENCODE_DISABLE_AUTOUPDATE=1
OPENCODE_DISABLE_MODELS_FETCH=1
OPENCODE_DISABLE_LSP_DOWNLOAD=1
EOF
```

- [ ] **Step 4: bin/opencode-glm 작성**

```bash
cat > bin/opencode-glm <<'EOF'
#!/usr/bin/env bash
# opencode 를 사내 GLM 설정으로 실행하는 래퍼.
# - config/opencode.env 를 로드하고 OPENCODE_CONFIG 를 리포 절대경로로 고정한다.
# - OPENCODE_GLM_BIN (기본 <repo>/.bin/opencode) 을 exec 한다.
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"

if [[ -f "$ROOT/config/opencode.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/config/opencode.env"
  set +a
fi
export OPENCODE_CONFIG="$ROOT/config/opencode.json"

BIN="${OPENCODE_GLM_BIN:-$ROOT/.bin/opencode}"
if [[ ! -x "$BIN" ]]; then
  echo "[opencode-glm] opencode binary not found: $BIN" >&2
  echo "[opencode-glm] run: $ROOT/scripts/install-opencode.sh" >&2
  exit 1
fi

if [[ -z "${GLM_API_KEY:-}" ]]; then
  echo "[opencode-glm] warning: GLM_API_KEY is empty (ok for the mock, required for the real vLLM server)" >&2
fi

exec "$BIN" "$@"
EOF
chmod +x bin/opencode-glm
```

- [ ] **Step 5: 래퍼 동작 검증 (스텁 바이너리)**

```bash
stub="$(mktemp)"
cat > "$stub" <<'EOF'
#!/usr/bin/env bash
echo "OPENCODE_CONFIG=$OPENCODE_CONFIG"
echo "AUTOUPDATE=$OPENCODE_DISABLE_AUTOUPDATE MODELS_FETCH=$OPENCODE_DISABLE_MODELS_FETCH LSP=$OPENCODE_DISABLE_LSP_DOWNLOAD"
echo "args=$*"
EOF
chmod +x "$stub"
OPENCODE_GLM_BIN="$stub" bin/opencode-glm --version 2>/dev/null
echo "--- missing binary ---"
OPENCODE_GLM_BIN=/nonexistent/opencode bin/opencode-glm --version; echo "exit=$?"
rm -f "$stub"
```
Expected:
```
OPENCODE_CONFIG=/home/mini/github/opencode-glm/config/opencode.json
AUTOUPDATE=1 MODELS_FETCH=1 LSP=1
args=--version
--- missing binary ---
[opencode-glm] opencode binary not found: /nonexistent/opencode
[opencode-glm] run: /home/mini/github/opencode-glm/scripts/install-opencode.sh
exit=1
```

- [ ] **Step 6: Commit**

```bash
git add config/opencode.json config/opencode.env bin/opencode-glm
git commit -m "feat: company-glm 프로바이더 설정과 opencode-glm 래퍼 추가

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SSznsrf2rp77wmjcB8kLmL"
```

---

### Task 2: 고정 버전 설치 스크립트

**Files:**
- Create: `scripts/install-opencode.sh`
- Create: `scripts/checksums.txt`

**Interfaces:**
- Consumes: 없음
- Produces: `.bin/opencode` (v1.18.27 실행 파일). `scripts/install-opencode.sh [--offline <tarball>] [--record]`. 종료 코드 0 성공 / 2 플랫폼 미지원 / 3 체크섬 문제 / 4 버전·내용 불일치 / 5 다운로드·파일 문제.

- [ ] **Step 1: checksums.txt 작성**

```bash
mkdir -p scripts
cat > scripts/checksums.txt <<'EOF'
# <sha256>  v<version>/<asset>
# 온라인 PC에서 다운로드 후 `sha256sum` 으로 확인한 값. 다른 자산은 확인 후 --record 로 추가한다.
4af5494f9433f59db8c1e344198f0ee72a50c06ec009fb4a8aeab4c2d4abd702  v1.18.27/opencode-linux-x64.tar.gz
EOF
```

- [ ] **Step 2: install-opencode.sh 작성**

```bash
cat > scripts/install-opencode.sh <<'EOF'
#!/usr/bin/env bash
# opencode 고정 버전 설치.
#   scripts/install-opencode.sh                 # GitHub Releases 에서 다운로드
#   scripts/install-opencode.sh --offline X.tgz # 반입한 tarball 사용 (폐쇄망)
#   scripts/install-opencode.sh --record        # checksums.txt 에 없는 자산의 해시를 기록 (수동 검증 후에만)
# 종료 코드: 0 성공, 2 플랫폼 미지원, 3 체크섬 문제, 4 버전/내용 불일치, 5 다운로드/파일 문제
set -euo pipefail

VERSION="1.18.27"
REPO="anomalyco/opencode"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHECKSUMS="$ROOT/scripts/checksums.txt"
DIST="$ROOT/dist"
BIN_DIR="$ROOT/.bin"

OFFLINE=""
RECORD=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --offline) OFFLINE="${2:-}"; [[ -n "$OFFLINE" ]] || { echo "--offline needs a path" >&2; exit 5; }; shift 2 ;;
    --record) RECORD=1; shift ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

asset_name() {
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"
  [[ "$os" == "Linux" ]] || return 1
  case "$arch" in
    x86_64)
      if grep -q -m1 -w avx2 /proc/cpuinfo; then echo "opencode-linux-x64.tar.gz"; else echo "opencode-linux-x64-baseline.tar.gz"; fi ;;
    aarch64|arm64) echo "opencode-linux-arm64.tar.gz" ;;
    *) return 1 ;;
  esac
}

ASSET="$(asset_name)" || { echo "unsupported platform: $(uname -s) $(uname -m)" >&2; exit 2; }
KEY="v$VERSION/$ASSET"
mkdir -p "$DIST"

if [[ -n "$OFFLINE" ]]; then
  TARBALL="$OFFLINE"
  [[ -f "$TARBALL" ]] || { echo "tarball not found: $TARBALL" >&2; exit 5; }
  echo "using offline tarball: $TARBALL"
else
  TARBALL="$DIST/$ASSET"
  URL="https://github.com/$REPO/releases/download/v$VERSION/$ASSET"
  echo "downloading $URL"
  curl -fL --retry 3 -o "$TARBALL.part" "$URL" || { rm -f "$TARBALL.part"; echo "download failed: $URL" >&2; exit 5; }
  mv -f "$TARBALL.part" "$TARBALL"
fi

ACTUAL="$(sha256sum "$TARBALL" | cut -d' ' -f1)"
EXPECTED="$(grep -E "^[0-9a-f]{64}  $KEY\$" "$CHECKSUMS" 2>/dev/null | head -n1 | cut -d' ' -f1 || true)"
if [[ -z "$EXPECTED" ]]; then
  if [[ $RECORD -eq 1 ]]; then
    echo "$ACTUAL  $KEY" >> "$CHECKSUMS"
    echo "recorded checksum for $KEY"
  else
    echo "no checksum for $KEY in $CHECKSUMS (verify manually, then re-run with --record)" >&2
    exit 3
  fi
elif [[ "$ACTUAL" != "$EXPECTED" ]]; then
  echo "checksum mismatch for $KEY" >&2
  echo "  expected: $EXPECTED" >&2
  echo "  actual:   $ACTUAL" >&2
  exit 3
fi
echo "checksum ok: $ACTUAL"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
tar -xzf "$TARBALL" -C "$TMP"
EXE="$(find "$TMP" -type f -name opencode | head -n1)"
[[ -n "$EXE" ]] || { echo "no 'opencode' executable inside $TARBALL" >&2; exit 4; }
chmod +x "$EXE"

GOT="$(OPENCODE_DISABLE_AUTOUPDATE=1 OPENCODE_DISABLE_MODELS_FETCH=1 "$EXE" --version 2>/dev/null | tail -n1 || true)"
[[ "$GOT" == "$VERSION"* ]] || { echo "version mismatch: expected $VERSION, got '$GOT'" >&2; exit 4; }

mkdir -p "$BIN_DIR"
mv -f "$EXE" "$BIN_DIR/opencode"
echo "installed opencode $GOT -> $BIN_DIR/opencode"
EOF
chmod +x scripts/install-opencode.sh
```

- [ ] **Step 3: 온라인 설치 실행**

```bash
scripts/install-opencode.sh
.bin/opencode --version
bin/opencode-glm --version 2>/dev/null
```
Expected: 마지막 두 줄 모두 `1.18.27`. 다운로드는 약 58MB, 풀린 바이너리는 약 185MB.

- [ ] **Step 4: 체크섬 불일치·오프라인 경로 검증**

```bash
cp scripts/checksums.txt /tmp/claude-1000/-home-mini-github-opencode-glm/25159681-27bc-4e16-bb24-2974c9e887f4/scratchpad/checksums.bak
sed -i 's/^4af5494f/0000000f/' scripts/checksums.txt
scripts/install-opencode.sh --offline dist/opencode-linux-x64.tar.gz; echo "exit=$?"
cp /tmp/claude-1000/-home-mini-github-opencode-glm/25159681-27bc-4e16-bb24-2974c9e887f4/scratchpad/checksums.bak scripts/checksums.txt
scripts/install-opencode.sh --offline dist/opencode-linux-x64.tar.gz; echo "exit=$?"
git diff --stat scripts/checksums.txt
```
Expected: 첫 실행은 `checksum mismatch` 메시지와 `exit=3`. 두 번째는 `installed opencode 1.18.27 -> .../.bin/opencode`와 `exit=0`. `git diff --stat`는 출력 없음(원복 확인).

- [ ] **Step 5: 참고 클론을 v1.18.27로 체크아웃**

```bash
git -C /home/mini/github/opencode status --porcelain | head -3
git -C /home/mini/github/opencode checkout -q v1.18.27
git -C /home/mini/github/opencode describe --tags
```
Expected: `status --porcelain` 출력 없음(변경 없는 클론), 마지막 줄 `v1.18.27`. 출력이 있으면 체크아웃하지 말고 사용자에게 보고한다.

- [ ] **Step 6: Commit**

```bash
git add scripts/install-opencode.sh scripts/checksums.txt
git commit -m "feat: opencode v1.18.27 고정 설치 스크립트와 체크섬 추가

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SSznsrf2rp77wmjcB8kLmL"
```

---

### Task 3: mock GLM 서버 핵심 (모델 목록, 시나리오 판정, 비스트리밍 응답, 로그, 오류)

**Files:**
- Create: `mock-glm/requirements.txt`
- Create: `mock-glm/server.py`
- Test: `mock-glm/test_server.py`

**Interfaces:**
- Consumes: 없음
- Produces (Python 모듈 `server`):
  - 모듈 전역 `MODEL: str`, `API_KEY: str | None`, `LOG_PATH: str`, 상수 `TOOL_OK = "GLM_MOCK_TOOL_OK"`, `DONE = "GLM_MOCK_DONE"`, `TEXT_REPLY = "GLM mock reply"`, `REASONING = ["요청을 확인하기 위해 ", "셸 명령을 실행합니다."]`
  - `classify(messages: list[dict], tools: list | None) -> str` → `"tool_call" | "final" | "text"`
  - `build_reply(scenario: str, messages: list[dict]) -> dict` → `{"reasoning": list[str], "tool_call": dict | None, "text": list[str], "finish": str}` (tool_call은 `{"id": "call_mock_1", "name": "bash", "arguments": '{"command": "echo GLM_MOCK_TOOL_OK"}'}`)
  - `usage_for(messages, reply) -> dict` → `{"prompt_tokens", "completion_tokens", "total_tokens"}`
  - `log_request(entry: dict) -> None` (LOG_PATH에 JSON 한 줄 append, 디렉터리 자동 생성)
  - FastAPI `app`: `GET /v1/models`, `POST /v1/chat/completions` (이 태스크는 `stream: false`만)

- [ ] **Step 1: requirements.txt 작성**

```bash
mkdir -p mock-glm
cat > mock-glm/requirements.txt <<'EOF'
# 이 PC의 시스템 Python 3.10 에 이미 설치된 버전. 새 환경이면: pip install -r requirements.txt
fastapi==0.139.0
uvicorn==0.50.0
httpx==0.28.1
pytest==9.0.2
EOF
```

- [ ] **Step 2: 실패하는 테스트 작성**

```bash
cat > mock-glm/test_server.py <<'EOF'
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
EOF
```

- [ ] **Step 3: 테스트가 실패하는지 확인**

```bash
cd mock-glm && python3 -m pytest test_server.py -q 2>&1 | tail -3; cd ..
```
Expected: `ModuleNotFoundError: No module named 'server'` 로 수집 단계에서 실패.

- [ ] **Step 4: server.py 구현 (비스트리밍)**

```bash
cat > mock-glm/server.py <<'EOF'
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
EOF
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
cd mock-glm && python3 -m pytest test_server.py -q 2>&1 | tail -3; cd ..
```
Expected: `9 passed`.

- [ ] **Step 6: Commit**

```bash
git add mock-glm/requirements.txt mock-glm/server.py mock-glm/test_server.py
git commit -m "feat: vLLM 호환 mock GLM 서버 (비스트리밍, 시나리오, 로그)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SSznsrf2rp77wmjcB8kLmL"
```

---

### Task 4: mock 서버 스트리밍(SSE)과 API 키 인증

**Files:**
- Modify: `mock-glm/server.py` (`chat_completions` 끝부분과 새 함수 `stream_response`)
- Test: `mock-glm/test_server.py` (테스트 추가)

**Interfaces:**
- Consumes: Task 3의 `build_reply`, `usage_for`, `_next_id`, `MODEL`, `API_KEY`
- Produces: `stream_response(reply: dict, usage: dict, include_usage: bool) -> Iterator[str]` — SSE 라인(`data: {...}\n\n`) 제너레이터. `POST /v1/chat/completions`가 `stream: true`면 `text/event-stream`으로 응답. `API_KEY` 설정 시 `Authorization: Bearer <key>` 불일치는 401.

- [ ] **Step 1: 실패하는 테스트 추가**

```bash
cat >> mock-glm/test_server.py <<'EOF'


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
EOF
```

- [ ] **Step 2: 새 테스트가 실패하는지 확인**

```bash
cd mock-glm && python3 -m pytest test_server.py -q 2>&1 | tail -5; cd ..
```
Expected: 스트리밍 테스트 4개가 실패(비스트리밍 JSON이 돌아와 `content-type` 또는 `events[-1]` 단정 실패). 인증 테스트 2개는 Task 3 코드로 이미 통과할 수 있다.

- [ ] **Step 3: 스트리밍 구현**

`mock-glm/server.py`에서 `from fastapi.responses import JSONResponse` 를 아래로 바꾼다:

```python
from fastapi.responses import JSONResponse, StreamingResponse
```

`completion_json` 함수 바로 아래에 추가한다:

```python
def _sse(obj: dict) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def stream_response(reply: dict, usage: dict, include_usage: bool):
    cid = _next_id()
    created = int(time.time())

    def chunk(delta: dict, finish: str | None = None) -> dict:
        return {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": MODEL,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }

    yield _sse(chunk({"role": "assistant", "content": ""}))
    for piece in reply["reasoning"]:
        yield _sse(chunk({"reasoning_content": piece}))
    if reply["tool_call"]:
        tc = reply["tool_call"]
        yield _sse(chunk({"tool_calls": [{"index": 0, "id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": ""}}]}))
        yield _sse(chunk({"tool_calls": [{"index": 0, "function": {"arguments": tc["arguments"]}}]}))
    for piece in reply["text"]:
        yield _sse(chunk({"content": piece}))
    yield _sse(chunk({}, reply["finish"]))
    if include_usage:
        yield _sse({"id": cid, "object": "chat.completion.chunk", "created": created, "model": MODEL, "choices": [], "usage": usage})
    yield "data: [DONE]\n\n"
```

`chat_completions` 의 마지막 줄 `return JSONResponse(completion_json(reply, usage))` 를 아래로 바꾼다:

```python
    if stream:
        include_usage = bool((payload.get("stream_options") or {}).get("include_usage"))
        return StreamingResponse(stream_response(reply, usage, include_usage), media_type="text/event-stream")
    return JSONResponse(completion_json(reply, usage))
```

적용 명령(정확한 문자열 치환):

```bash
python3 - <<'EOF'
p = "mock-glm/server.py"
s = open(p, encoding="utf-8").read()
s = s.replace("from fastapi.responses import JSONResponse\n", "from fastapi.responses import JSONResponse, StreamingResponse\n", 1)
stream_fn = '''

def _sse(obj: dict) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\\n\\n"


def stream_response(reply: dict, usage: dict, include_usage: bool):
    cid = _next_id()
    created = int(time.time())

    def chunk(delta: dict, finish: str | None = None) -> dict:
        return {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": MODEL,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }

    yield _sse(chunk({"role": "assistant", "content": ""}))
    for piece in reply["reasoning"]:
        yield _sse(chunk({"reasoning_content": piece}))
    if reply["tool_call"]:
        tc = reply["tool_call"]
        yield _sse(chunk({"tool_calls": [{"index": 0, "id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": ""}}]}))
        yield _sse(chunk({"tool_calls": [{"index": 0, "function": {"arguments": tc["arguments"]}}]}))
    for piece in reply["text"]:
        yield _sse(chunk({"content": piece}))
    yield _sse(chunk({}, reply["finish"]))
    if include_usage:
        yield _sse({"id": cid, "object": "chat.completion.chunk", "created": created, "model": MODEL, "choices": [], "usage": usage})
    yield "data: [DONE]\\n\\n"
'''
anchor = '\n\n@app.get("/v1/models")'
assert anchor in s
s = s.replace(anchor, stream_fn + anchor, 1)
old_ret = "    return JSONResponse(completion_json(reply, usage))\n"
new_ret = '''    if stream:
        include_usage = bool((payload.get("stream_options") or {}).get("include_usage"))
        return StreamingResponse(stream_response(reply, usage, include_usage), media_type="text/event-stream")
    return JSONResponse(completion_json(reply, usage))
'''
assert old_ret in s
s = s.replace(old_ret, new_ret, 1)
open(p, "w", encoding="utf-8").write(s)
print("patched")
EOF
```

- [ ] **Step 4: 전체 테스트 통과 확인**

```bash
cd mock-glm && python3 -m pytest test_server.py -q 2>&1 | tail -3; cd ..
```
Expected: `15 passed`.

- [ ] **Step 5: 실제 uvicorn으로 SSE 육안 확인**

```bash
( cd mock-glm && MOCK_LOG=/tmp/claude-1000/-home-mini-github-opencode-glm/25159681-27bc-4e16-bb24-2974c9e887f4/scratchpad/req.jsonl python3 -m uvicorn server:app --host 127.0.0.1 --port 8000 >/dev/null 2>&1 & echo $! > /tmp/claude-1000/-home-mini-github-opencode-glm/25159681-27bc-4e16-bb24-2974c9e887f4/scratchpad/uv.pid )
sleep 2
curl -sN http://127.0.0.1:8000/v1/chat/completions -H 'content-type: application/json' -d '{"model":"glm-5.3-flash","stream":true,"stream_options":{"include_usage":true},"messages":[{"role":"user","content":"hi"}],"tools":[{"type":"function","function":{"name":"bash","parameters":{"type":"object"}}}]}' | head -c 1200
kill "$(cat /tmp/claude-1000/-home-mini-github-opencode-glm/25159681-27bc-4e16-bb24-2974c9e887f4/scratchpad/uv.pid)"
```
Expected: `data: {"id":"chatcmpl-mock-1",...` 로 시작하는 청크들이 순서대로 출력되고 `data: [DONE]` 으로 끝난다.

- [ ] **Step 6: Commit**

```bash
git add mock-glm/server.py mock-glm/test_server.py
git commit -m "feat: mock GLM 서버 SSE 스트리밍과 API 키 인증

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SSznsrf2rp77wmjcB8kLmL"
```

---

### Task 5: mock 서버 제어 스크립트

**Files:**
- Create: `scripts/mock.sh`

**Interfaces:**
- Consumes: `mock-glm/server.py` (uvicorn 앱 `server:app`)
- Produces: `scripts/mock.sh start|stop|status`. `start`는 헬스체크 통과 시 exit 0(이미 떠 있어도 0), 15초 내 실패 시 exit 1. PID는 `logs/mock.pid`, 서버 출력은 `logs/mock.log`, 요청 로그는 `logs/requests.jsonl`(환경변수 `MOCK_LOG`로 변경 가능). 포트는 `MOCK_PORT`(기본 8000).

- [ ] **Step 1: mock.sh 작성**

```bash
cat > scripts/mock.sh <<'EOF'
#!/usr/bin/env bash
# mock GLM 서버 제어: scripts/mock.sh start|stop|status
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${MOCK_PORT:-8000}"
LOG_DIR="$ROOT/logs"
PID_FILE="$LOG_DIR/mock.pid"
LOG_FILE="$LOG_DIR/mock.log"
REQ_LOG="${MOCK_LOG:-$LOG_DIR/requests.jsonl}"
URL="http://127.0.0.1:$PORT/v1/models"
mkdir -p "$LOG_DIR"

healthy() { curl -fsS -m 2 "$URL" >/dev/null 2>&1; }

case "${1:-}" in
  start)
    if healthy; then echo "mock already running on :$PORT"; exit 0; fi
    (
      cd "$ROOT/mock-glm"
      MOCK_PORT="$PORT" MOCK_LOG="$REQ_LOG" nohup python3 -m uvicorn server:app --host 127.0.0.1 --port "$PORT" >"$LOG_FILE" 2>&1 &
      echo $! > "$PID_FILE"
    )
    for _ in $(seq 1 30); do
      if healthy; then echo "mock up on :$PORT (pid $(cat "$PID_FILE"), log $LOG_FILE)"; exit 0; fi
      sleep 0.5
    done
    echo "mock failed to start within 15s; see $LOG_FILE" >&2
    exit 1
    ;;
  stop)
    if [[ -f "$PID_FILE" ]]; then
      kill "$(cat "$PID_FILE")" 2>/dev/null || true
      rm -f "$PID_FILE"
      echo "mock stopped"
    else
      echo "no pid file ($PID_FILE); nothing to stop"
    fi
    ;;
  status)
    if healthy; then echo "mock healthy on :$PORT"; else echo "mock not responding on :$PORT"; exit 1; fi
    ;;
  *)
    echo "usage: $0 start|stop|status" >&2
    exit 2
    ;;
esac
EOF
chmod +x scripts/mock.sh
```

- [ ] **Step 2: 기동·상태·중지 검증**

```bash
scripts/mock.sh start
scripts/mock.sh start
scripts/mock.sh status
curl -s http://127.0.0.1:8000/v1/models
echo
scripts/mock.sh stop
scripts/mock.sh status; echo "exit=$?"
```
Expected:
```
mock up on :8000 (pid <n>, log /home/mini/github/opencode-glm/logs/mock.log)
mock already running on :8000
mock healthy on :8000
{"object":"list","data":[{"id":"glm-5.3-flash","object":"model","owned_by":"vllm"}]}
mock stopped
mock not responding on :8000
exit=1
```

- [ ] **Step 3: Commit**

```bash
git add scripts/mock.sh
git commit -m "feat: mock 서버 start/stop/status 스크립트

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SSznsrf2rp77wmjcB8kLmL"
```

---

### Task 6: 엔드투엔드 검증 스크립트

**Files:**
- Create: `scripts/verify_events.py`
- Create: `scripts/verify_mocklog.py`
- Create: `scripts/verify.sh`

**Interfaces:**
- Consumes: `bin/opencode-glm`, `scripts/mock.sh`, `.bin/opencode`, mock 로그 형식(Task 3 `log_request` 엔트리 키: `scenario`, `stream`, `tool_names`, `params`)
- Produces: `scripts/verify.sh [--live]` → 성공 시 stdout `VERIFY OK`, exit 0. 실패 시 stderr `VERIFY FAIL [<단계번호>]: <이유>`, exit 1. `scripts/verify_events.py <jsonl> [--live]`, `scripts/verify_mocklog.py <jsonl> <이전 줄 수>` 는 각각 문제 없으면 exit 0.

`opencode run --format json` 이벤트 형식(`packages/opencode/src/cli/cmd/run.ts` 기준): 한 줄에 하나의 JSON `{"type": "tool_use"|"text"|"reasoning"|"step_start"|"step_finish"|"error", "timestamp", "sessionID", "part": {...}}`. `tool_use`의 `part.tool`은 도구 이름, `part.state.status`는 `completed|error`, 출력은 `part.state.output`(문자열). `text`의 본문은 `part.text`.

- [ ] **Step 1: verify_events.py 작성**

```bash
cat > scripts/verify_events.py <<'EOF'
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
EOF
chmod +x scripts/verify_events.py
```

- [ ] **Step 2: verify_mocklog.py 작성**

```bash
cat > scripts/verify_mocklog.py <<'EOF'
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
EOF
chmod +x scripts/verify_mocklog.py
```

- [ ] **Step 3: verify.sh 작성**

```bash
cat > scripts/verify.sh <<'EOF'
#!/usr/bin/env bash
# 엔드투엔드 스모크: mock 기동 -> 버전 -> 모델 목록 -> opencode run(tool call) -> 로그 단정
#   scripts/verify.sh          # mock 대상
#   scripts/verify.sh --live   # config/opencode.json 의 실서버 대상 (mock 단정 생략)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIVE=0
[[ "${1:-}" == "--live" ]] && LIVE=1
MODEL="company-glm/glm-5.3-flash"
EXPECTED_VERSION="1.18.27"
LOG_DIR="$ROOT/logs"
REQ_LOG="$LOG_DIR/requests.jsonl"
OC_LOG="${XDG_DATA_HOME:-$HOME/.local/share}/opencode/log/opencode.log"
mkdir -p "$LOG_DIR"

fail() { echo "VERIFY FAIL [$1]: $2" >&2; exit 1; }
count_lines() { if [[ -f "$1" ]]; then wc -l < "$1"; else echo 0; fi; }

# 1. mock
if [[ $LIVE -eq 0 ]]; then
  "$ROOT/scripts/mock.sh" start || fail 1 "mock did not start"
  trap '"$ROOT/scripts/mock.sh" stop >/dev/null 2>&1 || true' EXIT
fi

# 2. version
VERSION="$("$ROOT/bin/opencode-glm" --version 2>/dev/null | tail -n1 || true)"
[[ "$VERSION" == "$EXPECTED_VERSION"* ]] || fail 2 "opencode version is '$VERSION', expected $EXPECTED_VERSION"
echo "version ok: $VERSION"

# 3. model listing
"$ROOT/bin/opencode-glm" models company-glm 2>/dev/null | grep -qx "$MODEL" || fail 3 "$MODEL not listed by 'opencode models company-glm'"
echo "model listed: $MODEL"

# markers for incremental log checks
REQ_BEFORE="$(count_lines "$REQ_LOG")"
OC_BEFORE="$(count_lines "$OC_LOG")"

# 4. run
WORK="$(mktemp -d)"
PROMPT="smoke test"
[[ $LIVE -eq 1 ]] && PROMPT="현재 디렉터리 파일 목록을 셸 명령으로 확인하고 한 줄로 요약해줘"
RUN_OUT="$LOG_DIR/verify-run.jsonl"
RUN_ERR="$LOG_DIR/verify-run.stderr"
set +e
( cd "$WORK" && timeout 180 "$ROOT/bin/opencode-glm" run --format json --model "$MODEL" "$PROMPT" ) >"$RUN_OUT" 2>"$RUN_ERR"
RUN_RC=$?
set -e
rm -rf "$WORK"
[[ $RUN_RC -eq 0 ]] || fail 4 "opencode run exited $RUN_RC (see $RUN_ERR and $RUN_OUT)"
if [[ $LIVE -eq 1 ]]; then
  python3 "$ROOT/scripts/verify_events.py" "$RUN_OUT" --live || fail 4 "event assertions (see $RUN_OUT)"
else
  python3 "$ROOT/scripts/verify_events.py" "$RUN_OUT" || fail 4 "event assertions (see $RUN_OUT)"
fi

# 5. mock request log
if [[ $LIVE -eq 0 ]]; then
  python3 "$ROOT/scripts/verify_mocklog.py" "$REQ_LOG" "$REQ_BEFORE" || fail 5 "mock request log assertions (see $REQ_LOG)"
fi

# 6. no models.dev fetch attempt in opencode log (this run only)
if [[ -f "$OC_LOG" ]]; then
  if tail -n +"$((OC_BEFORE + 1))" "$OC_LOG" | grep -q "Failed to fetch models.dev"; then
    fail 6 "opencode tried to fetch models.dev (offline flags not applied?)"
  fi
fi
echo "offline ok: no models.dev fetch in $OC_LOG"

echo "VERIFY OK"
EOF
chmod +x scripts/verify.sh
```

- [ ] **Step 4: 단정 스크립트 단위 확인 (가짜 입력)**

```bash
S=/tmp/claude-1000/-home-mini-github-opencode-glm/25159681-27bc-4e16-bb24-2974c9e887f4/scratchpad
cat > "$S/ev-good.jsonl" <<'EOF'
{"type":"step_start","part":{"type":"step-start"}}
{"type":"tool_use","part":{"type":"tool","tool":"bash","state":{"status":"completed","input":{"command":"echo GLM_MOCK_TOOL_OK"},"output":"GLM_MOCK_TOOL_OK\n"}}}
{"type":"text","part":{"type":"text","text":"도구 실행 결과: GLM_MOCK_TOOL_OK\nGLM_MOCK_DONE"}}
EOF
cat > "$S/ev-bad.jsonl" <<'EOF'
{"type":"error","error":{"name":"ProviderError","data":{"message":"boom"}}}
EOF
python3 scripts/verify_events.py "$S/ev-good.jsonl"; echo "exit=$?"
python3 scripts/verify_events.py "$S/ev-bad.jsonl"; echo "exit=$?"
cat > "$S/req.jsonl" <<'EOF'
{"scenario":"text","stream":true,"tool_names":[],"params":{"model":"glm-5.3-flash"}}
{"scenario":"tool_call","stream":true,"tool_names":["bash","read"],"params":{"model":"glm-5.3-flash","stream_options":{"include_usage":true}}}
{"scenario":"final","stream":true,"tool_names":["bash"],"params":{"model":"glm-5.3-flash","stream_options":{"include_usage":true}}}
EOF
python3 scripts/verify_mocklog.py "$S/req.jsonl" 0; echo "exit=$?"
python3 scripts/verify_mocklog.py "$S/req.jsonl" 2; echo "exit=$?"
```
Expected: `events ok: 1 tool_use, 1 text, 3 total` / `exit=0`; 그다음 `events: error event: ...`, `events: no completed bash tool_use ...` 등과 `exit=1`; `mocklog ok: 3 requests this run (1 tool_call, 1 final)` / `exit=0`; 마지막은 `mocklog: no tool_call request logged` / `exit=1`.

- [ ] **Step 5: 실제 엔드투엔드 실행**

```bash
scripts/verify.sh; echo "exit=$?"
```
Expected 출력 예:
```
mock up on :8000 (pid ..., log .../logs/mock.log)
version ok: 1.18.27
model listed: company-glm/glm-5.3-flash
events ok: 1 tool_use, 1 text, N total
mocklog ok: 3 requests this run (1 tool_call, 1 final)
offline ok: no models.dev fetch in /home/mini/.local/share/opencode/log/opencode.log
VERIFY OK
exit=0
```
(`tool_use`/요청 수는 세션 제목 생성 요청이 섞여 달라질 수 있다. `requests.jsonl`에 `scenario: text` 요청이 하나 더 있는 것은 정상.)

실패 시 확인 순서:
1. `logs/verify-run.stderr` — opencode 자체 오류(권한 자동 거절 메시지 `permission requested: ... auto-rejecting`가 있으면 `config/opencode.json`에 `"permission": {"bash": "allow"}`를 추가하지 말고, 먼저 왜 ask가 됐는지 `bin/opencode-glm debug config`로 확인한다).
2. `logs/verify-run.jsonl` — `error` 이벤트의 `data.message`.
3. `logs/requests.jsonl` — mock에 요청이 도달했는지, `params`에 이상한 키가 있는지.
4. `logs/mock.log` — uvicorn 예외.
5. 이벤트 필드명이 예상과 다르면(`part.state.output`이 없고 `part.state.content`만 있는 등) `verify_events.py`의 `output_text`가 이미 두 형태를 처리하므로, 그 외 차이만 `run.ts` 기준으로 맞춘다.

- [ ] **Step 6: Commit**

```bash
git add scripts/verify.sh scripts/verify_events.py scripts/verify_mocklog.py
git commit -m "feat: 엔드투엔드 검증 스크립트 (mock → opencode run → 로그 단정)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SSznsrf2rp77wmjcB8kLmL"
```

---

### Task 7: README와 사내 배포 런북

**Files:**
- Create: `README.md`
- Create: `docs/runbook-onprem.md`
- Modify: `docs/superpowers/specs/2026-09-03-opencode-glm-design.md` (5.3절에 `enabled_providers` 반영)

**Interfaces:**
- Consumes: Task 1~6의 명령과 파일 경로
- Produces: 문서만

- [ ] **Step 1: README.md 작성**

```bash
cat > README.md <<'EOF'
# opencode-glm

opencode(v1.18.27 고정)를 사내 GLM(vLLM) 서버에 연결해 쓰기 위한 설정·검증 리포.
실서버가 없는 환경에서는 `mock-glm/`의 vLLM 호환 mock 서버로 배관을 검증한다.

## 빠른 시작

```bash
scripts/install-opencode.sh        # GitHub Releases 에서 v1.18.27 다운로드·검증·설치 (.bin/opencode)
scripts/verify.sh                  # mock 기동 → opencode run 으로 tool call 흐름 자동 검증 → VERIFY OK
scripts/mock.sh start              # 대화형으로 써 보려면 mock 을 띄우고
bin/opencode-glm                   # TUI 실행 (모델: company-glm/glm-5.3-flash)
scripts/mock.sh stop
```

폐쇄망에서는 반입한 tarball 로 설치한다: `scripts/install-opencode.sh --offline /path/opencode-linux-x64.tar.gz`

## 구성

| 경로 | 역할 |
|---|---|
| `bin/opencode-glm` | 래퍼. `config/opencode.env` 로드 → `OPENCODE_CONFIG=config/opencode.json` → `.bin/opencode` 실행 |
| `config/opencode.json` | `company-glm` custom provider(OpenAI 호환), 기본 모델, share/autoupdate 끔, provider allow-list |
| `config/opencode.env` | `OPENCODE_DISABLE_AUTOUPDATE/MODELS_FETCH/LSP_DOWNLOAD=1` (폐쇄망 하드닝) |
| `scripts/install-opencode.sh` | 고정 버전 설치. `scripts/checksums.txt` 와 sha256 대조, `--version` 확인 |
| `scripts/mock.sh` | mock 서버 start/stop/status (`MOCK_PORT`, 기본 8000) |
| `scripts/verify.sh` | 엔드투엔드 스모크. `--live` 는 실서버용 |
| `mock-glm/server.py` | FastAPI mock. `/v1/models`, `/v1/chat/completions`(SSE). 요청은 `logs/requests.jsonl` 에 기록 |
| `docs/runbook-onprem.md` | 사내 반입·배포·vLLM 플래그 런북 |

## 실서버로 전환

1. `config/opencode.json` 의 `options.baseURL` 을 vLLM 주소(`http://<host>:<port>/v1`)로 바꾼다.
2. vLLM 이 `--api-key` 를 쓰면 `export GLM_API_KEY=...` (설정의 `{env:GLM_API_KEY}` 로 주입된다).
3. `models` 키(`glm-5.3-flash`)는 vLLM `--served-model-name` 과 같아야 한다. `limit.context/output` 은 `--max-model-len` 에 맞춘다.
4. `scripts/verify.sh --live` 로 확인한다.

## 개발

```bash
cd mock-glm && python3 -m pytest -q      # mock 서버 테스트
```

의존성은 `mock-glm/requirements.txt` (이 PC의 시스템 Python 3.10 에 이미 설치돼 있음).

## 왜 shim 이 없나

Claude Code 용 glm-shim 은 Anthropic 형식만 말하는 Claude Code 에 환경변수를 맞춰 주는 설정 래퍼였다.
opencode 는 OpenAI 호환 API 를 직접 말하므로 변환 계층이 필요 없고, 같은 역할은 `bin/opencode-glm` + `config/` 가 한다.
설계 근거는 `docs/superpowers/specs/2026-09-03-opencode-glm-design.md` 참고.
EOF
```

- [ ] **Step 2: docs/runbook-onprem.md 작성**

```bash
cat > docs/runbook-onprem.md <<'EOF'
# 사내(폐쇄망) 배포 런북: opencode ↔ GLM(vLLM)

대상: 개발자 PC/공용 서버(Linux x86_64)에 opencode v1.18.27 을 설치해 사내 vLLM GLM 에 연결한다.

## 1. 반입 목록

온라인 PC에서 준비해 승인된 경로로 반입한다.

| 항목 | 출처 | 비고 |
|---|---|---|
| `opencode-linux-x64.tar.gz` | `https://github.com/anomalyco/opencode/releases/download/v1.18.27/` | AVX2 없는 CPU면 `opencode-linux-x64-baseline.tar.gz`, ARM 이면 `opencode-linux-arm64.tar.gz` |
| `scripts/checksums.txt` | 이 리포 | 반입 전 온라인 PC에서 `sha256sum` 으로 값을 재확인한다 |
| 이 리포 전체 | `git archive -o opencode-glm.tar HEAD` | 설정·스크립트·문서 |

x64 자산의 sha256: `4af5494f9433f59db8c1e344198f0ee72a50c06ec009fb4a8aeab4c2d4abd702`

## 2. 설치

```bash
tar xf opencode-glm.tar && cd opencode-glm
scripts/install-opencode.sh --offline /path/to/opencode-linux-x64.tar.gz   # 체크섬·버전 검증 후 .bin/opencode
sudo install -m 0755 .bin/opencode /usr/local/bin/opencode                 # 시스템 전체 설치 (선택)
```

`checksums.txt` 에 없는 자산(baseline/arm64)은 온라인 PC에서 해시를 확인한 뒤 `--record` 로 추가하고 커밋한다.

## 3. 관리 설정 (사용자 override 불가)

`config/opencode.json` 을 그대로 `/etc/opencode/opencode.json` 에 둔다. Linux 관리 설정 디렉터리는 `/etc/opencode/` 이며 최상위 우선순위로 적용된다.

```bash
sudo mkdir -p /etc/opencode
sudo cp config/opencode.json /etc/opencode/opencode.json
sudo chown root:root /etc/opencode/opencode.json && sudo chmod 0644 /etc/opencode/opencode.json
```

배포 전에 고칠 값:
- `provider.company-glm.options.baseURL`: `http://<vllm-host>:<port>/v1`
- `provider.company-glm.models.glm-5.3-flash.limit`: vLLM `--max-model-len` 에 맞춰 `context`, 출력 상한은 `output`
- 모델 키 이름: vLLM `--served-model-name` 과 동일해야 한다

설정 확인: `opencode debug config` (관리 설정이 최종 값에 반영됐는지 본다).

## 4. 환경변수

`/etc/profile.d/opencode.sh`:

```bash
export OPENCODE_DISABLE_AUTOUPDATE=1
export OPENCODE_DISABLE_MODELS_FETCH=1
export OPENCODE_DISABLE_LSP_DOWNLOAD=1
# vLLM 을 --api-key 로 띄웠다면 개인별 키를 각자 셸 프로필에서 export 한다:
# export GLM_API_KEY=...
```

관리 설정을 쓰면 `OPENCODE_CONFIG` 는 필요 없다(래퍼 없이 `opencode` 를 바로 실행).

## 5. 네트워크

- 사내 CA: `export NODE_EXTRA_CA_CERTS=/etc/ssl/certs/company-ca.pem`
- 프록시가 있으면 `HTTPS_PROXY` 를 쓰되 로컬 서버와 vLLM 은 제외: `export NO_PROXY=localhost,127.0.0.1,<vllm-host>`
- 차단해도 되는 외부 호스트(오프라인 플래그로 호출 자체를 막는다): `api.github.com`(업데이트 체크), `models.opencode.ai`(모델 카탈로그 갱신), `github.com`/`registry.npmjs.org`(LSP·플러그인 다운로드), `opncd.ai`(share, 설정에서 disabled)

## 6. vLLM 서버 플래그 (공식 레시피 기준)

| 모델 | `--tool-call-parser` | `--reasoning-parser` | 추가 플래그 |
|---|---|---|---|
| GLM-4.5 / 4.5-Air / 4.6 | `glm45` | `glm45` | `--enable-auto-tool-choice` |
| GLM-4.7 / 4.7-Flash | `glm47` | `glm45` | `--enable-auto-tool-choice` |
| GLM-5 / 5.1 / 5.x (5.3-flash 포함) | `glm47` | `glm45` | `--enable-auto-tool-choice --chat-template-content-format=string` |

예:

```bash
vllm serve zai-org/GLM-5.3-Flash \
  --served-model-name glm-5.3-flash \
  --tool-call-parser glm47 --reasoning-parser glm45 --enable-auto-tool-choice \
  --chat-template-content-format=string \
  --max-model-len 131072
```

- 5.3 은 배포 시점 vLLM 버전의 `vllm serve --help` 에서 파서 이름을 재확인한다.
- thinking 은 vLLM 기본 on. 끄려면 `opencode.json` 의 모델에 `"options": {"chat_template_kwargs": {"enable_thinking": false}}` 를 넣는다(모델 options 는 요청 본문에 그대로 합쳐진다).
- tool calling 이 안 되면 먼저 `--enable-auto-tool-choice` 와 파서 플래그 누락을 의심한다.

## 7. 검증

```bash
scripts/verify.sh --live      # 실서버: tool call 1회 이상 + 텍스트 응답 + 오류 없음
opencode models company-glm   # company-glm/glm-5.3-flash 만 보여야 한다
```

문제 시: `~/.local/share/opencode/log/opencode.log`, `opencode debug config`.

## 8. 버전 업데이트 절차

1. 후보 태그 선정 기준: 릴리스 노트가 bugfix-only, 태그 후 1주 이상 회귀 보고 없음, OpenAI 호환 프로바이더 관련 수정이 있으면 우선.
2. 온라인 PC: 새 tarball 다운로드 → `sha256sum` → `scripts/install-opencode.sh` 의 `VERSION` 과 `scripts/checksums.txt` 갱신 → `scripts/verify.sh`(mock) 통과 확인 → 커밋.
3. 반입 후 `--offline` 설치 → `scripts/verify.sh --live` → `/usr/local/bin/opencode` 교체.
EOF
```

- [ ] **Step 3: 스펙 5.3절에 enabled_providers 반영**

```bash
python3 - <<'EOF'
p = "docs/superpowers/specs/2026-09-03-opencode-glm-design.md"
s = open(p, encoding="utf-8").read()
old = '  "small_model": "company-glm/glm-5.3-flash",\n  "provider": {'
new = '  "small_model": "company-glm/glm-5.3-flash",\n  "enabled_providers": ["company-glm"],\n  "provider": {'
assert old in s
s = s.replace(old, new, 1)
old2 = "- `experimental.policies`는 전 프로바이더 deny 후 `company-glm`만 allow. 사내 계정에 다른 클라우드 자격증명이 있어도 사용 불가."
new2 = old2 + "\n- `enabled_providers: [\"company-glm\"]`를 함께 둔다. 스파이크에서 policies만으로는 `opencode models` 목록에 내장 `opencode/*` 무료 모델이 남았고, allow-list를 추가하면 `company-glm`만 남는 것을 확인했다."
assert old2 in s
s = s.replace(old2, new2, 1)
open(p, "w", encoding="utf-8").write(s)
print("spec patched")
EOF
```

- [ ] **Step 4: 문서 링크·명령 점검**

```bash
grep -n "scripts/verify.sh\|install-opencode.sh\|mock.sh" README.md docs/runbook-onprem.md | wc -l
ls scripts/verify.sh scripts/install-opencode.sh scripts/mock.sh bin/opencode-glm
git status --short
```
Expected: 첫 줄은 0보다 큰 수, `ls`는 네 파일 모두 존재, `git status`에는 `README.md`, `docs/runbook-onprem.md`, 스펙 수정만 보인다.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/runbook-onprem.md docs/superpowers/specs/2026-09-03-opencode-glm-design.md
git commit -m "docs: README와 사내 배포 런북 추가, 스펙에 enabled_providers 반영

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SSznsrf2rp77wmjcB8kLmL"
git log --oneline
```
