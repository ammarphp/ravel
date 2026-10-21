"""Connected actual ordinary authority with a synthetic in-child reader only.

No ROOT/Linux/WMS/native fit qualification. Root must admit the real two worker
subprocesses under its observer/supervisor; author has not executed this file.
"""

from method_decision_fixture import admit_method
from copy import deepcopy
import json
import sys
import pytest
from ravel.physics import root_stream as s,root_stream_partitions as p,root_stream_statistics as stats
from ravel.workflow import science,site_workflow
from ravel.workflow.state_io import read_json,atomic_json
from root_stream_fixture import put,pin
from root_partition_ordinary_fixture import prepare_fixture,ordinary,law


def test_real_selected_ordinary_partition_resume_merge_wms_and_statistical_consumer(tmp_path,monkeypatch):
    # The budgets are wall ceilings, not measurements. The merge worker re-validates the plan,
    # the approval and every partition completion before and after it merges, and the master and
    # campaign windows run from the first partition claim through each lifecycle step below.
    # On a busy machine these take minutes, so the ceilings leave that room.
    source=tmp_path/'source';ds,a,cfg,spec,proof=prepare_fixture(source,monkeypatch,seconds=3000,wall_seconds=3600)
    request={'schema_version':1,'specification':spec,'partition_entries':100,'max_partitions':100,
        'grouping':{'kind':'independent_entries','source':proof,'statement':'Pinned synthetic independent original physical entry premise'},
        'owner':{'kind':'research_cycle','cycle':str(source/'cycle')},
        'budget':{'partition_seconds':60,'merge_seconds':600,'max_total_seconds':3000}}
    prepared=p.prepare(request,source,tmp_path/'master');master=prepared['master'];part=prepared['partition_specifications'][0]
    assert len(prepared['partition_specifications'])==1 and prepared['execution_authorized'] is False
    public=s.context(read_json(part['specification']['path'])['task'],source)
    assert public['input_pins']==[] and public['restricted_partition_input_witness']['complete'] is True
    assert len(public['restricted_partition_input_witness']['sha256'])==64
    assert all(token not in json.dumps(public) for token in ('\"start\"','\"stop\"','\"entries\"','completed.jsonl'))
    assert p.resume(master,[],source)['pending_partition_ids']==[part['partition_id']]
    rd=tmp_path/'partition';receipt=ordinary(part['specification'],rd)
    # Complete ordinary child -> promised common bytes -> unchanged final guard.
    common=rd/'outputs/attempt-1';common_path=common/'result.json';original_common=common_path.read_bytes()
    assert original_common==s.encoded(receipt['result'])
    final_guard=s.guard(receipt['result'],common/'root-stream')
    assert final_guard.finish(receipt['result'],common=common) is True
    alternate=(json.dumps(dict(reversed(list(receipt['result'].items()))),indent=2,allow_nan=False)+'\n').encode()
    assert json.loads(alternate)==receipt['result'] and alternate!=original_common
    try:
        common_path.write_bytes(alternate)
        with pytest.raises(ValueError):final_guard.finish(receipt['result'],common=common)
    finally:
        common_path.write_bytes(original_common)
    assert common_path.read_bytes()==original_common
    assert receipt['result']['native_receipt']['external_native_calls']==0
    assert receipt['result']['delivery']['normalization_applied'] is False
    assert receipt['result']['delivery']['complete_original_study'] is False
    completed=p.record(master,part['partition_id'],rd,Path(master['path']).parent/'completed'/(part['partition_id']+'.json'))
    resumed=p.resume(master,[completed],source)
    assert resumed['pending_partition_ids']==[] and resumed['failed_attempt_renewed'] is False
    with pytest.raises(ValueError):p.resume(master,[completed,completed],source)
    # A once-valid record cannot substitute for the actual original succeeded
    # attempt; missing, changed receipt/output/native and source all refuse.
    targets=[rd/'logs/science-attempts/00000001.json',Path(receipt['outputs'][0]['path']),
        Path(read_json(completed['path'])['raw_native']['path']),source/'kernel.py']
    for target in targets:
        old=target.read_bytes();target.write_bytes(b'{}\n')
        with pytest.raises((ValueError,OSError,KeyError,TypeError)):p.resume(master,[completed],source)
        target.write_bytes(old)
    assert p.resume(master,[completed],source)['pending_partition_ids']==[]
    merge=p.merge_specification(master,[completed],source,tmp_path/'merge-draft')
    merge_rd=tmp_path/'merge';science.plan(merge_rd,merge['specification']['path']); admit_method(merge_rd)
    _,effective,destination=s.ordinary_plan_destination(merge_rd)
    assert 'output_directory' not in science.verify_plan(merge_rd,approved=False)
    blind=put(source,'export-policy.json',{'schema_version':1,
        'policy':'exclude_signal_region_data_from_model_and_analysis','review_source':proof,'original_domain':a['blinding']['source']})
    exported=site_workflow.export({'schema_version':1,'site_id':'pure-root-control','python':pin(sys.executable),
        'tasks':[{'id':'merge','rundir':str(merge_rd),'plan':pin(merge_rd/science.PLAN),'owner':{'kind':'ordinary'},'depends_on':[]}],
        'audit':{'prompts':[proof],'model_build':'none-pure-software','timestamps':['2026-10-09T00:00:00Z'],
            'token_accounting':proof,'environment':proof,'tracked_skill_sources':[proof],'blinding_policy':blind},
        'wms':{'engine':'snakemake','version':'9.27.0','cores':1,'retries':0}},source,tmp_path/'wms')
    science.approve(merge_rd,'Root-admitted pure merge lifecycle only',scripted=True)
    marker=site_workflow.run_step(exported['manifest']['path'],'merge',exported['manifest']['sha256'])
    assert marker['status']=='delivered' and marker['scientific_acceptance_inferred'] is False
    whole=s.ordinary_delivery(merge_rd);out=merge_rd/destination
    assert whole['result']['native_receipt']['kind']=='ordinary_complete_raw_partition_merge'
    assert whole['result']['delivery']['kind']=='root-stream-public-moments'
    assert whole['result']['delivery']['samples'][0]['quantities']['regions']['values']['nominal']==[400.,200.,800.]
    assert whole['result']['delivery']['samples'][2]['quantities']['regions']['values']['nominal']==[1.,1.]
    roles=put(source,'roles.json',{'schema_version':1,'quantity':'regions','bins':[{'id':n,'role':r} for n,r in
        [('CR','control_region'),('VR','validation_region'),('SR','signal_region')]],'statement':'original fixed roles'})
    design={'schema_version':1,'background':law(proof),'expected_sensitivity':law(proof,True),
        'term_bindings':[{'model':m,'term':t,'sample':sample,'quantity':'regions','bin_ids':bins}
            for m,bins in [('background',['CR']),('expected_sensitivity',['SR','CR'])]
            for t,sample in [('B','background'),('S','signal')]],
        'control_counts':{'sample':'data','quantity':'regions','bin_ids':['CR']},
        'validation':{'sample':'data','quantity':'regions','bin_ids':['VR']},'region_roles':roles,
        'statement':'complete source law; full original MC denominators retained','native_bundle':None}
    evidence=stats.materialize({'schema_version':1,'stream_task':put(source,'merge-task.json',effective['task']),
        'stream_result':pin(out/'root-stream/root-stream-result.json'),'stream_closure':whole['result']['commitment'],
        'design':put(source,'design.json',design)},source,tmp_path/'statistics')
    assert evidence['held_out_validation']=={'bin_ids':['VR'],'counts':[1],'fit_executed':False,'held_out':True}
    expected=read_json(tmp_path/'statistics/expected_sensitivity.json')
    assert all(row['observed'] is None for row in expected['bins'])
    assert expected['terms'][0]['coefficients']==['800','400']
    assert expected['terms'][1]['coefficients']==['750','125']
    assert evidence['sensitivity_computed'] is False
    # Completed WMS reuse needs the same actual attempt, not merely its marker.
    assert site_workflow.verify(exported['manifest']['path'],exported['manifest']['sha256'])['tasks'][0]['id']=='merge'
    token=merge_rd/'logs/science-attempts/00000001.json';old=token.read_bytes();token.unlink()
    with pytest.raises((ValueError,OSError,KeyError)):site_workflow.verify(exported['manifest']['path'],exported['manifest']['sha256'])
    token.write_bytes(old)


