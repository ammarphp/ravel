#!/usr/bin/env bash
# Build MadAnalysis 5's SampleAnalyzer libraries against the recast environment.
# Usage: build-ma5.sh --ma5 DIR --env ENV
set -euo pipefail
. "$(dirname "$0")/common.sh"
while [ $# -gt 0 ]; do case "$1" in
  --ma5) MA5="$2"; shift 2 ;; --env) ENV="$2"; shift 2 ;; *) ravel_die "unknown argument $1" ;; esac; done
ravel_activate "$ENV"
cd "$MA5"
# --build compiles SampleAnalyzer, --forced answers its questions with the defaults.
printf 'quit\n' | "$ENV/bin/python" bin/ma5 --build --forced
[ -f tools/SampleAnalyzer/Lib/libcommons_for_ma5.so ] || ravel_die "SampleAnalyzer libraries were not built"
