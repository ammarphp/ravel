"""``controller.step`` parent kinds: an ``ask`` or ``route`` step runs no worker and escalates a typed request.

The request is built from the approved plan step's own bytes: an ``ask`` carries its question, its options and its
P7 default; a ``route`` carries its route, scope, stated budget and child context lineage. The controller graph's
``parent_request`` consumes it. Fictional plans only; no worker, model or native call.
"""
from __future__ import annotations

import pytest

from test_p04_support import (graphs, inert_worker, make_step, records, run_env, run_step,  # noqa: F401
                              services_installed)

OPTIONS = [{'id': 'opt-a', 'description': 'the first fictional option'},
           {'id': 'opt-b', 'description': 'the second   fictional\noption'}]
P7 = {'assumption': 'The fictional run takes the first option.', 'default': 'opt-a', 'alternatives': ['opt-b'],
      'claim_type': 'comparison', 'direction_established': False, 'expected_sign': 'unknown',
      'expected_size': 'unknown', 'reversible_knob': 'option', 'flag': {'checkin_flag': 3, 'deviation': 'default'},
      'physics_critical': False, 'justification': None}


def ask_step(**judgment):
    step = make_step('q1', kind='ask', role=None, outputs=(), parameters={'judgment': judgment})
    step['question'] = 'Which fictional option should the run take?'
    return step


def test_an_ask_outcome_carries_the_plan_options_and_its_p7_default(run_env, inert_worker, graphs):
    step = ask_step(options=OPTIONS + [{'id': 'reject', 'description': 'every request offers its own refusal'},
                                       {'description': 'an option without an id'}],
                    default=P7, default_option='opt-a')
    outcome = run_step(run_env, step)
    assert outcome['status'] == 'escalated' and outcome['escalation'] == 'ask', outcome
    request = outcome['request']
    assert request['kind'] == 'ask' and request['status'] == 'escalated' and request['escalation'] == 'ask'
    assert request['question'] == step['question']
    assert request['options'] == [{'id': 'opt-a', 'description': 'the first fictional option'},
                                  {'id': 'opt-b', 'description': 'the second fictional option'}]
    assert request['default'] == 'opt-a'
    assert request['judgments'] == outcome['judgments'] and request['tier'] is None
    assert 'route' not in request and 'lineage' not in request
    assert records(run_env.store, 'step-dispatch') == []


@pytest.mark.parametrize('judgment', [{'options': OPTIONS, 'default_option': 'opt-a'},
                                      {'options': OPTIONS, 'default': P7, 'default_option': 'not-an-option'}])
def test_an_ask_default_is_only_a_p7_default_among_its_options(run_env, inert_worker, graphs, judgment):
    outcome = run_step(run_env, ask_step(**judgment))
    assert outcome['status'] == 'escalated'
    assert outcome['request']['default'] is None
    assert [o['id'] for o in outcome['request']['options']] == ['opt-a', 'opt-b']


def test_an_ask_without_options_escalates_an_empty_option_list(run_env, inert_worker, graphs):
    outcome = run_step(run_env, ask_step())
    # The controller graph's parent request holds this question, typed (ask_options_missing).
    assert outcome['request']['options'] == [] and outcome['request']['default'] is None


def test_a_route_outcome_carries_its_scope_budget_and_child_lineage(run_env, inert_worker, graphs):
    step = make_step('child-route', kind='route', role=None, outputs=(), budget={'wall_seconds': 30, 'children': 1},
                     parameters={'judgment': {'budget_fraction': 0.25}})
    step['route'] = 'study'
    outcome = run_step(run_env, step)
    assert outcome['status'] == 'escalated' and outcome['escalation'] == 'route', outcome
    request = outcome['request']
    assert request['kind'] == 'route' and request['status'] == 'escalated' and request['escalation'] == 'route'
    assert request['route'] == 'study'
    assert request['scope'] == {'step_id': 'child-route', 'attempt': 1}
    assert request['budget'] == {'budget': {'wall_seconds': 30, 'children': 1}, 'budget_share': {'fraction': 0.25}}
    plan_sha256 = records(run_env.store, 'plan')[-1]['plan_sha256']
    assert request['lineage'] == {'parent_plan_sha256': plan_sha256, 'parent_step_id': 'child-route', 'attempt': 1}
    assert request['judgments'] == outcome['judgments'] and request['tier'] is None
    assert 'options' not in request and 'question' not in request
    assert records(run_env.store, 'step-dispatch') == []


def test_a_step_of_another_kind_never_produces_a_parent_request(run_env, inert_worker, graphs):
    outcome = run_step(run_env, make_step('s1'))
    assert outcome['status'] == 'completed', outcome
    assert 'request' not in outcome and outcome['escalation'] is None
