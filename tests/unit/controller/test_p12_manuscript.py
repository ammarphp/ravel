"""P12: a manuscript is delivered only from staged authoring, manuscript.build and the PDF build (R03)."""
from __future__ import annotations

from copy import deepcopy

import pytest

from ravel.controller.routes import manuscript, ml

PLAN_SHA = "d" * 64


class Store:
    """A fake ``RunStore`` (append and scan only) holding the governed step's records."""

    def __init__(self):
        self.rows = {}

    def append(self, kind, record):
        rows = self.rows.setdefault(kind, [])
        identifier = f"{kind}-{len(rows) + 1}"
        rows.append({"id": identifier, "kind": kind, "record": deepcopy(record)})
        return identifier

    def scan(self, kind):
        return deepcopy(self.rows.get(kind, []))


def step(step_id, kind, *, depends_on=(), outputs=(), **extra):
    row = {"id": step_id, "kind": kind, "inputs": [], "outputs": list(outputs), "depends_on": list(depends_on),
           "waypoint": False, "rung": None, "budget": {}, "protocols": [], "review": [], "instruction_sources": [],
           "obligations": []}
    row.update(extra)
    return row


def out(path, kind="document"):
    return {"path": path, "kind": kind, "required": True}


def manuscript_plan(route="manuscript"):
    steps = [
        step("m01-author", "author", role="manuscript-writer",
             outputs=[out("outputs/claim_map.json", manuscript.CLAIM_MAP_KIND), out("outputs/outline.md")]),
        step("m02-build", "subgraph", depends_on=["m01-author"], graph={"id": "manuscript.build"},
             role="manuscript-writer", outputs=[out("outputs/sources/main.tex")]),
        step("m03-pdf", "operate", depends_on=["m02-build"], operation="manuscript-build", role="analysis-author",
             outputs=[out("outputs/manuscript.pdf")]),
    ]
    deliverables = [{"id": "D1", "status": "mapped", "step": "m03-pdf", "output": "outputs/manuscript.pdf",
                     "reason": None, "artifact_kind": "document", "claim_kind": "document"}]
    return {"schema_version": 1, "kind": "controller-plan", "revision": 0,
            "route": {"id": route, "version": 1, "spec_sha256": "e" * 64}, "steps": steps,
            "deliverables": deliverables, "waypoints": [], "sha256": PLAN_SHA}


def complete(store, step_id, path, status="accepted"):
    store.append("step-outcome", {"schema_version": 1, "step_id": step_id, "attempt": 1, "status": "completed"})
    store.append("custody", {"schema_version": 1, "artifact": f"{step_id}:{path}", "step_id": step_id, "path": path,
                             "sha256": "f" * 64, "kind": "document", "status": status})


def receipted(store):
    complete(store, "m01-author", "outputs/claim_map.json")
    complete(store, "m02-build", "outputs/sources/main.tex")
    complete(store, "m03-pdf", "outputs/manuscript.pdf")


def codes(errors):
    return [e["code"] for e in errors]


def approved(kind, pins):
    return {"id": "a1"} if kind == "approve_plan" and pins == {"plan_sha256": PLAN_SHA} else None


def test_R03_receipted_manuscript_delivers():
    """Positive control: every stage completed with accepted custody."""
    store, plan = Store(), manuscript_plan()
    receipted(store)
    assert manuscript.delivery_errors_from_store(store, plan) == []


def test_R03_pdf_built_outside_manuscript_build_refused():
    """The mutation: a worker submits a PDF from its authoring step; the plan maps the deliverable there."""
    store, plan = Store(), manuscript_plan(route="judgment")
    plan["steps"][0]["outputs"].append(out("outputs/paper.pdf"))
    plan["deliverables"] = [dict(plan["deliverables"][0], step="m01-author", output="outputs/paper.pdf")]
    complete(store, "m01-author", "outputs/paper.pdf")
    errors = manuscript.delivery_errors_from_store(store, plan)
    assert codes(errors) == ["manuscript_built_outside_mode"]


