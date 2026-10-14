"""The reading and plan contract itself: evaluated keywords only, closed vocabularies, and the rules.

These tests run before the reader and planner land; they check the contract the suites hold the
production modules to.
"""
import copy

import pytest

import intake_records as ir
import record_examples as ex


def test_schemas_use_only_evaluated_keywords():
    for name, schema in (("reading", ir.READING_SCHEMA), ("plan", ir.PLAN_SCHEMA)):
        unknown = ir.schema_keywords(schema) - ir.EVALUATED_KEYWORDS
        assert not unknown, f"{name} schema uses keywords the stdlib validator ignores: {sorted(unknown)}"


def test_vocabularies_are_closed_and_name_no_workflow_or_source():
    for name, values in ir.VOCABULARIES.items():
        assert len(values) == len(set(values)), name
        named = [v for v in values if ir.VOCABULARY_DENYLIST.search(v)]
        assert not named, f"{name} names a workflow, paper, benchmark or experiment: {named}"
    sizes = {k: len(v) for k, v in ir.VOCABULARIES.items()}
    assert sizes["artifact kinds"] == 13 and sizes["effects"] == 9 and sizes["node kinds"] == 4
    assert sizes["claim kinds"] == 9 and sizes["bases"] == 13 and sizes["boundary classes"] == 6


def test_production_vocabularies_match_when_they_land():
    """Any vocabulary constant a landed module exports must equal the contract's."""
    names = {"ARTIFACT_KINDS": ir.ARTIFACT_KINDS, "EFFECTS": ir.EFFECTS, "CLAIM_KINDS": ir.CLAIM_KINDS,
             "BOUNDARY_CLASSES": ir.BOUNDARY_CLASSES, "CONSTRAINT_TYPES": ir.CONSTRAINT_TYPES,
             "FIELD_AUTHORITY": ir.FIELD_AUTHORITY, "DISMISSALS": ir.DISMISSALS, "BASES": ir.BASES,
             "NODE_KINDS": ir.NODE_KINDS, "WAYPOINT_KINDS": ir.WAYPOINT_KINDS}
    intake = ir.Intake()
    modules = [m for m in (intake.reading_module, intake.plan_module, intake.check_module, intake.label_module) if m]
    if not modules:
        pytest.skip("no reading or plan module has landed")
    for module in modules:
        for name, expected in names.items():
            value = getattr(module, name, None)
            if value is not None:
                assert set(value) == set(expected), f"{module.__name__}.{name}"


def test_example_records_satisfy_the_contract():
    reading, plan = ex.reading(), ex.plan()
    assert ir.reading_rule_errors(ex.PROMPT, reading) == []
    assert ir.plan_rule_errors(reading, plan, ["original-request", "O1"]) == []


def _mutated_reading(change):
    reading = ex.reading()
    change(reading)
    return ir.reading_rule_errors(ex.PROMPT, reading)


@pytest.mark.parametrize("change,needle", [
    (lambda r: r["facts"][0]["evidence"][0].update(text="10000"), "does not equal the request bytes"),
    (lambda r: r.update(prompt_sha256="0" * 64), "prompt_sha256"),
    (lambda r: r["facts"][2].update(witness=None), "neither used nor dismissed"),
    (lambda r: r["dismissed"].append({"witness": "W9", "reason": "negated", "note": "x"}), "unknown witness"),
    (lambda r: r["facts"][0].update(evidence=[]), "user_quoted without a span"),
    (lambda r: r["constraints"].append({"id": "K4", "type": "delegation", "value": {"authority_granted": True},
                                        "evidence": [ex.span(ex.PROMPT, "Generate")]}), "authority_granted false"),
    (lambda r: r["authors"].insert(0, ex.author("host-agent")), "deterministic reader must be the first"),
    (lambda r: r["constraints"].append(dict(r["constraints"][0])), "duplicate constraints ids"),
    (lambda r: r["constraints"][0].update(type="routing_hint"), "schema"),
    (lambda r: r.update(extra=1), "schema"),
    (lambda r: r["boundaries"].append({"id": "B1", "class": "out_of_scope", "obligation_ids": [], "statement": "s",
                                       "would_make_possible": "w", "evidence": [ex.span(ex.PROMPT, "plot")]}), "schema"),
    (lambda r: r["boundaries"].append({"id": "B1", "class": "contradiction", "obligation_ids": [], "statement": "s",
                                       "would_make_possible": "w", "evidence": []}), "schema"),
])
def test_reading_rules_refuse(change, needle):
    errors = _mutated_reading(change)
    assert any(needle in e for e in errors), errors


def _mutated_plan(change, obligations=("original-request", "O1")):
    reading, plan = ex.reading(), ex.plan()
    change(plan)
    return ir.plan_rule_errors(reading, plan, list(obligations))


