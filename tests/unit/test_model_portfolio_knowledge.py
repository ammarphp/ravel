"""Portable complete supplied coverage; no SModelS/native/provider calls."""
from copy import deepcopy
import hashlib,json
from pathlib import Path
import pytest
from ravel.physics.reinterpret_db import summarize
from ravel.workflow import model_portfolio_knowledge as m,physics_knowledge as pk,agent_graph,agent_host,research_cycle


def pin(p):
    p=p.resolve();b=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'size':len(b)}


def write(p,value):
    p.write_text(json.dumps(value,allow_nan=False)+'\n');return pin(p)


def fixture(base):
    original=base.resolve()/'original';original.mkdir()
    sig=lambda name,weight,ids:{'sms':name,'weight_fb':weight,'native_sms_ids':ids}
    group=lambda label,sigs,total:{'label':label,'description':'Explicitly synthetic '+label,
                                  'sqrts_tev':13.,'total_xsec_fb':total,'signatures':sigs}
    native={'output_status':{'decomposition status':1},'predictions':[],'decomposition':[],
            'coverage':[group('missing_prompt',[sig('FIRST supplied topology',2.,[1]),sig('SECOND distinct lifetime topology',3.,[2])],5.),
                        group('outsideGrid_prompt',[sig('SECOND distinct lifetime topology',1.,[2])],1.),
                        group('missing_displaced',[sig('zero surviving-cut row',0.,[3])],0.)],
            'supplied_physics':{'format':'slha','scope':'Explicitly synthetic supplied spectrum/decay metadata'},
            'loaded_database_census':'loaded-database-census.json'}
    result={'status':'passed','physics_validated':False,'scope':'Supplied toy model portfolio',**summarize(native),
            'source':'Explicitly synthetic coverage observations; no native execution',
            'database':{'version':'3.1.1'},'runtime':{'smodels_version':'3.1.1'},
            'protocol':{'sigmacut_fb':.005,'prompt_width_gev':1e-11,'stable_width_gev':1e-25},
            'output_status':native['output_status'],'predictions':native['predictions'],
            'supplied_physics':native['supplied_physics'],'native_artifacts':['portfolio-native.json'],
            'limitations':['Native groups overlap and cannot be summed.','Missing/omitted response is not an efficiency zero.']}
    a=original/'portfolio-native.json';b=original/'portfolio.json'
    return write(a,native),write(b,result),native,deepcopy(result)


def test_complete_population_and_real_existing_knowledge_consumer(tmp_path):
    a,b,n,r=fixture(tmp_path)
    old={p.name:pin(p) for p in Path(a['path']).parent.iterdir()}
    request=m.prepare(a,b,tmp_path/'knowledge',base=tmp_path)
    packet=pk.retrieve(request,tmp_path)
    assert len(packet['nodes'])==8 and not packet['selection']['omitted']
    ids=packet['selection']['selected_ids']
    assert 'signature.0.1' in ids and 'signature.1.0' in ids and 'signature.2.0' in ids
    assert 'SECOND distinct lifetime topology' in next(x['statement'] for x in packet['nodes'] if x['id']=='signature.0.1')
    assert packet['claims']=={'physics_verified':False,'execution_authorized':False}
    assert len(packet['test_obligations'])==6 and all(x['check'] is None for x in packet['test_obligations'])
    assert all(len(p['basis'])==3 for p in packet['premises'])
    assert len(pk.input_pins(request,tmp_path))==4
    assert {p.name:pin(p) for p in Path(a['path']).parent.iterdir()}==old
    prepared=json.loads((tmp_path/'knowledge/PREPARATION.json').read_text())
    assert (prepared['coverage_groups'],prepared['coverage_signatures'])==(3,4)
    assert prepared['accepted_parent_validated'] is False and prepared['native_calls']==prepared['provider_calls']==0
    with pytest.raises(FileExistsError):m.prepare(a,b,tmp_path/'knowledge')


def graph_node(base,request):
    req=base/'request.json'
    sources=[{'id':'request','path':str(req),'sha256':pin(req)['sha256']}]
    sources += [{'id':'source.'+str(i),'path':p['path'],'sha256':p['sha256']} for i,p in enumerate(pk.input_pins(request,base))]
    return {'id':'retrieve','kind':'tool','role':'proposer','depends_on':[],'inputs':sources,'packet':None,
            'action':'physics-knowledge','parameters':{'request_input':'request'},'max_attempts':1}


