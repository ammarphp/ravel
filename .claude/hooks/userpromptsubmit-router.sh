#!/usr/bin/env bash
# UserPromptSubmit router (G1): on a PHYSICS prompt, run the deterministic route_prompt.py and inject
# the INITIATE reminder as additionalContext. Non-blocking (exit 0) -- the hard blocks live in the
# PreToolUse-Skill guard (G22) and the pre-generate guard. Fallback: workflow/INITIATE.md itself.
set -u
input="$(cat)"
REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
prompt="$(printf '%s' "$input" | python3 -c 'import sys,json
try: d=json.load(sys.stdin)
except Exception: d={}
print(d.get("prompt") or d.get("user_prompt") or "")')"
session="$(printf '%s' "$input" | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("session_id") or "")
except Exception: print("")')"
[ -z "$prompt" ] && exit 0
# Conservative physics-prompt pre-gate (never nag a dev/ops prompt).
if ! printf '%s' "$prompt" | grep -qiE 'initiate:|reproduc|reinterpret|exclud|arxiv|atlas|cms|figure [0-9]|mass.?plane|scan|limit on|summary.?plot|is .* excluded|sensitiv'; then
  exit 0
fi
routed="$(python3 "$REPO/trial-runs/_infrastructure/route_prompt.py" --prompt "$prompt" --print 2>&1)"
tmode="$(printf '%s' "$routed" | python3 -c 'import sys,re
t=sys.stdin.read()
m=re.search(r"task_mode=(\S+)",t) or re.search(r"\"task_mode\":\s*\"([^\"]+)\"",t)
print(m.group(1) if m else "")')"
case "$tmode" in
  reproduce|reinterpret|scan|summary_plot|projection|anomaly_search|survey|no_routine|unsupported)
    # RECONCILE D-3: route_prompt.py succeeded -> mark the run routed in the ledger (sets
    # run_state.routed). Best-effort + session-scoped so it never clobbers an unrelated run;
    # physicist-intake re-asserts once the run scaffold exists. Redirected so the additionalContext
    # JSON stays the ONLY stdout payload. cmd_record resolves the active rundir via find_active_rundir;
    # a fresh prompt with no active run self-scopes to a harmless no-op (return 0). p1's record CLI has
    # NO --session flag, so we pass --project-dir (D-3 / re-verify RR4 fix).
    python3 "$REPO/trial-runs/_infrastructure/workflow_state.py" record --kind route \
      --project-dir "$REPO" >/dev/null 2>&1 || true
    # A3 (trial QA.1): leave a session-keyed route-pending marker; the PreToolUse guard blocks
    # Agent/Task fan-out for THIS session until a task_contract.json exists (then consumes it).
    if [ -n "$session" ]; then
      mkdir -p "$REPO/logs" && : > "$REPO/logs/.route-pending-${session}"
    fi
    reminder="ROUTING (G1): this is a physics request (task_mode=$tmode). Per workflow/INITIATE.md, FIRST invoke the physicist-intake skill (it runs route_prompt.py -> a validated task_contract.json, the no-generation survey, cost_preflight, the run scaffold, then CHECK-IN 1). NO heavy compute before the CHECK-IN 1 go-ahead. Do NOT invoke new-analysis/run-scan/run-stage/certify before task_contract.json exists."
    python3 -c 'import json,sys
print(json.dumps({"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":sys.argv[1]}}))' "$reminder"
    ;;
esac
exit 0
