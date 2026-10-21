#!/usr/bin/env bash
# UserPromptSubmit router (G1, R-50 item 3): run the deterministic intake router on every prompt that
# is not a development request, and inject the INITIATE reminder as additionalContext. There is no
# lexical physics pre-gate: calculation, research and method-study prompts route too. A development
# prompt (a brief naming a worktree, branch, owned files or acceptance tests; a code task) and a
# short reply inside a session ("yes", "go ahead") stay silent and leave no route-pending marker.
# Routing itself never blocks a prompt (exit 0); a router that cannot run blocks it (exit 2) and labels
# the session NOT GOVERNED. The hard blocks live in the PreToolUse guards. Fallback: docs/workflow/start.md.
set -u
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
"${RAVEL_PYTHON:-python3}" -c 'import ravel.workflow.route_prompt, ravel.workflow.host_governance' >/dev/null 2>&1 || {
  ravel_hook_failed userpromptsubmit-router
  echo "BLOCKED: RAVEL prompt routing is unavailable (userpromptsubmit-router cannot import ravel); this session is labelled NOT GOVERNED. Restore the hook interpreter or the installed RAVEL from your own terminal." >&2
  exit 2
}
if ! printf '%s' "$input" | "${RAVEL_PYTHON:-python3}" -m ravel.workflow.host_guards --host claude --phase prompt --project "$REPO"; then
  ravel_hook_failed userpromptsubmit-router
  echo "BLOCKED: RAVEL prompt routing failed for this prompt; this session is labelled NOT GOVERNED." >&2
  exit 2
fi
exit 0
