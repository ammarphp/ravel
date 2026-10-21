"""Ordinary research children retain source intake and immutable gate custody.

All records are fictional. These controls exercise the real contract reader and
custody journal; they replace neither decision authority nor scientific gates.
"""
import json
from pathlib import Path

import pytest

from ravel.workflow import research_cycle as cycle, review_points, rdj_custody, task_completion, science
from test_langgraph_research_orchestration import parent
from test_research_cycle import write, contract, propose, experiment, specification
from method_decision_fixture import admit_method


def bound_child(tmp_path, epoch=2):
    if epoch == 2:
        from test_research_full_cycle_authority import intake
        original, _ = intake(tmp_path)
    else:
        original, _ = parent(tmp_path)
    root = tmp_path / 'parent'
    original['agent_layer_epoch'] = epoch
    pin = write(root / 'inputs/task_contract.json', original)
    if epoch != 2:
        rdj_custody.record_input_snapshot(root, 'run_init')
    binding = {'contract': pin, 'assignment_id': 'original-task'}
    state = {'base_dir': str(tmp_path), 'contract': {'goal_binding': binding}, 'premises': [],
             'parent_task': task_completion.binding_projection(binding, base_dir=tmp_path)}
    rd = tmp_path / 'child'
    (rd / 'inputs').mkdir(parents=True)
    e = {'id': 'fictional', 'rundir': str(rd)}
    e['task_contract'] = cycle._experiment_contract(state, e, rd, materialize=True)
    rdj_custody.record_input_snapshot(rd, 'run_init')
    return state, e, rd, original


@pytest.mark.parametrize('epoch', [1, 2])
def test_child_materializes_original_goal_and_epoch_before_approval(tmp_path, epoch):
    state, e, rd, original = bound_child(tmp_path, epoch)
    child = json.loads((rd / 'inputs/task_contract.json').read_text())
    assert child['prompt'] == original['prompt']
    assert child['task_requirements'] == original['task_requirements']
    assert child['agent_layer_epoch'] == epoch
    assert child['goal_binding'] == state['contract']['goal_binding']
    assert review_points._facts(rd)['agent_layer_epoch'] == epoch
    assert cycle._experiment_contract(state, e, rd) == e['task_contract']
    assert not (rd / 'inputs/checkin1_approval.json').exists()
    assert rdj_custody.snapshot_digest(rd, 'inputs/task_contract.json', event='run_init') == e['task_contract']['sha256']


@pytest.mark.parametrize('damage', ['missing', 'forged', 'stale_plan'])
def test_child_missing_forged_or_stale_contract_refuses(tmp_path, damage):
    state, e, rd, _ = bound_child(tmp_path)
    path = rd / 'inputs/task_contract.json'
    if damage == 'missing':
        path.unlink()
    elif damage == 'forged':
        doc = json.loads(path.read_text())
        doc['agent_layer_epoch'] = 1
        write(path, doc)
    else:
        write(rd / 'inputs/request_plan.json', {'nodes': [{'id': 'forgery'}]})
    with pytest.raises((ValueError, OSError)):
        cycle._experiment_contract(state, e, rd)
    assert not (rd / 'inputs/checkin1_approval.json').exists()


def test_even_repinning_a_forged_child_cannot_replace_original_goal(tmp_path):
    state, e, rd, _ = bound_child(tmp_path)
    path = rd / 'inputs/task_contract.json'
    doc = json.loads(path.read_text())
    doc['prompt'] = 'Substituted scientific question.'
    e['task_contract'] = write(path, doc)
    with pytest.raises(ValueError, match='original research goal'):
        cycle._experiment_contract(state, e, rd)


def test_parent_contract_custody_survives_repinning(tmp_path):
    state, e, rd, _ = bound_child(tmp_path)
    pin = state['contract']['goal_binding']['contract']
    doc = json.loads(Path(pin['path']).read_text())
    doc['assumptions'] = [*doc['assumptions'], 'Forged original-source assumption.']
    state['contract']['goal_binding']['contract'] = write(Path(pin['path']), doc)
    state['parent_task'] = task_completion.binding_projection(state['contract']['goal_binding'], base_dir=tmp_path)
    with pytest.raises(ValueError, match='run_init snapshot'):
        cycle._experiment_contract(state, e, rd)


