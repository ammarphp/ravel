"""Closed prior evidence controls, without old-package imports or external work.

Public science approval, launch capture, execution receipts and review decisions
use the trusted current implementation with an explicitly synthetic old source
population. Popen is a stand-in: these are custody controls, not execution or
provider-readiness evidence.
"""
import copy
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest

from ravel.physics import model_provider_bridge as provider, model_tool_bridge as custody
from ravel.workflow import accepted_prior_science as prior
from ravel.workflow import execution, launch_authorization, physics_review as review, science
from ravel.workflow.state_io import atomic_json, read_json


@pytest.fixture
def closed(tmp_path, monkeypatch, request):
    base = tmp_path.resolve()
    package = base/'old-epoch/src/ravel'
    for name in ('_bootstrap.py', 'workflow/execution.py', 'physics/model_provider_bridge.py'):
        path = package/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('raise AssertionError("old source must never be imported or executed")\n')
    fr = base/'provider'; fr.mkdir()
    for name, text in [('FeynRules.m','synthetic source'),('ToolBox.m','synthetic source'),
                       ('FeynRulesPackage.m','FR$VersionNumber="2.3.49";')]:
        (fr/name).write_text(text)
    kernel = base/'kernel'; kernel.write_text('opaque synthetic executable; never run\n'); kernel.chmod(0o700)
    metadata = base/'metadata'; metadata.write_text('synthetic metadata\n')
    pin = lambda p: {'path':str(p), 'sha256':execution.file_hash(p)}
    manifest = base/'provider-manifest.json'; atomic_json(manifest,custody.source_tree(fr))
    config = base/'provider-config.json'
    atomic_json(config, {'schema_version':1,'operation':'wolfram-feynrules-readiness',
        'source':'Explicit synthetic custody fixture; no native readiness inferred',
        'kernel':pin(kernel),'application_metadata':pin(metadata),
        'provider_tree':{'root':str(fr),'manifest':pin(manifest)},'trusted_provider_source':True,
        'expected_kernel_version':14.3,'expected_provider_version':'2.3.49',
        'existing_installation_license_status':'unverified_no_activation_or_credentials_requested',
        'max_seconds':60,'max_ram_mib':2048})
    policy = {'schema_version':1,'actors':{'proposer':'worker','executor':'worker',
        'physics_critic':'critic','skeptical_verifier':'skeptic','physics_decider':'decider'},
        'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],
        'required_checks':[{'id':'integrity','kind':'integrity'},{'id':'agreement','kind':'scientific'}],
        'claim_scopes':{'provider_readiness':{'checks':['integrity','agreement'],'actions':['delivery','reuse']}}}
    source = base/'spec.json'
    atomic_json(source, {'schema_version':2,'mode':'model-provider-bridge',
        'source':'Synthetic engineering receipt and declared review controls only',
        'assumptions':['No actual kernel, provider, model or scientific execution'],
        'max_seconds':60,'max_attempts':1,'approval_mode':'scripted_yes','task':{'config':str(config)},
        'review_policy':{'schema_version':1,'policy':policy,'correction_contract':{'input_slots':[],'task_fields':[]}}})
    rd = base/'run'
    # Metadata selects an owned artificial file population. No old file is loaded
    # as Python; all calls below execute the currently imported trusted modules.
    with monkeypatch.context() as old:
        old.setattr(execution,'__file__',str(package/'workflow/execution.py'))
        old.setattr(provider,'__file__',str(package/'physics/model_provider_bridge.py'))
        old.setattr(science,'module_command',lambda module,*args:
            [sys.executable,str(package/'_bootstrap.py'),module,*map(str,args)])
        science.plan(rd,source)
        if getattr(request,'param',None)=='legacy_absent_plan_capsule':
            proposal=read_json(rd/science.PLAN);proposal.pop('prepared_runtime')
            atomic_json(rd/science.PLAN,proposal)
            atomic_json(rd/'inputs/checkin1.json',science.make_checkin(
                read_json(rd/science.SPEC),execution.file_hash(rd/science.PLAN),proposal['stages'][0]))
        from method_decision_fixture import admit_method
        admit_method(rd)
        science.approve(rd,'Approve this exact synthetic one-attempt custody envelope',scripted=True)
        token = {'attempt':1,'plan_sha256':execution.file_hash(rd/science.PLAN),'budget_seconds':60,
                 'started_utc':execution.utc_now(),'correction_id':None,'correction_plan_sha256':None}
        atomic_json(rd/'execution_attempt.json',token)
        atomic_json(rd/'logs/science-attempts/00000001.json',token)
        proposal = science.verify_plan(rd,approved=True)
        stage,binding,_ = science._selected(rd,proposal)
        record = execution.begin_attempt(rd,'science',binding,stage['log'])
        context = {'kind':'science-stage','stage':'science','review_action':'bulk',
            'max_seconds':60,'plan_sha256':execution.file_hash(rd/science.PLAN),
            'stage_spec':review._stage_spec(rd,{**stage,'inputs':binding['inputs']})}
        old.setattr(launch_authorization.subprocess,'Popen',lambda *a,**k:SimpleNamespace(pid=731731))
        child = launch_authorization.authorized_popen(rd,'science',stage['command'],context=context)
        record.update(child_pid=child.pid,authorization_receipt=child.ravel_authorization)
        if getattr(request,'param',None)=='legacy_missing_environment':
            record.pop('runtime_environment')
        execution._update(rd,'science',record)
        out = rd/'outputs/attempt-1'
        atomic_json(out/'result.json',{'value':1,'physics_validated':False,'synthetic_custody_fixture':True})
        atomic_json(out/'recipe.json',{'task':read_json(rd/science.EXECUTION_TASK)['task']})
        atomic_json(out/'verification.json',{'passed':True,'scope':'model-provider-bridge',
            'physics_validated':False,'expert_review':False,'result_sha256':execution.file_hash(out/'result.json')})
        atomic_json(out/'checkin2.json',{'schema_version':1,'kind':'checkin2','sections':{
            'waypoint':'Synthetic closed receipt','expectation':'Custody only', 'ask':{'options':['GO','ADJUST']}}})
        (rd/stage['log']).write_text('Synthetic receipt, stand-in Popen; no external execution\n')
        assert execution.finish_attempt(rd,record,0)==0
        atomic_json(rd/'inputs/checks.json',{'schema_version':1,'checks':[
            {'id':name,'status':'pass','attempt_ids':[record['attempt_id']],
             'evidence':[{'path':'outputs/attempt-1/result.json','location':'$.value'}]}
            for name in ('integrity','agreement')]})
        review.open_cycle(rd,effective_settings=[science.EXECUTION_TASK],
                          stage_receipts=[record['attempt_record']],check_results='inputs/checks.json')
        state=getattr(request,'param',None)
        if state in ('send_back','stopped'):
            findings=[] if state=='stopped' else [{'id':'synthetic-defect','summary':'Unresolved synthetic control',
                'evidence':[{'path':'outputs/attempt-1/result.json','location':'$.value'}],
                'check_ids':['agreement'],'required_paths':[],'required_stages':['science']}]
            review.submit_review(rd,role='physics_critic',actor_id='critic',
                verdict='stop' if state=='stopped' else 'send_back',summary='Synthetic negative control',findings=findings)
        elif state!='awaiting_review':
            for role,actor in [('physics_critic','critic'),('skeptical_verifier','skeptic'),('physics_decider','decider')]:
                review.submit_review(rd,role=role,actor_id=actor,verdict='accept',
                    summary='Synthetic located custody evidence only',claim_scope='provider_readiness')
            assert review.gate_errors(rd,'reuse')==[]
    return SimpleNamespace(root=rd,package=package,record=record,config=config,provider=fr,metadata=metadata)


