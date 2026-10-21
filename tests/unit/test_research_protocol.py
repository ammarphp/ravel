"""Connected pure engineering controls, with no worker/provider/native dispatch.

Graph/Host/cycle/source admission/comparator arithmetic and ordinary plan are
real. Returned scientific-stage receipts and acceptance are explicit synthetic
seams, never counted as scientific review or experimental effectiveness.
"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import pytest
from ravel.workflow import research_cycle as cycle, research_protocol as proto
from ravel.workflow import agent_host, agent_graph, science, execution, state_io
from ravel.physics import research_comparison as compare
from test_research_cycle import contract, write


@pytest.fixture(autouse=True)
def no_process(monkeypatch):
    monkeypatch.setattr(execution,'runtime_context',lambda:{'explicit_inert_source_control':True,
        'environment_sha256':execution.digest(execution.runtime_environment())})
    def refuse(*a,**kw):raise AssertionError('No scientific/model/provider/metadata process admitted')
    monkeypatch.setattr(subprocess,'Popen',refuse)


def make(base,monkeypatch,*,goal_binding=None,confirmation=False):
    root=base/'cycle';c=contract(base);c['budget']={'calls':60,'output_tokens':8192,'wall_seconds':3600,'native_attempts':32}
    c['max_experiments']=32;c['required_experiments']=['base-full','new-full']
    if goal_binding is not None:c['goal_binding']=deepcopy(goal_binding)
    cycle.create(root,c,base_dir=base, evaluation_harness=True)
    ideas=[{'id':'loss','statement':'Explicit fixed-rule complete-cell source comparison can discriminate this engineering case.',
        'stream':'citation_led','premise_ids':[],'source_basis':[],'parents':[]}]
    cycle.propose(root,ideas,origin={'kind':'supplied_source','pin':write(base/'ideas.json',ideas),'description':'Source-supplied synthetic method, no mandatory speculation.'})
    components={k:write(base/(k+'.txt'),v) for k,v in [('base','original grouping'),('new','changed grouping'),('weights','retained weighting')]}
    population=write(base/'population.json',{'ids':['a','b'],'scope':'Whole supplied engineering population'})
    normalization=write(base/'normalization.json',{'unit':'1','scale':1,'scope':'Literal declared normalization'})
    criteria=write(base/'criteria.json',{'statement':'Compare both complete full cells with fixed rule and no missing-cell substitution','unit':'1','scope':'supplied_method_diagnostic'})
    fixed=write(base/'rule.json',{'schema_version':1,'metric':'loss','unit':'1','direction':'minimize','min_gain':0.1,'tolerance':0.001,'uncertainty':'deterministic','reduction':'all_cells'})
    candidates=[{'id':identity,'parent':parent,'generation':generation,'components':mapping,'invariant_inputs':[],'premise_ids':['pairing'],'requalifies':None,'reason':'Synthetic source manifest, not a measured mechanism.'} for identity,parent,generation,mapping in [
        ('original',None,0,{'grouping':components['base'],'weighting':components['weights']}),
        ('changed','original',1,{'grouping':components['new'],'weighting':components['weights']}),
        ('ablated','changed',2,{'grouping':components['new']})]]
    cells=[{'id':identity,'population':population,'normalization':normalization,'regime':'supplied_math','fidelity':fidelity,
        'exposure':exposure,'metric':'loss','unit':'1','premise_ids':[],'replaces':None} for identity,fidelity,exposure in [
            ('small','subset','adaptive_screen'),('full-a','full','adaptive_full'),('full-b','full','adaptive_full')]]
    def stage(identity,purpose,candidate,ids,required=(),comparators=(),ablation=None):
        return {'id':identity,'purpose':purpose,'candidate':candidate,'cells':[{'cell_id':i,'experiment_id':identity,
            'value_pointer':'/cells/'+str(n)+'/operands/0/value','interval_pointer':None,'quality_pointer':'/status'} for n,i in enumerate(ids)],
            'requires':[{'comparison_id':i,'allowed_decisions':allowed} for i,allowed in comparators],'requires_stages':list(required),
            'acceptance_scope':'supplied_method_diagnostic','premise_ids':[],'ablation':ablation,'replaces':None}
    stages=[stage('base-screen','baseline','original',['small']),stage('base-full','baseline','original',['full-a','full-b']),
        stage('new-screen','screen','changed',['small'],required=['base-full']),
        stage('new-full','full','changed',['full-a','full-b'],comparators=[('screen-contrast',['better'])]),
        stage('ablation','ablation','ablated',['full-a','full-b'],comparators=[('full-contrast',['better','equivalent','worse'])],
            ablation={'component':'weighting','kind':'remove_one','parent_candidate':'changed'})]
    # Full incumbent is itself a separately declared full stage of the same run;
    # one returned result can populate multiple cells/stages, without an attempt.
    stages.append({**deepcopy(stages[1]),'id':'incumbent-full','purpose':'full','cells':deepcopy(stages[1]['cells'])})
    comparators=[{'id':i,'left_stage':left,'right_stage':right,'experiment_id':'compare-'+i,'rule':fixed,'acceptance_scope':'supplied_comparison_diagnostic','replaces':None}
        for i,left,right in [('screen-contrast','new-screen','base-screen'),('full-contrast','new-full','incumbent-full'),('ablation-contrast','ablation','new-full')]]
    claims=[{'id':'complete-method','statement':'The complete declared method comparison is delivered within supplied arithmetic scope.',
        'acceptance_criteria':criteria,'stage_ids':['incumbent-full','new-full','ablation'],'comparison_ids':['full-contrast','ablation-contrast'],
        'premise_ids':[],'report_slot':'method-comparison','replaces':None}]
    protocol={'schema_version':1,'id':'complete-method-protocol','scope':'Explicit synthetic arithmetic methodology controls; no efficacy',
        'candidates':candidates,'cells':cells,'stages':stages,'comparisons':comparators,'claims':claims,
        'required_stage_ids':['incumbent-full','new-full','ablation'],'required_comparison_ids':['full-contrast','ablation-contrast'],
        'round_limits':{'generations':4,'ablations':4,'meta_reviews':4},'not_applicable':[],
        'meta_actors':{'critic':'fixture-meta-critic','verifier':'fixture-meta-verifier'}}
    # This test-double verifies the ordinary commitments that it presents. It
    # deliberately does NOT fabricate a physics journal or reuse authority.
    def supplied_scope(state,e,accepted=False):
        for pin in [e['study'],*e['input_pins']]:cycle._check_pin(pin,state['base_dir'])
        if e['observation'] is None:raise ValueError('explicit synthetic returned outcome required')
        for pin in [e['observation']['receipt'],e['observation']['result']]:cycle._check_pin(pin,state['base_dir'])
        if accepted:
            if e['adjudication'] is None or e['adjudication']['view']['state']!='accepted':raise ValueError('synthetic acceptance not presented')
            cycle._check_pin(e['adjudication']['snapshot'],state['base_dir'])
    monkeypatch.setattr(cycle,'_current_evidence',supplied_scope)
    # No feedback prose is invented by the pure fixture. Its fields explicitly
    # distinguish this from independently produced actual critic reviews.
    from ravel.workflow import research_followup
    monkeypatch.setattr(research_followup,'_feedback_content',lambda root,i:(None,{'explicit_synthetic_scoped_receipt':i},None,[],None))
    if confirmation:
        for index, cell in enumerate(protocol['cells']):
            cell.update(seeds=[10+index], generation='select-data')
        confirm_cell = {**deepcopy(protocol['cells'][1]), 'id': 'confirm-cell',
            'population': write(base/'confirm-population.json', {'ids': ['fresh'], 'scope': 'withheld'}),
            'seeds': [30], 'generation': 'confirm-data', 'exposure': 'withheld_confirmation'}
        protocol['cells'].append(confirm_cell)
        protocol['stages'].append(stage('final-confirm', 'confirm', 'changed', ['confirm-cell'], required=['new-full']))
    proto.bind(root,write(base/'protocol.json',protocol))
    return root,protocol


def template():
    from test_research_cycle import specification
    # The ordinary v2 review contract is the existing supplied test policy.
    policy={'schema_version':1,'actors':{'proposer':'fixture-worker','executor':'fixture-worker','physics_critic':'fixture-critic','skeptical_verifier':'fixture-skeptic','physics_decider':'fixture-decider'},
        'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],'required_checks':[{'id':'integrity','kind':'integrity'},{'id':'math','kind':'scientific'}],
        'claim_scopes':{s:{'checks':['integrity','math'],'actions':['delivery','reuse']} for s in ['supplied_method_diagnostic','supplied_comparison_diagnostic']}}
    return {'schema_version':2,'mode':'research-comparison','source':'Synthetic supplied scalar arithmetic; no scientific efficacy.',
        'assumptions':['Input scalar values and method manifests are supplied; deterministic interval arithmetic does not establish physics or coverage.'],
        'max_seconds':10,'max_attempts':1,'approval_mode':'scripted_yes','task':{},
        'review_policy':{'schema_version':1,'policy':policy,'correction_contract':{'task_fields':[],'input_slots':[]}}}


def design(base,root,protocol,identity,values):
    stage=next(s for s in protocol['stages'] if s['id']==identity);candidate=next(c for c in protocol['candidates'] if c['id']==stage['candidate'])
    cells={c['id']:c for c in protocol['cells']};out=base/identity;out.mkdir()
    left=write(out/'supplied-values.json',{'value':values,'quality':True});right=write(out/'reference-values.json',{'value':[0]*len(values),'quality':True})
    rows=[]
    for n,a in enumerate(stage['cells']):
        c=cells[a['cell_id']];rows.append({'id':c['id'],'metric':'loss','unit':'1','exposure':c['exposure'],
            'left':{'source':left,'value_pointer':'/value/'+str(n),'interval_pointer':None,'quality_pointer':'/quality'},
            'right':{'source':right,'value_pointer':'/value/'+str(n),'interval_pointer':None,'quality_pointer':'/quality'}})
    deps=[*candidate['components'].values(),*candidate['invariant_inputs']]
    for a in stage['cells']:deps.extend([cells[a['cell_id']]['population'],cells[a['cell_id']]['normalization']])
    request=write(out/'request.json',{'schema_version':1,'protocol_sha256':cycle.ce.digest({'synthetic_stage':identity}),
        'comparison_id':'stage-'+identity,'rule':protocol['comparisons'][0]['rule'],'cells':rows,'dependencies':proto._pins(deps,base)})
    spec=template();spec['task']={'schema_version':1,'request':request}
    if 'goal_binding' in cycle._load(root)[1]['contract']:spec['goal_binding']=deepcopy(cycle._load(root)[1]['contract']['goal_binding'])
    specpin=write(out/'study.json',spec)
    e={'id':identity,'question':'Deliver the complete supplied '+identity+' cell matrix.','premise_ids':['pairing'],'parent':None,
        'change':'Explicit prospective supplied source manifest.','study':specpin,'cost':{'calls':0,'output_tokens':0,'wall_seconds':10,'native_attempts':1},
        'predictions':{'loss':None},'observable':{'pointer':'/decision','outcomes':{'better':'better','equivalent':'equivalent','worse':'worse','unknown':'unknown'}},
        'context_outputs':{},'acceptance_scope':'supplied_method_diagnostic','exploratory':False}
    if any(s['purpose'] == 'screen' and any(r['experiment_id'] == identity for r in s['cells']) for s in protocol['stages']):
        state = cycle._load(root)[1]
        action = {'experiment_id': identity, 'protocol_sha256': proto._bound(state)[1]['protocol']['sha256']}
        case = write(base/(identity+'-r1-case.json'), {'schema_version': 2, 'synthetic': True})
        receipt = write(base/(identity+'-r1.json'), {'schema_version': 1, 'kind': 'rdj-receipt',
            'outcome': 'authorize', 'gate': 'research_choice', 'action_digest': proto.ce.digest(action),
            'class': 'R1', 'open_a_findings': 0, 'unresolved_branches': 0,
            'case': case, 'case_sha256': case['sha256']})
        proto.authorize_screen(root, {**action, 'rdj_receipt': receipt})
    cycle.design(root,e);return e


def accepted_fixture(root,identity,*,remove_cell=None,failed=None):
    _,state=cycle._load(root);e=next(e for e in state['experiments'] if e['id']==identity);out=Path(state['base_dir'])/(identity+'-returned');out.mkdir()
    spec=proto._json(e['study'],state['base_dir']);result=compare.calculate(spec['task'],state['base_dir'])
    if remove_cell is not None:result['cells'].pop(remove_cell)
    resultpin=write(out/'result.json',result);receipt=write(out/'record.json',{'explicit_synthetic_stage_record':True,
        'stage':'science','attempt_id':'synthetic-'+identity,'status':'failed' if failed else 'succeeded'})
    e['rundir']=str(out);e['observation']={'receipt':receipt,'result':resultpin,'attempt_id':'synthetic-'+identity,
        'execution_status':'failed' if failed else 'succeeded','result_category':failed or 'defined_measurement','measured':None,'outcome':None,'prediction_comparison':{'loss':'unknown'}}
    e['adjudication']=None if failed else {'scope':e['acceptance_scope'],'view':{'state':'accepted'},'snapshot':write(out/'review.json',{'events':[],'explicit_synthetic_scope':e['acceptance_scope']})}
    cycle._commit(Path(root),state,'explicit_synthetic_outcome_presented',experiment_id=identity)
    return resultpin


def complete_comparator(base,root,identity):
    result=proto.prepare_comparison(root,identity,template(),base/(identity+'-generated'),predictions={'loss':None})
    cycle.design(root,result['experiment']);accepted_fixture(root,result['experiment']['id']);return result


def baseline_screen_full(base,monkeypatch,*,new_full=(3,4),confirmation=False):
    root,p=make(base,monkeypatch,confirmation=confirmation)
    for i,values in [('base-screen',[5]),('base-full',[2,3]),('new-screen',[1]),('new-full',list(new_full)),('ablation',[5,6])]:design(base,root,p,i,values)
    assert proto.eligibility(cycle._load(root)[1],'new-screen')
    accepted_fixture(root,'base-screen');accepted_fixture(root,'base-full')
    assert proto.eligibility(cycle._load(root)[1],'new-screen')==[]
    accepted_fixture(root,'new-screen');assert proto.eligibility(cycle._load(root)[1],'new-full')
    complete_comparator(base,root,'screen-contrast');assert proto.eligibility(cycle._load(root)[1],'new-full')==[]
    accepted_fixture(root,'new-full');complete_comparator(base,root,'full-contrast')
    accepted_fixture(root,'ablation');complete_comparator(base,root,'ablation-contrast')
    return root,p


def meta_host(transport='local'):
    """The inert meta host: an observed local model on loopback, or the loopback control transport."""
    local={'privacy':'local_only','local_models':['inert']} if transport=='local' else {}
    return agent_host.AgentHost(endpoint='http://127.0.0.1:9/v1/responses',**local)


def meta(base,root,monkeypatch,action,*,stages=(),required=(),resolves=(),replacement_stages=(),replacement_comparisons=(),replacement_claims=(),transport='local'):
    """One meta response through an inert host: an observed local model transport, or the loopback control."""
    count=sum(e['kind']=='protocol_meta_review_applied' for e in cycle._load(root)[1]['events'])
    prepared=proto.prepare_meta_review(root,base/('meta-'+str(count)),role='verifier',model='inert',reasoning_effort='high',max_output_tokens=128,max_wall_seconds=10)
    value={'kind':'research_meta_review','subject_sha256':prepared['context']['sha256'],'actor_id':prepared['actor_id'],'action':action,
        'affected_claim_ids':['complete-method'],'affected_stage_ids':list(stages),'objections':[{'location':'new-full / algorithm','statement':'Explicit synthetic located objection or resolution.'}],
        'required_experiment_ids':list(required),'premise_revision':None,'resolves_meta_revisions':list(resolves),'replacement_stage_ids':list(replacement_stages),
        'replacement_comparison_ids':list(replacement_comparisons),'replacement_claim_ids':list(replacement_claims)}
    host=meta_host(transport)
    def response(data,params,request,control):
        presented=json.loads(data)['input'];assert 'complete-method' in json.dumps(presented)
        return host._result(value,params,request,response_id='inert-meta-transport',observed_model='inert',usage={'input_tokens':8,'output_tokens':16})
    monkeypatch.setattr(host,'_responses',response)
    result=cycle.execute_graph(root,prepared['graph_root'],state_io.read_json(prepared['graph_spec']['path']),host)
    assert result['complete'],result
    return proto.apply_meta_review(root,graph_root=prepared['graph_root'],node_id='meta',context_pin=prepared['context'],allow_control=True)


def test_connected_complete_matrix_screen_win_full_loss_ablation_and_real_host_plan(tmp_path,monkeypatch):
    root,p=baseline_screen_full(tmp_path,monkeypatch)
    view=proto.status(root)
    assert view['comparisons']['screen-contrast']['decision']=='better'
    assert view['comparisons']['full-contrast']['decision']=='worse'
    assert view['full_stage_cell_denominator']==10 and view['complete_scientific_evidence']
    assert view['incumbent_options']['undominated_candidate_ids']==['original']
    # Acceptance of multiple narrower synthetic arithmetic receipts cannot
    # fulfill the unrelated original requested-quantity denominator.
    assert not cycle.status(root)['connected_task_complete']
    graph=tmp_path/'protocol-status-graph'
    prepared=proto.prepare_host_request(root,'status',{},graph,tmp_path/'prepared-host')
    unique={p['path']:p for p in prepared['inputs']};inputs=[{'id':'p'+str(i),'path':p['path'],'sha256':p['sha256']} for i,p in enumerate(unique.values())]
    identity=next(i['id'] for i in inputs if i['path']==prepared['request']['path'])
    # Functional custody replay is filesystem-bound; keep a bounded allowance
    # that does not turn host load into a failure of the status contract.
    spec={'schema_version':1,'graph_id':'protocol-status','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,'max_wall_seconds':60,'max_reworks':0},
        'nodes':[{'id':'status','kind':'tool','role':'designer','depends_on':[],'inputs':inputs,'packet':None,'action':'research-protocol','parameters':{'request_input':identity},'max_attempts':1}]}
    result=cycle.execute_graph(root,graph,spec,agent_host.AgentHost());assert result['complete'],result
    assert result['usage']['calls']==1 and cycle._graph_result(graph,'status')['value']['value']==view
    # Ordinary comparison planning is the genuine engine, not a plan sentinel.
    generated=complete_comparator  # no repeat or comparison recapture
    observed=cycle._load(root)[1]
    comparison_e=next(e for e in observed['experiments'] if e['id']=='compare-full-contrast')
    plan=tmp_path/'unapproved-plan';science.plan(plan,comparison_e['study']['path'])
    assert science.verify_plan(plan,approved=False)['schema_version']==2
    assert not (plan/science.APPROVAL).exists() and not (plan/'execution_attempt.json').exists()
    assert not list((plan/'outputs').rglob('result.json'))


def test_missing_full_cell_is_unknown_not_inferior_or_promoted(tmp_path,monkeypatch):
    root,p=make(tmp_path,monkeypatch)
    design(tmp_path,root,p,'base-full',[1,2]);accepted_fixture(root,'base-full',remove_cell=1)
    view=proto.status(root)
    assert [r['status'] for r in view['stages']['incumbent-full']]==['accepted_current','scientifically_unresolved']
    assert view['incumbent_options']['undominated_candidate_ids']==[]
    assert not view['complete_scientific_evidence']


@pytest.mark.parametrize('kind',['infrastructure_failure','scientific_unresolved'])
def test_failed_delivery_and_scientific_unresolved_are_distinct(tmp_path,monkeypatch,kind):
    root,p=make(tmp_path,monkeypatch);design(tmp_path,root,p,'base-full',[1,2]);accepted_fixture(root,'base-full',failed=kind)
    expected='operationally_unresolved' if kind=='infrastructure_failure' else 'scientifically_unresolved'
    assert {r['status'] for r in proto.status(root)['stages']['base-full']}=={expected}


def test_material_objection_reopens_only_named_candidate_and_never_restores_invalid_incumbent(tmp_path,monkeypatch):
    root,p=baseline_screen_full(tmp_path,monkeypatch,new_full=(1,2))
    assert proto.status(root)['incumbent_options']['undominated_candidate_ids']==['changed']
    meta(tmp_path,root,monkeypatch,'candidate_revision',stages=['new-full'])
    view=proto.status(root)
    assert {r['status'] for r in view['stages']['incumbent-full']}=={'accepted_current'}
    assert {r['status'] for r in view['stages']['new-full']}=={'stale'}
    assert view['incumbent_options']['undominated_candidate_ids']==['original']
    assert not view['complete_scientific_evidence']


def test_report_only_preserves_numeric_evidence_but_additional_evidence_blocks_claim(tmp_path,monkeypatch):
    root,p=baseline_screen_full(tmp_path,monkeypatch)
    objection={**deepcopy(p['stages'][1]),'id':'objection-probe','purpose':'objection_test','cells':deepcopy(p['stages'][1]['cells'])}
    for row in objection['cells']:row['experiment_id']='objection-probe'
    p['stages'].append(objection);proto.bind(root,write(tmp_path/'extended-protocol.json',p))
    design(tmp_path,root,p,'objection-probe',[2,3])
    meta(tmp_path,root,monkeypatch,'report_only')
    assert proto.status(root)['complete_scientific_evidence']
    state=meta(tmp_path,root,monkeypatch,'additional_evidence',required=['objection-probe'])
    view=proto.status(root)
    assert not view['complete_scientific_evidence']
    assert view['incumbent_options']['undominated_candidate_ids']==['original']
    revision=state['events'][-1]['revision']
    accepted_fixture(root,'objection-probe')
    meta(tmp_path,root,monkeypatch,'resolve_objections',required=['objection-probe'],resolves=[revision])
    assert proto.status(root)['complete_scientific_evidence']


@pytest.mark.parametrize('mutation',['second-component','held-input','cell-unit','rule-edit','claim-scope'])
def test_prospective_component_and_claim_scope_are_not_silently_changed(tmp_path,monkeypatch,mutation):
    root,p=make(tmp_path,monkeypatch);changed=deepcopy(p)
    if mutation=='second-component':changed['candidates'][2]['components']['grouping']=changed['candidates'][0]['components']['grouping']
    elif mutation=='held-input':changed['candidates'][2]['invariant_inputs']=[p['cells'][0]['population']]
    elif mutation=='cell-unit':changed['cells'][0]['unit']='pb'
    elif mutation=='rule-edit':changed['comparisons'][0]['rule']=write(tmp_path/'easier-rule.json',{**state_io.read_json(p['comparisons'][0]['rule']['path']),'min_gain':0})
    else:
        row=deepcopy(p['claims'][0]);row.update(id='easier-claim',replaces='complete-method',statement='Deliver one easier quantity only.');changed['claims'].append(row)
    before=cycle._load(root)[1]
    with pytest.raises(ValueError):proto.bind(root,write(tmp_path/'changed-protocol.json',changed))
    assert cycle._load(root)[1]==before


def test_source_rule_or_operand_mutation_holds_cross_candidate_comparison(tmp_path,monkeypatch):
    root,p=baseline_screen_full(tmp_path,monkeypatch)
    saved=cycle._load(root)[1];e=next(e for e in saved['experiments'] if e['id']=='base-full')
    Path(e['observation']['result']['path']).write_text('{}')
    with pytest.raises(ValueError):proto.prepare_comparison(root,'full-contrast',template(),tmp_path/'new-comparator',predictions={'loss':None})
    assert proto.eligibility(cycle._load(root)[1],'ablation')


def test_model_control_receipt_is_not_fresh_scientific_authority(tmp_path,monkeypatch):
    root,p=baseline_screen_full(tmp_path,monkeypatch)
    # A loopback control response is retained advice: it applies no action, even in control mode.
    advice=meta(tmp_path,root,monkeypatch,'report_only',transport='control')
    assert advice['kind']=='review_advice' and advice['independent'] is False
    state=cycle._load(root)[1]
    assert not any(e['kind']=='protocol_meta_review_applied' for e in state['events'])
    with pytest.raises(ValueError,match='fresh separately'):
        proto.apply_meta_review(root,graph_root=state['graphs'][-1]['root'],node_id='meta',context_pin=advice['value']['context'])


def replacements(base,root,p):
    updated=deepcopy(p);repair=deepcopy(p['candidates'][1]);repair.update(id='repaired',parent='changed',generation=2,requalifies='changed')
    repair['components']['grouping']=write(base/'repaired-method.txt','A fresh explicitly bounded source repair, not old votes.')
    ablated=deepcopy(p['candidates'][2]);ablated.update(id='ablated-repaired',parent='repaired',generation=3,requalifies='ablated')
    ablated['components']['grouping']=repair['components']['grouping'];updated['candidates'] += [repair,ablated]
    stage_map={s['id']:s for s in p['stages']}
    for old,new,candidate in [('new-screen','new-screen-v2','repaired'),('new-full','new-full-v2','repaired'),('ablation','ablation-v2','ablated-repaired')]:
        stage=deepcopy(stage_map[old]);stage.update(id=new,candidate=candidate,replaces=old)
        for row in stage['cells']:row['experiment_id']=new
        if old=='new-full':stage['requires'][0]['comparison_id']='screen-contrast-v2'
        if old=='ablation':stage['requires'][0]['comparison_id']='full-contrast-v2';stage['ablation']['parent_candidate']='repaired'
        updated['stages'].append(stage)
    comp_map={c['id']:c for c in p['comparisons']}
    for old,left,right in [('screen-contrast','new-screen-v2','base-screen'),('full-contrast','new-full-v2','incumbent-full'),('ablation-contrast','ablation-v2','new-full-v2')]:
        comp=deepcopy(comp_map[old]);comp.update(id=old+'-v2',experiment_id='compare-'+old+'-v2',left_stage=left,right_stage=right,replaces=old)
        updated['comparisons'].append(comp)
    claim=deepcopy(p['claims'][0]);claim.update(id='complete-method-v2',replaces='complete-method',stage_ids=['incumbent-full','new-full-v2','ablation-v2'],comparison_ids=['full-contrast-v2','ablation-contrast-v2'])
    updated['claims'].append(claim)
    proto.bind(root,write(base/'protocol-v2.json',updated));return updated


def test_material_repair_retests_screen_full_and_ablation_then_fresh_meta_closes_original_obligations(tmp_path,monkeypatch):
    root,p=baseline_screen_full(tmp_path,monkeypatch,new_full=(1,2))
    p=replacements(tmp_path,root,p)
    state=meta(tmp_path,root,monkeypatch,'candidate_revision',stages=['new-full'],required=['new-full-v2','ablation-v2'])
    revision=state['events'][-1]['revision'];before=cycle._usage(cycle._load(root)[1])
    for identity,values in [('new-screen-v2',[0.5]),('new-full-v2',[0.5,1.5]),('ablation-v2',[4,5])]:design(tmp_path,root,p,identity,values)
    assert proto.eligibility(cycle._load(root)[1],'new-full-v2')
    accepted_fixture(root,'new-screen-v2');complete_comparator(tmp_path,root,'screen-contrast-v2')
    assert proto.eligibility(cycle._load(root)[1],'new-full-v2')==[]
    accepted_fixture(root,'new-full-v2');complete_comparator(tmp_path,root,'full-contrast-v2')
    accepted_fixture(root,'ablation-v2');complete_comparator(tmp_path,root,'ablation-contrast-v2')
    assert not proto.status(root)['complete_scientific_evidence']
    state=meta(tmp_path,root,monkeypatch,'resolve_objections',required=['new-full-v2','ablation-v2'],resolves=[revision],
        replacement_stages=['new-full-v2','ablation-v2'],replacement_comparisons=['full-contrast-v2','ablation-contrast-v2'],replacement_claims=['complete-method-v2'])
    view=proto.status(root)
    assert view['complete_scientific_evidence']
    assert view['replacement_obligations']['claims']=={'complete-method':'complete-method-v2'}
    assert view['replacement_obligations']['stages']['new-full']=='new-full-v2'
    assert {r['status'] for r in view['stages']['new-full']}=={'stale'}
    assert view['incumbent_options']['undominated_candidate_ids']==['repaired']
    assert cycle._usage(state)['calls']==before['calls']+1
    assert state['events'][-1]['old_votes_carried'] is False and state['contract']['budget']['calls']==60


def test_prior_votes_cannot_close_new_additional_evidence_objection(tmp_path,monkeypatch):
    root,p=baseline_screen_full(tmp_path,monkeypatch)
    state=meta(tmp_path,root,monkeypatch,'additional_evidence',required=['ablation']);revision=state['events'][-1]['revision']
    with pytest.raises(ValueError,match='same prior output and votes'):
        meta(tmp_path,root,monkeypatch,'resolve_objections',required=['ablation'],resolves=[revision])
    assert not proto.status(root)['complete_scientific_evidence']


@pytest.mark.parametrize('mutation',['missing-interval','wide-interval','false-quality','unit','mixed','bool-value'])
def test_interval_quality_unit_and_whole_matrix_decisions(tmp_path,mutation):
    left=write(tmp_path/'left.json',{'value':[1,2],'interval':[[0.9,1.1],[1.9,2.1]],'quality':True})
    right=write(tmp_path/'right.json',{'value':[3,4],'interval':[[2.9,3.1],[3.9,4.1]],'quality':True})
    rule=write(tmp_path/'interval-rule.json',{'schema_version':1,'metric':'loss','unit':'1','direction':'minimize','min_gain':0.1,'tolerance':0.001,'uncertainty':'supplied_intervals','reduction':'all_cells'})
    rows=[{'id':'cell'+str(i),'metric':'loss','unit':'1','exposure':'adaptive_full',
        'left':{'source':left,'value_pointer':'/value/'+str(i),'interval_pointer':'/interval/'+str(i),'quality_pointer':'/quality'},
        'right':{'source':right,'value_pointer':'/value/'+str(i),'interval_pointer':'/interval/'+str(i),'quality_pointer':'/quality'}} for i in range(2)]
    if mutation in {'missing-interval','wide-interval','false-quality','mixed','bool-value'}:
        value=state_io.read_json(left['path'])
        if mutation=='missing-interval':value.pop('interval')
        elif mutation=='wide-interval':value['interval']=[[-20,20],[-20,20]]
        elif mutation=='false-quality':value['quality']=False
        elif mutation=='mixed':value['value'][1]=6;value['interval'][1]=[5.9,6.1]
        else:value['value'][0]=True
        left=write(Path(left['path']),value)
        for row in rows:row['left']['source']=left
    if mutation=='unit':rows[0]['unit']='pb'
    request=write(tmp_path/'request.json',{'schema_version':1,'protocol_sha256':'a'*64,'comparison_id':'interval-comparison','rule':rule,'cells':rows,'dependencies':[]})
    task={'schema_version':1,'request':request}
    if mutation=='unit':
        with pytest.raises(ValueError,match='metric/unit'):compare.calculate(task,tmp_path)
    else:
        result=compare.calculate(task,tmp_path);assert result['decision']=='unknown' and result['cell_count']==2
        assert not result['scientific_acceptance'] and not result['physics_validated']


def test_source_divergence_invalidates_only_affected_source_stage_and_baseline_survives(tmp_path,monkeypatch):
    root,p=baseline_screen_full(tmp_path,monkeypatch,new_full=(1,2))
    Path(p['candidates'][1]['components']['grouping']['path']).write_text('Altered original source; no retarget or rehash adoption.')
    view=proto.status(root)
    assert {r['status'] for r in view['stages']['new-full']}=={'stale'}
    assert {r['status'] for r in view['stages']['incumbent-full']}=={'accepted_current'}
    assert view['incumbent_options']['undominated_candidate_ids']==['original']
    assert not view['complete_scientific_evidence']


def test_specification_and_consumed_value_snapshot_aba_cannot_swap_source_answers(tmp_path,monkeypatch):
    root,p=make(tmp_path,monkeypatch);e=design(tmp_path,root,p,'base-full',[1,2]);spec=state_io.read_json(e['study']['path'])
    request=state_io.read_json(spec['task']['request']['path']);source=Path(request['cells'][0]['left']['source']['path']);original=source.read_bytes()
    captured=compare._json
    def swap(pin,base):
        if pin['path']==str(source):
            source.write_bytes(original.replace(b'1',b'9',1))
            try:return captured(pin,base)
            finally:source.write_bytes(original)
        return captured(pin,base)
    monkeypatch.setattr(compare,'_json',swap)
    with pytest.raises(ValueError,match='authenticated'):compare.calculate(spec['task'],tmp_path)


def test_promotion_preparation_cannot_bypass_missing_baseline(tmp_path,monkeypatch):
    root,p=make(tmp_path,monkeypatch);design(tmp_path,root,p,'new-screen',[1])
    before=cycle._load(root)[1];rundir=tmp_path/'premature-plan'
    with pytest.raises(ValueError,match='not currently admissible'):
        cycle.prepare_experiment(root,'new-screen',rundir)
    assert not rundir.exists() and cycle._load(root)[1]==before


def test_planned_stage_source_drift_refuses_at_last_dispatch_boundary(tmp_path,monkeypatch):
    root,p=make(tmp_path,monkeypatch);design(tmp_path,root,p,'base-screen',[1])
    planned=cycle.prepare_experiment(root,'base-screen',tmp_path/'ordinary-unapproved-plan')
    assert planned['experiments'][0]['plan'] is not None
    Path(p['candidates'][0]['components']['grouping']['path']).write_text('Changed after genuine preparation')
    monkeypatch.setattr(science,'run',lambda *a,**kw:pytest.fail('Stale protocol reached ordinary dispatch'))
    with pytest.raises(ValueError,match='protocol prerequisites'):
        cycle.run_experiment(root,'base-screen')
    assert not (tmp_path/'ordinary-unapproved-plan'/science.APPROVAL).exists()


@pytest.mark.parametrize('operation',['host-prepare','meta-prepare'])
def test_bounded_normal_cli_prepares_real_host_and_meta_routes_without_dispatch(tmp_path,monkeypatch,capsys,operation):
    root,p=make(tmp_path,monkeypatch)
    if operation=='host-prepare':
        command={'operation':'status','parameters':{},'graph_root':str(tmp_path/'prepared-graph'),'output_dir':str(tmp_path/'host-request')}
    else:
        command={'output_dir':str(tmp_path/'meta-prepared'),'role':'critic','model':'inert','reasoning_effort':'high','max_output_tokens':128,'max_wall_seconds':10}
    pin=write(tmp_path/'command.json',command);before=cycle._load(root)[1]
    assert proto.main([operation,'--cycle',str(root),'--request',pin['path']])==0
    output=json.loads(capsys.readouterr().out)
    assert output['execution_authorized'] is False and cycle._load(root)[1]==before
    if operation=='meta-prepare':
        graph=state_io.read_json(output['graph_spec']['path']);agent_graph.validate(graph)
        assert graph['nodes'][0]['inputs']==[] and graph['nodes'][0]['packet'] is not None
        assert not Path(output['graph_root']).exists()
    else:assert output['request'] in output['inputs']


def test_unique_source_byte_ceiling_is_admitted_before_payload_io(tmp_path,monkeypatch):
    pins=[{'path':str(tmp_path/('opaque'+str(i))),'sha256':'a'*64,'size':8*1024**2} for i in range(9)]
    monkeypatch.setattr(compare,'_snapshot',lambda *a,**kw:pytest.fail('Oversized source population reached payload I/O'))
    with pytest.raises(ValueError,match='unique comparison source population'):proto._pins(pins,tmp_path)


def test_additional_evidence_objection_requires_concrete_fresh_test_obligations(tmp_path,monkeypatch):
    root,p=baseline_screen_full(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='explicit fresh ordinary test'):
        meta(tmp_path,root,monkeypatch,'additional_evidence')
    assert not any(e['kind']=='protocol_meta_review_applied' for e in cycle._load(root)[1]['events'])


def test_comparison_preserves_original_parent_assignment_and_real_unapproved_plan(tmp_path,monkeypatch):
    from test_task_completion import goal,PROMPT
    from ravel.workflow import task_completion
    _,cp=goal(tmp_path);binding={'contract':cp,'assignment_id':'summary-child'}
    root,p=make(tmp_path,monkeypatch,goal_binding=binding)
    for identity,values in [('base-screen',[2]),('base-full',[2,3]),('new-screen',[1])]:
        design(tmp_path,root,p,identity,values);accepted_fixture(root,identity)
    result=proto.prepare_comparison(root,'screen-contrast',template(),tmp_path/'parent-bound-comparison',predictions={'loss':None})
    spec=state_io.read_json(result['experiment']['study']['path'])
    assert spec['goal_binding']==binding and Path(cp['path']) in science.task_inputs(spec,Path(result['experiment']['study']['path']).parent)
    cycle.design(root,result['experiment']);rundir=tmp_path/'parent-bound-plan'
    cycle.prepare_experiment(root,result['experiment']['id'],rundir)
    plan=science.verify_plan(rundir,approved=False)
    assert state_io.read_json(rundir/science.SPEC)['goal_binding']==binding
    assert plan['stage_binding']['input_snapshot'][cp['path']]['files'][0]['sha256']==cp['sha256']
    view=cycle.status(root);assert view['parent_task']['original_request']==PROMPT and view['parent_task_accepted'] is False
    assert not (rundir/science.APPROVAL).exists() and not (rundir/'execution_attempt.json').exists()
    request=write(tmp_path/'parent-still-open.json',{'schema_version':1,'contract':cp,'outcomes':[],'parent_review':None,'report':None})
    original=task_completion.evaluate(request,base_dir=tmp_path)
    assert set(original['unmet_obligation_ids'])=={'original-request','atlas','cms','domain'} and not original['parent_task_accepted']


def test_full_stage_cannot_relabel_screen_cells_as_full_evidence(tmp_path,monkeypatch):
    root,p=make(tmp_path,monkeypatch);changed=deepcopy(p)
    next(s for s in changed['stages'] if s['id']=='new-screen')['purpose']='full'
    before=cycle._load(root)[1]
    with pytest.raises(ValueError,match='screen-only cells'):
        proto.bind(root,write(tmp_path/'screen-as-full.json',changed))
    assert cycle._load(root)[1]==before


def test_full_candidate_needs_every_declared_full_stage_with_missing_cells_retained(tmp_path,monkeypatch):
    root,p=baseline_screen_full(tmp_path,monkeypatch)
    assert proto.status(root)['incumbent_options']['valid_full_candidate_ids']==['changed','original']
    extra=deepcopy(next(s for s in p['stages'] if s['id']=='incumbent-full'))
    extra.update(id='another-full-regime',replaces=None)
    for row in extra['cells']:row['experiment_id']='another-full-regime'
    p['stages'].append(extra);p['required_stage_ids'].append(extra['id'])
    proto.bind(root,write(tmp_path/'complete-full-regimes.json',p))
    view=proto.status(root)
    assert view['incumbent_options']['valid_full_candidate_ids']==['changed']
    assert view['missing_required_stages']==['another-full-regime']
    assert [row['status'] for row in view['stages']['another-full-regime']]==['unplanned','unplanned']
    assert {row['status'] for row in view['stages']['incumbent-full']}=={'accepted_current'}
    assert not view['complete_scientific_evidence']
