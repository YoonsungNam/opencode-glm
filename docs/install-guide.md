# 사내 설치 가이드: opencode ↔ GLM(vLLM)

대상: 사내 데스크톱(Linux x86_64, 인터넷 연결 가능)에 opencode v1.18.27 을 설치해 사내 vLLM GLM 서버(`glm-5.3-flash`)에 연결하는 사람. 외부 접근이 완전히 막힌 호스트는 [runbook-onprem.md](runbook-onprem.md) 의 반입 절차를 먼저 따르고, 그 뒤 이 문서의 3절부터 이어서 진행한다.

## 1. 사전 요구사항

| 항목 | 요구 | 확인 명령 |
|---|---|---|
| OS | Linux x86_64 (Ubuntu 22.04 / glibc 2.35 에서 검증). AVX2 없는 CPU 는 설치 스크립트가 baseline 자산을 자동 선택 | `uname -m`, `grep -c avx2 /proc/cpuinfo` |
| 기본 도구 | git, bash, curl, tar, sha256sum | `git --version && curl --version | head -1` |
| ripgrep | `rg` 가 PATH 에 있어야 한다. 없으면 opencode 가 grep/glob 도구를 처음 쓸 때 GitHub 에서 받아오려 하고, 이를 끄는 설정이 없다 | `command -v rg` |
| Python | **3.10 이상**. 실서버 검증 스크립트는 표준 라이브러리만 쓴다 | `python3 --version` |
| Python 패키지 | **실서버만 쓰면 불필요.** mock 서버·pytest 를 돌릴 때만 `mock-glm/requirements*.txt` | 2절 표 참고 |
| vLLM 서버 | GLM 을 OpenAI 호환 API 로 서빙 중이어야 함. 플래그는 runbook §6 | `curl http://<vllm-host>:<port>/v1/models` |

ripgrep 설치 (둘 중 하나):

```bash
sudo apt install ripgrep                       # 배포판 패키지 (버전이 낮아도 무방)
# 또는 사용자 경로에 릴리스 바이너리 설치
curl -fsSLO https://github.com/BurntSushi/ripgrep/releases/download/15.1.0/ripgrep-15.1.0-x86_64-unknown-linux-musl.tar.gz
tar -xzf ripgrep-15.1.0-x86_64-unknown-linux-musl.tar.gz
install -m 0755 ripgrep-15.1.0-x86_64-unknown-linux-musl/rg ~/.local/bin/rg   # ~/.local/bin 이 PATH 에 있어야 함
```

## 2. 의존성 한눈에 보기

| 구성 요소 | 파이썬 | 패키지 |
|---|---|---|
| opencode 바이너리, 래퍼, 설치·mock·verify 셸 스크립트 | 필요 없음 | bash/curl/tar/sha256sum, `rg` |
| `scripts/verify_events.py`, `scripts/verify_mocklog.py` | 3.10+ | 없음 (표준 라이브러리) |
| `mock-glm/server.py` | 3.10+ | `mock-glm/requirements.txt` (fastapi, uvicorn) |
| `mock-glm/test_server.py` | 3.10+ | `mock-glm/requirements-dev.txt` (+ pytest, httpx) |

전이 의존성까지 고정한 `mock-glm/requirements.lock` 은 Linux x86_64 / Python 3.10 에서 생성·검증됐다. 다른 파이썬 버전이면 `requirements-dev.txt` 로 설치한다.

## 3. 설치

```bash
git clone https://github.com/YoonsungNam/opencode-glm.git
cd opencode-glm
scripts/install-opencode.sh
```

기대 출력(마지막 줄들):

```
checksum ok: 4af5494f9433f59db8c1e344198f0ee72a50c06ec009fb4a8aeab4c2d4abd702
installed opencode 1.18.27 -> /path/to/opencode-glm/.bin/opencode
```

확인:

```bash
bin/opencode-glm --version            # 1.18.27  (GLM_API_KEY 경고 한 줄은 정상)
bin/opencode-glm models company-glm   # company-glm/glm-5.3-flash
```

바이너리는 리포 안 `.bin/opencode` 에만 놓인다(git 무시). 어디서든 부르려면 래퍼를 PATH 에 링크한다:

```bash
ln -s "$PWD/bin/opencode-glm" ~/.local/bin/opencode-glm
```

(선택) mock 서버와 테스트까지 쓰려면:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r mock-glm/requirements-dev.txt
scripts/verify.sh                     # 로컬 mock 으로 배관 검증 → 마지막 줄 VERIFY OK
```

## 4. 실서버 연결 설정

`config/opencode.json` 에서 바꿀 값:

| 키 | 값 | 비고 |
|---|---|---|
| `provider.company-glm.options.baseURL` | `http://<vllm-host>:<port>/v1` | 끝에 `/v1` 포함 |
| `provider.company-glm.models` 의 키 | vLLM `--served-model-name` 과 동일 | 기본 `glm-5.3-flash`. 이름을 바꾸면 `model`, `small_model`, `scripts/verify.sh` 의 `MODEL`, `scripts/verify_mocklog.py` 의 `EXPECTED_MODEL` 도 함께 |
| `...models.<키>.limit.context` | vLLM `--max-model-len` 이하 | 예: 131072 |
| `...models.<키>.limit.output` | 한 응답의 최대 출력 토큰 | 예: 32768 |

vLLM 이 `--api-key` 로 떠 있으면 셸 프로필에 키를 둔다:

```bash
export GLM_API_KEY=...        # ~/.bashrc 등. 설정의 {env:GLM_API_KEY} 로 주입된다
```