from pathlib import Path

@pytest.mark.parametrize('retained',['master.json','partition-plan-closure.json','merge-plan-closure.json'])
def test_private_partition_machine_namespace_and_provenance_copy_never_enter_model_context(tmp_path,retained):
    from ravel.workflow.agent_host import AgentHost,HostFailure
    namespace=tmp_path/'master';namespace.mkdir();(namespace/retained).write_bytes(b'{}\n')
    original=namespace/'completed.jsonl';original.write_bytes(b'{"sample":"data","start":0,"stop":9}\n')
    clone=tmp_path/'renamed-note.md';clone.write_bytes(original.read_bytes())
    with pytest.raises(ValueError):s.model_artifact_source(original,pin(original)['sha256'])
    with pytest.raises(ValueError):s.model_input_text(clone.read_text(),source_path=original,source_sha256=pin(original)['sha256'])
    with pytest.raises(HostFailure):AgentHost()._context({'packet':None,'role':'lead'},{'request_id':'pure'},
        {'intervals':(original,pin(original)['sha256'])})


def test_never_run_caller_pass_record_is_not_persisted_completion(tmp_path,monkeypatch):
    source=tmp_path/'source';ds,a,cfg,spec,proof=prepare_fixture(source,monkeypatch)
    prepared=p.prepare({'schema_version':1,'specification':spec,'partition_entries':100,'max_partitions':100,
        'grouping':{'kind':'independent_entries','source':proof,'statement':'Synthetic premise'},
        'owner':{'kind':'research_cycle','cycle':str(source/'cycle')},
        'budget':{'partition_seconds':20,'merge_seconds':20,'max_total_seconds':40}},source,tmp_path/'master')
    part=prepared['partition_specifications'][0];rd=tmp_path/'not-run';science.plan(rd,part['specification']['path']); admit_method(rd)
    with pytest.raises((ValueError,OSError,KeyError)):
        p.record(prepared['master'],part['partition_id'],rd,tmp_path/'master/completed'/ (part['partition_id']+'.json'))
    assert not (rd/'execution_attempt.json').exists()


