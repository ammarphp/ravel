"""P11 XF04/V08: role separation is mandatory; model family is descriptive."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

from ravel.workflow import decision_case as dc
from ravel.workflow import rdj_loop as rdj

# Reuse the small synthetic run builder without changing the shared fixture module.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rdj_fixtures import PROPOSER, Run  # noqa: E402


def actor(name):
    return dc.actor({"actor_id": name, "session_receipt": f"fixture:{name}",
                     "attestation": "transport_attested"})


@pytest.fixture
def small_case(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "state"))
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    case, state, _ = rdj._load(run.root, case_id)
    critic = actor("critic")
    rdj._record_critique(run.root, case, state, {"findings": []}, critic)
    return run, case, state, critic


@pytest.mark.parametrize("verifier_family,critic_family,relationship", [
    ("observed-family", "observed-family", "same"),
    ("observed-family", "other-observed-family", "different"),
    (None, "observed-family", "unknown"),
    ("observed-family", None, "unknown"),
])
def test_XF04_V08_r3_distinct_roles_record_family_without_veto(
        small_case, monkeypatch, verifier_family, critic_family, relationship):
    run, case, state, critic = small_case
    case["risk"]["class"] = "R3"
    policy = deepcopy(rdj.anchor_check.policy())
    policy["r3_distinct_family"] = True  # A legacy policy flag must no longer impose a family veto.
    monkeypatch.setattr(rdj.anchor_check, "policy", lambda: policy)
    verifier = actor("verifier")
    output = {"per_finding": [], "outcome": "gather_evidence"}
    rdj._record_verification(run.root, case, state, output, verifier, verifier_family,
                             {critic["session_receipt"]: critic_family})

    # The verifier's verdict and supplied attestation retain their original meanings.
    assert case["verification"] == {"reviewer": verifier, **output}
    assert state["verified_digest"] == rdj._verify_digest(case, state)
    assert not state["self_attested_verifier"]
    relationships = state["verifier_family_relationships"]
    assert relationships == [{"critic": critic, "critic_family": critic_family,
                              "verifier_family": verifier_family, "relationship": relationship,
                              "label": f"separate session, {relationship} model family"}]

    # Family details extend the receipt's existing summary, never the closed verification schema.
    receipt = rdj._write_receipt(run.root, case, state, "gather_evidence", [])
    assert receipt["attestation_summary"]["verifier_family_relationships"] == relationships
    assert receipt["outcome"] == "gather_evidence"
    # No transport call was registered: metadata must not defeat the usual attestation downgrade.
    assert receipt["attestation_summary"]["verifier"] == "self_attested"


@pytest.mark.parametrize("risk_class", ["R0", "R1", "R2", "R3"])
@pytest.mark.parametrize("shared", ["actor_id", "session_receipt"])
def test_XF04_V08_shared_critic_identity_refused_even_with_human_callback(
        small_case, monkeypatch, risk_class, shared):
    run, case, state, critic = small_case
    case["risk"]["class"] = risk_class
    monkeypatch.setattr(rdj, "_human", lambda *_: True)
    verifier = {**actor("verifier"), shared: critic[shared]}
    before_case, before_state = deepcopy(case), deepcopy(state)

    with pytest.raises(rdj.IndependenceError, match="different sessions and actors"):
        rdj._record_verification(run.root, case, state, {"per_finding": [], "outcome": "authorize"},
                                 verifier, "observed-family", {critic["session_receipt"]: "observed-family"})

    assert case == before_case
    assert state == before_state
