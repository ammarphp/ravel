#!/usr/bin/env bash
# MCP admission: fail closed, including unavailable interpreters or policy.
set -u
RAVEL_HOOK_INPUT="$(cat)"
REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
HOOK_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/src"
[ -d "$REPO/src/ravel" ] && HOOK_SRC="$REPO/src"
[ -d "$HOOK_SRC/ravel" ] && export PYTHONPATH="$HOOK_SRC${PYTHONPATH:+:$PYTHONPATH}"
verdict="$(printf '%s' "$RAVEL_HOOK_INPUT" | "${RAVEL_PYTHON:-python3}" -m ravel.workflow.site_tools check --hook --project "$REPO" 2>/dev/null)"
case "$verdict" in
  allow) exit 0 ;;
  block:*) echo "BLOCKED (site-tool gate): ${verdict#block:}" >&2; exit 2 ;;
  *) echo "BLOCKED (site-tool gate): admission unavailable. Use RAVEL's governed route (docs/workflow/start.md) and restore the hook interpreter/policy." >&2; exit 2 ;;
esac
