"""Read-only specialist consultations and pinned advisory producer handoffs.

Failure and on-use callers prepare a request, then run ``consult.case`` through
the graph substrate. The knowledge-bundle provider supplies targeted knowledge. Worker budgets
and receipts remain those of the governed worker; this module grants no launch,
retry, acceptance vote or permission to edit the failed run.
"""
from __future__ import annotations

from copy import deepcopy
from importlib import import_module
import json
from pathlib import Path
import re

from . import agent_worker, broker, role_registry, toolbelt
from .state_io import atomic_json, file_lock, read_json

DATA = Path(__file__).resolve().parents[1] / 'data/knowledge/consult_bindings.json'
SHA = re.compile(r'[0-9a-f]{64}\Z')


def bindings():
    value = read_json(DATA)
    if value.get('schema_version') != 1 or value.get('kind') != 'consult-bindings':
        raise ValueError('versioned consult bindings required')
    from .higgs_registration import compose
    return compose(value, DATA)


def for_tool(tool):
    for name, row in bindings()['consults'].items():
        if tool in row['tools']:
            return {'id': name, **deepcopy(row)}
    return None


def _fresh_or_equal(run, relative, value):
    path = broker.confined(run, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path.with_suffix('.lock')):
        if path.exists():
            if read_json(path) != value:
                raise ValueError('consult identity reused with changed content')
        else:
            atomic_json(path, value)
    return {'path': relative, 'sha256': broker.sha(path)}


def _pin_file(run, pin):
    if type(pin) is not dict or set(pin) != {'path', 'sha256'} or not SHA.fullmatch(str(pin['sha256'])):
        raise ValueError('exact consult pin required')
    path = broker.locate(run, pin['path'])
    if not path.is_file() or path.stat().st_size > 4_000_000 or broker.sha(path) != pin['sha256']:
        raise ValueError('consult pin changed or exceeds bound')
    return path


def _read_pin(run, pin):
    return read_json(_pin_file(run, pin))


def prepare_failure(rundir, *, node_id, observations, budgets, transport_preference, evidence=(), rca_ticket=None):
    """Persist a failure request; neither knowledge retrieval nor worker dispatch."""
    from .failure_router import classify
    agent_worker._key(node_id, 1)
    failure = classify(observations)
    return _prepare(rundir, node_id, failure, budgets, transport_preference, evidence, rca_ticket)


def _prepare(rundir, node_id, failure, budgets, transports, evidence, rca_ticket, question=None):
    run = broker.ordinary(rundir)
    for pin in evidence:
        _pin_file(run, pin)
    request = {'schema_version': 1, 'kind': 'consult-request', 'producer_node_id': node_id,
               'failure': failure, 'budgets': deepcopy(budgets), 'transport_preference': deepcopy(transports),
               'evidence': deepcopy(list(evidence)), 'rca_ticket': deepcopy(rca_ticket), 'question': question,
               'trigger_sha256': broker.digest({'failure': failure, 'evidence': list(evidence), 'question': question})}
    # Reuse the worker's budget/transport validation even for no-agent requests.
    agent_worker._validate(_spec_base(request, failure.get('consult_role') or 'consult-inference'))
    return _fresh_or_equal(run, 'consults/requests/' + broker.digest(request) + '.json', request)


