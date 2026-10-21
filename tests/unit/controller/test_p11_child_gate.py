"""Adaptive ordinary children retain protected route custody at delivery."""
from copy import deepcopy
import pytest
from p11_fakes import FakeRunStore
from ravel.controller.routes import research


def control(tmp_path):
    store = FakeRunStore('child-custody', root=tmp_path/'protected')
    experiment = {'id': 'candidate', 'rundir': str(tmp_path/'ordinary'),
        'study': {'path': 'study.json', 'sha256': 'a'*64}, 'cost': {'wall_seconds': 10}}
    state = {'experiments': [experiment]}
    context = {'store': store, 'plan': {'parameters': {'research_children': []}}}
    dispatched = {'step': {'id': 'research-child-candidate', 'kind': 'route', 'route': 'study',
        'parameters': {'experiment': deepcopy(experiment), 'own_checkin1': True, 'inherit_authority': True, 'inherit_budget': True}},
        'outcome': {'step_id': 'research-child-candidate', 'attempt': 1, 'status': 'completed'}}
    return store, state, context, dispatched


def test_P03_MODE_research_comparison_adaptive_child_requires_completed_protected_route(tmp_path):
    store, state, context, dispatched = control(tmp_path)
    assert research.child_route_errors(state, context) == ['ordinary child has no completed governed route: candidate']
    store.append('research-step-outcome', dispatched)
    assert research.child_route_errors(state, context) == []


@pytest.mark.parametrize('damage', ['study', 'cost', 'rundir', 'route', 'status'])
def test_P03_C2_changed_child_or_refused_route_cannot_satisfy_delivery_custody(tmp_path, damage):
    store, state, context, dispatched = control(tmp_path)
    if damage == 'route':
        dispatched['step']['route'] = 'other'
    elif damage == 'status':
        dispatched['outcome']['status'] = 'held'
    else:
        dispatched['step']['parameters']['experiment'][damage] = 'changed'
    store.append('research-step-outcome', dispatched)
    assert research.child_route_errors(state, context) == ['ordinary child has no completed governed route: candidate']


def test_P03_declared_child_population_hole_survives_a_complete_other_child(tmp_path):
    store, state, context, dispatched = control(tmp_path)
    context['plan']['parameters']['research_children'] = [{'id': 'omitted'}]
    store.append('research-step-outcome', dispatched)
    assert research.child_route_errors(state, context) == ['declared ordinary child is missing: omitted']
