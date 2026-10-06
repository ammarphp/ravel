#!/usr/bin/env bash
# Pinned, user-local bootstrap. --dry-run performs checks without writing/network.
set -euo pipefail
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT/../native/scripts/paths.sh"
source "$PROJECT/../native/scripts/macos-common.sh"
DRY=0
case "${1:-}" in --dry-run) DRY=1 ;; '') ;; *) echo "Usage: $0 [--dry-run]" >&2; exit 2 ;; esac
[ "$#" -le 1 ] || { echo 'Unexpected arguments' >&2; exit 2; }
ARCH="$(ravel_macos_arch)"
BUILD="${BUILD_DIR:-$RAVEL_NATIVE_BUILD}"
PREFIX="$BUILD/tools/miniforge3"
# Both digests are from the upstream release assets, checked 2026-09-05.
# https://github.com/conda-forge/miniforge/releases/tag/26.5.3-0
VERSION=26.5.3-0
case "$ARCH" in
  arm64) SHA=0d765919d3ccfd1f89147aa1cf8133bfc55b3a3c13f5bacdcc091c33132fddd2 ;;
  x86_64) SHA=0266a7bfeb12165286133145717bef0d88070f1b76710beb6a62fec4e88371a1 ;;
esac
ASSET="Miniforge3-$VERSION-MacOSX-$ARCH.sh"
URL="https://github.com/conda-forge/miniforge/releases/download/$VERSION/$ASSET"
if [ -e "$PREFIX" ] || [ -L "$PREFIX" ]; then
  ravel_check_conda "$PREFIX" "$ARCH"
  echo "[reuse] Existing native Miniforge: $PREFIX (not upgraded or repinned)"
  exit 0
fi
case "$PREFIX" in /*) ;; *) echo 'ERROR: native build prefix must be absolute' >&2; exit 1 ;; esac
# Miniforge's installer rejects prefixes containing spaces. Fail before download.
case "$PREFIX" in *[[:space:]]*) echo 'ERROR: choose a RAVEL_NATIVE_BUILD without whitespace for Miniforge' >&2; exit 1 ;; esac
for TOOL in curl shasum mktemp; do command -v "$TOOL" >/dev/null || { echo "ERROR: missing $TOOL" >&2; exit 1; }; done
printf 'Installer: %s\nSHA256: %s\nPrefix: %s\n' "$URL" "$SHA" "$PREFIX"
[ "$DRY" = 0 ] || exit 0
mkdir -p "$BUILD/tools"
WORK="$(mktemp -d "$BUILD/tools/miniforge-download.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
curl --proto '=https' --tlsv1.2 -L --fail --retry 3 -o "$WORK/$ASSET" "$URL"
ACTUAL="$(shasum -a 256 "$WORK/$ASSET")"; ACTUAL="${ACTUAL%% *}"
[ "$ACTUAL" = "$SHA" ] || { echo 'ERROR: Miniforge checksum mismatch; installer was not executed' >&2; exit 1; }
# An interrupted install is kept for inspection, never silently overwritten.
bash "$WORK/$ASSET" -b -p "$PREFIX"
ravel_check_conda "$PREFIX" "$ARCH"
printf '%s  %s\n' "$SHA" "$ASSET" > "$PREFIX/ravel-bootstrap.sha256"
"$PREFIX/bin/conda" --version
