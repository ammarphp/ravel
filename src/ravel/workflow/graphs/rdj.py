"""RDJ case scheduling on the substrate, with custody as the domain authority.

The dispatcher protocol is the single-call agent seam until the tool gate's
full-tool reviewers land. Reservations retain their domain path, input digest,
review scope and original thread instance in custody. Started model effects are
never retried without a typed, registered downstream receipt. Graph state and
proposer resume values cannot authorize an action.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
import os
from pathlib import Path
import time
from typing import TypedDict

from .. import decision_case as dc, effect_ledger as ledger, graph_nodes as nodes
from .. import graph_registry, graph_substrate as substrate, rdj_custody as custody, rdj_loop as rdj
from .. import role_registry
from ..state_io import atomic_json, file_lock, read_json

CASE = "rdj.case"
ROLE = "rdj.role"
ACTIVE = ContextVar("rdj_dispatcher", default=None)


def _options(state):
    return {"max_steps": 32, "edge_batch_size": 64, "authorize": True,
            "interactive": True, "campaign": None, **state.get("options", {})}


@contextmanager
def dispatch_context(dispatcher):
    """Review-points and gate-wiring seam for embedding ``case(ctx)`` in an enclosing substrate graph.

    The caller supplies the existing case instance and projects optional ``options``
    (including the original campaign vector). Yielded errors are operational data;
    the enclosing graph still calls its ordinary RDJ gate provider.
    """
    context = {"dispatcher": dispatcher, "errors": []}
    token = ACTIVE.set(context)
    try:
        with ledger.registrations(charge_ledgers={"run_ceilings": (_present_run, _charge_run),
                        "campaign": (_present_campaign, _charge_campaign)},
                        validators={"rdj_reservation": _validate_reservation, "rdj_role_receipt": _validate_role}):
            yield context
    finally:
        ACTIVE.reset(token)


class State(nodes.BaseState, total=False):
    turn: int
    requests: list
    options: dict
    branch: str
    case_sha256: str
    challenges: list
    receipt: dict


class RoleView(TypedDict):
    meta: dict
    request: dict


class RoleState(nodes.BaseState, total=False):
    request: dict


def _standard(builder, graph_id):
    nodes.add(builder, "decision_turn", nodes.decision_turn("rdj"), graph_id=graph_id)
    nodes.add(builder, "reconcile", nodes.reconcile_node(), graph_id=graph_id)
    nodes.add(builder, "hold", nodes.hold("rdj_hold"), graph_id=graph_id)
    return builder


def _root(state):
    return Path(state["meta"]["scope_root"])


def _downstream_path(request):
    return f"rdj/downstream/role-{request['slot']}.json"


def _prepare_path(identifier):
    return f"rdj/downstream/reservation-{identifier}.json"


def _write_downstream(root, path, saved, result):
    atomic_json(root / path, {"schema_version": 1, "identity_sha256": saved["identity_sha256"],
                             "epoch": saved["epoch"], "result": result})


def _request(row):
    record = row["record"]
    return {**deepcopy(record["request"]), "slot": row["seq"],
            "graph_root": f"rdj/graphs/{record['case_id']}/{row['seq']:04d}-{record['role']}"}


def _adopt(root, row):
    """Recover a roles append that committed before the case's usage save."""
    record, slot = row["record"], row["seq"]
    case, state, _ = rdj._load(root, record["case_id"])
    if any(c["slot"] == slot for c in state["calls"]):
        return
    role = record["role"]
    state["usage"]["model_calls"] += 1
    state["usage"]["by_role"][role] = state["usage"]["by_role"].get(role, 0) + 1
    if role == "edge_reviewer":
        for edge in record["request"]["payload"]["edges"]:
            key = edge["edge_id"]
            state["edge_reviews"][key] = state["edge_reviews"].get(key, 0) + 1
    state["calls"].append({"slot": slot, "role": role, "payload_sha256": record["payload_sha256"],
                           "status": "reserved", "utc": rdj._now(), "path": record["path"],
                           "graph_instance": record["graph_instance"], "request": _request(row)})
    rdj._commit(root, case, state, "role_reserved", {"slot": slot, "role": role,
                                                    "payload_sha256": record["payload_sha256"],
                                                    "path": record["path"]})


def _prepared(root, saved):
    rows = [r for r in custody.rows(root, "roles")
            if r["record"].get("prepare_call_id") == saved["call_id"]]
    return sorted((_request(r) for r in rows), key=lambda r: r["key"])


