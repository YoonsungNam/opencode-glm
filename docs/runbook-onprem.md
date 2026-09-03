# 사내(폐쇄망) 배포 런북: opencode ↔ GLM(vLLM)

대상: 개발자 PC/공용 서버(Linux x86_64)에 opencode v1.18.27 을 설치해 사내 vLLM GLM 에 연결한다.

## 1. 반입 목록

온라인 PC에서 준비해 승인된 경로로 반입한다.

| 항목 | 출처 | 비고 |
|---|---|---|
| `opencode-linux-x64.tar.gz` | `https://github.com/anomalyco/opencode/releases/download/v1.18.27/` | AVX2 없는 CPU면 `opencode-linux-x64-baseline.tar.gz`, ARM 이면 `opencode-linux-arm64.tar.gz` |
| ripgrep(`rg`) 바이너리 | 배포판 패키지(`apt install ripgrep` 등) 또는 `https://github.com/BurntSushi/ripgrep/releases/download/15.1.0/` 의 tarball | opencode 의 grep/glob 도구와 skill 탐색이 `rg` 를 쓴다. PATH 에 없으면 GitHub 에서 자동 다운로드를 시도하며 이를 끄는 플래그가 없다. `/usr/local/bin/rg` 또는 `~/.cache/opencode/bin/rg` 에 두면 다운로드하지 않는다 |
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
- 차단해도 되는 외부 호스트(아래 예외 하나를 빼면 오프라인 플래그로 호출 자체를 막는다): `api.github.com`(업데이트 체크), `models.opencode.ai`(모델 카탈로그 갱신), `github.com`/`registry.npmjs.org`(LSP·플러그인 다운로드), `opncd.ai`(share, 설정에서 disabled)
- 예외: `github.com` 의 ripgrep 15.1.0 자동 다운로드는 플래그로 막을 수 없다. §1 대로 `rg` 를 사전 설치해 회피한다. `command -v rg` 로 확인.

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

`verify.sh --live` 는 `rg` 가 PATH 에 없으면 즉시 실패한다(위 예외 때문).

문제 시: `~/.local/share/opencode/log/opencode.log`, `opencode debug config`.

## 8. 버전 업데이트 절차

1. 후보 태그 선정 기준: 릴리스 노트가 bugfix-only, 태그 후 1주 이상 회귀 보고 없음, OpenAI 호환 프로바이더 관련 수정이 있으면 우선.
2. 온라인 PC: 새 tarball 다운로드 → `sha256sum` → `scripts/install-opencode.sh` 의 `VERSION` 과 `scripts/checksums.txt` 갱신 → `scripts/verify.sh`(mock) 통과 확인 → 커밋.
3. 반입 후 `--offline` 설치 → `scripts/verify.sh --live` → `/usr/local/bin/opencode` 교체.
