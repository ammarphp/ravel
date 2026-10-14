"""Synthetic private adapter controls: no event, model or native process calls."""
from pathlib import Path
import copy,json
import pytest
from ravel.validation import mpi_paired_effect as m
from diagnostic_plan_fixture import metadata, intervention, signal

def runtime(monkeypatch,tmp_path):
    stages=[{'id':'producer_'+str(i),'argv':['inert-tool'],'outputs':['artifact_'+str(i)],'max_seconds':1,'depends_on':[]} for i in range(4)]
    d={'plan':{**metadata(file='mpi-paired-effect.json'),'intervention':intervention(),'loader_stages':[s['id'] for s in stages]},'resources':{'resource_root':str(tmp_path),'max_seconds':60,'free_floor_bytes':100000,'retained_bytes':200000,'headroom_bytes':1000},'environment':{},'inputs':{'qualified_binary':'/binary','qualified_wrapper_source':'/source','mpi_on_card':'/on','mpi_off_card':'/off'},'schema':{'path':'/schema'},'settings':{},'masses':{},'expected_identities':{},'selection_sources':{},'signal_spec':{}}
    binary=tmp_path/'qualified-binary';binary.write_text('synthetic unexecuted binary')
    d['inputs']['qualified_binary']=str(binary)
    state={'calls':[],'saved':[],'observations':0,'guards':[]}
    monkeypatch.setattr(m,'document',lambda *_:(None,d,{'stages':stages,'census':{'showers':2,'new_hard_events':0}}))
    def observe(*_):state['observations']+=1;return {str(binary):m.native.digest(binary)}
    monkeypatch.setattr(m,'input_snapshot',observe)
    monkeypatch.setattr(m,'accepted_qualification',lambda *_:{'cycle_id':'actual-required-in-production'})
    def atomic(p,value):
        state['saved'].append(copy.deepcopy(value));p.write_text(json.dumps(value))
    real_publish=m.plans.publish
    def publish(out,plan,value):state['saved'].append(copy.deepcopy(value));return real_publish(out,plan,value)
    monkeypatch.setattr(m.plans,'publish',publish)
    class Guard:
        def __init__(self,*_):pass
        def check(self,final=False):state['guards'].append(final)
    monkeypatch.setattr(m.native,'Guard',Guard)
    from types import SimpleNamespace
    monkeypatch.setattr(m.native.shutil,'disk_usage',lambda _:SimpleNamespace(free=100*1024**3))
    def child(s,out,*_):
        row={'id':s['id'],'status':'completed'};state['calls'].append(row)
        (out/'native-logs'/(s['id']+'.log')).write_text('dyld[123]: <ABC-012> '+str(binary)+'\n')
        (out/'native-logs'/(s['id']+'.command.json')).write_text(json.dumps(row));return row
    monkeypatch.setattr(m.native,'child',child)
    monkeypatch.setattr(m,'read_json',lambda p,*_,**kw:{} if str(p)=='/schema' else json.loads(Path(p).read_text()))
    def finalize(**kw):kw['save']({'retained':'returned synthetic estimate'});return {}
    monkeypatch.setattr(m.post,'finalize',finalize)
    return d,state,stages

def test_complete_chain_uses_fresh_begin_end_and_final_guard(monkeypatch,tmp_path):
    d,s,stages=runtime(monkeypatch,tmp_path);r=m.run({},tmp_path,tmp_path/'out')
    assert r['status']=='passed' and r['successful_end_custody'] and not r['physics_validated']
    assert len(r['commands'])==len(stages) and s['observations']==2 and s['guards'][-1] is True
    assert r['postprocessing']=={'retained':'returned synthetic estimate'}

def test_partial_failed_command_is_retained(monkeypatch,tmp_path):
    d,s,stages=runtime(monkeypatch,tmp_path);old=m.native.child
    def child(stage,out,*args):
        if len(s['calls'])==3:
            (out/'native-logs'/(stage['id']+'.command.json')).write_text(json.dumps({'id':stage['id'],'status':'failed','pid':9876}))
            raise ValueError('supplied native refusal')
        return old(stage,out,*args)
    monkeypatch.setattr(m.native,'child',child);r=m.run({},tmp_path,tmp_path/'out')
    assert r['status']=='failed' and len(r['commands'])==4 and r['commands'][-1]['pid']==9876
    assert r['postprocessing'] is None and s['observations']==1

