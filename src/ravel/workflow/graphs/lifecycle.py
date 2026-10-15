"""``lifecycle.drive``: the run lifecycle on the graph substrate, and ``ravel drive``.

```
coordinate (coordinator card as a worker, once) ─► guard ─► sync (plan, workflow_state, records)
  ├ review:<at>  ─► review.points at <at> (subgraph) ─────────────────────────────► guard
  ├ checkin1     ─► seal orders, pin obligations ─► interrupt(checkin1_response) ─► gate(approve_plan + record) ─► guard
  ├ node         ─► production.node (subgraph) ────────────────────────────────────► guard
  ├ checkin2     ─► interrupt(checkin2_response) ─► gate(checkin2_accept + record) ─► guard
  ├ blocked      ─► hold
  └ done         ─► END
```

The plan and ``workflow_state`` remain the lifecycle authority: ``sync`` derives the next
step from the pinned request plan, the CHECK-IN records, the review points still
pending and the production node records, never from graph state alone. Order:
CHECK-IN 1 (plan-critic review, then the human approval), production nodes below the
full rung, CHECK-IN 2 (the claims' ``checkin2:<claim>`` review points, whose human
response the review graph asks for; without a claim this graph asks), the full and
scan nodes, then CHECK-IN 3 (the ``checkin3`` triad and its response). A resume value
is data: each human gate requires the run's own approval record, named by path and
sha256 in the response and re-verified here. The coordinator worker's output is
advisory; routing is code.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from typing import TypedDict

from .. import graph_nodes as nodes, graph_substrate
from .. import production_executor as executor
from ..agent_graph import GraphError
from ..state_io import read_json

GRAPH_ID = 'lifecycle.drive'
MAX_PASSES = 64
CHECKIN1_RECORD = 'inputs/checkin1_approval.json'
CHECKIN2_RECORD = 'inputs/checkin2_go.json'


class State(nodes.BaseState, total=False):
    drive: dict
    passes: int
    branch: str
    at: str
    node_id: str
    reviewed: dict
    produced: dict
    why: str


# ---- records the human gates require (monkeypatched only in synthetic tests) -----------------

def checkin1_errors(root):
    """The CHECK-IN 1 approval record's live verification (``workflow_state.verify_approval``)."""
    from .. import workflow_state
    return list(workflow_state.verify_approval(str(root)))


def checkin2_errors(root):
    """The CHECK-IN 2 GO record's live verification (``workflow_state.verify_checkin2_go``)."""
    from .. import workflow_state
    return list(workflow_state.verify_checkin2_go(str(root)))


RECORDS = {'checkin1_response': ('approve_plan', CHECKIN1_RECORD, 'checkin1_errors'),
           'checkin2_response': ('checkin2_accept', CHECKIN2_RECORD, 'checkin2_errors')}


def _approved(root, schema_id):
    gate, rel, check = RECORDS[schema_id]
    path = Path(root) / rel
    if path.is_symlink() or not path.is_file():
        return False
    return not globals()[check](root)


def record_errors(root, schema_id, response):
    """A human resume names the run's own approval record; its bytes and live verification must hold."""
    gate, rel, check = RECORDS[schema_id]

    def error(code, message, pins=()):
        return {'code': code, 'gate': gate, 'provider': 'lifecycle', 'message': message,
                'fix': f'record the approval ({rel}) and answer with its path and sha256', 'pins': list(pins)}
    if response is None:
        return [error('human_response_missing', 'no recorded human response precedes this gate')]
    value = response['value']
    if value.get('decision') != 'approve':
        return [error('human_not_approved', 'the human response is ' + str(value.get('decision')))]
    record = value.get('record')
    if type(record) is not dict:
        return [error('approval_record_missing', f'the human response names no approval record ({rel})')]
    expected = (Path(root) / rel).resolve()
    try:
        named = (Path(root) / record['path']).resolve()
    except (OSError, ValueError):
        named = None
    if named != expected or expected.is_symlink() or not expected.is_file():
        return [error('approval_record_missing', f'the named record is not this run\'s {rel}', [str(record.get('path'))])]
    if hashlib.sha256(expected.read_bytes()).hexdigest() != record['sha256']:
        return [error('approval_record_invalid', f'{rel} differs from the bytes the response names', [rel])]
    problems = globals()[check](root)
    if problems:
        return [error('approval_record_invalid', '; '.join(map(str, problems))[:1500], [rel])]
    return []


