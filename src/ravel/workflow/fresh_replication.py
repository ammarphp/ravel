"""Prepare complete fresh scientific checks through the existing study lifecycle.

Original execution custody is an operand, never a new verification. Preparation
does not dispatch, approve, vote, invent an oracle, or change the research head.
The same ordinary science/Graph/review services own later effects and acceptance.
"""
from copy import deepcopy
from contextlib import contextmanager
import inspect
from pathlib import Path

from . import candidate_experiments as ce, report_integrity as integrity
from . import research_cycle as cycle, science, execution
from ravel.physics import research_comparison as comparison

PURPOSES = {"faithful_reexecution", "independent_reference", "objection_test"}
MAX_CELLS = comparison.MAX_CELLS


class _ProducerSessions:
    """Existing producer sessions owned by exactly one pure comparison call."""
    def __init__(self):
        self.entries = {}
        self.active = False
        self.closed = False
        self.operational = None
        self._operational_original = None

    def __enter__(self):
        if self.active or self.closed:
            raise ValueError('producer validation owner cannot be reused')
        self.active = True
        return self

    def session_for(self, rundir):
        if not self.active:
            raise ValueError('producer validation owner is closed')
        rd = science.root(rundir)
        verifier = science.verify_plan
        entry = self.entries.get(rd)
        if entry is not None and entry['verifier'] is not verifier:
            raise ValueError('producer plan verifier changed during comparison')
        if entry is None:
            if getattr(self, '_readonly_frozen', False):
                raise ValueError('new producer participant after read-only ending freeze')
            # Preserve legacy/injected callables without silently giving their
            # different contract another callable's observational proof.
            try:
                signature = inspect.signature(verifier)
                if not {'_session', '_recheck'} <= set(signature.parameters):
                    return None
                signature.bind(rd, approved=True, _session=None, _recheck=True)
            except (TypeError, ValueError):
                return None
            if not science.review_enabled(rd):
                return None
            session = execution._validation_session(rd)
            entry = {'verifier': verifier, 'session': session, 'ledger_digest': None}
            # Register before any further read so failures still close it.
            self.entries[rd] = entry
            if session.ledger_existed:
                entry['ledger_digest'] = execution.digest(session.read_document(session.ledger))
        session = entry['session']
        execution._check_validation_session(rd, session)
        if session.ledger.exists() != session.ledger_existed:
            raise ValueError('execution ledger appeared or disappeared during comparison')
        if session.ledger_existed:
            # read_document observes the original file identity, reads actual
            # current bytes and tracks each returned mutable object. No ledger
            # document or authority label is served from the plan-proof cache.
            actual = session.read_document(session.ledger)
            if execution.digest(actual) != entry['ledger_digest']:
                raise ValueError('execution ledger changed during comparison')
        return session

    def readonly_sessions(self):
        if not self.active or self.closed:
            raise ValueError('live producer participant required')
        return tuple(entry['session'] for entry in self.entries.values())

    def readonly_check(self):
        if not self.active or self.closed:
            raise ValueError('live producer participant required')
        if self.operational is not self._operational_original:
            raise ValueError('operational participant binding changed')
        if getattr(self, '_readonly_frozen', False):
            if self.operational is not self._readonly_operational:
                raise ValueError('operational participant changed after freeze')
            if tuple((rd, id(entry), id(entry['session'])) for rd, entry in self.entries.items()) != self._readonly_entries:
                raise ValueError('producer participant roster changed after freeze')
        for entry in self.entries.values():
            if science.verify_plan is not entry['verifier']:
                raise ValueError('producer verifier changed during read-only calculation')

    def readonly_freeze(self):
        self.readonly_check()
        if getattr(self, '_readonly_frozen', False):
            raise ValueError('producer roster already frozen')
        self._readonly_frozen = True
        self._readonly_operational = self.operational
        self._readonly_entries = tuple((rd, id(entry), id(entry['session'])) for rd, entry in self.entries.items())

    def readonly_close(self):
        failures = []
        self.active = False
        self.closed = True
        for entry in self.entries.values():
            try:
                entry['session'].close()
            except BaseException as exc:
                failures.append(exc)
        self.entries.clear()
        if failures:
            failure = failures[0]
            for other in failures[1:]:
                failure.add_note('producer close failure: ' + str(other))
            raise failure

    def __exit__(self, kind, primary, traceback):
        failures = []
        try:
            if primary is None:
                for entry in self.entries.values():
                    try:
                        failures.extend(entry['session'].finish())
                    except BaseException as exc:
                        failures.append(exc)
        finally:
            # A failing finish/close must not strand any other producer.
            self.active = False
            self.closed = True
            for entry in self.entries.values():
                try:
                    entry['session'].close()
                except BaseException as exc:
                    failures.append(exc)
        if failures:
            if primary is not None:
                for failure in failures:
                    primary.add_note('producer validation cleanup failure: ' + str(failure))
            else:
                failure = next((v for v in failures if isinstance(v, BaseException)), None)
                if failure is not None:
                    for other in failures:
                        if other is not failure:
                            failure.add_note('producer validation cleanup failure: ' + str(other))
                    raise failure
                raise ValueError('; '.join(failures))
        return False


@contextmanager
def _producer_validation(scope=None):
    if scope is None:
        with _ProducerSessions() as owned:
            yield owned
    else:
        if type(scope) is not _ProducerSessions or not scope.active:
            raise ValueError('active same-call producer validation owner required')
        yield scope


