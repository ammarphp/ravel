"""Live-call stage reuse; actual planner bodies, inert inputs, no execution.

The two public controls retain the complete installed RAVEL source census.
Other controls replace execution.__file__ with a tiny owned source population
to challenge the exact planner's implicit membership semantics cheaply. They
do not import/execute that stand-in or certify scientific/native results.
"""
import os
from pathlib import Path
import sys

import pytest

from ravel.workflow import execution, science
from test_science_validation_session import prepared, token


def counted(monkeypatch):
    original = execution.plan_stage
    calls = []
    def planner(*args, _session=None, **kwargs):
        calls.append(_session)
        return original(*args, _session=_session, **kwargs)
    monkeypatch.setattr(execution, 'plan_stage', planner)
    return original, calls


@pytest.fixture
def literal(tmp_path, monkeypatch):
    source = tmp_path / 'package'
    (source / 'workflow').mkdir(parents=True)
    module = source / 'workflow/execution.py'
    module.write_text('# owned inert source-membership stand-in\n')
    (source / 'member.py').write_text('# second retained member\n')
    monkeypatch.setattr(execution, '__file__', str(module))
    rd = tmp_path / 'study'; rd.mkdir()
    payload = tmp_path / 'input.bin'; payload.write_bytes(b'original')
    request = {'rd': rd, 'stage': 'science', 'command': [sys.executable, '-c', 'pass'],
               'inputs': [str(payload)], 'outputs': ['outputs/result.json'],
               'parents': [], 'cwd': rd}
    return request, source, payload


def planned(request, session, **changes):
    return science._plan_stage(**(request | changes), session=session)


def test_public_launch_reuses_exact_binding_only_inside_current_call(prepared, monkeypatch):
    rd, _, _, _ = prepared; token(rd)
    _, calls = counted(monkeypatch)
    first = science.launch_binding(rd, 'science')
    second = science.launch_binding(rd, 'science')
    assert first == second
    assert len(calls) == 2 and calls[0] is not calls[1]
    assert all(session.closed and not session.proofs for session in calls)


def test_public_approval_requirement_survives_unapproved_plan_proof(prepared, monkeypatch):
    rd, _, _, _ = prepared
    _, calls = counted(monkeypatch)
    with pytest.raises(ValueError, match='approval|receipt|fingerprint'):
        with science._validation_scope(rd) as session:
            science.verify_plan(rd, approved=False, _session=session)
            monkeypatch.setattr(science, '_approval_fingerprint', lambda paths: '0' * 64)
            science.verify_plan(rd, approved=True, _session=session)
    assert calls and all(session.closed for session in calls)


def test_proof_equals_actual_fresh_stage_binding(literal, monkeypatch):
    request, _, _ = literal
    original, calls = counted(monkeypatch)
    with science._validation_scope(request['rd']) as session:
        first = planned(request, session)
        second = planned(request, session)
        fresh = original(request['rd'], request['stage'], request['command'], request['inputs'],
                         request['outputs'], request['parents'], request['cwd'], _session=session)
        assert first == second == fresh and first is not second
        assert len(calls) == 1


@pytest.mark.parametrize('field', ['stage', 'command', 'inputs', 'outputs', 'cwd', 'output_policy'])
def test_complete_request_changes_do_not_reuse_binding(literal, monkeypatch, field):
    request, _, payload = literal; _, calls = counted(monkeypatch)
    extra = payload.with_name('extra.bin'); extra.write_bytes(b'additional retained input')
    elsewhere = request['rd'] / 'elsewhere'; elsewhere.mkdir()
    change = {'stage': 'other', 'command': [sys.executable, '-c', 'pass '],
              'inputs': [str(payload), str(extra)], 'outputs': ['outputs/other.json'],
              'cwd': elsewhere, 'output_policy': {'schema_version': 1, 'allow_empty_directory_members': []}}[field]
    with science._validation_scope(request['rd']) as session:
        first = planned(request, session)
        second = planned(request, session, **{field: change})
        assert len(calls) == 2
        if field != 'stage': assert first['fingerprint'] != second['fingerprint']


@pytest.mark.parametrize('field', ['parents', 'helper_declaration'])
def test_changed_admission_declaration_reaches_original_refusal(literal, monkeypatch, field):
    request, _, _ = literal; _, calls = counted(monkeypatch)
    with science._validation_scope(request['rd']) as session:
        planned(request, session)
        with pytest.raises((ValueError, KeyError)):
            planned(request, session, **{field: ['absent'] if field == 'parents' else {}})
        assert len(calls) == 2


def test_replaced_planner_does_not_acquire_prior_callable_proof(literal, monkeypatch):
    request, _, _ = literal; original, first = counted(monkeypatch)
    with science._validation_scope(request['rd']) as session:
        planned(request, session)
        later = []
        def replacement(*args, _session=None, **kwargs):
            later.append(_session)
            return original(*args, _session=_session, **kwargs)
        monkeypatch.setattr(execution, 'plan_stage', replacement)
        planned(request, session)
        assert len(first) == len(later) == 1


