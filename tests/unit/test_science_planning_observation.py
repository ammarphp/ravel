"""Synthetic plan custody only: no worker/native/model/provider execution."""

from method_decision_fixture import admit_method
from pathlib import Path
from contextlib import contextmanager
from types import SimpleNamespace
import os

import pytest

from ravel.workflow import execution, science
from ravel.workflow.state_io import atomic_json, read_json
from ravel.validation import likelihood_parity
from test_physics_review import policy


@pytest.fixture
def prospect(tmp_path, monkeypatch):
    payload = tmp_path/'runtime.bin'; payload.write_bytes(b'planning-byte-custody-'*4096)
    inventory = {'schema_version': 1, 'files': [{'path': str(payload), 'sha256': execution.file_hash(payload)}]}
    calls = []; budgets = []
    def inputs(task, base, session):
        calls.append(session)
        return likelihood_parity.runtime_files(inventory, _session=session)
    def budget(task, base, session):
        budgets.append(session)
        likelihood_parity.runtime_files(inventory, _session=session)
        return 7
    implementation = SimpleNamespace(validate=lambda task: None,
        inputs=lambda task, base: likelihood_parity.runtime_files(inventory),
        _validation_inputs=inputs, execution_seconds=lambda task, base: 7,
        _validation_execution_seconds=budget)
    monkeypatch.setattr(science, 'adapter', lambda spec: implementation)
    review = policy(); review.update(allowed_stages=['science'], allowed_changed_paths=[], max_redos=0)
    document = {'schema_version': 2, 'mode': 'likelihood-parity', 'source': 'Synthetic planning lifecycle control',
        'assumptions': ['No computation or scientific acceptance'], 'max_seconds': 45, 'max_attempts': 1,
        'approval_mode': 'scripted_yes', 'task': {'input': str(payload)},
        'review_policy': {'schema_version': 1, 'policy': review,
            'correction_contract': {'task_fields': [], 'input_slots': []}}}
    source = tmp_path/'spec.json'; atomic_json(source, document)
    return tmp_path/'new-run', source, payload, implementation, calls, budgets


def captured_sessions(monkeypatch):
    rows = []; factory = execution._validation_session
    def acquire(*args, **kwargs):
        result = factory(*args, **kwargs); rows.append(result); return result
    monkeypatch.setattr(execution, '_validation_session', acquire)
    return rows


def test_two_real_input_budget_scopes_close_before_each_effect_and_packet_is_fresh(prospect, monkeypatch):
    rd, source, payload, implementation, calls, budgets = prospect
    rows = captured_sessions(monkeypatch); writes = []; writer = science.atomic_json
    def write(path, value):
        path = Path(path)
        if path == rd/science.SPEC:
            assert len(rows) == 1 and rows[0].closed and not rows[0].hashes and not rows[0].proofs
            assert not rd.joinpath(science.PLAN).exists()
        if path == rd/science.PLAN:
            assert len(rows) == 2 and all(s.closed for s in rows)
            assert all(not s.hashes and not s.proofs for s in rows)
        writes.append(path); return writer(path, value)
    monkeypatch.setattr(science, 'atomic_json', write)
    proposal = science.plan(rd, source)
    assert len(rows) == 3 and rows[0] is not rows[1] and rows[1] is not rows[2]
    assert calls[:2] == budgets[:2] == rows[:2]
    assert all(s.closed for s in rows)
    assert proposal['stages'][0]['inputs'][:3] == [science.SPEC, science.EXECUTION_TASK, science.REVIEW_POLICY]
    assert str(payload) in proposal['stage_binding']['input_snapshot']
    assert proposal['max_seconds'] == 45 and proposal['max_attempts'] == 1
    from ravel.workflow.prepared_runtime import validate
    validate(proposal['prepared_runtime'], proposal['stage_binding'])
    assert read_json(rd/science.PLAN) == proposal and science.verify_plan(rd) == proposal
    assert not (rd/science.APPROVAL).exists() and not (rd/'execution_attempt.json').exists()
    assert read_json(rd/'current_state.json')['execution']['status'] == 'planned'


