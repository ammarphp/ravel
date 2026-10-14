# census-module: ravel.workflow.graph_substrate
"""An unregistered StateGraph planted inside the sanctioned substrate module."""
from langgraph.graph import StateGraph as Graph


def rogue_graph(state_type):
    builder = Graph(state_type)
    return builder.compile()
