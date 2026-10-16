"""Synthetic independent-rule controls; no native execution or efficacy claim."""
from copy import deepcopy
import hashlib
import math

import pytest

from ravel import analysis_sources as sources
from ravel.physics import analysis_ir, routine_candidate as candidate
from ravel.physics import routine_counterexamples as boundary
from ravel.workflow.state_io import atomic_json


def event(identity="seed", pts=(30.0, 0.0, 25.0), weight=-2.0):
    return {"event_id": identity, "group_id": identity, "weights": {"nominal": weight},
            "objects": {"electron": [], "muon": [], "jet": [
                {"pt": pt, "eta": 0.5, "phi": 0.25, "mass": 0.0, "charge": 0, "idbits": 0}
                for pt in pts]}, "met": {"pt": 12.0, "phi": 0.4}}


def source_rules(row):
    # Reconstructed literally from the fixture's three source lines. This
    # evaluator does not call the candidate interpreter or inspect its nodes.
    n = sum(obj["pt"] >= 30.0 and abs(obj["eta"]) < 5.0 for obj in row["objects"]["jet"])
    return {"regions": ["selected"] if n >= 1 else [], "observables": {"n": n}}


def strict_fault(row):
    n = sum(obj["pt"] > 30.0 and abs(obj["eta"]) < 5.0 for obj in row["objects"]["jet"])
    return {"regions": ["selected"] if n >= 1 else [], "observables": {"n": n}}


def oracle(evaluator=source_rules, source="a" * 64):
    return boundary.IndependentOracle(evaluator, source, "Three separately reconstructed synthetic source rules", "fixture rule author")


def pin(path):
    return {"path": str(path), "sha256": sources.digest(path)}


