#!/usr/bin/env bash
# Build GM2Calc and PhaseTracer with CMake and record EasyScan's engine paths.
# Usage: build-easyscan-engines.sh --env ENV --gm2calc DIR --phasetracer DIR --easyscan DIR
#                                  --alglib DIR --manifest FILE --jobs N
set -euo pipefail
. "$(dirname "$0")/common.sh"
JOBS=2
ALGLIB=""
while [ $# -gt 0 ]; do case "$1" in
  --env) ENV="$2"; shift 2 ;; --gm2calc) GM2="$2"; shift 2 ;; --phasetracer) PT="$2"; shift 2 ;;
  --easyscan) ES="$2"; shift 2 ;; --alglib) ALGLIB="$2"; shift 2 ;; --manifest) MANIFEST="$2"; shift 2 ;; --jobs) JOBS="$2"; shift 2 ;;
  *) ravel_die "unknown argument $1" ;; esac; done
[ -f "$ALGLIB/lib/libalglib.a" ] || ravel_die "ALGLIB is not built at $ALGLIB"
ravel_activate "$ENV"
for tree in "$GM2" "$PT"; do
  cmake -S "$tree" -B "$tree/build" -DCMAKE_PREFIX_PATH="$ENV" -DCMAKE_BUILD_TYPE=Release \
    -DALGLIB_INCLUDES="$ALGLIB/include/alglib" -DALGLIB_LIBRARIES="$ALGLIB/lib/libalglib.a"
  cmake --build "$tree/build" --parallel "$JOBS"
done
[ -x "$GM2/build/bin/gm2calc.x" ] || ravel_die "GM2Calc was not built"
mkdir -p "$(dirname "$MANIFEST")"
cat > "$MANIFEST.partial-$$" <<JSON
{
  "easyscan": "$ES",
  "gm2calc": "$GM2/build/bin/gm2calc.x",
  "phasetracer_build": "$PT/build"
}
JSON
mv "$MANIFEST.partial-$$" "$MANIFEST"
