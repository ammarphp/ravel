"""The prompt router routes physics requests and stays silent on development briefs (R-50 item 3, S1-14).

Synthetic prompts only; the routing corpus is the generic intake corpus under tests/unit/fixtures.
"""
import synthetic_identifiers as syn
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ROUTER = REPO / ".claude/hooks/userpromptsubmit-router.sh"
PROTECT = REPO / ".claude/hooks/protect-enforcement.sh"
CORPUS = REPO / "tests/unit/fixtures/intake-corpus/requests.json"

DEVELOPMENT_BRIEF = """# STREAM BRIEF: X-99 Example package

Slot 3 of 20 · parent: coordinator · depth 1
Branch  release/x99-example from release/candidate
Worktree /work/checkout/local-runs/worktrees/x99-example

## Deliverable
A scan summary for the reinterpretation layer: limits on a synthetic model, ATLAS and CMS style tables.

## Ownership
Owns (may edit): `src/ravel/workflow/example.py`, `tests/unit/test_example.py`

## Acceptance tests
1. `ravel example --json` prints the excluded mass plane for each likelihood.
"""


def _env(project, tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "RAVEL_SESSION_ID")}
    env.update(CLAUDE_PROJECT_DIR=str(project), RAVEL_STATE_DIR=str(tmp_path / "state"), RAVEL_PYTHON=sys.executable)
    return env


def _project(tmp_path):
    """A project that carries the checkout's package, as a real project directory does."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "src").symlink_to(REPO / "src")
    return project


def _route(prompt, project, tmp_path, session="S-ROUTER"):
    return subprocess.run(["bash", str(ROUTER)], input=json.dumps({"prompt": prompt, "session_id": session}),
                          capture_output=True, text=True, env=_env(project, tmp_path))


def test_development_brief_creates_no_marker_and_leaves_src_writable(tmp_path):
    project = _project(tmp_path)
    r = _route(DEVELOPMENT_BRIEF, project, tmp_path)
    assert r.returncode == 0 and r.stdout.strip() == ""
    assert not (project / "logs").exists() or not list((project / "logs").glob(".route-pending-*"))
    edit = subprocess.run(["bash", str(PROTECT)], input=json.dumps({
        "tool_name": "Edit", "session_id": "S-ROUTER",
        "tool_input": {"file_path": str(project / "src/ravel/workflow/stop_dispatch.py")}}),
        capture_output=True, text=True, env=_env(project, tmp_path))
    assert edit.returncode == 0, edit.stderr


@pytest.mark.parametrize("prompt", [
    ("Initiate: reproduce Figure 3 of arXiv:" + syn.arxiv(1)),
    "Evaluate 1.2e-3 * 139 * 1000 and state the answer in events, taking the inputs as a cross section in pb.",
    "Write a short paper summarizing the results in run A.",
])
def test_genuine_physics_request_still_routes(tmp_path, prompt):
    project = _project(tmp_path)
    r = _route(prompt, project, tmp_path)
    assert r.returncode == 0 and "physicist-intake" in r.stdout and "additionalContext" in r.stdout
    from ravel.workflow.route_prompt import route
    assert (project / "logs/.route-pending-S-ROUTER").is_file() == (route(prompt)["compute_plan"] != "none")


@pytest.mark.parametrize("prompt", [
    "Explain how the gate verdict object is structured",
    "Summarize what you did so far in this session",
    "What does the CHECK-IN 1 approval require from me?",
])
def test_noncompute_prompt_keeps_reminder_without_marker(tmp_path, prompt):
    project = _project(tmp_path)
    r = _route(prompt, project, tmp_path)
    assert r.returncode == 0 and "additionalContext" in r.stdout
    assert not (project / "logs/.route-pending-S-ROUTER").exists()


def test_short_reply_is_not_a_new_request(tmp_path):
    project = _project(tmp_path)
    assert _route("yes, go ahead", project, tmp_path).stdout.strip() == ""
    assert not (project / "logs").exists()
    assert "physicist-intake" in _route("Initiate: scan sleptons", project, tmp_path).stdout


def test_no_corpus_request_is_classified_as_development():
    from ravel.workflow.host_governance import development_prompt
    cases = syn.load_json(CORPUS)["cases"]
    assert len(cases) >= 26
    misread = [c["id"] for c in cases if development_prompt(c["prompt"])]
    assert misread == []


@pytest.mark.parametrize("prompt", [
    DEVELOPMENT_BRIEF,
    "fix the typo in the README",
    "Refactor src/ravel/workflow/example.py and add unit tests.",
    "Run pytest on tests/unit/test_example.py and fix the failing hook.",
    "git rebase release/candidate and resolve the merge conflict",
])
def test_development_prompts_are_recognized(prompt):
    from ravel.workflow.host_governance import development_prompt
    assert development_prompt(prompt)
