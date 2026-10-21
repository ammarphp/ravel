"""The scan review declaration binds the ledger's plan whether the ledger projected the scientific plan
(the controller materialises the plan stage before CHECK-IN 1, ahead of the engagement decision) or the
applied view; any other ledger plan is refused."""
from copy import deepcopy

import pytest

from ravel.controller import ledger
from ravel.controller.ledger import gates, state as ledger_state
from ravel.controller.ledger.materialise import plan_context
from p02_support import FakeStore, INTAKE, RUN, fixture_catalogue, row, satisfy, use_catalogue
from test_p18_scan import applied_scan


def _store(monkeypatch, tmp_path, scientific, applied, ledger_plan):
    import json
    rows = [row('X-POINT', 'route.analysis.scan', 'plan', 'point'),
            row('X-REVIEW', 'review.credit', 'review', 'seat', cls='R')]
    installed = ledger.load_catalogue().rows
    declared = set(applied.get('obligations', []))
    for step in applied['steps']:
        declared.update(step.get('obligations', []))
    rows.extend(json.loads(json.dumps(installed[rid], default=dict)) for rid in sorted(declared))
    use_catalogue(monkeypatch, fixture_catalogue(rows))
    store = FakeStore(RUN, root=tmp_path)
    ledger.materialise(store, 'intake', {**INTAKE, 'deliverables': []})
    store.append('plan', {'plan': scientific, 'plan_sha256': scientific['sha256'], 'applied_plan': applied,
                          'applied_sha256': applied['engagement']['applied_sha256']})
    ledger.materialise(store, 'plan', {'plan': ledger_plan})
    satisfy(store, ledger.materialise(store, 'review', {'step': 'plan_review', 'seat': 'plan-critic', 'attempt': 1}))
    return store


@pytest.mark.parametrize('projected', ['scientific', 'applied'])
def test_the_scan_review_population_binds_either_projection_of_the_plan(monkeypatch, tmp_path, projected):
    scientific, applied, _ = applied_scan(monkeypatch, expanded=True, tier='full')
    store = _store(monkeypatch, tmp_path, scientific, applied, scientific if projected == 'scientific' else applied)
    state = ledger_state.load(store, full=True)
    assert plan_context({'plan': applied}, state) != plan_context({'plan': scientific}, state), \
        'the engagement view must change the projection for this control to bite'
    populations = gates._scan_review_populations(store, state)
    declared = applied['engagement']['seat_plan']['scan_review']['steps']
    assert set(populations) == set(declared)


def test_a_ledger_plan_of_another_plan_is_refused(monkeypatch, tmp_path):
    scientific, applied, _ = applied_scan(monkeypatch, expanded=True, tier='full')
    other = deepcopy(scientific)
    dropped = [s['id'] for s in other['steps'] if s['id'].startswith('scan.point.')][-1]
    other['steps'] = [s for s in other['steps'] if s['id'] != dropped]
    for step in other['steps']:
        step['depends_on'] = [d for d in step.get('depends_on') or () if d != dropped]
    store = _store(monkeypatch, tmp_path, scientific, applied, other)
    with pytest.raises(ValueError, match='not the current applied plan'):
        gates._scan_review_populations(store, ledger_state.load(store, full=True))
