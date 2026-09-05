#!/usr/bin/env bash
# PreToolUse-on-Skill guard (G22/N1): in a physics session whose ACTIVE run has NO task_contract.json
# yet, block any Skill that presupposes an approved contract -- physicist-intake must run FIRST.
# The active run is resolved SESSION-SCOPED (RECONCILE / R8-critical): from the tool-call `cwd` if it
# sits inside a trial-runs/<rundir> tree, else from `session_id` via that run's run_state.json -- NOT
# a repo-wide glob (a mature repo carries many old trial-runs/*/inputs/task_contract.json that would
# mask a fresh run and leave G22 permanently dead). No resolvable active run -> block (a physics
# session must run physicist-intake first). Reads the tool-call JSON on stdin; exit 2 blocks.
# Fallback: docs/workflow/start.md's "fire physicist-intake first".
set -u
input="$(cat)"
REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
tool_name="$(printf '%s' "$input" | python3 -c 'import sys,json
try: print((json.load(sys.stdin).get("tool_name") or "").strip())
except Exception: print("")')"
skill="$(printf '%s' "$input" | python3 -c 'import sys,json
try: d=json.load(sys.stdin)
except Exception: d={}
ti=d.get("tool_input") or {}
print((ti.get("skill") or ti.get("name") or "").strip())')"
session_for_marker="$(printf '%s' "$input" | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("session_id") or "")
except Exception: print("")')"
# A3 (trial QA.1): Agent/Task fan-out while THIS session's route is pending (physics prompt
# classified, no contract yet) is the 8-agent-survey-before-routing failure. Block until the
# contract exists; consume the marker once it does. Dev sessions (no marker) are never touched.
if [ "$tool_name" = "Agent" ] || [ "$tool_name" = "Task" ]; then
  marker="$REPO/logs/.route-pending-${session_for_marker}"
  [ -z "$session_for_marker" ] && exit 0
  [ ! -f "$marker" ] && exit 0
  have_contract_a3="$(printf '%s' "$input" | python3 -c 'import sys,json,os,glob
try: d=json.load(sys.stdin)
except Exception: d={}
repo=sys.argv[1]
session=(d.get("session_id") or "")
tr=os.path.join(repo,"trial-runs")
rd=None
for p in glob.glob(os.path.join(tr,"*","run_state.json")):
    try:
        if json.load(open(p)).get("session_id")==session: rd=os.path.dirname(p); break
    except Exception: pass
have=bool(rd) and any(os.path.isfile(os.path.join(rd,x))
                      for x in ("task_contract.json", os.path.join("inputs","task_contract.json")))
print("yes" if have else "no")' "$REPO")"
  if [ "$have_contract_a3" = "yes" ]; then
    rm -f "$marker"
    exit 0
  fi
  echo "BLOCKED (A3/N8): this session's physics request has not been routed yet (no task_contract.json). Invoke the physicist-intake skill FIRST -- it produces the contract + CHECK-IN 1; subagent fan-out (the pre-routing survey failure, trial QA.1) unblocks the moment the contract exists." >&2
  exit 2
fi
[ "$tool_name" != "Skill" ] && [ -n "$tool_name" ] && exit 0
[ -z "$skill" ] && exit 0
case "$skill" in
  new-analysis|run-scan|run-stage|certify|route-analysis|verification-panel) ;;
  *) exit 0 ;;
esac
have_contract="$(printf '%s' "$input" | python3 -c 'import sys,json,os,glob
try: d=json.load(sys.stdin)
except Exception: d={}
repo=sys.argv[1]
cwd=(d.get("cwd") or "")
session=(d.get("session_id") or "")
tr=os.path.join(repo,"trial-runs")

def rundir_from_cwd(cwd):
    if not cwd: return None
    cwd=os.path.abspath(cwd)
    if cwd==tr or cwd.startswith(tr+os.sep):
        rest=os.path.relpath(cwd,tr).split(os.sep)
        if rest and rest[0] not in (".",".."): return os.path.join(tr,rest[0])
    return None

def rundir_from_session(session):
    if not session: return None
    for p in glob.glob(os.path.join(tr,"*","run_state.json")):
        try:
            if json.load(open(p)).get("session_id")==session: return os.path.dirname(p)
        except Exception: pass
    return None

rd=rundir_from_cwd(cwd) or rundir_from_session(session)
have=bool(rd) and any(os.path.isfile(os.path.join(rd,x))
                      for x in ("task_contract.json", os.path.join("inputs","task_contract.json")))
print("yes" if have else "no")' "$REPO")"
if [ "$have_contract" = "no" ]; then
  echo "BLOCKED (G22/N1): the '$skill' skill presupposes an approved task_contract.json for THIS run, but the active run has none yet. Invoke the physicist-intake skill FIRST -- it routes the request, runs the no-generation survey, and composes CHECK-IN 1 (docs/workflow/start.md)." >&2
  exit 2
fi
exit 0
