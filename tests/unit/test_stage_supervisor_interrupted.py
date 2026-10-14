"""Modeled recovery only; all process inspection/signal/runtime operations are inert."""
from copy import deepcopy
import hashlib, json, os
from pathlib import Path
import pytest
from ravel.workflow import execution, science, stage_supervisor as s
from test_stage_supervisor_container_recovery import control, prepare


@pytest.fixture
def stopped(tmp_path, monkeypatch):
    root = tmp_path
    directory = root/'logs/execution/science'/('a'*32)
    directory.mkdir(parents=True)
    record = {'stage':'science','attempt_id':'a'*32,'attempt_record':str((directory/'record.json').relative_to(root)),
              'status':'running','child_pid':34567,'child_identity':'original-owned-start',
              'supervisor_pid':11111,'command':['NO-SCIENCE'],'inputs':[], 'outputs':['outputs/attempt-1'],
              'fingerprint':'f'*64,'started_utc':'retained-original-start','log':'logs/science.log',
              'original_scientific_diagnostics':{'native_vectors_returned':0,'nll':None}}
    execution._update(root,'science',record)
    out = root/'outputs/attempt-1';out.mkdir(parents=True)
    (out/'partial.json').write_text('{"status":"incomplete","fit":null}\n')
    token = b'{"attempt":1,"budget_seconds":110,"plan_sha256":"original"}\n'
    (root/'execution_attempt.json').write_bytes(token)
    attempts=root/'logs/science-attempts';attempts.mkdir()
    (attempts/'00000001.json').write_bytes(token)
    (root/'inputs').mkdir();(root/'inputs/science-approval.json').write_text('{"machine_approval":true}\n')
    monkeypatch.setattr(execution,'process_identity',lambda pid:None)
    monkeypatch.setattr(execution,'process_group_members',lambda pid:[])
    def absent(pid, sig):
        assert pid == 34567 and sig == 0
        raise ProcessLookupError('modeled absent leader')
    monkeypatch.setattr(s.os,'kill',absent)
    monkeypatch.setattr(s.os,'killpg',lambda *a:pytest.fail('recovery signalled a process'))
    monkeypatch.setattr(s.os,'getpgid',lambda *a:pytest.fail('absent leader has no getpgid observation'))
    monkeypatch.setattr(s.subprocess,'Popen',lambda *a,**k:pytest.fail('recovery launched a worker'))
    monkeypatch.setattr(s.subprocess,'run',lambda *a,**k:pytest.fail('recovery launched a command'))
    monkeypatch.setattr(execution,'begin_attempt',lambda *a,**k:pytest.fail('negative finalization creates attempt'))
    return root, record


def current(root):return execution.load_execution(root)['stages']['science']

def artifacts(root):
    paths=[root/'execution_attempt.json',root/'logs/science-attempts/00000001.json',
           root/'inputs/science-approval.json',root/'outputs/attempt-1/partial.json']
    return {str(p.relative_to(root)):p.read_bytes() for p in paths}


def test_absent_leader_group_fails_but_preserves_spent_attempt_and_full_snapshot(stopped):
    root, prior = stopped
    original=(root/prior['attempt_record']).read_bytes();protected=artifacts(root)
    with pytest.raises(ValueError,match='recovery remains held'):
        s.recover_previous_attempt(root,'science',grace=2)
    got=current(root); marker=got['interrupted_finalization'];pin=marker['preterminal']
    assert got['status']=='failed' and got['exit_code']==130
    assert got['cleanup']['requires_recovery'] is True
    assert got['cleanup']['group_state']=='empty'
    assert marker['descendant_containment']=='not_established' and marker['scientific_acceptance'] is False
    assert 'receipt_sha256' not in got and 'output_snapshot' not in got
    assert got['original_scientific_diagnostics']==prior['original_scientific_diagnostics']
    assert got['started_utc']==prior['started_utc'] and got['attempt_id']==prior['attempt_id']
    assert (root/pin['path']).read_bytes()==original
    assert pin=={'path':pin['path'],'sha256':hashlib.sha256(original).hexdigest(),'size':len(original)}
    assert json.loads(original)==prior
    assert (root/pin['path']).stat().st_mode & 0o222==0
    assert artifacts(root)==protected


