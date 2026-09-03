# opencode ↔ 사내 GLM(vLLM) 연결 설계

- 작성일: 2026-09-03
- 상태: 승인됨 (사용자 승인 후 구현 플랜 작성 단계)
- 대상 리포: `/home/mini/github/opencode-glm`
- 참고 클론: `/home/mini/github/opencode` (읽기 전용, `v1.18.27` 체크아웃)

## 1. 배경과 목적

사내 GPU에 vLLM으로 띄운 GLM 모델을 opencode(오픈소스 AI 코딩 에이전트)에 연결해 쓰려 한다.
실서버(vLLM GLM)는 아직 없으므로, 이 PC에서 **vLLM 호환 mock 서버**를 두고
opencode의 설치·버전 고정·프로바이더 설정·tool calling 배관·폐쇄망 하드닝을 먼저 검증한다.
검증이 끝나면 같은 설정 파일을 사내 배포(관리 설정)에 그대로 쓴다.

## 2. 범위

포함:
- opencode 안정 버전 선정과 고정 설치 (`v1.18.27`)
- custom provider(`company-glm`) 설정과 폐쇄망 하드닝 설정
- vLLM 호환 mock GLM 서버 (결정론적 시나리오)
- 엔드투엔드 스모크 검증 스크립트
- 사내 반입·배포·vLLM 설정 런북

제외:
- 실제 vLLM/GLM 모델 구동 (이 PC에 GPU 없음)
- opencode 소스 수정·빌드 (필요해지면 별도 작업)
- 팀 전체 배포 실행 (런북 문서화까지만)
- 데스크톱 앱, 웹 UI, share 기능

## 3. 결정 사항

| 항목 | 결정 | 근거 |
|---|---|---|
| opencode 버전 | `v1.18.27` (2026-09-02 태그) | 1.18.20 이후 bugfix-only 라인. 프로바이더 헤더/청크 타임아웃 기본 5분, SSE 취소 오류 수정, 1.18.22의 OpenAI 호환 서버 `textVerbosity` 오전송 수정 포함. 태그 이후 dev 커밋 6개는 데스크톱 UI뿐 |
| 바이너리 확보 | GitHub Releases prebuilt `opencode-linux-x64.tar.gz` | bun 불필요, 공식과 동일 바이너리, 폐쇄망 반입 파일 하나. 이 PC는 x86_64 / glibc 2.35 / AVX2 |
| 클론 브랜치 | `dev` 대신 `v1.18.27` 태그 체크아웃, 빌드 안 함 | 참고용. `2.0` 브랜치는 4,529커밋 뒤처진 실험 브랜치라 제외 |
| provider ID | `company-glm` | opencode는 provider ID에 `zai`/`zhipuai`가 포함되면 Z.AI 클라우드 전용 `thinking: {type: enabled, clear_thinking: false}`를 요청 본문에 주입함 (`packages/opencode/src/provider/transform.ts`). vLLM에는 불필요하므로 회피 |
| SDK | `@ai-sdk/openai-compatible` (바이너리에 번들됨, 런타임 npm 설치 없음) | `/v1/chat/completions` 사용. `reasoning_content` 델타 파싱 지원 |
| mock 방식 | Python FastAPI 스크립트 mock | 시스템 Python 3.10에 FastAPI/uvicorn/pytest/httpx 기설치. 결정론적이라 자동 검증 가능 |
| mock 모델명 | `glm-4.7` | open weights 모델. opencode가 `glm-4.7`에 temperature 1.0을 자동 적용하는 것 외 특수 처리 없음 |

## 4. 디렉터리 구조

