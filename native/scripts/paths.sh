#!/usr/bin/env bash
# Shared native locations. Existing source toolchains keep their original bytes.
RAVEL_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [ -z "${RAVEL_NATIVE_BUILD:-}" ]; then
  if [ -d "$RAVEL_REPO/stages/01-event-generation/build" ]; then
    RAVEL_NATIVE_BUILD="$RAVEL_REPO/stages/01-event-generation/build"
  else
    RAVEL_NATIVE_BUILD="$RAVEL_REPO/native/build"
  fi
fi
RAVEL_NATIVE_BIN="${RAVEL_NATIVE_BIN:-$RAVEL_REPO/native/build/bin}"
export RAVEL_NATIVE_BUILD RAVEL_NATIVE_BIN
