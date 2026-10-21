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
RAVEL_HOOK_INPUT="$input"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
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
# MCP has its own content-free observation ledger, also when no run exists.
case "$input" in
  *mcp__*)
    if printf '%s' "$input" | "${RAVEL_PYTHON:-python3}" -c 'import json,sys; sys.exit(0 if str(json.load(sys.stdin).get("tool_name", "")).startswith("mcp__") else 1)' 2>/dev/null; then
      if ! printf '%s' "$input" | "${RAVEL_PYTHON:-python3}" -m ravel.workflow.site_tools observe --project "$REPO" >/dev/null 2>&1; then
        ravel_hook_failed posttooluse-observer-mcp
        echo "RAVEL hook unavailable: site-tool observation failed; this session is labelled NOT GOVERNED" >&2
      fi
      exit 0
    fi ;;
esac
"${RAVEL_PYTHON:-python3}" -c 'import ravel.workflow.workflow_state' >/dev/null 2>&1 || {
  ravel_hook_failed posttooluse-observer
  echo "RAVEL hook unavailable: posttooluse-observer cannot import ravel; this session is labelled NOT GOVERNED" >&2
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