```
opencode-glm/
├── bin/opencode-glm            # 래퍼: env 로드 + 고정 바이너리 exec
├── scripts/
│   ├── install-opencode.sh     # tarball 다운로드/검증/설치, --offline 지원
│   ├── checksums.txt           # "<sha256>  <asset 파일명>" (버전별 고정값)
│   ├── mock.sh                 # mock 서버 start/stop/status
│   └── verify.sh               # 엔드투엔드 스모크 테스트
├── config/
│   ├── opencode.json           # provider + 하드닝 설정 (사내 /etc/opencode 용과 동일)
│   └── opencode.env            # OPENCODE_DISABLE_* 등 환경변수
├── mock-glm/
│   ├── server.py               # FastAPI, vLLM 호환 OpenAI 엔드포인트
│   ├── test_server.py          # pytest
│   └── requirements.txt        # fastapi, uvicorn, httpx, pytest (핀 고정)
├── docs/
│   ├── superpowers/specs/2026-09-03-opencode-glm-design.md
│   └── runbook-onprem.md
├── logs/                        # mock 요청 로그, opencode 로그 (git-ignored)
├── .bin/                        # 설치된 opencode 바이너리 (git-ignored)
├── dist/                        # 다운로드한 tarball (git-ignored)
├── .gitignore
└── README.md
```

## 5. 컴포넌트 상세

### 5.1 scripts/install-opencode.sh

- 상수: `VERSION=1.18.27`, `REPO=anomalyco/opencode`.
- 플랫폼 판별: `uname -s`/`uname -m`과 `/proc/cpuinfo`의 avx2 유무로 자산명 결정.
  - linux x86_64 + avx2 → `opencode-linux-x64.tar.gz`
  - linux x86_64, avx2 없음 → `opencode-linux-x64-baseline.tar.gz`
  - linux aarch64 → `opencode-linux-arm64.tar.gz`
  - 그 외 → 오류 종료.
- 온라인 모드(기본): `https://github.com/anomalyco/opencode/releases/download/v$VERSION/<asset>`를 `dist/`에 다운로드.
- 오프라인 모드: `--offline <tarball 경로>`로 반입 파일을 사용.
- 검증: `sha256sum`을 `scripts/checksums.txt`의 해당 자산 값과 대조. 항목이 없으면 `--record` 옵션일 때만 기록하고, 아니면 실패.
- 설치: `.bin/`에 풀고 실행 파일이 `.bin/opencode`가 되도록 배치. 실행 후 `opencode --version` 출력이 `$VERSION`으로 시작하는지 확인, 아니면 실패.
- 종료 코드: 성공 0, 플랫폼 미지원 2, 체크섬 불일치 3, 버전 불일치 4, 다운로드 실패 5.

### 5.2 bin/opencode-glm

- `REPO_ROOT`를 스크립트 위치 기준으로 계산.
- `config/opencode.env`를 `set -a; source; set +a`로 로드.
- `OPENCODE_GLM_BIN`(기본 `$REPO_ROOT/.bin/opencode`)이 없으면 설치 안내 메시지와 함께 종료 코드 1.
- `GLM_API_KEY`가 비어 있으면 stderr에 경고 한 줄(실서버는 키 필요, mock은 불필요).
- `exec "$OPENCODE_GLM_BIN" "$@"`.

### 5.3 config/opencode.json

```json
{
  "$schema": "https://opencode.ai/config.json",
  "share": "disabled",
  "autoupdate": false,
  "model": "company-glm/glm-4.7",
  "small_model": "company-glm/glm-4.7",
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
        "glm-4.7": {
          "name": "GLM-4.7 (on-prem)",
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
```

- `baseURL`은 `GLM_BASE_URL` 환경변수로 덮어쓸 수 있게 `{env:GLM_BASE_URL}`을 쓰지 않는다. 미설정 시 빈 문자열이 되어 실패하기 때문. 실서버 전환은 이 파일의 `baseURL`을 수정한다.
- `limit`은 실서버 `--max-model-len`에 맞춰 조정한다. 런북에 명시.
- `experimental.policies`는 전 프로바이더 deny 후 `company-glm`만 allow. 사내 계정에 다른 클라우드 자격증명이 있어도 사용 불가.
- LSP·formatter는 opencode 기본이 비활성이므로 설정하지 않는다.

