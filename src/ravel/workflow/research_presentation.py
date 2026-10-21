"""Bounded protocol material over complete ordinary native evidence custody.

No dispatch, acceptance, new journal or cross-call cache lives here. An inventory
commitment proves custody; only separately presented material/pages are content.
"""
from copy import deepcopy
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path

from . import candidate_experiments as ce, review_context, state_io

MAX_INVENTORY_BYTES = 16 * 1024**2
MAX_FILES = 20_000
MAX_PAGES = 32


def _cycle():
    from . import research_cycle
    return research_cycle


def raw_json(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2,
                       allow_nan=False) + "\n").encode()


def document(pin, base, maximum):
    cycle = _cycle()
    ce.keys(pin, ("path", "sha256", "size")); ce.sha(pin["sha256"])
    if type(pin["size"]) is not int or not 0 <= pin["size"] <= maximum:
        raise ValueError("typed retained document exceeds its existing evidence bound")
    path = Path(pin["path"])
    path, raw = cycle._bounded_source_snapshot(path if path.is_absolute() else Path(base)/path, maximum)
    if len(raw) != pin["size"] or hashlib.sha256(raw).hexdigest() != pin["sha256"]:
        raise ValueError("typed retained document changed")
    return review_context._strict_json_bytes(raw)


def _inventory(root, session):
    """Expand the whole scientific closure; no inventory row is read credit."""
    from . import research_protocol as protocol, failed_stage_review
    cycle = _cycle(); _, state = cycle._load(root); base = state["base_dir"]
    rows, missing, failed_documents = {}, [], {}

    def add(pin, origin):
        ce.sha(pin["sha256"])
        path = Path(pin["path"]); path = cycle._ordinary(path if path.is_absolute() else Path(base)/path)
        if not path.is_file(): raise ValueError("committed protocol evidence file absent")
        before = path.stat()
        size = pin.get("size", before.st_size)
        if type(size) is not int or size < 0 or before.st_size != size:
            raise ValueError("protocol inventory evidence size changed")
        session.require_regular(path)
        actual={'path':str(path),'sha256':session.hash_file(path),'size':before.st_size}
        if actual["sha256"] != pin["sha256"] or actual["size"] != size:
            raise ValueError("protocol inventory evidence changed")
        old = rows.get(str(path))
        if old is not None and old["pin"] != actual:
            raise ValueError("conflicting protocol inventory commitments")
        if old is None:
            if len(rows) >= MAX_FILES: raise ValueError("complete evidence index exceeds existing declared population")
            rows[str(path)] = {"pin": actual, "origins": []}
        if origin not in rows[str(path)]["origins"]: rows[str(path)]["origins"].append(origin)

    def snapshot(value, origin):
        if not value:return
        # Reuse the ordinary one-call reader/census, without changing output
        # admission or claiming failed bytes are successful scientific outputs.
        if session.snapshot(list(value)) != value:
            raise ValueError('complete retained snapshot membership/content changed')
        for path, entry in value.items():
            for row in entry["files"]:
                add({"path": str(Path(path) if row["name"] == "." else Path(path)/row["name"]),
                     "sha256": row["sha256"], "size": row["size"]}, origin)

    from . import agent_host, agent_graph, research_progress
    for module in (cycle, protocol, review_context, agent_host, agent_graph, research_progress,
                   __import__(__name__,fromlist=['_'])):
        add(cycle._pin(Path(module.__file__)), 'current_presentation_source')
    add(state["contract"]["context_request"], "question")
    for pin in state["context"]["source_inventory"]: add(pin, "scientific_context")
    for pin in (state.get("parent_task") or {}).get("input_pins", []): add(pin, "original_parent")
    for row in state["premises"]:
        for pin in row["basis"]: add(pin, "premise:"+row["id"])
    for row in state["hypotheses"]:
        for pin in row["source_basis"]: add(pin, "hypothesis:"+row["id"])
    bound = protocol._bound(state)
    if bound is not None:
        for pin in [bound[1]["protocol"], *protocol._all_pins(bound[0])]: add(pin, "protocol")
    for e in state["experiments"]:
        identity = e["id"]
        if e.get("observation") is not None:
            # The original scientific/runtime/source/ledger/parent gates remain
            # authoritative. Historical interpretations are labelled by core.
            cycle._current_evidence(state, e)
        for pin in e["input_pins"]: add(pin, identity+":input")
        for key in ("study", "plan", "failed_intake", "diagnostic_feedback"):
            if e.get(key) is not None: add(e[key], identity+":"+key)
        observation = e.get("observation")
        if observation is not None:
            add(observation["receipt"], identity+":receipt")
            record = document(observation["receipt"], base, 64*1024**2)
            for key in ("input_snapshot", "output_snapshot"):
                if key in record: snapshot(record[key], identity+":"+key)
            if observation.get("result") is not None: add(observation["result"], identity+":result")
        if e.get("adjudication") is not None: add(e["adjudication"]["snapshot"], identity+":review")
        if cycle._failed_parent(e):
            value = cycle._read_failed_intake(e["failed_intake"], base)
            # _current_evidence above already verifies this exact canonical pin.
            failed_documents[identity] = value
            for name in value['missing_output_roots']:
                session.require_inventory(name)
            snapshot(value["source_inputs"], identity+":failed_source")
            snapshot(value["returned_outputs"], identity+":failed_returned")
            for pin in [value["record"], value["execution_ledger"], *value["launch_observation"]["pins"], *value["evidence"]]:
                add(pin, identity+":failed_proof")
            missing.extend({"experiment_id": identity, **deepcopy(row)} for row in value["returned_output_obligations"])
    files = [{"id": f"source{i:06d}", **rows[path]} for i, path in enumerate(sorted(rows))]
    value = {"schema_version": 1, "kind": "complete_protocol_evidence_inventory", "files": files,
             "file_count": len(files), "total_source_bytes": sum(r["pin"]["size"] for r in files),
             "missing_output_obligations": missing, "content_read_by_reviewer": False}
    if len(raw_json(value)) > MAX_INVENTORY_BYTES: raise ValueError("complete custody inventory exceeds existing retained manifest bound")
    if cycle._load(root)[1]["sha256"] != state["sha256"]:
        raise ValueError("research state changed during evidence inventory")
    session.track(state);session.track(value);session.track(failed_documents)
    return state, value, failed_documents