def observe(closed, **kw):
    return prior.accepted(closed.root,claim_scope=kw.get('claim_scope','provider_readiness'),
        mode=kw.get('mode','model-provider-bridge'),attempt_id=kw.get('attempt_id',closed.record['attempt_id']))


def protected(closed):
    return {str(p):execution.file_hash(p) for p in closed.root.rglob('*') if p.is_file()}


def test_public_current_source_refuses_old_launch_but_prior_reuse_preserves_exact_history(closed):
    before = protected(closed)
    with pytest.raises(ValueError,match='inventory changed'):
        science.verify_plan(closed.root,approved=True)
    assert review.gate_errors(closed.root,'reuse')
    result = observe(closed)
    assert result['receipt']==closed.record
    assert result['framework_root']==str(closed.package)
    assert result['historical_runtime']==closed.record['runtime']
    assert result['current_runtime_requalified'] is False and result['execution_authority_granted'] is False
    assert all(Path(p).is_file() for p in result['paths'])
    assert str(closed.root/'logs/authorization/00000001.json') in result['paths']
    assert 'not authenticated' in result['attestation']
    assert protected(closed)==before
    with pytest.raises(ValueError,match='inventory changed'):
        science.verify_plan(closed.root,approved=True)


def test_different_current_environment_does_not_rewrite_historical_runtime(closed,monkeypatch):
    monkeypatch.setenv('OMP_NUM_THREADS','137')
    assert execution.stage_errors(closed.root,'science')
    result=observe(closed)
    assert result['historical_runtime']==closed.record['runtime']
    assert result['current_runtime_requalified'] is False


