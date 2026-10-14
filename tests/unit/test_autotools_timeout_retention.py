"""Mocked actual helper/lifecycle timeout controls, never launch native commands."""
import base64,json,subprocess
from pathlib import Path
import pytest
from ravel.physics import routine_build,autotools_library_build as build

@pytest.fixture(autouse=True)
def no_native(monkeypatch):
 def forbid(*a,**k):raise AssertionError('External/native process forbidden')
 monkeypatch.setattr(subprocess,'Popen',forbid);monkeypatch.setattr(subprocess,'run',forbid)

@pytest.mark.parametrize('stdout,stderr,kind',[(b'partial\x00\xff',b'error\x80','bytes'),(b'',b'','bytes'),(None,None,'unavailable'),('diagnostic','error','text_utf8_surrogatepass')])
def test_timeout_raw_bytes_null_exit_and_original_exception(tmp_path,monkeypatch,stdout,stderr,kind):
 command=['explicit-fake-command'];problem=subprocess.TimeoutExpired(command,600,output=stdout,stderr=stderr)
 def fake(*a,**k):raise problem
 monkeypatch.setattr(subprocess,'run',fake);log=tmp_path/'command-1.json'
 with pytest.raises(subprocess.TimeoutExpired) as error:routine_build._process(command,tmp_path,{'CXX':'bound'},log,max_seconds=600)
 assert error.value is problem
 r=json.loads(log.read_text());assert r['returncode'] is None and r['timed_out'] is True and r['timeout_seconds']==600
 assert r['stdout_capture_kind']==r['stderr_capture_kind']==kind and r['native_process_quiescence_established'] is False
 assert r['command']==command and r['cwd']==str(tmp_path.resolve()) and r['environment']=={'CXX':'bound'}
 def raw(x):return b'' if x is None else x.encode('utf-8',errors='surrogatepass') if type(x) is str else x
 assert base64.b64decode(r['stdout_base64'])==raw(stdout) and base64.b64decode(r['stderr_base64'])==raw(stderr)


def test_timeout_preserves_shrinking_existing_deadline(tmp_path,monkeypatch):
 monkeypatch.setattr(routine_build.time,'monotonic',lambda:100)
 def timeout(command,**kwargs):assert kwargs['timeout']==7;raise subprocess.TimeoutExpired(command,7,output=b'partial')
 monkeypatch.setattr(subprocess,'run',timeout)
 with pytest.raises(subprocess.TimeoutExpired):routine_build._process(['fake'],tmp_path,{},tmp_path/'log',work_deadline=107,max_seconds=600)
 assert json.loads((tmp_path/'log').read_text())['timeout_seconds']==7

def test_success_observation_schema_is_unchanged(tmp_path,monkeypatch):
 class R:returncode=0;stdout=b'ordinary';stderr=b''
 monkeypatch.setattr(subprocess,'run',lambda *a,**k:R())
 assert routine_build._process(['fake'],tmp_path,{},tmp_path/'log')==(0,b'ordinary')
 r=json.loads((tmp_path/'log').read_text())
 assert set(r)=={'schema_version','command','returncode','cwd','environment','started_at','finished_at','stdout_base64','stderr_base64'}
