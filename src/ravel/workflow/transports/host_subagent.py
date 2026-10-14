"""Host-subagent adapter: RAVEL running inside a host (Claude Code, Codex, Gemini CLI, opencode).

The host spawns its own subagent; RAVEL never launches it and sees only what the host
reports. ``brief`` writes the work packet the host's subagent follows (the role, its
workspace, the toolbelt names and the broker socket for ``ravel work call``) and pins the
toolbelt in custody. ``serve_broker`` keeps the broker open while the subagent works. It
is built by the shared ``tool_gate.production_broker`` over that pinned toolbelt, so the
brief lists exactly the tools the broker serves, every call passes the gate, and every
tool output still counts only through a broker receipt. ``complete`` writes the worker receipt from
the host-reported final record.

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

from .. import broker, transport_registry as tr
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
    tool_broker = production_broker(run, ws, tools=tools, role=spec['role']['id'], node_id=spec['node_id'],
                                    attempt=spec['attempt'], max_calls=spec['budgets']['max_broker_calls'])
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


def complete(rundir, spec, packet, *, final):
    """The worker receipt for a host-reported final record; never more than ``host_attested``."""
    from .. import agent_worker
    document = _document(packet['transport_id'])
    if packet['declaration_sha256'] != tr.declaration_sha256(document):
        _refuse('declaration:changed')
    from ..state_io import read_json
    run = broker.ordinary(rundir)
    start = _start_path(run, spec)
    acknowledged = read_json(start) if start.is_file() and not start.is_symlink() else None
    if (type(acknowledged) is not dict or acknowledged.get('kind') != 'host-subagent-start'
            or acknowledged.get('node_id') != spec['node_id'] or acknowledged.get('attempt') != spec['attempt']
            or acknowledged.get('brief_sha256') != _brief_sha256(packet)):
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
    return agent_worker.finish(rundir, spec, final=deepcopy(final), execution=execution)


__all__ = ['LaunchRefused', 'brief', 'complete', 'serve_broker', 'unsupported']
