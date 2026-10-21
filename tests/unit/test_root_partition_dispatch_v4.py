"""Authored/unrun V4 controls using the original real ordinary fake-reader seam.

The source-derived ROOT stream, campaign, plan, approval, registered attempt,
claims and lock boundaries are real APIs. Only the original external reader is
synthetic. No ROOT/site/physics/throughput qualification is inferred.
"""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from ravel.workflow import science,research_cycle as cycle,state_io
from ravel.workflow.state_io import read_json
from ravel.physics import root_stream as stream,root_stream_partitions as partitions
from root_stream_fixture import put,pin
import test_root_partition_campaign as campaign


def staged_campaign(base,monkeypatch,change):
    real_prepare=campaign.prepare_fixture
    def prepare(root,patch,*,fail_reader=False):
        ds,analysis,config,spec,proof=real_prepare(root,patch,fail_reader=fail_reader)
        wrapper=root/'runtime/ordinary_reader.py'
        raw=wrapper.read_text()
        injection='''
from ravel.workflow import research_cycle as cycle
from ravel.physics import root_stream_partitions as partitions
owner=wrapper.parent.parent/'exact-owner'
marker=wrapper.parent.parent/'after-claim.json'
effect_marker=wrapper.parent.parent/'effect-entered.json'
real_runtime=s.runtime
def observed_runtime(value,base,capture):
    result=real_runtime(value,base,capture)
    if value.get('schema_version')!=2:return result
    master=partitions.read_master(value['partitioning']['master'],base)
    _,state=partitions.owner_state(master)
    claims=partitions.master_claims(master,state)
    # verify_worker/task_inputs invokes runtime before any claim, and ending
    # verification invokes it again. Observe only the first postclaim call.
    if not claims or marker.exists():return result
    assert len(claims)==1
    marker.write_text(json.dumps({'task_id':claims[0]['task_id'],'claims':len(claims)}))
    if CHANGE=='premise':
        cycle.revise_premise(owner,'pairing','Real premise revised after claim during runtime staging.',basis=[],reason='Source-only software control')
    return result
s.runtime=observed_runtime
real_reader=reinterpret_db.execute_native
def observed_reader(argv,output,limits):
    if CHANGE=='locked_positive':
        try:
            cycle.revise_premise(owner,'pairing','An effect-time update must not interleave.',basis=[],reason='Source-only lock control')
        except ValueError as error:
            assert 'another process owns' in str(error)
        else:raise AssertionError('final effect admission lock was not held')
    effect_marker.write_text(json.dumps({'entered':True,'kind':'synthetic_reader_only'}))
    return real_reader(argv,output,limits)
reinterpret_db.execute_native=observed_reader
'''
        injection='CHANGE='+repr(change)+'\n'+injection
        needle='from ravel.physics.science_worker import main'
        assert raw.count(needle)==1
        # Modify only the freshly generated fixture before its master is pinned.
        wrapper.write_text(raw.replace(needle,injection+'\n'+needle))
        runtime=root/'runtime'
        assets={p.name:{k:pin(p)[k] for k in ('sha256','size')} for p in runtime.iterdir() if p.is_file()}
        config['runtime']['trees'][0]['manifest']=put(root,'runtime.json',{'schema_version':1,'files':assets})
        cfg=put(root,'config.json',config)
        value=read_json(spec['path']);value['task']['config']=cfg
        return ds,analysis,config,put(root,'spec.json',value),proof
    monkeypatch.setattr(campaign,'prepare_fixture',prepare)
    return campaign.campaign_source(base,monkeypatch)


@pytest.mark.parametrize('change',['premise','locked_positive'])
def test_actual_postclaim_staging_and_effect_serialization(tmp_path,monkeypatch,change):
    source,owner,analysis,proof,prepared=staged_campaign(tmp_path,monkeypatch,change)
    part=prepared['partition_specifications'][0]
    _,rd=campaign.prepared_experiment(tmp_path,owner,part['specification'],'branch')
    result=cycle.run_experiment(owner,'branch')
    observed=read_json(source/'after-claim.json')
    assert observed=={'task_id':part['partition_id'],'claims':1}
    master=partitions.read_master(prepared['master'],source);_,state=partitions.owner_state(master)
    claims=partitions.master_claims(master,state)
    assert len(claims)==1 and claims[0]['task_id']==part['partition_id']
    assert cycle._usage(state)['native_attempts']==2
    if change=='premise':
        assert result!=0 and not (source/'effect-entered.json').exists()
        assert not (rd/'outputs/attempt-1/root-stream/native/native-result.json').exists()
        assert science.execution.load_execution(rd)['stages']['science']['status']=='failed'
        resumed=partitions.resume(prepared['master'],[],source)
        assert resumed['blocked_claimed_partition_ids']==[part['partition_id']]
        assert resumed['charged_attempt_seconds']==20 and resumed['failed_attempt_renewed'] is False
    else:
        assert result==0 and read_json(source/'effect-entered.json')['entered'] is True
        assert stream.ordinary_delivery(rd)['result']['status']=='passed'
        assert science.execution.load_execution(rd)['stages']['science']['status']=='succeeded'
        # The refused interleaving cannot revise the originally admitted premise.
        assert not next(e for e in state['experiments'] if e['id']=='branch').get('applicability_reopened')


