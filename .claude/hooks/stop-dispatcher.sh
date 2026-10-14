#!/usr/bin/env bash
# Stop-hook dispatcher shim -- pipes the Stop JSON to ravel.workflow.stop_dispatch (the branch brain).
# The run comes from the R-50 registry (working directory, then session id), never the newest run.
# exit 2 blocks turn-end (stderr reason fed back to the agent); exit 0 allows / fail-opens.
input="$(cat)"
REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
# The project's own package first (as before), else this hook's checkout, else an installed ravel.
HOOK_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/src"
[ -d "$REPO/src/ravel" ] && HOOK_SRC="$REPO/src"
[ -d "$HOOK_SRC/ravel" ] && export PYTHONPATH="$HOOK_SRC${PYTHONPATH:+:$PYTHONPATH}"
"${RAVEL_PYTHON:-python3}" -c 'import ravel.workflow.stop_dispatch' >/dev/null 2>&1 || {
  echo "RAVEL hook unavailable: stop-dispatcher cannot import ravel" >&2
  mkdir -p "$REPO/logs" && printf '%s\n' "stop-dispatcher unavailable: ravel import failed" >> "$REPO/logs/hook-failures.log"
  exit 0
}
printf '%s' "$input" | "${RAVEL_PYTHON:-python3}" -m ravel.workflow.stop_dispatch
exit $?
