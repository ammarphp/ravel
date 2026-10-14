#!/usr/bin/env bash
# Build SPheno 4.0.5 with the spectrum environment's gfortran.
# Usage: build-spheno.sh --src DIR --env ENV
set -euo pipefail
. "$(dirname "$0")/common.sh"
while [ $# -gt 0 ]; do case "$1" in
  --src) SRC="$2"; shift 2 ;; --env) ENV="$2"; shift 2 ;; *) ravel_die "unknown argument $1" ;; esac; done
ravel_activate "$ENV"
# SPheno selects its gfortran flags only when F90 is exactly "gfortran"; the activated environment puts that compiler first on PATH.
make -C "$SRC" F90=gfortran
[ -x "$SRC/bin/SPheno" ] || ravel_die "SPheno was not built"
