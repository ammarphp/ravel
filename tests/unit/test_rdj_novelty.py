"""Fictional unfamiliar-route and source-custody controls; no scientific execution."""
import copy
import json

import pytest

from ravel.workflow import broker, rdj_anchor, rdj_custody
from ravel.workflow import rdj_loop as rdj

from rdj_fixtures import PROPOSER, Roles, Run, add, node, sha


@pytest.fixture(autouse=True)
def custody(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "state"))


def choice_case(run, roles, anchors):
    case_id = rdj.open_case(run.root, "research_choice", run.action(
        "screening_choice", "Compare fictional variants", route="unfamiliar-route"), PROPOSER)
    add(run, case_id, "action", node("A", "The comparison is bounded"))
    rdj.run_roles(run.root, case_id, roles)
    add(run, case_id, "A", node("B", "The retained inputs describe the comparison", anchors=anchors))
    rdj.run_roles(run.root, case_id, roles)
    add(run, case_id, "action", node("alt", "Keep the current variant", kind="alternative"),
        kind="why_over_alternative")
    rdj.run_roles(run.root, case_id, roles)
    return case_id


def row(spec):
    return {"id": "reference", "kind": spec["kind"], "binding": spec["binding"],
            "locator": "", "value": spec.get("value"), "quantity": None, "verified": None}


def context(run):
    return {"rundir": str(run.root), "input_snapshot": rdj_custody.input_snapshot(run.root),
            "generated": sorted(rdj_anchor.generated_paths(run.root)), "action_pins": []}


def acquired(tmp_path, *, source_class="standard_reference", descriptor=True, reference_changes=None):
    """A trusted inert acquisition and an independently supplied reference descriptor."""
    body = b"Use the supplied fictional comparison law.\n"
    source = {"uri": "fixture://source", "record_id": "fictional-reference"}
    reference = {"schema_version": 1, "kind": "scientific-practice-reference", "source_class": source_class,
                 "source": source, "content_sha256": sha(body), **(reference_changes or {})}
    run = Run(tmp_path / "run", extra_inputs=[("inputs/reference.json", reference)] if descriptor else [])
    workspace = broker.work_root(run.root) / "reader" / "1"
    for name in ("inputs", "outputs", "scratch", "calls"):
        (workspace / name).mkdir(parents=True, exist_ok=True)
    executor = broker.Broker(run.root, workspace, node_id="reader", attempt=1,
                             allowed_actions=["acquire"], max_calls=2)

    def acquire(args):
        (workspace / "outputs/source.txt").write_bytes(body)
        return {"output_paths": ["outputs/source.txt"], "source": source}

    executor.register("acquire", acquire, derivation="retrieval")
    assert executor.call({"call_id": "read", "action": "acquire", "args": {}})["status"] == "ok"
    path = workspace / "calls/1.json"
    binding = {"acquisition_receipt": {"path": broker.logical(run.root, path), "sha256": sha(path.read_bytes())},
               "content_sha256": sha(body), "excerpt_span": {"start": 0, "end": len(body)}, "excerpt_sha256": sha(body)}
    if descriptor:
        binding["source_reference"] = run.pin("inputs/reference.json")
    return run, {"kind": "retrieved_document", "binding": binding}, executor


def test_unfamiliar_route_elevates_and_requires_practice_even_with_external_evidence(tmp_path):
    run = Run(tmp_path / "run", extra_inputs=[("inputs/reference.json", {"value": 2})])
    roles = Roles()
    anchor = {"kind": "external_fact", "binding": {
        "record_id": "fictional-reference", "file": run.pin("inputs/reference.json")}, "locator": "/value"}
    case_id = choice_case(run, roles, [anchor])
    case = run.case(case_id)
    assert case["risk"]["class"] == "R2" and case["risk"]["computed_factors"]["novelty"]
    with pytest.raises(rdj.OpenItems) as refused:
        rdj.authorize(run.root, case_id)
    assert {row["code"] for row in refused.value.items} == {"exploratory_choice"}
    assert len(roles.calls) == 5
    assert rdj_anchor.policy()["practice_source_classes"]
    assert not rdj_anchor.practice_anchor({**anchor, "id": "a"}, "external")


@pytest.mark.parametrize("source_class", rdj_anchor.policy()["practice_source_classes"])
def test_verified_reference_category_closes_practice_gap_without_changing_class_or_role_calls(tmp_path, source_class):
    run, spec, executor = acquired(tmp_path, source_class=source_class)
    anchor = row(spec)
    assert rdj_anchor.verify_full(anchor, run.root, context=context(run)) == (
        "external", None, "Use the supplied fictional comparison law.\n")
    assert rdj_anchor.practice_anchor(anchor, "external", rundir=run.root, context=context(run))
    roles = Roles()
    case_id = choice_case(run, roles, [spec])
    receipt = rdj.authorize(run.root, case_id)
    assert receipt["outcome"] == "authorize" and receipt["class"] == "R2"
    assert receipt["exploratory"] == []
    assert len(roles.calls) == 5
    assert len(executor.verify_ledger()) == 1


def test_acquired_document_without_independent_classification_stays_exploratory(tmp_path):
    run, spec, _ = acquired(tmp_path, descriptor=False)
    anchor = row(spec)
    assert rdj_anchor.verify(anchor, run.root, context=context(run)) == "external"
    assert not rdj_anchor.practice_anchor(anchor, "external", rundir=run.root, context=context(run))
    case_id = choice_case(run, Roles(), [spec])
    with pytest.raises(rdj.OpenItems) as refused:
        rdj.authorize(run.root, case_id)
    assert {item["code"] for item in refused.value.items} == {"exploratory_choice"}


