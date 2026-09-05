#!/usr/bin/env bash
# D7 PREVENT (G9): before a MadGraph/shower launch, block if a declared BSM/HV model has no fetched
# generation recipe. Best-effort hook; the authoritative half is the steps/03-generate.md gate.
set -uo pipefail
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HOOK_DIR/../.." && pwd)"
input="$(cat)"
cmd="$(printf '%s' "$input" | python3 -c 'import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    d = {}
print((d.get("tool_input") or {}).get("command", "") or "")')"
[ -z "$cmd" ] && exit 0
python3 "$REPO/src/ravel/workflow/resource_census.py" \
    --pre-generate-hook --command "$cmd" --project-dir "${CLAUDE_PROJECT_DIR:-$REPO}"
exit $?