def test_repeated_recover_and_public_resume_cannot_clear_hold_or_reset_budget(stopped,monkeypatch):
    root,_=stopped
    with pytest.raises(ValueError,match='held'):s.recover_previous_attempt(root,'science')
    state=(root/'execution_state.json').read_bytes();protected=artifacts(root)
    monkeypatch.setattr(execution,'process_group_members',lambda pid:pytest.fail('durable hold queried PID again'))
    monkeypatch.setattr(science,'verify_plan',lambda *a,**k:pytest.fail('held attempt reached new admission'))
    monkeypatch.setattr(science,'approve',lambda *a,**k:pytest.fail('recovery changes approval'))
    for _ in range(3):
        with pytest.raises(ValueError,match='held'):s.recover_previous_attempt(root,'science')
        with pytest.raises(ValueError,match='held'):science.run(root,resume=True)
    assert (root/'execution_state.json').read_bytes()==state
    assert artifacts(root)==protected
    assert sorted(p.name for p in (root/'logs/science-attempts').iterdir())==['00000001.json']


def test_cleanup_boolean_alone_is_not_descendant_resolution(stopped):
    root,_=stopped
    with pytest.raises(ValueError):s.recover_previous_attempt(root,'science')
    old=current(root);old['cleanup']['requires_recovery']=False;execution._update(root,'science',old)
    with pytest.raises(ValueError,match='recovery remains held'):s.recover_previous_attempt(root,'science')
    assert current(root)['interrupted_finalization']['requires_recovery'] is True


@pytest.mark.parametrize('defect',['missing','changed','symlink'])
def test_snapshot_custody_drift_never_releases_hold(stopped,defect):
    root,_=stopped
    with pytest.raises(ValueError):s.recover_previous_attempt(root,'science')
    pin=current(root)['interrupted_finalization']['preterminal'];p=root/pin['path']
    raw=p.read_bytes();p.unlink()
    if defect=='changed':p.write_bytes(raw+b' ')
    if defect=='symlink':
        replacement=root/'replacement.json';replacement.write_bytes(raw);p.symlink_to(replacement)
    with pytest.raises((ValueError,OSError)):s.recover_previous_attempt(root,'science')
    assert current(root)['status']=='failed' and current(root)['cleanup']['requires_recovery'] is True


@pytest.mark.parametrize('state',['missing_pid','unreadable','reused','wrong_group','group_unknown','active_leaderless'])
def test_uncertain_ownership_is_held_without_signal_or_false_negative_finalization(stopped,monkeypatch,state):
    root,old=stopped
    if state=='missing_pid':
        old.update(child_pid=None,child_identity=None);execution._update(root,'science',old)
    if state=='unreadable':monkeypatch.setattr(s.os,'kill',lambda *a:None)
    if state=='reused':monkeypatch.setattr(execution,'process_identity',lambda pid:'new-unrelated-start')
    if state=='wrong_group':
        monkeypatch.setattr(execution,'process_identity',lambda pid:'original-owned-start')
        monkeypatch.setattr(s.os,'getpgid',lambda pid:pid+1)
    if state=='group_unknown':
        def unknown(pid):raise PermissionError('modeled inaccessible census')
        monkeypatch.setattr(execution,'process_group_members',unknown)
    if state=='active_leaderless':monkeypatch.setattr(execution,'process_group_members',lambda pid:[pid+1])
    before=artifacts(root)
    with pytest.raises((ValueError,PermissionError)):s.recover_previous_attempt(root,'science')
    got=current(root)
    assert 'interrupted_finalization' not in got and artifacts(root)==before
    assert not (root/Path(old['attempt_record']).parent/'interrupted-preterminal.json').exists()
    if state!='active_leaderless':assert got['status']=='running'
    else:assert got['status']=='failed' and got['cleanup']['requires_recovery']


def test_terminal_failure_with_empty_group_retains_legacy_recovery_behavior(stopped):
    root,old=stopped
    old.update(status='failed',exit_code=124,error='original-wall-clock',
        cleanup={'requires_recovery':True,'process_group':34567,'group_state':'active'})
    execution._update(root,'science',old);before=(root/'execution_state.json').read_bytes()
    s.recover_previous_attempt(root,'science')
    assert (root/'execution_state.json').read_bytes()==before
    assert 'interrupted_finalization' not in current(root)