def _producer_keywords(scope, e):
    if scope is None:
        return {}
    # The nonattached retained-failure branch never calls verify_plan.
    if cycle._failed_parent(e) and e.get('kind') != 'attached_failed_stage':
        return {}
    session = scope.session_for(e['rundir'])
    return {} if session is None else {'_session': session}


class _Consumed(integrity.CustodyInputs):
    """One operation's common explicit operational budget and observations."""
    def __init__(self, limits=None, *, _observation=None):
        super().__init__()
        self.observation = _observation
        self.limits=integrity.custody_limits(limits)
        self.budget=integrity.CustodyAccumulator(self.limits)


def _json(pin, base, consumed):
    return integrity._operational_json(pin,base,consumed,limits=consumed.limits,accumulator=consumed.budget, **integrity._anchored_keywords(consumed.observation))


def _dependency(pin,base,consumed):
    return integrity._dependency(pin,base,consumed,limits=consumed.limits,accumulator=consumed.budget, **integrity._anchored_keywords(consumed.observation))


def _pins(pins, base, consumed):
    for pin in pins:_dependency(pin,base,consumed)


def _ending(consumed):
    # Keep the original identity map and SAME accumulator at every ending read.
    # No late reread supplies an intended baseline or a cross-call cache.
    fields=lambda v:(v.st_dev,v.st_ino,v.st_mode,v.st_size,v.st_mtime_ns,v.st_ctime_ns)
    pins=list(consumed.values())
    before={p['path']:fields(integrity._ordinary(p['path']).stat()) for p in pins}
    for pin in pins:_dependency(pin,Path(pin['path']).parent,consumed)
    if any(fields(integrity._ordinary(p['path']).stat())!=before[p['path']] for p in pins):
        raise ValueError('operational dependency changed during complete ending observation')


def _emit(path,value,consumed):
    return integrity._operational_new(path,value,limits=consumed.limits,
        consumed=consumed,accumulator=consumed.budget)


def _envelope(pin,base):
    # Envelope I/O is bounded by the common maximum metadata capacity, not a
    # scientific content/presentation allowance. It supplies no authority:
    # reread under the declared policy and reconstruct the actual original
    # producer/check source before use. A default-policy large envelope refuses.
    cap={'max_files':1,'max_bytes':integrity.MAX_OPERATIONAL_METADATA_BYTES,
         'max_metadata_bytes':integrity.MAX_OPERATIONAL_METADATA_BYTES}
    return integrity._operational_json(pin,base,integrity.CustodyInputs(),limits=cap,
        accumulator=integrity.CustodyAccumulator(cap))


def _located(row, base, consumed, allowed=None):
    value = integrity._located(row, base, consumed)["value"]
    p = str(integrity._artifact_path(row["artifact"], base))
    if allowed is not None and consumed[p] not in allowed:
        raise ValueError("state/population/representation must descend actual original or prospective study custody")
    return deepcopy(value)


def _experiment(state, identity):
    rows = [e for e in state["experiments"] if e["id"] == identity]
    if len(rows) != 1:
        raise ValueError("exact ordinary research experiment required")
    return rows[0]


def _original(root, report_pin, method_id, base, consumed, state=None):
    if state is None: _, state = cycle._load(root)
    report = _json(report_pin, base, consumed)
    # Scientific content uses the original exact manuscript/text law. Complete
    # operational execution joins use the SAME existing helper with the source
    # declared capacity, separately from prose budgets. Every operation remains.
    content=deepcopy(report)
    for method in content['methods']:
        for op in method['operations']:op['execution']=None
    prepared=integrity.prepare(content,base_dir=base)
    for method in report['methods']:
        for op in method['operations']:
            code=[integrity._located(v,base,consumed) for v in op['code']]
            results=[integrity._located(v,base,consumed) for v in op['results']]
            integrity._executed(op['execution'],code,results,base,consumed,
                limits=consumed.limits,accumulator=consumed.budget, **integrity._anchored_keywords(consumed.observation))
            # Failed stages are retained operands too. The common success helper
            # intentionally does not certify their result, but their complete
            # retained input/partial-output census must still be authenticated.
            if op['execution'] is not None:
                record=_json(op['execution']['receipt'],base,consumed)
                for field in ('input_snapshot','output_snapshot'):
                    for name,snapshot in record.get(field,{}).items():
                        for leaf in snapshot['files']:
                            path=Path(name) if leaf['name']=='.' else Path(name)/leaf['name']
                            _dependency({'path':str(path),'sha256':leaf['sha256'],'size':leaf['size']},base,consumed)
    from . import scientific_report
    quantitative = report["quantitative_report"]
    if quantitative is None: raise ValueError("original method must bind its whole scientific quantity report")
    source = _json(quantitative["request"], base, consumed)
    context = scientific_report._context(source["context"], integrity._artifact_path(quantitative["request"], base).parent)
    if context != state["context"]: raise ValueError("original report must bind the exact original research quantity context")
    _pins(prepared["input_pins"], base, consumed)
    _pins([cycle._pin(Path(root)/"history"/f"{state['revision']:04d}.json")], base, consumed)
    rows = [m for m in report["methods"] if m["id"] == method_id]
    if len(rows) != 1:
        raise ValueError("exact current manuscript method required")
    operations = rows[0]["operations"]
    if not operations or any(op["execution"] is None for op in operations):
        raise ValueError("every original operation needs its actual retained execution, including failures")
    return state, report, operations


