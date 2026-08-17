#!/usr/bin/env python3
"""G20 EMBED/COMMIT (D16): (a) check_agent_surface FAILs on a staged tree with a dead ref; (b) the
installed pre-commit hook is executable and invokes check_agent_surface (so a drift blocks the
commit). The hooks dir is resolved via `git rev-parse --git-path hooks`: in a LINKED worktree
L.REPO/.git is a FILE (a gitdir pointer), so L.REPO/.git/hooks/pre-commit does not exist."""
import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    with L.tempdir() as td:
        # a minimal staged export tree whose workflow doc references a nonexistent path
        wf = os.path.join(td, "workflow"); os.makedirs(wf)
        with open(os.path.join(wf, "x.md"), "w") as f:
            f.write("See `workflow/does_not_exist_zzz.md` for details.\n")
        p = L.run_tool("check_agent_surface.py", ["--stage", td])
        L.gate_fired(p.returncode != 0, f"check_agent_surface --stage exit {p.returncode}, expected nonzero")
    # resolve the REAL hooks dir (worktree-safe); .git may be a file, not a dir
    gp = subprocess.run(["git", "rev-parse", "--git-path", "hooks"], cwd=L.REPO,
                        capture_output=True, text=True)
    if gp.returncode != 0:
        raise L.CaseSetupError(f"git rev-parse --git-path hooks failed: {(gp.stderr or '').strip()}")
    hooks_dir = gp.stdout.strip()
    if not os.path.isabs(hooks_dir):
        hooks_dir = os.path.join(L.REPO, hooks_dir)
    hook = os.path.join(hooks_dir, "pre-commit")
    L.gate_fired(os.path.isfile(hook) and os.access(hook, os.X_OK),
                 f"pre-commit missing or not executable at {hook} (D16 not installed — run: bash trial-runs/_infrastructure/install_git_hooks.sh)")
    body = open(hook, encoding="utf-8", errors="replace").read()
    L.gate_fired("check_agent_surface" in body, "pre-commit does not invoke check_agent_surface.py")

if __name__ == "__main__":
    sys.exit(run())
