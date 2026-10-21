"""Prospective actual campaign/WMS paths with the existing synthetic reader only.

Author has not imported/collected/executed these controls. Ordinary source,
plan/approval/registered worker/campaign and aggregate claims are real. No ROOT,
site, model, physics acceptance or sampler result is inferred.
"""
from pathlib import Path
import sys
import pytest
from ravel.workflow import science, research_cycle as cycle, site_workflow, state_io
from ravel.workflow.state_io import read_json
from ravel.physics import root_stream as stream, root_stream_partitions as partitions
from root_stream_fixture import put,pin
from root_partition_ordinary_fixture import prepare_fixture,contract
from test_root_partition_ordinary import partition_request
from stage_evidence_fixture import stage_evidence


def campaign_source(base,monkeypatch,*,failed=False,budget=None,wall_seconds=None):
    # ``budget`` replaces the master's partition, merge and total wall ceilings and ``wall_seconds``
    # the owning campaign's wall budget; the source plan's ceiling follows the master total.
    seconds={} if budget is None else {'seconds':budget['max_total_seconds']}
    source=base/'source';ds,analysis,config,spec,proof=prepare_fixture(source,monkeypatch,fail_reader=failed,**seconds)
    # Exact whole-master reservation fills native budget; duplicate debit would
    # make genuine per-branch preparation unaffordable. No original input drops.
    definition=contract(source);definition['budget']['native_attempts']=2
    if wall_seconds is not None:definition['budget']['wall_seconds']=wall_seconds
    owner=source/'exact-owner';cycle.create(owner,definition,base_dir=source, evaluation_harness=True)
    request=partition_request(source,spec,proof,budget);request['owner']['cycle']=str(owner)
    prepared=partitions.prepare(request,source,base/'master')
    hypotheses=[{'id':'current','statement':'The complete synthetic source delivery may pass.',
        'stream':'speculative','premise_ids':['pairing'],'source_basis':[],'parents':[]}]
    cycle.propose(owner,hypotheses,origin={'kind':'supplied_source','pin':put(source,'hypotheses.json',hypotheses),
        'description':'Synthetic source proposal, no model transport'})
    return source,owner,analysis,proof,prepared


def design(owner,spec,identity,*,parent=None,seconds=None,calls=0):
    value=read_json(spec['path']);seconds=value['max_seconds'] if seconds is None else seconds
    e={'id':identity,'question':'Deliver the original complete synthetic branch without renewed authority.',
        'premise_ids':['pairing'],'parent':parent,'change':'Exact source-bound partition or merge operation.',
        'study':spec,'cost':{'calls':calls,'output_tokens':0,'wall_seconds':seconds,'native_attempts':1},
        'predictions':{'current':'passed'},'observable':{'pointer':'/status','outcomes':{'passed':'passed','failed':'failed'}},
        'context_outputs':{},'acceptance_scope':stream.SCOPE,'exploratory':False}
    cycle.design(owner,e);return e


def prepared_experiment(base,owner,spec,identity,**kwargs):
    e=design(owner,spec,identity,**kwargs);rd=base/identity
    selected=cycle.select(owner);assert next(x for x in selected['designs'] if x['id']==identity)['affordable']
    cycle.prepare_experiment(owner,identity,rd)
    from method_decision_fixture import admit_method
    admit_method(rd)
    science.approve(rd,'Synthetic engineering admission; no native/site/physicist approval',scripted=True)
    return e,rd


def exported(source,analysis,proof,owner,rd,identity,out):
    blind=put(source,'export-policy-'+identity+'.json',{'schema_version':1,
        'policy':'exclude_signal_region_data_from_model_and_analysis','review_source':proof,
        'original_domain':analysis['blinding']['source']})
    return site_workflow.export({'schema_version':1,'site_id':'actual-campaign-control','python':pin(sys.executable),
        'tasks':[{'id':identity,'rundir':str(rd),'plan':pin(rd/science.PLAN),
            'owner':{'kind':'research_cycle','cycle':str(owner),'experiment':identity},'depends_on':[]}],
        'audit':{'prompts':[proof],'model_build':'none-synthetic','timestamps':['2026-10-09T00:00:00Z'],
            'token_accounting':proof,'environment':proof,'tracked_skill_sources':[proof],'blinding_policy':blind},
        'wms':{'engine':'snakemake','version':'9.27.0','cores':1,'retries':0}},source,out)


