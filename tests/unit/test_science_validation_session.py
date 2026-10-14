"""Authority-local byte-read dedup and mutations; no model or worker execution."""

from method_decision_fixture import admit_method
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ravel.workflow import execution, physics_review, science, launch_authorization
from ravel.workflow.state_io import atomic_json, read_json
from ravel.workflow.validation_io import ValidationSession
from ravel.validation import likelihood_parity
from test_physics_review import policy


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    payload = tmp_path / 'runtime.bin'
    payload.write_bytes(b'bounded-runtime-control-' * 4096)
    inventory = {'schema_version': 1, 'files': [{'path': str(payload), 'sha256': execution.file_hash(payload)}]}
    implementation = SimpleNamespace(
        validate=lambda task: None,
        inputs=lambda task, base: likelihood_parity.runtime_files(inventory),
        _validation_inputs=lambda task, base, session: likelihood_parity.runtime_files(inventory, _session=session))
    monkeypatch.setattr(science, 'adapter', lambda spec: implementation)
    review_policy = policy()
    review_policy.update(allowed_stages=['science'], allowed_changed_paths=[], max_redos=0)
    spec = {'schema_version': 2, 'mode': 'likelihood-parity', 'source': 'Synthetic validation byte closure only',
            'assumptions': ['No likelihood calculation or physics acceptance'], 'max_seconds': 45,
            'max_attempts': 1, 'approval_mode': 'scripted_yes', 'task': {'input': str(payload)},
            'review_policy': {'schema_version': 1, 'policy': review_policy,
                              'correction_contract': {'task_fields': [], 'input_slots': []}}}
    source = tmp_path / 'spec.json';atomic_json(source, spec)
    rd = tmp_path / 'run';science.plan(rd, source); admit_method(rd)
    science.approve(rd, 'Exact synthetic byte closure', scripted=True)
    return rd, payload, inventory, implementation


def capture_reads(monkeypatch, payload):
    reads = [];sessions = [];factory = execution._validation_session;old = ValidationSession.hash_file
    def opened(*args, **kwargs):
        session = factory(*args, **kwargs);sessions.append(session);return session
    def hashed(self, path):
        count = self.hash_calls
        result = old(self, path)
        if Path(path) == payload and self.hash_calls > count:
            reads.append(self)
        return result
    monkeypatch.setattr(execution, '_validation_session', opened)
    monkeypatch.setattr(ValidationSession, 'hash_file', hashed)
    return reads, sessions


def token(rd):
    p = read_json(rd / science.PLAN)
    attempt = {'attempt': 1, 'plan_sha256': execution.file_hash(rd / science.PLAN),
               'budget_seconds': p['max_seconds'], 'started_utc': execution.utc_now(), 'correction_id': None, 'correction_plan_sha256': None}
    atomic_json(rd / 'execution_attempt.json', attempt)
    atomic_json(rd / 'logs/science-attempts/00000001.json', attempt)


def context_for(selected, rd):
    return {'kind': 'science-stage', 'stage': 'science', 'review_action': 'bulk',
            'max_seconds': selected['max_seconds'], 'plan_sha256': execution.file_hash(rd / science.PLAN),
            'stage_spec': physics_review._stage_spec(rd, {**selected['stage'], 'inputs': selected['binding']['inputs']})}


def test_one_content_read_per_plan_validation_and_fresh_between_calls(prepared, monkeypatch):
    rd, payload, _, _ = prepared;reads,sessions = capture_reads(monkeypatch, payload)
    first = science.verify_plan(rd, approved=True)
    second = science.verify_plan(rd, approved=True)
    assert first == second and len(reads) == 2 and len(set(map(id, reads))) == 2
    assert all(s.closed and not s.hashes for s in sessions)