@pytest.mark.parametrize('kind',['physical-event-groups','root-stream-partition-master','root-stream-partition-moments',
    'root-stream-ordinary-partition-completion','root-stream-private-partition-plan','root-stream-private-merge-plan'])
def test_typed_machine_group_and_completion_records_do_not_require_data_kind_to_refuse(kind):
    with pytest.raises(ValueError):s.model_input_text(json.dumps({'schema_version':1,'kind':kind,'groups':
        [{'id':'original','sample':'data','spans':[{'member':'data_file','start':0,'stop':99}]}]}))


# Successor controls are additions; the original 48 prospective identities and
# their mathematical/scientific assertions remain present.
def partition_request(source,spec,proof,budget=None):
    return {'schema_version':1,'specification':spec,'partition_entries':100,'max_partitions':100,
        'grouping':{'kind':'independent_entries','source':proof,'statement':'Pinned synthetic original event premise'},
        'owner':{'kind':'research_cycle','cycle':str(source/'cycle')},
        'budget':budget or {'partition_seconds':20,'merge_seconds':20,'max_total_seconds':40}}


def test_relative_original_configuration_uses_actual_specification_parent(tmp_path,monkeypatch):
    source=tmp_path/'nested-source';ds,a,cfg,spec,proof=prepare_fixture(source,monkeypatch)
    original=read_json(spec['path']);original['task']['config']['path']='config.json'
    relative=put(source,'relative-spec.json',original)
    request=partition_request(source,relative,proof)
    prepared=p.prepare(request,tmp_path,tmp_path/'master')
    master=p.read_master(prepared['master'],tmp_path)
    assert master['base_config']['path']==str(source/'config.json')
    assert master['base_spec']['path']==relative['path']
    assert master['dataset_sha256']==s.core.digest(ds)
    assert p.resume(prepared['master'],[],tmp_path)['charged_attempt_seconds']==0


def test_same_original_master_cannot_renew_allocation_in_a_fresh_directory(tmp_path,monkeypatch):
    from ravel.workflow import research_cycle as cycle
    source=tmp_path/'source';ds,a,cfg,spec,proof=prepare_fixture(source,monkeypatch)
    request=partition_request(source,spec,proof);p.prepare(request,source,tmp_path/'first')
    with pytest.raises(ValueError,match='reservation cannot be reset or repeated'):
        p.prepare(request,source,tmp_path/'second')
    _,state=cycle._load(source/'cycle')
    rows=[r for r in state['resource_ledger'] if r['id'].startswith('root-stream-master:')]
    assert len(rows)==1 and rows[0]['ceiling']=={'calls':0,'output_tokens':0,'wall_seconds':40,'native_attempts':2}


