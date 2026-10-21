"""Named P13 census obligations at their enforcement boundaries; no scientific jobs."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ravel.workflow import physics_review, review_enforcement, review_projection, role_registry
from ravel.workflow import review_independence as ri, review_dispatch
from test_p13_review_independence import controller, staffed, session  # noqa: F401

CARDS = sorted(role_registry.all_cards(), key=lambda c: c['id'])


@pytest.mark.parametrize('card', CARDS, ids=lambda c: f"ROLE-{c['id']}-independence")
def test_CF10_ROLE_independence_every_card_enforces_its_session_and_actor_requirements(card):
    mine = {'session_id': 'new', 'seat': 'new-seat', 'actor_id': 'reviewer', 'fresh': True}
    others = [{'session_id': 'prior-' + str(i), 'seat': 'prior-' + str(i), 'role': role, 'actor_id': 'producer'}
              for i, role in enumerate(card['independence']['distinct_actor_from'])]
    assert ri.seat_refusal(card, mine, [mine, *others]) is None
    reused = {**mine, 'seat': 'another-attempt'}
    assert ri.seat_refusal(card, mine, [mine, *others, reused]) == 'session_reused'
    if card['independence']['fresh_session']:
        assert ri.seat_refusal(card, {**mine, 'fresh': False}, others) == 'session_not_fresh'
    for prior in others:
        assert ri.seat_refusal(card, {**mine, 'actor_id': prior['actor_id']}, [prior]) == \
            'actor_not_distinct:' + prior['role']


def test_V03_V06_census_includes_another_graph_phase_and_attempt(tmp_path, controller):
    store = controller(tmp_path)
    query = staffed(store, tmp_path)
    assert ri.decide(query)['independent'] is True
    review_dispatch.record_session(store, session('s-reviewer', 'screen-producer', 'producer',
                                                   seat='earlier-graph:phase-1:attempt-4'))
    assert ri.decide(query)['independent'] is False
    assert len(store.scan(review_dispatch.SESSION_KIND)) == 3  # failed credit never deletes its census


def test_V04_withheld_sources_are_screened_for_workspace_and_blind_cards(tmp_path, monkeypatch):
    from ravel.workflow import knowledge_broker
    monkeypatch.setattr(knowledge_broker, 'policy_rows', lambda run: [{'paths': ['hidden/*']}])
    for role in ('ml-trainer', 'ml-reviewer'):
        kept, removed = review_projection.screen_inputs(tmp_path, role, ['inputs/hidden/canary.json',
                                                                       'inputs/features.json'])
        assert kept == ['inputs/features.json']
        assert removed == [{'path': 'inputs/hidden/canary.json', 'class': 'withheld_sources'}]


def test_G04_blocking_review_refuses_stage_before_any_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(physics_review, 'active', lambda *a, **k: True)
    monkeypatch.setattr(physics_review, 'status', lambda *a, **k: {'state': 'awaiting_review'})
    errors = ['unresolved scientific finding']
    monkeypatch.setattr(physics_review, 'gate_errors', lambda *a, **k: list(errors))
    with pytest.raises(ValueError, match='scientific review blocks stage'):
        review_enforcement.before_stage(tmp_path, 'generic', ['inert'], [], [], [], str(tmp_path), 'log')
    errors.clear()
    # Accepted reuse does not take the fresh-launch or overwrite path.
    assert review_enforcement.before_stage(tmp_path, 'generic', ['inert'], [], [], [], str(tmp_path), 'log',
                                           resume=True) is None


def test_G09_observation_session_never_admits_fresh_execution(tmp_path, monkeypatch):
    from ravel.workflow import execution
    observed = []
    monkeypatch.setattr(execution, '_check_validation_session', lambda root, value: observed.append(value))
    monkeypatch.setattr(physics_review, 'active', lambda *a, **k: False)
    token = object()
    with pytest.raises(ValueError, match='observation session is confined'):
        review_enforcement.before_stage(tmp_path, 'generic', ['inert'], [], [], [], str(tmp_path), 'log',
                                        _session=token)
    assert observed == [token]
    assert review_enforcement.before_stage(tmp_path, 'generic', ['inert'], [], [], [], str(tmp_path), 'log',
                                           _session=token, resume=True) is None


def test_D04_delivery_requires_current_registered_review(tmp_path, controller):
    controller(tmp_path)
    assert review_enforcement.delivery_errors(tmp_path)


def test_V09_V10_verbal_agreement_never_supplies_executed_certification():
    from ravel.workflow import review_projection_checks as rpc
    document = {'status': 'passed', 'physics_validated': True, 'summary': 'All checks passed.'}
    outcome = rpc.run_check('check:validation.certify_acceptance', document)
    assert outcome['status'] == 'inconclusive'
    assert outcome['diagnostics']


def test_V07_unchanged_repair_cannot_be_authorized(run):
    from test_physics_review import opened, reject
    root, _ = run
    opened(run)
    reject(root)
    before = deepcopy(physics_review.status(root))
    with pytest.raises(ValueError, match='chang'):
        physics_review.authorize_correction(root, actor_id='physicist', changed_paths=['inputs/settings.cfg'],
                                            stages=['detector'], recheck_checks=['agreement'])
    after = physics_review.status(root)
    assert after['redos_used'] == before['redos_used']
    assert physics_review.gate_errors(root, 'bulk')


# The established inert receipt fixture starts no process; only JSON custody is exercised.
from test_physics_review import run  # noqa: E402, F401


MUST_CHECK_ROWS = (
    'ROLE-assumption-auditor-must_check-0',
    'ROLE-detector-calibrator-must_check-0',
    'ROLE-detector-calibrator-must_check-1',
    'ROLE-detector-calibrator-must_check-2',
    'ROLE-detector-calibrator-must_check-3',
    'ROLE-detector-calibrator-must_check-4',
    'ROLE-detector-calibrator-must_check-5',
    'ROLE-detector-calibrator-must_check-6',
    'ROLE-detector-calibrator-must_check-7',
    'ROLE-discrepancy-attributor-must_check-0',
    'ROLE-extended-scalar-modeler-must_check-0',
    'ROLE-extended-scalar-modeler-must_check-1',
    'ROLE-figure-critic-must_check-0',
    'ROLE-figure-critic-must_check-1',
    'ROLE-figure-critic-must_check-2',
    'ROLE-higgs-combination-reviewer-must_check-1',
    'ROLE-higgs-coupling-analyst-must_check-0',
    'ROLE-literature-scout-must_check-1',
    'ROLE-ml-planner-must_check-0',
    'ROLE-ml-planner-must_check-1',
    'ROLE-ml-planner-must_check-2',
    'ROLE-ml-planner-must_check-3',
    'ROLE-ml-planner-must_check-4',
    'ROLE-ml-planner-must_check-5',
    'ROLE-ml-planner-must_check-6',
    'ROLE-ml-planner-must_check-7',
    'ROLE-ml-planner-must_check-8',
    'ROLE-ml-reviewer-must_check-0',
    'ROLE-ml-reviewer-must_check-1',
    'ROLE-ml-reviewer-must_check-2',
    'ROLE-ml-reviewer-must_check-3',
    'ROLE-ml-reviewer-must_check-4',
    'ROLE-ml-reviewer-must_check-5',
    'ROLE-ml-reviewer-must_check-6',
    'ROLE-ml-reviewer-must_check-7',
    'ROLE-ml-reviewer-must_check-8',
    'ROLE-ml-trainer-must_check-0',
    'ROLE-ml-trainer-must_check-1',
    'ROLE-ml-trainer-must_check-2',
    'ROLE-ml-trainer-must_check-3',
    'ROLE-ml-trainer-must_check-4',
    'ROLE-ml-trainer-must_check-5',
    'ROLE-model-critic-must_check-0',
    'ROLE-model-critic-must_check-1',
    'ROLE-model-critic-must_check-2',
)


@pytest.mark.parametrize('row_id', MUST_CHECK_ROWS, ids=MUST_CHECK_ROWS)
def test_CF12_ROLE_must_check_census_entry_requires_computation_or_a_review_verdict(tmp_path, row_id):
    from ravel.workflow import review_projection_checks as rpc, run_validator_checks as rvc
    role, index = row_id.removeprefix('ROLE-').rsplit('-must_check-', 1)
    card = role_registry.load(role)
    check_id = card['must_check'][int(index)]
    assert rpc.permitted(card, check_id)
    assert rpc.computes(check_id) is (check_id not in rpc.reviewer_items())
    if check_id in rvc.ADAPTERS:
        value = rvc.run(check_id, rvc.RunCheckInput(tmp_path, {}, tmp_path))
    else:
        value = rpc.run_check(check_id, {})
    assert value['status'] in {'inconclusive', 'failed'}, (row_id, check_id, value)