@contextmanager
def _inventory_session(root):
    """One atomic read operation; complete ending census, no cross-call cache."""
    cycle=_cycle();state=cycle._load(root)[1]
    session=cycle.science.execution._validation_session(state['base_dir'])
    try:
        value=_inventory(root,session)
        yield value
        if cycle._load(root)[1]['sha256']!=value[0]['sha256']:
            raise ValueError('research state changed during whole indexed operation')
        errors=session.finish()
        if errors:raise ValueError('; '.join(errors))
    finally:session.close()


def inventory(root):
    """Standalone fresh whole custody census; never scientific content credit."""
    with _inventory_session(root) as value:
        return (*value,None)


def core(root, inventory_value, failed_documents, state):
    from . import research_protocol as protocol
    cycle = _cycle(); feedback = []
    for e in state["experiments"]:
        row = {"experiment_id": e["id"], "current_applicability": cycle._applicability(state, e),
               "observation": deepcopy(e.get("observation")), "adjudication": deepcopy(e.get("adjudication")),
               "diagnostic_feedback": deepcopy(e.get("diagnostic_feedback")), "actual_role_content": []}
        if e.get('observation') is not None and e['observation'].get('result') is not None:
            result_pin=e['observation']['result']
            # Preserve complete typed JSON result material. Large/binary native
            # payloads are not silently parsed or inferred from their hashes.
            try:
                row['returned_typed_result']=document(result_pin,state['base_dir'],64*1024**2)
            except (UnicodeError, __import__('json').JSONDecodeError):
                row['returned_typed_result']={'deferred_source':deepcopy(result_pin),
                    'content_read_by_reviewer':False,'reason':'binary/native result requires explicit selected page and applicability review'}
        if e.get("adjudication") is not None:
            saved = document(e["adjudication"]["snapshot"], state["base_dir"], 64*1024**2)
            # Opening/custody inventories stay in the complete external source.
            # Every actual scientific review, objection and correction retains
            # its full text. No favourable verdict or excerpt selection here.
            row["actual_role_content"] = [deepcopy(x) for x in saved.get("events", [])
                if x.get("event") not in {"registered", "open"}]
        if e.get("diagnostic_feedback") is not None:
            saved = document(e["diagnostic_feedback"], state["base_dir"], MAX_INVENTORY_BYTES)
            row["actual_role_content"].append(saved)
        if e["id"] in failed_documents:
            value = failed_documents[e["id"]]
            row["failed_material"] = {key: deepcopy(value[key]) for key in (
                "failure_kind", "stage_status", "exit_code", "execution_error", "result", "result_status",
                "returned_output_obligations", "limitations")}
            # Exact law/source/assumptions, not only a census digest.
            specpath = str(Path(value["run_dir"])/cycle.science.SPEC)
            fact = value["source_inputs"].get(specpath)
            if fact is not None and fact.get("kind") == "file":
                member = fact["files"][0]
                source = {"path": specpath, "sha256": member["sha256"], "size": member["size"]}
                spec = document(source, state["base_dir"], ce.MAX_BYTES)
                row["failed_material"]["original_scientific_specification"] = {"source": source, "content": spec}
        feedback.append(row)
    raw = raw_json(inventory_value)
    value = {"kind": "indexed_staged_protocol_review_context", "presentation_version": 1,
        "state_sha256": state["sha256"], "question": state["contract"]["question"], "scope": state["contract"]["scope"],
        "protocol_status": protocol.context_status(state), "actual_feedback": feedback,
        "current_goal": deepcopy(state.get("parent_task")), "resource_ledger": deepcopy(state["resource_ledger"]),
        "timing": deepcopy(state["timing"]), "hypotheses": deepcopy(state["hypotheses"]), "premises": deepcopy(state["premises"]),
        "protocol": None if protocol._bound(state) is None else deepcopy(protocol._bound(state)[0]),
        "requested_quantities": deepcopy(state["context"]["requested_quantities"]),
        "measured_quantities": deepcopy(state["context"]["measured_quantities"]),
        "required_experiments": deepcopy(state["contract"]["required_experiments"]),
        "inventory_commitment": {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw),
            "file_count": inventory_value["file_count"], "total_source_bytes": inventory_value["total_source_bytes"],
            "missing_output_obligations": deepcopy(inventory_value["missing_output_obligations"])},
        "actions": ["report_only", "additional_evidence", "candidate_revision", "premise_revision", "resolve_objections"],
        "access": {"inventory_artifact": "inventory", "source_ids": "canonical path sorted sourceNNNNNN",
            "page_bytes_max": 65536, "max_pages": MAX_PAGES, "source_content_credit_from_inventory": False,
            "fresh_role_required_for_new_pages": True},
        "instructions": "All typed scientific material and objections are retained. Inventory custody is not reading. Cite only actually presented core/pages. Deferred sources are unknown to this response. No invalid incumbent restoration or scientific vote authority."}
    if len(raw_json(value)) > ce.MAX_BYTES:
        raise ValueError("complete mandatory scientific core exceeds finite presentation; narrower explicit review required")
    return value


