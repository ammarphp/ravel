#!/usr/bin/env bash
# SessionStart orientation: best-effort, ALWAYS exit 0. Injects the state summary of THIS
# session's active run so a resumed/compacted session re-orients mechanically instead of from prose
# memory. The run comes from the R-50 registry (working directory, then session id); a session with
# no run of its own gets nothing -- never another session's newest run.
set -u
RAVEL_HOOK_INPUT="$(cat 2>/dev/null || true)"
export RAVEL_HOOK_INPUT
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
  ravel_hook_failed sessionstart-orient
  echo "RAVEL hook unavailable: sessionstart-orient cannot orient this session; it is labelled NOT GOVERNED" >&2
}
exit 0
