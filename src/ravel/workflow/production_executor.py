"""Production executors: work orders, dispatch, adoption, host waivers and the executor provider.

- ``data/roles/executors.json`` maps a plan node's operation to its production role. Its
  ``coordinator`` block states what the host may do itself (plan, route, dispatch, present
  CHECK-INs, run smoke rungs); it edits nothing under ``stages/`` at the full or scan rung.
- ``seal_orders`` writes ``inputs/work-orders/<node>.json`` for every production node before
  CHECK-IN 1 (role, input pins, handbooks, self-checks, consults, budgets, review points,
  declared outputs and the node's stage); ``work_dispatch.pin_obligations`` then pins them.
- ``next_order`` returns the next pending node whose production parents are complete.
  ``dispatch`` launches the role's governed worker through ``agent_worker.dispatch``;
  ``adopt`` brings its checked output bytes into the run (``work_dispatch.adopt``).
- ``waive`` records ``executor: host`` with a reason. A waiver is listed by
  ``host_authored_nodes`` for the CHECK-IN 2 packet and the delivery record; under
  delegation it counts only with an R2 (or higher) RDJ authorize receipt for its bytes.
- ``gate_errors`` is the ``executor`` provider of ``decision_gate``: a ``launch`` at the full or
  scan rung needs the node's ok worker receipt or a valid waiver. Smoke and dry rungs pass.
- ``launch_stage`` runs a node's compute through ``stage_supervisor.supervise`` (which holds the
  machine lease) and, after a supervised success, registers the stage receipt and, for a
  ``python -m ravel.*`` command, the module origin in RAVEL custody.

Nothing here grants scientific acceptance. The plan and ``workflow_state`` remain the
lifecycle authority; the custody records hold the credit.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from .decision_gate import GateError
from .state_io import atomic_json, read_json

PROVIDER = 'executor'
DATA = Path(__file__).resolve().parents[1] / 'data' / 'roles' / 'executors.json'
ORDERS = 'inputs/work-orders'
NODES = 'production/nodes'
WAIVERS = 'production/waivers'
WAIVER_CLASSES = ('R2', 'R3')


class ExecutorRefused(ValueError):
    """The executor refused a launch before anything started; ``errors`` are gate errors."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__('launch refused: ' + '; '.join(f'{e.provider}:{e.code}: {e.message}' for e in self.errors))


def _utc():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return _sha(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode())


def _pin(root, rel):
    return {'path': rel, 'sha256': _sha((Path(root) / rel).read_bytes())}


def default_output(node_id):
    """The obligations sidecar a node declares when its plan names no outputs (one run path per node)."""
    return {'path': f'outputs/{node_id}/obligations.json', 'kind': 'obligations', 'required': True}


def executors():
    value = read_json(DATA)
    if value.get('kind') != 'production-executors' or value.get('schema_version') != 1:
        raise ValueError('executors.json is not a version-1 production-executors record')
    return value


# ---------------------------------------------------------------- plan and orders

def _facts(rundir):
    from .review_points import _facts as facts
    return facts(Path(rundir))


def role_for(node, table=None):
    """The production role for a plan node: its declared ``role`` or its operation's executor."""
    table = table or executors()
    if node.get('role'):
        return node['role']
    return table['operations'].get(node.get('operation'))


def production_nodes(facts):
    """Plan nodes that have an executor role, in a stable topological order (edges, then id)."""
    table = executors()
    plan = facts.get('plan') or {}
    nodes = {n['id']: n for n in plan.get('nodes', []) if role_for(n, table)}
    parents = {nid: set() for nid in nodes}
    for edge in plan.get('edges', []):
        source, target = edge['from']['ref'], edge['to']['ref']
        if source in nodes and target in nodes:
            parents[target].add(source)
    ordered, done = [], set()
    while len(ordered) < len(nodes):
        ready = sorted(n for n in nodes if n not in done and parents[n] <= done)
        if not ready:
            raise ValueError('production nodes form a cycle')
        ordered.append(ready[0])
        done.add(ready[0])
    return [{**nodes[n], 'parents': sorted(parents[n])} for n in ordered]