def test_R03_unreceipted_build_refused():
    store, plan = Store(), manuscript_plan()
    complete(store, "m01-author", "outputs/claim_map.json")
    complete(store, "m02-build", "outputs/sources/main.tex")
    assert codes(manuscript.delivery_errors_from_store(store, plan)) == ["manuscript_unreceipted"]
    complete(store, "m03-pdf", "outputs/manuscript.pdf", status="rejected")
    assert codes(manuscript.delivery_errors_from_store(store, plan)) == ["manuscript_unreceipted"]


def test_R03_unreceipted_stage_refused():
    store, plan = Store(), manuscript_plan()
    complete(store, "m01-author", "outputs/claim_map.json", status="staged")
    complete(store, "m02-build", "outputs/sources/main.tex")
    complete(store, "m03-pdf", "outputs/manuscript.pdf")
    errors = manuscript.delivery_errors_from_store(store, plan)
    assert codes(errors) == ["manuscript_stage_unreceipted"] and errors[0]["step"] == "m01-author"


@pytest.mark.parametrize("cut", ["authoring", "build-graph"])
def test_R03_route_cannot_reach_deliver_without_staging(cut):
    store, plan = Store(), manuscript_plan()
    if cut == "authoring":
        plan["steps"][0]["outputs"] = [out("outputs/outline.md")]  # no claim map
        expected = "manuscript_claim_map_missing"
    else:
        plan["steps"][2]["depends_on"] = ["m01-author"]
        plan["steps"] = [plan["steps"][0], plan["steps"][2]]
        expected = "manuscript_staging_missing"
    receipted(store)
    assert expected in codes(manuscript.delivery_errors_from_store(store, plan))
    pdf = plan["steps"][-1]
    assert expected in codes(ml.admit(pdf, plan=plan, authority=approved))


def test_R03_pdf_document_in_any_plan_is_a_manuscript():
    store, plan = Store(), manuscript_plan(route="analysis")
    plan["steps"].append(step("x9", "synthesize", outputs=[out("outputs/note.pdf")]))
    plan["deliverables"].append({"id": "D2", "status": "mapped", "step": "x9", "output": "outputs/note.pdf",
                                 "reason": None, "artifact_kind": "document", "claim_kind": "finding"})
    receipted(store)
    complete(store, "x9", "outputs/note.pdf")
    errors = manuscript.delivery_errors_from_store(store, plan)
    assert codes(errors) == ["manuscript_built_outside_mode"] and errors[0]["deliverable"] == "D2"


def test_R03_non_manuscript_deliverables_untouched():
    store, plan = Store(), manuscript_plan(route="analysis")
    plan["steps"].append(step("x9", "synthesize", outputs=[out("outputs/limits.json", "table"),
                                                         out("outputs/summary.md")]))
    plan["deliverables"] = [
        {"id": "D3", "status": "mapped", "step": "x9", "output": "outputs/limits.json", "reason": None,
         "artifact_kind": "table", "claim_kind": "exclusion"},
        {"id": "D4", "status": "mapped", "step": "x9", "output": "outputs/summary.md", "reason": None,
         "artifact_kind": "document", "claim_kind": "document"}]
    assert manuscript.delivery_errors_from_store(store, plan) == []


def test_MODE_manuscript_build_admitted_with_full_contract():
    plan = manuscript_plan()
    assert ml.admit(plan["steps"][2], plan=plan, authority=approved) == []
    assert ml.admit(plan["steps"][1], plan=plan, authority=approved) == []


@pytest.mark.parametrize("part", ["executor", "authority", "delivery", "kind"])
def test_MODE_manuscript_build_vocabulary_grants_nothing(part):
    plan = manuscript_plan()
    pdf = plan["steps"][2]
    authority = approved
    if part == "executor":
        pdf["role"] = "manuscript-writer"
        expected = "mode_executor_mismatch"
    elif part == "authority":
        authority = lambda kind, pins: None  # noqa: E731
        expected = "mode_authority_missing"
    elif part == "delivery":
        plan["deliverables"] = []
        expected = "mode_delivery_contract_missing"
    else:
        pdf["kind"] = "author"
        expected = "manuscript_build_kind"
    assert expected in codes(ml.admit(pdf, plan=plan, authority=authority))


