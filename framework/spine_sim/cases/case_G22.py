#!/usr/bin/env python3
"""G22 SKILL-PRECEDENCE (N1): a physics session whose first Skill is new-analysis (not
physicist-intake) with NO active-run task_contract.json -> the PreToolUse-on-Skill guard exits 2.
Drive against an ISOLATED CLAUDE_PROJECT_DIR with an EMPTY trial-runs/ -- the real repo carries 7
contracts, so a real-repo drive never fires (p2 also scopes the guard to the session rundir)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    with L.tempdir() as proj:                          # isolated CLAUDE_PROJECT_DIR
        os.makedirs(os.path.join(proj, "trial-runs"))  # empty: no run carries a contract
        stdin = {"hook_event_name": "PreToolUse", "tool_name": "Skill", "cwd": proj,
                 "tool_input": {"skill": "new-analysis"}}
        cp = L.drive_hook(L.HOOKS["pretooluse_skill"], stdin, extra_env={"CLAUDE_PROJECT_DIR": proj})
        L.gate_fired(cp.returncode == 2,
                     f"pretooluse-skill guard exit {cp.returncode}, expected 2 (new-analysis before contract)")

if __name__ == "__main__":
    sys.exit(run())
