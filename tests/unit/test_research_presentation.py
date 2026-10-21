"""Connected software-only presentation controls; all external transports inert."""
from copy import deepcopy
import hashlib, json
from pathlib import Path
import pytest
from ravel.workflow import research_cycle as cycle, research_protocol as proto, research_presentation as material
from ravel.workflow import agent_host, state_io, execution, review_context
from test_research_protocol import make, no_process, design, accepted_fixture
from test_research_cycle import contract, write


def population(base,root,n=150):
    _,state=cycle._load(root)
    folder=base/'supplied-native';folder.mkdir()
    pins=[]
    for i in range(n):
        path=folder/f'{i:06d}.bin';path.write_bytes(bytes([i%256,0,255,1]))
        pins.append(cycle._pin(path))
    # Explicit inert native inventory admission: no scientific acceptance or run.
    state['hypotheses'][0]['source_basis']=pins
    cycle._commit(root,state,'explicit_software_inventory_fixture')
    return pins


def selections(root,pin):
    inv=material.inventory(root)[1]
    identity=next(r['id'] for r in inv['files'] if r['pin']==pin)
    return [{'artifact_id':identity,'offset':1,'max_bytes':1024}]


def execute_meta(base,root,monkeypatch,*,pages=None,max_request=2_000_000,op='report_only',citation_id='public_case'):
    out=base/'meta'
    prepared=proto.prepare_meta_review(root,out,role='verifier',model='inert',reasoning_effort='high',max_output_tokens=256,max_wall_seconds=10,
        presentation='indexed',evidence_pages=pages)
    spec=state_io.read_json(prepared['graph_spec']['path']);manifest=state_io.read_json(out/'context/manifest.json')
    entry=next(e for e in manifest['artifacts'] if e['id']==citation_id)
    value={'kind':'research_meta_review','subject_sha256':prepared['context']['sha256'],'actor_id':prepared['actor_id'],'action':op,
        'affected_claim_ids':['complete-method'],'affected_stage_ids':[],'objections':[{'location':'full original matrix','statement':'Exact software-only report, no scientific judgment.'}],
        'required_experiment_ids':[],'premise_revision':None,'resolves_meta_revisions':[], 'replacement_stage_ids':[], 'replacement_comparison_ids':[], 'replacement_claim_ids':[],
        'evidence_citations':[{'artifact_id':entry['id'],'sha256':entry['sha256'],'location':'complete question and whole original obligations'}]}
    # An observed local model on loopback: meta actions need an observed transport; a control response is advice.
    host=agent_host.AgentHost(endpoint='http://127.0.0.1:9/v1/responses',max_request_bytes=max_request,
                              privacy='local_only',local_models=['inert'])
    def response(data,params,request,control):
        payload=json.loads(data)['input']
        assert 'complete-method' in json.dumps(payload)
        return host._result(value,params,request,response_id='inert-indexed-meta',observed_model='inert',usage={'input_tokens':8,'output_tokens':16})
    monkeypatch.setattr(host,'_responses',response)
    result=cycle.execute_graph(root,prepared['graph_root'],spec,host)
    return prepared,result,manifest


def test_initial_zero_fact_progress_complete_denominator_and_unchanged_final(tmp_path,monkeypatch):
    c=contract(tmp_path);root=tmp_path/'cycle';cycle.create(root,c,base_dir=tmp_path, evaluation_harness=True)
    before=cycle._load(root)[1]
    result=cycle.progress_synthesis(root)
    assert result['required_experiments']==['paired']
    assert result['all_experiments']==[{'id':'paired','status':'not_designed','observation':None,'scientific_acceptance':False}]
    assert len(result['requested_quantity_census'])==1 and result['accepted_scoped_facts'] is None
    assert 'No accepted quantitative facts' in result['report_text']
    assert not any(result[k] for k in ['final_delivery','parent_task_accepted','execution_authorized','physics_validated'])
    assert cycle._load(root)[1]==before
    with pytest.raises(ValueError,match='complete current'):cycle.synthesize(root,{},base_dir=tmp_path)


