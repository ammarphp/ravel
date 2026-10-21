"""A producer step that a reviewer card executes: checks with no subject follow the step's declared outputs (D1).

The comparison card owes acceptance and cutflow checks, and the run owes both at a review point. A comparison step
that declares no event-level output records both as typed not-applicable, citing its declared products; a step that
declares an event-level output keeps them owed, so with no subject they stay inconclusive.
"""
from __future__ import annotations

from test_p04_support import (graphs, inert_worker, make_step, records, run_env, run_step,  # noqa: F401
                              services_installed)

CHECKS = ('check:validation.certify_acceptance', 'check:validation.validate_cutflow')


def _run_owes_the_checks(monkeypatch):
    # The run owes both checks at a review point (as a claim that rests on selected events would make it).
    from ravel.workflow import review_points
    monkeypatch.setattr(review_points, 'check_classification', lambda run_dir, checks, **_: {
        'epoch': 2, 'derived_points_sha256': '0' * 64,
        'checks': {c: {'applies': True, 'rows': [6, 7], 'points': ['RP7:C1']} for c in checks}})


def _results(store, step_id):
    rows = [r for r in records(store, 'step-validation') if r.get('step_id') == step_id]
    return {r['check_id']: r for r in rows[-1]['report']['results']}


def test_a_comparison_without_event_level_outputs_records_the_checks_not_applicable(run_env, inert_worker, graphs,
                                                                                    monkeypatch):
    _run_owes_the_checks(monkeypatch)
    step = make_step('cmp', kind='compare', role='discrepancy-attributor',
                     outputs=(('outputs/comparison.json', 'comparison'),))
    run_step(run_env, step)
    results = _results(run_env.store, 'cmp')
    for check in CHECKS:
        row = results[check]
        assert row['status'] == 'not_applicable', row
        assert row['classification']['reason'] == 'no_declared_event_level_outputs', row
        assert row['classification']['evidence']['products']['kinds'] == ['comparison']
        assert row['classification']['run_level_point_owed'] is True


def test_a_step_with_an_event_level_output_keeps_the_checks_owed(run_env, inert_worker, graphs, monkeypatch):
    _run_owes_the_checks(monkeypatch)
    step = make_step('cmp', kind='compare', role='discrepancy-attributor',
                     outputs=(('outputs/comparison.json', 'comparison'), ('outputs/cutflow.json', 'cutflow')))
    run_step(run_env, step)
    results = _results(run_env.store, 'cmp')
    assert all(results[check]['status'] == 'inconclusive' for check in CHECKS), results