def test_real_existing_graph_and_host_consume_output_without_model_dispatch(tmp_path):
    a,b,_,_=fixture(tmp_path);request=m.prepare(a,b,tmp_path/'knowledge')
    node=graph_node(tmp_path/'knowledge',request)
    spec={'schema_version':1,'graph_id':'supplied-SMS-context',
          'budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,'max_wall_seconds':30,'max_reworks':0},'nodes':[node]}
    root=tmp_path/'graph';agent_graph.create(root,spec)
    result=agent_graph.execute(root,agent_host.AgentHost(),workers=1)
    assert result['complete'] and result['usage']['calls']==1
    assert agent_graph.execute(root,agent_host.AgentHost(),workers=1)['usage']['calls']==1
    assert not (root/'science-approval.json').exists()


@pytest.mark.parametrize('attack',['report_truncated','report_reclassified','unknown_as_zero','native_missing_field',
                                  'duplicate_group','duplicate_sms_identity','negative_weight','bool_energy','nan_text',
                                  'wrong_source_version'])
def test_malformed_or_rehashed_population_refuses_before_output(tmp_path,attack):
    a,b,n,r=fixture(tmp_path)
    if attack=='report_truncated':r['coverage']['groups'][0]['signatures'].pop()
    elif attack=='report_reclassified':r['status']='failed'
    elif attack=='unknown_as_zero':r['coverage']['omitted_below_sigmacut_not_zero']=False
    elif attack=='native_missing_field':n.pop('decomposition')
    elif attack=='duplicate_group':n['coverage'].append(deepcopy(n['coverage'][0]));r['coverage']['groups']=deepcopy(n['coverage'])
    elif attack=='duplicate_sms_identity':n['coverage'][0]['signatures'][0]['native_sms_ids']=[1,1];r['coverage']['groups']=deepcopy(n['coverage'])
    elif attack=='negative_weight':n['coverage'][0]['signatures'][0]['weight_fb']=-1;r['coverage']['groups']=deepcopy(n['coverage'])
    elif attack=='bool_energy':n['coverage'][0]['sqrts_tev']=True;r['coverage']['groups']=deepcopy(n['coverage'])
    elif attack=='wrong_source_version':r['runtime']['smodels_version']='different-version'
    a=write(Path(a['path']),n);b=write(Path(b['path']),r)
    if attack=='nan_text':
        p=Path(a['path']);p.write_text(p.read_text().replace('13.0','NaN'));a=pin(p)
    with pytest.raises(ValueError):m.prepare(a,b,tmp_path/'refused')
    assert not (tmp_path/'refused').exists()


def test_oversize_complete_population_refuses_without_first_signature_fallback(tmp_path):
    a,b,n,r=fixture(tmp_path)
    n['coverage'][0]['signatures'] *= 129;r['coverage']['groups']=deepcopy(n['coverage'])
    a=write(Path(a['path']),n);b=write(Path(b['path']),r)
    # Increase through the existing strict complete-census bound, without slicing.
    n['coverage'][0]['signatures'] *= 2;r['coverage']['groups']=deepcopy(n['coverage'])
    a=write(Path(a['path']),n);b=write(Path(b['path']),r)
    with pytest.raises(ValueError,match='no automatic truncation'):m.prepare(a,b,tmp_path/'refused')
    assert not (tmp_path/'refused').exists()


def test_no_evidence_index_in_original_scientific_output_inventory(tmp_path):
    a,b,_,_=fixture(tmp_path)
    with pytest.raises(ValueError,match='original output directory'):m.prepare(a,b,Path(a['path']).parent/'derived')
    assert sorted(p.name for p in Path(a['path']).parent.iterdir())==['portfolio-native.json','portfolio.json']


@pytest.mark.parametrize('alias',['unrelated_parent','base_parent'])
def test_dotdot_output_alias_refuses_before_original_inventory_changes(tmp_path,alias):
    a,b,_,_=fixture(tmp_path)
    original=Path(a['path']).parent
    before={p.name:pin(p) for p in original.iterdir()}
    if alias=='unrelated_parent':
        (tmp_path/'unrelated').mkdir()
        output=tmp_path/'unrelated'/'..'/'original'/'derived'
    else:
        output=tmp_path/'..'/tmp_path.name/'original'/'derived'
    with pytest.raises(ValueError,match='parent-directory aliases'):
        m.prepare(a,b,output,base=tmp_path)
    assert {p.name:pin(p) for p in original.iterdir()}==before
    assert not (original/'derived').exists()


def test_original_source_drift_invalidates_retrieval_and_missing_parent_host_refuses(tmp_path):
    a,b,_,_=fixture(tmp_path);request=m.prepare(a,b,tmp_path/'knowledge')
    node=graph_node(tmp_path/'knowledge',request)
    node['inputs']=[p for p in node['inputs'] if p['path']!=a['path']]
    spec={'schema_version':1,'graph_id':'incomplete-parent',
          'budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,'max_wall_seconds':30,'max_reworks':0},'nodes':[node]}
    root=tmp_path/'graph';agent_graph.create(root,spec)
    result=agent_graph.execute(root,agent_host.AgentHost(),workers=1)
    assert not result['complete']
    Path(a['path']).write_bytes(Path(a['path']).read_bytes()+b'changed')
    with pytest.raises(ValueError):pk.retrieve(request,tmp_path)


def test_ending_original_change_refuses_preparation_without_valid_request(tmp_path,monkeypatch):
    a,b,_,_=fixture(tmp_path);original=pk.retrieve
    def changed(*args):
        Path(a['path']).write_bytes(Path(a['path']).read_bytes()+b'changed')
        return original(*args)
    monkeypatch.setattr(pk,'retrieve',changed)
    with pytest.raises(ValueError):m.prepare(a,b,tmp_path/'retained-partial')
    assert (tmp_path/'retained-partial/knowledge.json').exists()
    assert not (tmp_path/'retained-partial/request.json').exists()
    assert not (tmp_path/'retained-partial/PREPARATION.json').exists()


def test_failed_native_disposition_and_all_coverage_remain_failure_evidence(tmp_path):
    a,b,n,r=fixture(tmp_path)
    n['output_status']['decomposition status']=-1
    r['output_status']=deepcopy(n['output_status']);r['status']='failed'
    a=write(Path(a['path']),n);b=write(Path(b['path']),r)
    request=m.prepare(a,b,tmp_path/'failed-evidence')
    packet=pk.retrieve(request,tmp_path)
    assert len(packet['nodes'])==8 and packet['claims']=={'physics_verified':False,'execution_authorized':False}
    basis=json.loads((tmp_path/'failed-evidence/coverage-evidence.jsonl').read_text().splitlines()[0])
    assert basis['status']=='failed' and (basis['complete_groups'],basis['complete_signatures'])==(3,4)
    assert json.loads((tmp_path/'failed-evidence/PREPARATION.json').read_text())['accepted_parent_validated'] is False


def test_existing_research_cycle_retains_full_source_premises_and_open_obligations(tmp_path):
    a,b,_,_=fixture(tmp_path);request=m.prepare(a,b,tmp_path/'knowledge')
    api=tmp_path/'source_api.py';api.write_text('def response_applicability(signature):\n    return None\n')
    context={'schema_version':1,'task_id':'supplied-SMS-followup',
        'task':'Retain complete unknown response coverage and design separately admitted discriminating tests.',
        'source_capsules':[],
        'api_documents':[{'id':'api','pin':{k:pin(api)[k] for k in ('path','sha256')},
                          'language':'python','role':'api','version':'Explicit synthetic source-control example','dependencies':[]}],
        'queries':[{'id':'response','symbol':'response_applicability','mode':'definition','documents':['api'],'required':True}],
        'requested_quantities':[{'id':'response','artifact':'future_response','pointer':'/value',
                                 'check':{'kind':'finite'},'meaning':'Future separately admitted response; none is supplied here.'}],
        'compatibility_groups':[{'id':'response','artifacts':['future_response'],'carryover':False,
                                 'basis':'A future response must be evaluated in its own model/domain study.'}],
        'max_source_bytes':128000,'max_context_bytes':16000,'max_steps':2}
    contract={'schema_version':1,'id':'SMS-unknown-followup','question':'Which responses remain unavailable for the complete supplied SMS population?',
        'scope':'Source-only synthetic consumer control; no model, response, native study or physics acceptance.',
        'context_request':write(tmp_path/'context.json',context),'premises':[],
        'budget':{'calls':2,'output_tokens':0,'wall_seconds':60,'native_attempts':1},
        'max_experiments':2,'exploration_every':2,'required_experiments':[]}
    root=tmp_path/'cycle';before=research_cycle.create(root,contract,base_dir=tmp_path, evaluation_harness=True)
    packet=pk.retrieve(request,tmp_path)
    mapping={p['id']:'smodels.'+p['id'] for p in packet['premises']}
    bound=research_cycle.bind_knowledge(root,pin(tmp_path/'knowledge/request.json'),premise_map=mapping,
                                     reason='Keep every overlapping SMS assertion and unknown response obligation.')
    assert len(bound['premises'])==8 and bound['knowledge_bindings'][-1]['source_assertions_only']
    assert bound['knowledge_bindings'][-1]['scientific_acceptance'] is False
    assert bound['resource_ledger']==before['resource_ledger']==[]
    selection=research_cycle.knowledge_next(root,obligation_designs={p['id']:[] for p in packet['test_obligations']})
    assert selection['selected'] is None and len(selection['missing_design_obligations'])==6
    assert len(selection['open_obligations'])==6 and not selection['execution_authorized']
    assert not selection['physics_validated'] and not selection['benefit_measured']
    assert not list(root.rglob('science-approval.json'))