def _closure(spec_pin, base, consumed):
    path = integrity._artifact_path(spec_pin, base)
    spec = _json(spec_pin, base, consumed)
    science.validate(spec)
    if spec["schema_version"] != 2 or spec["max_attempts"] != 1 or spec["review_policy"]["policy"]["max_redos"] != 0:
        raise ValueError("ordinary one-attempt schema2 study with original scientific review required")
    pins = [cycle._pin(p) for p in science.task_inputs(spec, path.parent)]
    _pins(pins, base, consumed)
    return spec, pins


def _cost(value, spec):
    cycle._vector(value)
    if value["native_attempts"] != 1 or value["wall_seconds"] < spec["max_seconds"]:
        raise ValueError("prospective ordinary cost must cover its whole hard ceiling and one attempt")


def _request(root, report_pin, method_id, check_contract_pin, base, *, _state=None, _producer_scope=None):
    """Authenticate the complete prospective check without emitting files."""
    preliminary=_Consumed(_observation=None if _producer_scope is None else _producer_scope.operational)
    check=_json(check_contract_pin,base,preliminary)
    consumed=_Consumed(check.get('custody_limits'), _observation=None if _producer_scope is None else _producer_scope.operational)
    _pins([check_contract_pin,cycle._pin(__file__),cycle._pin(integrity.__file__)],base,consumed)
    current_head = cycle._load(root)[1]["sha256"]
    state, report, operations = _original(root, report_pin, method_id, base, consumed, _state)
    check = _json(check_contract_pin, base, consumed)
    ce.keys(check, ("schema_version", "id", "purpose", "operations", "population", "rule",
        "rule_evidence", "error_semantics", "reference", "comparison",
        *(["custody_limits"] if "custody_limits" in check else [])))
    if type(check["schema_version"]) is not int or check["schema_version"] != 1 or check["purpose"] not in PURPOSES:
        raise ValueError("fresh replication contract/v1 with explicit purpose required")
    ce.identity(check["id"])
    fixed = comparison.rule(_json(check["rule"], base, consumed))
    if _located(check["rule_evidence"], base, consumed) != fixed:
        raise ValueError("prospective rule must equal its source-located tolerance/error law")
    semantics = _located(check["error_semantics"], base, consumed)
    ce.keys(semantics, ("kind", "meaning", "coverage"))
    if semantics["kind"] not in {"deterministic", "supplied_intervals", "unknown"}:
        raise ValueError("explicit deterministic/supplied/unknown source error semantics required")
    integrity._text(semantics["meaning"]); integrity._text(semantics["coverage"])
    if semantics["kind"] != "unknown" and semantics["kind"] != fixed["uncertainty"]:
        raise ValueError("comparison tolerance must use the source error semantics")
    reference = check["reference"]
    ce.keys(reference, ("quality", "sources", "points", "minimum_points"))
    quality = _located(reference["quality"], base, consumed)
    ce.keys(quality, ("state", "scope"))
    if quality["state"] not in {"supplied", "unknown", "unavailable"}:
        raise ValueError("reference quality is source-supplied or unresolved, never certified by preparation")
    integrity._text(quality["scope"])
    for key in ("sources", "points"):
        integrity._rows(reference[key], "reference " + key)
        _pins(reference[key], base, consumed)
    if type(reference["minimum_points"]) is not int or not 1 <= reference["minimum_points"] <= MAX_CELLS:
        raise ValueError("finite source-declared independent-point requirement required")
    hashes = [p["sha256"] for p in reference["points"]]
    if len(hashes) != len(set(hashes)):
        raise ValueError("aliases or duplicate point payloads cannot provide independent confirmation")
    if quality["state"] == "supplied" and check["purpose"] == "independent_reference":
        if not reference["sources"] or len(hashes) < reference["minimum_points"]:
            raise ValueError("complete independent source/point population required")
    plans = []; originals = []; allowed_population = []; ids = set()
    rows = integrity._rows(check["operations"], "replication operations", empty=False)
    if [r["operation_id"] for r in rows] != [o["id"] for o in operations]:
        raise ValueError("every original method operation must remain in order")
    for row, op in zip(rows, operations):
        ce.keys(row, ("operation_id", "original_experiment", "fresh_experiment", "study",
            "state", "representation", "differences", "cost", "acceptance_scope",
            *(["input_exposure"] if "input_exposure" in row else []),
            *(["tool_context"] if "tool_context" in row else [])))
        e = _experiment(state, row["original_experiment"])
        cycle._current_evidence(state, e, accepted=False, **_producer_keywords(_producer_scope, e))
        rd = Path(op["execution"]["rundir"])
        rd = rd if rd.is_absolute() else Path(base)/rd
        op_receipt = _dependency(op["execution"]["receipt"], base, consumed)
        e_receipt = _dependency(e["observation"]["receipt"], state["base_dir"], consumed)
        if e_receipt != op_receipt or cycle._ordinary(e["rundir"]).resolve() != cycle._ordinary(rd).resolve():
            raise ValueError("method must bind this exact original ordinary experiment")
        original_spec, original_inputs = _closure(e["study"], state["base_dir"], consumed)
        fresh_pin = e["study"] if row["study"] is None else row["study"]
        spec, inputs = _closure(fresh_pin, base, consumed)
        original_inputs=cycle._tool_input_closure(e,original_inputs,state['base_dir'],state=state)
        original_exposure=cycle._exposure_manifest(e,original_inputs,state['base_dir'])
        supplemental={k:deepcopy(row.get(k,e[k] if k in e else None))
            for k in ('input_exposure','tool_context') if k in row or k in e}
        prospective={**e,**supplemental,'study':fresh_pin}
        inputs=cycle._tool_input_closure(prospective,inputs,base,state=state)
        exposure=cycle._exposure_manifest(prospective,inputs,base)
        _pins([*original_inputs,*inputs,*[v for k,v in supplemental.items() if k=='input_exposure']],base,consumed)
        if original_exposure is not None:
            private={p['sha256'] for p in original_exposure['inputs'] if p['purpose']!='model_context'}
            if exposure is None or any(p['sha256'] in private and p['purpose']=='model_context' for p in exposure['inputs']):
                raise ValueError('original withheld/execution-only exposure cannot become model content')
        ce.identity(row["fresh_experiment"])
        if row["fresh_experiment"] in ids or row["fresh_experiment"] in {x["id"] for x in state["experiments"]}:
            raise ValueError("distinct not-yet-designed fresh experiment identity required")
        ids.add(row["fresh_experiment"])
        if spec.get("goal_binding") != original_spec.get("goal_binding") or spec.get("goal_binding") != state["contract"].get("goal_binding"):
            raise ValueError("whole original parent assignment must be retained")
        original_allowed = [e["study"], *e["input_pins"], e["observation"]["receipt"]]
        if e["observation"]["result"] is not None: original_allowed.append(e["observation"]["result"])
        original_allowed = [_dependency(p, state["base_dir"], consumed) for p in original_allowed]
        allowed_population.extend(original_allowed)
        prospective = [_dependency(p, base, consumed) for p in [fresh_pin, *inputs]]
        values = {}
        for name in ("state", "representation"):
            ce.keys(row[name], ("original", "fresh"))
            values[name] = {"original": _located(row[name]["original"], base, consumed, original_allowed),
                "fresh": _located(row[name]["fresh"], base, consumed, prospective)}
        differences = [_located(d, base, consumed) for d in integrity._rows(row["differences"], "source-backed comparison differences")]
        if check["purpose"] == "faithful_reexecution":
            if spec != original_spec or inputs != original_inputs or differences or any(v["original"] != v["fresh"] for v in values.values()):
                raise ValueError("faithful replay must preserve complete original specification/input/state/representation")
        elif (spec != original_spec or any(v["original"] != v["fresh"] for v in values.values())) and not differences:
            raise ValueError("different state/basis/bounds/auxiliary laws need an explicit source-supported separate test")
        if check["purpose"] == "independent_reference" and quality["state"] == "supplied":
            original_hashes = {p["sha256"] for p in original_inputs}
            references=[_dependency(p,base,consumed) for p in reference["sources"]]
            if not any(p in inputs and p["sha256"] not in original_hashes for p in references):
                raise ValueError("independent reference must bind a distinct actually consumed source, not a heldout label")
        _cost(row["cost"], spec)
        if row["acceptance_scope"] not in spec["review_policy"]["policy"]["claim_scopes"]:
            raise ValueError("fresh ordinary review must prospectively cover its actual scope")
        experiment = {k: deepcopy(e[k]) for k in ("question", "premise_ids", "predictions", "observable", "context_outputs", "exploratory")}
        experiment.update(supplemental)
        experiment.update(id=row["fresh_experiment"], parent=e["id"], study=deepcopy(fresh_pin),
            change="Fresh " + check["purpose"] + " under source-bound request " + check["id"],
            cost=deepcopy(row["cost"]), acceptance_scope=row["acceptance_scope"])
        plans.append(experiment)
        originals.append({"operation_id": op["id"], "experiment": deepcopy(e), "state": values["state"],
            "representation": values["representation"], "differences": differences, "prospective_inputs": inputs})
    population = check["population"]
    ce.keys(population, ("source", "id_field", "cells"))
    ce.identity(population["id_field"])
    original_rows = _located(population["source"], base, consumed, allowed_population)
    if type(original_rows) is not list or not 1 <= len(original_rows) <= MAX_CELLS:
        raise ValueError("complete source-owned original entry/bin/component roster required")
    original_ids = [r[population["id_field"]] for r in original_rows]
    cells = deepcopy(population["cells"])
    if type(cells) is not list or [c['id'] for c in cells] != original_ids:
        raise ValueError("every original cell, including failed/omitted/unknown slots, must remain in order")
    for source, cell in zip(original_rows, cells):
        for name in ('metric','unit','exposure'):
            if name in source and source[name] != cell[name]: raise ValueError('known native population semantics cannot be relabeled')
        if 'exposure' not in source and cell['exposure'] != 'adaptive_full':
            raise ValueError('withheld/screen exposure requires actual original source evidence')
    if type(cells) is not list or not 1 <= len(cells) <= MAX_CELLS:
        raise ValueError("complete finite source-owned original cell population required")
    cell_ids = set()
    for c in cells:
        ce.keys(c, ("id", "operation_id", "metric", "unit", "exposure", "value_pointer", "interval_pointer", "quality_pointer"))
        ce.identity(c["id"])
        if c["id"] in cell_ids or c["operation_id"] not in {o["id"] for o in operations}:
            raise ValueError("complete unique original operation/cell roster required")
        cell_ids.add(c["id"])
        if (c["metric"], c["unit"]) != (fixed["metric"], fixed["unit"]) or c["exposure"] not in {"adaptive_screen", "adaptive_full", "withheld_confirmation"}:
            raise ValueError("source population must preserve fixed units/metric and actual exposure")
        for key in ("value_pointer", "quality_pointer"): comparison._pointer(c[key])
        if c["interval_pointer"] is not None: comparison._pointer(c["interval_pointer"])
    if {c["operation_id"] for c in cells} != {o["id"] for o in operations}:
        raise ValueError("original unsuccessful operations cannot disappear from comparison population")
    comp = check["comparison"]
    ce.keys(comp, ("experiment_id", "study_template", "cost", "predictions", "acceptance_scope"))
    ce.identity(comp["experiment_id"])
    if comp["experiment_id"] in ids or comp["experiment_id"] in {e["id"] for e in state["experiments"]}:
        raise ValueError("comparison has its own distinct ordinary experiment identity")
    template = _json(comp["study_template"], base, consumed)
    if template.get("mode") != "research-comparison" or template.get("task") != {}:
        raise ValueError("existing ordinary research-comparison template with unfilled task required")
    if template.get("goal_binding") != state["contract"].get("goal_binding"):
        raise ValueError("comparison must preserve the whole original parent assignment")
    _cost(comp["cost"], template)
    if template.get("schema_version") != 2 or template.get("max_attempts") != 1 or template["review_policy"]["policy"]["max_redos"] != 0:
        raise ValueError("prospective comparison requires ordinary one-attempt scientific review")
    if comp["acceptance_scope"] not in template["review_policy"]["policy"]["claim_scopes"]:
        raise ValueError("comparison scope absent from its original review policy")
    if cycle._load(root)[1]["sha256"] != current_head:
        raise ValueError("research state changed during replication preparation")
    _ending(consumed)
    return {"schema_version": 1, "kind": "fresh-replication-request", "id": check["id"], "purpose": check["purpose"],
        "cycle_root": str(cycle._ordinary(root)), "state_sha256": state["sha256"], "revision": state["revision"],
        "base_dir": str(Path(base).resolve()), "report": deepcopy(report_pin), "method_id": method_id,
        "check_contract": deepcopy(check_contract_pin), "original_parent": deepcopy(state.get("parent_task")),
        "original_contract": deepcopy(state["contract"]), "original_context": deepcopy(state["context"]),
        "originals": originals, "experiments": plans, "population": cells, "rule": deepcopy(check["rule"]),
        "error_semantics": semantics, "reference_quality": quality, "comparison": deepcopy(comp),
        "inputs": list(consumed.values()), "custody_limits":deepcopy(consumed.limits), "execution_authorized": False, "replication_accepted": False,
        "limitations": ["Complete declared source census requires semantic review; hashes do not prove omissions absent.",
            "Declared runtime closure is not a load trace or native qualification.",
            "Supplied point/source identities do not prove statistical independence, coverage or physical correctness.",
            "Unavailable oracle and stochastic/error-law uncertainty remain unresolved."]}


