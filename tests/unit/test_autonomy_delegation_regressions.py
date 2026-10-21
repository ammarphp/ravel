"""Authority and recovery regressions; all requests and operator transports are fictional."""
import hashlib
import json
from pathlib import Path

import pytest

from ravel.workflow import operating_mode as mode
from ravel.workflow.approval_authority import AGENT_MARKERS
from ravel.workflow.state_io import atomic_json
from test_operating_mode import operator, set_operator_mode, authorize_environment, authorize_run, initialize_trusted


def test_direct_setter_requires_trusted_operator_record(operator):
    with pytest.raises(ValueError, match='operator'):
        mode.set_mode('autonomous')
    assert not mode.config_path('project').exists()


def test_stripping_all_markers_does_not_authenticate_operator(operator, monkeypatch):
    for name in AGENT_MARKERS:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match='operator'):
        mode.set_mode('autonomous')


def test_injected_environment_cannot_grant_authority(operator, monkeypatch):
    monkeypatch.setenv('RAVEL_OPERATING_MODE', 'autonomous')
    monkeypatch.setenv('RAVEL_AUTONOMY_BOUNDS', json.dumps({**mode.DEFAULT_BOUNDS, 'max_seconds':999999}))
    with pytest.raises(ValueError, match='operator'):
        mode.initialize(operator/'forged', {'prompt':'Inspect a fictional polynomial.'})
    assert not (operator/'forged'/mode.RUN_RECORD).exists()


@pytest.mark.parametrize('statement', [
    'Do not proceed without further approval.',
    'Never continue without further confirmation.',
    'Do not complete the task without asking me for approval.',
    'Do not perform this task without confirmation.',
    'Never execute the task without approval.',
    'Only proceed after my approval.',
    'Wait until I approve before proceeding.',
])
def test_all_explicit_approval_prerequisites_override_defaults(operator, statement):
    # Text interpretation is checked independently of operator authentication.
    assert mode.request_mode(statement)[0]=='physicist-in-the-loop'


@pytest.mark.parametrize('source', ['project','environment'])
@pytest.mark.parametrize('statement', [
    'Do not proceed without further approval.',
    'Never continue without further confirmation.',
    'Do not run autonomously.', 'Never work autonomously.',
    'Do not complete this task autonomously.', 'Never perform this task without further confirmation.',
    'Only proceed after my approval.',
])
def test_approval_prerequisites_override_trusted_defaults(operator, monkeypatch, source, statement):
    if source=='project': set_operator_mode('autonomous')
    else:
        authorize_environment(operator)
        monkeypatch.setenv('RAVEL_OPERATING_MODE','autonomous')
    root=operator/'run'
    value=mode.initialize(root,{'prompt':statement})
    assert value['mode']=='physicist-in-the-loop'
    assert value['source']=='explicit_request'


@pytest.mark.parametrize('damage', ['delete','truncate'])
def test_restrictive_project_cannot_disappear_into_user_fallback(operator, damage):
    set_operator_mode('autonomous',scope='user')
    set_operator_mode('physicist-in-the-loop')
    path=mode.config_path('project')
    if damage=='delete': path.unlink()
    else: path.write_text('')
    with pytest.raises(ValueError): mode.initialize(operator/'run',{'prompt':'Fictional task'})
    assert not (operator/'run'/mode.RUN_RECORD).exists()


@pytest.mark.parametrize('record_parent', [False,True])
def test_child_never_reinterprets_original_human_default(operator, record_parent):
    from ravel.workflow import execution
    parent=operator/'parent'
    document={'prompt':'Fictional task'}
    path=parent/'inputs/task_contract.json';atomic_json(path,document)
    if record_parent:
        assert mode.initialize(parent,document,configured_only=True) is None
        assert mode._frozen(parent)['mode']=='physicist-in-the-loop'
    set_operator_mode('autonomous')
    child={'goal_binding':{'contract':{'path':str(path),'sha256':execution.file_hash(path),
                                     'size':path.stat().st_size},'assignment_id':'toy'}}
    root=parent/'child'
    assert mode.initialize(root,child,configured_only=True) is None
    assert mode._frozen(root)['mode']=='physicist-in-the-loop'
    assert mode._frozen(root)['budget_root']==str(parent)