@pytest.mark.parametrize("changes", [
    {"source_class": "arbitrary_citation"}, {"schema_version": True}, {"kind": "citation"},
    {"source": {"uri": "fixture://other", "record_id": "fictional-reference"}},
    {"content_sha256": "0" * 64},
])
def test_reference_category_needs_exact_identity_and_content(tmp_path, changes):
    run, spec, _ = acquired(tmp_path, reference_changes=changes)
    anchor = row(spec)
    assert rdj_anchor.verify(anchor, run.root, context=context(run)) == "external"
    assert not rdj_anchor.practice_anchor(anchor, "external", rundir=run.root, context=context(run))


def test_authority_category_cannot_be_asserted_in_anchor_binding(tmp_path):
    run, spec, _ = acquired(tmp_path, descriptor=False)
    spec["binding"]["source_class"] = "standard_reference"
    assert rdj_anchor.verify(row(spec), run.root, context=context(run)) == "invalid"
    assert not rdj_anchor.practice_anchor(row(spec), "external", rundir=run.root, context=context(run))


@pytest.mark.parametrize("target", ["body", "receipt"])
def test_retrieval_custody_rejects_changed_bytes(tmp_path, target):
    run, spec, executor = acquired(tmp_path)
    path = executor.workspace / ("outputs/source.txt" if target == "body" else "calls/1.json")
    path.write_bytes(b"changed")
    if target == "receipt":
        spec["binding"]["acquisition_receipt"]["sha256"] = sha(path.read_bytes())
    assert rdj_anchor.verify(row(spec), run.root, context=context(run)) == "generated"
    assert not rdj_anchor.practice_anchor(row(spec), "external", rundir=run.root, context=context(run))


@pytest.mark.parametrize("changes", [
    {"excerpt_span": {"start": True, "end": 2}}, {"excerpt_span": {"start": 1, "end": 999}},
    {"excerpt_sha256": "0" * 64}, {"content_sha256": "0" * 64},
])
def test_excerpt_is_bound_to_acquired_bytes(tmp_path, changes):
    run, spec, _ = acquired(tmp_path)
    spec["binding"].update(changes)
    assert rdj_anchor.verify(row(spec), run.root, context=context(run)) == "invalid"


def test_reference_descriptor_from_later_generated_bytes_grants_no_practice_authority(tmp_path):
    run, spec, _ = acquired(tmp_path, descriptor=False)
    reference = {"schema_version": 1, "kind": "scientific-practice-reference", "source_class": "standard_reference",
                 "source": {"uri": "fixture://source", "record_id": "fictional-reference"},
                 "content_sha256": spec["binding"]["content_sha256"]}
    spec["binding"]["source_reference"] = run.put("inputs/later-reference.json", reference)
    assert not rdj_anchor.practice_anchor(row(spec), "external", rundir=run.root, context=context(run))


def test_generated_reference_descriptor_and_opinion_output_never_grant_authority(tmp_path):
    run, spec, executor = acquired(tmp_path)
    ctx = {**context(run), "generated": ["inputs/reference.json"]}
    assert not rdj_anchor.practice_anchor(row(spec), "external", rundir=run.root, context=ctx)
    value = {"kind": "review_verdict", "claim": "The method is correct"}
    raw = json.dumps(value).encode()
    (executor.workspace / "outputs/source.txt").write_bytes(raw)
    # An opinion record stays generated even when a genuine producer captures it.
    executor.allowed_actions.add("opinion")
    executor.register("opinion", lambda args: {"output_paths": ["outputs/source.txt"],
        "source": {"uri": "fixture://source", "record_id": "fictional-reference"}}, derivation="retrieval")
    executor.call({"call_id": "opinion", "action": "opinion", "args": {}})
    receipt = executor.workspace / "calls/2.json"
    spec["binding"].update(acquisition_receipt={"path": broker.logical(run.root, receipt),
        "sha256": sha(receipt.read_bytes())}, content_sha256=sha(raw), excerpt_sha256=sha(raw),
        excerpt_span={"start": 0, "end": len(raw)})
    assert rdj_anchor.verify(row(spec), run.root, context=context(run)) == "generated"


def test_reference_descriptor_mutation_reopens_practice_gap(tmp_path):
    run, spec, _ = acquired(tmp_path)
    case_id = choice_case(run, Roles(), [spec])
    assert rdj.authorize(run.root, case_id)["outcome"] == "authorize"
    run.put("inputs/reference.json", {"kind": "citation"})
    with pytest.raises(rdj.OpenItems) as refused:
        rdj.authorize(run.root, case_id)
    assert "exploratory_choice" in {item["code"] for item in refused.value.items}


def test_excerpt_value_and_board_boundary_cannot_be_overridden(tmp_path):
    run, spec, _ = acquired(tmp_path)
    anchor = row({**spec, "value": "A stronger claim"})
    assert rdj_anchor.verify(anchor, run.root, context=context(run)) == "invalid"
    path = spec["binding"]["acquisition_receipt"]["path"].rsplit("/", 2)[0]
    ctx = {**context(run), "generated_dirs": [path]}
    assert rdj_anchor.verify(row(spec), run.root, context=ctx) == "generated"


def test_reacquisition_receipts_do_not_make_identical_content_independent(tmp_path):
    _, spec, _ = acquired(tmp_path)
    other = copy.deepcopy(spec)
    other["binding"]["acquisition_receipt"]["path"] = "agent-work/other/1/calls/1.json"
    assert rdj_anchor.evidence_source(spec) == rdj_anchor.evidence_source(other)
    assert hash(rdj_anchor.evidence_source(spec))