def _validate_reservation(root, saved, document):
    requests = _prepared(root, saved)
    if document["result"] != requests:
        raise ValueError("reservation downstream differs from custody")
    for request in requests:
        with rdj._lock(root, request["case_id"]):
            row = next(r for r in custody.rows(root, "roles") if r["seq"] == request["slot"])
            _adopt(root, row)
    return {"status": "completed", "result": requests}


def _validate_role(root, saved, document):
    request = document["request"]
    row = next(r for r in custody.rows(root, "roles") if r["seq"] == request["slot"])
    if _request(row) != request or row["record"]["path"] != saved["path"]:
        raise ValueError("role downstream does not belong to its reservation")
    if saved["identity"].get("payload_sha256") != request["payload_sha256"]:
        raise ValueError("role payload differs from effect identity")
    rdj._resolve(root, request, document["result"])
    return {"status": "completed", "result": document["result"]}


def _role_downstream(root, saved, request, ref):
    _write_downstream(root, _downstream_path(request), saved, ref)
    path = root / _downstream_path(request)
    document = read_json(path)
    atomic_json(path, {**document, "request": request})


def _recover(root):
    """Materialize only custody-backed downstream evidence; never dispatch here."""
    for saved in ledger.receipts(root):
        if saved["status"] not in ledger.OPEN or saved["graph"]["id"] not in (CASE, ROLE):
            continue
        if (saved.get("downstream") or {}).get("kind") == "rdj_reservation":
            requests = _prepared(root, saved)
            if requests:
                _write_downstream(root, saved["downstream"]["path"], saved, requests)
            continue
        if (saved.get("downstream") or {}).get("kind") != "rdj_role_receipt":
            continue
        rows = [r for r in custody.rows(root, "roles") if r["record"].get("path") == saved["path"]]
        if not rows:
            continue
        request = _request(rows[-1])
        refs = [{"kind": "worker_receipt", "path": r["record"]["path"]}
                for r in custody.rows(root, "workers")]
        refs += [{"kind": "agent_graph", "root": request["graph_root"], "node_id": "rdj"}]
        for ref in refs:
            try:
                rdj._resolve(root, request, ref)
            except (OSError, ValueError, KeyError, TypeError):
                continue
            _role_downstream(root, saved, request, ref)
            break


