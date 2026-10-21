"""P12: ML and manuscript science modes are admitted only on their full contract (MODE rows, R12)."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from ravel.controller.routes import ml
from ravel.controller.routes.ml import modes, training

PLAN_SHA = "a" * 64
INFERENCE_MODES = ("published-classifier", "classifier-inputs", "analysis-response-features")
OUTPUT_KINDS = {"published-classifier": "table", "classifier-inputs": "table", "analysis-response-features": "table"}


class Authority:
    """A fake of the authority service's ``current(store, kind, pins)``, bound to one store."""

    def __init__(self, *granted):
        self.granted = [dict(kind=kind, pins=pins) for kind, pins in granted]
        self.asked = []

    def __call__(self, kind, pins):
        self.asked.append((kind, dict(pins)))
        for row in self.granted:
            if row["kind"] == kind and all(pins.get(k) == v for k, v in row["pins"].items()):
                return {"id": f"auth-{len(self.asked)}", "kind": kind, "subject": {"pins": dict(pins)}}
        return None


def plan_approved():
    return ("approve_plan", {"plan_sha256": PLAN_SHA})


def training_r3(step="t03-study"):
    return ("r3_action", {"plan_sha256": PLAN_SHA, "step": step, "operation": "ml-training"})


def step(step_id, kind, *, depends_on=(), outputs=(), **extra):
    row = {"id": step_id, "kind": kind, "inputs": [], "outputs": list(outputs), "depends_on": list(depends_on),
           "waypoint": False, "rung": None, "budget": {}, "protocols": [], "review": [], "instruction_sources": [],
           "obligations": []}
    row.update(extra)
    return row


def out(path, kind, required=True):
    return {"path": path, "kind": kind, "required": required}


def plan(route, steps, deliverables):
    return {"schema_version": 1, "kind": "controller-plan", "revision": 0,
            "route": {"id": route, "version": 1, "spec_sha256": "b" * 64}, "steps": steps,
            "deliverables": deliverables, "waypoints": [], "sha256": PLAN_SHA}


def mapped(deliverable, step_id, output, artifact="table", claim="estimate"):
    return {"id": deliverable, "status": "mapped", "step": step_id, "output": output, "reason": None,
            "artifact_kind": artifact, "claim_kind": claim}


def inference_plan(mode="published-classifier", **override):
    apply = step("i03-apply", "operate", depends_on=["i01-spec"], operation=mode, role="analysis-author",
                 outputs=[out("outputs/performance.json", OUTPUT_KINDS[mode])])
    apply.update(override)
    report = step("i04-report", "synthesize", depends_on=["i03-apply"], role="analysis-author",
                  outputs=[out("outputs/report.md", "document")])
    spec = step("i01-spec", "author", role="analysis-author", outputs=[out("outputs/spec.json", "document")])
    return plan("ml.inference", [spec, apply, report], [mapped("D1", "i04-report", "outputs/report.md")]), apply


def training_plan(route="ml.training", **override):
    study = step("t03-study", "subgraph", depends_on=["t01-spec"], graph={"id": "ml.study"}, operation="ml-training",
                 role="ml-trainer", consequence_class="R3",
                 outputs=[out("outputs/ml_study.json", "table"), out("outputs/classifier.json", "selection")])
    study.update(override)
    spec = step("t01-spec", "author", role="ml-planner", outputs=[out("outputs/spec.json", "document")])
    return plan(route, [spec, study], [mapped("D1", "t03-study", "outputs/ml_study.json")]), study


def codes(errors):
    return [e["code"] for e in errors]


# ---- inference modes ------------------------------------------------------------------------

@pytest.mark.parametrize("mode", INFERENCE_MODES)
def test_MODE_inference_admitted_with_full_contract(mode):
    """Positive control: typed adapter, executor, authority and delivery contract all present."""
    found, apply = inference_plan(mode)
    assert ml.admit(apply, plan=found, authority=Authority(plan_approved())) == []


def _refusals(mode, mutate):
    found, apply = inference_plan(mode)
    authority = Authority(plan_approved())
    mutate(found, apply, authority)
    return codes(ml.admit(apply, plan=found, authority=authority))


def _no_executor(found, apply, authority):
    apply["role"] = "investigation-worker"


def _no_authority(found, apply, authority):
    authority.granted.clear()


def _no_delivery(found, apply, authority):
    found["deliverables"] = [dict(found["deliverables"][0], status="open", step=None, output=None)]


def _no_outputs(found, apply, authority):
    apply["outputs"] = []


def _untyped_task(found, apply, authority):
    apply["parameters"] = {"task": {"mode": "ml-training"}}


