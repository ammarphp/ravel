#!/usr/bin/env bash
# SessionStart orientation (R3/H6): best-effort, ALWAYS exit 0. Injects the active run's state
# summary so a resumed/compacted session re-orients mechanically instead of from prose memory.
set -u
SPINE_HOOK_INPUT="$(cat 2>/dev/null || true)"
export SPINE_HOOK_INPUT
REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
python3 -c "
import glob, json, os, sys
repo = sys.argv[1]
runs = []
for p in glob.glob(os.path.join(repo, 'trial-runs', '*', 'run_state.json')):
    try:
        runs.append((os.path.getmtime(p), p))
    except OSError:
        pass
if not runs:
    raise SystemExit
_, p = max(runs)
try:
    st = json.load(open(p))
except Exception:
    raise SystemExit
rd = os.path.relpath(os.path.dirname(p), repo)
step = st.get('current_step') or '?'
nr = st.get('next_required') or {}
what = nr.get('what') if isinstance(nr, dict) else nr
ctx = ('ACTIVE RUN ' + rd + ': current_step=' + str(step)
       + (('; next_required=' + str(what)) if what else '')
       + ' -- the run-state machine + gates are MANDATORY '
         '(status: python3 trial-runs/_infrastructure/workflow_state.py status --rundir ' + rd
       + '; resume record: ' + rd + '/RESUME.md).')
print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart',
                                          'additionalContext': ctx}}))
" "$REPO" 2>/dev/null || true
exit 0
