"""LangGraph semantics the substrate depends on, pinned as regression probes.

P1-P12 are the capability probes (capabilities.md Appendix A), Q1-Q5 and R1-R13 the
substrate probes (LANGGRAPH-SUBSTRATE Appendix A; R1-R13 back the pair-review changes of
its Appendix D), and S1-S2 two behaviours found while building the kernel. Each asserts what the pinned version does today; a failure after an upgrade
means a substrate assumption must be re-checked, not that the test should be edited.
Crashes are real process deaths (``os._exit``) in a child. No network.
"""
from importlib import metadata
import json
import operator
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import textwrap
import warnings
from typing import Annotated, TypedDict

import pytest

PINS = {"langgraph": "1.2.14", "langgraph-checkpoint": "4.2.0", "langgraph-checkpoint-sqlite": "3.1.1",
        "langchain-core": "1.6.7"}


def test_pinned_versions():
    assert {name: metadata.version(name) for name in PINS} == PINS


def _saver(path):
    from langgraph.checkpoint.sqlite import SqliteSaver
    return SqliteSaver(sqlite3.connect(str(path), check_same_thread=False))


def _child(code, *args, crash=None, timeout=120):
    env = {**os.environ, "LANGSMITH_TRACING": "false", "PROBE_CRASH": crash or ""}
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code), *map(str, args)], env=env,
                          capture_output=True, text=True, timeout=timeout)


def _count(path):
    return len(Path(path).read_text()) if Path(path).exists() else 0


class Log(TypedDict, total=False):
    log: Annotated[list, operator.add]
    n: int


# ---- P1: interrupts ---------------------------------------------------------------------------

def test_p1_node_reruns_from_top_ids_per_task_scalar_refused_id_map_resumes(tmp_path):
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command, Send, interrupt
    entries = []
    def two(state):
        entries.append(1)
        first = interrupt("first")
        second = interrupt("second")
        return {"log": [f"{first}-{second}"]}
    def branch(state):
        return {"log": [interrupt({"branch": state["n"]})]}
    builder = StateGraph(Log)
    builder.add_node("two", two)
    builder.add_node("branch", branch)
    builder.add_edge(START, "two")
    builder.add_conditional_edges("two", lambda s: [Send("branch", {"n": i}) for i in (1, 2)], ["branch"])
    builder.add_edge("branch", END)
    config = {"configurable": {"thread_id": "p1"}}
    app = builder.compile(checkpointer=_saver(tmp_path / "p1.sqlite"))
    app.invoke({"log": []}, config)
    app = builder.compile(checkpointer=_saver(tmp_path / "p1.sqlite"))  # a fresh process's view
    app.invoke(Command(resume="a"), config)
    app.invoke(Command(resume="b"), config)
    assert len(entries) == 3  # re-ran from the top on each resume
    pending = app.get_state(config).interrupts
    assert len(pending) == 2 and len({p.id for p in pending}) == 2
    with pytest.raises(Exception):
        app.invoke(Command(resume="scalar"), config)
    app.invoke(Command(resume={p.id: f"r{p.value['branch']}" for p in pending}), config)
    assert sorted(app.get_state(config).values["log"]) == ["a-b", "r1", "r2"]


# ---- P2: Send crash, pending writes, durability --------------------------------------------

P2 = """
import os, sys, sqlite3, time, operator
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from langgraph.checkpoint.sqlite import SqliteSaver
class S(TypedDict, total=False):
    log: Annotated[list, operator.add]
db, counts, durability = sys.argv[1], sys.argv[2], sys.argv[3]
def worker(state):
    with open(os.path.join(counts, state['i']), 'a') as f: f.write('x')
    if os.environ['PROBE_CRASH'] == state['i']:
        time.sleep(1.5); os._exit(9)
    return {'log': [state['i']]}
b = StateGraph(S); b.add_node('w', worker)
b.add_conditional_edges(START, lambda s: [Send('w', {'i': i}) for i in 'abcd'], ['w']); b.add_edge('w', END)
app = b.compile(checkpointer=SqliteSaver(sqlite3.connect(db, check_same_thread=False)))
cfg = {'configurable': {'thread_id': 't'}, 'max_concurrency': 4}
first = not app.get_state(cfg).created_at
try:
    out = app.invoke({'log': []} if first else None, cfg, durability=durability)
    print(sorted(out['log']))
except Exception as e:
    print(type(e).__name__)
"""


def test_p2_send_crash_reruns_only_the_crashed_worker(tmp_path):
    counts = tmp_path / "counts"
    counts.mkdir()
    assert _child(P2, tmp_path / "p2.sqlite", counts, "sync", crash="c").returncode == 9
    done = _child(P2, tmp_path / "p2.sqlite", counts, "sync")
    assert done.stdout.strip() == "['a', 'b', 'c', 'd']"
    assert {i: _count(counts / i) for i in "abcd"} == {"a": 1, "b": 1, "c": 2, "d": 1}


def test_p2_exit_durability_loses_everything_on_crash(tmp_path):
    counts = tmp_path / "counts"
    counts.mkdir()
    assert _child(P2, tmp_path / "p2.sqlite", counts, "exit", crash="c").returncode == 9
    from langgraph.graph import StateGraph
    assert not _saver(tmp_path / "p2.sqlite").get({"configurable": {"thread_id": "t"}})


# ---- P3: subgraph crash and namespaces -------------------------------------------------------

P3 = """
import os, sys, sqlite3, operator
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
class S(TypedDict, total=False):
    log: Annotated[list, operator.add]
counts = sys.argv[2]
def mark(name):
    def f(state):
        with open(os.path.join(counts, name), 'a') as fh: fh.write('x')
        if os.environ['PROBE_CRASH'] == name: os._exit(9)
        return {'log': [name]}
    return f
c = StateGraph(S); c.add_node('c1', mark('c1')); c.add_node('c2', mark('c2'))
c.add_edge(START, 'c1'); c.add_edge('c1', 'c2'); c.add_edge('c2', END)
p = StateGraph(S); p.add_node('pre', mark('pre')); p.add_node('sub', c.compile())
p.add_edge(START, 'pre'); p.add_edge('pre', 'sub'); p.add_edge('sub', END)
app = p.compile(checkpointer=SqliteSaver(sqlite3.connect(sys.argv[1], check_same_thread=False)))
cfg = {'configurable': {'thread_id': 't'}}
first = not app.get_state(cfg).created_at
if first:
    app.invoke({'log': []}, cfg, durability='sync')
else:
    out = app.invoke(None, cfg, durability='sync')
    print(out['log'])
"""