@pytest.mark.parametrize('damage', ['zero_budget', 'unknown_key', 'bad_policy'])
def test_invalid_spec_creates_no_owner_or_session(prospect, monkeypatch, damage):
    rd, source, _, _, _, _ = prospect; document = read_json(source)
    if damage == 'zero_budget': document['max_seconds'] = 0
    elif damage == 'unknown_key': document['unexpected'] = 'invalid'
    else: document['review_policy']['policy']['max_redos'] = -1
    atomic_json(source, document); rows = captured_sessions(monkeypatch)
    with pytest.raises(ValueError): science.plan(rd, source)
    assert rows == [] and not rd.exists()


@pytest.mark.parametrize('owner', ['existing', 'symlink'])
def test_nonprospective_owner_preserves_original_input_before_destination_refusal(owner, prospect, monkeypatch):
    rd, source, _, implementation, calls, _ = prospect
    if owner == 'existing': rd.mkdir()
    else:
        target = rd.with_name('target'); target.mkdir(); rd.symlink_to(target, target_is_directory=True)
    independent = []; old = implementation.inputs
    implementation.inputs = lambda *a: (independent.append(True), old(*a))[1]
    rows = captured_sessions(monkeypatch)
    with pytest.raises((ValueError, FileExistsError)): science.plan(rd, source)
    assert independent == [True] and calls == [] and rows == []
    assert not (rd/science.PLAN).exists()


def test_legacy_task_inputs_seam_gets_original_positional_calls_and_no_planning_session(prospect, monkeypatch):
    rd, source, _, _, _, _ = prospect; original = science.task_inputs; calls = []
    def legacy(spec, base):
        calls.append((spec, base)); return original(spec, base)
    monkeypatch.setattr(science, 'task_inputs', legacy)
    rows = captured_sessions(monkeypatch)
    proposal = science.plan(rd, source)
    assert len(calls) == 2 and proposal == read_json(rd/science.PLAN)
    # The public packet still has its original independent verifier seam: a
    # legacy input callable cannot accept its existing _session keyword.
    assert len(rows) == 1 and rows[0].closed
    state = read_json(rd/'current_state.json')
    assert state['execution']['status'] == 'invalid' and state['errors']
    assert not (rd/science.APPROVAL).exists()


def test_legacy_planner_keeps_independent_positional_contract(prospect, monkeypatch):
    rd, source, _, _, _, _ = prospect; old = execution.plan_stage; seen = []
    def legacy(rundir, stage, command, inputs, outputs, parents=None, cwd=None, *, output_policy=None, helper_declaration=None):
        seen.append((rundir, stage, command, inputs, outputs, parents, cwd))
        return old(rundir, stage, command, inputs, outputs, parents, cwd,
            **({'output_policy': output_policy} if output_policy is not None else {}),
            **({'helper_declaration': helper_declaration} if helper_declaration is not None else {}))
    monkeypatch.setattr(execution, 'plan_stage', legacy)
    proposal = science.plan(rd, source)
    assert seen and all(row[1] == 'science' for row in seen)
    assert science.verify_plan(rd) == proposal
    assert not (rd/science.APPROVAL).exists()