@pytest.mark.parametrize('retained',['failed','missing_execution','unknown_terminal'])
def test_failed_or_unknown_attempt_spend_survives_resume_and_separate_rundir(tmp_path,monkeypatch,retained):
    from ravel.workflow import research_cycle as cycle
    source=tmp_path/'source';ds,a,cfg,spec,proof=prepare_fixture(source,monkeypatch,fail_reader=True)
    prepared=p.prepare(partition_request(source,spec,proof),source,tmp_path/'master')
    part=prepared['partition_specifications'][0];rd=tmp_path/'attempt-a'
    science.plan(rd,part['specification']['path']); admit_method(rd);science.approve(rd,'Synthetic failed reader, not physics approval',scripted=True)
    try:science.run(rd)
    except (ValueError,RuntimeError):pass
    assert science.execution.load_execution(rd)['stages']['science']['status']=='failed'
    ledger=rd/science.execution.STATE_NAME;original=ledger.read_bytes()
    if retained=='missing_execution':ledger.unlink()
    elif retained=='unknown_terminal':ledger.write_bytes(b'{"truncated":true}\n')
    resumed=p.resume(prepared['master'],[],source)
    assert resumed['pending_partition_ids']==[]
    assert resumed['blocked_claimed_partition_ids']==[part['partition_id']]
    assert resumed['charged_attempt_seconds']==20 and resumed['reserved_master_seconds']==40
    ledger.write_bytes(original)
    second=tmp_path/'attempt-b';science.plan(second,part['specification']['path']); admit_method(second)
    science.approve(second,'Synthetic duplicate attempt refusal only',scripted=True)
    try:science.run(second)
    except (ValueError,RuntimeError):pass
    assert science.execution.load_execution(second)['stages']['science']['status']=='failed'
    master=p.read_master(prepared['master'],source);_,state=p.owner_state(master)
    claims=p.master_claims(master,state)
    assert len(claims)==1 and claims[0]['rundir']==str(rd) and claims[0]['seconds']==20
    assert p.resume(prepared['master'],[],source)['failed_attempt_renewed'] is False


def test_wms_rejects_same_master_partition_with_distinct_task_ids_and_rundirs(tmp_path,monkeypatch):
    source=tmp_path/'source';ds,a,cfg,spec,proof=prepare_fixture(source,monkeypatch)
    prepared=p.prepare(partition_request(source,spec,proof),source,tmp_path/'master')
    part=prepared['partition_specifications'][0];tasks=[]
    for name in ('first','second'):
        rd=tmp_path/name;science.plan(rd,part['specification']['path']); admit_method(rd)
        tasks.append({'id':name,'rundir':str(rd),'plan':pin(rd/science.PLAN),'owner':{'kind':'ordinary'},'depends_on':[]})
    blind=put(source,'export-policy.json',{'schema_version':1,
        'policy':'exclude_signal_region_data_from_model_and_analysis','review_source':proof,'original_domain':a['blinding']['source']})
    request={'schema_version':1,'site_id':'duplicate-refusal','python':pin(sys.executable),'tasks':tasks,
        'audit':{'prompts':[proof],'model_build':'none-pure-software','timestamps':['2026-10-09T00:00:00Z'],
            'token_accounting':proof,'environment':proof,'tracked_skill_sources':[proof],'blinding_policy':blind},
        'wms':{'engine':'snakemake','version':'9.27.0','cores':1,'retries':0}}
    with pytest.raises(ValueError,match='duplicate original master partition/merge dispatch'):
        site_workflow.export(request,source,tmp_path/'wms')
    assert not (tmp_path/'wms').exists()


def test_missing_or_changed_original_aggregate_owner_refuses_before_dispatch(tmp_path,monkeypatch):
    source=tmp_path/'source';ds,a,cfg,spec,proof=prepare_fixture(source,monkeypatch)
    prepared=p.prepare(partition_request(source,spec,proof),source,tmp_path/'master')
    head=source/'cycle/head.json';original=head.read_bytes();head.unlink()
    with pytest.raises((ValueError,OSError,KeyError)):p.resume(prepared['master'],[],source)
    head.write_bytes(original)
    assert p.resume(prepared['master'],[],source)['pending_partition_ids']


