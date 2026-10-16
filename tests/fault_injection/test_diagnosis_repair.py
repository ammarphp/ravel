"""Fictional finite controls for diagnosis through corrected descendant reruns."""
from copy import deepcopy
import hashlib
import json

import pytest

from ravel.validation import residual_decomposition as rd
from ravel.workflow import agent_graph as graph
from ravel.workflow import constructive_contrast as cc
from ravel.workflow import diagnosis_repair as repair


def pin(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n")
    return pin(path)


def reference(path, value):
    return {"artifact": write(path, value), "pointer": ""}


def discrepancies(tmp_path):
    report = {"rows": [
        {"sr": "selection", "role": "driving", "mine": 0.5, "pub": 1., "ratio": .5,
         "ok": False, "mu95_impact": .5, "attribution": {"cause_class": "unresolved"}},
        {"sr": "tail", "role": "contributing", "mine": .9, "pub": 1., "ratio": .9,
         "ok": False, "mu95_impact": None, "attribution": {"cause_class": "unresolved"}}]}
    return repair.cutflow_discrepancies(write(tmp_path / "cutflow.json", report),
                                      graph_nodes={"selection": ["selection"], "tail": ["normalization"]})


def experiment(tmp_path, *, candidate_value=1., discriminating=True):
    row = discrepancies(tmp_path)[0]
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("selected = value >= 1\n")
    compound = tmp_path / "compound.txt"
    compound.write_text("selected = value > 1\n")
    license_path = tmp_path / "LICENSE"
    license_path.write_text("Fictional authored control.\n")
    census = write(tmp_path / "census.json", {"schema_version": 1, "kind": "original_event_census",
        "records": [{"event_id": str(i), "group_id": str(i), "shard_id": "original"} for i in range(16)]})
    basis = {"quantity": "selected_weight", "unit": "1", "normalization": "sum_original_weight",
             "role": "nominal", "definition": "Finite supplied control", "channels": ["selected"]}
    data = {}
    for arm, value in (("baseline", 2.), ("candidate", candidate_value)):
        data[arm] = write(tmp_path / (arm + ".json"), {
            "schema_version": 1, "kind": "events", "basis": basis, "population_id": "finite-control",
            "expected_exposure": 16, "uncertainty_scope": "supplied finite control", "scale": 1.,
            "records": [{"event_id": str(i), "group_id": str(i), "weight": 1., "bins": [value]} for i in range(16)]})
    plan = {"schema_version": 2, "source": "Fictional supplied record", "question": "Does the intervention decrease selected weight?",
        "manipulation": {"variable": "selection", "baseline": "inclusive", "candidate": "exclusive"},
        "fixed_artifacts": [pin(baseline), census],
        "comparison": {"kind": "paired_events", **data, "basis": basis, "require_complete_exposure": True},
        "hypotheses": [{"id": "H1", "statement": "Selected weight decreases", "channels": ["selected"],
                        "direction": "decrease", "relative_tolerance": .1}],
        "precision": {"max_relative_mc_error": .3, "envelope_sigma": 1., "reference_covariance": "required"},
        "data_use": [{"population_id": "finite-control", "role": "validation", "artifact": data[arm]}
                     for arm in ("baseline", "candidate")],
        "budget": {"max_attempts": 1, "max_seconds": 20, "max_new_events": 0},
        "stopping": {"success": "all_criteria_supported", "failure": "any_criterion_contradicted", "unresolved": "stop_without_conclusion"},
        "applicability": {"status": "established", "reason": "Finite engineering control only"}, "capacity": None}
    request = {"schema_version": 1, "finding": {"id": row["id"], "claim": "The comparator explains the discrepancy",
        "objection": "Measure the isolated intervention with matched events"},
        "baseline": pin(baseline), "compound_candidate": pin(compound), "license": pin(license_path),
        "component": {"id": "comparator", "before": ">= 1", "after": "> 1"}, "control_probes": [],
        "rivals": [{"id": "comparator", "statement": "Comparator changes selected weight", "predictions": {"H1": ["supported"]}},
                   {"id": "other", "statement": "Another component explains the discrepancy",
                    "predictions": {"H1": ["contradicted"] if discriminating else ["supported"]}}],
        "next_actions": {"supported": {"action": "propose_challenger_review", "reason": "Review measured challenger"},
                         "contradicted": {"action": "revise_hypothesis", "reason": "Preserve the adverse result"},
                         "unresolved": {"action": "request_evidence", "reason": "Retain missing information"}},
        "evaluation_contract": cc.freeze_contract(plan, original_census=census)}
    return row, request, plan


def correction(tmp_path):
    row, request, plan = experiment(tmp_path)
    prepared = repair.prepare_experiment(row, request)
    evaluation = repair.evaluate_experiment(prepared, plan)
    after = tmp_path / "corrected.txt"
    after.write_text(prepared["preparation"]["controlled_source"])
    record = {"discrepancy_id": row["id"], "rival_id": "comparator", "changed_nodes": ["selection"],
              "before": request["baseline"], "after": pin(after), "reason": "Recheck the measured intervention"}
    correction_pin = write(tmp_path / "correction.json", record)
    return repair.prepare_correction(evaluation, correction_pin)


def node(identity, dependencies=(), inputs=()):
    return {"id": identity, "kind": "tool", "role": "executor", "depends_on": list(dependencies),
            "inputs": list(inputs), "packet": None, "action": "finite_control", "parameters": {}, "max_attempts": 1}


def graph_spec(source, reworks=2):
    return {"schema_version": 1, "graph_id": "finite-diagnosis", "budget": {
        "max_nodes": 8, "max_calls": 20, "max_output_tokens": 100, "max_wall_seconds": 300, "max_reworks": reworks},
        "nodes": [node("cards"), node("selection", ["cards"], [{"id": "source", **source}]),
                  node("normalization", ["selection"]), node("templates", ["normalization"]),
                  node("inference", ["templates"]), node("independent")]}


class FiniteHost:
    identity = {"fixture": "finite-diagnosis-host"}

    def __init__(self):
        self.calls = []
        self.final_value = .25

    def execute(self, item, request, control):
        def run():
            self.calls.append(item["id"])
            return {"stage": item["id"], "requested": {
                "quantity": "upper_limit", "unit": "1", "value": self.final_value}}
        return control.call("finite_control", "tool", request, run, output_tokens=0)


def test_first_divergence_keeps_downstream_failures_and_independent_control(tmp_path):
    names = ["cards", "selection", "normalization", "templates", "inference", "independent"]
    expected, observed = [1., 4., 8., 8., .125, 4.], [1., 2., 4., 4., .25, 4.]
    stages = [{"id": name, "comparison": reference(tmp_path / (name + ".json"), {
        "observed": value, "expected": target, "absolute_tolerance": 1e-12})}
        for name, value, target in zip(names, observed, expected)]
    result = repair.first_divergence(stages)
    assert result["first"] == "selection"
    assert [r["passed"] for r in result["comparisons"]] == [True, False, False, False, False, True]
    assert result["cause_established"] is result["execution_authorized"] is False
    with pytest.raises(ValueError, match="duplicate stage"):
        repair.first_divergence(stages + stages[:1])


def test_cutflow_proxy_cannot_become_final_quantity_bound(tmp_path):
    rows = discrepancies(tmp_path)
    result = repair.rank_discrepancies(rows, {"id": "upper_limit", "unit": "1"})
    assert all(r["max_abs_supplied_bound"] is None for r in result["rows"])
    assert rows[0]["observation"]["mu95_impact"] == .5
    report_pin = rows[0]["source"]["artifact"]
    report = json.loads((tmp_path / "cutflow.json").read_text())
    report["rows"][0].update(mine=0., ratio=0.)
    report["rows"][1].update(mine=None, ratio=None, ok=True)
    rows = repair.cutflow_discrepancies(write(tmp_path / "zero.json", report),
        graph_nodes={"selection": ["selection"], "tail": ["normalization"]})
    assert len(rows) == 2 and rows[0]["observation"]["ratio"] == 0.
    assert report_pin != rows[0]["source"]["artifact"]


def test_endpoint_span_is_unbounded_and_separate_enclosures_rank_by_effect(tmp_path):
    rows = discrepancies(tmp_path)
    evidence = reference(tmp_path / "enclosure.json", {"domain": [0., 1.], "justification": "Fictional exhaustive finite enclosure"})
    for row, lower, upper in zip(rows, [-.4, -.1], [.2, .05]):
        row["effect"] = reference(tmp_path / (row["id"] + "-effect.json"), {
            "quantity": "upper_limit", "unit": "1", "lower": lower, "upper": upper,
            "kind": "supplied_enclosure", "basis": "Fictional finite-domain control", "enclosure_evidence": evidence})
    result = repair.rank_discrepancies(list(reversed(rows)), {"id": "upper_limit", "unit": "1"})
    assert [r["max_abs_supplied_bound"] for r in result["rows"]] == [.4, .1]
    endpoint = json.loads((tmp_path / "selection-effect.json").read_text())
    endpoint.update(kind="endpoint_sensitivity", enclosure_evidence=None)
    rows[0]["effect"] = reference(tmp_path / "endpoint.json", endpoint)
    result = repair.rank_discrepancies(rows, {"id": "upper_limit", "unit": "1"})
    assert result["rows"][0]["bound_status"] == "unknown"
    assert result["rows"][0]["sensitivity_span"] == .4
    with pytest.raises(ValueError, match="quantity or unit"):
        repair.rank_discrepancies(rows, {"id": "yield", "unit": "events"})


def test_residual_claim_reuses_actual_above_noise_refusal(tmp_path):
    model = {"schema_version": 1, "kind": "residual-model", "response": "inverse", "nodes": [{
        "id": "n0", "result": 2., "reference": 1., "regions": [{"name": "selected", "role": "signal",
        "background": [10.], "ours": {"yield": [5.], "sumw2": [.0001]},
        "reference": {"yield": [10.], "staterror": [.01]}}]}]}
    record = rd.decompose(model)
    rows = repair.residual_discrepancies(write(tmp_path / "decomposition.json", record),
        [{"term": "rate", "scope": "all"}], graph_nodes={"all:rate": ["normalization"]})
    assert rows[0]["id"] == "all:rate"
    with pytest.raises(ValueError, match="not above noise"):
        repair.residual_discrepancies(pin(tmp_path / "decomposition.json"), [{"term": "shape", "scope": "all"}],
            graph_nodes={"all:shape": ["selection"]})


def test_measured_discrimination_correction_and_descendant_rerun(tmp_path):
    fixed = correction(tmp_path)
    assert fixed["evaluation"]["application"]["surviving_rivals"] == ["comparator"]
    assert fixed["execution_authorized"] is fixed["discrepancy_resolved"] is False
    root = tmp_path / "graph"
    spec = graph_spec(fixed["correction"]["before"])
    graph.create(root, spec)
    host = FiniteHost()
    initial = graph.execute(root, host)
    before_usage = initial["usage"]["calls"]
    revised = deepcopy(spec)
    revised["nodes"][1]["inputs"] = [{"id": "source", **fixed["correction"]["after"]}]
    handoff = repair.request_rework(fixed, root, revised_spec=revised)
    state = handoff["graph"]
    assert state["usage"]["calls"] == before_usage and state["reworks"] == 1
    assert state["nodes"]["cards"]["status"] == state["nodes"]["independent"]["status"] == "completed"
    assert all(state["nodes"][name]["status"] == "pending" for name in ["selection", "normalization", "templates", "inference"])
    assert handoff["execution_authorized"] is handoff["discrepancy_resolved"] is False
    graph.execute(root, host)
    assert host.calls.count("cards") == host.calls.count("independent") == 1
    assert all(host.calls.count(name) == 2 for name in ["selection", "normalization", "templates", "inference"])


def test_unresolved_and_nondiscriminating_experiments_cannot_correct(tmp_path):
    row, request, plan = experiment(tmp_path)
    prepared = repair.prepare_experiment(row, request)
    unresolved = repair.evaluate_experiment(prepared)
    assert unresolved["state"] == "needs_discriminating_evidence"
    with pytest.raises(ValueError, match="cannot select a correction"):
        repair.prepare_correction(unresolved, {"path": "unused", "sha256": "0" * 64})
    request["rivals"][1]["predictions"] = {"H1": ["supported"]}
    with pytest.raises(ValueError, match="frozen discriminating"):
        repair.prepare_experiment(row, request)


def test_stale_source_and_forged_result_labels_refuse(tmp_path):
    fixed = correction(tmp_path)
    forged = deepcopy(fixed["evaluation"])
    forged["application"]["surviving_rivals"] = ["other"]
    with pytest.raises(ValueError, match="record changed"):
        repair.prepare_correction(forged, fixed["correction_pin"])
    (tmp_path / "candidate.json").write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        repair.request_rework(fixed, tmp_path / "unused-graph")


def test_adverse_measurement_preserves_frozen_hypothesis_revision_action(tmp_path):
    row, request, plan = experiment(tmp_path, candidate_value=3.)
    evaluation = repair.evaluate_experiment(repair.prepare_experiment(row, request), plan)
    assert evaluation["application"]["status"] == "contradicted"
    assert evaluation["application"]["surviving_rivals"] == ["other"]
    assert evaluation["application"]["next_action"]["action"] == "revise_hypothesis"
    assert evaluation["state"] == "needs_discriminating_evidence"
    with pytest.raises(ValueError, match="cannot select a correction"):
        repair.prepare_correction(evaluation, {"path": "unused", "sha256": "0" * 64})


def test_cumulative_rework_budget_is_preserved(tmp_path):
    fixed = correction(tmp_path)
    root = tmp_path / "graph"
    graph.create(root, graph_spec(fixed["correction"]["before"], reworks=0))
    with pytest.raises(graph.GraphError, match="rework budget exhausted"):
        repair.request_rework(fixed, root)
    assert graph.status(root)["reworks"] == 0


def test_unrelated_revision_and_unbound_corrected_source_refuse(tmp_path):
    fixed = correction(tmp_path)
    root = tmp_path / "graph"
    spec = graph_spec(fixed["correction"]["before"])
    graph.create(root, spec)
    revised = deepcopy(spec)
    revised["nodes"][0]["parameters"] = {"unrelated": True}
    with pytest.raises(ValueError, match="exactly the correction"):
        repair.request_rework(fixed, root, revised_spec=revised)
    revised = deepcopy(spec)
    revised["nodes"][1]["parameters"] = {"changed": True}
    with pytest.raises(ValueError, match="bind the corrected source"):
        repair.request_rework(fixed, root, revised_spec=revised)


@pytest.mark.parametrize("bad", [float("nan"), True, "1"])
def test_non_numeric_stage_evidence_refused(tmp_path, bad):
    ref = reference(tmp_path / "bad.json", {"observed": bad, "expected": 1., "absolute_tolerance": 0.})
    with pytest.raises(ValueError):
        repair.first_divergence([{"id": "stage", "comparison": ref}])


def completed_rerun(tmp_path, *, execute=True):
    fixed = correction(tmp_path)
    root = tmp_path / "graph"
    spec = graph_spec(fixed["correction"]["before"])
    graph.create(root, spec)
    host = FiniteHost()
    graph.execute(root, host)
    revised = deepcopy(spec)
    revised["nodes"][1]["inputs"] = [{"id": "source", **fixed["correction"]["after"]}]
    handoff = repair.request_rework(fixed, root, revised_spec=revised)
    expected = reference(tmp_path / "independent-reference.json", {
        "quantity": "upper_limit", "unit": "1", "expected": .125, "absolute_tolerance": 1e-12})
    host.final_value = .125
    if execute:
        graph.execute(root, host)
    return root, handoff, expected, host


def verify(root, handoff, expected):
    return repair.verify_rerun(handoff, root, final_node="inference", quantity_pointer="/requested", reference=expected)


def test_rerun_verifies_actual_completed_quantity_without_executing(tmp_path):
    root, handoff, expected, host = completed_rerun(tmp_path)
    calls = list(host.calls)
    before = graph.status(root)
    result = verify(root, handoff, expected)
    assert result["observed"] == result["expected"] == .125
    assert result["difference"] == 0. and result["comparison_passed"] is True
    assert result["affected_nodes"] == ["inference", "normalization", "selection", "templates"]
    assert result["rerun_completed"] is True
    assert result["source_consumption_verified"] is result["discrepancy_resolved"] is False
    assert result["execution_authorized"] is False
    assert host.calls == calls and graph.status(root) == before
    with pytest.raises(ValueError, match="corrected descendant"):
        repair.verify_rerun(handoff, root, final_node="independent", quantity_pointer="/requested", reference=expected)


def test_complete_rerun_keeps_adverse_final_comparison(tmp_path):
    root, handoff, expected, host = completed_rerun(tmp_path)
    adverse = reference(tmp_path / "adverse-reference.json", {
        "quantity": "upper_limit", "unit": "1", "expected": .2, "absolute_tolerance": .001})
    result = verify(root, handoff, adverse)
    assert result["rerun_completed"] is True and result["comparison_passed"] is False
    assert result["difference"] == pytest.approx(-.075)
    assert result["discrepancy_resolved"] is False


def test_pending_handoff_cannot_be_reported_as_rerun_completion(tmp_path):
    root, handoff, expected, host = completed_rerun(tmp_path, execute=False)
    with pytest.raises(ValueError, match="not complete"):
        verify(root, handoff, expected)
    assert host.calls.count("selection") == 1


def test_invalidation_without_corrected_source_binding_cannot_verify_repair(tmp_path):
    fixed = correction(tmp_path)
    root = tmp_path / "graph"
    graph.create(root, graph_spec(fixed["correction"]["before"]))
    host = FiniteHost()
    graph.execute(root, host)
    handoff = repair.request_rework(fixed, root)
    graph.execute(root, host)
    expected = reference(tmp_path / "independent-reference.json", {
        "quantity": "upper_limit", "unit": "1", "expected": .25, "absolute_tolerance": 1e-12})
    with pytest.raises(ValueError, match="did not declare the corrected source"):
        verify(root, handoff, expected)


@pytest.mark.parametrize("mutation", ["measurement", "reference"])
def test_rerun_stale_scientific_evidence_refuses(tmp_path, mutation):
    root, handoff, expected, host = completed_rerun(tmp_path)
    path = tmp_path / ("candidate.json" if mutation == "measurement" else "independent-reference.json")
    path.write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        verify(root, handoff, expected)


def test_old_receipt_cannot_substitute_for_corrected_final_output(tmp_path):
    root, handoff, expected, host = completed_rerun(tmp_path)
    path = root / graph.STATE
    state = json.loads(path.read_text())
    state["nodes"]["inference"]["result"] = handoff["baseline_graph"]["nodes"]["inference"]["result"]
    write(path, state)
    with pytest.raises(ValueError, match="fresh generation receipt|current node and generation"):
        verify(root, handoff, expected)


def test_final_output_cannot_substitute_for_separate_reference(tmp_path):
    root, handoff, expected, host = completed_rerun(tmp_path)
    current = graph.status(root)["nodes"]["inference"]["result"]
    substituted = {"artifact": pin(root / current["path"]), "pointer": "/result/requested"}
    with pytest.raises(ValueError, match="separately pinned"):
        verify(root, handoff, substituted)


def test_unrelated_rework_invalidates_original_rerun_handoff(tmp_path):
    root, handoff, expected, host = completed_rerun(tmp_path)
    graph.rework(root, ["independent"], reason="Fictional unrelated intervention")
    graph.execute(root, host)
    with pytest.raises(ValueError, match="revised or reworked"):
        verify(root, handoff, expected)


def test_untouched_generation_mutation_is_not_a_corrected_rerun(tmp_path):
    root, handoff, expected, host = completed_rerun(tmp_path)
    path = root / graph.STATE
    state = json.loads(path.read_text())
    state["nodes"]["independent"]["generation"] += 1
    write(path, state)
    with pytest.raises(ValueError, match="untouched node"):
        verify(root, handoff, expected)


@pytest.mark.parametrize("number", ["NaN", "Infinity", "1e999"])
def test_cutflow_report_nonfinite_json_is_rejected(tmp_path, number):
    path = tmp_path / "bad-report.json"
    path.write_text('{"rows": [], "unconsumed": ' + number + '}')
    with pytest.raises(ValueError, match="nonfinite|finite"):
        repair.cutflow_discrepancies(pin(path), graph_nodes={})


def rewrite_final_receipt(root, mutate):
    """Keep public digests coherent while challenging deeper receipt custody."""
    state_path = root / graph.STATE
    state = json.loads(state_path.read_text())
    current = state["nodes"]["inference"]["result"]
    receipt_path = root / current["path"]
    receipt = json.loads(receipt_path.read_text())
    mutate(receipt, state)
    write(receipt_path, receipt)
    current["sha256"] = graph.digest(receipt)
    current["binding_sha256"] = receipt["request"]["binding_sha256"]
    write(state_path, state)


@pytest.mark.parametrize("field,value", [
    ("packet", {"unretained": True}), ("graph_revision", -1),
    ("request_id", "0" * 64), ("binding_sha256", "0" * 64)])
def test_coherent_digest_cannot_hide_changed_dispatch_request(tmp_path, field, value):
    root, handoff, expected, host = completed_rerun(tmp_path)
    rewrite_final_receipt(root, lambda receipt, state: receipt["request"].update({field: value}))
    with pytest.raises(ValueError, match="current node and generation request"):
        verify(root, handoff, expected)


@pytest.mark.parametrize("mutation", ["duplicate", "omit", "call_metadata", "wrong_kind"])
def test_accounted_dispatch_population_and_metadata_are_checked(tmp_path, mutation):
    root, handoff, expected, host = completed_rerun(tmp_path)
    def mutate(receipt, state):
        calls = receipt["call_receipts"]
        if mutation == "duplicate":
            calls.append(deepcopy(calls[0]))
        elif mutation == "omit":
            # A duplicate state reservation is sufficient to challenge population
            # agreement; no label alone may certify its execution.
            extra = deepcopy(state["calls"][calls[0]["call_id"]])
            state["calls"]["f" * 64] = extra
        else:
            identity = calls[0]["call_id"]
            path = root / "calls" / (identity + ".json")
            measured = json.loads(path.read_text())
            measured["node_id" if mutation == "call_metadata" else "kind"] = "unrelated"
            write(path, measured)
            calls[0]["sha256"] = graph.digest(measured)
            state["calls"][identity]["receipt_sha256"] = calls[0]["sha256"]
            if mutation == "wrong_kind":
                state["calls"][identity]["kind"] = "unrelated"
    rewrite_final_receipt(root, mutate)
    with pytest.raises(ValueError, match="unique|population|dispatch receipt changed|executable host"):
        verify(root, handoff, expected)


def test_dispatch_bytes_are_rechecked_after_quantity_comparison(tmp_path, monkeypatch):
    root, handoff, expected, host = completed_rerun(tmp_path)
    state = graph.status(root)
    receipt = json.loads((root / state["nodes"]["inference"]["result"]["path"]).read_text())
    call_path = root / "calls" / (receipt["call_receipts"][0]["call_id"] + ".json")
    original = repair._observation
    def observe(ref, base_dir):
        value = original(ref, base_dir)
        if ref == expected:
            call_path.write_text("{}")
        return value
    monkeypatch.setattr(repair, "_observation", observe)
    with pytest.raises(ValueError, match="bytes changed"):
        verify(root, handoff, expected)


def test_correction_cannot_revise_a_node_without_its_original_source(tmp_path):
    fixed = correction(tmp_path)
    root = tmp_path / "graph"
    spec = graph_spec(fixed["correction"]["before"])
    spec["nodes"][1]["inputs"] = []
    graph.create(root, spec)
    revised = deepcopy(spec)
    revised["nodes"][1]["inputs"] = [{"id": "source", **fixed["correction"]["after"]}]
    before = graph.status(root)
    with pytest.raises(ValueError, match="bind the original source"):
        repair.request_rework(fixed, root, revised_spec=revised)
    assert graph.status(root) == before


@pytest.mark.parametrize("mutation", ["measurement", "correction", "predecessor"])
def test_repair_basis_is_rechecked_after_quantity_comparison(tmp_path, monkeypatch, mutation):
    root, handoff, expected, host = completed_rerun(tmp_path)
    paths = {
        "measurement": tmp_path / "candidate.json",
        "correction": tmp_path / "correction.json",
        "predecessor": root / "specs" / (handoff["baseline_graph"]["spec_sha256"] + ".json"),
    }
    original = repair._observation
    def observe(ref, base_dir):
        value = original(ref, base_dir)
        if ref == expected:
            paths[mutation].write_text("{}")
        return value
    monkeypatch.setattr(repair, "_observation", observe)
    with pytest.raises(ValueError, match="changed"):
        verify(root, handoff, expected)


def test_resealed_handoff_cannot_substitute_a_different_descendant_set(tmp_path):
    root, handoff, expected, host = completed_rerun(tmp_path)
    handoff["affected_nodes"] = ["inference"]
    handoff["sha256"] = graph.digest({key: value for key, value in handoff.items() if key != "sha256"})
    with pytest.raises(ValueError, match="correction descendants"):
        verify(root, handoff, expected)


def test_revision_uses_a_durable_state_fence(tmp_path, monkeypatch):
    fixed = correction(tmp_path)
    root = tmp_path / "graph"
    spec = graph_spec(fixed["correction"]["before"])
    graph.create(root, spec)
    revised = deepcopy(spec)
    revised["nodes"][1]["inputs"] = [{"id": "source", **fixed["correction"]["after"]}]
    original = graph.revise
    def concurrent_revision(*args, **kwargs):
        assert kwargs.get("expected_state_sha256")
        state_path = root / graph.STATE
        state = json.loads(state_path.read_text())
        state["history"].append({"sequence": len(state["history"]) + 1, "event": "concurrent_control"})
        write(state_path, state)
        return original(*args, **kwargs)
    monkeypatch.setattr(graph, "revise", concurrent_revision)
    with pytest.raises(graph.GraphError, match="superseded"):
        repair.request_rework(fixed, root, revised_spec=revised)
    assert graph.status(root)["reworks"] == 0
