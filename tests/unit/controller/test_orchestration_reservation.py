"""An orchestrating subgraph reserves no model calls of its own; the research loop also no core-hours."""
from ravel.controller.step import graph


def subgraph(graph_id, **budget):
    return {'id': 'loop', 'kind': 'subgraph', 'graph': {'id': graph_id}, 'budget': budget}


def test_the_research_loop_reserves_its_wall_ceiling_and_no_calls_or_core_hours():
    amounts = graph._amounts(subgraph('research.loop', wall_seconds=1800), None, 'subgraph')
    assert amounts['wall_seconds'] == 1800 and amounts['model_calls'] == 0 and amounts['core_hours'] == 0


def test_declared_amounts_win_and_unknown_subgraphs_stay_unknown():
    amounts = graph._amounts(subgraph('research.loop', model_calls=5, core_hours=1.5), None, 'subgraph')
    assert amounts['model_calls'] == 5 and amounts['core_hours'] == 1.5
    binder = graph._amounts(subgraph('manuscript.build'), None, 'subgraph')
    assert binder['model_calls'] == 0 and binder['core_hours'] is None
    unknown = graph._amounts(subgraph('some.other.graph'), None, 'subgraph')
    assert unknown['model_calls'] is None and unknown['core_hours'] is None
