#!/usr/bin/env bash
set -euo pipefail
. "$(dirname "$0")/common.sh"
SRC="" ENV="" JOBS=2
while [ $# -gt 0 ]; do
 case "$1" in
  --src) SRC="$2"; shift 2 ;; --env) ENV="$2"; shift 2 ;; --jobs) JOBS="$2"; shift 2 ;;
  *) ravel_die "unknown argument: $1" ;;
 esac
done
[ -f "$SRC/Makefile" ] || ravel_die "supplied source has no Makefile"
ravel_activate "$ENV"
[ -x "$ENV/bin/gsl-config" ] || ravel_die "GSL is required in the build environment"
make -C "$SRC" -j "$JOBS" CXX="$CXX" GSL_CONFIG="$ENV/bin/gsl-config"
[ -x "$SRC/bin/CalcPhys" ] || ravel_die "calculator output was not built"
