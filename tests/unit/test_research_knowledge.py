"""Portable research consumer controls; synthetic sources/studies, no scientific run."""
from copy import deepcopy
import hashlib
import json

import pytest
from ravel.workflow import research_cycle as cycle, physics_knowledge as kernel, agent_host
from ravel.workflow.state_io import read_json
from test_research_cycle import contract, propose, experiment, write


def request(base, *, identity="v1", domain="toy", extra=False):
    source = write(base / (identity + "-source.txt"), "The toy fixed factor is a disputed premise.\nThe toy ordered factors need an explicit comparison.\n")
    def node(identity, line, obligation=None, hypothesis=False):
        return {"id": identity, "kind": "hypothesis" if hypothesis else "fact",
            "statement": "Explicit synthetic " + identity + " assertion; no physical evidence.",
            "tags": ["comparison"], "domain": [domain], "conventions": ["ordered-beams"],
            "applicability": "Synthetic two-beam component fixture only.", "equations": [],
            "evidence": [] if hypothesis else [{"source": "text", "line_start": line, "line_end": line,
                "excerpt_sha256": "0" * 64, "locator": "toy line"}],
            "obligations": [] if obligation is None else [{"id": obligation, "description": "Test the toy source disagreement.",
                "resource_class": "prospective_study", "check": None}]}
    a = node("fixed", 1, "compare-flux")
    b = node("ordered", 2)
    h = node("rival", 1, "explore-rival", hypothesis=True)
    hidden = node("other", 1); hidden["tags"] = ["unrelated"]; hidden["domain"] = ["other-domain"]
    lines = (base / (identity + "-source.txt")).read_bytes().splitlines(keepends=True)
    for n in (a, b, hidden):
        for e in n["evidence"]: e["excerpt_sha256"] = hashlib.sha256(lines[e["line_start"] - 1]).hexdigest()
    if extra: a["conventions"] = ["explicit-new-convention"]
    graph = {"schema_version": 1, "id": "toy-knowledge", "sources": [{"id": "text", "pin": source,
        "citation": "Own synthetic test text, not a primary physics source.", "version": identity, "format": "text", "parents": []}],
        "nodes": [a, b, h, hidden], "edges": [{"id": "conflict", "kind": "contradicts", "source": "fixed", "target": "ordered",
        "statement": "The two toy assertions require a discriminating study.", "assessment": "located_source_conflict"}]}
    g = write(base / (identity + "-knowledge.json"), graph)
    return write(base / (identity + "-request.json"), {"schema_version": 1, "knowledge": g,
        "query": {"text": "comparison", "tags": ["comparison"], "roots": ["fixed"], "domain": [domain], "max_nodes": 4}})


MAPPING = {"fixed": "flux-fixed", "ordered": "flux-ordered", "rival": "rival-premise"}


def setup(base):
    root = base / "cycle"
    cycle.create(root, contract(base), base_dir=base, evaluation_harness=True)
    propose(base, root)
    pin = request(base)
    state = cycle.bind_knowledge(root, pin, premise_map=MAPPING, reason="Retain toy conflicts and propose a comparison.")
    return root, pin, state


def designs(base, root):
    first = experiment(base, "a-ordinary", grouped=False, premise_ids=list(MAPPING.values()))
    first["predictions"]["grouped"] = "shared"
    second = experiment(base, "z-obligation", grouped=False, premise_ids=list(MAPPING.values()))
    cycle.design(root, first); cycle.design(root, second)
    return {"compare-flux": ["z-obligation"], "explore-rival": []}