def configured(tmp_path, *, threshold=math.nextafter(30.0, math.inf), repair=False):
    root = tmp_path / "original"; root.mkdir()
    source = root / "selection.txt"
    source.write_text("objects: supplied jets\nselect pt >= 30 and abs(eta) < 5\naccept count >= 1\n")
    capsule = {"schema_version": 1, "kind": "analysis-source-capsule", "framework": "cpp",
        "routine": "SyntheticSelection", "source": {"repository": "supplied", "revision": None,
        "description": "Synthetic independent-rule control"}, "root": str(root),
        "files": [{"path": source.name, "sha256": sources.digest(source), "role": "compile"}],
        "layout": {"include_dirs": [], "asset_dirs": []}, "dependencies": [],
        "dependency_review": {"complete": True, "description": "Synthetic text-only source"}, "submodules": []}
    cp = tmp_path / "capsule.json"; atomic_json(cp, capsule)
    claims = [{"id": "rule" + str(index), "path": source.name, "line_start": index,
        "line_end": index, "excerpt_sha256": hashlib.sha256(line).hexdigest(), "kind": kind}
        for index, (line, kind) in enumerate(zip(source.read_bytes().splitlines(keepends=True),
            ("objects", "expression", "selection")), 1)]
    contract = {"schema_version": 1, "level": "reconstructed", "source": "synthetic rules",
        "energy_unit": "GeV", "flags": {kind: {} for kind in boundary.KINDS},
        "response_evidence": [], "weight_names": ["nominal"]}
    events = [event("pass", (40,), 1.5), event("negative", (40,), -0.5),
              event("reject", (20,), 1.0), event("zero", (29,), 0.0)]
    program = {"schema_version": 1, "name": "synthetic_selection", "nodes": [
        {"id": "jets", "op": "input", "collection": "jet"},
        {"id": "threshold", "op": "const", "value": 30.0, "unit": "GeV"},
        {"id": "eta", "op": "const", "value": 5.0, "unit": "1"},
        {"id": "selected_jets", "op": "filter", "args": ["jets", "threshold", "eta"]},
        {"id": "n", "op": "count", "args": ["selected_jets"]},
        {"id": "one", "op": "const", "value": 1, "unit": "1"},
        {"id": "accept", "op": "compare", "args": ["n", "one"], "comparison": "ge"}],
        "regions": [{"name": "selected", "cuts": ["accept"]}],
        "limits": {"max_events": 8, "max_objects_per_event": 16, "max_pairs_per_event": 64}}
    baseline = tmp_path / "baseline"
    analysis_ir.write_bundle(analysis_ir.evaluate_program(program, contract, events), baseline)
    contract_path, events_path = tmp_path / "contract.json", tmp_path / "events.json"
    atomic_json(contract_path, contract); atomic_json(events_path, events)
    source_oracle = tmp_path / "oracle.json"
    atomic_json(source_oracle, {"schema_version": 1, "kind": "source-case-oracle",
        "source_capsule_sha256": sources.digest(cp), "events_sha256": sources.digest(events_path),
        "records": [{"event_id": row["event_id"], **source_rules(row)} for row in events],
        "author": "separate synthetic source rule author", "scope": "independent finite rules"})
    domain = tmp_path / "domain.json"
    atomic_json(domain, {"schema_version": 1, "kind": "supplied-reconstructed-domain",
        "jet_mass": "massless", "interpretation": "Synthetic massless object domain"})
    def recipe(value):
        p = deepcopy(program); p["nodes"][1]["value"] = value
        return {"schema_version": 1, "name": p["name"], "limits": p["limits"],
            "steps": [{"node": node, "claims": ["rule1", "rule2", "rule3"]} for node in p["nodes"]],
            "regions": [{"region": region, "claims": ["rule3"]} for region in p["regions"]]}
    candidates = [{"id": "draft", "parent": None, "recipe": recipe(threshold),
        "candidate_source_capsule": pin(cp), "build": None, "reason": "Synthetic threshold fault"}]
    board = []
    if repair:
        candidates.append({**deepcopy(candidates[0]), "id": "repaired", "parent": "draft", "recipe": recipe(30.0)})
        board.append({"from": "draft", "to": "repaired", "claims": ["rule2"], "trigger": "event_selection"})
    config = {"schema_version": 1, "kind": "routine-construction", "source_capsule": pin(cp),
        "source_scope": {"kind": "supplied_object_port", "unserved_obligations": ["Synthetic domain only"]},
        "model_construction": None, "population_review": None, "claims": claims,
        "contract": pin(contract_path), "events": pin(events_path), "event_domain": pin(domain),
        "reference": {"kind": "detached-analysis-witness", "bundle": str(baseline),
            "manifest_sha256": sources.digest(baseline / "manifest.json"), "source_capsule_sha256": sources.digest(cp),
            "claims": ["rule1", "rule2", "rule3"], "interpretation": "Reconstructed synthetic rules",
            "source_oracle": pin(source_oracle)}, "candidates": candidates, "repair_board": board}
    config_path = tmp_path / "construction.json"; atomic_json(config_path, config)
    return {"backend": "routine-candidate", "input": str(config_path), "candidate": "draft", "parent_feedback": None}, config


def one_case(row=None):
    return [{"category": "threshold", "detail": "equal", "event": row or event()}]


def test_boundary_population_is_complete_deterministic_and_preserves_input():
    seed = event(); before = deepcopy(seed)
    kwargs = {"thresholds": [{"collection": "jet", "field": "pt", "value": 30.0}],
        "overlap_radii": [0.4], "flow_edges": [{"collection": "met", "field": "pt", "value": 12.0}]}
    result = boundary.generate_boundary_events(seed, **kwargs)
    assert result == boundary.generate_boundary_events(seed, **kwargs)
    assert seed == before and result["complete_requested_population"]
    categories = {row["category"] for row in result["cases"]}
    assert categories == {"seed", "empty_collections", "threshold", "flow_bin", "multiplicity",
        "ordering_tie", "overlap_removal", "signed_weight", "visible_decay_configuration"}
    assert not result["truth_decay_coverage"] and not result["physics_validated"]
    thresholds = [row["event"]["objects"]["jet"][0]["pt"] for row in result["cases"] if row["category"] == "threshold"]
    assert thresholds == [math.nextafter(30.0, -math.inf), 30.0, math.nextafter(30.0, math.inf)]
    assert len({row["event"]["event_id"] for row in result["cases"]}) == len(result["cases"])
    assert {-1.0, 0.0, 1.0} <= {row["event"]["weights"]["nominal"] for row in result["cases"]}
    for row in result["cases"]:
        boundary.validate_event(row["event"])