@pytest.mark.parametrize('route',['campaign','wms'])
def test_actual_same_owner_campaign_partition_merge_and_original_charge(tmp_path,monkeypatch,route):
    # The budgets are wall ceilings, not measurements: the merge worker re-validates the plan, the
    # approval and the partition completion before and after it merges, and the master and campaign
    # windows run from the first partition claim through every step below.
    budget={'partition_seconds':60,'merge_seconds':600,'max_total_seconds':3000}
    source,owner,analysis,proof,prepared=campaign_source(tmp_path,monkeypatch,budget=budget,wall_seconds=3600)
    part=prepared['partition_specifications'][0];_,rd=prepared_experiment(tmp_path,owner,part['specification'],'branch')
    _,before=cycle._load(owner);assert cycle._usage(before)['native_attempts']==2
    extra=next(r for r in before['resource_ledger'] if r['id']=='experiment:branch')
    assert extra['ceiling']=={'calls':0,'output_tokens':0,'wall_seconds':0,'native_attempts':0}
    if route=='campaign':assert cycle.run_experiment(owner,'branch')==0,stage_evidence(rd)
    else:
        wms=exported(source,analysis,proof,owner,rd,'branch',tmp_path/'wms-part')
        assert site_workflow.run_step(wms['manifest']['path'],'branch',wms['manifest']['sha256'])['status']=='delivered'
        assert site_workflow.verify(wms['manifest']['path'],wms['manifest']['sha256'])['tasks'][0]['owner']['kind']=='research_cycle'
    receipt=stream.ordinary_delivery(rd);assert receipt['result']['status']=='passed'
    assert science.execution.load_execution(rd)['stages']['science']['status']=='succeeded'
    master=partitions.read_master(prepared['master'],source);_,state=partitions.owner_state(master)
    claims=partitions.master_claims(master,state);assert len(claims)==1 and claims[0]['rundir']==str(rd)
    assert claims[0]['attempt_id']==science.execution.load_execution(rd)['stages']['science']['attempt_id']
    completed=partitions.record(prepared['master'],part['partition_id'],rd,
        Path(prepared['master']['path']).parent/'completed'/(part['partition_id']+'.json'))
    merge=partitions.merge_specification(prepared['master'],[completed],source,tmp_path/'merge-draft')
    _,mr=prepared_experiment(tmp_path,owner,merge['specification'],'merge')
    if route=='campaign':assert cycle.run_experiment(owner,'merge')==0,stage_evidence(mr)
    else:
        wms=exported(source,analysis,proof,owner,mr,'merge',tmp_path/'wms-merge')
        assert site_workflow.run_step(wms['manifest']['path'],'merge',wms['manifest']['sha256'])['status']=='delivered'
    whole=stream.ordinary_delivery(mr)
    assert whole['result']['delivery']['samples'][0]['quantities']['regions']['values']['nominal']==[400.,200.,800.]
    _,state=partitions.owner_state(master);claims=partitions.master_claims(master,state)
    assert len(claims)==2 and [x['seconds'] for x in claims]==[budget['partition_seconds'],budget['merge_seconds']]
    assert cycle._usage(state)['native_attempts']==2
    assert claims[0]['deadline_epoch']==claims[1]['deadline_epoch']
    assert all(not e.get('adjudication') for e in state['experiments'])
    assert all(row['ceiling']['native_attempts']==0 for row in state['resource_ledger'] if row['id'].startswith('experiment:'))


