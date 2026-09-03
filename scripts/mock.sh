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