def input_pins(root, operation, parameters):
    """Complete actual normal Host input closure, including fresh observations."""
    _, state = cycle._load(root)
    if operation == 'replication':
        ce.keys(parameters, ('current_report_pin','method_id','output_dir','check_contract_pin'))
        document=_request(root,parameters['current_report_pin'],parameters['method_id'],
            parameters['check_contract_pin'],state['base_dir'])
        # The ordinary protocol subject authenticates the current state and
        # permits exactly its new charged Graph reservation. That reservation
        # creates a new history revision without changing scientific custody;
        # do not compare its mutable revision as an immutable operand census.
        # The actual emitted request DOES retain that exact issued history pin.
        history=str((Path(root)/'history'/f"{document['revision']:04d}.json").resolve())
        return [p for p in document['inputs'] if p['path']!=history]
    if operation != 'replication-comparison': raise ValueError('finite replication preparation required')
    ce.keys(parameters, ('request_pin','output_dir'))
    return comparison_inputs(root,parameters['request_pin'])


def prepare_replication_request(root, current_report_pin, method_id, output_dir, *, check_contract_pin):
    _, state = cycle._load(root)
    base = state["base_dir"]
    document = _request(root, current_report_pin, method_id, check_contract_pin, base)
    out = cycle._ordinary(output_dir)
    out.mkdir(exist_ok=False)
    observed=_Consumed(document['custody_limits'])
    _pins(document['inputs'],base,observed)
    pin = _emit(out/"replication-request.json", document,observed)
    if cycle._load(root)[1]["sha256"] != document["state_sha256"]:
        raise ValueError("research changed before replication request return")
    _ending(observed)
    _json(pin,out,observed)
    return {"request": pin, "experiments": deepcopy(document["experiments"]),
        "execution_authorized": False, "replication_accepted": False}