def build_order(rundir, node, facts=None):
    """The work order for one node, derived by code from the plan, the role card and review points."""
    from . import review_points, role_registry
    facts = facts if facts is not None else _facts(rundir)
    table = executors()
    role = role_for(node, table)
    card = role_registry.load(role)
    points = [{'id': p['id'], 'row': p['row'], 'gate': p['gate']} for p in review_points.derive(facts)
              if p.get('node_id') == node['id']]
    inputs = []
    for rel in node.get('input_paths', []):
        inputs.append(_pin(rundir, rel))
    order = {'schema_version': 1, 'kind': 'work-order', 'node_id': node['id'], 'role': role,
             'operation': node.get('operation'), 'rung': node.get('rung'), 'executor': node.get('executor', 'worker'),
             'inputs': inputs, 'handbooks': list(card['knowledge']['must_read']),
             'self_check': role_registry.self_checks(role), 'consults': deepcopy(card['knowledge']['consult']),
             'budgets': deepcopy(table['budgets']), 'review_points': points,
             'declared_outputs': deepcopy(node.get('outputs') or [default_output(node['id'])]),
             'stage': deepcopy(node.get('stage'))}
    bindings = [row['value'] for row in node.get('fields', []) if row['pointer'] == '/check_inputs']
    if len(bindings) > 1 or bindings and (type(bindings[0]) is not dict
            or any(type(parameters) is not dict for parameters in bindings[0].values())):
        raise ValueError('one check_inputs parameter object is required')
    if bindings:
        order['check_inputs'] = deepcopy(bindings[0])
    from .work_dispatch import derive_obligations
    order['obligations'] = derive_obligations(order)
    order['order_sha256'] = _order_digest(order)
    return order


def _order_digest(order):
    from .work_order_fidelity import digest
    return digest(order)


def order_path(rundir, node_id):
    return Path(rundir) / ORDERS / (node_id + '.json')


def seal_orders(rundir):
    """Write each production node's order once, before CHECK-IN 1 approval. Idempotent for equal bytes."""
    root = Path(rundir)
    facts = _facts(root)
    nodes = production_nodes(facts)
    if (root / 'inputs/checkin1_approval.json').exists() and not all(order_path(root, n['id']).is_file() for n in nodes):
        raise ValueError('work orders are sealed before CHECK-IN 1 approval; nothing was written')
    sealed = []
    for node in nodes:
        order = build_order(root, node, facts)
        path = order_path(root, node['id'])
        if path.is_symlink():
            raise ValueError('work order path must be a regular file: ' + str(path))
        if path.exists():
            if read_json(path) != order:
                raise ValueError('a sealed work order differs from the plan: ' + node['id'])
        else:
            atomic_json(path, order)
        sealed.append({'node_id': node['id'], **_pin(root, f'{ORDERS}/{node["id"]}.json')})
    return sealed


def load_order(rundir, node_id):
    from . import work_order_fidelity as fidelity
    path = order_path(rundir, node_id)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'no sealed work order for {node_id}; run seal_orders before CHECK-IN 1')
    order = fidelity.read_json(path)
    if order.get('kind') != 'work-order' or order.get('node_id') != node_id or order.get('order_sha256') != _order_digest(order):
        raise ValueError(f'work order {node_id} changed after sealing')
    return order


# ---------------------------------------------------------------- node status

def node_record(rundir, node_id):
    path = Path(rundir) / NODES / (node_id + '.json')
    return read_json(path) if path.is_file() and not path.is_symlink() else None


def complete(rundir, node_id, *, executor, receipt=None, waiver=None, adoption=None, stage=None):
    """Write the node's completion record once; an equal record is a no-op."""
    value = {'schema_version': 1, 'kind': 'production-node', 'node_id': node_id, 'executor': executor,
             'order_sha256': load_order(rundir, node_id)['order_sha256'], 'receipt': receipt, 'waiver': waiver,
             'adoption': adoption, 'stage': stage, 'scientific_acceptance': False}
    path = Path(rundir) / NODES / (node_id + '.json')
    if path.exists():
        previous = read_json(path)
        if {k: v for k, v in previous.items() if k != 'completed_utc'} != value:
            raise ValueError(f'production node {node_id} already completed with a different record')
        return previous
    atomic_json(path, {**value, 'completed_utc': _utc()})
    return read_json(path)