def _reserve(state, identity):
    root, instance = _root(state), state["meta"]["instance"]
    case_id, turn = instance["case_id"], state.get("turn", 0)
    prepare = ledger.latest(root, nodes.invocation(state["meta"], {"stage": "reserve", "turn": turn}))
    if turn >= _options(state)["max_steps"]:
        _write_downstream(root, _prepare_path(prepare["call_id"]), prepare, [])
        return []
    with rdj._lock(root, case_id):
        # Re-entry after partial saving adopts the original slots before considering budgets.
        previous = _prepared(root, prepare)
        if previous:
            for request in previous:
                row = next(r for r in custody.rows(root, "roles") if r["seq"] == request["slot"])
                _adopt(root, row)
            return previous
        case, domain, _ = rdj._load(root, case_id)
        changed = rdj._refresh(root, case, domain)
        roles = rdj._pending_roles(case, domain, rdj._challenges(case, domain))
        if not roles:
            if changed:
                rdj._commit(root, case, domain, "refreshed")
            _write_downstream(root, _prepare_path(prepare["call_id"]), prepare, [])
            return []
        role = roles[0]
        full = rdj._payload(role, case, domain)
        payloads = [full]
        if role == "edge_reviewer":
            edges = sorted(full["edges"], key=lambda e: e["edge_id"])
            size = _options(state)["edge_batch_size"]
            payloads = [{**full, "edges": edges[i:i + size]} for i in range(0, len(edges), size)]
        payloads.sort(key=dc.jdigest)
        for payload in payloads:
            case, domain, _ = rdj._load(root, case_id)
            rdj._refresh(root, case, domain)
            reason = rdj._budget_reason(root, case, domain, role, payload)
            if reason:
                domain["budget_exhausted"], domain["budget_reason"] = True, reason
                rdj._commit(root, case, domain, "budget_exhausted", {"reason": reason})
                break
            payload_sha = dc.jdigest(payload)
            key = f"{turn:04d}-{payload_sha}"
            parent = nodes.invocation(state["meta"], {"map": "roles", "item": key})
            path = ledger.path(ROLE, instance, parent, {"role": role, "payload": payload_sha})
            request = {"case_id": case_id, "role": role, "agent_role": rdj.AGENT_ROLES[role],
                       "payload": payload, "payload_sha256": payload_sha, "key": key, "path": path,
                       "before": dc.jdigest(case), "edge_digests": {e["edge_id"]: dc.merkle(case)["edges"][e["edge_id"]]
                                                                   for e in payload.get("edges", [])},
                       "campaign": _options(state)["campaign"]}
            digest = case["decision_point"]["action"]["digest"]
            card = role_registry.load(request["agent_role"])
            request["effect_identity"] = {
                "payload_sha256": payload_sha, "case_id": case_id,
                "card": {"id": card["id"], "version": card["version"],
                         "card_sha256": role_registry.card_sha256(card["id"])},
                "instruction_sha256": dc.jdigest({"instructions": payload["instructions"],
                                                  "output_schema": payload["output_schema"]}),
                "budgets": deepcopy(getattr((ACTIVE.get() or {}).get("dispatcher"), "budget", card["stop"])),
                "rdj_challenge_set_sha256": dc.jdigest(rdj._challenges(case, domain)),
                "action_digest": digest,
            }
            try:
                row = custody.append(root, "roles", {"case_id": case_id, "role": role,
                     "payload_sha256": payload_sha, "gate": case["decision_point"]["gate"], "action_digest": digest,
                     "path": path, "graph_instance": instance, "prepare_call_id": prepare["call_id"], "request": request},
                     check=lambda rows: rdj._run_budget(rows, digest))
            except custody.CustodyError as exc:
                domain["budget_exhausted"], domain["budget_reason"] = True, str(exc)
                rdj._commit(root, case, domain, "budget_exhausted", {"reason": str(exc)})
                break
            # Downstream is durable before the case save: either side of that save recovers.
            _write_downstream(root, _prepare_path(prepare["call_id"]), prepare, _prepared(root, prepare))
            _adopt(root, row)
        result = _prepared(root, prepare)
        _write_downstream(root, _prepare_path(prepare["call_id"]), prepare, result)
        return result


def _record(state, identity):
    root = _root(state)
    for request in sorted(state["requests"], key=lambda r: r["key"]):
        result = state["results"][request["key"]]
        if result["outcome"] != "ok":
            return {"failed": True, "status": result["status"]}
        ref = result["results"]["reference"]
        with rdj._lock(root, request["case_id"]):
            case, domain, _ = rdj._load(root, request["case_id"])
            call = next(c for c in domain["calls"] if c["slot"] == request["slot"])
            if call["status"] in ("completed", "stale", "rejected"):
                continue
            rdj._refresh(root, case, domain)
            work_case, work_state = deepcopy(case), deepcopy(domain)
            try:
                output, session, family = rdj._resolve(root, request, ref)
                current = dc.merkle(case)["edges"]
                stale = (any(current.get(e) != sha for e, sha in request["edge_digests"].items())
                         if request["role"] == "edge_reviewer" else dc.jdigest(case) != request["before"])
                if stale:
                    rdj._finish_call(root, request["case_id"], request["slot"], "stale", case=case, state=domain)
                    continue
                families = {c["session"]["session_receipt"]: c.get("family") for c in domain["calls"] if c.get("session")}
                if request["role"] == "edge_reviewer":
                    rdj._record_edge_reviews(root, work_case, work_state, output, session, list(request["edge_digests"]))
                elif request["role"] == "critic":
                    rdj._record_critique(root, work_case, work_state, output, session)
                else:
                    rdj._record_verification(root, work_case, work_state, output, session, family, families)
                dc.validate_case_v2(work_case)
            except (ValueError, KeyError, TypeError) as exc:
                rdj._finish_call(root, request["case_id"], request["slot"], "rejected", str(exc)[:300],
                                 case=case, state=domain)
                ACTIVE.get()["errors"].append(exc)
                raise
            rdj._finish_call(root, request["case_id"], request["slot"], "completed", case=work_case, state=work_state,
                             extra={"session": session, "family": family, "output_sha256": dc.jdigest(output)})
    return {"failed": False}


