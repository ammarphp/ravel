"""Per-call validation of receipt DAGs and adversarial file replacement controls."""
from pathlib import Path
import copy
import json
import os
import pytest
from ravel.workflow import execution as e
from ravel.workflow.validation_io import ValidationSession

@pytest.fixture(autouse=True)
def runtime(monkeypatch):monkeypatch.setattr(e,'runtime_context',lambda:{'context':'inert-current'})


def seal(rec):
 rec['fingerprint']=e.digest({k:rec[k]for k in('command','cwd','inputs','outputs','input_snapshot','parents','runtime')});rec['receipt_sha256']=e.digest({k:rec[k]for k in('fingerprint','output_snapshot')})


def save(run,state):(run/e.STATE_NAME).write_text(json.dumps(state))


def chain(tmp_path,n=4,directory=False):
 run=tmp_path/'run';run.mkdir();shared=run/'shared.dat';shared.write_bytes(b's'*8192);stages={};plan=[]
 for i in range(n):
  name='s'+str(i);out=run/('artifact'+str(i))
  if directory:out.mkdir();(out/'data.dat').write_bytes(bytes([65+i])*1024)
  else:out.write_bytes(bytes([65+i])*1024)
  ins=[str(shared)]+([str(run/('artifact'+str(i-1)))]if i else []);outs=[str(out)];parents={'s'+str(i-1):stages['s'+str(i-1)]['receipt_sha256']}if i else {}
  rec={'command':['inert',name],'cwd':str(run),'inputs':ins,'outputs':outs,'input_snapshot':e.snapshot(run,ins),'parents':parents,'runtime':e.runtime_context(),'output_snapshot':e.snapshot(run,outs,outputs=True),'status':'succeeded'};seal(rec);stages[name]=rec
  plan.append({'stage':name,'command':['inert',name],'cwd':str(run),'inputs':ins.copy(),'outputs':outs.copy(),'depends_on':list(parents)})
 state={'schema_version':1,'revision':n,'stages':stages};save(run,state);return run,plan,state


def test_one_hash_per_identity_and_stage_per_call(tmp_path,monkeypatch):
 run,plan,state=chain(tmp_path,12);seen=[];old=e._validation_session
 def capture(*a):s=old(*a);seen.append(s);return s
 monkeypatch.setattr(e,'_validation_session',capture)
 for _ in range(2):assert e.validate_completed_execution(run,plan)==[]
 assert len(seen)==2
 for s in seen:
  assert s.hash_calls==14 and s.hash_bytes==8192+12*1024+(run/e.STATE_NAME).stat().st_size
  assert s.closed and not s.hashes and not s.stages


@pytest.mark.parametrize('entry',['stage','execution','completed'])
def test_changed_content_same_size_mtime_rejects(tmp_path,entry):
 run,plan,state=chain(tmp_path);p=run/'shared.dat';old=p.stat();p.write_bytes(b'x'*8192);os.utime(p,ns=(old.st_atime_ns,old.st_mtime_ns))
 result=e.stage_errors(run,'s3')if entry=='stage'else e.validate_execution(run)if entry=='execution'else e.validate_completed_execution(run,plan)
 assert result and any('inputs changed'in x for x in result)


def finishing(monkeypatch,action):
 old=ValidationSession.finish
 def new(self):action();return old(self)
 monkeypatch.setattr(ValidationSession,'finish',new)


