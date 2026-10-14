#!/usr/bin/env bash
# Build Contur's analysis database inside the prefix (CONTUR_USER_DIR).
# Usage: build-contur-data.sh --env ENV --user-dir DIR
set -euo pipefail
. "$(dirname "$0")/common.sh"
while [ $# -gt 0 ]; do case "$1" in
  --env) ENV="$2"; shift 2 ;; --user-dir) USERDIR="$2"; shift 2 ;; *) ravel_die "unknown argument $1" ;; esac; done
ravel_activate "$ENV"
export CONTUR_USER_DIR="$USERDIR"
mkdir -p "$USERDIR"
DATA="$("$ENV/bin/python" -c 'import contur.config.paths as p; print(p.data_path())' 2>/dev/null || true)"
if [ -z "$DATA" ] || [ ! -d "$DATA" ]; then
  DATA="$("$ENV/bin/python" -c 'import contur, os; print(os.path.join(os.path.dirname(contur.__file__), "data"))')"
fi
export CONTUR_DATA_PATH="$DATA"
if [ -f "$ENV/bin/conturenv.sh" ]; then set +u; . "$ENV/bin/conturenv.sh"; set -u; fi
make -C "$CONTUR_DATA_PATH" -j"$(ravel_jobs 2)"
date -u +%Y-%m-%dT%H:%M:%SZ > "$USERDIR/.ravel-contur-data-built"