@pytest.mark.parametrize('route',['campaign','wms'])
@pytest.mark.parametrize('retained',['failed','missing_execution','unknown_execution'])
def test_failed_same_owner_branch_remains_charged_and_cannot_renew(tmp_path,monkeypatch,route,retained):
    source,owner,analysis,proof,prepared=campaign_source(tmp_path,monkeypatch,failed=True)
    part=prepared['partition_specifications'][0];_,rd=prepared_experiment(tmp_path,owner,part['specification'],'failed')
    if route=='campaign':assert cycle.run_experiment(owner,'failed')!=0
    else:
        wms=exported(source,analysis,proof,owner,rd,'failed',tmp_path/'wms')
        with pytest.raises(ValueError):site_workflow.run_step(wms['manifest']['path'],'failed',wms['manifest']['sha256'])
        assert not (tmp_path/'wms/completed/failed.json').exists()
    assert science.execution.load_execution(rd)['stages']['science']['status']=='failed'
    ledger=rd/science.execution.STATE_NAME;original=ledger.read_bytes()
    if retained=='missing_execution':ledger.unlink()
    elif retained=='unknown_execution':ledger.write_bytes(b'{"truncated":true}\n')
    resumed=partitions.resume(prepared['master'],[],source)
    ledger.write_bytes(original)
    assert resumed['blocked_claimed_partition_ids']==[part['partition_id']] and resumed['charged_attempt_seconds']==20
    assert resumed['failed_attempt_renewed'] is False
    _,other=prepared_experiment(tmp_path,owner,part['specification'],'duplicate')
    assert cycle.run_experiment(owner,'duplicate')!=0
    master=partitions.read_master(prepared['master'],source);_,state=partitions.owner_state(master)
    assert len(partitions.master_claims(master,state))==1 and cycle._usage(state)['native_attempts']==2
    assert science.execution.load_execution(other)['stages']['science']['status']=='failed'


@pytest.mark.parametrize('change',['premise','parent','clock','plan','held_lock','direct_worker'])
def test_actual_campaign_admission_failures_do_not_create_partition_claim(tmp_path,monkeypatch,change):
    source,owner,analysis,proof,prepared=campaign_source(tmp_path,monkeypatch)
    part=prepared['partition_specifications'][0]
    if change=='parent':
        design(owner,part['specification'],'unreviewed')
        design(owner,part['specification'],'branch',parent='unreviewed')
        with pytest.raises(ValueError):cycle.prepare_experiment(owner,'branch',tmp_path/'branch')
        assert not (tmp_path/'branch').exists()
    else:
        _,rd=prepared_experiment(tmp_path,owner,part['specification'],'branch')
        if change=='premise':cycle.revise_premise(owner,'pairing','Changed original scientific premise.',basis=[],reason='Source software negative')
        elif change=='clock':
            # Observe actual canonical elapsed campaign clock via its existing
            # clock input seam, preserving the real admission/claim functions.
            with state_io.file_lock(owner/'operation.lock',blocking=False):
                _,state=cycle._load(owner);assert cycle._clock(state,20) is None
                cycle._commit(owner,state,'synthetic_elapsed_clock_boundary')
            deadline=state['timing']['deadline_epoch']
            monkeypatch.setattr(cycle.time,'time',lambda:deadline+1)
        elif change=='plan':(rd/science.PLAN).write_bytes(b'{}\n')
        if change=='held_lock':
            with state_io.file_lock(owner/'operation.lock',blocking=False):
                with pytest.raises(ValueError,match='another process owns'):cycle.run_experiment(owner,'branch')
        elif change=='direct_worker':
            with pytest.raises(ValueError, match='reserve exposure'):
                science.run(rd)
            assert not (rd/'execution_attempt.json').exists()
        else:
            with pytest.raises((ValueError,OSError,KeyError,cycle.OperationalBoundaryError)):cycle.run_experiment(owner,'branch')
        assert not (rd/'outputs/attempt-1/root-stream/native/native-result.json').exists()
    master=partitions.read_master(prepared['master'],source);_,state=partitions.owner_state(master)
    assert partitions.master_claims(master,state)==[]
    assert cycle._usage(state)['native_attempts']==2