@pytest.mark.parametrize('case',['same_size_mtime','replace_same_bytes','remove','add_file','add_empty_dir','add_symlink','replace_output_symlink','ledger_replace','ledger_content','runtime_failure','runtime_changed','plan_changed','census_failure'])
def test_late_drift_and_failed_census_rejects(tmp_path,monkeypatch,case):
 run,plan,state=chain(tmp_path,directory=True);p=run/'artifact0/data.dat';st=p.stat()
 def action():
  if case=='same_size_mtime':p.write_bytes(b'z'*1024);os.utime(p,ns=(st.st_atime_ns,st.st_mtime_ns))
  elif case=='replace_same_bytes':
   q=run/'replacement';q.write_bytes(p.read_bytes());os.utime(q,ns=(st.st_atime_ns,st.st_mtime_ns));q.replace(p)
  elif case=='remove':p.unlink()
  elif case=='add_file':(p.parent/'new.dat').write_bytes(b'new')
  elif case=='add_empty_dir':(p.parent/'empty').mkdir()
  elif case=='add_symlink':(p.parent/'link').symlink_to(run/'shared.dat')
  elif case=='replace_output_symlink':p.unlink();p.symlink_to(run/'shared.dat')
  elif case=='ledger_replace':
   q=run/'new-ledger';q.write_bytes((run/e.STATE_NAME).read_bytes());q.replace(run/e.STATE_NAME)
  elif case=='ledger_content':z=copy.deepcopy(state);z['revision']+=1;save(run,z)
  elif case=='runtime_failure':monkeypatch.setattr(e,'runtime_context',lambda:(_ for _ in()).throw(OSError('runtime census failed')))
  elif case=='runtime_changed':monkeypatch.setattr(e,'runtime_context',lambda:{'context':'changed'})
  elif case=='plan_changed':plan[0]['command'].append('changed')
  elif case=='census_failure':monkeypatch.setattr(ValidationSession,'census',lambda *a:(_ for _ in()).throw(OSError('enumeration failed')))
 factory=e._validation_session
 def new(*a):s=factory(*a);s.runtime_context=lambda:e.runtime_context();return s
 monkeypatch.setattr(e,'_validation_session',new);finishing(monkeypatch,action)
 assert any('final census'in x for x in e.validate_completed_execution(run,plan))


def test_input_alias_target_is_rechecked(tmp_path,monkeypatch):
 run,plan,state=chain(tmp_path,1);source=run/'shared.dat';alias=run/'alias';alias.symlink_to(source);other=run/'other';other.write_bytes(source.read_bytes())
 rec=state['stages']['s0'];rec['inputs']=[str(alias)];rec['input_snapshot']=e.snapshot(run,rec['inputs']);seal(rec);save(run,state);plan[0]['inputs']=[str(alias)]
 def swap():alias.unlink();alias.symlink_to(other)
 finishing(monkeypatch,swap);assert e.validate_completed_execution(run,plan)


def test_opened_file_mutation_rejects(tmp_path,monkeypatch):
 run,plan,state=chain(tmp_path,1);target=run/'shared.dat';original=Path.open
 class Stream:
  def __init__(self,s):self.s=s;self.changed=False
  def __enter__(self):self.s.__enter__();return self
  def __exit__(self,*a):return self.s.__exit__(*a)
  def fileno(self):return self.s.fileno()
  def read(self,*a):
   out=self.s.read(*a)
   if not self.changed:
    self.changed=True;st=target.stat()
    with original(target,'r+b')as w:w.write(b'z')
    os.utime(target,ns=(st.st_atime_ns,st.st_mtime_ns))
   return out
 def opened(path,*a,**kw):
  s=original(path,*a,**kw);return Stream(s)if path==target and a and a[0]=='rb'else s
 monkeypatch.setattr(Path,'open',opened);assert any('while hashing'in x for x in e.validate_completed_execution(run,plan))


def test_hardlink_does_not_hide_different_expected_digest(tmp_path):
 run,plan,state=chain(tmp_path,1);link=run/'alias';os.link(run/'shared.dat',link);rec=state['stages']['s0'];rec['inputs'].append(str(link));rec['input_snapshot']=e.snapshot(run,rec['inputs']);rec['input_snapshot'][str(link)]['files'][0]['sha256']='0'*64;seal(rec);save(run,state);plan[0]['inputs'].append(str(link))
 assert any('inputs changed'in x for x in e.validate_completed_execution(run,plan))


@pytest.mark.parametrize('case',['cycle','parent_receipt','status','missing','unplanned','command','runtime','fingerprint'])
def test_receipt_dag_guards(tmp_path,case):
 run,plan,state=chain(tmp_path);rec=state['stages']['s0']
 if case=='cycle':rec['parents']={'s3':state['stages']['s3']['receipt_sha256']}
 elif case=='parent_receipt':state['stages']['s3']['parents']['s2']='0'*64
 elif case=='status':rec['status']='failed'
 elif case=='missing':del state['stages']['s0']
 elif case=='unplanned':state['stages']['extra']=copy.deepcopy(rec)
 elif case=='command':rec['command']=['different']
 elif case=='runtime':rec['runtime']={'context':'wrong'}
 elif case=='fingerprint':rec['fingerprint']='0'*64
 save(run,state);assert e.validate_completed_execution(run,plan)


