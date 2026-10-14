# census-module: ravel.workflow.graph_nodes
"""Control flow planted inside graph_nodes at qualnames no sanction names."""
from langgraph.types import Command, Send


def rogue_body(state):
    return Command(goto="elsewhere")


def rogue_router(state):
    return [Send("worker", {"item": item}) for item in state["items"]]