def pending(rundir, facts=None):
    """Production nodes not yet complete, each with whether its production parents are complete."""
    facts = facts if facts is not None else _facts(rundir)
    nodes = production_nodes(facts)
    done = {n['id'] for n in nodes if node_record(rundir, n['id'])}
    return [{'node_id': n['id'], 'role': role_for(n), 'rung': n.get('rung'), 'ready': set(n['parents']) <= done}
            for n in nodes if n['id'] not in done]


def next_order(rundir):
    """``ravel work next``: the next pending node and its sealed work order, or None when all are complete."""
    for row in pending(rundir):
        if row['ready']:
            order = load_order(rundir, row['node_id'])
            return {'node_id': row['node_id'], 'order': order,
                    'order_pin': _pin(rundir, f'{ORDERS}/{row["node_id"]}.json')}
    return None


# ---------------------------------------------------------------- dispatch and adoption

def worker_spec(rundir, node_id, attempt=1, *, transport_preference=None):
    """The governed worker spec for a node's role, carrying its sealed work order."""
    from . import role_registry
    order = load_order(rundir, node_id)
    card = role_registry.load(order['role'])
    preference = transport_preference
    if preference is None:
        path = Path(rundir) / 'inputs/agent_preferences.json'
        value = read_json(path) if path.is_file() else {}
        preference = value.get('transport_preference') if type(value) is dict else None
    budgets = order['budgets']
    return {'schema_version': 1, 'kind': 'agent-worker-spec', 'node_id': node_id, 'attempt': attempt,
            'role': {'id': card['id'], 'version': card['version'], 'card_sha256': role_registry.card_sha256(order['role'])},
            'transport_preference': list(preference) if type(preference) is list and preference else ['default'],
            'inputs': [{'pin': pin, 'as': 'inputs/' + Path(pin['path']).name} for pin in order['inputs']],
            'declared_outputs': [{k: row[k] for k in ('path', 'kind', 'required')} for row in order['declared_outputs']],
            'budgets': {k: budgets[k] for k in ('max_turns', 'max_wall_seconds', 'max_broker_calls', 'max_cost_usd')},
            'final_record_schema': 'producer.v1', 'work_order': _pin(rundir, f'{ORDERS}/{node_id}.json'),
            'rdj_challenges': None, 'parent': {'review_point_id': None, 'map_id': 'production:' + node_id, 'rca_ticket': None}}


def dispatch(rundir, node_id, attempt=1, *, transport_preference=None, **options):
    """``ravel work dispatch --node``: launch the node's role worker; the dispatcher writes the receipt."""
    from . import agent_worker
    if load_order(rundir, node_id).get('executor') == 'host':
        raise ValueError(f'node {node_id} is host-authored under a waiver; nothing is dispatched')
    return agent_worker.dispatch(Path(rundir), worker_spec(rundir, node_id, attempt,
                                                           transport_preference=transport_preference), **options)


def bound_to_sealed_order(rundir, node_id, attempt, receipt):
    """True when the attempt's dispatcher record and its receipt bind the node's sealed order.

    The dispatcher's custody record must pin exactly the sealed order file as it is now, and the
    receipt's request digest must be the digest of that recorded request. A worker dispatched
    without an order, or with another order, holds no production credit for the node."""
    from . import agent_worker, broker
    try:
        load_order(rundir, node_id)  # the sealed order still verifies
        spec = agent_worker._record(Path(rundir), node_id, attempt)['spec']
        request = broker.digest({'role': spec['role'], 'work_order': spec['work_order'], 'inputs': spec['inputs'],
                                 'budgets': spec['budgets']})
        return (spec['work_order'] == _pin(rundir, f'{ORDERS}/{node_id}.json')
                and receipt.get('request_sha256') == request)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def worker_receipt(rundir, node_id):
    """The latest ok, custody-verified worker receipt for the node that is bound to its sealed order, or None."""
    from . import agent_worker
    found = None
    for attempt in range(1, 1001):
        if not agent_worker.dispatched(Path(rundir), node_id, attempt):
            break
        try:
            receipt = agent_worker.load_receipt(Path(rundir), node_id, attempt)
        except (OSError, ValueError):
            continue
        if (receipt['status'] == 'ok' and receipt.get('role', {}).get('id') == load_order(rundir, node_id)['role']
                and bound_to_sealed_order(rundir, node_id, attempt, receipt)):
            found = receipt
    return found


