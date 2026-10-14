from copy import deepcopy
from pathlib import Path
import json,os,hashlib
import pytest
from cosmic_evolution_fixture import fixture,write,pin,save,policy,FakeController,FakeClient,FIELDS,ZS,LIMITS,inert_admission
from ravel.physics import cosmic_evolution as op, cosmic_evolution_worker as worker, cosmic_evolution_core as core
from ravel.workflow import science,state_io,agent_graph,agent_host,capability_routing

def test_public_ordinary_prepare_plan_unapproved(tmp_path,monkeypatch):
    monkeypatch.setattr(science.execution.platform,'platform',lambda:'synthetic platform identity; no native probe')
    path,d,_,_=fixture(tmp_path/'input',writer=False)
    pol=write(path.parent/'policy.json',policy());specpath=tmp_path/'spec.json'
    spec=op.prepare(path,pol['path'],specpath)
    assert science.adapter(spec) is op and 'cosmic-evolution' in science.MODES
    assert set(op.inputs(spec['task'],path.parent))<=set(science.task_inputs(spec,specpath.parent))
    rd=tmp_path/'run';p=science.plan(rd,specpath);science.verify_plan(rd)
    assert p['mode']=='cosmic-evolution' and not (rd/science.APPROVAL).exists()
    assert p['max_attempts']==1 and (rd/'inputs/checkin1.json').is_file()
    with pytest.raises((ValueError,OSError)):science.verify_plan(rd,approved=True)
    catalog=capability_routing.catalogue();row=next(r for r in catalog['operations'] if r['mode']=='cosmic-evolution')
    assert row['entrypoints']==['inputs','run','validate']

def graph(tmp_path,path,closure,role='designer'):
    rows=[{'id':'request','path':str(path),'sha256':pin(path)['sha256']},{'id':'closure','path':str(closure),'sha256':pin(closure)['sha256']}]
    g={'schema_version':1,'graph_id':'cosmic-context','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,'max_wall_seconds':30,'max_reworks':0},
       'nodes':[{'id':'context','kind':'tool','role':role,'depends_on':[],'inputs':rows,'packet':None,'action':'cosmic-evolution-context','parameters':{'request_input':'request','closure_input':'closure'},'max_attempts':1}]}
    rd=tmp_path/'graph';agent_graph.create(rd,g);return rd

def test_actual_graph_host_complete_closure_no_model(tmp_path):
    path,d,_,_=fixture(tmp_path/'input',writer=False);cp=tmp_path/'closure.json';c=op.prepare_context(path,cp)
    rd=graph(tmp_path,path,cp);r=agent_graph.execute(rd,agent_host.AgentHost())
    state=state_io.read_json(rd/'graph_state.json');assert state['usage']['calls']==1
    result=agent_graph.status(rd);assert result['complete']
    node=state['nodes']['context'];assert node['status']=='completed'
    actual=agent_graph._result(rd,node['result'])
    assert actual['result']['value']['physics_verified'] is False
    assert actual['result']['value']['input_pins']==c['inputs']
    # Public status complete with one deterministic call is source preparation,
    # never engine dispatch or parent acceptance. Exact input census retained.
    assert len(c['inputs'])==len(op.inputs({'input':str(path)},path.parent))
    assert 'ravel.physics.cosmic_evolution_core' in agent_host.AgentHost().identity['sources']

@pytest.mark.parametrize('attack',['omission','wrong-source','changed-nested','blind'])
def test_graph_full_closure_and_role_refuse(tmp_path,attack):
    path,d,_,_=fixture(tmp_path/'input',writer=False);cp=tmp_path/'closure.json';c=op.prepare_context(path,cp)
    if attack=='omission':c['inputs'].pop();write(cp,c)
    elif attack=='wrong-source':c['configuration']['sha256']='0'*64;write(cp,c)
    elif attack=='changed-nested':Path(d['cases'][0]['transfer']['file']['path']).write_text('different science')
    rd=graph(tmp_path,path,cp,role='critic' if attack=='blind' else 'designer')
    r=agent_graph.execute(rd,agent_host.AgentHost());assert not agent_graph.status(rd)['complete']
    assert state_io.read_json(rd/'graph_state.json')['usage']['calls']<=1

def test_real_site_worker_body_inert_build_ic_nyx(tmp_path,monkeypatch):
    path,d,w,s=fixture(tmp_path/'input',operation='site-local-execution',generated=True)
    inert_admission(monkeypatch,path.parent)
    # Reader cwd is native, so copied paths must preserve the actual source list.
    task=save(path,d);_,_,captured,_,_,schemas=op._capture(task,path.parent)
    monkeypatch.setenv('SLURM_JOB_ID','17');out=tmp_path/'out';out.mkdir()
    r=worker.execute(d,path,captured,schemas,out,tmp_path/'synthetic-run',controller_factory=FakeController,client_factory=FakeClient)
    assert [p['kind'] for p in r[0]['phases']]==['build','cosmicic','nyx']
    handoff=r[0]['phases'][2]['ic_handoff'];assert handoff['scratch']['shape']==[2,2,2] and handoff['source_bytes_preserved']
    assert len([p for p in r[0]['delivery']['inventory'] if '/Header' in p['path']])==7
    assert r[0]['phases'][2]['distributed']['accounting_complete'] is False
    assert not any(x.get('kind')=='cancel' for x in FakeController.last.calls)
    assert state_io.read_json(out/'fixture/ic/ic-products.json')['products']['validation']['particles']==8

