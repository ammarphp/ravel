"""``production.node``: one plan node through its production executor.

```
order (sealed work order) ─► worker: dispatch(role worker) ─► adopt ─┐
                         └─► host:   waiver (R2 receipt when delegated) ┤
                                    ┌───────────────────────────────────┘
                                    ├─ stage declared ─► gate(launch) ─► launch (supervisor + lease) ─► complete
                                    └─ no stage ─────────────────────────────────────────────────────► complete
```

``production_executor`` owns the order, receipt and waiver rules; this graph only
executes them. The ``launch`` gate's action names the node and its rung, so the
executor provider refuses a full or scan launch without the worker's receipt or a
counting waiver. Completion writes ``production/nodes/<node>.json``: a record of who
produced the node, never a scientific acceptance.
"""
from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from .. import graph_nodes as nodes
from .. import production_executor as executor

GRAPH_ID = 'production.node'


class View(TypedDict):
    meta: dict
    node: dict


class State(nodes.BaseState, total=False):
    node: dict
    order: dict
    produced: dict
    stage: dict


def _root(state):
    return Path(state['meta']['scope_root'])


def _node_id(state):
    return (state.get('node') or {}).get('node_id') or state['meta']['instance']['node_id']


def _attempt(state):
    return int((state.get('node') or {}).get('attempt') or state['meta']['instance'].get('attempt') or 1)


def _refused(code, error):
    """A refusal before anything was written: a typed hold, never an ambiguous effect."""
    return nodes.RecoveryHold(code, str(error)[:1500])


def _order(state, identity):
    try:
        order = executor.load_order(_root(state), _node_id(state))
    except ValueError as exc:
        raise _refused('production_order_invalid', exc) from exc
    waived = executor.waiver_path(_root(state), _node_id(state)).exists()
    return {'node_id': order['node_id'], 'role': order['role'], 'rung': order.get('rung'),
            'order_sha256': order['order_sha256'], 'stage': order.get('stage'),
            'executor': 'host' if order.get('executor') == 'host' or waived else 'worker'}


def _adopt(state, identity):
    root, node_id, attempt = _root(state), _node_id(state), _attempt(state)
    receipt = executor.worker_receipt(root, node_id)
    if receipt is None:
        raise _refused('production_receipt_missing', f'node {node_id} has no ok worker receipt to adopt')
    try:
        # Adoption verifies the pin, the obligations and every destination before it copies a byte.
        adoption = executor.adopt(root, node_id, receipt['attempt'])
    except ValueError as exc:
        raise _refused('production_adoption_refused', exc) from exc
    return {'executor': 'worker', 'receipt': {'node_id': node_id, 'attempt': receipt['attempt'],
                                              'role': receipt['role']['id'], 'status': receipt['status']},
            'adoption': {'copied': [{'to': row['to'], 'sha256': row['sha256']} for row in adoption['copied']]},
            'attempt': attempt}


def _waiver(state, identity):
    root, node_id = _root(state), _node_id(state)
    errors = executor.waiver_errors(root, node_id)
    if errors:
        raise nodes.RecoveryHold(errors[0].code, errors[0].message + '; ' + errors[0].fix)
    pin = executor._pin(root, f'{executor.WAIVERS}/{node_id}.json')
    return {'executor': 'host', 'waiver': pin}


def _stage_spec(state):
    return state['order'].get('stage') or {}


def _launch_action(state):
    spec = _stage_spec(state)
    return executor.launch_action(_node_id(state), stage=spec['name'], cmd=spec['argv'], rung=state['order']['rung'],
                                  inputs=spec.get('inputs', ()), outputs=spec.get('outputs', ()))


def _launch(state, identity):
    """The gated launch effect: executor re-check, the supervisor (machine lease), then registration."""
    from .. import stage_supervisor
    root, spec, action = _root(state), _stage_spec(state), _launch_action(state)
    errors = executor.launch_errors(root, action, gate_check=None)
    if errors:
        raise _refused('production_launch_refused', executor.ExecutorRefused(errors))
    options = {k: spec[k] for k in ('kill_secs', 'lease_wait', 'cwd') if k in spec}
    code = stage_supervisor.supervise(spec['name'], root, spec.get('events', 1), spec.get('log') or f'logs/{spec["name"]}.log',
                                      list(spec['argv']), inputs=list(spec.get('inputs', ())),
                                      outputs=list(spec.get('outputs', ())), required_plan=state['order']['rung'],
                                      node_id=_node_id(state), **options)
    if code != 0:
        raise ValueError(f'stage {spec["name"]} exited {code}')
    return {'node_id': _node_id(state), 'stage': spec['name'], 'exit_code': code, 'action_digest': action['digest'],
            'registered': executor.register_stage(root, spec['name'])}


