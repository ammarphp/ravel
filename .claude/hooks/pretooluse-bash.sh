#!/usr/bin/env bash
# PreToolUse Bash shim over host_gate.verdict(tool_call), shared with ravel gate.
# All deny verdicts block with the first error message. Registered runs are resolved
# by cwd/session; a classified compute launch with no run is pre_intake even without
# a route marker. The marker still distinguishes routed Claude development sessions
# in the intake/fan-out guards. Exit 2 blocks; tool-call JSON travels through stdin.
set -u
RAVEL_HOOK_INPUT="$(cat)"
REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
# The project's own package first (as before), else this hook's checkout, else an installed ravel.
HOOK_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/src"
[ -d "$REPO/src/ravel" ] && HOOK_SRC="$REPO/src"
[ -d "$HOOK_SRC/ravel" ] && export PYTHONPATH="$HOOK_SRC${PYTHONPATH:+:$PYTHONPATH}"
verdict="$(printf '%s' "$RAVEL_HOOK_INPUT" | "${RAVEL_PYTHON:-python3}" -m ravel.workflow.host_gate --hook bash --project "$REPO" 2>/dev/null)"
case "$verdict" in
  allow) exit 0 ;;
  block:*)
    echo "BLOCKED (pre-exec compute gate): ${verdict#block:}" >&2
    exit 2 ;;
  *)
    # The gate module itself failed: hold a generation launch rather than fail open.
    if printf '%s' "$RAVEL_HOOK_INPUT" | grep -qE 'generate_events|mg5_aMC|pythia_shower|run-pipeline-native|madevent|scan_orchestrator|scan_babysitter'; then
      echo "BLOCKED (pre-exec compute gate): the gate module is unavailable (python3 -m ravel.workflow.host_gate failed)." >&2
      exit 2
    fi
    exit 0 ;;
esac
