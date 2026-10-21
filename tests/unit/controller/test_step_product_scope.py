"""A physical check a step's own declared products cannot carry is not that producer's to discharge.

The operation check policy disposes the check for the step (all its declared products are non-physical); a run-level
review point that still owes the check stays owed to its specialist reviewer and is recorded beside the disposition.
A check the step's products can carry still runs.
"""
from ravel.controller.step import graph
from ravel.workflow import operation_check_policy as policy, review_points
from test_p04_support import FakeStore

STEP = {'id': 'decision', 'kind': 'author', 'operation': None,
        'outputs': [{'path': 'outputs/public-record.json', 'kind': 'document', 'required': True}]}
CARD = {'id': 'analysis-author'}


def _run_level(monkeypatch, applies):
    monkeypatch.setattr(review_points, 'check_classification', lambda run_dir, checks, **_: {'checks': {
        c: {'applies': applies, 'rows': [6, 7], 'points': ['RP7:C2'] if applies else []} for c in checks}})


def test_a_documents_only_step_records_its_own_scope_and_leaves_the_run_point_owed(tmp_path, monkeypatch):
    _run_level(monkeypatch, True)
    store = FakeStore(tmp_path / 'store')
    own = policy.dispositions(STEP, sorted(policy.CHECKS))
    assert own and all(row['applies'] is False for row in own.values())
    exempt = graph._scope_dispositions(store, tmp_path, CARD, STEP, own, {})
    assert set(exempt) == set(policy.CHECKS)
    cited = exempt[policy.CUTFLOW]
    assert cited['reason'] == 'no_declared_physical_outputs' and cited['evidence'] and cited['run_level_point_owed']
    [record] = [r for r in graph.records(store, graph.CLASSIFICATION) if r.get('kind') == 'step-product-scope']
    assert record['step_id'] == 'decision' and record['run_level'][policy.CUTFLOW]['points'] == ['RP7:C2']
    # The run-level classification itself is unchanged: the point stays owed at review.
    assert review_points.check_classification(tmp_path, [policy.CUTFLOW])['checks'][policy.CUTFLOW]['applies']


def test_a_step_whose_products_can_carry_the_check_still_owes_it(tmp_path, monkeypatch):
    _run_level(monkeypatch, True)
    store = FakeStore(tmp_path / 'store')
    physical = {**STEP, 'outputs': [{'path': 'outputs/cutflow.json', 'kind': 'table', 'required': True}]}
    own = policy.dispositions(physical, sorted(policy.CHECKS))
    assert graph._scope_dispositions(store, tmp_path, CARD, physical, own, {}) == {}
    assert not graph.records(store, graph.CLASSIFICATION)


def test_a_check_the_policy_already_exempts_keeps_its_citation(tmp_path, monkeypatch):
    _run_level(monkeypatch, False)
    store = FakeStore(tmp_path / 'store')
    own = policy.dispositions(STEP, sorted(policy.CHECKS))
    prior = {c: {'record': 'review-classification-1', 'applies': False, 'reason': 'r', 'evidence': {'e': 1}}
             for c in policy.CHECKS}
    assert graph._scope_dispositions(store, tmp_path, CARD, STEP, own, prior) == prior


def test_a_comparison_step_records_cutflow_and_acceptance_not_applicable(tmp_path, monkeypatch):
    _run_level(monkeypatch, True)
    store = FakeStore(tmp_path / 'store')
    compare = {**STEP, 'id': 'compare', 'kind': 'compare',
               'outputs': [{'path': 'outputs/comparison.json', 'kind': 'comparison', 'required': True}]}
    own = policy.dispositions(compare, sorted(policy.CHECKS | policy.EVENT_CHECKS))
    exempt = graph._scope_dispositions(store, tmp_path, CARD, compare, own, {})
    assert set(exempt) == set(policy.EVENT_CHECKS)
    assert exempt[policy.ACCEPTANCE]['reason'] == 'no_declared_event_level_outputs'
    assert exempt[policy.ACCEPTANCE]['run_level_point_owed'] is True
