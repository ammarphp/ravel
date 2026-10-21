#!/usr/bin/env bash
# PreToolUse: the enforcement surface is read-only during a physics session.
# Session detection uses only stdlib records, so a missing ravel import cannot disarm this guard.
set -u
RAVEL_HOOK_INPUT="$(cat)"
export RAVEL_HOOK_INPUT
REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
# The guard code is this hook's own checkout, else the installed ravel: a project copy of the
# package never shadows it, and the working directory is never searched for it.
HOOK_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/src"
unset PYTHONHOME PYTHONSTARTUP
export PYTHONSAFEPATH=1
[ -d "$HOOK_SRC/ravel" ] && export PYTHONPATH="$HOOK_SRC${PYTHONPATH:+:$PYTHONPATH}"
# A hook that cannot run its guard records a NOT GOVERNED label for this session and project.
ravel_hook_failed() {
  sid="$(printf '%s' "${RAVEL_HOOK_INPUT:-}" | tr -d '\n' | sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\([A-Za-z0-9._:-]*\)".*/\1/p')"
  ledger="${RAVEL_STATE_DIR:-$HOME/.local/state/ravel}/host-integrity"
  mkdir -p "$ledger" 2>/dev/null && chmod 700 "$ledger" 2>/dev/null
  printf '{"schema_version": 1, "kind": "hook_failure", "hook": "%s", "project": "%s", "session": "%s", "utc": "%s"}\n' \
    "$1" "$(printf '%s' "$REPO" | tr -d '\042\134')" "$sid" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$ledger/events.jsonl" 2>/dev/null
  mkdir -p "$REPO/logs" 2>/dev/null && printf '%s\n' "$1 unavailable: NOT GOVERNED" >> "$REPO/logs/hook-failures.log" 2>/dev/null
  return 0
}
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
  ravel_hook_failed protect-enforcement
  echo "BLOCKED: the RAVEL hook interpreter is unavailable; restore RAVEL_PYTHON." >&2
  exit 2
fi
case "$verdict" in
  block:*)
    echo "BLOCKED (enforcement-surface guard): ${verdict#block:}. Make enforcement changes in a development session." >&2
    exit 2 ;;
  allow) exit 0 ;;
  *) ravel_hook_failed protect-enforcement
     echo "BLOCKED: the enforcement guard returned no usable verdict; this session is labelled NOT GOVERNED." >&2; exit 2 ;;
esac
