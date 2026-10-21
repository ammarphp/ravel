"""Synthetic workload chains through the registered graphs on stub transports.

Each workload is a synthetic sibling: a typed request plan of generic operations and claims,
never a benchmark, paper, task, challenge or person. ``run_chain`` drives it as one
``lifecycle.drive`` instance (review.points and production.node run as its subgraphs) with
``RAVEL_AGENT_TRIPWIRE=1``. ``ChainWorkers`` stands in for ``agent_worker.dispatch``: it
materializes the real workspace, writes every output through the worker's broker (only a
broker output pin credits an output) and closes the attempt with ``agent_worker.finish``.
No model, sandbox, network or native tool is involved.

The dispatched role set is compared with the set the merged rows derive
(``review_points.derive`` over ``data/review_points.json`` plus ``data/roles/executors.json``
plus the coordinator). Roles a workload's design needs that no merged row dispatches in the
lifecycle are listed as skipped, each with its landing slot. ``score`` is the L-10 grader:
raw (verdict only) beside strict (verdict plus the quantity inside the tolerance declared
before the run), with custody and probe checks that give trivial outputs zero.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'unit'))

FIXTURES = HERE / 'fixtures' / 'workload_chains'
PROVIDERS = ('review_points', 'rdj', 'ceilings', 'executor', 'spawn_rows', 'input_closure', 'raw_launch')
OPTIONS = ('graph', 'framework_step', 'packet', 'protected', 'effect')
# The ``at`` values lifecycle.drive routes to review.points; every other derived point is skipped.
LIFECYCLE_ATS = ('checkin1', 'checkin2:', 'checkin3')
RESULT_KIND = 'synthetic-result'
VERDICTS = ('excluded', 'not_excluded', 'consistent', 'inconsistent')


def load(name):
    return json.loads((FIXTURES / name).read_text())


def workloads():
    return load('workloads.json')['workloads']


def landing():
    return load('landing.json')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


# ---- the run ---------------------------------------------------------------------------------

def run_root(tmp_path, monkeypatch):
    """A fresh run with its own machine state: worker custody is keyed by the run path, and a
    reused temporary path must never meet a previous session's custody records."""
    from rdj_fixtures import Run
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path.resolve() / 'state'))
    monkeypatch.delenv('RAVEL_WORK_ROOT', raising=False)
    return Run(tmp_path.resolve() / 'run', snapshot=False).root


def plan_of(workload):
    """The workload's request plan; the scored node additionally declares its result output."""
    plan = deepcopy(workload['plan'])
    scored = workload['scored_node']
    for node in plan['nodes']:
        if node['id'] == scored:
            node['outputs'] = [{'path': f'outputs/{scored}/obligations.json', 'kind': 'obligations', 'required': True},
                               {'path': f'outputs/{scored}/result.json', 'kind': RESULT_KIND, 'required': True}]
    return plan


def seed(root, workload):
    """Pin the request plan in an epoch-two contract; nothing else about the workload reaches the run."""
    plan = plan_of(workload)
    value = {'nodes': plan['nodes'], 'edges': plan.get('edges', []), 'claims': plan.get('claims', []),
             'trap_sweep': plan.get('trap_sweep', False)}
    pin = write(root / 'inputs/request_plan.json', value)
    pin['path'] = 'inputs/request_plan.json'
    path = root / 'inputs/task_contract.json'
    contract = json.loads(path.read_text()) if path.exists() else {}
    write(path, {**contract, 'agent_layer_epoch': 2, 'delegated': False, 'request_plan': pin})
    write(root / 'inputs/checkin1.json', {'schema_version': 1, 'kind': 'checkin1', 'sections': {}})
    return value


def put(rundir, ws, rel, text):
    """Write one worker output through the worker's broker, as a transport-run worker would."""
    from ravel.workflow import agent_tripwire, broker
    agent_tripwire.check('broker.call')
    tool = broker.Broker(rundir, ws, node_id=ws.parent.name, attempt=int(ws.name), allowed_actions=['write'],
                         max_calls=100000)
    reply = tool.call({'call_id': 'put-' + hashlib.sha256((rel + '\0' + text).encode()).hexdigest()[:24],
                       'action': 'write', 'args': {'path': rel, 'content': text}})
    assert reply['status'] == 'ok', reply