@pytest.mark.parametrize('closed',['legacy_missing_environment'],indirect=True)
def test_inspectable_legacy_receipt_without_runtime_capsule_cannot_claim_closed_prior_reuse(closed):
    with pytest.raises(ValueError,match='original runtime environment capsule'):observe(closed)


@pytest.mark.parametrize('closed',['awaiting_review','send_back','stopped'],indirect=True)
def test_real_unaccepted_journal_cannot_supply_prior_reuse(closed):
    with pytest.raises(ValueError,match='review does not authorize reuse'):observe(closed)


@pytest.mark.parametrize('changes',[{'attempt_id':'other'},{'claim_scope':'gauge_validity'},{'mode':'model-ward'}])
def test_accepted_claim_cannot_be_relabelled(closed,changes):
    with pytest.raises(ValueError):observe(closed,**changes)


@pytest.mark.parametrize('change',['source','source_member','input','output','extra_output','empty_output',
    'log','policy','approval','token','boolean_attempt','token_time','ledger','launch','blob','head'])
def test_original_bytes_membership_authority_and_evidence_mutations_refuse(closed,change):
    rd=closed.root
    if change=='source':(closed.package/'physics/model_provider_bridge.py').write_text('changed')
    elif change=='source_member':(closed.package/'late.py').write_text('late member')
    elif change=='input':closed.metadata.write_text('changed metadata')
    elif change=='output':atomic_json(rd/'outputs/attempt-1/result.json',{'value':2})
    elif change=='extra_output':(rd/'outputs/attempt-1/extra.txt').write_text('unexpected member')
    elif change=='empty_output':(rd/'outputs/attempt-1/result.json').write_bytes(b'')
    elif change=='log':(rd/closed.record['log']).write_text('changed log')
    elif change=='policy':atomic_json(rd/review.POLICY,{'max_redos':100})
    elif change=='approval':atomic_json(rd/science.APPROVAL,{'later_approval':True})
    elif change in ('token','boolean_attempt','token_time'):
        token=read_json(rd/'execution_attempt.json')
        if change=='token':token['budget_seconds']=600
        elif change=='boolean_attempt':token['attempt']=True
        else:token['started_utc']=read_json(rd/science.APPROVAL)['utc']
        atomic_json(rd/'execution_attempt.json',token);atomic_json(rd/'logs/science-attempts/00000001.json',token)
    elif change=='ledger':
        ledger=read_json(rd/execution.STATE_NAME);ledger['stages']['science']['child_pid']=731732
        atomic_json(rd/execution.STATE_NAME,ledger)
    elif change=='launch':
        (rd/'logs/authorization/00000002.json').unlink()
    elif change=='blob':
        next((rd/review.DIRECTORY/'snapshots').glob('*.blob')).write_text('changed retained evidence')
    else:atomic_json(rd/review.HEAD,{'sequence':0})
    with pytest.raises(ValueError):observe(closed)


def test_same_content_source_alias_and_relocated_run_do_not_substitute_original_paths(closed,tmp_path):
    source=closed.package/'physics/model_provider_bridge.py'
    alternate=tmp_path/'alternate.py';alternate.write_bytes(source.read_bytes())
    source.unlink();source.symlink_to(alternate)
    with pytest.raises(ValueError):observe(closed)


def test_copied_accepted_run_cannot_substitute_original_worker_run_identity(closed,tmp_path):
    duplicate=tmp_path.resolve()/'duplicate'
    shutil.copytree(closed.root,duplicate)
    copied=copy.copy(closed);copied.root=duplicate
    with pytest.raises(ValueError):observe(copied)


def test_ending_source_membership_drift_refuses_before_evidence_authority_returns(closed,monkeypatch):
    create=execution._validation_session
    def session(*a,**kw):
        current=create(*a,**kw);finish=current.finish
        def changed():
            (closed.package/'during-observation.py').write_text('new member at ending boundary')
            return finish()
        current.finish=changed
        return current
    monkeypatch.setattr(execution,'_validation_session',session)
    with pytest.raises(ValueError,match='during validation'):observe(closed)


def test_fresh_next_observation_rechecks_original_source(closed):
    observe(closed)
    (closed.package/'workflow/execution.py').write_text('changed after previous observation')
    with pytest.raises(ValueError):observe(closed)


