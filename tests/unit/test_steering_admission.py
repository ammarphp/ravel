"""Steering admission at the real launch, approval and command entry points.

Each test drives the path a launch or an operator command takes (the launch authorization, the
stage supervisor, a backend submission, a graph node start or the command line) with synthetic
plans and inert launch seams.
"""
import json

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


def refused_launch(run, monkeypatch, node_id, match):
    """The launch authorization refuses before its spawn step is reached."""
    from ravel.workflow import launch_authorization as la
    monkeypatch.setattr(la, '_authorized_popen_locked', lambda *a, **kw: pytest.fail('spawn reached'))
    with pytest.raises(ValueError, match=match):
        la.authorized_popen(run, 'full', ['inert'], context={'node_id': node_id})


def admitted_launch(run, monkeypatch, node_id):
    from types import SimpleNamespace
    from ravel.workflow import launch_authorization as la
    process = SimpleNamespace(pid=424242)
    monkeypatch.setattr(la, '_authorized_popen_locked', lambda *a, **kw: process)
    assert la.authorized_popen(run, 'full', ['inert'], context={'node_id': node_id}) is process


# ---------------------------------------------------------------- malformed plan descriptors

def set_contract(run, value):
    (run / 'inputs/task_contract.json').write_text(value if isinstance(value, str) else json.dumps(value))


@pytest.mark.parametrize('node_id', ['build', None, 'not-a-plan-node'])
@pytest.mark.parametrize('descriptor', ['malformed', 7, ['inputs/plan.json'], {'path': 3}, {'sha256': 'x'},
                                        {'path': 'inputs/absent-plan.json'}, {'path': '../outside.json'}])
def test_malformed_plan_descriptor_refuses_the_launch(run, monkeypatch, node_id, descriptor):
    set_contract(run, {'run_id': 'synthetic-study', 'request_plan': descriptor})
    allowed, reason = gw.dispatch_permitted(run, node_id)
    assert not allowed and 'plan unreadable' in reason
    assert any('steering_refused' in e for e in gw.launch_errors(run, 'full', ['inert'], {'node_id': node_id}))
    refused_launch(run, monkeypatch, node_id, 'plan unreadable')


@pytest.mark.parametrize('contract', ['{not json', '[]', '"text"'])
def test_unreadable_contract_refuses_the_launch(run, monkeypatch, contract):
    set_contract(run, contract)
    refused_launch(run, monkeypatch, 'build', 'unreadable')


@pytest.mark.parametrize('node_id', ['build', None, 'not-a-plan-node'])
@pytest.mark.parametrize('plan', [
    {'nodes': [{'id': 'build'}], 'edges': ['bad']},
    {'nodes': 1, 'edges': []},
    {'nodes': [{'id': 'build'}, 'text'], 'edges': []},
    {'nodes': [{'id': ''}], 'edges': []},
    {'nodes': [{'name': 'build'}], 'edges': []},
    {'nodes': [{'id': 'build'}], 'edges': {'from': 'build', 'to': 'child'}},
    {'nodes': [{'id': 'build'}], 'edges': [{'from': {'ref': 3}, 'to': 'build'}]},
    {'nodes': [{'id': 'build'}], 'edges': [{'from': 'build'}]},
    ['nodes'],
])
def test_malformed_plan_structure_refuses_without_a_known_node(run, monkeypatch, node_id, plan):
    (run / 'inputs/plan.json').write_text(json.dumps(plan))
    allowed, reason = gw.dispatch_permitted(run, node_id)
    assert not allowed and 'plan unreadable' in reason
    refused_launch(run, monkeypatch, node_id, 'plan unreadable')


@pytest.mark.parametrize('graph', [{'nodes': 'text'}, {'nodes': [{'id': 'task', 'depends_on': 'build'}]},
                                   {'nodes': [{'id': 'task', 'depends_on': [3]}]}, ['task']])
def test_malformed_graph_specification_refuses_the_launch(run, monkeypatch, graph):
    (run / 'graph_spec.json').write_text(json.dumps(graph))
    refused_launch(run, monkeypatch, None, 'plan unreadable')