def _dispatch(state, identity):
    root, request = _root(state), state["request"]
    with rdj._lock(root, request["case_id"]):
        rdj._load(root, request["case_id"])
        row = next(r for r in custody.rows(root, "roles") if r["seq"] == request["slot"])
        if _request(row) != request:
            raise ledger.NotDispatched("role request differs from its custody reservation")
    dispatcher = (ACTIVE.get() or {}).get("dispatcher")
    if dispatcher is None:
        raise ledger.NotDispatched("RDJ dispatcher required; use ravel rdj run with --host-config")
    try:
        ref = dispatcher.dispatch(root, request)
    except Exception as exc:
        with rdj._lock(root, request["case_id"]):
            rdj._finish_call(root, request["case_id"], request["slot"], "failed", f"{type(exc).__name__}: {exc}"[:300])
        ACTIVE.get()["errors"].append(exc)
        raise
    saved = ledger.latest(root, request["path"])
    _role_downstream(root, saved, request, ref)
    return ref


def _present_run(root, identifier):
    from .. import run_ceilings
    return any(row.get("call_id") == identifier for row in run_ceilings._ledger(root))


def _charge_run_unchecked(root, identifier, amount):
    """Small idempotent adapter over the decision gate's existing invocation ledger format."""
    from .. import run_ceilings
    with file_lock(Path(root) / "agent-work/ledger.lock"):
        rows, record = run_ceilings._ledger(root), run_ceilings.resolve(root)
        if any(row.get("call_id") == identifier for row in rows):
            return
        if sum(r["n"] for r in rows) + amount > record["max_invocations"]:
            raise run_ceilings.CeilingExceeded("max_invocations exceeded; obtain a new CHECK-IN 1 ceiling")
        path = Path(root) / run_ceilings.LEDGER
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"sequence": len(rows) + 1, "kind": "rdj", "n": amount, "ns": time.time_ns(),
                                     "ceilings": record, "call_id": identifier}, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


def _charge_run(root, identifier, amount):
    try:
        return _charge_run_unchecked(root, identifier, amount)
    except Exception as exc:
        if ACTIVE.get() is not None:
            ACTIVE.get()["errors"].append(exc)
        raise


def _present_campaign(root, identifier):
    # The amount is held in the write-ahead effect receipt, including the campaign.
    from .. import research_cycle
    saved = ledger.read(root, identifier)
    amount = next(c["amount"] for c in saved["charges"] if c["ledger"] == "campaign")
    _, state = research_cycle._load(Path(amount["root"]))
    return any(r["id"] == "operation:rdj:" + identifier for r in state["resource_ledger"])


def _charge_campaign(root, identifier, amount):
    from .. import research_cycle
    research_cycle.reserve_operation(Path(amount["root"]), "operation:rdj:" + identifier, amount["amount"],
                                     {"rdj_effect_call_id": identifier, "rundir": str(Path(root).resolve())})


def _charges(state):
    result = [{"ledger": "run_ceilings", "amount": 1}]
    if state["request"].get("campaign"):
        result.append({"ledger": "campaign", "amount": state["request"]["campaign"]})
    return result


def role(ctx):
    from langgraph.graph import StateGraph, START, END
    builder = _standard(StateGraph(RoleState, input_schema=RoleView), ROLE)
    for name, agent_role in rdj.AGENT_ROLES.items():
        node = nodes.effect(name, kind="model", run=_dispatch,
              segment=lambda s: {"role": s["request"]["role"], "payload": s["request"]["payload_sha256"]},
              identity=lambda s: {**s["request"]["effect_identity"], "slot": s["request"]["slot"]},
              provisioning=lambda s: {"requested_model": getattr(
                  (ACTIVE.get() or {}).get("dispatcher"), "model", None),
                  "reasoning_effort": getattr((ACTIVE.get() or {}).get("dispatcher"), "reasoning_effort", None)},
              to_state=lambda s, ref: {"results": {"reference": ref}}, charges=_charges,
              downstream=lambda s: {"kind": "rdj_role_receipt", "path": _downstream_path(s["request"])})
        node.kind, node.role = "agent", agent_role
        nodes.add(builder, name, node, graph_id=ROLE)
        builder.add_edge(name, END)
    nodes.connect(builder, START, nodes.route(lambda s: s["request"]["role"], {r: r for r in rdj.AGENT_ROLES}))
    return builder