@pytest.mark.parametrize('phase', [1, 2])
@pytest.mark.parametrize('mutation', ['bytes', 'replacement', 'symlink', 'ledger', 'runtime', 'argument', 'absent_inventory', 'owner'])
def test_callback_drift_is_terminally_refused_before_planning_publication(phase, mutation, prospect, monkeypatch):
    rd, source, payload, implementation, calls, _ = prospect; old = implementation._validation_inputs; once = []
    def inputs(task, base, session):
        result = old(task, base, session)
        if len(calls) == phase:
            missing = source.parent/'observed-missing'; session.require_inventory(missing)
            def mutate():
                once.append(True)
                if mutation == 'bytes':
                    before = payload.stat(); raw = payload.read_bytes(); payload.write_bytes(b'X'+raw[1:])
                    os.utime(payload, ns=(before.st_atime_ns, before.st_mtime_ns))
                elif mutation == 'replacement':
                    new = payload.with_name('replacement'); new.write_bytes(payload.read_bytes()); new.replace(payload)
                elif mutation == 'symlink':
                    new = payload.with_name('target'); new.write_bytes(payload.read_bytes()); payload.unlink(); payload.symlink_to(new)
                elif mutation == 'ledger': atomic_json(session.ledger, {'unissued': 'fixture-created late ledger'})
                elif mutation == 'runtime': monkeypatch.setenv('PATH', os.environ.get('PATH','')+':/synthetic-unselected-tool')
                elif mutation == 'argument':
                    spec = next(obj for obj, digest in session.tracked if isinstance(obj, dict) and 'review_policy' in obj)
                    spec['max_attempts'] += 1
                elif mutation == 'absent_inventory': missing.mkdir()
                elif phase == 1: rd.mkdir()
                else:
                    proposal = next(obj for obj, digest in session.tracked if isinstance(obj, dict) and 'stage_binding' in obj)
                    proposal['max_seconds'] += 1
            session.retain_final_check(mutate)
        return result
    implementation._validation_inputs = inputs; rows = captured_sessions(monkeypatch)
    with pytest.raises((ValueError, OSError), match='changed|differs|appeared|symlink|runtime|commitment|regular'):
        science.plan(rd, source)
    assert once == [True] and rows and all(s.closed for s in rows)
    assert all(not s.hashes and not s.proofs for s in rows)
    assert not (rd/science.PLAN).exists() and not (rd/science.APPROVAL).exists()
    if phase == 1 and mutation not in ('ledger', 'owner'): assert not rd.exists()
    if phase == 2: assert (rd/science.SPEC).exists()


def test_setup_effect_boundary_never_reuses_first_input_hash(prospect, monkeypatch):
    rd, source, payload, _, calls, _ = prospect; old = science.atomic_json; changed = []
    def write(path, value):
        if Path(path) == rd/science.SPEC:
            assert calls[0].closed
            raw = payload.read_bytes(); payload.write_bytes(b'X'+raw[1:]); changed.append(True)
        return old(path, value)
    monkeypatch.setattr(science, 'atomic_json', write)
    with pytest.raises(ValueError, match='runtime bytes differ'): science.plan(rd, source)
    assert changed and len(calls) == 2 and calls[0] is not calls[1] and all(s.closed for s in calls)
    assert (rd/science.SPEC).exists() and not (rd/science.PLAN).exists()


@pytest.mark.parametrize('phase', [1, 2])
def test_primary_callback_failure_always_closes_and_publishes_no_plan(phase, prospect, monkeypatch):
    rd, source, _, implementation, calls, _ = prospect; old = implementation._validation_inputs
    def inputs(task, base, session):
        result = old(task, base, session)
        if len(calls) == phase:
            def fail(): raise RuntimeError('fixture callback refusal')
            session.retain_final_check(fail)
        return result
    implementation._validation_inputs = inputs; rows = captured_sessions(monkeypatch)
    with pytest.raises(RuntimeError, match='fixture callback refusal'): science.plan(rd, source)
    assert all(s.closed and not s.hashes and not s.proofs for s in rows)
    assert not (rd/science.PLAN).exists() and not (rd/science.APPROVAL).exists()


def test_approval_and_later_packet_are_fresh_after_planning(prospect, monkeypatch):
    rd, source, _, _, calls, _ = prospect; rows = captured_sessions(monkeypatch)
    science.plan(rd, source); admit_method(rd); planning = tuple(rows[:2]); before = len(rows)
    science.approve(rd, 'Exact synthetic planning transfer', scripted=True)
    assert len(rows) > before and all(s not in planning for s in rows[2:])
    assert all(s.closed for s in rows)
    assert science.packet(rd)['execution']['status'] == 'approved'
    assert not (rd/'execution_attempt.json').exists()


