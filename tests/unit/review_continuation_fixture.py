"""Closed prior evidence controls, without old-package imports or external work.

Public science approval, launch capture, execution receipts and review decisions
use the trusted current implementation with an explicitly synthetic old source
population. Popen is a stand-in: these are custody controls, not execution or
provider-readiness evidence.
"""

from method_decision_fixture import admit_method
import copy
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest

from ravel.physics import model_provider_bridge as provider, model_tool_bridge as custody
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
    if getattr(request, 'param', None) == 'awaiting_many':
        for i in range(9730):
            path = package/f'fixtures/f{i:04d}.py'; path.parent.mkdir(exist_ok=True)
            path.write_text('source-bound inert fixture; never imported or executed\n')
        for i in range(3):
            path = package/f'fixtures/empty{i}.py'; path.write_bytes(b'')
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
        science.plan(rd,source); admit_method(rd)
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
            from bound_review import bound_review
            bound_review(rd,role='physics_critic',
                verdict='stop' if state=='stopped' else 'send_back',summary='Synthetic negative control',findings=findings)
        elif state not in ('awaiting_review', 'awaiting_many'):
            # Recorded votes are bound responses of dispatched roles; declared names are advice.
            from bound_review import bound_review
            for role in ('physics_critic','skeptical_verifier','physics_decider'):
                bound_review(rd,role=role,verdict='accept',
                    summary='Synthetic located custody evidence only',claim_scope='provider_readiness')
            assert review.gate_errors(rd,'reuse')==[]
    return SimpleNamespace(root=rd,package=package,record=record,config=config,provider=fr,metadata=metadata)