def pages(inventory_value, selections, role, base):
    if selections is None: selections = []
    if type(selections) is not list or len(selections) > MAX_PAGES:
        raise ValueError("at most 32 explicit source page selections required")
    index = {r["id"]: r for r in inventory_value["files"]}; seen = set(); out = []
    inventory_sha = hashlib.sha256(raw_json(inventory_value)).hexdigest()
    cycle = _cycle()
    for i, selected in enumerate(selections):
        ce.keys(selected, ("artifact_id", "offset", "max_bytes"))
        identity = selected["artifact_id"]
        if type(identity) is not str or identity not in index:
            raise ValueError("source page must belong to exact complete inventory")
        key = (identity, selected["offset"], selected["max_bytes"])
        if key in seen: raise ValueError("duplicate source page selection")
        seen.add(key); pin = index[identity]["pin"]
        if pin["size"] > 64*1024**2: raise ValueError("selected source exceeds existing role artifact bound; supply a bounded witness")
        path, raw = cycle._bounded_source_snapshot(Path(pin["path"]), 64*1024**2)
        if len(raw) != pin["size"] or hashlib.sha256(raw).hexdigest() != pin["sha256"]:
            raise ValueError("selected complete source changed")
        from .failed_stage_review import _project_diagnostic_bytes
        projected, projection = _project_diagnostic_bytes(raw, role, str(path))
        payload = review_context._artifact_page(projected, identity, offset=selected["offset"], max_bytes=selected["max_bytes"])
        payload.update(inventory_sha256=inventory_sha, source=deepcopy(pin), projection=projection,
                       original_source_reading_credit=False)
        out.append({"id": f"page{i:04d}", "selection": deepcopy(selected), "payload": payload})
    return out


def prepared(root, *, evidence_pages=None, role="critic", max_presented_bytes=ce.MAX_BYTES):
    if role not in {"critic", "verifier"}: raise ValueError("separate protocol meta role required")
    if type(max_presented_bytes) is not int or not 1 <= max_presented_bytes <= ce.MAX_BYTES:
        raise ValueError("finite unchanged maximum scientific presentation required")
    with _inventory_session(root) as value_from_session:
        state,inv,failures=value_from_session; value=core(root,inv,failures,state)
        selected = pages(inv, evidence_pages, role, state["base_dir"])
        value["selected_evidence_pages"] = [deepcopy(row["payload"]) for row in selected]
        value["presentation_options"] = {"evidence_pages": deepcopy(evidence_pages or []),
                                         "role": role, "max_presented_bytes": max_presented_bytes}
        core_raw = raw_json(value)
        # Account serialized actual artifact wrappers; actual Host may be smaller,
        # so application also insists on its observed presentation receipt.
        cost = len(raw_json({"id": "public_case", "content": core_raw.decode("utf-8")}))
        cost += sum(len(raw_json({"id": r["id"], "content": raw_json(r["payload"]).decode("utf-8")})) for r in selected)
        if cost > max_presented_bytes: raise ValueError("mandatory core/pages exceed declared serialized presentation budget")
        if _cycle()._load(root)[1]["sha256"] != state["sha256"]:
            raise ValueError("research changed while preparing selected material")
        return state, inv, value, selected
    

