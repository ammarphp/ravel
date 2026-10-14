"""Classify → hold or governed advisory worker → pinned consult record."""
from .. import broker, consults, graph_nodes as nodes


class State(nodes.BaseState, total=False):
    request: dict
    consult_spec: dict
    consult_receipt: dict


def build(ctx):
    from langgraph.graph import END, START, StateGraph
    builder = StateGraph(State)
    run = ctx.scope_root
    pin = ctx.instance['request']
    add = lambda name, node: nodes.add(builder, name, node, graph_id=ctx.graph_id)

    def classify(state):
        request = consults.load_request(run, pin)
        return {'request': request, 'results': {'failure': request['failure']}}

    add('classify', nodes.Node('effect', classify))
    nodes.connect(builder, 'classify', nodes.route(
        lambda s: 'consult' if s['request']['failure']['agent_required'] else 'hold',
        {'consult': 'context', 'hold': 'no_agent'}))
    add('no_agent', nodes.hold('failure_requires_owner_action_or_diagnostics',
                              'follow the classified recovery route; this route creates no consult worker'))
    add('context', nodes.effect('consult.context', kind='journal',
        segment=lambda s: {'consult': 'context', 'node': s['request']['producer_node_id'],
                           'trigger': s['request']['trigger_sha256']},
        identity=lambda s: {'request': pin},
        run=lambda s, identity: consults.worker_spec(run, pin),
        to_state=lambda s, result: {'consult_spec': result}))
    # Declare each specialist at build time so G8 sees the actual registered
    # role. Only the deterministic classifier selects the route; no model handoff
    # can select an unregistered role or change the worker's pinned card.
    paths = {}
    for role in sorted({row['role'] for row in consults.bindings()['consults'].values()}):
        name = role.replace('-', '_')
        paths[role] = name
        def selected_spec(role):
            def spec(state):
                value = state['consult_spec']
                if value['role']['id'] != role:
                    raise ValueError('consult route differs from pinned worker role')
                return value
            return spec
        agent = nodes.agent('consult.worker', rundir=run, spec=selected_spec(role),
            segment=lambda s: {'consult': s['request']['failure']['consult_role'],
                               'node': s['request']['producer_node_id'], 'trigger': s['request']['trigger_sha256']},
            to_state=lambda s, result: {'consult_receipt': result})
        # Preserve the factory's governed ledger effect and expose agent metadata.
        agent.kind, agent.role = 'agent', role
        add(name, agent)
        builder.add_edge(name, 'record')
    nodes.connect(builder, 'context', nodes.route(lambda s: s['consult_spec']['role']['id'], paths))
    add('record', nodes.effect('consult.record', kind='journal',
        segment=lambda s: {'consult': 'record', 'node': s['request']['producer_node_id'],
                           'trigger': s['request']['trigger_sha256']},
        identity=lambda s: {'request': pin, 'receipt_sha256': broker.digest(s['consult_receipt'])},
        run=lambda s, identity: consults.record(run, pin, s['consult_receipt']),
        to_state=lambda s, result: {'results': {'consult_record': result}}))
    add('decision_turn', nodes.decision_turn('consult'))
    add('reconcile', nodes.reconcile_node())
    add('hold', nodes.hold('consult_hold'))
    builder.add_edge(START, 'classify')
    builder.add_edge('record', END)
    return builder