def test_new_unbound_child_requires_explicit_legacy_harness(tmp_path):
    rd = tmp_path / 'child'
    (rd / 'inputs').mkdir(parents=True)
    state = {'base_dir': str(tmp_path), 'contract': {'question': 'Fictional arithmetic?'}}
    e = {'rundir': str(rd)}
    with pytest.raises(ValueError, match='original goal or an explicit unbound synthetic campaign'):
        cycle._experiment_contract(state, e, rd, materialize=True)
    state['protocol_exemption'] = 'evaluation_harness'
    e['task_contract'] = cycle._experiment_contract(state, e, rd, materialize=True)
    rdj_custody.record_input_snapshot(rd, 'run_init')
    assert review_points._facts(rd) == {'agent_layer_epoch': 1}
    cycle._experiment_contract(state, e, rd)


def test_existing_unbound_native_or_legacy_records_keep_existing_contract_rules(tmp_path):
    state = {'base_dir': str(tmp_path), 'contract': {'question': 'Existing contract.'}}
    rd = tmp_path / 'existing'
    assert cycle._experiment_contract(state, {'rundir': str(rd)}, rd) is None


def prepared_harness(tmp_path):
    root, rd = tmp_path / 'cycle', tmp_path / 'run'
    cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True)
    propose(tmp_path, root)
    cycle.design(root, experiment(tmp_path, 'paired', grouped=True))
    cycle.prepare_experiment(root, 'paired', rd)
    return root, rd


def test_actual_preparation_joins_science_verification_and_approval_pins(tmp_path):
    root, rd = prepared_harness(tmp_path)
    science.verify_plan(rd)
    paths = cycle.verify_experiment_contract(rd)
    assert str(rd / 'inputs/task_contract.json') in paths
    assert str(rd / cycle.CHILD_CONTRACT_ORIGIN) in paths
    assert set(paths) <= set(science.approval_input_paths(rd))
    assert cycle._load(root)[1]['experiments'][0]['task_contract'] == cycle._pin(rd / 'inputs/task_contract.json')
    assert not (rd / science.APPROVAL).exists()


@pytest.mark.parametrize('damage', ['missing', 'forged'])
def test_contracted_study_keeps_rung_refusal_without_authenticated_campaign_origin(tmp_path, damage):
    import sys
    from ravel.workflow import stage_supervisor
    root, rd = prepared_harness(tmp_path)
    admit_method(rd)
    science.approve(rd, 'Execute the exact fictional supplied arithmetic.', scripted=True)
    assert stage_supervisor._research_child_study(rd)
    origin = rd / cycle.CHILD_CONTRACT_ORIGIN
    if damage == 'missing':
        origin.unlink()
        assert not stage_supervisor._research_child_study(rd)
        refusal = 'explicit compute rung'
    else:
        write(origin, {'root': str(tmp_path / 'foreign'), 'experiment_id': 'paired'})
        with pytest.raises((ValueError, OSError)):
            stage_supervisor._research_child_study(rd)
        refusal = None
    with pytest.raises((ValueError, OSError), match=refusal):
        stage_supervisor.supervise('science', rd, 0, 'logs/science.log', cmd=[sys.executable, '-c', 'pass'])
    assert not (rd / 'logs/science.log').exists()
    assert not (rd / 'logs/execution/science').exists()


def test_frozen_child_validation_reuses_its_original_final_observation(tmp_path):
    _, rd = prepared_harness(tmp_path)
    session = science.execution._validation_session(rd)
    try:
        expected = science._research_contract_paths(rd, session)
        original = tuple(session.final_checks)
        assert len(original) == 1
        assert science._research_contract_paths(rd, session) == expected
        assert tuple(session.final_checks) == original
        session.readonly_freeze()
        assert science._research_contract_paths(rd, session) == expected
        assert tuple(session.final_checks) == original
        session.readonly_drain()
        session.readonly_terminal()
    finally:
        session.close()


@pytest.mark.parametrize('damage', ['missing', 'stale', 'forged'])
def test_frozen_child_boundary_still_rechecks_current_custody(tmp_path, damage):
    _, rd = prepared_harness(tmp_path)
    session = science.execution._validation_session(rd)
    try:
        science._research_contract_paths(rd, session)
        original = tuple(session.final_checks)
        session.readonly_freeze()
        origin = rd/cycle.CHILD_CONTRACT_ORIGIN
        if damage == 'missing': origin.unlink()
        elif damage == 'stale': origin.write_bytes(origin.read_bytes() + b'\n')
        else: write(origin, {'root': str(tmp_path/'foreign'), 'experiment_id': 'paired'})
        with pytest.raises((ValueError, OSError)):
            science._research_contract_paths(rd, session)
        assert tuple(session.final_checks) == original
        with pytest.raises((ValueError, OSError)):
            session.readonly_drain()
    finally:
        session.close()


