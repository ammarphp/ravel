#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Queued native build only. Source decisions and model packages are supplied;
# no release, coupling convention or physics parameter point is built in.
# The source preflight is the installer step before this one; this recipe takes no interpreter.
set -euo pipefail
. "$(dirname "$0")/common.sh"
SRC= ENV= DECISION= JOBS=1
while [ $# -gt 0 ]; do case "$1" in
  --src) SRC="$2"; shift 2 ;;
  --env) ENV="$2"; shift 2 ;;
  --decision) DECISION="$2"; shift 2 ;;
  --jobs) JOBS="$2"; shift 2 ;;
  *) ravel_die "unknown argument $1" ;;
esac; done
[ -n "$SRC" ] && [ -n "$ENV" ] && [ -n "$DECISION" ] || ravel_die "source, environment and decision required"
case "$JOBS" in ''|*[!0-9]*|0) ravel_die "positive build job count required" ;; esac
ravel_activate "$ENV"
[ -f "$ENV/include/X11/Xlib.h" ] || ravel_die "conda X11 headers required; GUI is not invoked"
[ -f "$DECISION" ] || ravel_die "source decision record missing: $DECISION"
export CPPFLAGS="-I$ENV/include ${CPPFLAGS:-}" LDFLAGS="-L$ENV/lib ${LDFLAGS:-}"
# Installation uses the existing setup group executor. Per-model compilation
# is declared as a supplied programme in an admitted EasyScan stage.
make -C "$SRC" -j "$JOBS"
[ -f "$SRC/sources/micromegas.a" ] || ravel_die "micrOMEGAs library missing"
[ -x "$SRC/CalcHEP_src/bin/s_calchep" ] || ravel_die "CalcHEP batch executable missing"
