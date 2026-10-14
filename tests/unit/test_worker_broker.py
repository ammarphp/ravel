"""Inert controls for receipted actions; prose is never authority."""
import hashlib
import json
from pathlib import Path

import pytest


def make(tmp_path, monkeypatch, **options):
    from ravel.workflow.broker import Broker, work_root
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    run = tmp_path / 'run'; run.mkdir(exist_ok=True)
    workspace = work_root(run) / 'worker' / '1'; workspace.mkdir(parents=True, exist_ok=True)
    for name in ('inputs', 'outputs', 'scratch', 'calls'):
        (workspace / name).mkdir(exist_ok=True)
    return Broker(run, workspace, node_id='worker', attempt=1,
                  allowed_actions=['read', 'write', 'board read'], max_calls=20, **options)


def test_disallowed_and_forbidden_actions_are_receipted(tmp_path, monkeypatch):
    broker = make(tmp_path, monkeypatch, forbidden_sources=['inputs/private*'])
    for action, args, code in [('shell', {}, 'not_allowlisted'),
        ('read', {'path':'inputs/private.txt'}, 'forbidden_source'),
        ('write', {'path':'../escape', 'content':'x'}, 'write_outside_workspace')]:
        result = broker.call({'call_id':code, 'action':action, 'args':args})
        assert result['status']=='refused' and result['error']['code']==code
    assert len(list((broker.workspace/'calls').glob('*.json')))==3
    assert len(broker.verify_ledger())==3


def test_third_identical_no_change_call_escalates_and_replay_is_free(tmp_path, monkeypatch):
    broker=make(tmp_path,monkeypatch)
    (broker.workspace/'inputs/data').write_text('synthetic')
    replies=[broker.call({'call_id':str(i),'action':'read','args':{'path':'inputs/data'}}) for i in range(3)]
    assert replies[-1]['error']['code']=='decision_block'
    assert broker.call({'call_id':'0','action':'read','args':{'path':'inputs/data'}})==replies[0]
    assert len(broker.verify_ledger())==3
    assert broker.call({'call_id':'later','action':'read','args':{'path':'inputs/data'}})['error']['code']=='decision_block'


def test_real_output_state_change_resets_repetition(tmp_path,monkeypatch):
    broker=make(tmp_path,monkeypatch)
    (broker.workspace/'inputs/data').write_text('synthetic')
    for i in range(2):assert broker.call({'call_id':str(i),'action':'read','args':{'path':'inputs/data'}})['status']=='ok'
    (broker.workspace/'outputs/change').write_text('state changed')
    assert broker.call({'call_id':'2','action':'read','args':{'path':'inputs/data'}})['status']=='ok'


def test_sealed_peer_read_denied_logged_even_when_unsealed_identity(tmp_path,monkeypatch):
    broker=make(tmp_path,monkeypatch,season={'phase':'sealed','participants':[
        {'actor_id':'one','session_id':'same','attestation':'self_attested'},
        {'actor_id':'two','session_id':'same','attestation':'self_attested'}]},actor_id='one')
    called=[]
    broker.register('board read',lambda args:called.append(args) or {'text':'peer'},read_only=True)
    reply=broker.call({'call_id':'peer','action':'board read','args':{'actor_id':'two'}})
    assert reply['error']['code']=='peer_read_denied' and called==[]
    seal=broker.sealing_status()
    assert seal['status']=='unsealed' and 'independence' not in seal
    assert len(broker.peer_denials())==1


def test_duplicate_call_id_changed_args_is_refused(tmp_path,monkeypatch):
    broker=make(tmp_path,monkeypatch)
    broker.call({'call_id':'one','action':'read','args':{'path':'inputs/missing'}})
    result=broker.call({'call_id':'one','action':'read','args':{'path':'inputs/changed'}})
    assert result['status']=='refused' and result['error']['code']=='call_identity_changed'


