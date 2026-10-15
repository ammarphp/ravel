"""Synthetic controls for fact-derived review obligations; no model or native calls."""
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path

import pytest


def module():
    return importlib.import_module('ravel.workflow.review_points')


def facts(**changes):
    value = {'agent_layer_epoch': 2, 'delegated': True, 'nodes': [], 'claims': [], 'edges': []}
    value.update(changes)
    return value


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def run(tmp_path, **changes):
    value = facts(**changes)
    pin = write(tmp_path / 'inputs/plan.json', value)
    write(tmp_path / 'inputs/task_contract.json', {'agent_layer_epoch': 2, 'delegated': value['delegated'], 'request_plan': pin})
    return value


def receipt(root, point, role, number=1, *, register=True, verified_label='transport_attested', **changes):
    from ravel.workflow import rdj_custody
    rp = module()
    f = rp._facts(root)
    p = next(p for p in rp.derive(f) if p['id'] == point)
    plan = f['plan']
    subject = (next(c for c in plan['claims'] if c['id'] == p['claim_id']) if p.get('claim_id') else
               next(n for n in plan['nodes'] if n['id'] == p['node_id']) if p.get('node_id') else plan)
    digest = hashlib.sha256(json.dumps({'point_id': point, 'subject': subject}, sort_keys=True,
                                     separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    final_path = root/'agent-work'/(role+str(number))/'1/final.json'
    final = ({'sha256': hashlib.sha256(final_path.read_bytes()).hexdigest()} if final_path.exists()
             else write(final_path, {'findings': []}))
    value = {'schema_version': 2, 'kind': 'agent-worker-receipt', 'node_id': role + str(number),
             'attempt': 1, 'review_point_id': point, 'role': {'id': role}, 'status': 'ok',
             'execution_mode': 'transport_attested_cli', 'review_subject': {'scope': rp.subject_scope(p), 'sha256': digest},
             'attestation': 'transport_attested', 'session_id': role + str(number), 'actor_id': role + str(number),
             'run_tree': {'modified': False}, 'final_record': {'valid': True, 'path': 'final.json', 'sha256': final['sha256']}, 'model': {'family': role}}
    # The dispatcher's part: it assigns the actor of this worker session at spawn and registers it.
    # A test that passes its own ``actor_id`` models a worker that declares one.
    declared = 'actor_id' in changes
    worker_session = changes.pop('worker_session', None)
    value.update(changes)
    actor = rdj_custody.actor_record('synthetic-cli', 'synthetic-model', worker_session or 'ws-' + value['node_id'],
                                     value['node_id'] + '/1', family=value['model'].get('family'))
    if not declared:
        value['actor_id'] = actor['actor_id']
    path = root / 'agent-work' / value['node_id'] / '1/receipt.json'
    write(path, value)
    if register:
        rdj_custody.register_worker_receipt(root, path.relative_to(root).as_posix(), verified_label=verified_label,
                                            **({} if declared else {'actor': actor}))
    return value


def credit_pending(root, gate='checkin2_accept'):
    """Credit every blocking review point of ``gate`` as the dispatcher does: one registered,
    transport-attested receipt per missing role seat, each from its own worker session and actor."""
    rp = module()
    seats = [(p['id'], role['role']) for p in rp.pending(root) if p['blocking'] and p['gate'] == gate
             for role in p['roles'] for _ in range(role['count'])]
    for number, (point_id, role) in enumerate(seats, 1):
        receipt(root, point_id, role, 9000 + number)
    return seats


def test_compute_and_authored_plan_requires_plan_critic():
    rp = module()
    points = rp.derive(facts(nodes=[{'id': 'N1', 'operation': 'literal-calculation', 'rung': 'smoke'}]))
    assert any(p['row'] == 1 and p['blocking'] and p['gate'] == 'approve_plan' for p in points)
    assert rp.derive({'agent_layer_epoch': 1, 'nodes': [{'id': 'N1', 'authored': {}}]}) == []


def test_smoke_claim_and_computed_basis_cannot_be_hidden_by_kind():
    rp = module()
    claim = {'id': 'C1', 'kind': 'agreement', 'inherits': ['N1']}
    plan = facts(nodes=[{'id': 'N1', 'operation': 'columnar-analysis', 'rung': 'smoke', 'fields': [{'pointer': '/selection_origin', 'value': 'reimplemented'}]}], claims=[claim])
    points = rp.derive(plan)
    assert {4, 5, 7} <= {p['row'] for p in points}
    assert any(p.get('requires_certificate') for p in points)


@pytest.mark.parametrize('mutation', ['shared', 'nested', 'escape', 'concatenate', 'llm_merge', 'unpinned', 'no_baseline', 'no_receipts'])
def test_unsafe_parallel_work_refused(mutation):
    rp = module()
    fan = {'workers': [{'id': 'a', 'write_set': ['stages/a'], 'inputs': [{'path': 'input', 'sha256': 'a'*64}], 'receipt_id': 'a'},
                       {'id': 'b', 'write_set': ['stages/b'], 'inputs': [{'path': 'input', 'sha256': 'a'*64}], 'receipt_id': 'b'}],
           'join': {'kind': 'computed_comparison'}, 'budget_cap': 100, 'single_worker': {'kind': 'estimate', 'budget_cap': 100}}
    if mutation == 'shared': fan['workers'][1]['write_set'] = ['stages/a']
    if mutation == 'nested': fan['workers'][1]['write_set'] = ['stages/a/sub']
    if mutation == 'escape': fan['workers'][1]['write_set'] = ['stages/b/../a']
    if mutation in {'concatenate', 'llm_merge'}: fan['join']['kind'] = mutation
    if mutation == 'unpinned': fan['workers'][0]['inputs'][0].pop('sha256')
    if mutation == 'no_baseline': fan.pop('single_worker')
    if mutation == 'no_receipts': fan['workers'][1]['receipt_id'] = 'a'
    with pytest.raises(ValueError): rp.derive(facts(nodes=[{'id': 'N1', 'fan_out': fan}]))


def test_resume_only_missing_roles_stable_parallel_groups(tmp_path):
    rp = module()
    run(tmp_path, claims=[{'id': 'C1', 'kind': 'agreement'}])
    points = rp.pending(tmp_path)
    critic = next(p for p in points if p['row'] == 4 and p['roles'][0]['role'] == 'physics-critic')
    receipt(tmp_path, critic['id'], 'physics-critic')
    pending = rp.pending(tmp_path)
    assert critic['id'] not in [p['id'] for p in pending]
    assert pending == rp.pending(tmp_path)
    assert any(p['parallel_group'] == critic['parallel_group'] for p in pending)
    assert all(p['parallel_group'] is None for p in pending if p['roles'][0]['role'] in {'skeptical-verifier', 'physics-decider'})


def test_same_session_and_relay_do_not_satisfy_independence(tmp_path):
    rp = module()
    run(tmp_path, claims=[{'id': 'C1', 'kind': 'prediction'}])
    point = next(p for p in rp.pending(tmp_path) if p['row'] == 4)
    receipt(tmp_path, point['id'], point['roles'][0]['role'], attestation='host_attested_external', verified_label=None)
    assert not rp.satisfied(tmp_path, point['id'])
    assert rp.attestation_label({'execution_mode': 'host_attested_external'}) == 'self_attested'
    assert rp.attestation_label({'execution_mode': 'transport_attested_cli'}) == 'self_attested'


def test_calibration_and_observed_rows(tmp_path):
    rp = module()
    run(tmp_path, nodes=[{'id': 'N1', 'operation': 'search-statistics', 'observed_statistic': True,
                          'parameter_provenance': [{'choice': 'scale', 'basis': 'agreement_with_observed'}]}])
    points = rp.derive(rp._facts(tmp_path))
    assert any(p.get('rdj_class') == 'R2' and p.get('decision_class') == 'calibration' for p in points)
    assert any(p.get('rdj_class') == 'R3' and p.get('human_approval') for p in points)
    assert rp.checkin3_section(tmp_path)['calibration_choices']


def test_exported_plan_population_derives_without_identity_dispatch():
    from request_plan_corpus import CASES, catalogue
    from ravel.workflow.request_plan import draft
    rp = module()
    for builder in CASES.values():
        case = builder()
        plan = draft(case.doc, case.contract(), catalogue=catalogue)
        value = facts(plan=plan)
        # Existing compute fan-outs are sequential native partitions, not worker maps.
        first = rp.derive(value)
        assert first == rp.derive(deepcopy(value))
        assert {c['id'] for c in plan['claims']} <= {p.get('claim_id') for p in first}


def test_opinion_only_finding_does_not_hold_gate(tmp_path):
    rp = module()
    assert not rp.blocking_finding(tmp_path, {'severity': 'A', 'message': 'Prefer another method'})
    assert not rp.blocking_finding(tmp_path, {'severity': 'A', 'code_check': {'id': 'check:closure', 'status': 'failed'}})
    assert not rp.blocking_finding(tmp_path, {'severity': 'A', 'code_check': {'id': 'check:closure', 'status': 'passed'}})
    assert rp.blocking_finding(tmp_path, {'severity': 'A', 'evidence_request': {'id': 'E1', 'kind': 'measurement', 'status': 'pending'}})


def test_human_manual_review_is_distinct_from_transport_review(tmp_path):
    rp = module(); run(tmp_path, delegated=False, claims=[{'id': 'C1', 'kind': 'prediction'}])
    value = rp.deliver(tmp_path, {'verdict': 'accept', 'human_approver': {'id': 'operator', 'approval_id': 'approval:1'}})
    assert value['attestation'] == 'human_manual'
    run(tmp_path, delegated=True, claims=[{'id': 'C1', 'kind': 'prediction'}])
    with pytest.raises(ValueError): rp.deliver(tmp_path, {'verdict': 'accept'})


def test_same_session_cannot_fill_three_votes(tmp_path):
    rp = module(); run(tmp_path, claims=[{'id': 'C1', 'kind': 'prediction'}])
    points = [p for p in rp.pending(tmp_path) if p['row'] == 4]
    for p in points: receipt(tmp_path, p['id'], p['roles'][0]['role'], session_id='same')
    assert len([p for p in rp.pending(tmp_path) if p['row'] == 4]) == 2


def test_unknown_host_or_missing_role_capability_is_named(tmp_path):
    rp = module(); run(tmp_path, nodes=[{'id': 'N1', 'operation': 'literal-calculation'}])
    errors = rp.gate_errors(tmp_path, 'approve_plan', {'digest': 'a'*64})
    assert any(e.code == 'review_transport_missing' and e.pins for e in errors)


def test_parallel_safe_fanout_is_not_mutated():
    rp = module()
    node = {'id': 'N1', 'fan_out': {'workers': [
        {'id': name, 'write_set': ['stages/'+name], 'inputs': [{'path': 'input', 'sha256': 'a'*64}], 'receipt_id': name}
        for name in ['a', 'b']], 'join': {'kind': 'computed_comparison'}, 'budget_cap': 64,
        'single_worker': {'kind': 'estimate', 'budget_cap': 64}}}
    before = deepcopy(node)
    assert rp.parallel_safety(node)['safe']
    assert node == before


def test_unregistered_epoch_two_judgment_uses_plan_points(tmp_path):
    from ravel.workflow.scientific_judgment import next_step
    run(tmp_path, nodes=[{'id': 'N1', 'operation': 'literal-calculation'}])
    result = next_step(tmp_path)
    assert result['phase'] == 'review_points' and result['review_points']
    assert result['execution_authorized'] is False


def test_verifier_waits_for_entire_first_pass(tmp_path):
    rp = module(); run(tmp_path, claims=[{'id': 'C1', 'kind': 'agreement'}])
    points = rp.pending(tmp_path)
    verifier = next(p for p in points if p['row'] == 4 and p['roles'][0]['role'] == 'skeptical-verifier')
    assert verifier['ready'] is False
    for p in points:
        if p['parallel_group'] == 'ci2:C1:first-pass': receipt(tmp_path, p['id'], p['roles'][0]['role'])
    assert next(p for p in rp.pending(tmp_path) if p['id'] == verifier['id'])['ready'] is True


@pytest.mark.parametrize('operation', ['search-statistics', 'prescribed-statistic'])
def test_typed_plan_fields_trigger_calibration_and_unblind(operation):
    rp = module()
    plan = facts(nodes=[{'id': 'N1', 'operation': operation, 'fields': [
        {'pointer': '/task/level', 'value': 'observed'},
        {'pointer': '/task/parameter_provenance', 'value': [{'choice': 'selection', 'basis': 'agreement_with_observed', 'non_overlap': {'regions': ['validation', 'inference']}}]}]}])
    assert {16, 17} <= {p['row'] for p in rp.derive(plan)}


def test_typed_rdj_evidence_request_missing_item_still_blocks(tmp_path):
    rp = module()
    assert rp.blocking_finding(tmp_path, {'severity': 'A', 'evidence_request': {'id': 'E1', 'kind': 'evidence', 'status': 'pending'}})


def test_generic_epoch_two_cycle_requires_retained_stage_receipts(tmp_path, monkeypatch):
    from ravel.workflow import scientific_judgment as judgment
    run(tmp_path, nodes=[{'id': 'N1', 'operation': 'literal-calculation'}])
    with pytest.raises(ValueError, match='stage receipts'):
        judgment.open_cycle(tmp_path, check_results='checks.json')
    calls = []
    monkeypatch.setattr(judgment.review, 'open_cycle', lambda root, **kw: calls.append(kw) or {'accepted_input': True})
    assert judgment.open_cycle(tmp_path, check_results='checks.json', stage_receipts=['stage-receipt.json']) == {'accepted_input': True}
    assert calls[0]['stage_receipts'] == ['stage-receipt.json']


@pytest.mark.parametrize('joined', [False, True])
def test_legacy_review_accept_cannot_bypass_epoch_two_receipts(tmp_path, monkeypatch, joined):
    rp = module()
    from ravel.workflow import physics_review
    run(tmp_path, claims=[{'id': 'C1', 'kind': 'prediction'}])
    request = tmp_path / 'accept.json'; request.write_text(json.dumps({'verdict': 'accept'}))
    calls = []
    monkeypatch.setattr(physics_review, 'main', lambda argv: calls.append(argv) or 0)
    argv = ([f'--rundir={tmp_path}', 'review', f'--request={request}'] if joined
            else ['--rundir', str(tmp_path), 'review', '--request', str(request)])
    with pytest.raises(ValueError, match='attested receipts'):
        rp.main(argv)
    assert calls == []


def test_forged_receipt_in_agent_work_not_credited(tmp_path):
    rp = module(); run(tmp_path, claims=[{'id': 'C1'}])
    for p in rp.derive(rp._facts(tmp_path)):
        if p['row'] == 4:
            receipt(tmp_path, p['id'], p['roles'][0]['role'], register=False,
                    execution_mode='transport_attested_cli')
    assert len([p for p in rp.pending(tmp_path) if p['row'] == 4]) == 3


def test_receipt_bytes_changed_after_registration_not_credited(tmp_path):
    rp = module(); run(tmp_path, claims=[{'id': 'C1'}])
    p = next(p for p in rp.pending(tmp_path) if p['row'] == 4)
    v = receipt(tmp_path, p['id'], p['roles'][0]['role'])
    path = tmp_path/'agent-work'/v['node_id']/'1/receipt.json'
    path.write_text(path.read_text()+' ')
    assert not rp.satisfied(tmp_path, p['id'])


def test_receipt_without_final_record_path_not_credited(tmp_path):
    rp = module(); run(tmp_path, claims=[{'id': 'C1'}])
    p = next(p for p in rp.pending(tmp_path) if p['row'] == 4)
    receipt(tmp_path, p['id'], p['roles'][0]['role'], final_record={'valid': True})
    assert not rp.satisfied(tmp_path, p['id'])


def test_receipt_for_changed_claim_is_stale(tmp_path):
    rp = module(); run(tmp_path, claims=[{'id': 'C1'}])
    p = next(p for p in rp.pending(tmp_path) if p['row'] == 4)
    receipt(tmp_path, p['id'], p['roles'][0]['role'])
    run(tmp_path, claims=[{'id': 'C1', 'kind': 'agreement'}])
    assert not rp.satisfied(tmp_path, p['id'])


def test_execution_mode_cli_without_verified_label_is_self_attested():
    assert module().attestation_label({'execution_mode': 'transport_attested_cli'}) == 'self_attested'


def test_receipt_attestation_field_ignored():
    assert module().attestation_label({'attestation': 'transport_attested'}) == 'self_attested'


@pytest.mark.parametrize('delegated', [True, False], ids=['delegated', 'human_led'])
def test_self_attested_never_counts_toward_voting_or_specialist(tmp_path, delegated):
    rp = module(); run(tmp_path, delegated=delegated, claims=[{'id': 'C1', 'absolute_yield': True}])
    for p in rp.pending(tmp_path):
        if p['row'] in {4, 5}:
            receipt(tmp_path, p['id'], p['roles'][0]['role'], execution_mode='relay_schema_2', verified_label=None)
            assert not rp.satisfied(tmp_path, p['id'])


def test_human_led_point_refuses_unregistered_human_manual(tmp_path):
    rp = module(); run(tmp_path, delegated=False, claims=[{'id': 'C1'}])
    p = next(p for p in rp.pending(tmp_path) if p['row'] == 4)
    receipt(tmp_path, p['id'], p['roles'][0]['role'], execution_mode='human_manual', verified_label=None)
    assert not rp.satisfied(tmp_path, p['id'])


def test_pending_reports_self_attested_as_independent_false(tmp_path):
    rp = module(); run(tmp_path, delegated=False, claims=[{'id': 'C1'}])
    p = next(p for p in rp.pending(tmp_path) if p['row'] == 4)
    receipt(tmp_path, p['id'], p['roles'][0]['role'], execution_mode='relay_schema_2', verified_label=None)
    p = next(x for x in rp.pending(tmp_path) if x['id'] == p['id'])
    assert p['receipts'][0]['independent'] is False


def test_no_transport_attested_cli_label_anywhere():
    import inspect
    assert 'transport_attested_cli' not in inspect.getsource(module()._missing)


@pytest.mark.parametrize('finding', [
    {'new_receipt': {'id': 'ghost'}},
    {'code_check': {'id': 'check:ghost', 'status': 'failed'}},
], ids=['ghost_new_receipt', 'self_declared_failed_code_check'])
def test_unverified_finding_is_advisory(tmp_path, finding):
    assert not module().blocking_finding(tmp_path, {'severity': 'A', **finding})


def test_human_led_plan_not_refused_for_missing_advisory_role_card(tmp_path):
    rp = module(); run(tmp_path, delegated=False, nodes=[{'id': 'N1', 'operation': 'literal-calculation'}])
    point = next(p for p in rp.derive(rp._facts(tmp_path)) if p['row'] == 1)
    assert rp.dispatchability(tmp_path, [point]) == []


def test_registered_code_check_in_worker_final_record_blocks_gate(tmp_path):
    from rdj_fixtures import Run
    r = Run(tmp_path/'run', snapshot=False)
    rp = module()
    run(r.root, claims=[{'id': 'C1'}])
    locator = r.check_result('closure')
    p = next(p for p in rp.pending(r.root) if p['row'] == 4)
    role = p['roles'][0]['role']
    final = write(r.root/'agent-work'/(role+'1')/'1/final.json', {'findings': [
        {'materiality': 'A', 'evidence_class': 'code_check', 'evidence_locators': [locator]}]})
    receipt(r.root, p['id'], role, final_record={'path': 'final.json', 'sha256': final['sha256'], 'valid': True})
    assert any(e.code == 'blocking_finding' and e.pins == (locator,) for e in rp.gate_errors(r.root, 'checkin2_accept', {}))


def test_checkin_summary_discloses_self_attested_as_non_independent(tmp_path):
    rp = module(); run(tmp_path, delegated=False, claims=[{'id': 'C1'}])
    p = next(p for p in rp.pending(tmp_path) if p['row'] == 4)
    receipt(tmp_path, p['id'], p['roles'][0]['role'], execution_mode='relay_schema_2', verified_label=None)
    report = rp.checkin3_section(tmp_path)['review_receipts']
    assert report[0]['review_point_id'] == p['id']
    assert report[0]['attestation'] == 'self_attested' and report[0]['independent'] is False
