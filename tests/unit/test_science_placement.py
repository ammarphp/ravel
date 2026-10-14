"""A placed science stage: fingerprinted placement, CHECK-IN 1 section, real backend run.

The terminal adapter is a tiny engineering fixture; planning, approval, launch
authorization, supervision, the backend job and payload custody are real.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

from ravel.workflow import science

WORKER = r'''
from pathlib import Path
from types import SimpleNamespace
import json,sys
base,rd,package=map(str,sys.argv[1:4]);base=Path(base);rd=Path(rd)
sys.path.insert(0,package)
from ravel.workflow import science,execution
payload=json.loads((rd/'inputs/backend-plan.json').read_text())['spec']['argv']
science.module_command=lambda *_:payload
def inputs(task,base):return [Path(task['payload']),Path(__file__).resolve()]
science.adapter=lambda _:SimpleNamespace(validate=lambda _:None,inputs=inputs,_validation_inputs=lambda t,b,s:inputs(t,b))
proposal=science.verify_worker(rd)
output=Path(proposal['output_directory']);output.mkdir(parents=True)
custody=execution.worker_custody(rd,'science')
(output/'tiny.json').write_text(json.dumps({'engineering_marker':True,'physics_validated':False,'custody':custody['mode']}))
'''

CONTROLLER = r'''
from pathlib import Path
from types import SimpleNamespace
import json,sys
base,rd,package,cpus,action=sys.argv[1:6];base=Path(base);rd=Path(rd)
sys.path.insert(0,package)
from ravel.workflow import science,execution
from ravel.workflow.state_io import atomic_json
worker=(base/'worker.py').resolve();payload=base/'runtime.bin'
if not payload.exists():payload.write_bytes(b'synthetic unchanged runtime bytes')
command=[sys.executable,'-B',str(worker),str(base),str(rd),package]
science.module_command=lambda *_:command
inputs=lambda t,b:[Path(t['payload']),worker]
science.adapter=lambda _:SimpleNamespace(validate=lambda _:None,inputs=inputs,_validation_inputs=lambda t,b,s:inputs(t,b))
policy={'schema_version':1,'actors':{'proposer':'producer','executor':'executor','physics_critic':'critic','skeptical_verifier':'skeptic','physics_decider':'decider'},'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],'required_checks':[{'id':'integrity','kind':'integrity'}],'claim_scopes':{'engineering':{'checks':['integrity'],'actions':['delivery']}}}
spec={'schema_version':2,'mode':'likelihood-parity','source':'Synthetic placement control','assumptions':['No physics calculation'],'max_seconds':30,'max_attempts':1,'approval_mode':'scripted_yes','task':{'payload':str(payload)},'review_policy':{'schema_version':1,'policy':policy,'correction_contract':{'task_fields':[],'input_slots':[]}}}
if cpus!='none':spec['execution']={'backend_plan':{'backend':'native','resources':{'cpus':int(cpus),'memory_mib':256}}}
source=base/(rd.name+'-spec.json');atomic_json(source,spec);science.plan(rd,source); __import__("method_decision_fixture").admit_method(rd)
if action=='run':
 science.approve(rd,'Scripted assent to a synthetic placement control',scripted=True)
 result=science.run(rd)
 print(json.dumps({'controller_return':result,'record_status':execution.load_execution(rd)['stages']['science']['status']}))
'''


def controller(tmp_path, name, cpus, action):
    (tmp_path / 'worker.py').write_text(WORKER)
    (tmp_path / 'controller.py').write_text(CONTROLLER)
    package = str(Path(science.__file__).resolve().parents[2])
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(Path(__file__).parent), os.environ.get('PYTHONPATH', '')]), PYTHONDONTWRITEBYTECODE='1', RAVEL_STATE_DIR=str(tmp_path / 'state'))
    process = subprocess.Popen([sys.executable, '-B', str(tmp_path / 'controller.py'), str(tmp_path),
                                str(tmp_path / name), package, cpus, action],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
                               start_new_session=True)
    try:
        out, _ = process.communicate(timeout=120)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    assert process.returncode == 0, out
    return tmp_path / name, out


def test_science_placement_changes_the_plan_fingerprint_and_checkin_shows_it(tmp_path):
    runs = {cpus: controller(tmp_path, f'run-{cpus}', cpus, 'plan')[0] for cpus in ('none', '1', '2')}
    plans = {cpus: json.loads((rd / science.PLAN).read_text()) for cpus, rd in runs.items()}
    fingerprints = {plan['stage_binding']['fingerprint'] for plan in plans.values()}
    assert len(fingerprints) == 3
    assert plans['1']['stages'][0]['command'][2:4] == ['ravel.workflow.execution_backend', 'worker']
    assert 'inputs/backend-plan.json' in plans['1']['stages'][0]['inputs']
    checkins = {cpus: json.loads((rd / 'inputs/checkin1.json').read_text())['sections']['i-b']
                for cpus, rd in runs.items()}
    assert 'placement' not in checkins['none']
    assert checkins['1']['placement']['resources']['cpus'] == 1
    assert checkins['2']['placement']['resources']['cpus'] == 2
    assert 'Placement: native backend, 2 CPU(s)' in (runs['2'] / 'CHECKIN1.md').read_text()


def test_placed_science_stage_runs_through_the_backend(tmp_path):
    rd, out = controller(tmp_path, 'run', '1', 'run')
    summary = json.loads(out.strip().splitlines()[-1])
    assert summary['record_status'] == 'succeeded', out + (rd / 'logs/science-worker-1.log').read_text()
    marker = json.loads((rd / 'outputs/attempt-1/tiny.json').read_text())
    assert marker == {'engineering_marker': True, 'physics_validated': False, 'custody': 'backend'}
    handles = sorted((rd / 'logs/execution/science').glob('*/backend/backend-handle.json'))
    assert len(handles) == 1 and json.loads(handles[0].read_text())['state'] == 'fetched'


def test_placement_requires_a_single_attempt():
    with pytest.raises(ValueError, match='one prospectively bound version2 attempt'):
        science.validate({'schema_version': 2, 'max_attempts': 2, 'mode': 'quantities',
                          'execution': {'backend_plan': {'backend': 'native', 'resources': {'cpus': 1, 'memory_mib': 64}}}})