def test_progress_cli_and_parent_original_obligations(tmp_path,monkeypatch,capsys):
    from test_task_completion import goal,PROMPT
    _,parent=goal(tmp_path)
    c=contract(tmp_path);c['goal_binding']={'contract':parent,'assignment_id':'summary-child'}
    root=tmp_path/'cycle';cycle.create(root,c,base_dir=tmp_path, evaluation_harness=True)
    assert cycle.main(['progress','--cycle',str(root)])==0
    result=json.loads(capsys.readouterr().out)
    assert result['parent_task']['original_request']==PROMPT
    assert len(result['parent_completion_view']['obligation_census'])==4
    assert not result['parent_task_accepted'] and not result['parent_completion_view']['parent_task_accepted']


def test_indexed_host_full_inventory_above_graph_cap_and_binary_selection(tmp_path,monkeypatch):
    root,p=make(tmp_path,monkeypatch);pins=population(tmp_path,root)
    page=selections(root,pins[0]);core=proto.context(root,presentation='indexed',evidence_pages=page)
    assert core['inventory_commitment']['file_count']>128
    payload=core['selected_evidence_pages'][0]
    assert payload['content_encoding']=='base64' and not payload['original_source_reading_credit']
    graph=tmp_path/'graph';prepared=proto.prepare_host_request(root,'context',{},graph,tmp_path/'prepared',presentation='indexed',evidence_pages=page)
    assert len(prepared['inputs'])==3
    inputs=[{'id':'p'+str(i),'path':p['path'],'sha256':p['sha256']} for i,p in enumerate(prepared['inputs'])]
    spec={'schema_version':1,'graph_id':'indexed-status','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,'max_wall_seconds':10,'max_reworks':0},
        'nodes':[{'id':'status','kind':'tool','role':'designer','depends_on':[],'inputs':inputs,'packet':None,'action':'research-protocol','parameters':{'request_input':'p0'},'max_attempts':1}]}
    result=cycle.execute_graph(root,graph,spec,agent_host.AgentHost())
    assert result['complete'],result
    returned=cycle._graph_result(graph,'status')['value']['value']
    assert returned['inventory_commitment']==core['inventory_commitment']
    assert result['usage']['calls']==1


def test_fresh_indexed_meta_receipt_application_and_replay_refusal(tmp_path,monkeypatch):
    root,p=make(tmp_path,monkeypatch);pins=population(tmp_path,root)
    prepared,result,manifest=execute_meta(tmp_path,root,monkeypatch,pages=selections(root,pins[0]))
    assert result['complete'],result
    updated=proto.apply_meta_review(root,graph_root=prepared['graph_root'],node_id='meta',context_pin=prepared['context'],allow_control=True)
    event=updated['events'][-1]
    assert event['presentation_receipt']['deferred_source_content_read'] is False
    assert set(event['presentation_receipt']['presented_artifacts'])=={'public_case','page0000'}
    with pytest.raises(ValueError):proto.apply_meta_review(root,graph_root=prepared['graph_root'],node_id='meta',context_pin=prepared['context'],allow_control=True)


@pytest.mark.parametrize('identity',['inventory','page0000'])
def test_custody_only_citation_or_host_page_deferral_refuses(tmp_path,monkeypatch,identity):
    root,p=make(tmp_path,monkeypatch);pins=population(tmp_path,root)
    pages=selections(root,pins[0])
    if identity=='page0000':
        # Budget presents exact priority core but defers its separate page.
        state,inv,core,selected=material.prepared(root,evidence_pages=pages,role='verifier')
        budget=len(agent_host._json_bytes({'id':'public_case','content':material.raw_json(core).decode()}))
        cap=budget*4
    else:cap=2_000_000
    prepared,result,manifest=execute_meta(tmp_path,root,monkeypatch,pages=pages,max_request=cap,citation_id=identity)
    assert result['complete'],result
    if identity=='page0000':
        # A later genuine API read is not content presented to the old response.
        review_context.read_artifact(tmp_path/'meta/context','page0000',expected_manifest_sha256=manifest['sha256'])
    with pytest.raises(ValueError,match='presentation|deferred'):
        proto.apply_meta_review(root,graph_root=prepared['graph_root'],node_id='meta',context_pin=prepared['context'],allow_control=True)