# ---- sync: the next lifecycle step from the run's own records ---------------------------------

def _root(state):
    return Path(state['meta']['scope_root'])


def _ats(facts, prefix):
    from .. import review_points
    return sorted({p['when']['at'] for p in review_points.derive(facts) if p['when']['at'].startswith(prefix)})


def derive(root, reviewed=None):
    """``{branch, at?, node_id?, why}`` for the run as its records stand now."""
    from .. import review_points
    reviewed = reviewed or {}
    facts = review_points._facts(root)
    if facts.get('agent_layer_epoch') != 2:
        raise nodes.RecoveryHold('lifecycle_epoch_two_only', 'epoch-one runs keep the existing ravel run lifecycle')
    if not _approved(root, 'checkin1_response'):
        if 'checkin1' not in reviewed and _ats(facts, 'checkin1'):
            return {'branch': 'review', 'at': 'checkin1', 'why': 'plan review points before CHECK-IN 1'}
        return {'branch': 'checkin1', 'why': 'CHECK-IN 1 has no verified approval record'}
    rungs = executor.executors()['worker_rungs']
    try:
        rows = executor.pending(root, facts)
    except executor.ExecutorRefused as exc:
        raise nodes.RecoveryHold(exc.errors[0].code, str(exc)) from exc
    early = [r for r in rows if r['rung'] not in rungs]
    late = [r for r in rows if r['rung'] in rungs]
    for group in (early,):
        ready = [r for r in group if r['ready']]
        if ready:
            return {'branch': 'node', 'node_id': ready[0]['node_id'], 'why': 'production node below the full rung'}
        if group:
            return {'branch': 'blocked', 'why': 'production nodes wait on parents that are not complete: '
                    + ', '.join(r['node_id'] for r in group)}
    claims = _ats(facts, 'checkin2')
    for at in claims:
        if at not in reviewed:
            return {'branch': 'review', 'at': at, 'why': 'CHECK-IN 2 review points for ' + at}
    if not claims and late and not _approved(root, 'checkin2_response'):
        return {'branch': 'checkin2', 'why': 'CHECK-IN 2 before the full rung has no verified GO record'}
    ready = [r for r in late if r['ready']]
    if ready:
        return {'branch': 'node', 'node_id': ready[0]['node_id'], 'why': 'production node at the full or scan rung'}
    if late:
        return {'branch': 'blocked', 'why': 'production nodes wait on parents that are not complete: '
                + ', '.join(r['node_id'] for r in late)}
    if 'checkin3' not in reviewed:
        return {'branch': 'review', 'at': 'checkin3', 'why': 'CHECK-IN 3 review points'}
    return {'branch': 'done', 'why': 'every production node is complete and CHECK-IN 3 passed'}


# ---- in-node subgraphs (the child checkpoints under this thread) ------------------------------

_COMPILED: dict = {}


def _child(scope_root, graph_id, instance):
    key = (str(scope_root), graph_id, json.dumps(instance, sort_keys=True))
    if key not in _COMPILED:
        ctx = graph_substrate.BuildContext(scope_root=Path(scope_root), graph_id=graph_id,
                                           version=graph_substrate.graph_registry.get(graph_id)['version'],
                                           instance=deepcopy(instance), row=graph_substrate.graph_registry.get(graph_id))
        _COMPILED[key] = graph_substrate.build(graph_id, ctx, checkpointer=None)
    return _COMPILED[key]