class ChainWorkers:
    """Stub transport for every role the lifecycle, review and production graphs dispatch.

    ``result`` is what the scored node's producer writes as its result (a probe replaces it);
    ``None`` writes nothing for that output. Each call first asserts the substrate context at
    the worker launch layer, so a dispatch from outside an acting node fails the chain.
    """

    def __init__(self, root, *, scored_node, result):
        self.root = Path(root)
        self.scored_node = scored_node
        self.result = result
        self.calls = []

    def __call__(self, rundir, spec, **options):
        from ravel.workflow import agent_tripwire, agent_worker
        verdict = agent_tripwire.check('agent_worker.launch')
        role = spec['role']['id']
        ws = agent_worker.materialize(rundir, spec, **{k: v for k, v in options.items() if k in OPTIONS})
        context = (verdict or {}).get('context') or {}
        self.calls.append({'role': role, 'node_id': spec['node_id'], 'map_id': spec['parent']['map_id'],
                           'graph_id': context.get('graph_id'), 'ravel_kind': context.get('ravel_kind'),
                           'card_sha256': spec['role']['card_sha256'],
                           'framework_step': options.get('framework_step')})
        if spec['parent']['map_id'].startswith('review:'):
            packet = json.loads((ws / 'inputs/review-packet.json').read_text())
            put(rundir, ws, 'outputs/review.json', json.dumps({'findings': []}))
            # The review item's own receipt carries review_subject and is the credit. Only a supervised
            # launch observes a transport, so the review runs through launch and supervise: the
            # dispatcher assigns the actor and the adapter observes the attestation and a distinct session.
            from worker_supervision import descriptor, supervised
            worker = supervised(rundir, spec, session=spec['node_id'], launch_spec=descriptor(family=role),
                                final={'completed': True, 'disposition': 'supported', 'findings': []},
                                **{k: v for k, v in options.items() if k in OPTIONS})
            assert worker['review_subject']['sha256'] == packet['subject_sha256'], worker
            return worker
        order_path = ws / 'inputs/work-order.json'
        if order_path.exists():
            order = json.loads(order_path.read_text())
            sidecar = {'obligations': {row['id']: {'checked': True, 'by': role} for row in order['obligations']},
                       'node_id': order['node_id']}
            for output in order['declared_outputs']:
                if output['kind'] == RESULT_KIND:
                    if self.result is not None:
                        text = self.result if isinstance(self.result, str) else json.dumps(self.result)
                        put(rundir, ws, output['path'], text)
                    continue
                put(rundir, ws, output['path'], json.dumps(sidecar))
        return agent_worker.finish(rundir, spec, execution={'exit_status': 0}, final={'completed': True})

    def roles(self):
        return [c['role'] for c in self.calls]


def _providers(gate):
    return {p: True for p in PROVIDERS}


def _approve_checkin1(root, monkeypatch):
    from ravel.workflow import workflow_state
    from ravel.workflow.graphs import lifecycle
    write(root / 'inputs/checkin1_approval.json', {'schema_version': 2, 'generated_by': 'synthetic',
                                                    'approved_plan': 'full', 'quote': 'Approved as planned'})
    monkeypatch.setattr(workflow_state, 'verify_approval', lambda *a, **k: [])
    monkeypatch.setattr(lifecycle, 'checkin1_errors', lambda root: [])
    return 'inputs/checkin1_approval.json'


def _approve_checkin2(root, monkeypatch):
    from ravel.workflow import workflow_state
    from ravel.workflow.graphs import lifecycle
    write(root / 'inputs/checkin2_go.json', {'schema_version': 1, 'generated_by': 'synthetic', 'quote': 'GO'})
    monkeypatch.setattr(workflow_state, 'verify_checkin2_go', lambda *a, **k: [])
    monkeypatch.setattr(lifecycle, 'checkin2_errors', lambda root: [])
    return 'inputs/checkin2_go.json'


def _science_approve(root):
    from ravel.workflow.graphs.review import APPROVER
    from ravel.workflow.science import APPROVAL
    write(root / APPROVAL, {'generated_by': APPROVER, 'schema_version': 2, 'quote': 'Approved'})
    return APPROVAL