@pytest.mark.parametrize('change',['source','extra','foreign','duplicate','oversized_core'])
def test_exact_current_sources_pages_and_core_bound(tmp_path,monkeypatch,change):
    root,p=make(tmp_path,monkeypatch);pins=population(tmp_path,root,2)
    page=selections(root,pins[0])
    if change=='source':
        Path(pins[0]['path']).write_bytes(b'changed')
    elif change=='foreign':page[0]['artifact_id']='foreign'
    elif change=='duplicate':page+=deepcopy(page)
    elif change=='extra':page[0]['unexpected']=True
    else:
        with pytest.raises(ValueError,match='budget'):proto.context(root,presentation='indexed',max_presented_bytes=1)
        return
    with pytest.raises(ValueError):proto.context(root,presentation='indexed',evidence_pages=page)


def test_full_typed_negative_results_and_objection_text_are_not_truncated(tmp_path,monkeypatch):
    root,p=make(tmp_path,monkeypatch)
    design(tmp_path,root,p,'base-screen',[5]);accepted_fixture(root,'base-screen')
    value=proto.context(root,presentation='indexed')
    row=value['actual_feedback'][0]
    assert row['returned_typed_result']['cells'][0]['operands'][0]['value']==5
    assert len(value['protocol']['cells'])==3 and len(value['protocol']['stages'])==6


def test_generic_reader_does_not_inherit_large_intake_cap(tmp_path,monkeypatch):
    pin=write(tmp_path/'large.json',{'not_a_canonical_intake':'x'*2_000_001})
    with pytest.raises(ValueError):cycle._read(pin,tmp_path)
    with pytest.raises(ValueError,match='canonical'):cycle._read_failed_intake(pin,tmp_path)


def test_progress_host_route_unissued_and_exhausted_usage(tmp_path,monkeypatch):
    root,p=make(tmp_path,monkeypatch)
    _,state=cycle._load(root)
    state['timing']['started_epoch']=1;state['timing']['deadline_epoch']=2
    cycle._commit(root,state,'explicit_expired_software_campaign')
    # Preparation and direct finite Host interpretation use the existing ledger;
    # an expired campaign cannot be granted a new dispatch for this test.
    graph=tmp_path/'graph';prepared=proto.prepare_host_request(root,'progress',{},graph,tmp_path/'prepared',presentation='indexed')
    request=state_io.read_json(prepared['request']['path'])
    _,state=cycle._load(root)
    state['resource_ledger'].append({'id':'graph:'+str(graph),'ceiling':{'calls':1,'output_tokens':0,'wall_seconds':1,'native_attempts':0},'basis':{}})
    cycle._commit(root,state,'explicit_undispatched_graph_reservation')
    result=proto.host_prepare(request,presented_pins=prepared['inputs'],base_dir=tmp_path)
    assert not result['final_delivery'] and result['timing']['deadline_epoch']==2
    assert len(result['all_experiments'])==2 and result['resource_ledger'][-1]['ceiling']['calls']==1