def _invoke(state, graph_id, instance, view, segment):
    from ..graph_nodes import _invoke_child, _meta, invocation
    meta = _meta(state)
    row = graph_substrate.graph_registry.get(graph_id)
    child_meta = {'graph_id': graph_id, 'version': row['version'], 'instance': deepcopy(instance),
                  'scope_root': meta['scope_root'], 'path': invocation(meta, segment)}
    compiled = _child(meta['scope_root'], graph_id, instance)
    return _invoke_child(compiled, {**view, 'meta': child_meta}, 'child')['results']['child']


def _review(state):
    at, attempt = state['at'], state['meta']['instance']['attempt']
    found = _invoke(state, 'review.points', {'at': at, 'attempt': attempt}, {}, {'review': at})
    return {'reviewed': {**(state.get('reviewed') or {}), at: found['outcome']}}


def _produce(state):
    node_id, attempt = state['node_id'], state['meta']['instance']['attempt']
    found = _invoke(state, 'production.node', {'node_id': node_id, 'attempt': attempt},
                    {'node': {'node_id': node_id, 'attempt': attempt}}, {'node': node_id})
    return {'produced': {**(state.get('produced') or {}), node_id: found['outcome']}}


# ---- the graph -----------------------------------------------------------------------------------

def _coordinator_spec(root, drive, attempt):
    from .. import role_registry
    card = role_registry.load('coordinator')
    budgets = executor.executors()['budgets']
    preference = drive.get('transport_preference') or ['default']
    return {'schema_version': 1, 'kind': 'agent-worker-spec', 'node_id': 'coordinator', 'attempt': attempt,
            'role': {'id': card['id'], 'version': card['version'], 'card_sha256': role_registry.card_sha256('coordinator')},
            'transport_preference': list(preference), 'inputs': [],
            'declared_outputs': [{'path': 'outputs/coordination.json', 'kind': 'coordination-note', 'required': False}],
            'budgets': dict(budgets), 'final_record_schema': 'producer.v1', 'work_order': None, 'rdj_challenges': None,
            'parent': {'review_point_id': None, 'map_id': 'lifecycle', 'rca_ticket': None}}


def _response(state, schema_id):
    found = [v for v in (state.get('responses') or {}).values() if v.get('schema_id') == schema_id]
    return found[-1] if found else None


def _action(state, gate_name):
    root = _root(state)
    rel = RECORDS['checkin1_response' if gate_name == 'approve_plan' else 'checkin2_response'][1]
    path = root / rel
    digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else hashlib.sha256(rel.encode()).hexdigest()
    return {'kind': 'lifecycle.' + gate_name, 'summary': 'CHECK-IN response for ' + gate_name, 'digest': digest,
            'pins': [], 'node_id': None, 'rung': None, 'scope': None}


def human_gate(gate_name, schema_id):
    base = nodes.gate(gate_name, lambda s: _action(s, gate_name))

    def body(state):
        update = base.function(state)
        verdict = update['gates'][gate_name]
        verdict['errors'] = verdict['errors'] + record_errors(_root(state), schema_id, _response(state, schema_id))
        verdict['providers'] = sorted({e.get('provider', '') for e in verdict['errors']})
        return update
    body.__name__ = 'human_gate_' + gate_name
    return nodes.Node('gate', body, gate=gate_name)


def _seal(state, identity):
    from .. import work_dispatch
    root = _root(state)
    try:
        sealed = executor.seal_orders(root)
    except executor.ExecutorRefused as exc:
        raise nodes.RecoveryHold(exc.errors[0].code, str(exc)) from exc
    pinned = None
    if sealed and (root / 'inputs/checkin1.json').is_file() and not (root / 'inputs/work-obligations.json').exists():
        pinned = work_dispatch.pin_obligations(root)
    return {'sealed': sealed, 'obligations': pinned}


