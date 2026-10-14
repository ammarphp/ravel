#!/usr/bin/env bash
# Generate and build FlexibleSUSY spectrum generators, one source tree per model.
# Model code is generated from SARAH with your licensed Wolfram kernel.
# Usage: build-flexiblesusy.sh --source DIR --sarah DIR --env ENV --out DIR --models A,B --jobs N
set -euo pipefail
. "$(dirname "$0")/common.sh"
JOBS=2
while [ $# -gt 0 ]; do case "$1" in
  --source) FS="$2"; shift 2 ;; --sarah) SARAH="$2"; shift 2 ;; --env) ENV="$2"; shift 2 ;;
  --out) OUT="$2"; shift 2 ;; --models) MODELS="$2"; shift 2 ;; --jobs) JOBS="$2"; shift 2 ;;
  *) ravel_die "unknown argument $1" ;; esac; done
WS="$(bash "$(dirname "$0")/find-wolframscript.sh")" || ravel_die "no activated Wolfram kernel found"
# wolframscript may be a symlink or a launcher whose folder holds no kernel; look beside it, then in the installed applications.
MATH_CMD=""
real_ws="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$WS")"
for dir in "$(dirname "$WS")" "$(dirname "$real_ws")" /Applications/Wolfram*.app/Contents/MacOS /Applications/Mathematica*.app/Contents/MacOS; do
  for name in WolframKernel math MathKernel; do
    [ -x "$dir/$name" ] && [ -z "$MATH_CMD" ] && MATH_CMD="$dir/$name"
  done
done
[ -n "$MATH_CMD" ] || ravel_die "no Wolfram kernel executable (WolframKernel or math) found beside $WS or in /Applications"
ravel_activate "$ENV"
mkdir -p "$OUT"
# FlexibleSUSY loads SARAH with Needs["SARAH`"] through the kernel's own $Path. A small wrapper puts the pinned
# SARAH directory on $Path for this build only; no init.m or other Wolfram setting is written.
KERNEL_DIR="$OUT/.kernel"
mkdir -p "$KERNEL_DIR"
printf 'PrependTo[$Path, "%s"];\n' "$SARAH" > "$KERNEL_DIR/sarah-path.m"
printf '#!/bin/sh\nexec "%s" -initfile "%s" "$@"\n' "$MATH_CMD" "$KERNEL_DIR/sarah-path.m" > "$KERNEL_DIR/math"
chmod +x "$KERNEL_DIR/math"
MATH_CMD="$KERNEL_DIR/math"
IFS=, read -r -a LIST <<< "$MODELS"
for model in "${LIST[@]}"; do
  final="$OUT/$model"
  [ -x "$final/models/$model/run_$model.x" ] && continue
  partial="$final.partial-$$"
  mkdir -p "$partial"
  git -C "$FS" archive HEAD | tar -x -C "$partial"
  (
    cd "$partial"
    ./createmodel --name="$model" --with-math-cmd="$MATH_CMD"
    ./configure --with-models="$model" --with-solvers=two_scale --with-math-cmd="$MATH_CMD" \
      --with-cxx="$ENV/bin/clang++" --with-fc="$ENV/bin/gfortran" \
      --with-boost-incdir="$ENV/include" --with-eigen-incdir="$ENV/include/eigen3" \
      --with-gsl-config="$ENV/bin/gsl-config" --disable-librarylink --disable-threads \
      "--with-cxxflags=-std=c++17 -O2 -fPIC"
    make -j"$JOBS" "models/$model/run_$model.x"
  )
  ravel_finish "$partial" "$final"
done
