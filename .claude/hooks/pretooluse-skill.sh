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
printf '%s' "$input" | "${RAVEL_PYTHON:-python3}" -c 'import sys
from ravel.workflow.host_guards import skill_main
raise SystemExit(skill_main(sys.argv[1]))' "$REPO"
status=$?
[ "$status" -eq 0 ] && exit 0
exit 2