def test_malformed_output_json_not_hidden_by_input_cache(tmp_path):
 run,plan,state=chain(tmp_path,1);p=run/'bad.json';p.write_text('{"a":1,"a":2}');rec=state['stages']['s0'];rec['inputs']=[str(p)];rec['input_snapshot']=e.snapshot(run,[str(p)]);rec['outputs']=[str(p)];rec['output_snapshot']=rec['input_snapshot'];seal(rec);save(run,state);plan[0].update(inputs=[str(p)],outputs=[str(p)])
 assert e.validate_completed_execution(run,plan)


def test_supplied_stale_state_cannot_match_new_ledger(tmp_path):
 run,plan,state=chain(tmp_path);different=copy.deepcopy(state);different['revision']+=1;save(run,different)
 assert any('supplied validation state'in x for x in e.stage_errors(run,'s3',state))


def test_hash_session_closed_on_failed_census(tmp_path):
 run,plan,state=chain(tmp_path);session=e._validation_session(run,state);session.snapshot([str(run/'shared.dat')]);(run/'shared.dat').unlink()
 assert session.finish() and session.closed and not session.hashes
 with pytest.raises(ValueError,match='closed'):session.hash_file(run/e.STATE_NAME)


def test_actual_chain_file_and_directory_snapshot_parity(tmp_path):
 run,plan,state=chain(tmp_path,directory=True);session=e._validation_session(run,state)
 for stage in state['stages'].values():
  assert session.snapshot(stage['inputs'])==e.snapshot(run,stage['inputs'])
  assert session.snapshot(stage['outputs'],outputs=True)==e.snapshot(run,stage['outputs'],outputs=True)
 assert session.finish()==[]


def test_diamond_shared_parent_does_not_lose_validation(tmp_path):
 run,plan,state=chain(tmp_path);rec=state['stages']['s3'];rec['parents']['s1']=state['stages']['s1']['receipt_sha256'];seal(rec);plan[3]['depends_on'].append('s1');save(run,state)
 assert e.validate_completed_execution(run,plan)==[]
 (run/'artifact0').write_bytes(b'changed')
 assert e.validate_completed_execution(run,plan)


@pytest.mark.parametrize('when',['before_open','during_read'])
def test_same_byte_path_replacement_around_open_rejects(tmp_path,monkeypatch,when):
 run,plan,state=chain(tmp_path,2);target=run/'shared.dat';original=Path.open;once=[]
 def swap():
  replacement=run/'replacement';replacement.write_bytes(target.read_bytes());replacement.replace(target)
 class Wrapped:
  def __init__(self,s):self.s=s
  def __enter__(self):self.s.__enter__();return self
  def __exit__(self,*a):return self.s.__exit__(*a)
  def fileno(self):return self.s.fileno()
  def read(self,*a):
   if not once:once.append(True);swap()
   return self.s.read(*a)
 def opened(path,*args,**kw):
  if path==target and args and args[0]=='rb':
   if when=='before_open'and not once:once.append(True);swap()
   stream=original(path,*args,**kw)
   return Wrapped(stream)if when=='during_read'else stream
  return original(path,*args,**kw)
 monkeypatch.setattr(Path,'open',opened)
 result=e.validate_completed_execution(run,plan)
 assert result and any('replaced' in x or 'pathname changed'in x or 'changed while hashing'in x for x in result)


def test_hardlink_reuse_validates_each_expectation_and_reads_once(tmp_path):
 run,plan,state=chain(tmp_path,1);target=run/'shared.dat';alias=run/'hard';os.link(target,alias)
 s=e._validation_session(run,state);first=s.snapshot([str(target)]);calls=s.hash_calls;other=s.snapshot([str(alias)])
 assert first[str(target)]['files']==other[str(alias)]['files']and s.hash_calls==calls
 assert s.finish()==[]


def test_hardlink_write_with_restored_mtime_is_not_cached(tmp_path):
 run,plan,state=chain(tmp_path,1);target=run/'shared.dat';alias=run/'hard';os.link(target,alias);s=e._validation_session(run,state)
 s.snapshot([str(target)]);old=target.stat();alias.write_bytes(b'x'*old.st_size);os.utime(alias,ns=(old.st_atime_ns,old.st_mtime_ns))
 with pytest.raises(ValueError,match='identity changed'):s.snapshot([str(target)])
 assert s.finish()