def test_MODE_manuscript_build_graph_needs_claim_map():
    plan = manuscript_plan()
    build = plan["steps"][1]
    build["depends_on"] = []
    assert "manuscript_claim_map_missing" in codes(ml.admit(build, plan=plan, authority=approved))
    build["operation"] = "manuscript-build"
    assert "mode_step_operation" in codes(ml.admit(build, plan=plan, authority=approved))


def test_A06_C03_manuscript_checkin1_rows_need_credit_and_the_accepted_claim_map(tmp_path, monkeypatch):
    """CHECK-IN 1's content rows come from the route's own evidence; without it nothing is recorded."""
    from ravel.controller.routes.analysis import discharge
    from ravel.controller.routes.manuscript import staged
    from ravel.controller.routes.ml import staged as artifacts
    plan = {"sha256": "c" * 64, "checkins": [{"id": "checkin1"}], "deliverables": [{"id": "D1"}],
            "steps": [{"id": "m01-author", "kind": "author", "outputs": [
                {"path": "outputs/claim_map.json", "kind": "manuscript:claim-map", "required": True},
                {"path": "outputs/trap_sweep.json", "kind": "validation:trap-sweep", "required": True}]}]}
    sweep = {"none_hit": True, "traps_hit": []}
    recorded, adopted = [], {}
    monkeypatch.setattr(discharge, "record", lambda store, node, status, evidence, rows=None, **kw:
                        recorded.append((node, status, sorted(rows), evidence)) or sorted(rows))

    def found(store, run_dir, step_id, path, **kw):
        if (step_id, path) not in adopted:
            raise artifacts.AdoptionMissing(path)
        return b"", None, {"sha256": adopted[(step_id, path)]}
    monkeypatch.setattr(artifacts, "adopted", found)
    monkeypatch.setattr(artifacts, "adopted_json", lambda *a, **kw: (dict(sweep), None, found(*a, **kw)[2]))
    credited = {"state": {"reviews": {"checkin1": {"plan-critic": {"credited": True, "receipts": ["r1"]}}}}}
    context = {"store": object(), "plan": plan, "run_dir": str(tmp_path), **credited}
    assert staged.checkin("approve_plan", context) == {}
    assert [(r[1], r[2]) for r in recorded] == [("not_applicable", ["C04"])], "no claim map: no content rows"
    adopted[("m01-author", "outputs/claim_map.json")] = "d" * 64
    adopted[("m01-author", "outputs/trap_sweep.json")] = "e" * 64
    recorded.clear()
    staged.checkin("approve_plan", {**context, "state": {"reviews": {}}})
    assert [(r[1], r[2]) for r in recorded] == [("not_applicable", ["C04"])], "no credit: no content rows"
    recorded.clear()
    staged.checkin("approve_plan", context)
    assert [(r[1], r[2]) for r in recorded] == [("not_applicable", ["C04"]), ("satisfied", ["A06", "C03"]),
                                                ("not_applicable", ["C14"])]
    assert recorded[1][3]["content"] == ["d" * 64] and recorded[1][3]["credit"].startswith("review:")
    assert recorded[2][3]["trap_sweeps"] == ["e" * 64]
    for hit, reading in (({"none_hit": False, "traps_hit": [{"id": "T3"}]}, {}),
                         ({"none_hit": True, "traps_hit": []}, {"ambiguities": [{"issue": "which unit", "status": "open"}]})):
        sweep.clear(); sweep.update(hit)
        recorded.clear()
        staged.checkin("approve_plan", {**context, "reading": reading})
        assert ("not_applicable", ["C14"]) not in [(r[1], r[2]) for r in recorded], "a hit trap or open ambiguity stays"
    sweep.clear(); sweep.update(none_hit=True, traps_hit=[])
    recorded.clear()
    staged.checkin("final", context)
    assert recorded == []
    with_variants = {**context, "plan": {**plan, "checkins": [{"id": "checkin1", "variants": ["a", "b"]}]}}
    staged.checkin("approve_plan", with_variants)
    assert ("not_applicable", ["C04"]) not in [(r[1], r[2]) for r in recorded]
