"""Real typed compiler feedback, full-population replay and fresh admissions."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ravel import analysis_sources as sources
from ravel.physics import analysis_ir
from ravel.workflow.state_io import atomic_json


from ravel.physics import routine_candidate as candidate


def pin(path):
    return {"path": str(path), "sha256": sources.digest(path)}


def setup(tmp_path, extra_passes=0):
    root = tmp_path / "original"; root.mkdir()
    source = root / "unknown.cc"
    source.write_text("// supplied-object interface; no detector calibration\n"
                      "// count jets with pT at least 30 GeV\n"
                      "// accept at least one selected jet\n")
    capsule = {"schema_version":1, "kind":"analysis-source-capsule", "framework":"cpp",
        "routine":"PreviouslyUnknown", "source":{"repository":"supplied", "revision":None,
        "description":"Engineering control; does not establish unfamiliar CMS/ATLAS task efficacy"},
        "root":str(root), "files":[{"path":"unknown.cc", "sha256":sources.digest(source), "role":"compile"}],
        "layout":{"include_dirs":[],"asset_dirs":[]}, "dependencies":[],
        "dependency_review":{"complete":True,"description":"Bounded declared test source only"}, "submodules":[]}
    cp = tmp_path / "capsule.json"; atomic_json(cp, capsule)
    claims = [{"id":name, "path":"unknown.cc", "line_start":line,"line_end":line,
               "excerpt_sha256":__import__('hashlib').sha256(source.read_bytes().splitlines(keepends=True)[line-1]).hexdigest(),
               "kind":kind} for name,line,kind in (("objects",1,"objects"),("threshold",2,"expression"),("accept",3,"selection"))]
    contract = {"schema_version":1,"level":"reconstructed","source":"explicit supplied engineering controls",
        "energy_unit":"GeV","flags":{"electron":{},"muon":{},"jet":{}},"response_evidence":[],"weight_names":["nominal"]}
    events = [{"event_id":name,"group_id":"pair" if name in ("pass","negative") else name,
        "weights":{"nominal":weight},"objects":{"electron":[],"muon":[],"jet":
        [{"pt":pt,"eta":0,"phi":0,"mass":0,"charge":0,"idbits":0}]},"met":{"pt":0,"phi":0}}
        for name,pt,weight in (("pass",40,1.5),("negative",40,-.5),("reject",20,1.),("zero",29,0.))]
    for index in range(extra_passes):
        row=deepcopy(events[0]);row['event_id']=row['group_id']='extra-'+str(index);events.append(row)
    program = {"schema_version":1,"name":"source_constructed","nodes":[
        {"id":"jets","op":"input","collection":"jet"},
        {"id":"threshold","op":"const","value":30,"unit":"GeV"},
        {"id":"eta","op":"const","value":5,"unit":"1"},
        {"id":"selected","op":"filter","args":["jets","threshold","eta"]},
        {"id":"n","op":"count","args":["selected"]},
        {"id":"one","op":"const","value":1,"unit":"1"},
        {"id":"accept","op":"compare","args":["n","one"],"comparison":"ge"}],
        "regions":[{"name":"SR","cuts":["accept"]}],
        "limits":{"max_events":10,"max_objects_per_event":16,"max_pairs_per_event":64}}
    upstream = tmp_path / "upstream"
    baseline=analysis_ir.evaluate_program(program,contract,events)
    analysis_ir.write_bundle(baseline, upstream)
    contract_path, events_path = tmp_path / "contract.json", tmp_path / "events.json"
    atomic_json(contract_path,contract); atomic_json(events_path,events)
    oracle=tmp_path/'source-oracle.json';atomic_json(oracle,{'schema_version':1,'kind':'source-case-oracle',
        'source_capsule_sha256':sources.digest(cp),'events_sha256':sources.digest(events_path),
        'records':[{'event_id':r['event_id'],'regions':r['regions'],'observables':{'n':r['nodes']['n']['value']}} for r in baseline['decisions']],
        'author':'test fixture author; no claimed scientific independence','scope':'Engineering source binding controls only'})
    domain=tmp_path/'domain.json';atomic_json(domain,{'schema_version':1,'kind':'supplied-reconstructed-domain',
        'jet_mass':'massless','interpretation':'Engineering control with exactly massless supplied jets'})
    def recipe(p):
        return {"schema_version":1,"name":p["name"],"limits":p["limits"],
                "steps":[{"node":n,"claims":["objects" if n["op"]=="input" else "threshold" if n["id"] in ("threshold","eta","selected") else "accept"]} for n in p["nodes"]],
                "regions":[{"region":r,"claims":["accept"]} for r in p["regions"]]}
    broken = deepcopy(program); broken["nodes"][1]["unit"]="rad"
    mismatch = deepcopy(program); mismatch["nodes"][1]["value"]=50
    config = {"schema_version":1,"kind":"routine-construction","source_capsule":pin(cp),
        "source_scope":{"kind":"supplied_object_port","unserved_obligations":["Native arbitrary-C++ execution and experimental calibration"]},"model_construction":None,"population_review":None,"claims":claims,
        "contract":pin(contract_path),"events":pin(events_path),"event_domain":pin(domain),
        "reference":{"kind":"detached-analysis-witness","bundle":str(upstream),
            "manifest_sha256":sources.digest(upstream/'manifest.json'),"source_capsule_sha256":sources.digest(cp),
            "claims":["objects","threshold","accept"],"interpretation":"Explicit control interpretation; no native C++ equivalence proof"},
        "repair_board":[{"from":"bad-unit","to":"bad-threshold","claims":["threshold"],"trigger":"typed_compiler"},
                        {"from":"bad-threshold","to":"corrected","claims":["threshold"],"trigger":"event_selection"}],
        "candidates":[{"id":name,"parent":parent,"recipe":recipe(p),"candidate_source_capsule":pin(cp),"build":None,
            "reason":"Finite predeclared engineering fixture"} for name,parent,p in
            (("bad-unit",None,broken),("bad-threshold","bad-unit",mismatch),("corrected","bad-threshold",program))]}
    config['reference']['source_oracle']=pin(oracle)
    cfg=tmp_path/'construction.json'; atomic_json(cfg,config)
    task={"backend":"routine-candidate","input":str(cfg),"candidate":"bad-unit","parent_feedback":None}
    return task, config


def successor(task, cid, previous):
    return {**task,"candidate":cid,"parent_feedback":pin(previous/'construction-feedback.json')}


def test_actual_typed_failure_selection_feedback_repair_and_detached_verification(tmp_path):
    task,_=setup(tmp_path)
    one,two,three=[tmp_path/n for n in ('one','two','three')]
    a=candidate.run(task,tmp_path,one)
    assert a['candidate_disposition']=='typed_compiler_refused'
    assert a['permitted_successors']==['bad-threshold']
    assert not (one/'candidate-witness').exists()
    second=successor(task,'bad-threshold',one)
    b=candidate.run(second,tmp_path,two)
    assert b['candidate_disposition']=='event_mismatch'
    assert b['feedback']['upstream_comparison']['events']==4
    assert b['feedback']['upstream_comparison']['change_counts']['selection_changed']==2
    assert b['feedback']['independent_verification']['events']==4
    assert b['permitted_successors']==['corrected']
    third=successor(task,'corrected',two)
    c=candidate.run(third,tmp_path,three)
    assert c['candidate_disposition']=='verified_on_supplied_events'
    assert c['feedback']['upstream_comparison']['matched_events']==4
    assert len({row['source_admission_id'] for row in (a,b,c)})==3
    assert all(row['prior_reviews_carried']==[] and row['physics_validated'] is False for row in (a,b,c))
    assert candidate.verify_delivery(third,tmp_path,three)['status']=='passed'
    trace=json.loads((three/'candidate-witness/trace.json').read_text())
    assert {r['event_id'] for r in trace if not r['regions']}=={'reject','zero'}
    assert json.loads((three/'standalone-verifier.json').read_text())['returncode']==0


@pytest.mark.parametrize('defect',['claim_excerpt','unresolved_dependency','missing_reject','source_bytes','reference_anchor','parent_cycle','unbound_step'])
def test_source_and_complete_population_refusal_before_effect(tmp_path,monkeypatch,defect):
    task,config=setup(tmp_path)
    if defect=='claim_excerpt': config['claims'][0]['excerpt_sha256']='0'*64
    elif defect=='unresolved_dependency':
        cp=Path(config['source_capsule']['path']); cap=json.loads(cp.read_text());cap['dependency_review']['complete']=False
        atomic_json(cp,cap);config['source_capsule']=pin(cp)
        config['source_scope']={'kind':'complete_routine','unserved_obligations':[]}
    elif defect=='missing_reject':
        ep=Path(config['events']['path']); rows=json.loads(ep.read_text());rows.pop();atomic_json(ep,rows);config['events']=pin(ep)
    elif defect=='source_bytes': (tmp_path/'original/unknown.cc').write_text('changed source\n')
    elif defect=='reference_anchor': config['reference']['manifest_sha256']='0'*64
    elif defect=='parent_cycle':
        config['candidates'][0]['parent']='corrected';config['repair_board'].append({'from':'corrected','to':'bad-unit','claims':['accept'],'trigger':'event_selection'})
    else: config['candidates'][0]['recipe']['steps'][0]['claims']=['invented']
    atomic_json(Path(task['input']),config)
    monkeypatch.setattr(candidate.subprocess,'run',lambda *a,**k:pytest.fail('effect before source admission'))
    with pytest.raises(ValueError): candidate.inputs(task,tmp_path)
    assert not (tmp_path/'output').exists()


@pytest.mark.parametrize('defect',['no_feedback','wrong_parent','wrong_trigger','invented_successor','feedback_bytes'])
def test_finite_repair_cannot_skip_or_substitute_parent_feedback(tmp_path,defect):
    task,_=setup(tmp_path);one=tmp_path/'one';candidate.run(task,tmp_path,one)
    revised=successor(task,'bad-threshold',one)
    if defect=='no_feedback':revised['parent_feedback']=None
    elif defect=='invented_successor':revised['candidate']='invented'
    else:
        fp=one/'construction-feedback.json';feedback=json.loads(fp.read_text())
        if defect=='wrong_parent':feedback['candidate_id']='corrected'
        elif defect=='wrong_trigger':feedback['failure_trigger']='event_selection'
        else:feedback['source_admission_id']='0'*64
        atomic_json(fp,feedback)
        if defect!='feedback_bytes':revised['parent_feedback']=pin(fp)
    with pytest.raises(ValueError):candidate.inputs(revised,tmp_path)


def test_code_change_invalidates_retained_admission_and_votes_cannot_carry(tmp_path):
    task,config=setup(tmp_path);one=tmp_path/'one';candidate.run(task,tmp_path,one)
    feedback=json.loads((one/'construction-feedback.json').read_text());feedback['prior_reviews_carried']=['old-verifier-vote']
    atomic_json(one/'construction-feedback.json',feedback)
    with pytest.raises(ValueError,match='review boundary'):candidate.verify_delivery(task,tmp_path,one)
    feedback['prior_reviews_carried']=[];atomic_json(one/'construction-feedback.json',feedback)
    config['candidates'][0]['recipe']['steps'][1]['node']['value']=31
    atomic_json(Path(task['input']),config)
    with pytest.raises(ValueError,match='fresh admission'):candidate.verify_delivery(task,tmp_path,one)


def test_coherently_rehashed_candidate_missing_rejection_still_fails(tmp_path):
    task,_=setup(tmp_path);one,two,three=[tmp_path/n for n in ('one','two','three')]
    candidate.run(task,tmp_path,one);second=successor(task,'bad-threshold',one);candidate.run(second,tmp_path,two)
    third=successor(task,'corrected',two);candidate.run(third,tmp_path,three)
    bundle=three/'candidate-witness';trace=json.loads((bundle/'trace.json').read_text());trace.pop();atomic_json(bundle/'trace.json',trace)
    manifest=json.loads((bundle/'manifest.json').read_text());manifest['files']['trace.json']=sources.digest(bundle/'trace.json');atomic_json(bundle/'manifest.json',manifest)
    detached=json.loads((three/'standalone-verifier.json').read_text());detached['report']['manifest_sha256']=sources.digest(bundle/'manifest.json');atomic_json(three/'standalone-verifier.json',detached)
    with pytest.raises(ValueError,match='independent replay'):candidate.verify_delivery(third,tmp_path,three)


def test_massive_jet_cannot_use_massless_rapidity_interpretation(tmp_path):
    task,config=setup(tmp_path);ep=Path(config['events']['path']);rows=json.loads(ep.read_text())
    rows[0]['objects']['jet'][0]['mass']=.1;atomic_json(ep,rows);config['events']=pin(ep);atomic_json(Path(task['input']),config)
    with pytest.raises(ValueError,match='massless-jet'):candidate.inputs(task,tmp_path)


def test_coherently_rehashed_parent_cannot_forge_compiler_error_or_carry_votes(tmp_path):
    task,_=setup(tmp_path);one=tmp_path/'one';candidate.run(task,tmp_path,one)
    fp=one/'construction-feedback.json';original=json.loads(fp.read_text())
    for mutated in ({**original,'prior_reviews_carried':['oldvote']},
                    {**original,'feedback':{'typed_compiler':{'status':'refused','error':'invented'}}}):
        atomic_json(fp,mutated);revised=successor(task,'bad-threshold',one)
        with pytest.raises(ValueError):candidate.inputs(revised,tmp_path)


def test_self_consistent_baseline_cannot_override_independent_source_oracle(tmp_path):
    task,config=setup(tmp_path);op=Path(config['reference']['source_oracle']['path']);oracle=json.loads(op.read_text())
    oracle['records'][0]['regions']=[];atomic_json(op,oracle);config['reference']['source_oracle']=pin(op);atomic_json(Path(task['input']),config)
    with pytest.raises(ValueError,match='source oracle selection differs'):candidate.inputs(task,tmp_path)


def test_static_branch_exposes_complete_outer_budget_without_effect(tmp_path,monkeypatch):
    task,_=setup(tmp_path);monkeypatch.setattr(candidate.subprocess,'run',lambda *a,**k:pytest.fail('budget inspection launched process'))
    assert candidate.execution_seconds(task,tmp_path)==60


def _external_control_reply(task, root, prepared):
    """A supplied transport control, explicitly not actual frontier inference."""
    config=json.loads(Path(task['input']).read_text());recipe=config['candidates'][0]['recipe']
    node_keys=('id','op','args','collection','value','unit','field','comparison','count','index','flags','pt_from')
    value={'schema_version':1,'name':recipe['name'],'steps':[
        {'node':{key:step['node'].get(key) for key in node_keys},'claims':step['claims']} for step in recipe['steps']],
        'regions':recipe['regions'],'unserved_obligations':[],
        'public_rationale':'Canned engineering transport control only; no model construction efficacy claim.'}
    response={'schema_version':1,'request_id':prepared['request_id'],'request_sha256':prepared['request_sha256'],
        'invocation_id':'supplied-fixture-control','actor_id':'test-control','observed_model':'fixture-control',
        'fresh_context':True,'parent_transcript_supplied':False,'value':value}
    rp=root.parent/'external-control-response.json';atomic_json(rp,response)
    from ravel.workflow import agent_graph
    agent_graph.deliver_external(root,'construct',rp)
    return rp


def test_agenthost_external_source_only_contract_receipts_and_fresh_draft(tmp_path):
    task,_=setup(tmp_path);root=tmp_path/'model-graph'
    prepared=candidate.prepare_agent_request(task,tmp_path,root,model='fixture-control',reasoning_effort='low',
        max_output_tokens=1000,requested_task='Construct source behavior from original text.')
    request=json.loads(Path(prepared['request_file']).read_text());panel=json.loads(request['context']['input_artifacts'][0]['content'])
    assert prepared['model_executed'] is False
    assert panel['actual_feedback'] is None and panel['counterexample_events']==[]
    assert 'evaluation event population' in panel['withheld']
    assert 'candidates' not in panel and 'reference' not in panel and 'events' not in panel
    assert panel['operator_contract']['filter'].startswith('pT >= supplied threshold; abs(eta) <')
    assert len(panel['source_text'])==1 and '// count jets' in panel['source_text'][0]['text']
    _external_control_reply(task,root,prepared)
    generated=candidate.materialize_agent_candidate(root,source_task=task,base_dir=tmp_path,
        output_config=tmp_path/'new-model-draft.json',candidate_id='actual-draft-control')
    parsed=json.loads((tmp_path/'new-model-draft.json').read_text())
    assert parsed['model_construction'] is not None
    assert candidate.inputs(generated['task'],tmp_path)
    assert generated['model_binding']['prior_reviews_carried']==[]
    assert generated['model_binding']['fresh_scientific_plan_required'] is True
    assert generated['model_binding']['model_transport']['inference_token_ceiling_enforced'] is False
    assert not (tmp_path/'candidate-witness').exists()
    parsed['candidates'][0]['recipe']['steps'][1]['node']['value']=99
    atomic_json(tmp_path/'new-model-draft.json',parsed)
    with pytest.raises(ValueError,match='actual model construction reply'):candidate.inputs(generated['task'],tmp_path)


def test_external_repair_request_requires_actual_feedback_and_preserves_call_budget(tmp_path):
    task,_=setup(tmp_path);out=tmp_path/'actual-typed-feedback';candidate.run(task,tmp_path,out);root=tmp_path/'model-graph'
    prepared=candidate.prepare_agent_request(task,tmp_path,root,model='fixture-control',reasoning_effort='low',
        max_output_tokens=1000,requested_task='Construct source behavior.')
    _external_control_reply(task,root,prepared)
    second=candidate.prepare_agent_request(task,tmp_path,root,model='fixture-control',reasoning_effort='low',
        max_output_tokens=1000,requested_task='Repair from actual feedback.',repair_ordinal=1,feedback=pin(out/'construction-feedback.json'))
    assert second['usage']['calls']==2
    request=json.loads(Path(second['request_file']).read_text());panel=json.loads(request['context']['input_artifacts'][0]['content'])
    assert panel['actual_feedback']['candidate_disposition']=='typed_compiler_refused'
    assert panel['withheld'] and 'source oracle and expected decisions' in panel['withheld']
    with pytest.raises(ValueError,match='at most two repairs'):
        candidate.prepare_agent_request(task,tmp_path,root,model='fixture-control',reasoning_effort='low',
            max_output_tokens=1000,requested_task='Unbounded retry.',repair_ordinal=3)


def test_native_branch_budget_binds_actual_sealed_compiler_without_launch(tmp_path,monkeypatch):
    import shutil
    from ravel.physics import routine_build
    compiler=shutil.which('clang++') or shutil.which('g++')
    if not compiler:pytest.skip('No real compiler identity to inspect')
    task,config=setup(tmp_path)
    build_path=tmp_path/'native-build.json'
    build_config={'schema_version':1,'source_capsule':config['source_capsule']['path'],
        'recipe':{'name':'cpp-executable','compile_units':['unknown.cc'],'output':'probe','flags':['-std=c++17','-O0']},
        'runtime':{'tools':{'compiler':pin(Path(compiler))},'artifacts':[],'environment':{}},
        'probe':{'executable':'$BUILD_OUTPUT','arguments':[],'expected_exit_code':0,'stdout_contains':['probe']}}
    atomic_json(build_path,build_config)
    sealed=routine_build.seal_configuration({'backend':'routine-build','input':str(build_path)},tmp_path)
    atomic_json(build_path,sealed)
    config['candidates'][0]['build']=pin(build_path);atomic_json(Path(task['input']),config)
    monkeypatch.setattr(candidate.subprocess,'run',lambda *a,**k:pytest.fail('budget inspection executed native process'))
    assert candidate.execution_seconds(task,tmp_path)==420
    assert not (tmp_path/'.unexecuted-budget-plan').exists()


def test_repair_discloses_at_most_four_expected_witnesses_and_keeps_full_receipt(tmp_path):
    task,config=setup(tmp_path,extra_passes=4)
    task={**task,'candidate':'bad-threshold'}
    config['candidates'][1]['parent']=None;config['repair_board']=[]
    config['candidates']=[config['candidates'][1]]
    atomic_json(Path(task['input']),config)
    out=tmp_path/'actual-selection-feedback';candidate.run(task,tmp_path,out)
    full=json.loads((out/'construction-feedback.json').read_text())
    assert len(full['feedback']['upstream_comparison']['witnesses'])==6
    root=tmp_path/'model-graph'
    prepared=candidate.prepare_agent_request(task,tmp_path,root,model='fixture-control',reasoning_effort='low',
        max_output_tokens=1000,requested_task='Construct source behavior.')
    _external_control_reply(task,root,prepared)
    prepared=candidate.prepare_agent_request(task,tmp_path,root,model='fixture-control',reasoning_effort='low',
        max_output_tokens=1000,requested_task='Repair only retained objections.',repair_ordinal=1,feedback=pin(out/'construction-feedback.json'))
    request=json.loads(Path(prepared['request_file']).read_text())
    panel=json.loads(request['context']['input_artifacts'][0]['content'])
    exposed=panel['actual_feedback']['feedback']['upstream_comparison']
    disclosed=len(exposed['witnesses'])
    assert 0 < disclosed <= 4
    assert exposed['witnesses_disclosed']==disclosed
    assert exposed['witnesses_withheld']==6-disclosed
    assert len(panel['counterexample_events'])==disclosed
    original=full['feedback']['upstream_comparison']
    events=json.loads(Path(config['events']['path']).read_text())
    by_event={row['event_id']:row for row in events}
    by_witness={row['event_id']:row for row in original['witnesses']}
    assert exposed['events']==original['events']==len(events)
    assert exposed['matched_events']==original['matched_events']==len(events)-6
    assert exposed['change_counts']==original['change_counts']
    assert sum(exposed['change_counts'].values())==6
    assert {row['event_id'] for row in exposed['witnesses']}=={row['event_id'] for row in panel['counterexample_events']}
    for row in exposed['witnesses']:
        assert row==by_witness[row['event_id']]
        assert row['input_event_sha256']==candidate._digest(by_event[row['event_id']])
    for row in panel['counterexample_events']:
        assert row==by_event[row['event_id']]
    prefix=original['witnesses'][:4]
    prior_context={'witnesses':prefix,'events':[by_event[row['event_id']] for row in prefix]}
    selected_context={'witnesses':exposed['witnesses'],'events':panel['counterexample_events']}
    size=lambda value:len(json.dumps(value,sort_keys=True,allow_nan=False).encode())
    assert size(selected_context)<=size(prior_context)
    assert panel['actual_feedback']['retained_full_feedback']==pin(out/'construction-feedback.json')
    assert json.loads((out/'construction-feedback.json').read_text())==full


def population_control():
    """Independent source population control, not a scientific routine oracle."""
    jets=[{'id':'j0','pt':40,'eta':0,'phi':0,'mass':0},
          {'id':'j1','pt':40,'eta':1,'phi':2,'mass':0}]
    seed={'schema_version':1,'kind':'independent-source-construction-witness-seed','complete_population':True,
        'events':[{'id':'tie','weight':-.5,'objects':{'jets':jets},
                   'expected':{'port_admission':'accepted','ordered_accepted_jets':['j0','j1'],'n_good':2}},
                  {'id':'massive','weight':0,'objects':{'jets':[{**jets[0],'mass':1}]},
                   'expected':{'port_admission':'refused_massive_jet'}}]}
    events=[{'event_id':'tie','group_id':'tie','weights':{'nominal':-.5},
        'objects':{'electron':[],'muon':[],'jet':[{key:j[key] for key in ('pt','eta','phi','mass')}|
            {'charge':0,'idbits':0} for j in jets]},'met':{'pt':0,'phi':0}}]
    ledger={'source_seed':{'path':'source-seed.json','sha256':'0'*64},'raw_case_population':2,
        'admitted_port_population':1,'explicit_domain_refusal_population':1,
        'refused_cases':[seed['events'][1]],'scope_exceptions':[{'event_id':'tie',
            'unserved_output':'exact_equal_pT_tie_order','reason':'Upstream tie order is unspecified; preserve count assertion.'}],
        'all_cases_preserved':True,'physics_validated':False}
    oracle={'records':[{'event_id':'tie','observables':{'n_good':2}}]}
    return ledger,seed,events,oracle,{'jet_mass':'massless'}


@pytest.mark.parametrize('defect',[None,'removed_refusal','wrong_refusal','raw_weight','raw_object','silent_tie_omission','unsupported_exception','scalar','false_total','schema_alias'])
def test_full_original_population_conversion_refusal_and_tie_exception(defect):
    ledger,seed,events,oracle,domain=population_control()
    if defect=='removed_refusal':ledger['refused_cases']=[]
    elif defect=='wrong_refusal':domain['jet_mass']='supplied_nonnegative'
    elif defect=='raw_weight':events[0]['weights']['nominal']=.5
    elif defect=='raw_object':events[0]['objects']['jet'][0]['phi']=0.1
    elif defect=='silent_tie_omission':ledger['scope_exceptions']=[]
    elif defect=='unsupported_exception':ledger['scope_exceptions'][0]['unserved_output']='n_good'
    elif defect=='scalar':oracle['records'][0]['observables']['n_good']=1
    elif defect=='false_total':ledger['raw_case_population']=True
    elif defect=='schema_alias':seed['schema_version']=True
    if defect:
        with pytest.raises(ValueError):candidate._verify_population(ledger,seed,events,oracle,domain)
    else:
        result=candidate._verify_population(ledger,seed,events,oracle,domain)
        assert result['original_event_ids']==['tie','massive']
        assert result['refused_event_ids']==['massive'] and result['raw_case_population']==2
        assert result['source_assertions_authenticated'] is result['physics_validated'] is False


def test_coherently_mutated_population_scope_cannot_replace_retained_delivery(tmp_path):
    task,_=setup(tmp_path);out=tmp_path/'actual-delivery';candidate.run(task,tmp_path,out)
    path=out/'construction-feedback.json';original=json.loads(path.read_text())
    for changed in ({**original,'population_review':{'raw_case_population':1}},
                    {**original,'source_scope':{'kind':'complete_routine','unserved_obligations':[]}},
                    {**original,'execution_authorized':True}):
        atomic_json(path,changed)
        with pytest.raises(ValueError,match='population/scope or authority'):candidate.verify_delivery(task,tmp_path,out)
