#!/usr/bin/env bash
set -euo pipefail
. "$(dirname "$0")/common.sh"
SRC="" ENV="" LHAPDF="" JOBS=2
while [ $# -gt 0 ]; do
 case "$1" in
  --src) SRC="$2"; shift 2 ;; --env) ENV="$2"; shift 2 ;;
  --lhapdf) LHAPDF="$2"; shift 2 ;; --jobs) JOBS="$2"; shift 2 ;;
  *) ravel_die "unknown argument: $1" ;;
 esac
done
[ -f "$SRC/Makefile" ] || ravel_die "supplied source has no Makefile"
[ -x "$LHAPDF/bin/lhapdf-config" ] || ravel_die "LHAPDF configuration is required"
ravel_activate "$ENV"
export PATH="$LHAPDF/bin:$PATH"
make -C "$SRC" -j "$JOBS" FC="${FC:-gfortran}" LHAPDF_CONFIG="$LHAPDF/bin/lhapdf-config"
[ -x "$SRC/bin/sushi" ] || ravel_die "production calculator output was not built"