def build(ctx):
    from langgraph.graph import END, START, StateGraph
    builder = StateGraph(State)
    add = lambda name, node: nodes.add(builder, name, node, graph_id=GRAPH_ID)
    run = ctx.scope_root
    add('decision_turn', nodes.decision_turn(GRAPH_ID))
    add('reconcile', nodes.reconcile_node())
    add('hold', nodes.hold('lifecycle_hold'))
    coordinator = nodes.agent('lifecycle.coordinator', rundir=run,
                              spec=lambda s: _coordinator_spec(run, s.get('drive') or {}, s['meta']['instance']['attempt']),
                              segment=lambda s: {'coordinate': s['meta']['instance']['attempt']},
                              to_state=lambda s, receipt: {'results': {'coordinator': {
                                  'status': receipt['status'], 'advisory': True}}})
    coordinator.kind, coordinator.role = 'agent', 'coordinator'
    add('coordinate', coordinator)

    def policy(state):
        return 'exhausted' if state.get('passes', 0) >= MAX_PASSES else 'go'
    add('guard', nodes.guard(policy, {'go': 'sync'}))

    def sync(state):
        found = derive(_root(state), state.get('reviewed'))
        return {'branch': found['branch'], 'at': found.get('at', ''), 'node_id': found.get('node_id', ''),
                'why': found['why'], 'passes': state.get('passes', 0) + 1}
    add('sync', nodes.Node('effect', sync))
    nodes.connect(builder, 'sync', nodes.route(lambda s: s['branch'], {
        'review': 'review', 'checkin1': 'seal', 'node': 'produce', 'checkin2': 'checkin2', 'blocked': 'blocked',
        'done': 'done'}))
    add('review', nodes.Node('subgraph', _review))
    nodes.connect(builder, 'review', nodes.route(
        lambda s: 'ok' if s['reviewed'][s['at']] == 'ok' else 'held', {'ok': 'guard', 'held': 'review_held'}))
    add('review_held', nodes.hold('lifecycle_review_held', 'the review points graph held or refused its gate; '
                                  'see ravel review status, then ravel drive with the next --attempt'))
    add('produce', nodes.Node('subgraph', _produce))
    nodes.connect(builder, 'produce', nodes.route(
        lambda s: 'ok' if s['produced'][s['node_id']] == 'ok' else 'held', {'ok': 'guard', 'held': 'node_held'}))
    add('node_held', nodes.hold('lifecycle_node_held', 'the production node held or failed; see its gates and '
                                'receipts, then ravel drive with the next --attempt'))
    add('seal', nodes.effect('lifecycle.seal', kind='journal', run=_seal, segment=lambda s: {'seal': 'orders'},
                             identity=lambda s: {'plan': 'sealed-before-checkin1'}, to_state=lambda s, r: {}))
    for schema_id, gate_name in (('checkin1_response', 'approve_plan'), ('checkin2_response', 'checkin2_accept')):
        name = schema_id.split('_')[0]
        source = 'seal' if name == 'checkin1' else None
        add(name, nodes.interrupt(schema_id, lambda s, n=name: {'checkin': n, 'why': s.get('why'),
                                                              'record': RECORDS[n + '_response'][1],
                                                              'host_authored_nodes': executor.host_authored_nodes(_root(s))},
                                  segment=lambda s, n=name: {'checkin': n}))
        if source:
            builder.add_edge(source, name)
        add(name + '_gate', human_gate(gate_name, schema_id))
        builder.add_edge(name, name + '_gate')
        nodes.connect(builder, name + '_gate', nodes.gate_route(gate_name, passed='guard', refused='refused'))
    add('refused', nodes.hold('lifecycle_checkin_refused', 'record the CHECK-IN approval and answer with its path '
                              'and sha256 through ravel drive --respond on the next --attempt'))
    add('blocked', nodes.hold('lifecycle_blocked'))

    def done(state):
        return {'results': {'lifecycle': {'complete': True, 'scientific_acceptance': False,
                                          'host_authored_nodes': executor.host_authored_nodes(_root(state))}}}
    add('done', nodes.Node('effect', done))
    builder.add_edge('done', END)
    builder.add_edge(START, 'coordinate')
    builder.add_edge('coordinate', 'guard')
    return builder