def _prepared(root, request_pin, *, _producer_scope=None):
    _, state = cycle._load(root)
    envelope=_envelope(request_pin,state['base_dir'])
    consumed=_Consumed(envelope.get('custody_limits'), _observation=None if _producer_scope is None else _producer_scope.operational)
    document = _json(request_pin, state["base_dir"], consumed)
    if document.get("kind") != "fresh-replication-request" or document.get("cycle_root") != str(cycle._ordinary(root)):
        raise ValueError("this cycle's actual fresh preparation required")
    old = cycle._read(cycle._pin(Path(root)/"history"/f"{document['revision']:04d}.json"), root)
    if old["sha256"] != document["state_sha256"] or old["contract"] != state["contract"]:
        raise ValueError("original replication state or whole goal changed")
    # Original immutable declaration/result/receipt/review stay exact, even as
    # the existing campaign adds fresh experiments and spends its own budget.
    for row in document["originals"]:
        e = _experiment(state, row["experiment"]["id"])
        if e != row["experiment"] or not cycle._applicability(state, e)["measurement"]:
            raise ValueError("original scientific method/evidence/premise changed")
        cycle._current_evidence(state, e, accepted=False, **_producer_keywords(_producer_scope, e))
    _pins(document["inputs"], document["base_dir"], consumed)
    # Reconstruct the entire intended producer document from actual immutable
    # history and authenticated source bytes. A pin to caller-authored JSON
    # cannot loosen the population, law, fresh identity or uncertainty gates.
    replay = _request(root, document["report"], document["method_id"], document["check_contract"],
        document["base_dir"], _state=old, _producer_scope=_producer_scope)
    if replay != document:
        raise ValueError("prepared request differs from its original source/state producer")
    _ending(consumed)
    return state, document, consumed


