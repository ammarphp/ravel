"""P06: stop, pause, resume and revocation live in the protected store (A10, B05, C40, G06, SW05).

Only the operator (``ravel operator``) or the physicist at the controller terminal writes a
control; every effect checks it; status reports requested, draining, then stopped; nothing in
the run tree clears it; a new controller process reads the same state.
"""
from __future__ import annotations

import pytest

from test_p06_support import FakeRunStore, autonomous, frozen_store, operator_home, ownership, view  # noqa: F401
from ravel.controller.authority import (AuthorityRefused, MACHINE, OPERATOR_COMMAND, TERMINAL, authorize_effect,
                                        check, control, observe_stop, request, stop_state, verify)
from ravel.controller.authority import cli, common, stop, terminal

PLAN = 'a' * 64


def operator_command(store, action, reason='operator decision'):
    return stop.record_control(store, action, label=OPERATOR_COMMAND, source='operator_cli',
                               evidence={'operator_uid': 0}, reason=reason)


def approved(store):
    return request(store, 'ci1', {'view': view(store, 'approve_plan', plan_sha256=PLAN)}, {'rung': 'full'})


def smoke():
    return {'id': 'e1', 'rung': 'smoke', 'pins': {'plan_sha256': PLAN}}


def test_A10_B05_C40_stop_blocks_the_next_effect_and_reports_draining_then_stopped(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    approved(store)
    assert stop_state(store) == 'running' and authorize_effect(store, smoke())
    record = operator_command(store, 'stop', 'drain before the maintenance window')
    assert stop_state(store) == 'stop_requested' and record['label'] == OPERATOR_COMMAND
    with pytest.raises(AuthorityRefused):
        authorize_effect(store, smoke())
    with pytest.raises(AuthorityRefused):
        check(store, 'nested submission')  # an inert backend's second submission is refused too
    with pytest.raises(AuthorityRefused):
        observe_stop(store, 'stopped')  # stopped is observed only after draining began
    observe_stop(store, 'draining', {'live_descendants': 2})
    assert stop_state(store) == 'draining'
    observe_stop(store, 'stopped', {'reaped': 2})
    assert stop_state(store) == 'stopped'
    # A fresh controller process (a new store object on the same directory) reads the same state.
    reopened = FakeRunStore(store.run_id, root=store.root)
    assert stop_state(reopened) == 'stopped'
    operator_command(reopened, 'resume', 'maintenance finished')
    assert stop_state(store) == 'running' and authorize_effect(store, smoke())


def test_pause_holds_requests_and_effects_until_resume(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    operator_command(store, 'pause')
    assert stop_state(store) == 'pause_requested' and control(store)['request'] == 'pause'
    held = approved(store)
    assert 'pending' in held and 'pause requested' in held['pending']['reason']
    with pytest.raises(AuthorityRefused):
        authorize_effect(store, smoke())
    operator_command(store, 'resume')
    assert approved(store)['label'] == MACHINE


def test_A10_G06_revocation_withdraws_machine_authority_for_the_rest_of_the_run(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    approval = approved(store)
    operator_command(store, 'revoke', 'the delegation ends here')
    assert stop_state(store) == 'stop_requested' and control(store)['revoked']
    with pytest.raises(AuthorityRefused):
        authorize_effect(store, smoke())
    operator_command(store, 'resume', 'continue with a human deciding')
    assert stop_state(store) == 'running' and control(store)['revoked']
    with pytest.raises(AuthorityRefused):
        verify(store, approval['id'], kind='ci1')  # the machine approval no longer authorizes
    with pytest.raises(AuthorityRefused):
        authorize_effect(store, smoke())
    held = request(store, 'ci1', {'view': view(store, 'approve_plan', plan_sha256='b' * 64)}, {'rung': 'smoke'})
    assert 'pending' in held and 'revoked machine authority' in held['pending']['reason']


def test_G06_legacy_delegated_authorize_names_the_store_revocation(operator_home, tmp_path, ownership):
    from ravel.workflow import scientific_autonomy
    autonomous()
    run_dir = tmp_path / 'run'
    run_dir.mkdir()
    store = ownership.register(run_dir, frozen_store(tmp_path))
    with pytest.raises(ValueError, match='controller-owned'):
        scientific_autonomy.authorize(run_dir, 'approve_plan')
    operator_command(store, 'revoke')
    with pytest.raises(ValueError, match='revoked by the operator'):
        scientific_autonomy.authorize(run_dir, 'approve_plan')
    with pytest.raises(ValueError, match='controller-owned'):
        scientific_autonomy.revoke(run_dir, user_text={'path': 'x', 'sha256': 'y'}, quote='stop')


def test_SW05_no_run_tree_file_or_worker_label_clears_a_stop(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    operator_command(store, 'stop')
    for name in ('STOP', '.stop', 'stop.flag'):
        (tmp_path / name).unlink(missing_ok=True)
    assert stop_state(store) == 'stop_requested'
    for label in (MACHINE, 'delegated_machine', 'terminal_operator_unattested', 'human_operator'):
        with pytest.raises(AuthorityRefused):
            stop.record_control(store, 'resume', label=label, source='worker', evidence={}, reason='resume')
    assert stop_state(store) == 'stop_requested'
    with pytest.raises(AuthorityRefused):
        operator_command(frozen_store(tmp_path, run_id='running-run'), 'resume')  # nothing to resume


def test_terminal_controls_need_the_physicist_at_the_controller_terminal(operator_home, tmp_path, monkeypatch):
    autonomous()
    store = frozen_store(tmp_path)
    monkeypatch.setattr(terminal, '_open_terminal', lambda: (_ for _ in ()).throw(terminal.TerminalUnavailable('none')))
    held = request(store, 'stop', {'reason': 'stop from the terminal'}, {})
    assert 'pending' in held and stop_state(store) == 'running'
    monkeypatch.setattr(terminal, 'ask', lambda text, *, decisions, timeout=None: {
        'decision': 'confirm', 'comment': '', 'response_sha256': '1' * 64, 'prompt_sha256': '2' * 64,
        'nonce_sha256': '3' * 64, 'device': {'name': None, 'rdev': 0}, 'attempts': 1})
    record = request(store, 'stop', {'reason': 'stop from the terminal'}, {})
    assert record['label'] == 'terminal_operator_unattested' and stop_state(store) == 'stop_requested'


def test_operator_cli_controls_and_status(operator_home, tmp_path, monkeypatch, capsys):
    autonomous()
    store = frozen_store(tmp_path)
    monkeypatch.setattr(common, 'open_store', lambda identifier: store)
    assert cli.main(['pause', '--run', store.run_id, '--reason', 'operator pause']) == 0
    assert stop_state(store) == 'pause_requested'
    assert cli.main(['status', '--run', store.run_id]) == 0
    assert '"pause_requested"' in capsys.readouterr().out
    monkeypatch.setenv('CODEX_THREAD_ID', 'agent')
    assert cli.main(['resume', '--run', store.run_id, '--reason', 'an agent tries']) == 2
    assert stop_state(store) == 'pause_requested'
    monkeypatch.delenv('CODEX_THREAD_ID')
    assert cli.main(['resume', '--run', store.run_id, '--reason', 'operator resumes']) == 0
    assert stop_state(store) == 'running'
