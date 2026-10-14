"""Source/call custody controls; fixture replies are not model efficacy evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ravel import analysis_sources as sources
from ravel.physics import native_construction as native, routine_build
from ravel.workflow import agent_graph
from ravel.workflow.state_io import atomic_json, read_json


def pin(path):
    return {"path": str(path), "sha256": sources.digest(path)}


def setup(tmp_path):
    root = tmp_path / 'original'; root.mkdir()
    code = root / 'Unknown.cc'; code.write_text('class Unknown {};\nRIVET_DECLARE_PLUGIN(Unknown);\n')
    (root / 'Unknown.info').write_text('Name: Unknown\n')
    (root / 'Unknown.yoda.gz').write_bytes(b'opaque-reference-control')
    cp = tmp_path / 'source.json'
    capsule = {'schema_version':1,'kind':'analysis-source-capsule','framework':'rivet','routine':'Unknown',
        'source':{'repository':'supplied','revision':None,'description':'Mechanical source transport control only'},
        'root':str(root),'files':[{'path':p.name,'sha256':sources.digest(p),'role':'compile' if p.suffix=='.cc' else 'configuration' if p.suffix=='.info' else 'reference'} for p in root.iterdir()],
        'layout':{'include_dirs':[],'asset_dirs':['.']},'dependencies':[],
        'dependency_review':{'complete':False,'description':'Control source; no native closure.'},'submodules':[]}
    atomic_json(cp,capsule)
    api = tmp_path / 'Analysis.hh'; api.write_text('void setRefDataName(string name);\n')
    template=tmp_path/'runtime.json';atomic_json(template,{'schema_version':2,'source_capsule':str(cp),
        'recipe':{'name':'rivet-plugin','compile_units':['Unknown.cc'],'output':'RivetControl.so','flags':[]},
        'runtime':{'tools':{},'artifacts':[pin(api)],'environment':{}},
        'probe':{'executable':'probe','arguments':[],'expected_exit_code':0,'stdout_contains':[]},
        'execution_identity':{'control_only':True}})
    config={'schema_version':1,'kind':'native-routine-construction','source_capsule':pin(cp),
        'target_routine':'RAVEL_Unknown','source_claims':[{'id':'source-all','path':'Unknown.cc','line_start':1,'line_end':2,
            'excerpt_sha256':hashlib.sha256(code.read_bytes()).hexdigest()}],
        'obligations':[{'id':'source-semantics','description':'Retain complete supplied source semantics.'},
            {'id':'reference','description':'Retain original reference identity.'}],
        'api_sources':[{**pin(api),'line_start':1,'line_end':1}], 'build_template':pin(template),
        'requested_task':'Construct the complete source routine, with distinct registration and original reference data.',
        'max_source_bytes':2000000}
    cfg=tmp_path/'construction.json';atomic_json(cfg,config)
    return cfg,config


def prepared(tmp_path):
    cfg,config=setup(tmp_path)
    packet=native.write_source_packet(cfg,tmp_path/'packet.json')
    packet_pin={k:packet[k] for k in ('path','sha256')}
    graph=tmp_path/'model-graph'
    request=native.prepare_agent_request(cfg,packet_pin,graph,model='fixture-control',reasoning_effort='high')
    return cfg,config,packet_pin,graph,request


def deliver(graph,request,config,*,wrong_registration=False,missing_obligation=False):
    target=config['target_routine'];register='Wrong' if wrong_registration else target
    value={'schema_version':1,'routine_name':target,'reference_data_name':'Unknown',
        'translation_unit':f'class {target} {{}};\nRIVET_DECLARE_PLUGIN({register});\n',
        'metadata_info':f'Name: {target}\n','metadata_plot':f'# BEGIN PLOT /{target}/.*\n# END PLOT\n',
        'source_claim_ids':['source-all'],'served_obligations':['source-semantics'] if missing_obligation else ['source-semantics','reference'],
        'unserved_obligations':[],'public_rationale':'Canned mechanical transport control, not actual model inference.'}
    response={'schema_version':1,'request_id':request['request_id'],'request_sha256':request['request_sha256'],
        'invocation_id':'fixture-response','actor_id':'fixture-control','observed_model':'fixture-control',
        'fresh_context':True,'parent_transcript_supplied':False,'value':value}
    path=graph.parent/'response.json';atomic_json(path,response)
    agent_graph.deliver_external(graph,'construct',path)
    return path


def test_source_packet_no_reservation_or_process_and_no_oracle(tmp_path,monkeypatch):
    cfg,config=setup(tmp_path)
    monkeypatch.setattr(routine_build.subprocess,'run',lambda *a,**k:pytest.fail('packet executed a process'))
    result=native.write_source_packet(cfg,tmp_path/'packet.json');packet=read_json(result['path'])
    assert not result['model_executed'] and not (tmp_path/'model-graph').exists()
    assert packet['source_dependency_review']['complete'] is False
    assert packet['source_text'][0]['text'].startswith('class Unknown')
    assert packet['reference_data_name']=='Unknown' and packet['target_routine']=='RAVEL_Unknown'
    assert {'evaluation events','expected outputs','previous typed program'}<=set(packet['withheld'])


def test_actual_receipted_control_materializes_new_unreviewed_capsule(tmp_path):
    cfg,config,packet,graph,request=prepared(tmp_path)
    response=deliver(graph,request,config)
    output=tmp_path/'candidate';draft=native.materialize_agent_candidate(cfg,packet,graph,output)
    capsule=sources.load_capsule(draft['capsule']);sources.source_files(capsule,output)
    assert not capsule['dependency_review']['complete']
    assert sources.digest(output/'source/original/Unknown.yoda.gz')==sources.digest(tmp_path/'original/Unknown.yoda.gz')
    assert sources.digest(output/'source/provenance/model-response-0.json')==sources.digest(response)
    assert draft['binding']['prior_reviews_carried']==[] and draft['binding']['fresh_runtime_seal_required']
    assert 'execution_identity' not in read_json(draft['build_task']['input'])
    with pytest.raises(ValueError,match='dependency'):
        routine_build.seal_configuration(draft['build_task'],output)
    with pytest.raises(ValueError,match='fresh ordinary directory'):
        native.materialize_agent_candidate(cfg,packet,graph,output)


def test_materialization_requires_completed_accounted_call(tmp_path):
    cfg,config,packet,graph,request=prepared(tmp_path)
    with pytest.raises(ValueError,match='completed proposer'):
        native.materialize_agent_candidate(cfg,packet,graph,tmp_path/'candidate')
    deliver(graph,request,config)
    call=next((graph/'calls').glob('*.json'));record=read_json(call);record['status']='failed';atomic_json(call,record)
    with pytest.raises(ValueError,match='accounting differs'):
        native.materialize_agent_candidate(cfg,packet,graph,tmp_path/'candidate')


def test_changed_external_raw_response_is_not_hidden_by_saved_public_value(tmp_path):
    cfg,config,packet,graph,request=prepared(tmp_path);response=deliver(graph,request,config)
    record=read_json(response);record['observed_model']='changed';atomic_json(response,record)
    with pytest.raises(ValueError,match='bytes differ'):
        native.materialize_agent_candidate(cfg,packet,graph,tmp_path/'candidate')


def test_rehashed_packet_cannot_change_original_source_meaning(tmp_path):
    cfg,config=setup(tmp_path);result=native.write_source_packet(cfg,tmp_path/'packet.json')
    record=read_json(result['path']);record['source_text'][0]['text']='invented answer';atomic_json(result['path'],record)
    with pytest.raises(ValueError,match='different source inputs'):
        native.prepare_agent_request(cfg,pin(Path(result['path'])),tmp_path/'graph',model='control',reasoning_effort='high')


@pytest.mark.parametrize('mutation', ['source','claim','api','template','target'])
def test_changed_source_claim_api_runtime_or_identity_refuses(tmp_path,mutation):
    cfg,config=setup(tmp_path)
    if mutation=='source':(tmp_path/'original/Unknown.cc').write_text('changed')
    if mutation=='api':(tmp_path/'Analysis.hh').write_text('changed')
    if mutation=='template':(tmp_path/'runtime.json').write_text('{}')
    if mutation=='claim':config['source_claims'][0]['excerpt_sha256']='0'*64;atomic_json(cfg,config)
    if mutation=='target':config['target_routine']='Unknown';atomic_json(cfg,config)
    with pytest.raises(ValueError):native.write_source_packet(cfg,tmp_path/'packet.json')


@pytest.mark.parametrize('wrong_registration,missing_obligation', [(True,False),(False,True)])
def test_registration_and_obligation_omissions_are_explicit_refusals(tmp_path,wrong_registration,missing_obligation):
    cfg,config,packet,graph,request=prepared(tmp_path)
    deliver(graph,request,config,wrong_registration=wrong_registration,missing_obligation=missing_obligation)
    with pytest.raises(ValueError):native.materialize_agent_candidate(cfg,packet,graph,tmp_path/'candidate')


def test_same_native_graph_cannot_reset_cumulative_reservation(tmp_path):
    cfg,config,packet,graph,request=prepared(tmp_path)
    with pytest.raises(ValueError,match='fresh ordinary graph'):
        native.prepare_agent_request(cfg,packet,graph,model='fixture-control',reasoning_effort='high')
    state=agent_graph.status(graph)
    assert state['usage']['calls']==1 and state['budget']['max_calls']==2
