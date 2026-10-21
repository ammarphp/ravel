"""A route that refuses to bind its prepare outputs ends the bind node with a typed hold naming the refusal."""
import pytest

from ravel.controller import graph
from ravel.workflow import graph_nodes as nodes


class Store:
    def __init__(self):
        self.rows = []

    def append(self, kind, record):
        self.rows.append((kind, record))
        return f'{kind}-{len(self.rows)}'


class Route:
    def __init__(self, error):
        self.error = error

    def bind(self, plan, context):
        raise self.error


@pytest.fixture
def bound(monkeypatch):
    store = Store()
    monkeypatch.setattr(graph, '_store', lambda state: store)
    monkeypatch.setattr(graph, 'current_plan', lambda state, store: {'route': {'id': 'fictional'}, 'steps': []})
    monkeypatch.setattr(graph, 'adapter_context', lambda state, store: {})
    return store, monkeypatch


@pytest.mark.parametrize('error', [ValueError('evidence must name a staged run input'), KeyError('outputs'),
                                   TypeError('not a mapping'), OSError('unreadable')])
def test_a_refused_route_bind_is_a_typed_hold_with_its_reason(bound, error):
    store, monkeypatch = bound
    monkeypatch.setattr(graph, 'adapter', lambda state, store: Route(error))
    with pytest.raises(nodes.RecoveryHold) as held:
        graph.bind({})
    assert 'route_bind_refused' in str(held.value) or getattr(held.value, 'reason', None) == 'route_bind_refused'
    assert store.rows == [('route-bind-refusal', {'route': 'fictional', 'error': type(error).__name__,
                                                  'reason': str(error)[:1500]})]


def test_a_route_s_own_typed_hold_and_other_failures_pass_through(bound):
    store, monkeypatch = bound
    monkeypatch.setattr(graph, 'adapter', lambda state, store: Route(nodes.RecoveryHold('route_own_hold', 'x')))
    with pytest.raises(nodes.RecoveryHold, match='route_own_hold|x'):
        graph.bind({})
    monkeypatch.setattr(graph, 'adapter', lambda state, store: Route(RuntimeError('a defect, not a refusal')))
    with pytest.raises(RuntimeError):
        graph.bind({})
    assert store.rows == []