def adopt(rundir, node_id, attempt):
    """Adopt a worker's checked outputs and return the adoption summary (``work_dispatch.adopt``)."""
    from . import work_dispatch
    return work_dispatch.adopt(Path(rundir), node_id, attempt)


# ---------------------------------------------------------------- host waivers

def waiver_path(rundir, node_id):
    return Path(rundir) / WAIVERS / (node_id + '.json')


def waive(rundir, node_id, reason):
    """Record ``executor: host`` for a node the host authors itself; never replaces a recorded waiver."""
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('a host waiver states its reason')
    order = load_order(rundir, node_id)
    value = {'schema_version': 1, 'kind': 'host-waiver', 'node_id': node_id, 'executor': 'host',
             'reason': reason.strip(), 'role': order['role'], 'rung': order.get('rung'),
             'order_sha256': order['order_sha256'], 'recorded_utc': _utc()}
    path = waiver_path(rundir, node_id)
    if path.exists():
        raise ValueError(f'node {node_id} already has a host waiver')
    atomic_json(path, value)
    return {'waiver': _pin(rundir, f'{WAIVERS}/{node_id}.json'), 'action': waiver_action(rundir, node_id)}


def waiver_action(rundir, node_id):
    """The RDJ action an R2 receipt must authorize for a waiver under delegation."""
    pin = _pin(rundir, f'{WAIVERS}/{node_id}.json')
    return {'kind': 'host_waiver', 'digest': pin['sha256'], 'summary': f'host authors plan node {node_id}',
            'pins': [pin], 'node_id': node_id, 'floor': 'R2'}


def waiver_errors(rundir, node_id, *, gate='launch'):
    """Why the node's waiver does not count (empty when it counts)."""
    def error(code, message, fix):
        return GateError(code, gate, PROVIDER, message, fix, (f'{WAIVERS}/{node_id}.json',))
    path = waiver_path(rundir, node_id)
    if path.is_symlink() or not path.is_file():
        return [error('executor_waiver_missing', f'node {node_id} has no host waiver', 'ravel work waive --node')]
    value = read_json(path)
    try:
        order = load_order(rundir, node_id)
    except ValueError as exc:
        return [error('executor_order_invalid', str(exc), 'reseal the work orders before CHECK-IN 1')]
    if value.get('kind') != 'host-waiver' or value.get('node_id') != node_id or value.get('order_sha256') != order['order_sha256']:
        return [error('executor_waiver_invalid', f'the waiver for {node_id} names another order', 'record a new waiver')]
    if _facts(rundir).get('delegated'):
        from . import rdj_loop
        accepted = rdj_loop.authorizing_receipt(rundir, gate, waiver_action(rundir, node_id))
        cls = ((accepted or {}).get('case') or {}).get('risk', {}).get('class')
        if cls not in WAIVER_CLASSES:
            return [error('executor_waiver_unauthorized', f'a delegated host waiver for {node_id} needs an R2 RDJ '
                          'authorize receipt for its bytes', 'open an RDJ case on the waiver action at R2')]
    return []


def host_authored_nodes(rundir):
    """Waived nodes for the CHECK-IN 2 packet and the delivery record (``host_authored_nodes``)."""
    root = Path(rundir)
    rows = []
    for path in sorted((root / WAIVERS).glob('*.json')):
        value = read_json(path)
        node_id = value.get('node_id')
        rows.append({'node_id': node_id, 'executor': 'host', 'reason': value.get('reason'), 'rung': value.get('rung'),
                     'waiver': _pin(root, f'{WAIVERS}/{path.name}'),
                     'counts': not waiver_errors(root, node_id)})
    return rows