def test_p3_child_resumes_at_crashed_node_and_shared_add_key_duplicates(tmp_path):
    counts = tmp_path / "counts"
    counts.mkdir()
    assert _child(P3, tmp_path / "p3.sqlite", counts, crash="c2").returncode == 9
    from langgraph.checkpoint.sqlite import SqliteSaver
    saved = list(_saver(tmp_path / "p3.sqlite").list({"configurable": {"thread_id": "t"}}))
    assert any(c.config["configurable"]["checkpoint_ns"].startswith("sub:") for c in saved)
    done = _child(P3, tmp_path / "p3.sqlite", counts)
    assert {n: _count(counts / n) for n in ("pre", "c1", "c2")} == {"pre": 1, "c1": 1, "c2": 2}
    log = eval(done.stdout.strip())
    assert log.count("pre") == 2  # the shared operator.add key duplicates the parent's entries


# ---- P4: functional API -------------------------------------------------------------------------

P4 = """
import os, sys, sqlite3, time
from langgraph.func import entrypoint, task
from langgraph.checkpoint.sqlite import SqliteSaver
counts = sys.argv[2]
def earlier_result_is_saved():
    # A finished task's result is saved by a background thread. The crash waits for that row:
    # a crash before the commit reruns the earlier task too, which is a different question.
    probe = sqlite3.connect(sys.argv[1]); deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if probe.execute("select count(*) from writes where channel = '__return__'").fetchone()[0]: return
        except sqlite3.OperationalError: pass
        time.sleep(0.01)
@task
def step(name):
    with open(os.path.join(counts, name), 'a') as fh: fh.write('x')
    if os.environ['PROBE_CRASH'] == name:
        earlier_result_is_saved()
        os._exit(9)
    return name
saver = SqliteSaver(sqlite3.connect(sys.argv[1], check_same_thread=False))
@entrypoint(checkpointer=saver)
def flow(value, *, previous=None):
    a = step('a').result(); b = step('b').result()
    return entrypoint.final(value={'out': [a, b], 'previous': previous}, save={'saved': value})
cfg = {'configurable': {'thread_id': 't'}}
if os.environ['PROBE_CRASH']:
    flow.invoke(1, cfg)
else:
    print(flow.invoke(None, cfg))
    print(sorted((n, len(open(os.path.join(counts, n)).read())) for n in 'ab'))
    print(flow.invoke(2, cfg)['previous'])
"""


def test_p4_functional_api_reruns_only_the_crashed_task(tmp_path):
    counts = tmp_path / "counts"
    counts.mkdir()
    assert _child(P4, tmp_path / "p4.sqlite", counts, crash="b").returncode == 9
    done = _child(P4, tmp_path / "p4.sqlite", counts)
    assert done.returncode == 0, done.stderr[-2000:]
    lines = done.stdout.strip().splitlines()
    assert lines[0] == "{'out': ['a', 'b'], 'previous': None}" and lines[1] == "[('a', 1), ('b', 2)]"
    assert lines[2] == "{'saved': 1}"  # previous equals the save= value of the last run


# ---- P5: retry, handler, recursion, drain, cache, timeout, fork --------------------------------

def test_p5_retry_handler_recursion_drain_cache_timeout_fork(tmp_path):
    from langgraph.cache.memory import InMemoryCache
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.errors import GraphDrained, GraphRecursionError, NodeError
    from langgraph.graph import END, START, StateGraph
    from langgraph.runtime import RunControl
    from langgraph.types import CachePolicy, Command, RetryPolicy

    attempts = []
    def flaky(state):
        attempts.append(1)
        raise ValueError("not transient")
    def handle(state, error: NodeError):
        return Command(goto=END, update={"log": [f"handled:{type(error.error).__name__}"]})
    builder = StateGraph(Log)
    builder.add_node("flaky", flaky, retry_policy=RetryPolicy(max_attempts=3, initial_interval=0.0), error_handler=handle)
    builder.add_edge(START, "flaky")
    out = builder.compile().invoke({"log": []})
    assert attempts == [1] and out["log"] == ["handled:ValueError"]  # default retry_on skips ValueError

    loop = StateGraph(Log)
    loop.add_node("a", lambda s: {"n": s.get("n", 0) + 1})
    loop.add_edge(START, "a")
    loop.add_edge("a", "a")
    with pytest.raises(GraphRecursionError):
        loop.compile().invoke({"n": 0}, {"recursion_limit": 4})

    control = RunControl()
    chain = StateGraph(Log)
    chain.add_node("a", lambda s: control.request_drain("test") or {"log": ["a"]})
    chain.add_node("b", lambda s: {"log": ["b"]})
    chain.add_edge(START, "a")
    chain.add_edge("a", "b")
    app = chain.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "drain"}}
    with pytest.raises(GraphDrained):
        app.invoke({"log": []}, config, control=control)
    assert app.get_state(config).next == ("b",)
    assert app.invoke(None, config)["log"] == ["a", "b"]

    runs = []
    cached = StateGraph(Log)
    cached.add_node("c", lambda s: runs.append(1) or {"n": s["n"] * 2}, cache_policy=CachePolicy())
    cached.add_edge(START, "c")
    app = cached.compile(cache=InMemoryCache())
    for value in (1, 1, 2, 2):
        app.invoke({"n": value})
    assert len(runs) == 2

    with pytest.raises(Exception):
        timed = StateGraph(Log)
        timed.add_node("t", lambda s: {}, timeout=0.5)
        timed.add_edge(START, "t")
        timed.compile().invoke({})

    hist = StateGraph(Log)
    hist.add_node("x", lambda s: {"log": ["x"]})
    hist.add_node("y", lambda s: {"log": ["y"]})
    hist.add_edge(START, "x")
    hist.add_edge("x", "y")
    app = hist.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "fork"}}
    app.invoke({"log": []}, config)
    after_x = next(s for s in app.get_state_history(config) if s.next == ("y",))
    forked = app.update_state(after_x.config, {"log": ["forked"]})
    assert app.invoke(None, forked)["log"] == ["x", "forked", "y"]


