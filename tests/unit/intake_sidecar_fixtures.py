"""Builders for pinned request readings and request plans (architecture §2.5.1, §2.5.2)."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from ravel.workflow.task_completion import initial_requirements

PROMPT = ("Compute the expected 95% CLs exclusion for a 300 GeV smuon with a 100 GeV bino "
          "using the published slepton search at 13 TeV and compare it with the published Figure 3.")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def span(prompt, text):
    start = prompt.index(text)
    return {"start": start, "end": start + len(text), "text": text}


def author(actor="deterministic-reader"):
    return {"actor": actor, "host": None, "model": None, "invocation_id": None, "fresh_context": None,
            "record": None}


def reading(prompt=PROMPT, **overrides):
    doc = {
        "schema_version": 1, "kind": "request-reading",
        "prompt_sha256": sha(prompt.encode()),
        "reader": {"module": "ravel.workflow.request_reading", "source_sha256": "0" * 64},
        "authors": [author()],
        "witness": [], "facts": [],
        "constraints": [],
        "deliverables": [],
        "ambiguities": [],
        "boundaries": [],
        "dismissed": [],
    }
    if "300 GeV" in prompt:
        doc["witness"] = [{"id": "W1", "type": "mass", "value": {"gev": 300}, "span": span(prompt, "300 GeV")}]
        doc["facts"] = [{"id": "F1", "type": "mass", "value": {"gev": 300}, "evidence": [span(prompt, "300 GeV")],
                         "authority": "user_quoted", "witness": "W1", "physics_critical": True}]
    doc.update(deepcopy(overrides))
    return doc


def node(node_id="N1", **overrides):
    row = {"id": node_id, "kind": "operation", "operation": "figure-comparison",
           "implementation": "science-mode", "status": "available", "held_by": None,
           "covers": ["original-request"], "fields": [], "rung": "full",
           "budget": {"basis": "ceiling", "max_seconds": 600, "events": None, "disk_bytes": None,
                      "native_attempts": 1},
           "placement": {"backend_plan": None}, "fan_out": None, "spec_template": None,
           "review": {"claim_scope": "fig3", "actions": ["delivery"]}, "authored": None, "request": None}
    row.update(deepcopy(overrides))
    return row


def claim(claim_id="C1", **overrides):
    row = {"id": claim_id, "kind": "exclusion",
           "statement": "the expected 95% CLs exclusion status of the stated smuon-bino point",
           "obligation_ids": ["original-request"],
           "deliverable": {"artifact": "inference", "template": None}, "level": "expected",
           "statistic": {"source": "policy_default", "definition": "95% CLs", "evidence": [], "secondary": []},
           "comparison": {"target": "published_figure", "locator": "Figure 3", "metric": None, "tolerance": None},
           "conventions": {"basis_conversion": False},
           "basis_declared": ["generated_prediction", "simulated_acceptance"], "inherits": []}
    row.update(deepcopy(overrides))
    return row


def plan(reading_pin, prompt=PROMPT, **overrides):
    doc = {
        "schema_version": 1, "kind": "request-plan", "prompt_sha256": sha(prompt.encode()),
        "reading": reading_pin,
        "signatures": {"path": "src/ravel/data/operation_signatures.json", "entries": {}},
        "status": "proposed", "authors": [author("host-agent")], "inputs": [],
        "nodes": [node()], "edges": [], "claims": [claim()], "waypoints": [], "boundaries": [],
        "coverage": [{"obligation_id": "original-request", "by": ["N1", "C1"]}],
        "aggregate_budget": {"wall_seconds": 600, "native_attempts": 1, "events": None, "disk_bytes": None,
                             "calls": None, "output_tokens": None},
        "label": {"task_mode": "research", "rule": "D5", "floor_row": "research"},
    }
    doc.update(deepcopy(overrides))
    return doc


def write_json(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(raw)
    return {"path": str(path.relative_to(path.parent.parent)) if path.parent.name == "inputs" else path.name,
            "sha256": sha(raw)}


def contract(prompt=PROMPT, **overrides):
    doc = {"schema_version": 1, "prompt": prompt, "task_mode": "research", "detector_mode": "none",
           "stat_mode": "TBD-judgment", "required_user_inputs": [], "assumptions": [], "compute_plan": "none",
           "approval_required": True, "task_requirements": initial_requirements(prompt)}
    doc.update(deepcopy(overrides))
    return doc


def pinned_run(rundir, *, prompt=PROMPT, reading_overrides=None, plan_overrides=None, contract_overrides=None):
    """Write reading, plan and a contract that pins both; return (contract, reading, plan).

    The release intake is the only writer of pinned readings and plans and stamps epoch two.
    """
    rundir = Path(rundir)
    reading_doc = reading(prompt, **(reading_overrides or {}))
    reading_pin = write_json(rundir / "inputs/reading.json", reading_doc)
    plan_doc = plan(reading_pin, prompt, **(plan_overrides or {}))
    plan_pin = write_json(rundir / "inputs/plan.json", plan_doc)
    contract_doc = contract(prompt, reading=reading_pin, request_plan=plan_pin,
                            **{"agent_layer_epoch": 2, **(contract_overrides or {})})
    write_json(rundir / "inputs/task_contract.json", contract_doc)
    return contract_doc, reading_doc, plan_doc


def checkin1(plan_doc, reading_doc, **extra_sections):
    """A CHECK-IN 1 whose plan sections equal the pinned plan."""
    claims = []
    flags = [{"id": "F1", "text": "the published selection is used as recorded"}]
    for row in plan_doc["claims"]:
        entry = {"id": row["id"], "kind": row["kind"], "statement": row["statement"], "fidelity": "of record"}
        if plan_doc["label"]["rule"] != "D3" and set(row["basis_declared"]) & {
                "simulated_acceptance", "published_statistical_model", "reimplemented_statistical_model"}:
            entry.update(fidelity="not certified on this route",
                         explanation=("This limit is computed in a separate child study, so the acceptance "
                                      "certificate that a published-analysis run checks is not applied to it."),
                         certifiable_route=("Run the published analysis in place through its preserved routine "
                                            "so the acceptance certificate gates the limit."))
            flags.append({"id": f"F{len(flags) + 1}",
                          "text": f"{row['id']}: not certified on this route; see the claims table"})
        claims.append(entry)
    for row in reading_doc["ambiguities"]:
        if row["status"] == "open":
            flags.append({"id": f"F{len(flags) + 1}", "text": f"{row['id']}: {row['issue']}"})
    sections = {
        "i": "request and scope", "iv": "plan and budget", "v": flags, "vi": ["answer", "ask", "propose"],
        "plan": [{"id": n["id"], "operation": n["operation"]} for n in plan_doc["nodes"]],
        "claims": claims,
        "coverage": deepcopy(plan_doc["coverage"]),
        "ambiguities": [{"id": a["id"], "status": a["status"], "issue": a["issue"]} for a in reading_doc["ambiguities"]],
    }
    if plan_doc["boundaries"]:
        sections["boundaries"] = [{"id": b} for b in plan_doc["boundaries"]]
    authored = [n for n in plan_doc["nodes"] if n["kind"] == "authored"]
    if authored:
        sections["authored"] = [{"id": n["id"], "purpose": (n["authored"] or {}).get("purpose", "")} for n in authored]
    sections.update(extra_sections)
    return {"schema_version": 1, "kind": "checkin1", "variant": "survey",
            "sections": {**sections, "census_table": [{"source": "published search"}], "coverage_gaps": []}}
