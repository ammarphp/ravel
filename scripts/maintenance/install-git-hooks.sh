#!/usr/bin/env bash
# D16 (G20): install a git pre-commit hook that blocks a commit leaving the agent surface inconsistent
# (dead ref / missing DIRECTORY.md row / unmirrored skill). Reproducible across worktrees + clones.
set -euo pipefail
# Resolve both Git paths before any mutation. A non-checkout must not turn empty
# command output into "/pre-commit" or report success after a failed write.
REPO="$(git rev-parse --show-toplevel)"
HOOKS="$(git -C "$REPO" rev-parse --git-path hooks)"
if [ -z "$REPO" ] || [ -z "$HOOKS" ]; then
  echo "cannot install Git hooks: empty repository or hooks path" >&2
  exit 1
fi
case "$HOOKS" in /*) : ;; *) HOOKS="$REPO/$HOOKS" ;; esac
mkdir -p "$HOOKS"
cat > "$HOOKS/pre-commit" <<'HOOK'
#!/usr/bin/env bash
# D16: mandatory agent-surface gate (mirrors embed-and-commit SKILL.md "run the surface gate").
set -uo pipefail
REPO="$(git rev-parse --show-toplevel)" || exit $?
# check_agent_surface transitively imports numpy (audit.py R9 runs shape_fit --selftest). If the
# host git is an x86_64 binary it spawns this hook — and its python3 — under Rosetta, where the
# native arm64 numpy .so cannot load and the gate would FALSE-FAIL on an arch mismatch, not real
# drift. When we detect a translated process on Apple-Silicon hardware, run the gate under the
# native arch so it reports true surface drift only. (No-op on native arm64 / Intel / Linux.)
RUN=(python3)
if [ "$(uname -s)" = "Darwin" ] \
   && [ "$(sysctl -n sysctl.proc_translated 2>/dev/null)" = "1" ] \
   && [ "$(sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ] \
   && command -v arch >/dev/null 2>&1; then
  RUN=(arch -arm64 python3)
fi
"${RUN[@]}" "$REPO/src/ravel/validation/check_agent_surface.py"
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "pre-commit: check_agent_surface FAILED (exit $rc) -- fix the agent-surface drift (DIRECTORY.md" >&2
  echo "row, dead ref, skill mirror) before committing (D16)." >&2
  exit "$rc"
fi
exit 0
HOOK
chmod +x "$HOOKS/pre-commit"
echo "installed pre-commit hook at $HOOKS/pre-commit"