def test_bounds_refuse_truncation_and_report_unsupported_neighbors():
    with pytest.raises(ValueError, match="truncation"):
        boundary.generate_boundary_events(event(), max_events=2)
    with pytest.raises(ValueError, match="multiplicity"):
        boundary.generate_boundary_events(event(), multiplicities=[17])
    result = boundary.generate_boundary_events(event(), thresholds=[{"collection": "jet", "field": "pt", "value": 0.0}], overlap_radii=[0.0])
    assert {row["category"] for row in result["refused_cases"]} == {"threshold", "overlap_removal"}
    assert any(row["detail"].get("position") == "equal" for row in result["cases"] if isinstance(row["detail"], dict))


def test_minimization_preserves_independent_disagreement_and_original_bytes():
    row = event(); before = deepcopy(row)
    result = boundary.minimize_disagreement(row, oracle(), strict_fault)
    minimized = result["minimized_event"]
    assert row == before and result["original_event"] == before
    assert len(minimized["objects"]["jet"]) == 1
    assert minimized["objects"]["jet"][0]["pt"] == 30.0
    assert minimized["weights"]["nominal"] == -1.0
    assert minimized["met"] == {"pt": 0, "phi": 0}
    assert set(result["preserved_disagreement_keys"]) == {"observable:n", "regions"}
    assert boundary.disagreement(source_rules(minimized), strict_fault(minimized))
    assert not result["globally_minimal"] and result["evaluations"] <= 64


def test_minimization_budget_and_errors_do_not_manufacture_disagreement():
    result = boundary.minimize_disagreement(event(), oracle(), strict_fault, max_evaluations=1)
    assert result["minimized_event"] == result["original_event"] and result["budget_exhausted"]
    def refuses_empty(row):
        if not row["objects"]["jet"]:
            raise ValueError("outside declared expert domain")
        return source_rules(row)
    result = boundary.minimize_disagreement(event(pts=(30,)), oracle(refuses_empty), strict_fault)
    assert result["domain_refusals"] and len(result["minimized_event"]["objects"]["jet"]) == 1
    with pytest.raises(ValueError, match="genuine"):
        boundary.minimize_disagreement(event(), oracle(), lambda row: source_rules(row))
    same = oracle()
    with pytest.raises(ValueError, match="cannot be the candidate"):
        boundary.minimize_disagreement(event(), same, same.evaluate)
    with pytest.raises(ValueError, match="replay"):
        oracle(analysis_ir.evaluate_program).validate()


def test_exact_numeric_and_boolean_faults_are_not_hidden_by_tolerance():
    def obs(value):
        return {"regions": [], "observables": {"x": value}}
    assert boundary.disagreement(obs(30.0), obs(math.nextafter(30.0, math.inf))) == ("observable:x",)
    assert boundary.disagreement(obs(True), obs(1)) == ("observable:x",)
    assert boundary.disagreement(obs(1.0), obs(1)) == ()
    assert boundary.disagreement(obs({"a": [{"b": True}]}), obs({"a": [{"b": 1}]})) == ("observable:x",)
    assert boundary.disagreement(obs([30.0]), obs([math.nextafter(30.0, math.inf)])) == ("observable:x",)
    assert boundary.disagreement(obs({"a": [1.0, None]}), obs({"a": [1, None]})) == ()
    assert boundary.disagreement(obs([None]), obs([])) == ("observable:x",)


