"""Steering at the stage supervisor: a stage is admitted or refused by the plan node that owns it.

The supervisor runs inert commands through its direct launch route in the test lock domain.
"""
import json
import sys

import pytest

from ravel.workflow import gate_wiring as gw, stage_supervisor as ss


@pytest.fixture
def study(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    root = tmp_path / 'graph-study'
    root.mkdir()
    # The plan binds each stage name to the node that owns it; ``other`` is an independent branch.
    (root / 'graph_spec.json').write_text(json.dumps({'nodes': [
        {'id': 'build', 'depends_on': [], 'stage': {'name': 'shower'}},
        {'id': 'child', 'depends_on': ['build'], 'stage': {'name': 'fit'}},
        {'id': 'other', 'depends_on': [], 'stage': {'name': 'detector'}}]}))
    return root


def supervised(root, stage, **options):
    return ss.supervise(stage, root, 0, f'logs/{stage}.log', [sys.executable, '-c', 'print("ran")'],
                        cwd=str(root), kill_secs=30, poll=0.02, grace=0.5, _engineering_only=True, **options)


def ran(root, stage):
    log = root / f'logs/{stage}.log'
    return log.is_file() and 'ran' in log.read_text()


def test_stage_of_an_unaffected_branch_runs_under_a_veto_elsewhere(study):
    gw.record_steering(study, 'Stop the independent branch.', effect='veto', affected_nodes=['other'])
    assert supervised(study, 'shower') == 0
    assert ran(study, 'shower')
    assert supervised(study, 'fit') == 0
    assert ran(study, 'fit')


def test_stage_of_the_vetoed_branch_is_still_refused(study):
    gw.record_steering(study, 'Stop the independent branch.', effect='veto', affected_nodes=['other'])
    assert supervised(study, 'detector') != 0
    assert not ran(study, 'detector')


def test_stage_below_a_vetoed_ancestor_is_refused_by_its_owning_node(study):
    gw.record_steering(study, 'Stop this branch.', effect='veto', affected_nodes=['build'])
    for stage in ('shower', 'fit'):
        assert supervised(study, stage) != 0
        assert not ran(study, stage)
    assert supervised(study, 'detector') == 0


def test_stage_no_plan_node_owns_stays_refused_while_any_branch_is_blocked(study):
    gw.record_steering(study, 'Stop the independent branch.', effect='veto', affected_nodes=['other'])
    assert supervised(study, 'unmapped') != 0
    assert not ran(study, 'unmapped')


def test_stage_two_plan_nodes_claim_stays_refused_while_any_branch_is_blocked(study):
    spec = json.loads((study / 'graph_spec.json').read_text())
    spec['nodes'].append({'id': 'second', 'depends_on': [], 'stage': {'name': 'shower'}})
    (study / 'graph_spec.json').write_text(json.dumps(spec))
    gw.record_steering(study, 'Stop the independent branch.', effect='veto', affected_nodes=['other'])
    assert supervised(study, 'shower') != 0
    assert not ran(study, 'shower')


def test_declared_plan_node_must_agree_with_the_plan(study):
    gw.record_steering(study, 'Stop this branch.', effect='veto', affected_nodes=['build'])
    # Naming an unaffected node for a stage the plan gives to the vetoed one is refused.
    with pytest.raises(ValueError, match='plan node'):
        supervised(study, 'shower', node_id='other')
    assert not ran(study, 'shower')
    assert supervised(study, 'detector', node_id='other') == 0


def test_launch_context_carries_the_owning_plan_node(study, monkeypatch):
    seen = []
    real = gw.steering_dispatch
    monkeypatch.setattr(gw, 'steering_dispatch', lambda root, node=None: seen.append(node) or real(root, node))
    assert supervised(study, 'shower') == 0
    assert seen == ['build']
    assert gw.launch_node(study, 'shower') == 'build'
    assert gw.launch_node(study, 'build') == 'build'
    assert gw.launch_node(study, 'unmapped') is None


def test_launch_authorization_resolves_a_stage_name_to_its_node(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from ravel.workflow import launch_authorization as la, rdj_custody as custody
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    root = tmp_path / 'study'
    (root / 'inputs').mkdir(parents=True)
    (root / 'inputs/task_contract.json').write_text(json.dumps({
        'run_id': 'synthetic-study', 'request_plan': {'path': 'inputs/plan.json'}}))
    (root / 'inputs/plan.json').write_text(json.dumps({
        'nodes': [{'id': 'build', 'stage': {'name': 'shower'}}, {'id': 'other', 'stage': {'name': 'detector'}}],
        'edges': []}))
    custody.bind_run(root, 'synthetic-study')
    gw.record_steering(root, 'Stop the independent branch.', effect='veto', affected_nodes=['other'])
    process = SimpleNamespace(pid=424242)
    monkeypatch.setattr(la, '_authorized_popen_locked', lambda *a, **kw: process)
    assert la.authorized_popen(root, 'full', ['inert'], context={'stage': 'shower', 'node_id': 'shower'}) is process
    monkeypatch.setattr(la, '_authorized_popen_locked', lambda *a, **kw: pytest.fail('spawn reached'))
    with pytest.raises(ValueError, match='veto'):
        la.authorized_popen(root, 'full', ['inert'], context={'stage': 'detector', 'node_id': 'detector'})
    assert any('veto' in e for e in gw.launch_errors(root, 'full', ['inert'], {'node_id': 'detector'}))
    assert not any('steering' in e for e in gw.launch_errors(root, 'dry', ['inert'], {'node_id': 'shower'}))


def nested(tmp_path, monkeypatch, parent, stage='inner'):
    """A backend stage in its own store, driven by the proven worker of the parent's approved stage."""
    from ravel.workflow import execution_backend as eb
    monkeypatch.setattr(eb, 'require_approved_stage',
                        lambda rundir, name, pinned=(): {'rundir': str(rundir), 'stage': name, 'attempt_id': 'a1',
                                                         'required_plan': None})
    store = tmp_path / 'backend-store'
    store.mkdir(exist_ok=True)
    code = ss.supervise(stage, store, 0, f'logs/{stage}.log', [sys.executable, '-c', 'print("ran")'],
                        cwd=str(store), kill_secs=30, poll=0.02, grace=0.5, nested_under=(parent, 'shower'))
    return code, ran(store, stage)


def test_nested_backend_stage_follows_the_steering_of_the_run_that_owns_it(study, tmp_path, monkeypatch):
    from ravel.workflow import agent_worker as aw, graph_substrate as gs
    registered = []
    real = gs._register_process
    monkeypatch.setattr(gs, '_register_process', lambda root, entry: registered.append(str(root)) or real(root, entry))
    assert nested(tmp_path, monkeypatch, study) == (0, True)
    assert registered == [str(study)]  # the owning run holds the process record a pause observes
    gw.record_steering(study, 'Stop the independent branch.', effect='veto', affected_nodes=['other'])
    assert nested(tmp_path, monkeypatch, study, 'second') == (0, True)
    gw.record_steering(study, 'Stop this branch.', effect='veto', affected_nodes=['build'])
    code, started = nested(tmp_path, monkeypatch, study, 'third')
    assert code != 0 and not started
    monkeypatch.setattr(gs, 'stop', lambda *a, **kw: {})
    monkeypatch.setattr(aw, 'stop', lambda *a, **kw: {})
