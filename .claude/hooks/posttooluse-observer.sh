#!/usr/bin/env bash
# PostToolUse OBSERVER (L1 keystone). Best-effort, NEVER blocks (always exit 0): parses
# tool_name/tool_input from the hook stdin JSON and appends a ledger entry via workflow_state.py
# record. Mapping (skill|edit|subagent ONLY):
#   Skill                          -> record --kind skill    (skill = tool_input.name)
#   Edit|Write|MultiEdit|Notebook  -> record --kind edit     (path = tool_input.file_path)
#   Agent|Task                     -> record --kind subagent (agent_type = tool_input.subagent_type)
# Bash is deliberately NOT recorded here: the observer cannot know a job's
# bg_kind/logfile/done_condition/next_action, so it must NEVER emit a compute_launched entry -- a
# liveness-blind entry would mislead the Stop DETACH/phantom-bg branches. Every compute_launched
# entry is written instead by the DRIVE step-doc's explicit `workflow_state.py record --kind compute
# ...` (which supplies the N6 fields). Fallback twin: the step docs instruct the agent to run the
# SAME `workflow_state.py record ...` for skill|edit|subagent when the hook is unavailable (see
# check-ins.md).
# The ledger is the session's own run (R-50 registry: working directory, then session id); with
# none, `record --project-dir` keeps its live-lock resolution or no-ops.
input="$(cat)"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
# The project's own package first (as before), else this hook's checkout, else an installed ravel.
HOOK_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/src"
[ -d "$REPO/src/ravel" ] && HOOK_SRC="$REPO/src"
[ -d "$HOOK_SRC/ravel" ] && export PYTHONPATH="$HOOK_SRC${PYTHONPATH:+:$PYTHONPATH}"
# MCP has its own content-free observation ledger, also when no run exists.
case "$input" in
  *mcp__*)
    if printf '%s' "$input" | "${RAVEL_PYTHON:-python3}" -c 'import json,sys; sys.exit(0 if str(json.load(sys.stdin).get("tool_name", "")).startswith("mcp__") else 1)' 2>/dev/null; then
      if ! printf '%s' "$input" | "${RAVEL_PYTHON:-python3}" -m ravel.workflow.site_tools observe --project "$REPO" >/dev/null 2>&1; then
        echo "RAVEL hook unavailable: site-tool observation failed" >&2
        mkdir -p "$REPO/logs" && printf '%s\n' "site-tool observation unavailable" >> "$REPO/logs/hook-failures.log"
      fi
      exit 0
    fi ;;
esac
"${RAVEL_PYTHON:-python3}" -c 'import ravel.workflow.workflow_state' >/dev/null 2>&1 || {
  echo "RAVEL hook unavailable: posttooluse-observer cannot import ravel" >&2
  mkdir -p "$REPO/logs" && printf '%s\n' "posttooluse-observer unavailable: ravel import failed" >> "$REPO/logs/hook-failures.log"
  exit 0
}

out="$(INPUT="$input" "${RAVEL_PYTHON:-python3}" - <<'PY'
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
# Bash is intentionally ignored: a compute_launched entry needs the N6 liveness fields the
# observer cannot supply, so those entries come only from the DRIVE `record --kind compute` command.
PY
)"

[ -n "$out" ] || exit 0
kind="${out%%$'\t'*}"
payload="${out#*$'\t'}"
rundir="$(printf '%s' "$input" | "${RAVEL_PYTHON:-python3}" -c 'import sys,json
from ravel.workflow import active_run
try: d=json.load(sys.stdin)
except Exception: d={}
r=active_run.resolve(d.get("session_id") or "", d.get("cwd") or "", sys.argv[1]) if (d.get("session_id") or d.get("cwd")) else None
print(r or "")' "$PROJECT_DIR" 2>/dev/null)"
if [ -n "$rundir" ] && [ -f "$rundir/run_state.json" ]; then
  "${RAVEL_PYTHON:-python3}" -m ravel.workflow.workflow_state record --rundir "$rundir" --kind "$kind" --payload "$payload" >/dev/null 2>&1 || true
else
  "${RAVEL_PYTHON:-python3}" -m ravel.workflow.workflow_state record --project-dir "$PROJECT_DIR" --kind "$kind" --payload "$payload" >/dev/null 2>&1 || true
fi
exit 0
