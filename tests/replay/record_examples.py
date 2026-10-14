"""Hand-built records that satisfy the reading and plan contract, for self-tests and mutations."""
import copy

from intake_records import prompt_sha256

PROMPT = ("Generate 10,000 Drell-Yan e+e- events at 13 TeV using MadGraph and Pythia and plot the "
          "dielectron invariant mass from 60 to 120 GeV. Do not run a detector simulation.")
SHA_A = "a" * 64
SHA_B = "b" * 64


def span(prompt, text, nth=0):
    start = -1
    for _ in range(nth + 1):
        start = prompt.index(text, start + 1)
    return {"start": start, "end": start + len(text), "text": text}


def author(actor="deterministic-reader"):
    return {"actor": actor, "host": None, "model": None, "invocation_id": None, "fresh_context": None,
            "record": None}


def reading(prompt=PROMPT):
    s = lambda text: span(prompt, text)  # noqa: E731
    return {
        "schema_version": 1, "kind": "request-reading", "prompt_sha256": prompt_sha256(prompt),
        "reader": {"module": "ravel.workflow.request_reading", "source_sha256": SHA_A},
        "authors": [author()],
        "witness": [
            {"id": "W1", "type": "count", "value": {"value": 10000}, "span": s("10,000")},
            {"id": "W2", "type": "energy", "value": {"value": 13000, "unit": "GeV"}, "span": s("13 TeV")},
            {"id": "W3", "type": "window", "value": {"low": 60, "high": 120, "unit": "GeV"}, "span": s("60 to 120 GeV")},
        ],
        "facts": [
            {"id": "F1", "type": "event_count", "value": {"value": 10000}, "evidence": [s("10,000")],
             "authority": "user_quoted", "witness": "W1", "physics_critical": True},
            {"id": "F2", "type": "collision_energy", "value": {"value": 13000, "unit": "GeV"}, "evidence": [s("13 TeV")],
             "authority": "user_quoted", "witness": "W2", "physics_critical": True},
            {"id": "F3", "type": "plot_window", "value": {"low": 60, "high": 120, "unit": "GeV"},
             "evidence": [s("60 to 120 GeV")], "authority": "user_quoted", "witness": "W3", "physics_critical": False},
        ],
        "constraints": [
            {"id": "K1", "type": "requested_tool", "value": {"tool": "MadGraph"}, "evidence": [s("MadGraph")]},
            {"id": "K2", "type": "requested_tool", "value": {"tool": "Pythia"}, "evidence": [s("Pythia")]},
            {"id": "K3", "type": "negated_stage", "value": {"stage": "detector"},
             "evidence": [s("Do not run a detector simulation")]},
        ],
        "deliverables": [
            {"id": "D1", "obligation_ids": ["O1"], "artifact": {"kind": "figure", "require": {}}, "claim_kind": "prediction"},
        ],
        "ambiguities": [],
        "boundaries": [],
        "dismissed": [],
    }


def plan(prompt=PROMPT):
    node = {
        "id": "N1", "kind": "operation", "operation": "model-events", "implementation": "science-mode",
        "status": "available", "held_by": None, "covers": ["original-request", "O1"], "fields": [
            {"pointer": "/task/events", "value": 10000, "authority": "user_quoted", "evidence": "F1"}],
        "rung": "full",
        "budget": {"basis": "ceiling", "max_seconds": 3600, "events": 10000, "disk_bytes": None, "native_attempts": 1},
        "placement": {"backend_plan": None}, "fan_out": None, "spec_template": None,
        "review": {"claim_scope": "parton and shower-level dielectron mass", "actions": ["delivery"]},
        "authored": None, "request": None,
    }
    figure = copy.deepcopy(node)
    figure.update(id="N2", operation="figure", covers=["O1"], rung="none",
                  budget={"basis": "ceiling", "max_seconds": 60, "events": None, "disk_bytes": None,
                          "native_attempts": None}, fields=[])
    return {
        "schema_version": 1, "kind": "request-plan", "prompt_sha256": prompt_sha256(prompt),
        "reading": {"path": "inputs/reading.json", "sha256": SHA_B},
        "signatures": {"path": "src/ravel/data/operation_signatures.json", "entries": {"model-events": SHA_A}},
        "status": "draft", "authors": [author("local-proposer")],
        "inputs": [],
        "nodes": [node, figure],
        "edges": [{"id": "E1", "from": {"ref": "N1", "slot": "events"}, "to": {"ref": "N2", "slot": "events"},
                   "kind": "event_sample", "require": {"level": "particle"}, "resolution": "compatible",
                   "converter": None, "acceptance": "execution_ledger"}],
        "claims": [{
            "id": "C1", "kind": "prediction", "statement": "the dielectron invariant-mass distribution between 60 and 120 GeV",
            "obligation_ids": ["O1"], "deliverable": {"artifact": "figure", "template": None}, "level": "not_applicable",
            "statistic": {"source": "not_applicable", "definition": None, "evidence": [], "secondary": []},
            "comparison": {"target": "none", "locator": None, "metric": None, "tolerance": None},
            "conventions": {"basis_conversion": False}, "basis_declared": ["generated_prediction"], "inherits": []}],
        "waypoints": [{"id": "WP1", "kind": "smoke_review", "after": "N1", "before": ["N2"],
                       "criterion": "the smoke sample has the requested process and energy", "check": None,
                       "on_false": "stop"}],
        "boundaries": [],
        "coverage": [{"obligation_id": "original-request", "by": ["N1", "C1"]}, {"obligation_id": "O1", "by": ["N1", "N2", "C1"]}],
        "aggregate_budget": {"wall_seconds": 3660, "native_attempts": 1, "events": 10000, "disk_bytes": None,
                             "calls": None, "output_tokens": None},
        "label": {"task_mode": "generate", "rule": "D2", "floor_row": "generate"},
    }
