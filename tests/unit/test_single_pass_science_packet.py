"""Synthetic observational custody controls; no worker/model/native delivery."""
from copy import deepcopy
from pathlib import Path

import pytest

from ravel.workflow import execution, science
from ravel.workflow.state_io import atomic_json, read_json
from ravel.workflow.validation_io import ValidationSession
from test_science_validation_session import prepared, token, context_for
from test_science_packet_observation import accepted


def input_calls(monkeypatch):
    calls = []; original = science.task_inputs
    def counted(spec, base, *, _session=None):
        calls.append((deepcopy(spec), str(base), _session))
        return original(spec, base, _session=_session)
    monkeypatch.setattr(science, 'task_inputs', counted)
    return calls


def sessions(monkeypatch):
    seen = []; factory = execution._validation_session
    def make(*args, **kwargs):
        result = factory(*args, **kwargs); seen.append(result); return result
    monkeypatch.setattr(execution, '_validation_session', make)
    return seen


def assert_closed(seen):
    assert seen and all(s.closed and not s.proofs and not s.hashes for s in seen)


@pytest.mark.parametrize('receipt_state', ['valid', 'missing'])
def test_public_packet_has_one_complete_original_and_effective_intake(prepared, monkeypatch, receipt_state):
    rd, _, _, _ = prepared
    if receipt_state == 'missing': (rd/science.APPROVAL).unlink()
    calls = input_calls(monkeypatch); seen = sessions(monkeypatch)
    result = science.packet(rd)
    assert result['execution']['status'] == ('approved' if receipt_state == 'valid' else 'planned')
    assert result['task_mode'] == 'likelihood-parity' and result['lifecycle_verdict'] == 'PENDING'
    assert len(calls) == 2 and calls[0][0] == calls[1][0]
    assert calls[0][2] is calls[1][2] is seen[0]
    assert_closed(seen)


@pytest.mark.parametrize('damage', ['plan_hash', 'checkin_hash', 'fingerprint', 'quote', 'keys'])
def test_bad_object_approval_retains_validated_mode_and_no_approval_proof(prepared, monkeypatch, damage):
    rd, _, _, _ = prepared; receipt = read_json(rd/science.APPROVAL)
    if damage == 'plan_hash': receipt['plan_sha256'] = '0'*64
    elif damage == 'checkin_hash': receipt['checkin_sha256'] = '0'*64
    elif damage == 'fingerprint': receipt['input_fingerprint'] = '0'*64
    elif damage == 'quote': receipt['quote'] = ''
    else: receipt['extra'] = True
    atomic_json(rd/science.APPROVAL, receipt)
    calls = input_calls(monkeypatch); seen = sessions(monkeypatch); before_finish = []; old = ValidationSession.finish
    def finish(session):
        before_finish.append(set(session.proofs)); return old(session)
    monkeypatch.setattr(ValidationSession, 'finish', finish)
    result = science.packet(rd, write=True)
    assert result['task_mode'] == 'likelihood-parity'
    assert result['execution']['status'] == 'invalid' and result['lifecycle_verdict'] == 'FAIL' and result['errors']
    assert len(calls) == 2 and ('science-v2-plan', True) not in before_finish[0]
    assert read_json(rd/'current_state.json') == result
    assert_closed(seen)
    with pytest.raises(ValueError): science.verify_plan(rd, approved=True)
    assert science.verify_approval_envelope(rd)


@pytest.mark.parametrize('receipt', [None, [], [1], True, 7, 'approval'])
def test_nonobject_receipt_is_explicit_refusal_not_attribute_error(prepared, monkeypatch, receipt):
    rd, _, _, _ = prepared; atomic_json(rd/science.APPROVAL, receipt)
    calls = input_calls(monkeypatch); seen = sessions(monkeypatch)
    result = science.packet(rd)
    assert result['task_mode'] == 'likelihood-parity' and result['execution']['status'] == 'invalid'
    assert result['errors'] == ['science approval requires an object'] and result['lifecycle_verdict'] == 'FAIL'
    assert len(calls) == 2
    assert_closed(seen)
    with pytest.raises(ValueError, match='science approval requires an object'): science.verify_plan(rd, approved=True)
    assert science.verify_approval_envelope(rd) == ['science approval requires an object']


