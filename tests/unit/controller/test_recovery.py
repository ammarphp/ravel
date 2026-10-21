"""Runtime recovery: which typed reasons are recoverable, the recovery budget and the planner's proposal rules."""
from __future__ import annotations

import pytest

from test_p06_support import new_store
from ravel.controller import recovery


@pytest.mark.parametrize('reason', ['run_input_missing', 'validators_inconclusive:validator_input_missing',
                                    'predecessor_unreceipted', 'reader_unavailable: no reader for the format',
                                    'source_unavailable', 'service_refused: 503'])
def test_recoverable_reasons_of_an_exhausted_or_held_step(reason):
    for status in ('failed', 'held'):
        assert recovery.classify({'status': status, 'reason': reason})['recoverable'] is True


@pytest.mark.parametrize('reason', ['provider_policy_refused', 'authority_refused', 'worker_sandbox_unavailable',
                                    'confined_launch_refused', 'forbidden_input', 'ledger_refused:missing_row',
                                    'budget_exhausted', 'run_stopped', 'validators_failed', 'review_uncredited',
                                    'instruction_packet_refused', 'transport_unavailable', 'run_input_changed', ''])
def test_safety_authority_confinement_ledger_stop_and_budget_reasons_are_never_recovered(reason):
    assert recovery.classify({'status': 'held', 'reason': reason})['recoverable'] is False


def test_a_retry_or_a_completed_step_is_not_recovered():
    for status in ('retry', 'completed', 'running', 'budget_exhausted', 'stopped'):
        assert recovery.classify({'status': status, 'reason': 'run_input_missing'})['recoverable'] is False


def test_requests_count_against_the_run_budget_and_a_spent_budget_is_named(tmp_path):
    store = new_store(tmp_path)
    mode = {'budgets': {'recoveries': 1}}
    row = {'status': 'held', 'reason': 'run_input_missing', 'attempts': 1}
    step = {'id': 's1', 'kind': 'derive', 'inputs': [{'artifact': 'inputs/missing.json'}], 'outputs': []}
    first = recovery.request(store, mode, step, row, {'detail': 'no file'}, run_inputs=[{'artifact': 'inputs/a.json'}],
                             tools=['op'])
    assert first['kind'] == 'recovery' and first['status'] == 'pending'
    assert first['request']['recovery']['failed_step'] == 's1' and first['request']['recovery']['run_inputs']
    assert recovery.request(store, mode, step, row, None, run_inputs=[], tools=[]) is None  # asked once
    other = {**step, 'id': 's2'}
    assert recovery.request(store, mode, other, row, None, run_inputs=[], tools=[]) is None
    assert [r['phase'] for r in store.scan(recovery.KIND)] == ['requested', 'budget_exhausted']
    assert recovery.used(store) == 1
    gaps = {gap['step']: gap['outcome'] for gap in recovery.gaps(store)}
    assert gaps == {'s1': 'requested', 's2': 'budget_exhausted'}  # an open request is not a completed recovery
    store.append(recovery.KIND, {'phase': 'adopted', 'step': 's1'})
    assert [gap['step'] for gap in recovery.gaps(store)] == ['s2']
    assert 'the recovery budget was exhausted' in recovery.summary(store)
    assert recovery.budget({}) == recovery.DEFAULT_BUDGET and recovery.budget({'budgets': {'recoveries': 0}}) == 0


def test_a_proposal_states_evidence_rejections_and_a_bound_for_an_approximation():
    good = {'failed_step': 's1', 'chosen': 'b', 'alternatives': [
        {'id': 'a', 'kind': 'method', 'description': 'other method', 'evidence': ['none admitted'],
         'rejection': 'no admitted operation'},
        {'id': 'b', 'kind': 'source', 'description': 'other source', 'evidence': ['inputs/b.json is staged']}]}
    assert recovery.proposal_errors(good, 's1') == []
    assert recovery.direction(recovery.chosen(good)) == 'input'
    assert recovery.direction({'kind': 'descope'}) == 'scope' and recovery.direction({'kind': 'method'}) == 'plan'
    bad = {'failed_step': 's1', 'chosen': 'x', 'alternatives': [
        {'id': 'a', 'kind': 'approximation', 'description': 'rough', 'evidence': []},
        {'id': 'a', 'kind': 'guess', 'description': 'guess', 'evidence': ['e']}]}
    errors = ' '.join(recovery.proposal_errors(bad, 's2'))
    for text in ('another failed step', 'distinct ids', 'unknown kind', 'cites no evidence', 'states no bound',
                 'no rejection reason', 'not among those considered'):
        assert text in errors, text
    none = {'failed_step': 's1', 'chosen': None, 'alternatives': [good['alternatives'][0]]}
    assert recovery.proposal_errors(none, 's1') == [] and recovery.chosen(none) is None


def test_the_operator_recovery_budget_is_finite_and_narrows_for_children(tmp_path):
    from copy import deepcopy
    from ravel.controller.authority import mode, operator
    assert operator.DEFAULT_BUDGETS['recoveries'] == 2 and 'recoveries' not in operator.NULLABLE_BUDGETS
    parent = {'mode': 'autonomous', 'delegation': 'operator_configured', 'budgets': deepcopy(operator.DEFAULT_BUDGETS),
              'bounds': deepcopy(operator.DEFAULT_BOUNDS), 'machine_checkins': list(operator.MACHINE_CHECKINS),
              'r3_policy': 'escalate_and_wait', 'wait_bound_seconds': 60, 'notify_command': None,
              'allow_unconfined': False}
    assert mode.narrow(parent, {'budgets': {'recoveries': 1}})['budgets']['recoveries'] == 1
    with pytest.raises(Exception, match='widen budget recoveries'):
        mode.narrow(parent, {'budgets': {'recoveries': 3}})
    with pytest.raises(ValueError):
        operator.validate({**operator.default_config(), 'budgets': {**operator.DEFAULT_BUDGETS, 'recoveries': None}})