def write_new(path, raw):
    """Commit intended serialization, never adopt its first filesystem reread."""
    cycle = _cycle(); path = cycle._ordinary(path)
    if type(raw) is not bytes or len(raw) > 64*1024**2:
        raise ValueError("bounded exact generated bytes required")
    expected = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
    with path.open("xb") as stream: stream.write(raw)
    cycle._check_pin(expected, path.parent)
    return expected


def write_json_new(path, value):
    # Preserve the existing atomic_json serialization for small/default callers.
    # All callers here already own a fresh preparation destination.
    return write_new(path, (json.dumps(value, indent=2, allow_nan=False)+"\n").encode())


def packet(root, output_dir, *, role, evidence_pages=None, max_presented_bytes=ce.MAX_BYTES):
    state, inv, value, selected = prepared(root, evidence_pages=evidence_pages, role=role,
                                          max_presented_bytes=max_presented_bytes)
    cycle = _cycle(); out = cycle._ordinary(output_dir); out.mkdir(exist_ok=False)
    context = out/"context"; (context/"artifacts").mkdir(parents=True)
    contents = [("public_case", raw_json(value), "inline", "complete mandatory scientific core"),
                ("inventory", raw_json(inv), "on_demand", "complete evidence custody inventory; no content credit")]
    contents += [(r["id"], raw_json(r["payload"]), "inline", "exact selected projected source byte page") for r in selected]
    manifest = {"schema_version": 1, "role": role, "cycle_id": "protocol:"+value["protocol"]["id"],
        "source_event_sha256": state["sha256"], "findings": [], "reviews": [], "allowed_claim_scopes": {},
        "required_checks": [], "omissions": [], "correction": None, "artifacts": [],
        "verification_scope": "Bounded meta material; complete custody retained, deferred bytes not read, no current peer response or vote.",
        "access_limitation": review_context.LIMITATION}
    pins = {}
    for identity, raw, presentation, projection in contents:
        relative = "artifacts/"+identity+".json"
        pin = write_new(context/relative, raw); pins[identity] = pin
        manifest["artifacts"].append({"id": identity, "path": relative, "sha256": pin["sha256"], "size": pin["size"],
            "source_sha256": pin["sha256"], "source_path": pin["path"], "projection": projection, "presentation": presentation})
    manifest["sha256"] = ce.digest(manifest)
    manifest_pin = write_new(context/"manifest.json", raw_json(manifest))
    fresh = prepared(root, evidence_pages=evidence_pages, role=role, max_presented_bytes=max_presented_bytes)
    if fresh[1:] != (inv, value, selected): raise ValueError("current full evidence/material changed during packet preparation")
    for p in [*pins.values(), manifest_pin]: cycle._check_pin(p, state["base_dir"])
    return state, value, pins, manifest, manifest_pin, selected


def validate_citations(value, subject, manifest, receipt, packet_root):
    """Transport presentation is required; semantics/independence are not proved."""
    cycle = _cycle(); entries = {e["id"]: e for e in manifest["artifacts"]}
    mandatory = {"public_case", *[f"page{i:04d}" for i in range(len(subject["selected_evidence_pages"]))]}
    if any(entries[i]["sha256"] not in receipt["presented_subject_sha256s"] for i in mandatory):
        raise ValueError("mandatory actual core/page presentation missing from role receipt")
    citations = value["evidence_citations"]
    if type(citations) is not list or not 1 <= len(citations) <= 33:
        raise ValueError("located actually presented core/page citations required")
    seen = set()
    for citation in citations:
        ce.keys(citation, ("artifact_id", "sha256", "location"))
        identity = citation["artifact_id"]
        if type(identity) is not str or identity not in mandatory or identity in seen or citation["sha256"] != entries[identity]["sha256"]:
            raise ValueError("citation is deferred, unseen or changed scientific content")
        seen.add(identity); cycle._text(citation["location"])
        raw = review_context.read_artifact(packet_root, identity, expected_manifest_sha256=manifest["sha256"])
        if identity != "public_case":
            page = review_context._strict_json_bytes(raw)
            if page != subject["selected_evidence_pages"][int(identity[4:])]:
                raise ValueError("citation page differs from exact current selected interval")
    return {"inventory": deepcopy(subject["inventory_commitment"]), "presented_artifacts": sorted(mandatory),
        "citations": deepcopy(citations), "deferred_source_content_read": False,
        "scientific_reading_or_correctness_proven": False}