def _complete(state, identity):
    produced = state.get('produced') or {}
    stage = state.get('stage') or {}
    registered = stage.get('registered')
    return executor.complete(_root(state), _node_id(state), executor=produced.get('executor', 'worker'),
                             receipt=produced.get('receipt'), waiver=produced.get('waiver'),
                             adoption=produced.get('adoption'),
                             stage=registered and {'receipt_id': registered['receipt_id'],
                                                   'module_origin': registered['module_origin']})


def build(ctx):
    from langgraph.graph import END, START, StateGraph
    builder = StateGraph(State, input_schema=View)
    add = lambda name, node: nodes.add(builder, name, node, graph_id=GRAPH_ID)
    run = ctx.scope_root
    add('decision_turn', nodes.decision_turn(GRAPH_ID))
    add('reconcile', nodes.reconcile_node())
    add('hold', nodes.hold('production_node_hold'))
    add('order', nodes.effect('production.order', kind='journal', run=_order,
                              segment=lambda s: {'order': _node_id(s)},
                              identity=lambda s: {'node_id': _node_id(s), 'attempt': _attempt(s)},
                              to_state=lambda s, r: {'order': r}))
    agent = nodes.agent('production.worker', rundir=run,
                        spec=lambda s: executor.worker_spec(Path(run), _node_id(s), _attempt(s)),
                        segment=lambda s: {'worker': _node_id(s), 'attempt': _attempt(s)},
                        to_state=lambda s, receipt: {'results': {'worker': {
                            'status': receipt['status'], 'node_id': receipt['node_id'], 'attempt': receipt['attempt']}}})
    agent.kind = 'agent'
    add('dispatch', agent)
    add('adopt', nodes.effect('production.adopt', kind='journal', run=_adopt,
                              segment=lambda s: {'adopt': _node_id(s)},
                              identity=lambda s: {'node_id': _node_id(s), 'order_sha256': s['order']['order_sha256']},
                              to_state=lambda s, r: {'produced': r}))
    add('waiver', nodes.effect('production.waiver', kind='journal', run=_waiver,
                               segment=lambda s: {'waiver': _node_id(s)},
                               identity=lambda s: {'node_id': _node_id(s), 'order_sha256': s['order']['order_sha256']},
                               to_state=lambda s, r: {'produced': r}))
    add('gate_launch', nodes.gate('launch', _launch_action))
    add('launch', nodes.effect('production.launch', kind='compute', run=_launch, gate='launch',
                               implementation=('ravel.workflow.production_executor',),
                               segment=lambda s: {'launch': _node_id(s)},
                               identity=lambda s: {'node_id': _node_id(s),
                                                   'action_bytes_sha256': _launch_action(s)['digest']},
                               to_state=lambda s, r: {'stage': r}))
    add('complete', nodes.effect('production.complete', kind='journal', run=_complete,
                                 segment=lambda s: {'complete': _node_id(s)},
                                 identity=lambda s: {'node_id': _node_id(s), 'order_sha256': s['order']['order_sha256']},
                                 to_state=lambda s, r: {'results': {'node': {
                                     'node_id': r['node_id'], 'executor': r['executor'], 'complete': True}}}))
    add('refused', nodes.hold('production_launch_refused', 'clear the launch gate errors recorded in gates: a '
                              'worker receipt for the node or a counting host waiver, then a new attempt'))
    builder.add_edge(START, 'order')
    nodes.connect(builder, 'order', nodes.route(lambda s: s['order']['executor'], {'worker': 'dispatch', 'host': 'waiver'}))
    builder.add_edge('dispatch', 'adopt')
    staged = nodes.route(lambda s: 'stage' if _stage_spec(s) else 'complete', {'stage': 'gate_launch', 'complete': 'complete'})
    nodes.connect(builder, 'adopt', staged)
    nodes.connect(builder, 'waiver', nodes.route(lambda s: 'stage' if _stage_spec(s) else 'complete',
                                                {'stage': 'gate_launch', 'complete': 'complete'}))
    nodes.connect(builder, 'gate_launch', nodes.gate_route('launch', passed='launch', refused='refused'))
    builder.add_edge('launch', 'complete')
    builder.add_edge('complete', END)
    return builder


def instance(node_id, attempt=1):
    if type(node_id) is not str or not node_id or type(attempt) is not int or attempt < 1:
        raise ValueError('production instance requires a plan node id and a positive attempt')
    return {'node_id': node_id, 'attempt': attempt}


def run(rundir, node_id, *, attempt=1, gate_check=None, gate_providers=None, clear_stop=False, max_steps=None):
    """Run one node's production executor standalone (the lifecycle runs it as a subgraph)."""
    from .. import graph_substrate
    return graph_substrate.run(rundir, GRAPH_ID, instance(node_id, attempt), input={'node': instance(node_id, attempt)},
                               gate_check=gate_check, gate_providers=gate_providers, clear_stop=clear_stop,
                               max_steps=max_steps)