MUTATIONS = {"executor": (_no_executor, "mode_executor_mismatch"),
             "authority": (_no_authority, "mode_authority_missing"),
             "delivery": (_no_delivery, "mode_delivery_contract_missing"),
             "outputs": (_no_outputs, "mode_outputs_undeclared"),
             "task": (_untyped_task, "mode_task_mismatch")}


@pytest.mark.parametrize("part", sorted(MUTATIONS))
def test_MODE_published_classifier_vocabulary_grants_nothing(part):
    mutate, expected = MUTATIONS[part]
    assert expected in _refusals("published-classifier", mutate)


@pytest.mark.parametrize("part", sorted(MUTATIONS))
def test_MODE_classifier_inputs_vocabulary_grants_nothing(part):
    mutate, expected = MUTATIONS[part]
    assert expected in _refusals("classifier-inputs", mutate)


@pytest.mark.parametrize("part", sorted(MUTATIONS))
def test_MODE_analysis_response_features_vocabulary_grants_nothing(part):
    mutate, expected = MUTATIONS[part]
    assert expected in _refusals("analysis-response-features", mutate)


@pytest.mark.parametrize("mode", INFERENCE_MODES)
def test_MODE_typed_adapter_required(mode):
    found, apply = inference_plan(mode)
    table = modes.signatures()
    untyped = deepcopy(table)
    untyped[mode]["implementation"] = {"kind": "command", "module": "ravel.physics.not_an_adapter"}
    assert "mode_adapter_untyped" in codes(ml.admit(apply, plan=found, authority=Authority(plan_approved()),
                                                     signature_table=untyped))
    missing = deepcopy(table)
    missing[mode]["implementation"]["module"] = "ravel.physics.no_such_adapter_module"
    assert "mode_adapter_missing" in codes(ml.admit(apply, plan=found, authority=Authority(plan_approved()),
                                                     signature_table=missing))
    assert "mode_not_registered" in codes(ml.admit(apply, plan=found, authority=Authority(plan_approved()),
                                                    modes=()))
    gone = {k: v for k, v in table.items() if k != mode}
    assert "mode_signature_missing" in codes(ml.admit(apply, plan=found, authority=Authority(plan_approved()),
                                                       signature_table=gone))


def test_MODE_admission_never_reads_the_descriptor_vocabulary(monkeypatch):
    """A descriptor match alone grants nothing: admission does not consult the descriptors at all."""
    import builtins
    real_open = builtins.open
    descriptors = str(Path(modes.DATA / "mode_descriptors.json"))

    def guarded(file, *args, **kwargs):
        assert str(file) != descriptors, "admission read the suggestion vocabulary"
        return real_open(file, *args, **kwargs)
    monkeypatch.setattr(builtins, "open", guarded)
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: (_ for _ in ()).throw(AssertionError(str(self)))
                        if str(self) == descriptors else Path.read_bytes(self).decode())
    found, apply = inference_plan()
    assert ml.admit(apply, plan=found, authority=Authority(plan_approved())) == []
    apply_only_named = step("x", "operate", operation="published-classifier")
    found["steps"].append(apply_only_named)
    assert ml.admit(apply_only_named, plan=found, authority=None)


def test_MODE_step_outside_the_plan_refused():
    found, apply = inference_plan()
    stray = dict(apply, id="injected")
    assert codes(ml.admit(stray, plan=found, authority=Authority(plan_approved()))) == ["mode_step_not_in_plan"]


def test_MODE_authority_error_never_admits():
    found, apply = inference_plan()

    def failing(kind, pins):
        raise RuntimeError("store unavailable")
    assert "mode_authority_unavailable" in codes(ml.admit(apply, plan=found, authority=failing))
    assert "mode_authority_unavailable" in codes(ml.admit(apply, plan=found, authority=None))


def test_MODE_ungoverned_step_is_left_to_its_own_admission():
    found, apply = inference_plan()
    other = step("o1", "operate", operation="event-production")
    assert ml.admit(other, plan=found, authority=None) == []
    assert ml.governed(other) is None and ml.governed(apply) == "published-classifier"


# ---- training (R12, MODE-ml-training) -------------------------------------------------------

def test_MODE_ml_training_holds_with_typed_prerequisite_reason():
    """Fully authorized training through ml.study still holds: the staged executor does not exist."""
    found, study = training_plan()
    errors = ml.admit(study, plan=found, authority=Authority(plan_approved(), training_r3()))
    assert codes(errors) == ["ml_training_prerequisites_unmet"]
    assert errors[0]["hold"] == ml.PREREQUISITE_HOLD
    assert errors[0]["missing"][0]["id"] == "staged_ml_executor"