@pytest.mark.parametrize('legacy',[False,True])
@pytest.mark.parametrize('route',['direct','stale','campaign'])
def test_actual_canonical_registration_and_legacy_worker_ownership(tmp_path,monkeypatch,legacy,route):
    source,owner,analysis,proof,prepared=campaign.campaign_source(tmp_path,monkeypatch)
    part=prepared['partition_specifications'][0];campaign.design(owner,part['specification'],'branch')
    existing=tmp_path/'existing';existing.mkdir();spelling=existing/'..'/'branch';rd=tmp_path/'branch'
    cycle.prepare_experiment(owner,'branch',spelling)
    from method_decision_fixture import admit_method
    admit_method(spelling)
    _,state=cycle._load(owner);e=next(e for e in state['experiments'] if e['id']=='branch')
    assert e['rundir']==str(rd) and e['plan']['path']==str(rd/science.PLAN)
    if legacy:
        # Exact retained V3 lexical spelling, not a forged approval or plan.
        with state_io.file_lock(owner/'operation.lock',blocking=False):
            _,state=cycle._load(owner)
            next(e for e in state['experiments'] if e['id']=='branch')['rundir']=str(spelling)
            cycle._commit(owner,state,'synthetic_retained_legacy_run_spelling')
    science.approve(spelling,'Synthetic engineering admission, not physics review',scripted=True)
    if route=='stale':
        cycle.revise_premise(owner,'pairing','Changed premise before direct worker.',basis=[],reason='Software source control')
    before_execution=science.execution.load_execution(rd)
    if route=='campaign':
        result=cycle.run_experiment(owner,'branch')
    else:
        # A current bound child cannot dispatch directly before its campaign
        # reserves the actual exposure. Refusal precedes worker execution.
        with pytest.raises(ValueError,match='research dispatch must reserve exposure'):
            science.run(spelling)
    master=partitions.read_master(prepared['master'],source);_,state=partitions.owner_state(master)
    assert cycle._usage(state)['native_attempts']==2
    if route=='campaign':
        assert result==0 and stream.ordinary_delivery(spelling)['result']['status']=='passed'
        assert len(partitions.master_claims(master,state))==1
        assert partitions.master_claims(master,state)[0]['rundir']==str(rd)
    else:
        assert partitions.master_claims(master,state)==[]
        assert science.execution.load_execution(rd)==before_execution
        assert not (rd/'outputs/attempt-1/root-stream/native/native-result.json').exists()
    assert not (existing/'branch').exists()


def test_alias_registration_refuses_before_materialization_or_new_charge(tmp_path,monkeypatch):
    source,owner,analysis,proof,prepared=campaign.campaign_source(tmp_path,monkeypatch)
    part=prepared['partition_specifications'][0];campaign.design(owner,part['specification'],'branch')
    target=tmp_path/'ordinary';target.mkdir();alias=tmp_path/'alias';alias.symlink_to(target,target_is_directory=True)
    _,before=cycle._load(owner)
    with pytest.raises(ValueError,match='ordinary research paths'):
        cycle.prepare_experiment(owner,'branch',alias/'branch')
    _,after=cycle._load(owner)
    assert after['sha256']==before['sha256'] and after['resource_ledger']==before['resource_ledger']
    assert not (target/'branch').exists()


def test_legacy_symlink_owner_cannot_become_standalone(tmp_path,monkeypatch):
    source,owner,analysis,proof,prepared=campaign.campaign_source(tmp_path,monkeypatch)
    part=prepared['partition_specifications'][0]
    _,rd=campaign.prepared_experiment(tmp_path,owner,part['specification'],'branch')
    alias=tmp_path/'legacy-alias';alias.symlink_to(rd,target_is_directory=True)
    with state_io.file_lock(owner/'operation.lock',blocking=False):
        _,state=cycle._load(owner)
        next(e for e in state['experiments'] if e['id']=='branch')['rundir']=str(alias)
        cycle._commit(owner,state,'synthetic_unsafe_legacy_alias')
    before = science.execution.load_execution(rd)
    with pytest.raises(ValueError, match='reserve exposure|symlink'):
        science.run(rd)
    master=partitions.read_master(prepared['master'],source);_,state=partitions.owner_state(master)
    assert partitions.master_claims(master,state)==[]
    assert science.execution.load_execution(rd) == before


def test_duplicate_canonical_owners_refuse_before_standalone_classification(tmp_path,monkeypatch):
    source,owner,analysis,proof,prepared=campaign.campaign_source(tmp_path,monkeypatch)
    part=prepared['partition_specifications'][0]
    _,rd=campaign.prepared_experiment(tmp_path,owner,part['specification'],'branch')
    existing=tmp_path/'existing';existing.mkdir()
    master=partitions.read_master(prepared['master'],source);_,state=partitions.owner_state(master)
    duplicate=deepcopy(state['experiments'][0]);duplicate['id']='second-owner'
    duplicate['rundir']=str(existing/'..'/'branch')
    # A disclosed synthetic state projection isolates the roster-ambiguity
    # refusal; no changed durable state, approval or claim is manufactured.
    projected=deepcopy(state);projected['experiments'].append(duplicate)
    with pytest.raises(ValueError,match='one actual campaign experiment'):
        partitions.campaign_attempt(master,projected,rd)
    assert partitions.master_claims(master,state)==[]
