#!/usr/bin/env bash
# Build FastJet from the pinned source tree. The conda packages ship the libraries but no
# fastjet-config, which the recast tools query for compile flags.
# Usage: build-fastjet.sh --src DIR --env ENV --out DIR [--jobs N]
set -euo pipefail
. "$(dirname "$0")/common.sh"
JOBS=2
while [ $# -gt 0 ]; do case "$1" in
  --src) SRC="$2"; shift 2 ;; --env) ENV="$2"; shift 2 ;; --out) OUT="$2"; shift 2 ;;
  --jobs) JOBS="$2"; shift 2 ;; *) ravel_die "unknown argument $1" ;; esac; done
[ -e "$OUT/bin/fastjet-config" ] && exit 0   # already built; rerunning the step is a no-op
[ -f "$SRC/configure" ] || ravel_die "no configure script in $SRC"
ravel_activate "$ENV"
partial="$OUT.partial-$$"
(
  cd "$SRC"
  ./configure --prefix="$partial" --enable-allcxxplugins --disable-pyext
  # Tar extraction scrambles timestamps; stop make from rerunning the autotools.
  touch aclocal.m4 configure config.h.in Makefile.in */Makefile.in
  make -j"$(ravel_jobs "$JOBS")" ACLOCAL=: AUTOCONF=: AUTOMAKE=: AUTOHEADER=:
  make install ACLOCAL=: AUTOCONF=: AUTOMAKE=: AUTOHEADER=:
)
# The tree is relocated by the rename, so rewrite the prefix the config script recorded.
sed -i.bak "s#$partial#$OUT#g" "$partial/bin/fastjet-config" && rm -f "$partial/bin/fastjet-config.bak"
ravel_finish "$partial" "$OUT"
