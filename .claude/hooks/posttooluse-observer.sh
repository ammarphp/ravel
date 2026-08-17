#!/usr/bin/env bash
# PostToolUse OBSERVER (L1 keystone). Best-effort, NEVER blocks (always exit 0): parses
# tool_name/tool_input from the hook stdin JSON and appends a ledger entry via workflow_state.py
# record. Mapping (skill|edit|subagent ONLY):
#   Skill                          -> record --kind skill    (skill = tool_input.name)
#   Edit|Write|MultiEdit|Notebook  -> record --kind edit     (path = tool_input.file_path)
#   Agent|Task                     -> record --kind subagent (agent_type = tool_input.subagent_type)
# Bash is deliberately NOT recorded here (D-2): the observer cannot know a job's
# bg_kind/logfile/done_condition/next_action, so it must NEVER emit a compute_launched entry -- a
# liveness-blind entry would mislead the Stop DETACH/phantom-bg branches. Every compute_launched
# entry is written instead by the DRIVE step-doc's explicit `workflow_state.py record --kind compute
# ...` (which supplies the N6 fields). Fallback twin: the step docs instruct the agent to run the
# SAME `workflow_state.py record ...` for skill|edit|subagent when the hook is unavailable (see
# check-ins.md).
input="$(cat)"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
WS="$PROJECT_DIR/trial-runs/_infrastructure/workflow_state.py"
[ -f "$WS" ] || exit 0

out="$(INPUT="$input" python3 - <<'PY'
import json, os, sys
try:
    d = json.loads(os.environ.get("INPUT", ""))
except Exception:
    sys.exit(0)
name = d.get("tool_name") or ""
ti = d.get("tool_input") or {}
def emit(kind, payload):
    print(kind + "\t" + json.dumps(payload))
if name == "Skill":
    sk = ti.get("name") or ti.get("skill") or ti.get("command") or ""
    if sk:
        emit("skill", {"skill": sk})
elif name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
    p = ti.get("file_path") or ti.get("notebook_path") or ""
    if p:
        emit("edit", {"path": p})
elif name in ("Agent", "Task"):
    emit("subagent", {"agent_type": ti.get("subagent_type") or ti.get("agent_type") or ""})
# Bash is intentionally ignored (D-2): a compute_launched entry needs the N6 liveness fields the
# observer cannot supply, so those entries come only from the DRIVE `record --kind compute` command.
PY
)"

[ -n "$out" ] || exit 0
kind="${out%%$'\t'*}"
payload="${out#*$'\t'}"
python3 "$WS" record --project-dir "$PROJECT_DIR" --kind "$kind" --payload "$payload" >/dev/null 2>&1 || true
exit 0