def test_MODE_ml_training_hold_reason_matches_the_study_graph():
    source = Path(training.__file__).resolve().parents[3] / "workflow" / "graphs" / "ml_study.py"
    assert repr(ml.PREREQUISITE_HOLD) in source.read_text(encoding="utf-8")


def test_MODE_ml_training_positive_control_with_staged_executor():
    """With every prerequisite met, training is admitted (the probe is supplied by the test only)."""
    found, study = training_plan()
    assert ml.admit(study, plan=found, authority=Authority(plan_approved(), training_r3()), prerequisites=[]) == []

    class Staged:
        pass
    for name in ml.STAGED_INTERFACE:
        setattr(Staged, name, staticmethod(lambda *a, **k: None))
    assert training.prerequisites(Staged) == []
    assert training.prerequisites(object())[0]["missing"] == list(ml.STAGED_INTERFACE)


def test_MODE_ml_training_atomic_operation_refused():
    found, study = training_plan(kind="operate", graph=None)
    study.pop("graph")
    errors = codes(ml.admit(study, plan=found, authority=Authority(plan_approved(), training_r3()), prerequisites=[]))
    assert "ml_training_atomic_refused" in errors


def test_R12_inference_request_cannot_obtain_training():
    """An inference plan; the worker's replan adds training: admission refuses it."""
    found, apply = inference_plan()
    authority = Authority(plan_approved())
    assert ml.admit(apply, plan=found, authority=authority) == []
    # The worker asks for a training operation; the replanned inference plan now carries it.
    _, study = training_plan()
    found["steps"].append(study)
    found["deliverables"].append(mapped("D2", "t03-study", "outputs/ml_study.json"))
    errors = codes(ml.admit(study, plan=found, authority=authority, prerequisites=[]))
    assert "ml_training_outside_training_route" in errors
    assert "ml_training_authority_missing" in errors
    # Even on the training route, CHECK-IN 1 alone does not authorize training.
    found["route"]["id"] = "ml.training"
    assert codes(ml.admit(study, plan=found, authority=authority, prerequisites=[])) == ["ml_training_authority_missing"]
    # And with its own authority it still waits for the training prerequisites.
    authority.granted.append(dict(kind="r3_action", pins=training_r3()[1]))
    assert codes(ml.admit(study, plan=found, authority=authority)) == ["ml_training_prerequisites_unmet"]


def test_R12_training_authority_is_bound_to_plan_step_and_operation():
    found, study = training_plan()
    other_step = Authority(plan_approved(), training_r3(step="t09-other"))
    assert "ml_training_authority_missing" in codes(ml.admit(study, plan=found, authority=other_step, prerequisites=[]))
    other_plan = Authority(plan_approved(), ("r3_action", {"plan_sha256": "c" * 64, "step": "t03-study",
                                                           "operation": "ml-training"}))
    assert "ml_training_authority_missing" in codes(ml.admit(study, plan=found, authority=other_plan, prerequisites=[]))


def test_R12_inference_step_carrying_training_refused():
    found, apply = inference_plan(parameters={"task": {"mode": "published-classifier", "train": True}})
    assert "ml_inference_requests_training" in codes(ml.admit(apply, plan=found, authority=Authority(plan_approved())))


def test_R12_study_graph_without_operation_is_still_training():
    found, study = training_plan(operation=None)
    errors = codes(ml.admit(study, plan=found, authority=Authority(plan_approved())))
    assert ml.governed(study) == "ml-training"
    assert "ml_training_authority_missing" in errors and "ml_training_prerequisites_unmet" in errors


def test_R12_judgment_planned_training_needs_the_same_authority():
    found, study = training_plan(route="judgment")
    assert codes(ml.admit(study, plan=found, authority=Authority(plan_approved()), prerequisites=[])) == [
        "ml_training_authority_missing"]
    for route in ("ml.inference", "analysis", "study", "research"):
        found["route"]["id"] = route
        assert "ml_training_outside_training_route" in codes(
            ml.admit(study, plan=found, authority=Authority(plan_approved(), training_r3()), prerequisites=[]))


def test_MODE_executors_and_signatures_name_the_governed_modes():
    table, executors = modes.signatures(), modes.executor_table()
    for mode in modes.GOVERNED:
        assert table[mode]["implementation"] == {**table[mode]["implementation"], "kind": "science-mode", "mode": mode}
        assert executors["operations"][mode]
    assert json.loads(json.dumps(ml.GOVERNED)) == list(ml.GOVERNED)