def _inspect(state):
    root, case_id = _root(state), state["meta"]["instance"]["case_id"]
    with rdj._lock(root, case_id):
        case, domain, _ = rdj._load(root, case_id)
        if rdj._refresh(root, case, domain):
            rdj._commit(root, case, domain, "refreshed")
        challenges = rdj._challenges(case, domain)
        branch = "roles" if state["requests"] else "end"
        if not state["requests"] and _options(state)["authorize"]:
            branch = ("proposer" if challenges and _options(state)["interactive"]
                      and not domain["budget_exhausted"] else "authorize")
        if state.get("turn", 0) >= _options(state)["max_steps"]:
            branch = "end"
        return {"branch": branch, "case_sha256": dc.jdigest(case), "challenges": challenges}


def _answer(state, identity):
    response = list(state.get("responses", {}).values())[-1]["value"]
    root, case_id = _root(state), state["meta"]["instance"]["case_id"]
    if response["case_sha256"] != state["case_sha256"]:
        raise ValueError("proposer answers belong to a stale case")
    # The content check and mutation share answer's case lock; no approval is accepted here.
    return rdj.answer(root, case_id, response["answers"], expected_case_sha256=response["case_sha256"])


def _authorize(state, identity):
    try:
        return rdj.authorize(_root(state), state["meta"]["instance"]["case_id"])
    except Exception as exc:
        if ACTIVE.get() is not None:
            ACTIVE.get()["errors"].append(exc)
        raise


def case(ctx):
    from langgraph.graph import StateGraph, START, END
    builder = _standard(StateGraph(State), CASE)
    reserve = nodes.effect("reserve", kind="check", run=_reserve,
        segment=lambda s: {"stage": "reserve", "turn": s.get("turn", 0)},
        identity=lambda s: {"case_id": s["meta"]["instance"]["case_id"], "turn": s.get("turn", 0)},
        implementation=(__name__, "ravel.workflow.rdj_loop"), to_state=lambda s, r: {"requests": r},
        downstream=lambda s: {"kind": "rdj_reservation", "path": _prepare_path(ledger.call_id(
            ledger.scope_id(_root(s)), nodes.invocation(s["meta"], {"stage": "reserve", "turn": s.get("turn", 0)}), 1))})
    nodes.add(builder, "reserve", reserve, graph_id=CASE)
    # This code-only routing projection is freshly derived from custody at each entry.
    nodes.add(builder, "inspect", nodes.Node("guard", _inspect), graph_id=CASE)
    child = substrate.build(ROLE, substrate.BuildContext(ctx.scope_root, ROLE, 1, ctx.instance))
    edge, mapped = nodes.map_node(lambda s: s["requests"], lambda r: r["key"], child,
                                  lambda s, r: {"request": r}, name="roles")
    nodes.add(builder, "roles", mapped, graph_id=CASE)
    nodes.add(builder, "fanout", nodes.Node("guard", lambda s: {}), graph_id=CASE)
    nodes.connect(builder, "fanout", edge)
    nodes.add(builder, "record", nodes.effect("record", kind="check", run=_record,
        segment=lambda s: {"stage": "record", "turn": s.get("turn", 0)},
        identity=lambda s: {"requests_sha256": dc.jdigest(s["requests"]),
                             "results_sha256": dc.jdigest({r["key"]: s["results"][r["key"]] for r in s["requests"]})},
        implementation=(__name__, "ravel.workflow.rdj_loop"),
        to_state=lambda s, r: {"turn": s.get("turn", 0) + 1, "branch": "end" if r["failed"] else "again",
                               **({"status": r["status"]} if r["failed"] else {})}), graph_id=CASE)
    nodes.add(builder, "proposer", nodes.interrupt("proposer_answers",
        lambda s: {"case_id": s["meta"]["instance"]["case_id"], "case_sha256": s["case_sha256"],
                   "challenges": s["challenges"]}, schema_id="rdj_proposer_answers", segment=lambda s: {"proposer": s["case_sha256"]}), graph_id=CASE)
    nodes.add(builder, "answer", nodes.effect("answer", kind="check", run=_answer,
        segment=lambda s: {"answer": s["case_sha256"]}, identity=lambda s: {"case_sha256": s["case_sha256"],
                      "responses_sha256": dc.jdigest(s.get("responses", {}))},
        implementation=(__name__, "ravel.workflow.rdj_loop"),
        to_state=lambda s, r: {"turn": s.get("turn", 0) + 1}), graph_id=CASE)
    nodes.add(builder, "authorize", nodes.effect("authorize", kind="check", run=_authorize,
        segment=lambda s: {"authorize": s["case_sha256"]}, identity=lambda s: {"case_sha256": s["case_sha256"]},
        implementation=("ravel.workflow.rdj_loop",), to_state=lambda s, r: {"receipt": r,
                    "results": {"rdj_receipt": r}}), graph_id=CASE)
    nodes.add(builder, "escalate", nodes.hold("rdj_escalated", "record a user decision before reopening"),
              graph_id=CASE)
    builder.add_edge(START, "reserve")
    builder.add_edge("reserve", "inspect")
    nodes.connect(builder, "inspect", nodes.route(lambda s: s["branch"],
                   {"roles": "fanout", "end": END, "proposer": "proposer", "authorize": "authorize"}))
    builder.add_edge("roles", "record")
    nodes.connect(builder, "record", nodes.route(lambda s: s["branch"], {"again": "reserve", "end": END}))
    builder.add_edge("proposer", "answer")
    builder.add_edge("answer", "reserve")
    nodes.connect(builder, "authorize", nodes.route(lambda s: s["receipt"]["outcome"],
                  {"authorize": END, "gather_evidence": END, "escalate": "escalate"}))
    return builder