@pytest.mark.parametrize("change,needle", [
    (lambda p: p.update(coverage=[p["coverage"][0]]), "covered by nothing"),
    (lambda p: p["coverage"][1]["by"].append("N7"), "names unknown"),
    (lambda p: p["edges"].append({**p["edges"][0], "id": "E2", "from": {"ref": "N2", "slot": "x"},
                                  "to": {"ref": "N1", "slot": "y"}}), "cycle"),
    (lambda p: p["edges"][0]["to"].update(ref="N9"), "unknown N9"),
    (lambda p: p.update(status="approved"), "schema"),
    (lambda p: p["claims"][0].update(kind="discovery"), "schema"),
    (lambda p: p["claims"][0].update(inherits=["C2"]), "not a document claim"),
    (lambda p: p.update(nodes=[dict(p["nodes"][0], id=f"N{i + 1}") for i in range(129)]), "schema"),
    (lambda p: p["boundaries"].append("B3"), "absent from the reading"),
    (lambda p: p.update(prompt_sha256="0" * 64), "different requests"),
    (lambda p: p["label"].update(rule="D6"), "schema"),
])
def test_plan_rules_refuse(change, needle):
    errors = _mutated_plan(change)
    assert any(needle in e for e in errors), errors


def test_bare_refusal_detection():
    reading, plan = ex.reading(), ex.plan()
    assert ir.bare_refusal(reading, plan) == []
    held = copy.deepcopy(reading)
    assert ir.bare_refusal(held, plan, {"task_mode": "unsupported", "rule": "D1"})
    held["boundaries"].append({"id": "B1", "class": "no_scientific_object", "obligation_ids": ["original-request"],
                               "statement": "nothing actionable remains", "would_make_possible": "state a physics question",
                               "evidence": [ex.span(ex.PROMPT, "Generate")]})
    assert ir.bare_refusal(held, plan, {"task_mode": "unsupported", "rule": "D1"}) == []
    empty = copy.deepcopy(plan)
    empty.update(inputs=[], claims=[])
    for node in empty["nodes"]:
        node.update(status="held", held_by=None)
    assert ir.bare_refusal(reading, empty)


def test_neutral_projection_ignores_identity_offsets_and_ids():
    label = "Example evaluation suite, task 3. "
    shifted_prompt = label + ex.PROMPT
    base = ex.reading()
    shifted = ex.reading(shifted_prompt)
    shifted["constraints"].append({"id": "K9", "type": "identity_context", "value": {"label": label.strip()},
                                   "evidence": [ex.span(shifted_prompt, label.strip())]})
    for item in shifted["facts"]:
        item["id"] = "F" + str(int(item["id"][1:]) + 10)
    assert ir.neutral_projection(base) == ir.neutral_projection(shifted)
    shifted["constraints"][0]["value"] = {"tool": "Herwig"}
    assert ir.neutral_projection(base) != ir.neutral_projection(shifted)


def test_intake_binds_landed_modules(monkeypatch):
    """The harness binds a module as soon as it is importable, with the contract's function names."""
    import sys
    import types

    def document(prompt, interpretation=None):
        base = ex.reading(ex.PROMPT)
        base.update(prompt_sha256=ir.prompt_sha256(prompt), witness=[], facts=[], constraints=[])
        return base

    def draft(reading, contract):
        return dict(ex.plan(), prompt_sha256=reading["prompt_sha256"])

    def derive(reading, plan):
        return {"task_mode": "generate", "rule": "D2", "floor_row": "generate"}

    for name, attrs in (("ravel.workflow.request_reading", {"document": document}),
                        ("ravel.workflow.request_plan", {"draft": draft}),
                        ("ravel.validation.validate_request_plan", {}),
                        ("ravel.workflow.derived_label", {"derive": derive})):
        monkeypatch.setitem(sys.modules, name, types.SimpleNamespace(__name__=name, **attrs))
    intake = ir.Intake()
    reading = intake.read("Compute the Z width.")
    assert ir.reading_rule_errors("Compute the Z width.", reading) == []
    plan = intake.plan(reading, {"prompt": "Compute the Z width."})
    assert ir.plan_rule_errors(reading, plan, ["original-request"]) == []
    assert intake.label(reading, plan)["rule"] == "D2"
    assert ir.bare_refusal(reading, plan, intake.label(reading, plan)) == []
    with pytest.raises(pytest.skip.Exception):
        intake.plan_errors(reading, plan)


def test_landed_schemas_use_only_evaluated_keywords():
    """T9 for the production modules: every module-level *SCHEMA dict is stdlib-evaluable."""
    intake = ir.Intake()
    modules = [m for m in (intake.reading_module, intake.plan_module, intake.check_module, intake.label_module) if m]
    if not modules:
        pytest.skip("no reading or plan module has landed")
    for module in modules:
        for name in dir(module):
            value = getattr(module, name)
            if name.endswith("SCHEMA") and isinstance(value, dict):
                unknown = ir.schema_keywords(value) - ir.EVALUATED_KEYWORDS - {"$comment"}
                assert not unknown, f"{module.__name__}.{name} uses {sorted(unknown)}"
