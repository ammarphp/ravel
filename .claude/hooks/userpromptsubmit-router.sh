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
prompt="$(printf '%s' "$input" | "${RAVEL_PYTHON:-python3}" -c 'import sys,json
try: d=json.load(sys.stdin)
except Exception: d={}
print(d.get("prompt") or d.get("user_prompt") or "")')"
session="$(printf '%s' "$input" | "${RAVEL_PYTHON:-python3}" -c 'import sys,json
try: print(json.load(sys.stdin).get("session_id") or "")
except Exception: print("")')"
cwd="$(printf '%s' "$input" | "${RAVEL_PYTHON:-python3}" -c 'import sys,json
try: print(json.load(sys.stdin).get("cwd") or "")
except Exception: print("")')"
[ -z "$prompt" ] && exit 0
# Development prompts and short in-session replies are never routed (host_governance owns the rule).
kind="$(printf '%s' "$prompt" | "${RAVEL_PYTHON:-python3}" -c 'import sys
try:
    from ravel.workflow import host_governance as hg
except Exception:
    print("route"); raise SystemExit
p=sys.stdin.read()
print("development" if hg.development_prompt(p) else "reply" if hg.conversational_reply(p) else "route")')"
[ "$kind" != "route" ] && exit 0
routed="$("${RAVEL_PYTHON:-python3}" -m ravel.workflow.route_prompt --prompt "$prompt" --print)" || {
  echo "RAVEL hook unavailable: userpromptsubmit-router could not route the prompt" >&2
  mkdir -p "$REPO/logs" && printf '%s\n' "userpromptsubmit-router unavailable" >> "$REPO/logs/hook-failures.log"
  exit 0
}
tmode="$(printf '%s' "$routed" | "${RAVEL_PYTHON:-python3}" -c 'import sys,json
try: print(json.load(sys.stdin).get("task_mode") or "")
except Exception: print("")')"
compute="$(printf '%s' "$routed" | "${RAVEL_PYTHON:-python3}" -c 'import sys,json
try:
    c=json.load(sys.stdin)
    print("yes" if c.get("task_mode") not in (None,"unsupported") and c.get("compute_plan") not in (None,"none") else "no")
except Exception: print("no")')"
[ -z "$tmode" ] && exit 0
# Mark the session's own run routed in its ledger (sets run_state.routed). The run
# comes from the R-50 registry (working directory, then session), never the newest run; with no
# run yet this is a no-op and physicist-intake re-asserts once the run exists. Redirected so the
# additionalContext JSON stays the ONLY stdout payload.
rundir="$("${RAVEL_PYTHON:-python3}" -m ravel.workflow.active_run resolve --session "$session" --cwd "$cwd" --repo "$REPO" 2>/dev/null)"
if [ -n "$rundir" ]; then
  "${RAVEL_PYTHON:-python3}" -m ravel.workflow.workflow_state record --kind route --what "$tmode" --rundir "$rundir" >/dev/null 2>&1 || true
fi
# Only a compute-admitting contract leaves a session-keyed marker.
# The PreToolUse guard blocks Agent/Task fan-out until its run has a task contract.
if [ -n "$session" ] && [ "$compute" = "yes" ]; then
  mkdir -p "$REPO/logs" && : > "$REPO/logs/.route-pending-${session}"
fi
reminder="ROUTING (G1): this is a physics request (task_mode=$tmode). Per docs/workflow/start.md, FIRST invoke the physicist-intake skill (it runs route_prompt.py -> a validated task_contract.json, the no-generation survey, cost_preflight, the run scaffold, then CHECK-IN 1). NO heavy compute before the CHECK-IN 1 go-ahead. Do NOT invoke new-analysis/run-scan/run-stage/certify before task_contract.json exists."
"${RAVEL_PYTHON:-python3}" -c 'import json,sys
print(json.dumps({"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":sys.argv[1]}}))' "$reminder"
exit 0