def test_added_empty_directory_during_first_hash_is_found(tmp_path,monkeypatch):
 run,plan,state=chain(tmp_path,1,directory=True);old=ValidationSession.hash_file;done=[]
 def changed(self,path):
  value=old(self,path)
  if Path(path)==run/'artifact0/data.dat'and not done:(run/'artifact0/new-empty').mkdir();done.append(True)
  return value
 monkeypatch.setattr(ValidationSession,'hash_file',changed)
 assert any('inventory changed' in v for v in e.validate_completed_execution(run,plan))


def test_replaced_directory_with_same_relative_bytes_is_found(tmp_path,monkeypatch):
 run,plan,state=chain(tmp_path,1,directory=True);old=ValidationSession.finish
 def replace(self):
  directory=run/'artifact0';previous=run/'old-directory';directory.rename(previous);directory.mkdir();(directory/'data.dat').write_bytes((previous/'data.dat').read_bytes());return old(self)
 monkeypatch.setattr(ValidationSession,'finish',replace)
 assert any('inventory changed' in v for v in e.validate_completed_execution(run,plan))


def test_fifo_inside_directory_is_rejected_without_open(tmp_path):
 run,plan,state=chain(tmp_path,1,directory=True);os.mkfifo(run/'artifact0/fifo')
 assert any('unsupported artifact directory entry'in x for x in e.validate_completed_execution(run,plan))


def test_final_ledger_replacement_after_open_must_reject(tmp_path,monkeypatch):
 run,plan,state=chain(tmp_path,2);ledger=run/e.STATE_NAME;original=Path.open;calls=[]
 def opened(path,*args,**kw):
  stream=original(path,*args,**kw)
  if path==ledger and (args[0]if args else kw.get('mode'))=='rb':
   calls.append(True)
   if len(calls)==2:
    replacement=run/'new-ledger';changed=copy.deepcopy(state);changed['revision']+=1;changed['stages']['s1']['status']='failed'
    with original(replacement,'w')as out:json.dump(changed,out)
    replacement.replace(ledger)
  return stream
 monkeypatch.setattr(Path,'open',opened)
 result=e.validate_completed_execution(run,plan)
 assert len(calls)==2 and json.loads(ledger.read_text())['revision']==state['revision']+1
 assert result, 'Final ledger bytes came from the old open inode after the ledger pathname was replaced'


def test_finish_clears_cache_on_runtime_exception(tmp_path,monkeypatch):
 run,plan,state=chain(tmp_path,1);s=e._validation_session(run,state);s.snapshot([str(run/'shared.dat')]);s.runtime_context=lambda:(_ for _ in()).throw(OSError('runtime unavailable'))
 assert s.finish()and s.closed and not s.hashes and not s.stages
 with pytest.raises(ValueError,match='closed'):s.hash_file(run/'shared.dat')


def test_malformed_json_is_parsed_after_input_digest_reuse(tmp_path):
 run,plan,state=chain(tmp_path,1);p=run/'same.json';p.write_text('{"x":NaN}')
 s=e._validation_session(run,state);s.snapshot([str(p)])
 with pytest.raises(ValueError,match='non-finite'):s.snapshot([str(p)],outputs=True)
 s.close()


@pytest.mark.parametrize('when',['unchanged','after_read','after_close'])
def test_final_ledger_descriptor_and_post_close_boundaries(tmp_path,monkeypatch,when):
 run,plan,state=chain(tmp_path,2);ledger=run/e.STATE_NAME;original=Path.open;opens=[]
 def changed(replace):
  value=copy.deepcopy(state);value['revision']+=1;value['stages']['s1']['status']='failed'
  path=run/'replacement-ledger'if replace else ledger
  with original(path,'w')as stream:json.dump(value,stream)
  if replace:path.replace(ledger)
 class Guarded:
  def __init__(self,stream):self.stream=stream
  def __enter__(self):self.stream.__enter__();return self
  def __exit__(self,*a):
   result=self.stream.__exit__(*a)
   if when=='after_close':changed(True)
   return result
  def fileno(self):return self.stream.fileno()
  def read(self,*a):
   data=self.stream.read(*a)
   if when=='after_read':changed(False)
   return data
 def opened(path,*args,**kw):
  stream=original(path,*args,**kw)
  if path==ledger and (args[0]if args else kw.get('mode'))=='rb':
   opens.append(True)
   if len(opens)==2:return Guarded(stream)
  return stream
 monkeypatch.setattr(Path,'open',opened)
 result=e.validate_completed_execution(run,plan)
 assert len(opens)==2
 if when=='unchanged':assert result==[]
 else:assert any('ledger' in v or 'identity changed' in v for v in result)

