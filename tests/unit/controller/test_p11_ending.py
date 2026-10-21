"""Actual original-budget refusal retains qualified scope and reaches the sink once."""
from copy import deepcopy
import sys
import types
import pytest
from ravel.workflow import research_controller as bridge, research_cycle as cycle
from p11_fakes import FakeRunStore
from test_research_cycle import contract


def test_R06_actual_budget_exhaustion_keeps_every_obligation_and_reuses_sink_receipt(tmp_path, monkeypatch):
    definition = contract(tmp_path)
    definition['budget']['calls'] = 1
    root = tmp_path/'run'/'campaign'
    root.parent.mkdir()
    cycle.create(root, definition, base_dir=tmp_path, evaluation_harness=True)
    _, before = cycle._load(root)
    amount = {'calls': 2, 'output_tokens': 0, 'wall_seconds': 0, 'native_attempts': 0}
    with pytest.raises(cycle.CampaignBudgetExhausted, match='resource ceiling exhausted: calls') as failure:
        cycle._charge(deepcopy(before), 'over-budget', amount, {})
    result = cycle.bounded_synthesis(root, str(failure.value), boundary={'operation': 'over-budget'})
    assert cycle._load(root)[1] == before
    store = FakeRunStore('bounded-control', root=tmp_path/'protected')
    context = {'run_dir': str(tmp_path/'run')}
    step = bridge._step('campaign', 'subgraph', outputs=['outputs/progress.json'])
    calls = []
    sink = types.ModuleType('ravel.controller.sink')
    def bounded_end(supplied_store, reason):
        assert supplied_store is store
        calls.append(reason)
        return {'kind': 'delivery-receipt', 'qualified': True, 'reason': reason}
    sink.bounded_end = bounded_end
    monkeypatch.setitem(sys.modules, 'ravel.controller.sink', sink)
    for _ in range(2):
        final = bridge._finish(store, step, context, root, store.path('research'), {}, {}, deepcopy(result))
        assert final['controller_outcome']['status'] == 'budget_exhausted'
        assert final['kind'] == 'research_bounded_synthesis'
        assert final['parent_task_accepted'] is False
        assert final['delivery_receipt']['qualified'] is True
        assert final['progress'] == result['progress']
        assert final['progress']['required_experiments'] == definition['required_experiments']
    assert calls == [str(failure.value)]
    assert len(store.scan('research-bounded-delivery')) == 1
    assert cycle._load(root)[1] == before


def test_R06_an_ordinary_pending_effect_is_held_without_qualified_delivery(tmp_path, monkeypatch):
    store = FakeRunStore('pending-control', root=tmp_path/'protected')
    sink = types.ModuleType('ravel.controller.sink')
    sink.bounded_end = lambda *args: pytest.fail('pending work is not resource exhaustion')
    monkeypatch.setitem(sys.modules, 'ravel.controller.sink', sink)
    context = {'run_dir': str(tmp_path/'run')}
    result = bridge._finish(store, bridge._step('campaign', 'subgraph'), context,
        tmp_path/'run/campaign', store.path('research'), {}, {}, {'phase': 'ordinary_effect_required'})
    assert result['controller_outcome']['status'] == 'held'
    assert store.scan('research-bounded-delivery') == []