@pytest.mark.parametrize('defect',['record_mismatch','namespace','existing_snapshot','snapshot_write','snapshot_after_write','oversized','symlink'])
def test_metadata_commitment_failures_do_not_manufacture_terminal_success(stopped,monkeypatch,defect):
    root,old=stopped;p=root/old['attempt_record']
    if defect=='record_mismatch':p.write_text(json.dumps({**old,'fingerprint':'changed'}))
    if defect=='namespace':
        old['attempt_record']='logs/wrong/record.json';execution._update(root,'science',old)
    if defect=='existing_snapshot':(p.parent/'interrupted-preterminal.json').write_text('{"foreign":true}')
    if defect=='oversized':monkeypatch.setattr(s,'INTERRUPTED_RECORD_MAX_BYTES',4)
    if defect=='symlink':
        raw=p.read_bytes();p.unlink();copy=root/'record-copy.json';copy.write_bytes(raw);p.symlink_to(copy)
    real_open=Path.open
    def sabotage(path,*a,**k):
        if path.name=='interrupted-preterminal.json' and a==('xb',):
            if defect=='snapshot_write':raise PermissionError('modeled snapshot cannot persist')
            stream=real_open(path,*a,**k)
            class Wrapper:
                def __enter__(self):return self
                def write(self,raw):return stream.write(raw+b' ')
                def flush(self):return stream.flush()
                def fileno(self):return stream.fileno()
                def __exit__(self,*args):return stream.__exit__(*args)
            return Wrapper()
        return real_open(path,*a,**k)
    if defect in ('snapshot_write','snapshot_after_write'):monkeypatch.setattr(Path,'open',sabotage)
    with pytest.raises((ValueError,OSError)):s.recover_previous_attempt(root,'science')
    assert current(root)['status']=='running' and 'interrupted_finalization' not in current(root)


def test_exact_preterminal_snapshot_can_complete_after_metadata_only_write_interruption(stopped):
    root,old=stopped;p=root/old['attempt_record'];saved=p.parent/'interrupted-preterminal.json'
    saved.write_bytes(p.read_bytes());saved.chmod(0o444)
    with pytest.raises(ValueError,match='recovery remains held'):s.recover_previous_attempt(root,'science')
    assert current(root)['status']=='failed'


def test_guest_unresolved_barrier_prevents_new_negative_finalization(stopped,monkeypatch):
    root,_=stopped
    def guest(root,stage):raise ValueError('previous owned container unresolved; stage held')
    monkeypatch.setattr(s,'_recover_container_orphan',guest)
    with pytest.raises(ValueError,match='container unresolved'):s.recover_previous_attempt(root,'science')
    assert current(root)['status']=='running' and 'interrupted_finalization' not in current(root)


def test_known_owned_guest_absence_is_not_full_host_descendant_containment(control,monkeypatch):
    v=control;prepare(v)
    v.record.update(child_pid=99999,child_identity='original-host');execution._update(v.root,'science',v.record)
    monkeypatch.setattr(execution,'process_identity',lambda pid:None)
    monkeypatch.setattr(s.os,'kill',lambda pid,sig:(_ for _ in ()).throw(ProcessLookupError()))
    with pytest.raises(ValueError,match='recovery remains held'):s.recover_previous_attempt(v.root,'science',grace=2)
    assert v.stop and not v.launches
    got=current(v.root)
    assert got['status']=='failed' and got['container_cleanup']['requires_recovery'] is False
    assert got['interrupted_finalization']['requires_recovery'] and got['cleanup']['requires_recovery']


def test_existing_diagnostics_and_cleanup_observations_are_retained(stopped):
    root,old=stopped
    old['cleanup']={'requires_recovery':False,'signals':[{'signal':'SIGTERM','outcome':'sent'}],
        'errors':[{'operation':'earlier','message':'preserved'}],'original_census_note':'retained'}
    execution._update(root,'science',old)
    with pytest.raises(ValueError,match='recovery remains held'):s.recover_previous_attempt(root,'science')
    got=current(root)
    assert got['cleanup']['signals']==old['cleanup']['signals']
    assert got['cleanup']['errors']==old['cleanup']['errors']
    assert got['cleanup']['original_census_note']=='retained'
    assert got['cleanup']['recovery_signals']==[]


def test_ledger_stage_identity_mismatch_cannot_finalize_another_stage(stopped):
    root,old=stopped
    old['stage']='fit';execution._update(root,'science',old)
    with pytest.raises(ValueError,match='namespace differs|stage identity differs'):s.recover_previous_attempt(root,'science')
    assert current(root)['status']=='running'