@pytest.mark.parametrize('point', ['pending','file','commit'])
def test_intake_transaction_recovers_exact_bytes(operator, monkeypatch, point):
    set_operator_mode('autonomous')
    root=operator/'run';doc={'prompt':'Fictional task'};authorize_run(root,doc)
    append=mode.rdj_custody._append;publish=mode._publish_exact
    def broken_append(path, record):
        value=append(path,record)
        if Path(path)==mode._ledger(root,'runs') and record['phase']==point:
            raise RuntimeError('simulated process loss')
        return value
    def broken_publish(path, raw):
        publish(path,raw)
        if point=='file': raise RuntimeError('simulated process loss')
    with monkeypatch.context() as patch:
        patch.setattr(mode.rdj_custody,'_append',broken_append)
        patch.setattr(mode,'_publish_exact',broken_publish)
        # The persisted phase is named committed, while the failure label is commit.
        if point=='commit':
            def after_commit(path,record):
                value=append(path,record)
                if Path(path)==mode._ledger(root,'runs') and record['phase']=='committed':
                    raise RuntimeError('simulated process loss')
                return value
            patch.setattr(mode.rdj_custody,'_append',after_commit)
        with pytest.raises(RuntimeError): mode.initialize(root,doc)
    if point!='commit':
        with pytest.raises(ValueError,match='pending'):mode.frozen(root)
    value=mode.initialize(root,doc)
    assert (root/mode.RUN_RECORD).read_bytes()==mode._json_bytes(value)
    assert len(mode.rdj_custody._read(mode._ledger(root,'runs')))==2


@pytest.mark.parametrize('point', ['pending','declaration','transition','commit'])
def test_delegation_transaction_recovers_without_duplicate_authority(operator, monkeypatch, point):
    from test_autonomy_delegation import planned
    from ravel.workflow import scientific_autonomy as autonomy
    set_operator_mode('autonomous');root=operator/'run';planned(root)
    append=mode.rdj_custody._append;publish=mode._publish_exact
    def broken_append(path,record):
        value=append(path,record)
        if Path(path)==mode._ledger(root,'delegations') and record['phase']=={'commit':'committed'}.get(point,point):
            raise RuntimeError('simulated process loss')
        return value
    def broken_publish(path,raw):
        publish(path,raw)
        if ((point=='declaration' and Path(path).name=='mode-delegation.json')
                or (point=='transition' and Path(path)==root/autonomy.TRANSITION)):
            raise RuntimeError('simulated process loss')
    with monkeypatch.context() as patch:
        patch.setattr(mode.rdj_custody,'_append',broken_append)
        patch.setattr(mode,'_publish_exact',broken_publish)
        with pytest.raises(RuntimeError):mode.bind_plan(root)
    if point!='commit':
        with pytest.raises(ValueError): autonomy.plan_authority(root,required_plan='none')
    assert mode.bind_plan(root)
    assert autonomy.plan_authority(root,required_plan='none')
    assert len(mode.rdj_custody._read(mode._ledger(root,'delegations')))==2


@pytest.mark.parametrize('operation', ['intake','binding'])
def test_concurrent_resume_serializes_one_authority(operator, operation):
    from concurrent.futures import ThreadPoolExecutor
    from test_autonomy_delegation import planned
    set_operator_mode('autonomous');root=operator/'run'
    if operation=='binding':
        planned(root);call=lambda:mode.bind_plan(root);kind='delegations'
    else:
        doc={'prompt':'Fictional task'};authorize_run(root,doc)
        call=lambda:mode.initialize(root,doc);kind='runs'
    with ThreadPoolExecutor(max_workers=4) as executor:
        values=list(executor.map(lambda _:call(), range(8)))
    assert all(v==values[0] for v in values)
    assert len(mode.rdj_custody._read(mode._ledger(root,kind)))==2


def test_pending_conflicting_file_never_earns_authority(operator,monkeypatch):
    set_operator_mode('autonomous');root=operator/'run';doc={'prompt':'Fictional task'};authorize_run(root,doc)
    with monkeypatch.context() as patch:
        patch.setattr(mode,'_publish_exact',lambda *a: (_ for _ in ()).throw(RuntimeError('crash')))
        with pytest.raises(RuntimeError):mode.initialize(root,doc)
    atomic_json(root/mode.RUN_RECORD,{'mode':'autonomous'})
    with pytest.raises(ValueError,match='conflict'):mode.initialize(root,doc)
    with pytest.raises(ValueError,match='pending'):mode.frozen(root)


STATEMENT_PROMPT = 'Please run autonomously. Inspect the fictional polynomial.'


