#!/usr/bin/env bash
# Build SUNDIALS and Nyx (Lyman-alpha executable, MPI + OpenMP) on a Linux site.
# Usage: build-nyx.sh --env ENV --amrex DIR --nyx DIR --sundials DIR --out DIR --jobs N
# The site's MPI wrappers compile both; ENV supplies only CMake and GNU make and is not activated,
# so its compilers never mix with the ones behind the wrappers.
set -euo pipefail
. "$(dirname "$0")/common.sh"
JOBS=2
ENV=""
while [ $# -gt 0 ]; do case "$1" in
  --env) ENV="$2"; shift 2 ;; --amrex) AMREX="$2"; shift 2 ;; --nyx) NYX="$2"; shift 2 ;;
  --sundials) SUN="$2"; shift 2 ;; --out) OUT="$2"; shift 2 ;; --jobs) JOBS="$2"; shift 2 ;;
  *) ravel_die "unknown argument $1" ;; esac; done
command -v mpicxx >/dev/null || ravel_die "an MPI compiler (mpicxx) is required; load the site's MPI module"
CMAKE=cmake; MAKE=make
sundials_tools=()
if [ -n "$ENV" ] && [ -x "$ENV/bin/cmake" ]; then CMAKE="$ENV/bin/cmake"; fi
if [ -n "$ENV" ] && [ -x "$ENV/bin/make" ]; then MAKE="$ENV/bin/make"; sundials_tools+=("-DCMAKE_MAKE_PROGRAM=$MAKE"); fi
# SUNDIALS gets the C compiler behind the same wrappers, so both parts share one OpenMP runtime.
if command -v mpicc >/dev/null; then sundials_tools+=("-DCMAKE_C_COMPILER=$(command -v mpicc)"); fi
partial="$OUT.partial-$$"
mkdir -p "$partial"
# Nyx's makefile names libsundials_core ahead of the solvers that need it. That order resolves only
# against shared libraries, so SUNDIALS is built shared and its libraries find each other by $ORIGIN.
"$CMAKE" -S "$SUN" -B "$partial/sundials-build" -DCMAKE_INSTALL_PREFIX="$partial/sundials" -DCMAKE_INSTALL_LIBDIR=lib \
  -DENABLE_OPENMP=ON -DBUILD_SHARED_LIBS=ON -DBUILD_STATIC_LIBS=OFF -DCMAKE_INSTALL_RPATH='$ORIGIN' \
  -DEXAMPLES_ENABLE_C=OFF -DEXAMPLES_INSTALL=OFF ${sundials_tools[@]+"${sundials_tools[@]}"}
"$CMAKE" --build "$partial/sundials-build" --parallel "$JOBS" --target install
# The makefile's own run path names the build directory, which is renamed below. XTRALIBS is appended
# to the link line (LDFLAGS or LIBRARIES here would replace the makefile's) and names the final place.
"$MAKE" -C "$NYX/Exec/LyA" -j"$JOBS" AMREX_HOME="$AMREX" USE_MPI=TRUE USE_OMP=TRUE USE_SUNDIALS=TRUE \
  SUNDIALS_ROOT="$partial/sundials" SUNDIALS_LIB_DIR="$partial/sundials/lib" XTRALIBS="-Wl,-rpath,$OUT/sundials/lib"
mkdir -p "$partial/bin"
cp "$NYX"/Exec/LyA/Nyx3d.gnu*.MPI.OMP.ex "$partial/bin/Nyx3d.gnu.MPI.OMP.ex"
ravel_finish "$partial" "$OUT"
