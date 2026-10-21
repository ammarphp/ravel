#!/usr/bin/env bash
# PreToolUse Bash shim over host_gate.verdict(tool_call), shared with ravel gate.
# All deny verdicts block with the first error message. Registered runs are resolved
# by cwd/session; a classified compute launch with no run is pre_intake even without
# a route marker. The marker still distinguishes routed Claude development sessions
# in the intake/fan-out guards. Exit 2 blocks; tool-call JSON travels through stdin.
set -u
RAVEL_HOOK_INPUT="$(cat)"
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
verdict="$(printf '%s' "$RAVEL_HOOK_INPUT" | "${RAVEL_PYTHON:-python3}" -m ravel.workflow.host_gate --hook bash --project "$REPO" 2>/dev/null)"
case "$verdict" in
  allow) exit 0 ;;
  block:*)
    echo "BLOCKED (pre-exec compute gate): ${verdict#block:}" >&2
    exit 2 ;;
  *)
    # The gate module itself failed: block every command (fail closed) and label the session.
    ravel_hook_failed pretooluse-bash
    echo "BLOCKED (pre-exec compute gate): the gate module is unavailable (python3 -m ravel.workflow.host_gate failed); this session is labelled NOT GOVERNED. Restore the hook interpreter or the installed RAVEL from your own terminal." >&2
    exit 2 ;;
esac