def test_request_statement_without_operator_service_keeps_intake_and_text_paths(operator, monkeypatch):
    # Production consumer, no protected ledger: intake must not refuse a request that
    # states delegation. The run stays physicist-in-the-loop under operating mode and
    # the statement remains available to the retained text-delegation paths.
    from test_operating_mode import PRODUCTION_OPERATOR_RECORDS
    from ravel.workflow import scientific_autonomy as autonomy
    monkeypatch.setattr(mode, '_operator_records', PRODUCTION_OPERATOR_RECORDS)
    root = operator / 'run'
    document = {'prompt': STATEMENT_PROMPT}
    atomic_json(root / 'inputs/task_contract.json', document)
    assert mode.initialize(root, document, configured_only=True) is None
    recorded = mode._frozen(root)
    assert (recorded['mode'], recorded['source'], recorded['materialized']) == ('physicist-in-the-loop', 'user_default', False)
    assert 'operator_receipt' not in recorded and not (root / mode.RUN_RECORD).exists()
    assert mode.receipt(root) == {'mode': 'physicist-in-the-loop', 'source': 'user_default', 'binding': None}
    assert autonomy.delegation_intent(STATEMENT_PROMPT)['text'] == 'Please run autonomously.'
    monkeypatch.setenv('RAVEL_OPERATING_MODE', 'autonomous')
    with pytest.raises(ValueError, match='operator'):
        mode.initialize(operator / 'environment', {'prompt': STATEMENT_PROMPT})
    monkeypatch.delenv('RAVEL_OPERATING_MODE')
    with pytest.raises(ValueError, match='operator'):
        mode.set_mode('autonomous')
    assert not mode.config_path('project').exists()


def test_privileged_identity_never_blocks_a_stated_request(operator, monkeypatch):
    # A privileged process has no trustworthy operator ledger: configured autonomy still
    # refuses, while a request statement falls back exactly as without the service.
    from test_operating_mode import PRODUCTION_OPERATOR_RECORDS
    monkeypatch.setattr(mode, '_operator_records', PRODUCTION_OPERATOR_RECORDS)
    monkeypatch.setattr(mode, '_privileged', lambda: True)
    assert mode.initialize(operator / 'run', {'prompt': STATEMENT_PROMPT}, configured_only=True) is None
    monkeypatch.setenv('RAVEL_OPERATING_MODE', 'autonomous')
    with pytest.raises(ValueError, match='non-privileged'):
        mode.initialize(operator / 'environment', {'prompt': 'Inspect the fictional polynomial.'})


def test_request_statement_without_operator_service_keeps_human_approval(operator, monkeypatch):
    from test_operating_mode import PRODUCTION_OPERATOR_RECORDS
    from test_autonomy_delegation import planned
    from ravel.workflow import workflow_state as ws
    from ravel.workflow.state_io import read_json
    monkeypatch.setattr(mode, '_operator_records', PRODUCTION_OPERATOR_RECORDS)
    root = operator / 'run'
    planned(root, STATEMENT_PROMPT, authorize=False)
    assert mode.frozen(root) is None
    assert ws.main(['approve', '--rundir', str(root), '--plan', 'none', '--quote', 'Approved as planned.']) == 0
    receipt = read_json(root / 'inputs/checkin1_approval.json')
    assert receipt['authority'] != 'delegated_machine'
    assert receipt['operating_mode'] == {'mode': 'physicist-in-the-loop', 'source': 'user_default', 'binding': None}
    assert not ws.verify_approval(str(root), required_plan='none')


def test_child_of_unserviced_request_statement_stays_human(operator):
    from ravel.workflow import execution
    parent = operator / 'parent'
    document = {'prompt': STATEMENT_PROMPT}
    path = parent / 'inputs/task_contract.json'; atomic_json(path, document)
    assert mode.initialize(parent, document, configured_only=True) is None
    set_operator_mode('autonomous')
    child_document = {'goal_binding': {'contract': {'path': str(path), 'sha256': execution.file_hash(path),
                                                    'size': path.stat().st_size}, 'assignment_id': 'toy'}}
    child = parent / 'child'
    assert mode.initialize(child, child_document, configured_only=True) is None
    assert mode._frozen(child)['mode'] == 'physicist-in-the-loop'