def test_valid_plan_without_a_descriptor_or_edges_is_admitted(run, monkeypatch):
    admitted_launch(run, monkeypatch, 'build')
    (run / 'inputs/plan.json').write_text(json.dumps({'nodes': [{'id': 'build'}]}))
    admitted_launch(run, monkeypatch, 'build')
    set_contract(run, {'run_id': 'synthetic-study'})
    admitted_launch(run, monkeypatch, None)


@pytest.mark.parametrize('plan', [{'nodes': [{'id': 'build'}], 'edges': ['bad']}, {'nodes': 1, 'edges': []}])
def test_branch_veto_command_on_a_malformed_plan_exits_with_a_typed_refusal(run, plan, capsys):
    (run / 'inputs/plan.json').write_text(json.dumps(plan))
    code = gw.main(['steer', 'veto', '--rundir', str(run), '--text', 'Stop this branch.', '--affects', 'build'])
    captured = capsys.readouterr()
    assert code == 2
    assert 'plan unreadable' in captured.err and 'Traceback' not in captured.err
    assert custody.rows(run, 'steering') == []
    # The study-wide control stays available while the plan is repaired.
    assert gw.main(['steer', 'veto', '--rundir', str(run), '--text', 'Stop the study.']) == 0
    assert not gw.dispatch_permitted(run, 'build')[0]


# ---------------------------------------------------------------- scope increases and signoff steps

def bounded(run, signoff):
    configured = gw.set_steering_policy(run, {**policy(), 'autonomy': 'bounded_delegated', 'signoff_steps': signoff},
                                        source_text='Delegate inside these bounds.')
    gw.ack_steering(run, configured['event_id'], interpretation='Policy retained.')
    (run / 'inputs/checkin1_approval.json').write_text('{"approved":"initial"}')
    gw.record_plan_approval(run)


def test_requirement_declared_as_a_scope_increase_holds_for_reapproval(run, monkeypatch, capsys):
    (run / 'inputs/checkin1_approval.json').write_text('{"approved":"initial"}')
    assert gw.main(['steer', 'require', '--rundir', str(run), '--text', 'Also cover the wider range.',
                    '--affects', 'build', '--scope-increase']) == 0
    event = json.loads(capsys.readouterr().out)
    assert event['requires_reapproval'] is True and event['approval_sha256_at_event'] is not None
    gw.ack_steering(run, event['event_id'], interpretation='Plan revised.', amended_plan=amended(run))
    # The acknowledgement reconciles the requirement; it never approves the larger scope.
    refused_launch(run, monkeypatch, 'child', 'reapproval')
    assert gw.steering_errors(run)
    (run / 'inputs/checkin1_approval.json').write_text('{"approved":"revised"}')
    gw.record_plan_approval(run)
    admitted_launch(run, monkeypatch, 'child')


def test_scope_increase_and_within_scope_are_exclusive_on_the_command_line(run, capsys):
    with pytest.raises(SystemExit):
        gw.main(['steer', 'redirect', '--rundir', str(run), '--text', 'Change course.', '--within-scope',
                 '--scope-increase'])
    capsys.readouterr()
    assert custody.rows(run, 'steering') == []


@pytest.mark.parametrize('effect', ['note', 'priority', 'pause', 'veto', 'requirement'])
def test_declared_scope_increase_requires_reapproval_for_every_effect(run, monkeypatch, effect):
    from ravel.workflow import graph_substrate as gs, agent_worker as aw
    monkeypatch.setattr(gs, 'stop', lambda *a, **kw: {})
    monkeypatch.setattr(aw, 'stop', lambda *a, **kw: {})
    event = gw.record_steering(run, 'Enlarge the study.', effect=effect, affected_nodes=['build'], scope_increase=True)
    assert event['requires_reapproval'] is True
    assert gw.steering_errors(run)