def prepare_question(rundir, *, node_id, tool, question, budgets, transport_preference, evidence=()):
    """The consult.ask seam: at most three distinct questions per producer node.

    Reservation is durable even if a later worker fails. Identical preparation is
    idempotent. All actual answers use the same charged worker graph as failures.
    """
    run = broker.ordinary(rundir)
    agent_worker._key(node_id, 1)
    if type(question) is not str or not question.strip() or len(question) > 8192:
        raise ValueError('bounded consult question required')
    binding = for_tool(tool)
    if binding is None:
        raise ValueError('registered consult tool required')
    failure = {'schema_version': 1, 'kind': 'consult-on-use', 'class_id': 'consult.on_use',
               'family': 'consult', 'consult_role': binding['role'], 'agent_required': True,
               'route': 'consult', 'observations': {'tool': tool}, 'acceptance_vote': False,
               'matched_rule': {}}
    location = broker.confined(run, 'consults/questions/' + node_id + '.json')
    location.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(location.with_suffix('.lock')):
        rows = read_json(location) if location.exists() else {}
        key = broker.digest({'tool': tool, 'question': question, 'evidence': list(evidence),
                             'budgets': budgets, 'transport_preference': transport_preference})
        if key in rows:
            _read_pin(run, rows[key])
            return deepcopy(rows[key])
        if len(rows) >= 3:
            raise ValueError('three consult questions per node exhausted')
        pin = _prepare(run, node_id, failure, budgets, transport_preference, evidence, None, question)
        rows[key] = pin
        atomic_json(location, rows)
        return pin


def load_request(run, pin):
    request = _read_pin(run, pin)
    expected = {'schema_version', 'kind', 'producer_node_id', 'failure', 'budgets', 'transport_preference',
                'evidence', 'rca_ticket', 'question', 'trigger_sha256'}
    if set(request) != expected or request['kind'] != 'consult-request' or request['schema_version'] != 1:
        raise ValueError('typed consult request required')
    if request['question'] is None:
        from .failure_router import classify
        if classify(request['failure']['observations']) != request['failure']:
            raise ValueError('consult classification or registry changed')
    else:
        binding = for_tool(request['failure']['observations']['tool'])
        if not binding or request['failure']['consult_role'] != binding['role']:
            raise ValueError('consult question role changed')
    if request['trigger_sha256'] != broker.digest({k: request[k] for k in ('failure', 'evidence', 'question')}):
        raise ValueError('consult trigger changed')
    for evidence in request['evidence']:
        _pin_file(run, evidence)
    return request


def _spec_base(request, role):
    card = role_registry.load(role)
    if card['requires']['tools'] != 'broker-readonly' or card['independence']['kind'] != 'advisory':
        raise ValueError('read-only advisory consult card required')
    return {'schema_version': 1, 'kind': 'agent-worker-spec',
            'node_id': 'consult.' + request['producer_node_id'] + '.' + request['trigger_sha256'][:16], 'attempt': 1,
            'role': {'id': card['id'], 'version': card['version'], 'card_sha256': role_registry.card_sha256(role)},
            'transport_preference': request['transport_preference'], 'inputs': [],
            'declared_outputs': [{'path': 'outputs/advice.json', 'kind': 'consult-advice', 'required': True}],
            'budgets': request['budgets'], 'final_record_schema': 'producer.v1', 'work_order': None,
            'rdj_challenges': None, 'parent': {'review_point_id': 'K2' if request['question'] is None else 'K1',
                                            'map_id': None, 'rca_ticket': request['rca_ticket']}}


