"""Ordinary CHECK-IN 2 role dispatch and controlled return to scientific work.

This composes AgentGraph, immutable role packets, public decision-case audits and
physics_review. Their existing journal is the sole decision/correction authority.
There is no separate judgment state, automatic approval, native run or retry.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

from . import agent_graph, decision_case, execution, physics_review as review, review_context
from .state_io import atomic_json, read_json

ROLE = {"critic": "physics_critic", "verifier": "skeptical_verifier", "synthesizer": "physics_decider"}
# transport_attested_cli: a launched agent CLI whose host-written session receipt verifies.
OBSERVATIONS = {"remote_transport_observed", "local_transport_observed", "transport_attested_cli"}
LIMITATION = "Declared actors and observed transport do not authenticate identities or prove independent scientific truth."


def _keys(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError(label + " has an invalid closed schema")


def _path(value):
    return review_context._safe_path(value)


def _pin(path):
    path = _path(path)
    if not path.is_file() or not path.stat().st_size:
        raise ValueError("nonempty regular judgment artifact required")
    return {"path": str(path), "sha256": execution.file_hash(path)}


def _read_pin(pin):
    """Authenticate the actual consumed buffer, including transient ABA writes."""
    from .validation_io import identity
    _keys(pin, {"path", "sha256"}, "judgment pin")
    path = _path(pin["path"])
    before = identity(path.stat())
    if not path.is_file() or before[3] <= 0 or before[3] > 16 * 1024**2:
        raise ValueError("bounded nonempty judgment JSON artifact required")
    with path.open("rb") as stream:
        if identity(os.fstat(stream.fileno())) != before:
            raise ValueError("judgment input changed before opening")
        raw = stream.read(before[3] + 1)
        if identity(os.fstat(stream.fileno())) != before:
            raise ValueError("judgment input changed during read")
    if (_path(pin["path"]) != path or identity(path.stat()) != before
            or len(raw) != before[3] or hashlib.sha256(raw).hexdigest() != pin["sha256"]):
        raise ValueError("scientific judgment consumed input changed")
    return review_context._strict_json_bytes(raw)


def _new(path, value):
    path = _path(path)
    with path.open("x", encoding="utf8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
    return _pin(path)


def _live(root, *, retained_study=False, _proof=None):
    root = review._root(root)
    if retained_study:
        from .retained_science_review import pending
        observed = pending(root)
        reg, events = observed["review"]["registration"], observed["review"]["events"]
        if _proof is not None: _proof.update(observed)
    else:
        reg, events = review._read(root)
        review._base_live(root, reg)
        review._judgments_live(root, review._view(reg, events))
    view = review._view(reg, events)
    if view["cycle"] is None:
        raise ValueError("open the actual successful CHECK-IN 2 cycle first")
    return root, reg, events, view


def next_step(root):
    """Derive work from the existing journal, without creating another state."""
    if not review.registered(root):
        from .review_points import _facts, pending
        from . import science
        if not (Path(root) / science.PLAN).exists() and _facts(Path(root)).get('agent_layer_epoch') == 2:
            return {'phase': 'review_points', 'role': None, 'review_points': pending(Path(root)),
                    'next': 'ravel review pending --rundir <run> --json', 'execution_authorized': False}
        packet = science.packet(root)
        phase = "failed_diagnostic" if packet.get("execution", {}).get("status") == "failed" else "open_cycle"
        return {"phase": phase, "role": None, "ordinary_packet": packet,
                "next": "judgment failed-feedback" if phase == "failed_diagnostic" else "judgment open --checks <located-checks>",
                "execution_authorized": False}
    _, _, _, view = _live(root)
    existing = {r["role"] for r in view["reviews"]}
    state = view["state"]
    if state == "awaiting_review":
        role = next((r for r in ("critic", "verifier", "synthesizer") if ROLE[r] not in existing), None)
        phase = "result_review"
    elif state in {"send_back", "correction_failed"}:
        role, phase = ("improver", "repair_proposal") if view["redos_remaining"] > 0 else (None, "new_experiment_required")
    elif state == "correction_admitted":
        role, phase = None, "return_to_work"
    elif state == "accepted":
        role, phase = None, "final_results_reviewed" if "final_results" in view["cycle"] else "scoped_delivery"
    else:
        role, phase = None, state
    return {"phase": phase, "role": role, "review": review.status(root),
            "next": "Execute only the already admitted ordinary correction; reopen a fresh successful cycle before closure"
                if phase == "return_to_work" else "Prepare the named fresh role" if role else "Follow the ordinary scoped gate",
            "execution_authorized": False, "actor_identity_authenticated": False}


def open_cycle(root, *, check_results, stage_receipts=None, effective_settings=None, correction_id=None, retained_study=False):
    """Ordinary science entry, using actual retained execution and supplied checks."""
    from . import science
    from .review_points import _facts
    if type(retained_study) is not bool:raise ValueError('retained_study must be explicit')
    if not (Path(root) / science.PLAN).exists() and _facts(Path(root)).get('agent_layer_epoch') == 2:
        if retained_study:
            raise ValueError('retained study opening requires its ordinary science plan')
        if not stage_receipts:
            raise ValueError('generic review opening requires actual retained stage receipts')
        return review.open_cycle(root, effective_settings=effective_settings, stage_receipts=stage_receipts,
                                 check_results=check_results, correction_id=correction_id)
    root = science.root(root)
    if retained_study:
        if correction_id is not None:raise ValueError('retained opening is first-cycle only')
        return review.open_cycle(root,effective_settings=effective_settings,stage_receipts=stage_receipts,
            check_results=check_results,retained_study=True)
    science.verify_plan(root, approved=True)
    if stage_receipts is None:
        record = execution.load_execution(root)["stages"].get("science", {})
        if record.get("status") != "succeeded":
            raise ValueError("FAILED work uses canonical diagnostic intake, never a successful review")
        stage_receipts = [record["attempt_record"]]
    return review.open_cycle(root, effective_settings=effective_settings or science.review_effective_settings(root),
        stage_receipts=stage_receipts, check_results=check_results, correction_id=correction_id)


def open_final_cycle(root, *, manifest, check_results):
    """Review actual final claims/population before presenting research results."""
    root,reg,events,view=_live(root)
    if view['state']!='accepted':raise ValueError('CI3 requires accepted current CI2 results')
    from . import scientific_autonomy
    _,document=scientific_autonomy.observed_run_document(root)
    if 'autonomy' in document:scientific_autonomy.authorize(root,'accept_recommendation')
    return review.open_cycle(root,effective_settings=[p['path'] for p in view['cycle']['effective_settings']],
        stage_receipts=[r['path'] for r in view['cycle']['receipts']],check_results=check_results,
        checkpoint=True,final_results=manifest)


def _unreviewed(case):
    """Withhold every copied interpretation while retaining scientific content."""
    case = deepcopy(decision_case.validate_case(case))
    for node in case["nodes"]:
        node.pop("review")
        for assumption in node["assumptions"]:
            assumption.pop("disposition"); assumption.pop("reason")
    for edge in case["edges"]:
        edge.pop("review")
    return case


def _audit(case, audit, actor, base_dir):
    """Fresh exact-case coverage, not inherited supported labels."""
    _keys(audit, {"case_sha256", "nodes", "edges"}, "fresh public audit")
    if audit["case_sha256"] != execution.digest(case):
        raise ValueError("public audit belongs to a changed claim or support edge")
    if type(audit["nodes"]) is not list or type(audit["edges"]) is not list:
        raise ValueError("finite public audit lists required")
    updated = deepcopy(case)
    node_reviews = {}
    for row in audit["nodes"]:
        _keys(row, {"id", "decision", "reason", "assumptions"}, "fresh node review")
        if row["id"] in node_reviews: raise ValueError("duplicate reviewed node")
        node_reviews[row["id"]] = row
    edge_reviews = {}
    for row in audit["edges"]:
        _keys(row, {"parent", "child", "decision", "reason"}, "fresh support-edge review")
        key = (row["parent"], row["child"])
        if key in edge_reviews: raise ValueError("duplicate reviewed edge")
        edge_reviews[key] = row
    if set(node_reviews) != {n["id"] for n in case["nodes"]} or set(edge_reviews) != {(e["parent"], e["child"]) for e in case["edges"]}:
        raise ValueError("fresh audit must cover every node and edge of the exact finite action case")
    for node in updated["nodes"]:
        row = node_reviews[node["id"]]
        node["review"] = {"reviewer_id": actor, "decision": row["decision"], "reason": row["reason"]}
        if type(row["assumptions"]) is not list or len(row["assumptions"]) != len(node["assumptions"]):
            raise ValueError("fresh audit omits material assumptions")
        for assumption, judgment in zip(node["assumptions"], row["assumptions"]):
            _keys(judgment, {"disposition", "reason"}, "fresh assumption review")
            assumption.update(judgment)
    for edge in updated["edges"]:
        row = edge_reviews[(edge["parent"], edge["child"])]
        edge["review"] = {"reviewer_id": actor, "decision": row["decision"], "reason": row["reason"]}
        if row["decision"] == "unresolved" and edge["request"] is None:
            edge["request"] = {"kind": "experiment", "description": "Resolve the claimed support from " + edge["child"] + " to " + edge["parent"]}
    return decision_case.evaluate_case(updated, base_dir)


def _add(packet, manifest, identity, value, source_pin=None):
    raw = (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()
    if len(raw) > 2_000_000: raise ValueError("bounded judgment packet artifact required")
    relative = "artifacts/" + identity + ".json"
    with (packet / relative).open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    sha = hashlib.sha256(raw).hexdigest()
    manifest["artifacts"].append({"id": identity, "path": relative, "sha256": sha,
        "source_path": source_pin["path"] if source_pin else str(packet / relative),
        "source_sha256": source_pin["sha256"] if source_pin else sha,
        "projection": "fresh public action/audit context; copied judgments withheld"})
    return sha


def _scalar(type_, **values): return {"type": type_, **values}
def _object(properties): return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}
def _array(item, maximum=256): return {"type": "array", "items": item, "maxItems": maximum}
S = _scalar("string", maxLength=65536)
N = _scalar(["string", "null"])

def output_schema(*, context_followup=False):
    """Finite public scientific assertions and decisions, never reasoning traces."""
    evidence = _object({"path": S, "location": S})
    finding = _object({"id": S, "summary": S, "evidence": {**_array(evidence), "minItems":1}, "check_ids": {**_array(S), "minItems":1}, "required_paths": _array(S), "required_stages": {**_array(S), "minItems":1}})
    decision = _scalar("string", enum=list(decision_case.STATUSES))
    disposition = _scalar("string", enum=["accepted", "unresolved", "rejected"])
    audit = _object({"case_sha256": S, "nodes": _array(_object({"id": S, "decision": decision, "reason": S,
        "assumptions": _array(_object({"disposition": disposition, "reason": S}))})),
        "edges": _array(_object({"parent": S, "child": S, "decision": decision, "reason": S}), 4096)})
    audit["type"] = ["object", "null"]
    proposal = _object({"changed_paths": _array(S), "stages": _array(S), "recheck_checks": _array(S),
        "replacements": _array(_object({"path": S, "text": S})),
        "tests": _array(_object({"finding_id": S, "observable": S, "intervention": S,
            "held_conditions": S, "method": S,
            "reference": {**_object({"artifact_id": S, "location": S, "expected_json": S, "grounding_reason": S}), "type": ["object", "null"]},
            "alternatives": _array(_object({"hypothesis": S, "prediction": S}), 16)})),
        "max_seconds": _scalar(["integer", "null"])})
    proposal["type"] = ["object", "null"]
    schema = _object({"schema_version": _scalar("integer"), "kind": S, "subject_sha256": S,
        "verdict": N, "summary": S, "findings": _array(finding), "closes": _array(S), "claim_scope": N,
        "audit": audit, "proposal": proposal, "proposal_verdict": N})
    if context_followup:
        selection = _object({'kind':_scalar('string',enum=['artifact','index']),
            'artifact_id':N,'section':N,'offset':_scalar('integer',minimum=0),
            'max_bytes':_scalar('integer',minimum=1,maximum=65536),'query':N})
        artifact_selection=deepcopy(selection); artifact_selection['properties'].update(
            kind=_scalar('string',enum=['artifact']),artifact_id=S,section=_scalar('null'),query=_scalar('null'))
        index_selection=deepcopy(selection); index_selection['properties'].update(
            kind=_scalar('string',enum=['index']),artifact_id=_scalar('null'),
            section=_scalar('string',enum=['artifacts','omissions']),query=_scalar('string',maxLength=256),
            max_bytes=_scalar('integer',minimum=1024,maximum=65536))
        selection['anyOf']=[artifact_selection,index_selection]
        schema["properties"]["schema_version"] = _scalar("integer",enum=[2])
        schema["properties"]["context_request"] = {**_object({"selections":_array(selection,32)}),"type":["object","null"]}
        schema["properties"]["citations"] = _array(_object({"artifact_id":S,"sha256":S,"location":S}),256)
        schema["required"] += ["context_request","citations"]
    accept, nonaccept, nonvoting = (deepcopy(schema) for _ in range(3))
    accept["properties"].update(kind=_scalar("string", enum=["scientific_review"]),
        verdict=_scalar("string", enum=["accept"]), claim_scope=_scalar("string", minLength=1))
    nonaccept["properties"].update(kind=_scalar("string", enum=["scientific_review"]),
        verdict=_scalar("string", enum=["send_back", "stop"]), claim_scope=_scalar("null"), closes=_array(S, 0))
    nonvoting["properties"].update(kind=_scalar("string", enum=["scientific_repair_proposal", "scientific_evidence_request", "scientific_repair_design_review"]),
        verdict=_scalar("null"), claim_scope=_scalar("null"), closes=_array(S, 0))
    if context_followup:
        nonvoting["properties"]["kind"]["enum"].append("scientific_context_request")
    schema["anyOf"] = [accept, nonaccept, nonvoting]
    return schema


def _default_case(root, reg, view, packet, manifest, request_pin, contract):
    """Ordinary action audit grounded in this scope and presented raw evidence.

    It starts unresolved. Fresh reviewer judgments, not producer check labels,
    decide whether the evidence supports the action. Extra contested slices can
    use the existing explicit decision-case schema instead.
    """
    author = reg["policy"]["actors"]["proposer"]
    placeholder = {"reviewer_id": "pending:" + contract["actor_id"], "decision": "unresolved", "reason": "Fresh exact-case review required"}
    root_node = {"id": "action", "author_id": author,
        "assertion": "Support the requested " + contract["phase"] + " action within scope " + str(contract["claim_scope"]),
        "rationale": "Only the current raw evidence and prospectively allowed scope can support this action", "material": True,
        "assumptions": [], "unknowns": [], "anchors": [{"kind": "user_requirement", "artifact": request_pin,
            "format": "json", "location": "/claim_scope", "value": contract["claim_scope"]}], "review": deepcopy(placeholder)}
    for artifact in manifest["artifacts"]:
        try: doc = read_json(packet / artifact["path"])
        except (ValueError, UnicodeError): continue
        if isinstance(doc, dict) and isinstance(doc.get("specification"), dict):
            for statement in doc["specification"].get("assumptions", []):
                root_node["assumptions"].append({"statement": statement, "disposition": "unresolved", "reason": "Fresh scope/applicability review required"})
    nodes, edges = [root_node], []
    checks = reg["policy"]["claim_scopes"].get(contract["claim_scope"], {}).get("checks", [])
    for index, check_id in enumerate(checks):
        check = next(c for c in view["cycle"]["checks"] if c["id"] == check_id)
        anchors = []
        for ref in check["evidence"]:
            source = review._identity(root, review._path(root, ref["path"]))
            for artifact in manifest["artifacts"]:
                if artifact["source_path"] != source: continue
                path = packet / artifact["path"]
                try: value = path.read_text(encoding="utf8")
                except UnicodeError: continue
                try: data = read_json(path); format_ = "json"
                except ValueError:
                    if value != value.strip(): continue
                    data, format_ = value, "text"
                anchors.append({"kind": "measurement", "artifact": _pin(path), "format": format_, "location": "", "value": data})
        node_id = f"check{index}"
        nodes.append({"id": node_id, "author_id": author, "assertion": "Executed evidence supports declared check " + check_id,
            "rationale": "Review the actual located measurements, units, conventions and applicability; a producer status is insufficient",
            "material": True, "assumptions": [], "unknowns": [] if anchors else [{"question": "No bounded raw witness for " + check_id,
                "request": {"kind": "evidence", "description": "Obtain an indexed raw witness for " + check_id}}], "anchors": anchors, "review": deepcopy(placeholder)})
        edges.append({"parent": "action", "child": node_id, "author_id": author,
            "rationale": "The prospectively requested scope requires this check", "review": deepcopy(placeholder),
            "request": {"kind": "experiment", "description": "Recheck " + check_id + " in a bounded source-bound intervention if current evidence is insufficient"}})
    return decision_case.validate_case({"schema_version": 1, "action": root_node["assertion"], "root": "action",
        "triggers": [{"kind": "high_consequence", "reason": "A scientific result claim or repair action changes what may be delivered"}],
        "budget": {"max_nodes": len(nodes), "max_depth": 1 if edges else 0}, "nodes": nodes, "edges": edges})



def _campaign(root, campaign, experiment):
    """Use the existing current campaign and its actual observed run association."""
    from . import research_cycle
    if (campaign is None) != (experiment is None):
        raise ValueError("campaign and observed experiment must be supplied together")
    if campaign is None: return None
    campaign = _path(campaign)
    _, state = research_cycle._load(campaign)
    matches = [e for e in state["experiments"] if e["id"] == experiment]
    if (len(matches) != 1 or matches[0]["rundir"] is None or matches[0]["observation"] is None
            or _path(matches[0]["rundir"]) != _path(root)):
        raise ValueError("campaign judgment must bind this exact observed experiment run")
    return {"root": str(campaign), "experiment": experiment}


def _campaign_graph(root, campaign, experiment, graph_root):
    """A connected review consumes only a graph charged by the existing ledger."""
    from . import research_cycle
    association = _campaign(root, campaign, experiment)
    if association is None: return
    _, state = research_cycle._load(association["root"])
    spec, _ = agent_graph._load(_path(graph_root))
    expected = {"calls": spec["budget"]["max_calls"], "output_tokens": spec["budget"]["max_output_tokens"],
                "wall_seconds": spec["budget"]["max_wall_seconds"], "native_attempts": 0}
    rows = [row for row in state["resource_ledger"] if row["id"] == "graph:" + str(_path(graph_root))]
    observed = [row for row in state["graphs"] if row["root"] == str(_path(graph_root))]
    research_cycle.validate_graph_reservation(state, graph_root, spec)
    current = agent_graph.status(graph_root)
    if "goal_binding" in state["contract"] and spec.get("goal_binding") != state["contract"]["goal_binding"]:
        raise ValueError("campaign review Graph must retain the original parent assignment")
    if (len(rows) != 1 or rows[0]["ceiling"] != expected
            or len(observed) != 1 or not observed[0]["complete"] or observed[0]["usage"] != current["usage"]
            or observed[0]["revision"] != current["spec_sha256"]):
        raise ValueError("campaign role requires its retained exact resource reservation and observed Graph usage")



def _inherit_goal(spec, association):
    if association is not None:
        from . import research_cycle
        _, state = research_cycle._load(association["root"])
        if "goal_binding" in state["contract"]:
            spec["goal_binding"] = deepcopy(state["contract"]["goal_binding"])
    return spec


def prepare_role(root, out, *, role, actor_id, model, reasoning_effort, max_output_tokens,
                 max_wall_seconds, claim_scope=None, case_pin=None, proposal_binding=None, action="model", allow_control=False,
                 campaign=None, experiment=None, retained_study=False, context_index_limits=None,
                 evidence_pages=None, max_context_reworks=0, case_dependencies=None):
    """Prepare an executable existing Graph; no model/compute is dispatched here."""
    if type(retained_study) is not bool:
        raise ValueError("retained_study must be an explicit boolean")
    if retained_study and (proposal_binding is not None or role == "improver" or campaign is not None):
        raise ValueError("retained study continuation is result-review only")
    proof = {}
    root, reg, events, view = _live(root, retained_study=retained_study, _proof=proof)
    if role not in review_context.ROLES: raise ValueError("unknown scientific role")
    review._text(actor_id, "declared role actor")
    repair = proposal_binding is not None
    if role in ROLE and actor_id != reg["policy"]["actors"][ROLE[role]]:
        raise ValueError("wrong registered role actor")
    if role == "improver" and actor_id in set(reg["policy"]["actors"].values()):
        raise ValueError("nonvoting improver must be distinct from every declared actor")
    if role == "improver" or repair:
        if view["state"] not in {"send_back", "correction_failed"} or view["redos_remaining"] <= 0:
            raise ValueError("bounded repair needs unresolved findings and an unspent redo")
    elif view["state"] not in {"awaiting_review", "send_back"}:
        raise ValueError("current result cannot receive another role")
    if not repair and role in ROLE and any(r["role"] == ROLE[role] for r in view["reviews"]):
        raise ValueError("role already decided this cycle")
    if role == "synthesizer" and not repair and not {"physics_critic", "skeptical_verifier"} <= {r["role"] for r in view["reviews"]}:
        raise ValueError("synthesis needs both actual independent decisions")
    if claim_scope is not None and claim_scope not in reg["policy"]["claim_scopes"]:
        raise ValueError("claim scope is not prospectively allowed")
    from . import scientific_context_followup as followup
    enabled_context = evidence_pages is not None or max_context_reworks != 0
    context_budget = followup.policy(max_context_reworks, evidence_pages) if enabled_context else None
    association = _campaign(root, campaign, experiment)
    out = _path(out)
    out.mkdir(parents=True, exist_ok=False)
    packet = out / "context"
    manifest = review_context.create(root, role, packet, index_limits=context_index_limits)
    case = _read_pin(case_pin) if case_pin is not None else None
    if case is not None: case = decision_case.validate_case(case)
    proposal = verify_binding(proposal_binding, allow_control=allow_control) if repair else None
    if repair and proposal["contract"]["rundir"] != str(root): raise ValueError("repair belongs to another run")
    if repair and proposal["receipt"]["role"] not in {"improver", "verifier"}: raise ValueError("invalid repair predecessor")
    if repair and role == "synthesizer" and (proposal["receipt"]["role"] != "verifier" or proposal["value"]["proposal_verdict"] != "adequate_for_bounded_test"):
        raise ValueError("decider needs a fresh adequate proposal skeptic, not an executed closure")
    prepared = []
    if repair:
        p = proposal["proposal"]
        prepared = [_pin(root / path) for path in p["changed_paths"]]
        replacements = {row["path"]: row["text"] for row in p["replacements"]}
        for pin in prepared:
            path = str(Path(pin["path"]).relative_to(root))
            if Path(pin["path"]).read_text() != replacements[path]: raise ValueError("prepared repair differs from the actual improvement proposal")
    source_pins = [_pin(Path(module.__file__)) for module in (execution, review, review_context, agent_graph, decision_case)] + [_pin(__file__)]
    if case_dependencies is not None:
        if case_pin is None or type(case_dependencies) is not list or len(case_dependencies) > 4096:
            raise ValueError("finite dependencies require an explicit located review case")
        for pin in case_dependencies:
            _keys(pin, {"path", "sha256"}, "case evidence dependency")
            path = decision_case.bound_file(pin, Path(case_pin["path"]).parent)
            actual = _pin(path)
            if actual not in source_pins: source_pins.append(actual)
    from . import scientific_autonomy
    required_visual=[]
    if "final_results" in view["cycle"]:
        from . import final_results_review as final
        required_visual=final.visual_sources(root,view['cycle']['final_results'])
        source_pins += [_pin(Path(__file__).with_name("final_results_review.py"))]
        if required_visual:
            source_pins += [_pin(Path(__file__).with_name('visual_presentation.py'))]
            # Always present the authenticated copy; source aliases and projected
            # summaries cannot stand in for actual figure pixels/pages.
            for i,pin in enumerate(required_visual):
                path,raw=scientific_autonomy._document({k:pin[k] for k in ('path','sha256')},root,max_bytes=64*1024**2)
                relative=f'artifacts/final_visual{i:04d}{path.suffix.lower()}'
                with (packet/relative).open('xb') as stream:stream.write(raw)
                manifest['artifacts'].append({'id':f'final_visual{i:04d}','path':relative,
                    'sha256':pin['sha256'],'source_path':str(path),'source_sha256':pin['sha256'],
                    'source_phase':'checkin3_final_results','projection':'exact bytes','size':len(raw)})
    from . import scientific_autonomy
    _,decision_document=scientific_autonomy.observed_run_document(root)
    if 'autonomy' in decision_document:
        source_pins += [_pin(Path(__file__).with_name('scientific_autonomy.py'))]
        source_pins += [_pin(p) for p in scientific_autonomy.input_paths(decision_document,root)]
    source_pins += [_pin(Path(__file__).with_name(name + ".py")) for name in
                   ("agent_host", "research_cycle", "diagnostic_plan", "validation_io", "state_io")]
    contract = {"schema_version": 1, "kind": "scientific_judgment_request", "rundir": str(root),
        "role": role, "actor_id": actor_id, "cycle_id": view["cycle"]["cycle_id"],
        "cycle_sha256": view["cycle"]["sha256"], "head_sha256": events[-1]["sha256"],
        "phase": "repair_design" if repair else "improvement" if role == "improver" else "result_review",
        **({"final_results": view["cycle"]["final_results"],"visual_sources":required_visual} if "final_results" in view["cycle"] else {}),
        "claim_scope": claim_scope, "case_pin": case_pin, "case_sha256": execution.digest(case) if case else None,
        "case_anchor_pins": list({a["artifact"]["path"]: a["artifact"] for n in case["nodes"] for a in n["anchors"]}.values()) if case else [],
        "proposal_binding": proposal_binding, "prepared_settings": prepared, "source_pins": source_pins,
        "intervention_envelope": {"allowed_changed_paths": reg["policy"]["allowed_changed_paths"],
            "allowed_stages": reg["policy"]["allowed_stages"], "required_checks": reg["policy"]["required_checks"],
            "redos_remaining": view["redos_remaining"]},
        "execution_authorized": False, "actor_identity_authenticated": False}
    if association is not None: contract["campaign"] = association
    if retained_study:
        from .retained_science_review import pending
        contract["retained_study"] = {k:proof[k] for k in ("kind", "attempt_id", "cycle_id", "cycle_sha256", "source_plan_sha256", "bound_framework_inputs_sha256", "framework_root")}
        contract["source_pins"] += [_pin(Path(__file__).with_name(name + ".py")) for name in
            ("retained_science_review", "science", "launch_authorization", "prepared_runtime")]
    if enabled_context:
        contract["context_read"] = context_budget
        contract["source_pins"].append(_pin(followup.__file__))
    request_pin = _new(out / "request.json", contract)
    if case is None:
        case = _default_case(root, reg, view, packet, manifest, request_pin, contract)
        case_pin = _new(out / "public-case.json", case)
        contract.update(case_pin=case_pin, case_sha256=execution.digest(case),
            case_anchor_pins=list({a["artifact"]["path"]: a["artifact"] for n in case["nodes"] for a in n["anchors"]}.values()))
        # The case anchors the pre-case action request. Preserve it as a separate
        # immutable input; the final request can then bind the exact finite case.
        request_pin = _new(out / "bound-request.json", contract)
    subject = _add(packet, manifest, "judgment_request", contract, request_pin)
    if case:
        _add(packet, manifest, "public_case", _unreviewed(case), case_pin)
        for i, pin in enumerate(contract["case_anchor_pins"]):
            path = decision_case.bound_file(pin, Path(case_pin["path"]).parent)
            raw = path.read_bytes()
            if len(raw) > 2_000_000: raise ValueError("provide a bounded located audit source")
            # The exact sources were declared as public anchors, not a prior verdict.
            relative = f"artifacts/anchor{i}.txt"
            (packet / relative).write_bytes(raw)
            manifest["artifacts"].append({"id": f"anchor{i}", "path": relative, "sha256": hashlib.sha256(raw).hexdigest(),
                "source_path": str(path), "source_sha256": pin["sha256"], "projection": "exact bound public anchor"})
    if repair:
        _add(packet, manifest, "repair_design", proposal["proposal"])
    if role in {"improver", "synthesizer"}:
        actual = []
        for event in view["reviews"]:
            values = {}
            for pin in event.get("supporting_artifacts", []):
                # The aggregate is already authenticated by _live; actual
                # public model outputs remain their ordinary attempt pins.
                if pin.get("kind") == "role_context" or not pin["path"].endswith(".json"): continue
                # Journal pins are canonical run-relative or absolute evidence
                # identities. Resolve through the same bound run as _live,
                # then retain _read_pin's exact schema and consumed-buffer guard.
                document = _read_pin({**pin, "path": str(review._path(root, pin["path"]))})
                if isinstance(document, dict) and isinstance(document.get("result"), dict) and document["result"].get("kind") == "model_result":
                    value = document["result"].get("value")
                    if isinstance(value, dict) and value.get("kind") == "scientific_review":
                        values[execution.digest(value)] = value
            actual.append({"role": event["role"], "actor_id": event["actor_id"], "journal_event_sha256": event["sha256"],
                           "recorded_review": event, "actual_public_role_outputs": list(values.values())})
        _add(packet, manifest, "actual_role_judgments", actual)
    manifest["sha256"] = execution.digest({k: v for k, v in manifest.items() if k != "sha256"})
    atomic_json(packet / "manifest.json", manifest)
    if enabled_context:
        request_pin, subject = _context_packet(out, packet, manifest, contract, request_pin,
                                               selections=evidence_pages or [], prior=None)
    instructions = (f"You are the separate scientific {role}, declared actor {actor_id}. Read the indexed evidence, declared assumptions and conventions. "
        "Give concise public evidence and rationale only. Scope a result claim separately from a testable unresolved hypothesis. "
        "Distinguish source/infrastructure failure, numerical unresolved work and negative hypothesis. Never infer agreement from producer status. "
        "For contested, novel or high-consequence actions audit the exact public case, every claim/support edge and assumption against presented anchors; "
        "missing support is an evidence or discriminating experiment request, not proof of falsity. Do not copy supplied prior dispositions. "
        "Use the closed response schema. Audit node and support-edge decision values are supported/unresolved/contradicted, "
        "never the overall verdict accept/send_back/stop. Material-assumption dispositions are accepted/unresolved/rejected. "
        "These are public evidential judgments, not automatic truth or permission. subject_sha256 must equal " + subject + ". "
        "Result roles return kind='scientific_review', verdict accept/send_back/stop with located findings; acceptance names only the requested permitted scope and all inherited closes. For send_back/stop claim_scope MUST be null and closes MUST be []. A send_back finding must name existing allowed stages requiring recomputation. For missing retained evidence without requested computation, return scientific_evidence_request with verdict/claim_scope/proposal/proposal_verdict null, findings=[], closes=[], an exact public unresolved audit and a located evidence request in summary; this is nonvoting and keeps this cycle pending, with the actual call still charged. "
        "An improver returns kind='scientific_repair_proposal', verdict/claim_scope/proposal_verdict null, no findings or closes; "
        "propose exact replacement text only within allowed mutable paths, original stages/checks, and tests for every located finding. Label it untested. "
        "A known fix may use method='direct_verification', reference={artifact_id,location,expected_json,grounding_reason} from an indexed independent input/reference, alternatives=[]; never cite the produced result or changed setting as its own reference. "
        "A claimed discriminating experiment uses method='discriminating_experiment', reference=null and genuinely different rival predictions. Do not invent rivals for routine known corrections. "
        "If no permissible useful repair exists, return kind='scientific_evidence_request' with proposal null and specific evidence/new-experiment request in summary. "
        "Repair skeptic/synthesizer returns kind='scientific_repair_design_review', verdict/claim_scope null, no findings/closes/proposal; "
        "proposal_verdict adequate_for_bounded_test/unresolved/contradicted. Adequate design is never repair closure or a physics acceptance vote. "
        "Unused audit/proposal fields are null. No model agreement, source checks or transport proves physics. " + LIMITATION)
    if 'final_results' in contract:
        instructions += " This is CHECK-IN 3 final-results review. Inspect every final claim and the complete actual report/figure/data/recipe census, changes since CI2 and current blinding-check evidence. Manifest assertions are not scientific proof. Never unblind SR data. Material result/reconstruction errors require the dependent scientific stage and new result revision; rewording a report alone cannot close them. Keep uncertain or missing claims open. "
    node = {"id": role, "kind": "model", "role": role, "depends_on": [], "inputs": [],
        "packet": {"path": str(packet), "manifest_sha256": manifest["sha256"]}, "action": action,
        "parameters": {"instructions": instructions, "model": model, "reasoning_effort": reasoning_effort,
            "max_output_tokens": max_output_tokens, "output_schema": output_schema(context_followup=enabled_context)}, "max_attempts": 1}
    if required_visual:node['parameters']['visual_sources']=required_visual
    spec = {"schema_version": 1, "graph_id": "judgment-" + role, "budget": {"max_nodes": 1, "max_calls": 1+max_context_reworks,
        "max_output_tokens": max_output_tokens*(1+max_context_reworks), "max_wall_seconds": max_wall_seconds, "max_reworks": max_context_reworks}, "nodes": [node]}
    if enabled_context:
        node["parameters"]["instructions"] += " Return schema_version=2 with context_request null unless kind scientific_context_request. Such a request is strictly nonvoting and selects exact retained artifact/index pages; all verdict/claim/proposal fields null and findings/closes empty. Cite only anchor_context_core or actually presented anchor_context_page IDs and their exact wrapper SHA. Index pages give discovery, not scientific content. No tools are available inside this call."
    spec = _inherit_goal(spec, association)
    agent_graph.create(out / "graph", spec)
    if enabled_context: followup.preflight(spec, out / "graph")
    binding = {"schema_version": 1, "request": request_pin, "graph_root": str(out / "graph"), "node_id": role,
        "context_manifest_sha256": manifest["sha256"], "subject_sha256": subject}
    _new(out / "binding.json", binding)
    return binding


def _context_packet(out, packet, manifest, contract, action_request, *, selections, prior):
    from . import scientific_context_followup as followup
    budget = contract['context_read']
    if prior is None:
        budget['origin_manifest'] = _new(out/'role-projection-manifest.json',deepcopy(manifest))
        budget['initial_action_request'] = action_request
    chosen = followup.pages(packet, manifest['sha256'], selections)
    followup.add_pages(packet,manifest,budget,chosen,_add)
    revision = budget['revision']
    # Preserve earlier packet bytes under explicit historical identities inside
    # this newly prepared copy. Never mutate the previous packet or binding.
    for identity in ('judgment_request','anchor_context_core'):
        row = next((a for a in manifest['artifacts'] if a['id']==identity),None)
        if row is not None:
            renamed='prior_'+identity+str(revision).zfill(4)
            relative='artifacts/'+renamed+'.json'
            (packet/row['path']).rename(packet/relative)
            row.update(id=renamed,path=relative,presentation='on_demand')
    core = {'kind':'ordinary_scientific_role_context_core','current_action':{
                k:deepcopy(v) for k,v in contract.items() if k not in {'context_read','core_sha256'}},
            'original_context_limits':{k:budget[k] for k in ('max_reworks','max_pages','max_source_bytes')},
            'original_projected_population':budget['origin_manifest'],
            'prior_actual_nonvoting_request':None if prior is None else deepcopy(prior['value']),
            'prior_receipt':None if prior is None else deepcopy(prior['receipt']),
            'selected_content_disclosure':'Only current core and authenticated selected pages are mandatory content; inventory custody is not all-content reading.'}
    contract['core_sha256'] = _add(packet,manifest,'anchor_context_core',core)
    request_pin = _new(out/'context-bound-request.json',contract)
    subject = _add(packet,manifest,'judgment_request',contract,request_pin)
    manifest['sha256'] = execution.digest({k:v for k,v in manifest.items() if k!='sha256'})
    atomic_json(packet/'manifest.json',manifest)
    return request_pin, subject


def continue_role(binding, out, *, selections=None, allow_control=False, campaign_root=None):
    """Prepare exact requested retained pages and revise the same finite Graph.

    Caller dispatch remains explicit. The original review journal does not change.
    """
    from . import scientific_context_followup as followup, research_cycle
    prior = verify_binding(binding,allow_control=allow_control)
    contract = deepcopy(prior['contract'])
    if 'context_read' not in contract or prior['value']['kind']!='scientific_context_request':
        raise ValueError('current actual finite nonvoting context request required')
    requested=prior['value']['context_request']['selections']
    if selections is None: selections=requested
    if selections!=requested:
        raise ValueError('coordinator selections must equal the actual bound context request')
    root,reg,events,view=_live(contract['rundir'],retained_study='retained_study' in contract)
    if events[-1]['sha256']!=contract['head_sha256']:
        raise ValueError('context continuation belongs to changed scientific judgments/findings')
    graph_root=_path(binding['graph_root']);spec,state=agent_graph._load(graph_root)
    if campaign_root is not None:
        if 'campaign' in contract:raise ValueError('explicit campaign and registered experiment association are ambiguous')
        campaign_root=research_cycle._ordinary(campaign_root).resolve(strict=True)
        _,charged=research_cycle._load(campaign_root)
        research_cycle.validate_graph_reservation(charged,graph_root,spec)
    node=next(n for n in spec['nodes'] if n['id']==binding['node_id'])
    budget=contract['context_read']
    if (budget['revision']>=budget['max_reworks'] or state['reworks']!=budget['revision']
            or state['usage']['calls']>=spec['budget']['max_calls']):
        raise ValueError('original finite context call/rework budget exhausted')
    out=_path(out)
    old=_path(node['packet']['path'])
    if out==old or out.is_relative_to(old) or old.is_relative_to(out) or out.is_relative_to(graph_root.parent):
        raise ValueError('context continuation must preserve the entire prior role directory')
    out.mkdir(parents=True,exist_ok=False);packet=out/'context';packet.mkdir()
    index=review_context._PacketIndex(old,binding['context_manifest_sha256'])
    manifest=deepcopy(index.manifest)
    for entry in manifest['artifacts']:
        raw=index.read(entry);target=packet/entry['path'];target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as stream:stream.write(raw)
    index.finish();atomic_json(packet/'manifest.json',manifest)
    budget['revision']+=1
    budget['predecessor']={'binding':_new(out/'predecessor-binding.json',binding),
                           'result':research_cycle._pin(graph_root/state['nodes'][binding['node_id']]['result']['path']),
                           'generation':state['nodes'][binding['node_id']]['generation']}
    request_pin,subject=_context_packet(out,packet,manifest,contract,binding['request'],selections=selections,prior=prior)
    new=deepcopy(spec);selected=next(n for n in new['nodes'] if n['id']==binding['node_id'])
    selected['packet']={'path':str(packet),'manifest_sha256':manifest['sha256']}
    selected['parameters']['instructions']=node['parameters']['instructions'].replace(binding['subject_sha256'],subject)
    followup.preflight(new,graph_root)
    reason='Actual nonvoting retained-context request '+execution.digest(prior['value'])
    result={**binding,'request':request_pin,'context_manifest_sha256':manifest['sha256'],'subject_sha256':subject}
    _new(out/'prepared-continuation.json', {'binding':result,'graph_root':str(graph_root),
        'new_spec':new,'expected_spec_sha256':execution.digest(spec),
        'predecessor_result_pin':budget['predecessor']['result'],'reason':reason,
        'campaign':contract.get('campaign'),'execution_authorized':False})
    if 'campaign' in contract:
        _campaign(root,contract['campaign']['root'],contract['campaign']['experiment'])
        research_cycle.revise_graph(contract['campaign']['root'],graph_root,new,
            expected_spec_sha256=execution.digest(spec),predecessor_result_pin=budget['predecessor']['result'],reason=reason)
    else:
        research_cycle.revise_graph(campaign_root,graph_root,new,expected_spec_sha256=execution.digest(spec),
            predecessor_result_pin=budget['predecessor']['result'],reason=reason)
    result={**binding,'request':request_pin,'context_manifest_sha256':manifest['sha256'],'subject_sha256':subject}
    _new(out/'binding.json',result)
    return result


def verify_binding(binding, *, allow_control=False):
    """Recompute current role, exact source, case, context and dependencies."""
    _keys(binding, {"schema_version", "request", "graph_root", "node_id", "context_manifest_sha256", "subject_sha256"}, "role binding")
    if type(binding["schema_version"]) is not int or binding["schema_version"] != 1: raise ValueError("role binding/v1 required")
    contract = _read_pin(binding["request"])
    _keys(contract, {"schema_version", "kind", "rundir", "role", "actor_id", "cycle_id", "cycle_sha256", "head_sha256", "phase", "claim_scope", "case_pin", "case_sha256", "case_anchor_pins", "proposal_binding", "prepared_settings", "source_pins", "intervention_envelope", "execution_authorized", "actor_identity_authenticated"} | ({"campaign"} if "campaign" in contract else set()) | ({"retained_study"} if "retained_study" in contract else set()) | ({"context_read","core_sha256"} if "context_read" in contract else set()) | ({"final_results","visual_sources"} if "final_results" in contract else set()), "judgment request")
    if binding["subject_sha256"] != binding["request"]["sha256"] or binding["node_id"] != contract["role"]:
        raise ValueError("the exact displayed request and role must match the binding")
    proof = {}
    root, reg, events, view = _live(contract["rundir"], retained_study="retained_study" in contract, _proof=proof)
    if contract.get("final_results") != view["cycle"].get("final_results"):
        raise ValueError("final role belongs to a changed artifact/claim population")
    if "retained_study" in contract:
        from .retained_science_review import pending
        if contract["retained_study"] != {k:proof[k] for k in ("kind", "attempt_id", "cycle_id", "cycle_sha256", "source_plan_sha256", "bound_framework_inputs_sha256", "framework_root")}:
            raise ValueError("retained original study identity changed")
    if view["cycle"]["cycle_id"] != contract["cycle_id"] or view["cycle"]["sha256"] != contract["cycle_sha256"]:
        raise ValueError("role belongs to a superseded scientific cycle")
    if contract["kind"] != "scientific_judgment_request" or type(contract["schema_version"]) is not int or contract["schema_version"] != 1 or contract["execution_authorized"] is not False or contract["actor_identity_authenticated"] is not False:
        raise ValueError("invalid scientific judgment request/v1 authority")
    if contract["role"] in ROLE and contract["actor_id"] != reg["policy"]["actors"][ROLE[contract["role"]]]:
        raise ValueError("changed role actor")
    if contract["role"] in {"synthesizer", "improver"} or contract["phase"] == "repair_design":
        if events[-1]["sha256"] != contract["head_sha256"]: raise ValueError("role summary belongs to changed findings or judgments")
    for pin in [*contract["source_pins"], *contract["prepared_settings"]]:
        if _pin(pin["path"]) != pin: raise ValueError("role source or prepared scientific settings changed")
    case = _read_pin(contract["case_pin"]) if contract["case_pin"] else None
    if case:
        if execution.digest(case) != contract["case_sha256"]: raise ValueError("public case changed")
        for pin in contract["case_anchor_pins"]: decision_case.bound_file(pin, Path(contract["case_pin"]["path"]).parent)
    if "campaign" in contract:
        _keys(contract["campaign"], {"root", "experiment"}, "judgment campaign association")
        _campaign_graph(root, contract["campaign"]["root"], contract["campaign"]["experiment"], binding["graph_root"])
    receipt = agent_graph.role_receipt(binding["graph_root"], binding["node_id"],
        expected_subject_sha256=binding["subject_sha256"], expected_packet_sha256=binding["context_manifest_sha256"],
        require_exact_subject=True, allowed_roles={contract["role"]})
    # A self-attested vote is refused with its own diagnostic before the observation check excludes its transport.
    # Neither relays nor software controls count as independent voting evidence.
    if (contract["role"] in ROLE and receipt.get("attestation") == "self_attested"
            and isinstance(receipt.get("public_value"), dict)
            and receipt["public_value"].get("kind") not in {"scientific_context_request", "scientific_evidence_request"}):
        raise ValueError("self-attested review is advisory; it does not count as independent")
    nonvoting = (contract["role"] not in ROLE or isinstance(receipt.get("public_value"), dict)
                 and receipt["public_value"].get("kind") in {"scientific_context_request", "scientific_evidence_request"})
    if receipt["execution_observation"] not in OBSERVATIONS | ({"control_only"} if allow_control and nonvoting else set()) or not receipt["context_transport_separated"]:
        raise ValueError("fresh observed role transport required; control transport is not scientific review")
    value = receipt["public_value"]
    _keys(value, {"schema_version", "kind", "subject_sha256", "verdict", "summary", "findings", "closes", "claim_scope", "audit", "proposal", "proposal_verdict"} | ({"context_request","citations"} if "context_read" in contract else set()), "scientific role response")
    if type(value["schema_version"]) is not int or value["schema_version"] != (2 if "context_read" in contract else 1) or value["subject_sha256"] != binding["subject_sha256"]:
        raise ValueError("scientific response subject changed")
    if "context_read" in contract:
        from . import scientific_context_followup as followup
        latest_spec,_=agent_graph._load(_path(binding['graph_root']))
        latest_node=next(n for n in latest_spec['nodes'] if n['id']==binding['node_id'])
        followup.verify_presentation(contract,receipt,value,latest_node['packet']['path'])
        if value['kind']=='scientific_context_request':
            _keys(value['context_request'], {'selections'}, 'exact nonvoting context request')
            if not value['context_request']['selections']:raise ValueError('context request requires explicit retained pages')
        elif value['context_request'] is not None:
            raise ValueError('a scientific vote/experiment request cannot simultaneously request context pages')
    if 'final_results' in contract:
        from . import final_results_review as final
        required_visual=final.visual_sources(root,contract['final_results'])
        if contract.get('visual_sources')!=required_visual:
            raise ValueError('required final figure source roster changed')
        current_spec,_=agent_graph._load(_path(binding['graph_root']))
        current_node=next(n for n in current_spec['nodes'] if n['id']==binding['node_id'])
        if current_node['parameters'].get('visual_sources',[])!=required_visual:
            raise ValueError('current Graph omitted or replaced mandatory final figures')
        if required_visual and value['kind'] not in {'scientific_evidence_request','scientific_context_request'}:
            from .visual_presentation import verify_visual_presentation
            verify_visual_presentation(receipt,expected_sources=required_visual,
                expected_packet_sha256=binding['context_manifest_sha256'],expected_node_id=binding['node_id'])
    if (contract["role"] in ROLE
            and value["kind"] not in {"scientific_context_request", "scientific_evidence_request"}
            and receipt["attestation"] == "self_attested"):
        raise ValueError("self-attested review is advisory; it does not count as independent")
    review._text(value["summary"], "public scientific rationale")
    audit = _audit(case, value["audit"], contract["actor_id"], Path(contract["case_pin"]["path"]).parent) if case else None
    if not case and value["audit"] is not None: raise ValueError("unpresented decision case cannot be reviewed")
    proposal = value["proposal"]
    predecessor = None
    if contract["proposal_binding"]:
        predecessor = verify_binding(contract["proposal_binding"], allow_control=allow_control)
        proposal = predecessor["proposal"]
    if value['kind']=='scientific_context_request':
        if any(value[k] is not None for k in ('verdict','claim_scope','proposal','proposal_verdict')) or value['findings'] or value['closes']:
            raise ValueError('context request is nonvoting and cannot close findings or request work')
    elif contract["phase"] == "improvement":
        if value["kind"] not in {"scientific_repair_proposal", "scientific_evidence_request"} or any(value[k] is not None for k in ("verdict", "claim_scope", "proposal_verdict")) or value["findings"] or value["closes"]:
            raise ValueError("improvement is nonvoting and cannot close evidence")
        if value["kind"] == "scientific_repair_proposal":
            graph_spec = read_json(_path(binding["graph_root"]) / agent_graph.SPEC)
            selected = next(n for n in graph_spec["nodes"] if n["id"] == binding["node_id"])
            if selected["packet"]["manifest_sha256"] != binding["context_manifest_sha256"]:
                raise ValueError("proposal packet differs from the exact current role binding")
            _proposal(root, reg, view, proposal, selected["packet"])
        elif proposal is not None: raise ValueError("new evidence/experiment request cannot silently admit a repair")
    elif contract["phase"] == "repair_design":
        if value["kind"] != "scientific_repair_design_review" or any(value[k] is not None for k in ("verdict", "claim_scope", "proposal")) or value["findings"] or value["closes"] or value["proposal_verdict"] not in {"adequate_for_bounded_test", "unresolved", "contradicted"}:
            raise ValueError("proposal review is not an executed closure vote")
    elif value["kind"] in {"scientific_evidence_request", "scientific_context_request"}:
        if any(value[k] is not None for k in ("verdict", "claim_scope", "proposal", "proposal_verdict")) or value["findings"] or value["closes"]:
            raise ValueError("result evidence request is nonvoting and cannot close findings")
    elif value["kind"] != "scientific_review" or value["proposal"] is not None or value["proposal_verdict"] is not None:
        raise ValueError("result review cannot substitute an unexecuted repair")
    elif (value["verdict"] not in {"accept", "send_back", "stop"}
            or value["verdict"] != "accept" and (value["claim_scope"] is not None or value["closes"])
            or value["verdict"] == "accept" and value["claim_scope"] != contract["claim_scope"]):
        raise ValueError("only acceptance may close findings or claim the requested scope")
    if audit and audit["status"] != "supported" and (value["verdict"] == "accept" or value["proposal_verdict"] == "adequate_for_bounded_test"):
        raise ValueError("unresolved material action audit requires evidence, bounded experiment or stop")
    support = [binding["request"], *contract["source_pins"], *contract["prepared_settings"]]
    if contract["case_pin"]:
        support += [contract["case_pin"], *[_pin(decision_case.bound_file(p, Path(contract["case_pin"]["path"]).parent)) for p in contract["case_anchor_pins"]]]
    graph_root = _path(binding["graph_root"])
    for p in [graph_root / agent_graph.SPEC, graph_root / agent_graph.STATE,
              *sorted((graph_root / "attempts").glob("*.json")), *sorted((graph_root / "calls").glob("*.json"))]: support.append(_pin(p))
    node = read_json(graph_root / agent_graph.SPEC)["nodes"][0]
    packet = _path(node["packet"]["path"])
    context_index = review_context._PacketIndex(packet, binding["context_manifest_sha256"])
    support.append({"kind": "role_context", "path": str(packet / "manifest.json"),
        "sha256": context_index.manifest_file_sha256,
        "manifest_sha256": binding["context_manifest_sha256"],
        "cycle_id": contract["cycle_id"], "cycle_sha256": contract["cycle_sha256"]})
    context_index.finish()
    if predecessor: support += predecessor["supporting_artifacts"]
    normalized = {}
    for pin in support:
        canonical = {**pin, "path": review._identity(root, review._path(root, pin["path"]))}
        previous = normalized.get(canonical["path"])
        if previous is not None and previous != canonical:
            raise ValueError("conflicting scientific role support commitments")
        normalized[canonical["path"]] = canonical
    support = review._supporting(root, list(normalized.values()))
    return {"contract": contract, "receipt": receipt, "value": value, "audit": audit,
        "proposal": proposal, "supporting_artifacts": support, "execution_authorized": False}


def _proposal(root, reg, view, proposal, packet_binding):
    _keys(proposal, {"changed_paths", "stages", "recheck_checks", "replacements", "tests", "max_seconds"}, "bounded repair proposal")
    if not isinstance(proposal["changed_paths"], list) or not proposal["changed_paths"] or len(set(proposal["changed_paths"])) != len(proposal["changed_paths"]): raise ValueError("distinct repair paths required")
    policy = reg["policy"]
    if not set(proposal["changed_paths"]) <= set(policy["allowed_changed_paths"]) or not set(proposal["stages"]) <= set(policy["allowed_stages"]): raise ValueError("repair widens original path/stage admission")
    replacement = proposal["replacements"]
    if type(replacement) is not list or len(replacement) != len(proposal["changed_paths"]): raise ValueError("exact replacements required")
    for row in replacement:
        _keys(row, {"path", "text"}, "repair replacement")
        review._relative(row["path"])
        if type(row["text"]) is not str or not row["text"] or len(row["text"].encode()) > 65536: raise ValueError("bounded nonempty scientific setting replacement required")
    if {r["path"] for r in replacement} != set(proposal["changed_paths"]): raise ValueError("replacement paths differ")
    tests = proposal["tests"]
    if type(tests) is not list or len(tests) != len(view["findings"]): raise ValueError("every located objection needs a prospective recheck")
    by_id = {}
    for test in tests:
        _keys(test, {"finding_id", "observable", "intervention", "held_conditions", "method", "reference", "alternatives"}, "prospective repair test")
        if test["finding_id"] in by_id: raise ValueError("duplicate finding test")
        by_id[test["finding_id"]] = test
        for field in ("observable", "intervention", "held_conditions"): review._text(test[field], field)
        alternatives = test["alternatives"]
        if test["method"] == "direct_verification":
            if alternatives != []: raise ValueError("direct verification uses its grounded reference, not invented rivals")
            reference = test["reference"]
            _keys(reference, {"artifact_id", "location", "expected_json", "grounding_reason"}, "direct reference check")
            review._text(reference["grounding_reason"], "independent reference/invariant provenance")
            packet = _path(packet_binding["path"])
            manifest = _read_pin(_pin(packet / "manifest.json"))
            if (manifest.get("sha256") != packet_binding["manifest_sha256"]
                    or execution.digest({k: v for k, v in manifest.items() if k != "sha256"}) != packet_binding["manifest_sha256"]):
                raise ValueError("direct-reference context manifest changed")
            entries = [a for a in manifest["artifacts"] if a["id"] == reference["artifact_id"]]
            if len(entries) != 1: raise ValueError("direct recheck reference must be a presented indexed artifact")
            def canonical(value):
                raw = Path(value)
                return _path(raw if raw.is_absolute() else _path(root) / raw)
            entry = entries[0]; source = canonical(entry["source_path"])
            excluded = [canonical(p) for r in view["cycle"]["receipts"] for p in r["outputs"]]
            mutable = {canonical(p["path"]) for p in view["cycle"]["effective_settings"]}
            mutable.update(canonical(p) for p in policy["allowed_changed_paths"])
            if (source in mutable or entry["id"] in {"judgment_request", "public_case", "actual_role_judgments", "repair_design"}
                    or any(source == out or source.is_relative_to(out) for out in excluded)):
                raise ValueError("the produced result or mutable setting is not an independent direct reference")
            raw = review_context.read_artifact(packet, entry["id"], expected_manifest_sha256=packet_binding["manifest_sha256"])
            actual = decision_case.pointer(review_context._strict_json_bytes(raw), reference["location"])
            expected = review_context._strict_json_bytes(reference["expected_json"].encode())
            if type(actual) is not type(expected) or execution.digest(actual) != execution.digest(expected):
                raise ValueError("direct expected result differs from its exact bound reference/invariant")
        elif test["method"] == "discriminating_experiment":
            if test["reference"] is not None: raise ValueError("discriminating design must declare its rival predictions")
            if type(alternatives) is not list or not 2 <= len(alternatives) <= 16: raise ValueError("explicit competing predictions required for a claimed discriminating test")
            for alt in alternatives:
                _keys(alt, {"hypothesis", "prediction"}, "prospective rival prediction")
                review._text(alt["hypothesis"], "rival hypothesis"); review._text(alt["prediction"], "prospective outcome")
            if len({a["hypothesis"] for a in alternatives}) != len(alternatives) or len({a["prediction"] for a in alternatives}) < 2: raise ValueError("identical predictions do not discriminate mechanisms")
        else:
            raise ValueError("repair test must be direct_verification or discriminating_experiment")
    if set(by_id) != {f["id"] for f in view["findings"]}: raise ValueError("repair omits located objection")
    for f in view["findings"]:
        if not set(f["required_stages"]) <= set(proposal["stages"]) or not set(f["check_ids"]) <= set(proposal["recheck_checks"]) or not set(f["required_paths"]) <= set(proposal["changed_paths"]): raise ValueError("repair drops an inherited obligation")
    if not set(proposal["recheck_checks"]) <= {c["id"] for c in policy["required_checks"]}: raise ValueError("repair introduces unregistered checks")


def consume(root, binding, *, allow_control=False):
    """Record a current actual role decision using the original review journal."""
    verified = verify_binding(binding, allow_control=allow_control)
    c, value = verified["contract"], verified["value"]
    if str(review._root(root)) != c["rundir"]: raise ValueError("role belongs to another run")
    if c["phase"] != "result_review" or value["kind"] in {"scientific_evidence_request", "scientific_context_request"}: return verified  # nonvoting evidence for next role
    if value["claim_scope"] is not None and value["claim_scope"] != c["claim_scope"]: raise ValueError("model changed requested claim scope")
    return review.submit_review(root, role=ROLE[c["role"]], actor_id=c["actor_id"], verdict=value["verdict"], summary=value["summary"],
        findings=value["findings"], closes=value["closes"], claim_scope=value["claim_scope"], supporting_artifacts=verified["supporting_artifacts"], retained_study="retained_study" in c)


def apply_proposal(root, binding, *, allow_control=False):
    """Explicit preparation on permitted mutable settings; never execute/admit."""
    verified = verify_binding(binding, allow_control=allow_control)
    if verified["receipt"]["role"] != "improver" or verified["contract"]["rundir"] != str(review._root(root)): raise ValueError("actual nonvoting improvement for this run required")
    root = review._root(root)
    from . import scientific_autonomy
    _,document=scientific_autonomy.observed_run_document(root)
    if 'autonomy' in document:scientific_autonomy.correction_authority(root,verified['proposal'])
    # Preserve actual original bytes in the existing cycle snapshots; never touch outputs.
    for row in verified["proposal"]["replacements"]:
        path = review._path(root, row["path"])
        path.write_text(row["text"], encoding="utf8")
    return {"prepared_settings": [_pin(root / p) for p in verified["proposal"]["changed_paths"]],
            "next": "fresh skeptical repair-design review, then decider admission", "execution_authorized": False}


def admit_repair(root, binding, *, allow_control=False):
    """An actual decider design result admits only exact existing correction scope."""
    verified = verify_binding(binding, allow_control=allow_control)
    if verified["receipt"]["role"] != "synthesizer" or verified["contract"]["phase"] != "repair_design" or verified["value"]["proposal_verdict"] != "adequate_for_bounded_test": raise ValueError("fresh adequate decider repair-design result required")
    root = review._root(root)
    if verified["contract"]["rundir"] != str(root): raise ValueError("repair belongs to another run")
    p = verified["proposal"]
    from . import scientific_autonomy
    _,document=scientific_autonomy.observed_run_document(root)
    if 'autonomy' in document:scientific_autonomy.correction_authority(root,p)
    support = verified["supporting_artifacts"]
    # Prepared settings are already committed by correction snapshots; keeping their
    # same bytes as model support is correct for this admitted correction only.
    if (root / "inputs/science-plan.json").is_file():
        from . import science
        if p["stages"] != ["science"]: raise ValueError("ordinary science repair has one declared science stage")
        return science.correct(root, actor_id=verified["contract"]["actor_id"], changed_paths=p["changed_paths"],
            recheck_checks=p["recheck_checks"], max_seconds=p["max_seconds"], supporting_artifacts=support)
    return review.authorize_correction(root, actor_id=verified["contract"]["actor_id"], changed_paths=p["changed_paths"],
        stages=p["stages"], recheck_checks=p["recheck_checks"], supporting_artifacts=support)


def execute_role(binding, host):
    """Explicit bounded model dispatch through the existing accounted Graph."""
    contract = _read_pin(binding["request"])
    from . import scientific_autonomy
    _,document=scientific_autonomy.observed_run_document(contract['rundir'])
    if 'autonomy' in document:scientific_autonomy.authorize(contract['rundir'],'accept_recommendation')
    _, _, events, view = _live(contract["rundir"], retained_study="retained_study" in contract)  # same custody as preparation and verification
    if contract["cycle_sha256"] != view["cycle"]["sha256"]:
        raise ValueError("stale scientific cycle before role dispatch")
    if contract["role"] in {"improver", "synthesizer"} or contract["phase"] == "repair_design":
        if events[-1]["sha256"] != contract["head_sha256"]: raise ValueError("stale findings before role dispatch")
    for pin in [binding["request"], *contract["source_pins"], *contract["prepared_settings"]]:
        if _pin(pin["path"]) != pin: raise ValueError("changed source or settings before dispatch")
    if contract["case_pin"]:
        _read_pin(contract["case_pin"])
        for pin in contract["case_anchor_pins"]: decision_case.bound_file(pin, Path(contract["case_pin"]["path"]).parent)
    spec, checkpoint = agent_graph._load(_path(binding['graph_root']))
    selected = next(n for n in spec['nodes'] if n['id'] == binding['node_id'])
    if selected['packet']['manifest_sha256'] != binding['context_manifest_sha256']:
        raise ValueError('superseded context binding before dispatch')
    if 'context_read' in contract:
        from . import scientific_context_followup
        if (events[-1]['sha256'] != contract['head_sha256']
                or checkpoint['reworks'] != contract['context_read']['revision']):
            raise ValueError('stale scientific context or Graph generation before dispatch')
        scientific_context_followup.preflight(spec, binding['graph_root'])
    if "campaign" in contract:
        from . import research_cycle
        _keys(contract["campaign"], {"root", "experiment"}, "judgment campaign association")
        association = _campaign(contract["rundir"], contract["campaign"]["root"], contract["campaign"]["experiment"])
        spec, _ = agent_graph._load(_path(binding["graph_root"]))
        return research_cycle.execute_graph(association["root"], binding["graph_root"], spec, host, prepared=True)
    return agent_graph.execute(binding["graph_root"], host, workers=1)


def advance(root, out, *, host, model, reasoning_effort, max_output_tokens, max_wall_seconds,
            claim_scope=None, case_pin=None, improver_actor=None, proposal_binding=None, allow_control=False,
            campaign=None, experiment=None, context_index_limits=None, evidence_pages=None, max_context_reworks=0):
    """Default durable critique/improvement/skeptical-verification subgraph.

    Original separate roles, actual presentation, limited calls, correction
    authority and nonvoting evidence requests remain ordinary domain services.
    An epoch-two run delegates to the ``review.points`` graph.
    """
    from .graphs import review as review_graph
    if review_graph.delegates(root):
        return review_graph.orchestrated(root, claim_scope)
    from .research_orchestrator import review
    return review(root, out, host=host, model=model, reasoning_effort=reasoning_effort,
        max_output_tokens=max_output_tokens, max_wall_seconds=max_wall_seconds,
        claim_scope=claim_scope, case_pin=case_pin, improver_actor=improver_actor,
        proposal_binding=proposal_binding, allow_control=allow_control, campaign=campaign,
        experiment=experiment, context_index_limits=context_index_limits,
        evidence_pages=evidence_pages, max_context_reworks=max_context_reworks)


def failed_feedback(root, intake_pin, critic_binding, verifier_binding, *, out=None, campaign=None, experiment=None, allow_control=False):
    """Actual failed CI2→canonical diagnostic feedback→existing prospective cycle."""
    from . import failed_stage_review as failed, research_cycle, gate_wiring
    if campaign is None and (experiment is not None or out is not None):
        raise ValueError("campaign, observed experiment and new feedback output must be supplied together")
    # R0/R1: the decision gate decides before any diagnostic is read or fed back.
    gate_wiring.require_transition(root, "failed_stage_feedback", gate_wiring.failed_feedback_action(root, intake_pin))
    document = _read_pin(intake_pin)
    checked = failed.verify(document, base_dir=root)
    feedback = failed.graph_feedback(checked, critic_binding, verifier_binding, base_dir=root, allow_control=allow_control)
    if campaign is not None:
        if experiment is None or out is None:
            raise ValueError("explicit already charged experiment and new feedback output required")
        if _path(out).is_relative_to(_path(root)):
            raise ValueError("diagnostic feedback must be separate from immutable failed run history")
        for binding in (critic_binding, verifier_binding):
            _campaign_graph(root, campaign, experiment, binding["graph_root"])
        feedback_pin = _new(out, feedback)
        research_cycle.attach_failed_stage(campaign, experiment, intake_pin)
        research_cycle.diagnostic_feedback(campaign, experiment, feedback_pin, allow_control=allow_control)
    return feedback


def host_tool(parameters, pins):
    """Ordinary Host/Graph entry; every supplied request is an explicit input.

    This tool never dispatches a nested model or worker. The orchestrator uses
    the existing Graph run/prepare-external path for the prepared role.
    """
    _keys(parameters, {"request_input"}, "scientific judgment tool parameters")
    identity = parameters["request_input"]
    if identity not in pins: raise ValueError("judgment request must be an explicit graph input")
    path, sha = pins[identity]
    request = _read_pin({"path": str(path), "sha256": sha})
    _keys(request, {"operation", "rundir", "arguments"}, "judgment tool request")
    allowed = {str(_path(p)): h for p, h in pins.values()}
    def require(pin):
        if allowed.get(str(_path(pin["path"]))) != pin["sha256"]:
            raise ValueError("judgment source must be explicitly presented to the caller graph")
    values = request["arguments"]
    if type(values) is not dict: raise ValueError("judgment arguments object required")
    operation = request["operation"]
    if operation == "status":
        _keys(values, set(), "status arguments")
        return next_step(request["rundir"])
    if operation == "open":
        _keys(values, {"check_results", "correction_id"}, "open arguments")
        require(values["check_results"])
        return open_cycle(request["rundir"], check_results=values["check_results"]["path"], correction_id=values["correction_id"])
    if operation == "prepare-role":
        _keys(values, {"out", "role", "actor_id", "model", "reasoning_effort", "max_output_tokens", "max_wall_seconds", "claim_scope", "case_pin", "proposal_binding"}
              | ({"campaign", "experiment"} if "campaign" in values or "experiment" in values else set()) | ({"retained_study"} if "retained_study" in values else set())
              | ({"context_index_limits"} if "context_index_limits" in values else set())
              | ({"evidence_pages"} if "evidence_pages" in values else set())
              | ({"max_context_reworks"} if "max_context_reworks" in values else set()), "prepare arguments")
        if values["case_pin"]: require(values["case_pin"])
        if values["proposal_binding"]:
            require(values["proposal_binding"])
            values = {**values, "proposal_binding": _read_pin(values["proposal_binding"])}
        return prepare_role(request["rundir"], **values)
    if operation == "continue-role":
        _keys(values, {"binding","out"}, "context continuation arguments")
        require(values["binding"]); binding=_read_pin(values["binding"]); require(binding["request"])
        return continue_role(binding,values["out"])
    if operation in {"consume", "apply-proposal", "admit-repair"}:
        _keys(values, {"binding"}, "role consumer arguments"); require(values["binding"])
        binding = _read_pin(values["binding"])
        require(binding["request"])
        return globals()[operation.replace("-", "_")](request["rundir"], binding)
    raise ValueError("unsupported judgment tool operation; no automatic approval/compute")


def prepare_failed_role(root, intake_pin, out, *, role, model, reasoning_effort,
                        max_output_tokens, max_wall_seconds, action="model", campaign=None, experiment=None, evidence_pages=None):
    """The ordinary failed-result handoff prepares canonical diagnostic roles."""
    from . import failed_stage_review as failed
    if role not in {"critic", "verifier"}: raise ValueError("failed diagnostic feedback needs separate critic/verifier roles")
    document = failed.verify(_read_pin(intake_pin), base_dir=root)
    association = _campaign(root, campaign, experiment)
    out = _path(out); failed_root = _path(root)
    if out == failed_root or out.is_relative_to(failed_root):
        raise ValueError("diagnostic contexts must be separate from immutable failed run history")
    out.mkdir(parents=True, exist_ok=False)
    packet = out / "context"
    manifest = failed.create_context(document, role, packet, base_dir=root, evidence_pages=evidence_pages)
    actor = document["actors"][ROLE[role]]
    schema = _object({"kind": S, "summary": S, "observations": _array(_object({"artifact_id": S, "location": S, "observation": S})),
        "mechanisms": _array(_object({"hypothesis": S, "intervention": S, "observable": S, "held_conditions": S,
            "rivals": _array(_object({"hypothesis": S, "prediction": S}), 16)})),
        "unknowns": _array(_object({"question": S, "specific_evidence_or_experiment": S}))})
    node = {"id": role, "kind": "model", "role": role, "depends_on": [], "inputs": [],
        "packet": {"path": str(packet), "manifest_sha256": manifest["sha256"]}, "action": action, "max_attempts": 1,
        "parameters": {"model": model, "reasoning_effort": reasoning_effort, "max_output_tokens": max_output_tokens,
            "output_schema": schema, "instructions": "Review this actual failed stage in a fresh independent diagnostic context. "
            "Keep infrastructure failure, numerical unresolved and a negative hypothesis distinct. Locate actual raw observations; "
            "propose useful source-bound interventions with held conditions, observable contrasts and competing predictions. "
            "List missing evidence explicitly. Deferred artifacts are authenticated but not automatically read: request exact artifact/byte pages "
            "for a fresh bounded role context when needed. No successful acceptance, failed-result delivery/reuse or automatic retry is available. " + LIMITATION}}
    spec = {"schema_version": 1, "graph_id": "failed-judgment-" + role,
        "budget": {"max_nodes": 1, "max_calls": 1, "max_output_tokens": max_output_tokens, "max_wall_seconds": max_wall_seconds, "max_reworks": 0}, "nodes": [node]}
    agent_graph.create(out / "graph", _inherit_goal(spec, association))
    binding = {"graph_root": str(out / "graph"), "node_id": role, "context_manifest_sha256": manifest["sha256"], "actor_id": actor}
    _new(out / "binding.json", binding)
    return binding


def research_feedback(root, campaign, experiment):
    """Terminal ordinary judgment→complete actual critique→existing revision path."""
    from . import research_cycle
    _, state = research_cycle._load(Path(campaign))
    row = next(e for e in state["experiments"] if e["id"] == experiment)
    if row["rundir"] is None or _path(row["rundir"]) != _path(root):
        raise ValueError("scientific judgment does not belong to this campaign experiment")
    from . import gate_wiring  # R0/R1: research_choice before adjudication.
    gate_wiring.require_transition(root, "research_choice",
                                   gate_wiring.research_choice_action(root, campaign, experiment, row))
    research_cycle.adjudicate(campaign, experiment)
    return research_cycle.feedback_packet(campaign, experiment)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "open", "open-final", "prepare-role", "execute-role", "consume", "apply-proposal", "admit-repair", "advance", "failed-feedback", "prepare-failed-role", "research-feedback", "continue-role"):
        p = subs.add_parser(name); p.add_argument("--rundir", type=Path, required=True)
        if name in {"open", "open-final"}: p.add_argument("--checks", required=True); p.add_argument("--correction-id"); p.add_argument("--retained-study", action="store_true")
        if name in {"prepare-role", "advance", "prepare-failed-role"}:
            p.add_argument("--campaign", type=Path); p.add_argument("--experiment")
        if name in {"prepare-role", "advance", "prepare-failed-role"}:
            p.add_argument("--out", type=Path, required=True); p.add_argument("--model", required=True); p.add_argument("--reasoning-effort", required=True)
            p.add_argument("--max-output-tokens", type=int, required=True); p.add_argument("--max-wall-seconds", type=int, required=True)
            p.add_argument("--claim-scope"); p.add_argument("--case", type=Path)
            if name == "prepare-role": p.add_argument("--retained-study", action="store_true")
        if name in {"prepare-role", "advance"}:
            p.add_argument("--evidence-pages", type=Path)
            p.add_argument("--max-context-reworks", type=int, default=0)
            p.add_argument("--max-index-artifacts", type=int)
            p.add_argument("--max-index-bytes", type=int)
        if name in {"prepare-role", "prepare-failed-role"}:
            p.add_argument("--role", choices=review_context.ROLES, required=True)
            p.add_argument("--actor", required=name == "prepare-role")
            p.add_argument("--proposal-binding", type=Path); p.add_argument("--external", action="store_true")
        if name == "continue-role": p.add_argument("--out", type=Path, required=True)
        if name == "open-final": p.add_argument("--final-manifest", type=Path, required=True)
        if name in {"execute-role", "consume", "apply-proposal", "admit-repair", "continue-role"}: p.add_argument("--binding", type=Path, required=True)
        if name in {"execute-role", "advance"}: p.add_argument("--host-config", type=Path, required=True)
        if name == "advance": p.add_argument("--improver-actor"); p.add_argument("--proposal-binding", type=Path)
        if name == "prepare-failed-role":
            p.add_argument("--intake", type=Path, required=True)
            p.add_argument("--evidence-pages", type=Path)
        if name == "research-feedback": p.add_argument("--campaign", type=Path, required=True); p.add_argument("--experiment", required=True)
        if name == "failed-feedback":
            p.add_argument("--campaign", type=Path); p.add_argument("--experiment"); p.add_argument("--out", type=Path)
            p.add_argument("--intake", type=Path, required=True); p.add_argument("--critic-binding", type=Path, required=True); p.add_argument("--verifier-binding", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "status": result = next_step(args.rundir)
        elif args.command == "open": result = open_cycle(args.rundir, check_results=args.checks, correction_id=args.correction_id, retained_study=args.retained_study)
        elif args.command == "open-final": result = open_final_cycle(args.rundir, manifest=_pin(args.final_manifest), check_results=args.checks)
        elif args.command == "research-feedback": result = research_feedback(args.rundir, args.campaign, args.experiment)
        elif args.command == "prepare-failed-role":
            result = prepare_failed_role(args.rundir, _pin(args.intake), args.out, role=args.role, model=args.model,
                reasoning_effort=args.reasoning_effort, max_output_tokens=args.max_output_tokens, max_wall_seconds=args.max_wall_seconds,
                action="external" if args.external else "model", campaign=args.campaign, experiment=args.experiment,
                evidence_pages=_read_pin(_pin(args.evidence_pages)) if args.evidence_pages else None)
        elif args.command in {"prepare-role", "advance"}:
            values = dict(model=args.model, reasoning_effort=args.reasoning_effort, max_output_tokens=args.max_output_tokens,
                max_wall_seconds=args.max_wall_seconds, claim_scope=args.claim_scope, case_pin=_pin(args.case) if args.case else None,
                campaign=args.campaign, experiment=args.experiment,
                evidence_pages=_read_pin(_pin(args.evidence_pages)) if args.evidence_pages else None,
                max_context_reworks=args.max_context_reworks)
            if args.max_index_artifacts is not None or args.max_index_bytes is not None:
                values["context_index_limits"] = {
                    "max_artifacts": args.max_index_artifacts if args.max_index_artifacts is not None else review_context._INDEX_DEFAULTS["max_artifacts"],
                    "max_total_bytes": args.max_index_bytes if args.max_index_bytes is not None else review_context._INDEX_DEFAULTS["max_total_bytes"]}
            if args.command == "prepare-role": result = prepare_role(args.rundir, args.out, role=args.role, actor_id=args.actor,
                proposal_binding=read_json(args.proposal_binding) if args.proposal_binding else None, action="external" if args.external else "model", retained_study=args.retained_study, **values)
            else:
                from .agent_host import AgentHost
                result = advance(args.rundir, args.out, host=AgentHost.from_config(read_json(args.host_config)),
                    improver_actor=args.improver_actor, proposal_binding=read_json(args.proposal_binding) if args.proposal_binding else None, **values)
        elif args.command == "failed-feedback": result = failed_feedback(args.rundir, _pin(args.intake), read_json(args.critic_binding), read_json(args.verifier_binding),
            campaign=args.campaign, experiment=args.experiment, out=args.out)
        elif args.command == "continue-role": result = continue_role(_read_pin(_pin(args.binding)),args.out)
        elif args.command == "execute-role":
            from .agent_host import AgentHost
            result = execute_role(read_json(args.binding), AgentHost.from_config(read_json(args.host_config)))
        else: result = globals()[args.command.replace("-", "_")](args.rundir, read_json(args.binding))
        print(json.dumps(result, indent=2, allow_nan=False)); return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc), "execution_authorized": False})); return 2


if __name__ == "__main__": raise SystemExit(main())
