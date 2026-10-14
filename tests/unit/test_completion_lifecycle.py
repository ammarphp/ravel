"""Completion lifecycle refusal controls with current synthetic artifacts."""
import argparse
from copy import deepcopy
from pathlib import Path
import pytest
from ravel.workflow import task_completion as tc, workflow_state, physics_review, state_io
from ravel.validation import validate_run_state as lifecycle, validate_checkin
from test_completion_composition import parent, outcome
from test_task_completion import write, request, review_run


def test_tier_b_comes_from_live_journal(tmp_path, monkeypatch):
    from ravel.workflow.completion_lifecycle import tier_b
    root = tmp_path / 'run'
    review_run(root, [], monkeypatch)
    assert tier_b(root)['verdict'] == 'PASS'
    monkeypatch.setattr(physics_review, 'gate_errors', lambda *a, **k: ['late hold'])
    with pytest.raises(ValueError, match='journal'): tier_b(root)


def test_changed_cost_fails_provenance_even_with_intact_contract(tmp_path):
    from ravel.workflow.completion_lifecycle import seal_cost
    c, cp = parent(tmp_path); root = Path(cp['path']).parent.parent
    record = seal_cost(root, {'schema_version': 1, 'mode': 'none', 'walltime_h': [0, 0], 'disk_gb_peak': 0})
    path = root / 'inputs/cost_preflight.json'; write(path, record)
    assert lifecycle.verify_provenance(str(root), c)['verdict'] == 'PASS'
    record['walltime_h'] = [0, 100]; write(path, record)
    assert lifecycle.verify_provenance(str(root), c)['verdict'] == 'FAIL'


def test_rdj_choice_census_cannot_be_omitted_or_relabelled(tmp_path):
    c, cp = parent(tmp_path); root = Path(cp['path']).parent.parent
    case = write(root / 'research/case.json', {'schema_version': 2})
    choice = {'id': 'choice-1', 'rule': 'supplied-reference'}
    receipt = write(root / 'research/receipt.json', {'schema_version': 1, 'kind': 'rdj-receipt', 'class': 'R2',
                    'outcome': 'authorize', 'gate': 'research_choice', 'action_digest': tc.ce.digest(choice),
                    'case': case, 'case_sha256': case['sha256'], 'open_a_findings': 0, 'unresolved_branches': 0})
    write(root / 'research/selection.json', {**choice, 'rdj_receipt': receipt})
    deck = {'schema_version': 1, 'kind': 'deck', 'sections': {k: 'Supplied result' for k in validate_checkin.DECK_SECTIONS}}
    assert any('every RDJ' in e for e in validate_checkin.validate(deck, str(root)))
    census = tc.compose(root, write=False)['ci3_list']
    deck['sections']['ci3_list'] = census
    assert validate_checkin.validate(deck, str(root)) == []
    deck['sections']['ci3_list'][0]['choice']['rule'] = 'different'
    assert any('every RDJ' in e for e in validate_checkin.validate(deck, str(root)))


def test_approval_installs_default_policy_before_fingerprinting(tmp_path, monkeypatch):
    c, cp = parent(tmp_path); root = Path(cp['path']).parent.parent
    monkeypatch.setattr(workflow_state, 'verify_approval', lambda *a, **k: [])
    assert workflow_state.cmd_approve(argparse.Namespace(rundir=str(root), plan='none', quote='Approve')) == 0
    policy = root / 'inputs/physics_review_policy.json'
    assert policy.is_file()
    assert 'original_task_completion' in state_io.read_json(policy)['claim_scopes']
    approval = state_io.read_json(root / 'inputs/checkin1_approval.json')
    assert approval['input_fingerprint'] == __import__('ravel.workflow.provenance', fromlist=['fingerprint']).fingerprint(workflow_state.approval_input_paths(str(root)))


def test_summary_invariant_recomputes_and_rejects_missing_inputs(tmp_path):
    c, _ = parent(tmp_path); c['task_mode'] = 'summary_plot'
    facts = {'result_pack_paths': {'survey': 'outputs/survey.json'}}
    name, _, fn = next(row for row in lifecycle.INVARIANTS if row[0] == 'summary-audit')
    assert fn(str(tmp_path), c, facts, False, False)[0] == 'FAIL'


def test_epoch_parent_does_not_require_unrelated_generation_matrix(tmp_path, monkeypatch):
    c, cp = parent(tmp_path); c['task_requirements']['completion_epoch'] = 1
    cp = write(Path(cp['path']), c); root = Path(cp['path']).parent.parent
    (root / 'inputs/children.jsonl').write_text('')
    assert lifecycle.evaluate(str(root), c, stage_limit='task_contract')['verdict'] == 'PASS'
    assert lifecycle.evaluate(str(root), c)['verdict'] == 'FAIL'


def test_scoped_delegated_approval_consumes_aggregate_reservation(tmp_path, monkeypatch):
    from ravel.workflow import scientific_autonomy as autonomy
    from ravel.workflow.completion_budget import reserve_delegated
    c, cp = parent(tmp_path); root = Path(cp['path']).parent.parent
    child = tmp_path / 'child'; child.mkdir()
    limits = {'max_seconds': 10, 'max_events': 0, 'max_children': 1}
    declaration = {'value': {'bounds': {'aggregate': limits}}}
    monkeypatch.setattr(autonomy, 'declaration', lambda *a, **k: declaration)
    document = {'mode': 'likelihood', 'goal_binding': {'contract': cp, 'assignment_id': 'A1'}, 'max_seconds': 10}
    reserve_delegated(document, declaration, child)
    assert state_io.read_json(root / 'inputs/delegation_reservations.json')['children'][0]['max_seconds'] == 10
    other = tmp_path / 'other'; other.mkdir()
    with pytest.raises(ValueError, match='aggregate'):
        reserve_delegated(document, declaration, other)


