"""Actual producer persistence and pre-read budget boundaries; no native calls."""
import hashlib,json,os
from pathlib import Path
import pytest
from ravel.physics import analysis_ir, sfitter_observed_events as o, sfitter_scan_extraction as e
from ravel.workflow import state_io
from ravel.validation import analysis_witness
from test_sfitter_observed_events import fixture
from test_sfitter_adapter import pin

@pytest.mark.parametrize('member',['analysis-witness/program.json','analysis-witness/manifest.json',
                                  'analysis-witness/verify.py','sfitter-observation-producer.json'])
def test_every_late_generated_member_remains_bound(tmp_path,monkeypatch,member):
    base,request,rp,_,_,_,task,_=fixture(tmp_path)
    real=o._write;out=tmp_path/'late'
    def changed(path,value,capture):
        result=real(path,value,capture)
        if Path(path).name=='sfitter-observation-producer.json':
            target=out/member;target.write_bytes(target.read_bytes()+b'\n ')
        return result
    monkeypatch.setattr(o,'_write',changed)
    with pytest.raises(ValueError):analysis_ir.run(task,base,out)
    assert (out/member).read_bytes().endswith(b'\n ')

@pytest.mark.parametrize('addition',['unindexed.txt','empty-directory'])
def test_ending_closed_population_comes_from_commitments(tmp_path,monkeypatch,addition):
    base,_,_,_,_,_,task,_=fixture(tmp_path);out=tmp_path/'added';real=o._write
    def changed(path,value,capture):
        result=real(path,value,capture)
        if Path(path).name=='sfitter-observation-producer.json':
            p=out/addition
            p.mkdir() if addition=='empty-directory' else p.write_text('retained unknown scientific output')
        return result
    monkeypatch.setattr(o,'_write',changed)
    with pytest.raises(ValueError,match='membership'):analysis_ir.run(task,base,out)
    assert (out/addition).exists()

@pytest.mark.parametrize('member',['program.json','trace.json','manifest.json','verification.json'])
def test_immediate_replay_write_matches_intended_serialized_bytes(tmp_path,monkeypatch,member):
    base,_,_,_,_,_,task,_=fixture(tmp_path);out=tmp_path/'immediate';real=state_io.atomic_json
    def changed(path,value):
        real(path,value)
        if Path(path).name==member:Path(path).write_bytes(Path(path).read_bytes()+b'\n ')
    monkeypatch.setattr(state_io,'atomic_json',changed)
    with pytest.raises(ValueError):analysis_ir.run(task,base,out)
    assert (out/'analysis-witness'/member).read_bytes().endswith(b'\n ')
    assert not (out/'sfitter-observation-producer.json').exists()

def test_failed_verification_checks_its_output_population(tmp_path,monkeypatch):
    base,_,_,_,_,_,task,_=fixture(tmp_path);out=tmp_path/'failed'
    real=analysis_witness.verify_bundle
    def failed(root):
        result=real(root);result['status']='failed';return result
    monkeypatch.setattr(analysis_witness,'verify_bundle',failed)
    returned=analysis_ir.run(task,base,out)
    assert returned['status']=='failed'
    assert json.loads((out/'analysis-witness/verification.json').read_bytes())['status']=='failed'
    assert not (out/'sfitter-observation-producer.json').exists()

def test_exception_path_checks_previously_committed_outputs(tmp_path,monkeypatch):
    base,_,_,_,_,_,task,_=fixture(tmp_path);out=tmp_path/'exception';real=o.emit_ir
    def failed(*args,**kwargs):
        real(*args,**kwargs)
        p=out/'analysis-witness/trace.json';p.write_bytes(p.read_bytes()+b'\n ')
        raise RuntimeError('synthetic callback failure after original trace commitment')
    monkeypatch.setattr(o,'emit_ir',failed)
    with pytest.raises(ValueError):analysis_ir.run(task,base,out)
    assert (out/'analysis-witness/trace.json').read_bytes().endswith(b'\n ')
    assert not (out/'sfitter-observation-producer.json').exists()

def test_input_recheck_callback_cannot_mutate_last_emitted_population(tmp_path,monkeypatch):
    base,_,_,_,_,_,task,_=fixture(tmp_path);out=tmp_path/'after-input-recheck'
    real=o.StreamCapture.finish
    def changed(capture):
        real(capture)
        if (out/'sfitter-observation-producer.json').exists():
            p=out/'sfitter-bin-observations.jsonl';p.write_bytes(p.read_bytes()+b'\n ')
    monkeypatch.setattr(o.StreamCapture,'finish',changed)
    with pytest.raises(ValueError):analysis_ir.run(task,base,out)
    assert (out/'sfitter-bin-observations.jsonl').read_bytes().endswith(b'\n ')

