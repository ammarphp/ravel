"""Real entry-point controls with explicitly mocked parent scientific authority.

No model/compiler/native event is executed. External replies are mechanical
fixtures, while graph accounting, source materialization and ordinary admission
are the real implementations under review.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import re
import time
import pytest
from ravel import analysis_sources as sources
from ravel.physics import native_construction as nc, native_incumbent as n, routine_build, existing_events, science_worker
from ravel.workflow import agent_graph, science
from ravel.workflow.state_io import atomic_json,read_json
from test_native_construction import setup, deliver


def pin(p):return {'path':str(p),'sha256':sources.digest(p)}


def incumbent(tmp_path,monkeypatch,*,relative_pins=False):
    cfg,config=setup(tmp_path)
    if relative_pins:
        for field in ('source_capsule','build_template'):
            config[field]['path']=str(Path(config[field]['path']).relative_to(tmp_path))
        for row in config['api_sources']:
            row['path']=str(Path(row['path']).relative_to(tmp_path))
        atomic_json(cfg,config)
    packet=nc.write_source_packet(cfg,tmp_path/'initial-packet.json');packet={k:packet[k] for k in ('path','sha256')}
    graph=tmp_path/'old-graph'
    request=nc.prepare_agent_request(cfg,packet,graph,model='fixture-control',reasoning_effort='high')
    response=deliver(graph,request,config)
    saved,mr,rq,responses=nc._proposal_receipt(graph,packet)
    rd=tmp_path/'accepted-control';(rd/'outputs/attempt-1').mkdir(parents=True);(rd/'inputs').mkdir()
    result_path=rd/'outputs/attempt-1/result.json'
    result={'status':'passed','routine':'RAVEL_Unknown','scope':'Synthetic accepted-authority control',
        'census':{'events':2},'physics_validated':False,'rebuild':False}
    atomic_json(result_path,result)
    atomic_json(rd/'inputs/science-execution-task.json',{'task':{'events':str(tmp_path/'old.hepmc')}})
    (tmp_path/'old.hepmc').write_text('HepMC::Asciiv3-START_EVENT_LISTING\nE 1 1 1\nU GEV MM\nW 1\nP 1 0 11 1 0 0 1 0 1\nHepMC::Asciiv3-END_EVENT_LISTING\n')
    status={'state':'accepted','claim_scope':'diagnostic','live_errors':[],'cycle_id':'mock-parent-cycle'}
    view={'cycle':{'cycle_id':'mock-parent-cycle'},'reviews':[]}
    monkeypatch.setattr(n,'_admission',lambda *_:(deepcopy(status),view,[]))
    loaded=nc._load(cfg)
    protected=[cfg,Path(packet['path']),mr,rq,*responses,result_path,tmp_path/'old.hepmc']
    monkeypatch.setattr(n,'_measured_parent',lambda *_:{'rd':rd,'loaded':loaded,'result_path':result_path,
        'result':result,'task':{'routine':'RAVEL_Unknown'},'raw':saved['result']['value'],
        'model_receipt':mr,'status':deepcopy(status),'view':view,'saved':saved,'protected':protected})
    measurement=tmp_path/'measurement.json';atomic_json(measurement,{'covariance_records_observed':0})
    metric={'name':'conditional joint records acquired','direction':'maximize','incumbent_score':0,
        'measurement':pin(measurement),'location':'/covariance_records_observed','scope':'Mechanical controlled test declaration'}
    lineage=n.capture_incumbent(rd,cfg,packet,graph,tmp_path/'lineage.json',
        objective='Acquire explicitly labelled conditional joint information while preserving source endpoints.',metric=metric)
    positive=deepcopy(config);positive['target_routine']='RAVEL_Unknown_E1';positive['improvement_lineage']=lineage
    header=tmp_path/'Observer.hh';header.write_text('// Source-only proposed observer, unqualified\n')
    positive['support_sources']=[{**pin(header),'description':'Candidate observer interface, no native qualification'}]
    positive['obligations'].append({'id':'joint-information','description':'Acquire complete group vectors or declare the obligation unserved.'})
    cp=tmp_path/'positive.json';atomic_json(cp,positive)
    return locals()


def proposed(f,tmp_path,*,campaign=False):
    if campaign:
        c=n.prepare_continuation_campaign(f['lineage'],tmp_path/'campaign.json',tmp_path/'new-graph',phase_seconds=900)
        f['positive']['continuation_campaign']=c;atomic_json(f['cp'],f['positive']);graph=tmp_path/'new-graph'
    else:graph=f['graph']
    packet=nc.write_source_packet(f['cp'],tmp_path/'positive-packet.json');packet={k:packet[k] for k in ('path','sha256')}
    request=nc.prepare_agent_request(f['cp'],packet,graph,model='fixture-control',reasoning_effort='high')
    return graph,packet,request


def reply(f,graph,request,tmp_path,**changes):
    target=f['positive']['target_routine']
    value={'schema_version':1,'routine_name':target,'reference_data_name':'Unknown',
        'translation_unit':f'#include "Observer.hh"\nclass {target} {{}};\nRIVET_DECLARE_PLUGIN({target});\n',
        'metadata_info':f'Name: {target}\n','metadata_plot':f'# BEGIN PLOT /{target}/.*\n# END PLOT\n',
        'source_claim_ids':['source-all'],'served_obligations':['source-semantics','reference'],
        'unserved_obligations':['joint-information'],
        'supporting_files':[{'path':'Observer.hh','text':'// Mechanical proposed source, no native result\n'}],
        'public_rationale':'Actual fixture transport only; joint information is explicitly unserved.'}
    value.update(changes)
    response={'schema_version':1,'request_id':request['request_id'],'request_sha256':request['request_sha256'],
        'invocation_id':'mechanical-E1','actor_id':'fixture-control','observed_model':'fixture-control',
        'fresh_context':False,'parent_transcript_supplied':False,'value':value}
    path=tmp_path/'positive-response.json';atomic_json(path,response)
    agent_graph.deliver_external(graph,'construct',path)
    return path


def test_successful_parent_real_packet_same_graph_and_fresh_challenger(tmp_path,monkeypatch):
    f=incumbent(tmp_path,monkeypatch);old=Path(f['mr']).read_bytes()
    graph,packet,request=proposed(f,tmp_path)
    assert graph==f['graph']
    panel=read_json(packet['path'])
    assert panel['revision_type']=='improve_successful_native_incumbent' and panel['failure_trigger'] is None
    assert panel['previous_public_candidate']==f['saved']['result']['value']
    assert 'event_population' not in panel and 'raw parent event rows and oracle' in panel['withheld']
    assert request['prior_calls_retained']==1 and agent_graph.status(graph)['usage']['calls']==2
    reply(f,graph,request,tmp_path)
    draft=nc.materialize_agent_candidate(f['cp'],packet,graph,tmp_path/'challenger')
    capsule=sources.load_capsule(draft['capsule']);record,paths=n.source_binding(f['lineage'],capsule,tmp_path)
    assert (tmp_path/'challenger/source/Observer.hh').is_file()
    assert draft['binding']['prior_reviews_carried']==[]
    assert draft['binding']['retained_incumbent_result']==pin(f['result_path'])
    assert read_json(draft['build_task']['input'])['improvement_lineage']==f['lineage']
    assert not capsule['dependency_review']['complete'] and Path(f['mr']).read_bytes()==old
    assert Path(f['lineage']['path']) in paths
    with pytest.raises(ValueError,match='unresolved'):
        routine_build.inputs(draft['build_task'],tmp_path)


def test_expired_old_graph_refuses_without_reset_then_new_phase_debits_past_usage(tmp_path,monkeypatch):
    f=incumbent(tmp_path,monkeypatch)
    state=read_json(f['graph']/agent_graph.STATE);state['started_epoch']=time.time()-8000
    atomic_json(f['graph']/agent_graph.STATE,state)
    packet=nc.write_source_packet(f['cp'],tmp_path/'expired-packet.json');packet={k:packet[k] for k in ('path','sha256')}
    before=(f['graph']/agent_graph.STATE).read_bytes()
    with pytest.raises(agent_graph.GraphError,match='wall-time'):
        nc.prepare_agent_request(f['cp'],packet,f['graph'],model='fixture-control',reasoning_effort='high')
    assert (f['graph']/agent_graph.STATE).read_bytes()==before
    c=n.prepare_continuation_campaign(f['lineage'],tmp_path/'campaign.json',tmp_path/'new-graph')
    campaign=read_json(c['path']);assert campaign['remaining_budget']=={'max_calls':1,'max_output_tokens':16000}
    assert campaign['inherited_usage']=={'calls':1,'reserved_output_tokens':16000}
    assert campaign['original_elapsed_seconds_at_capture']>=8000
    assert not campaign['original_end_to_end_deadline_compliance_claimed'] and not (tmp_path/'new-graph').exists()
    f['positive']['continuation_campaign']=c;atomic_json(f['cp'],f['positive'])
    pp=nc.write_source_packet(f['cp'],tmp_path/'campaign-packet.json');pp={k:pp[k] for k in ('path','sha256')}
    request=nc.prepare_agent_request(f['cp'],pp,tmp_path/'new-graph',model='fixture-control',reasoning_effort='high')
    assert (f['graph']/agent_graph.STATE).read_bytes()==before
    assert agent_graph.status(tmp_path/'new-graph')['budget']['max_calls']==1
    assert request['inherited_usage']['calls']==1
    reply(f,tmp_path/'new-graph',request,tmp_path)
    draft=nc.materialize_agent_candidate(f['cp'],pp,tmp_path/'new-graph',tmp_path/'challenger')
    n.source_binding(f['lineage'],sources.load_capsule(draft['capsule']),tmp_path)


@pytest.mark.parametrize('change',['identity','ceiling','remaining','ledger','phase','lineage','bool-schema','bool-call'])
def test_rehashed_continuation_manifest_cannot_reset_or_transplant_budget(tmp_path,monkeypatch,change):
    f=incumbent(tmp_path,monkeypatch);cp=n.prepare_continuation_campaign(f['lineage'],tmp_path/'campaign.json',tmp_path/'new')
    doc=read_json(cp['path'])
    if change=='identity':doc['historical_instance_id']='wrong'
    if change=='ceiling':doc['cumulative_ceiling']['max_calls']=4
    if change=='remaining':doc['remaining_budget']['max_calls']=2
    if change=='ledger':doc['historical_ledger'][0]['sha256']='0'*64
    if change=='phase':doc['phase_seconds']=True
    if change=='lineage':doc['improvement_lineage']['sha256']='0'*64
    if change=='bool-schema':doc['schema_version']=True
    if change=='bool-call':doc['remaining_budget']['max_calls']=True
    atomic_json(cp['path'],doc)
    with pytest.raises(ValueError):n.validate_campaign(pin(Path(cp['path'])),tmp_path,f['lineage'])
    assert not(tmp_path/'new').exists()


def test_current_accounted_improver_materializes_through_real_worker(tmp_path,monkeypatch):
    f=incumbent(tmp_path,monkeypatch);graph,packet,request=proposed(f,tmp_path,campaign=True);reply(f,graph,request,tmp_path)
    task={'backend':'native-construction','input':str(f['cp']),'source_packet':packet,'graph_root':str(graph)}
    assert science.adapter({'mode':'analyze','task':task}) is nc
    assert Path(f['lineage']['path']) in science.task_inputs({'mode':'analyze','task':task,'max_seconds':80},tmp_path)
    from test_science_capability_integration import specification
    spec=specification('analyze',task);spec['max_seconds']=80
    science.validate(spec)
    from ravel.plotting import science_figures
    rd=tmp_path/'materialize-study';rd.mkdir()
    monkeypatch.setattr(science_worker,'verify_worker',lambda _: {'base_dir':str(tmp_path),'attempt':1,
        'output_directory':'outputs/attempt-1','stage_binding':{'input_snapshot':{}}})
    monkeypatch.setattr(science_worker,'execution_spec',lambda _:spec)
    monkeypatch.setattr(science_figures,'render',lambda *_:{'figures':[],'tables':[]})
    before=f['result_path'].read_bytes()
    assert science_worker.main([str(rd),'--attempt','1'])==0
    result=read_json(rd/'outputs/attempt-1/result.json')
    assert result['candidate_disposition']=='unreviewed_source' and result['model_calls']==0 and result['native_calls']==0
    assert result['prior_reviews_carried']==[] and f['result_path'].read_bytes()==before
    assert read_json(rd/'outputs/attempt-1/verification.json')['candidate_disposition']=='unreviewed_source'


@pytest.mark.parametrize('mutation',['parent','measurement','call','packet','header'])
def test_changed_parent_or_reply_inputs_refuse_before_worker_output(tmp_path,monkeypatch,mutation):
    f=incumbent(tmp_path,monkeypatch);graph,packet,request=proposed(f,tmp_path,campaign=True);reply(f,graph,request,tmp_path)
    task={'backend':'native-construction','input':str(f['cp']),'source_packet':packet,'graph_root':str(graph)}
    paths={'parent':f['result_path'],'measurement':f['measurement'],'call':next((f['graph']/'calls').glob('*.json')),
        'packet':Path(packet['path']),'header':f['header']}
    paths[mutation].write_text('{}')
    with pytest.raises((ValueError,agent_graph.GraphError)):nc.run(task,tmp_path,tmp_path/'refused')
    assert not(tmp_path/'refused').exists()


def test_ordinary_v1_plan_refuses_new_native_construction_capability(tmp_path,monkeypatch):
    f=incumbent(tmp_path,monkeypatch);graph,packet,request=proposed(f,tmp_path);reply(f,graph,request,tmp_path)
    task={'backend':'native-construction','input':str(f['cp']),'source_packet':packet,'graph_root':str(graph)}
    from test_science_capability_integration import specification
    doc=specification('analyze',task);doc.update(schema_version=1,max_seconds=60);doc.pop('review_policy');doc.pop('max_attempts')
    path=tmp_path/'legacy.json';atomic_json(path,doc)
    with pytest.raises(ValueError,match='schema_version=2|version 2|schema version 2|prospective'):
        science.plan(tmp_path/'legacy',path)


def test_new_lineage_is_required_by_build_source_and_native_event_task(tmp_path,monkeypatch):
    f=incumbent(tmp_path,monkeypatch);graph,packet,request=proposed(f,tmp_path);reply(f,graph,request,tmp_path)
    draft=nc.materialize_agent_candidate(f['cp'],packet,graph,tmp_path/'challenger')
    capsule=sources.load_capsule(draft['capsule'])
    root=Path(capsule['root']);(root/'Observer.hh').write_text('// tampered after actual reply\n')
    next(row for row in capsule['files'] if row['path']=='Observer.hh')['sha256']=sources.digest(root/'Observer.hh')
    with pytest.raises(ValueError,match='source/assets differ'):n.source_binding(f['lineage'],capsule,tmp_path)
    with pytest.raises(ValueError,match='paired lineage'):
        existing_events.validate({'backend':'rivet-built','routine':'x','build_receipt':'r','build_plan':'p',
            'events':'e','metadata':'m','runtime':{'python':'p','version':'4.1.3'},'observables':[],'options':{},'seed':1,
            'improvement_lineage':f['lineage']})


def test_event_relabeling_and_binary64_spelling_do_not_create_novel_input(tmp_path):
    old=tmp_path/'old.hepmc';new=tmp_path/'new.hepmc'
    text='HepMC::Asciiv3-START_EVENT_LISTING\nE 1 1 1\nU GEV MM\nW 1\nP 1 0 11 1.0 -0 0 1e0 0 1\nHepMC::Asciiv3-END_EVENT_LISTING\n'
    old.write_text(text);new.write_text(text.replace('E 1 ','E 99 ').replace('1.0 -0','1 0'))
    assert n._event_fingerprints(old)==n._event_fingerprints(new)
    new.write_text(text.replace('P 1 0 11 1.0','P 1 0 11 2.0'))
    assert n._event_fingerprints(old)!=n._event_fingerprints(new)


def test_particle_vertex_labels_order_and_decimal_rounding_cannot_fake_novelty(tmp_path):
    left=tmp_path/'left.hepmc';right=tmp_path/'right.hepmc'
    header='HepMC::Asciiv3-START_EVENT_LISTING\nE 1 1 2\nU GEV MM\nW 1\n'
    end='HepMC::Asciiv3-END_EVENT_LISTING\n'
    left.write_text(header+'P 1 0 11 0.1 0 0 1 0 2\nV -1 0 [1]\nP 2 -1 11 0.2 0 0 1 0 1\n'+end)
    right.write_text(header.replace('E 1','E 90')+'P 29 -9 11 0.2 0 0 1 0 1\nP 17 0 11 0.100000000000000001 0 0 1 0 2\nV -9 0 [17]\n'+end)
    assert n._event_fingerprints(left)==n._event_fingerprints(right)


def reviewed_build(f,draft,tmp_path):
    """Explicit mechanical dependency declaration, not a real reviewed build."""
    import sys
    cp=Path(draft['capsule']);capsule=read_json(cp)
    capsule['dependencies'][0]['status']='resolved'
    capsule['dependency_review']={'complete':True,'description':'Synthetic mechanical declared closure only'}
    atomic_json(cp,capsule)
    config=read_json(draft['build_task']['input'])
    builder=tmp_path/'not-executed-builder';builder.write_text('''rivetcxx=$(which $(echo "python3.12" | awk '{print $1}'))
if [[ -x "$rivetcxx" ]]; then
mycxx="python3.12"
elif [[ -x "$abscxx" ]]; then
mycxx="$CXX"
fi
''');builder.chmod(0o755)
    python=Path(sys.executable).resolve()
    config['runtime']={'tools':{'compiler':pin(python),'build':pin(builder),'python':pin(python),'probe':pin(python)},
        'artifacts':[pin(f['header'])],'environment':{'PATH':'/mechanical-empty-path'}}
    bp=tmp_path/'reviewed-build.json';atomic_json(bp,config)
    task={'backend':'routine-build','input':str(bp)}
    sealed=routine_build.seal_configuration(task,tmp_path);atomic_json(bp,sealed)
    return task,cp


def test_complete_lineage_is_real_build_input_and_public_plan_field(tmp_path,monkeypatch):
    f=incumbent(tmp_path,monkeypatch);graph,packet,request=proposed(f,tmp_path,campaign=True);reply(f,graph,request,tmp_path)
    draft=nc.materialize_agent_candidate(f['cp'],packet,graph,tmp_path/'challenger')
    task,cp=reviewed_build(f,draft,tmp_path)
    monkeypatch.setattr(routine_build.subprocess,'run',lambda *_a,**_k:pytest.fail('planning started a native process'))
    files=routine_build.inputs(task,tmp_path)
    assert Path(f['lineage']['path']) in files and f['result_path'] in files
    plan=routine_build.build_plan(task,tmp_path,tmp_path/'future-build-output')
    assert plan['improvement_lineage']==f['lineage'] and plan['prior_reviews_carried']==[]
    assert not(tmp_path/'future-build-output').exists()
    config=read_json(task['input']);config.pop('improvement_lineage');atomic_json(task['input'],config)
    with pytest.raises(ValueError,match='cannot be omitted'):routine_build.inputs(task,tmp_path)


def native_event_control(tmp_path):
    events=tmp_path/'new.hepmc';events.write_text('''HepMC::Version 3.02.05
HepMC::Asciiv3-START_EVENT_LISTING
W nominal
E 101 1 3
U GEV MM
W 1
P 1 0 2212 0 0 6500 6500 0 4
P 2 0 2212 0 0 -6500 6500 0 4
P 3 0 11 20 0 0 20 0 1
HepMC::Asciiv3-END_EVENT_LISTING
''')
    metadata=tmp_path/'metadata.json';atomic_json(metadata,{'schema_version':1,'event_level':'hadron',
        'beam_pdg':[2212,2212],'beam_energy_gev':[6500,6500],'weight_names':['nominal'],
        'events':1,'groups':'independent','cross_section_pb':1,'source':'Synthetic structural admission control'})
    return events,metadata


def test_event_plan_waits_for_actual_build_and_pins_full_evaluation(tmp_path,monkeypatch):
    f=incumbent(tmp_path,monkeypatch);graph,packet,request=proposed(f,tmp_path,campaign=True);reply(f,graph,request,tmp_path)
    draft=nc.materialize_agent_candidate(f['cp'],packet,graph,tmp_path/'challenger');task,cp=reviewed_build(f,draft,tmp_path)
    plan=routine_build.build_plan(task,tmp_path,tmp_path/'future-build-output')
    events,metadata=native_event_control(tmp_path)
    ep=tmp_path/'evaluation.json';atomic_json(ep,{'schema_version':1,'kind':'native-improvement-evaluation',
        'improvement_lineage':f['lineage'],'partition':'held_out','events':pin(events),'metadata':pin(metadata),
        'checker_inputs':[pin(f['measurement'])]})
    template={'backend':'rivet-built','routine':'RAVEL_Unknown_E1','runtime':{'python':'not-used-in-control','version':'4.1.3'},
        'events':str(events),'metadata':str(metadata),'observables':[{'path':'/RAVEL_Unknown_E1/h','axes':[{'name':'x','unit':'GeV'}],
            'representation':'integrated','normalization':'absolute','unit':'pb'}],'options':{},'seed':1}
    refusal=f"supplied input not found: {tmp_path/'future-receipt'}"
    with pytest.raises(science.MissingInput,match=re.escape(refusal)):
        n.prepare_event_task(f['lineage'],{'path':str(tmp_path/'future-receipt'),'sha256':'0'*64},
            {'path':str(tmp_path/'future-plan'),'sha256':'0'*64},template,pin(ep),tmp_path/'refused.json')
    assert not(tmp_path/'refused.json').exists()
    pp=tmp_path/'build-plan.json';rp=tmp_path/'build-receipt.json'
    atomic_json(pp,plan);atomic_json(rp,{'fixture_only':'mock delivered build; no native process'})
    # Only native receipt authentication is replaced. New source/Host/lineage/
    # event census and ordinary adapter dispatch/input inventory stay real.
    monkeypatch.setattr(existing_events,'_built_evidence',lambda *_:(rp,pp,{},plan,None,None,None))
    monkeypatch.setattr(existing_events,'_built_inputs',lambda *_:[rp,pp,events,metadata])
    output=tmp_path/'event-task.json'
    proposed_task=n.prepare_event_task(f['lineage'],pin(rp),pin(pp),template,pin(ep),output)
    candidate=read_json(output);assert candidate['improvement_lineage']==f['lineage']
    inputs=existing_events.inputs(candidate,tmp_path)
    assert ep in inputs and f['result_path'] in inputs and f['measurement'] in inputs
    evaluation=read_json(ep)
    ambiguous=deepcopy(evaluation);ambiguous['schema_version']=True;atomic_json(ep,ambiguous)
    rehashed=deepcopy(candidate);rehashed['improvement_evaluation']=pin(ep)
    with pytest.raises(ValueError,match='explicit fresh held-out'):
        existing_events.inputs(rehashed,tmp_path)
    evaluation['events']['sha256']='0'*64;atomic_json(ep,evaluation)
    with pytest.raises(ValueError):existing_events.inputs(candidate,tmp_path)


@pytest.mark.parametrize('held,full,accepted',[(False,True,True),(True,False,True),(True,True,False)])
def test_favorable_partial_or_unreviewed_challenger_keeps_incumbent(tmp_path,monkeypatch,held,full,accepted):
    f=incumbent(tmp_path,monkeypatch);p=tmp_path/'challenger-result.json'
    atomic_json(p,{'status':'passed','improvement_lineage':f['lineage'],'prior_reviews_carried':[]})
    result=n.compare_challenger(f['lineage'],challenger_result=pin(p),challenger_score=10,
        held_out_complete=held,full_case_complete=full,independently_accepted=accepted)
    assert result['next_action']=='retain_incumbent' and not result['automatic_promotion']


def test_failed_unknown_challenger_never_replaces_accepted_parent(tmp_path,monkeypatch):
    f=incumbent(tmp_path,monkeypatch)
    result=n.compare_challenger(f['lineage'],challenger_result=None,challenger_score=None,
        held_out_complete=False,full_case_complete=False,independently_accepted=False)
    assert result['next_action']=='retain_incumbent'
    p=tmp_path/'failed.json';atomic_json(p,{'status':'failed','improvement_lineage':f['lineage'],'prior_reviews_carried':[]})
    assert n.compare_challenger(f['lineage'],challenger_result=pin(p),challenger_score=None,
        held_out_complete=True,full_case_complete=True,independently_accepted=True)['next_action']=='retain_incumbent'


def historical_fixture(f,tmp_path,monkeypatch,*,failure=None,budget=None):
    """Explicit mechanical historical API fixture, not old-source acceptance.

    The real native caller uses the same strict consumer interface, while these
    fixtures avoid the generic gate's real metadata subprocesses.
    """
    import sys,types
    contract_path=tmp_path/'history-contract.json';receipt_path=tmp_path/'history-receipt.json'
    contract={'run_directory':str(f['rd']), 'budget':budget or {
        'worker_inner_seconds':400,'solver_work_cutoff_seconds':390,
        'initial_capture_compile_gate_seconds':30,'final_gate_reservation_seconds':10,
        'complete_worker_seconds':420}}
    atomic_json(contract_path,contract);atomic_json(receipt_path,{'explicit_fixture_only':True})
    h=types.ModuleType('ravel.workflow.historical_qualification');h.calls=[];h.digest=agent_graph.digest
    h.validate=lambda c:c
    h.verify_receipt=lambda c,r:read_json(n.bound(r,tmp_path))
    h.inputs=lambda c,r:[contract_path,n.bound(r,tmp_path)]
    h.hook_resource_bounds=lambda c,r:dict(c['budget'])
    h.execution_seconds=lambda c,r:c['budget']['complete_worker_seconds']
    class Session:
        def __init__(self,c,r,directory,*,worker_started):
            self.c,self.r,self.directory=c,r,n.fresh(directory);self.directory.mkdir(parents=True)
            self.work_deadline=worker_started+c['budget']['solver_work_cutoff_seconds'];self.phases=[]
            atomic_json(self.directory/'session.json',{'contract_sha256':h.digest(c),'receipt':r,
                'metadata_child_ceiling':2,'worker_inner_seconds':c['budget']['worker_inner_seconds'],
                'solver_work_cutoff_seconds':c['budget']['solver_work_cutoff_seconds'],'scientific_calls':0})
        def boundary(self,phase):
            assert self.phases==([] if phase=='initial' else ['initial'])
            self.phases.append(phase);h.calls.append(phase)
            atomic_json(self.directory/(phase+'-started.json'),{'phase':phase,'remaining_seconds':10,
                'metadata_child_number':len(self.phases)})
            if phase==failure:raise ValueError('explicit mechanical historical '+phase+' refusal')
            directory=self.directory/phase;directory.mkdir();path=directory/'receipt.json'
            atomic_json(path,{'fixture_only':True,'phase':phase});receipt=pin(path)
            atomic_json(self.directory/(phase+'-completed.json'),{'validation_receipt':receipt,'scientific_calls':0})
            return receipt
    h.WorkerSession=Session
    monkeypatch.setitem(sys.modules,'ravel.workflow.historical_qualification',h)
    from ravel import workflow
    monkeypatch.setattr(workflow,'historical_qualification',h,raising=False)
    doc=read_json(f['lineage']['path']);doc['parent_qualification']={'contract':pin(contract_path),'receipt':pin(receipt_path)}
    doc['protected_inputs'] += [pin(contract_path),pin(receipt_path)]
    atomic_json(f['lineage']['path'],doc);f['lineage']=pin(Path(f['lineage']['path']))
    f['positive']['improvement_lineage']=f['lineage'];atomic_json(f['cp'],f['positive'])
    return h


def test_historical_plan_is_zero_child_and_complete_outer_budget_required(tmp_path,monkeypatch):
    f=incumbent(tmp_path,monkeypatch);h=historical_fixture(f,tmp_path,monkeypatch)
    graph,packet,request=proposed(f,tmp_path,campaign=True);reply(f,graph,request,tmp_path)
    task={'backend':'native-construction','input':str(f['cp']),'source_packet':packet,'graph_root':str(graph)}
    monkeypatch.setattr(existing_events.subprocess,'run',lambda *_a,**_k:pytest.fail('planning launched process'))
    files=nc.inputs(task,tmp_path);assert Path(f['lineage']['path']) in files
    assert nc.execution_seconds(task,tmp_path)==420 and h.calls==[]
    with pytest.raises(ValueError,match='hard ceiling'):
        science.task_inputs({'mode':'analyze','task':task,'max_seconds':419},tmp_path)
    science.task_inputs({'mode':'analyze','task':task,'max_seconds':420},tmp_path)
    assert h.calls==[]


def test_real_materialization_worker_uses_two_distinct_boundary_receipts(tmp_path,monkeypatch):
    f=incumbent(tmp_path,monkeypatch);h=historical_fixture(f,tmp_path,monkeypatch)
    graph,packet,request=proposed(f,tmp_path,campaign=True);reply(f,graph,request,tmp_path)
    task={'backend':'native-construction','input':str(f['cp']),'source_packet':packet,'graph_root':str(graph)}
    before=f['result_path'].read_bytes();out=tmp_path/'worker'
    result=nc.run(task,tmp_path,out);proof=result['historical_qualification']
    assert h.calls==['initial','final'] and proof['initial']!=proof['final']
    n.verify_worker_boundaries(f['lineage'],proof,tmp_path,out)
    assert result['candidate_disposition']=='unreviewed_source'
    assert not proof['native_runtime_qualified_by_history'] and f['result_path'].read_bytes()==before
    changed=deepcopy(proof);changed['final']=changed['initial']
    with pytest.raises(ValueError,match='separate fresh'):
        n.verify_worker_boundaries(f['lineage'],changed,tmp_path,out)
    changed=deepcopy(proof);changed['session_inputs']=changed['session_inputs'][:-1]
    with pytest.raises(ValueError,match='complete exact'):
        n.verify_worker_boundaries(f['lineage'],changed,tmp_path,out)


@pytest.mark.parametrize('phase',['initial','final'])
def test_metadata_refusal_preserves_incumbent_and_never_returns_success(tmp_path,monkeypatch,phase):
    f=incumbent(tmp_path,monkeypatch);h=historical_fixture(f,tmp_path,monkeypatch,failure=phase)
    graph,packet,request=proposed(f,tmp_path,campaign=True);reply(f,graph,request,tmp_path)
    task={'backend':'native-construction','input':str(f['cp']),'source_packet':packet,'graph_root':str(graph)}
    before=f['result_path'].read_bytes();out=tmp_path/'refused-worker'
    with pytest.raises(ValueError,match='historical '+phase+' refusal'):nc.run(task,tmp_path,out)
    assert h.calls==(['initial'] if phase=='initial' else ['initial','final'])
    assert (out/'historical-qualification'/(phase+'-started.json')).is_file()
    assert (out/'candidate/candidate-capsule.json').exists()==(phase=='final')
    assert f['result_path'].read_bytes()==before and not(out/'result.json').exists()


def test_selected_build_maximum_cannot_hide_in_too_small_history_budget(tmp_path,monkeypatch):
    f=incumbent(tmp_path,monkeypatch);h=historical_fixture(f,tmp_path,monkeypatch,budget={
        'worker_inner_seconds':150,'solver_work_cutoff_seconds':140,
        'initial_capture_compile_gate_seconds':30,'final_gate_reservation_seconds':10,'complete_worker_seconds':160})
    with pytest.raises(ValueError,match='omits selected native branch'):
        n.execution_seconds(f['lineage'],tmp_path,360)
    assert h.calls==[]


def test_actual_event_adapter_carries_initial_final_and_retains_parent(tmp_path,monkeypatch):
    f=incumbent(tmp_path,monkeypatch);h=historical_fixture(f,tmp_path,monkeypatch)
    graph,packet,request=proposed(f,tmp_path,campaign=True);reply(f,graph,request,tmp_path)
    draft=nc.materialize_agent_candidate(f['cp'],packet,graph,tmp_path/'challenger')
    build_task,cp=reviewed_build(f,draft,tmp_path)
    plan=routine_build.build_plan(build_task,tmp_path,tmp_path/'future-build')
    pp,rp=tmp_path/'build-plan.json',tmp_path/'build-receipt.json'
    atomic_json(pp,plan);atomic_json(rp,{'mock_native_build_authentication':True})
    events,metadata=native_event_control(tmp_path);ep=tmp_path/'evaluation.json'
    atomic_json(ep,{'schema_version':1,'kind':'native-improvement-evaluation',
        'improvement_lineage':f['lineage'],'partition':'full_case','events':pin(events),
        'metadata':pin(metadata),'checker_inputs':[pin(f['measurement'])]})
    task={'backend':'rivet-built','routine':f['positive']['target_routine'],'build_receipt':str(rp),'build_plan':str(pp),
        'runtime':{'python':'not-used','version':'4.1.3'},'events':str(events),'metadata':str(metadata),
        'observables':[{'path':'/RAVEL_Unknown_E1/h','axes':[{'name':'x','unit':'GeV'}],
            'representation':'integrated','normalization':'absolute','unit':'pb'}],
        'options':{},'seed':1,'improvement_lineage':f['lineage'],'improvement_evaluation':pin(ep)}
    monkeypatch.setattr(existing_events,'_built_evidence',lambda *_:(rp,pp,{},plan,None,None,None))
    monkeypatch.setattr(existing_events,'_built_inputs',lambda *_:[rp,pp,events,metadata])
    def observed(*_a,work_deadline):
        assert h.calls==['initial'] and time.monotonic()<work_deadline
        return {'status':'passed','fixture_native_execution_replaced':True}
    monkeypatch.setattr(existing_events,'_run_built',observed)
    assert existing_events.execution_seconds(task,tmp_path)==420 and h.calls==[]
    result=existing_events.run(task,tmp_path,tmp_path/'event-worker')
    assert h.calls==['initial','final'] and result['prior_reviews_carried']==[]
    assert not result['challenger_replaces_incumbent'] and not result['historical_qualification']['new_native_authority_inherited']


@pytest.mark.parametrize('mutate',['omitted-ledger','bool-output','bool-captured-calls','extra-call','authority','scope-clock'])
def test_rehashed_positive_contract_rejects_ledger_or_budget_declarations(tmp_path,monkeypatch,mutate):
    f=incumbent(tmp_path,monkeypatch)
    if mutate in ('omitted-ledger','scope-clock'):
        c=n.prepare_continuation_campaign(f['lineage'],tmp_path/'campaign.json',tmp_path/'new-graph')
        doc=read_json(c['path'])
        if mutate=='omitted-ledger':doc['historical_ledger']=doc['historical_ledger'][:1]
        else:doc['original_wall_ceiling_seconds']=900
        atomic_json(c['path'],doc)
        with pytest.raises(ValueError):n.validate_campaign(pin(Path(c['path'])),tmp_path,f['lineage'])
    else:
        doc=read_json(f['lineage']['path'])
        if mutate=='bool-output':doc['model_cost_bound']['max_output_tokens']=True
        elif mutate=='bool-captured-calls':doc['calls_at_capture']=True
        elif mutate=='extra-call':doc['model_cost_bound']['max_additional_calls']=2
        else:doc['model_cost_bound']['native_attempts_approved']=1
        atomic_json(f['lineage']['path'],doc)
        with pytest.raises(ValueError):n.validate_lineage(pin(Path(f['lineage']['path'])),tmp_path)
    assert not(tmp_path/'new-graph').exists()


def test_reply_bound_native_capsule_cannot_add_an_unaccounted_compile_unit(tmp_path,monkeypatch):
    f=incumbent(tmp_path,monkeypatch);graph,packet,request=proposed(f,tmp_path,campaign=True)
    reply(f,graph,request,tmp_path)
    draft=nc.materialize_agent_candidate(f['cp'],packet,graph,tmp_path/'challenger')
    capsule=sources.load_capsule(draft['capsule']);root=Path(capsule['root'])
    extra=root/'unaccounted.cc';extra.write_text('// Not part of the actual Host reply\n')
    capsule['files'].append({'path':extra.name,'sha256':sources.digest(extra),'role':'compile'})
    with pytest.raises(ValueError,match='source/assets differ from actual improved'):
        n.source_binding(f['lineage'],capsule,tmp_path)


def test_build_process_timeout_debits_remaining_branch_without_process(tmp_path,monkeypatch):
    import types
    observed=[]
    def process(command,**kwargs):
        observed.append(kwargs['timeout']);return types.SimpleNamespace(returncode=0,stdout=b'ok',stderr=b'')
    monkeypatch.setattr(routine_build.subprocess,'run',process)
    routine_build._process(['mechanical'],tmp_path,{},tmp_path/'log.json',work_deadline=time.monotonic()+3)
    assert 0<observed[0]<=3
    with pytest.raises(TimeoutError):
        routine_build._process(['must-not-dispatch'],tmp_path,{},tmp_path/'refused.json',work_deadline=time.monotonic()-1)
    assert len(observed)==1 and not(tmp_path/'refused.json').exists()


def test_ordinary_build_worker_wraps_selected_three_process_branch_with_old_gates(tmp_path,monkeypatch):
    """Native compiler/OS observations are explicitly replaced; caller stays real."""
    f=incumbent(tmp_path,monkeypatch);h=historical_fixture(f,tmp_path,monkeypatch)
    graph,packet,request=proposed(f,tmp_path,campaign=True);reply(f,graph,request,tmp_path)
    draft=nc.materialize_agent_candidate(f['cp'],packet,graph,tmp_path/'challenger')
    task,cp=reviewed_build(f,draft,tmp_path);out=tmp_path/'build-worker';calls=[]
    assert routine_build.execution_seconds(task,tmp_path)==420 and h.calls==[]
    def process(command,directory,environment,log,*,work_deadline):
        assert h.calls==['initial'] and time.monotonic()<work_deadline
        calls.append(list(command));stdout=f['positive']['target_routine'].encode()
        atomic_json(log,{'stderr_base64':'','mock_native_execution':True})
        if '-j' in command:
            Path(command[3]).write_bytes(b'explicit mechanical native output fixture')
        if Path(log).name=='probe.log':
            atomic_json(out/'loader-observation.json',{'native_OS_identity_explicitly_replaced':True})
            (out/'compiler-invocations.jsonl').write_text('native compiler observation explicitly replaced\n')
        return 0,stdout
    monkeypatch.setattr(routine_build,'_process',process)
    monkeypatch.setattr(routine_build,'verify_compiler_invocations',lambda *_:None)
    monkeypatch.setattr(routine_build,'verify_loader_observation',lambda *_a,**_k:{'native_identity_explicitly_replaced':True})
    before=f['result_path'].read_bytes();receipt=routine_build.run(task,tmp_path,out)
    assert len(calls)==3 and h.calls==['initial','final']
    assert receipt['improvement_lineage']==f['lineage'] and receipt['prior_reviews_carried']==[]
    assert receipt['historical_qualification']['selected_work_seconds_ceiling']==360
    assert f['result_path'].read_bytes()==before
    n.verify_worker_boundaries(f['lineage'],receipt['historical_qualification'],tmp_path,out)


def test_build_initial_old_gate_refusal_prevents_any_native_dispatch(tmp_path,monkeypatch):
    f=incumbent(tmp_path,monkeypatch);h=historical_fixture(f,tmp_path,monkeypatch,failure='initial')
    graph,packet,request=proposed(f,tmp_path,campaign=True);reply(f,graph,request,tmp_path)
    draft=nc.materialize_agent_candidate(f['cp'],packet,graph,tmp_path/'challenger')
    task,cp=reviewed_build(f,draft,tmp_path);out=tmp_path/'refused-build'
    monkeypatch.setattr(routine_build,'_process',lambda *_a,**_k:pytest.fail('native dispatch before failed old gate'))
    with pytest.raises(ValueError,match='historical initial refusal'):routine_build.run(task,tmp_path,out)
    assert h.calls==['initial'] and not(out/'build-receipt.json').exists()


def test_positive_event_route_cap0_is_passed_and_recorded_without_inventing_effective_weights(tmp_path,monkeypatch):
    import sys
    from types import SimpleNamespace
    f=incumbent(tmp_path,monkeypatch);h=historical_fixture(f,tmp_path,monkeypatch)
    graph,packet,request=proposed(f,tmp_path,campaign=True);reply(f,graph,request,tmp_path)
    draft=nc.materialize_agent_candidate(f['cp'],packet,graph,tmp_path/'challenger')
    build_task,cp=reviewed_build(f,draft,tmp_path)
    plan=routine_build.build_plan(build_task,tmp_path,tmp_path/'delivered-build')
    pp,rp=tmp_path/'build-plan.json',tmp_path/'build-receipt.json'
    atomic_json(pp,plan);atomic_json(rp,{'mock_native_build_authentication':True})
    binary=tmp_path/'mock-plugin.so';binary.write_bytes(b'Native identity explicitly replaced')
    executable=tmp_path/'mock-rivet';executable.write_text('Never executed\n')
    python=Path(sys.executable).resolve();events,metadata=native_event_control(tmp_path)
    ep=tmp_path/'full-evaluation.json';atomic_json(ep,{'schema_version':1,'kind':'native-improvement-evaluation',
        'improvement_lineage':f['lineage'],'partition':'full_case','events':pin(events),'metadata':pin(metadata),
        'checker_inputs':[pin(f['measurement'])]})
    path='/RAVEL_Unknown_E1/h'
    task={'backend':'rivet-built','routine':f['positive']['target_routine'],'build_receipt':str(rp),'build_plan':str(pp),
        'runtime':{'python':str(python),'version':'4.1.3'},'events':str(events),'metadata':str(metadata),
        'observables':[{'path':path,'axes':[{'name':'x','unit':'GeV'}],
            'representation':'integrated','normalization':'absolute','unit':'pb'}],'options':{},'seed':1,
        'improvement_lineage':f['lineage'],'improvement_evaluation':pin(ep),'native_weight_cap':0}
    receipt={'binary':pin(binary)};out=tmp_path/'actual-adapter-mechanical-control';calls=[]
    monkeypatch.setattr(existing_events,'_built_evidence',lambda *_:(rp,pp,receipt,plan,python,executable,binary))
    monkeypatch.setattr(routine_build,'bound_routine',lambda *_:{'explicit_native_source_authentication_mock':True})
    monkeypatch.setattr(routine_build,'verify_loader_observation',lambda *_a,**_k:{'explicit_OS_authentication_mock':True})
    monkeypatch.setattr(existing_events.subprocess,'run',lambda *_a,**_k:SimpleNamespace(returncode=0,stdout='rivet v4.1.3\n'))
    def call(command,cwd,env,log,*,work_deadline):
        assert h.calls==['initial'] and time.monotonic()<work_deadline
        calls.append(list(command));Path(log).write_text('Explicit mechanical native output fixture\n')
        if '--weight-cap' in command:
            (out/'histograms.yoda').write_text('Synthetic native data fixture\n')
            atomic_json(out/'loader-event-observation.json',{'runtime_version':'4.1.3',
                'python':pin(python),'explicit_OS_identity_mock':True})
        else:
            atomic_json(out/'observables.json',{'observables':{path:{}},
                'event_counters':{'/RAW/_EVTCOUNT':{'entries':1,'sumw':1,'sumw2':1}}})
    monkeypatch.setattr(existing_events,'_call',call)
    result=existing_events.run(task,tmp_path,out)
    assert len(calls)==2 and h.calls==['initial','final']
    assert calls[0][calls[0].index('--weight-cap')+1]=='0'
    assert result['native_weight_cap']==0 and result['native_effective_weights_observed'] is False
    assert result['historical_qualification']['selected_work_seconds_ceiling']==180
    assert read_json(out/'build-reuse.json')['native_dispatch']==result['native_dispatch']
    assert not result['challenger_replaces_incumbent']


def test_concrete_positive_preparation_has_exact_packet_and_no_host_or_native_action(tmp_path,monkeypatch):
    f=incumbent(tmp_path,monkeypatch);oldgraph=(f['graph']/agent_graph.STATE).read_bytes()
    monkeypatch.setattr(agent_graph,'create',lambda *_a,**_k:pytest.fail('preparation reserved graph'))
    monkeypatch.setattr(existing_events.subprocess,'run',lambda *_a,**_k:pytest.fail('preparation launched process'))
    result=n.prepare_improvement_packet(f['lineage'],tmp_path/'prepared-E1',
        target_routine='RAVEL_Unknown_E1',additional_obligations=[{'id':'joint-information',
            'description':'Qualify complete native group vectors or declare them unserved.'}],
        support_sources=f['positive']['support_sources'],continuation_graph=tmp_path/'new-graph')
    panel=read_json(result['source_packet']['path'])
    assert panel['previous_public_candidate']==f['saved']['result']['value']
    assert panel['revision_type']=='improve_successful_native_incumbent' and panel['failure_trigger'] is None
    assert {row['id'] for row in panel['obligations']}=={'source-semantics','reference','joint-information'}
    assert not result['host_call_reserved'] and not result['future_build_receipt_invented']
    assert not(tmp_path/'new-graph').exists() and (f['graph']/agent_graph.STATE).read_bytes()==oldgraph
    with pytest.raises((ValueError,FileNotFoundError)):
        nc.inputs(result['prospective_materialization_task'],tmp_path)


def test_positive_preparation_cannot_replace_incumbent_or_remove_prior_obligations(tmp_path,monkeypatch):
    f=incumbent(tmp_path,monkeypatch)
    for target,obligations in [('RAVEL_Unknown',[{'id':'new','description':'x'}]),
                               ('RAVEL_Unknown_E1',[{'id':'reference','description':'replace reference'}])]:
        with pytest.raises(ValueError):n.prepare_improvement_packet(f['lineage'],tmp_path/'refused',
            target_routine=target,additional_obligations=obligations,support_sources=[],
            continuation_graph=tmp_path/'new')
    assert not(tmp_path/'refused').exists() and not(tmp_path/'new').exists()


@pytest.mark.parametrize('mutation',['obligation-text','claim-span','copied-capsule'])
def test_successful_parent_retains_exact_obligation_claim_and_capsule_before_packet(tmp_path,monkeypatch,mutation):
    """Valid local replacements must still refuse successful-parent semantics."""
    f=incumbent(tmp_path,monkeypatch)
    before={p:p.read_bytes() for p in f['protected']}
    oldgraph=(f['graph']/agent_graph.STATE).read_bytes()
    if mutation=='obligation-text':
        f['positive']['obligations'][0]['description']='Serve only the new joint objective; discard original source semantics.'
    elif mutation=='claim-span':
        claim=f['positive']['source_claims'][0]
        claim.update(line_start=2,line_end=2,
            excerpt_sha256=hashlib.sha256((tmp_path/'original/Unknown.cc').read_bytes().splitlines(keepends=True)[1]).hexdigest())
    else:
        copied=tmp_path/'identical-but-unrelated-capsule.json'
        copied.write_bytes((tmp_path/'source.json').read_bytes())
        f['positive']['source_capsule']=pin(copied)
    atomic_json(f['cp'],f['positive'])
    monkeypatch.setattr(agent_graph,'create',lambda *_a,**_k:pytest.fail('refused source reserved Host graph'))
    with pytest.raises(ValueError,match='retain source claims/obligations'):
        nc.write_source_packet(f['cp'],tmp_path/'refused-packet.json')
    assert not(tmp_path/'refused-packet.json').exists()
    assert before=={p:p.read_bytes() for p in before}
    assert (f['graph']/agent_graph.STATE).read_bytes()==oldgraph


def test_literal_parent_obligations_allow_new_claims_and_reordered_original_objects(tmp_path,monkeypatch):
    f=incumbent(tmp_path,monkeypatch)
    added={'id':'registration-only','path':'Unknown.cc','line_start':2,'line_end':2,
        'excerpt_sha256':hashlib.sha256((tmp_path/'original/Unknown.cc').read_bytes().splitlines(keepends=True)[1]).hexdigest()}
    f['positive']['source_claims'].insert(0,added)
    f['positive']['obligations'].reverse()
    atomic_json(f['cp'],f['positive'])
    packet=nc.write_source_packet(f['cp'],tmp_path/'additional-claim-packet.json')
    panel=read_json(packet['path'])
    claims={row['id']:{k:v for k,v in row.items() if k!='text'} for row in panel['source_claims']}
    obligations={row['id']:row for row in panel['obligations']}
    assert claims['source-all']==f['config']['source_claims'][0] and claims[added['id']]==added
    assert all(obligations[row['id']]==row for row in f['config']['obligations'])
    assert 'joint-information' in obligations and not packet['model_executed']


def test_relative_incumbent_pins_prepare_same_artifacts_in_a_fresh_directory(tmp_path,monkeypatch):
    f=incumbent(tmp_path,monkeypatch,relative_pins=True)
    before={p:p.read_bytes() for p in f['protected']}
    oldgraph=(f['graph']/agent_graph.STATE).read_bytes()
    # Caller pins also have a different base from the new proposal directory.
    lineage={**f['lineage'],'path':Path(f['lineage']['path']).name}
    support={**f['positive']['support_sources'][0],'path':f['header'].name}
    monkeypatch.setattr(agent_graph,'create',lambda *_a,**_k:pytest.fail('preparation reserved Host graph'))
    monkeypatch.setattr(existing_events.subprocess,'run',lambda *_a,**_k:pytest.fail('preparation launched process'))
    output=tmp_path/'fresh/subdirectory/E1'
    result=n.prepare_improvement_packet(lineage,output,target_routine='RAVEL_Unknown_E1',
        additional_obligations=[{'id':'joint-information','description':'Acquire joint vectors or declare them unserved.'}],
        support_sources=[support],continuation_graph=tmp_path/'fresh/new-graph',base=tmp_path)
    loaded=nc._load(result['configuration']['path']);config=loaded['config']
    assert loaded['capsule_path']==tmp_path/'source.json'
    assert loaded['template_path']==tmp_path/'runtime.json'
    assert config['api_sources'][0]['path']==str(tmp_path/'Analysis.hh')
    assert config['support_sources']==[{**pin(f['header']),'description':support['description']}]
    assert config['improvement_lineage']==pin(Path(f['lineage']['path']))
    assert config['source_claims']==f['config']['source_claims']
    assert config['obligations'][:len(f['config']['obligations'])]==f['config']['obligations']
    campaign=n.validate_campaign(result['continuation_campaign'],output,config['improvement_lineage'])
    assert campaign['inherited_usage']=={'calls':1,'reserved_output_tokens':16000}
    panel=read_json(result['source_packet']['path'])
    assert panel==nc._source_packet(loaded)
    assert not result['host_call_reserved'] and not(tmp_path/'fresh/new-graph').exists()
    assert before=={p:p.read_bytes() for p in before}
    assert (f['graph']/agent_graph.STATE).read_bytes()==oldgraph


def test_common_worker_clock_cannot_be_reset_or_forged(tmp_path,monkeypatch):
    f=incumbent(tmp_path,monkeypatch);graph,packet,request=proposed(f,tmp_path,campaign=True);reply(f,graph,request,tmp_path)
    task={'backend':'native-construction','input':str(f['cp']),'source_packet':packet,'graph_root':str(graph)}
    with pytest.raises(TimeoutError,match='work deadline'):
        nc.run_in_worker(task,tmp_path,tmp_path/'late',worker_started=time.monotonic()-81)
    assert not(tmp_path/'late').exists()
    for value in (True,float('nan'),float('inf'),time.monotonic()+100):
        with pytest.raises(ValueError,match='common worker monotonic'):
            nc.run_in_worker(task,tmp_path,tmp_path/'forged',worker_started=value)
    assert not(tmp_path/'forged').exists()


def test_common_worker_start_is_forwarded_before_source_admission(tmp_path,monkeypatch):
    from test_science_capability_integration import specification
    from ravel.plotting import science_figures
    observed=[];start=[]
    rd=tmp_path/'worker';rd.mkdir()
    spec=specification('analyze',{'backend':'native-construction','input':'fixture','source_packet':{'path':'fixture','sha256':'0'*64},'graph_root':'fixture'})
    monkeypatch.setattr(science_worker,'verify_worker',lambda *_:start.append(time.monotonic()) or {'base_dir':str(tmp_path),'attempt':1,
        'output_directory':'outputs/attempt-1','stage_binding':{'input_snapshot':{}}})
    monkeypatch.setattr(science_worker,'execution_spec',lambda *_:spec)
    def execute(_task,_base,_out,*,worker_started):
        observed.append(worker_started)
        return {'status':'passed','kind':'native-construction-materialization','candidate_disposition':'unreviewed_source',
            'prior_reviews_carried':[],'execution_authorized':False,'physics_validated':False,'model_calls':0,'native_calls':0}
    monkeypatch.setattr(nc,'run_in_worker',execute)
    monkeypatch.setattr(science_figures,'render',lambda *_:{'figures':[],'tables':[]})
    assert science_worker.main([str(rd),'--attempt','1'])==0
    assert len(observed)==1 and observed[0]<=start[0]


@pytest.mark.parametrize('remaining',[-1,3])
def test_real_built_event_version_probe_obeys_remaining_budget(tmp_path,monkeypatch,remaining):
    """Real adapter preparation; native authentication and process are replaced."""
    from types import SimpleNamespace
    from test_rivet_built_adapter import evidence, task
    evidence(tmp_path,monkeypatch)
    monkeypatch.setattr(routine_build,'bound_routine',lambda *_:{'native_source_authentication_mock':True})
    observed=[]
    def process(command,**kwargs):
        observed.append((command,kwargs['timeout']))
        return SimpleNamespace(returncode=1,stdout='Explicit version-probe failure fixture',stderr='')
    monkeypatch.setattr(existing_events.subprocess,'run',process)
    if remaining<0:
        with pytest.raises(TimeoutError,match='before version probe'):
            existing_events._run_built(task(),tmp_path,tmp_path/'out',work_deadline=time.monotonic()+remaining)
        assert observed==[]
    else:
        with pytest.raises(ValueError,match='actual Rivet version'):
            existing_events._run_built(task(),tmp_path,tmp_path/'out',work_deadline=time.monotonic()+remaining)
        assert len(observed)==1 and observed[0][0][-1]=='--version' and 0<observed[0][1]<=remaining
    assert not(tmp_path/'out/build-reuse.json').exists()