# ---------------------------------------------------------------- the executor provider

def gate_errors(rundir, gate, action):
    """Provider ``executor``: a full or scan ``launch`` needs a worker receipt or a valid host waiver."""
    if gate != 'launch' or not isinstance(action, dict):
        return []
    rung = action.get('rung')
    if rung not in executors()['worker_rungs']:
        return []
    node_id = action.get('node_id')
    if not isinstance(node_id, str) or not node_id:
        return [GateError('executor_node_missing', gate, PROVIDER, f'a {rung} launch names no plan node',
                          'launch through the production executor, which names the node', ('action:node_id',))]
    try:
        order = load_order(rundir, node_id)
    except ValueError as exc:
        return [GateError('executor_order_invalid', gate, PROVIDER, str(exc), 'seal the work orders before CHECK-IN 1',
                          (f'{ORDERS}/{node_id}.json',))]
    if order.get('executor') == 'host' or waiver_path(rundir, node_id).exists():
        return waiver_errors(rundir, node_id, gate=gate)
    if worker_receipt(rundir, node_id) is not None:
        return []
    return [GateError('executor_receipt_missing', gate, PROVIDER,
                      f'plan node {node_id} at the {rung} rung has no ok worker receipt for role {order["role"]} and no host waiver',
                      'ravel work dispatch --node ' + node_id + ', or record a host waiver with its reason',
                      (f'{ORDERS}/{node_id}.json',))]


# ---------------------------------------------------------------- stage launch and receipts

def module_origin(command):
    """``{module, module_origin, module_sha256}`` for ``python -m ravel.<module>``, else None."""
    command = [str(t) for t in command or ()]
    if len(command) < 3 or command[1] != '-m' or not Path(command[0]).name.startswith('python'):
        return None
    module = command[2]
    if not module.startswith('ravel.'):
        return None
    spec = importlib.util.find_spec(module)
    if spec is None or not spec.origin:
        raise ValueError(f'stage module {module} is not installed')
    origin = Path(spec.origin).resolve()
    package = Path(importlib.util.find_spec('ravel').origin).resolve().parent
    if not origin.is_relative_to(package):
        raise ValueError(f'stage module {module} resolves outside RAVEL ({origin})')
    return {'module': module, 'module_origin': str(origin), 'module_sha256': _sha(origin.read_bytes())}


def register_stage(rundir, stage):
    """Register the stage's succeeded receipt and its module origin in custody; idempotent."""
    from . import execution, rdj_custody
    record = execution.load_execution(rundir)['stages'].get(stage)
    if not isinstance(record, dict) or record.get('status') != 'succeeded':
        raise ValueError(f'stage {stage} has no succeeded execution receipt')
    attempt = record['attempt_id']
    if not rdj_custody.stage_receipt_registered(rundir, stage, attempt, record):
        rdj_custody.register_stage_receipt(rundir, stage, attempt)
    origin = module_origin(record.get('command'))
    if origin is not None and registered_origin(rundir, stage, attempt) is None:
        rdj_custody.append(rundir, 'stages', {'stage': stage, 'attempt_id': attempt, 'kind': 'module_origin',
                                              'record_sha256': rdj_custody._digest(record), **origin})
    return {'stage': stage, 'attempt_id': attempt, 'receipt_id': f'stage:{stage}:{attempt}', 'module_origin': origin}


def registered_origin(rundir, stage, attempt_id):
    """The custody module-origin row for a stage attempt whose module file still has its bytes, or None."""
    from . import rdj_custody
    found = None
    for row in rdj_custody.rows(rundir, 'stages'):
        record = row['record']
        if record.get('kind') == 'module_origin' and record['stage'] == stage and record['attempt_id'] == attempt_id:
            found = record
    if found is None:
        return None
    origin = Path(found['module_origin'])
    if not origin.is_file() or _sha(origin.read_bytes()) != found['module_sha256']:
        raise ValueError(f'stage {stage} module {found["module"]} changed since its origin was registered')
    return found


