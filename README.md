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
