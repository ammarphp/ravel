"""Custody-backed live controls with synthetic plans and inert launch seams."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from ravel.workflow import gate_wiring as gw, rdj_custody as custody


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    root = tmp_path / 'study'
    (root / 'inputs').mkdir(parents=True)
    (root / 'inputs/task_contract.json').write_text(json.dumps({
        'run_id': 'synthetic-study', 'request_plan': {'path': 'inputs/plan.json'}}))
    (root / 'inputs/plan.json').write_text(json.dumps({
        'nodes': [{'id': n} for n in ['build', 'child', 'other']],
        'edges': [{'from': {'ref': 'build'}, 'to': {'ref': 'child'}}]}))
    custody.bind_run(root, 'synthetic-study')
    return root


def amended(run):
    path = run / 'inputs/amended.json'
    path.write_text('{"plan":"reconciled"}')
    return path


def policy(**extra):
    return dict(autonomy='manual', checkin_thresholds={}, hard_ceilings={},
                signoff_steps=[], unknown_cost='ask', on_pause='drain',
                result_acceptance='physicist', **extra)


def test_note_has_no_execution_effect_but_requires_ack(run):
    event = gw.record_steering(run, 'Keep this context.', effect='note')
    state = gw.steering_state(run)
    assert state['epoch'] == 1 and event['event_id'] in state['pending_ack']
    assert gw.dispatch_permitted(run, 'build')[0]
    gw.ack_steering(run, event['event_id'], interpretation='Read and retained.')
    assert not gw.steering_state(run)['pending_ack']


@pytest.mark.parametrize('effect', ['requirement', 'redirect'])
def test_affected_hold_reconciliation_and_old_results_preserved(run, effect):
    old = run / 'result.json'
    old.write_text('{"old":true}')
    event = gw.record_steering(run, 'Use revised constraints.', effect=effect,
                               affected_nodes=['build'], scope_increase=False)
    assert not gw.dispatch_permitted(run, 'build')[0]
    assert not gw.dispatch_permitted(run, 'child')[0]
    assert gw.dispatch_permitted(run, 'other')[0]
    with pytest.raises(ValueError, match='amended plan'):
        gw.ack_steering(run, event['event_id'], interpretation='Understood.')
    gw.ack_steering(run, event['event_id'], interpretation='Updated plan.', amended_plan=amended(run))
    assert gw.dispatch_permitted(run, 'child')[0]
    assert old.read_text() == '{"old":true}'


def test_ack_does_not_reapprove_scope(run):
    event = gw.record_steering(run, 'Extend the requested work.', effect='redirect', affected_nodes=['build'])
    gw.ack_steering(run, event['event_id'], interpretation='Plan revised.', amended_plan=amended(run))
    assert not gw.dispatch_permitted(run, 'build')[0]
    assert gw.dispatch_permitted(run, 'other')[0]
    (run / 'inputs/checkin1_approval.json').write_text('{}')
    assert not gw.dispatch_permitted(run, 'build')[0]  # editable file grants nothing
    custody.append(run, 'steering', {'event': 'approval', 'approval_sha256': gw._approval_digest(run)})
    assert gw.dispatch_permitted(run, 'build')[0]


@pytest.mark.parametrize('authority', ['delegated_machine', 'scripted_experiment'])
@pytest.mark.parametrize('autonomy', [None, 'manual'])
def test_scope_reapproval_refuses_machine_without_bounded_policy(run, authority, autonomy):
    if autonomy is not None:
        configured = gw.set_steering_policy(run, policy(), source_text='Keep manual signoff.')
        gw.ack_steering(run, configured['event_id'], interpretation='Policy retained.')
        (run / 'inputs/science-approval.json').write_text('{"approved":"initial"}')
        gw.record_plan_approval(run)
    event = gw.record_steering(run, 'Extend this branch.', effect='redirect', affected_nodes=['build'])
    gw.ack_steering(run, event['event_id'], interpretation='Plan revised.', amended_plan=amended(run))
    (run / 'inputs/science-approval.json').write_text('{"approved":"revised"}')
    before = custody.rows(run, 'steering')
    with pytest.raises(ValueError, match='authority'):
        gw.record_plan_approval(run, authority=authority)
    assert custody.rows(run, 'steering') == before
    # The dispatch and decision-gate consumers must also reject a machine row.
    custody.append(run, 'steering', {'event': 'approval', 'approval_sha256': gw._approval_digest(run),
                                     'authority': authority})
    assert not gw.dispatch_permitted(run, 'child')[0]
    assert gw.steering_errors(run)


def test_scope_reapproval_refuses_unchanged_receipt(run):
    receipt = run / 'inputs/science-approval.json'
    receipt.write_text('{"approved":"initial"}')
    original = gw._approval_digest(run)
    event = gw.record_steering(run, 'Extend this branch.', effect='redirect', affected_nodes=['build'])
    gw.ack_steering(run, event['event_id'], interpretation='Plan revised.', amended_plan=amended(run))
    with pytest.raises(ValueError, match='unchanged'):
        gw.record_plan_approval(run)
    assert event['approval_sha256_at_event'] == original
    custody.append(run, 'steering', {'event': 'approval', 'approval_sha256': original, 'authority': 'unknown'})
    assert not gw.dispatch_permitted(run, 'child')[0]
    assert gw.steering_errors(run)
    receipt.write_text('{"approved":"revised"}')
    gw.record_plan_approval(run)
    assert gw.dispatch_permitted(run, 'child')[0]
    assert gw.steering_errors(run) == []


@pytest.mark.parametrize('authority', ['delegated_machine', 'scripted_experiment'])
@pytest.mark.parametrize('signoff', ['build', 'child', 'synthetic-build', 'full'])
def test_bounded_reapproval_respects_node_operation_and_rung_signoff(run, authority, signoff):
    plan_path = run / 'inputs/plan.json'
    plan = json.loads(plan_path.read_text())
    plan['nodes'][0].update(operation='synthetic-build', rung='full')
    plan_path.write_text(json.dumps(plan))
    configured = gw.set_steering_policy(run, {**policy(), 'autonomy': 'bounded_delegated',
                                             'signoff_steps': [signoff]}, source_text='Retain mandatory signoff.')
    gw.ack_steering(run, configured['event_id'], interpretation='Policy retained.')
    (run / 'inputs/science-approval.json').write_text('{"approved":"initial"}')
    gw.record_plan_approval(run)
    event = gw.record_steering(run, 'Extend this branch.', effect='redirect', affected_nodes=['build'])
    gw.ack_steering(run, event['event_id'], interpretation='Plan revised.', amended_plan=amended(run))
    # Removing an operation from the current plan must not erase its signoff.
    plan['nodes'][0].pop('operation')
    plan['nodes'][0].pop('rung')
    plan_path.write_text(json.dumps(plan))
    (run / 'inputs/science-approval.json').write_text('{"approved":"revised"}')
    with pytest.raises(ValueError, match='authority'):
        gw.record_plan_approval(run, authority=authority)
    custody.append(run, 'steering', {'event': 'approval', 'approval_sha256': gw._approval_digest(run),
                                     'authority': authority})
    assert not gw.dispatch_permitted(run, 'child')[0]
    assert gw.steering_errors(run)


def test_policy_change_cannot_expand_existing_machine_delegation(run):
    initial = gw.set_steering_policy(run, policy(), source_text='Keep manual signoff.')
    gw.ack_steering(run, initial['event_id'], interpretation='Policy retained.')
    (run / 'inputs/science-approval.json').write_text('{"approved":"initial"}')
    gw.record_plan_approval(run)
    revised = gw.set_steering_policy(run, {**policy(), 'autonomy': 'bounded_delegated'},
                                     source_text='Delegate within new bounds.')
    gw.ack_steering(run, revised['event_id'], interpretation='New policy read.')
    (run / 'inputs/science-approval.json').write_text('{"approved":"revised"}')
    with pytest.raises(ValueError, match='authority'):
        gw.record_plan_approval(run, authority='delegated_machine')
    assert not gw.dispatch_permitted(run, 'other')[0]


def test_policy_change_after_approval_cannot_delegate_its_own_reapproval(run):
    (run / 'inputs/science-approval.json').write_text('{"approved":"initial"}')
    event = gw.set_steering_policy(run, {**policy(), 'autonomy': 'bounded_delegated'},
                                   source_text='Delegate within new bounds.')
    gw.ack_steering(run, event['event_id'], interpretation='New policy read.')
    (run / 'inputs/science-approval.json').write_text('{"approved":"revised"}')
    with pytest.raises(ValueError, match='authority'):
        gw.record_plan_approval(run, authority='delegated_machine')
    custody.append(run, 'steering', {'event': 'approval', 'approval_sha256': gw._approval_digest(run),
                                     'authority': 'delegated_machine'})
    assert not gw.dispatch_permitted(run, 'other')[0]
    assert gw.steering_errors(run)


def test_unmapped_stage_veto_holds_while_mapped_sibling_remains_permitted(run):
    gw.record_steering(run, 'Stop the independent branch.', effect='veto', affected_nodes=['other'])
    assert gw.dispatch_permitted(run, 'build')[0]
    assert not gw.dispatch_permitted(run, 'unmapped-stage')[0]
    assert any('veto' in error for error in gw.launch_errors(run, 'full', ['inert'],
                                                          {'node_id': 'unmapped-stage'}))


@pytest.mark.parametrize('effect', ['veto', 'redirect', 'pause'])
def test_unbound_rename_refuses_dispatch_when_steering_custody_is_missing(tmp_path, monkeypatch, effect):
    from ravel.workflow import graph_substrate as gs, agent_worker as aw
    monkeypatch.setattr(gs, 'stop', lambda *a, **kw: {})
    monkeypatch.setattr(aw, 'stop', lambda *a, **kw: {})
    root = tmp_path / 'unbound'
    (root / 'inputs').mkdir(parents=True)
    (root / 'inputs/task_contract.json').write_text('{}')
    gw.record_steering(root, 'Hold this work.', effect=effect, affected_nodes=['build'])
    moved = root.with_name('moved')
    root.rename(moved)
    allowed, reason = gw.dispatch_permitted(moved, 'build')
    assert not allowed
    assert 'custody' in reason
    with pytest.raises(custody.CustodyError, match='custody is missing'):
        gw.record_steering(moved, 'New context cannot reset custody.', effect='note')


@pytest.mark.parametrize('plan', [
    {'nodes': [{'id': 'build'}], 'edges': ['bad']},
    {'nodes': 1, 'edges': []},
])
def test_malformed_plan_returns_typed_dispatch_refusal(run, plan):
    (run / 'inputs/plan.json').write_text(json.dumps(plan))
    allowed, reason = gw.dispatch_permitted(run, 'build')
    assert not allowed
    assert 'plan unreadable' in reason


def test_veto_descendants_and_explicit_supersession(run):
    event = gw.record_steering(run, 'Do not dispatch this branch.', effect='veto', affected_nodes=['build'])
    gw.ack_steering(run, event['event_id'], interpretation='Branch stopped.')
    assert not gw.dispatch_permitted(run, 'child')[0]
    assert gw.dispatch_permitted(run, 'other')[0]
    resume = gw.record_steering(run, 'Release the veto.', effect='resume', supersedes=event['event_id'])
    gw.ack_steering(run, resume['event_id'], interpretation='Release recorded.')
    assert gw.dispatch_permitted(run, 'child')[0]


def test_pause_drains_and_resume_is_acknowledged(run, monkeypatch):
    from ravel.workflow import graph_substrate as gs, agent_worker as aw
    calls = []
    monkeypatch.setattr(gs, 'stop', lambda root, **kw: calls.append(('graph', kw)) or {})
    monkeypatch.setattr(gs, 'status', lambda root: {'holder': {'thread_id': 'busy'}, 'processes': []})
    monkeypatch.setattr(aw, 'stop', lambda root, **kw: calls.append(('worker', kw)) or {'verified_gone': False})
    monkeypatch.setattr(aw, 'processes', lambda root: [])
    event = gw.record_steering(run, 'Pause the study.', effect='pause')
    assert calls[0][1]['now'] is False and calls[1][1]['drain'] is True
    state = gw.steering_state(run)
    assert state['paused'] and state['pause_status'] == 'draining'
    assert state['pause_requested'] and not state['observed_stopped']
    assert not gw.dispatch_permitted(run, None)[0]
    gw.ack_steering(run, event['event_id'], interpretation='Paused.')
    resume = gw.record_steering(run, 'Continue the study.', effect='resume')
    assert not gw.dispatch_permitted(run, 'other')[0]
    gw.ack_steering(run, resume['event_id'], interpretation='Continue within the approved scope.')
    assert gw.dispatch_permitted(run, 'other')[0]


def test_pause_cancel_and_stop_observation(run, monkeypatch):
    from ravel.workflow import graph_substrate as gs, agent_worker as aw
    gw.set_steering_policy(run, policy(), source_text='Cancel on pause.', authority='unknown')
    # Replace with an explicit cancellation policy and acknowledge policy separately.
    gw.set_steering_policy(run, {**policy(), 'on_pause': 'cancel'}, source_text='Cancel on pause.', authority='unknown')
    calls = []
    monkeypatch.setattr(gs, 'stop', lambda root, **kw: calls.append(kw) or {})
    monkeypatch.setattr(gs, 'status', lambda root: {'holder': None, 'processes': []})
    monkeypatch.setattr(aw, 'stop', lambda root, **kw: {'verified_gone': True})
    monkeypatch.setattr(aw, 'processes', lambda root: [])
    gw.record_steering(run, 'Stop now.', effect='pause')
    assert calls[0]['now'] is True
    assert gw.steering_state(run)['observed_stopped']


def test_policy_custody_source_stale_approval_and_checkin(run):
    (run / 'inputs/checkin1_approval.json').write_text('{"approved":true}')
    text = 'Use the supplied limits exactly.\n'
    event = gw.set_steering_policy(run, policy(), source_text=text, authority='delegated_machine')
    state = gw.steering_state(run)
    assert state['policy']['source_text'] == text
    assert state['policy']['authority'] == 'delegated_machine'
    (run / 'inputs/steering/policy.json').write_text('{}')
    assert gw.steering_state(run)['policy']['source_text'] == text
    assert text.strip() in gw.render_steering_policy(run)
    gw.ack_steering(run, event['event_id'], interpretation='Policy applied.')
    assert not gw.dispatch_permitted(run, 'other')[0]
    (run / 'inputs/checkin1_approval.json').write_text('{"approved":"revised"}')
    custody.append(run, 'steering', {'event': 'approval', 'approval_sha256': gw._approval_digest(run)})
    assert gw.dispatch_permitted(run, 'other')[0]


@pytest.mark.parametrize('authority', ['human', 'human_operator', 'human_relayed'])
def test_human_label_requires_evidence(run, authority):
    with pytest.raises(ValueError, match='authority'):
        gw.record_steering(run, 'Context.', effect='note', authority=authority)
    assert gw.record_steering(run, 'Context.', effect='note')['authority'] == 'unknown'


def test_stale_ack_and_disposition_fail(run):
    event = gw.record_steering(run, 'Constraint.', effect='note')
    gw.record_steering(run, 'Later context.', effect='note')
    with pytest.raises(ValueError, match='stale'):
        gw.ack_steering(run, event['event_id'], interpretation='Read.', expected_epoch=1)
    with pytest.raises(ValueError, match='stale'):
        gw.record_result_disposition(run, 'accept', 'Accepted.', expected_epoch=1)
    with pytest.raises(ValueError, match='unknown'):
        gw.ack_steering(run, 'missing', interpretation='Read.')


@pytest.mark.parametrize('disposition', ['accept', 'reject', 'rework'])
def test_result_disposition_separate_from_scientific_acceptance(run, disposition):
    record = gw.record_result_disposition(run, disposition, 'Result response.')
    assert gw.steering_state(run)['result_disposition']['disposition'] == disposition
    assert record['scientific_acceptance'] is False
    assert custody.rows(run, 'review_acceptances') == []


def test_priority_only_orders_eligible_pending_work(run):
    gw.record_steering(run, 'Prefer the independent branch.', effect='priority', affected_nodes=['other'], priority=10)
    rows = [{'id': 'build', 'affordable': True}, {'id': 'other', 'affordable': True},
            {'id': 'child', 'affordable': False}]
    ordered = gw.prioritize_pending(run, rows)
    assert [r['id'] for r in ordered] == ['other', 'build', 'child']
    assert ordered[2]['affordable'] is False


def test_restart_rename_and_mirror_tampering_preserve_epoch(run):
    gw.record_steering(run, 'Context.', effect='note')
    (run / 'inputs/steering/0001.json').write_text('{}')
    renamed = run.with_name('renamed')
    run.rename(renamed)
    with pytest.raises(custody.CustodyError):
        gw.steering_state(renamed)
    custody.relocate(renamed, 'synthetic-study')
    assert gw.steering_state(renamed)['epoch'] == 1


@pytest.mark.parametrize('rung', ['dry', 'smoke', 'full', 'scan', 'science'])
def test_universal_launch_hook(run, rung):
    gw.record_steering(run, 'Veto this branch.', effect='veto', affected_nodes=['build'])
    assert any('veto' in e for e in gw.launch_errors(run, rung, ['inert'], {'node_id': 'child'}))


def test_pause_launch_race_serialized(run, monkeypatch):
    from ravel.workflow import graph_substrate as gs, agent_worker as aw
    monkeypatch.setattr(gs, 'stop', lambda *a, **kw: {})
    monkeypatch.setattr(aw, 'stop', lambda *a, **kw: {'verified_gone': True})
    entered, release, pause_started = threading.Event(), threading.Event(), threading.Event()
    def launch():
        with gw.steering_dispatch(run, 'other'):
            entered.set()
            assert release.wait(5)
    def pause():
        pause_started.set()
        return gw.record_steering(run, 'Pause.', effect='pause')
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(launch)
        assert entered.wait(5)
        b = pool.submit(pause)
        assert pause_started.wait(5)
        release.set()
        a.result(5); b.result(5)
    with pytest.raises(ValueError, match='paused'):
        with gw.steering_dispatch(run, 'other'):
            pytest.fail('dispatch started after pause')


def test_changed_amended_plan_reholds(run):
    event = gw.record_steering(run, 'Constraint.', effect='requirement', affected_nodes=['build'])
    path = amended(run)
    gw.ack_steering(run, event['event_id'], interpretation='Updated.', amended_plan=path)
    path.write_text('{"changed":true}')
    assert not gw.dispatch_permitted(run, 'build')[0]


def test_cli_policy_exact_file_and_typed_ack(run, capsys):
    source = run / 'policy-source.json'
    raw = json.dumps(policy(), indent=3) + '\n'
    source.write_text(raw)
    assert gw.main(['steer', 'policy', '--rundir', str(run), '--set', str(source)]) == 0
    event = json.loads(capsys.readouterr().out)
    assert gw.steering_state(run)['policy']['source_text'] == raw
    assert gw.main(['steer', 'ack', event['event_id'], '--rundir', str(run), '--interpretation', 'Applied.']) == 0


def test_cli_policy_flags(run):
    assert gw.main(['steer', 'policy', '--rundir', str(run), '--set', 'flags',
                    '--hard-ceiling', 'events=0', '--on-pause', 'cancel']) == 0
    assert gw.steering_state(run)['policy']['hard_ceilings']['events'] == 0


@pytest.mark.parametrize('action', ['note', 'require', 'redirect', 'veto', 'priority'])
def test_typed_commands(run, action, capsys):
    assert gw.main(['steer', action, '--rundir', str(run), '--text', 'Synthetic instruction.', '--affects', 'build']) == 0
    record = json.loads(capsys.readouterr().out)
    assert record['effect'] == ('requirement' if action == 'require' else action)


def test_typed_result_response(run, capsys):
    assert gw.main(['respond', 'reject', '--rundir', str(run), '--text', 'Revise the output.']) == 0
    assert json.loads(capsys.readouterr().out)['scientific_acceptance'] is False


def test_host_allows_ack_but_denies_machine_policy_setter():
    from ravel.workflow import host_gate
    for prefix in ('ravel gate-wiring', 'python -m ravel.workflow.gate_wiring', 'ravel'):
        assert host_gate.classify(prefix + ' steer ack steering-1 --rundir r --interpretation Read') == 'none'
        assert host_gate.classify(prefix + ' steer policy --rundir r --set flags') == 'approve_plan'
        assert host_gate.classify(prefix + ' respond accept --rundir r') == 'approve_plan'


def test_registered_checkin_presents_custody_policy(run):
    from ravel.validation.validate_checkin import with_registered_sections, registered_section_errors
    gw.set_steering_policy(run, policy(), source_text='Keep the declared ceiling.', authority='unknown')
    record = with_registered_sections({'kind': 'checkin1', 'sections': {}}, run)
    assert record['sections']['steering_policy']['source_text'] == 'Keep the declared ceiling.'
    record['sections']['steering_policy']['authority'] = 'human'
    assert any('steering_policy' in error for error in registered_section_errors(record, run))


def test_worker_drain_does_not_signal(run, monkeypatch):
    from ravel.workflow import agent_worker as aw, broker
    from ravel.workflow.state_io import atomic_json
    root = run.parent / 'worker-custody'
    monkeypatch.setattr(broker, 'custody', lambda p: root)
    atomic_json(root / 'processes.json', [{'status': 'running', 'verified_gone': False}])
    monkeypatch.setattr(aw, '_control', lambda *a: pytest.fail('drain must not signal workers'))
    assert aw.stop(run, drain=True)['draining']


def test_effect_scope_consults_parent_and_graph_dependencies(run):
    effects = run / 'effects'
    effects.mkdir()
    (run / 'graph_spec.json').write_text(json.dumps({'nodes': [{'id': 'build', 'depends_on': []},
                                                       {'id': 'task', 'depends_on': ['build']}]}))
    gw.record_steering(run, 'Veto branch.', effect='veto', affected_nodes=['build'])
    assert not gw.dispatch_permitted(effects, 'task')[0]


def test_authorized_spawn_guard_enforced_for_science(run, monkeypatch):
    from ravel.workflow import launch_authorization as la
    gw.record_steering(run, 'Veto branch.', effect='veto', affected_nodes=['build'])
    monkeypatch.setattr(la, '_authorized_popen_locked', lambda *a, **kw: pytest.fail('spawn reached'))
    with pytest.raises(ValueError, match='veto'):
        la.authorized_popen(run, 'science', ['inert'], context={'node_id': 'child'})


def test_parent_steering_reaches_prepared_child(run):
    child = run.parent / 'child-study'
    child.mkdir()
    gw.bind_steering_child(run, child, 'build')
    gw.record_steering(run, 'Veto parent branch.', effect='veto', affected_nodes=['build'])
    assert not gw.dispatch_permitted(child, 'worker')[0]
    assert gw.dispatch_permitted(run, 'other')[0]


def test_unbound_launch_cannot_bypass_scoped_hold(run):
    gw.record_steering(run, 'Hold branch.', effect='requirement', affected_nodes=['build'])
    assert not gw.dispatch_permitted(run, 'unknown-stage')[0]


@pytest.mark.parametrize('authority', ['delegated_machine', 'scripted_experiment'])
def test_science_approval_is_recorded_with_machine_authority(run, authority):
    gw.set_steering_policy(run, {**policy(), 'autonomy': 'bounded_delegated', 'signoff_steps': ['unrelated']},
                           source_text='Keep the bounds.', authority='unknown')
    event = gw.steering_records(run)[-1]
    gw.ack_steering(run, event['event_id'], interpretation='Policy applied.')
    (run / 'inputs/science-approval.json').write_text('{"approved":true}')
    assert not gw.dispatch_permitted(run, 'other')[0]
    record = gw.record_plan_approval(run, authority=authority)
    assert record['authority'] == authority
    assert gw.dispatch_permitted(run, 'other')[0]
    assert gw.steering_errors(run) == []


def test_instruction_fixture_is_embedded():
    from pathlib import Path
    from workflow_instruction_inventory_fixture import assert_live_steering_instruction
    assert_live_steering_instruction(Path(__file__).resolve().parents[2])


def test_graph_launch_consults_steering_before_build(run, monkeypatch):
    from ravel.workflow import graph_substrate as gs
    gw.record_steering(run, 'Veto branch.', effect='veto', affected_nodes=['build'])
    monkeypatch.setattr(gs, 'environment', lambda: None)
    monkeypatch.setattr(gs, '_scope_root', lambda root: root)
    monkeypatch.setattr(gs, '_context', lambda *a: pytest.fail('graph build reached'))
    with pytest.raises(ValueError, match='veto'):
        gs.run(run, 'synthetic-graph', {'node_id': 'child'})


def test_research_dispatch_consults_parent_before_admission(run, monkeypatch):
    from ravel.workflow import research_cycle as cycle
    gw.record_steering(run, 'Veto branch.', effect='veto', affected_nodes=['build'])
    monkeypatch.setattr(cycle, '_load', lambda *a: ({}, {}))
    monkeypatch.setattr(cycle, '_experiment_dispatch_admission', lambda *a: pytest.fail('child admission reached'))
    with pytest.raises(ValueError, match='veto'):
        cycle.run_experiment(run, 'child')


def test_scan_priority_reorders_pending_without_more_dispatch(run, monkeypatch):
    from types import SimpleNamespace
    from ravel.workflow import scan_orchestrator as scan
    event = gw.record_steering(run, 'Prefer independent work.', effect='priority', affected_nodes=['other'], priority=5)
    gw.ack_steering(run, event['event_id'], interpretation='Queue updated within budget.')
    points = [{'tag': 'build'}, {'tag': 'other'}]
    monkeypatch.setattr(scan, 'load_manifest', lambda *a: (run, {'points': points}))
    monkeypatch.setattr(scan, 'point_status', lambda *a: ('pending', None))
    launched = []
    monkeypatch.setattr(scan, 'launch_point', lambda point, *a, **kw: launched.append(point['tag']))
    scan.cmd_launch(SimpleNamespace(scandir=run, max=1, backend='container', force=False, go=False))
    assert launched == ['other']


def test_worker_launch_consults_steering_before_spawn(run, monkeypatch):
    from ravel.workflow import agent_worker as aw, sandbox
    from test_agent_worker import spec
    gw.record_steering(run, 'Veto branch.', effect='veto', affected_nodes=['build'])
    monkeypatch.setattr(sandbox, 'available', lambda: 'inert')
    monkeypatch.setattr(aw.subprocess, 'Popen', lambda *a, **kw: pytest.fail('spawn reached'))
    with pytest.raises(ValueError, match='veto'):
        aw.launch(run, spec('child'), launch_spec={'argv': ['/inert']}, wait=False)


def test_veto_keeps_original_descendants_after_plan_edit(run):
    gw.record_steering(run, 'Veto branch.', effect='veto', affected_nodes=['build'])
    (run / 'inputs/plan.json').write_text(json.dumps({'nodes': [{'id': n} for n in ['build', 'child', 'other']], 'edges': []}))
    assert not gw.dispatch_permitted(run, 'child')[0]


def test_resume_preserves_newer_independent_stop(run, monkeypatch):
    from ravel.workflow import graph_substrate as gs, agent_worker as aw
    from ravel.workflow.state_io import atomic_json
    monkeypatch.setattr(aw, 'stop', lambda *a, **kw: {})
    gw.record_steering(run, 'Pause study.', effect='pause')
    atomic_json(run / gs.STOP, {'reason': 'independent stop', 'now': True})
    resume = gw.record_steering(run, 'Continue.', effect='resume')
    gw.ack_steering(run, resume['event_id'], interpretation='Resume steering pause only.')
    assert (run / gs.STOP).exists()


def test_new_process_reads_relocated_epoch(run):
    import subprocess
    import sys
    gw.record_steering(run, 'Retained context.', effect='note')
    renamed = run.with_name('relocated-study')
    run.rename(renamed)
    custody.relocate(renamed, 'synthetic-study')
    child = subprocess.run([sys.executable, '-B', '-m', 'ravel.workflow.gate_wiring',
                            'steer', 'state', '--rundir', str(renamed)],
                           text=True, capture_output=True, timeout=20)
    assert child.returncode == 0, child.stderr
    assert json.loads(child.stdout)['epoch'] == 1


def test_owned_native_launch_registers_for_pause_cancel(run, monkeypatch):
    from types import SimpleNamespace
    from ravel.workflow import launch_authorization as la, graph_substrate as gs
    process = SimpleNamespace(pid=424242)
    monkeypatch.setattr(la, '_authorized_popen_locked', lambda *a, **kw: process)
    registered = []
    monkeypatch.setattr(gs, '_register_process', lambda root, record: registered.append(record))
    assert la.authorized_popen(run, 'full', ['inert'], context={'node_id': 'other'}, start_new_session=True) is process
    assert registered[0]['pgid'] == 424242 and registered[0]['state'] == 'running'


def test_pause_observation_includes_native_registered_work(run, monkeypatch):
    from ravel.workflow import graph_substrate as gs, agent_worker as aw
    monkeypatch.setattr(gs, 'stop', lambda *a, **kw: {})
    monkeypatch.setattr(aw, 'stop', lambda *a, **kw: {})
    monkeypatch.setattr(gs, 'status', lambda *a: {'holder': None, 'processes': [{'state': 'running', 'role': 'supervised-launch'}]})
    monkeypatch.setattr(aw, 'processes', lambda *a: [])
    gw.record_steering(run, 'Pause.', effect='pause')
    assert gw.steering_state(run)['pause_status'] == 'draining'


def test_priority_for_other_work_preserves_ordinary_research_selection(tmp_path):
    from ravel.workflow import research_cycle as cycle
    from test_research_cycle import contract, propose, experiment
    root = tmp_path / 'research-study'
    cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True)
    propose(tmp_path, root)
    cycle.design(root, experiment(tmp_path, 'later', grouped=False))
    cycle.design(root, experiment(tmp_path, 'earlier', grouped=False))
    before = cycle.select(root)['selected']
    event = gw.record_steering(root, 'Prioritize another branch.', effect='priority', affected_nodes=['other-work'], priority=5)
    gw.ack_steering(root, event['event_id'], interpretation='Priority recorded for that branch.')
    assert cycle.select(root)['selected'] == before


def test_scientific_plan_automatically_presents_steering_policy(tmp_path):
    from ravel.workflow import science
    from test_research_cycle import specification
    root = tmp_path / 'scientific-study'
    source = specification(tmp_path, 'supplied-source', grouped=False)
    gw.set_steering_policy(root, policy(), source_text='Keep the declared bounds.', authority='unknown')
    science.plan(root, source['path'])
    checkin = json.loads((root / 'inputs/checkin1.json').read_text())
    assert checkin['sections']['steering_policy']['source_text'] == 'Keep the declared bounds.'
    assert 'Keep the declared bounds.' in (root / 'CHECKIN1.md').read_text()