def run_chain(root, workload, monkeypatch, *, result=None, tripwire_record=None, max_stops=8):
    """Drive the workload's lifecycle instance to its end; return the observations and the workers.

    Each CHECK-IN stop is answered with the run's own synthetic approval record. The stops are
    recorded in order; a hold ends the drive and is returned as the last observation.
    """
    from ravel.workflow import agent_worker, graph_nodes, role_registry
    from ravel.workflow.graphs import lifecycle
    seed(root, workload)
    result = workload['producer_result'] if result is None else result
    workers = ChainWorkers(root, scored_node=workload['scored_node'], result=result)
    monkeypatch.setattr(agent_worker, 'dispatch', workers)
    # Production roles' self-checks need registered validators a stub cannot run (handoff U5).
    monkeypatch.setattr(role_registry, 'self_checks', lambda role, **k: [])
    monkeypatch.setenv('RAVEL_AGENT_TRIPWIRE', '1')
    if tripwire_record is not None:
        monkeypatch.setenv('RAVEL_AGENT_TRIPWIRE_RECORD', str(tripwire_record))
    refused = guard_sockets(monkeypatch)
    options = {'gate_check': lambda *a: [], 'gate_providers': _providers}
    stops = []
    try:
        observation = lifecycle.run(root, **options)
        for _ in range(max_stops):
            schemas = [i['schema_id'] for i in observation['interrupts']]
            stops.append(schemas)
            if not schemas:
                break
            if schemas == ['checkin1_response']:
                record = _approve_checkin1(root, monkeypatch)
            elif schemas == ['checkin2_response'] and not _claims(workload):
                record = _approve_checkin2(root, monkeypatch)
            else:
                record = _science_approve(root)
            observation = lifecycle.respond(root, decision='approve', record=record, **options)
    finally:
        graph_nodes.forget_handled()
    return {'observation': observation, 'stops': stops, 'workers': workers, 'refused_connections': refused}


def guard_sockets(monkeypatch):
    """Refuse every non-loopback connection for the chain's duration; the refusals are returned."""
    import socket
    refused = []
    original = socket.socket.connect

    def connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host not in ('127.0.0.1', '::1', 'localhost') and self.family != socket.AF_UNIX:
            refused.append(str(host))
            raise ConnectionRefusedError('workload chains refuse non-loopback connections: ' + str(host))
        return original(self, address)
    monkeypatch.setattr(socket.socket, 'connect', connect)
    return refused


def _claims(workload):
    return bool(workload['plan'].get('claims'))


# ---- role sets -------------------------------------------------------------------------------

def derived(root):
    """The role set the merged rows derive for this run: (dispatched in the lifecycle, skipped points)."""
    from ravel.workflow import production_executor as executor, review_points
    facts = review_points._facts(root)
    inside, outside = {'coordinator'}, []
    for node in executor.production_nodes(facts):
        inside.add(executor.role_for(node))
    # The merged rows: the core review points and the conditional staffing rows the dispatcher also routes.
    for point in review_points.population(facts):
        at = point['when']['at']
        names = [entry['role'] for entry in point['roles']]
        if any(at == prefix or (prefix.endswith(':') and at.startswith(prefix)) for prefix in LIFECYCLE_ATS):
            inside.update(names)
        else:
            outside.append({'point': point['id'], 'row': point['row'], 'at': at, 'roles': names})
    return inside, outside


def skipped(workload, dispatched, outside):
    """Every design role the chain did not dispatch, and every derived point the lifecycle does not route.

    Each entry names its landing slot from ``landing.json``; an entry without one is a gap.
    """
    table = landing()
    rows = []
    for component in workload['design']:
        for role in component['roles']:
            if role in dispatched:
                continue
            slot = table['roles'].get(role) or table['components'].get(component['component'])
            rows.append({'role': role, 'component': component['component'], 'source': 'design',
                         'landing': slot})
    for point in outside:
        kind = point['at'].split(':', 1)[0]
        for role in point['roles'] or ['(row %d)' % point['row']]:
            rows.append({'role': role, 'component': f"row {point['row']} at {point['at']}", 'source': 'derived',
                         'landing': table['ats'].get(kind)})
    return sorted(rows, key=lambda r: (r['source'], r['role'], r['component']))


def role_set_problems(record, workload):
    """Problems with the dispatched role set: it must equal the merged-row derivation and the pin."""
    problems = []
    dispatched, derived_set = set(record['dispatched_roles']), set(record['derived_roles'])
    for role in sorted(dispatched - derived_set):
        problems.append(f"{record['workload']}: {role} dispatched but no merged row derives it")
    for role in sorted(derived_set - dispatched):
        problems.append(f"{record['workload']}: {role} derived but never dispatched")
    if dispatched != set(workload['expect_dispatched']):
        problems.append(f"{record['workload']}: dispatched set differs from the pinned expectation")
    return problems


def skipped_problems(record, workload):
    """Every design role is dispatched or skipped; every skipped row names a slot from the vocabulary."""
    slots = set(landing()['slots'])
    problems = []
    listed = {row['role'] for row in record['skipped'] if row['source'] == 'design'}
    for component in workload['design']:
        for role in component['roles']:
            if role not in record['dispatched_roles'] and role not in listed:
                problems.append(f"{record['workload']}: design role {role} neither dispatched nor skipped")
    for row in record['skipped']:
        if row['landing'] not in slots:
            problems.append(f"{record['workload']}: skipped {row['role']} ({row['component']}) has no landing slot")
        if row['source'] == 'design' and row['role'] in record['dispatched_roles']:
            problems.append(f"{record['workload']}: {row['role']} is listed as skipped but was dispatched")
    return problems