def design_prepared(root, request_pin, *, experiment_id):
    """Explicit normal design mutation; preparation itself never changes head."""
    state, document, consumed = _prepared(root, request_pin)
    selected = [e for e in document["experiments"] if e["id"] == experiment_id]
    if len(selected) != 1:
        raise ValueError("exact prospective fresh experiment required")
    existing = [e for e in state["experiments"] if e["id"] == experiment_id]
    if existing:
        if any(existing[0][k] != v for k, v in selected[0].items()):
            raise ValueError("existing design differs from issued replication")
        return {"experiment_id": experiment_id, "already_designed": True, "execution_authorized": False}
    _ending(consumed)
    # All existing protocol membership, parent, budget and source gates remain.
    cycle.design(root, deepcopy(selected[0]))
    return {"experiment_id": experiment_id, "already_designed": False, "execution_authorized": False}


def _outcome(e, cells, base, consumed, *, quality_allowed):
    observation = e["observation"]
    source = None if observation["result"] is None else _json(observation["result"], base, consumed)
    rows = []
    for cell in cells:
        value = interval = None; reason = None; quality = False
        try:
            if source is None or observation["execution_status"] != "succeeded":
                raise ValueError("ordinary execution failed or returned no scientific result")
            q = cycle._pointer(source, cell["quality_pointer"])
            value = comparison._number(cycle._pointer(source, cell["value_pointer"]))
            if cell["interval_pointer"] is not None: interval = cycle._pointer(source, cell["interval_pointer"])
            quality = quality_allowed and (q is True or (type(q) is str and q == "passed"))
            if not quality: reason = "source quality, reference error law or ordinary independent review unresolved"
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            reason = str(exc)
        rows.append({"id": cell["id"], "value": value, "interval": interval, "quality": quality, "reason": reason,
            "original_execution_status": observation["execution_status"], "result": observation["result"],
            "receipt": observation["receipt"], "review": None if e["adjudication"] is None else e["adjudication"]["snapshot"]})
    return rows


def comparison_inputs(root, request_pin, *, _producer_scope=None):
    """Read-only worker-side reauthentication of the complete replication join."""
    with _producer_validation(_producer_scope) as scope:
        return _comparison_inputs(root, request_pin, scope)


def _comparison_inputs(root, request_pin, _producer_scope):
    """Read-only worker-side reauthentication of the complete replication join."""
    state, document, consumed = _prepared(root,request_pin, _producer_scope=_producer_scope)
    for prospective in document['experiments']:
        e = _experiment(state,prospective['id'])
        if any(e[k] != v for k,v in prospective.items()):raise ValueError('fresh design differs from issued request')
        events = [v for v in state['events'] if v['kind'] in {'prospective_design_added','model_designed_discriminating_experiment'} and v.get('experiment_id')==e['id']]
        if not events or min(v['revision'] for v in events)<=document['revision']:raise ValueError('actual post-request fresh experiment required')
        if e['observation'] is None:raise ValueError('actual terminal ordinary observation required')
        old = next(x['experiment'] for x in document['originals'] if x['experiment']['id']==e['parent'])
        if e['rundir']==old['rundir'] or e['observation']['receipt']==old['observation']['receipt'] or e['observation']['attempt_id']==old['observation']['attempt_id']:
            raise ValueError('distinct fresh run/attempt/receipt required')
        cycle._current_evidence(state,e,accepted=False, **_producer_keywords(_producer_scope, e))
        accepted = e['adjudication'] is not None and e['adjudication']['view']['state']=='accepted'
        if accepted:cycle._current_evidence(state,e,accepted=True, **_producer_keywords(_producer_scope, e))
        pins = [e['study'],*e['input_pins'],e['observation']['receipt']]
        if e['observation']['result'] is not None:pins.append(e['observation']['result'])
        if e['adjudication'] is not None:pins.append(e['adjudication']['snapshot'])
        binding={'rundir':e['rundir'],'receipt':e['observation']['receipt']}
        actual=integrity._executed(binding,[],[],state['base_dir'],consumed,limits=consumed.limits,accumulator=consumed.budget, **integrity._anchored_keywords(consumed.observation))
        record = _json(e['observation']['receipt'],state['base_dir'],consumed)
        if record.get('attempt_id')!=e['observation']['attempt_id'] or record.get('status')!=e['observation']['execution_status']:
            raise ValueError('fresh observation differs from exact current ordinary attempt')
        if e['observation']['result'] is not None:
            result=_dependency(e['observation']['result'],state['base_dir'],consumed)
            if not integrity._snapshot_member(record,'output_snapshot',result):
                raise ValueError('fresh result does not descend its actual same-attempt output custody')
        for field in ('input_snapshot','output_snapshot'):
            for name,snapshot in record.get(field,{}).items():
                for leaf in snapshot['files']:
                    path=Path(name) if leaf['name']=='.' else Path(name)/leaf['name']
                    pins.append({'path':str(path),'sha256':leaf['sha256'],'size':leaf['size']})
        _pins(pins,state['base_dir'],consumed)
    _ending(consumed)
    if cycle._load(root)[1]['sha256']!=state['sha256']:raise ValueError('research changed during complete comparison admission')
    return list(consumed.values())


