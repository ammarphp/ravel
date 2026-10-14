"""Synthetic runs and stub workers for the production executor and lifecycle graph tests.

``Workers`` stands in for ``agent_worker.dispatch`` (a stub transport): it materializes the
real workspace, writes the role's outputs and closes the attempt with ``agent_worker.finish``,
so production receipts are the dispatcher's own custody records. A review item's own version-2
receipt carries ``review_subject`` and earns its credit. No model, sandbox, network or native
tool is involved.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from ravel.workflow import agent_worker, graph_nodes
from test_agent_worker import put

PROVIDERS = ('review_points', 'rdj', 'ceilings', 'executor', 'spawn_rows', 'input_closure', 'raw_launch')
OPTIONS = ('graph', 'framework_step', 'packet', 'protected', 'effect')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def run_root(tmp_path):
    from rdj_fixtures import Run
    return Run(tmp_path.resolve() / 'run', snapshot=False).root


def plan(root, *, nodes=(), edges=(), claims=(), delegated=False, trap_sweep=False):
    value = {'nodes': list(nodes), 'edges': list(edges), 'claims': list(claims), 'trap_sweep': trap_sweep}
    pin = write(root / 'inputs/request_plan.json', value)
    pin['path'] = 'inputs/request_plan.json'
    path = root / 'inputs/task_contract.json'
    contract = json.loads(path.read_text()) if path.exists() else {}
    write(path, {**contract, 'agent_layer_epoch': 2, 'delegated': delegated, 'request_plan': pin})
    write(root / 'inputs/checkin1.json', {'schema_version': 1, 'kind': 'checkin1', 'sections': {}})
    return value


def edge(source, target, ident=None):
    return {'id': ident or f'E-{source}-{target}', 'from': {'ref': source}, 'to': {'ref': target, 'slot': 'in'}}


def approve_checkin1(root, monkeypatch):
    """A synthetic CHECK-IN 1 approval record; its live verification is stubbed for the synthetic run."""
    from ravel.workflow import workflow_state
    from ravel.workflow.graphs import lifecycle
    write(root / 'inputs/checkin1_approval.json', {'schema_version': 2, 'generated_by': 'synthetic',
                                                    'approved_plan': 'full', 'quote': 'Approved as planned'})
    monkeypatch.setattr(workflow_state, 'verify_approval', lambda *a, **k: [])
    monkeypatch.setattr(lifecycle, 'checkin1_errors', lambda root: [])
    return {'path': 'inputs/checkin1_approval.json',
            'sha256': hashlib.sha256((root / 'inputs/checkin1_approval.json').read_bytes()).hexdigest()}


def science_approve(root):
    """The science.approve record shape the review graph's human gates verify (synthetic quote)."""
    from ravel.workflow.graphs.review import APPROVER
    from ravel.workflow.science import APPROVAL
    pin = write(root / APPROVAL, {'generated_by': APPROVER, 'schema_version': 2, 'quote': 'Approved'})
    return {'path': APPROVAL, 'sha256': pin['sha256']}


def no_self_checks(monkeypatch):
    """Production roles' self-checks need registered validators the stub cannot run (handoff U5)."""
    from ravel.workflow import role_registry
    monkeypatch.setattr(role_registry, 'self_checks', lambda role, **k: [])


def reviewed(rundir, spec, ws, findings):
    """Close a review attempt as a transport adapter would: the output through the broker, and an
    execution record with a transport attestation and a distinct session and actor. The dispatcher
    writes the version-2 receipt and registers it; that receipt is the review credit."""
    from ravel.workflow import broker
    tool = broker.Broker(rundir, ws, node_id=spec['node_id'], attempt=spec['attempt'], allowed_actions=['write'],
                         max_calls=100)
    reply = tool.call({'call_id': 'put-' + spec['node_id'], 'action': 'write',
                       'args': {'path': 'outputs/review.json', 'content': json.dumps({'findings': findings})}})
    assert reply['status'] == 'ok', reply
    role = spec['role']['id']
    execution = {'exit_status': 0, 'attestation': 'transport_attested', 'session_id': spec['node_id'],
                 'actor_id': spec['node_id'], 'model': {'requested': None, 'observed': None, 'family': role, 'effort': None}}
    return agent_worker.finish(rundir, spec, execution=execution,
                               final={'completed': True, 'disposition': 'supported', 'findings': findings})


class Workers:
    """Stub transport for every role the executor and the review graph dispatch."""

    def __init__(self, root, *, fail_once=()):
        self.root = Path(root)
        self.fail = set(fail_once)
        self.calls = []

    def __call__(self, rundir, spec, **options):
        role = spec['role']['id']
        assert graph_nodes.TRIPWIRE.get() is None or graph_nodes.TRIPWIRE.get()['ravel_kind'] == 'agent'
        ws = agent_worker.materialize(rundir, spec, **{k: v for k, v in options.items() if k in OPTIONS})
        self.calls.append({'role': role, 'node_id': spec['node_id'], 'attempt': spec['attempt'],
                           'transport_preference': list(spec['transport_preference']),
                           'map_id': spec['parent']['map_id']})
        if role in self.fail:
            self.fail.discard(role)
            return agent_worker.finish(rundir, spec, final=None, execution={'exit_status': 1})
        if spec['parent']['map_id'].startswith('review:'):
            return self._review(rundir, spec, ws, role)
        order_path = ws / 'inputs/work-order.json'
        if order_path.exists():
            order = json.loads(order_path.read_text())
            sidecar = {'obligations': {row['id']: {'checked': True, 'by': role} for row in order['obligations']},
                       'node_id': order['node_id']}
            for output in order['declared_outputs']:
                put(rundir, ws, output['path'], json.dumps(sidecar))
        return agent_worker.finish(rundir, spec, execution={'exit_status': 0}, final={'completed': True})

    def _review(self, rundir, spec, ws, role):
        packet = json.loads((ws / 'inputs/review-packet.json').read_text())
        worker = reviewed(rundir, spec, ws, [])
        assert worker['review_subject']['sha256'] == packet['subject_sha256']
        return worker

    def roles(self):
        return [c['role'] for c in self.calls]


def providers(gate):
    return {p: True for p in PROVIDERS}


def drive(root, monkeypatch, workers, **options):
    from ravel.workflow.graphs import lifecycle
    monkeypatch.setattr(agent_worker, 'dispatch', workers)
    options.setdefault('gate_check', lambda *a: [])
    try:
        return lifecycle.run(root, gate_providers=providers, **options)
    finally:
        graph_nodes.forget_handled()


def answer(root, monkeypatch, workers, decision, record=None, **options):
    from ravel.workflow.graphs import lifecycle
    monkeypatch.setattr(agent_worker, 'dispatch', workers)
    try:
        return lifecycle.respond(root, decision=decision, record=record, gate_check=lambda *a: [],
                                 gate_providers=providers, **options)
    finally:
        graph_nodes.forget_handled()


def interrupt_schema(observation):
    return [i['schema_id'] for i in observation['interrupts']]


def deep(value):
    return deepcopy(value)
