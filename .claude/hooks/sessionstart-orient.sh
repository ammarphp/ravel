#!/usr/bin/env bash
# SessionStart orientation: best-effort, ALWAYS exit 0. Injects the state summary of THIS
# session's active run so a resumed/compacted session re-orients mechanically instead of from prose
# memory. The run comes from the R-50 registry (working directory, then session id); a session with
# no run of its own gets nothing -- never another session's newest run.
set -u
RAVEL_HOOK_INPUT="$(cat 2>/dev/null || true)"
export RAVEL_HOOK_INPUT
REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
# The project's own package first (as before), else this hook's checkout, else an installed ravel.
HOOK_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/src"
[ -d "$REPO/src/ravel" ] && HOOK_SRC="$REPO/src"
[ -d "$HOOK_SRC/ravel" ] && export PYTHONPATH="$HOOK_SRC${PYTHONPATH:+:$PYTHONPATH}"
"${RAVEL_PYTHON:-python3}" -c "
import json, os, sys
from ravel.workflow import active_run
repo = sys.argv[1]
try:
    d = json.loads(os.environ.get('RAVEL_HOOK_INPUT') or '{}')
except Exception:
    d = {}
rd = active_run.resolve(d.get('session_id') or '', d.get('cwd') or '', repo)
if rd is None:
    raise SystemExit
try:
    st = json.load(open(os.path.join(rd, 'run_state.json')))
except Exception:
    raise SystemExit
try:
    shown = os.path.relpath(rd, repo)
except ValueError:
    shown = str(rd)
if shown.startswith('..'):
    shown = str(rd)
step = st.get('current_step') or '?'
nr = st.get('next_required') or {}
what = nr.get('what') if isinstance(nr, dict) else nr
ctx = ('ACTIVE RUN ' + shown + ': current_step=' + str(step)
       + (('; next_required=' + str(what)) if what else '')
       + ' -- the run-state machine + gates are MANDATORY '
         '(status: ravel status --rundir ' + shown + ' --write'
       + '; resume record: ' + shown + '/RESUME.md).')
print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart',
                                          'additionalContext': ctx}}))
" "$REPO" 2>/dev/null || {
  echo "RAVEL hook unavailable: sessionstart-orient cannot orient this session" >&2
  mkdir -p "$REPO/logs" && printf '%s\n' "sessionstart-orient unavailable" >> "$REPO/logs/hook-failures.log"
}
exit 0
