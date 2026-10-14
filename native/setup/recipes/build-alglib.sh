#!/usr/bin/env bash
# Build the ALGLIB free edition (GPL, fetched at install time) as a static library with the
# header layout PhaseTracer's FindALGLIB.cmake expects: include/alglib/*.h and lib/libalglib.a.
# Usage: build-alglib.sh --src DIR --env ENV --out DIR [--jobs N]
set -euo pipefail
. "$(dirname "$0")/common.sh"
JOBS=2
while [ $# -gt 0 ]; do case "$1" in
  --src) SRC="$2"; shift 2 ;; --env) ENV="$2"; shift 2 ;; --out) OUT="$2"; shift 2 ;;
  --jobs) JOBS="$2"; shift 2 ;; *) ravel_die "unknown argument $1" ;; esac; done
[ -e "$OUT/lib/libalglib.a" ] && exit 0   # already built; rerunning the step is a no-op
[ -d "$SRC/src" ] || ravel_die "no src directory in $SRC"
ravel_activate "$ENV"
partial="$OUT.partial-$$"
mkdir -p "$partial/include/alglib" "$partial/lib" "$partial/obj"
cp "$SRC"/src/*.h "$partial/include/alglib/"
ls "$SRC"/src/*.cpp | xargs -P "$(ravel_jobs "$JOBS")" -I{} sh -c \
  '"$1" -std=c++17 -O2 -fPIC -c "$2" -o "$3/$(basename "$2" .cpp).o"' _ "$CXX" {} "$partial/obj"
ar rcs "$partial/lib/libalglib.a" "$partial"/obj/*.o
rm -rf "$partial/obj"
ravel_finish "$partial" "$OUT"