def test_end_custody_changed_refuses_with_estimate_retained(monkeypatch,tmp_path):
    d,s,_=runtime(monkeypatch,tmp_path)
    def observe(*_):
        s['observations']+=1
        p=Path(d['inputs']['qualified_binary']);return {str(p):m.native.digest(p) if s['observations']==1 else 'changed'}
    monkeypatch.setattr(m,'input_snapshot',observe);r=m.run({},tmp_path,tmp_path/'out')
    assert r['status']=='failed' and not r['successful_end_custody'] and r['postprocessing']

def test_final_resource_failure_retains_no_passed_completion(monkeypatch,tmp_path):
    d,s,_=runtime(monkeypatch,tmp_path)
    class Guard:
        def __init__(self,*_):pass
        def check(self,final=False):
            if final:raise ValueError('supplied final cap refusal')
    monkeypatch.setattr(m.native,'Guard',Guard);r=m.run({},tmp_path,tmp_path/'out')
    assert r['status']=='failed' and not r['successful_end_custody'] and s['saved'][-1]['status']=='failed'

def test_qualification_refusal_before_children(monkeypatch,tmp_path):
    d,s,_=runtime(monkeypatch,tmp_path)
    monkeypatch.setattr(m,'accepted_qualification',lambda *_:(_ for _ in ()).throw(ValueError('hold')))
    r=m.run({},tmp_path,tmp_path/'out');assert r['status']=='failed' and not s['calls']

@pytest.mark.parametrize('kind',['parent','symlink','populated'])
def test_output_ownership_refuses(monkeypatch,tmp_path,kind):
    runtime(monkeypatch,tmp_path);out=tmp_path/'out'
    if kind=='parent':out=out/'..'/'escape'
    if kind=='symlink':out.symlink_to(tmp_path,target_is_directory=True)
    if kind=='populated':out.mkdir();(out/'existing').write_text('keep')
    with pytest.raises(ValueError):m.run({},tmp_path,out)

def qualification(monkeypatch,tmp_path):
    from ravel.workflow import physics_review
    monkeypatch.setattr(physics_review,'validate_snapshot',lambda _:[])
    root=tmp_path/'accepted';root.mkdir();result=root/'result.json';binary=root/'binary';source=root/'source'
    events=[{'event':'cycle','cycle_id':'c','snapshots':[{'path':str(p),'sha256':'hash'} for p in (result,binary,source)]}]
    for role in ('physics_critic','skeptical_verifier','physics_decider'):events.append({'event':'review','cycle_id':'c','role':role,'verdict':'accept','claim_scope':m.QUALIFICATION_SCOPE})
    head={'sequence':4,'sha256':'h'};reg={'id':'r'};snapshot={'registration':reg,'checkpoint':head,'events':events,'action':'reuse'}
    q={k:{'path':str(root/k),'sha256':'hash'} for k in ('review_snapshot','registration','head')};q['registration']['path']=str(root/'logs/physics_review/registration.json');q['head']['path']=str(root/'logs/physics_review/head.json');q['result']={'path':str(result),'sha256':'hash'};q['rundir']=str(root);q['claim_scope']=m.QUALIFICATION_SCOPE
    documents={q['review_snapshot']['path']:snapshot,q['registration']['path']:reg,q['head']['path']:head,str(result):{'status':'passed','successful_end_custody':True,'planned_native_counts':{'compiles':1,'shower_calls':4,'shower_exposures':12,'new_hard_events':0,'detectors':0,'conversions':0,'analyses':0,'fits':0,'retries':0},'snapshots':{'on':{},'off':{}},'pairs':{'on':{},'off':{}}}}
    directory=root/'logs/physics_review/events';directory.mkdir(parents=True)
    q['events']=[]
    for i,e in enumerate(events,1):
        path=directory/f'{i:08d}.json';path.write_text(json.dumps(e));q['events'].append({'path':str(path),'sha256':'hash'});documents[str(path)]=copy.deepcopy(e)
    monkeypatch.setattr(m,'read_json',lambda p,*_,**__:documents[str(p)])
    documents['/runtime']={'files':[{'path':str(binary),'sha256':'hash'}]}
    d={'plan':{'qualification_expectations':{'native_counts':copy.deepcopy(documents[str(result)]['planned_native_counts']),'arms':['on','off']}},'runtime_inventory':{'path':'/runtime','sha256':'hash'},'qualification':q,'inputs':{'qualified_binary':str(binary),'qualified_wrapper_source':str(source)},'sources':[{'path':str(p),'sha256':'hash'} for p in (binary,source)]}
    return d,documents,snapshot,events