@pytest.mark.parametrize('mutation',['late_bytes','late_restored_bytes','core_omitted','state_change'])
def test_consumed_inventory_and_actual_presentation_ending_guards(tmp_path,monkeypatch,mutation):
    root,p=make(tmp_path,monkeypatch);pins=population(tmp_path,root,2)
    if mutation in {'late_bytes','late_restored_bytes','state_change'}:
        old=material.core
        def altered(*args):
            value=old(*args)
            if mutation=='state_change':
                _,state=cycle._load(root);cycle._commit(root,state,'explicit_concurrent_software_revision')
            else:
                path=Path(pins[0]['path']);raw=path.read_bytes();path.write_bytes(b'late change')
                if mutation=='late_restored_bytes':path.write_bytes(raw)
            return value
        monkeypatch.setattr(material,'core',altered)
        with pytest.raises(ValueError):proto.context(root,presentation='indexed')
    else:
        prepared,result,_=execute_meta(tmp_path,root,monkeypatch,max_request=100)
        assert not result['complete']
        with pytest.raises(ValueError):proto.apply_meta_review(root,graph_root=prepared['graph_root'],node_id='meta',context_pin=prepared['context'],allow_control=True)


def quantitative_case(base,monkeypatch,*,goal_binding=None):
    from test_scientific_report import fixture,attach_context
    request=fixture(base);context=attach_context(base,request)
    c=contract(base);c['context_request']=write(base/'original-context-request.json',context['request'])
    c['required_experiments']=['attempt1','still-unissued']
    if goal_binding is not None:
        c['goal_binding']=goal_binding
    root=base/'cycle';cycle.create(root,c,base_dir=base, evaluation_harness=True)
    _,state=cycle._load(root);state['context']=context
    receipt=write(base/'observed-record.json',{'stage':'science','attempt_id':'explicit-inert','status':'succeeded','exit_code':0,
        'started_utc':'2026-10-09T00:00:00Z','finished_utc':'2026-10-09T00:00:01Z'})
    review=write(base/'scoped-review.json',{'events':[],'explicit_inert_scope':True})
    study=write(base/'study.json',{'explicit_inert_study':True})
    result=cycle._pin(base/request['artifact_request']['tools']['probe']['path'])
    e={'id':'attempt1','question':'Retain both supplied scores.','parent':None,'change':'Pure supplied value source fixture.',
       'predictions':{},'premise_bindings':{},'study':study,'input_pins':[],'plan':None,'rundir':str(base/'inert'),
       'observation':{'receipt':receipt,'result':result,'outcome':'recorded','execution_status':'succeeded'},
       'adjudication':{'scope':'supplied_math','view':{'state':'accepted','claim_scope':'supplied_math'},'snapshot':review},
       'acceptance_scope':'supplied_math','cost':{'calls':0,'output_tokens':0,'wall_seconds':1,'native_attempts':1}}
    state['experiments'].append(e);cycle._commit(root,state,'explicit_inert_quantity_review_fixture')
    def accepted(state,e,accepted=False):
        for pin in [e['study'],e['observation']['receipt'],e['observation']['result'],e['adjudication']['snapshot']]:cycle._check_pin(pin,base)
        if accepted and e['adjudication']['view']['state']!='accepted':raise ValueError('unaccepted synthetic scope')
    monkeypatch.setattr(cycle,'_current_evidence',accepted)
    return root,request


@pytest.mark.parametrize('change',['none','unreviewed','reopened','foreign_equal_value','ending_result'])
def test_progress_only_current_scope_and_exact_value_provenance(tmp_path,monkeypatch,change):
    root,request=quantitative_case(tmp_path,monkeypatch)
    if change in {'unreviewed','reopened'}:
        _,state=cycle._load(root)
        if change=='unreviewed':state['experiments'][0]['adjudication']['view']['state']='review_pending'
        else:state['experiments'][0]['applicability_reopened']='located material objection'
        cycle._commit(root,state,'explicit_invalidated_scope_fixture')
    elif change=='foreign_equal_value':
        raw=(tmp_path/'probe.json').read_bytes();other=tmp_path/'other.json';other.write_bytes(raw)
        request['artifact_request']['tools']['probe']=cycle._pin(other)
    elif change=='ending_result':
        from ravel.workflow import scientific_report
        original=scientific_report.compose
        def altered(*a,**kw):
            value=original(*a,**kw);(tmp_path/'probe.json').write_text('{"scores":[]}');return value
        monkeypatch.setattr(scientific_report,'compose',altered)
    if change=='none':
        result=cycle.progress_synthesis(root,base_dir=tmp_path,report_request=request)
        assert len(result['accepted_scoped_facts']['facts'])==2 and not result['final_delivery']
        assert result['all_experiments'][-1]['id']=='still-unissued'
        with pytest.raises(ValueError):cycle.synthesize(root,request,base_dir=tmp_path)
    else:
        with pytest.raises(ValueError):cycle.progress_synthesis(root,base_dir=tmp_path,report_request=request)


