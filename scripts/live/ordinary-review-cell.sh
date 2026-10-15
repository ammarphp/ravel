#!/bin/bash
# Live cell: an ordinary delegated study whose blind normalization auditor is one real sandboxed worker.
#
# Dry run by default: prints the preflight and the exact command, starts nothing.
# --run (root only) runs the live test in tests/integration/test_ordinary_delegated_review.py once:
# one worker on the claude-cli-worker transport, budget at most USD 2, about 10-20 minutes and
# under 100 MB of disk. It is not a native physics job and calls no generator or site tool.
#
# Requirements for --run:
#   - a clean, detached worktree of the candidate (this script's checkout);
#   - RAVEL_PY: a Python with the repository's test dependencies (default: <checkout>/.venv/bin/python);
#   - the worker login directory (RAVEL_WORKER_LOGIN_DIR, default ~/.local/state/ravel-claude-worker),
#     with any files moved aside for an earlier qualification restored. An inherited CLAUDE_CONFIG_DIR
#     is never used: it may be an operator's own configuration;
#   - the host's live qualification record for claude-cli-worker (under RAVEL_TRANSPORT_STATE,
#     default ~/.local/state/ravel); it is copied, read-only use, into the cell's temporary state;
#   - a 5-minute load average of at most 14.
# Evidence: the pytest output and live-cell.json in the printed temporary directory, which is kept.
set -u

MODE=dry-run
case "${1:-}" in
  "") ;;
  --run) MODE=run ;;
  --dry-run) ;;
  -h|--help) awk 'NR>1 && /^#/{print; next} NR>1{exit}' "$0"; exit 0 ;;
  *) echo "usage: $0 [--dry-run|--run]" >&2; exit 2 ;;
esac

GIT=/usr/bin/git
REPO=$(cd "$(dirname "$0")/../.." && pwd -P)
PY=${RAVEL_PY:-$REPO/.venv/bin/python}
LOGIN=${RAVEL_WORKER_LOGIN_DIR:-$HOME/.local/state/ravel-claude-worker}
TRANSPORTS=${RAVEL_TRANSPORT_STATE:-$HOME/.local/state/ravel}/transports
QUALIFICATION=$TRANSPORTS/claude-cli-worker.qualification.json
TEST=tests/integration/test_ordinary_delegated_review.py

problems=0
check() {  # check <ok:0|1> <message>
  if [ "$1" = 0 ]; then echo "  ok    $2"; else echo "  FAIL  $2"; problems=$((problems + 1)); fi
}

echo "ordinary review live cell ($MODE)"
echo "checkout: $REPO"
"$GIT" -C "$REPO" symbolic-ref -q HEAD >/dev/null 2>&1; detached=$?
check $([ "$detached" -ne 0 ] && echo 0 || echo 1) "detached HEAD at $("$GIT" -C "$REPO" rev-parse --short HEAD 2>/dev/null)"
dirty=$("$GIT" -C "$REPO" status --porcelain --untracked-files=no 2>/dev/null | head -1)
check $([ -z "$dirty" ] && echo 0 || echo 1) "no tracked changes in the checkout"
check $([ -x "$PY" ] && echo 0 || echo 1) "test interpreter $PY (set RAVEL_PY)"
check $([ -d "$LOGIN" ] && [ ! -L "$LOGIN" ] && echo 0 || echo 1) "worker login directory $LOGIN"
check $([ ! -e "$LOGIN.moved-aside" ] && echo 0 || echo 1) "nothing left moved aside ($LOGIN.moved-aside restored)"
check $([ -f "$QUALIFICATION" ] && echo 0 || echo 1) "live qualification record $QUALIFICATION"
load=$(sysctl -n vm.loadavg 2>/dev/null | awk '{print $3}')
check $(awk -v l="${load:-99}" 'BEGIN{print (l <= 14) ? 0 : 1}') "5-minute load ${load:-unknown} <= 14"

COMMAND="RAVEL_LIVE_CELL=1 RAVEL_LIVE_CELL_OUT=<tmp>/live-cell.json RAVEL_STATE_DIR=<tmp>/state \
MPLCONFIGDIR=<tmp>/mpl CLAUDE_CONFIG_DIR=$LOGIN PYTHONPATH=$REPO/src \
$PY -m pytest -q -p no:cacheprovider --basetemp <tmp>/pt -rxXs $TEST -k live_cell"
echo "command: $COMMAND"
echo "budget: one worker, max_cost_usd 2.0 in its spec; about 10-20 min; under 100 MB"

if [ "$MODE" = dry-run ]; then
  echo "dry run: nothing started ($problems preflight problem(s))"
  exit 0
fi
if [ "$problems" -ne 0 ]; then
  echo "refused: $problems preflight problem(s)" >&2
  exit 1
fi

T=$(mktemp -d "${TMPDIR:-/tmp}/rv-live-cell.XXXX") || exit 1
T=$(cd "$T" && pwd -P)  # a run directory must not sit behind a symlinked /tmp
mkdir -p "$T/state" "$T/mpl" "$T/pt"
cp -R "$TRANSPORTS" "$T/state/transports"
echo "evidence directory (kept): $T"
cd "$REPO" || exit 1
env RAVEL_LIVE_CELL=1 RAVEL_LIVE_CELL_OUT="$T/live-cell.json" RAVEL_STATE_DIR="$T/state" \
  MPLCONFIGDIR="$T/mpl" CLAUDE_CONFIG_DIR="$LOGIN" PYTHONPATH="$REPO/src" \
  "$PY" -m pytest -q -p no:cacheprovider --basetemp "$T/pt" -rxXs "$TEST" -k live_cell 2>&1 | tee "$T/pytest.log"
status=${PIPESTATUS[0]}
echo "pytest exit $status; evidence: $T/pytest.log $T/live-cell.json"
exit "$status"
