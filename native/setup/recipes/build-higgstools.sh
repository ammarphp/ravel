#!/usr/bin/env bash
# Build under the dedicated interpreter with the existing compiler/dependency prefix.
set -euo pipefail
. "$(dirname "$0")/common.sh"
SRC="" ENV="" PYTHON="" RECEIPT=""
while [ $# -gt 0 ]; do
 case "$1" in
  --src) SRC="$2"; shift 2 ;; --env) ENV="$2"; shift 2 ;; --python) PYTHON="$2"; shift 2 ;;
  --receipt) RECEIPT="$2"; shift 2 ;;
  *) ravel_die "unknown argument: $1" ;;
 esac
done
[ -d "$SRC" ] || ravel_die "verified source is required"
[ -x "$PYTHON" ] || ravel_die "isolated interpreter is required"
case "$PYTHON" in */.venv/bin/*) ravel_die "restricted build cannot use RAVEL's interpreter" ;; esac
ravel_activate "$ENV"
export CMAKE_PREFIX_PATH="$ENV"
"$PYTHON" -m pip install --no-input --no-binary :all: --no-build-isolation "$SRC"
[ -n "$RECEIPT" ] || ravel_die "installation receipt path is required"
"$PYTHON" - "$RECEIPT" <<'PY'
import importlib.metadata
import json
from pathlib import Path
import sys
Path(sys.argv[1]).write_text(json.dumps({'version': importlib.metadata.version('HiggsTools')}) + '\n')
PY