def test_progress_nonselected_current_review_drift_refuses(tmp_path,monkeypatch):
    root,request=quantitative_case(tmp_path,monkeypatch)
    from ravel.workflow import research_outcome_metrics
    original=research_outcome_metrics.project;done=[]
    def changed(*a,**kw):
        value=original(*a,**kw)
        if not done:
            (tmp_path/'scoped-review.json').write_text('{"events":[],"changed_review":true}')
            done.append(True)
        return value
    monkeypatch.setattr(research_outcome_metrics,'project',changed)
    with pytest.raises(ValueError,match='census changed|committed source pin'):cycle.progress_synthesis(root)


def test_progress_parent_completion_cannot_replace_original_contract(tmp_path,monkeypatch):
    from test_task_completion import goal
    from ravel.workflow import rdj_custody
    _,parent=goal(tmp_path/'parent');_,foreign=goal(tmp_path/'foreign')
    rdj_custody.record_input_snapshot(Path(parent['path']).parent.parent,'run_init')
    binding={'contract':parent,'assignment_id':'summary-child'}
    root,request=quantitative_case(tmp_path,monkeypatch,goal_binding=binding)
    request['task_completion']=write(tmp_path/'foreign-completion.json',{'schema_version':1,'contract':foreign,
        'outcomes':[],'parent_review':None,'report':None})
    with pytest.raises(ValueError,match='original parent'):cycle.progress_synthesis(root,base_dir=tmp_path,report_request=request)


def test_context_cli_indexed_page_options_and_closed_keys(tmp_path,monkeypatch,capsys):
    root,p=make(tmp_path,monkeypatch);pins=population(tmp_path,root,2)
    options=tmp_path/'options.json';options.write_text(json.dumps({'presentation':'indexed','evidence_pages':selections(root,pins[0]),'role':'critic'}))
    out=tmp_path/'context.json'
    assert proto.main(['context','--cycle',str(root),'--request',str(options),'--out',str(out)])==0
    value=state_io.read_json(out);assert len(value['selected_evidence_pages'])==1
    options.write_text('{"presentation":"indexed","unknown":true}')
    with pytest.raises(ValueError):proto.main(['context','--cycle',str(root),'--request',str(options),'--out',str(tmp_path/'foreign.json')])


@pytest.mark.parametrize('target',['public_case','manifest'])
def test_meta_preparation_generated_commitment_drift_refuses(tmp_path,monkeypatch,target):
    root,p=make(tmp_path,monkeypatch);out=tmp_path/'meta';original=cycle._check_pin
    def modified(pin,base):
        expected=out/'context'/('manifest.json' if target=='manifest' else 'artifacts/public_case.json')
        if Path(pin['path'])==expected and expected.exists():expected.write_bytes(b'{"late_changed":true}')
        return original(pin,base)
    monkeypatch.setattr(cycle,'_check_pin',modified)
    with pytest.raises(ValueError):proto.prepare_meta_review(root,out,role='critic',model='inert',reasoning_effort='high',
        max_output_tokens=128,max_wall_seconds=10,presentation='indexed')
