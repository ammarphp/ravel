#!/usr/bin/env bash
# Export the installed distribution's CMake prefix without importing restricted modules.
set -euo pipefail
. "$(dirname "$0")/common.sh"
PYTHON="" OUT=""
while [ $# -gt 0 ]; do
 case "$1" in
  --python) PYTHON="$2"; shift 2 ;; --out) OUT="$2"; shift 2 ;;
  *) ravel_die "unknown argument: $1" ;;
 esac
done
[ -x "$PYTHON" ] || ravel_die "isolated interpreter is required"
[ ! -e "$OUT" ] || ravel_die "output exists; preserve it before exporting"
"$PYTHON" - "$OUT" <<'PY'
import importlib.metadata
from pathlib import Path
import shutil
import sys

dist = importlib.metadata.distribution('HiggsTools')
configs = [Path(dist.locate_file(p)) for p in (dist.files or [])
           if p.name.lower() == 'higgstoolsconfig.cmake']
if len(configs) != 1:
    raise SystemExit('Installed source must supply one HiggsTools CMake config; prefix qualification required')
# Export the complete prefix, preserving libraries and headers needed by CMake targets.
config = configs[0]
if config.parent.parent.name != 'cmake' or config.parent.parent.parent.name != 'lib':
    raise SystemExit('CMake prefix layout requires source-specific qualification')
prefix = config.parent.parent.parent.parent
out = Path(sys.argv[1])
shutil.copytree(prefix, out)
PY
