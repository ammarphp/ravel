from pathlib import Path
import json,sys,time
import pytest
from ravel.workflow import historical_qualification as h

def test_append_only_explicit_phases_show_last_started_work(tmp_path):
    h._phase_progress(tmp_path,'child_enter',time.monotonic());first=(tmp_path/'phase-progress.jsonl').read_bytes()
    h._phase_progress(tmp_path,'old_snapshot_begin',time.monotonic())
    raw=(tmp_path/'phase-progress.jsonl').read_bytes();assert raw.startswith(first)
    rows=[json.loads(r) for r in raw.splitlines()];assert [r['sequence'] for r in rows]==[1,2]
    assert rows[-1]['phase']=='old_snapshot_begin' and rows[-1]['scientific_calls']==0
    assert 'no admission' in rows[-1]['scope']

@pytest.mark.parametrize('case',['unknown','duplicate','oversize','incomplete','leaf_symlink','ancestor_symlink'])
def test_bounded_ordinary_progress_refuses_ambiguous_history(tmp_path,case):
    out=tmp_path/'out';out.mkdir();p=out/'phase-progress.jsonl';phase='child_enter'
    if case=='unknown':phase='invented-success'
    elif case=='duplicate':h._phase_progress(out,phase,time.monotonic())
    elif case=='oversize':p.write_bytes(b'x'*(h.PHASE_PROGRESS_MAX_BYTES+1))
    elif case=='incomplete':p.write_bytes(b'{')
    elif case=='leaf_symlink':p.symlink_to(tmp_path/'missing')
    else:out.rename(tmp_path/'real');out.symlink_to(tmp_path/'real',target_is_directory=True)
    with pytest.raises((ValueError,FileExistsError)):h._phase_progress(out,phase,time.monotonic())

@pytest.mark.parametrize('returncode',[None,0,7,-15])
def test_actual_child_poll_retained_without_quiescence_or_admission(tmp_path,returncode):
    class Child:
        pid=123
        def poll(self):return returncode
    pin=h._child_observation(tmp_path,Child(),'metadata_wall_seconds',time.monotonic())
    row=json.loads(Path(pin['path']).read_text());assert row['observed_returncode'] is returncode or row['observed_returncode']==returncode
    assert row['exhausted']=='metadata_wall_seconds' and 'no quiescence' in row['scope']



def test_real_child_entry_progress_survives_original_import_guard(tmp_path,monkeypatch):
    monkeypatch.setitem(sys.modules,'ravel',object())
    with pytest.raises(ValueError,match='Already loaded ravel'):
        h._historical_child({},tmp_path)
    rows=[json.loads(line) for line in (tmp_path/'phase-progress.jsonl').read_bytes().splitlines()]
    assert [row['phase'] for row in rows]==['child_enter']
    assert not (tmp_path/'child-validation.json').exists()


def test_parent_retains_observed_failure_even_when_closure_raises(tmp_path,monkeypatch):
    out=tmp_path/'gate'
    contract={'old_runtime':{'environment':{},'cwd':str(tmp_path),'interpreter_invocation':sys.executable,'interpreter_binary':{'path':'supplied-binary','sha256':'a'*64}}}
    route={'key':'preparation','contract_sha256':h.digest(contract),'helper_source':h.pin(Path(h.__file__).resolve()),'request_root':str(out),'interpreter_binary':contract['old_runtime']['interpreter_binary'],'interpreter_invocation':sys.executable}
    class Registration:
        KEY_ENV='TEST_KEY';DEADLINE_ENV='TEST_DEADLINE'
        digest=staticmethod(h.digest)
        @staticmethod
        def wait_closed(key,deadline):raise TimeoutError('synthetic closure missing DONE')
    class Child:
        pid=123;returncode=7
        def poll(self):return 7
    monkeypatch.setattr(h,'_registration_module',lambda:(Registration,{'declaration':{'helpers':[route]}}))
    monkeypatch.setattr(h,'_check_sources',lambda c:None)
    monkeypatch.setattr(h.subprocess,'Popen',lambda *a,**k:Child())
    with pytest.raises(TimeoutError,match='missing DONE'):h.validate_historical(contract,out)
    refusal=json.loads((out/'refusal.json').read_text());observation=json.loads((out/'child-observation.json').read_text())
    assert refusal['child_observed_returncode']==observation['observed_returncode']==7
    assert refusal['admitted'] is False and refusal['outer_cleanup_pending'] is False
    assert not (out/'validation-receipt.json').exists()


@pytest.mark.parametrize('existing',[False,True])
def test_observed_prior_log_identity_required_before_append(tmp_path,monkeypatch,existing):
    path=tmp_path/'phase-progress.jsonl'
    if existing:h._phase_progress(tmp_path,'child_enter',time.monotonic())
    original=h.os.open
    def replacing(p,*a,**k):
        if Path(p)==path:
            if existing:
                old=path.read_bytes();path.unlink();path.write_bytes(old)
            else:path.write_bytes(b'')
        return original(p,*a,**k)
    monkeypatch.setattr(h.os,'open',replacing)
    with pytest.raises((ValueError,FileExistsError)):h._phase_progress(tmp_path,'old_snapshot_begin',time.monotonic())

@pytest.mark.parametrize('include',[False,True])
def test_optional_diagnostic_pins_in_complete_ordinary_input_graph(tmp_path,monkeypatch,include):
    names=['request','started','child_started','stdout','stderr','child_validation']+(['child_observation','phase_progress'] if include else [])
    receipt={k:{'path':str(tmp_path/k),'sha256':'a'*64} for k in names}
    p=tmp_path/'receipt.json';p.write_text(json.dumps(receipt))
    monkeypatch.setattr(h,'verify_receipt',lambda *a:{'custody_pins':[]})
    result=h.inputs({},h.pin(p));assert set(result)=={p,*[tmp_path/n for n in names]}
