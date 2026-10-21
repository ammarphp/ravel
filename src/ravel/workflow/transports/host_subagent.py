"""Host-subagent adapter: RAVEL running inside a host (Claude Code, Codex, Gemini CLI, opencode).

The host spawns its own subagent; RAVEL never launches it and sees only what the host
reports. ``brief`` writes the work packet the host's subagent follows (the role, its
workspace, the toolbelt names and the broker socket for ``ravel work call``) and pins the
toolbelt in custody. ``serve_broker`` keeps the broker open while the subagent works. It
is built by the shared ``tool_gate.production_broker`` over that pinned toolbelt, so the
brief lists exactly the tools the broker serves, every call passes the gate, and every
tool output still counts only through a broker receipt. ``complete`` writes the worker receipt from
the host-reported final record. When the run pins a project instruction document, the brief
carries its text for the subagent to read first. The receipt records the brief and the sha256
the host reported back; it shows delivery only when that report names the pinned document.

These routes are never blind-capable and never serve a voting or blind role: the host's
own tool policy is the only boundary (``cli-policy``), user configuration is loaded, and
the receipt is ``host_attested`` at most.

Live steering is decided at the handoff. ``brief`` is refused while a pause, a veto or a hold
blocks the node. RAVEL does not observe the host's spawn and cannot serialize it, so the
working window is what it admits: ``serve_broker`` takes the final steering check under the
steering lock, records the admitted start in custody (the host-side start acknowledgement)
and keeps the subagent registered as running work while the broker is open, so a later pause
finds it draining. ``complete`` writes a receipt only for an attempt with that record; a
subagent the host started outside an admitted window earns none.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy

from .. import broker, project_instructions, transport_registry as tr
from ..state_io import atomic_json
from .cli_worker import LaunchRefused, _card, _refuse, toolbelt_for


def unsupported(document):
    """Why this adapter cannot serve the declaration (None when it can)."""
    if document['transport_kind'] != 'host-subagent':
        return 'transport_kind:' + document['transport_kind']
    if document['capabilities']['blind_capable']:
        return 'blind_capable:host-subagent'
    return None


def _refuse_review(card, spec):
    from ..agent_worker import blind_roles
    if tr.is_voting(card):
        _refuse('isolation', 'a voting role needs a sandbox-isolated worker; a host subagent runs under host policy')
    if (card.get('requires') or {}).get('blind') or spec['role']['id'] in blind_roles():
        _refuse('blind', 'a host subagent is never blind')


START_SUFFIX = '.host-start.json'


def _steering_refused(reason):
    raise LaunchRefused(f'host subagent refused: steering ({reason})', ['steering'])


def _start_path(run, spec):
    from .. import agent_worker
    return broker.custody(run) / (agent_worker._key(spec['node_id'], spec['attempt']) + START_SUFFIX)


def _brief_sha256(packet):
    return broker.digest(packet)


def _document(transport_id):
    document = tr.load(transport_id)
    problem = unsupported(document)
    if problem:
        _refuse(problem)
    return document


def brief(rundir, spec, workspace, *, transport_id, card=None):
    """Write the host work packet into custody and ``inputs/host-brief.json``; return it."""
    from .. import agent_worker
    run = broker.ordinary(rundir)
    spec = agent_worker._validate(spec)
    ws = broker.ordinary(workspace)
    if ws != agent_worker.workspace(run, spec['node_id'], spec['attempt']):
        _refuse('workspace', 'not this attempt\'s workspace')
    document = _document(transport_id)
    card = _card(spec, card)
    _refuse_review(card, spec)
    from .. import toolbelt
    try:
        belt = toolbelt_for(card, document, False)
    except toolbelt.ToolbeltError as exc:
        raise LaunchRefused(f'host subagent refused: toolbelt:{exc}', ['toolbelt']) from None
    # Only tools whose broker action the production broker registers are listed.
    tools = [t['name'] for t in belt['tools'] if t['executes_through']['action'] in (*toolbelt.EXECUTABLE_ACTIONS, toolbelt.CHECK_ACTION)]
    socket_path = broker.Broker(run, ws, node_id=spec['node_id'], attempt=spec['attempt'], allowed_actions=[],
                                max_calls=0).socket_path
    packet = {'schema_version': 1, 'kind': 'host-subagent-brief', 'transport_id': document['id'],
              'declaration_sha256': tr.declaration_sha256(document), 'node_id': spec['node_id'],
              'attempt': spec['attempt'], 'role': spec['role'], 'workspace': str(ws),
              'broker_socket': str(socket_path), 'call': 'ravel work call --socket <broker_socket> --request <file>',
              'tools': tools, 'toolbelt_manifest_sha256': belt['manifest_sha256'],
              'declared_outputs': spec['declared_outputs'], 'final_record_schema': spec['final_record_schema'],
              'budgets': spec['budgets'], 'attestation': 'host_attested', 'isolation': 'cli-policy'}
    packet.update({'rundir': str(run), 'subject': subject_for(spec),
                   'spec_sha256': broker.digest(spec), 'role_card': deepcopy(card)})
    try:
        declared = project_instructions.for_packet(project_instructions.for_run(run))
    except project_instructions.ProjectInstructionsError as exc:
        raise LaunchRefused(str(exc), exc.missing) from None
    if declared is not None:
        packet['project_instructions'] = declared
    target = ws / 'inputs' / 'host-brief.json'
    from .. import gate_wiring
    try:
        # The handoff is a dispatch: nothing is handed to the host while steering blocks the node.
        with gate_wiring.steering_dispatch(run, spec['node_id']):
            if not target.exists():
                atomic_json(target, packet)
                target.chmod(0o400)
            key = agent_worker._key(spec['node_id'], spec['attempt'])
            atomic_json(broker.custody(run) / (key + '.host-toolbelt.json'), belt)
            atomic_json(broker.custody(run) / (key + '.host-brief.json'), packet)
    except gate_wiring.SteeringRefused as exc:
        _steering_refused(exc)
    return packet


@contextmanager
def serve_broker(rundir, spec, packet):
    """Keep this attempt's broker open for ``ravel work call`` while the host subagent works."""
    from .. import agent_worker
    from .. import toolbelt
    from ..state_io import read_json
    from ..tool_gate import production_broker
    run = broker.ordinary(rundir)
    ws = agent_worker.workspace(run, spec['node_id'], spec['attempt'])
    key = agent_worker._key(spec['node_id'], spec['attempt'])
    belt = read_json(broker.custody(run) / (key + '.host-toolbelt.json'))
    if (toolbelt.manifest_sha256(belt) != belt.get('manifest_sha256')
            or belt['manifest_sha256'] != packet['toolbelt_manifest_sha256']):
        _refuse('toolbelt:changed')
    tools = [t for t in belt['tools'] if t['name'] in set(packet['tools'])]
    if sorted(packet['tools']) != sorted(t['name'] for t in tools):
        _refuse('toolbelt:changed')
    from .. import literature_settings
    # Literature serving comes only from the installation settings this process reads.
    tool_broker = production_broker(run, ws, tools=tools, role=spec['role']['id'], node_id=spec['node_id'],
                                    attempt=spec['attempt'], max_calls=spec['budgets']['max_broker_calls'],
                                    retrieval=literature_settings.for_tools(tools))
    from contextlib import ExitStack
    from .. import gate_wiring
    with ExitStack() as window:
        try:
            # The start of the working window is admitted under the steering lock and stays
            # registered as running work until the broker closes.
            identifier = window.enter_context(
                gate_wiring.steering_admitted(run, spec['node_id'], role='host-subagent'))
        except gate_wiring.SteeringRefused as exc:
            _steering_refused(exc)
        # The start acknowledgement: RAVEL admitted this window; it did not observe the host's spawn.
        atomic_json(_start_path(run, spec), {
            'schema_version': 1, 'kind': 'host-subagent-start', 'node_id': spec['node_id'],
            'attempt': spec['attempt'], 'transport_id': packet['transport_id'],
            'brief_sha256': _brief_sha256(packet), 'admission_id': identifier,
            'steering_epoch': gate_wiring.steering_state(run)['epoch'], 'admitted_utc': broker.utc(),
            'host_spawn_observed': False})
        window.enter_context(broker.serve(tool_broker))
        yield tool_broker