def worker_spec(run, request_pin):
    """Knowledge-bundle materialize seam; hold when targeted knowledge cannot be supplied."""
    from .graph_nodes import RecoveryHold
    request = load_request(run, request_pin)
    failure = request['failure']
    if not failure['agent_required']:
        raise ValueError('no consult agent for this failure')
    spec = _spec_base(request, failure['consult_role'])
    card = role_registry.load(failure['consult_role'])
    binding = for_tool(failure['observations']['tool'])
    # Add the roster's full handbooks to the context card. The actual worker role
    # remains pinned to its registered card; this only requests more read-only inputs.
    context_card = deepcopy(card)
    context_card['knowledge']['must_read'] = sorted(set(card['knowledge']['must_read']) |
                                                  set((binding or {}).get('handbooks', [])))
    try:
        provider = import_module('ravel.workflow.knowledge_bundle').materialize
    except ModuleNotFoundError as exc:
        if exc.name != 'ravel.workflow.knowledge_bundle':
            raise
        raise RecoveryHold('consult_bundle_unavailable', 'merge the targeted knowledge-bundle provider') from exc
    directory = broker.confined(run, 'consults/context/' + request['trigger_sha256'])
    facts = {**failure['observations'], 'node_id': spec['node_id'], 'failure_class': failure['class_id']}
    bundle = provider(context_card, facts, {'rundir': str(run), 'workspace': str(directory), 'node_id': spec['node_id']})
    if type(bundle) is not dict or bundle.get('kind') != 'knowledge-bundle' or bundle.get('card_id') != card['id']:
        raise ValueError('typed consult knowledge bundle required')
    served = {item['id'] for item in bundle['items']}
    missing = set(context_card['knowledge']['must_read']) - served
    if missing:
        raise RecoveryHold('consult_handbook_missing', 'supply full required handbooks: ' + ', '.join(sorted(missing)))
    copies = []
    for ordinal, item in enumerate(bundle['items']):
        # The provider records each item relative to the workspace it was given.
        path = broker.ordinary(directory / item['path'])
        if not path.is_relative_to(directory) or not path.is_file() or broker.sha(path) != item['sha256']:
            raise ValueError('consult knowledge item changed or outside its bundle')
        copies.append({'pin': {'path': path.relative_to(broker.ordinary(run)).as_posix(), 'sha256': item['sha256']},
                       'as': 'inputs/knowledge/' + str(ordinal) + path.suffix})
    from .knowledge import load_atlas
    atlas = {row['id']: row for row in load_atlas()['entries']}
    # Consult bundles serve whole handbooks, which include their pitfall sections.
    pairs = [{'pitfall_id': identity, 'check_id': check}
             for identity in sorted(atlas) if '#pitfall-' in identity
             and (identity in served or identity.split('#', 1)[0] in served)
             for check in atlas[identity].get('links', {}).get('checks', [])]
    belt = toolbelt.build(card, facts)
    packet = {'schema_version': 1, 'kind': 'consult-context', 'failure': failure,
              'question': request['question'], 'bundle': bundle, 'pitfall_checks': pairs,
              'failure_modes': [failure['matched_rule']] if failure['matched_rule'] else [],
              'lessons': [item for item in bundle['items'] if item['kind'] == 'lesson'],
              'toolbelt': belt, 'advisory': True, 'acceptance_vote': False,
              'instructions': 'Return outputs/advice.json with schema_version=1, kind=consult-advice, a short answer and fixes. Each fix names an offered pitfall_id, its check_id and a concrete fix. Advice never authorizes retry, edits or acceptance.'}
    pin = _fresh_or_equal(run, 'consults/context/' + request['trigger_sha256'] + '/packet.json', packet)
    spec['inputs'] = [{'pin': pin, 'as': 'inputs/consult-context.json'}, *copies,
                      *[{'pin': p, 'as': 'inputs/evidence/' + str(i) + Path(p['path']).suffix}
                        for i, p in enumerate(request['evidence'])]]
    return agent_worker._validate(spec)


def validate_advice(advice, pitfall_checks, *, require_fix=True):
    if (type(advice) is not dict or set(advice) != {'schema_version', 'kind', 'answer', 'fixes'}
            or advice['schema_version'] != 1 or advice['kind'] != 'consult-advice'
            or type(advice['answer']) is not str or not advice['answer'].strip() or len(advice['answer']) > 8192
            or type(advice['fixes']) is not list or not (1 if require_fix else 0) <= len(advice['fixes']) <= 16):
        raise ValueError('short typed consult advice required')
    offered = {(p['pitfall_id'], p['check_id']) for p in pitfall_checks}
    for fix in advice['fixes']:
        if (type(fix) is not dict or set(fix) != {'pitfall_id', 'check_id', 'fix'}
                or (fix['pitfall_id'], fix['check_id']) not in offered
                or type(fix['fix']) is not str or not fix['fix'].strip() or len(fix['fix']) > 8192):
            raise ValueError('consult fix must cite an offered pitfall and its check')
    return deepcopy(advice)