def launch_action(node_id, *, stage, cmd, rung, inputs=(), outputs=()):
    value = {'node_id': node_id, 'stage': stage, 'command': [str(t) for t in cmd], 'rung': rung,
             'inputs': sorted(map(str, inputs)), 'outputs': sorted(map(str, outputs))}
    return {'kind': 'node_launch', 'digest': _digest(value), 'summary': f'launch {stage} for plan node {node_id}',
            'pins': [], 'node_id': node_id, 'rung': rung, 'scope': None}


def launch_errors(rundir, action, *, gate_check='decision_gate'):
    """The launch refusals for ``action``: the executor provider always, plus ``gate_check``.

    ``gate_check`` is ``decision_gate.check`` by default; the production graph, which has already
    passed its ``launch`` gate node, passes None and only the executor provider is re-checked.
    """
    root = Path(rundir).resolve()
    errors = list(gate_errors(root, 'launch', action))
    if gate_check == 'decision_gate':
        from . import decision_gate
        errors += [e for e in decision_gate.check(root, 'launch', action) if e.provider != PROVIDER]
    elif callable(gate_check):
        errors += list(gate_check(root, 'launch', action))
    return errors


def launch_stage(rundir, node_id, *, stage, cmd, events, rung, inputs=(), outputs=(), logrel=None,
                 gate_check='decision_gate', **supervise_options):
    """Host-plane launch of a node's stage: the full ``launch`` decision gate, then the supervisor
    (which holds the machine lease), then stage-receipt and module-origin registration."""
    from . import stage_supervisor
    root = Path(rundir).resolve()
    action = launch_action(node_id, stage=stage, cmd=cmd, rung=rung, inputs=inputs, outputs=outputs)
    errors = launch_errors(root, action, gate_check=gate_check)
    if errors:
        raise ExecutorRefused(errors)
    code = stage_supervisor.supervise(stage, root, events, logrel or f'logs/{stage}.log', list(cmd),
                                      inputs=list(inputs), outputs=list(outputs), required_plan=rung, node_id=node_id,
                                      **supervise_options)
    result = {'node_id': node_id, 'stage': stage, 'exit_code': code, 'action_digest': action['digest']}
    if code == 0:
        result['registered'] = register_stage(root, stage)
    return result


# ---------------------------------------------------------------- CLI

def _print(value):
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def main(argv=None):
    """``ravel work next|seal|dispatch --node|waive|host-authored``; other work subcommands delegate."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    own = {'next', 'seal', 'waive', 'host-authored', 'executor-status'}
    if not arguments or not (arguments[0] in own or arguments[0] == 'dispatch' and '--node' in arguments):
        from .work_cli import main as work
        return work(arguments)
    ap = argparse.ArgumentParser(prog='ravel work', description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='command', required=True)
    for name, text in (('next', 'the next pending plan node and its work order'),
                       ('seal', 'seal every production node\'s work order before CHECK-IN 1'),
                       ('host-authored', 'host-authored (waived) nodes for CHECK-IN 2 and delivery'),
                       ('executor-status', 'pending production nodes')):
        sub.add_parser(name, help=text).add_argument('--rundir', type=Path, required=True)
    command = sub.add_parser('dispatch', help='dispatch the node\'s role worker from its sealed work order')
    command.add_argument('--rundir', type=Path, required=True)
    command.add_argument('--node', required=True)
    command.add_argument('--attempt', type=int, default=1)
    command = sub.add_parser('waive', help='record executor: host for a node, with its reason')
    command.add_argument('--rundir', type=Path, required=True)
    command.add_argument('--node', required=True)
    command.add_argument('--reason', required=True)
    args = ap.parse_args(arguments)
    try:
        if args.command == 'next':
            _print(next_order(args.rundir))
        elif args.command == 'seal':
            _print(seal_orders(args.rundir))
        elif args.command == 'host-authored':
            _print(host_authored_nodes(args.rundir))
        elif args.command == 'executor-status':
            _print(pending(args.rundir))
        elif args.command == 'dispatch':
            receipt = dispatch(args.rundir, args.node, args.attempt)
            _print(receipt)
            return 0 if receipt.get('status') == 'ok' else 1
        else:
            _print(waive(args.rundir, args.node, args.reason))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'ravel work: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