def test_aggregate_budget_refuses_before_actual_open_and_keeps_duplicates(tmp_path,monkeypatch):
    monkeypatch.setattr(e,'MAX_SOURCE_BYTES',10)
    a=tmp_path/'a';a.write_bytes(b'1234567');b=tmp_path/'b';b.write_bytes(b'1234')
    wanted_a,wanted_b=pin(a),pin(b)
    original=Path.open;reads=[]
    def observed(path,*args,**kwargs):
        if args and args[0]=='rb':reads.append(str(path))
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',observed)
    c=e._SourceCapture();c.pin(wanted_a,tmp_path);c.pin(wanted_a,tmp_path)
    with pytest.raises(ValueError,match='aggregate byte ceiling'):c.pin(wanted_b,tmp_path)
    assert str(b) not in reads, 'oversized unique payload must not open for capture'
    assert len(c.files)==1 and sum(len(x[1]) for x in c.files.values())==7
    assert reads.count(str(a))>=2

def test_exact_aggregate_boundary_is_admitted(tmp_path,monkeypatch):
    monkeypatch.setattr(e,'MAX_SOURCE_BYTES',10)
    a=tmp_path/'a';a.write_bytes(b'1234567');b=tmp_path/'b';b.write_bytes(b'123')
    c=e._SourceCapture();c.pin(pin(a),tmp_path);c.pin(pin(b),tmp_path);c.finish()
    assert sum(len(x[1]) for x in c.files.values())==10

def test_post_stat_replacement_refuses_before_read(tmp_path,monkeypatch):
    p=tmp_path/'source';p.write_bytes(b'1234');wanted=pin(p);original=Path.open;read_calls=[]
    class Tracked:
        def __init__(self,stream):self.stream=stream
        def __enter__(self):self.stream.__enter__();return self
        def __exit__(self,*args):return self.stream.__exit__(*args)
        def fileno(self):return self.stream.fileno()
        def read(self,n):read_calls.append(n);return self.stream.read(n)
    def swapped(path,*args,**kwargs):
        if Path(path)==p and args and args[0]=='rb':
            alternate=tmp_path/'replacement';alternate.write_bytes(b'12345');os.replace(alternate,p)
            return Tracked(original(path,*args,**kwargs))
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',swapped)
    with pytest.raises(ValueError,match='replaced before capture'):e._SourceCapture().pin(wanted,tmp_path)
    assert read_calls==[]

def test_actual_bounded_read_retains_descriptor_drift_refusal(tmp_path,monkeypatch):
    p=tmp_path/'source';p.write_bytes(b'1234');wanted=pin(p);original=Path.open;read_limits=[]
    monkeypatch.setattr(e,'MAX_SOURCE_BYTES',4)
    class Tracked:
        def __init__(self,stream):self.stream=stream
        def __enter__(self):self.stream.__enter__();return self
        def __exit__(self,*args):return self.stream.__exit__(*args)
        def fileno(self):return self.stream.fileno()
        def read(self,n):
            read_limits.append(n)
            with original(p,'ab') as changed:changed.write(b'5')
            return self.stream.read(n)
    def changed(path,*args,**kwargs):
        stream=original(path,*args,**kwargs)
        return Tracked(stream) if Path(path)==p and args and args[0]=='rb' else stream
    monkeypatch.setattr(Path,'open',changed)
    with pytest.raises(ValueError,match='changed during capture'):e._SourceCapture().pin(wanted,tmp_path)
    assert read_limits==[5]


from ravel.physics import sfitter_observed_events as observed

@pytest.mark.parametrize('phase',['producer_commit','final_input_check'])
def test_absent_output_root_cannot_skip_final_custody(tmp_path,monkeypatch,phase):
 base,_,_,_,_,_,task,_=fixture(tmp_path)
 out=tmp_path/'live';moved=tmp_path/'retained-moved-output'
 realwrite=o._write;realfinish=o.StreamCapture.finish
 def move_after_commit(path,value,capture):
  result=realwrite(path,value,capture)
  if phase=='producer_commit' and Path(path).name=='sfitter-observation-producer.json':os.rename(out,moved)
  return result
 def move_during_input_finish(capture):
  realfinish(capture)
  if phase=='final_input_check' and (out/'sfitter-observation-producer.json').exists():os.rename(out,moved)
 monkeypatch.setattr(o,'_write',move_after_commit)
 monkeypatch.setattr(o.StreamCapture,'finish',move_during_input_finish)
 with pytest.raises(ValueError):
  returned=analysis_ir.run(task,base,out)
  (tmp_path/'unexpected-passed-return.json').write_text(json.dumps(returned,indent=2))
 assert not out.exists() and (moved/'sfitter-observation-producer.json').exists()

