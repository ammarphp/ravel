from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Files the workflow-adherence spine (Phases 0-6) introduced. Each MUST carry a DIRECTORY.md
# reference once it has landed on disk, or the map has drifted (directory-keeper contract).
NEW_SPINE_FILES = [
    "trial-runs/_infrastructure/workflow_state.py",
    "trial-runs/_infrastructure/provenance.py",
    "trial-runs/_infrastructure/progress_reporter.py",
    "trial-runs/_infrastructure/stop_dispatch.py",
    "trial-runs/_infrastructure/stage_supervisor.py",
    "trial-runs/_infrastructure/validate_parameters.py",
    "trial-runs/_infrastructure/validate_checkin.py",
    "trial-runs/_infrastructure/preflight_watcher.py",
    "trial-runs/_infrastructure/sr_plausibility.py",
    "trial-runs/_infrastructure/install_git_hooks.sh",
    "framework/spine_sim",
    ".claude/hooks/stop-dispatcher.sh",
    ".claude/hooks/posttooluse-observer.sh",
    ".claude/hooks/userpromptsubmit-router.sh",
    ".claude/hooks/pretooluse-skill.sh",
    "framework/spine/HOOK-PRIMACY.json",
]


def _directory_text():
    return (REPO / "DIRECTORY.md").read_text(encoding="utf-8")


def test_every_landed_spine_file_has_a_directory_row():
    dir_text = _directory_text()
    missing = []
    for rel in NEW_SPINE_FILES:
        if not (REPO / rel).exists():
            continue  # not landed in this tree yet; a later phase owns its row
        base = Path(rel).name  # e.g. workflow_state.py / spine_sim / HOOK-PRIMACY.json
        if base not in dir_text:
            missing.append(rel)
    assert not missing, f"DIRECTORY.md has no row for landed spine files: {missing}"


def test_run_state_convention_documented():
    assert "run_state.json" in _directory_text(), \
        "the per-run run_state.json ledger convention is not documented in DIRECTORY.md"