def test_p5_async_timeout_raises_node_timeout_error():
    import asyncio
    from langgraph.errors import NodeTimeoutError
    from langgraph.graph import START, StateGraph
    async def slow(state):
        await asyncio.sleep(2)
        return {}
    graph = StateGraph(Log)
    graph.add_node("slow", slow, timeout=0.1)
    graph.add_edge(START, "slow")
    with pytest.raises(NodeTimeoutError):
        asyncio.run(graph.compile().ainvoke({}))


# ---- P6: replay, transient retry, stray resume ----------------------------------------------

def test_p6_replay_retry_and_stray_resume():
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import START, StateGraph
    from langgraph.types import Command, RetryPolicy
    executed = []
    builder = StateGraph(Log)
    builder.add_node("x", lambda s: executed.append("x") or {"log": ["x"]})
    builder.add_node("y", lambda s: executed.append("y") or {"log": ["y"]})
    builder.add_edge(START, "x")
    builder.add_edge("x", "y")
    app = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "p6"}}
    app.invoke({"log": []}, config)
    past = next(s for s in app.get_state_history(config) if s.next == ("y",))
    app.invoke(None, past.config)
    assert executed == ["x", "y", "y"]
    before = app.get_state(config).values
    app.invoke(Command(resume="stray"), config)
    assert app.get_state(config).values == before

    tries = []
    def transient(state):
        tries.append(1)
        if len(tries) < 3:
            raise ConnectionError("refused before any byte was sent")
        return {"log": ["ok"]}
    retry = StateGraph(Log)
    retry.add_node("t", transient, retry_policy=RetryPolicy(max_attempts=3, initial_interval=0.0, jitter=False,
                                                            retry_on=ConnectionError))
    retry.add_edge(START, "t")
    assert retry.compile().invoke({"log": []})["log"] == ["ok"] and len(tries) == 3


# ---- P7: Store with a local embedding --------------------------------------------------------

def test_p7_stores_search_offline_with_local_embedding(tmp_path):
    from langgraph.store.memory import InMemoryStore
    from langgraph.store.sqlite import SqliteStore
    vocabulary = ["jets", "leptons", "photons"]
    def embed(texts):
        return [[float(t.count(w)) + 0.01 for w in vocabulary] for t in texts]
    index = {"dims": 3, "embed": embed, "fields": ["text"]}
    connection = sqlite3.connect(str(tmp_path / "store.sqlite"), check_same_thread=False, isolation_level=None)
    sqlite_store = SqliteStore(connection, index=index)
    sqlite_store.setup()
    for store in (InMemoryStore(index=index), sqlite_store):
        store.put(("idx", "a"), "1", {"text": "jets jets jets", "tag": "x"})
        store.put(("idx", "a"), "2", {"text": "leptons", "tag": "y"})
        store.put(("idx", "b"), "3", {"text": "photons", "tag": "x"})
        assert store.search(("idx", "a"), query="jets")[0].key == "1"
        assert [i.key for i in store.search(("idx",), filter={"tag": "x"})] in (["1", "3"], ["3", "1"])
        assert {i.key for i in store.search(("idx", "b"))} == {"3"}


# ---- shared fake chat model (P8, P11, P12, Q1) -----------------------------------------------

def _fake_model(script):
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.outputs import ChatGeneration, ChatResult

    class Scripted(BaseChatModel):
        turns: list
        bound: dict = {}

        @property
        def _llm_type(self):
            return "scripted"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            message = self.turns.pop(0)
            return ChatResult(generations=[ChatGeneration(message=message)])

        def bind_tools(self, tools, **kwargs):
            self.bound.update(kwargs, tools=[getattr(t, "name", None) or t.__name__ for t in tools])
            return self

    return Scripted(turns=list(script))


def _call(name, args, identifier):
    return {"name": name, "args": args, "id": identifier, "type": "tool_call"}


def test_p8_react_agent_deprecated_offline_parallel_tool_once(monkeypatch):
    import socket
    from langchain_core.messages import AIMessage
    from langchain_core.tools import tool
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.prebuilt import create_react_agent
    from langgraph.types import Command, interrupt
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("network attempted"))
    executed = []

    @tool
    def lookup(q: str) -> str:
        """Look something up."""
        executed.append(q)
        return f"found {q}"

    @tool
    def confirm(q: str) -> str:
        """Ask a human."""
        return str(interrupt({"confirm": q}))

    model = _fake_model([AIMessage("", tool_calls=[_call("lookup", {"q": "a"}, "1"), _call("confirm", {"q": "b"}, "2")]),
                         AIMessage("done")])
    with pytest.warns(Warning):
        agent = create_react_agent(model, [lookup, confirm], checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "p8"}}
    agent.invoke({"messages": [("user", "go")]}, config)
    assert agent.get_state(config).interrupts
    final = agent.invoke(Command(resume="yes"), config)
    assert final["messages"][-1].content == "done" and executed == ["a"]


def test_p11_tool_node_wrapper_denies_before_execution():
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.tools import tool
    from langgraph.prebuilt import ToolNode
    executed = []

    @tool
    def act(x: int) -> int:
        """Act."""
        executed.append(x)
        return x

    def gate(request, execute):
        if request.tool_call["args"]["x"] < 0:
            return ToolMessage("denied", tool_call_id=request.tool_call["id"], status="error")
        return execute(request)

    from langgraph.graph import START, MessagesState, StateGraph
    builder = StateGraph(MessagesState)
    builder.add_node("tools", ToolNode([act], wrap_tool_call=gate))
    builder.add_edge(START, "tools")
    out = builder.compile().invoke({"messages": [AIMessage("", tool_calls=[_call("act", {"x": -1}, "d"),
                                                                          _call("act", {"x": 2}, "a")])]})
    assert executed == [2] and [m.content for m in out["messages"][1:]] == ["denied", "2"]


def test_p12_response_format_validates_with_tool_choice_any():
    from langchain_core.messages import AIMessage
    from pydantic import BaseModel
    from langgraph.prebuilt import create_react_agent

    class Verdict(BaseModel):
        decision: str
        confidence: float

    model = _fake_model([AIMessage("no tools needed"),
                         AIMessage("", tool_calls=[_call("Verdict", {"decision": "refute", "confidence": 0.5}, "v")])])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        agent = create_react_agent(model, [], response_format=Verdict)
    out = agent.invoke({"messages": [("user", "judge")]})
    assert isinstance(out["structured_response"], Verdict) and out["structured_response"].decision == "refute"
    assert model.bound.get("tool_choice") == "any"


# ---- P9: no exclusion between processes ------------------------------------------------------

