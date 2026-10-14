#!/usr/bin/env bash
# PreToolUse: the enforcement surface is read-only during a physics session.
# Session detection uses only stdlib records, so a missing ravel import cannot disarm this guard.
set -u
RAVEL_HOOK_INPUT="$(cat)"
export RAVEL_HOOK_INPUT
REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
HOOK_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/src"
[ -d "$REPO/src/ravel" ] && HOOK_SRC="$REPO/src"
[ -d "$HOOK_SRC/ravel" ] && export PYTHONPATH="$HOOK_SRC${PYTHONPATH:+:$PYTHONPATH}"
verdict="$("${RAVEL_PYTHON:-python3}" -c "$(cat <<'PY'
import hashlib, json, os, re, sys
from pathlib import Path
try:
    d = json.loads(os.environ.get('RAVEL_HOOK_INPUT') or '{}')
except (ValueError, TypeError):
    print('allow'); raise SystemExit
repo = Path(sys.argv[1])
session = d.get('session_id') or ''
ti = d.get('tool_input') or {}
path = ti.get('file_path') or ti.get('notebook_path') or ''
if not path:
    print('allow'); raise SystemExit
p = os.path.abspath(path)
resolved = str(Path(p).resolve())
physics = bool(session) and (repo / 'logs' / ('.route-pending-' + session)).is_file()
# Registry lookup is intentionally independent of importing the enforcement package.
if not physics and session:
    state = Path(os.environ.get('RAVEL_STATE_DIR') or Path.home() / '.local/state/ravel')
    key = hashlib.sha256(session.encode('utf-8')).hexdigest()[:32] + '.json'
    try:
        row = json.loads((state / 'active-runs' / key).read_text())
        physics = (row.get('schema_version') == 1 and row.get('kind') == 'active-run'
                   and row.get('session_id') == session and isinstance(row.get('rundir'), str)
                   and (Path(row['rundir']) / 'run_state.json').is_file())
    except (OSError, ValueError, TypeError, AttributeError):
        pass
if not physics and d.get('cwd'):
    cwd = Path(d['cwd']).expanduser().absolute()
    physics = any((candidate / 'run_state.json').is_file() for candidate in (cwd, *cwd.parents))
if not physics and session:
    for candidate in (repo / 'trial-runs').glob('*/run_state.json'):
        try:
            if json.loads(candidate.read_text()).get('session_id') == session:
                physics = True
                break
        except (OSError, ValueError, AttributeError):
            continue
if not physics:
    print('allow'); raise SystemExit
try:
    from ravel.workflow import host_governance as hg
except Exception:
    print('block:the ravel enforcement module is unavailable; restore the installed hook interpreter')
    raise SystemExit
ENF = re.compile(r'/\.claude/settings\.json$|/\.claude/hooks/'
                 r'|/\.(claude|codex|gemini)/(?:[^/]+/)*ravel-gate\.sh$'
                 r'|/tests/adversarial/'
                 r'|/scripts/(green_board|check_repository)\.py$|/Makefile$'
                 r'|/src/ravel/(validation|workflow)/[^/]+\.py$'
                 r'|/src/ravel/data/transports/[^/]+\.json$|/src/ravel/data/gates/providers\.json$'
                 r'|/src/ravel/plotting/figure_target\.py$'
                 r'|/src/ravel/(paths|evidence_layout|_bootstrap)\.py$')
try:
    paths = list(hg.surface_files(repo).values())
    # Digests include existing files. Write protection also includes registered
    # destinations that have not been created yet.
    for extension in hg.SURFACE_EXTENSIONS:
        paths.extend(extension(repo).values())
    registered = {str(Path(value).resolve()) for value in paths}
except Exception:
    print('block:the enforcement surface could not be resolved'); raise SystemExit
print('block:the enforcement surface is read-only during a physics session'
      if ENF.search(p) or ENF.search(resolved) or resolved in registered else 'allow')
PY
)" "$REPO")"
status=$?
if [ "$status" -ne 0 ]; then
  # If even stdlib cannot run, refusing the write is the only enforceable result.
  echo "BLOCKED: the RAVEL hook interpreter is unavailable; restore RAVEL_PYTHON." >&2
  exit 2
fi
case "$verdict" in
  block:*)
    echo "BLOCKED (enforcement-surface guard): ${verdict#block:}. Make enforcement changes in a development session." >&2
    exit 2 ;;
  allow) exit 0 ;;
  *) echo "BLOCKED: the enforcement guard returned no usable verdict." >&2; exit 2 ;;
esac