@pytest.mark.parametrize("invalid", [object(), (1, 2), {1: "coerced key"},
    {"nested": [float("inf")]}, {"nested": [float("nan")]}],
    ids=["opaque", "tuple", "nonstring-key", "nested-infinity", "nested-nan"])
def test_unsupported_or_nonfinite_oracle_values_are_refused(invalid):
    with pytest.raises(ValueError):
        boundary.observation({"regions": [], "observables": {"x": invalid}})


def test_cyclic_oracle_values_and_nonstring_weight_names_are_refused():
    cyclic = []; cyclic.append(cyclic)
    with pytest.raises(ValueError, match="nesting"):
        boundary.observation({"regions": [], "observables": {"x": cyclic}})
    row = event(); row["weights"] = {1: -1.0}
    with pytest.raises(ValueError, match="string weight"):
        boundary.validate_event(row)
    with pytest.raises(ValueError, match="string weight"):
        boundary.generate_boundary_events(row)


@pytest.mark.parametrize("sign", [-1, 1])
def test_unrepresentable_integer_quantities_are_domain_refusals(sign):
    value = sign * 10 ** 400
    for target in ("weight", "object", "met"):
        row = event()
        if target == "weight":
            row["weights"]["nominal"] = value
        elif target == "object":
            row["objects"]["jet"][0]["eta"] = value
        else:
            row["met"]["phi"] = value
        with pytest.raises(ValueError, match="finite supplied boundary"):
            boundary.validate_event(row)
    for kwargs in (
        {"thresholds": [{"collection": "jet", "field": "pt", "value": value}]},
        {"flow_edges": [{"collection": "met", "field": "pt", "value": value}]},
        {"overlap_radii": [value]},
    ):
        with pytest.raises(ValueError, match="finite supplied boundary"):
            boundary.generate_boundary_events(event(), **kwargs)


def flow_rules(row):
    # Separately reconstructed rule: lower edge included, upper edge excluded;
    # underflow is index zero and the final exact edge enters overflow.
    value = row["met"]["pt"]
    index = 0 if value < 10.0 else 1 if value < 20.0 else 2
    weight = row["weights"]["nominal"]
    return {"regions": [], "observables": {"bin": index,
        "weighted_flow": [weight if cell == index else 0.0 for cell in range(3)]}}


def closed_upper_edge_fault(row):
    value = row["met"]["pt"]
    index = 0 if value <= 10.0 else 1 if value <= 20.0 else 2
    return {"regions": [], "observables": {"bin": index,
        "weighted_flow": [row["weights"]["nominal"] if cell == index else 0.0 for cell in range(3)]}}


@pytest.mark.parametrize("weight", [-2.0, 0.0, 1.0])
def test_independent_flow_assignment_oracle_catches_both_edge_equalities_with_signed_weights(weight):
    generated = boundary.generate_boundary_events(event(weight=weight), flow_edges=[
        {"collection": "met", "field": "pt", "value": 10.0},
        {"collection": "met", "field": "pt", "value": 20.0}])
    cases = [case for case in generated["cases"] if case["category"] == "flow_bin"]
    assert [flow_rules(case["event"])["observables"]["bin"] for case in cases] == [0, 1, 1, 1, 2, 2]
    for case in cases:
        expected = flow_rules(case["event"])
        assert sum(expected["observables"]["weighted_flow"]) == weight
        differences = boundary.disagreement(expected, closed_upper_edge_fault(case["event"]))
        assert bool(differences) == (case["detail"]["position"] == "equal")
    equality = cases[1]["event"]
    result = boundary.minimize_disagreement(equality, oracle(flow_rules), closed_upper_edge_fault)
    assert result["minimized_event"]["met"]["pt"] == 10.0
    assert result["minimized_event"]["weights"]["nominal"] == (-1.0 if weight < 0 else weight)
    assert result["expected"]["observables"]["bin"] == 1
    assert result["actual"]["observables"]["bin"] == 0


