#!/usr/bin/env bash
# Compile pythia_shower and pythia_shower_merged against the rivet environment.
# Usage: build-shower.sh --env ENV --src DIR --out BIN
set -euo pipefail
. "$(dirname "$0")/common.sh"
while [ $# -gt 0 ]; do case "$1" in
  --env) ENV="$2"; shift 2 ;; --src) SRC="$2"; shift 2 ;; --out) OUT="$2"; shift 2 ;;
  *) ravel_die "unknown argument $1" ;; esac; done
ravel_activate "$ENV"
mkdir -p "$OUT"
read -r -a PYFLAGS <<< "$("$ENV/bin/pythia8-config" --cxxflags --libs)"
read -r -a HMFLAGS <<< "$("$ENV/bin/HepMC3-config" --cflags --libs)"
for name in pythia_shower pythia_shower_merged; do
  partial="$OUT/.$name.partial-$$"
  echo "building $name"
  "$CXX" -std=c++17 -O2 ${CXXFLAGS:-} "$SRC/$name.cc" "${PYFLAGS[@]}" "${HMFLAGS[@]}" \
    -Wl,-rpath,"$ENV/lib" ${LDFLAGS:-} -o "$partial"
  rm -f "$OUT/$name"
  mv "$partial" "$OUT/$name"
done
