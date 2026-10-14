"""Scientific review recomputes fit and scan alarms from retained outputs; reviewers cannot overwrite them."""
from pathlib import Path
import sys

import pytest

from ravel.workflow import execution, physics_review as review, workflow_state
from ravel.workflow.state_io import atomic_json
from test_physics_review import accept, check_packet, policy


def inference(chi2):
    return {'schema_version': 1, 'kind': 'inference', 'mode': 'coupling-morphing', 'status': 'passed',
            'statistic': {'origin': 'not-applicable'}, 'physics_validated': False, 'diagnostics': {},
            'results': [{'quantity': 'morph-coefficients', 'role': 'primary', 'ndf': 2, 'chi2': [chi2]}],
            # A hand-edited pass does not survive recomputation.
            'computed_checks': [{'id': 'closure@x', 'trigger': 'closure', 'status': 'pass', 'computed': True}]}


def attempt(root, chi2):
    inputs = ["inputs/settings.cfg", "inputs/held-fixed.txt"]
    spec = {"command": [sys.executable, "-c", "pass"], "cwd": str(root.resolve()), "inputs": inputs,
            "outputs": ["outputs/produced.json", "outputs/inference.json"],
            "input_snapshot": execution.snapshot(root, inputs), "parents": {}, "runtime": execution.runtime_context()}
    spec["fingerprint"] = execution.digest(spec)
    record = execution.begin_attempt(root, "detector", spec, "logs/detector.log")
    atomic_json(root / "outputs/produced.json", {"value": 1})
    atomic_json(root / "outputs/inference.json", inference(chi2))
    (root / "logs/detector.log").write_text("generated\n")
    assert execution.finish_attempt(root, record, 0) == 0
    return record


@pytest.fixture
def make_run(tmp_path, monkeypatch):
    def build(chi2):
        root = tmp_path / f"run-{chi2}"
        (root / "inputs").mkdir(parents=True)
        atomic_json(root / review.POLICY, policy())
        atomic_json(root / "inputs/checkin1_approval.json", {"fixture": "approval verifier tested elsewhere"})
        monkeypatch.setattr(workflow_state, "approval_input_paths", lambda rd: [str(Path(rd) / review.POLICY)])
        monkeypatch.setattr(workflow_state, "verify_approval", lambda *a, **kw: [])
        (root / "inputs/settings.cfg").write_text("efficiency=0.8\n")
        (root / "inputs/held-fixed.txt").write_text("fixed recipe\n")
        atomic_json(root / "inputs/reference.json", {"reference": 1})
        record = attempt(root, chi2)
        check_packet(root, record)
        review.open_cycle(root, effective_settings=["inputs/settings.cfg"],
                          stage_receipts=[record["attempt_record"]], check_results="inputs/checks.json")
        return root
    return build


def test_computed_failure_blocks_a_scientific_claim_even_when_reviewers_pass_every_check(make_run):
    root = make_run(chi2=40.0)  # chi2/ndf = 20 > 3
    cycle = review._view(*review._read(root))["cycle"]
    assert any(c["status"] == "fail" and c["trigger"] == "closure" for c in review.computed_checks(cycle))
    with pytest.raises(ValueError, match="computed check failures block"):
        accept(root, scope="reproduction")


def test_diagnostic_scope_stays_available_with_a_computed_failure(make_run):
    root = make_run(chi2=40.0)
    accept(root, scope="diagnostic")
    assert review.status(root)["claim_scope"] == "diagnostic"


def test_clean_twin_accepts_the_scientific_scope(make_run):
    root = make_run(chi2=2.0)
    accept(root, scope="reproduction")
    assert review.status(root)["claim_scope"] == "reproduction"
