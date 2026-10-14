# census-module: ravel.workflow.synthetic_caller
"""A role dispatch outside any substrate node factory."""
from ravel.workflow import agent_graph


def run_directly(root, host):
    return agent_graph.execute(root, host)