def test_late_registered_scientific_hold_refuses_prior_reuse_without_overwriting_votes(closed):
    rd=closed.root
    reg,events=review._read(rd);view=review._view(reg,events);cycle=view['cycle']
    old=next(p for p in cycle['snapshots'] if p['path']=='outputs/attempt-1/result.json')
    fresh=rd/'inputs/late.json';atomic_json(fresh,{'synthetic_new_finding':True,'science_calls':0})
    context={'schema_version':1,'kind':'post_acceptance_scientific_finding','run_id':reg['run_id'],
        'cycle_id':cycle['cycle_id'],'cycle_sha256':cycle['sha256'],'claim_scope':'provider_readiness',
        'accepted_review_sha256':[e['sha256'] for e in view['reviews']], 'role':'physics_critic','actor_id':'critic',
        'findings':[{'id':'new-custody-obligation','summary':'Synthetic adverse claim control',
            'check_ids':['agreement'],'accepted_evidence':[{'path':old['path'],'sha256':old['sha256'],'location':'$.value'}],
            'new_evidence':[{'path':'inputs/late.json','sha256':execution.file_hash(fresh),'location':'$.synthetic_new_finding'}]}]}
    target=rd/'inputs/late-context.json';atomic_json(target,context)
    preserved={str(p):p.read_bytes() for p in (rd/review.DIRECTORY/'events').glob('*.json')}
    budget=(rd/'execution_attempt.json').read_bytes()
    review.submit_hold(rd,actor_id='decider',cycle_id=cycle['cycle_id'],claim_scope='provider_readiness',
        summary='Hold this synthetic accepted scope',finding_context=str(target),finding_context_sha256=execution.file_hash(target))
    with pytest.raises(ValueError,match='review does not authorize reuse'):observe(closed)
    assert all(Path(p).read_bytes()==raw for p,raw in preserved.items())
    assert (rd/'execution_attempt.json').read_bytes()==budget


def test_no_process_or_old_source_import_is_needed_for_a_new_observation(closed,monkeypatch):
    monkeypatch.setattr(launch_authorization.subprocess,'Popen',lambda *a,**k:pytest.fail('prior evidence must never launch a process'))
    result=observe(closed)
    assert result['execution_authority_granted'] is False
    assert all('old-epoch' not in str(getattr(module,'__file__','')) for module in list(sys.modules.values()) if module)


@pytest.mark.parametrize('closed',['legacy_absent_plan_capsule'],indirect=True)
def test_legacy_original_plan_without_prepared_capsule_keeps_receipt_requirements(closed):
    assert 'prepared_runtime' not in read_json(closed.root/science.PLAN)
    result=observe(closed)
    assert result['receipt']==closed.record and result['execution_authority_granted'] is False
    assert result['current_runtime_requalified'] is False


def test_prior_capsule_uses_original_binding_without_live_interpreter_rebinding(closed,monkeypatch):
    from ravel.workflow import prepared_runtime as prepared
    plan=read_json(closed.root/science.PLAN);calls=[];validate=prepared.validate
    def recorded(capsule,binding,*,live_interpreter=True):
        calls.append((copy.deepcopy(capsule),copy.deepcopy(binding),live_interpreter))
        return validate(capsule,binding,live_interpreter=live_interpreter)
    monkeypatch.setattr(prepared,'validate',recorded)
    monkeypatch.setattr(prepared,'_interpreter',lambda *a:pytest.fail('historical observation rebinds current Python'))
    monkeypatch.setattr(sys,'executable',sys.executable+'-different-observer-venv')
    monkeypatch.setenv('OMP_NUM_THREADS','777')
    result=observe(closed)
    assert calls==[(plan['prepared_runtime'],plan['stage_binding'],False)]
    assert result['historical_runtime']==closed.record['runtime'] and not result['execution_authority_granted']


@pytest.mark.parametrize('mutation',['runtime_values','fingerprint','source_snapshot','binary_hash'])
def test_retained_capsule_semantics_refuse_even_without_live_reexec(closed,mutation):
    from ravel.workflow import prepared_runtime as prepared
    plan=read_json(closed.root/science.PLAN);capsule=copy.deepcopy(plan['prepared_runtime'])
    if mutation=='runtime_values':capsule['environment']['PATH']='forged selected value'
    elif mutation=='fingerprint':capsule['stage_fingerprint']='0'*64
    elif mutation=='source_snapshot':capsule['source_snapshot_sha256']='0'*64
    else:capsule['interpreter']['sha256']='0'*64
    with pytest.raises(ValueError):prepared.validate(capsule,plan['stage_binding'],live_interpreter=False)