def record(run, request_pin, receipt):
    """Admit advice only from the actual governed worker and credited output."""
    request = load_request(run, request_pin)
    spec = _spec_base(request, request['failure']['consult_role'])
    actual = agent_worker.load_receipt(run, spec['node_id'], 1)
    if actual != receipt or actual['status'] != 'ok' or actual['role'] != spec['role']:
        raise ValueError('consult requires the matching successful governed worker receipt')
    ws = agent_worker.workspace(run, spec['node_id'], 1)
    packet = read_json(ws / 'inputs/consult-context.json')
    output = next((o for o in actual['credited_outputs'] if o['path'] == 'outputs/advice.json'), None)
    if output is None:
        raise ValueError('consult advice was not credited')
    advice = validate_advice(read_json(ws / output['path']), packet['pitfall_checks'],
                             require_fix=request['question'] is None)
    receipt_pin = {'path': broker.logical(run, ws / 'receipt.json'), 'sha256': broker.sha(ws / 'receipt.json')}
    document = {'schema_version': 1, 'kind': 'consult-record', 'producer_node_id': request['producer_node_id'],
                'request': request_pin, 'trigger_sha256': request['trigger_sha256'], 'role': actual['role'],
                'failure_class': request['failure']['class_id'], 'advice': advice, 'worker_receipt': receipt_pin,
                'bundle_sha256': packet['bundle']['bundle_sha256'], 'advisory': True, 'acceptance_vote': False}
    pin = _fresh_or_equal(run, 'consults/records/' + request['trigger_sha256'] + '.json', document)
    # Custody, rather than a producer-writable directory listing, selects next-turn inputs.
    entries = broker.ledger(run, 'consult-records')
    if not any(e['record']['pin'] == pin for e in entries):
        broker.append_ledger(run, 'consult-records', {'pin': pin, 'request': request_pin,
                             'producer_node_id': request['producer_node_id'], 'worker_node_id': spec['node_id']})
    return pin


def next_turn_spec(run, spec, *, request):
    """Production seam: add exact advisory records before worker materialization."""
    request_doc = load_request(run, request)
    result = deepcopy(spec)
    if result['node_id'] != request_doc['producer_node_id']:
        raise ValueError('consult belongs to a different producer node')
    rows = [entry['record'] for entry in broker.ledger(run, 'consult-records')
            if entry['record']['request'] == request and entry['record']['producer_node_id'] == result['node_id']]
    if request_doc['failure']['agent_required'] and not rows:
        raise ValueError('required failure consult record is not available')
    for entry in rows:
        document = _read_pin(run, entry['pin'])
        receipt = agent_worker.load_receipt(run, entry['worker_node_id'], 1)
        if (document['advisory'] is not True or document['acceptance_vote'] is not False
                or document['worker_receipt']['sha256'] != broker.sha(broker.locate(run, document['worker_receipt']['path']))):
            raise ValueError('consult record or receipt changed')
        if receipt['status'] != 'ok':
            raise ValueError('consult worker receipt no longer valid')
        item = {'pin': entry['pin'], 'as': 'inputs/consults/' + document['trigger_sha256'] + '.json'}
        if item not in result['inputs']:
            result['inputs'].append(item)
    return agent_worker._validate(result)


def diagnostic_inputs(run, *, request):
    """Failed-stage/RCA owner seam; advice supplements the existing diagnostic packet."""
    document = load_request(run, request)
    probe = _spec_base(document, document['failure']['consult_role'] or 'consult-inference')
    probe['node_id'] = document['producer_node_id']
    next_spec = next_turn_spec(run, probe, request=request)
    return {'schema_version': 1, 'kind': 'consult-diagnostic-inputs', 'request': request,
            'failure': document['failure'], 'evidence': document['evidence'], 'rca_ticket': document['rca_ticket'],
            'consult_records': [item['pin'] for item in next_spec['inputs']],
            'advisory': True, 'acceptance_vote': False, 'retry_authorized': False}