def test_exact_accepted_binary_association(monkeypatch,tmp_path):
    d,*_=qualification(monkeypatch,tmp_path);assert m.accepted_qualification(d,lambda:None)['cycle_id']=='c'


def retained_qualification(monkeypatch,tmp_path):
    d,docs,snapshot,events=qualification(monkeypatch,tmp_path)
    q=d['qualification'];q['claim_scope']=m.RETAINED_QUALIFICATION_SCOPE
    for e in events[1:]:e['claim_scope']=m.RETAINED_QUALIFICATION_SCOPE
    for pin,e in zip(q['events'],events):docs[pin['path']]=copy.deepcopy(e)
    stages=['prepare','probe_a','probe_b']
    result=docs[q['result']['path']]
    result.pop('planned_native_counts')
    result.update(scope=m.RETAINED_QUALIFICATION_SCOPE,
        new_native_counts=dict(compiles=0,shower_calls=0,shower_exposures=0,new_hard_events=0,
                               detectors=0,conversions=0,analyses=0,fits=0,retries=0),
        original_resource_contract_satisfied=False,original_result_rewritten=False,
        origin={'original_scientific_status':'failed','original_controller_status':'failed'},
        commands=[{'stage':stage,'returncode':0} for stage in stages],
        transports={stage:{'status':'content_verified','original_events':6,'joined_events':6} for stage in stages[1:]},
        transport_comparisons={stage:{'status':'passed'} for stage in stages[1:]})
    d['plan']['qualification_expectations']={'stages':stages,'transport_ids':stages[1:],'events':6,'arms':['on','off']}
    return d,docs,snapshot,events,result


def test_explicit_retained_scope_requires_its_own_accepted_cycle(monkeypatch,tmp_path):
    d,docs,snapshot,events,result=retained_qualification(monkeypatch,tmp_path)
    before=copy.deepcopy(result)
    out=m.accepted_qualification(d,lambda:None)
    assert out['scope']==m.RETAINED_QUALIFICATION_SCOPE and result==before
    assert result['origin']['original_scientific_status']=='failed'


@pytest.mark.parametrize('change',['undeclared_route','old_scope_votes','old_failure_result','changed_binary',
                                  'native_call','old_status_rewrite','old_resource_upgrade','missing_command',
                                  'failed_command','missing_transport','partial_transport','mismatch_transport',
                                  'held_cycle'])
def test_retained_route_does_not_upgrade_original_failure_or_waive_custody(monkeypatch,tmp_path,change):
    from ravel.workflow import physics_review
    d,docs,snapshot,events,result=retained_qualification(monkeypatch,tmp_path)
    q=d['qualification']
    if change=='undeclared_route':q.pop('claim_scope')
    elif change=='old_scope_votes':
        for e in events[1:]:e['claim_scope']=m.QUALIFICATION_SCOPE
        for pin,e in zip(q['events'],events):docs[pin['path']]=copy.deepcopy(e)
    elif change=='old_failure_result':result.update(status='failed',successful_end_custody=False)
    elif change=='changed_binary':d['sources'][0]['sha256']='changed'
    elif change=='native_call':result['new_native_counts']['shower_calls']=1
    elif change=='old_status_rewrite':result['origin']['original_scientific_status']='passed'
    elif change=='old_resource_upgrade':result['original_resource_contract_satisfied']=True
    elif change=='missing_command':result['commands'].pop()
    elif change=='failed_command':result['commands'][1]['returncode']=1
    elif change=='missing_transport':result['transports'].pop('probe_a')
    elif change=='partial_transport':result['transports']['probe_a']['joined_events']=5
    elif change=='mismatch_transport':result['transport_comparisons']['probe_b']['status']='mismatch'
    elif change=='held_cycle':monkeypatch.setattr(physics_review,'validate_snapshot',lambda _:['late scientific hold'])
    with pytest.raises(ValueError):m.accepted_qualification(d,lambda:None)