def test_scoped_delegated_approve_records_machine_authority_without_launch(tmp_path, monkeypatch):
    import hashlib
    import intake_sidecar_fixtures as fx
    from ravel import cli
    from ravel.workflow import scientific_autonomy as autonomy
    prompt = 'Run autonomously: Calculate the supplied counting-model diagnostic.'
    root = tmp_path / 'scoped'
    plan_binding = write(root / 'inputs/execution-plan.json', {'schema_version': 1, 'stages': []})
    claim = fx.claim(kind='calculation', statement='The supplied diagnostic quantity.',
                     deliverable={'artifact': 'scalar', 'template': None}, level='not_applicable',
                     comparison={'target': 'none', 'locator': None, 'metric': None, 'tolerance': None},
                     basis_declared=['supplied_inputs'],
                     statistic={'source': 'not_applicable', 'definition': None, 'evidence': [], 'secondary': []})
    contract, reading, plan = fx.pinned_run(root, prompt=prompt,
        contract_overrides={'task_mode': 'likelihood', 'stat_mode': 'provided-likelihood', 'compute_plan': 'full',
                            'execution_plan': {'path': 'inputs/execution-plan.json', 'sha256': plan_binding['sha256']},
                            'cost_estimate': {'mode': 'full', 'points': 1, 'walltime_h': [0, .01]}},
        plan_overrides={'nodes': [fx.node(operation='quantities')], 'claims': [claim],
                        'label': {'task_mode': 'likelihood', 'rule': 'D1', 'floor_row': 'likelihood'}})
    write(root / 'inputs/scoped.json', {'schema_version': 1, 'mode': 'likelihood', 'max_seconds': 36})
    user = root / 'inputs/user.txt'; user.write_text(prompt)
    declared = autonomy.prepare_declaration(contract, root / 'inputs/delegation.json',
        user_text={'path': str(user), 'sha256': hashlib.sha256(prompt.encode()).hexdigest()},
        quote='Run autonomously:', origin='initial_prompt', delegate_actor='coordinator', actions=['approve_plan'],
        bounds={'compute_plans': ['full'], 'allowed_changed_paths': [], 'allowed_stages': [], 'max_redos': 0},
        task_class='research_analysis', base_dir=root)
    write(root / 'inputs/task_contract.json', declared['document'])
    checkin = fx.checkin1(plan, reading); checkin['variant'] = 'calculation'
    checkin['sections'].update({key: 'Supplied bounded diagnostic' for key in ('formula', 'conventions', 'inputs', 'precision', 'check_value')})
    write(root / 'inputs/checkin1.json', checkin)
    write(root / 'inputs/cost_preflight.json', {'schema_version': 1, 'generated_by': 'cost_preflight.py', 'mode': 'full', 'points': 1, 'walltime_h': [0, .01]})
    from ravel.workflow import gate_wiring
    gate_wiring.record_run_init(root)  # the release intake records run_init once the contract is final
    from method_decision_fixture import admit_method
    admit_method(root)
    # A delegated approval first takes the approve_plan decision. Without it nothing is recorded;
    # that decision has its own tests (test_gate_wiring_r2r3), so the record is isolated here.
    assert cli.main(['approve', '--rundir', str(root), '--delegated']) == 2
    assert not (root / 'inputs/checkin1_approval.json').exists()
    gated = []
    monkeypatch.setattr(gate_wiring, 'require_delegated', lambda rundir, gate, action: gated.append(gate))
    assert cli.main(['approve', '--rundir', str(root), '--delegated']) == 0
    assert gated == ['approve_plan']
    approval = state_io.read_json(root / 'inputs/checkin1_approval.json')
    assert approval['authority'] == 'delegated_machine'
    assert workflow_state.verify_approval(str(root)) == []
    assert not (root / 'execution_state.json').exists()


def test_epoch_parent_completion_does_not_bypass_run_invariants(tmp_path, monkeypatch):
    from ravel.workflow import completion_lifecycle
    c, cp = parent(tmp_path); c['task_requirements']['completion_epoch'] = 1
    cp = write(Path(cp['path']), c); root = Path(cp['path']).parent.parent
    (root / 'inputs/children.jsonl').write_text('')
    accepted = {'stages': [], 'invariants': [], 'parent_task_accepted': True, 'verdict': 'PASS', 'exit': 0}
    monkeypatch.setattr(completion_lifecycle, 'evaluate_parent', lambda *a, **k: deepcopy(accepted))
    invariants = [('approval-before-compute', 'generation', lambda *a: ('FAIL', 'compute before approval'))]
    monkeypatch.setattr(lifecycle, 'INVARIANTS', invariants)
    result = lifecycle.evaluate(str(root), c)
    assert result['verdict'] == 'FAIL' and result['parent_task_accepted'] is False
    assert result['invariants'] == [{'name': 'approval-before-compute', 'status': 'FAIL', 'detail': 'compute before approval'}]
    assert lifecycle.evaluate(str(root), c, stage_limit='task_contract')['verdict'] == 'PASS'