def complete(rundir, spec, packet, *, final, instructions_sha256=None):
    """The worker receipt for a host-reported final record; never more than ``host_attested``.

    ``instructions_sha256`` is the host's report of the project instruction document its subagent
    read (the sha256 printed in the brief). A run that pins a document credits the session only
    when that report names the pinned document; the brief alone shows that RAVEL prepared the text.
    """
    from .. import agent_worker
    document = _document(packet['transport_id'])
    if packet['declaration_sha256'] != tr.declaration_sha256(document):
        _refuse('declaration:changed')
    from ..state_io import read_json
    run = broker.ordinary(rundir)
    dispatch_path = broker.custody(run) / (agent_worker._key(spec['node_id'], spec['attempt']) + '.role-dispatch.json')
    if dispatch_path.is_file():
        dispatch_record = read_json(dispatch_path)
        advisory = dispatch_record['identity']['mode'] == 'advisory'
        raise LaunchRefused('host subagent refused: ' + ('advisory' if advisory else 'refused host')
                            + ' dispatch cannot become a required-role receipt',
                            ['advisory' if advisory else 'role_dispatch'])
    start = _start_path(run, spec)
    acknowledged = read_json(start) if start.is_file() and not start.is_symlink() else None
    # A host may hand back the packet without the instruction record; the start is then matched
    # against the packet with the record RAVEL kept in custody, so any other change still refuses.
    kept_brief = broker.custody(rundir) / (agent_worker._key(spec['node_id'], spec['attempt']) + '.host-brief.json')
    admitted = packet
    if 'project_instructions' not in packet and kept_brief.is_file() and not kept_brief.is_symlink():
        kept_record = read_json(kept_brief).get('project_instructions')
        if kept_record is not None:
            admitted = {**packet, 'project_instructions': kept_record}
    if (type(acknowledged) is not dict or acknowledged.get('kind') != 'host-subagent-start'
            or acknowledged.get('node_id') != spec['node_id'] or acknowledged.get('attempt') != spec['attempt']
            or acknowledged.get('brief_sha256') != _brief_sha256(admitted)):
        # No admitted start for this attempt and brief: the work ran outside a steering-admitted
        # window, so no receipt is written for it.
        raise LaunchRefused('host subagent refused: steering (no admitted start is recorded for this attempt; '
                            'open its broker under live steering before the subagent works)', ['steering'])
    execution = {'exit_status': 0, 'attestation': 'host_attested',
                 'transport': {'id': document['id'], 'transport_kind': 'host-subagent',
                               'declaration_sha256': packet['declaration_sha256'], 'probe_sha256': None,
                               'host_reported': True, 'receipt': None},
                 'isolation': {'profile': 'cli-policy', 'user_configuration_loaded': True,
                               'evidence': {'confirmed': False, 'basis': 'host-reported; RAVEL observed no process'}},
                 'model': {'requested': None, 'observed': None, 'family': None, 'effort': None}}
    # The delivery record comes from the brief RAVEL kept in custody, not from the packet handed back.
    kept = broker.custody(rundir) / (agent_worker._key(spec['node_id'], spec['attempt']) + '.host-brief.json')
    if kept.is_file():
        from ..state_io import read_json
        declared = read_json(kept).get('project_instructions')
        if declared is not None:
            execution['transport']['project_instructions'] = project_instructions.acknowledged(
                declared['record'], instructions_sha256)
    return agent_worker.finish(rundir, spec, final=deepcopy(final), execution=execution)