@pytest.mark.parametrize('authority', ['delegated_machine', 'scripted_experiment'])
def test_machine_reapproval_refused_for_a_signoff_descendant_added_by_the_amended_plan(run, monkeypatch, authority):
    bounded(run, ['final-fit'])
    event = gw.record_steering(run, 'Extend this branch.', effect='redirect', affected_nodes=['build'])
    # The amended plan adds a descendant of the redirected node whose operation needs signoff.
    plan = json.loads((run / 'inputs/plan.json').read_text())
    plan['nodes'].append({'id': 'added', 'operation': 'final-fit'})
    plan['edges'].append({'from': {'ref': 'child'}, 'to': {'ref': 'added'}})
    (run / 'inputs/plan.json').write_text(json.dumps(plan))
    gw.ack_steering(run, event['event_id'], interpretation='Plan revised.', amended_plan=amended(run))
    (run / 'inputs/checkin1_approval.json').write_text('{"approved":"revised"}')
    before = custody.rows(run, 'steering')
    with pytest.raises(ValueError, match='authority'):
        gw.record_plan_approval(run, authority=authority)
    assert custody.rows(run, 'steering') == before
    custody.append(run, 'steering', {'event': 'approval', 'approval_sha256': gw._approval_digest(run),
                                     'authority': authority})
    refused_launch(run, monkeypatch, 'added', 'reapproval')
    refused_launch(run, monkeypatch, 'child', 'reapproval')
    assert gw.steering_errors(run)


def test_redirect_event_alone_covers_a_signoff_descendant_the_amended_plan_adds(run):
    """The study-wide policy event also holds this case on the launch path; the redirect event
    itself must cover the added descendant, so the hold does not depend on another event."""
    bounded(run, ['final-fit'])
    event = gw.record_steering(run, 'Extend this branch.', effect='redirect', affected_nodes=['build'])
    assert 'final-fit' not in event['reapproval_steps']
    plan = json.loads((run / 'inputs/plan.json').read_text())
    plan['nodes'].append({'id': 'added', 'operation': 'final-fit', 'rung': 'full'})
    plan['edges'].append({'from': {'ref': 'child'}, 'to': {'ref': 'added'}})
    (run / 'inputs/plan.json').write_text(json.dumps(plan))
    rows = custody.rows(run, 'steering')
    recorded = next(r['record']['record'] for r in rows if r['record'].get('event') == 'steering'
                    and r['record']['record']['event_id'] == event['event_id'])
    assert {'added', 'final-fit', 'full'} <= gw._reapproval_steps(run, recorded)
    assert not gw._reapproval_authority_permitted(run, rows, recorded, 'delegated_machine')
    assert gw._reapproval_authority_permitted(run, rows, recorded, 'unknown')


def test_machine_reapproval_still_admitted_when_no_step_needs_signoff(run, monkeypatch):
    bounded(run, ['final-fit'])
    event = gw.record_steering(run, 'Extend this branch.', effect='redirect', affected_nodes=['build'])
    plan = json.loads((run / 'inputs/plan.json').read_text())
    plan['nodes'].append({'id': 'added', 'operation': 'ordinary-step'})
    plan['edges'].append({'from': {'ref': 'child'}, 'to': {'ref': 'added'}})
    (run / 'inputs/plan.json').write_text(json.dumps(plan))
    gw.ack_steering(run, event['event_id'], interpretation='Plan revised.', amended_plan=amended(run))
    (run / 'inputs/checkin1_approval.json').write_text('{"approved":"revised"}')
    assert gw.record_plan_approval(run, authority='delegated_machine')['authority'] == 'delegated_machine'
    admitted_launch(run, monkeypatch, 'added')


def science_study(tmp_path, signoff):
    """A scientific study directory: a science plan and no request-plan graph."""
    root = tmp_path / 'science-study'
    (root / 'inputs').mkdir(parents=True)
    (root / 'inputs/science.json').write_text(json.dumps({'mode': 'synthetic-operation'}))
    (root / 'inputs/science-plan.json').write_text(json.dumps({
        'mode': 'synthetic-operation', 'stages': [{'stage': 'science', 'command': ['inert']}]}))
    configured = gw.set_steering_policy(root, {**policy(), 'autonomy': 'bounded_delegated', 'signoff_steps': signoff},
                                        source_text='Delegate inside these bounds.')
    gw.ack_steering(root, configured['event_id'], interpretation='Policy retained.')
    (root / 'inputs/science-approval.json').write_text('{"approved":"initial"}')
    gw.record_plan_approval(root)
    return root


