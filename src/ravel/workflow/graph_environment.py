"""The LangGraph process environment, set before any LangGraph import (CAP §2.6, §2.14; R4).

LangGraph reads ``LANGGRAPH_STRICT_MSGPACK`` once, when its serializer modules are
imported. Every kernel module (``graph_substrate``, ``effect_ledger``, ``graph_nodes``,
``graph_registry``, ``langgraph_runtime``) imports this module first, so importing any
of them in a plain process turns strict msgpack on and tracing off before the first
``langgraph`` import. ``graph_substrate.environment()`` still refuses a process in
which LangGraph was imported earlier by something else.

``open_checkpoint_connection`` is the one way the kernel opens a checkpoint file. SQLite's busy
timeout does not cover the first journal-mode switch of a fresh file, so two processes that open
the same new file at once can fail with "database is locked" before either runs a node; the open
retries that switch, and the creation of the tables, within a bounded time.
"""
import os
import random
import sqlite3
import time

VARIABLES = {"LANGGRAPH_STRICT_MSGPACK": "true", "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"}


def apply():
    os.environ.update(VARIABLES)


apply()


def _retry_locked(action, deadline):
    while True:
        try:
            return action()
        except sqlite3.OperationalError as error:
            text = str(error).lower()
            if ("locked" not in text and "busy" not in text) or time.monotonic() >= deadline:
                raise
            time.sleep(random.uniform(0.02, 0.1))


def open_checkpoint_connection(path, *, timeout=30.0):
    """A connection to a checkpoint file in WAL mode with its tables created, safe to open from several processes at once.

    The caller wraps it in a ``SqliteSaver`` and closes it. A lock held by another process during the
    first-time switch or table creation is retried until ``timeout`` seconds have passed, then raised.
    """
    from langgraph.checkpoint.sqlite import SqliteSaver
    connection = sqlite3.connect(str(path), check_same_thread=False, timeout=timeout)
    deadline = time.monotonic() + timeout
    try:
        _retry_locked(lambda: connection.execute("PRAGMA journal_mode=WAL").fetchone(), deadline)
        _retry_locked(SqliteSaver(connection).setup, deadline)
    except BaseException:
        connection.close()
        raise
    return connection
