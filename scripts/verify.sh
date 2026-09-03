#!/usr/bin/env bash
# 엔드투엔드 스모크: 환경 가드 -> mock 기동 -> 버전 -> 모델 목록 -> opencode run(tool call) -> 로그 단정
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
MODELS_CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/opencode/models.json"
mkdir -p "$LOG_DIR"

fail() { echo "VERIFY FAIL [$1]: $2" >&2; exit 1; }
count_lines() { if [[ -f "$1" ]]; then wc -l < "$1"; else echo 0; fi; }

# 0. environment guards
if [[ $LIVE -eq 0 ]]; then
  if [[ -n "${MOCK_PORT:-}" && "${MOCK_PORT}" != "8000" ]]; then
    fail 0 "MOCK_PORT=$MOCK_PORT is not supported here: config/opencode.json targets http://127.0.0.1:8000/v1 — unset MOCK_PORT"
  fi
  if [[ -n "${MOCK_LOG:-}" ]]; then
    fail 0 "MOCK_LOG override is not supported here: verify reads $REQ_LOG — unset MOCK_LOG"
  fi
fi
if ! command -v rg >/dev/null 2>&1; then
  if [[ $LIVE -eq 1 ]]; then
    fail 0 "ripgrep (rg) not on PATH: opencode would try to download it from github.com (see docs/runbook-onprem.md §1)"
  fi
  echo "warning: ripgrep (rg) not on PATH; opencode will try to download it from github.com on first grep/glob use" >&2
fi

# 1. mock
if [[ $LIVE -eq 0 ]]; then
  "$ROOT/scripts/mock.sh" start || fail 1 "mock did not start"
  trap '"$ROOT/scripts/mock.sh" stop >/dev/null 2>&1 || true' EXIT
fi

# markers for incremental log checks
REQ_BEFORE="$(count_lines "$REQ_LOG")"
OC_BEFORE="$(count_lines "$OC_LOG")"
RUN_START="$(date +%s)"

# 2. version
VERSION="$("$ROOT/bin/opencode-glm" --version 2>/dev/null | tail -n1 || true)"
[[ "$VERSION" == "$EXPECTED_VERSION"* ]] || fail 2 "opencode version is '$VERSION', expected $EXPECTED_VERSION"
echo "version ok: $VERSION"

# 3. model listing
"$ROOT/bin/opencode-glm" models company-glm 2>/dev/null | grep -qx "$MODEL" || fail 3 "$MODEL not listed by 'opencode models company-glm'"
echo "model listed: $MODEL"

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
if [[ -f "$MODELS_CACHE" ]] && [[ "$(stat -c %Y "$MODELS_CACHE")" -ge "$RUN_START" ]]; then
  fail 6 "models.dev catalog was fetched during this run ($MODELS_CACHE written; OPENCODE_DISABLE_MODELS_FETCH not applied?)"
fi
echo "offline ok: no models.dev fetch (log clean, $MODELS_CACHE not written)"

echo "VERIFY OK"
