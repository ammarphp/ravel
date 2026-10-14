"""The LangGraph process environment, set before any LangGraph import (CAP §2.6, §2.14; R4).

LangGraph reads ``LANGGRAPH_STRICT_MSGPACK`` once, when its serializer modules are
imported. Every kernel module (``graph_substrate``, ``effect_ledger``, ``graph_nodes``,
``graph_registry``, ``langgraph_runtime``) imports this module first, so importing any
of them in a plain process turns strict msgpack on and tracing off before the first
``langgraph`` import. ``graph_substrate.environment()`` still refuses a process in
which LangGraph was imported earlier by something else.
"""
import os

VARIABLES = {"LANGGRAPH_STRICT_MSGPACK": "true", "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"}


def apply():
    os.environ.update(VARIABLES)


apply()