def test_frozen_session_cannot_register_a_first_child_authority_observation(tmp_path):
    _, rd = prepared_harness(tmp_path)
    session = science.execution._validation_session(rd)
    try:
        session.readonly_freeze()
        with pytest.raises(ValueError, match='live callable final observation'):
            science._research_contract_paths(rd, session)
        assert session.final_checks == []
    finally:
        session.close()


def test_child_methodology_provider_uses_only_its_authenticated_campaign(tmp_path):
    from ravel.workflow import research_protocol as protocol
    root, rd = prepared_harness(tmp_path)
    protocol.bind_default(root)
    action = {'kind': 'screening_choice', 'scope': 'ideas'}
    expected = protocol.gate_errors(root, 'research_choice', action)
    assert expected and any('limitation_census' in error.message for error in expected)
    assert protocol.gate_errors(rd, 'research_choice', action) == expected
    assert not (rd / 'research/binding.json').exists()


@pytest.mark.parametrize('damage', ['missing', 'forged', 'stale', 'copied'])
def test_child_methodology_provider_refuses_untrusted_campaign_origin(tmp_path, damage):
    from ravel.workflow import research_protocol as protocol
    root, rd = prepared_harness(tmp_path)
    protocol.bind_default(root)
    origin = rd / cycle.CHILD_CONTRACT_ORIGIN
    if damage == 'missing':
        origin.unlink()
    elif damage == 'forged':
        write(origin, {'root': str(tmp_path / 'foreign'), 'experiment_id': 'paired'})
    elif damage == 'stale':
        origin.write_bytes(origin.read_bytes() + b'\n')
    else:
        import shutil
        copied = tmp_path / 'copied-child'
        shutil.copytree(rd, copied)
        rd = copied
    errors = protocol.gate_errors(rd, 'research_choice', {'kind': 'screening_choice', 'scope': 'limitation_census'})
    assert errors and all(error.code == 'research_protocol_pending' for error in errors)
    assert not any(error.message == 'bound research protocol missing or unreadable' for error in errors)


def prepared_epoch_two_review_child(tmp_path):
    from test_research_full_cycle_child_plan import planned
    source, _, _, _, _, _ = planned(tmp_path, 'literal-calculation')
    binding = source['contract']['goal_binding']
    rdj_custody.record_input_snapshot(Path(binding['contract']['path']).parent.parent, 'run_init')
    definition = contract(tmp_path)
    definition['goal_binding'] = binding
    root = tmp_path/'review-campaign'
    cycle.create(root, definition, base_dir=tmp_path, evaluation_harness=True)
    propose(tmp_path, root)
    e = experiment(tmp_path, 'paired', grouped=True)
    spec = json.loads(Path(e['study']['path']).read_text())
    spec['goal_binding'] = binding
    e['study'] = write(Path(e['study']['path']), spec)
    cycle.design(root, e)
    rd = tmp_path/'review-child'
    cycle.prepare_experiment(root, 'paired', rd)
    admit_method(rd)
    science.approve(rd, 'Inert routing control; no execution or acceptance.', scripted=True)
    return root, rd


def test_authenticated_epoch_two_child_enters_existing_scientific_role_cascade(tmp_path, monkeypatch):
    from ravel.workflow import research_orchestrator as orchestrator
    from ravel.workflow.graphs import review as review_graph
    _, rd = prepared_epoch_two_review_child(tmp_path)
    assert review_graph.delegates(rd) is True
    entered = []
    class CascadeReached(Exception): pass
    def session(out, request):
        entered.append(request)
        raise CascadeReached()
    # Stop at the existing cascade's request boundary; no review or model
    # response is fabricated, and intake/approval verification stays real.
    monkeypatch.setattr(orchestrator, '_session', session)
    class Host:
        identity = {'fixture': 'Routing observation only; no worker calls.'}
    with pytest.raises(CascadeReached):
        orchestrator.review(rd, tmp_path/'review', host=Host(), model='control', reasoning_effort='high',
            max_output_tokens=128, max_wall_seconds=10, claim_scope='supplied_math_diagnostic')
    assert entered[0]['kind'] == 'review' and entered[0]['rundir'] == str(rd)
    assert not (rd/'logs/physics_review/registration.json').exists()


def test_generic_epoch_two_review_still_delegates(tmp_path, monkeypatch):
    from ravel.workflow import research_orchestrator as orchestrator
    from ravel.workflow.graphs import review as review_graph
    _, _, rd, _ = bound_child(tmp_path, 2)
    result = {'phase': 'routing_observation', 'execution_authorized': False}
    seen = []
    def generic(root, scope):
        seen.append((root, scope))
        return result
    monkeypatch.setattr(review_graph, 'orchestrated', generic)
    assert orchestrator.review(rd, tmp_path/'review', host=None, model='control', reasoning_effort='high',
        max_output_tokens=128, max_wall_seconds=10, claim_scope='diagnostic') == result
    assert seen == [(rd, 'diagnostic')]