def test_launch_selection_shares_one_read_but_new_phase_is_fresh(prepared, monkeypatch):
    rd,payload,_,_ = prepared;token(rd);reads,_ = capture_reads(monkeypatch,payload)
    selected = science.launch_binding(rd,'science')
    assert len(reads)==1
    assert science.verify_launch(rd,'science',selected['stage']['command'],context_for(selected,rd))==[]
    assert len(reads)==2 and reads[0] is not reads[1]


@pytest.mark.parametrize('mutation', ['same_size_restored_mtime', 'symlink', 'parent_symlink'])
def test_same_validation_mutation_cannot_reuse_hash(prepared, monkeypatch, mutation):
    rd,payload,_,implementation = prepared;hook=implementation._validation_inputs;done=[]
    def changing(task,base,session):
        result=hook(task,base,session)
        if not done:
            done.append(True);before=payload.stat()
            if mutation=='same_size_restored_mtime':
                raw=payload.read_bytes();payload.write_bytes(b'X'+raw[1:])
                os.utime(payload,ns=(before.st_atime_ns,before.st_mtime_ns))
            elif mutation=='symlink':
                target=payload.with_name('same-bytes.bin');target.write_bytes(payload.read_bytes())
                payload.unlink();payload.symlink_to(target)
            else:
                # Insert a same-target symlink into the parent path after hashing.
                parent=payload.parent;target=parent.with_name(parent.name+'-moved')
                parent.rename(target);parent.symlink_to(target,target_is_directory=True)
        return result
    implementation._validation_inputs=changing
    with pytest.raises((ValueError,OSError),match='changed|symlink|binding|runtime bytes differ|regular'):
        science.verify_plan(rd,approved=True)


def test_restored_mtime_between_authority_phases_is_rehashed_and_refused(prepared,monkeypatch):
    rd,payload,_,_=prepared;reads,_=capture_reads(monkeypatch,payload)
    science.verify_plan(rd,approved=True);before=payload.stat();raw=payload.read_bytes()
    payload.write_bytes(b'X'+raw[1:]);os.utime(payload,ns=(before.st_atime_ns,before.st_mtime_ns))
    with pytest.raises(ValueError,match='runtime bytes differ'):
        science.verify_plan(rd,approved=True)
    assert len(reads)==2 and reads[0] is not reads[1]


def test_changed_expected_digest_is_checked_even_with_cached_content(prepared):
    rd,payload,inventory,_=prepared
    with pytest.raises(ValueError,match='runtime bytes differ'):
        with science._validation_scope(rd) as session:
            likelihood_parity.runtime_files(inventory,_session=session)
            changed={'schema_version':1,'files':[{'path':str(payload),'sha256':'0'*64}]}
            likelihood_parity.runtime_files(changed,_session=session)


def test_final_census_rejects_same_target_symlink_inserted_after_last_hash(prepared,monkeypatch):
    rd,payload,_,_=prepared;old=ValidationSession.finish;done=[]
    def finish(session):
        if not done:
            done.append(True);target=payload.with_name('same.bin');target.write_bytes(payload.read_bytes())
            payload.unlink();payload.symlink_to(target)
        return old(session)
    monkeypatch.setattr(ValidationSession,'finish',finish)
    with pytest.raises(ValueError,match='symlink|changed'):
        science.verify_plan(rd,approved=True)


def test_legacy_planner_callable_seam_keeps_positional_api(prepared,monkeypatch):
    rd,_,_,_=prepared;original=execution.plan_stage
    def legacy(rd,stage,command,inputs,outputs,parents,cwd):
        return original(rd,stage,command,inputs,outputs,parents,cwd)
    monkeypatch.setattr(execution,'plan_stage',legacy)
    assert science.verify_plan(rd,approved=True)['schema_version']==2


