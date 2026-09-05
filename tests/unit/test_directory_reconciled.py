from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Files the workflow-adherence spine (Phases 0-6) introduced. Each MUST carry a DIRECTORY.md
# reference once it has landed on disk, or the map has drifted (directory-keeper contract).
NEW_SPINE_FILES = [
    "src/ravel/workflow/workflow_state.py",
    "src/ravel/workflow/provenance.py",
    "src/ravel/workflow/progress_reporter.py",
    "src/ravel/workflow/stop_dispatch.py",
    "src/ravel/workflow/stage_supervisor.py",
    "src/ravel/validation/validate_parameters.py",
    "src/ravel/validation/validate_checkin.py",
    "src/ravel/workflow/preflight_watcher.py",
    "src/ravel/validation/sr_plausibility.py",
    "scripts/maintenance/install-git-hooks.sh",
    "tests/adversarial",
    ".claude/hooks/stop-dispatcher.sh",
    ".claude/hooks/posttooluse-observer.sh",
    ".claude/hooks/userpromptsubmit-router.sh",
    ".claude/hooks/pretooluse-skill.sh",
    "tests/fixtures/hook-probes/hook-primacy.json",
]


def _directory_text():
    return (REPO / "DIRECTORY.md").read_text(encoding="utf-8")


def test_every_landed_spine_file_has_a_directory_row():
    dir_text = _directory_text()
    missing = []
    for rel in NEW_SPINE_FILES:
        if not (REPO / rel).exists():
            missing.append(rel + " (required file absent)")
            continue
        base = Path(rel).name  # e.g. workflow_state.py / spine_sim / HOOK-PRIMACY.json
        if base not in dir_text:
            missing.append(rel)
    assert not missing, f"DIRECTORY.md has no row for landed spine files: {missing}"


def test_run_state_convention_documented():
    assert "run_state.json" in _directory_text(), \
        "the per-run run_state.json ledger convention is not documented in DIRECTORY.md"
