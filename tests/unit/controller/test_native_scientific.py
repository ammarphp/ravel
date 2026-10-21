"""Scientific row checks follow actual dispatch, staging and protected review credit."""
import pytest

from test_p04_support import (graphs, inert_worker, make_step, records, run_env,
                              run_step, services_installed)


@pytest.mark.parametrize('refusal', [None, 'dispatch', 'adopt', 'review'])
def test_declared_scientific_rows_are_checked_at_each_enforcing_boundary(
        run_env, inert_worker, graphs, monkeypatch, refusal):
    from ravel.controller.routes.study import runtime
    calls = []
    def check(store, step, context, *, phase):
        calls.append((phase, context, records(store, 'step-credit')))
        return ([{'code': 'scientific_evidence_unresolved', 'row': 'P05', 'message': 'changed basis'}]
                if phase == refusal else [])
    monkeypatch.setattr(runtime, 'scientific_checks', check)
    step = make_step('derive')
    step['parameters']['evidence_requirements'] = [
        {'row': 'P05', 'expected': 'inputs:expected.json',
         'observed': 'derive:outputs/result.json', 'validator': 'descriptor-continuity'}]
    result = run_step(run_env, step)
    phases = [row[0] for row in calls]
    if refusal == 'dispatch':
        assert phases == ['dispatch']
        assert records(run_env.store, 'worker-session') == []
        assert records(run_env.store, 'step-observation') == []
        assert result['status'] == 'held'
    elif refusal == 'adopt':
        assert phases == ['dispatch', 'adopt']
        assert result['status'] == 'failed'
    else:
        assert phases == ['dispatch', 'adopt', 'review']
        assert calls[-1][2] and calls[-1][2][-1]['credited'] is True
        assert calls[1][1]['allow_staged_evidence'] is True
        assert calls[-1][1]['ledger_scope']['step'] == step['id']
        assert result['status'] == ('held' if refusal else 'completed')
        if refusal:
            assert result['reason'] == 'scientific_evidence_unresolved'
    if refusal in ('adopt', 'review'):
        adopted = records(run_env.store, 'custody')
        assert adopted[-1]['status'] == 'rejected'