@pytest.mark.parametrize('attack',['receipt','binary','missing-products'])
def test_derived_build_cannot_borrow_changed_outputs(tmp_path,monkeypatch,attack):
    path,d,w,s=fixture(tmp_path/'input',operation='site-local-execution',generated=True);save(path,d)
    inert_admission(monkeypatch,path.parent)
    cap=op._capture({'input':str(path)},path.parent)[2];monkeypatch.setenv('SLURM_JOB_ID','17');out=tmp_path/'out';out.mkdir()
    worker.execute(d,path,cap,s,out,tmp_path/'run',controller_factory=FakeController,client_factory=FakeClient)
    root=out/'fixture';receipt=root/'build/build-products.json'
    if attack=='receipt':v=state_io.read_json(receipt);v['configuration_sha256']='0'*64;write(receipt,v)
    elif attack=='binary':write(root/'build/native/init','changed binary')
    else:(root/'build/native/init').unlink()
    with pytest.raises(ValueError):worker.derived_payload(root,{'build_phase':'build','path':'init'},science.execution.digest(d),LIMITS)

@pytest.mark.parametrize('attack',['missing-header','missing-level','tail-field','missing-checkpoint','missing-halo','missing-insitu','late-byte','late-ABA'])
def test_full_output_delivery_refuses_missing_or_changed_tail(tmp_path,monkeypatch,attack):
    path,d,w,s=fixture(tmp_path/'input',operation='site-local-execution',generated=True);save(path,d)
    inert_admission(monkeypatch,path.parent)
    cap=op._capture({'input':str(path)},path.parent)[2];monkeypatch.setenv('SLURM_JOB_ID','17');out=tmp_path/'out';out.mkdir()
    r=worker.execute(d,path,cap,s,out,tmp_path/'run',controller_factory=FakeController,client_factory=FakeClient)
    root=out/'fixture';p=root/'nyx/native/plt2/Header'
    if attack.startswith('missing'):
        suffix={'missing-header':'plt2/Header','missing-level':'plt2/Level_0/Cell_D_00000','missing-checkpoint':'chk/Header','missing-halo':'halo.txt','missing-insitu':'insitu.txt'}[attack];(root/'nyx/native'/suffix).unlink()
    elif attack=='tail-field':p.write_text(p.read_text().replace('particle_count\n',''))
    else:
        raw=p.read_bytes();p.write_bytes(raw+b'x')
        if attack=='late-ABA':p.write_bytes(raw)
    if attack in ('late-byte','late-ABA'):assert core.output_inventory(root,LIMITS)!=r[0]['delivery']['inventory']
    else:
        with pytest.raises(ValueError):core.check_outputs(root,d['cases'][0]['outputs'],LIMITS)

def test_actual_common_worker_source_preparation_and_report(tmp_path,monkeypatch):
    path,d,_,_=fixture(tmp_path/'input',writer=False);spec=op.prepare(path,write(path.parent/'policy.json',policy())['path'],tmp_path/'spec.json')
    rd=tmp_path/'synthetic-run';rd.mkdir();proposal={'base_dir':str(path.parent),'output_directory':'outputs/attempt-1','stage_binding':{'input_snapshot':[]}}
    from ravel.physics import science_worker as sw
    for module in (science,sw):
        monkeypatch.setattr(module,'verify_worker',lambda r:proposal);monkeypatch.setattr(module,'execution_spec',lambda r:spec)
    assert sw.main([str(rd)])==0
    result=state_io.read_json(rd/'outputs/attempt-1/result.json')
    assert result['physics_validated'] is False and result['whole_parent_accepted'] is False
    assert (rd/'outputs/attempt-1/cosmic-evolution-report.md').exists()
    assert state_io.read_json(rd/'outputs/attempt-1/verification.json')['physics_validated'] is False

