"""A governed research step starts as a run of its own: a fresh context with only the node record and scope."""
from contextvars import ContextVar
from pathlib import Path

from ravel.workflow import graph_nodes, research_controller

AMBIENT = ContextVar('software-control-ambient-runnable-configuration', default=None)


class Store:
    run_id = 'run-20261020-000000-0000abcd'

    def __init__(self, root):
        self.root = root

    def path(self, *parts):
        return self.root.joinpath(*parts)


def test_only_the_node_record_and_the_research_scope_reach_the_governed_step(tmp_path):
    store, run_dir = Store(tmp_path / 'store'), tmp_path / 'run'
    run_dir.mkdir()
    record = {'ravel_kind': 'service', 'graph_id': 'research.loop', 'role': None, 'node': 'decision'}
    seen = []

    def step():
        seen.append((graph_nodes.TRIPWIRE.get(), AMBIENT.get(), research_controller.active()[0] is store,
                     research_controller.active()[1]['run_dir']))
        return 'outcome'
    tokens = graph_nodes.TRIPWIRE.set(record), AMBIENT.set({'callbacks': ['inherited']})
    try:
        assert research_controller.governed_call(store, {'run_dir': str(run_dir)}, step) == 'outcome'
    finally:
        AMBIENT.reset(tokens[1]); graph_nodes.TRIPWIRE.reset(tokens[0])
    assert seen == [(record, None, True, str(run_dir))]
    assert research_controller.active() is None, 'the scope is released after the step'
    research_controller.governed_call(store, {'run_dir': str(run_dir)}, step)
    assert seen[-1][:2] == (None, None)
