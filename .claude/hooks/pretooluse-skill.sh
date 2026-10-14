#!/usr/bin/env bash
# PreToolUse-on-Skill guard (G22/N1): in a physics session whose ACTIVE run has NO task_contract.json
# yet, block any Skill that presupposes an approved contract -- physicist-intake must run FIRST.
# The active run is resolved SESSION-SCOPED by the R-50 registry (ravel.workflow.active_run): from the
# tool-call `cwd` (a directory holding run_state.json, or <repo>/trial-runs/<run>), else from
# `session_id` (the run `ravel initiate`/`plan` registered for this session, or a trial run whose
# run_state.json names it) -- NOT a repo-wide glob and never the newest run. No resolvable active
# run -> block (a physics session must run physicist-intake first). Reads the tool-call JSON on
# stdin; exit 2 blocks. Fallback: docs/workflow/start.md's "fire physicist-intake first".
set -u
input="$(cat)"
REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
# The project's own package first (as before), else this hook's checkout, else an installed ravel.
HOOK_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/src"
[ -d "$REPO/src/ravel" ] && HOOK_SRC="$REPO/src"
[ -d "$HOOK_SRC/ravel" ] && export PYTHONPATH="$HOOK_SRC${PYTHONPATH:+:$PYTHONPATH}"
field() {
  printf '%s' "$input" | "${RAVEL_PYTHON:-python3}" -c 'import sys,json
try: d=json.load(sys.stdin)
except Exception: d={}
ti=d.get("tool_input") or {}
key=sys.argv[1]
v=d.get(key) if key in ("tool_name","session_id","cwd") else (ti.get("skill") or ti.get("name"))
print((v or "").strip())' "$1"
}
tool_name="$(field tool_name)"
skill="$(field skill)"
session="$(field session_id)"
cwd="$(field cwd)"
# yes when the session's active run carries a task contract.
have_contract() {
  "${RAVEL_PYTHON:-python3}" -c 'import sys
from pathlib import Path
try:
    from ravel.workflow import active_run
except Exception:
    print("no"); raise SystemExit
rd=active_run.resolve(sys.argv[1], sys.argv[2], sys.argv[3])
have=rd is not None and any((Path(rd)/x).is_file() for x in ("task_contract.json","inputs/task_contract.json"))
print("yes" if have else "no")' "$session" "$cwd" "$REPO"
}
# Agent/Task fan-out while THIS session's route is pending (physics prompt
# classified, no contract yet) is the 8-agent-survey-before-routing failure. Block until the
# session's run has a contract; consume the marker once it does. KV-7: `ravel initiate` records the
# host session id, so the run it creates is found here and host-spawned subagents unblock.
# Dev sessions (no marker) are never touched.
if [ "$tool_name" = "Agent" ] || [ "$tool_name" = "Task" ]; then
  [ -z "$session" ] && exit 0
  marker="$REPO/logs/.route-pending-${session}"
  [ ! -f "$marker" ] && exit 0
  if [ "$(have_contract)" = "yes" ]; then
    rm -f "$marker"
    exit 0
  fi
  echo "BLOCKED (routing gate): this session's physics request has not been routed yet (no task_contract.json). Invoke the physicist-intake skill FIRST -- it produces the contract + CHECK-IN 1; subagent fan-out (the pre-routing survey failure) unblocks the moment the contract exists." >&2
  exit 2
fi
[ "$tool_name" != "Skill" ] && [ -n "$tool_name" ] && exit 0
[ -z "$skill" ] && exit 0
case "$skill" in
  new-analysis|run-scan|run-stage|certify|route-analysis|verification-panel) ;;
  *) exit 0 ;;
esac
if [ "$(have_contract)" = "no" ]; then
  echo "BLOCKED (G22/N1): the '$skill' skill presupposes an approved task_contract.json for THIS run, but the active run has none yet. Invoke the physicist-intake skill FIRST -- it routes the request, runs the no-generation survey, and composes CHECK-IN 1 (docs/workflow/start.md)." >&2
  exit 2
fi
exit 0