# ---- entry points ----------------------------------------------------------------------------------

def instance(attempt=1):
    if type(attempt) is not int or attempt < 1:
        raise ValueError('lifecycle instance requires a positive attempt')
    return {'attempt': attempt}


def run(rundir, *, attempt=1, transport=None, responses=None, gate_check=None, gate_providers=None,
        clear_stop=False, max_steps=None):
    """Start or continue the lifecycle; ``transport`` is the workers' transport preference (e.g. ravel-loop)."""
    key = instance(attempt)
    if responses:
        return graph_substrate.respond(rundir, GRAPH_ID, key, responses, gate_check=gate_check,
                                       gate_providers=gate_providers, clear_stop=clear_stop)
    drive = {'transport_preference': [transport] if transport else None}
    return graph_substrate.run(rundir, GRAPH_ID, key, input={'drive': drive}, gate_check=gate_check,
                               gate_providers=gate_providers, clear_stop=clear_stop, max_steps=max_steps)


def respond(rundir, *, decision, record=None, attempt=1, note=None, gate_check=None, gate_providers=None):
    """Answer the single pending CHECK-IN interrupt (``ravel drive respond``)."""
    from ..graph_substrate import _pending
    _, _, snapshot = _pending(rundir, GRAPH_ID, instance(attempt))
    pending = [p for p in snapshot.interrupts if isinstance(p.value, dict)
               and p.value.get('schema_id') in ('checkin1_response', 'checkin2_response', 'checkin3_response')]
    if len(pending) != 1:
        raise GraphError(f'expected one pending CHECK-IN, found {len(pending)}')
    value = {'decision': decision}
    if note:
        value['note'] = note
    if record is not None:
        path = Path(rundir) / record
        value['record'] = {'path': str(record), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    return run(rundir, attempt=attempt, responses={pending[0].id: value}, gate_check=gate_check,
               gate_providers=gate_providers)


def main(argv=None):
    """``ravel drive [respond]``: run the lifecycle graph; it stops at every human CHECK-IN."""
    import argparse
    arguments = list(sys.argv[1:] if argv is None else argv)
    answering = arguments[:1] == ['respond']
    parser = argparse.ArgumentParser(prog='ravel drive' + (' respond' if answering else ''),
                                     description=__doc__.split('\n\n')[0])
    parser.add_argument('--rundir', type=Path, required=True)
    parser.add_argument('--attempt', type=int, default=1)
    if answering:
        parser.add_argument('--decision', choices=['approve', 'revise', 'stop'], required=True)
        parser.add_argument('--record', help='run-relative approval record the decision rests on')
        parser.add_argument('--note')
    else:
        parser.add_argument('--transport', help='worker transport preference, e.g. ravel-loop')
        parser.add_argument('--respond', type=Path, help='JSON map of pending interrupt id to response value')
        parser.add_argument('--clear-stop', action='store_true')
    args = parser.parse_args(arguments[1:] if answering else arguments)
    try:
        if answering:
            value = respond(args.rundir, decision=args.decision, record=args.record, attempt=args.attempt, note=args.note)
        else:
            responses = read_json(args.respond) if args.respond else None
            value = run(args.rundir, attempt=args.attempt, transport=args.transport, responses=responses,
                        clear_stop=args.clear_stop)
        print(json.dumps(value, indent=2, sort_keys=True, default=str))
        return 0
    except (ValueError, OSError, KeyError, TypeError, GraphError) as exc:
        print('drive: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
