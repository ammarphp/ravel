#!/usr/bin/env bash
# Dependencies must already exist in the supplied prefixes; CMake fetching is disabled.
set -euo pipefail
. "$(dirname "$0")/common.sh"
SRC="" ENV="" HIGGSTOOLS="" OUT="" JOBS=2
while [ $# -gt 0 ]; do
 case "$1" in
  --src) SRC="$2"; shift 2 ;; --env) ENV="$2"; shift 2 ;;
  --higgstools) HIGGSTOOLS="$2"; shift 2 ;; --out) OUT="$2"; shift 2 ;;
  --jobs) JOBS="$2"; shift 2 ;; *) ravel_die "unknown argument: $1" ;;
 esac
done
[ -f "$SRC/CMakeLists.txt" ] || ravel_die "supplied source has no CMakeLists.txt"
[ -d "$HIGGSTOOLS/lib/cmake" ] || ravel_die "HiggsTools CMake prefix is required"
[ ! -e "$OUT" ] || ravel_die "output exists; preserve it before building"
ravel_activate "$ENV"
PARTIAL="$OUT.partial-$$"
cmake -S "$SRC" -B "$SRC/build" -DCMAKE_BUILD_TYPE=Release \
 -DCMAKE_INSTALL_PREFIX="$PARTIAL" -DCMAKE_PREFIX_PATH="$HIGGSTOOLS;$ENV" \
 -DHiggsTools_ROOT="$HIGGSTOOLS" -DFETCHCONTENT_FULLY_DISCONNECTED=ON \
 -DFETCHCONTENT_UPDATES_DISCONNECTED=ON
cmake --build "$SRC/build" --parallel "$JOBS"
cmake --install "$SRC/build"
[ -d "$PARTIAL/bin" ] || ravel_die "scanner install has no executables"
ravel_finish "$PARTIAL" "$OUT"
