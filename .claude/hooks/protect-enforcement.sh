#!/usr/bin/env bash
# PreToolUse: the enforcement surface is read-only during a physics session.
# Session detection uses only stdlib records, so a missing ravel import cannot disarm this guard.
set -u
RAVEL_HOOK_INPUT="$(cat)"
export RAVEL_HOOK_INPUT
REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
HOOK_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/src"
[ -d "$REPO/src/ravel" ] && HOOK_SRC="$REPO/src"
[ -d "$HOOK_SRC/ravel" ] && export PYTHONPATH="$HOOK_SRC${PYTHONPATH:+:$PYTHONPATH}"
verdict="$("${RAVEL_PYTHON:-python3}" -c "$(cat <<'PY'
import json, os, runpy, sys
from pathlib import Path
root = Path(sys.argv[2])
module = runpy.run_path(str(root / 'ravel/workflow/host_guards.py'))
try:
    data = json.loads(os.environ.get('RAVEL_HOOK_INPUT') or '{}')
except (ValueError, TypeError):
    data = {}
print(module['enforcement'](data, sys.argv[1]))
PY
)" "$REPO" "$HOOK_SRC")"
status=$?
if [ "$status" -ne 0 ]; then
  # If even stdlib cannot run, refusing the write is the only enforceable result.
  echo "BLOCKED: the RAVEL hook interpreter is unavailable; restore RAVEL_PYTHON." >&2
  exit 2
fi
case "$verdict" in
  block:*)
    echo "BLOCKED (enforcement-surface guard): ${verdict#block:}. Make enforcement changes in a development session." >&2
    exit 2 ;;
  allow) exit 0 ;;
  *) echo "BLOCKED: the enforcement guard returned no usable verdict." >&2; exit 2 ;;
esac