P9 = """
import os, sys, time
from typing import TypedDict
from ravel.workflow.graph_environment import open_checkpoint_connection
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
class S(TypedDict, total=False):
    n: int
def effect(state):
    with open(sys.argv[2], 'a') as fh: fh.write('x')
    time.sleep(1.0)
    return {'n': 1}
b = StateGraph(S); b.add_node('e', effect); b.add_edge(START, 'e'); b.add_edge('e', END)
conn = open_checkpoint_connection(sys.argv[1])  # both processes open the same FRESH file at once
app = b.compile(checkpointer=SqliteSaver(conn))
app.invoke({'n': 0}, {'configurable': {'thread_id': 'shared'}})
"""


def test_p9_two_processes_on_one_thread_both_execute(tmp_path):
    env = {**os.environ, "LANGSMITH_TRACING": "false"}
    args = [sys.executable, "-c", textwrap.dedent(P9), str(tmp_path / "p9.sqlite"), str(tmp_path / "effect")]
    first, second = subprocess.Popen(args, env=env), subprocess.Popen(args, env=env)
    assert first.wait(timeout=120) == 0 and second.wait(timeout=120) == 0
    assert _count(tmp_path / "effect") == 2


def test_p9_first_open_retries_a_lock_and_gives_up_at_its_deadline(tmp_path):
    import time
    from ravel.workflow import graph_environment as environment
    attempts = []

    def locked_twice():
        attempts.append(1)
        if len(attempts) < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ready"

    assert environment._retry_locked(locked_twice, time.monotonic() + 30) == "ready" and len(attempts) == 3

    def always_locked():
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError, match="locked"):
        environment._retry_locked(always_locked, time.monotonic() + 0.2)

    def other_failure():
        raise sqlite3.OperationalError("no such table: checkpoints")

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        environment._retry_locked(other_failure, time.monotonic() + 30)
    connection = environment.open_checkpoint_connection(tmp_path / "fresh.sqlite")
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert {row[0] for row in connection.execute("select name from sqlite_master where type='table'")} >= {"checkpoints", "writes"}
    finally:
        connection.close()


# ---- P10: v2 streaming -----------------------------------------------------------------------

def test_p10_v2_stream_namespaced_typed_events_and_graph_output():
    from langgraph.config import get_stream_writer
    from langgraph.graph import END, START, StateGraph
    child = StateGraph(Log)
    child.add_node("inner", lambda s: get_stream_writer()({"progress": 1}) or {"log": ["inner"]})
    child.add_edge(START, "inner")
    parent = StateGraph(Log)
    parent.add_node("sub", child.compile())
    parent.add_edge(START, "sub")
    app = parent.compile()
    parts = list(app.stream({"log": []}, {"max_concurrency": 2}, stream_mode=["updates", "custom"],
                            subgraphs=True, version="v2"))
    assert {p["type"] for p in parts} == {"updates", "custom"}
    custom = [p for p in parts if p["type"] == "custom"]
    assert custom[0]["data"] == {"progress": 1} and custom[0]["ns"][0].startswith("sub:")
    result = app.invoke({"log": []}, version="v2")
    assert type(result).__name__ == "GraphOutput" and result.value["log"] == ["inner"]


# ---- Q1/Q2: tool loop over the effect ledger --------------------------------------------------

QLOOP = """
import os, sys, sqlite3
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import Command
from langgraph.errors import NodeError
from langgraph.checkpoint.sqlite import SqliteSaver
import runpy
fake = runpy.run_path(sys.argv[2])
from ravel.workflow import effect_ledger
scope, log = sys.argv[1], os.path.join(sys.argv[1], 'effects.log')
def once(key, fn):
    def wrapped():
        value = fn()
        with open(log, 'a') as fh: fh.write(key + '\\n')
        if os.environ['PROBE_CRASH'] == 'at:' + key: os._exit(9)
        return value
    where = effect_ledger.path('probe.q', {}, None, {'effect': key.replace(':', '-')})
    out = effect_ledger.call(scope, graph={'id': 'probe.q', 'version': 1}, path=where, kind='model',
                             identity={'effect': key}, provisioning={}, function=wrapped)
    if os.environ['PROBE_CRASH'] == 'after:' + key: os._exit(9)
    return out
script = [AIMessage('', tool_calls=[fake['_call']('t', {'x': 'a'}, 't0a'), fake['_call']('t', {'x': 'b'}, 't0b')]),
          AIMessage('', tool_calls=[fake['_call']('t', {'x': 'c'}, 't1a')]), AIMessage('final:done')]
@tool
def t(x: str) -> str:
    '''Synthetic tool.'''
    return x
class S(MessagesState):
    turn: int
def model(state):
    turn = state.get('turn', 0)
    msg = once(f'model:{turn}', lambda: script[turn].model_dump(mode='json'))
    return {'messages': [AIMessage(**{k: v for k, v in msg.items() if k in ('content', 'tool_calls', 'id')})], 'turn': turn + 1}
def gate(request, execute):
    key = 'tool:' + request.tool_call['id']
    content = once(key, lambda: execute(request).content)
    return ToolMessage(content, tool_call_id=request.tool_call['id'])
def handle(state, error: NodeError):
    return Command(goto='reconcile', update={'messages': []})
b = StateGraph(S)
b.add_node('model', model); b.add_node('tools', ToolNode([t], wrap_tool_call=gate), error_handler=handle)
b.add_node('reconcile', lambda s: {'turn': -1})
b.add_edge(START, 'model'); b.add_conditional_edges('model', tools_condition); b.add_edge('tools', 'model')
b.add_edge('reconcile', END)
app = b.compile(checkpointer=SqliteSaver(sqlite3.connect(os.path.join(scope, 'q.sqlite'), check_same_thread=False)))
cfg = {'configurable': {'thread_id': 'q'}}
first = not app.get_state(cfg).created_at
out = app.invoke({'messages': [('user', 'go')], 'turn': 0} if first else None, cfg, durability='sync')
print('TURN', out['turn'], out['messages'][-1].content)
"""