__all__ = ['LaunchRefused', 'brief', 'complete', 'serve_broker', 'unsupported',
           'subject_for', 'dispatch_role', 'dispatch_parser', 'main']


def subject_for(spec):
    """The exact review subject, sealed work order, or otherwise the pinned spec."""
    from .. import agent_worker
    spec = agent_worker._validate(spec)
    if spec['parent'].get('review_subject') is not None:
        return deepcopy(spec['parent']['review_subject'])
    if spec['work_order']:
        return {'scope': spec['work_order']['path'], 'sha256': spec['work_order']['sha256']}
    return {'scope': 'worker-spec', 'sha256': broker.digest(spec)}


def dispatch_role(rundir, spec, *, node_id, role, subject, adapter=None,
                  mode='required', parent_session_id=None, **worker_options):
    """Dispatch one exactly bound role; never execute it in the caller's context.

    CLI workers use the existing governed supervisor. A host delegate may produce
    an explicitly advisory result only: its schema and reported child identity
    establish neither confinement nor independent-review credit. Blind/voting
    cards refuse even advisory host execution before any packet is exposed.
    """
    from .. import agent_worker, gate_wiring, role_registry
    from ..state_io import file_lock, read_json
    from .generic_delegate import DelegateAdapter, NativeDelegateAdapter
    spec = agent_worker._validate(spec)
    run = broker.ordinary(rundir)
    card = _card(spec, None)
    if (node_id != spec['node_id'] or role != card['id'] or spec['role']['version'] != card['version']
            or subject != subject_for(spec)
            or mode not in ('required', 'advisory')):
        raise LaunchRefused('role dispatch refused: run/node/role/subject binding mismatch', ['binding'])
    key = agent_worker._key(node_id, spec['attempt'])
    identity = {'rundir': str(run), 'node_id': node_id, 'attempt': spec['attempt'],
                'role': role, 'subject': deepcopy(subject), 'spec_sha256': broker.digest(spec),
                'mode': mode, 'adapter': deepcopy(adapter.identity) if isinstance(adapter, (DelegateAdapter, NativeDelegateAdapter)) else None,
                'parent_session_id': parent_session_id,
                'packet': agent_worker._packet_binding(worker_options.get('packet')),
                'protected': sorted(str(broker.ordinary(p)) for p in worker_options.get('protected', ())),
                'effect': agent_worker._effect_binding(worker_options.get('effect')),
                'graph': deepcopy(worker_options.get('graph')),
                'framework_step': worker_options.get('framework_step')}
    target = broker.custody(run) / (key + '.role-dispatch.json')

    def result(status, *, missing=(), receipt=None, final=None, session_id=None, detail=None, request_sha256=None):
        return {'schema_version': 1, 'kind': 'role-dispatch-result', **deepcopy(identity),
                'status': status, 'label': 'ADVISORY - REQUIRED ROLE NOT SATISFIED' if status == 'advisory'
                else 'ROLE DISPATCH ' + status.upper(), 'missing': list(missing),
                'required_role_satisfied': bool(status == 'completed' and receipt and receipt['status'] == 'ok'),
                'worker_receipt': receipt, 'advisory_result': final, 'session_id': session_id,
                'request_sha256': request_sha256 if request_sha256 is not None else
                receipt.get('request_sha256') if receipt else None,
                'attestation': receipt.get('attestation') if receipt else 'host_attested' if adapter is not None else None,
                'isolation': deepcopy(receipt.get('isolation')) if receipt else
                {'profile': 'cli-policy', 'user_configuration_loaded': True,
                 'evidence': {'confirmed': False, 'basis': 'host report; no confinement observed'}}
                if adapter is not None else None,
                'detail': detail}

    def refusal(*, missing, detail=None):
        outcome = result('refused', missing=missing, detail=detail)
        atomic_json(target, {'identity': identity, 'result': outcome})
        return outcome

    # A single reservation for this run/node/attempt, also across concurrent hosts.
    # A reserved/ambiguous call is never automatically invoked again.
    with file_lock(target.with_suffix('.lock')):
        if target.exists():
            kept = read_json(target)
            if kept['identity'] != identity:
                raise LaunchRefused('role dispatch refused: attempt already bound differently', ['binding'])
            if kept['result'] is not None and adapter is not None:
                return kept['result']
            if adapter is not None:
                return result('ambiguous', missing=['reconciliation'], detail='dispatch reserved; do not repeat the host call')
        with gate_wiring.steering_dispatch(run, node_id):
            if broker.stop_mode(run):
                return refusal(missing=['stop_requested'])
            if adapter is not None and not isinstance(adapter, (DelegateAdapter, NativeDelegateAdapter)):
                return refusal(missing=['delegate:contract'])
            routes = [tr.load(t) for t in spec['transport_preference']]
            host_routes = [d for d in routes if d['transport_kind'] == 'host-subagent']
            if adapter is None and host_routes and len(host_routes) == len(routes):
                return refusal(missing=['delegate:unavailable'])
            if adapter is not None:
                if (set(worker_options) - {'graph', 'framework_step', 'packet', 'protected', 'effect', 'wait'}
                        or worker_options.get('wait', True) is not True):
                    return refusal(missing=['delegate:worker_options'])
                transport_id = 'host-subagent-' + adapter.host
                if transport_id not in spec['transport_preference']:
                    return refusal(missing=['transport_preference'])
                document = _document(transport_id)
                caps, reasons = tr.effective_capabilities(document, None)
                missing = tr.unmet(document, caps, card) + reasons
                # A host callback never proves that it is outside the parent's
                # conversation, even if a future card needs only host attestation.
                if mode == 'required':
                    return refusal(missing=sorted(set(missing + ['independence:unproven'])))
                try:
                    _refuse_review(card, spec)
                except LaunchRefused as exc:
                    return refusal(missing=exc.missing, detail=str(exc))
                if not parent_session_id or type(parent_session_id) is not str:
                    return refusal(missing=['parent_session_id'])
            elif mode == 'advisory':
                return refusal(missing=['delegate:unavailable'])
            atomic_json(target, {'identity': identity, 'result': None, 'reserved_utc': broker.utc()})

    invoked = False
    try:
        if adapter is None:
            receipt = agent_worker.dispatch(run, spec, **worker_options)
            failure = receipt.get('failure') or {}
            outcome = result('completed' if receipt['status'] == 'ok' else receipt['status'], receipt=receipt,
                             missing=failure.get('missing', ()), detail=failure.get('detail'))
        else:
            ws = agent_worker.materialize(run, spec,
                                          **{k: v for k, v in worker_options.items() if k != 'wait'})
            packet = brief(run, spec, ws, transport_id=transport_id, card=card)
            request = {'schema_version': 1, 'kind': 'role-dispatch-request', 'rundir': str(run),
                       'node_id': node_id, 'attempt': spec['attempt'], 'role': role,
                       'subject': deepcopy(subject), 'spec_sha256': broker.digest(spec),
                       'brief': packet, 'role_card': card}
            request_sha = broker.digest(request)
            with serve_broker(run, spec, packet):
                invoked = True
                response = adapter.invoke(request)
            if response['request_sha256'] != request_sha or response['session_id'] == parent_session_id:
                raise ValueError('host response does not bind this request and a distinct child')
            # A claimed child cannot fill multiple seats in this run. This ledger
            # records host reports, not authenticated independence or actor credit.
            with file_lock(broker.custody(run) / 'role-dispatch-sessions.lock'):
                sessions_path = broker.custody(run) / 'role-dispatch-sessions.json'
                sessions = read_json(sessions_path) if sessions_path.exists() else []
                if response['session_id'] in sessions:
                    raise ValueError('host reused a child session for another role attempt')
                atomic_json(sessions_path, sessions + [response['session_id']])
            if not agent_worker.FINAL_SCHEMAS[spec['final_record_schema']](response['final']):
                raise ValueError('host final record does not match the required schema')
            declared = packet.get('project_instructions')
            if declared and response['instructions_sha256'] != declared['record']['sha256']:
                raise ValueError('host did not acknowledge the pinned project instructions')
            # No finish()/acceptance receipt: advisory work can never be adopted as
            # the required role, including when its broker produced valid outputs.
            outcome = result('advisory', missing=sorted(set(missing + ['independence:unproven'])),
                             final=response['final'], session_id=response['session_id'], request_sha256=request_sha)
    except LaunchRefused as exc:
        outcome = (result('ambiguous', missing=['reconciliation'], detail='delegate returned an invalid completion; do not retry')
                   if invoked else result('refused', missing=exc.missing, detail=str(exc)))
    except Exception:
        # No retry: invocation or completion may have happened. Do not retain
        # host exception text, which can contain provider bodies or credentials.
        outcome = result('ambiguous', missing=['reconciliation'], detail='dispatch completion unknown; explicit reconciliation required')
    with file_lock(target.with_suffix('.lock')):
        atomic_json(target, {'identity': identity, 'result': outcome})
    return outcome


def dispatch_parser():
    """The same concrete parser used by redirects and the public CLI bridge."""
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description='Dispatch one exactly bound RAVEL role')
    parser.add_argument('command', choices=['dispatch'])
    parser.add_argument('--rundir', type=Path, required=True)
    parser.add_argument('--node', required=True)
    parser.add_argument('--role', required=True)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--subject', type=Path, required=True)
    return parser


def main(argv=None):
    import json
    from ..state_io import read_json
    args = dispatch_parser().parse_args(argv)
    try:
        value = dispatch_role(args.rundir, read_json(args.spec), node_id=args.node, role=args.role,
                              subject=read_json(args.subject))
    except (OSError, ValueError) as exc:
        print(json.dumps({'kind': 'role-dispatch-error', 'status': 'refused', 'detail': str(exc)}))
        return 1
    print(json.dumps(value, indent=2, allow_nan=False))
    return 0 if value['required_role_satisfied'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