@pytest.mark.parametrize('damage', ['missing', 'forged', 'stale', 'missing_contract'])
def test_scientific_review_cannot_use_an_untrusted_claimed_child_route(tmp_path, monkeypatch, damage):
    from ravel.workflow import research_orchestrator as orchestrator
    _, rd = prepared_epoch_two_review_child(tmp_path)
    origin = rd/cycle.CHILD_CONTRACT_ORIGIN
    if damage == 'missing': origin.unlink()
    elif damage == 'forged': write(origin, {'root': str(tmp_path/'foreign'), 'experiment_id': 'paired'})
    elif damage == 'stale': origin.write_bytes(origin.read_bytes() + b'\n')
    else: (rd/'inputs/task_contract.json').unlink()
    monkeypatch.setattr(orchestrator, '_session', lambda *a, **k: pytest.fail('untrusted child reached role cascade'))
    with pytest.raises((ValueError, OSError)):
        orchestrator.review(rd, tmp_path/'review', host=None, model='control', reasoning_effort='high',
            max_output_tokens=128, max_wall_seconds=10, claim_scope='supplied_math_diagnostic')


@pytest.mark.parametrize('epoch', [1, 2])
def test_campaign_create_materializes_and_rechecks_original_intake(tmp_path, epoch):
    source, _, _, original = bound_child(tmp_path, epoch)
    request = contract(tmp_path)
    request['goal_binding'] = source['contract']['goal_binding']
    root = tmp_path / 'campaign'
    created = cycle.create(root, request, base_dir=tmp_path, evaluation_harness=True)
    assert created['intake_contract'] == cycle._pin(root / 'inputs/task_contract.json')
    assert review_points._facts(root)['agent_layer_epoch'] == epoch
    assert json.loads((root / 'inputs/task_contract.json').read_text())['prompt'] == original['prompt']
    cycle._load(root)
    (root / 'inputs/task_contract.json').unlink()
    with pytest.raises((ValueError, OSError)):
        cycle._load(root)


def test_campaign_missing_committed_intake_pin_cannot_adopt_current_files(tmp_path):
    source, _, _, _ = bound_child(tmp_path, 1)
    request = contract(tmp_path)
    request['goal_binding'] = source['contract']['goal_binding']
    root = tmp_path / 'campaign'
    state = cycle.create(root, request, base_dir=tmp_path, evaluation_harness=True)
    # Even extant bytes with genuine run_init custody cannot replace the
    # campaign's missing original immutable admission join.
    state.pop('intake_contract')
    cycle._commit(root, state, 'fixture_missing_original_intake_pin')
    with pytest.raises(ValueError, match='original committed intake contract'):
        cycle._load(root)


@pytest.mark.parametrize('damage', ['missing', 'both_missing', 'forged', 'origin'])
def test_ordinary_approval_refuses_damaged_child_envelope(tmp_path, damage):
    _, rd = prepared_harness(tmp_path)
    admit_method(rd)
    if damage == 'missing':
        (rd / 'inputs/task_contract.json').unlink()
    elif damage == 'both_missing':
        (rd / 'inputs/task_contract.json').unlink()
        (rd / cycle.CHILD_CONTRACT_ORIGIN).unlink()
    elif damage == 'forged':
        write(rd / 'inputs/task_contract.json', {'agent_layer_epoch': 1, 'prompt': 'Replacement.'})
    else:
        write(rd / cycle.CHILD_CONTRACT_ORIGIN, {'root': str(tmp_path / 'other'), 'experiment_id': 'paired'})
    with pytest.raises((ValueError, OSError)):
        science.approve(rd, 'Fictional arithmetic control.', scripted=True)
    assert not (rd / science.APPROVAL).exists()


def test_postapproval_new_task_envelope_cannot_enter_worker_plane(tmp_path, monkeypatch):
    rd = tmp_path / 'ordinary'
    spec = specification(tmp_path, 'supplied', grouped=True)
    science.plan(rd, spec['path'])
    admit_method(rd)
    science.approve(rd, 'Fictional ordinary arithmetic control.', scripted=True)
    write(rd / 'inputs/task_contract.json', {'agent_layer_epoch': 1, 'prompt': 'Injected after approval.'})
    # Registration waiting is a transport boundary; the actual worker authority
    # and immutable science-plan verification below remain in production.
    monkeypatch.setattr(science, '_await_worker_registration', lambda *a, **k: None)
    with pytest.raises(ValueError, match='immutable envelope changed'):
        science.verify_worker(rd)