@pytest.mark.parametrize('kind',['scope','binary','current_head','current_journal','result_failed','arm_missing','population','invalid_review'])
def test_acceptance_association_adversaries(monkeypatch,tmp_path,kind):
    from ravel.workflow import physics_review
    d,docs,snapshot,events=qualification(monkeypatch,tmp_path)
    if kind=='scope':snapshot['events'][-1]['claim_scope']='unrelated'
    elif kind=='binary':d['sources'][0]['sha256']='other'
    elif kind=='current_head':snapshot['checkpoint']={'sequence':99,'sha256':'new'}
    elif kind=='current_journal':snapshot['events']=events[:-1]
    elif kind=='result_failed':docs[d['qualification']['result']['path']]['status']='failed'
    elif kind=='arm_missing':docs[d['qualification']['result']['path']]['pairs'].pop('off')
    elif kind=='population':docs[d['qualification']['result']['path']]['planned_native_counts']['shower_exposures']=6
    elif kind=='invalid_review':monkeypatch.setattr(physics_review,'validate_snapshot',lambda _:['held'])
    with pytest.raises(ValueError):m.accepted_qualification(d,lambda:None)

def test_no_children_if_entry_reserve_insufficient(monkeypatch,tmp_path):
    from types import SimpleNamespace
    d,s,_=runtime(monkeypatch,tmp_path)
    monkeypatch.setattr(m.native.shutil,'disk_usage',lambda _:SimpleNamespace(free=1000))
    r=m.run({},tmp_path,tmp_path/'out');assert r['status']=='failed' and not s['calls']

def test_accepted_native_runtime_identity_cannot_change(monkeypatch,tmp_path):
    d,docs,_,_=qualification(monkeypatch,tmp_path);docs['/runtime']['files'][0]['sha256']='different'
    with pytest.raises(ValueError,match='Physical runtime'):m.accepted_qualification(d,lambda:None)

def test_unrecorded_current_review_event_refuses(monkeypatch,tmp_path):
    d,*_=qualification(monkeypatch,tmp_path)
    (Path(d['qualification']['rundir'])/'logs/physics_review/events/00000005.json').write_text('{}')
    with pytest.raises(ValueError,match='population'):m.accepted_qualification(d,lambda:None)

