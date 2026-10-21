#!/usr/bin/env bash
# Stop-hook dispatcher shim -- pipes the Stop JSON to ravel.workflow.stop_dispatch (the branch brain).
# The run comes from the R-50 registry (working directory, then session id), never the newest run.
# exit 2 blocks turn-end (stderr reason fed back to the agent); exit 0 allows. A dispatcher that cannot
# import holds the first stop, allows a repeated one and labels the session NOT GOVERNED.
input="$(cat)"
RAVEL_HOOK_INPUT="$input"
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
"${RAVEL_PYTHON:-python3}" -c 'import ravel.workflow.stop_dispatch' >/dev/null 2>&1 || {
  ravel_hook_failed stop-dispatcher
  echo "RAVEL hook unavailable: stop-dispatcher cannot import ravel; delivery gates were not applied and this session is labelled NOT GOVERNED" >&2
  # Hold the first stop so the agent sees it; a repeated stop is allowed, so the turn cannot loop.
  case "$input" in *'"stop_hook_active": true'*|*'"stop_hook_active":true'*) exit 0 ;; esac
  exit 2
}
printf '%s' "$input" | "${RAVEL_PYTHON:-python3}" -m ravel.workflow.stop_dispatch
exit $?
