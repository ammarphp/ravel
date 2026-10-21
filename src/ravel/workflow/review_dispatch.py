"""Dispatcher-observed evidence for independent review credit: the default resolver.

``review_independence.decide`` grants independent credit only on evidence from the
dispatch itself. This module derives that evidence from records RAVEL's own dispatchers
write while they dispatch, never from a run file, a role's output or a declaration:

- governed CLI worker: the worker dispatcher's custody record of the supervised launch,
  the receipt it wrote and registered (transport-verified label, assigned actor), the
  role projection it copied into the workspace and the sandbox denial evidence its
  supervisor observed;
- graph model role: the record the graph runner writes when the node completes
  (``record_graph``), pinning that attempt's receipt, request, packet and transport
  observation outside the graph and run trees.

A receipt written straight into the run tree, a registration without a supervised launch,
a host-subagent or relay report, a declared reviewer name and a control transport have no
such evidence, so the review stays advice. The evidence is re-read at every decision.

These records lie outside the run tree and every worker sandbox: no reviewer and no agent
editing run files can write them. They are written by processes of the same OS user, and an
unsandboxed process of that user can still write them (docs/reference/transports.md), so the
evidence they give is labelled ``same_user_state``, never ``controller_store``. A host with a
stronger boundary installs its own resolver through ``review_independence.authority_session``,
which replaces this one.

For a run the controller owns, ``store_lookup`` is the only resolver: the controller appends a
``review-session`` record for every seat session it starts (``record_session``) and a
``review-output`` record for every review output it observes (``record_review``) to the run's
protected store, and the decision reads nothing else. A host-mediated, relay or one-shot session
never holds a seat there.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .review_independence import CONTROLLER_STORE, SAME_USER_STATE
from .transport_registry import CONTROLLER_SEATLESS

STORE = 'review-dispatch'
RECORD_KIND = 'graph-role-dispatch'
OBSERVED = frozenset({'remote_transport_observed', 'local_transport_observed', 'transport_attested_cli'})
PARENT = 'parent-conversation:'
# The packet layouts of the four RAVEL projection producers, recognised by their own closed fields.
PROJECTION = 'ravel.workflow.review_projection'
JUDGMENT = 'ravel.workflow.scientific_judgment'
PROTOCOL = 'ravel.workflow.research_protocol'
RDJ = 'ravel.workflow.rdj_loop'
RDJ_EDGE_ROLE, RDJ_PAYLOAD = 'rdj_edge_reviewer', 'rdj-payload'
SESSION_KIND, REVIEW_KIND = 'review-session', 'review-output'
SESSION_FIELDS = frozenset({'session_id', 'seat', 'step_id', 'role', 'card_id', 'role_kind', 'actor_id', 'model',
                            'transport_id', 'transport_kind', 'fresh', 'parent_transcript_supplied'})
REVIEW_FIELDS = frozenset({'binding', 'seat', 'session_id', 'dispatch_id', 'packet', 'read_boundary',
                           'read_boundary_verified', 'exposure', 'exposure_verified', 'output_unmodified',
                           'subject_session_ids'})
# Transports whose fresh context and blinding are the delivering host's own statement: never a seat.
SEATLESS_TRANSPORTS = frozenset(CONTROLLER_SEATLESS)


def _same_card(first, second):
    """Role names compared through the one generated name-to-card mapping (``role_registry.same_card``)."""
    from .role_registry import same_card
    return same_card(first, second)


def _digest(value):
    from .review_independence import digest
    return digest(value)


def _store():
    from . import machine_lease
    return Path(machine_lease.machine_state_root()) / STORE / 'graphs'


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('record is absent')
    return json.loads(path.read_text(encoding='utf-8'))


def builder(manifest):
    """The RAVEL producer of a role packet, recognised from its manifest layout, or None."""
    if type(manifest) is not dict:
        return None
    kind = manifest.get('kind')
    ids = {a.get('id') for a in manifest.get('artifacts') or [] if type(a) is dict}
    if kind == 'review-projection':
        return PROJECTION
    if kind == 'rdj_role_packet_v1':
        return RDJ
    if kind is None and str(manifest.get('cycle_id', '')).startswith('protocol:'):
        return PROTOCOL
    if kind is None and 'judgment_request' in ids and 'source_event_sha256' in manifest:
        return JUDGMENT
    return None


def _manifest(packet):
    """The authenticated manifest of a bound packet, or None."""
    from . import review_context
    if type(packet) is not dict or set(packet) != {'path', 'manifest_sha256'}:
        return None
    try:
        index = review_context._PacketIndex(packet['path'], packet['manifest_sha256'])
        manifest = deepcopy(index.manifest)
        index.finish()
    except (OSError, ValueError, TypeError):
        return None
    return manifest


def exposure(manifest, role):
    """What each exposure dimension of this packet is under its producer's projection policy.

    Author identity is never anonymized by these projections. Producer interpretation is
    withheld where the policy removes headlines; peer verdicts where the policy removes them
    or the role precedes them. Reference values are ordinary review evidence unless withheld.
    """
    kind = builder(manifest)
    forbidden = set(manifest.get('forbidden_inputs') or [])
    if kind == PROJECTION:
        return {'author_identity': 'permitted',
                'author_rationale': 'withheld' if 'producer_headline' in forbidden else 'permitted',
                'reference_values': 'permitted',
                'peer_verdicts': 'withheld' if 'other_verdicts' in forbidden else 'permitted'}
    if kind == RDJ:
        # The RDJ projection drops author objects and edge-review reasons, keeps public rationale.
        return {'author_identity': 'withheld', 'author_rationale': 'permitted',
                'reference_values': 'permitted', 'peer_verdicts': 'permitted'}
    if kind == JUDGMENT:
        reviews = manifest.get('reviews') or []
        return {'author_identity': 'permitted', 'author_rationale': 'permitted', 'reference_values': 'permitted',
                'peer_verdicts': 'permitted' if reviews or role == 'synthesizer' else 'withheld'}
    if kind == PROTOCOL:
        # Previous actual role feedback is retained; the current peer meta-response is withheld.
        return {'author_identity': 'permitted', 'author_rationale': 'permitted', 'reference_values': 'permitted',
                'peer_verdicts': 'permitted'}
    return None


def _subjects(manifest):
    return {s for a in manifest.get('artifacts') or [] if type(a) is dict
            for s in (a.get('sha256'), a.get('source_sha256')) if type(s) is str}


# ---------------------------------------------------------------- graph producer

def controller_attestation(observed):
    """The attestation a protected controller observation supports, from the dispatcher's own evidence only.

    A worker's transport claims never count here. The observation's ``transport_evidence`` (the dispatcher's
    record of the transport and its execution mode) and ``isolation`` (freshness derived solely from the
    dispatcher's launch observation, ``controller.step.graph._observed_isolation``) decide: an HTTP transport the
    dispatcher observed, or a CLI launch whose recorded launch context proved a fresh session without a parent
    transcript, is ``transport_attested``; anything else, including an observation without that evidence, is
    ``self_attested``.
    """
    from .agent_graph import observation_for
    if type(observed) is not dict:
        return 'self_attested'
    transport = observed.get('transport_evidence') or {}
    isolation = observed.get('isolation') or {}
    mode = transport.get('execution_mode')
    fresh = (isolation.get('fresh_request') is True and isolation.get('parent_transcript_supplied') is False)
    if mode == 'transport_attested_cli':
        launch = isolation.get('launch_context') or {}
        return 'transport_attested' if (fresh and launch.get('fresh_session') is True
                                        and launch.get('no_parent_transcript_channel') is True) else 'self_attested'
    if observation_for(mode) in {'remote_transport_observed', 'local_transport_observed'} and fresh:
        return 'transport_attested'
    return 'self_attested'


def _controller_evidence(binding):
    """Resolve only the protected controller's exact call, step observation and adopted output, or None."""
    from . import research_controller as controller
    try:
        with controller._LOCK:
            store = controller._STORES.get(binding['run_id'])
        if store is None:store = controller._service('store').RunStore(binding['run_id'])
        if Path(store.path()).resolve().is_relative_to(Path(binding['graph_root']).resolve()):return None
        calls = [row for row in controller._rows(store, 'research-call')
                 if row['request']['request_id'] == binding['request_id']]
        if len(calls) != 1:return None
        call = calls[0]; observed = call['observation']; transport = observed.get('transport_evidence') or {}
        if Path(store.path()).resolve().is_relative_to(Path(call['run_dir']).resolve()):return None
        packet = call['node'].get('packet') or {}
        boundary=(observed.get('isolation') or {}).get('packet_read_boundary') or {}
        subject=boundary.get('subject_sha256')
        if subject is not None:
            inputs=call['node'].get('inputs')
            if (call.get('worker_packet_subject_sha256')!=subject
                    or (call.get('worker_packet') or {}).get('manifest_sha256')!=boundary.get('packet_sha256')
                    or call['node'].get('role')!=RDJ_EDGE_ROLE or packet or type(inputs) is not list or len(inputs)!=1
                    or inputs[0].get('id')!=RDJ_PAYLOAD or inputs[0].get('sha256')!=subject):return None
        rows = [row for row in controller._rows(store, 'step-observation')
                if row.get('step_id') == call['step_id'] and row.get('attempt') == call['outcome']['attempt']
                and row.get('receipt_sha256') in call['outcome'].get('receipts', [])]
        if (call['outcome'].get('status') != 'completed' or rows != [observed] or observed.get('status') not in {'ok', 'completed'}
                or not observed.get('actor_id') or not observed.get('session_id')
                or observed['actor_id'] != binding['actor_id'] or observed['session_id'] != binding['session_id']
                or _digest(call['node']) != binding['node_sha256']
                or _digest(call['request']) != binding['request_sha256']
                or call['result_sha256'] != binding['result_sha256']
                or packet.get('manifest_sha256') != binding['packet_sha256']
                or (observed.get('model') or {}).get('observed') != binding['observed_model']
                or transport.get('execution_mode') != binding['execution_mode']):return None
        public, pin = controller._read_output(call['outcome'], {'run_dir': call['run_dir']}, 'public-record.json')
        if pin != call['output'] or _digest(public) != binding['public_value_sha256']:return None
        return deepcopy(observed)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def record_graph(root, node, saved, reference):
    """Record one completed model node; called only by the graph runner that executed it.

    The record pins the attempt receipt and what the runner observed of its transport. It
    grants nothing by itself: the resolver checks it against the consumer's exact query.
    """
    from . import agent_graph, review_context
    if node.get('kind') != 'model' or node.get('action') == 'external':
        return None
    root = Path(root).resolve()
    store = _store()
    if store.resolve().is_relative_to(root) or root.is_relative_to(store.resolve()):
        return None
    result = saved.get('result') if type(saved.get('result')) is dict else {}
    transport = result.get('transport') if type(result.get('transport')) is dict else {}
    isolation = result.get('isolation') if type(result.get('isolation')) is dict else {}
    mode = transport.get('execution_mode', 'unestablished')
    observation = agent_graph.observation_for(mode)
    try:
        attestation, _ = agent_graph._receipt_attestation(root, transport, observation, isolation)
    except (OSError, ValueError, KeyError, TypeError):
        attestation = 'self_attested'
    controller_binding = None
    controller_observed = None
    if transport.get('controller_run_id'):
        # A controller-dispatched research call: its attestation is the protected step observation's, bound to
        # this exact node, request, result, actor, session, packet, model, mode and public value; else none.
        controller_binding = {'run_id': transport['controller_run_id'], 'graph_root': str(root),
            'request_id': (saved.get('request') or {}).get('request_id'),
            'node_sha256': _digest(node), 'request_sha256': _digest(saved.get('request')),
            'result_sha256': _digest(result), 'actor_id': transport.get('actor_id'),
            'session_id': transport.get('invocation_id'), 'packet_sha256': (node.get('packet') or {}).get('manifest_sha256'),
            'observed_model': transport.get('observed_model'), 'execution_mode': mode,
            'public_value_sha256': _digest(result.get('value'))}
        controller_observed = _controller_evidence(controller_binding)
        attestation = controller_attestation(controller_observed) if controller_observed is not None else 'self_attested'
    tools = None
    if mode == 'transport_attested_cli':
        observation = 'transport_attested_cli' if attestation == 'transport_attested' else 'unestablished'
        launcher = (transport.get('session_receipt') or {}).get('launcher_receipt') or {}
        tools = (launcher.get('configuration') or {}).get('effective_tools')
        if controller_observed is not None and controller_observed.get('tool_inventory') == []:
            tools = 'none'
    if observation in {'remote_transport_observed', 'local_transport_observed'}:
        disabled = isolation.get('model_tools_supplied') is False
    else:
        disabled = observation == 'transport_attested_cli' and tools == 'none'
    manifest, presented, run = None, [], None
    if node.get('packet'):
        try:
            index = review_context._PacketIndex(node['packet']['path'], node['packet']['manifest_sha256'])
            manifest = deepcopy(index.manifest)
            if builder(manifest) == JUDGMENT:
                # The judgment request names the run whose cycle this role reviews.
                entry = next(a for a in manifest['artifacts'] if a.get('id') == 'judgment_request')
                run = json.loads(index.read(entry)).get('rundir')
            index.finish()
        except (OSError, ValueError, TypeError, KeyError, StopIteration):
            manifest, run = None, None
        presented = sorted(_subjects(manifest)) if manifest else []
    kind, shown = builder(manifest), exposure(manifest, node['role']) if manifest else None
    # The supervisor's packet read boundary, from the protected observation only: the worker read its projected
    # packet (or the RDJ edge payload) through confined workspace tools and nothing else.
    boundary = ((controller_observed or {}).get('isolation') or {}).get('packet_read_boundary') or {}
    edge_inputs = node.get('inputs') or []
    edge_subject = (boundary.get('subject_sha256') if node.get('packet') is None and node['role'] == RDJ_EDGE_ROLE
                    and len(edge_inputs) == 1 and edge_inputs[0].get('id') == RDJ_PAYLOAD
                    and edge_inputs[0].get('sha256') == boundary.get('subject_sha256') else None)
    packet_only = (controller_observed is not None and boundary.get('kind') == 'controller-packet-read-boundary.v1'
                   and boundary.get('verified') is True
                   and (boundary.get('packet_sha256') == (node.get('packet') or {}).get('manifest_sha256')
                        or edge_subject is not None)
                   and boundary.get('role') == node['role'] and set(boundary.get('broker_actions') or []) <= {'read', 'write'})
    inputs = node.get('inputs') or []
    if (not node.get('packet') and node['role'] == RDJ_EDGE_ROLE and len(inputs) == 1
            and inputs[0].get('id') == RDJ_PAYLOAD):
        # The RDJ dispatcher pins its own computed payload for the (non-blind) edge reviewer:
        # the claims, support and public rationale under review, without author objects or verdicts.
        kind, presented = RDJ, [inputs[0]['sha256']]
        shown = {'author_identity': 'withheld', 'author_rationale': 'permitted', 'reference_values': 'permitted',
                 'peer_verdicts': 'withheld'}
    record = {'schema_version': 1, 'kind': RECORD_KIND, 'graph_root': str(root), 'run': run, 'node_id': node['id'],
              'role': node['role'], 'attempt_id': saved.get('attempt_id'),
              'request_id': (saved.get('request') or {}).get('request_id'),
              'receipt_sha256': reference['sha256'], 'host_sha256': reference['host_sha256'],
              'packet': deepcopy(node.get('packet')),
              'packet_builder': kind, 'packet_subjects': presented, 'exposure': shown,
              'controller_binding': controller_binding, 'controller_edge_subject_sha256': edge_subject,
              'execution_mode': mode, 'observation': observation, 'attestation': attestation,
              'fresh_request': isolation.get('fresh_request') is True,
              'parent_transcript_supplied': isolation.get('parent_transcript_supplied'),
              'read_boundary': 'tools_disabled' if disabled else 'packet_only' if packet_only else None,
              'read_boundary_verified': disabled or packet_only,
              'public_value_sha256': _digest(result.get('value')), 'observed_model': transport.get('observed_model')}
    raw = (json.dumps(record, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    store.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = store / (reference['sha256'] + '.json')
    try:
        with path.open('xb') as stream:
            stream.write(raw)
    except FileExistsError:
        pass  # A resumed runner records the same attempt again; the first record stands.
    return record


def graph_record(receipt_sha256):
    """The runner's record of one completed model node, or None."""
    try:
        record = _read(_store() / (receipt_sha256 + '.json'))
    except (OSError, ValueError):
        return None
    return record if type(record) is dict and record.get('kind') == RECORD_KIND else None


# ---------------------------------------------------------------- census

def _session(receipt):
    session = receipt.get('session_id')
    transport = (receipt.get('transport') or {}).get('id')
    return f'worker-session:{transport}:{session}' if type(session) is str and session else None


def _reviewing(receipt):
    return ('review_subject' in receipt or receipt.get('rdj') is not None
            or (receipt.get('final_record') or {}).get('schema') == 'reviewer.v1')


_CENSUS = {}


def _stamp(path):
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_size, stat.st_mtime_ns


def _recorded(run, folder):
    """``[(receipt sha256, context, reviewing)]`` of every worker receipt the dispatcher wrote, and host children.

    The ledgers only grow; a census is re-read whenever either changes.
    """
    from . import broker
    ledger, sessions = folder / 'worker-receipts.jsonl', folder / 'role-dispatch-sessions.json'
    key = (str(run), _stamp(ledger), _stamp(sessions))
    if key in _CENSUS:
        return _CENSUS[key]
    workers = []
    for row in broker.ledger(run, 'worker-receipts'):
        pin = row['record']['pin']
        path = broker.locate(run, pin['path'])
        if _sha(path) != pin['sha256']:
            continue  # A later version of this attempt's receipt names the current session.
        receipt = _read(path)
        context = _session(receipt)
        if context is not None:
            workers.append((pin['sha256'], context, _reviewing(receipt), _model(receipt)))
    children = ['host-child:' + str(s) for s in _read(sessions)] if sessions.exists() else []
    if len(_CENSUS) > 64:
        _CENSUS.clear()
    _CENSUS[key] = (workers, children)
    return workers, children


def census(run, *, exclude=None):
    """``(authors, reviews)``: every context the dispatchers recorded acting in this run.

    Authors are the dispatching conversation and every producer worker session; reviews are
    every other review worker session and every host-reported child session. Raises when a
    dispatcher ledger cannot be read, so an unreadable census never counts as complete.
    """
    from . import broker
    authors, reviews = [PARENT + str(run)], []
    folder = broker._state_dir() / 'workers' / broker.digest(str(run))
    if folder.is_dir():
        workers, children = _recorded(run, folder)
        for sha, context, reviewing, _ in workers:
            if sha != exclude:
                (reviews if reviewing else authors).append(context)
        reviews += children
    return sorted(set(authors)), sorted(set(reviews))


def _model(receipt):
    """The model a worker receipt records (observed before requested) with its registered family."""
    model = receipt.get('model') if type(receipt.get('model')) is dict else {}
    return {'model': model.get('observed') or model.get('requested'), 'family': model.get('family')}


def author_models(run, *, exclude=None):
    """``{context: model}`` of the producer worker sessions the dispatchers recorded, for the family label."""
    from . import broker
    folder = broker._state_dir() / 'workers' / broker.digest(str(run))
    if not folder.is_dir():
        return {}
    workers, _ = _recorded(run, folder)
    return {context: model for sha, context, reviewing, model in workers if not reviewing and sha != exclude}


# ---------------------------------------------------------------- resolver

def _proof(query, *, dispatch_id, context, run, packet, read_boundary, exposure_value, output_unmodified,
           reviewer_model=None):
    # The census excludes only this invocation's own receipt; every other recorded context counts.
    authors, reviews = census(run, exclude=query['receipt_sha256'])
    # Observed models feed only the family label of a credited seat; they never decide credit.
    models = {'reviewer': reviewer_model or {},
              **{'author:' + c: m for c, m in author_models(run, exclude=query['receipt_sha256']).items()}}
    # Same-user dispatcher records, not the controller's store: the decision carries this boundary.
    return {'binding': deepcopy(query), 'authority_boundary': SAME_USER_STATE,
            'dispatch_id': dispatch_id, 'context_id': context,
            'author_context_ids': authors, 'author_census_complete': True,
            'other_review_context_ids': reviews, 'review_census_complete': True,
            'parent_transcript_supplied': False, 'packet': packet,
            'read_boundary': read_boundary, 'read_boundary_verified': True,
            'exposure': exposure_value, 'exposure_verified': True, 'output_unmodified': output_unmodified,
            'models': models}


def _graph(query, record):
    observed = None
    if record.get('controller_binding') is not None:
        # Re-resolve the protected controller evidence now: its output, packet, attestation and freshness.
        observed = _controller_evidence(record['controller_binding'])
        if (record['controller_binding'].get('public_value_sha256') != query['output_sha256']
                or record['controller_binding'].get('packet_sha256') != query['packet_sha256']
                or observed is None or controller_attestation(observed) != 'transport_attested'
                or (observed.get('isolation') or {}).get('fresh_request') is not True
                or (observed.get('isolation') or {}).get('parent_transcript_supplied') is not False):return None
    if record.get('read_boundary') == 'packet_only':
        boundary = ((observed or {}).get('isolation') or {}).get('packet_read_boundary') or {}
        if (record.get('controller_binding') is None or boundary.get('kind') != 'controller-packet-read-boundary.v1'
                or boundary.get('verified') is not True
                or (boundary.get('packet_sha256') != query['packet_sha256'] and not (query['packet_sha256'] is None
                    and _same_card(record.get('role'), RDJ_EDGE_ROLE)
                    and boundary.get('subject_sha256') == record.get('controller_edge_subject_sha256') == query['subject_sha256']))
                or not set(boundary.get('broker_actions') or []) <= {'read', 'write'}):return None
    if record.get('packet') is None:
        # Only the RDJ edge reviewer's dispatcher-pinned payload stands in for a role packet.
        pinned = (_same_card(record.get('role'), RDJ_EDGE_ROLE) and record.get('packet_builder') == RDJ
                  and query['packet_sha256'] is None and record.get('packet_subjects') == [query['subject_sha256']])
        packet_sha = query['subject_sha256']
    else:
        pinned = (type(record['packet']) is dict and query['packet_sha256'] is not None
                  and record['packet'].get('manifest_sha256') == query['packet_sha256'])
        packet_sha = query['packet_sha256']
    if (not pinned or record.get('receipt_sha256') != query['receipt_sha256'] or not _same_card(record.get('role'), query['role'])
            or record.get('public_value_sha256') != query['output_sha256']
            or record.get('observation') not in OBSERVED or record.get('attestation') != 'transport_attested'
            or record.get('fresh_request') is not True or record.get('parent_transcript_supplied') is not False
            or record.get('read_boundary') not in {'tools_disabled', 'packet_only'}
            or record.get('read_boundary_verified') is not True
            or record.get('packet_builder') not in {JUDGMENT, PROTOCOL, RDJ}
            or query['subject_sha256'] not in (record.get('packet_subjects') or [])
            or type(record.get('exposure')) is not dict or type(record.get('request_id')) is not str):
        return None
    run = Path(query['run'])
    # The run binding the packet carries: a judgment request names its run, an RDJ role graph lies in it.
    if record['packet_builder'] == JUDGMENT and record.get('run') != query['run']:
        return None
    if record['packet_builder'] == RDJ and not Path(record['graph_root']).is_relative_to(run):
        return None
    return _proof(query, dispatch_id='graph:' + record['receipt_sha256'],
                  context='graph-request:' + record['request_id'], run=run,
                  packet={'builder': record['packet_builder'], 'projection_verified': True, 'author_summary': False,
                          'sha256': packet_sha, 'subject_sha256': query['subject_sha256']},
                  read_boundary=record['read_boundary'], exposure_value=deepcopy(record['exposure']),
                  output_unmodified=True, reviewer_model={'model': record.get('observed_model')})


def _worker(query):
    """Evidence of one supervised worker launch, from the dispatcher's own custody."""
    from . import agent_worker, broker, rdj_custody, review_points
    run = Path(query['run'])
    registration = None
    for row in rdj_custody.rows(run, 'workers'):
        if row['record'].get('sha256') == query['receipt_sha256']:
            registration = row['record']
    if registration is None:
        return None
    rel = registration['path']
    path = run / rel
    if '..' in Path(rel).parts or _sha(path) != query['receipt_sha256']:
        return None
    receipt = _read(path)
    agent_worker.receipt_version(receipt)
    subject = ((receipt.get('review_subject') or {}).get('sha256') if receipt['schema_version'] >= 2
               else (receipt.get('rdj') or {}).get('payload_sha256'))
    final = receipt['final_record']
    if (receipt['kind'] != 'agent-worker-receipt' or receipt['status'] != 'ok'
            or not _same_card(receipt['role'].get('id'), query['role']) or subject != query['subject_sha256']
            or final.get('valid') is not True or final.get('sha256') != query['output_sha256']
            or review_points.worker_label(receipt, registration.get('verified_label')) != 'transport_attested'
            or review_points.registered_actor(receipt, registration) is None):
        return None
    node, attempt = receipt['node_id'], receipt['attempt']
    record_path = broker._state_dir() / 'workers' / broker.digest(str(run)) / (agent_worker._key(node, attempt) + '.worker.json')
    record = _read(record_path)
    launch = record.get('launch')
    if (record.get('receipt') != {'path': rel, 'sha256': query['receipt_sha256']}
            or type(launch) is not dict or not launch.get('token')
            or (record.get('actor') or {}).get('actor_id') != receipt['actor_id']
            or not _same_card(record['spec']['role']['id'], query['role'])
            or (receipt['transport'] or {}).get('transport_kind') != 'cli-worker'):
        return None
    custody = record_path.parent
    key = agent_worker._key(node, attempt)
    from .transports.host_subagent import START_SUFFIX
    if (custody / (key + START_SUFFIX)).exists():
        return None  # A host window served this attempt.
    dispatch = custody / (key + '.role-dispatch.json')
    if dispatch.exists():
        kept = _read(dispatch)
        identity = kept.get('identity') or {}
        if (identity.get('mode') != 'required' or not _same_card(identity.get('role'), query['role'])
                or identity.get('spec_sha256') != broker.digest(record['spec'])
                or (identity.get('subject') or {}).get('sha256') != query['subject_sha256']):
            return None
    manifest = _manifest(record.get('packet'))
    if (manifest is None or builder(manifest) != PROJECTION or not _same_card(manifest.get('role'), query['role'])
            or manifest.get('subject_sha256') != query['subject_sha256']
            or 'producer_headline' not in set(manifest.get('forbidden_inputs') or [])):
        return None
    workspace = agent_worker.workspace(run, node, attempt)
    item = next((a for a in manifest['artifacts'] if a.get('id') == 'item'), None)
    for copy in record.get('input_copies') or []:
        if copy['path'].startswith('inputs/packet/'):
            continue
        if _controller_instruction_copy(query, record, copy, workspace, custody, key):
            continue
        if copy['path'] != 'inputs/review-packet.json' or item is None:
            return None  # An input the dispatcher copied beside the projection: possible author framing.
        from . import review_context
        index = review_context._PacketIndex(record['packet']['path'], record['packet']['manifest_sha256'])
        projected = json.loads(index.read(item))
        index.finish()
        raw = (workspace / copy['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != copy['sha256'] or json.loads(raw) != projected:
            return None
    isolation = receipt.get('isolation') or {}
    if (isolation.get('profile') != 'ravel-sandbox' or isolation.get('user_configuration_loaded') is not False
            or (isolation.get('evidence') or {}).get('confirmed') is not True):
        return None
    context = _session(receipt)
    if context is None:
        return None
    current = path.parent / final['path']
    unchanged = current.is_file() and not current.is_symlink() and _sha(current) == query['output_sha256']
    return _proof(query, dispatch_id=f'worker:{node}/{attempt}#{launch["token"]}', context=context, run=run,
                  packet={'builder': PROJECTION, 'projection_verified': True, 'author_summary': False,
                          'sha256': record['packet']['manifest_sha256'], 'subject_sha256': query['subject_sha256']},
                  read_boundary='packet_only', exposure_value=exposure(manifest, query['role']),
                  output_unmodified=unchanged, reviewer_model=_model(receipt))


def observed_projection(query):
    """The authenticated manifest of the packet the dispatcher bound to the worker launch ``query`` names (the
    projection that review read), or None. Read only; the registration and the dispatcher record are the
    ones ``_worker`` verifies."""
    from . import agent_worker, broker, rdj_custody
    try:
        run = Path(query['run'])
        registration = None
        for row in rdj_custody.rows(run, 'workers'):
            if row['record'].get('sha256') == query['receipt_sha256']:
                registration = row['record']
        if registration is None:
            return None
        rel = registration['path']
        if '..' in Path(rel).parts or _sha(run / rel) != query['receipt_sha256']:
            return None
        receipt = _read(run / rel)
        node, attempt = receipt['node_id'], receipt['attempt']
        record = _read(broker._state_dir() / 'workers' / broker.digest(str(run))
                       / (agent_worker._key(node, attempt) + '.worker.json'))
        if record.get('receipt') != {'path': rel, 'sha256': query['receipt_sha256']}:
            return None
        return _manifest(record.get('packet'))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _controller_instruction_copy(query, record, copy, workspace, custody, key):
    """The sole non-projection input allowed beside a governed review packet.

    Authenticate the controller instruction bytes against the protected launch descriptor
    and the dispatcher's spec. Public receipt fields cannot bless arbitrary raw inputs.
    The role's subject artifacts still come exclusively from the verified projection.
    """
    from .review_independence import controller_run
    if type(copy) is not dict or copy.get('path') != 'inputs/packet.md' or controller_run(query['run']) is None:
        return False
    spec = record.get('spec') or {}
    if type(spec) is not dict:
        return False
    inputs = spec.get('inputs')
    if (spec.get('final_record_schema') != 'controller.v1' or type(inputs) is not list or len(inputs) != 1
            or type(inputs[0]) is not dict or type(inputs[0].get('pin')) is not dict
            or inputs[0].get('as') != copy['path']
            or (inputs[0].get('pin') or {}).get('sha256') != copy.get('sha256')):
        return False
    descriptor_path = custody / (key + '.launch.json')
    if descriptor_path.is_symlink() or not descriptor_path.is_file():
        return False
    launch = record.get('launch')
    if type(launch) is not dict or _sha(descriptor_path) != launch.get('descriptor_sha256'):
        return False
    descriptor = _read(descriptor_path)
    if type(descriptor) is not dict or type(descriptor.get('transport')) is not dict:
        return False
    controller = descriptor['transport'].get('controller')
    path = workspace / copy['path']
    return (type(controller) is dict and controller.get('packet_sha256') == copy.get('sha256')
            and path.is_file() and not path.is_symlink() and _sha(path) == copy['sha256'])


# ---------------------------------------------------------------- controller run store

def _records(store, kind):
    """The records the controller appended under ``kind`` (unwrapping a store envelope)."""
    found = []
    for entry in store.scan(kind):
        if type(entry) is dict and type(entry.get('record')) is dict and not {'binding', 'session_id'} & set(entry):
            entry = entry['record']
        found.append(entry)
    return found


def _closed(record, fields, label):
    if type(record) is not dict or set(record) - fields or not {'session_id', 'seat'} <= set(record):
        raise ValueError(f'{label} record must be a closed object naming its session and seat')
    if any(type(record[k]) is not str or not record[k].strip() for k in ('session_id', 'seat')):
        raise ValueError(f'{label} record names an empty session or seat')


def record_session(store, record):
    """Controller-only: the seat session it started (fresh, its actor, model and transport).

    Called by the controller's dispatch node once per seat start, before any review output. A
    session on a host-mediated, relay or one-shot transport never holds a seat.
    """
    _closed(record, SESSION_FIELDS, 'review-session')
    if record.get('transport_kind') in SEATLESS_TRANSPORTS:
        raise ValueError('a host-mediated, relay or one-shot session cannot hold a review seat')
    if record.get('role_kind') not in ('producer', 'reviewer'):
        raise ValueError('review-session role_kind must be producer or reviewer')
    return store.append(SESSION_KIND, deepcopy(record))


def record_review(store, record):
    """Controller-only: one review output it observed, bound to the exact consumer query."""
    _closed(record, REVIEW_FIELDS, 'review-output')
    binding = record.get('binding')
    if type(binding) is not dict or set(binding) != {'run', 'role', 'subject_sha256', 'receipt_sha256',
                                                     'output_sha256', 'packet_sha256'}:
        raise ValueError('review-output record needs the exact decision binding')
    return store.append(REVIEW_KIND, deepcopy(record))


def capture_worker_session(store, *, receipt, step_id, seat, role_kind):
    """Controller observation seam for a verified worker receipt, including producer sessions.

    The dispatcher calls this after ``load_receipt`` verifies its custody. Replays of that
    observation are idempotent; a session observed in another attempt is recorded as reused.
    Failed attempts stay in the census. No caller-declared reviewer identity is accepted.
    """
    context = _session(receipt)
    if context is None:
        return None  # No child session was observed, e.g. a pre-launch refusal.
    prior = [r for r in _records(store, SESSION_KIND) if type(r) is dict]
    role = receipt['role']['id']
    record = {'session_id': context, 'seat': seat, 'step_id': step_id, 'role': role, 'card_id': role,
              'role_kind': role_kind, 'actor_id': receipt.get('actor_id'),
              'model': (receipt.get('model') or {}).get('observed'),
              'transport_id': receipt['transport']['id'],
              'transport_kind': receipt['transport'].get('transport_kind'),
              'fresh': receipt.get('attestation') == 'transport_attested'
                       and not any(r.get('session_id') == context and r.get('seat') != seat for r in prior),
              'parent_transcript_supplied': False}
    matches = [r for r in prior if r.get('session_id') == context and r.get('seat') == seat]
    if matches:
        if len(matches) != 1 or matches[0] != record:
            raise ValueError('worker session observation changed')
        return None
    return record_session(store, record)


def capture_worker_review(store, query):
    """Transfer verified launch, packet and output observations into the controller store.

    This controller-only seam reuses the worker verifier, not its same-user credit label.
    A raw instruction packet, a handwritten receipt or an unconfined launch supplies no
    review observation. The controller census must already include this exact worker.
    """
    proof = _worker(query)
    if proof is None:
        return None
    sessions = [r for r in _records(store, SESSION_KIND) if type(r) is dict
                and r.get('session_id') == proof['context_id'] and _same_card(r.get('role'), query['role'])
                and r.get('role_kind') == 'reviewer']
    if len(sessions) != 1:
        return None
    record = {'binding': deepcopy(query), 'seat': sessions[0]['seat'], 'session_id': proof['context_id'],
              'dispatch_id': proof['dispatch_id'], 'packet': deepcopy(proof['packet']),
              'read_boundary': proof['read_boundary'], 'read_boundary_verified': proof['read_boundary_verified'],
              'exposure': deepcopy(proof['exposure']), 'exposure_verified': proof['exposure_verified'],
              'output_unmodified': proof['output_unmodified']}
    matches = [r for r in _records(store, REVIEW_KIND) if type(r) is dict and r.get('binding') == query]
    if matches:
        if len(matches) != 1 or matches[0] != record:
            raise ValueError('worker review observation changed')
        return None
    return record_review(store, record)


def store_lookup(query, store):
    """Evidence for exactly this query from the controller's own run-store records, or None.

    The census is every session the controller started in this run, re-read at each decision. The
    seat's session must pass its card's ``independence`` fields (``review_independence.seat_refusal``)
    and its actor must differ from every producer of the reviewed subject. The proof carries the
    observed models for the family label only.
    """
    from . import role_registry
    from .review_independence import seat_refusal
    try:
        sessions = [r for r in _records(store, SESSION_KIND) if type(r) is dict]
        reviews = [r for r in _records(store, REVIEW_KIND) if type(r) is dict and r.get('binding') == query]
        if len(reviews) != 1:
            return None
        review = reviews[0]
        mine = [r for r in sessions if r.get('session_id') == review.get('session_id')
                and r.get('seat') == review.get('seat')]
        if (len(mine) != 1 or not _same_card(mine[0].get('role'), query['role']) or mine[0].get('role_kind') != 'reviewer'
                or mine[0].get('transport_kind') in SEATLESS_TRANSPORTS):
            return None
        session = mine[0]
        card = role_registry.load(session['card_id']) if session.get('card_id') else None
        if (card is None or not _same_card(card['id'], session['role']) or session.get('fresh') is not True
                or type(session.get('actor_id')) is not str or not session['actor_id'].strip()
                or seat_refusal(card, session, sessions) is not None):
            return None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    producers = [r for r in sessions if r.get('role_kind') == 'producer']
    authors = sorted({'controller:' + str(query['run'])} | {r['session_id'] for r in producers})
    others = sorted({r['session_id'] for r in sessions if r.get('role_kind') == 'reviewer' and r is not session})
    named = review.get('subject_session_ids')
    if named is not None and (type(named) is not list or not named
            or any(type(s) is not str or not s for s in named) or len(set(named)) != len(named)
            or not set(named) <= {r['session_id'] for r in producers}):
        return None
    judged = [r for r in producers if named is None or r['session_id'] in named]
    if any(r.get('actor_id') == session.get('actor_id') for r in judged):
        return None  # The reviewer's actor produced what it reviews.
    models = {'reviewer': {'model': session.get('model')},
              **{'author:' + r['session_id']: {'model': r.get('model')} for r in judged}}
    return {'binding': deepcopy(query), 'authority_boundary': CONTROLLER_STORE,
            'dispatch_id': review.get('dispatch_id'), 'context_id': session['session_id'],
            'author_context_ids': authors, 'author_census_complete': True,
            'other_review_context_ids': others, 'review_census_complete': True,
            'parent_transcript_supplied': session.get('parent_transcript_supplied'),
            'packet': deepcopy(review.get('packet')), 'read_boundary': review.get('read_boundary'),
            'read_boundary_verified': review.get('read_boundary_verified'),
            'exposure': deepcopy(review.get('exposure')), 'exposure_verified': review.get('exposure_verified'),
            'output_unmodified': review.get('output_unmodified'), 'models': models}


def lookup(query):
    """The default resolver of a run the controller does not own: dispatcher evidence, or None."""
    try:
        record = graph_record(query['receipt_sha256'])
        if record is not None:
            return _graph(query, record)
        return _worker(query)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