def test_declared_overhead_cost_is_separate_from_already_reserved_branch(tmp_path,monkeypatch):
    source,owner,analysis,proof,prepared=campaign_source(tmp_path,monkeypatch)
    part=prepared['partition_specifications'][0];_,rd=prepared_experiment(tmp_path,owner,part['specification'],'extra',seconds=25,calls=2)
    _,state=cycle._load(owner);reservation=next(x for x in state['resource_ledger'] if x['id']=='experiment:extra')
    assert reservation['ceiling']=={'calls':2,'output_tokens':0,'wall_seconds':5,'native_attempts':0}
    assert next(x for x in state['experiments'] if x['id']=='extra')['cost']['wall_seconds']==25
    assert cycle._usage(state)=={'calls':2,'output_tokens':0,'wall_seconds':45,'native_attempts':2}


def test_unrelated_campaign_cannot_adopt_original_master_reservation(tmp_path,monkeypatch):
    source,owner,analysis,proof,prepared=campaign_source(tmp_path,monkeypatch)
    definition=contract(source);other=source/'other-owner';cycle.create(other,definition,base_dir=source, evaluation_harness=True)
    rows=[{'id':'current','statement':'Explicit source rival','stream':'speculative','premise_ids':['pairing'],'source_basis':[],'parents':[]}]
    cycle.propose(other,rows,origin={'kind':'supplied_source','pin':put(source,'other-hypotheses.json',rows),'description':'Source fixture'})
    part=prepared['partition_specifications'][0];design(other,part['specification'],'wrong')
    with pytest.raises(ValueError,match='original aggregate campaign owner'):cycle.prepare_experiment(other,'wrong',tmp_path/'wrong')
    assert not (tmp_path/'wrong').exists()
    master=partitions.read_master(prepared['master'],source);_,state=partitions.owner_state(master)
    assert partitions.master_claims(master,state)==[]


def test_actual_pending_phase_check_remains_a_dispatch_refusal(tmp_path,monkeypatch):
    source,owner,analysis,proof,prepared=campaign_source(tmp_path,monkeypatch)
    part=prepared['partition_specifications'][0]
    design(owner,part['specification'],'audit')
    _,rd=prepared_experiment(tmp_path,owner,part['specification'],'branch')
    master=partitions.read_master(prepared['master'],source);_,state=cycle._load(owner)
    zero={k:0 for k in cycle.VECTORS}
    request={'schema_version':1,'budget':state['contract']['budget'],'usage':cycle._usage(state),
        'checks':[{'id':'scientific-check','cost':zero}],
        'designs':[{'id':e['id'],'construction_cost':e['cost'],'check_ids':[], 'polish_cost':zero} for e in state['experiments']],
        'completed_check_ids':[],'retained_design_ids':[],'mandatory_check_ids':['scientific-check']}
    cycle.configure_phases(owner,put(source,'phase.json',request),
        check_contracts={'scientific-check':{'experiment_id':'audit','required_check_ids':['integrity'],'purpose':'scientific'}},
        preconstruction_checks={'audit':[],'branch':['scientific-check']})
    with pytest.raises(ValueError,match='checking reservation|preconstruction'):cycle.run_experiment(owner,'branch')
    _,state=cycle._load(owner)
    assert partitions.master_claims(master,state)==[] and cycle._usage(state)['native_attempts']==2
    assert state['phase_checks']==[]


def test_worker_rechecks_real_premise_changed_after_parent_lock_handoff(tmp_path,monkeypatch):
    source,owner,analysis,proof,prepared=campaign_source(tmp_path,monkeypatch)
    part=prepared['partition_specifications'][0];_,rd=prepared_experiment(tmp_path,owner,part['specification'],'branch')
    real=science.run;calls=[]
    def handoff(rundir,*,resume=False):
        calls.append(str(rundir))
        cycle.revise_premise(owner,'pairing','Late actual scientific premise change.',basis=[],reason='Software source boundary')
        return real(rundir,resume=resume)
    monkeypatch.setattr(science,'run',handoff)
    assert cycle.run_experiment(owner,'branch')!=0 and calls==[str(rd)]
    master=partitions.read_master(prepared['master'],source);_,state=partitions.owner_state(master)
    assert partitions.master_claims(master,state)==[]
    assert science.execution.load_execution(rd)['stages']['science']['status']=='failed'