def test_injected_legacy_stage_seam_retains_original_positional_planning(prospect, monkeypatch):
    rd, source, _, _, calls, _ = prospect; old = science._stage; seen = []; before_packet = []
    def legacy(rundir, inputs, number, *, base_dir=None, output_policy=None):
        seen.append(True)
        return old(rundir, inputs, number, base_dir=base_dir,
            **({'output_policy': output_policy} if output_policy is not None else {}))
    monkeypatch.setattr(science, '_stage', legacy)
    rows = captured_sessions(monkeypatch); writer = science.atomic_json
    def write(path, value):
        if Path(path) == rd/science.PLAN:
            assert seen == [True] and calls == [] and all(s.closed for s in rows)
            before_packet.append(len(rows))
        return writer(path, value)
    monkeypatch.setattr(science, 'atomic_json', write)
    proposal = science.plan(rd, source)
    assert seen == [True] and len(before_packet) == 1
    packet_sessions = rows[before_packet[0]:]
    assert len(packet_sessions) == 1 and packet_sessions[0].closed
    assert calls == [packet_sessions[0], packet_sessions[0]]
    assert all(s.closed for s in rows)
    assert proposal == read_json(rd/science.PLAN)
    assert read_json(rd/'current_state.json')['execution']['status'] == 'invalid'
    assert not (rd/science.APPROVAL).exists()


def test_replaced_input_owner_after_setup_uses_fresh_original_fallback(prospect, monkeypatch):
    rd, source, _, _, calls, _ = prospect; old_writer = science.atomic_json; original = science.task_inputs; legacy_calls = []
    def legacy(spec, base):
        legacy_calls.append(True); return original(spec, base)
    def write(path, value):
        if Path(path) == rd/science.SPEC:
            assert calls[0].closed
            monkeypatch.setattr(science, 'task_inputs', legacy)
        return old_writer(path, value)
    monkeypatch.setattr(science, 'atomic_json', write)
    rows = captured_sessions(monkeypatch)
    proposal = science.plan(rd, source)
    assert legacy_calls == [True] and len(calls) == 1 and len(rows) == 2 and all(s.closed for s in rows)
    assert proposal == read_json(rd/science.PLAN)
    assert read_json(rd/'current_state.json')['execution']['status'] == 'invalid'
    assert not (rd/science.APPROVAL).exists()


@pytest.mark.parametrize('mutation', ['append', 'remove', 'path_type', 'reorder', 'duplicate'])
def test_actual_retained_input_list_mutation_is_refused_after_terminal_before_setup(prospect, monkeypatch, mutation):
    rd, source, _, implementation, _, _ = prospect; original = science._planning_validation_scope; changed = []
    other = source.parent/'second-input.bin'; other.write_bytes(b'Synthetic second input for ordered inventory custody')
    inventory = {'schema_version': 1, 'files': [{'path': str(other), 'sha256': execution.file_hash(other)}]}
    input_hook = implementation._validation_inputs
    def inputs(task, base, session):
        return [*input_hook(task, base, session), *likelihood_parity.runtime_files(inventory, _session=session)]
    implementation._validation_inputs = inputs
    @contextmanager
    def observed(rundir, *tracked, prospective=False, _input_inventories=None):
        with original(rundir, *tracked, prospective=prospective, _input_inventories=_input_inventories) as session:
            if _input_inventories is not None:
                def mutate():
                    current, expected = _input_inventories[0]
                    assert tuple((type(path), str(path)) for path in current) == expected
                    if mutation == 'append': current.append(source.parent/'unselected-input')
                    elif mutation == 'remove': current.clear()
                    elif mutation == 'path_type': current[0] = str(current[0])
                    elif mutation == 'reorder': current.reverse()
                    else: current.append(current[0])
                    changed.append(True)
                session.retain_final_check(mutate)
            yield session
    monkeypatch.setattr(science, '_planning_validation_scope', observed)
    rows = captured_sessions(monkeypatch)
    with pytest.raises(ValueError, match='planning input inventory changed during validation'):
        science.plan(rd, source)
    assert changed == [True] and len(rows) == 1 and rows[0].closed
    assert not rows[0].hashes and not rows[0].proofs
    assert not rd.exists() and not (rd/science.PLAN).exists() and not (rd/science.APPROVAL).exists()