@pytest.mark.parametrize('object_kind', ['returned', 'request'])
def test_caller_mutation_is_refused_at_ending_observation(literal, object_kind):
    request, _, _ = literal
    with pytest.raises(ValueError, match='supplied state or plan changed'):
        with science._validation_scope(request['rd']) as session:
            first = planned(request, session)
            if object_kind == 'returned': first['fingerprint'] = '0' * 64
            else: request['command'].append('changed argument')


@pytest.mark.parametrize('mutation', ['bytes', 'bytes_original_aba', 'replace_same_bytes', 'input_target'])
def test_input_custody_still_closes_after_binding_reuse(literal, mutation):
    request, _, payload = literal
    target = payload.with_name('original.bin')
    if mutation == 'input_target':
        payload.rename(target); payload.symlink_to(target)
    with pytest.raises(ValueError, match='changed|inventory'):
        with science._validation_scope(request['rd']) as session:
            planned(request, session)
            before = (target if mutation == 'input_target' else payload).stat()
            if mutation == 'input_target':
                other = payload.with_name('other.bin'); other.write_bytes(target.read_bytes())
                payload.unlink(); payload.symlink_to(other)
            elif mutation == 'replace_same_bytes':
                other = payload.with_name('other.bin'); other.write_bytes(payload.read_bytes()); other.replace(payload)
            else:
                payload.write_bytes(b'modified')
                if mutation == 'bytes_original_aba': payload.write_bytes(b'original')
                os.utime(payload, ns=(before.st_atime_ns, before.st_mtime_ns))
            planned(request, session)


@pytest.mark.parametrize('when', ['before_reuse', 'before_return'])
def test_full_source_population_cannot_grow_after_first_binding(literal, when):
    request, source, _ = literal
    with pytest.raises(ValueError, match='source membership'):
        with science._validation_scope(request['rd']) as session:
            planned(request, session)
            (source / 'late.py').write_text('# omitted late source\n')
            if when == 'before_reuse': planned(request, session)


@pytest.mark.parametrize('mutation', ['script_appears', 'output_symlink'])
def test_dynamic_path_selection_cannot_change_after_first_binding(literal, mutation):
    request, _, _ = literal
    if mutation == 'script_appears': request['command'] = [sys.executable, 'late.py']
    with pytest.raises(ValueError, match='selected paths|symlink'):
        with science._validation_scope(request['rd']) as session:
            planned(request, session)
            if mutation == 'script_appears': (request['rd'] / 'late.py').write_text('# never executed\n')
            else:
                target = request['rd'].parent / 'elsewhere'; target.mkdir()
                (request['rd'] / 'outputs').symlink_to(target, target_is_directory=True)
            planned(request, session)


def test_closed_cross_run_and_invalid_command_keep_refusing(literal):
    request, _, _ = literal
    session = execution._validation_session(request['rd'])
    try:
        with pytest.raises(ValueError, match='cross-run'):
            planned(request, session, rd=request['rd'].parent)
        with pytest.raises(ValueError, match='nonempty list of strings'):
            planned(request, session, command=[])
    finally: session.close()
    with pytest.raises(ValueError, match='closed'):
        planned(request, session)


def test_list_policy_does_not_authorize_tuple_collision_or_change_valid_proof(literal, monkeypatch):
    request, _, _ = literal; _, calls = counted(monkeypatch)
    valid = {'schema_version': 1, 'allow_empty_directory_members': []}
    invalid = {'schema_version': 1, 'allow_empty_directory_members': ()}
    # These are the exact source-defined collision in the original JSON key.
    assert execution.digest(valid) == execution.digest(invalid)
    with science._validation_scope(request['rd']) as session:
        first = planned(request, session, output_policy=valid)
        with pytest.raises(ValueError, match='invalid explicit output policy'):
            planned(request, session, output_policy=invalid)
        later = planned(request, session, output_policy=valid)
        assert first == later and first is not later and len(calls) == 2
    with pytest.raises(ValueError, match='invalid explicit output policy'):
        with science._validation_scope(request['rd']) as session:
            planned(request, session, output_policy=invalid)
    assert len(calls) == 3 and calls[0] is not calls[-1]


@pytest.mark.parametrize('object_kind', ['request', 'returned'])
def test_type_only_mutation_cannot_disappear_in_ending_json_digest(literal, object_kind):
    request, _, _ = literal
    policy = {'schema_version': 1, 'allow_empty_directory_members': []}
    with pytest.raises(ValueError, match='changed types'):
        with science._validation_scope(request['rd']) as session:
            result = planned(request, session, output_policy=policy)
            changed = policy if object_kind == 'request' else result['output_policy']
            before = execution.digest(changed)
            changed['allow_empty_directory_members'] = ()
            assert execution.digest(changed) == before