def test_minimization_cannot_drop_previously_agreeing_oracle_assertions():
    def complete_rules(row):
        result = source_rules(row)
        if len(row["objects"]["jet"]) != 1:
            result["observables"]["fixed"] = {"full": [True]}
        return result
    def faulty(row):
        result = strict_fault(row)
        result["observables"]["fixed"] = {"full": [True]}
        return result
    result = boundary.minimize_disagreement(event(), oracle(complete_rules), faulty)
    assert result["domain_refusals"] > 0
    assert set(result["expected"]["observables"]) == {"n", "fixed"}
    assert len(result["minimized_event"]["objects"]["jet"]) >= 2


def test_candidate_integration_finds_new_boundary_after_full_original_regression(tmp_path):
    task, config = configured(tmp_path)
    original_pin = deepcopy(config["events"])
    report = candidate.check_counterexamples(task, tmp_path, one_case(), oracle(source=config["source_capsule"]["sha256"]), observable_nodes=["n"])
    assert report["original_population_comparison"]["matched_events"] == 4
    assert report["original_population_event_ids"] == ["pass", "negative", "reject", "zero"]
    assert report["counts"] == {"passed": 0, "failed": 1, "refused": 0}
    assert report["diagnostic_status"] == "failed"
    assert not report["candidate_disposition_changed"] and not report["compute_authorized"]
    assert not report["oracle_provenance"]["independence_authenticated"]
    assert report["cases"][0]["minimization"]["minimized_event"]["objects"]["jet"][0]["pt"] == 30.0
    assert pin(original_pin["path"]) == original_pin


def test_repaired_candidate_keeps_every_original_case_and_parent_gate(tmp_path):
    task, config = configured(tmp_path, threshold=50.0, repair=True)
    out = tmp_path / "failed"
    failure = candidate.run(task, tmp_path, out)
    assert failure["candidate_disposition"] == "event_mismatch"
    revised = {**task, "candidate": "repaired", "parent_feedback": pin(out / "construction-feedback.json")}
    report = candidate.check_counterexamples(revised, tmp_path, one_case(), oracle(source=config["source_capsule"]["sha256"]), observable_nodes=["n"])
    assert report["original_population_comparison"]["events"] == report["original_population_comparison"]["matched_events"] == 4
    assert report["counts"]["passed"] == 1 and report["full_original_regression_required_after_repair"]
    assert report["cases"][0]["minimization"] is None
    revised["parent_feedback"] = None
    with pytest.raises(ValueError, match="exact retained parent"):
        candidate.check_counterexamples(revised, tmp_path, one_case(), oracle(source=config["source_capsule"]["sha256"]), observable_nodes=["n"])


def test_oracle_pin_refusal_and_domain_errors_cannot_pass(tmp_path):
    task, config = configured(tmp_path)
    with pytest.raises(ValueError, match="original source"):
        candidate.check_counterexamples(task, tmp_path, one_case(), oracle(), observable_nodes=["n"])
    row = event(); row["objects"]["jet"][0]["mass"] = 1.0
    report = candidate.check_counterexamples(task, tmp_path, one_case(row), oracle(source=config["source_capsule"]["sha256"]), observable_nodes=["n"])
    assert report["counts"] == {"passed": 0, "failed": 0, "refused": 1}
    assert report["diagnostic_status"] == "inconclusive" and report["cases"][0]["minimization"] is None


def test_supplementary_success_cannot_hide_original_regression_failure(tmp_path):
    task, config = configured(tmp_path, threshold=50.0)
    report = candidate.check_counterexamples(task, tmp_path, one_case(event(pts=(20,))),
        oracle(source=config["source_capsule"]["sha256"]), observable_nodes=["n"])
    assert report["counts"]["passed"] == 1 and report["diagnostic_status"] == "failed"
    assert report["original_population_comparison"]["matched_events"] == 2
    assert {row["event_id"] for row in report["original_population_comparison"]["witnesses"]} == {"pass", "negative"}