def test_complete_kernel_packet_binds_real_controller_and_preserves_exploration(tmp_path):
    root, pin, state = setup(tmp_path)
    packet = kernel.retrieve(read_json(pin["path"]), tmp_path)
    bound = state["knowledge_bindings"][-1]
    assert bound["packet"] == packet and bound["source_assertions_only"]
    assert packet["selection"]["omitted"] == [{"id": "other", "reason": "not_task_selected"}]
    assert packet["contradictions"][0]["id"] == "conflict"
    assert next(x for x in state["premises"] if x["id"] == "rival-premise")["basis"] == []
    assert {x["stream"] for x in state["hypotheses"]} == {"citation_led", "speculative"}
    obligations = designs(tmp_path, root)
    assert cycle.select(root)["selected"] == "a-ordinary"
    result = cycle.knowledge_next(root, obligation_designs=obligations)
    assert result["selected"] == "z-obligation"
    assert result["missing_design_obligations"] == ["explore-rival"]
    assert len(result["open_obligations"]) == 2
    assert not result["execution_authorized"] and not result["physics_validated"] and not result["benefit_measured"]


@pytest.mark.parametrize("mapping", [{"fixed": "one"}, {"fixed": "one", "ordered": "one", "rival": "rival-premise"}])
def test_incomplete_or_collapsed_premise_mapping_refuses_atomically(tmp_path, mapping):
    root = tmp_path / "cycle"; before = cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True)
    with pytest.raises(ValueError): cycle.bind_knowledge(root, request(tmp_path), premise_map=mapping, reason="Explicit test.")
    assert cycle._load(root)[1] == before


def test_retrieval_source_drift_refuses_and_does_not_recapture(tmp_path):
    root, pin, state = setup(tmp_path)
    (tmp_path / "v1-source.txt").write_text("changed\n")
    with pytest.raises(ValueError): cycle.knowledge_next(root, obligation_designs={})
    assert read_json(root / "history" / f"{state['revision']:04d}.json") == state


def test_ending_source_drift_before_first_binding_refuses(tmp_path, monkeypatch):
    root = tmp_path / "cycle"; state = cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True)
    pin = request(tmp_path); original = kernel.retrieve
    def mutate(request, base):
        packet = original(request, base)
        (tmp_path / "v1-source.txt").write_text("changed after retrieval\n")
        return packet
    monkeypatch.setattr(kernel, "retrieve", mutate)
    with pytest.raises(ValueError): cycle.bind_knowledge(root, pin, premise_map=MAPPING, reason="Source drift test.")
    assert read_json(root / "history/0000.json") == state
    assert len(list((root / "history").glob("*.json"))) == 1


def test_domain_successor_reopens_child_without_erasing_original_history(tmp_path):
    root, _, old = setup(tmp_path)
    cycle.design(root, experiment(tmp_path, "parent", grouped=False, premise_ids=list(MAPPING.values())))
    cycle.design(root, experiment(tmp_path, "child", grouped=True, parent="parent"))
    before = cycle._load(root)[1]
    state = cycle.bind_knowledge(root, request(tmp_path, identity="v2", extra=True), premise_map=MAPPING,
        reason="An immutable context successor changes an explicit convention.")
    assert {e["id"] for e in state["experiments"] if "applicability_reopened" in e} == {"parent", "child"}
    assert read_json(root / "history" / f"{old['revision']:04d}.json") == old
    assert read_json(root / "history" / f"{before['revision']:04d}.json") == before
    assert len(state["hypotheses"]) == len(before["hypotheses"])
    assert not any(r["affordable"] for r in cycle.select(root)["designs"])


@pytest.mark.parametrize("mapping", [{}, {"compare-flux": ["unknown"], "explore-rival": []},
    {"compare-flux": ["z-obligation", "z-obligation"], "explore-rival": []}])
def test_missing_unknown_duplicate_obligation_design_refuses(tmp_path, mapping):
    root, _, _ = setup(tmp_path); designs(tmp_path, root)
    with pytest.raises(ValueError): cycle.knowledge_next(root, obligation_designs=mapping)


def test_unbound_knowledge_design_cannot_gain_selection_priority(tmp_path):
    root, _, _ = setup(tmp_path)
    cycle.design(root, experiment(tmp_path, "unbound", grouped=False))
    with pytest.raises(ValueError): cycle.knowledge_next(root, obligation_designs={"compare-flux": ["unbound"], "explore-rival": []})