### 5.4 config/opencode.env

```
OPENCODE_CONFIG=<REPO_ROOT>/config/opencode.json   # 래퍼가 절대경로로 치환
OPENCODE_DISABLE_AUTOUPDATE=1
OPENCODE_DISABLE_MODELS_FETCH=1
OPENCODE_DISABLE_LSP_DOWNLOAD=1
```

- 래퍼는 `OPENCODE_CONFIG`를 항상 `$REPO_ROOT/config/opencode.json` 절대경로로 설정한다(env 파일의 값은 문서용 예시).
- `OPENCODE_DISABLE_MODELS_FETCH=1`이어도 릴리스 바이너리에 빌드 시점 models.dev 스냅샷이 내장돼 있어 카탈로그는 동작한다 (`packages/core/src/models-dev.ts`의 `OPENCODE_MODELS_DEV` 폴백).

### 5.5 mock-glm/server.py

FastAPI 단일 파일. 실행: `python3 -m uvicorn server:app --host 127.0.0.1 --port $MOCK_PORT` (mock.sh가 감쌈).

환경변수:
- `MOCK_PORT` (기본 8000), `MOCK_MODEL` (기본 `glm-4.7`), `MOCK_API_KEY` (기본 없음), `MOCK_LOG` (기본 `logs/requests.jsonl`).

엔드포인트:
- `GET /v1/models` → `{"object":"list","data":[{"id":MOCK_MODEL,"object":"model","owned_by":"vllm"}]}`
- `POST /v1/chat/completions`

인증: `MOCK_API_KEY`가 설정되면 `Authorization: Bearer <key>`가 정확히 일치해야 하며, 아니면 401 `{"error":{"message":"invalid api key"}}`.

시나리오 판정(요청 `messages`, `tools` 기준):
1. **tool_call 턴**: `tools`가 비어 있지 않고, 마지막 `user` 메시지 이후에 `role: tool` 메시지가 없음 →
   `reasoning_content` 델타 2개("요청을 확인하기 위해 ", "셸 명령을 실행합니다.") → tool_call 델타(`id: call_mock_1`, `function.name: bash`, `arguments: {"command":"echo GLM_MOCK_TOOL_OK"}`) → `finish_reason: tool_calls`.
2. **최종 답변 턴**: 마지막 메시지가 `role: tool` → 텍스트 델타로 `도구 실행 결과: <tool content 앞 80자>` 한 줄과 `GLM_MOCK_DONE` → `finish_reason: stop`.
3. **단순 텍스트**: `tools`가 없거나 빈 배열 → 텍스트 `GLM mock reply` → `finish_reason: stop`. (세션 제목 생성 등)

응답 형식:
- `stream: false` → 표준 `chat.completion` 객체. 시나리오 1은 `message.tool_calls`, 시나리오 1의 reasoning은 `message.reasoning_content`.
- `stream: true` → `text/event-stream`. 각 청크는 `data: {"id":"chatcmpl-mock-<n>","object":"chat.completion.chunk","created":<epoch>,"model":MOCK_MODEL,"choices":[{"index":0,"delta":{...},"finish_reason":null}]}`. 첫 청크 delta에 `role: assistant`. 종료 청크는 `delta: {}`와 `finish_reason`. `stream_options.include_usage`가 true면 그 뒤에 `choices: []`와 `usage` 청크. 마지막은 `data: [DONE]`.
- usage: `prompt_tokens`는 메시지 content 총 길이 // 4, `completion_tokens`는 생성 텍스트 길이 // 4 (0이면 1), `total_tokens`는 합.

