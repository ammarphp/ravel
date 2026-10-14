"""A plan descriptor that is present but invalid refuses the launch with the typed refusal.

Driven through the launch authorization and the steering command: a null descriptor, a wrong
type, a path that cannot be resolved and a symbolic-link loop never admit a launch and never
escape as an exception. A contract without the key keeps its meaning: the run has no request plan.
"""
import json

import pytest

from ravel.workflow import gate_wiring as gw, rdj_custody as custody
from test_steering_admission import admitted_launch, refused_launch, run, set_contract  # noqa: F401


def loop(run):
    """Two links that point at each other under ``inputs/``."""
    (run / 'inputs/first').symlink_to('second')
    (run / 'inputs/second').symlink_to('first')


def descriptor(run, kind):
    if kind == 'loop':
        loop(run)
        return {'path': 'inputs/first'}
    if kind == 'through-loop':
        loop(run)
        return {'path': 'inputs/first/plan.json'}
    if kind == 'null-byte':
        return {'path': 'inputs/plan\x00.json'}
    if kind == 'too-long':
        return {'path': 'inputs/' + 'p' * 5000 + '.json'}
    if kind == 'directory':
        return {'path': 'inputs'}
    return {'null': None, 'false': False, 'zero': 0, 'empty-text': '', 'empty-list': [], 'empty-object': {},
            'null-path': {'path': None}, 'empty-path': {'path': ''}}[kind]


INVALID = ['null', 'false', 'zero', 'empty-text', 'empty-list', 'empty-object', 'null-path', 'empty-path',
           'loop', 'through-loop', 'null-byte', 'too-long', 'directory']


@pytest.mark.parametrize('node_id', ['build', None, 'not-a-plan-node'])
@pytest.mark.parametrize('kind', INVALID)
def test_present_but_invalid_descriptor_refuses_the_launch(run, monkeypatch, node_id, kind):
    set_contract(run, {'run_id': 'synthetic-study', 'request_plan': descriptor(run, kind)})
    allowed, reason = gw.dispatch_permitted(run, node_id)
    assert not allowed and reason.startswith('plan unreadable'), reason
    errors = gw.launch_errors(run, 'full', ['inert'], {'node_id': node_id})
    assert errors and all('steering_refused: plan unreadable' in e for e in errors), errors
    refused_launch(run, monkeypatch, node_id, 'plan unreadable')
    with pytest.raises(gw.SteeringRefused, match='plan unreadable'):
        with gw.steering_dispatch(run, node_id):
            pytest.fail('dispatch started on an unreadable plan')


@pytest.mark.parametrize('kind', INVALID)
def test_branch_steering_command_on_an_invalid_descriptor_exits_with_the_typed_refusal(run, kind, capsys):
    set_contract(run, {'run_id': 'synthetic-study', 'request_plan': descriptor(run, kind)})
    for action in ('veto', 'redirect', 'require'):
        code = gw.main(['steer', action, '--rundir', str(run), '--text', 'Change this branch.', '--affects', 'build'])
        captured = capsys.readouterr()
        assert code == 2, (action, captured)
        assert 'plan unreadable' in captured.err and 'Traceback' not in captured.err
    assert custody.rows(run, 'steering') == []
    assert not (run / 'inputs/user-steering').exists() and not (run / 'inputs/steering').exists()
    # The study-wide control stays available while the descriptor is repaired, and it refuses every launch.
    assert gw.main(['steer', 'veto', '--rundir', str(run), '--text', 'Stop the study.']) == 0
    capsys.readouterr()
    assert gw.main(['steer', 'state', '--rundir', str(run)]) == 0
    assert json.loads(capsys.readouterr().out)['vetoed_nodes'] == ['*']
    allowed, reason = gw.dispatch_permitted(run, 'other')
    assert not allowed and reason.startswith('plan unreadable')


@pytest.mark.parametrize('kind', ['null', 'loop', 'null-byte'])
def test_stage_owner_lookup_on_an_invalid_descriptor_raises_the_typed_refusal(run, kind):
    set_contract(run, {'run_id': 'synthetic-study', 'request_plan': descriptor(run, kind)})
    with pytest.raises(gw.PlanUnreadable):
        gw.launch_node(run, 'build')


def test_contract_without_the_key_has_no_request_plan_and_is_admitted(run, monkeypatch, capsys):
    set_contract(run, {'run_id': 'synthetic-study'})
    assert gw.dispatch_permitted(run, None)[0] and gw.dispatch_permitted(run, 'build')[0]
    admitted_launch(run, monkeypatch, None)
    assert gw.main(['steer', 'veto', '--rundir', str(run), '--text', 'Stop this branch.', '--affects', 'build']) == 0
    capsys.readouterr()
    # Without a plan the identity is taken as given; nothing below it is known.
    assert not gw.dispatch_permitted(run, 'build')[0]


def test_valid_descriptor_reached_through_a_link_inside_the_run_is_still_read(run, monkeypatch):
    (run / 'inputs/alias.json').symlink_to('plan.json')
    set_contract(run, {'run_id': 'synthetic-study', 'request_plan': {'path': 'inputs/alias.json'}})
    admitted_launch(run, monkeypatch, 'child')
