#!/usr/bin/env bash
# PostToolUse guard (D15 / G17, moment-of-change): after an Edit/Write to a CHECK-IN-1-baselined
# input file, BLOCK the turn (exit 2) unless the run's DEVIATIONS.md names the changed file. The
# belt-and-suspenders twin of validate_run_state's inv_deviations_on_change (the post-hoc half).
# Reads the tool-call JSON on stdin; extracts the edited path with python3 (not greedy grep).
input="$(cat)"
RAVEL_HOOK_INPUT="$input"
path="$(printf '%s' "$input" | "${RAVEL_PYTHON:-python3}" -c 'import json,sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
ti = d.get("tool_input") or {}
print(ti.get("file_path") or ti.get("path") or "")')"
[ -z "$path" ] && exit 0
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
"${RAVEL_PYTHON:-python3}" -c 'import ravel.validation.validate_run_state' >/dev/null 2>&1 || {
  # The edit has happened; the host allows only reporting it, so report and label (fail closed).
  ravel_hook_failed deviations-guard
  echo "RAVEL hook unavailable: deviations-guard cannot import ravel; this edit was not checked and the session is labelled NOT GOVERNED" >&2
  exit 2
}
if "${RAVEL_PYTHON:-python3}" -m ravel.validation.validate_run_state --edit-guard "$path"; then
  exit 0            # exit 0 from --edit-guard == allow
else
  exit 2            # --edit-guard returned 1 (block); its reason is already on stderr -> map to hook block
fi