def test_obligation_priority_cannot_exceed_resources(tmp_path):
    root, _, _ = setup(tmp_path); mapping = designs(tmp_path, root)
    _, state = cycle._load(root)
    state["experiments"][1]["cost"]["calls"] = state["contract"]["budget"]["calls"] + 1
    cycle._commit(root, state, "synthetic_unaffordable_design")
    result = cycle.knowledge_next(root, obligation_designs=mapping)
    assert result["selected"] == "a-ordinary"
    assert not result["designs"][1]["affordable"]


def test_negative_and_unknown_prediction_memory_is_scoped_and_custody_checked(tmp_path, monkeypatch):
    root, _, _ = setup(tmp_path); mapping = designs(tmp_path, root)
    _, state = cycle._load(root)
    e = state["experiments"][0]
    e["observation"] = {"outcome": "shared", "result_category": "defined_measurement",
        "prediction_comparison": {"independent": "differs", "grouped": "matches", "unknown": "unknown"}}
    e["adjudication"] = {"view": {"state": "accepted"}}
    cycle._commit(root, state, "explicit_mock_observed_roles")
    calls = []
    monkeypatch.setattr(cycle, "_current_evidence", lambda state, e, **kw: calls.append((e["id"], kw)))
    result = cycle.knowledge_next(root, obligation_designs=mapping)
    assert calls == [("a-ordinary", {"accepted": True})]
    evidence = result["retained_outcomes"][0]
    assert evidence["prediction_comparison"]["unknown"] == "unknown" and not evidence["global_hypothesis_refutation"]
    assert evidence["scientific_acceptance"] and len(result["open_obligations"]) == 2
    assert len(cycle._load(root)[1]["hypotheses"]) == 3
    def refuse(*args, **kwargs): raise ValueError("synthetic current review hold")
    monkeypatch.setattr(cycle, "_current_evidence", refuse)
    with pytest.raises(ValueError): cycle.knowledge_next(root, obligation_designs=mapping)


def test_ending_state_change_refuses_stale_recommendation(tmp_path, monkeypatch):
    root, _, _ = setup(tmp_path); mapping = designs(tmp_path, root)
    _, state = cycle._load(root)
    state["experiments"][0]["observation"] = {"outcome": None, "result_category": "execution_or_adapter_failure_unresolved",
        "prediction_comparison": {"independent": "unknown", "grouped": "unknown", "unknown": "unknown"}}
    cycle._commit(root, state, "explicit_mock_failed_stage")
    def mutate(state, e, **kwargs):
        cycle._commit(root, state, "synthetic_interleaved_revision")
    monkeypatch.setattr(cycle, "_current_evidence", mutate)
    with pytest.raises(ValueError, match="state changed"):
        cycle.knowledge_next(root, obligation_designs=mapping)


def test_duplicate_binding_and_authority_claim_refuse(tmp_path, monkeypatch):
    root, pin, state = setup(tmp_path)
    with pytest.raises(ValueError, match="already retained"):
        cycle.bind_knowledge(root, pin, premise_map=MAPPING, reason="No repeated binding.")
    original = kernel.retrieve
    def falsely_authorized(request, base):
        packet = original(request, base); packet["claims"]["execution_authorized"] = True
        return packet
    monkeypatch.setattr(kernel, "retrieve", falsely_authorized)
    with pytest.raises(ValueError, match="authority"):
        cycle.knowledge_next(root, obligation_designs={})


def test_required_check_reservation_blocks_even_contradiction_priority(tmp_path, monkeypatch):
    root, _, _ = setup(tmp_path); mapping = designs(tmp_path, root)
    monkeypatch.setattr(cycle, "_phase_allocation", lambda state: {"affordable_design_ids": ["a-ordinary"]})
    result = cycle.knowledge_next(root, obligation_designs=mapping)
    assert result["selected"] == "a-ordinary"
    assert "required checking reservation blocks construction" in result["designs"][1]["reasons"]


