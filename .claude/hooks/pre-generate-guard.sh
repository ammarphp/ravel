#!/usr/bin/env bash
# D7 PREVENT (G9): before a MadGraph/shower launch, block if a declared BSM/HV model has no fetched
# generation recipe. Best-effort hook; the authoritative half is the steps/03-generate.md gate.
set -uo pipefail
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HOOK_DIR/../.." && pwd)"
input="$(cat)"
RAVEL_HOOK_INPUT="$input"
cmd="$(printf '%s' "$input" | "${RAVEL_PYTHON:-python3}" -c 'import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    d = {}
print((d.get("tool_input") or {}).get("command", "") or "")')"
[ -z "$cmd" ] && exit 0
# The guard code is this hook's own checkout, else the installed ravel: a project copy of the
# package never shadows it, and the working directory is never searched for it.
HOOK_SRC="$REPO/src"
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
"${RAVEL_PYTHON:-python3}" -m ravel.workflow.resource_census \
    --pre-generate-hook --command "$cmd" --project-dir "${CLAUDE_PROJECT_DIR:-$REPO}"
status=$?
[ "$status" -eq 0 ] && exit 0
if [ "$status" -ne 2 ]; then
  # The guard could not run: hold the launch (fail closed) and label the session.
  ravel_hook_failed pre-generate-guard
  echo "BLOCKED: the pre-generation guard is unavailable; this session is labelled NOT GOVERNED." >&2
fi
exit 2
