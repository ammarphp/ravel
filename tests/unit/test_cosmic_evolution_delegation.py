"""Actual ordinary admission on synthetic records; native/RNG/Slurm callbacks inert.

The public plan and scripted approval are engineering fixtures. Registration is
explicitly synthesized and process birth observations are an inert observer.
No real study, approval, launch, model call or HPC rank exists in this control.
"""

from method_decision_fixture import admit_method
from pathlib import Path
from copy import deepcopy
import os
import pytest
from cosmic_evolution_fixture import fixture,write,pin,policy,LIMITS
from ravel.physics import cosmic_evolution as op, cosmic_evolution_worker as worker
from ravel.workflow import science,execution,state_io

def ordinary(tmp_path,monkeypatch):
    monkeypatch.setattr(execution.platform,'platform',lambda:'synthetic platform; no native probe')
    monkeypatch.setattr(execution,'process_identity',lambda pid:'synthetic-birth-'+str(pid))
    path,d,w,s=fixture(tmp_path/'input',operation='site-local-execution')
    spec=op.prepare(path,write(path.parent/'policy.json',policy())['path'],tmp_path/'spec.json',approval_mode='scripted_yes')
    rd=tmp_path/'synthetic-run';p=science.plan(rd,tmp_path/'spec.json'); admit_method(rd)
    science.approve(rd,'Synthetic engineering scripted assent; not human or physics approval',scripted=True)
    attempt={'attempt':1,'plan_sha256':execution.file_hash(rd/science.PLAN),'budget_seconds':p['max_seconds'],
             'correction_id':None,'correction_plan_sha256':None,'started_utc':execution.utc_now()}
    write(rd/'execution_attempt.json',attempt);write(rd/'logs/science-attempts/00000001.json',attempt)
    record={'status':'running','supervisor_pid':os.getppid(),'child_pid':os.getpid(),
            'child_identity':'synthetic-birth-'+str(os.getpid()),'fingerprint':p['stage_binding']['fingerprint']}
    write(rd/execution.STATE_NAME,{'schema_version':execution.VERSION,'revision':1,'stages':{'science':record}})
    # This is the genuine, unchanged local worker gate over synthetic records.
    actual=science.verify_worker(rd);assert actual['attempt']==1
    proposal,token=worker._admission(rd,parent=True)
    return rd,path,d,w,proposal,token

@pytest.mark.parametrize('attack',['none','wrong-attempt','changed-attempt','replaced-token','wrong-rank','wrong-step','no-ack','late-parent'])
def test_real_ordinary_parent_delegates_without_rank_pid_masquerade(tmp_path,monkeypatch,attack):
    rd,path,d,w,proposal,token=ordinary(tmp_path,monkeypatch)
    case=d['cases'][0];phase=case['phases'][-1];cap=op._capture({'input':str(path)},path.parent)[2]
    phase_out=rd/proposal['output_directory']/'cosmic-evolution'/case['id']/phase['id'];native=phase_out/'native';native.mkdir(parents=True)
    for row in phase['copies']:(native/row['to']).write_bytes(Path(row['file']['path']).read_bytes())
    handoff=worker.handoff_ic(case,phase,phase_out.parent,native,w,execution.digest(d),cap,LIMITS)
    h=phase_out/'handshake';h.mkdir()
    plan={'rundir':str(rd),'config_path':str(path),'phase_id':phase['id'],'case_id':case['id'],'nonce':'fresh',
          'payload':{**phase['payload'],'path':str(Path(phase['payload']['path']).absolute())},'argv':phase['argv'],
          'handshake':str(h),'native_cwd':str(native),'ranks':phase['ranks'],'job_id':17,'uid':os.getuid(),
          'handshake_seconds':5,'payload_seconds':15,'build_receipt':None,'ic_handoff':handoff,'parent_admission':deepcopy(token)}
    ack={'nonce':'fresh','payload':plan['payload'],'job_id':17,'step_id':3,'uid':os.getuid(),'start':100,'delegation_sha256':execution.digest(token)}
    if attack=='wrong-attempt':plan['parent_admission']['attempt']=2
    elif attack=='changed-attempt':
        v=state_io.read_json(rd/'execution_attempt.json');v['attempt']=2;write(rd/'execution_attempt.json',v)
    elif attack=='replaced-token':plan['parent_admission']['approval_sha256']='0'*64
    if attack!='no-ack':write(h/'ack.json',ack)
    pp=phase_out/'rank-plan.json';write(pp,plan)
    # A remote rank has another PID. The original gate MUST still refuse it.
    parent_pid=os.getpid();monkeypatch.setattr(execution.os,'getpid',lambda:parent_pid+100)
    monkeypatch.setattr(execution.os,'getppid',lambda:parent_pid+101)
    with pytest.raises(ValueError):science.verify_worker(rd)
    monkeypatch.setenv('SLURM_PROCID','9' if attack=='wrong-rank' else '0')
    monkeypatch.setenv('SLURM_JOB_ID','17');monkeypatch.setenv('SLURM_STEP_ID','4' if attack=='wrong-step' else '3')
    monkeypatch.setattr(worker.socket,'gethostname',lambda:'n0')
    calls=[];monkeypatch.setattr(worker.subprocess,'call',lambda *a,**k:calls.append(a[0]) or 0)
    if attack=='no-ack':
        ticks=iter([0,10,20,30]);monkeypatch.setattr(worker.time,'monotonic',lambda:next(ticks))
    elif attack=='late-parent':
        old=worker._document
        def read(p,sha=None,**kw):
            v=old(p,sha,**kw)
            if Path(p)==h/'ack.json':
                state=state_io.read_json(rd/execution.STATE_NAME);state['stages']['science']['status']='failed';write(rd/execution.STATE_NAME,state)
            return v
        monkeypatch.setattr(worker,'_document',read)
    if attack=='none':assert worker.rank(pp,pin(pp)['sha256'])==0 and len(calls)==1
    else:
        with pytest.raises((ValueError,OSError)):worker.rank(pp,pin(pp)['sha256'])
        assert not calls