def test_q1_tool_loop_crash_after_receipt_keeps_every_effect_once(tmp_path):
    assert _child(QLOOP, tmp_path, Path(__file__), crash="after:tool:t1a").returncode == 9
    done = _child(QLOOP, tmp_path, Path(__file__))
    assert done.returncode == 0, done.stderr[-3000:]
    assert "final:done" in done.stdout
    log = (tmp_path / "effects.log").read_text().split()
    # t0a and t0b are parallel tool calls of one turn; their order is not fixed.
    assert log[0] == "model:0" and sorted(log[1:3]) == ["tool:t0a", "tool:t0b"]
    assert log[3:] == ["model:1", "tool:t1a", "model:2"]
    from ravel.workflow import effect_ledger
    for receipt in effect_ledger.receipts(tmp_path):
        assert receipt["framework_step"]["thread_id"] == "q" and receipt["framework_step"]["task_id"]


def test_q2_crash_inside_effect_raises_ambiguous_and_routes_to_reconcile(tmp_path):
    assert _child(QLOOP, tmp_path, Path(__file__), crash="at:tool:t1a").returncode == 9
    done = _child(QLOOP, tmp_path, Path(__file__))
    assert done.returncode == 0, done.stderr[-3000:]
    assert "TURN -1" in done.stdout  # handler routed the Ambiguous to reconcile
    assert (tmp_path / "effects.log").read_text().split().count("tool:t1a") == 1


def test_q2_untyped_handler_parameter_is_not_injected():
    from langgraph.graph import START, StateGraph
    def boom(state):
        raise KeyError("x")
    def untyped(state, error):
        return {"log": ["handled"]}
    builder = StateGraph(Log)
    builder.add_node("boom", boom, error_handler=untyped)
    builder.add_edge(START, "boom")
    with pytest.raises(TypeError):
        builder.compile().invoke({"log": []})


# ---- Q3: sealed fan-out, input projection, refusing reducer -----------------------------------

Q3 = """
import os, sys, sqlite3, time
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from langgraph.checkpoint.sqlite import SqliteSaver
def sealed(left, right):
    out = dict(left or {})
    for k, v in (right or {}).items():
        if v.get('kind') not in ('hypothesis',): raise ValueError('undeclared post kind')
        out[k] = v
    return out
class S(TypedDict, total=False):
    sealed: Annotated[dict, sealed]
    seen: Annotated[dict, sealed]
    pid: str
def proposer(state):
    with open(os.path.join(sys.argv[2], state['pid']), 'a') as fh: fh.write('x')
    if os.environ['PROBE_CRASH'] == state['pid']:
        time.sleep(1.5); os._exit(9)
    return {'sealed': {state['pid']: {'kind': 'hypothesis', 'peers_visible': sorted(state.get('sealed', {}))}}}
b = StateGraph(S); b.add_node('p', proposer)
b.add_conditional_edges(START, lambda s: [Send('p', {'pid': p}) for p in ('p1', 'p2', 'p3')], ['p']); b.add_edge('p', END)
app = b.compile(checkpointer=SqliteSaver(sqlite3.connect(sys.argv[1], check_same_thread=False)))
cfg = {'configurable': {'thread_id': 't'}, 'max_concurrency': 3}
first = not app.get_state(cfg).created_at
out = app.invoke({} if first else None, cfg, durability='sync')
print(sorted(out['sealed']), [v['peers_visible'] for v in out['sealed'].values()])
"""


def test_q3_only_crashed_proposer_reruns_without_peer_visibility(tmp_path):
    counts = tmp_path / "counts"
    counts.mkdir()
    assert _child(Q3, tmp_path / "q3.sqlite", counts, crash="p2").returncode == 9
    done = _child(Q3, tmp_path / "q3.sqlite", counts)
    assert done.stdout.strip() == "['p1', 'p2', 'p3'] [[], [], []]"
    assert {p: _count(counts / p) for p in ("p1", "p2", "p3")} == {"p1": 1, "p2": 2, "p3": 1}


def test_q3_input_schema_projection_and_refusing_reducer():
    from pydantic import BaseModel
    from langgraph.graph import START, StateGraph

    def refuse_kind(left, right):
        if any(post.get("kind") != "hypothesis" for post in right):
            raise ValueError("undeclared post kind")
        return left + right

    class Full(TypedDict, total=False):
        projection: str
        private: str
        posts: Annotated[list, refuse_kind]

    class CriticView(TypedDict):
        projection: str

    seen = []
    builder = StateGraph(Full)
    builder.add_node("critic", lambda s: seen.append(sorted(s)) or {}, input_schema=CriticView)
    builder.add_edge(START, "critic")
    builder.compile().invoke({"projection": "p", "private": "secret", "posts": []})
    assert seen == [["projection"]]
    bad = StateGraph(Full)
    bad.add_node("post", lambda s: {"posts": [{"kind": "verdict"}]})
    bad.add_edge(START, "post")
    with pytest.raises(ValueError, match="undeclared"):
        bad.compile().invoke({"posts": []})


# ---- Q4: typed interrupts in Send branches, mixed resume map, drain --------------------------

def test_q4_mixed_resume_map_applies_valid_and_raises_for_invalid(tmp_path):
    from pydantic import BaseModel
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command, Send, interrupt

    class Answer(BaseModel):
        decision: str

    class Branch(TypedDict, total=False):
        log: Annotated[list, operator.add]
        b: int

    def ask(state):
        answer = interrupt({"branch": state["b"]}, response_schema=Answer)
        approved = (tmp_path / f"approval-{state['b']}").exists()
        return {"log": [f"{state['b']}:{answer.decision}:{'pass' if approved else 'refuse'}"]}

    child = StateGraph(Branch)
    child.add_node("ask", ask)
    child.add_edge(START, "ask")
    parent = StateGraph(Log)
    parent.add_node("branch", child.compile())
    parent.add_conditional_edges(START, lambda s: [Send("branch", {"b": i}) for i in (1, 2)], ["branch"])
    parent.add_edge("branch", END)
    app = parent.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "q4"}}
    app.invoke({"log": []}, config)
    pending = app.get_state(config).interrupts
    assert len(pending) == 2
    first, second = sorted(pending, key=lambda p: p.value["branch"])
    with pytest.raises(Exception, match="validation error"):
        app.invoke(Command(resume={first.id: {"decision": "approve"}, second.id: {"decision": 5}}), config)
    assert len(app.get_state(config).interrupts) == 1  # partial progress: why the substrate validates first
    app.invoke(Command(resume={second.id: {"decision": "approve"}}), config)
    assert sorted(app.get_state(config).values["log"]) == ["1:approve:refuse", "2:approve:refuse"]


# ---- Q5: strict msgpack ----------------------------------------------------------------------

class Card:  # placeholder replaced below by a pydantic model at import of the probe
    pass


