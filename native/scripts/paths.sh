#!/usr/bin/env bash
# Shared native locations. Existing source toolchains keep their original bytes.
RAVEL_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [ -n "${BUILD_DIR:-}" ]; then
  if [ -n "${RAVEL_NATIVE_BUILD:-}" ] && [ "$BUILD_DIR" != "$RAVEL_NATIVE_BUILD" ]; then
    echo 'ERROR: BUILD_DIR and RAVEL_NATIVE_BUILD disagree; use one native prefix' >&2
    return 1
  fi
  RAVEL_NATIVE_BUILD="$BUILD_DIR"
fi
if [ -z "${RAVEL_NATIVE_BUILD:-}" ]; then
  if [ -d "$RAVEL_REPO/stages/01-event-generation/build" ]; then
    RAVEL_NATIVE_BUILD="$RAVEL_REPO/stages/01-event-generation/build"
  else
    RAVEL_NATIVE_BUILD="$RAVEL_REPO/native/build"
  fi
fi
RAVEL_NATIVE_BIN="${RAVEL_NATIVE_BIN:-$RAVEL_REPO/native/build/bin}"
case "$RAVEL_NATIVE_BUILD" in /*) ;; *) echo 'ERROR: RAVEL_NATIVE_BUILD must be absolute' >&2; return 1 ;; esac
case "$RAVEL_NATIVE_BIN" in /*) ;; *) echo 'ERROR: RAVEL_NATIVE_BIN must be absolute' >&2; return 1 ;; esac
export RAVEL_NATIVE_BUILD RAVEL_NATIVE_BIN
