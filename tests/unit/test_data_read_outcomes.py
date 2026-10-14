"""Authored UNRUN software controls; synthetic ROOT readers are explicitly inert.

Ordinary plan/verify is genuine; effect authorization/native responses and the
actual completed-attempt reader are substituted only in the named effect tests.
No fixture claims observed provenance, native qualification or physics validity.
"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import pytest
from ravel.physics import root_stream as stream, root_stream_core as core
from ravel.workflow import data_read_outcomes as reads, scientific_context as context
from ravel.workflow import research_tools as tools, science, execution
from root_stream_fixture import population, put, pin, accumulate
from test_root_stream import native_fixture
from test_scientific_context import request as context_request, attempt
from test_science_capability_integration import specification


@pytest.fixture(autouse=True)
def no_native_or_provider(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError('no native/provider/process allowed')
    monkeypatch.setattr(subprocess,'Popen',deny)
    monkeypatch.setattr(execution,'runtime_context',lambda:{'inert_software_control':True,
        'environment_sha256':execution.digest(execution.runtime_environment())})


def prepared(base, *, roles=None, missing=None):
    ds,a,cfg,task,proof=population(base)
    rows=[]
    for sample in ds['samples']:
        for member in sample['members']:
            rows.append({'sample':sample['id'],'member':member['id'],
                'role':(roles or {}).get(sample['id'],'software_fixture'),
                'availability':'missing' if sample['id']==missing else 'supplied',
                'acquisition_source':'Explicit software fixture, never detector observations',
                'version':'authored fixture v1','identity_authority':member['checksum']['authority'],
                'provenance':[proof]})
    authority=put(base,'acquisition.json',{'schema_version':1,'kind':'data-acquisition-source-authority',
        'original_goal_sha256':a['original_goal']['sha256'],'sources':rows})
    preparation=reads.prepare(task,authority,base,base/'prepared')
    enriched=core.strict(Path(preparation['task']['path']).read_bytes())
    cap=core.Capture();contract,lineage=reads.bound_contract(preparation['read_contract'],enriched,cfg,ds,a,base,cap);cap.finish()
    return ds,a,cfg,enriched,preparation,contract,lineage,authority


def emitted(parts,coverage, *, succeeded=True,current=True):
    ds,a,cfg,task,prep,contract,lineage,_=parts
    return reads.emit(prep['read_contract'],contract,lineage,cfg,ds,a,coverage=coverage,
        reader_succeeded=succeeded,source_custody_current=current,
        reader_binding={'explicit_inert_record':True},parents=[])


def request_for(base, prep, *, purpose='original_quantity'):
    value=context_request(base)
    q=value['requested_quantities'][0]
    q.update(id='regions',artifact='root-result',pointer='/read_summary/outcome',
        check={'kind':'exact','value':'read_complete'},meaning='Original complete source-bound ROOT quantity')
    q['read_requirement']=deepcopy(prep['read_requirements']['regions'])
    q['read_requirement']['purpose']=purpose
    if purpose=='partial_diagnostic':q.update(pointer='/read_summary/subset_renormalized',check={'kind':'exact','value':False})
    value['compatibility_groups'][0]['artifacts']=['root-result']
    return value


def effect_result(base,monkeypatch, *, failure=False):
    parts=prepared(base);ds,a,cfg,task,prep,_,_,_=parts
    rd=base/'ordinary';rd.mkdir();put(rd,science.PLAN,{'inert_authorization':True})
    output=rd/'outputs';output.mkdir()
    plan={'max_seconds':cfg['limits']['max_seconds'],'output_directory':'outputs'}
    monkeypatch.setattr(stream,'_approved',lambda *args:(rd,plan))
    from ravel.physics import reinterpret_db
    def native(argv,native_dir,limits):
        if failure:
            coverage=[{'sample':'background','member':'background_file','start':0,'stop':2}]
            (native_dir/'completed-intervals.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in coverage))
            raise ValueError('inert reader failed after first signed chunk')
        full=native_fixture(ds,a,cfg,accumulate(ds,a,cfg['limits'],2))
        stream.write_new(native_dir/'native-result.json',full)
        return {'inert_native_receipt':True}
    monkeypatch.setattr(reinterpret_db,'execute_native',native)
    result=stream.run(task,base,output/'root-stream')
    result_pin=stream.write_new(output/'result.json',result)
    return parts,result,result_pin,output


def test_D01_complete_population_roles_units_and_all_requested_quantities(tmp_path):
    parts=prepared(tmp_path,roles={'background':'supplied_mc','signal':'generated_simulation','data':'observed'})
    full=accumulate(parts[0],parts[1],parts[2]['limits'],2)
    record=emitted(parts,full['coverage'])
    assert record['outcome']=='read_complete'
    assert [p['role'] for p in record['population']]==['supplied_mc','generated_simulation','observed']
    assert sum(p['expected_entries'] for p in record['population'])==12
    assert record['requested_quantities']==[{'id':'regions','outcome':'read_complete','state':'resolved',
        'reason':None,'contract':parts[1]['quantities'][0]['contract']}]
    assert record['representation']['branch_contract']==parts[1]['branch_contract']
    assert record['physics_validated'] is False


@pytest.mark.parametrize('role',['observed','supplied_mc','generated_simulation','calibration','software_fixture'])
def test_original_role_is_retained_not_detector_truth(tmp_path,role):
    sample='data' if role=='observed' else 'background'
    parts=prepared(tmp_path,roles={sample:role})
    record=emitted(parts,accumulate(parts[0],parts[1],parts[2]['limits'],2)['coverage'])
    assert next(r for r in record['population'] if r['sample']==sample)['role']==role
    assert 'not actor authentication or detector truth' in record['limits'][0]


@pytest.mark.parametrize('sample,role',[('background','observed'),('data','supplied_mc'),('data','generated_simulation')])
def test_original_sample_kind_cannot_be_relabelled(tmp_path,sample,role):
    with pytest.raises(ValueError):prepared(tmp_path,roles={sample:role})
    assert not (tmp_path/'prepared').exists()


@pytest.mark.parametrize('fault',['missing','reordered','duplicate','wrong_authority','no_provenance','goal'])
def test_complete_original_acquisition_roster_required(tmp_path,fault):
    parts=prepared(tmp_path);source=core.strict(Path(parts[7]['path']).read_bytes())
    if fault=='missing':source['sources'].pop()
    if fault=='reordered':source['sources'].reverse()
    if fault=='duplicate':source['sources'][1]=deepcopy(source['sources'][0])
    if fault=='wrong_authority':source['sources'][0]['identity_authority']=parts[4]['read_contract']
    if fault=='no_provenance':source['sources'][0]['provenance']=[]
    if fault=='goal':source['original_goal_sha256']='0'*64
    bad=put(tmp_path,'bad-authority.json',source)
    with pytest.raises(ValueError):reads.prepare({'config':parts[3]['config']},bad,tmp_path,tmp_path/'refused')
    assert not (tmp_path/'refused').exists()


def test_D03_missing_observations_remain_unresolved_separate_simulation(tmp_path):
    parts=prepared(tmp_path,roles={'data':'observed','signal':'generated_simulation'},missing='data')
    prep=parts[4]
    assert prep['acquisition_state']=='acquisition_missing' and not prep['acquisitions_available']
    assert prep['original_requested_quantities'][0]['state']=='unresolved'
    record=emitted(parts,[],succeeded=False)
    data=next(row for row in record['population'] if row['sample']=='data')
    assert data['outcome']=='acquisition_missing' and data['remaining_interval']==[0,4]
    assert next(row for row in record['population'] if row['sample']=='signal')['role']=='generated_simulation'
    assert record['synthetic_substitution'] is False and record['requested_quantities'][0]['state']=='unresolved'


def test_D04_failed_shard_signed_original_denominator_never_subset_renormalized(tmp_path):
    parts=prepared(tmp_path)
    coverage=[{'sample':'background','member':'background_file','start':0,'stop':3}]
    record=emitted(parts,coverage,succeeded=False)
    assert record['outcome']=='read_partial' and len(record['population'])==3
    assert [row['attempted_entries'] for row in record['population']]==[3,0,0]
    assert [row['remaining_interval'] for row in record['population']]==[[3,5],[0,3],[0,4]]
    assert record['normalization'][0]['normalization']['sum_weights']==10
    assert record['normalization'][0]['weight_contract']==parts[1]['weight_contract']
    assert record['subset_renormalized'] is False
    # Independent signed raw population prefix includes negative and zero weights.
    assert [2,-1,0]==[row[0] for row in __import__('root_stream_fixture').event_population()['background'][:3]]
    assert 'values' not in record and 'covariance' not in record


@pytest.mark.parametrize('coverage',[
    [{'sample':'foreign','member':'background_file','start':0,'stop':1}],
    [{'sample':'background','member':'background_file','start':1,'stop':2}],
    [{'sample':'background','member':'background_file','start':0,'stop':2}]*2,
    [{'sample':'background','member':'background_file','start':0,'stop':6}],
    [{'sample':'signal','member':'signal_file','start':0,'stop':2}],
])
def test_interval_population_cannot_be_completed_by_renumbering(tmp_path,coverage):
    with pytest.raises(ValueError):emitted(prepared(tmp_path),coverage)


def test_D05_same_basename_changed_source_refuses_before_effect(tmp_path):
    parts=prepared(tmp_path)
    Path(parts[7]['path']).write_text('{}\n')
    with pytest.raises(ValueError):stream.context(parts[3],tmp_path)


def test_unapproved_reader_never_creates_output_or_attempt(tmp_path):
    parts=prepared(tmp_path)
    with pytest.raises(ValueError,match='approved ordinary'):stream.run(parts[3],tmp_path,tmp_path/'run')
    assert not (tmp_path/'run').exists()


def test_public_summary_restricts_data_entries_and_full_read_record(tmp_path):
    parts=prepared(tmp_path);record=emitted(parts,accumulate(parts[0],parts[1],parts[2]['limits'],2)['coverage'])
    summary=reads.public_summary(record)
    assert not any(name in json.dumps(summary) for name in ('expected_entries','attempted_intervals','guid-data','remaining_interval'))
    assert stream.model_input_text(json.dumps(summary))==json.dumps(summary)
    with pytest.raises(ValueError,match='restricted machine'):stream.model_input_text(json.dumps(record))


@pytest.mark.parametrize('failure',[False,True])
def test_connected_existing_root_reader_guard_result_and_quantity_context(tmp_path,monkeypatch,failure):
    parts,result,result_pin,output=effect_result(tmp_path,monkeypatch,failure=failure)
    stream.guard(result,output/'root-stream').finish(result,common=output)
    # Only completed-attempt authentication is an explicit inert stand-in here;
    # root.run, durable native ledger, publication guard and context are genuine.
    monkeypatch.setattr(reads,'ordinary_outcome',lambda *args:{'explicit_inert_attempt_reader':True})
    compiled=context.compile_context(request_for(tmp_path,parts[4]),tmp_path)
    returned=tools.data_result_context(put(tmp_path,'context.json',compiled),result_pin,base_dir=tmp_path,
        artifact_id='root-result',attempt_id='actual-reader',question='Which original member was not read?',
        next_experiment=attempt()['next_experiment'])
    measured=returned['scientific_context']['measured_quantities'][0]
    assert measured['passed'] is (not failure)
    assert measured['read_outcome']['outcome']==('read_partial' if failure else 'read_complete')
    assert returned['scientific_context']['quantity_completion'] is (not failure)
    assert not returned['scientific_acceptance']
    machine=core.strict(Path(result['read_outcomes']['path']).read_bytes())
    assert machine['parents'] and len(machine['population'])==3 and not machine['subset_renormalized']
    if failure:
        diagnostic=context.compile_context(request_for(tmp_path,parts[4],purpose='partial_diagnostic'),tmp_path)
        updated=context.apply_step(diagnostic,attempt({'root-result':{k:result_pin[k] for k in ('path','sha256')}}),tmp_path)
        assert updated['quantity_completion']
        assert not updated['measured_quantities'][0]['read_outcome']['original_scientific_obligation_complete']
        assert result['delivery'] is None


def test_D02_same_shape_synthetic_output_cannot_substitute_failed_data(tmp_path):
    parts=prepared(tmp_path);compiled=context.compile_context(request_for(tmp_path,parts[4]),tmp_path)
    fake=put(tmp_path,'synthetic.json',{'read_summary':{'outcome':'read_complete'}})
    with pytest.raises(ValueError,match='actual typed ROOT reader'):
        context.apply_step(compiled,attempt({'root-result':{k:fake[k] for k in ('path','sha256')}}),tmp_path)


@pytest.mark.parametrize('fault',['role','unit','parent','ledger','result','unbound_context'])
def test_D05_D06_connected_source_result_and_role_changes_refuse(tmp_path,monkeypatch,fault):
    parts,result,result_pin,output=effect_result(tmp_path,monkeypatch)
    monkeypatch.setattr(reads,'ordinary_outcome',lambda *args:{'explicit_inert_attempt_reader':True})
    request=request_for(tmp_path,parts[4])
    if fault=='role':request['requested_quantities'][0]['read_requirement']['roles']=['observed']
    if fault=='unbound_context':request['requested_quantities'][0].pop('read_requirement')
    if fault=='unit':
        Path(parts[2]['analysis']['path']).write_text('{}\n')
    if fault in ('parent','ledger','result'):
        target=(Path(parts[7]['path']) if fault=='parent' else
            output/'root-stream/native/native-result.json' if fault=='ledger' else Path(result_pin['path']))
        target.write_text('{}\n')
    with pytest.raises(ValueError):
        compiled=context.compile_context(request,tmp_path)
        context.apply_step(compiled,attempt({'root-result':{k:result_pin[k] for k in ('path','sha256')}}),tmp_path)


def test_default_new_acquisition_prepares_genuine_unapproved_ordinary_plan(tmp_path):
    parts=prepared(tmp_path)
    spec=specification('root-stream',{'config':parts[3]['config']})
    spec['review_policy']['policy']['claim_scopes']={core.SCOPE:{'checks':['integrity'],'actions':['delivery']}}
    req=context_request(tmp_path)
    req['requested_quantities'][0].update(id='regions',artifact='root-result',pointer='/read_summary/outcome',
        check={'kind':'exact','value':'read_complete'})
    req['compatibility_groups'][0]['artifacts']=['root-result']
    result=tools.prepare_data_acquisition(put(tmp_path,'spec.json',spec),parts[7],put(tmp_path,'request.json',req),
        base_dir=tmp_path,output_dir=tmp_path/'acquisition',rundir=tmp_path/'ordinary-plan',quantity_bindings={'regions':'regions'})
    assert science.verify_plan(tmp_path/'ordinary-plan',approved=False)['schema_version']==2
    assert not (tmp_path/'ordinary-plan'/science.APPROVAL).exists()
    assert not (tmp_path/'ordinary-plan'/'execution_attempt.json').exists()
    assert result['reader']['read_contract']
    original=core.strict(Path(result['context_request']['path']).read_bytes())
    assert original['requested_quantities'][0]['read_requirement']['quantity_id']=='regions'
    assert not result['execution_authorized']


def test_legacy_plain_root_task_and_context_contract_unchanged(tmp_path):
    ds,a,cfg,task,_=population(tmp_path)
    assert stream.validate(task)==task
    assert 'read_contract' not in stream.context(task,tmp_path)
    value=context_request(tmp_path)
    assert 'read_requirement' not in context.compile_context(value,tmp_path)['requested_quantities'][0]


@pytest.mark.parametrize('fault',['valid','running','fingerprint','input_snapshot','runtime','launch','succeeded'])
def test_failed_outcome_requires_terminal_actual_admitted_attempt(tmp_path,monkeypatch,fault):
    """Explicit inert ordinary metadata; real terminal-consumer refusal logic."""
    from contextlib import contextmanager
    from types import SimpleNamespace
    from ravel.workflow import launch_authorization
    parts=prepared(tmp_path);rd=tmp_path/'attempt';rd.mkdir()
    plan_pin=put(rd,science.PLAN,{'source':'inert original plan'})
    stage={'outputs':['outputs/attempt-1']}
    record={'command':['inert'],'cwd':str(rd),'inputs':[],'outputs':stage['outputs'],
        'input_snapshot':{},'parents':{},'runtime':{'inert':True},'status':'failed',
        'exit_code':3,'finished_utc':'explicit inert fixture'}
    record['fingerprint']=execution.digest({k:record[k] for k in
        ('command','cwd','inputs','outputs','input_snapshot','parents','runtime')})
    original_binding={'fingerprint':record['fingerprint']}
    if fault=='running':record['status']='running'
    if fault=='succeeded':record['status']='succeeded'
    if fault=='fingerprint':record['command']=['changed']
    if fault=='input_snapshot':record['input_snapshot']={'changed':{}}
    if fault=='runtime':record['runtime']={'changed':True}
    session=SimpleNamespace(runtime={'inert':True},snapshot=lambda *args,**kwargs:{},
        read_document=lambda *args:{'stages':{'science':record}})
    @contextmanager
    def scope(*args):yield session
    monkeypatch.setattr(science,'root',lambda value:rd)
    monkeypatch.setattr(science,'_validation_scope',scope)
    monkeypatch.setattr(science,'verify_plan',lambda *args,**kwargs:{})
    monkeypatch.setattr(science,'_selected',lambda *args,**kwargs:(stage,original_binding,None))
    monkeypatch.setattr(science,'execution_spec',lambda *args,**kwargs:{'mode':'root-stream','task':parts[3]})
    monkeypatch.setattr(launch_authorization,'audit_launches',lambda *args,**kwargs:['refused'] if fault=='launch' else [])
    claimed={'contract':parts[4]['read_contract'],'reader':{'run_directory':str(rd),
        'config':parts[3]['config'],'ordinary_plan':plan_pin,'ordinary_output_directory':stage['outputs'][0]}}
    if fault=='valid':
        result=reads.ordinary_outcome(claimed,{'status':'failed'},rd/stage['outputs'][0])
        assert result['execution_status']=='failed' and not result['scientific_acceptance']
        assert result['failed_output_snapshot_authenticated'] is False
    else:
        with pytest.raises(ValueError):reads.ordinary_outcome(claimed,{'status':'failed'},rd/stage['outputs'][0])


def test_reachable_default_public_prepare_cli_keeps_existing_service(monkeypatch,tmp_path,capsys):
    request=put(tmp_path,'cli.json',{'original_arguments':'explicit inert routing control'})
    calls=[]
    monkeypatch.setattr(tools,'prepare_data_acquisition',lambda **kw:calls.append(kw) or {'unapproved':True})
    assert tools.main(['data-prepare','--request',request['path']])==0
    assert calls==[{'original_arguments':'explicit inert routing control'}]
    assert json.loads(capsys.readouterr().out)=={'unapproved':True}
    assert tools.data_operations()['reader']['entrypoint']=='root_stream.run'
