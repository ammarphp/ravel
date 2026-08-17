#!/usr/bin/env bash
# PostToolUse guard (D15 / G17, moment-of-change): after an Edit/Write to a CHECK-IN-1-baselined
# input file, BLOCK the turn (exit 2) unless the run's DEVIATIONS.md names the changed file. The
# belt-and-suspenders twin of validate_run_state's inv_deviations_on_change (the post-hoc half).
# Reads the tool-call JSON on stdin; extracts the edited path with python3 (not greedy grep).
input="$(cat)"
path="$(printf '%s' "$input" | python3 -c 'import json,sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
ti = d.get("tool_input") or {}
print(ti.get("file_path") or ti.get("path") or "")')"
[ -z "$path" ] && exit 0
VRS="$CLAUDE_PROJECT_DIR/trial-runs/_infrastructure/validate_run_state.py"
[ -f "$VRS" ] || exit 0
if python3 "$VRS" --edit-guard "$path"; then
  exit 0            # exit 0 from --edit-guard == allow
else
  exit 2            # --edit-guard returned 1 (block); its reason is already on stderr -> map to hook block
fi