@pytest.mark.parametrize('target',['request','result','common-result','rank-plan','ack','ic-receipt'])
def test_real_emission_seams_refuse_changed_intended_bytes(tmp_path,monkeypatch,target):
    path,d,w,s=fixture(tmp_path/'input',operation='site-local-execution' if target in ('rank-plan','ack','ic-receipt') else 'source-preparation',generated=target in ('rank-plan','ack','ic-receipt'),writer=True)
    actual=state_io.atomic_json; interceptions=[]
    names={'request':'spec.json','result':'cosmic-result.json','common-result':'result.json','rank-plan':'rank-plan.json','ack':'ack.json','ic-receipt':'ic-products.json'}
    def wrong(p,v):
        actual(p,v)
        if Path(p).name==names[target]:
            interceptions.append(str(p));actual(p,{**v,'physics_validated':True})
    monkeypatch.setattr(state_io,'atomic_json',wrong)
    with pytest.raises(ValueError):
        if target=='request':op.prepare(path,write(path.parent/'policy.json',policy())['path'],tmp_path/'spec.json')
        elif target in ('rank-plan','ack','ic-receipt'):
            inert_admission(monkeypatch,path.parent)
            cap=op._capture({'input':str(path)},path.parent)[2];monkeypatch.setenv('SLURM_JOB_ID','17');out=tmp_path/'out';out.mkdir()
            worker.execute(d,path,cap,s,out,tmp_path/'run',controller_factory=FakeController,client_factory=FakeClient)
        else:
            spec=op.prepare(path,write(path.parent/'policy.json',policy())['path'],tmp_path/'spec.json');rd=tmp_path/'synthetic-run';rd.mkdir()
            proposal={'base_dir':str(path.parent),'output_directory':'outputs/attempt-1','stage_binding':{'input_snapshot':[]}}
            from ravel.physics import science_worker as sw
            for module in (science,sw):monkeypatch.setattr(module,'verify_worker',lambda r:proposal);monkeypatch.setattr(module,'execution_spec',lambda r:spec)
            sw.main([str(rd)])
    assert interceptions, 'intended real emitter was not reached'

@pytest.mark.parametrize('attack',['none','no-ack','foreign-ack','changed-payload','changed-handoff'])
def test_real_rank_shim_never_executes_before_exact_ack_and_inputs(tmp_path,monkeypatch,attack):
    path,d,w,s=fixture(tmp_path/'input',operation='site-local-execution',generated=False);save(path,d)
    admission=inert_admission(monkeypatch,path.parent)
    spec={'mode':'cosmic-evolution','task':{'input':str(path)}};rd=tmp_path/'synthetic-run';rd.mkdir()
    proposal={'base_dir':str(path.parent),'output_directory':'outputs/attempt-1'}
    monkeypatch.setattr(science,'verify_worker',lambda r:proposal);monkeypatch.setattr(science,'execution_spec',lambda r:spec)
    cap=op._capture(spec['task'],path.parent)[2];case=d['cases'][0];phase=case['phases'][-1]
    phase_out=rd/proposal['output_directory']/'cosmic-evolution'/case['id']/phase['id'];work=phase_out/'native';work.mkdir(parents=True)
    for row in phase['copies']:(work/row['to']).write_bytes(Path(row['file']['path']).read_bytes())
    handoff=worker.handoff_ic(case,phase,phase_out.parent,work,w,science.execution.digest(d),cap,LIMITS)
    h=phase_out/'handshake';h.mkdir();plan={'rundir':str(rd),'config_path':str(path),'phase_id':'nyx','case_id':'fixture','nonce':'fresh',
        'payload':{**phase['payload'],'path':str(Path(phase['payload']['path']).absolute())},'argv':phase['argv'],'handshake':str(h),'native_cwd':str(work),
        'ranks':phase['ranks'],'job_id':17,'uid':os.getuid(),'handshake_seconds':5,'payload_seconds':15,'build_receipt':None,'ic_handoff':handoff,'parent_admission':admission}
    ack={'nonce':'fresh','payload':plan['payload'],'job_id':17,'step_id':3,'uid':os.getuid(),'start':100,'delegation_sha256':science.execution.digest(admission)}
    if attack=='foreign-ack':ack['nonce']='old'
    if attack!='no-ack':write(h/'ack.json',ack)
    pp=phase_out/'rank-plan.json';write(pp,plan)
    if attack=='changed-payload':Path(plan['payload']['path']).write_text('changed')
    elif attack=='changed-handoff':write(work/'chunk.bin',b'different')
    monkeypatch.setenv('SLURM_PROCID','0');monkeypatch.setenv('SLURM_JOB_ID','17');monkeypatch.setenv('SLURM_STEP_ID','3')
    monkeypatch.setattr(worker.socket,'gethostname',lambda:'n0')
    calls=[];monkeypatch.setattr(worker.subprocess,'call',lambda *a,**k:calls.append({'argv':a[0],'cwd':str(k['cwd'])}) or 0)
    if attack=='no-ack':
        ticks=iter([0,10,20,30]);monkeypatch.setattr(worker.time,'monotonic',lambda:next(ticks))
    if attack=='none':
        assert worker.rank(pp,pin(pp)['sha256'])==0 and len(calls)==1
        assert calls[0]['argv']==[plan['payload']['path'],'inputs']
        assert state_io.read_json(h/'exit-0.json')['exit_code']==0
    else:
        with pytest.raises(ValueError):worker.rank(pp,pin(pp)['sha256'])
        assert not calls