def test_requested_observable_interface_cannot_be_silently_omitted(tmp_path):
    task, config = configured(tmp_path, threshold=30.0)
    report = candidate.check_counterexamples(task, tmp_path, one_case(),
        oracle(source=config["source_capsule"]["sha256"]), observable_nodes=["n", "eta"])
    assert report["counts"] == {"passed": 0, "failed": 0, "refused": 1}
    assert "requested observable interface" in report["cases"][0]["error"]
    assert report["original_population_comparison"]["matched_events"] == 4
    def requires_missing(row):
        expected = source_rules(row)
        expected["observables"]["absent"] = 2
        return expected
    report = candidate.check_counterexamples(task, tmp_path, one_case(),
        oracle(requires_missing, source=config["source_capsule"]["sha256"]),
        observable_nodes=["n", "absent"], max_minimizations=0)
    assert report["counts"] == {"passed": 0, "failed": 1, "refused": 0}
    assert report["cases"][0]["disagreement_keys"] == ["observable:absent"]


def test_pairwise_edges_expose_intersection_fault_missed_by_single_factors():
    seed = event(pts=(40,))
    seed['met']['pt'] = 15.0
    kwargs = {'thresholds': [{'collection': 'jet', 'field': 'pt', 'value': 30.0}],
              'flow_edges': [{'collection': 'met', 'field': 'pt', 'value': 10.0}]}

    def rules(row):
        return {'regions': [], 'observables': {
            'intersection': row['objects']['jet'][0]['pt'] >= 30.0 and row['met']['pt'] >= 10.0}}

    def fault(row):
        value = rules(row)
        if row['objects']['jet'][0]['pt'] == 30.0 and row['met']['pt'] == 10.0:
            value['observables']['intersection'] = False
        return value

    single = boundary.generate_boundary_events(seed, **kwargs)
    assert not any(boundary.disagreement(rules(case['event']), fault(case['event']))
                   for case in single['cases'] if case['category'] in ('threshold', 'flow_bin'))
    paired = boundary.generate_boundary_events(seed, **kwargs, pairwise_edges=True)
    assert paired == boundary.generate_boundary_events(seed, **kwargs, pairwise_edges=True)
    pairs = [case for case in paired['cases'] if case['category'] == 'edge_pair']
    assert len(pairs) == 9
    assert {(case['detail'][0]['position'], case['detail'][1]['position']) for case in pairs} == {
        (left, right) for left in ('below', 'equal', 'above') for right in ('below', 'equal', 'above')}
    failures = [case for case in pairs if boundary.disagreement(rules(case['event']), fault(case['event']))]
    assert len(failures) == 1
    minimized = boundary.minimize_disagreement(failures[0]['event'], oracle(rules), fault)
    assert minimized['minimized_event']['objects']['jet'][0]['pt'] == 30.0
    assert minimized['minimized_event']['met']['pt'] == 10.0
    assert len(paired['cases']) == len(single['cases']) + 9
    with pytest.raises(ValueError, match='truncation'):
        boundary.generate_boundary_events(seed, **kwargs, pairwise_edges=True, max_events=len(paired['cases']) - 1)


def test_pairwise_edges_skip_conflicting_targets_and_report_domain_refusals():
    kwargs = {'thresholds': [{'collection': 'jet', 'field': 'pt', 'value': 0.0},
                             {'collection': 'jet', 'field': 'pt', 'value': 30.0}],
              'flow_edges': [{'collection': 'met', 'field': 'pt', 'value': 0.0}]}
    result = boundary.generate_boundary_events(event(), **kwargs, pairwise_edges=True)
    pairs = [case for case in result['cases'] if case['category'] == 'edge_pair']
    refused = [case for case in result['refused_cases'] if case['category'] == 'edge_pair']
    assert len(pairs) == 10 and len(refused) == 8
    assert all(case['detail'][0]['collection'] != case['detail'][1]['collection'] for case in pairs)
    for case in pairs:
        boundary.validate_event(case['event'])
    with pytest.raises(ValueError, match='boolean'):
        boundary.generate_boundary_events(event(), pairwise_edges=1)