로깅: 요청마다 `MOCK_LOG`에 한 줄 JSON 추가.
```
{"ts": ISO8601, "scenario": "tool_call|final|text", "model": ..., "stream": bool,
 "n_messages": int, "roles": [...], "system_chars": int, "tool_names": [...],
 "params": {messages/tools를 제외한 본문 최상위 키 전부}, "auth": "ok|missing|bad"}
```
`params`에 Z.AI 전용 `thinking` 키가 들어오면 그대로 기록되어 verify.sh가 부재를 확인한다.

### 5.6 scripts/mock.sh

- `start`: 이미 떠 있으면 무시. 아니면 uvicorn을 백그라운드로 띄우고 PID를 `logs/mock.pid`에, stdout/stderr를 `logs/mock.log`에 기록. `/v1/models`가 200을 줄 때까지 최대 15초 대기, 실패 시 종료 코드 1.
- `stop`: PID 파일 기준 종료.
- `status`: 헬스체크 결과 출력.

### 5.7 scripts/verify.sh

순서와 단정:
1. `scripts/mock.sh start` (trap으로 종료 시 항상 `stop`).
2. `bin/opencode-glm --version` 출력이 `1.18.27`로 시작.
3. `bin/opencode-glm models company-glm` 출력에 `company-glm/glm-4.7` 포함.
4. 임시 디렉터리(`mktemp -d`)에서 `bin/opencode-glm run --format json --model company-glm/glm-4.7 "smoke test"` 실행, stdout을 `logs/verify-run.jsonl`에 저장. 파이썬으로 파싱해:
   - `type == "tool_use"`이고 `part.tool == "bash"`, `part.state.status == "completed"`, `part.state.output`에 `GLM_MOCK_TOOL_OK` 포함인 이벤트가 존재.
   - `type == "text"`이고 `part.text`에 `GLM_MOCK_DONE` 포함인 이벤트가 존재.
   - `type == "error"` 이벤트가 없음.
5. `logs/requests.jsonl`의 이번 실행분에서: `scenario == tool_call`인 항목의 `stream == true`, `tool_names`에 `bash` 포함, `params`에 `thinking` 키 없음, `params.temperature == 1.0`, `params.stream_options.include_usage == true`.
6. opencode 로그 디렉터리(`~/.local/share/opencode/log/`)의 최신 파일에 `Failed to fetch models.dev` 문자열이 없음.
7. 실패한 단정은 항목 번호와 함께 stderr에 출력하고 종료 코드 1. 전부 통과 시 `VERIFY OK` 출력, 종료 코드 0.

JSON 이벤트의 필드명(`part.tool`, `part.state.status`, `part.state.output`, `part.text`)은 `packages/opencode/src/cli/cmd/run.ts`의 `emit("tool_use", { part })`/`emit("text", { part })` 기준이며, 구현 시 실제 출력으로 재확인한다.

### 5.8 docs/runbook-onprem.md

목차:
1. 반입 목록: tarball, `checksums.txt`, 이 리포(archive).
2. 설치: `install-opencode.sh --offline`, `/usr/local/bin/opencode` 배치.
3. 관리 설정: `config/opencode.json`을 `/etc/opencode/opencode.json`으로 (root 소유, 사용자 override 불가). `baseURL`·`limit`을 실서버에 맞게 수정.
4. 환경변수: `/etc/profile.d/opencode.sh`에 `opencode.env` 내용 + `GLM_API_KEY` 발급 방식.
5. 네트워크: 사내 CA는 `NODE_EXTRA_CA_CERTS`, 프록시는 `HTTPS_PROXY`/`NO_PROXY=localhost,127.0.0.1,<vllm host>`.
6. vLLM 서버 플래그 (공식 레시피 기준):

   | 모델 | `--tool-call-parser` | `--reasoning-parser` | 추가 |
   |---|---|---|---|
   | GLM-4.5 / 4.5-Air / 4.6 | `glm45` | `glm45` | `--enable-auto-tool-choice` |
   | GLM-4.7 / 4.7-Flash | `glm47` | `glm45` | `--enable-auto-tool-choice` |
   | GLM-5 / 5.1 | `glm47` | `glm45` | `--enable-auto-tool-choice --chat-template-content-format=string` |

   `--served-model-name`은 `opencode.json`의 모델 키와 일치해야 한다. thinking은 vLLM 기본 on이며, 끄려면 모델 `options`에 `"chat_template_kwargs": {"enable_thinking": false}` (opencode가 모델 options를 요청 본문에 합침).