# ---- the chain record (REL-G G2/G6 input) ----------------------------------------------------

def chain_record(root, workload, chain, tripwire):
    from ravel.workflow import production_executor as executor
    workers = chain['workers']
    dispatched = sorted(set(workers.roles()))
    inside, outside = derived(root)
    observation = chain['observation']
    nodes = {n['id']: executor.node_record(root, n['id']) for n in workload['plan']['nodes']}
    return {'schema_version': 1, 'kind': 'workload-chain-record', 'workload': workload['id'],
            'graphs': sorted({c['graph_id'] for c in workers.calls if c['graph_id']}),
            'stops': chain['stops'], 'terminal': observation['terminal'],
            'dispatched_roles': dispatched, 'derived_roles': sorted(inside),
            'skipped': skipped(workload, set(dispatched), outside),
            'calls': deepcopy(workers.calls),
            'nodes': {k: (v or {}).get('executor') for k, v in nodes.items()},
            'tripwire': {'mode': '1', 'verdicts': len(tripwire),
                         'layers': sorted({v['layer'] for v in tripwire}),
                         'violations': [v for v in tripwire if not v['ok']]},
            'refused_connections': list(chain.get('refused_connections', [])),
            'plan_sha256': digest(plan_of(workload))}


def keep(record):
    """Write the chain record where the release gate collects it (``RAVEL_CHAIN_RECORD_DIR``), if set."""
    target = os.environ.get('RAVEL_CHAIN_RECORD_DIR')
    if not target:
        return None
    path = Path(target) / f"{record['workload']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1, sort_keys=True, default=str) + '\n')
    return path


# ---- L-10 grader -----------------------------------------------------------------------------

def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def score(root, workload, expectation):
    """L-10 grading of a finished chain: ``{raw, strict, reason}``.

    Before any comparison the result must be (1) present and non-empty, (2) produced inside the
    chain: the scored node's production record names an ok worker receipt for the plan's role
    and the receipt credits the result bytes, (3) not the reference itself, and (4) substantive:
    a declared verdict and a finite quantity. Any failure scores 0 on both scales. Raw is the
    verdict; strict also needs the quantity inside the tolerance declared before the run.
    """
    from ravel.workflow import production_executor as executor
    node = workload['scored_node']
    rel = f'outputs/{node}/result.json'
    path = Path(root) / rel
    zero = lambda reason: {'raw': 0, 'strict': 0, 'reason': reason}
    if not path.is_file() or not path.read_bytes().strip():
        return zero('empty')
    try:
        value = json.loads(path.read_text())
    except ValueError:
        return zero('format_only')
    record = executor.node_record(root, node)
    receipt = (record or {}).get('receipt') or {}
    worker = _worker_receipt(root, receipt)
    expected_role = executor.role_for(next(n for n in workload['plan']['nodes'] if n['id'] == node))
    credited = {o.get('sha256') for o in (worker or {}).get('credited_outputs', [])}
    if (record is None or record.get('executor') != 'worker' or worker is None or worker.get('status') != 'ok'
            or worker['role']['id'] != expected_role or hashlib.sha256(path.read_bytes()).hexdigest() not in credited):
        return zero('no_custody')
    if (value == expectation or digest(value) == digest(expectation)
            or isinstance(value, dict) and set(value) & set(expectation) - {'verdict', 'quantity', 'value'}):
        return zero('copied_reference')
    if (not isinstance(value, dict) or value.get('verdict') not in VERDICTS
            or value.get('quantity') != expectation['quantity'] or not _finite(value.get('value'))):
        return zero('format_only')
    raw = int(value['verdict'] == expectation['verdict'])
    tolerance = expectation['tolerance']
    inside = abs(value['value'] - expectation['value']) <= tolerance['relative'] * abs(expectation['value'])
    return {'raw': raw, 'strict': int(raw == 1 and inside), 'reason': 'scored'}


def _worker_receipt(root, receipt):
    """The dispatcher's receipt for the node's credited attempt, read from the run's agent work tree."""
    node_id, attempt = receipt.get('node_id'), receipt.get('attempt')
    if not node_id or not attempt:
        return None
    for path in sorted(Path(root).glob(f'**/{node_id}/{attempt}/receipt.json')):
        value = json.loads(path.read_text())
        if value.get('kind') == 'agent-worker-receipt' and value.get('node_id') == node_id:
            return value
    return None


def observed_tripwire():
    from ravel.workflow import agent_tripwire
    return list(agent_tripwire.OBSERVED)


def reset_tripwire():
    from ravel.workflow import agent_tripwire
    agent_tripwire.OBSERVED.clear()