def check_comparison(request, base, *, extra_pins=(), _producer_scope=None):
    """Reconstruct issued cell mappings and derived outcomes at worker intake."""
    with _producer_validation(_producer_scope) as scope:
        return _check_comparison(request, base, extra_pins, scope)


def _check_comparison(request, base, extra_pins, _producer_scope):
    """Reconstruct issued cell mappings and derived outcomes at worker intake."""
    pin=request['replication_request']
    document=_envelope(pin,base)
    root=document['cycle_root']
    pins=comparison_inputs(root,pin, _producer_scope=_producer_scope)
    state,issued,consumed=_prepared(root,pin, _producer_scope=_producer_scope)
    _pins([*pins,*extra_pins],base,consumed)
    if request['protocol_sha256']!=pin['sha256'] or request['comparison_id']!=issued['comparison']['experiment_id'] or request['rule']!=issued['rule']:
        raise ValueError('replication comparison cannot change its issued rule or identity')
    quality = issued['error_semantics']['kind']!='unknown' and issued['reference_quality']['state']=='supplied'
    fresh=[];old=[]
    for original,prospective in zip(issued['originals'],issued['experiments']):
        e=_experiment(state,prospective['id']);o=original['experiment']
        cells=[c for c in issued['population'] if c['operation_id']==original['operation_id']]
        accepted=e['adjudication'] is not None and e['adjudication']['view']['state']=='accepted'
        old_accepted=o['adjudication'] is not None and o['adjudication']['view']['state']=='accepted'
        fresh.extend(_outcome(e,cells,state['base_dir'],consumed,quality_allowed=quality and accepted))
        old.extend(_outcome(o,cells,state['base_dir'],consumed,quality_allowed=quality and old_accepted))
    by_side={'left':{c['id']:c for c in fresh},'right':{c['id']:c for c in old}}
    if [c['id'] for c in request['cells']]!=[c['id'] for c in issued['population']]:raise ValueError('complete issued comparison denominator required')
    for i,(cell,original) in enumerate(zip(request['cells'],issued['population'])):
        if any(cell[k]!=original[k] for k in ('id','metric','unit','exposure')):raise ValueError('issued representation/exposure changed')
        for side in ('left','right'):
            row=cell[side]
            expected={k:f'/cells/{i}/{v}' for k,v in [('value_pointer','value'),('interval_pointer','interval'),('quality_pointer','quality')]}
            if any(row[k]!=v for k,v in expected.items()):raise ValueError('exact intended replication operand pointers required')
            data=_json(row['source'],base,consumed)
            wanted=[by_side[side][c['id']] for c in issued['population']]
            if data.get('cells')!=wanted:raise ValueError('comparison operand differs from actual ordinary outcome/review/unknown law')
    _ending(consumed)
    return list(consumed.values())