def test_broker_and_acquisition_custody_reject_edited_public_receipts(tmp_path,monkeypatch):
    from ravel.workflow.broker import verify_broker_receipt, verify_acquisition_receipt, logical
    broker=make(tmp_path,monkeypatch)
    broker.allowed_actions.add('acquire')
    def acquire(args):
        p=broker.workspace/'outputs/source.txt';p.write_text('supplied external bytes')
        return {'output_paths':['outputs/source.txt'],'source':{'record_id':'synthetic-record','uri':'fixture://source'}}
    broker.register('acquire',acquire,derivation='retrieval')
    broker.call({'call_id':'get','action':'acquire','args':{}})
    path=broker.workspace/'calls/1.json'
    pin={'path':logical(broker.rundir,path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    assert verify_broker_receipt(broker.rundir,pin)['derivation']=='retrieval'
    assert verify_acquisition_receipt(broker.rundir,pin)['source']['record_id']=='synthetic-record'
    value=json.loads(path.read_text());value['exit_status']=17;path.write_text(json.dumps(value))
    pin['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='custody'):verify_broker_receipt(broker.rundir,pin)


def test_native_action_without_lease_refused_and_busy_action_waits(tmp_path,monkeypatch):
    broker=make(tmp_path,monkeypatch);broker.allowed_actions.add('native')
    effects=[]
    broker.register('native',lambda args:effects.append(1) or {},native=True)
    assert broker.call({'call_id':'missing','action':'native','args':{}})['error']['code']=='lease_busy'
    broker.lease=lambda action,args:None
    assert broker.call({'call_id':'busy','action':'native','args':{}})['error']['code']=='lease_busy'
    assert not effects


def test_socket_and_in_process_calls_use_identical_receipts(tmp_path,monkeypatch):
    from ravel.workflow.broker import serve, socket_call
    broker=make(tmp_path,monkeypatch)
    (broker.workspace/'inputs/data').write_text('data')
    try:
        with serve(broker):
            request={'call_id':'one','action':'read','args':{'path':'inputs/data'}}
            assert socket_call(broker.socket_path,request)==broker.call(request)
    except PermissionError:
        pytest.skip('sandbox-blocked: Unix socket binding denied; reviewer must run')


def test_artifact_and_board_prose_cannot_dispatch_controls(tmp_path,monkeypatch):
    from ravel.validation.check_authority_boundary import check
    from ravel.workflow.broker import authority_inputs
    broker=make(tmp_path,monkeypatch)
    gates=[];orders=[]
    for fixture in ('artifact.txt','board-post.json'):
        content=(Path(__file__).parents[1]/'fixtures/canaries'/fixture).read_text()
        (broker.workspace/'inputs/data').write_text(content)
        reply=broker.call({'call_id':fixture,'action':'read','args':{'path':'inputs/data'}})
        assert reply['status']=='ok'
        assert 'control' not in authority_inputs(reply)
    result=check()
    assert result['valid'] and result['gate_inputs']==[] and result['work_orders']==[]
    assert gates==orders==[]


def test_crash_after_broker_reservation_cannot_repeat_effect(tmp_path,monkeypatch):
    broker=make(tmp_path,monkeypatch);broker.allowed_actions.add('effect')
    effects=[]
    def effect(args):
        effects.append(1)
        raise SystemExit('inert crash before completion receipt')
    broker.register('effect',effect)
    call={'call_id':'once','action':'effect','args':{}}
    with pytest.raises(SystemExit):broker.call(call)
    resumed=make(tmp_path,monkeypatch);resumed.allowed_actions.add('effect')
    resumed.register('effect',lambda args:effects.append(2) or {})
    reply=resumed.call(call)
    assert reply['error']['code']=='ambiguous_call' and effects==[1]


def test_sealed_label_requires_registered_transport_receipts(tmp_path,monkeypatch):
    broker=make(tmp_path,monkeypatch,season={'phase':'sealed','participants':[
        {'actor_id':'one','session_id':'one','attestation':'transport_attested'},
        {'actor_id':'two','session_id':'two','attestation':'transport_attested'}]})
    assert broker.sealing_status()['status']=='unsealed'
    assert 'independence' not in broker.sealing_status()


def test_sealed_unknown_actor_cannot_turn_missing_identity_into_peer_access(tmp_path,monkeypatch):
    broker=make(tmp_path,monkeypatch,season={'phase':'sealed','participants':[]})
    called=[]
    broker.register('board read',lambda args:called.append(args) or {'stdout':'peer'},read_only=True)
    reply=broker.call({'call_id':'unknown','action':'board read','args':{'actor_id':None}})
    assert reply['error']['code']=='peer_read_denied' and called==[]


def test_forbidden_sources_match_the_normalized_path(tmp_path,monkeypatch):
    broker=make(tmp_path,monkeypatch,forbidden_sources=['inputs/private*'])
    (broker.workspace/'inputs/private.txt').write_text('blinded')
    for i,alias in enumerate(('./inputs/private.txt','inputs//private.txt','inputs/./private.txt','inputs/private.txt/')):
        reply=broker.call({'call_id':f'alias-{i}','action':'read','args':{'path':alias}})
        assert reply['status']=='refused' and reply['error']['code']=='forbidden_source'
        assert 'blinded' not in reply['stdout_tail']


def test_symlinked_and_hard_linked_paths_are_refused_without_touching_targets(tmp_path,monkeypatch):
    import os
    broker=make(tmp_path,monkeypatch)
    outside=tmp_path/'outside';outside.mkdir();(outside/'secret').write_text('outside bytes')
    (broker.workspace/'outputs/link').symlink_to(outside)
    os.link(outside/'secret',broker.workspace/'scratch/hard')
    for i,(action,args) in enumerate([('read',{'path':'outputs/link/secret'}),
            ('write',{'path':'outputs/link/new','content':'x'}),('write',{'path':'outputs/link','content':'x'}),
            ('write',{'path':'scratch/hard','content':'x'}),('read',{'path':'scratch/hard'})]):
        reply=broker.call({'call_id':f'link-{i}','action':action,'args':args})
        assert reply['status']=='refused' and 'outside bytes' not in reply['stdout_tail']
    assert (outside/'secret').read_text()=='outside bytes' and sorted(p.name for p in outside.iterdir())==['secret']


def test_directory_swapped_after_policy_check_cannot_redirect_the_broker(tmp_path,monkeypatch):
    import shutil
    from ravel.workflow import broker as module
    broker=make(tmp_path,monkeypatch)
    outside=tmp_path/'outside';outside.mkdir();(outside/'secret').write_text('outside bytes')
    (broker.workspace/'outputs/sub').mkdir();(broker.workspace/'outputs/sub/data').write_text('own bytes')
    checked=module.Broker._canonical
    def swap_after_check(self,rel,**kwargs):
        parts=checked(self,rel,**kwargs)
        sub=self.workspace/'outputs/sub'
        if sub.is_dir() and not sub.is_symlink():
            shutil.rmtree(sub);sub.symlink_to(outside)
        return parts
    monkeypatch.setattr(module.Broker,'_canonical',swap_after_check)
    read=broker.call({'call_id':'race-read','action':'read','args':{'path':'outputs/sub/secret'}})
    assert read['status']=='refused' and 'outside bytes' not in read['stdout_tail']
    (broker.workspace/'outputs/sub').unlink();(broker.workspace/'outputs/sub').mkdir()
    write=broker.call({'call_id':'race-write','action':'write','args':{'path':'outputs/sub/secret','content':'x'}})
    assert write['status']=='refused'
    assert (outside/'secret').read_text()=='outside bytes'


def test_scratch_changes_do_not_defeat_repeat_detection(tmp_path,monkeypatch):
    broker=make(tmp_path,monkeypatch)
    (broker.workspace/'inputs/data').write_text('synthetic')
    replies=[]
    for i in range(3):
        (broker.workspace/'scratch/tick').write_text(str(i))
        replies.append(broker.call({'call_id':str(i),'action':'read','args':{'path':'inputs/data'}}))
    assert replies[-1]['error']['code']=='decision_block'


def test_repeat_snapshot_walks_by_descriptor_and_never_follows_links(tmp_path,monkeypatch):
    from ravel.workflow import broker as module
    broker=make(tmp_path,monkeypatch)
    outside=tmp_path/'outside';outside.mkdir();(outside/'secret').write_text('outside bytes')
    (broker.workspace/'outputs/own').write_text('own')
    (broker.workspace/'outputs/linked').symlink_to(outside)
    (broker.workspace/'outputs/file-link').symlink_to(outside/'secret')
    def refuse(*args,**kwargs):raise AssertionError('snapshot hashed a file by pathname')
    monkeypatch.setattr(module,'sha',refuse)
    before=broker._snapshot()
    (outside/'secret').write_text('changed outside bytes');(outside/'more').write_text('new')
    assert broker._snapshot()==before
    (broker.workspace/'outputs/own').write_text('own changed')
    assert broker._snapshot()!=before


def test_crash_between_custody_append_and_state_pin_adopts_the_receipt(tmp_path,monkeypatch):
    from ravel.workflow import broker as module
    broker=make(tmp_path,monkeypatch);broker.allowed_actions.add('effect')
    effects=[]
    broker.register('effect',lambda args:effects.append(1) or {})
    original=module.atomic_json
    def crash(path,value):
        if path==broker._state and any(c.get('pin') for c in value.get('calls',{}).values()):
            raise SystemExit('inert crash after the custody append')
        return original(path,value)
    monkeypatch.setattr(module,'atomic_json',crash)
    call={'call_id':'once','action':'effect','args':{}}
    with pytest.raises(SystemExit):broker.call(call)
    monkeypatch.setattr(module,'atomic_json',original)
    resumed=make(tmp_path,monkeypatch);resumed.allowed_actions.add('effect')
    resumed.register('effect',lambda args:effects.append(2) or {})
    reply=resumed.call(call)
    assert reply['status']=='ok' and effects==[1]
    assert resumed.call(call)==reply and len(resumed.verify_ledger())==1


@pytest.mark.parametrize('deferred, expected', [(False, 'ok'), (True, 'failed')])
def test_run_validator_uses_real_run_and_exact_receipt_id(tmp_path, monkeypatch, deferred, expected):
    from ravel.workflow import review_projection_checks
    target = make(tmp_path, monkeypatch)
    target.allowed_actions.add('check run')
    (target.rundir / 'inputs').mkdir()
    contract = {'detector_mode': 'TBD-judgment' if deferred else 'none', 'stat_mode': 'none'}
    (target.rundir / 'inputs/task_contract.json').write_text(json.dumps(contract))
    check = 'check:validation.validate_run_state.check_route'
    card = {'id': 'synthetic', 'must_check': [check], 'tools': {'validators': []}}
    review_projection_checks.register(target, card)
    reply = target.call({'call_id': 'route', 'action': 'check run', 'args': {'check_id': check}})
    assert reply['status'] == expected, reply
    receipt = target.verify_ledger()[-1]
    assert receipt['validator_id'] == check
    assert receipt['exit_status'] == (0 if expected == 'ok' else 1)
    assert receipt['output_pins']


@pytest.mark.parametrize('check', ['check:synthetic.unlisted', 'trap:T6', 'check-run'])
def test_unlisted_check_cannot_claim_a_validator_receipt(tmp_path, monkeypatch, check):
    from ravel.workflow import review_projection_checks
    target = make(tmp_path, monkeypatch)
    target.allowed_actions.add('check run')
    review_projection_checks.register(target, {'id': 'synthetic', 'must_check': [check], 'tools': {}})
    reply = target.call({'call_id': 'refuse', 'action': 'check run', 'args': {'check_id': check}})
    assert reply['status'] == 'refused'
    assert target.verify_ledger()[-1]['validator_id'] is None


def test_document_check_failure_is_a_failed_exact_receipt(tmp_path, monkeypatch):
    from ravel.workflow import review_projection_checks
    target = make(tmp_path, monkeypatch)
    target.allowed_actions.add('check run')
    check = 'review.normalization_recompute'
    review_projection_checks.register(target, {'id': 'normalization-auditor', 'must_check': [], 'tools': {}})
    (target.workspace / 'inputs/check.json').write_text(json.dumps({
        'cross_section_pb': 1, 'luminosity_ifb': 1, 'branching_ratio': 1,
        'efficiency': 1, 'reported_yield': 500}))
    reply = target.call({'call_id': 'fail', 'action': 'check run',
                         'args': {'check_id': check, 'paths': ['inputs/check.json']}})
    assert reply['status'] == 'failed'
    assert target.verify_ledger()[-1]['validator_id'] == check


@pytest.mark.parametrize('check', [
    'check:physics.normalization_ledger.check', 'check:validation.validate_cutflow',
    'check:validation.validate_run_state.check_route'])
def test_missing_run_inputs_fail_without_claiming_execution(tmp_path, monkeypatch, check):
    from ravel.workflow import review_projection_checks
    target = make(tmp_path, monkeypatch)
    target.allowed_actions.add('check run')
    review_projection_checks.register(target, {'id': 'synthetic', 'must_check': [check], 'tools': {}})
    reply = target.call({'call_id': 'missing', 'action': 'check run', 'args': {'check_id': check}})
    assert reply['status'] == 'failed'
    assert target.verify_ledger()[-1]['validator_id'] is None


@pytest.mark.parametrize('valid', [True, False])
def test_normalization_adapter_recomputes_the_ledger(tmp_path, monkeypatch, valid):
    from ravel.workflow import review_projection_checks
    from test_normalization_ledger import ledger
    target = make(tmp_path, monkeypatch)
    target.allowed_actions.add('check run')
    (target.rundir / 'inputs').mkdir()
    document = ledger()
    if not valid:
        document['k']['applied_once'] = False
    (target.rundir / 'inputs/normalization_ledger.json').write_text(json.dumps(document))
    check = 'check:physics.normalization_ledger.check'
    review_projection_checks.register(target, {'id': 'synthetic', 'must_check': [check], 'tools': {}})
    reply = target.call({'call_id': 'normalization', 'action': 'check run', 'args': {'check_id': check}})
    assert reply['status'] == ('ok' if valid else 'failed'), reply
    assert target.verify_ledger()[-1]['validator_id'] == check


def test_allowlisted_check_without_role_permission_is_refused(tmp_path, monkeypatch):
    from ravel.workflow import review_projection_checks
    target = make(tmp_path, monkeypatch)
    target.allowed_actions.add('check run')
    review_projection_checks.register(target, {'id': 'synthetic', 'must_check': [], 'tools': {}})
    reply = target.call({'call_id': 'wrong-role', 'action': 'check run',
                         'args': {'check_id': 'check:validation.validate_task_contract.validate'}})
    assert reply['status'] == 'refused'
    assert target.verify_ledger()[-1]['validator_id'] is None


@pytest.mark.parametrize('shared', [False, True])
def test_input_closure_adapter_preserves_reference_independence(tmp_path, monkeypatch, shared):
    from ravel.workflow import run_validator_checks
    from ravel.workflow.broker import sha
    target = make(tmp_path, monkeypatch)
    (target.rundir / 'inputs').mkdir()
    reference = target.rundir / 'inputs/reference.json'
    reference.write_text('{}')
    pin = {'path': 'inputs/reference.json', 'sha256': sha(reference)}
    fit = target.rundir / 'inputs/fit.json'
    fit.write_text(json.dumps({'inputs': [pin] if shared else []}))
    check = 'check:validation.input_closure.check'
    value = run_validator_checks.RunCheckInput(target.rundir, {'check_inputs': {check: {
        'fit': {'path': 'inputs/fit.json', 'sha256': sha(fit)}, 'reference': pin}}}, target.workspace)
    report = run_validator_checks.run(check, value)
    assert report['validator_executed']
    assert report['status'] == ('failed' if shared else 'passed')


@pytest.mark.parametrize('record', [{}, {'traps_checked': ['T6']}])
def test_incomplete_trap_record_earns_no_success(tmp_path, monkeypatch, record):
    from ravel.workflow import review_projection_checks
    target = make(tmp_path, monkeypatch)
    target.allowed_actions.add('check run')
    (target.rundir / 'inputs').mkdir()
    (target.rundir / 'inputs/task_contract.json').write_text('{}')
    (target.rundir / 'inputs/trap_sweep.json').write_text(json.dumps(record))
    check = 'check:validation.validate_run_state.check_trap_sweep'
    review_projection_checks.register(target, {'id': 'synthetic', 'must_check': [check], 'tools': {}})
    assert target.call({'call_id': 'traps', 'action': 'check run', 'args': {'check_id': check}})['status'] == 'failed'
    assert target.verify_ledger()[-1]['validator_id'] == check


def test_validator_removed_from_allowlist_is_never_called(tmp_path, monkeypatch):
    from ravel.workflow import review_projection_checks
    from ravel.validation import validate_run_state
    target = make(tmp_path, monkeypatch)
    target.allowed_actions.add('check run')
    check = 'check:validation.validate_run_state.check_route'
    document = review_projection_checks.allowlist()
    document['validators'] = [row for row in document['validators'] if row['id'] != check]
    monkeypatch.setattr(review_projection_checks, 'allowlist', lambda: document)
    calls = []
    monkeypatch.setattr(validate_run_state, 'check_route', lambda *a: calls.append(a))
    review_projection_checks.register(target, {'id': 'synthetic', 'must_check': [check], 'tools': {}})
    reply = target.call({'call_id': 'removed', 'action': 'check run', 'args': {'check_id': check}})
    assert reply['status'] == 'refused' and calls == []
    assert target.verify_ledger()[-1]['validator_id'] is None



def test_route_warning_keeps_the_validator_s_declared_success(tmp_path, monkeypatch):
    from ravel.workflow import review_projection_checks
    target = make(tmp_path, monkeypatch)
    target.allowed_actions.add('check run')
    (target.rundir / 'inputs').mkdir()
    (target.rundir / 'inputs/task_contract.json').write_text(json.dumps({
        'detector_mode': 'delphes-custom-uncertified', 'stat_mode': 'none'}))
    check = 'check:validation.validate_run_state.check_route'
    review_projection_checks.register(target, {'id': 'synthetic', 'must_check': [check], 'tools': {}})
    reply = target.call({'call_id': 'warn', 'action': 'check run', 'args': {'check_id': check}})
    assert reply['status'] == 'ok'
    output = target.workspace / json.loads(reply['stdout_tail'])['result']
    assert json.loads(output.read_text())['diagnostics']['status'] == 'WARN'