def test_complete_master_over_128_tasks_uses_typed_claim_capacity_not_role_revision_cap(tmp_path,monkeypatch):
    from ravel.workflow import research_cycle as cycle
    from root_partition_ordinary_fixture import contract
    source=tmp_path/'source';ds,a,cfg,spec,proof=prepare_fixture(source,monkeypatch)
    sample=ds['samples'][0];sample['members'][0]['entries']=130
    original=read_json(sample['normalization']['original_population']['path']);original['members'][0]['entries']=130
    sample['normalization']['original_population']=put(source,'large-original.json',original)
    normalization=read_json(sample['normalization']['source']['path'])
    normalization['original_population_sha256']=sample['normalization']['original_population']['sha256']
    sample['normalization']['source']=put(source,'large-normalization.json',normalization)
    ds['membership_authority']=put(source,'large-members.json',{'schema_version':1,'samples':ds['samples']})
    cfg['dataset']=put(source,'large-dataset.json',ds);cfg['limits'].update(max_seconds=600,max_chunks=1000)
    original_spec=read_json(spec['path']);original_spec['task']['config']=put(source,'large-config.json',cfg);original_spec['max_seconds']=600
    large_spec=put(source,'large-specification.json',original_spec)
    owner=contract(source);owner['budget'].update(wall_seconds=1000,native_attempts=1000)
    cycle.create(source/'large-cycle',owner,base_dir=source, evaluation_harness=True)
    request=partition_request(source,large_spec,proof);request.update(partition_entries=1,max_partitions=200,
        owner={'kind':'research_cycle','cycle':str(source/'large-cycle')},
        budget={'partition_seconds':2,'merge_seconds':2,'max_total_seconds':400})
    prepared=p.prepare(request,source,tmp_path/'large-master');master=p.read_master(prepared['master'],source)
    assert len(master['partitions'])==137 and len(prepared['partition_specifications'])==137
    assert master['owner']['attempt_journal']['capacity']==138
    _,state=p.owner_state(master)
    from ravel.workflow import research_history
    # Partition attempts keep their own journal; the campaign journal keeps at least the former bound.
    assert state['revision']==1 and research_history.capacity(state)>=research_history.LEGACY_REVISIONS
    assert p.master_claims(master,state)==[]
    assert state['resource_ledger'][0]['ceiling']['native_attempts']==138
    assert p.resume(prepared['master'],[],source)['pending_partition_ids']==[row['id'] for row in master['partitions']]


@pytest.mark.parametrize('fault',['missing_head','missing_record','head_rollback','bad_parent','unfinished_publication'])
def test_original_attempt_journal_refuses_missing_rollback_and_broken_or_unknown_publication(tmp_path,monkeypatch,fault):
    source=tmp_path/'source';ds,a,cfg,spec,proof=prepare_fixture(source,monkeypatch)
    prepared=p.prepare(partition_request(source,spec,proof),source,tmp_path/'master')
    part=prepared['partition_specifications'][0];rd=tmp_path/'actual';ordinary(part['specification'],rd)
    master=p.read_master(prepared['master'],source);_,state=p.owner_state(master)
    directory=Path(master['owner']['attempt_journal']['directory']);head=directory/'head.json';record=directory/'history/00001.json'
    old_head=head.read_bytes();old_record=record.read_bytes()
    if fault=='missing_head':head.unlink()
    elif fault=='missing_record':record.unlink()
    elif fault=='head_rollback':atomic_json(head,pin(directory/'history/00000.json'))
    elif fault=='bad_parent':
        value=read_json(record);value['parent']['sha256']='0'*64;atomic_json(record,value);atomic_json(head,pin(record))
    else:(directory/'history/00002.json').write_bytes(old_record)
    with pytest.raises((ValueError,OSError,KeyError)):p.resume(prepared['master'],[],source)
    head.write_bytes(old_head);record.write_bytes(old_record)
    if fault=='unfinished_publication':(directory/'history/00002.json').unlink()
    resumed=p.resume(prepared['master'],[],source)
    assert resumed['blocked_claimed_partition_ids']==[part['partition_id']]
    assert resumed['charged_attempt_seconds']==20 and resumed['failed_attempt_renewed'] is False



def test_original_attempt_claim_namespace_and_provenance_copy_remain_machine_private(tmp_path):
    directory=tmp_path/'cycle/root-stream-attempts/original';history=directory/'history';history.mkdir(parents=True)
    claim=history/'00001.json';claim.write_text('{"schema_version":1,"kind":"root-stream-master-attempt-claim","claim":{"task_id":"data-group"}}\n')
    copied=tmp_path/'role-note.md';copied.write_bytes(claim.read_bytes())
    with pytest.raises(ValueError):s.model_artifact_source(claim,pin(claim)['sha256'])
    with pytest.raises(ValueError):s.model_input_text(copied.read_text(),source_path=claim,source_sha256=pin(claim)['sha256'])
    for kind in ('root-stream-master-attempt-genesis','root-stream-master-attempt-claim'):
        with pytest.raises(ValueError):s.model_input_text(json.dumps({'schema_version':1,'kind':kind}))