def test_q5_strict_msgpack_round_trips_messages_and_blocks_models(tmp_path):
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.graph import START, StateGraph
    from pydantic import BaseModel

    global Card

    class Card(BaseModel):  # noqa: F811 - module-level name so the serializer records its path
        title: str

    Card.__module__, Card.__qualname__ = __name__, "Card"
    globals()["Card"] = Card

    class Q5(TypedDict, total=False):
        messages: list
        card: object

    builder = StateGraph(Q5)
    builder.add_node("w", lambda s: {"messages": [HumanMessage("h"), AIMessage("a"), ToolMessage("t", tool_call_id="1")],
                                     "card": Card(title="synthetic")})
    builder.add_edge(START, "w")
    strict = lambda: JsonPlusSerializer(allowed_msgpack_modules=None)
    path = str(tmp_path / "q5.sqlite")
    builder.compile(checkpointer=SqliteSaver(sqlite3.connect(path, check_same_thread=False), serde=strict())).invoke(
        {}, {"configurable": {"thread_id": "q5"}})
    reloaded = builder.compile(checkpointer=SqliteSaver(sqlite3.connect(path, check_same_thread=False), serde=strict()))
    values = reloaded.get_state({"configurable": {"thread_id": "q5"}}).values
    assert [type(m).__name__ for m in values["messages"]] == ["HumanMessage", "AIMessage", "ToolMessage"]
    assert type(values["card"]) is dict and values["card"]["title"] == "synthetic"


# ---- behaviours found while building the kernel ----- ----------------------------------------

CHILD_SCRIPT = """
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
class S(TypedDict, total=False):
    n: int
g = StateGraph(S); g.add_node('a', lambda s: {'n': 1}); g.add_edge(START, 'a'); g.add_edge('a', END)
app = g.compile(checkpointer=InMemorySaver())
list(app.stream({'n': 0}, {'configurable': {'thread_id': 'x'}, 'max_concurrency': int(__import__('sys').argv[1])},
                stream_mode=['updates'], subgraphs=True, version='v2', durability='sync'))
print('ok')
"""


def test_s1_stream_with_subgraphs_deadlocks_at_max_concurrency_one():
    # graph_substrate reserves one extra executor slot for the stream consumer.
    assert _child(CHILD_SCRIPT, 2).stdout.strip() == "ok"
    process = subprocess.Popen([sys.executable, "-c", textwrap.dedent(CHILD_SCRIPT), "1"], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env={**os.environ, "LANGSMITH_TRACING": "false"})
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            process.communicate(timeout=8)
    finally:
        process.kill()
        process.communicate()


def test_s2_stream_with_subgraphs_reraises_a_handled_node_error():
    # graph_substrate swallows exactly the exception objects its default handler routed.
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.errors import NodeError
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command
    def boom(state):
        raise KeyError("x")
    def handle(state, error: NodeError):
        return Command(goto=END, update={"log": ["handled"]})
    builder = StateGraph(Log)
    builder.set_node_defaults(error_handler=handle)
    builder.add_node("boom", boom)
    builder.add_edge(START, "boom")
    app = builder.compile(checkpointer=InMemorySaver())
    assert app.invoke({"log": []}, {"configurable": {"thread_id": "a"}})["log"] == ["handled"]
    with pytest.raises(KeyError):
        list(app.stream({"log": []}, {"configurable": {"thread_id": "b"}, "max_concurrency": 2},
                        stream_mode=["updates"], subgraphs=True, version="v2"))
    assert app.get_state({"configurable": {"thread_id": "b"}}).values["log"] == ["handled"]


# ---- R1-R13: the probes behind the pair-review changes (LANGGRAPH-SUBSTRATE App. A, D) ---------

class Trail(TypedDict, total=False):
    trail: Annotated[list, operator.add]
    handoff: str


def _mark(name, **extra):
    def body(state):
        return {"trail": [name], **extra}
    return body


def test_r1_command_parent_drops_two_levels_down_skips_finish_one_level_down_data_handoff_works():
    """F1/A12: handoffs are final-record data routed by the parent's path_map; Command.PARENT is banned."""
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command

    def top(agent):
        builder = StateGraph(Trail)
        builder.add_node("agent", agent)
        builder.add_node("role_b", _mark("top:role_b"))
        builder.add_node("refuse_unregistered", _mark("top:refuse"))
        builder.add_edge(START, "agent")
        builder.add_edge("role_b", END)
        builder.add_edge("refuse_unregistered", END)
        return builder

    # Two levels: a loop subgraph inside the agent subgraph hands off to the top graph.
    loop = StateGraph(Trail)
    loop.add_node("handoff", lambda s: Command(goto="role_b", graph=Command.PARENT, update={"trail": ["loop:handoff"]}))
    loop.add_edge(START, "handoff")
    agent = StateGraph(Trail)
    agent.add_node("prepare", _mark("agent:prepare"))
    agent.add_node("loop", loop.compile())
    agent.add_node("finish", _mark("agent:finish"))
    agent.add_edge(START, "prepare")
    agent.add_edge("prepare", "loop")
    agent.add_edge("loop", "finish")
    agent.add_edge("finish", END)
    builder = top(agent.compile())
    builder.add_edge("agent", END)
    assert builder.compile().invoke({"trail": []})["trail"] == ["agent:prepare", "loop:handoff", "agent:finish"]

    # One level: the handoff arrives, but finish never runs.
    agent = StateGraph(Trail)
    agent.add_node("run", lambda s: Command(goto="role_b", graph=Command.PARENT, update={"trail": ["agent:run"]}))
    agent.add_node("finish", _mark("agent:finish"))
    agent.add_edge(START, "run")
    agent.add_edge("run", "finish")
    builder = top(agent.compile())
    assert builder.compile().invoke({"trail": []})["trail"] == ["agent:run", "top:role_b"]

    # Data handoff: finish runs, then the parent routes through its path_map.
    for target, expected in (("role_b", "top:role_b"), ("role_x", "top:refuse")):
        agent = StateGraph(Trail)
        agent.add_node("final", _mark("loop:final", handoff=target))
        agent.add_node("finish", _mark("agent:finish"))
        agent.add_edge(START, "final")
        agent.add_edge("final", "finish")
        builder = top(agent.compile())
        builder.add_conditional_edges("agent", lambda s: s["handoff"] if s["handoff"] == "role_b" else "refuse",
                                      {"role_b": "role_b", "refuse": "refuse_unregistered"})
        assert builder.compile().invoke({"trail": []})["trail"] == ["loop:final", "agent:finish", expected]


