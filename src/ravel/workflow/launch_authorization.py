"""Checked launches with retained authorization snapshots and append-only events.

Local hash chains detect inconsistent records; they are not authentication or an
external, tamper-proof clock. Only this interface's launches have ordering evidence.

A run the controller owns is different in three ways. Its launches start through the
confined launcher (``ravel.controller.confine``): the journaled command stays the
approved argv and the sandbox wrapper is added at ``Popen`` time, after a confinement
check that refuses or holds before any event is written. Every journal event is first
appended to the controller's store and only then copied into the run tree, so a changed
run-tree copy no longer audits. And its events carry the controller's real clock: a
fixed test clock in the environment is ignored.
"""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import signal
import subprocess

from . import provenance
from .execution import digest, file_hash, utc_now
from .state_io import file_lock, read_json

JOURNAL = "logs/authorization"
STORE_KIND = "launch-authorization"


def parse_utc(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("operational timestamp must be nonblank UTC")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
        raise ValueError("operational timestamp must include UTC timezone")
    return stamp


def _controller_run(root):
    """The run id when ``root`` is (inside) a run directory the controller owns, else None."""
    from ravel.controller.confine import runs
    found = runs.owner_of(Path(root).resolve())
    return found[0] if found else None


def operational_utc(root=None):
    """Real clock by default; an explicit fixed clock keeps tests deterministic.

    A controller-owned run always uses the real clock.
    """
    value = utc_now() if root is not None and _controller_run(root) else (
        os.environ.get("WORKFLOW_STATE_UTC") or utc_now())
    parse_utc(value)
    return value


def _events(root):
    records = []
    previous = ""
    previous_time = None
    for sequence, path in enumerate(sorted((Path(root) / JOURNAL).glob("*.json")), 1):
        event = read_json(path)
        if (not isinstance(event, dict) or type(event.get("schema_version")) is not int
                or event["schema_version"] != 1 or event.get("event") not in ("authorized", "launched")
                or type(event.get("sequence")) is not int
                or event["sequence"] != sequence or path.name != f"{sequence:08d}.json"
                or event.get("previous_sha256") != previous
                or event.get("sha256") != digest({k: v for k, v in event.items() if k != "sha256"})):
            raise ValueError("authorization event sequence or hash chain changed")
        stamp = parse_utc(event.get("utc"))
        if previous_time is not None and stamp < previous_time:
            raise ValueError("authorization event clock moved backwards")
        previous, previous_time = event["sha256"], stamp
        records.append(event)
    return records


def _append(root, payload):
    directory = Path(root) / JOURNAL
    with file_lock(directory / "write.lock"):
        records = _events(root)
        event = {"schema_version": 1, "sequence": len(records) + 1,
                 "previous_sha256": records[-1]["sha256"] if records else "",
                 "utc": operational_utc(root), **payload}
        if records and parse_utc(event["utc"]) < parse_utc(records[-1]["utc"]):
            raise ValueError("authorization event clock moved backwards")
        run_id = _controller_run(root)
        if not run_id:
            event["governance_label"] = "NOT GOVERNED"
        event["sha256"] = digest(event)
        if run_id:
            # The store holds the original; the run-tree file below is a copy for reading.
            from ravel.controller.confine import runs
            runs.store(run_id).append(STORE_KIND, event)
        # Exclusive creation: existing events are never updated or replaced.
        with (directory / f"{event['sequence']:08d}.json").open("x", encoding="utf-8") as stream:
            json.dump(event, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return event


def _pin(path, *, document=False, _session=None):
    path = Path(path).resolve()
    if _session is not None:
        _session.require_regular(path)
    entry = {"path": str(path), "sha256": (_session.hash_file if _session is not None else file_hash)(path)}
    if document:
        # Preserve CRLF and other valid JSON whitespace in the byte commitment.
        entry["text"] = path.read_bytes().decode("utf-8")
        if provenance.sha256_bytes(entry["text"].encode()) != entry["sha256"]:
            raise ValueError("authorization document changed while capturing it")
    return entry


def _absent_pin(path):
    """An optional approval input that is absent, pinned with provenance's absence hash."""
    return {"path": str(Path(path).resolve()), "sha256": provenance.sha256_file(path), "absent": True}


def _pin_changed(pin, _session=None):
    if pin.get("absent") is True:
        return os.path.lexists(pin["path"])
    return (_session.hash_file if _session is not None else file_hash)(pin["path"]) != pin["sha256"]


def _capture(root, required_plan, *, command=None, context=None):
    root = Path(root).resolve()
    from . import execution
    from . import workflow_state as ws
    from . import physics_review as review
    context = context or {}
    if required_plan == "science" or review._science_run(root) and context.get("kind") == "science-stage":
        return _capture_science(root, required_plan, command or [], context)
    correction = context.get("review_action") == "correction"
    def check():
        if context.get('kind') == 'scoped-likelihood-stage':
            from . import scoped
            spec = context.get('stage_spec', {})
            if required_plan != 'full':
                return ['scoped likelihood requires its actual full CHECK-IN 1 envelope']
            scoped.verify_supervised_stage(root, context.get('stage'), command or [], spec.get('inputs', []),
                spec.get('outputs', []), spec.get('depends_on', []), spec.get('cwd'), spec.get('log'),
                context.get('max_seconds'), context.get('events'), allow_running=True)
        if correction:
            spec = context.get("stage_spec", {})
            return ws.verify_approval_envelope(str(root), required_plan) + review.correction_execution_errors(
                root, context.get("stage"), command or [], spec.get("inputs", []), spec.get("outputs", []),
                spec.get("depends_on", []), spec.get("cwd", ""), spec.get("log"), **execution.helper_declaration_fields(spec))
        errors = ws.verify_approval(str(root), required_plan=required_plan, disclose=True)
        if review.active(root):
            errors += review.gate_errors(root, "bulk")
        # a delegated epoch-two dry or smoke screen needs its R1 receipt under the held lease.
        from . import gate_wiring
        return errors + gate_wiring.launch_errors(root, required_plan, command or [], context)
    errors = check()
    if errors:
        raise ValueError("launch authorization refused: " + "; ".join(errors))
    approval = _pin(Path(root) / "inputs/checkin1_approval.json", document=True)
    # The delegated-defaults record is optional; an absent one is pinned with the
    # approval fingerprint's absence sentinel, and creating it later changes both.
    from ravel.validation.intake_records import DELEGATED_DEFAULTS_PATH
    from .approval_inputs import authorization_pins
    optional = str(Path(root) / DELEGATED_DEFAULTS_PATH)
    paths = ws.approval_input_paths(str(root))
    absent = [p for p in paths if p == optional and not os.path.lexists(p)]
    present = authorization_pins([p for p in paths if p not in absent], _pin)
    pins = iter(present)
    inputs = [_absent_pin(p) if p in absent else next(pins) for p in paths]
    contract = read_json(inputs[0]["path"])
    from . import operation_resources as resources
    declared_operation = resources.fields(contract)
    if resources.fields(context.get("stage_spec", {})) != declared_operation:
        raise ValueError("solver resource class differs from the approved task")
    if declared_operation:
        spec = context["stage_spec"]
        if required_plan != "full" or context.get("kind") != "scientific-stage":
            raise ValueError("solver resources require their ordinary full-stage approval")
        actual = resources.authority(root, spec["operation_resources"], stage=context.get("stage"),
            command=command or [], cwd=spec["cwd"], inputs=spec["inputs"], outputs=spec["outputs"],
            events=context.get("events"), max_seconds=context.get("max_seconds"))
        if context.get("events") is None or context.get("max_seconds") is None or actual != context.get("operation_authority"):
            raise ValueError("solver launch resources or authority changed")
    needs_go = not correction and required_plan in ws.BULK_PLANS and contract.get("task_mode") not in ws.NO_CHECKIN2_TASK_MODES
    snapshot = {"required_plan": required_plan, "approval": approval, "approval_inputs": inputs,
                "go": None, "go_inputs": [], "review": None, "review_inputs": []}
    if declared_operation:
        paths = resources.binding(root, declared_operation["operation_resources"])
        snapshot["operation_inputs"] = [resources.document_pin(p) for p in paths]
    if needs_go:
        snapshot["go"] = _pin(Path(root) / "inputs/checkin2_go.json", document=True)
        snapshot["go_inputs"] = [_pin(p, document=i in (0, 1, 2, 5))
                                 for i, p in enumerate(ws.checkin2_go_input_paths(str(root)))]
    if review.active(root):
        snapshot["review"] = review.snapshot(root, action="correction" if correction else "bulk", stage=context.get("stage"))
        snapshot["review_inputs"] = [_pin(p) for p in review.bound_paths(root)]
    if context.get('kind') == 'scoped-likelihood-stage':
        from . import scoped
        proposal = scoped.verify_plan(root, require_approval=True)
        paths = [Path(root) / p for p in (scoped.PLAN, scoped.SPEC, 'execution_attempt.json')]
        paths += [Path(root) / p if not Path(p).is_absolute() else Path(p) for p in proposal['stage_binding']['inputs']]
        snapshot['scoped_inputs'] = [_pin(p, document=i < 3) for i, p in enumerate(dict.fromkeys(paths))]
    # Recheck both the approval language and the captured bytes before recording.
    errors = check()
    pins = _authorization_pins(snapshot)
    if errors or any(_pin_changed(p) for p in pins):
        raise ValueError("authorization inputs changed while preparing launch")
    return snapshot


def _authorization_pins(snapshot):
    pins = [snapshot["approval"], *snapshot["approval_inputs"], *snapshot["go_inputs"], *snapshot["review_inputs"],
            *snapshot.get("science_launch_inputs", []), *snapshot.get("science_stage_inputs", [])]
    pins += snapshot.get('scoped_inputs', [])
    pins += snapshot.get('operation_inputs', [])
    if snapshot["go"]:
        pins.append(snapshot["go"])
    return pins


def _capture_science(root, required_plan, command, context, *, _session=None):
    from . import science, physics_review as review
    if _session is None:
        with science._validation_scope(root) as session:
            return _capture_science(root, required_plan, command, context, _session=session)
    from . import execution
    execution._check_validation_session(root, _session)
    if required_plan != "science" or context.get("kind") != "science-stage":
        raise ValueError("science launch needs its actual study envelope")
    try:
        selected = science._verified_launch_binding(root, context.get("stage"), command, context, _session=_session)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        raise ValueError("launch authorization refused: " + str(exc)) from exc
    correction = context.get("review_action") == "correction"
    snapshot = {"approval_kind": "science", "required_plan": "science",
        "approval": _pin(Path(root) / science.APPROVAL, document=True, _session=_session),
        "approval_inputs": [_pin(p, document=True, _session=_session) for p in science.approval_input_paths(root)],
        "go": None, "go_inputs": [], "review": None, "review_inputs": [],
        "science_launch_inputs": [_pin(p, document=True, _session=_session) for p in science.launch_input_paths(root)],
        "science_stage_inputs": [_pin(Path(root) / p if not Path(p).is_absolute() else p, _session=_session) for p in selected["binding"]["inputs"]],
        "stage_binding": selected["binding"]}
    if review.active(root):
        snapshot["review"] = review.snapshot(root, action="correction" if correction else "bulk", stage=context.get("stage"))
        snapshot["review_inputs"] = [_pin(p, _session=_session) for p in review.bound_paths(root)]
    errors = science.verify_launch(root, context.get("stage"), command, context, _session=_session)
    if errors or any(_session.hash_file(pin["path"]) != pin["sha256"] for pin in _authorization_pins(snapshot)):
        raise ValueError("authorization inputs changed while preparing science launch")
    return snapshot


def _historical_scoped(snapshot, event, contract):
    """Replay the retained scoped likelihood recipe under its genuine first approval."""
    from . import scoped, physics_review
    if (snapshot['required_plan'] != 'full' or contract.get('task_mode') != 'likelihood'
            or event['context'].get('review_action') != 'bulk'):
        raise ValueError('retained scoped launch is outside its likelihood-only full approval')
    root = Path(snapshot['approval']['path']).parent.parent
    pins = snapshot.get('scoped_inputs', [])
    if len(pins) < 3 or [p['path'] for p in pins[:3]] != [str(root / p) for p in (scoped.PLAN, scoped.SPEC, 'execution_attempt.json')]:
        raise ValueError('scoped launch has no exact retained plan, specification or spent-attempt receipt')
    for pin in pins[:3]:
        if provenance.sha256_bytes(pin['text'].encode()) != pin['sha256']:
            raise ValueError('retained scoped authorization document changed')
    proposal, spec, attempt = [json.loads(pin['text']) for pin in pins[:3]]
    if (contract.get('execution_plan') != {'path': scoped.PLAN, 'sha256': pins[0]['sha256']}
            or proposal.get('mode') != 'likelihood' or spec.get('mode') != 'likelihood'
            or proposal.get('max_attempts') != 1 or proposal.get('max_seconds') != spec.get('max_seconds')
            or type(attempt.get('attempt')) is not int or attempt['attempt'] != 1
            or attempt.get('plan_sha256') != pins[0]['sha256'] or attempt.get('budget_seconds') != proposal['max_seconds']
            or parse_utc(attempt.get('started_utc')) > parse_utc(event['utc'])):
        raise ValueError('retained scoped plan or attempt exceeds its approved envelope')
    binding = proposal['stage_binding']
    if (binding.get('fingerprint') != digest({k: v for k, v in binding.items() if k != 'fingerprint'})
            or len(proposal['stages']) != 1):
        raise ValueError('retained scoped recipe fingerprint changed')
    stage = proposal['stages'][0]
    expected = physics_review._stage_spec(root, {**stage, 'inputs': binding['inputs'], 'log': 'logs/scoped-worker.log'})
    committed = {p['path']: p['sha256'] for p in pins}
    if (len(committed) != len(pins) or any(data['kind'] != 'file' or len(data['files']) != 1
            or committed.get(path) != data['files'][0]['sha256'] for path, data in binding['input_snapshot'].items())):
        raise ValueError('retained scoped stage input commitments changed')
    context = event['context']
    if (context.get('stage') != 'likelihood' or stage['stage'] != 'likelihood'
            or event['command'] != stage['command'] or binding['command'] != stage['command']
            or binding['cwd'] != stage['cwd'] or binding['outputs'] != stage['outputs']
            or stage['outputs'] != ['outputs'] or stage['depends_on'] or binding['parents']
            or context.get('stage_spec') != expected or type(context.get('events')) is not int or context['events'] != 0
            or context.get('plan_sha256') != pins[0]['sha256'] or context.get('max_seconds') != proposal['max_seconds']):
        raise ValueError('retained scoped launch command, scope or hard ceiling changed')


def _historical_errors(event):
    """Use frozen approval bytes/digests, never today's approval as a substitute."""
    from . import workflow_state as ws
    snapshot = event["authorization"]
    rung = snapshot["required_plan"]
    from .operation_resources import retained
    retained(snapshot, event.get("context", {}), event["command"])
    science_launch = snapshot.get("approval_kind") == "science"
    if science_launch:
        from . import science
        errors = science.validate_authorization_snapshot(snapshot, event)
        if errors:
            raise ValueError("invalid retained science approval: " + "; ".join(errors))
        contract = {}
    else:
        if rung not in ws.APPROVAL_PLANS:
            raise ValueError("unknown launch compute rung")
        contract = json.loads(snapshot["approval_inputs"][0]["text"])
        if event.get('context', {}).get('kind') == 'scoped-likelihood-stage':
            _historical_scoped(snapshot, event, contract)
    review_doc = snapshot.get("review")
    correction = event.get("context", {}).get("review_action") == "correction"
    needs_go = rung in ws.BULK_PLANS and contract.get("task_mode") not in ws.NO_CHECKIN2_TASK_MODES
    if needs_go and not correction and snapshot["go"] is None:
        raise ValueError("bulk launch has no retained GO")
    if correction and not review_doc:
        raise ValueError("correction launch has no retained review authority")
    if review_doc:
        from . import physics_review as review
        errors = review.validate_snapshot(review_doc)
        if errors:
            raise ValueError("invalid retained review: " + "; ".join(errors))
        if review_doc["action"] != ("correction" if correction else "bulk"):
            raise ValueError("retained review authorizes a different action")
        pins = {p["path"]: p["sha256"] for p in snapshot.get("review_inputs", [])}
        root = Path(snapshot["approval"]["path"]).parent.parent
        approved_pins = {p["path"]: p["sha256"] for p in [*snapshot["approval_inputs"], snapshot["approval"]]}
        registered_pins = {str(root / p["path"]) if not Path(p["path"]).is_absolute() else p["path"]: p["sha256"]
                           for p in review_doc["registration"]["bindings"]}
        policy_pin = next((p for p in snapshot["approval_inputs"] if p["path"] == str(root / review.POLICY)), None)
        # A retained amendment re-approval replaces only the registered pins it names.
        amended = {str(root / p) for p in review.amended_paths(
            review_doc["registration"], json.loads(snapshot["approval"]["text"]), snapshot["approval"]["sha256"])}
        if ({p: s for p, s in registered_pins.items() if p not in amended} != {p: s for p, s in approved_pins.items() if p not in amended}
                or policy_pin is None or json.loads(policy_pin["text"]) != review_doc["registration"]["policy"]):
            raise ValueError("retained review refers to a different first approval or policy")
        def committed(rel, value):
            expected = provenance.sha256_bytes((json.dumps(value, indent=2, allow_nan=False) + "\n").encode())
            return pins.get(str(root / rel)) == expected
        if not committed(review.REGISTRATION, review_doc["registration"]) or not committed(review.HEAD, review_doc["checkpoint"]):
            raise ValueError("review registration or checkpoint is not bound to launch inputs")
        for e in review_doc["events"]:
            if parse_utc(e["utc"]) > parse_utc(event["utc"]):
                raise ValueError("review was recorded after authorization")
            if not committed(f"{review.DIRECTORY}/events/{e['sequence']:08d}.json", e):
                raise ValueError("review event is not bound to launch inputs")
        if correction:
            ctx = event["context"]
            admission = next(e for e in reversed(review_doc["events"]) if e["event"] == "correction")
            spec = next((s for s in admission["stage_specs"] if s["stage"] == ctx.get("stage")), None)
            if review_doc["stage"] != ctx.get("stage") or spec != ctx.get("stage_spec") or spec["command"] != event["command"]:
                raise ValueError("correction launch differs from its retained exact stage specification")
    for pin in [*snapshot["approval_inputs"], *snapshot["go_inputs"]]:
        if "text" in pin and provenance.sha256_bytes(pin["text"].encode()) != pin["sha256"]:
            raise ValueError("retained authorization input changed")
    if science_launch:
        return
    for key, tool, version in (("approval", ws.APPROVAL_GENERATOR, ws.APPROVAL_VERSION),
                               ("go", ws.CHECKIN2_GO_GENERATOR, ws.CHECKIN2_GO_VERSION)):
        pin = snapshot[key]
        if pin is None:
            if key == "approval":
                raise ValueError("launch receipt has no first approval")
            continue
        record = json.loads(pin["text"])
        if provenance.sha256_bytes(pin["text"].encode()) != pin["sha256"]:
            raise ValueError(f"retained {key} digest changed")
        delegated=(key=='approval' and record.get('schema_version')==3) or (key=='go' and record.get('schema_version')==4)
        if delegated:
            from . import scientific_autonomy
            root=Path(snapshot['approval']['path']).parent.parent
            contract=json.loads(snapshot['approval_inputs'][0]['text'])
            sources={p['path']:p['text'].encode() for p in snapshot['approval_inputs'] if 'text' in p}
            scientific_autonomy.verify_decision(contract,record,root,sources=sources,
                action='approve_plan' if key=='approval' else 'checkin2_go')
            fields={'schema_version','generated_by','generated_utc','quote','input_fingerprint','authority','delegation','delegate_actor'}
            fields|=({'approved_plan','task_contract','checkin1','cost_preflight'} if key=='approval'
                     else {'decision','checkin2','checkin1_approval','evidence_manifest'})
            if key == 'approval': fields |= set(record) & {'approved_inputs', 'input_changes'}
            fields |= set(record) & {'operating_mode'}
            if set(record)!=fields:raise ValueError('retained delegated decision has an invalid closed schema')
            delegated_scope=scientific_autonomy.declaration(contract,root,_sources=sources)['value']['bounds']['compute_plans']
            if (record['approved_plan'] if key=='approval' else contract['compute_plan']) not in delegated_scope:
                raise ValueError('retained machine decision exceeds exact delegated compute scope')
            tool='workflow_state.py delegated-approve' if key=='approval' else 'workflow_state.py delegated-go'
        if 'operating_mode' in record:
            from . import operating_mode
            root = Path(snapshot['approval']['path']).parent.parent
            sources = {p['path']: p['text'].encode() for p in snapshot['approval_inputs'] if 'text' in p}
            operating_mode.verify_receipt(root, record, sources=sources)
        versions = (4,) if delegated and key=='go' else (3,) if delegated else (2, 3) if key == "go" else (version,)
        if (type(record.get("schema_version")) is not int or record["schema_version"] not in versions
                or record.get("generated_by") != tool
                or record.get("input_fingerprint") != provenance.sha256_bytes(
                    "".join(p["sha256"] for p in snapshot[key + "_inputs"]).encode("utf-8"))):
            raise ValueError(f"retained {key} binding is invalid")
        if parse_utc(record.get("generated_utc")) > parse_utc(event["utc"]):
            raise ValueError(f"{key} was recorded after authorization")
        if key == "approval" and ws.APPROVAL_PLANS.index(record["approved_plan"]) < ws.APPROVAL_PLANS.index(rung):
            raise ValueError("launch exceeded its retained first approval")
        if key == "go":
            if record.get("decision") != "GO" or len(snapshot["go_inputs"]) < 7:
                raise ValueError("launch did not retain evidence-bound GO")
            if snapshot["go_inputs"][1]["sha256"] != snapshot["approval"]["sha256"]:
                raise ValueError("GO was bound to a different first approval")
            manifest = json.loads(snapshot["go_inputs"][2]["text"])
            comparison = json.loads(snapshot["go_inputs"][5]["text"])
            entries = [manifest[k] for k in ("produced", "reference", "comparison")] + manifest["inputs"]
            if (manifest["result"] != comparison or [p["sha256"] for p in entries]
                    != [p["sha256"] for p in snapshot["go_inputs"][3:3 + len(entries)]]):
                raise ValueError("retained waypoint comparison or evidence identities changed")
            if record["schema_version"] == 3:
                if not review_doc or correction or snapshot["go_inputs"][3 + len(entries):] != snapshot["review_inputs"]:
                    raise ValueError("GO is not bound to the retained accepted review")


def authorized_popen(root, required_plan, command, *, context, confinement=None, **kwargs):
    """Check and retain approval immediately before Popen; retain a separate launch event.

    ``confinement`` is a confined launch plan (``ravel.controller.confine.prepare``) or the
    extras of the default one (``attempt_dir``, ``channels``, ``limits``). A run the controller
    owns always launches confined; an absent or unqualified sandbox holds it before any event.
    """
    from . import agent_tripwire
    agent_tripwire.check("authorized_popen")
    command = list(map(str, command))
    if not command or not isinstance(context, dict):
        raise ValueError("launch needs a command and context object")
    from . import physics_review as review, wms_policy
    from ravel.controller.confine import tripwire
    tripwire.check(root, "authorized_popen")
    # A governed run launches only from its workflow-manager step or a worker in that step's custody.
    wms_policy.require_custody(root)
    # Serialize a review transition against the final check and spawn. This is a
    # local ordering guarantee; it does not authenticate actors or external tools.
    from . import gate_wiring
    with gate_wiring.steering_dispatch(root, context.get("node_id")), file_lock(Path(root) / review.DIRECTORY / "write.lock"):
        process = _authorized_popen_locked(root, required_plan, command, context=context, confinement=confinement,
                                           **kwargs)
        if kwargs.get('start_new_session'):
            try:
                gate_wiring.register_steering_process(root, process, context)
            except BaseException:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                raise
        return process


def verified_resource_context(root, required_plan, command, context, *, _session=None):
    """Derive autonomous reservations from the exact approved execution envelope.

    ``events`` remains the stage's workload. ``resource_events`` counts newly
    generated events, so showering and analysis never charge generation again.
    The native dispatcher records an attempt but reserves no stage resources;
    every actual stage still passes this admission before its own process starts.
    """
    from . import operating_mode
    mode = operating_mode.frozen(root)
    if mode is None or mode['mode'] != 'autonomous':
        return context
    root = Path(root).resolve()
    if context.get('kind') != 'science-stage' and required_plan not in mode['bounds']['compute_plans']:
        raise ValueError('launch compute rung exceeds frozen operator scope')
    result = operating_mode._ResourceContext(context)
    # These are derived outputs, never declarations a caller can use to escape
    # resource accounting or the allowed-stage check.
    for key in ('resource_events', 'resource_reservation', 'resource_stages'):
        result.pop(key, None)
    kind = result.get('kind')
    if kind == 'science-stage':
        from . import science
        selected = science._verified_launch_binding(root, result.get('stage'), command, result, _session=_session)
        read = _session.read_document if _session is not None else read_json
        checkin = read(root / 'inputs/checkin1.json')
        events = checkin['sections']['iv']['new_generated_events']
        if type(events) is not int or events < 0:
            raise ValueError('approved science generated-event ceiling is invalid')
        result.update(max_seconds=selected['max_seconds'], events=0, resource_events=events)
        return result
    if kind in ('native-stage', 'scan-dispatch'):
        from ravel.physics import native_pipeline as native
        from ravel.paths import module_command
        from . import physics_review, stage_supervisor
        # Correction plans may be additional inputs of the approved stage. Each
        # candidate must still pass native plan and amendment approval checks.
        candidates = [native.approved_plan_path(root)]
        if kind == 'scan-dispatch' and '--plan' in command:
            index = command.index('--plan')
            if index + 1 < len(command):
                candidates.append(Path(command[index + 1]))
        candidates += [Path(p) for p in result.get('stage_spec', {}).get('inputs', [])
                       if str(p).endswith('.json')]
        plan = None
        for path in dict.fromkeys(candidates):
            path = (root / path).resolve() if not path.is_absolute() else path.resolve()
            if not path.is_relative_to(root) or not path.is_file():
                continue
            value = read_json(path)
            if not isinstance(value, dict) or value.get('plan_sha256') != result.get('plan_sha256'):
                continue
            plan = native.load_plan(path)
            native.verify_execution_approval(plan)
            if (Path(plan['rundir']).resolve() != root or Path(plan['plan_path']).resolve() != path
                    or plan['required_compute_plan'] != required_plan):
                raise ValueError('native reservation differs from its approved run, plan or compute rung')
            break
        if plan is None:
            raise ValueError('native reservation requires the exact approved execution plan')
        stages = [s['stage'] for s in plan['stages']]
        if kind == 'scan-dispatch':
            expected = module_command('ravel.physics.native_pipeline', 'run', '--plan', plan['plan_path'])
            if list(command) != expected or not set(stages) <= set(mode['bounds']['allowed_stages']):
                raise ValueError('native dispatcher command or stage scope differs from delegated authority')
            result.update(stage='scan-dispatch', max_seconds=0, events=plan['nevents'], resource_events=0,
                          resource_reservation='orchestration', resource_stages=stages)
            return result
        rows = [s for s in plan['stages'] if s['stage'] == result.get('stage')]
        if len(rows) != 1:
            raise ValueError('native reservation requires one approved stage')
        stage = rows[0]
        from . import execution
        expanded = execution.plan_stage(root, stage['stage'], stage['command'], stage['inputs'],
            stage['outputs'], stage['depends_on'], str(root))
        expected = physics_review._stage_spec(root, {**stage, 'inputs': expanded['inputs'], 'cwd': str(root),
            'log': str(native.log_root(plan) / (stage['stage'] + '.log'))})
        seconds = max(stage_supervisor.FLOOR_SECS,
                      stage_supervisor.stage_budget_min(stage['stage'], plan['nevents'])
                      * stage_supervisor.KILL_MARGIN * 60.0)
        if (list(command) != stage['command'] or result.get('stage_spec') != expected
                or result.get('max_seconds') != seconds or type(result.get('events')) is not int
                or result['events'] != plan['nevents']):
            raise ValueError('native stage command, scope or watchdog differs from the approved resource contract')
        result.update(max_seconds=seconds, resource_events=plan['nevents'] if stage['stage'] == 'madgraph' else 0)
        return result
    if kind == 'scoped-likelihood-stage':
        from . import scoped
        plan = scoped.verify_plan(root, require_approval=True)
        if (result.get('max_seconds') != plan['max_seconds'] or type(result.get('events')) is not int
                or result['events'] != 0):
            raise ValueError('scoped resource context differs from the approved plan')
        result['resource_events'] = 0
        return result
    if kind == 'scientific-stage' and result.get('stage_spec', {}).get('operation_resources'):
        # _capture also checks the typed solver's exact command, paths, and
        # authority. It declares zero generated events and a pinned time bound.
        from . import operation_resources
        spec = result['stage_spec']
        declaration = spec['operation_resources']
        operation_resources.authority(root, declaration, stage=result.get('stage'), command=command,
            cwd=spec['cwd'], inputs=spec['inputs'], outputs=spec['outputs'],
            events=result.get('events'), max_seconds=result.get('max_seconds'))
        result['resource_events'] = 0
        return result
    raise ValueError('autonomous launch requires a verified plan-derived resource contract')


def _prepare_popen_authorization(root, required_plan, command, context, *, _session=None):
    from . import operating_mode
    if _session is not None:
        _session.track(context)
    context = verified_resource_context(root, required_plan, command, context, _session=_session)
    if _session is not None:
        _session.track(command)
        _session.track(context)
    authorization = (_capture_science(root, required_plan, command, context, _session=_session)
                     if _session is not None else _capture(root, required_plan, command=command, context=context))
    if _session is not None:
        _session.track(authorization)
    event = {"event": "authorized", "command": command, "context": context,
             "authorization": authorization}
    # Historical checks reject empty/future-dated operational approval records.
    _historical_errors({**event, "utc": operational_utc(root)})
    with operating_mode.launch_reservation(root, command, context):
        event = _append(root, event)
    if "operation_inputs" in authorization:
        # Ordinary generic launches lack the science ValidationSession; keep the
        # typed solver context fresh after append and before any process starts.
        _historical_errors(event)
    pins = _authorization_pins(authorization)
    if any(_pin_changed(pin, _session) for pin in pins):
        raise ValueError("authorization evidence changed before Popen")
    return event


def _confinement_plan(root, command, context, confinement, kwargs):
    """The confined launch plan of this launch, a controller-side entry point record, or None.

    None is a legacy run the controller does not own. A controller-side entry point is one of
    RAVEL's own brokers (``confine.entry_point``), whose payloads are confined where they
    start. Planning refuses or holds before the authorization event is written.
    """
    from ravel.controller import confine
    if isinstance(confinement, confine.Plan):
        if confinement.argv != command or confinement.run_dir != Path(root).resolve():
            raise confine.ConfinementRefused("the confinement plan names another command or run; nothing was started")
        return confinement
    if isinstance(confinement, dict) and confinement.get("class") == "controller-side":
        registered = confine.entry_point(root, command)
        if registered is None or registered != confinement:
            raise confine.ConfinementRefused("an unregistered controller-side launch was refused; nothing was started")
        return registered
    if confinement is None and not _controller_run(root):
        return None
    broker = confine.entry_point(root, command)
    if broker is not None:
        return broker
    extras = dict(confinement or {})
    spec = confine.spec_for_stage(root, command, context=context, cwd=kwargs.get("cwd"), env=kwargs.get("env"),
                                  attempt_dir=extras.pop("attempt_dir", None), channels=extras.pop("channels", ()),
                                  limits=extras.pop("limits", None))
    if extras:
        raise ValueError("unknown confinement options: " + ", ".join(sorted(extras)))
    return confine.prepare(spec)


def _authorized_popen_locked(root, required_plan, command, *, context, confinement=None, **kwargs):
    plan = _confinement_plan(root, command, context, confinement, kwargs)
    if required_plan == "science":
        from . import science
        # This launch transaction ends before Popen. A worker starts its own
        # fresh admission; no cache is carried into another process or finish.
        with science._validation_scope(root) as session:
            event = _prepare_popen_authorization(root, required_plan, command, context, _session=session)
    else:
        event = _prepare_popen_authorization(root, required_plan, command, context)
    from ravel.controller import confine
    if plan is None:
        process = subprocess.Popen(command, **kwargs)
    elif isinstance(plan, dict):
        from ravel.controller.confine import brokers
        process = subprocess.Popen(command, **{**kwargs, "env": brokers.environment(kwargs.get("env"))})
    else:
        process = confine.start(plan, subprocess.Popen, **kwargs)
    record = plan if isinstance(plan, dict) else plan.record if plan is not None else None
    try:
        launched = _append(root, {"event": "launched", "authorization_sequence": event["sequence"],
                                 "authorization_sha256": event["sha256"], "pid": process.pid,
                                 **({"confinement": record} if record is not None else {})})
    except BaseException:
        try:
            if kwargs.get("start_new_session"):
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
        process.wait()
        if isinstance(plan, confine.Plan):
            confine.finish(plan)
        raise
    process.ravel_authorization = {"sequence": launched["sequence"], "sha256": launched["sha256"]}
    return process


def store_mirror_errors(root, events=None):
    """For a controller-owned run: the run-tree journal must equal the store's original events."""
    run_id = _controller_run(root)
    if not run_id:
        return []
    from ravel.controller.confine import runs
    stored = []
    for row in runs.store(run_id).scan(STORE_KIND):
        value = row.get("record", row) if isinstance(row, dict) else None
        if isinstance(value, dict):
            stored.append(value.get("sha256"))
    local = [e["sha256"] for e in (_events(root) if events is None else events)]
    if local != stored:
        return ["the run-tree launch journal differs from the controller store's original events"]
    return []


def audit_launches(root, *, plan_sha256=None, require_generation=False, require_science=False):
    try:
        events = _events(root)
        mirror = store_mirror_errors(root, events)
        if mirror:
            raise ValueError(mirror[0])
        authorized, launches, started = {}, [], {}
        for event in events:
            if type(event.get("schema_version")) is not int or event["schema_version"] != 1:
                raise ValueError("invalid authorization event schema")
            if event.get("event") == "authorized":
                _historical_errors(event)
                authorized[event["sequence"]] = event
            elif event.get("event") == "launched":
                sequence = event.get("authorization_sequence")
                if type(sequence) is not int or sequence not in authorized:
                    raise ValueError("launch has no earlier authorization event")
                auth = authorized[sequence]
                if event.get("authorization_sha256") != auth["sha256"] or type(event.get("pid")) is not int or event["pid"] <= 0:
                    raise ValueError("launch authorization digest or process identity is invalid")
                launches.append(auth)
                started[event["sequence"]] = (event, auth)
            else:
                raise ValueError("unknown authorization event")
        ledger = Path(root) / "execution_state.json"
        if ledger.exists():
            for stage, record in read_json(ledger)["stages"].items():
                if record.get("child_pid") is None:
                    continue
                receipt = record.get("authorization_receipt")
                if not isinstance(receipt, dict) or receipt.get("sequence") not in started:
                    raise ValueError(f"stage {stage} has no retained launch authorization")
                event, auth = started[receipt["sequence"]]
                if (receipt.get("sha256") != event["sha256"] or record["child_pid"] != event["pid"]
                        or auth["command"] != record["command"] or auth["context"].get("stage") != stage):
                    raise ValueError(f"stage {stage} launch authorization disagrees with its execution receipt")
        bulk = [e for e in launches if e["authorization"]["required_plan"] in (("science",) if require_science else ("full", "scan"))]
        if plan_sha256 is not None:
            bulk = [e for e in bulk if e["context"].get("plan_sha256") == plan_sha256]
        if require_generation:
            bulk = [e for e in bulk if e["context"].get("kind") == "native-generation"
                    or e["context"].get("stage") == "madgraph"]
        if not bulk:
            raise ValueError("recorded bulk compute has no matching launch-time authorization receipt; a later GO cannot backfill it")
        return []
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        return [str(exc)]


def audit_scan_launches(root, manifest, scan):
    """An aggregate has no process of its own; audit every reported point's receipts."""
    try:
        from . import workflow_state as ws
        from .result_pack import _repo_root
        points, results = manifest["points"], scan["points"]
        if not isinstance(points, list) or not points or not isinstance(results, list):
            raise ValueError("scan authorization needs nonempty manifest points and a result list")
        by_tag = {}
        for point in points:
            if not isinstance(point, dict) or not isinstance(point.get("tag"), str) or point["tag"] in by_tag:
                raise ValueError("scan manifest needs distinct string point tags")
            by_tag[point["tag"]] = point
        # Audit the complete declared population, including explicit missing/failed
        # points. Only completed result rows need a launch history below.
        population = scan.get('point_population', results)
        if not isinstance(population, list):
            raise ValueError('scan point population must be a list')
        members = {}
        for row in population:
            tag = row.get('tag') if isinstance(row, dict) else None
            if not isinstance(tag, str) or tag not in by_tag or tag in members:
                raise ValueError('scan population has a missing, duplicate or unmanifested point tag')
            members[tag] = row
        seen, paths, errors = set(), set(), []
        omitted = sorted(set(by_tag) - set(members))
        if omitted:
            errors.append('scan result omits manifest point(s) ' + ', '.join(omitted))
        if 'point_population' in scan:
            unresolved = sorted(tag for tag, row in members.items() if row.get('status') != 'completed')
            if unresolved and (scan.get('n_missing') == 0 or scan.get('missing_tags') == []):
                errors.append('scan claims full coverage while point(s) ' + ', '.join(unresolved) + ' are unresolved')
            result_tags = {r.get('tag') for r in results if isinstance(r, dict) and isinstance(r.get('tag'), str)}
            absent = sorted(tag for tag, row in members.items()
                            if row.get('status') == 'completed' and tag not in result_tags)
            if absent:
                errors.append('scan completed population has no result row for point(s) ' + ', '.join(absent))
        for row in results:
            tag = row.get("tag") if isinstance(row, dict) else None
            if not isinstance(tag, str) or tag not in by_tag or tag in seen:
                raise ValueError("scan result has a missing, duplicate or unmanifested point tag")
            seen.add(tag)
            if 'point_population' in scan and (tag not in members or members[tag].get('status') != 'completed'):
                errors.append('scan result includes point ' + tag + ' that its population does not record as completed')
            value = by_tag[tag].get("run_dir")
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"scan point {tag} needs a run_dir")
            path = Path(value)
            if not path.is_absolute():
                path = Path(_repo_root(root)) / path
            path = path.resolve()
            if path == Path(root).resolve():
                raise ValueError("scan aggregate cannot stand in for its point's launch history")
            if path in paths:
                raise ValueError("distinct scan points cannot reuse one run's launch history")
            paths.add(path)
            from .scan_orchestrator import point_attempt_root
            plan = read_json(point_attempt_root(by_tag[tag], path) / "inputs/native_execution_plan.json")
            if plan.get("required_compute_plan") not in ("full", "scan"):
                raise ValueError(f"scan point {tag} has no recorded bulk compute plan")
            errors += [f"point {tag}: {e}" for e in [*ws.verify_checkin2_go(str(path)),
                        *audit_launches(path, plan_sha256=plan["plan_sha256"], require_generation=True)]]
        return errors
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return [f"scan launch authorization unavailable: {exc}"]
