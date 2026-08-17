#!/usr/bin/env python3
"""G9 PREVENT (D7): a run-pipeline/mg5 launch naming a trial-runs/<run> whose contract declares a BSM
model with NO fetched recipe -> the pre-generate guard hook blocks (exit 2). The guard resolves the
run dir by matching `trial-runs/[^\\s]+` IN THE COMMAND (relative to CLAUDE_PROJECT_DIR), and only
fires when targets.model is set (the base contract has none) -- so drive it against an ISOLATED
CLAUDE_PROJECT_DIR with the run under trial-runs/ (mirror p4b test_guard_blocks_mg5_without_recipe)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    with L.tempdir() as proj:                       # isolated CLAUDE_PROJECT_DIR
        rd = os.path.join(proj, "trial-runs", "2026-07-09_svj")
        # a minimal contract carrying a BSM model + NO inputs/generation_recipe.json -> guard refuses
        L.write_json(rd, "inputs/task_contract.json", {"targets": {"model": "SVJ"}})
        stdin = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "cwd": rd,
                 "tool_input": {"command":
                                "bash run-pipeline-native.sh trial-runs/2026-07-09_svj config.toml"}}
        cp = L.drive_hook(L.HOOKS["pre_generate"], stdin, extra_env={"CLAUDE_PROJECT_DIR": proj})
        L.gate_fired(cp.returncode == 2, f"pre-generate guard exit {cp.returncode}, expected 2")

if __name__ == "__main__":
    sys.exit(run())
