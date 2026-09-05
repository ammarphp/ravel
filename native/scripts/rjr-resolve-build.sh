#!/usr/bin/env bash
# Build rjr_resolve against native RestFrames + recast ROOT 6.40 (arm64).
#
# Run inside the recast conda env, e.g.:
#   CONDA=stages/01-event-generation/build/tools/miniforge3/bin/conda
#   $CONDA run -n recast bash native/scripts/rjr-resolve-build.sh
#
# Env overrides:
#   RF_PREFIX  -- native RestFrames install prefix (default /tmp/rf_install)
#   OUT        -- output binary path (default native/build/bin/rjr_resolve)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Persistent native RestFrames install (gitignored, regenerable). Override with RF_PREFIX.
REPO="$(cd "$HERE/../.." && pwd)"
source "$REPO/native/scripts/paths.sh"
RF_PREFIX="${RF_PREFIX:-$RAVEL_NATIVE_BUILD/tools/restframes-native}"
OUT="${OUT:-$RAVEL_NATIVE_BIN/rjr_resolve}"

if [ ! -f "$RF_PREFIX/lib/libRestFrames.dylib" ]; then
  echo "ERROR: native RestFrames not found at $RF_PREFIX/lib/libRestFrames.dylib" >&2
  echo "       (re)build it first; see the validation report for the recipe." >&2
  exit 1
fi

mkdir -p "$(dirname "$OUT")"
CXX="$(root-config --cxx)"
echo "Compiler: $CXX"
echo "ROOT:     $(root-config --version) @ $(root-config --prefix)"
echo "RestFrames prefix: $RF_PREFIX"

"$CXX" $(root-config --cflags) \
  -I"$RF_PREFIX/include" \
  "$REPO/native/src/rjr_resolve.cc" \
  -L"$RF_PREFIX/lib" -lRestFrames \
  $(root-config --libs) \
  -Wl,-rpath,"$RF_PREFIX/lib" \
  -Wl,-rpath,"$(root-config --libdir)" \
  -o "$OUT"

echo "Built: $OUT"
