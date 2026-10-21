#!/usr/bin/env bash
# MCP admission: fail closed, including unavailable interpreters or policy.
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
verdict="$(printf '%s' "$RAVEL_HOOK_INPUT" | "${RAVEL_PYTHON:-python3}" -m ravel.workflow.site_tools check --hook --project "$REPO" 2>/dev/null)"
case "$verdict" in
  allow) exit 0 ;;
  block:*) echo "BLOCKED (site-tool gate): ${verdict#block:}" >&2; exit 2 ;;
  *) ravel_hook_failed pretooluse-mcp
     echo "BLOCKED (site-tool gate): admission unavailable; this session is labelled NOT GOVERNED. Use RAVEL's governed route (docs/workflow/start.md) and restore the hook interpreter/policy." >&2; exit 2 ;;
esac