7. 검증: `verify.sh`를 실서버 대상으로 돌리되 mock 전용 단정(4, 5)은 건너뛰는 `--live` 옵션 사용. `opencode debug config`로 최종 설정 확인.
8. 버전 업데이트 절차: 태그 선정 기준(bugfix-only 릴리스, 태그 후 1주 이상 회귀 없음, 릴리스 노트에 OpenAI 호환 관련 수정 확인), `checksums.txt` 갱신, verify 재실행.

### 5.9 README.md

빠른 시작(설치 → mock 기동 → verify → TUI 실행), 디렉터리 설명, 런북 링크.

## 6. 데이터 흐름

```
사용자 ─ bin/opencode-glm ─▶ opencode(v1.18.27, TUI/run)
                                │  POST /v1/chat/completions (stream, tools, temperature 1.0)
                                ▼
                      mock-glm (127.0.0.1:8000)  ──▶ logs/requests.jsonl
                                │  SSE: reasoning_content → tool_calls(bash) → [DONE]
                                ▼
                     opencode가 bash 실행 → tool 결과를 messages에 추가 → 재요청
                                │  SSE: text "...GLM_MOCK_DONE" → [DONE]
                                ▼
                            최종 답변 출력
```

## 7. 에러 처리

- 설치: 체크섬/버전/플랫폼 불일치는 즉시 실패, 부분 설치물은 남기지 않음(임시 디렉터리에 풀고 성공 시 이동).
- 래퍼: 바이너리 부재 시 안내 후 종료 1. 키 미설정은 경고만.
- mock: 잘못된 JSON 본문은 400. 알 수 없는 모델명은 404 `{"error":{"message":"model not found"}}`. 인증 실패 401.
- verify: 어느 단계가 실패했는지 번호로 출력. mock은 trap으로 반드시 종료.
- opencode 타임아웃: 1.18.27 기본(헤더/청크 5분)에 의존하고 `timeout`만 10분.

## 8. 테스트

- `mock-glm/test_server.py` (pytest + FastAPI TestClient), TDD로 작성:
  - `/v1/models` 응답.
  - 시나리오 1/2/3 각각 비스트리밍 응답 구조.
  - 시나리오 1 스트리밍: 청크 순서(role → reasoning_content → tool_calls → finish_reason → usage → [DONE]), `include_usage` 없으면 usage 청크 없음.
  - `MOCK_API_KEY` 설정 시 401/200.
  - 로그 한 줄 기록과 `params` 키 구성.
- 설치/래퍼/verify: 실제 실행으로 검증. `verify.sh` 통과가 완료 기준.

## 9. 가정과 구현 시 확인 항목

- tarball 내부 경로가 `opencode-linux-x64/bin/opencode`인지 (빌드 스크립트 `dist/<name>/bin` 기준). 다르면 설치 스크립트에서 `find`로 실행 파일을 찾는다.
- `opencode run --format json`의 이벤트 필드명 (5.7 참고).
- `bash` 도구는 기본 권한이 allow라 `run`에서 프롬프트 없이 실행됨 (permissions 문서 "대부분 allow"). 프롬프트가 뜨면 `--auto`를 verify.sh에만 추가한다.
- 커스텀 프로바이더는 `auth.json` 자격증명 없이도 `options.apiKey`(빈 문자열 포함)로 로드됨. 로드되지 않으면 `opencode auth login`의 Other 항목으로 더미 키를 넣는 절차를 README에 추가한다.