def test_r2_handler_defaults_are_not_inherited_and_a_handler_goto_outside_its_graph_is_swallowed():
    """F8/N4: every builder owns its handler; a handler routes only inside its builder."""
    from langgraph.errors import NodeError
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command

    def boom(state):
        raise KeyError("inner")

    def parent(inner):
        seen = []
        def handle(state, error: NodeError):
            seen.append(error.node)
            return Command(goto="decision", update={"trail": ["parent:handler"]})
        builder = StateGraph(Trail)
        builder.set_node_defaults(error_handler=handle)
        builder.add_node("agent", inner)
        builder.add_node("decision", _mark("parent:decision"))
        builder.add_edge(START, "agent")
        builder.add_edge("agent", END)
        builder.add_edge("decision", END)
        return builder.compile(), seen

    inner = StateGraph(Trail)
    inner.add_node("work", boom)
    inner.add_edge(START, "work")
    app, seen = parent(inner.compile())
    assert app.invoke({"trail": []})["trail"] == ["parent:handler", "parent:decision"] and seen == ["agent"]

    def escape(state, error: NodeError):
        return Command(goto="decision", update={"trail": ["inner:handler"]})
    inner = StateGraph(Trail)
    inner.set_node_defaults(error_handler=escape)
    inner.add_node("work", boom)
    inner.add_edge(START, "work")
    app, seen = parent(inner.compile())
    assert app.invoke({"trail": []})["trail"] == ["inner:handler"] and seen == []


R3 = """
import os, sys, sqlite3
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.runtime import get_runtime
from langgraph.types import RetryPolicy
class Transient(Exception):
    pass
class S(TypedDict, total=False):
    n: int
def node(state):
    info = get_runtime().execution_info
    with open(sys.argv[2], 'a') as f:
        f.write(f'{info.node_attempt} {info.task_id}\\n')
    if info.node_attempt == 1 and os.environ['PROBE_CRASH']:
        raise Transient()
    if os.environ['PROBE_CRASH']:
        os._exit(9)
    return {'n': 1}
g = StateGraph(S); g.add_node('a', node, retry_policy=RetryPolicy(retry_on=Transient, initial_interval=0.01))
g.add_edge(START, 'a'); g.add_edge('a', END)
app = g.compile(checkpointer=SqliteSaver(sqlite3.connect(sys.argv[1], check_same_thread=False)))
print(app.invoke({'n': 0} if os.environ['PROBE_CRASH'] else None, {'configurable': {'thread_id': 't'}}))
"""


def test_r3_node_attempt_restarts_at_one_after_a_resume_with_the_same_task_id(tmp_path):
    """F9: attempt numbers come from the ledger; node_attempt is observation only."""
    log = tmp_path / "attempts.txt"
    assert _child(R3, tmp_path / "db.sqlite", log, crash="1").returncode == 9
    assert _child(R3, tmp_path / "db.sqlite", log).returncode == 0
    rows = [line.split() for line in log.read_text().splitlines()]
    assert [r[0] for r in rows] == ["1", "2", "1"] and len({r[1] for r in rows}) == 1


class Fan(TypedDict, total=False):
    done: Annotated[list, operator.add]
    started: Annotated[list, operator.add]
    k: int


def _fanout(item_body, *, handler=None, target=None):
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Send
    builder = StateGraph(Fan)
    if handler is not None:
        builder.set_node_defaults(error_handler=handler)
    builder.add_node("item", target or item_body)
    builder.add_conditional_edges(START, lambda s: [Send("item", {"k": k}) for k in (1, 2, 3, 4)], ["item"])
    builder.add_edge("item", END)
    return builder


def test_r5a_an_interrupt_in_one_send_item_does_not_cancel_its_siblings(tmp_path):
    """F17 refuted for interrupts: siblings complete; only the interrupted item re-runs."""
    import time as clock
    from langgraph.types import Command, interrupt
    entries = []

    def item(state):
        entries.append(state["k"])
        if state["k"] == 1:
            interrupt({"ask": 1})
            return {"done": [1]}
        clock.sleep(0.2)
        return {"done": [state["k"]]}
    app = _fanout(item).compile(checkpointer=_saver(tmp_path / "db.sqlite"))
    config = {"configurable": {"thread_id": "t"}, "max_concurrency": 2}
    first = app.invoke({"done": []}, config)
    assert sorted(first["done"]) == [2, 3, 4] and len(app.get_state(config).interrupts) == 1
    entries.clear()
    final = app.invoke(Command(resume="ok"), config)
    assert entries == [1] and sorted(final["done"]) == [1, 2, 3, 4]


def test_r5b_r5c_a_send_item_exception_is_contained_only_by_a_subgraph_target_with_its_own_handler():
    """N1: a default handler does not contain a Send item's exception; a subgraph target does."""
    import time as clock
    from langgraph.errors import NodeError
    from langgraph.graph import END, START, StateGraph
    started = []

    def item(state):
        started.append(state["k"])
        if state["k"] == 1:
            raise ValueError("boom")
        clock.sleep(0.2)
        return {"done": [state["k"]]}
    with pytest.raises(ValueError):  # R5b: without a handler the run raises (which items started is timing)
        _fanout(item).compile().invoke({"done": []}, {"max_concurrency": 2})
    packets = []
    def handle(state, error: NodeError):
        packets.append(dict(state))
        return {"done": ["handled"]}
    started.clear()
    with pytest.raises(ValueError, match="boom"):
        _fanout(item, handler=handle).compile().invoke({"done": []}, {"max_concurrency": 2})
    assert packets and packets[0].get("k") == 1

    class Done(TypedDict, total=False):
        done: Annotated[list, operator.add]

    def contain(state, error: NodeError):
        return {"done": [f"failed:{state['k']}"]}
    inner = StateGraph(Fan, output_schema=Done)  # a private output (R8)
    inner.set_node_defaults(error_handler=contain)
    inner.add_node("work", item)
    inner.add_edge(START, "work")
    inner.add_edge("work", END)
    final = _fanout(None, target=inner.compile()).compile().invoke({"done": []}, {"max_concurrency": 2})
    assert sorted(map(str, final["done"])) == ["2", "3", "4", "failed:1"]


