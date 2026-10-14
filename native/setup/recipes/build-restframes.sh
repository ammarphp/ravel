#!/usr/bin/env bash
# Build RestFrames from the SimpleAnalysis source tarball and RAVEL's rjr_resolve.
# Usage: build-restframes.sh --tarball FILE --env ENV --out DIR --bin DIR --src DIR
set -euo pipefail
. "$(dirname "$0")/common.sh"
while [ $# -gt 0 ]; do case "$1" in
  --tarball) TARBALL="$2"; shift 2 ;; --env) ENV="$2"; shift 2 ;; --out) OUT="$2"; shift 2 ;;
  --bin) BIN="$2"; shift 2 ;; --src) SRC="$2"; shift 2 ;; *) ravel_die "unknown argument $1" ;; esac; done
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
ravel_activate "$ENV"
mkdir -p "$BIN"
if [ "$(uname -s)" = Darwin ]; then
  # The macOS builder checks architectures and the SDK; it reads the tarball from the prefix.
  [ -d "$OUT" ] || "$ENV/bin/python" -B "$REPO/scripts/run.py" ravel.physics.native_build restframes \
    --prefix "$ENV" --out "$OUT"
  "$ENV/bin/python" -B "$REPO/scripts/run.py" ravel.physics.native_build rjr --prefix "$ENV" \
    --restframes "$OUT" --out "$BIN/rjr_resolve" --replace
  exit 0
fi
if [ ! -d "$OUT" ]; then
  work="$(mktemp -d "${OUT%/*}/.restframes-src.XXXXXX")"
  tar -xzf "$TARBALL" -C "$work"
  src="$(find "$work" -maxdepth 2 -name configure -print -quit)"
  [ -n "$src" ] || ravel_die "no configure script in $TARBALL"
  partial="$OUT.partial-$$"
  (cd "$(dirname "$src")" && ./configure --prefix="$partial" --with-rootsys="$ENV" \
     && make -j"$(ravel_jobs 2)" && make install)
  rm -rf "$work"
  ravel_finish "$partial" "$OUT"
fi
read -r -a RCFLAGS <<< "$("$ENV/bin/root-config" --cflags)"
read -r -a RLIBS <<< "$("$ENV/bin/root-config" --libs)"
"$CXX" "${RCFLAGS[@]}" -I"$OUT/include" "$SRC/rjr_resolve.cc" -L"$OUT/lib" -lRestFrames "${RLIBS[@]}" \
  -Wl,-rpath,"$OUT/lib" -Wl,-rpath,"$ENV/lib" -o "$BIN/.rjr_resolve.partial-$$"
mv "$BIN/.rjr_resolve.partial-$$" "$BIN/rjr_resolve"
