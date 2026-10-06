#!/usr/bin/env bash
# Stop-hook dispatcher shim -- pipes the Stop JSON to stop_dispatch.py (the branch brain).
# exit 2 blocks turn-end (stderr reason fed back to the agent); exit 0 allows / fail-opens.
input="$(cat)"
printf '%s' "$input" | python3 "${CLAUDE_PROJECT_DIR:-.}/src/ravel/workflow/stop_dispatch.py"
exit $?