vLLM 쪽 필수 플래그(자세한 표는 runbook §6): `--enable-auto-tool-choice --tool-call-parser glm47 --reasoning-parser glm45 --chat-template-content-format=string --served-model-name glm-5.3-flash`. 이 플래그가 없으면 opencode 의 도구 호출이 동작하지 않는다.

## 5. 검증

```bash
scripts/verify.sh --live
```

기대 출력:

```
version ok: 1.18.27
model listed: company-glm/glm-5.3-flash
events ok: N tool_use, M text, K total
offline ok: no models.dev fetch (log clean, ~/.cache/opencode/models.json not written)
VERIFY OK
```

`--live` 는 mock 을 띄우지 않고 실서버에 "현재 디렉터리 파일 목록을 셸 명령으로 확인하고 한 줄로 요약해줘" 를 보내, 도구 호출 1회 이상 + 텍스트 응답 + 오류 없음을 확인한다. 실패하면 `VERIFY FAIL [단계]: 이유` 가 찍힌다(9절 참고).

최종 설정 확인: `bin/opencode-glm debug config`.

## 6. 일상 사용

```bash
cd <작업할 프로젝트>
opencode-glm                 # TUI. 기본 모델 company-glm/glm-5.3-flash
```

TUI 안에서 `/models` 로 모델 목록을 확인할 수 있다(`company-glm/glm-5.3-flash` 하나만 보이는 것이 정상). 세션·로그는 `~/.local/share/opencode/`, 캐시는 `~/.cache/opencode/` 에 쌓인다.

주의: 작업 프로젝트에 자체 `opencode.json` 이 있으면 래퍼의 설정보다 나중에 병합돼 `model` 이나 `enabled_providers` 를 덮어쓸 수 있다. 팀 전체에 강제하려면 runbook §3 의 `/etc/opencode/opencode.json` 관리 설정을 쓴다.

## 7. 팀 배포로 넘어갈 때

한 사람의 검증이 끝나면 runbook 의 §2(`/usr/local/bin/opencode`), §3(관리 설정), §4(`/etc/profile.d` 환경변수) 순으로 진행한다. 이 가이드의 `bin/opencode-glm` + `config/` 는 개인 PoC 경로이고, 관리 설정 경로에서는 래퍼 없이 `opencode` 를 바로 실행한다.

## 8. 외부 접근이 막힌 호스트

runbook §1 의 반입 목록(opencode tarball, `checksums.txt`, ripgrep, 리포 archive, 선택적으로 파이썬 wheel 묶음)을 준비한 뒤:

```bash
scripts/install-opencode.sh --offline /path/opencode-linux-x64.tar.gz
# 파이썬 패키지가 필요할 때만
pip install --no-index --find-links /path/wheelhouse -r mock-glm/requirements.lock
```

이후 4절부터 동일하다. `OPENCODE_DISABLE_*` 플래그(`config/opencode.env`)와 사전 설치한 `rg` 덕분에 opencode 는 외부로 나가는 호출을 하지 않는다.

## 9. 문제 해결

| 증상 | 원인 | 조치 |
|---|---|---|
| `bin/opencode-glm models company-glm` 에 모델이 없음 | `config/opencode.json` 문법 오류 또는 래퍼 대신 `opencode` 를 직접 실행 | `python3 -m json.tool config/opencode.json`, 래퍼로 실행, `bin/opencode-glm debug config` |
| `VERIFY FAIL [0]: ripgrep (rg) not on PATH` | `rg` 미설치 | 1절대로 설치 |
| `VERIFY FAIL [0]: MOCK_PORT=...` / `MOCK_LOG` | 환경변수 오버라이드 | `unset MOCK_PORT MOCK_LOG` |
| `VERIFY FAIL [4]` 와 `logs/verify-run.jsonl` 의 `error` 에 401 / `invalid api key` | `GLM_API_KEY` 미설정·불일치 | `echo $GLM_API_KEY` 확인 후 재실행 |
| `VERIFY FAIL [4]` 와 연결 거부/timeout | `baseURL`·포트 오류, vLLM 미기동 | `curl <baseURL>/models` 로 먼저 확인 |
| 모델이 도구를 쓰지 않고 말로만 답함, `events: no completed tool_use event` | vLLM 에 `--enable-auto-tool-choice`/`--tool-call-parser` 누락 | runbook §6 플래그 추가 후 vLLM 재기동 |
| 답변 본문에 `<think>...</think>` 가 그대로 섞임 | `--reasoning-parser glm45` 누락 | 플래그 추가 |
| `context length` 초과 오류 | `limit.context` 가 `--max-model-len` 보다 큼 | `limit.context` 를 낮춘다 |
| `VERIFY FAIL [6]: ... models.dev catalog was fetched` | `OPENCODE_DISABLE_MODELS_FETCH` 미적용 (래퍼를 안 썼거나 profile.d 미반영) | 래퍼 사용 또는 runbook §4 |
| `run` 출력에 `permission requested: ... auto-rejecting` | 권한 설정이 `ask` | `bin/opencode-glm debug config` 로 `permission` 확인 |
| pytest 에 `StarletteDeprecationWarning` | 설치된 starlette/fastapi 의 안내 메시지 | 무시 (코드 문제 아님) |

로그 위치: opencode `~/.local/share/opencode/log/opencode.log`, verify 실행 `logs/verify-run.jsonl`·`logs/verify-run.stderr`, mock `logs/mock.log`·`logs/requests.jsonl`.

## 10. 업데이트

opencode 버전 변경은 runbook §8(태그 선정 기준, `scripts/install-opencode.sh` 의 `VERSION` 과 `scripts/checksums.txt` 갱신, verify 재실행)을 따른다. 파이썬 패키지 버전을 바꾸면 `requirements*.txt` 와 `requirements.lock` 을 같이 갱신하고 `python3 -m pytest -q` 로 확인한다.
