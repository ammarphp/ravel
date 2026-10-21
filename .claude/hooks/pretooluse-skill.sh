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
RAVEL_HOOK_INPUT="$input"
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
printf '%s' "$input" | "${RAVEL_PYTHON:-python3}" -c 'import sys
from ravel.workflow.host_guards import skill_main
raise SystemExit(skill_main(sys.argv[1]))' "$REPO"
status=$?
[ "$status" -eq 0 ] && exit 0
if [ "$status" -ne 2 ]; then
  ravel_hook_failed pretooluse-skill
  echo "BLOCKED: the RAVEL skill guard is unavailable; this session is labelled NOT GOVERNED." >&2
fi
exit 2