def test_worker_admission_is_one_fresh_boundary_and_checks_process_custody(prepared, monkeypatch):
    rd, payload, _, _ = prepared
    token(rd)
    selected = science.launch_binding(rd, 'science')
    record = execution.begin_attempt(rd, 'science', selected['binding'], selected['stage']['log'])
    record.update(supervisor_pid=os.getppid(), child_pid=os.getpid(),
                  child_identity=execution.process_identity(os.getpid()))
    execution._update(rd, 'science', record)
    reads, sessions = capture_reads(monkeypatch, payload)
    first = science.verify_worker(rd)
    second = science.verify_worker(rd)
    assert first == second and len(reads) == 2 and reads[0] is not reads[1]
    assert all(session.closed for session in sessions)
    record['supervisor_pid'] = os.getpid()
    execution._update(rd, 'science', record)
    with pytest.raises(ValueError, match='current approved supervised attempt'):
        science.verify_worker(rd)


def test_capture_shares_one_observed_transaction_and_closes_its_session(prepared, monkeypatch):
    rd, payload, _, _ = prepared
    token(rd)
    selected = science.launch_binding(rd, 'science')
    context = context_for(selected, rd)
    reads, _ = capture_reads(monkeypatch, payload)
    direct_reads = []
    old_hash = launch_authorization.file_hash
    def hashed(path):
        result = old_hash(path)
        if Path(path) == payload:
            direct_reads.append(path)
        return result
    monkeypatch.setattr(launch_authorization, 'file_hash', hashed)
    captured = launch_authorization._capture_science(rd, 'science', selected['stage']['command'], context)
    assert captured['stage_binding'] == selected['binding']
    assert len(reads) == 1 and reads[0].closed and not reads[0].hashes
    # Ending identity census replaces duplicate content passes only in this call.
    assert len(direct_reads) == 0


def test_last_pre_popen_byte_check_rejects_restored_mtime_mutation(prepared, monkeypatch):
    rd, payload, _, _ = prepared
    token(rd)
    selected = science.launch_binding(rd, 'science')
    context = context_for(selected, rd)
    append = launch_authorization._append
    def changed(root, event):
        result = append(root, event)
        if event['event'] == 'authorized':
            before = payload.stat()
            raw = payload.read_bytes()
            payload.write_bytes(b'X' + raw[1:])
            os.utime(payload, ns=(before.st_atime_ns, before.st_mtime_ns))
        return result
    monkeypatch.setattr(launch_authorization, '_append', changed)
    monkeypatch.setattr(launch_authorization.subprocess, 'Popen', lambda *a, **k: pytest.fail('changed input launched'))
    with pytest.raises(ValueError, match='changed before Popen|artifact identity changed during validation'):
        launch_authorization.authorized_popen(rd, 'science', selected['stage']['command'], context=context)
    assert [event['event'] for event in launch_authorization._events(rd)] == ['authorized']


def test_regular_resolution_is_reused_within_one_call_and_fresh_next_phase(tmp_path,monkeypatch):
    payload=tmp_path/'runtime.bin';payload.write_bytes(b'fresh per phase')
    resolved=[];old=Path.resolve
    def counted(path,*a,**k):
        if path==payload:resolved.append(path)
        return old(path,*a,**k)
    monkeypatch.setattr(Path,'resolve',counted)
    sessions=[]
    for _ in range(2):
        session=execution._validation_session(tmp_path);sessions.append(session)
        for _ in range(8):
            assert science.regular(payload,tmp_path,_session=session)==payload
            assert session.hash_file(payload)==hashlib.sha256(b'fresh per phase').hexdigest()
        assert len(session.regular_resolutions)==1 and session.hash_calls==1
        assert session.finish()==[]
        session.close()
        assert not session.regular_resolutions
    assert len(resolved)==2 and sessions[0] is not sessions[1]


@pytest.mark.parametrize('mutation',['same_size_restored_mtime','replace_same_bytes','remove',
                                     'directory_replacement','symlink_target_drift'])