def test_common_failure_never_sets_mode_or_proceeds_to_approval(prepared, monkeypatch):
    rd, _, _, _ = prepared; plan = read_json(rd/science.PLAN); plan['max_seconds'] += 1
    atomic_json(rd/science.PLAN, plan)
    calls = input_calls(monkeypatch); seen = sessions(monkeypatch)
    def approval(*args, **kwargs): pytest.fail('common failure reached approval')
    # Retain canonical callable identity while witnessing only actual receipt reads.
    original_read = ValidationSession.read_document
    def read(session, path):
        if Path(path) == rd/science.APPROVAL: approval()
        return original_read(session, path)
    monkeypatch.setattr(ValidationSession, 'read_document', read)
    result = science.packet(rd)
    assert result['task_mode'] is None and result['execution']['status'] == 'invalid'
    assert result['errors'] == ['science plan, prospective policy or immutable envelope changed']
    assert not calls
    assert_closed(seen)


@pytest.mark.parametrize('target', ['verify_plan', '_verify_v2', '_verify_v2_common', '_verify_v2_approval', 'review_enabled', '_packet_negative_close'])
def test_replaced_validator_uses_original_observed_sequence_without_new_closing(target, prepared, monkeypatch):
    rd, _, _, _ = prepared; original = getattr(science, target); called = []
    def replacement(*args, **kwargs):
        called.append(kwargs.get('approved', None)); return original(*args, **kwargs)
    monkeypatch.setattr(science, target, replacement)
    calls = input_calls(monkeypatch)
    result = science.packet(rd)
    assert result['execution']['status'] == 'approved' and result['task_mode'] == 'likelihood-parity'
    assert len(calls) == 4
    if target == 'verify_plan': assert called == [None, True]
    elif target == '_packet_negative_close': assert called == []
    else: assert called


def test_noncanonical_session_keeps_original_full_verifier_path(prepared, monkeypatch):
    rd, _, _, _ = prepared
    class Derived(ValidationSession): pass
    factory = execution._validation_session
    def make(*args, **kwargs):
        session = factory(*args, **kwargs)
        session.__class__ = Derived
        return session
    monkeypatch.setattr(execution, '_validation_session', make)
    calls = input_calls(monkeypatch)
    assert science.packet(rd)['execution']['status'] == 'approved'
    assert len(calls) == 4


def test_default_private_observation_preserves_old_false_then_true_sequence(prepared, monkeypatch):
    rd, _, _, _ = prepared; calls = input_calls(monkeypatch)
    with science._validation_scope(rd) as session:
        result = science._packet_v2_observed(rd, session)
    assert result['execution']['status'] == 'approved' and len(calls) == 4
    assert_closed([session])


def test_existing_true_to_false_alias_remains_exact_with_default_observation(prepared, monkeypatch):
    rd, _, _, _ = prepared; calls = input_calls(monkeypatch)
    with science._validation_scope(rd) as session:
        proposal = science.verify_plan(rd, approved=True, _session=session)
        assert science.verify_plan(rd, _session=session) is proposal
        result = science._packet_v2_observed(rd, session)
    assert result['execution']['status'] == 'approved' and len(calls) == 2
    assert_closed([session])


def test_accepted_resume_authority_uses_original_default_path(accepted, monkeypatch):
    rd, _, _ = accepted; calls = input_calls(monkeypatch)
    proposal, reusable = science._accepted_resume_observed(rd)
    assert reusable is True and proposal['mode'] == 'likelihood-parity'
    assert len(calls) == 2