def test_reused_run_path_names_the_previous_run(operator):
    import shutil
    root = operator / 'trial-runs' / 'reused'
    root.mkdir(parents=True)
    assert mode.initialize(root, {'prompt': 'Inspect the fictional polynomial.'}, configured_only=True) is None
    shutil.rmtree(root)
    root.mkdir(parents=True)
    assert mode.initialize(root, {'prompt': 'Inspect the fictional polynomial.'}, configured_only=True) is None
    with pytest.raises(ValueError, match='different original request.*previous run used this directory path'):
        mode.initialize(root, {'prompt': 'Inspect another fictional polynomial.'}, configured_only=True)


def test_present_run_ledger_for_another_selection_still_refuses(operator):
    root = operator / 'run'
    mode._operator_records.issue('run', root.resolve(), {'rundir': str(root.resolve()), 'mode': 'physicist-in-the-loop'})
    with pytest.raises(ValueError, match='operator receipt'):
        mode.initialize(root, {'prompt': STATEMENT_PROMPT})
    assert not (root / mode.RUN_RECORD).exists()


def test_setting_receipt_is_not_a_run_receipt(operator):
    set_operator_mode('autonomous')
    with pytest.raises(ValueError,match='operator'):
        mode.initialize(operator/'run',{'prompt':'Fictional task'})


def test_forged_zero_reservation_refuses(operator):
    set_operator_mode('autonomous');root=operator/'run';initialize_trusted(root,{'prompt':'Task'})
    with pytest.raises(ValueError,match='verified plan'):
        with mode.launch_reservation(root,['forged'],{'stage':'scan-dispatch','max_seconds':0,'events':0,
                'resource_reservation':'orchestration','resource_events':0,'resource_stages':['science']}):
            pytest.fail('forged wrapper admitted')


@pytest.mark.parametrize('target', ['declaration','plan'])
def test_pending_delegation_conflict_never_recovers_with_new_bytes(operator,monkeypatch,target):
    from test_autonomy_delegation import planned
    from ravel.workflow import scientific_autonomy as autonomy
    set_operator_mode('autonomous');root=operator/'run';planned(root)
    with monkeypatch.context() as patch:
        patch.setattr(mode,'_publish_exact',lambda *a: (_ for _ in ()).throw(RuntimeError('crash')))
        with pytest.raises(RuntimeError):mode.bind_plan(root)
    path=root/('inputs/mode-delegation.json' if target=='declaration' else 'inputs/plan.json')
    atomic_json(path,{'replacement':'cannot acquire authority'})
    with pytest.raises(ValueError):mode.bind_plan(root)
    with pytest.raises(ValueError):autonomy.plan_authority(root,required_plan='none')


def test_negated_prerequisite_blocks_legacy_text_parser_too():
    from ravel.workflow import scientific_autonomy as autonomy
    assert autonomy.delegation_intent('Run autonomously. Do not proceed without further approval.') is None


# Preserve the real read boundary; the operator fixture replaces only transport.
REAL_OPERATOR_RECORDS = mode._operator_records

def test_agent_writable_operator_store_is_not_authenticated(tmp_path,monkeypatch):
    import os
    real_path=Path
    def mapped(value):
        if str(value) in {'/etc','/private/etc'}: return tmp_path/'etc'
        return real_path(value)
    target=tmp_path/'run'
    path=tmp_path/'etc/ravel/operator-authority'/str(os.getuid())/'run'/(mode._key(target)+'.jsonl')
    path.parent.mkdir(parents=True);path.write_text('')
    monkeypatch.setattr(mode,'Path',mapped)
    with pytest.raises(ValueError,match='root-owned|non-privileged'):
        REAL_OPERATOR_RECORDS('run',target)
    # A present but untrusted ledger is never mistaken for an absent one.
    with pytest.raises(ValueError,match='root-owned|non-privileged'):
        mode._has_operator_records('run',target)


@pytest.mark.parametrize('published', [False, True])
def test_actual_intake_entry_resumes_pending_mode(operator,monkeypatch,published):
    from test_autonomy_delegation import planned
    from ravel.workflow import workflow_state as ws
    from ravel.workflow.state_io import read_json
    set_operator_mode('autonomous');root=operator/'run'
    publish=mode._publish_exact
    def crash(path,raw):
        if published:publish(path,raw)
        raise RuntimeError('simulated intake loss')
    with monkeypatch.context() as patch:
        patch.setattr(mode,'_publish_exact',crash)
        with pytest.raises(RuntimeError):planned(root)
    path=root/'inputs/task_contract.json'
    state=ws.new_state(str(root),read_json(path),str(path),'fixture')
    assert state['session_id']=='fixture'
    assert mode.frozen(root)['mode']=='autonomous'