def _instance(root, case_id, mode):
    case_value, state, lines = rdj._load(root, case_id)
    for call in reversed(state["calls"]):
        if call.get("graph_instance") and (call["status"] == "reserved" or (
                (ledger.latest(root, call.get("path", "")) or {}).get("status") in ledger.OPEN)):
            return call["graph_instance"]
    # A crash after the custody append but before the case save retains the original instance too.
    known = {c["slot"] for c in state["calls"]}
    for row in reversed(custody.rows(root, "roles")):
        inst = row["record"].get("graph_instance", {})
        if row["record"]["case_id"] == case_id and row["seq"] not in known and inst:
            return inst
    if mode == "full":
        for path in sorted((root / substrate.THREADS).glob("*.json")):
            saved = read_json(path)
            if saved.get("graph_id") == CASE and saved.get("instance", {}).get("case_id") == case_id \
                    and saved["instance"].get("mode") == mode and saved.get("state") in ("interrupted", "paused", "running"):
                return saved["instance"]
    return {"case_id": case_id, "cycle": lines[-1]["digest"], "mode": mode}


def run(rundir, case_id, dispatcher=None, *, max_steps=32, edge_batch_size=64, workers=1,
        authorize=False, interactive=False, respond=None, campaign=None, campaign_charge=None):
    """Run/resume an existing case; return RDJ status plus the non-authoritative graph observation.

    Campaign callers supply their original campaign and explicit per-call resource
    vector. Standalone run-scoped cases charge custody and run ceilings. This seam
    is consumed by the review points and gate wiring; no campaign is created or budget guessed here.
    """
    if type(max_steps) is not int or max_steps < 1 or type(edge_batch_size) is not int or edge_batch_size < 1:
        raise ValueError("positive step and edge batch bounds required")
    if campaign is not None and campaign_charge is None:
        raise ValueError("campaign RDJ calls require an explicit per-call resource vector")
    campaign_value = None
    if campaign is not None:
        from .. import research_cycle
        campaign_value = {"root": str(Path(campaign).resolve()), "amount": research_cycle._vector(campaign_charge)}
        if campaign_value["amount"]["calls"] < 1:
            raise ValueError("campaign charge must reserve at least one model call")
    root = Path(rundir).resolve()
    if type(workers) is not int or not 1 <= workers <= 16:
        raise ValueError("workers must be an integer in [1, 16]")
    from .. import run_ceilings
    workers = min(workers, run_ceilings.resolve(root)["max_concurrent_workers"])
    mode = "full" if authorize else "roles"
    with rdj._lock(root, case_id):
        instance = _instance(root, case_id, mode)
    with dispatch_context(dispatcher) as context:
        _recover(root)
        observation = substrate.run(root, CASE, instance, input={"turn": 0, "options": {
            "max_steps": max_steps, "edge_batch_size": edge_batch_size, "authorize": authorize,
            "interactive": interactive, "campaign": campaign_value}}, respond=respond,
            workers=workers, max_steps=max_steps * 8 + 20)
        if context["errors"]:
            raise context["errors"][0]
        return {**rdj.status(root, case_id), "graph": observation}