def test_r6_r9_destinations_and_command_goto_are_not_enforced_path_map_is():
    """F14/N2/A12: branching only by path_map; Command bodies banned."""
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command

    builder = StateGraph(Trail)
    builder.add_node("gate", lambda s: Command(goto="other", update={"trail": ["gate"]}), destinations=("effect",))
    builder.add_node("effect", _mark("effect"))
    builder.add_node("other", _mark("other"))
    builder.add_edge(START, "gate")
    assert builder.compile().invoke({"trail": []})["trail"] == ["gate", "other"]

    builder = StateGraph(Trail)  # R9: a static edge and a Command goto both run
    builder.add_node("gate", lambda s: Command(goto="hold", update={"trail": ["gate"]}))
    builder.add_node("effect", _mark("effect"))
    builder.add_node("hold", _mark("hold"))
    builder.add_edge(START, "gate")
    builder.add_edge("gate", "effect")
    assert sorted(builder.compile().invoke({"trail": []})["trail"]) == ["effect", "gate", "hold"]

    builder = StateGraph(Trail)  # a goto to an unknown node is dropped silently
    builder.add_node("gate", lambda s: Command(goto="nowhere", update={"trail": ["gate"]}))
    builder.add_edge(START, "gate")
    assert builder.compile().invoke({"trail": []})["trail"] == ["gate"]

    builder = StateGraph(Trail)  # a router key outside path_map raises
    builder.add_node("gate", _mark("gate"))
    builder.add_node("work", _mark("work"))
    builder.add_edge(START, "gate")
    builder.add_conditional_edges("gate", lambda s: "elsewhere", {"work": "work"})
    with pytest.raises(Exception):
        builder.compile().invoke({"trail": []})


def test_r7_node_input_schema_does_not_filter_send_a_subgraph_input_schema_does():
    """A10: map_node sends only to subgraphs whose graph-level input_schema is the role view."""
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Send

    class Full(TypedDict, total=False):
        public: str
        secret: str
        seen: Annotated[list, operator.add]

    class View(TypedDict, total=False):
        public: str

    def look(state):
        return {"seen": [sorted(state)]}

    def parent(target, **options):
        builder = StateGraph(Full)
        builder.add_node("look", target, **options)
        builder.add_conditional_edges(START, lambda s: [Send("look", {"public": "p", "secret": "s"})], ["look"])
        builder.add_edge("look", END)
        return builder.compile()
    assert parent(look, input_schema=View).invoke({})["seen"] == [["public", "secret"]]
    inner = StateGraph(Full, input_schema=View)
    inner.add_node("look", look)
    inner.add_edge(START, "look")
    inner.add_edge("look", END)
    assert "secret" not in parent(inner.compile()).invoke({})["seen"][0]


def test_r8_parallel_children_returning_base_channels_collide():
    """A11: base channels are private; a child's output is one keyed results entry."""
    from langgraph.errors import InvalidUpdateError
    from langgraph.graph import END, START, StateGraph

    class Parent(TypedDict, total=False):
        meta: dict
        budget: Annotated[int, operator.add]

    child = StateGraph(Parent)
    child.add_node("spend", lambda s: {"budget": 1})
    child.add_edge(START, "spend")
    child.add_edge("spend", END)
    builder = StateGraph(Parent)
    builder.add_node("a", child.compile())
    builder.add_node("b", child.compile())
    builder.add_edge(START, "a")
    builder.add_edge(START, "b")
    with pytest.raises(InvalidUpdateError):
        builder.compile().invoke({"meta": {"graph": "p"}, "budget": 10})


def test_r10_a_router_returning_send_bypasses_its_path_map():
    """N3: only map_node may emit Send, and its router asserts its declared target."""
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Send
    builder = StateGraph(Trail)
    builder.add_node("work", _mark("work"))
    builder.add_node("effect", _mark("effect"))
    builder.add_conditional_edges(START, lambda s: Send("effect", {"trail": []}), {"work": "work"})
    builder.add_edge("effect", END)
    assert builder.compile().invoke({"trail": []})["trail"] == ["effect"]


def test_r11_a_nonblocking_flock_refuses_another_thread_and_a_nested_call(tmp_path):
    """F7: the campaign lock is re-entrant in-process (effect_ledger.reentrant_lock)."""
    import threading
    from ravel.workflow.state_io import file_lock
    lock = tmp_path / "operation.lock"
    outcomes = []
    with file_lock(lock, blocking=False):
        with pytest.raises(ValueError, match="another process owns"):
            with file_lock(lock, blocking=False):
                pass
        def other():
            try:
                with file_lock(lock, blocking=False):
                    outcomes.append("acquired")
            except ValueError:
                outcomes.append("refused")
        worker = threading.Thread(target=other)
        worker.start()
        worker.join(10)
    assert outcomes == ["refused"]


def test_r12_tasks_and_updates_events_carry_payloads():
    """F12/A14: the runner writes redacted event lines only."""
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Send

    class Board(TypedDict, total=False):
        sealed: Annotated[list, operator.add]
        payload: str

    builder = StateGraph(Board)
    builder.add_node("propose", lambda s: {"sealed": [s["payload"]]})
    builder.add_conditional_edges(START, lambda s: [Send("propose", {"payload": "SECRET-HYPOTHESIS"})], ["propose"])
    builder.add_edge("propose", END)
    parts = list(builder.compile().stream({}, stream_mode=["tasks", "updates"], subgraphs=True, version="v2"))
    assert "SECRET-HYPOTHESIS" in json.dumps([p["data"] for p in parts], default=str)


R13 = """
import fcntl, os, subprocess, sys, time
lock = open(sys.argv[1], 'w'); fcntl.flock(lock, fcntl.LOCK_EX)
fds = (lock.fileno(),) if sys.argv[2] == 'inherit' else ()
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(4)'], start_new_session=True, pass_fds=fds,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(child.pid, flush=True)
os._exit(0)
"""


def test_r13_a_lease_survives_its_holder_only_when_the_orphan_inherits_the_descriptor(tmp_path):
    """A9: the per-job supervisor passes the lease descriptor to the native job."""
    import fcntl
    import signal
    results = {}
    for mode in ("drop", "inherit"):
        lease = tmp_path / f"{mode}.lock"
        done = _child(R13, lease, mode)
        orphan = int(done.stdout.split()[0])
        with open(lease, "w") as probe:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                results[mode] = "acquired"
            except BlockingIOError:
                results[mode] = "busy"
        os.kill(orphan, signal.SIGKILL)
    assert results == {"drop": "acquired", "inherit": "busy"}
