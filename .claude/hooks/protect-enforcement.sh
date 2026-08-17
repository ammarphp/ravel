#!/usr/bin/env bash
# PreToolUse guard (R3/H3, catalogue N9): during a PHYSICS session (route-pending marker for this
# session, or a session-scoped run_state), the ENFORCEMENT SURFACE is read-only -- an agent that
# finds a gate inconvenient must not be able to disarm it mid-run. Dev sessions are untouched.
# Input JSON travels via env var (a heredoc would swallow piped stdin).
set -u
SPINE_HOOK_INPUT="$(cat)"
export SPINE_HOOK_INPUT
REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
verdict="$(python3 -c "
import json, os, re, sys, glob
try:
    d = json.loads(os.environ.get('SPINE_HOOK_INPUT') or '{}')
except Exception:
    print('allow'); raise SystemExit
ti = d.get('tool_input') or {}
path = ti.get('file_path') or ti.get('notebook_path') or ''
if not path:
    print('allow'); raise SystemExit
p = os.path.abspath(path)
ENF = re.compile(r'/\.claude/settings\.json$|/\.claude/hooks/|/framework/spine_sim/'
                 r'|/framework/green_board\.py$|/Makefile$'
                 r'|/trial-runs/_infrastructure/(validate_run_state|stop_dispatch|workflow_state'
                 r'|validate_checkin|validate_parameters|provenance|stage_supervisor'
                 r'|preflight_watcher|resource_census|verify_pack|figure_target|lhe_check)\.py$')
if not ENF.search(p):
    print('allow'); raise SystemExit
repo = sys.argv[1]
session = d.get('session_id') or ''
physics = False
if session and os.path.isfile(os.path.join(repo, 'logs', '.route-pending-' + session)):
    physics = True
if not physics and session:
    for rp in glob.glob(os.path.join(repo, 'trial-runs', '*', 'run_state.json')):
        try:
            if json.load(open(rp)).get('session_id') == session:
                physics = True; break
        except Exception:
            pass
print('block' if physics else 'allow')
" "$REPO")"
if [ "$verdict" = "block" ]; then
  echo "BLOCKED (R3/H3, catalogue N9): the enforcement surface (settings/hooks/gate tools) is read-only during a physics run -- disarming a gate mid-run IS the failure class, not a workaround. Make enforcement changes in a dev session." >&2
  exit 2
fi
exit 0