def test_regular_resolution_reuse_refuses_file_identity_drift_before_hash(tmp_path,mutation):
    directory=tmp_path/'runtime';directory.mkdir();payload=directory/'runtime.bin';payload.write_bytes(b'original')
    session=execution._validation_session(tmp_path)
    science.regular(payload,tmp_path,_session=session);before=payload.stat()
    if mutation=='same_size_restored_mtime':
        payload.write_bytes(b'modified');os.utime(payload,ns=(before.st_atime_ns,before.st_mtime_ns))
    elif mutation=='replace_same_bytes':
        new=tmp_path/'new';new.write_bytes(payload.read_bytes());new.replace(payload)
    elif mutation=='directory_replacement':
        directory.rename(tmp_path/'original-runtime')
        directory.mkdir();payload.write_bytes(b'original')
    elif mutation=='symlink_target_drift':
        target=directory/'original.bin';payload.rename(target);payload.symlink_to(target)
        alternate=directory/'same-bytes.bin';alternate.write_bytes(target.read_bytes())
        payload.unlink();payload.symlink_to(alternate)
    else:payload.unlink()
    with pytest.raises((OSError,ValueError)):
        science.regular(payload,tmp_path,_session=session)
    session.close()


@pytest.mark.parametrize('mutation',['same_target_file_symlink','same_target_parent_symlink'])
def test_cached_resolution_cannot_hide_literal_symlink_from_final_authority_check(tmp_path,mutation):
    directory=tmp_path/'runtime';directory.mkdir();payload=directory/'data.bin';payload.write_bytes(b'original')
    session=execution._validation_session(tmp_path)
    science.regular(payload,tmp_path,_session=session);session.hash_file(payload)
    if mutation=='same_target_file_symlink':
        target=directory/'original.bin';payload.rename(target);payload.symlink_to(target)
    else:
        target=tmp_path/'moved-runtime';directory.rename(target);directory.symlink_to(target,target_is_directory=True)
    # Target bytes and inode may remain the same; the ending literal path contract
    # must still fail before authority returns, rather than trust that cached target.
    errors=session.finish()
    assert errors and any('symlink' in error for error in errors)
    session.close()


@pytest.mark.parametrize('mutation',['add_file','add_empty_directory','directory_replacement'])
def test_regular_resolution_reuse_preserves_final_directory_membership_check(tmp_path,mutation):
    directory=tmp_path/'runtime';directory.mkdir();payload=directory/'data.bin';payload.write_bytes(b'original')
    session=execution._validation_session(tmp_path)
    science.regular(payload,tmp_path,_session=session);session.hash_file(payload)
    session.require_inventory(directory)
    # A cache hit remains observational: it cannot authorize against this old
    # directory census after a new member or same-content replacement appears.
    assert science.regular(payload,tmp_path,_session=session)==payload
    if mutation=='add_file':(directory/'unexpected.bin').write_bytes(b'new')
    elif mutation=='add_empty_directory':(directory/'unexpected').mkdir()
    else:
        directory.rename(tmp_path/'old-runtime');directory.mkdir();payload.write_bytes(b'original')
    errors=session.finish()
    assert errors and any('inventory changed' in error for error in errors)
    assert session.closed and not session.regular_resolutions


def test_new_phase_rehashes_mutated_bytes_and_closed_resolution_refuses_use(tmp_path):
    payload=tmp_path/'runtime.bin';payload.write_bytes(b'original')
    inventory={'schema_version':1,'files':[{'path':str(payload),'sha256':hashlib.sha256(b'original').hexdigest()}]}
    first=execution._validation_session(tmp_path)
    assert likelihood_parity.runtime_files(inventory,_session=first)==[payload]
    assert first.finish()==[];first.close()
    before=payload.stat();payload.write_bytes(b'modified');os.utime(payload,ns=(before.st_atime_ns,before.st_mtime_ns))
    with pytest.raises(ValueError,match='closed'):science.regular(payload,tmp_path,_session=first)
    second=execution._validation_session(tmp_path)
    with pytest.raises(ValueError,match='runtime bytes differ'):
        likelihood_parity.runtime_files(inventory,_session=second)
    assert second.hash_calls==1;second.close()