def document_fixture(monkeypatch,tmp_path):
    from ravel.workflow import science
    tools={'python':'/tools/python'}
    inputs={k:'/inputs/'+k for k in ('selected_lhe','expected_identities','qualified_binary','qualified_wrapper_source','mpi_on_card','mpi_off_card')}
    settings={a:{'flags':{'PartonLevel:MPI':a=='on','Random:setSeed':True},'modes':{'Tune:pp':3,'Random:seed':17,'Main:numberOfEvents':6},'words':{'Beams:LHEF':inputs['selected_lhe']}} for a in ('on','off')}
    stages=[{'id':'step_'+str(i),'argv':['inert-tool'],'outputs':['artifact_'+str(i)],'max_seconds':2,'depends_on':[]} for i in range(2)]
    plan={**metadata(),'intervention':intervention(),'stages':stages,'census':{'new_hard_events':0,'new_compiles':0,'selected_original_events':6},'qualification_expectations':{},'setting_contrasts':[{'group':'flags','field':'PartonLevel:MPI','on':True,'off':False}],'loader_stages':[s['id'] for s in stages]}
    d={'plan':plan,'schema_version':1,'scope':m.SCOPE,'tools':tools,'inputs':inputs,'sources':[{'path':p,'sha256':'a'*64} for p in set(tools.values())|set(inputs.values())],'runtime_inventory':{},'qualification':{},'schema':{},'settings':settings,'masses':{'101':1.,'102':2.},'expected_identities':{'path':inputs['expected_identities'],'sha256':'a'*64},'selection_sources':{k:'a'*64 for k in ('selection_source_sha256','diagnostic_source_sha256','rjr_binary_sha256')},'signal_spec':signal(),'environment':{k:'1' for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','PYTHONDONTWRITEBYTECODE','DYLD_PRINT_LIBRARIES')},'resources':{'max_seconds':60,'workers':1,'attempts':1,'retained_bytes':200000,'free_floor_bytes':100000,'headroom_bytes':1000,'inherited_bytes':0,'lineage_ceiling_bytes':200000,'resource_root':str(tmp_path)},'platform':m.platform.platform(),'assumptions':['synthetic']*6}
    monkeypatch.setattr(science,'regular',lambda *_:tmp_path/'document')
    monkeypatch.setattr(m.native,'digest',lambda _:'a'*64)
    monkeypatch.setattr(m,'read_json',lambda *_:d)
    return d,{'input':str(tmp_path/'document'),'sha256':'a'*64}


def test_closed_document_and_supplied_stage_budget(monkeypatch,tmp_path):
    d,t=document_fixture(monkeypatch,tmp_path);_,_,plan=m.document(t,tmp_path)
    assert len(plan['stages'])==2 and plan['sum_native_command_ceilings_seconds']==4


@pytest.mark.parametrize('change',['tune','seed','count','weight','mass','missing_pin','threads','floor','retention','attempts','clock'])
def test_document_scientific_resource_adversaries(monkeypatch,tmp_path,change):
    d,t=document_fixture(monkeypatch,tmp_path)
    if change in ('tune','seed'):d['settings']['on']['modes'][{'tune':'Tune:pp','seed':'Random:seed'}[change]]='invalid'
    elif change=='count':d['settings']['on']['modes']['Main:numberOfEvents']=True
    elif change=='weight':d['signal_spec']['kfactor']=-1.
    elif change=='mass':d['masses']['101']=-1.
    elif change=='missing_pin':d['sources']=[]
    elif change=='threads':d['environment']['OMP_NUM_THREADS']='2'
    elif change=='floor':d['resources']['free_floor_bytes']=-1
    elif change=='retention':d['resources']['retained_bytes']=0
    elif change=='attempts':d['resources']['attempts']=2
    elif change=='clock':d['resources']['max_seconds']=1
    with pytest.raises(ValueError):m.document(t,tmp_path)


@pytest.mark.parametrize('row',[{'path':'/x','sha256':'a'*64,'extra':True},{'path':'/x','sha256':'g'*64},{'path':'../x','sha256':'a'*64},{'path':'/x','sha256':'a'*64,'bytes':True}])
def test_malformed_pin_not_silently_omitted(row):
    with pytest.raises(ValueError):list(m.pins({'nested':[row]}))

def test_runtime_metadata_ceiling_accepts_21mb_without_unbounded_read(monkeypatch):
    # No 21MB allocation: check the exact bound handed to the reviewed reader.
    calls=[]
    def read(p,cb,**kw):calls.append(kw['ceiling']);return {},b'{}',()
    monkeypatch.setattr(m.witness,'_read_pin',read)
    assert m.read_json('/runtime',ceiling=64*1024**2)=={}
    assert calls==[64*1024**2]

@pytest.mark.parametrize('change',['channel','selection','typedflag'])
def test_source_basis_and_typed_settings_refuse(monkeypatch,tmp_path,change):
    d,t=document_fixture(monkeypatch,tmp_path)
    if change=='channel':d['signal_spec']['channel_order'][0]=d['signal_spec']['channel_order'][1]
    elif change=='selection':d['selection_sources']['selection_source_sha256']='unknown'
    elif change=='typedflag':d['settings']['on']['flags']['Random:setSeed']=1
    with pytest.raises(ValueError):m.document(t,tmp_path)


def test_children_keep_custody_reserve(monkeypatch,tmp_path):
    import time
    d,s,stages=runtime(monkeypatch,tmp_path);inner=m.native.child;seen=[]
    def child(stage,out,environment,deadline,guard):
        seen.append(deadline-time.monotonic());return inner(stage,out,environment,deadline,guard)
    monkeypatch.setattr(m.native,'child',child)
    assert m.run({},tmp_path,tmp_path/'out')['status']=='passed'
    assert len(seen)==len(stages) and max(seen)<=d['resources']['max_seconds']-m.native.CUSTODY_RESERVE_SECONDS
