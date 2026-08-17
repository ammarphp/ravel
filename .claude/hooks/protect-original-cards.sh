#!/usr/bin/env bash
# PreToolUse guard: hard-block any Edit/Write/MultiEdit to the PRISTINE ORIGINAL cards in the DSRLab
# root. They are read-only ground truth; all work happens on copies (e.g. trial-runs/<run>/inputs/).
# Reads the tool-call JSON on stdin; exits 2 to block (feedback goes to Claude via stderr).
# No jq dependency — matches the exact absolute paths in the raw JSON.
input="$(cat)"
if printf '%s' "$input" | grep -qE '$DSRLAB_ROOT/(proc_card\.dat|param_card_200_150\.dat)"'; then
  echo "BLOCKED: the pristine original cards ($DSRLAB_ROOT/{proc_card.dat,param_card_200_150.dat}) are read-only ground truth. Copy them into the run's inputs/ and edit the copy. (See CLAUDE.md hard rules.)" >&2
  exit 2
fi
exit 0
