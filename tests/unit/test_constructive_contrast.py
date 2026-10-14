"""Portable synthetic constructive-contrast controls using public package APIs.

No target-source execution, native solver, model calls or corpus dependency.
The explicit original-weight limit is intentional and is not physics validation.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ravel.workflow import agent_graph, agent_host as host, constructive_contrast as cc
from ravel.workflow import diagnostic_plan as dp, execution


@pytest.fixture(autouse=True)
def prohibit_model_transport(monkeypatch):
    def refused(*args, **kwargs):
        raise AssertionError("Synthetic constructive tools must never use model transport")
    monkeypatch.setattr(host.AgentHost, "_responses", refused)
    monkeypatch.setattr(host.AgentHost, "_command", refused)


def pin(path):
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n")
    return pin(path)


def make_request(baseline, compound, license_path, before, after, contract=None, probes=None):
    return {"schema_version": 1, "finding": {"id": "component-objection", "claim": "One component explains the observed change.",
             "objection": "Other code changes accompany the named component; isolate that component before attributing an effect."},
            "baseline": pin(baseline), "compound_candidate": pin(compound), "license": pin(license_path),
            "component": {"id": "selection-boundary", "before": before, "after": after}, "control_probes": probes or [],
            "rivals": [{"id": "component-equivalent", "statement": "The isolated component leaves the selected quantity equivalent.", "predictions": {"H1": ["supported"]}},
                       {"id": "component-material", "statement": "The isolated component changes the selected quantity beyond the criterion.", "predictions": {"H1": ["contradicted"]}}],
            "next_actions": {"supported": {"action": "propose_challenger_review", "reason": "Present the informative controlled alternative for fresh full-case review."},
                             "contradicted": {"action": "revise_hypothesis", "reason": "Retain the adverse result and revise the component explanation."},
                             "unresolved": {"action": "request_evidence", "reason": "Request missing precision or evidence within the original envelope."}},
            "evaluation_contract": contract}


def collider_sources(tmp_path):
    base = tmp_path / "baseline.cpp"; other = tmp_path / "compound.cpp"; license_path = tmp_path / "LICENSE"
    original = "// Synthetic collider source control; never compiled or executed.\nconst int event_limit = 16;\nconst int threads = 1;\nconst double normalization = 1.;\nbool selected(double pt) { return pt >= 10.; }\n"
    compound = original.replace("event_limit = 16", "event_limit = 8").replace("threads = 1", "threads = 2").replace("normalization = 1.", "normalization = 2.").replace("pt >= 10.", "pt > 10.")
    base.write_text(original); other.write_text(compound); license_path.write_text("Original synthetic engineering fixture; no upstream solver code.\n")
    probes = [{"label": name, "baseline_literal": before, "compound_literal": after, "interpretation": reason} for name, before, after, reason in (
        ("exposure", "event_limit = 16", "event_limit = 8", "Supplied exposure-change interpretation; no causal effect measured."),
        ("workers", "threads = 1", "threads = 2", "Supplied runtime-change interpretation; no causal effect measured."),
        ("normalization", "normalization = 1.", "normalization = 2.", "Supplied normalization-change interpretation; no causal effect measured."))]
    return base, other, license_path, probes


def collider_plan(tmp_path, baseline_source, *, candidate_value=1., precision=.3, role="validation"):
    basis = {"quantity": "selected_weight", "unit": "1", "normalization": "sum_original_weight", "role": "nominal",
             "definition": "Synthetic supplied sixteen-event engineering control, not source execution", "channels": ["selected"]}
    datasets = {}
    census = {"schema_version": 1, "kind": "original_event_census", "records": [
        {"event_id": str(i), "group_id": str(i), "shard_id": "synthetic-original"} for i in range(16)]}
    census_pin = write(tmp_path / "original-census.json", census)
    for arm, value in (("baseline", 1.), ("candidate", candidate_value)):
        data = {"schema_version": 1, "kind": "events", "basis": basis, "population_id": "synthetic-fixed-16", "expected_exposure": 16,
                "uncertainty_scope": "Prescribed supplied-event engineering control", "scale": 1,
                "records": [{"event_id": str(i), "group_id": str(i), "weight": 1., "bins": [value]} for i in range(16)]}
        datasets[arm] = write(tmp_path / (arm + "-events.json"), data)
    return {"schema_version": 2, "source": "Synthetic supplied-event constructive contrast control", "question": "Does the controlled component keep selected yield equivalent?",
            "manipulation": {"variable": "boundary comparator", "baseline": "inclusive", "candidate": "exclusive"}, "fixed_artifacts": [pin(baseline_source), census_pin],
            "comparison": {"kind": "paired_events", **datasets, "basis": basis, "require_complete_exposure": True},
            "hypotheses": [{"id": "H1", "statement": "Yield remains within the explicit engineering margin.", "channels": ["selected"], "direction": "equivalent", "relative_tolerance": .1}],
            "precision": {"max_relative_mc_error": precision, "envelope_sigma": 1, "reference_covariance": "required"},
            "data_use": [{"population_id": "synthetic-fixed-16", "role": role, "artifact": datasets[arm]} for arm in ("baseline", "candidate")],
            "budget": {"max_attempts": 1, "max_seconds": 30, "max_new_events": 0},
            "stopping": {"success": "all_criteria_supported", "failure": "any_criterion_contradicted", "unresolved": "stop_without_conclusion"},
            "applicability": {"status": "established", "reason": "Explicit synthetic supplied-event control; no scientific applicability claim."}, "capacity": None}


def prepared_collider(tmp_path, **options):
    base, other, license_path, probes = collider_sources(tmp_path)
    p = collider_plan(tmp_path, base, **options)
    req = make_request(base, other, license_path, "return pt >= 10.;", "return pt > 10.;", cc.freeze_contract(p, original_census=p["fixed_artifacts"][1]), probes)
    return cc.prepare(req), p


def test_controlled_collider_preserves_exposure_runtime_normalization_and_license(tmp_path):
    prep, p = prepared_collider(tmp_path)
    originals = {key: Path(prep["request"][key]["path"]).read_bytes()
                 for key in ("baseline", "compound_candidate", "license")}
    expected = originals["baseline"].replace(b"return pt >= 10.;", b"return pt > 10.;", 1)
    assert prep["controlled_source"].encode() == expected
    assert "return pt > 10.;" in prep["controlled_source"]
    assert "event_limit = 16" in prep["controlled_source"]
    assert "threads = 1" in prep["controlled_source"] and "normalization = 1." in prep["controlled_source"]
    assert len(prep["control_observations"]) == 3
    assert all(x["verified_literal_observation"] for x in prep["control_observations"])
    out = tmp_path / "alternative"; original_license = (tmp_path / "LICENSE").read_bytes()
    result = cc.materialize(prep, out)
    assert result["executed"] is False
    assert (out / "LICENSE").read_bytes() == original_license
    assert hashlib.sha256((out / "controlled-source.txt").read_bytes()).hexdigest() == prep["controlled_source_sha256"]
    assert {key: Path(prep["request"][key]["path"]).read_bytes() for key in originals} == originals
    with pytest.raises(FileExistsError): cc.materialize(prep, out)


@pytest.mark.parametrize("mode", ["missing", "ambiguous", "unchanged"])
def test_bad_component_edit_refused(tmp_path, mode):
    base, other, license_path, _ = collider_sources(tmp_path)
    before, after = "return pt >= 10.;", "return pt > 10.;"
    if mode == "missing": before = "missing component"
    if mode == "ambiguous": base.write_text(base.read_text() + before)
    if mode == "unchanged": after = before
    with pytest.raises(ValueError, match="one distinct literal"): cc.prepare(make_request(base, other, license_path, before, after))


def test_source_text_is_never_imported_or_executed(tmp_path):
    base, other, license_path, _ = collider_sources(tmp_path)
    base.write_text("raise RuntimeError('TARGET MUST NEVER RUN')\n" + base.read_text())
    prep = cc.prepare(make_request(base, other, license_path, "return pt >= 10.;", "return pt > 10.;"))
    assert "TARGET MUST NEVER RUN" in prep["controlled_source"]
    assert prep["physics_validated"] is False and prep["execution_authorized"] is False


def test_supplied_result_is_recomputed_and_mapped_to_frozen_rivals(tmp_path):
    prep, p = prepared_collider(tmp_path)
    result = cc.apply_results(prep, p)
    assert result["diagnostic"] == dp.evaluate(p)
    assert result["status"] == "supported"
    assert result["surviving_rivals"] == ["component-equivalent"]
    assert result["next_action"]["action"] == "propose_challenger_review"
    assert result["execution_authorized"] is False and result["physics_validated"] is False


def test_adverse_complete_measurement_retained_as_a_scientific_result(tmp_path):
    prep, p = prepared_collider(tmp_path, candidate_value=2.)
    result = cc.apply_results(prep, p)
    assert result["status"] == "contradicted"
    assert result["surviving_rivals"] == ["component-material"]
    assert result["next_action"]["action"] == "revise_hypothesis"
    assert result["diagnostic"]["criterion_outcomes"][0]["channels"][0]["difference"] == 16.


@pytest.mark.parametrize("options", [{"precision": .01}, {"role": "calibration"}])
def test_unresolved_precision_or_calibration_retains_all_rivals(tmp_path, options):
    prep, p = prepared_collider(tmp_path, **options)
    result = cc.apply_results(prep, p)
    assert result["status"] == "unresolved"
    assert result["surviving_rivals"] == ["component-equivalent", "component-material"]
    assert result["next_action"]["action"] == "request_evidence"


@pytest.mark.parametrize("mutation", ["margin", "normalization", "budget", "population", "role"])
def test_post_result_scientific_choice_changes_refused(tmp_path, mutation):
    prep, p = prepared_collider(tmp_path)
    if mutation == "margin": p["hypotheses"][0]["relative_tolerance"] = .9
    if mutation == "normalization": p["comparison"]["basis"]["normalization"] = "different denominator"
    if mutation == "budget": p["budget"]["max_new_events"] = 100
    if mutation == "population":
        for use in p["data_use"]: use["population_id"] = "new-selected-population"
    if mutation == "role":
        for use in p["data_use"]: use["role"] = "calibration"
    with pytest.raises(ValueError, match="scientific contract"): cc.apply_results(prep, p)


@pytest.mark.parametrize("fault", ["missing", "group", "weight", "basis", "stale"])
def test_bad_pairing_and_source_evidence_cannot_resolve_scientific_objection(tmp_path, fault):
    prep, p = prepared_collider(tmp_path)
    path = Path(p["comparison"]["candidate"]["path"]); data = dp.read_json(path)
    if fault == "missing": data["records"].pop()
    if fault == "group": data["records"][0]["group_id"] = "different"
    if fault == "weight": data["records"][0]["weight"] = 2.
    if fault == "basis": data["basis"]["unit"] = "pb"
    if fault == "stale": path.write_text(path.read_text() + "\n")
    else:
        new_pin = write(path, data); p["comparison"]["candidate"] = new_pin; p["data_use"][1]["artifact"] = new_pin
    result = cc.apply_results(prep, p)
    assert result["diagnostic"]["status"] == "contradicted"
    assert result["diagnostic"]["integrity_checks"][-1]["criterion"] == "evidence_integrity"
    assert result["status"] == "unresolved" and result["next_action"]["action"] == "request_evidence"
    assert len(result["surviving_rivals"]) == 2


def test_measurement_pins_can_arrive_without_changing_prospective_criteria(tmp_path):
    prep, p = prepared_collider(tmp_path)
    data = dp.read_json(p["comparison"]["candidate"]["path"])
    for row in data["records"]: row["bins"] = [2.]
    new_pin = write(tmp_path / "new-measurement.json", data)
    p["comparison"]["candidate"] = new_pin; p["data_use"][1]["artifact"] = new_pin
    assert cc.freeze_contract(p, original_census=p["fixed_artifacts"][1]) == prep["request"]["evaluation_contract"]
    assert cc.apply_results(prep, p)["status"] == "contradicted"


def test_no_discriminating_prediction_is_not_a_new_winner(tmp_path):
    prep, p = prepared_collider(tmp_path)
    req = deepcopy(prep["request"])
    req["rivals"][1]["predictions"] = deepcopy(req["rivals"][0]["predictions"])
    identical = cc.prepare(req)
    result = cc.apply_results(identical, p)
    assert identical["discriminating_predictions"] is False
    assert len(result["surviving_rivals"]) == 2
    assert result["next_action"]["action"] == "revise_hypothesis"


def test_unpredicted_resolved_result_requires_new_explanation(tmp_path):
    prep, p = prepared_collider(tmp_path, candidate_value=2.)
    req = deepcopy(prep["request"])
    req["rivals"][1]["predictions"] = deepcopy(req["rivals"][0]["predictions"])
    result = cc.apply_results(cc.prepare(req), p)
    assert result["surviving_rivals"] == [] and result["next_action"]["action"] == "revise_hypothesis"


@pytest.mark.parametrize("fault", ["prediction_criterion", "unresolved_prediction", "automatic_launch", "unknown_as_winner"])
def test_rival_and_next_action_semantics_refuse_unsupported_claims(tmp_path, fault):
    prep, _ = prepared_collider(tmp_path); req = deepcopy(prep["request"])
    if fault == "prediction_criterion": req["rivals"][1]["predictions"] = {"not-a-criterion": ["supported"]}
    if fault == "unresolved_prediction": req["rivals"][1]["predictions"] = {"H1": ["unresolved"]}
    if fault == "automatic_launch": req["next_actions"]["supported"]["action"] = "launch"
    if fault == "unknown_as_winner": req["next_actions"]["unresolved"]["action"] = "propose_challenger_review"
    with pytest.raises(ValueError): cc.prepare(req)


@pytest.mark.parametrize("field", ["controlled_source", "rivals", "request"])
def test_tampered_preparation_cannot_be_applied(tmp_path, field):
    prep, p = prepared_collider(tmp_path)
    if field == "controlled_source": prep[field] += "\nchanged after preparation\n"
    if field == "rivals": prep[field][0]["statement"] = "changed after preparation"
    if field == "request": prep[field]["finding"]["objection"] = "changed after preparation"
    with pytest.raises(ValueError, match="preparation changed"): cc.apply_results(prep, p)


def test_changed_original_and_oversized_sources_refused(tmp_path):
    prep, p = prepared_collider(tmp_path)
    Path(prep["request"]["compound_candidate"]["path"]).write_text("late changed source")
    with pytest.raises(ValueError, match="source bytes changed"): cc.apply_results(prep, p)
    huge = tmp_path / "huge.cpp"; huge.write_bytes(b"x" * (cc.MAX_SOURCE_BYTES + 1))
    req = deepcopy(prep["request"]); req["baseline"] = pin(huge)
    with pytest.raises(ValueError, match="source exceeds byte bound"): cc.prepare(req)


@pytest.mark.parametrize("fault", ["both_shrink", "both_change_ids", "numeric_scale"])
def test_self_consistent_measurements_cannot_change_prospective_exposure_or_normalization(tmp_path, fault):
    prep, p = prepared_collider(tmp_path)
    for role in ("baseline", "candidate"):
        path = Path(p["comparison"][role]["path"]); data = dp.read_json(path)
        if fault == "both_shrink":
            data["expected_exposure"] = 8; data["records"] = data["records"][:8]
        if fault == "both_change_ids":
            for row in data["records"]: row["event_id"] = "replaced-" + row["event_id"]
        if fault == "numeric_scale" and role == "candidate": data["scale"] = 2
        new_pin = write(path, data); p["comparison"][role] = new_pin
        p["data_use"][0 if role == "baseline" else 1]["artifact"] = new_pin
    # Existing dataset self-consistency can be satisfied; the prospective
    # constructive contract separately retains its original census/scale.
    assert dp.evaluate(p)["integrity_checks"][-1]["status"] == "supported"
    result = cc.apply_results(prep, p)
    assert result["status"] == "unresolved" and result["application_evidence_errors"]
    assert result["next_action"]["action"] == "request_evidence" and len(result["surviving_rivals"]) == 2


def test_paired_contract_requires_actual_original_census_not_matching_seeds(tmp_path):
    _, p = prepared_collider(tmp_path)
    with pytest.raises(ValueError, match="actual original_event_census"): cc.freeze_contract(p)


def test_source_change_during_diagnostic_refuses_next_action(tmp_path, monkeypatch):
    prep, p = prepared_collider(tmp_path)
    original = cc.dp.evaluate
    def changing(plan, base_dir):
        result = original(plan, base_dir)
        Path(prep["request"]["compound_candidate"]["path"]).write_text("changed during diagnostic")
        return result
    monkeypatch.setattr(cc.dp, "evaluate", changing)
    with pytest.raises(ValueError, match="source bytes changed"): cc.apply_results(prep, p)


class Control:
    def __init__(self): self.calls = []
    def cancelled(self): return False
    def check_cancelled(self): pass
    def call(self, label, kind, request, function, output_tokens=0):
        self.calls.append(label)
        return function()


def host_node(action, parameters, paths):
    inputs = [{"id": identity, **pin(path)} for identity, path in paths.items()]
    n = {"id": "n1", "kind": "tool", "role": "proposer", "depends_on": [], "inputs": inputs, "packet": None,
         "action": action, "parameters": parameters, "max_attempts": 1}
    req = {"schema_version": 1, "graph_id": "engineering", "graph_revision": "a" * 64, "node_id": "n1", "generation": 1,
           "node_sha256": execution.digest(n), "request_id": "b" * 64, "input_artifacts": deepcopy(inputs), "packet": None, "dependencies": []}
    return n, req


def test_public_host_prepare_requires_actual_source_inputs_and_no_hidden_reads(tmp_path, monkeypatch):
    prep, _ = prepared_collider(tmp_path)
    reqpath = tmp_path / "request.json"; write(reqpath, prep["request"])
    n, req = host_node("constructive-prepare", {"request_input": "request"}, {"request": reqpath})
    control = Control()
    with pytest.raises(host.HostFailure, match="explicitly hash-bound"): host.AgentHost().execute(n, req, control)
    assert control.calls == []
    paths = {"request": reqpath}
    paths.update({f"source{i}": Path(p["path"]) for i, p in enumerate(cc.input_pins(prep["request"]))})
    n, req = host_node("constructive-prepare", {"request_input": "request"}, paths)
    result = host.AgentHost().execute(n, req, Control())
    assert result["value"] == prep and result["execution_authorized"] is False
    assert "ravel.workflow.constructive_contrast" in host.AgentHost().identity["sources"]
    assert "ravel.workflow.diagnostic_plan" in host.AgentHost().identity["sources"]
    assert "ravel.physics.event_contrasts" in host.AgentHost().identity["sources"]


def test_public_host_application_requires_all_measurements_then_reuses_diagnostic(tmp_path, monkeypatch):
    prep, p = prepared_collider(tmp_path)
    preppath = tmp_path / "preparation.json"; planpath = tmp_path / "plan.json"; write(preppath, prep); write(planpath, p)
    paths = {"preparation": preppath, "plan": planpath}
    paths.update({f"source{i}": Path(x["path"]) for i, x in enumerate(cc.input_pins(prep["request"]))})
    n, req = host_node("constructive-apply", {"preparation_input": "preparation", "plan_input": "plan"}, paths)
    with pytest.raises(host.HostFailure, match="explicitly hash-bound"): host.AgentHost().execute(n, req, Control())
    paths.update({f"measurement{i}": Path(x["path"]) for i, x in enumerate(cc.evaluation_pins(p))})
    n, req = host_node("constructive-apply", {"preparation_input": "preparation", "plan_input": "plan"}, paths)
    result = host.AgentHost().execute(n, req, Control())
    assert result["value"] == cc.apply_results(prep, p)
    assert result["value"]["next_action"]["action"] == "propose_challenger_review"


@pytest.mark.parametrize("dependency", ["dp", "event_contrasts"])
def test_actual_evaluator_and_census_source_changes_alter_host_identity(tmp_path, monkeypatch, dependency):
    before = host.AgentHost().identity
    module = getattr(cc, dependency)
    copy = tmp_path / (dependency + ".py")
    copy.write_bytes(Path(module.__file__).read_bytes() + b"\n# Private identity-change engineering control.\n")
    monkeypatch.setattr(module, "__file__", str(copy))
    after = host.AgentHost().identity
    assert after["sources"][module.__name__] != before["sources"][module.__name__]
    assert execution.digest(after) != execution.digest(before)


def replace_data(plan, role, data):
    new_pin = write(Path(plan["comparison"][role]["path"]), data)
    plan["comparison"][role] = new_pin
    plan["data_use"][0 if role == "baseline" else 1]["artifact"] = new_pin


def test_multiple_criteria_filter_outer_alternatives_separately(tmp_path):
    base, other, license_path, probes = collider_sources(tmp_path)
    plan = collider_plan(tmp_path, base)
    plan["comparison"]["basis"]["channels"].append("second")
    for role in ("baseline", "candidate"):
        data = dp.read_json(plan["comparison"][role]["path"])
        data["basis"] = deepcopy(plan["comparison"]["basis"])
        for record in data["records"]:
            record["bins"] = [1., 1. if role == "baseline" else 2.]
        replace_data(plan, role, data)
    plan["hypotheses"].append({"id": "H2", "statement": "Second channel increases by the supplied margin.",
                              "channels": ["second"], "direction": "increase", "relative_tolerance": .1})
    contract = cc.freeze_contract(plan, original_census=plan["fixed_artifacts"][1])
    request = make_request(base, other, license_path, "return pt >= 10.;", "return pt > 10.;", contract, probes)
    request["rivals"] = [
        {"id": "both-patterns", "statement": "Both declared patterns occur.", "predictions": {"H1": ["supported"], "H2": ["supported"]}},
        {"id": "first-fails", "statement": "First criterion fails.", "predictions": {"H1": ["contradicted"], "H2": ["supported"]}},
        {"id": "second-fails", "statement": "Second criterion fails.", "predictions": {"H1": ["supported"], "H2": ["contradicted"]}},
    ]
    result = cc.apply_results(cc.prepare(request), plan)
    assert result["observed_criteria"] == {"H1": "supported", "H2": "supported"}
    assert result["surviving_rivals"] == ["both-patterns"]
    assert result["diagnostic"] == dp.evaluate(plan)
    assert result["physics_validated"] is False


def test_equal_group_replacement_cannot_evade_original_census(tmp_path):
    prep, plan = prepared_collider(tmp_path)
    for role in ("baseline", "candidate"):
        data = dp.read_json(plan["comparison"][role]["path"])
        for row in data["records"]:
            row["group_id"] = "replacement-" + row["group_id"]
        replace_data(plan, role, data)
    assert dp.evaluate(plan)["status"] == "supported"
    result = cc.apply_results(prep, plan)
    assert result["status"] == "unresolved"
    assert any("IDs/groups" in error for error in result["application_evidence_errors"])
    assert len(result["surviving_rivals"]) == 2


def test_stale_original_census_refuses_application(tmp_path):
    prep, plan = prepared_collider(tmp_path)
    census = Path(prep["request"]["evaluation_contract"]["original_census"]["path"])
    census.write_text(census.read_text() + "\n")
    with pytest.raises(ValueError):
        cc.apply_results(prep, plan)


def test_blinded_role_cannot_use_source_construction(tmp_path, monkeypatch):
    prep, _ = prepared_collider(tmp_path)
    path = tmp_path / "request.json"
    write(path, prep["request"])
    paths = {"request": path}
    paths.update({f"source{i}": Path(pin["path"]) for i, pin in enumerate(cc.input_pins(prep["request"]))})
    node, request = host_node("constructive-prepare", {"request_input": "request"}, paths)
    node["role"] = next(iter(host.BLIND_ROLES))
    request["node_sha256"] = execution.digest(node)
    control = Control()
    with pytest.raises(host.HostFailure, match="blinded"):
        host.AgentHost().execute(node, request, control)
    assert control.calls == []


def test_pairing_does_not_claim_original_weight_or_source_consumption(tmp_path):
    """Located limit, not a source-weight proof: census contains no weights."""
    prep, plan = prepared_collider(tmp_path)
    for role in ("baseline", "candidate"):
        data = dp.read_json(plan["comparison"][role]["path"])
        for row in data["records"]:
            row["weight"] = 2.
        replace_data(plan, role, data)
    result = cc.apply_results(prep, plan)
    assert result["status"] == "supported"
    assert result["physics_validated"] is False and result["execution_authorized"] is False
    assert any("not causal proof" in item for item in result["limitations"])
    assert any("source consumption" in item for item in prep["limitations"])


def test_absent_contract_never_fabricates_threshold_or_causal_resolution(tmp_path):
    base, other, license_path, _ = collider_sources(tmp_path)
    prep = cc.prepare(make_request(base, other, license_path, "return pt >= 10.;", "return pt > 10.;"))
    result = cc.apply_results(prep)
    assert prep["evaluation_contract_sha256"] is None
    assert result["diagnostic"] is None and result["status"] == "unresolved"
    assert result["next_action"]["action"] == "request_evidence"
    assert len(result["surviving_rivals"]) == 2


@pytest.mark.parametrize("dependency", ["dp", "event_contrasts"])
def test_actual_graph_records_tool_and_reuse_rejects_changed_evaluator(tmp_path, monkeypatch, dependency):
    prep, _ = prepared_collider(tmp_path)
    path = tmp_path / "request.json"
    write(path, prep["request"])
    paths = {"request": path}
    paths.update({f"source{i}": Path(pin["path"]) for i, pin in enumerate(cc.input_pins(prep["request"]))})
    node, _ = host_node("constructive-prepare", {"request_input": "request"}, paths)
    spec = {"schema_version": 1, "graph_id": "constructive-review-control",
            "budget": {"max_nodes": 1, "max_calls": 1, "max_output_tokens": 0,
                       "max_wall_seconds": 30, "max_reworks": 0}, "nodes": [node]}
    directory = tmp_path / "graph"
    agent_graph.create(directory, spec)
    adapter = host.AgentHost()
    first = agent_graph.execute(directory, adapter, workers=1)
    assert first["complete"] and first["usage"]["calls"] == 1
    saved = dp.read_json(directory / first["nodes"]["n1"]["result"]["path"])
    assert saved["result"]["action"] == "constructive-prepare"
    assert saved["result"]["value"] == prep
    assert agent_graph.execute(directory, adapter, workers=1)["usage"]["calls"] == 1
    module = getattr(cc, dependency)
    source = tmp_path / (dependency + "-identity-only.py")
    source.write_bytes(Path(module.__file__).read_bytes() + b"\n# Independent source identity control.\n")
    monkeypatch.setattr(module, "__file__", str(source))
    retained = agent_graph.status(directory)
    with pytest.raises(agent_graph.GraphError, match="^completed generation source/request/host differs; explicit rework required$"):
        agent_graph.execute(directory, adapter, workers=1)
    # The refusal precedes any reservation: no call is charged and the completed generation is untouched.
    assert agent_graph.status(directory) == retained and retained["usage"]["calls"] == 1
