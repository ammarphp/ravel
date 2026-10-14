"""Real governed supervisor/worker registration; synthetic engineering output only.

Markers establish publication order. No scientific adapter computation or numerical
acceptance is exercised. Every attempt retains the normal fresh approval/input/
ledger validation; only the terminal adapter is a deliberately tiny test fixture.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from ravel.workflow import science

WORKER = r'''
"""Only admission and an engineering marker, never a scientific adapter run."""
from pathlib import Path
from types import SimpleNamespace
import hashlib,json,sys,time,os
base,rd,mode,package=map(str,sys.argv[1:5]);base=Path(base);rd=Path(rd)
sys.path.insert(0,package)
from ravel.workflow import science,execution
from ravel.workflow.validation_io import ValidationSession
science.module_command=lambda *_:json.loads((rd/science.PLAN).read_text())['stages'][0]['command']
def inputs(task,base):return [Path(task['payload']),Path(__file__).resolve()]
def session_inputs(task,base,session):
 paths=inputs(task,base)
 if mode=='late_ledger':
  state=execution.load_execution(rd);record=state['stages']['science'];record['fingerprint']='0'*64;execution._update(rd,'science',record)
 return paths
science.adapter=lambda _:SimpleNamespace(validate=lambda _:None,inputs=inputs,_validation_inputs=session_inputs)
original=ValidationSession.__init__
def instrumented(self,*args,**kwargs):
 original(self,*args,**kwargs)
 if mode=='race':
  (rd/'session-started').write_text('ledger already pinned')
  end=time.monotonic()+4
  while not (rd/'publication-finished').exists():
   if time.monotonic()>end:raise ValueError('engineering publication barrier timed out')
   time.sleep(.01)
ValidationSession.__init__=instrumented
if hasattr(science,'_await_worker_registration'):
 original_wait=science._await_worker_registration
 def observed_wait(*args,**kwargs):
  (rd/'await-started').write_text('immediately before real registration wait')
  return original_wait(*args,**kwargs)
 science._await_worker_registration=observed_wait
(rd/'worker-started').write_text(json.dumps({'pid':os.getpid(),'ppid':os.getppid()}))
try:
 proposal=science.verify_worker(rd)
 output=rd/proposal['output_directory'];output.mkdir(parents=True)
 (output/'tiny.json').write_text('{"engineering_marker":true,"physics_validated":false}\n')
 print('ADMISSION_PASSED')
except Exception as e:
 (rd/'admission-error.txt').write_text(str(e))
 print('ADMISSION_REFUSED:',e)
 raise
'''

SUPERVISOR = r'''
"""Real public supervisor and exact governed admission, synthetic terminal marker."""
from pathlib import Path
from types import SimpleNamespace
import json,sys,time,os,hashlib
base,rd,mode,package=map(str,sys.argv[1:5]);base=Path(base);rd=Path(rd)
sys.path.insert(0,package)
from ravel.workflow import science,execution
from ravel.workflow.state_io import atomic_json,read_json
worker=(base/'worker.py').resolve();payload=base/('runtime-'+rd.name+'.bin')
payload.write_bytes(b'synthetic unchanged runtime bytes!')
command=[sys.executable,'-B',str(worker),str(base),str(rd),mode,package,'1']
science.module_command=lambda *_:command
science.adapter=lambda _:SimpleNamespace(validate=lambda _:None,inputs=lambda t,b:[Path(t['payload']),worker],_validation_inputs=lambda t,b,s:[Path(t['payload']),worker])
policy={'schema_version':1,'actors':{'proposer':'producer','executor':'executor','physics_critic':'critic','skeptical_verifier':'skeptic','physics_decider':'decider'},'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],'required_checks':[{'id':'integrity','kind':'integrity'}],'claim_scopes':{'engineering':{'checks':['integrity'],'actions':['delivery']}}}
spec={'schema_version':2,'mode':'likelihood-parity','source':'Synthetic real process-registration race control','assumptions':['No likelihood calls or physics validation'],'max_seconds':15,'max_attempts':1,'approval_mode':'scripted_yes','task':{'payload':str(payload)},'review_policy':{'schema_version':1,'policy':policy,'correction_contract':{'task_fields':[],'input_slots':[]}}}
source=base/(rd.name+'-spec.json');atomic_json(source,spec);science.plan(rd,source); __import__("method_decision_fixture").admit_method(rd);science.approve(rd,'Actual root-authorized synthetic registration-race control',scripted=True)
original=execution.record_process
def delayed(root,record,pid):
 end=time.monotonic()+6
 while not (rd/'worker-started').exists():
  if time.monotonic()>end:raise ValueError('tiny worker did not start')
  time.sleep(.01)
 # Explicit markers prove ordering without a scheduling delay assumption.
 marker='await-started' if hasattr(science,'_await_worker_registration') else 'session-started'
 while not (rd/marker).exists():
  if time.monotonic()>end:raise ValueError('tiny worker causal marker missing: '+marker)
  time.sleep(.01)
 if marker=='await-started' and (rd/'session-started').exists():
  raise ValueError('candidate constructed validation session before registration')
 (rd/'publication-order.json').write_text(json.dumps({'marker':marker,'session_present_before_publication':(rd/'session-started').exists(),'await_present_before_publication':(rd/'await-started').exists()}))
 if mode=='cancel':
  record['status']='interrupted';execution._update(root,'science',record)
 elif mode=='wrong_parent':
  record['supervisor_pid']=os.getpid()+1000000;original(root,record,pid)
 elif mode=='wrong_pid':original(root,record,pid+1000000)
 elif mode=='wrong_identity':
  original(root,record,pid);record['child_identity']='forged-start';execution._update(root,'science',record)
 elif mode=='never_publish':time.sleep(5.5)
 elif mode=='parent_death':
  os.kill(os.getpid(),9)
 else:
  original(root,record,pid)
  if mode=='changed_input':payload.write_bytes(b'changed input of identical length!')
 (rd/'publication-finished').write_text('supervisor has published or cancelled')
execution.record_process=delayed
try:
 result=science.run(rd)
 print(json.dumps({'controller_return':result,'record_status':execution.load_execution(rd)['stages']['science']['status']}))
except Exception as e:print('CONTROLLER_ERROR',str(e));raise
'''

@pytest.mark.parametrize('mode', ['race', 'cancel', 'wrong_pid', 'wrong_identity',
                                  'changed_input', 'late_ledger', 'parent_death',
                                  'never_publish'])
def test_real_worker_waits_for_publication_and_rejects_adverse_lifecycle(tmp_path, mode):
    worker = tmp_path / 'worker.py'
    supervisor = tmp_path / 'supervisor.py'
    worker.write_text(WORKER)
    supervisor.write_text(SUPERVISOR)
    rundir = tmp_path / 'run'
    package = str(Path(science.__file__).resolve().parents[2])
    log = tmp_path / 'controller.log'
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=os.pathsep.join([str(Path(__file__).parent), os.environ.get('PYTHONPATH', '')]))
    with log.open('w') as stream:
        process = subprocess.Popen(
            [sys.executable, '-B', str(supervisor), str(tmp_path), str(rundir), mode, package],
            stdout=stream, stderr=subprocess.STDOUT, env=environment, start_new_session=True)
        try:
            code = process.wait(timeout=30)
            if mode == 'parent_death':
                deadline = time.monotonic() + 6
                while not (rundir / 'admission-error.txt').exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
        finally:
            # A deliberately killed parent may leave its tiny child briefly alive.
            # This is the unique process group created for this test only.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
    assert (rundir / 'publication-order.json').exists(), log.read_text()
    order = json.loads((rundir / 'publication-order.json').read_text())
    assert order == {'marker': 'await-started', 'session_present_before_publication': False,
                     'await_present_before_publication': True}
    state = json.loads((rundir / 'execution_state.json').read_text())['stages']['science']
    record_path, = (rundir / 'logs/execution/science').glob('*/record.json')
    assert json.loads(record_path.read_text()) == state
    error_path = rundir / 'admission-error.txt'
    output = rundir / 'outputs/attempt-1/tiny.json'
    worker_log = (rundir / 'logs/science-worker-1.log').read_text()
    if mode == 'race':
        assert code == 0, log.read_text()
        assert output.exists() and not error_path.exists(), worker_log
        assert state['status'] == 'succeeded'
        assert (rundir / 'session-started').exists()
        assert 'ADMISSION_PASSED' in worker_log
        # The fixture produced only an engineering marker. science.run's final
        # scientific-delivery result is intentionally incomplete (return code3).
        assert '"controller_return": 3' in log.read_text()
    else:
        assert not output.exists() and error_path.exists(), worker_log
        error = error_path.read_text()
        expected = {'cancel': 'current approved supervised attempt',
                    'wrong_pid': 'registration differs',
                    'wrong_identity': 'registration differs',
                    'changed_input': 'stale',
                    'late_ledger': 'current approved supervised attempt',
                    'parent_death': 'parent changed or disappeared',
                    'never_publish': 'registration timed out'}[mode]
        if mode == 'parent_death':
            # The parent can die before or after the helper captures its PID/start
            # identity. Each legitimate scheduling branch must refuse admission.
            assert any(message in error for message in (
                'parent changed or disappeared', 'current approved supervised attempt',
                'process registration identity unavailable')), error
        else:
            assert expected in error, error
        assert state['status'] == ('running' if mode == 'parent_death' else 'failed')
        assert code == (-signal.SIGKILL if mode == 'parent_death' else 0)
