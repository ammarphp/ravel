"""Required durable LangGraph routing over the existing scientific services.

Framework checkpoints schedule/recover work. The canonical Graph call receipts,
current source/role bindings, campaign budgets and ordinary scientific approvals
remain authoritative. No framework value is accepted as an effect receipt.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from copy import deepcopy
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import stat
from typing import Annotated, TypedDict

from . import graph_environment  # noqa: F401  (strict msgpack before any LangGraph import)
from . import state_io


REQUIRED = {'langgraph': '1.2.14', 'langgraph-checkpoint-sqlite': '3.1.1',
            'langgraph-checkpoint': '4.2.0', 'langchain-core': '1.6.7'}


def _merge(left, right):
    result = dict(left)
    for key, value in right.items():
        if key in result and result[key] != value:
            raise ValueError('framework branch replaced a completed generation reference')
        result[key] = deepcopy(value)
    return result


class ScheduleState(TypedDict):
    # Only public node identities/references are shared. Role content and Host
    # objects are closures, never graph state or model context.
    completed: Annotated[dict, _merge]


class _RetryGeneration(Exception):
    """Framework retry policy, still subject to the original call/attempt ledger."""


def identity():
    """Version/source identity, not a certificate of all installed package files."""
    versions = {}
    for package, expected in REQUIRED.items():
        actual = metadata.version(package)
        if actual != expected:
            raise ValueError(f'required research framework {package} must be {expected}; found {actual}')
        versions[package] = actual
    raw = Path(__file__).read_bytes()
    return {'backend': 'langgraph', 'versions': versions,
            'adapter_sha256': hashlib.sha256(raw).hexdigest(),
            'persistence': 'local_sqlite', 'durability': 'sync',
            'installed_member_census_verified': False}


def _regular_database(path):
    path = Path(path)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('framework database path cannot traverse a symlink')
    if path.exists() and not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('framework database must be a regular file')
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
    return path


def _checkpoint_root(root):
    root = Path(root).expanduser().absolute()
    if root.is_symlink() or any(p.is_symlink() for p in root.parents):
        raise ValueError('framework checkpoint directory cannot traverse an alias')
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise ValueError('framework checkpoint directory must be an ordinary directory')
    return root


@contextmanager
def persistent(root):
    """One local framework history; no in-memory restart fallback."""
    from langgraph.checkpoint.sqlite import SqliteSaver
    root = _checkpoint_root(root)
    db = _regular_database(root / 'checkpoints.sqlite')
    connection = graph_environment.open_checkpoint_connection(db)
    try:
        try:
            from . import graph_substrate
        except ImportError:
            yield SqliteSaver(connection)
        else:
            graph_substrate.environment()
            yield SqliteSaver(connection,serde=graph_substrate.strict_serializer())
    finally:
        connection.close()


def _completed(root, node_id, host_sha):
    """Consume a canonical completed generation without allocating an attempt."""
    from . import agent_graph as graph
    with state_io.file_lock(root / 'state.lock'):
        spec, state = graph._load(root)
        node = next(n for n in spec['nodes'] if n['id'] == node_id)
        graph._artifact_checks(node)
        current = state['nodes'][node_id]
        if current['status'] != 'completed':
            return None
        saved = graph._result(root, current['result'])
        expected_host = graph._node_host_sha(node, host_sha)
        request = graph._request(spec, state, node, expected_host)
        saved_request = deepcopy(saved['request'])
        historical_revision = saved_request.pop('graph_revision', None)
        current_request = {k:v for k,v in request.items() if k != 'graph_revision'}
        # Canonical rework increments the global revision but preserves every
        # unaffected generation. Its pinned receipt may therefore predate this
        # revision; node/inputs/packet/dependencies/Host/goal/request ID may not.
        if (type(historical_revision) is not int
                or not 0 <= historical_revision <= state['graph_revision']
                or current['result']['binding_sha256'] != request['binding_sha256']
                or current['result']['host_sha256'] != expected_host
                or saved_request != current_request):
            raise graph.GraphError('completed generation source/request/host differs; explicit rework required')
        return {'generation': current['generation'], 'attempt_id': current['attempt_id'],
                'result': deepcopy(current['result'])}


def _generation(root, node_id, host_sha):
    from langgraph.types import interrupt
    from . import agent_graph as graph
    previous = _completed(root, node_id, host_sha)
    if previous is not None:
        return previous
    with state_io.file_lock(root / 'state.lock'):
        spec, state = graph._load(root)
        if state['cancelled']:
            return {'hold': 'cancelled'}
        graph._deadline(spec, state)
        node = next(n for n in spec['nodes'] if n['id'] == node_id)
        current = state['nodes'][node_id]
        if not all(state['nodes'][p]['status'] == 'completed' for p in node['depends_on']):
            return {'hold': 'dependency_unresolved'}
        external = node['kind'] == 'model' and node['action'] == 'external'
        if (current['status'] in {'ambiguous', 'cancelled'} or current['status'] == 'failed'
                and (not current['retryable'] or current['generation_attempts'] >= node['max_attempts'])):
            return {'hold': 'ordinary_reconciliation_or_rework_required'}
    if external:
        # Restart executes all validation above again. A resume boolean is not
        # a model result: only ordinary deliver_external can complete the node.
        interrupt({'kind': 'ordinary_external_response_required', 'graph_root': str(root),
                   'node_id': node_id, 'generation': current['generation'],
                   'approval_or_scientific_acceptance': False})
        completed = _completed(root, node_id, host_sha)
        if completed is None:
            raise graph.GraphError('framework resume lacks an ordinary authenticated external result')
        return completed
    return None


def _finish(root, host_sha):
    from . import agent_graph as graph
    with state_io.file_lock(root / 'state.lock'):
        spec, state = graph._load(root)
        if not state['cancelled']:
            graph._deadline(spec, state)
        nodes = deepcopy(spec['nodes'])
        completed = {k for k, v in state['nodes'].items() if v['status'] == 'completed'}
    for node in nodes:
        graph._artifact_checks(node)
        if node['id'] in completed:
            _completed(root, node['id'], host_sha)
    return graph.status(root)


def execute(root, host, *, workers=1, clear_stop=False):
    """Default framework scheduler; same public result as canonical Graph.

    Ordinary resume uses successful pending writes. Explicit rework/revision
    creates a new checkpoint thread generation, retaining old history while
    consuming unchanged completed canonical effects without another call.
    """
    from langgraph.graph import StateGraph, START, END
    from langgraph.types import Command, RetryPolicy
    from . import agent_graph as graph
    root = graph._root(root)
    graph._integer(workers, 'worker count', 1, 16)
    try:
        from . import graph_substrate as substrate
    except ImportError:
        substrate=None
    if substrate is not None:substrate.environment()
    framework_identity = substrate.identity() if substrate is not None else identity()
    host_sha = graph._host_identity(host)
    with state_io.file_lock(root / 'run.lock', blocking=False):
        with state_io.file_lock(root / 'state.lock'):
            spec, state = graph._load(root)
            cancelled = state['cancelled']
            if not cancelled:
                graph._deadline(spec, state)
            if getattr(host, 'privacy', None) == 'local_only' and any(
                    n['kind'] == 'model' and n['action'] == 'external' for n in spec['nodes']):
                raise graph.GraphError('local_only graph cannot use externally hosted model roles')
            for node in spec['nodes']:
                graph._artifact_checks(node)
            original = {'instance_id': state['instance_id'], 'spec_sha256': state['spec_sha256'],
                        'graph_revision': state['graph_revision'],
                        'generations': {k: v['generation'] for k, v in state['nodes'].items()},
                        'reconciliations': [e['sequence'] for e in state['history']
                                            if e['event'] in {'call_reconciled', 'resumed', 'drained'}]}
        if cancelled:
            return graph.status(root)
        # Thread generations are routing identities. Source/current-effect
        # validation below still rejects an unrelated/changed checkpoint.
        thread = graph.digest({'original': original, 'framework': framework_identity})
        builder = StateGraph(ScheduleState)
        labels = {n['id']: 'node_' + str(i) for i, n in enumerate(spec['nodes'])}
        def make_node(node_id):
            def perform(_state):
                completed = _generation(root, node_id, host_sha)
                if completed is not None and 'hold' in completed:
                    return {'completed': {}}
                if completed is None:
                    graph._run_node(root, node_id, host, host_sha)
                    completed = _completed(root, node_id, host_sha)
                if completed is None:
                    with state_io.file_lock(root / 'state.lock'):
                        latest_spec, latest = graph._load(root)
                        current = latest['nodes'][node_id]
                        node = next(n for n in latest_spec['nodes'] if n['id'] == node_id)
                        if (not latest['cancelled'] and current['status'] == 'failed' and current['retryable']
                                and current['generation_attempts'] < node['max_attempts']):
                            raise _RetryGeneration('ordinary retryable generation; original finite attempt budget applies')
                    return {'completed': {}}
                return {'completed': {node_id: completed}}
            return perform
        successors = set()
        for node in spec['nodes']:
            builder.add_node(labels[node['id']], make_node(node['id']), retry_policy=RetryPolicy(
                max_attempts=node['max_attempts'], initial_interval=0.0, jitter=False,
                retry_on=_RetryGeneration))
        # StateGraph requires all parents to exist when adding a list-valued
        # AND edge. Canonical specifications need not be topologically listed.
        for node in spec['nodes']:
            if node['depends_on']:
                builder.add_edge([labels[p] for p in node['depends_on']], labels[node['id']])
                successors.update(node['depends_on'])
            else:
                builder.add_edge(START, labels[node['id']])
        for node in spec['nodes']:
            if node['id'] not in successors:
                builder.add_edge(labels[node['id']], END)
        drained = []
        with persistent(root / 'framework') as saver, ExitStack() as lifecycle:
            try:
                from . import graph_substrate
            except ImportError:
                if any(n['kind'] in {'agent','map'} for n in spec['nodes']):
                    raise graph.GraphError('worker graphs require the graph substrate module')
                app = builder.compile(checkpointer=saver)
            else:
                from . import effect_ledger
                # The substrate runner lifecycle on the graph's effect scope: one runner per
                # scope, a runner epoch stamped into every reservation, reserving charges
                # recovered at start, and a stop request that dispatches no further node.
                scope = root / 'effects'
                if clear_stop:
                    graph_substrate.refuse_controller_switches(scope, clear_stop=True)
                    (scope / effect_ledger.STOP).unlink(missing_ok=True)
                lifecycle.enter_context(graph_substrate.scope_runner(effect_ledger._scope(scope), spec['graph_id'], thread))
                effect_ledger.recover(scope)
                def node_runner(node_id, _host):
                    while True:
                        if effect_ledger.stop_requested(scope):
                            # Drained: nothing is dispatched; a recorded drain routes the
                            # next run to a new thread generation that re-enters the node.
                            drained.append(node_id)
                            return None
                        try:
                            return make_node(node_id)({})['completed'].get(node_id)
                        except _RetryGeneration:
                            continue  # canonical node/graph budgets bound every retry
                ctx = graph_substrate.BuildContext(root, spec['graph_id'], state['graph_revision'],
                    {'graph_root':str(root)}, node_runner=node_runner)
                ctx.checkpointer = saver
                from .graphs import intake_plan
                app = intake_plan.compile_if_planner(spec, host, ctx)
            config = {'configurable': {'thread_id': thread}, 'max_concurrency': workers,
                      'recursion_limit': len(spec['nodes']) + 3}
            snapshot = app.get_state(config)
            if snapshot.created_at:
                # Even fully checkpointed results are checked against current
                # canonical receipts before they can be returned or reused.
                for node_id, result in snapshot.values.get('completed', {}).items():
                    if node_id not in labels or _completed(root, node_id, host_sha) != result:
                        raise graph.GraphError('framework checkpoint differs from current generation receipt')
                pauses = snapshot.interrupts
                if pauses:
                    with state_io.file_lock(root / 'state.lock'):
                        _, current = graph._load(root)
                    if any(current['nodes'][p.value['node_id']]['status'] != 'completed' for p in pauses):
                        return _finish(root, host_sha)
                    value = Command(resume={p.id: None for p in pauses})
                else:
                    value = None
            else:
                value = {'completed': {}}
            app.invoke(value, config, durability='sync')
            if drained:
                with state_io.file_lock(root / 'state.lock'):
                    _, latest = graph._load(root)
                    graph._event(latest, 'drained', nodes=sorted(set(drained)))
                    graph._save(root, latest)
        if (substrate.identity() if substrate is not None else identity()) != framework_identity:
            raise graph.GraphError('research framework identity changed during execution')
        return _finish(root, host_sha)


def run_state_machine(directory, *, thread_id, state_type, nodes, edges,
                      conditional_edges=(), initial, resume=None, max_steps, identity_binding,
                      max_concurrency=1, event_sink=None):
    """Shared durable coordinator/subgraph runner, not a new authority ledger.

    Node adapters own exact domain-effect receipt checks. This state contains
    public pins/status; it is never delivered wholesale to a blind model role.
    """
    from langgraph.graph import StateGraph
    from langgraph.types import Command
    if type(thread_id) is not str or not thread_id.strip():
        raise ValueError('exact source-bound public thread identity required')
    if type(max_steps) is not int or max_steps < 1 or type(max_concurrency) is not int or max_concurrency < 1:
        raise ValueError('positive original finite framework limits required')
    json.dumps(identity_binding,sort_keys=True,allow_nan=False)
    before = identity()
    builder = StateGraph(state_type)
    for name, function in nodes.items():
        builder.add_node(name, function)
    for left, right in edges:
        builder.add_edge(left, right)
    for name, route, mapping in conditional_edges:
        builder.add_conditional_edges(name, route, mapping)
    key = hashlib.sha256(json.dumps({'thread': thread_id, 'binding': identity_binding,
                                    'framework': before}, sort_keys=True).encode()).hexdigest()
    directory = _checkpoint_root(directory)
    lock = directory / 'invocation.lock'
    if lock.is_symlink() or (lock.exists() and not stat.S_ISREG(lock.lstat().st_mode)):
        raise ValueError('framework invocation lock must be an ordinary file')
    # SQLite serializes writes, not application get_state/invoke decisions.
    # Keep one nonblocking owner across the whole invocation and ending read.
    with state_io.file_lock(lock, blocking=False), persistent(directory) as saver:
        app = builder.compile(checkpointer=saver)
        config = {'configurable': {'thread_id': key}, 'recursion_limit': max_steps,
                  'max_concurrency': max_concurrency}
        old = app.get_state(config)
        if old.created_at:
            # Ordinary retry re-enters the node without supplying an interrupt
            # response. A manufactured {interrupt_id: None} would resolve the
            # slot: interrupt() returns that value instead of pausing again.
            # Only an explicitly supplied response uses Command. It is routing
            # data; adapters must reauthenticate their actual domain predicate
            # after interrupt returns and before any scientific effect.
            value = Command(resume=resume) if resume is not None else None
        elif resume is not None:
            raise ValueError('cannot resume an absent research checkpoint')
        else:
            value = deepcopy(initial)
        if event_sink is None:
            app.invoke(value, config, durability='sync')
        else:
            if not callable(event_sink):
                raise ValueError('framework event sink must be a callable')
            for event in app.stream(value, config, stream_mode='updates', durability='sync'):
                # Observation only. The consumer receives detached public node
                # updates, never an approval or authority channel.
                event_sink(deepcopy(event))
        final = app.get_state(config)
        result = deepcopy(final.values)
        observation = {'thread_id': key, 'checkpoint_id': final.config.get('configurable', {}).get('checkpoint_id'),
                       'next': list(final.next), 'interrupted': bool(final.interrupts),
                       'interrupts': [{'id':p.id,'value':deepcopy(p.value)} for p in final.interrupts],
                       'framework': before, 'framework_values_are_scientific_authority': False}
        if identity() != before:
            raise ValueError('research framework identity changed during coordinator execution')
        return result, observation