@pytest.mark.parametrize('amount',[9,10,11])
def test_budget_actual_read_admission_boundaries(tmp_path,monkeypatch,amount):
 monkeypatch.setattr(e,'MAX_SOURCE_BYTES',10)
 a=tmp_path/'a';a.write_bytes(b'1234567');b=tmp_path/'b';b.write_bytes(b'x'*(amount-7))
 wanted_a,wanted_b=pin(a),pin(b);real=Path.open;opened=[]
 def tracking(p,*args,**kwargs):
  if p==b and args==('rb',):opened.append(str(p))
  return real(p,*args,**kwargs)
 monkeypatch.setattr(Path,'open',tracking)
 cap=e._SourceCapture();cap.pin(wanted_a,tmp_path)
 if amount>10:
  with pytest.raises(ValueError,match='aggregate byte ceiling'):cap.pin(wanted_b,tmp_path)
  assert opened==[]
 else:
  cap.pin(wanted_b,tmp_path);cap.pin(wanted_a,tmp_path);cap.finish()
  assert sum(len(raw) for _,raw in cap.files.values())==amount


def test_success_checks_committed_original_output_paths(tmp_path):
    base, _, _, _, _, _, task, _ = fixture(tmp_path)
    out = tmp_path / 'successful'
    returned = analysis_ir.run(task, base, out)
    assert returned['status'] == 'passed'
    observation = returned['sfitter_observation']
    trace = Path(observation['trace']['path'])
    assert trace == out / 'sfitter-bin-observations.jsonl'
    assert hashlib.sha256(trace.read_bytes()).hexdigest() == observation['trace']['sha256']
    assert json.loads((out / 'sfitter-observation-producer.json').read_bytes()) == observation
    assert json.loads((out / 'analysis-witness/verification.json').read_bytes())['status'] == 'passed'


def test_pre_output_failure_retains_primary_diagnostic_and_missing_root(tmp_path, monkeypatch):
    base, _, _, _, _, _, task, _ = fixture(tmp_path)
    out = tmp_path / 'never-created'
    primary = RuntimeError('original scientific callback failed before any emitted output')
    def fail_before_output(*args, **kwargs):
        raise primary
    monkeypatch.setattr(analysis_ir, 'write_bundle', fail_before_output)
    with pytest.raises(ValueError) as caught:
        analysis_ir.run(task, base, out)
    assert caught.value.__cause__ is primary
    assert str(primary) in str(caught.value)
    assert 'ending producer custody refused' in str(caught.value)
    assert not out.exists(), 'ending custody must never recreate the absent root'


def test_input_failure_before_output_setup_keeps_original_exception(tmp_path, monkeypatch):
    base, _, _, _, _, _, task, _ = fixture(tmp_path)
    out = tmp_path / 'input-failed'
    primary = ValueError('original source intake failed before output capture setup')
    def fail_intake(*args, **kwargs):
        raise primary
    monkeypatch.setattr(analysis_ir, 'inputs', fail_intake)
    with pytest.raises(ValueError) as caught:
        analysis_ir.run(task, base, out)
    assert caught.value is primary
    assert caught.value.__cause__ is None
    assert not out.exists()


def test_secondary_output_loss_keeps_original_failure_and_relocated_bytes(tmp_path, monkeypatch):
    base, _, _, _, _, _, task, _ = fixture(tmp_path)
    out = tmp_path / 'failed-output'
    moved = tmp_path / 'retained-failed-output'
    real = observed.emit_ir
    primary = RuntimeError('original scientific join callback failed after committed output')
    def fail_with_loss(*args, **kwargs):
        real(*args, **kwargs)
        out.rename(moved)
        raise primary
    monkeypatch.setattr(observed, 'emit_ir', fail_with_loss)
    with pytest.raises(ValueError) as caught:
        analysis_ir.run(task, base, out)
    assert caught.value.__cause__ is primary
    assert str(primary) in str(caught.value)
    assert 'ending producer custody refused' in str(caught.value)
    assert not out.exists()
    assert (moved / 'sfitter-bin-observations.jsonl').is_file()
    assert (moved / 'analysis-witness/verification.json').is_file()