@pytest.mark.parametrize('which', ['inputs/native_execution_plan.json', 'inputs/checkin1_approval.json', 'inputs/task_contract.json', science.APPROVAL])
@pytest.mark.parametrize('boundary', ['final_callback', 'after_finish'])
def test_negative_observations_close_after_both_callback_boundaries(which, boundary, prepared, monkeypatch):
    rd, _, _, _ = prepared
    if which == science.APPROVAL: (rd/science.APPROVAL).unlink()
    original = ValidationSession.finish; created = []
    def create():
        atomic_json(rd/which, {'late': 'synthetic marker, no authority'}); created.append(which)
    def finish(session):
        if boundary == 'final_callback': session.retain_final_check(create)
        result = original(session)
        if boundary == 'after_finish':
            assert session.closed; create()
        return result
    monkeypatch.setattr(ValidationSession, 'finish', finish)
    result = science.packet(rd, write=True)
    assert result['execution']['status'] == 'invalid' and result['lifecycle_verdict'] == 'FAIL'
    assert result['task_mode'] is None and created == [which]
    diagnostic = 'study approval appeared during packet observation' if which == science.APPROVAL else 'science plan, prospective policy or immutable envelope changed'
    assert result['errors'] == [diagnostic]
    assert read_json(rd/'current_state.json') == result


@pytest.mark.parametrize('which', ['inputs/native_execution_plan.json', 'inputs/checkin1_approval.json', 'inputs/task_contract.json', science.APPROVAL])
def test_dangling_markers_preserve_exists_law_without_authority(which, prepared, monkeypatch):
    rd, _, _, _ = prepared
    if which == science.APPROVAL: (rd/science.APPROVAL).unlink()
    original = ValidationSession.finish
    def finish(session):
        result = original(session); (rd/which).symlink_to(rd/'not-an-authority-file'); return result
    monkeypatch.setattr(ValidationSession, 'finish', finish)
    result = science.packet(rd)
    assert not (rd/which).exists() and (rd/which).is_symlink()
    assert result['execution']['status'] == ('planned' if which == science.APPROVAL else 'approved')
    assert result['lifecycle_verdict'] == 'PENDING' and result['physics_validated'] is False


def test_two_public_packets_never_share_producer_or_approval_proofs(prepared, monkeypatch):
    rd, _, _, _ = prepared; calls = input_calls(monkeypatch); seen = sessions(monkeypatch)
    first = science.packet(rd); second = science.packet(rd)
    assert first == second and len(calls) == 4
    assert len(seen) == 2 and seen[0] is not seen[1]
    assert_closed(seen)


def test_ordinary_approval_and_launch_admissions_stay_fresh(prepared, monkeypatch):
    rd, _, _, _ = prepared; calls = input_calls(monkeypatch); seen = sessions(monkeypatch)
    assert science.verify_approval_envelope(rd) == []
    token(rd); selected = science.launch_binding(rd, 'science')
    assert science.verify_launch(rd, 'science', selected['stage']['command'], context_for(selected, rd)) == []
    assert len(calls) == 6 and len({id(row[2]) for row in calls}) == 3
    assert_closed(seen)


def test_initial_forbidden_envelope_and_invalid_plan_version_keep_refusal_order(prepared):
    rd, _, _, _ = prepared
    atomic_json(rd/'inputs/native_execution_plan.json', {'synthetic': True})
    result = science.packet(rd)
    assert result['task_mode'] is None and result['errors'] == ['science plan, prospective policy or immutable envelope changed']
    (rd/'inputs/native_execution_plan.json').unlink()
    plan = read_json(rd/science.PLAN); plan['schema_version'] = 2.0; atomic_json(rd/science.PLAN, plan)
    result = science.packet(rd)
    assert result['task_mode'] is None and result['errors'] == ['invalid science plan version']


def test_receipt_created_during_common_is_sampled_and_validated_after_common(prepared, monkeypatch):
    rd, _, _, _ = prepared; receipt = read_json(rd/science.APPROVAL); (rd/science.APPROVAL).unlink()
    original = science.task_inputs; calls = []; read_approval = []; reader = ValidationSession.read_document
    def intake(*args, **kwargs):
        result = original(*args, **kwargs); calls.append(True)
        if len(calls) == 1: atomic_json(rd/science.APPROVAL, receipt)
        return result
    def read(session, path):
        if Path(path) == rd/science.APPROVAL: read_approval.append(True)
        return reader(session, path)
    monkeypatch.setattr(science, 'task_inputs', intake); monkeypatch.setattr(ValidationSession, 'read_document', read)
    result = science.packet(rd)
    assert result['execution']['status'] == 'approved' and result['task_mode'] == 'likelihood-parity'
    assert len(calls) == 2 and read_approval


