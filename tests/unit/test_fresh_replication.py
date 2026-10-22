"""Authored source-connected engineering controls, unexecuted by the author.

The module seed uses the real supplied-quantity worker and ordinary role APIs;
review actors are explicit synthetic controls, never physicists/models. Each
case copies only immutable small campaign metadata, sharing read-only original
source/run custody. No native physics/provider is requested. Independent source
and unknown-error fixtures are declarations, not validated scientific oracles.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest
from ravel.workflow import fresh_replication as fresh, research_cycle as cycle
from ravel.workflow import research_protocol as protocol, research_coordinator_decisions as decisions
from ravel.workflow import agent_host, science, physics_review, review_context, scientific_report
from ravel.physics import quantities, research_comparison as comparison
from ravel.workflow.state_io import read_json
from method_decision_fixture import admit_method
from stage_evidence_fixture import stage_evidence
from test_research_cycle import contract, propose, experiment, run_one, review_math, report_request, write
from test_report_integrity import fixture as manuscript_fixture, located, span


# Host-speed margins of the synthetic campaign. Both are upper bounds: a worker ends when its
# work is done, so a fast host is not slowed. On a slow host the original 600 s campaign clock
# runs out during this file's own run time, and the comparison worker (two complete producer
# reconstructions over a source closure of several hundred files) does not finish inside the
# 30 s ceiling of the original study; it needed about 270 s on the cluster node.
# The module-scoped seed starts its campaign clock at its first dispatch and later tests dispatch
# against that clock. The file takes 73 minutes on the cluster node and over two hours on a hosted
# runner, so a one-hour clock expired for the tests that run late ("experiment not currently
# admissible for preparation"). The clock outlasts the longest file limit of the hosted jobs
# (16200 s, .github/workflows/ci.yml) with margin: no host is slow enough to expire it.
CAMPAIGN_SECONDS=21600;COMPARISON_SECONDS=900


def campaign(base):
    value=contract(base);value['budget']['wall_seconds']=CAMPAIGN_SECONDS
    return value


def location(pin, pointer):
    value=cycle._pointer(read_json(pin['path']),pointer)
    return {'artifact':deepcopy(pin),'format':'json','location':pointer,'value':deepcopy(value)}


@pytest.fixture(scope='module')
def seed_domain(_machine_lease_module_domain):
    """The machine-state domain the module-scoped seed dispatched its review roles in."""
    return _machine_lease_module_domain


@pytest.fixture(autouse=True)
def seed_dispatch_domain(request, lock_domain_at):
    """A test that reuses the seed works in the seed's machine-state domain.

    The graph runner recorded the seed's role dispatches in that domain, as one machine state
    root holds them in a real campaign; a fresh per-test domain would hide the records and
    with them the seed's independent review credit.
    """
    if {'seed', 'classified_seed'} & set(request.fixturenames):
        lock_domain_at(request.getfixturevalue('seed_domain'))


@pytest.fixture(scope='module')
def seed(tmp_path_factory, seed_domain):
    base=tmp_path_factory.mktemp('replication-original')
    root=base/'cycle';cycle.create(root,campaign(base),base_dir=base, evaluation_harness=True);propose(base,root)
    e=experiment(base,'paired',grouped=True)
    rd=run_one(base,root,e);review_math(rd,root,'paired')
    quantitative=report_request(base,root,rd)
    quantitative['artifact_request']['basis'][0]['path']='context-request.json'
    quantitative['artifact_request']['tools']['study']['path']=str(rd.relative_to(base)/'outputs/attempt-1/result.json')
    qp=write(base/'quantitative-report.json',quantitative)
    text=scientific_report.compose(quantitative,base_dir=base)['report_text']
    report=manuscript_fixture(base/'manuscript')
    result=cycle._pin(rd/'outputs/attempt-1/result.json')
    result_location=location(result,'/quantities/covariance/0/0')
    report['claims'][0].update(statement='The complete supplied two-record grouped covariance is one, conditional on the source grouping.',evidence=[result_location])
    op=report['methods'][0]['operations'][0]
    op.update(description='Evaluate the actual supplied signed-group quantity implementation.',
        code=[located(Path(quantities.__file__),Path(quantities.__file__).read_text())],results=[result_location],
        execution={'rundir':str(rd),'receipt':cycle._load(root)[1]['experiments'][0]['observation']['receipt']},differences=[])
    report['methods'][0]['description']='Actual supplied grouped-weight variance; no physics efficacy is claimed.'
    original=Path(report['manuscript']['path']).read_text()
    original=original.replace('The supplied score is four [1].','The conditional grouped covariance is one [1].')
    original=original.replace('We square the supplied x [1]; no optimization is claimed.','We evaluate complete supplied signed groups [1]; no optimization is claimed.')
    # Retain every character with recomputed literal spans after that honest edit.
    parts=original.splitlines(keepends=True);cursor=0
    for unit,part in zip(report['units'],parts):unit['span']=span(part,cursor);cursor+=len(part)
    for occurrence,unit in zip(report['citations'][0]['occurrences'],report['units'][:2]):
        occurrence['span']=span('[1]',original.index('[1]',unit['span']['start']))
    report['units'].append({'id':'quantities','kind':'other','span':span(text,len(original))})
    report['manuscript']=write(base/'manuscript'/'manuscript.md',original+text)
    report['quantitative_report']={'request':qp,'span':span(text,len(original))}
    rp=write(base/'integrity-request.json',report)
    return {'base':base,'root':root,'experiment':e,'report':rp}


def case(seed,tmp_path,*,quality='supplied',semantics='deterministic',purpose='faithful_reexecution'):
    root=tmp_path/'cycle';shutil.copytree(seed['root'],root)
    e=seed['experiment'];base=seed['base'];study=read_json(e['study']['path'])
    rule={'schema_version':1,'metric':'conditional variance','unit':'1','direction':'minimize',
        'min_gain':0.,'tolerance':0.,'uncertainty':'deterministic','reduction':'all_cells'}
    rule_pin=write(tmp_path/'rule.json',rule)
    policy_pin=write(tmp_path/'source-policy.json',{'rule':rule,
        'error':{'kind':semantics,'meaning':'Exact supplied finite arithmetic unless marked unknown.',
            'coverage':'Synthetic supplied grouping only; no stochastic coverage or physical uncertainty claim.'},
        'reference':{'state':quality,'scope':'Supplied original engineering reference only; identity is not scientific independence.'}})
    template=deepcopy(study);template.update(mode='research-comparison',task={},max_seconds=COMPARISON_SECONDS)
    template_pin=write(tmp_path/'comparison-template.json',template)
    source_contract=cycle._pin(Path(e['study']['path']).parent/'contract.json')
    c={'schema_version':1,'id':'fresh-check','purpose':purpose,
        'custody_limits':{'max_files':20000,'max_bytes':16*1024**3,'max_metadata_bytes':16*1024**2},
        'operations':[{'operation_id':'evaluate','original_experiment':'paired','fresh_experiment':'replicated','study':None,
            'state':{'original':location(e['study'],'/task'),'fresh':location(e['study'],'/task')},
            'representation':{'original':location(source_contract,'/normalization'),'fresh':location(source_contract,'/normalization')},
            'differences':[],'cost':deepcopy(e['cost']),'acceptance_scope':e['acceptance_scope']}],
        'population':{'source':location(source_contract,'/bins'),'id_field':'id','cells':[{
            'id':'one','operation_id':'evaluate','metric':rule['metric'],'unit':'1','exposure':'adaptive_full',
            'value_pointer':'/quantities/covariance/0/0','interval_pointer':None,'quality_pointer':'/status'}]},
        'rule':rule_pin,'rule_evidence':location(policy_pin,'/rule'),'error_semantics':location(policy_pin,'/error'),
        'reference':{'quality':location(policy_pin,'/reference'),'sources':[],'points':[],'minimum_points':1},
        'comparison':{'experiment_id':'fresh-comparison','study_template':template_pin,
            'cost':{**deepcopy(e['cost']),'wall_seconds':COMPARISON_SECONDS},
            'predictions':{'independent':'equivalent','grouped':'equivalent','unknown':None},'acceptance_scope':e['acceptance_scope']}}
    return root,c,write(tmp_path/'check.json',c)


def prepare(seed,tmp_path,**kwargs):
    root,c,cp=case(seed,tmp_path,**kwargs)
    result=fresh.prepare_replication_request(root,seed['report'],'square',tmp_path/'prepared',check_contract_pin=cp)
    return root,c,result


def review(rd,root,identity):
    record=science.execution.load_execution(rd)['stages']['science']
    result=read_json(rd/'outputs/attempt-1/result.json')
    assert result['status']=='passed' and result['physics_validated'] is False
    checks=write(rd/'inputs/replication-checks.json',{'schema_version':1,'checks':[
        {'id':key,'status':'pass','attempt_ids':[record['attempt_id']],
         'evidence':[{'path':'outputs/attempt-1/result.json','location':'$'}]} for key in ('integrity','math')]})
    physics_review.open_cycle(rd,effective_settings=science.review_effective_settings(rd),
        stage_receipts=[record['attempt_record']],check_results='inputs/replication-checks.json')
    for role,actor,packet_role in [('physics_critic','fixture-critic','critic'),
        ('skeptical_verifier','fixture-skeptic','verifier'),('physics_decider','fixture-decider','synthesizer')]:
        out=root/(identity+'-'+packet_role);manifest=review_context.create(rd,packet_role,out)
        # Every indexed copy is read and authenticated in one custody session, and one of them through
        # the per-artifact entry point as well. A separate call per artifact authenticates the whole
        # packet again each time, which is quadratic in a packet of several hundred source files.
        assert review_context.verify_packet(out,expected_manifest_sha256=manifest['sha256'])['artifacts']==manifest['artifacts']
        first=manifest['artifacts'][0]
        content=review_context.read_artifact(out,first['id'],expected_manifest_sha256=manifest['sha256'])
        assert hashlib.sha256(content).hexdigest()==first['sha256']
        # The recorded vote is the bound response of the dispatched role; a declared name is advice.
        from bound_review import bound_review
        bound_review(rd,role=role,verdict='accept',claim_scope='supplied_math_diagnostic',
            summary='Synthetic complete finite arithmetic/control review only; no scientific/model/physicist acceptance.')
    cycle.adjudicate(root,identity)


def fresh_run(seed,tmp_path,root,prepared,*,accepted=True,failed=False):
    fresh.design_prepared(root,prepared['request'],experiment_id='replicated')
    e=read_json(prepared['request']['path'])['experiments'][0]
    rd=tmp_path/'replicated-run'
    cycle.prepare_experiment(root,e['id'],rd);admit_method(rd)
    with pytest.raises((ValueError,OSError)):cycle.run_experiment(root,e['id'])
    science.approve(rd,'Root-owned inert software control with supplied quantity worker only.',scripted=True)
    if failed:
        # Real durable failed attempt, no worker invoked in this branch. The
        # declared source/spec/authority are unchanged; a retained infrastructure
        # failure is not a scientific negative or accepted reference.
        proposal=science.verify_plan(rd,approved=True)
        attempt={'attempt':1,'plan_sha256':science.execution.file_hash(rd/science.PLAN),
            'budget_seconds':proposal['max_seconds'],'started_utc':science.execution.utc_now(),
            'correction_id':None,'correction_plan_sha256':None}
        write(rd/'execution_attempt.json',attempt);write(rd/'logs/science-attempts/00000001.json',attempt)
        stage,binding,_=science._selected(rd,proposal)
        record=science.execution.begin_attempt(rd,'science',binding,stage['log'])
        (rd/stage['log']).write_text('Explicit inert retained infrastructure failure; no native worker.\n')
        science.execution.finish_attempt(rd,record,2,'fixture infrastructure refusal')
    else:assert cycle.run_experiment(root,e['id'])==0,stage_evidence(rd)
    cycle.observe(root,e['id'])
    if accepted and not failed:review(rd,root,e['id'])
    return rd


def test_R01_actual_coordinator_graph_fresh_worker_review_and_comparison(seed,tmp_path):
    root,c,cp=case(seed,tmp_path);before=cycle._load(root)[1]['sha256']
    graph_root=tmp_path/'prepare-graph'
    params={'current_report_pin':seed['report'],'method_id':'square','output_dir':str(tmp_path/'prepared'),'check_contract_pin':cp}
    transport=protocol.prepare_host_request(root,'replication',params,graph_root,tmp_path/'host',presentation='indexed')
    assert cycle._load(root)[1]['sha256']==before
    inputs=[{'id':'p'+str(i),**{k:p[k] for k in ('path','sha256')}} for i,p in enumerate(transport['inputs'])]
    assert len(inputs)<=128
    req_id=next(p['id'] for p in inputs if p['path']==transport['request']['path'])
    spec={'schema_version':1,'graph_id':'fresh-preparation','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,
        'max_wall_seconds':60,'max_reworks':0},'nodes':[{'id':'prepare','kind':'tool','role':'proposer','depends_on':[],
        'inputs':inputs,'packet':None,'action':'research-protocol','parameters':{'request_input':req_id},'max_attempts':1}]}
    observed=cycle.execute_graph(root,graph_root,spec,agent_host.AgentHost())
    assert observed['complete'] and observed['usage']['calls']==1
    prepared=cycle._graph_result(graph_root,'prepare')['value']['value']
    assert not prepared['execution_authorized'] and not prepared['replication_accepted']
    assert 'replication-prepare' in decisions.EXTENSIONS and 'replication-comparison' in decisions.EXTENSIONS
    fresh_run(seed,tmp_path,root,prepared)
    bound=decisions.invoke_extension('replication-comparison',root,{'request_pin':prepared['request']},tmp_path/'comp',None,{})
    task=read_json(bound['study']['path'])['task']
    arithmetic=comparison.calculate(task,tmp_path/'comp')
    assert arithmetic['decision']=='equivalent' and len(arithmetic['cells'])==1
    assert not bound['replication_accepted'] and bound['complete_original_cell_denominator']==['one']
    cycle.design(root,bound['experiment']);rd=tmp_path/'comparison-run'
    cycle.prepare_experiment(root,'fresh-comparison',rd);admit_method(rd)
    science.approve(rd,'Pure supplied comparison software control only.',scripted=True)
    assert cycle.run_experiment(root,'fresh-comparison')==0,stage_evidence(rd)
    cycle.observe(root,'fresh-comparison');review(rd,root,'fresh-comparison')
    assert cycle._load(root)[1]['experiments'][-1]['adjudication']['view']['state']=='accepted'


def test_prepare_is_pinned_complete_and_has_no_effect_or_vote(seed,tmp_path):
    root,c,cp=case(seed,tmp_path);before=cycle._load(root)[1]
    prepared=decisions.invoke_extension('replication-prepare',root,{'current_report_pin':seed['report'],
        'method_id':'square','check_contract_pin':cp},tmp_path/'prepared',None,{})
    assert cycle._load(root)[1]==before
    d=read_json(prepared['request']['path'])
    assert d['population']==c['population']['cells'] and d['originals'][0]['experiment']==before['experiments'][0]
    assert not prepared['execution_authorized'] and not prepared['replication_accepted']
    assert not (tmp_path/'replicated-run').exists()
    fresh.design_prepared(root,prepared['request'],experiment_id='replicated')
    assert cycle._load(root)[1]['experiments'][-1]['rundir'] is None


@pytest.mark.parametrize('change',['bounds','normalization','auxiliary'])
def test_R04_same_score_cannot_mask_changed_state_or_representation(seed,tmp_path,change):
    root,c,cp=case(seed,tmp_path)
    spec=read_json(seed['experiment']['study']['path']);folder=Path(seed['experiment']['study']['path']).parent
    spec['task']={k:str(folder/v) for k,v in spec['task'].items()}
    if change=='bounds':spec['max_seconds']+=1
    elif change=='auxiliary':spec['assumptions'].append('Changed auxiliary conditioning is explicit.')
    else:
        changed=read_json(folder/'contract.json');changed['normalization']['scale']=2.
        spec['task']['contract']=str(tmp_path/'different-contract.json')
        changed_contract=write(Path(spec['task']['contract']),changed)
        c['operations'][0]['representation']['fresh']=location(changed_contract,'/normalization')
        assert c['operations'][0]['representation']['original']['value']['scale']==1.
        assert c['operations'][0]['representation']['fresh']['value']['scale']==2.
        assert c['operations'][0]['representation']['fresh']['artifact']==changed_contract
        assert changed_contract['path']==spec['task']['contract']
    sp=write(tmp_path/'different-study.json',spec);c['operations'][0]['study']=sp
    c['operations'][0]['state']['fresh']=location(sp,'/task')
    cp=write(tmp_path/'changed-check.json',c)
    with pytest.raises(ValueError,match='faithful replay'):fresh.prepare_replication_request(root,seed['report'],'square',tmp_path/'held',check_contract_pin=cp)


def test_R04_stale_normalization_representation_refuses_actual_prospective_custody(seed,tmp_path):
    root,c,cp=case(seed,tmp_path)
    spec=read_json(seed['experiment']['study']['path']);folder=Path(seed['experiment']['study']['path']).parent
    spec['task']={k:str(folder/v) for k,v in spec['task'].items()}
    changed=read_json(folder/'contract.json');changed['normalization']['scale']=2.
    spec['task']['contract']=str(tmp_path/'different-contract.json')
    changed_contract=write(Path(spec['task']['contract']),changed)
    sp=write(tmp_path/'different-study.json',spec);c['operations'][0]['study']=sp
    c['operations'][0]['state']['fresh']=location(sp,'/task')
    # Intentionally retain the original representation, outside the fresh study's inputs.
    assert c['operations'][0]['representation']['fresh']==c['operations'][0]['representation']['original']
    assert c['operations'][0]['representation']['fresh']['value']['scale']==1.
    assert changed['normalization']['scale']==2.
    assert c['operations'][0]['representation']['fresh']['artifact']!=changed_contract
    cp=write(tmp_path/'changed-check.json',c)
    with pytest.raises(ValueError,match='state/population/representation must descend actual original or prospective study custody'):
        fresh.prepare_replication_request(root,seed['report'],'square',tmp_path/'held',check_contract_pin=cp)
    assert not (tmp_path/'held').exists()


@pytest.mark.parametrize('change',['drop','relabel','foreign-operation'])
def test_R03_original_full_population_and_exposure_are_not_redefined(seed,tmp_path,change):
    root,c,cp=case(seed,tmp_path)
    if change=='drop':c['population']['cells']=[]
    elif change=='relabel':c['population']['cells'][0]['exposure']='withheld_confirmation'
    else:c['population']['cells'][0]['operation_id']='foreign'
    cp=write(tmp_path/'bad-check.json',c)
    with pytest.raises(ValueError):fresh.prepare_replication_request(root,seed['report'],'square',tmp_path/'held',check_contract_pin=cp)


@pytest.mark.parametrize('quality,semantics',[('unknown','deterministic'),('supplied','unknown')])
def test_R05_unknown_reference_or_error_law_retains_whole_unknown(seed,tmp_path,quality,semantics):
    root,c,prepared=prepare(seed,tmp_path,quality=quality,semantics=semantics)
    fresh_run(seed,tmp_path,root,prepared)
    bound=fresh.prepare_comparison(root,prepared['request'],tmp_path/'comp')
    outcome=comparison.calculate(read_json(bound['study']['path'])['task'],tmp_path/'comp')
    assert outcome['decision']=='unknown' and len(outcome['cells'])==1
    assert read_json((tmp_path/'comp')/'fresh-outcomes.json')['cells'][0]['quality'] is False
    assert not bound['replication_accepted']


def test_R03_failed_fresh_attempt_remains_in_actual_complete_comparison(seed,tmp_path):
    root,c,prepared=prepare(seed,tmp_path)
    fresh_run(seed,tmp_path,root,prepared,accepted=False,failed=True)
    bound=fresh.prepare_comparison(root,prepared['request'],tmp_path/'comp')
    raw=read_json(tmp_path/'comp'/'fresh-outcomes.json')['cells']
    assert len(raw)==1 and raw[0]['value'] is None and raw[0]['quality'] is False
    assert raw[0]['original_execution_status']=='failed'
    assert comparison.calculate(read_json(bound['study']['path'])['task'],tmp_path/'comp')['decision']=='unknown'


def test_R02_old_result_or_receipt_cannot_be_relabelled_fresh(seed,tmp_path):
    root,c,prepared=prepare(seed,tmp_path);fresh.design_prepared(root,prepared['request'],experiment_id='replicated')
    state=cycle._load(root)[1];old=state['experiments'][0];new=state['experiments'][-1]
    # Internal synthetic adversary, not a public capability or authorized vote.
    for key in ('rundir','plan','observation','adjudication'):new[key]=deepcopy(old[key])
    cycle._commit(root,state,'synthetic_old_score_relabel')
    with pytest.raises(ValueError,match='distinct fresh'):fresh.prepare_comparison(root,prepared['request'],tmp_path/'held')


@pytest.mark.parametrize('change',['duplicate','too-few','heldout-label'])
def test_R06_alias_payloads_minimum_points_and_labels_do_not_supply_independence(seed,tmp_path,change):
    root,c,cp=case(seed,tmp_path,purpose='independent_reference')
    a=write(tmp_path/'point-a.json',{'score':1});b=write(tmp_path/'point-b.json',{'score':1})
    c['reference']['sources']=[a];c['reference']['points']=[a,b] if change=='duplicate' else [a]
    c['reference']['minimum_points']=2 if change=='too-few' else 1
    cp=write(tmp_path/'reference-check.json',c)
    with pytest.raises(ValueError,match='duplicate|point population|actually consumed'):fresh.prepare_replication_request(root,seed['report'],'square',tmp_path/'held',check_contract_pin=cp)


def test_generated_request_cannot_rebaseline_post_write_mutation(seed,tmp_path,monkeypatch):
    root,c,cp=case(seed,tmp_path);real=fresh.integrity.state_io.atomic_json
    def late(path,value):
        real(path,value)
        if Path(path).name=='replication-request.json':
            changed=deepcopy(value);changed['execution_authorized']=True;real(path,changed)
    monkeypatch.setattr(fresh.integrity.state_io,'atomic_json',late)
    with pytest.raises(ValueError,match='changed|differs'):fresh.prepare_replication_request(root,seed['report'],'square',tmp_path/'held',check_contract_pin=cp)


def test_repinning_forged_issued_population_does_not_supply_producer_authority(seed,tmp_path):
    root,c,prepared=prepare(seed,tmp_path);d=read_json(prepared['request']['path']);d['population'][0]['quality_pointer']='/physics_validated'
    forged=write(tmp_path/'forged.json',d)
    with pytest.raises(ValueError,match='producer'):fresh.design_prepared(root,forged,experiment_id='replicated')


def test_comparison_worker_rechecks_actual_source_outcomes_and_original_closure(seed,tmp_path):
    root,c,prepared=prepare(seed,tmp_path);fresh_run(seed,tmp_path,root,prepared)
    bound=fresh.prepare_comparison(root,prepared['request'],tmp_path/'comp')
    original=read_json(tmp_path/'comp'/'fresh-outcomes.json');changed=deepcopy(original);changed['cells'][0]['value']=99
    fake=write(tmp_path/'false-outcomes.json',changed);request=read_json(bound['comparison']['path'])
    request['cells'][0]['left']['source']=fake
    bad=write(tmp_path/'false-comparison.json',request)
    with pytest.raises(ValueError,match='actual ordinary outcome'):comparison.calculate({'schema_version':1,'request':bad},tmp_path)


def test_R05_distinct_consumed_source_mismatch_is_retained_not_repaired(seed,tmp_path):
    root,c,cp=case(seed,tmp_path,purpose='independent_reference')
    spec=read_json(seed['experiment']['study']['path']);folder=Path(seed['experiment']['study']['path']).parent
    rows=[json.loads(x) for x in (folder/'records.jsonl').read_text().splitlines()]
    for row in rows:row['group_id']=row['event_id']
    records=write(tmp_path/'reference-records.jsonl','\n'.join(json.dumps(x) for x in rows)+'\n')
    spec['task']={'contract':str(folder/'contract.json'),'records':records['path']}
    sp=write(tmp_path/'reference-study.json',spec)
    c['operations'][0]['study']=sp;c['operations'][0]['state']['fresh']=location(sp,'/task')
    difference=write(tmp_path/'difference.json',{'law':'Separate supplied source changes only grouping; comparison asks for conditional covariance difference, not identical numerical replay.'})
    c['operations'][0]['differences']=[location(difference,'/law')]
    c['reference']['sources']=[records];c['reference']['points']=[records]
    cp=write(tmp_path/'independent-check.json',c)
    prepared=fresh.prepare_replication_request(root,seed['report'],'square',tmp_path/'prepared',check_contract_pin=cp)
    fresh_run(seed,tmp_path,root,prepared)
    bound=fresh.prepare_comparison(root,prepared['request'],tmp_path/'comp')
    result=comparison.calculate(read_json(bound['study']['path'])['task'],tmp_path/'comp')
    assert result['decision']=='worse' and result['cells'][0]['gain_interval']==[-4.,-4.]
    assert result['complete_original_cell_denominator']==['one'] and not bound['replication_accepted']


def test_legacy_scientific_dependency_limit_is_not_bypassed(tmp_path):
    rule=write(tmp_path/'legacy-rule.json',{'schema_version':1,'metric':'score','unit':'1','direction':'maximize',
        'min_gain':0.,'tolerance':0.,'uncertainty':'deterministic','reduction':'all_cells'})
    a=write(tmp_path/'operand.json',{'value':1,'quality':True})
    operand={'source':a,'value_pointer':'/value','interval_pointer':None,'quality_pointer':'/quality'}
    request={'schema_version':1,'protocol_sha256':'1'*64,'comparison_id':'legacy','rule':rule,
        'cells':[{'id':'all','metric':'score','unit':'1','exposure':'adaptive_full','left':operand,'right':operand}],
        'dependencies':[a]*129}
    task={'schema_version':1,'request':write(tmp_path/'legacy.json',request)}
    with pytest.raises(ValueError,match='dependencies'):comparison.calculate(task,tmp_path)
    request['dependencies']=[];task['request']=write(tmp_path/'legacy-small.json',request)
    assert comparison.calculate(task,tmp_path)['decision']=='equivalent'


@pytest.mark.parametrize('change',['bool','max-files','max-metadata','unknown-key'])
def test_explicit_operational_capacity_is_closed_and_never_truncated(seed,tmp_path,change):
    root,c,cp=case(seed,tmp_path)
    limits={'max_files':20000,'max_bytes':16*1024**3,'max_metadata_bytes':16*1024**2}
    if change=='bool':limits['max_files']=True
    elif change=='max-files':limits['max_files']=1
    elif change=='max-metadata':limits['max_metadata_bytes']=1
    else:limits['automatic_raise']=True
    c['custody_limits']=limits;cp=write(tmp_path/'bounded-check.json',c)
    before=cycle._load(root)[1]['sha256']
    with pytest.raises(ValueError):fresh.prepare_replication_request(root,seed['report'],'square',tmp_path/'held',check_contract_pin=cp)
    assert cycle._load(root)[1]['sha256']==before and not (tmp_path/'held').exists()


def test_explicit_capacity_retains_same_complete_custody_and_no_authority(seed,tmp_path):
    root,c,cp=case(seed,tmp_path)
    c['custody_limits']={'max_files':20000,'max_bytes':16*1024**3,'max_metadata_bytes':16*1024**2}
    cp=write(tmp_path/'bounded-check.json',c)
    prepared=fresh.prepare_replication_request(root,seed['report'],'square',tmp_path/'prepared',check_contract_pin=cp)
    document=read_json(prepared['request']['path'])
    assert document['custody_limits']==c['custody_limits']
    assert {p['path'] for p in document['inputs']}>= {seed['report']['path'],cp['path'],seed['experiment']['study']['path']}
    assert len({p['path'] for p in document['inputs']})==len(document['inputs'])
    fresh.design_prepared(root,prepared['request'],experiment_id='replicated')
    assert not prepared['execution_authorized'] and not prepared['replication_accepted']


def test_prospective_exposure_must_bind_exact_whole_source_population(seed,tmp_path):
    root,c,cp=case(seed,tmp_path)
    manifest=write(tmp_path/'false-exposure.json',{'kind':'research_execution_input_exposure',
        'study':seed['experiment']['study'],'inputs':[],
        'reason':'Synthetic omission is forbidden, not a blinding guarantee.',
        'whole_worker_custody_retained':True,'OS_blinding_enforced':False})
    c['operations'][0]['input_exposure']=manifest;cp=write(tmp_path/'exposure-check.json',c)
    with pytest.raises(ValueError,match='all execution dependencies'):fresh.prepare_replication_request(root,seed['report'],'square',tmp_path/'held',check_contract_pin=cp)


def test_ending_reread_does_not_miss_earlier_dependency_changed_later(tmp_path,monkeypatch):
    a=write(tmp_path/'a.json',{'x':1});z=write(tmp_path/'z.json',{'x':2})
    observed=fresh._Consumed();fresh._pins([a,z],tmp_path,observed)
    real=fresh._dependency
    def late(pin,base,consumed):
        answer=real(pin,base,consumed)
        if pin['path']==z['path']:Path(a['path']).write_text('changed earlier observed leaf\n')
        return answer
    monkeypatch.setattr(fresh,'_dependency',late)
    with pytest.raises(ValueError,match='ending observation'):fresh._ending(observed)


def test_absent_capacity_preserves_common_legacy_policy(tmp_path):
    observed=fresh._Consumed()
    assert observed.limits=={'max_files':4096,'max_bytes':16*1024**3,'max_metadata_bytes':2000000}
    pin=write(tmp_path/'small.json',{'value':1})
    fresh._pins([pin,pin],tmp_path,observed);fresh._ending(observed)
    assert len(observed.budget.members)==1 and observed.budget.total_bytes==pin['size']


# FR1 controls use a genuinely classified ORIGINAL study before its first
# ordinary execution. They never attach an invented manifest to completed state.
@pytest.fixture(scope='module')
def classified_seed(tmp_path_factory, seed_domain):
    base=tmp_path_factory.mktemp('classified-replication-original')
    root=base/'cycle';cycle.create(root,campaign(base),base_dir=base, evaluation_harness=True);propose(base,root)
    e=experiment(base,'paired',grouped=True)
    source=Path(e['study']['path']);spec=read_json(source)
    inputs=[cycle._pin(path) for path in science.task_inputs(spec,source.parent)]
    purposes={pin['path']:'execution_dependency' for pin in inputs}
    purposes[str((source.parent/spec['task']['contract']).resolve())]='model_context'
    purposes[str((source.parent/spec['task']['records']).resolve())]='withheld_evaluation'
    e=cycle.bind_input_exposure(e,purposes,base/'original-exposure',base_dir=base,
        reason='Synthetic original source classification: disclose mathematical contract, withhold record payload, keep runtime execution-only. No OS blinding claim.')
    rd=run_one(base,root,e);review_math(rd,root,'paired')
    quantitative=report_request(base,root,rd)
    quantitative['artifact_request']['basis'][0]['path']='context-request.json'
    quantitative['artifact_request']['tools']['study']['path']=str(rd.relative_to(base)/'outputs/attempt-1/result.json')
    qp=write(base/'quantitative-report.json',quantitative)
    text=scientific_report.compose(quantitative,base_dir=base)['report_text']
    report=manuscript_fixture(base/'manuscript')
    result=cycle._pin(rd/'outputs/attempt-1/result.json')
    result_location=location(result,'/quantities/covariance/0/0')
    report['claims'][0].update(statement='The complete supplied two-record grouped covariance is one, conditional on the source grouping.',evidence=[result_location])
    op=report['methods'][0]['operations'][0]
    op.update(description='Evaluate the actual supplied signed-group quantity implementation.',
        code=[located(Path(quantities.__file__),Path(quantities.__file__).read_text())],results=[result_location],
        execution={'rundir':str(rd),'receipt':cycle._load(root)[1]['experiments'][0]['observation']['receipt']},differences=[])
    report['methods'][0]['description']='Actual supplied grouped-weight variance; no physics efficacy is claimed.'
    original=Path(report['manuscript']['path']).read_text()
    original=original.replace('The supplied score is four [1].','The conditional grouped covariance is one [1].')
    original=original.replace('We square the supplied x [1]; no optimization is claimed.','We evaluate complete supplied signed groups [1]; no optimization is claimed.')
    # Retain every character with recomputed literal spans after that honest edit.
    parts=original.splitlines(keepends=True);cursor=0
    for unit,part in zip(report['units'],parts):unit['span']=span(part,cursor);cursor+=len(part)
    for occurrence,unit in zip(report['citations'][0]['occurrences'],report['units'][:2]):
        occurrence['span']=span('[1]',original.index('[1]',unit['span']['start']))
    report['units'].append({'id':'quantities','kind':'other','span':span(text,len(original))})
    report['manuscript']=write(base/'manuscript'/'manuscript.md',original+text)
    report['quantitative_report']={'request':qp,'span':span(text,len(original))}
    rp=write(base/'integrity-request.json',report)
    return {'base':base,'root':root,'experiment':e,'report':rp}



def _classified_comparison(classified_seed,tmp_path):
    root,c,prepared=prepare(classified_seed,tmp_path)
    fresh_run(classified_seed,tmp_path,root,prepared)
    bound=decisions.invoke_extension('replication-comparison',root,
        {'request_pin':prepared['request']},tmp_path/'comp',None,{})
    return root,prepared,bound


def test_FR1_classified_original_reaches_new_comparison_design_and_worker(classified_seed,tmp_path):
    root,prepared,bound=_classified_comparison(classified_seed,tmp_path)
    e=bound['experiment'];manifest=read_json(e['input_exposure']['path'])
    assert manifest['study']==bound['study'] and manifest['study']!=classified_seed['experiment']['study']
    assert e['input_exposure']!=classified_seed['experiment']['input_exposure']
    spec=read_json(bound['study']['path']);state=cycle._load(root)[1]
    dependencies=[cycle._pin(path) for path in science.task_inputs(spec,Path(bound['study']['path']).parent)]
    dependencies=cycle._tool_input_closure(e,dependencies,state['base_dir'],state=state)
    assert cycle._exposure_manifest(e,dependencies,state['base_dir'])==manifest
    original=read_json(classified_seed['experiment']['input_exposure']['path'])
    source_purposes={row['sha256']:row['purpose'] for row in original['inputs']}
    for row in manifest['inputs']:
        assert row['purpose']==source_purposes.get(row['sha256'],'execution_dependency')
    assert any(row['purpose']=='withheld_evaluation' for row in manifest['inputs'])
    generated={bound['comparison']['path'],str((tmp_path/'comp/fresh-outcomes.json').resolve()),
        str((tmp_path/'comp/original-outcomes.json').resolve())}
    assert generated<={row['path'] for row in manifest['inputs'] if row['purpose']=='execution_dependency'}
    presented=[e['input_exposure'],*[{k:row[k] for k in ('path','sha256','size')}
        for row in manifest['inputs'] if row['purpose']=='model_context']]
    cycle._model_input_admission(e,dependencies,presented,state['base_dir'])
    private=next(row for row in manifest['inputs'] if row['purpose']=='withheld_evaluation')
    with pytest.raises(ValueError,match='withheld evaluation'):
        cycle._model_input_admission(e,dependencies,[*presented,{k:private[k] for k in ('path','sha256','size')}],state['base_dir'])
    assert not bound['execution_authorized'] and not bound['replication_accepted']
    cycle.design(root,e);rd=tmp_path/'classified-comparison-run'
    cycle.prepare_experiment(root,e['id'],rd);admit_method(rd)
    science.approve(rd,'Pure classified supplied comparison software control only.',scripted=True)
    assert cycle.run_experiment(root,e['id'])==0,stage_evidence(rd)
    cycle.observe(root,e['id']);review(rd,root,e['id'])
    assert read_json(rd/'outputs/attempt-1/result.json')['decision']=='equivalent'
    assert cycle._load(root)[1]['experiments'][-1]['adjudication']['view']['state']=='accepted'


def test_FR1_old_exposure_cannot_bind_new_comparison_study(classified_seed,tmp_path):
    root,prepared,bound=_classified_comparison(classified_seed,tmp_path)
    e=deepcopy(bound['experiment']);e['input_exposure']=classified_seed['experiment']['input_exposure']
    before=cycle._load(root)[1]['sha256']
    with pytest.raises(ValueError,match='exact prospective study'):cycle.design(root,e)
    assert cycle._load(root)[1]['sha256']==before


def test_FR1_source_private_classification_cannot_be_promoted_by_check_caller(classified_seed,tmp_path):
    root,c,cp=case(classified_seed,tmp_path)
    original=read_json(classified_seed['experiment']['input_exposure']['path'])
    for row in original['inputs']:
        if row['purpose']=='withheld_evaluation':row['purpose']='model_context'
    c['operations'][0]['input_exposure']=write(tmp_path/'unauthorized-disclosure.json',original)
    cp=write(tmp_path/'unauthorized-check.json',c);before=cycle._load(root)[1]['sha256']
    with pytest.raises(ValueError,match='original withheld/execution-only'):
        fresh.prepare_replication_request(root,classified_seed['report'],'square',tmp_path/'held',check_contract_pin=cp)
    assert cycle._load(root)[1]['sha256']==before and not (tmp_path/'held').exists()


def test_FR1_generated_comparison_exposure_cannot_rebaseline_post_write_mutation(classified_seed,tmp_path,monkeypatch):
    root,c,prepared=prepare(classified_seed,tmp_path)
    fresh_run(classified_seed,tmp_path,root,prepared)
    real=fresh._emit;changed=[]
    def mutate(path,value,consumed):
        answer=real(path,value,consumed)
        if value.get('kind')=='research_execution_input_exposure':
            altered=deepcopy(value)
            for row in altered['inputs']:
                if row['purpose']=='withheld_evaluation':row['purpose']='model_context'
            Path(path).write_text(json.dumps(altered,indent=2)+'\n');changed.append(str(path))
        return answer
    monkeypatch.setattr(fresh,'_emit',mutate)
    with pytest.raises(ValueError,match='intended comparison exposure'):
        fresh.prepare_comparison(root,prepared['request'],tmp_path/'comp')
    assert len(changed)==1
