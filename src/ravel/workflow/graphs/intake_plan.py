"""Named intake graph wrapper over the existing charged designer/preparation.

The existing node runner owns budgets, source checks, origin receipts and Host
calls. The exact planner specification authenticating the choice is preserved.
"""
from typing import Annotated

from .. import agent_graph, graph_nodes as nodes, graph_registry, graph_substrate


def is_planner(spec):
    population = spec.get('nodes', [])
    return (len(population) == 2 and population[0].get('id') == 'choose'
            and population[0].get('kind') == 'model' and population[0].get('role') == 'designer'
            and population[1].get('id') == 'prepare' and population[1].get('action') == 'intake-plan'
            and population[1].get('depends_on') == ['choose'])


def _builder(spec, host, ctx):
    from langgraph.graph import END, START, StateGraph
    canonical = agent_graph.validate(spec)
    if not is_planner(canonical):
        raise ValueError('exact bounded intake planner graph required')

    class State(nodes.BaseState, total=False):
        completed: Annotated[dict, nodes.write_once]

    builder = StateGraph(State)
    def body(node_id):
        def execute(state):
            if ctx.node_runner is None:
                raise nodes.RecoveryHold('intake_runner_unavailable', 'use the ordinary intake Graph entry with its charged node runner')
            result = ctx.node_runner(node_id, host)
            return {'completed': {node_id: result}} if result is not None else {}
        return execute
    # Keep legacy checkpoint task labels; the canonical node IDs and receipts
    # are unchanged. The named subsystem supplies current G8 role metadata.
    nodes.add(builder, 'node_0', nodes.Node('agent', body('choose'), role='designer'), graph_id='intake.plan')
    nodes.add(builder, 'node_1', nodes.Node('effect', body('prepare'), role='executor'), graph_id='intake.plan')
    nodes.add(builder, 'decision_turn', nodes.decision_turn('intake'), graph_id='intake.plan')
    nodes.add(builder, 'reconcile', nodes.reconcile_node(), graph_id='intake.plan')
    nodes.add(builder, 'hold', nodes.hold('intake_hold'), graph_id='intake.plan')
    builder.add_edge(START, 'node_0')
    builder.add_edge('node_0', 'node_1')
    builder.add_edge('node_1', END)
    return builder


def compile_spec(spec, host, ctx):
    return graph_substrate.finish(_builder(spec, host, ctx), 'intake.plan',
                                  checkpointer=getattr(ctx, 'checkpointer', None),
                                  expected_structure=graph_registry.get('intake.plan')['structure_sha256'])


def compile_if_planner(spec, host, ctx):
    if is_planner(spec):
        return compile_spec(spec, host, ctx)
    return graph_substrate.compile_spec(spec, host, ctx)


def build(ctx):
    spec, _ = agent_graph._load(ctx.instance['graph_root'])
    return _builder(spec, ctx.extras.get('host'), ctx)
