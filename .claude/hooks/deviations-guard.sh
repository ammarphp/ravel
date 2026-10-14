#!/usr/bin/env bash
# PostToolUse guard (D15 / G17, moment-of-change): after an Edit/Write to a CHECK-IN-1-baselined
# input file, BLOCK the turn (exit 2) unless the run's DEVIATIONS.md names the changed file. The
# belt-and-suspenders twin of validate_run_state's inv_deviations_on_change (the post-hoc half).
# Reads the tool-call JSON on stdin; extracts the edited path with python3 (not greedy grep).
input="$(cat)"
path="$(printf '%s' "$input" | "${RAVEL_PYTHON:-python3}" -c 'import json,sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
ti = d.get("tool_input") or {}
print(ti.get("file_path") or ti.get("path") or "")')"
[ -z "$path" ] && exit 0
REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
# The project's own package first (as before), else this hook's checkout, else an installed ravel.
HOOK_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/src"
[ -d "$REPO/src/ravel" ] && HOOK_SRC="$REPO/src"
[ -d "$HOOK_SRC/ravel" ] && export PYTHONPATH="$HOOK_SRC${PYTHONPATH:+:$PYTHONPATH}"
"${RAVEL_PYTHON:-python3}" -c 'import ravel.validation.validate_run_state' >/dev/null 2>&1 || {
  echo "RAVEL hook unavailable: deviations-guard cannot import ravel" >&2
  mkdir -p "$REPO/logs" && printf '%s\n' "deviations-guard unavailable: ravel import failed" >> "$REPO/logs/hook-failures.log"
  exit 0
}
if "${RAVEL_PYTHON:-python3}" -m ravel.validation.validate_run_state --edit-guard "$path"; then
  exit 0            # exit 0 from --edit-guard == allow
else
  exit 2            # --edit-guard returned 1 (block); its reason is already on stderr -> map to hook block
fi