def prepare_comparison(root, request_pin, output_dir):
    """Bind fresh ordinary outcomes and prepare the existing numerical worker.

    Failed cells are explicit unknown operands, not omitted or renormalized.
    No arithmetic result or source/readiness label becomes scientific acceptance.
    """
    state, document, consumed = _prepared(root, request_pin)
    current = state["sha256"]; left = []; right = []; bindings = []
    _pins(comparison_inputs(root,request_pin),state["base_dir"],consumed)
    quality_allowed = document["error_semantics"]["kind"] != "unknown" and document["reference_quality"]["state"] == "supplied"
    for original, prospective in zip(document["originals"], document["experiments"]):
        e = _experiment(state, prospective["id"])
        if any(e[k] != v for k, v in prospective.items()): raise ValueError("fresh method design differs from issued request")
        events = [v for v in state["events"] if v["kind"] in {"prospective_design_added", "model_designed_discriminating_experiment"} and v.get("experiment_id") == e["id"]]
        if not events or min(v["revision"] for v in events) <= document["revision"]:
            raise ValueError("fresh design must follow issued request; old score cannot masquerade as replication")
        if e["observation"] is None: raise ValueError("fresh actual terminal ordinary observation required")
        cycle._current_evidence(state, e, accepted=False)
        old = original["experiment"]
        if e["rundir"] == old["rundir"] or e["observation"]["receipt"] == old["observation"]["receipt"] or e["observation"]["attempt_id"] == old["observation"]["attempt_id"]:
            raise ValueError("distinct fresh run/attempt/receipt required, not original custody")
        accepted = e["adjudication"] is not None and e["adjudication"]["view"]["state"] == "accepted"
        if accepted: cycle._current_evidence(state, e, accepted=True)
        old_accepted = old["adjudication"] is not None and old["adjudication"]["view"]["state"] == "accepted"
        if old_accepted: cycle._current_evidence(state, old, accepted=True)
        cells = [c for c in document["population"] if c["operation_id"] == original["operation_id"]]
        left.extend(_outcome(e, cells, state["base_dir"], consumed, quality_allowed=quality_allowed and accepted))
        right.extend(_outcome(old, cells, state["base_dir"], consumed, quality_allowed=quality_allowed and old_accepted))
        bindings.append({"experiment": e["id"], "receipt": deepcopy(e["observation"]["receipt"]),
            "result": deepcopy(e["observation"]["result"]), "review": None if e["adjudication"] is None else deepcopy(e["adjudication"]["snapshot"])})
        _pins([e["study"], *e["input_pins"], e["observation"]["receipt"], *([e["adjudication"]["snapshot"]] if accepted else [])], state["base_dir"], consumed)
    # Reassemble in the original population order even when operations interleave.
    left_by = {r["id"]: r for r in left}; right_by = {r["id"]: r for r in right}
    left = [left_by[c["id"]] for c in document["population"]]; right = [right_by[c["id"]] for c in document["population"]]
    out = cycle._ordinary(output_dir); out.mkdir(exist_ok=False)
    lp = _emit(out/"fresh-outcomes.json", {"cells": left, "bindings": bindings},consumed)
    rp = _emit(out/"original-outcomes.json", {"cells": right},consumed)
    rows = []
    for i, c in enumerate(document["population"]):
        def operand(pin):
            return {"source": pin, "value_pointer": f"/cells/{i}/value", "interval_pointer": f"/cells/{i}/interval", "quality_pointer": f"/cells/{i}/quality"}
        rows.append({k: deepcopy(c[k]) for k in ("id", "metric", "unit", "exposure")})
        rows[-1].update(left=operand(lp), right=operand(rp))
    # Scientific operands stay under the old finite payload limits. Complete
    # operational lineage is separately reauthenticated by the actual worker.
    dependencies = []
    comp = {"schema_version": 1, "protocol_sha256": request_pin["sha256"], "comparison_id": document["comparison"]["experiment_id"],
        "rule": document["rule"], "cells": rows, "dependencies": dependencies, "replication_request": deepcopy(request_pin)}
    cp = _emit(out/"comparison.json", comp,consumed)
    spec = _json(document["comparison"]["study_template"], document["base_dir"], consumed)
    spec["task"] = {"schema_version": 1, "request": cp}
    science.validate(spec)
    sp = _emit(out/"science.json", spec,consumed)
    template = deepcopy(document["experiments"][0])
    template.update(id=document["comparison"]["experiment_id"], parent=None, study=sp,
        question="Compare every original and fresh cell under the issued source error law.",
        change="Whole-population fresh replication comparison, including failures and unknown oracle quality.",
        cost=document["comparison"]["cost"], predictions=document["comparison"]["predictions"],
        acceptance_scope=document["comparison"]["acceptance_scope"], context_outputs={}, exploratory=False,
        observable={"pointer": "/decision", "outcomes": {k: k for k in ("better", "equivalent", "worse", "unknown")}})
    # A comparison is a NEW study. Its complete input closure must not inherit
    # an exposure manifest bound to the original/fresh method study. Preserve
    # the actual tool context and the strictest source visibility for identical
    # payloads across ALL operations; new derived/operational bytes stay out of
    # model content unless a separate prospective disclosure is supplied.
    source_purposes = {}
    priority = {"model_context": 0, "execution_dependency": 1, "withheld_evaluation": 2}
    classified = False
    for original, prospective in zip(document["originals"], document["experiments"]):
        for source in (original["experiment"], _experiment(state, prospective["id"])):
            exposure = cycle._exposure_manifest(source, source["input_pins"], state["base_dir"])
            if exposure is None: continue
            classified = True
            _pins([source["input_exposure"]], state["base_dir"], consumed)
            for row in exposure["inputs"]:
                previous = source_purposes.get(row["sha256"], "model_context")
                source_purposes[row["sha256"]] = max((previous, row["purpose"]), key=priority.__getitem__)
    exposure_pin = None
    if classified:
        dependencies = [cycle._pin(path) for path in science.task_inputs(spec, out)]
        dependencies = cycle._tool_input_closure(template, dependencies, state["base_dir"], state=state)
        _pins(dependencies, state["base_dir"], consumed)
        purposes = {pin["path"]: source_purposes.get(pin["sha256"], "execution_dependency") for pin in dependencies}
        reason = ("New complete comparison closure; preserve every original/fresh source exposure, "
                  "with non-model classification taking precedence. New derived/operational inputs "
                  "are execution-only; no model disclosure or OS blinding is inferred.")
        intended = {"kind": "research_execution_input_exposure", "study": sp,
            "inputs": [{**pin, "purpose": purposes[pin["path"]]} for pin in dependencies],
            "reason": reason, "whole_worker_custody_retained": True, "OS_blinding_enforced": False}
        # Commit intended bytes BEFORE the existing binder observes its file.
        # It therefore reuses the exact declared artifact rather than giving
        # a first reread authority or overwriting a changed file to pass.
        exposure_pin = _emit(out/(ce.digest(intended)+".json"), intended, consumed)
        template = cycle.bind_input_exposure(template, purposes, out, base_dir=state["base_dir"], reason=reason)
        if template["input_exposure"] != exposure_pin:
            raise ValueError("intended comparison exposure changed during ordinary binding")
        cycle._exposure_manifest(template, dependencies, state["base_dir"])
    if cycle._load(root)[1]["sha256"] != current: raise ValueError("research changed before comparison return")
    _ending(consumed)
    for p in (request_pin, lp, rp, cp, sp, *([exposure_pin] if exposure_pin is not None else [])): _json(p,out,consumed)
    return {"comparison": cp, "study": sp, "experiment": deepcopy(template), "fresh_bindings": bindings,
        "complete_original_cell_denominator": [c["id"] for c in document["population"]],
        "execution_authorized": False, "replication_accepted": False,
        "next": "ordinary design, CHECK-IN 1, admitted worker, independent roles and scoped comparison; no vote is carried"}


def _readonly_producer(context):
    scope = context.resource(_ProducerSessions)
    owner = integrity._anchored_owner(context)
    if scope.operational is not None and scope.operational is not owner:
        raise ValueError('operational observation changed during comparison')
    if scope._operational_original is not None and scope._operational_original is not owner:
        raise ValueError('original operational observation changed during comparison')
    scope.operational = owner
    scope._operational_original = owner
    return scope
