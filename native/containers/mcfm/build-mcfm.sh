#!/bin/bash
# Build ravel_mcfm_amplitudes inside the MCFM toolchain container.
#
# Usage (paths are host paths mounted at identical container paths):
#   build-mcfm.sh UPSTREAM_ROOT OVERLAY_ROOT BUILD_DIR
#
# UPSTREAM_ROOT  pristine MCFM checkout at the pinned commit (read-only mount)
# OVERLAY_ROOT   exported tree with the RAVEL overlay applied (read-only mount)
# BUILD_DIR      new, empty build directory (the only writable mount)
#
# Writes BUILD_DIR/build-receipt.json for the MCFM amplitude program, plus BUILD_DIR/toolchain.json and linked-libraries.json that
# record the compilers and system libraries provided by the image.
set -euo pipefail
UPSTREAM=$1
OVERLAY=$2
BUILD=$3
COMMIT=0adaa4ed4079de1b17c84417a0a428a468f57e69
JOBS=${RAVEL_BUILD_JOBS:-1}

test "$(uname -s)" = Linux
test -d "$UPSTREAM/.git" || { echo "upstream checkout has no .git directory" >&2; exit 2; }
test "$(git -c safe.directory='*' -C "$UPSTREAM" rev-parse HEAD)" = "$COMMIT" || { echo "MCFM commit differs from $COMMIT" >&2; exit 2; }
test -z "$(ls -A "$BUILD")" || { echo "build directory must be empty" >&2; exit 2; }

CONFIGURE=(cmake -S "$OVERLAY" -B "$BUILD" -DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++
  -DCMAKE_Fortran_COMPILER=gfortran -Dwith_library=OFF -Dwith_vvamp=OFF -Duse_mpi=OFF -Duse_coarray=OFF
  -Duse_internal_lhapdf=ON)
COMPILE=(cmake --build "$BUILD" --target ravel_mcfm_amplitudes --parallel "$JOBS")
"${CONFIGURE[@]}"
"${COMPILE[@]}"
test -x "$BUILD/ravel_mcfm_amplitudes"

python3 /opt/ravel/bin/write_mcfm_receipt.py --upstream "$UPSTREAM" --overlay "$OVERLAY" --build "$BUILD" \
  --commit "$COMMIT" --command "$(printf '%q ' "${CONFIGURE[@]}") && $(printf '%q ' "${COMPILE[@]}")"
echo "build receipt: $BUILD/build-receipt.json"