@pytest.mark.parametrize('signoff', ['synthetic-operation', 'science'])
@pytest.mark.parametrize('affects', [[], ['science']])
def test_science_plan_operation_and_rung_signoff_holds_machine_reapproval(tmp_path, monkeypatch, signoff, affects):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    root = science_study(tmp_path, [signoff])
    event = gw.record_steering(root, 'Extend the study.', effect='redirect', affected_nodes=affects)
    gw.ack_steering(root, event['event_id'], interpretation='Plan revised.', amended_plan=amended(root))
    (root / 'inputs/science-approval.json').write_text('{"approved":"revised"}')
    with pytest.raises(ValueError, match='authority'):
        gw.record_plan_approval(root, authority='delegated_machine')
    refused_launch(root, monkeypatch, 'science', 'reapproval')
    gw.record_plan_approval(root)  # operator text reapproves
    admitted_launch(root, monkeypatch, 'science')


def test_science_plan_without_matching_signoff_admits_bounded_machine_reapproval(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    root = science_study(tmp_path, ['another-operation'])
    event = gw.record_steering(root, 'Extend the study.', effect='redirect')
    gw.ack_steering(root, event['event_id'], interpretation='Plan revised.', amended_plan=amended(root))
    (root / 'inputs/science-approval.json').write_text('{"approved":"revised"}')
    gw.record_plan_approval(root, authority='delegated_machine')
    admitted_launch(root, monkeypatch, 'science')


# ---------------------------------------------------------------- steering custody must exist

@pytest.fixture
def machine_rules(tmp_path, monkeypatch):
    """The machine lock domain's rules at a temporary location: no test-domain admission."""
    from ravel.workflow import machine_lease as ml
    monkeypatch.delenv(ml.TEST_ENV, raising=False)
    monkeypatch.setattr(ml, '_LOCATION', tmp_path / 'machine')
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    assert ml.domain() == 'machine'


def unbound(tmp_path, name='unbound'):
    root = tmp_path / name
    (root / 'inputs').mkdir(parents=True)
    (root / 'inputs/task_contract.json').write_text('{}')
    return root


def quiet_stops(monkeypatch):
    from ravel.workflow import graph_substrate as gs, agent_worker as aw
    monkeypatch.setattr(gs, 'stop', lambda *a, **kw: {})
    monkeypatch.setattr(aw, 'stop', lambda *a, **kw: {})


def test_run_without_any_steering_custody_is_refused_at_every_launch_path(tmp_path, monkeypatch, machine_rules):
    from ravel.workflow import agent_worker as aw, sandbox, graph_substrate as gs
    from test_agent_worker import spec
    root = unbound(tmp_path)
    allowed, reason = gw.dispatch_permitted(root, 'build')
    assert not allowed and 'custody is absent' in reason
    assert any('custody is absent' in e for e in gw.launch_errors(root, 'full', ['inert'], {'node_id': 'build'}))
    refused_launch(root, monkeypatch, 'build', 'custody is absent')
    with pytest.raises(ValueError, match='custody is absent'):
        with gw.steering_dispatch(root, None):
            pytest.fail('dispatch started without custody')
    monkeypatch.setattr(sandbox, 'available', lambda: 'inert')
    monkeypatch.setattr(aw.subprocess, 'Popen', lambda *a, **kw: pytest.fail('spawn reached'))
    with pytest.raises(ValueError, match='custody is absent'):
        aw.launch(root, spec('child'), launch_spec={'argv': ['/inert']}, wait=False)
    monkeypatch.setattr(gs, 'environment', lambda: None)
    monkeypatch.setattr(gs, '_context', lambda *a: pytest.fail('graph build reached'))
    with pytest.raises(ValueError, match='custody is absent'):
        gs.run(root, 'synthetic-graph', {'node_id': 'child'})


def test_operator_initialization_command_admits_a_prepared_run(tmp_path, monkeypatch, machine_rules, capsys):
    root = unbound(tmp_path)
    assert gw.main(['steer', 'state', '--rundir', str(root)]) == 2
    assert 'steer init' in capsys.readouterr().err
    assert gw.main(['steer', 'init', '--rundir', str(root)]) == 0
    assert json.loads(capsys.readouterr().out)['epoch'] == 0
    assert gw.main(['steer', 'init', '--rundir', str(root)]) == 0  # idempotent
    assert [r['record']['event'] for r in custody.rows(root, 'steering')] == ['journal_init']
    admitted_launch(root, monkeypatch, 'build')
    assert gw.main(['steer', 'init', '--rundir', str(tmp_path / 'absent')]) == 2


def test_agent_sessions_are_denied_the_initialization_command():
    from ravel.workflow import host_gate
    for prefix in ('ravel gate-wiring', 'python -m ravel.workflow.gate_wiring', 'ravel'):
        assert host_gate.classify(prefix + ' steer init --rundir r') == 'approve_plan'


@pytest.mark.parametrize('effect', ['veto', 'redirect', 'pause'])
def test_renamed_run_with_deleted_mirrors_is_refused(tmp_path, monkeypatch, machine_rules, effect):
    import shutil
    quiet_stops(monkeypatch)
    root = unbound(tmp_path)
    gw.initialize_steering(root, route='operator')
    gw.record_steering(root, 'Hold this work.', effect=effect, affected_nodes=['build'])
    shutil.rmtree(root / 'inputs/steering')
    moved = root.with_name('moved')
    root.rename(moved)
    allowed, reason = gw.dispatch_permitted(moved, 'build')
    assert not allowed and 'custody is absent' in reason
    refused_launch(moved, monkeypatch, 'other', 'custody is absent')
    # Steering a directory that holds run content cannot start a second journal for it.
    with pytest.raises(custody.CustodyError, match='custody is absent'):
        gw.record_steering(moved, 'New context cannot reset custody.', effect='note')


def test_copied_run_is_refused_while_the_original_keeps_its_steering(tmp_path, monkeypatch, machine_rules):
    import shutil
    quiet_stops(monkeypatch)
    root = unbound(tmp_path)
    gw.initialize_steering(root, route='operator')
    gw.record_steering(root, 'Pause the study.', effect='pause')
    copy = tmp_path / 'copy'
    shutil.copytree(root, copy)
    refused_launch(copy, monkeypatch, None, 'custody is missing')
    shutil.rmtree(copy / 'inputs/steering')
    refused_launch(copy, monkeypatch, None, 'custody is absent')
    refused_launch(root, monkeypatch, None, 'paused')


@pytest.mark.parametrize('effect, node', [('veto', ['build']), ('pause', [])])
@pytest.mark.parametrize('rules', ['test-domain', 'machine'])
def test_renamed_child_keeps_the_parent_veto_and_pause(tmp_path, monkeypatch, request, effect, node, rules):
    if rules == 'machine':
        request.getfixturevalue('machine_rules')
    else:
        monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    quiet_stops(monkeypatch)
    parent = unbound(tmp_path, 'parent')
    gw.initialize_steering(parent, route='research-study')
    child = tmp_path / 'exp1'
    (child / 'inputs').mkdir(parents=True)
    (child / 'inputs/task_contract.json').write_text('{}')
    gw.bind_steering_child(parent, child, 'build')
    assert json.loads((child / 'inputs/steering/parent-binding.json').read_text())['grants_authority'] is False
    admitted_launch(child, monkeypatch, None)
    gw.record_steering(parent, 'Stop this work.', effect=effect, affected_nodes=node)
    refused_launch(child, monkeypatch, None, 'parent steering')
    moved = child.with_name('exp1-copy')
    child.rename(moved)
    allowed, reason = gw.dispatch_permitted(moved, None)
    assert not allowed and 'custody' in reason
    refused_launch(moved, monkeypatch, None, 'custody')
    with pytest.raises(ValueError, match='custody'):
        with gw.steering_dispatch(moved, None):
            pytest.fail('a moved child launched outside its parent binding')
    # The parent does not rebind a child whose custody was lost.
    with pytest.raises(custody.CustodyError, match='custody is missing'):
        gw.bind_steering_child(parent, moved, 'build')


def test_renamed_parent_with_deleted_mirrors_is_refused(tmp_path, monkeypatch, machine_rules):
    import shutil
    quiet_stops(monkeypatch)
    parent = unbound(tmp_path, 'parent')
    gw.initialize_steering(parent, route='research-study')
    gw.record_steering(parent, 'Stop this branch.', effect='veto', affected_nodes=['build'])
    shutil.rmtree(parent / 'inputs/steering')
    moved = parent.with_name('parent-moved')
    parent.rename(moved)
    refused_launch(moved, monkeypatch, 'build', 'custody is absent')


def test_mirror_of_any_kind_without_custody_is_refused_in_the_test_domain(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    root = unbound(tmp_path)
    (root / 'inputs/steering').mkdir()
    (root / 'inputs/steering/notes.txt').write_text('left behind')
    refused_launch(root, monkeypatch, 'build', 'custody is missing')
    with pytest.raises(custody.CustodyError, match='custody is missing'):
        gw.initialize_steering(root, route='operator')


def test_steering_before_a_run_exists_starts_its_journal(tmp_path, monkeypatch, machine_rules):
    root = tmp_path / 'planned-later'
    event = gw.set_steering_policy(root, policy(), source_text='Keep the declared bounds.')
    gw.ack_steering(root, event['event_id'], interpretation='Policy retained.')
    assert gw.steering_state(root)['policy']['source_text'] == 'Keep the declared bounds.'


def test_run_initialization_snapshot_is_an_initialization_record(tmp_path, monkeypatch, machine_rules):
    root = tmp_path / 'released'
    (root / 'inputs').mkdir(parents=True)
    (root / 'inputs/task_contract.json').write_text(json.dumps({'agent_layer_epoch': 2}))
    refused_launch(root, monkeypatch, None, 'custody is absent')
    custody.record_input_snapshot(root, 'run_init')
    admitted_launch(root, monkeypatch, None)


def test_policy_presentation_tolerates_a_location_without_custody(tmp_path, machine_rules):
    assert gw.checkin_policy_section({'base_dir': tmp_path / 'not-a-run'}) is None
    assert gw.steering_policy(unbound(tmp_path)) is None
    with pytest.raises(custody.CustodyError):
        gw.steering_state(tmp_path / 'unbound')


def test_run_creation_commands_record_the_journal(tmp_path, monkeypatch, machine_rules):
    """Run, study, research, graph and scan directories RAVEL creates are admitted without an operator step."""
    from ravel import cli
    from ravel.workflow import agent_graph, research_cycle as cycle, science
    from test_research_cycle import contract, specification

    def routes(root):
        return [r['record'].get('route') for r in custody.rows(root, 'steering') if r['record']['event'] == 'journal_init']
    monkeypatch.chdir(tmp_path)
    run = tmp_path / 'initiated'
    assert cli.main(['initiate', '--prompt', 'Summarize the published limits on a synthetic scalar.',
                     '--out', str(run)]) == 0
    assert routes(run) == ['run-initialization'] and gw.dispatch_permitted(run, None)[0]
    study = tmp_path / 'scientific-study'
    science.plan(study, specification(tmp_path, 'supplied-source', grouped=False)['path'])
    assert routes(study) == ['study-plan'] and gw.dispatch_permitted(study, 'science')[0]
    research = tmp_path / 'research-study'
    cycle.create(research, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True)
    assert routes(research) == ['research-study'] and gw.dispatch_permitted(research, 'later')[0]
    monkeypatch.setattr(agent_graph, 'validate', lambda spec: spec)
    monkeypatch.setattr(agent_graph, 'status', lambda root: {})
    graph = tmp_path / 'graph-root'
    agent_graph.create(graph, {'graph_id': 'synthetic', 'nodes': [{'id': 'only'}]})
    assert routes(graph) == ['graph-scope'] and gw.dispatch_permitted(graph, 'only')[0]


def test_graph_scope_created_by_the_substrate_is_initialized_and_an_existing_one_is_not(tmp_path, monkeypatch, machine_rules):
    from ravel.workflow import graph_substrate as gs

    class Reached(Exception):
        pass

    def reached(*a):
        raise Reached()
    monkeypatch.setattr(gs, 'environment', lambda: None)
    monkeypatch.setattr(gs, '_context', reached)
    fresh = tmp_path / 'fresh-scope'
    with pytest.raises(Reached):
        gs.run(fresh, 'synthetic-graph', {'node_id': 'child'})
    assert [r['record']['route'] for r in custody.rows(fresh, 'steering')] == ['graph-scope']
    existing = unbound(tmp_path, 'existing-scope')
    with pytest.raises(ValueError, match='custody is absent'):
        gs.run(existing, 'synthetic-graph', {'node_id': 'child'})
    assert custody.rows(existing, 'steering') == []


def test_scan_plan_records_the_scan_journal(tmp_path, monkeypatch, machine_rules):
    from types import SimpleNamespace
    from ravel.workflow import scan_orchestrator as scan
    points = [{'mass': 1.0}]
    monkeypatch.setattr(scan, 'load_spec', lambda path: {
        'template_toml': str(tmp_path / 'template.toml'), 'run_root': str(tmp_path / 'runs'), 'run_prefix': 'synthetic',
        'name': 'synthetic', 'axes': [], 'quantities': [], 'datasets': [], 'output': {}, 'subst': {}})
    monkeypatch.setattr(scan, 'enumerate_points', lambda spec: points)
    monkeypatch.setattr(scan, 'substitute_toml', lambda text, spec, point: text)
    monkeypatch.setattr(scan, 'point_tag', lambda point: 'p1')
    (tmp_path / 'template.toml').write_text('value = 1\n')
    scan.cmd_plan(SimpleNamespace(spec=str(tmp_path / 'scan.json'), dry_run=False))
    directory = tmp_path / 'runs/synthetic_SCAN'
    assert [r['record']['route'] for r in custody.rows(directory, 'steering')] == ['scan-plan']
    assert gw.dispatch_permitted(directory, 'p1')[0]


# ---------------------------------------------------------------- stale acknowledgements and recorded-only policy fields

def test_acknowledging_an_older_event_needs_the_epoch_of_the_view_it_answers(run, capsys):
    first = gw.record_steering(run, 'First instruction.', effect='note')
    second = gw.record_steering(run, 'Later instruction.', effect='note')
    # An answer prepared before the later instruction arrived must not pass without saying which view it saw.
    assert gw.main(['steer', 'ack', first['event_id'], '--rundir', str(run), '--interpretation', 'Read.']) == 2
    assert 'expected-epoch' in capsys.readouterr().err
    with pytest.raises(ValueError, match='stale'):
        gw.ack_steering(run, first['event_id'], interpretation='Read.', expected_epoch=1)
    assert first['event_id'] in gw.steering_state(run)['pending_ack']
    assert gw.main(['steer', 'ack', first['event_id'], '--rundir', str(run), '--interpretation', 'Read both.',
                    '--expected-epoch', '2']) == 0
    # The newest event is answered without an epoch, as before.
    gw.ack_steering(run, second['event_id'], interpretation='Read.')
    assert gw.steering_state(run)['pending_ack'] == []


def test_policy_presentation_says_which_fields_steering_enforces(run):
    gw.set_steering_policy(run, {**policy(), 'hard_ceilings': {'events': 0}}, source_text='No events at all.')
    text = gw.render_steering_policy(run)
    assert 'Enforced by steering: autonomy, signoff_steps, on_pause' in text
    assert 'Recorded for the plan, not enforced by steering: checkin_thresholds, hard_ceilings' in text
