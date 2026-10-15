#!/usr/bin/env bash
# Build a supplied Fortran source tree; refuse undeclared output layouts.
set -euo pipefail
. "$(dirname "$0")/common.sh"
SRC="" ENV="" BINARY="" JOBS=2
while [ $# -gt 0 ]; do
  case "$1" in
    --src) SRC="$2"; shift 2 ;; --env) ENV="$2"; shift 2 ;;
    --binary) BINARY="$2"; shift 2 ;; --jobs) JOBS="$2"; shift 2 ;;
    *) ravel_die "unknown argument: $1" ;;
  esac
done
[ -f "$SRC/Makefile" ] || ravel_die "supplied source has no Makefile: $SRC"
case "$BINARY" in ''|*/*|*..*) ravel_die "binary must be a basename" ;; esac
ravel_activate "$ENV"
make -C "$SRC" -j "$JOBS" FC="${FC:-gfortran}" F77="${FC:-gfortran}"
[ -x "$SRC/$BINARY" ] || ravel_die "source output differs; qualify its build layout before release: $SRC/$BINARY"