def test_manual_premise_revision_requires_explicit_knowledge_rebinding(tmp_path):
    root, pin, _ = setup(tmp_path); mapping = designs(tmp_path, root)
    revised = cycle.revise_premise(root, "flux-fixed", "An explicit revised toy assertion.", basis=[], reason="Source-free exploratory revision.")
    with pytest.raises(ValueError, match="manually revised"):
        cycle.knowledge_next(root, obligation_designs=mapping)
    state = cycle.bind_knowledge(root, pin, premise_map=MAPPING, reason="Explicitly restore the unchanged literal source assertion context.")
    assert read_json(root / "history" / f"{revised['revision']:04d}.json") == revised
    assert not any(row["affordable"] for row in cycle.knowledge_next(root, obligation_designs=mapping)["designs"])


def test_genuine_ordinary_graph_retrieval_binding_and_selection_one_debit(tmp_path):
    root = tmp_path / "cycle"; cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True); propose(tmp_path, root)
    pin = request(tmp_path)
    specification = read_json(pin["path"])
    dependencies = [pin, *kernel.input_pins(specification, tmp_path)]
    inputs = [{"id": "request" if i == 0 else "source-" + str(i), **{key: p[key] for key in ("path", "sha256")}}
        for i, p in enumerate(dependencies)]
    graph = {"schema_version": 1, "graph_id": "knowledge-graph", "budget": {"max_nodes": 1, "max_calls": 1,
        "max_output_tokens": 0, "max_wall_seconds": 30, "max_reworks": 0}, "nodes": [{"id": "retrieve", "kind": "tool",
        "role": "proposer", "depends_on": [], "inputs": inputs, "packet": None, "action": "physics-knowledge",
        "parameters": {"request_input": "request"}, "max_attempts": 1}]}
    host = agent_host.AgentHost()
    result = cycle.execute_graph(root, tmp_path / "graph", graph, host)
    assert result["complete"] and result["usage"]["calls"] == 1
    assert cycle._graph_result(tmp_path / "graph", "retrieve")["value"]["value"] == kernel.retrieve(specification, tmp_path)
    again = cycle.execute_graph(root, tmp_path / "graph", graph, host)
    assert again["usage"] == result["usage"]
    state = cycle.bind_knowledge(root, pin, premise_map=MAPPING, reason="Bind the exact ordinary kernel request after retained retrieval.")
    assert cycle._usage(state)["calls"] == 1
    result = cycle.knowledge_next(root, obligation_designs=designs(tmp_path, root))
    assert result["selected"] == "z-obligation" and result["ordinary_selection"]["usage_ceiling"]["calls"] == 1


def test_historical_prediction_under_changed_hypothesis_premise_is_not_current_negative(tmp_path, monkeypatch):
    root, _, _ = setup(tmp_path); mapping = designs(tmp_path, root)
    _, state = cycle._load(root)
    hypothesis = next(h for h in state["hypotheses"] if h["id"] == "independent")
    hypothesis["premise_bindings"] = cycle._bindings(state, ["pairing"])
    state["experiments"][0]["observation"] = {"outcome": "shared", "result_category": "defined_measurement",
        "prediction_comparison": {"independent": "differs", "grouped": "matches", "unknown": "unknown"}}
    cycle._commit(root, state, "explicit_mock_scoped_observation")
    cycle.revise_premise(root, "pairing", "A revised hypothesis-only premise.", basis=[], reason="Hypothesis applicability changes independently of the measured experiment.")
    monkeypatch.setattr(cycle, "_current_evidence", lambda *args, **kwargs: None)
    result = cycle.knowledge_next(root, obligation_designs=mapping)
    assert result["retained_outcomes"][0]["prediction_comparison"]["independent"] == "differs"
    assert result["constructive_followup"]["prediction_differences"] == []
