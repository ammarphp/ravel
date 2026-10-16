#!/usr/bin/env bash
# UserPromptSubmit router (G1, R-50 item 3): run the deterministic intake router on every prompt that
# is not a development request, and inject the INITIATE reminder as additionalContext. There is no
# lexical physics pre-gate: calculation, research and method-study prompts route too. A development
# prompt (a brief naming a worktree, branch, owned files or acceptance tests; a code task) and a
# short reply inside a session ("yes", "go ahead") stay silent and leave no route-pending marker.
# Non-blocking (exit 0) -- the hard blocks live in the PreToolUse guards. Fallback: docs/workflow/start.md.
set -u
input="$(cat)"
REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
# The project's own package first (as before), else this hook's checkout, else an installed ravel.
HOOK_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/src"
[ -d "$REPO/src/ravel" ] && HOOK_SRC="$REPO/src"
[ -d "$HOOK_SRC/ravel" ] && export PYTHONPATH="$HOOK_SRC${PYTHONPATH:+:$PYTHONPATH}"
"${RAVEL_PYTHON:-python3}" -c 'import ravel.workflow.route_prompt, ravel.workflow.host_governance' >/dev/null 2>&1 || {
  echo "RAVEL hook unavailable: userpromptsubmit-router cannot import ravel" >&2
  mkdir -p "$REPO/logs" && printf '%s\n' "userpromptsubmit-router unavailable: ravel import failed" >> "$REPO/logs/hook-failures.log"
  exit 0
}
if ! printf '%s' "$input" | "${RAVEL_PYTHON:-python3}" -m ravel.workflow.host_guards --host claude --phase prompt --project "$REPO"; then
  echo "RAVEL hook unavailable: userpromptsubmit-router could not route the prompt" >&2
  mkdir -p "$REPO/logs" && printf '%s\n' "userpromptsubmit-router unavailable" >> "$REPO/logs/hook-failures.log"
fi
exit 0