@pytest.mark.parametrize('damage', ['utc', 'mode', 'delegation'])
def test_remaining_receipt_authority_predicates_still_refuse(prepared, damage):
    rd, _, _, _ = prepared; receipt = read_json(rd/science.APPROVAL)
    if damage == 'utc': receipt['utc'] = 'not a time'
    elif damage == 'mode': receipt['approval_mode'] = 'human_quote'
    else:
        receipt.update(schema_version=3, generated_by='ravel.workflow.science.approve_delegated',
            authority='machine_under_user_delegation', delegation={}, delegate_actor='synthetic-unissued-delegate',
            approval_mode='delegated_machine', proposal_approval_mode='scripted_yes')
    atomic_json(rd/science.APPROVAL, receipt)
    result = science.packet(rd)
    assert result['task_mode'] == 'likelihood-parity' and result['execution']['status'] == 'invalid'
    assert result['lifecycle_verdict'] == 'FAIL' and result['errors']
    assert science.verify_approval_envelope(rd)
    with pytest.raises((ValueError, OSError, KeyError)): science.verify_plan(rd, approved=True)


@pytest.mark.parametrize('kind', ['directory', 'resolving_link', 'activated_dangling'])
@pytest.mark.parametrize('which', ['inputs/native_execution_plan.json', science.APPROVAL])
def test_late_presence_uses_same_exists_law_for_directories_and_links(kind, which, prepared, monkeypatch):
    rd, _, _, _ = prepared
    if which == science.APPROVAL: (rd/science.APPROVAL).unlink()
    target = rd.parent/'synthetic-marker-target'
    if kind == 'activated_dangling': (rd/which).symlink_to(target)
    original = ValidationSession.finish
    def finish(session):
        result = original(session)
        if kind == 'directory': (rd/which).mkdir()
        else:
            target.write_text('synthetic engineering marker, no authority')
            if kind == 'resolving_link': (rd/which).symlink_to(target)
        return result
    monkeypatch.setattr(ValidationSession, 'finish', finish)
    result = science.packet(rd)
    assert (rd/which).exists()
    assert result['execution']['status'] == 'invalid' and result['lifecycle_verdict'] == 'FAIL'
    assert result['task_mode'] is None and result['errors']


@pytest.mark.parametrize('boundary', ['common', 'approval', 'final_callback'])
def test_enrolled_owner_change_never_publishes_mixed_approval_proof(boundary, prepared, monkeypatch):
    rd, _, _, _ = prepared; original_common = science._verify_v2_common
    changed = []; before_finish = []; original_finish = ValidationSession.finish
    def change():
        if not changed:
            changed.append(True)
            monkeypatch.setattr(science, '_verify_v2_common', lambda *a, **k: original_common(*a, **k))
    if boundary == 'common':
        original = science.task_inputs
        def intake(*args, **kwargs):
            result = original(*args, **kwargs); change(); return result
        monkeypatch.setattr(science, 'task_inputs', intake)
    elif boundary == 'approval':
        original = science._approval_fingerprint
        def fingerprint(paths):
            result = original(paths); change(); return result
        monkeypatch.setattr(science, '_approval_fingerprint', fingerprint)
    def finish(session):
        before_finish.append(set(session.proofs))
        if boundary == 'final_callback': session.retain_final_check(change)
        return original_finish(session)
    monkeypatch.setattr(ValidationSession, 'finish', finish)
    result = science.packet(rd)
    assert result['execution']['status'] == 'invalid' and result['lifecycle_verdict'] == 'FAIL'
    assert result['errors'] == ['packet validation owners changed during observation'] and changed
    if boundary != 'final_callback': assert ('science-v2-plan', True) not in before_finish[0]
    assert result['task_mode'] is None