@pytest.mark.parametrize('cross_kind', [False, True])
def test_chunk_minimization_preserves_fault_when_single_deletions_cannot(cross_kind):
    row = event(pts=(30, 40))
    if cross_kind:
        row['objects']['electron'] = [row['objects']['jet'].pop()]

    def rules(sample):
        n = sum(len(rows) for rows in sample['objects'].values())
        return {'regions': [], 'observables': {'parity': n % 2}}

    def fault(sample):
        result = rules(sample)
        n = sum(len(rows) for rows in sample['objects'].values())
        if n % 2 == 0:
            result['observables']['parity'] = 1
        return result

    result = boundary.minimize_disagreement(row, oracle(rules), fault)
    assert result['original_event'] == row
    assert sum(len(rows) for rows in result['minimized_event']['objects'].values()) == 0
    assert result['preserved_disagreement_keys'] == ['observable:parity']
    assert boundary.disagreement(result['expected'], result['actual']) == ('observable:parity',)
    assert not result['globally_minimal'] and result['evaluations'] <= 64


def test_refused_supplementary_case_cannot_mask_known_original_failure(tmp_path):
    task, config = configured(tmp_path, threshold=50.0)
    massive = event(); massive['objects']['jet'][0]['mass'] = 1.0
    report = candidate.check_counterexamples(task, tmp_path, one_case(massive),
        oracle(source=config['source_capsule']['sha256']), observable_nodes=['n'])
    assert report['counts'] == {'passed': 0, 'failed': 0, 'refused': 1}
    assert report['original_population_comparison']['matched_events'] == 2
    assert report['diagnostic_status'] == 'failed'


def test_flow_boundaries_preserve_signed_weight_and_expose_overflow_equality():
    from bisect import bisect_right

    edges = [10.0, 20.0, 30.0]
    seed = event(pts=(15.0,), weight=-2.0)
    population = boundary.generate_boundary_events(seed, flow_edges=[
        {'collection': 'jet', 'field': 'pt', 'value': value} for value in edges])
    cases = [case for case in population['cases'] if case['category'] == 'flow_bin']

    def source_histogram(row):
        # Independent source rules: left-closed bins and explicit flow cells.
        cells = [0.0, 0.0, 0.0, 0.0]
        for obj in row['objects']['jet']:
            x = obj['pt']
            index = 0 if x < 10.0 else 1 if x < 20.0 else 2 if x < 30.0 else 3
            cells[index] += row['weights']['nominal']
        return {'regions': [], 'observables': {'cells': cells}}

    def implementation(row):
        cells = [0.0] * 4
        for obj in row['objects']['jet']:
            index = bisect_right(edges, obj['pt'])
            if obj['pt'] == edges[-1]:
                index -= 1  # Inject only the final-edge equality fault.
            cells[index] += row['weights']['nominal']
        return {'regions': [], 'observables': {'cells': cells}}

    assert len(cases) == 9
    assert all(sum(source_histogram(case['event'])['observables']['cells']) == -2.0 for case in cases)
    failures = [case for case in cases if boundary.disagreement(
        source_histogram(case['event']), implementation(case['event']))]
    assert len(failures) == 1 and failures[0]['detail']['position'] == 'equal'
    assert failures[0]['detail']['value'] == 30.0
    result = boundary.minimize_disagreement(failures[0]['event'], oracle(source_histogram), implementation)
    assert result['minimized_event']['weights']['nominal'] == -1.0
    assert result['expected']['observables']['cells'] == [0.0, 0.0, 0.0, -1.0]
    assert result['actual']['observables']['cells'] == [0.0, 0.0, -1.0, 0.0]
