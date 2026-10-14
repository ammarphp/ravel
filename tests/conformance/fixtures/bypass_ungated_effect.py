# census-module: ravel.workflow.synthetic_graph
"""Effects that reach a consequential sink, with and without naming the mapped gate."""
from ravel.workflow import graph_nodes
from ravel.workflow.launch_authorization import authorized_popen


def _ungated_launch(state, identity):
    return authorized_popen(state["root"], state["plan"], ["/bin/true"], context="synthetic")


def _gated_launch(state, identity):
    return authorized_popen(state["root"], state["plan"], ["/bin/true"], context="synthetic")


def nodes():
    ungated = graph_nodes.effect("ungated", kind="external", run=_ungated_launch, segment=str,
                                 identity=dict, to_state=dict)
    gated = graph_nodes.effect("gated", kind="external", run=_gated_launch, segment=str,
                               identity=dict, to_state=dict, gate="launch")
    return ungated, gated
