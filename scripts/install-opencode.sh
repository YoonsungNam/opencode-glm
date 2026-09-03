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