@pytest.mark.parametrize('mutation', ['input_bytes', 'deleted_input', 'replaced_input', 'runtime', 'tracked_plan', 'tracked_spec', 'new_empty_output_directory'])
def test_existing_session_closures_still_refuse_after_single_common_pass(mutation, accepted, monkeypatch):
    rd, payload, _ = accepted; original = ValidationSession.finish
    def finish(session):
        if mutation == 'input_bytes':
            raw = payload.read_bytes(); payload.write_bytes(b'X'+raw[1:])
        elif mutation == 'deleted_input': payload.unlink()
        elif mutation == 'replaced_input':
            replacement = payload.with_name('replacement'); replacement.write_bytes(payload.read_bytes()); replacement.replace(payload)
        elif mutation == 'runtime': session.runtime_context = lambda: {'changed': 'runtime'}
        elif mutation == 'new_empty_output_directory': (rd/'outputs/attempt-1/empty-new-member').mkdir()
        else:
            document = next(obj for obj, _ in session.tracked if isinstance(obj, dict) and
                ('stage_binding' in obj if mutation == 'tracked_plan' else 'review_policy' in obj and 'task' in obj))
            document['max_seconds'] += 1
        return original(session)
    monkeypatch.setattr(ValidationSession, 'finish', finish)
    result = science.packet(rd)
    assert result['execution']['status'] == 'invalid' and result['lifecycle_verdict'] == 'FAIL' and result['errors']
    assert result['task_mode'] is None


def test_actual_adapter_hook_failure_is_preserved_before_approval(prepared):
    rd, _, _, implementation = prepared
    def refuse(*args, **kwargs): raise ValueError('actual injected adapter reports unresolved inputs')
    implementation._validation_inputs = refuse
    result = science.packet(rd)
    assert result['errors'] == ['actual injected adapter reports unresolved inputs']
    assert result['task_mode'] is None and result['lifecycle_verdict'] == 'FAIL'
    with pytest.raises(ValueError, match='unresolved inputs'): science.verify_plan(rd, approved=True)


@pytest.mark.parametrize('entry', ['packet', 'approved_verifier'])
def test_factoring_retains_original_captured_reader_across_common_and_receipt(entry, prepared):
    rd, _, _, implementation = prepared
    valid = read_json(rd/science.APPROVAL); invalid = {**valid, 'plan_sha256': '0'*64}
    atomic_json(rd/science.APPROVAL, invalid)
    original_hook = implementation._validation_inputs; forged_reads = []
    def intake(task, base, session):
        result = original_hook(task, base, session)
        original_reader = session.read_document
        def reader(path):
            if Path(path) == rd/science.APPROVAL:
                forged_reads.append(True); return deepcopy(valid)
            return original_reader(path)
        session.read_document = reader
        return result
    implementation._validation_inputs = intake
    if entry == 'packet':
        result = science.packet(rd)
        assert result['execution']['status'] == 'invalid' and result['task_mode'] == 'likelihood-parity'
        assert result['errors'] == ['missing or stale study approval']
    else:
        with pytest.raises(ValueError, match='missing or stale study approval'): science.verify_plan(rd, approved=True)
    assert forged_reads == []


@pytest.mark.parametrize('seconds', [44, 46])
def test_actual_original_and_effective_budget_hooks_keep_exact_hard_ceiling(seconds, prepared):
    rd, _, _, implementation = prepared; budgets = []
    def budget(task, base, session):
        budgets.append((deepcopy(task), session)); return seconds
    implementation.execution_seconds = lambda task, base: seconds
    implementation._validation_execution_seconds = budget
    result = science.packet(rd)
    if seconds == 44:
        assert result['execution']['status'] == 'approved' and result['task_mode'] == 'likelihood-parity'
        assert len(budgets) == 2 and budgets[0][0] == budgets[1][0] and budgets[0][1] is budgets[1][1]
    else:
        assert result['execution']['status'] == 'invalid' and result['task_mode'] is None
        assert result['errors'] == ['adapter execution budget exceeds the scientific-study hard ceiling']
        assert len(budgets) == 1
    assert budgets[0][1].closed
