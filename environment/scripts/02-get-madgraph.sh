#!/usr/bin/env bash
# Fetch the recorded MG5 source revision. This does not generate events.
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
DEST="$BUILD/tools/mg5amcnlo"
TAG=v2.9.27
REV=eb76cab72b8d44aac7162ac7221ac08a4384a169
REPO=https://github.com/mg5amcnlo/mg5amcnlo
ravel_check_conda "$PREFIX" "$ARCH"
ravel_check_macos_binary "$PREFIX/envs/mg5/bin/python" "$ARCH"
if [ -e "$DEST" ] || [ -L "$DEST" ]; then
  [ -f "$DEST/bin/mg5_aMC" ] && [ "$(git -C "$DEST" rev-parse HEAD)" = "$REV" ] || {
    echo "ERROR: existing MadGraph is incomplete or has a different revision: $DEST; it was not changed" >&2; exit 1;
  }
  [ -z "$(git -C "$DEST" diff --name-only HEAD)" ] || { echo 'ERROR: tracked MadGraph source changes require review; existing files preserved' >&2; exit 1; }
  echo "[reuse] Recorded MadGraph source: $DEST ($REV)"
  exit 0
fi
printf 'Source: %s tag %s, required commit %s\nDestination: %s\n' "$REPO" "$TAG" "$REV" "$DEST"
[ "$DRY" = 0 ] || exit 0
git clone --depth 1 --branch "$TAG" "$REPO" "$DEST"
[ "$(git -C "$DEST" rev-parse HEAD)" = "$REV" ] || { echo 'ERROR: upstream tag changed; clone retained for inspection, not executed' >&2; exit 1; }
echo '[done] Source obtained; use the approved native plan/run interface for generation.'
