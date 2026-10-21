"""Switch rows closed by the command policy: state-writing commands never touch a controller-owned run.

The adversary is an operator-path negative: a worker (or anything with a shell) runs the legacy
commands that write approvals, responses, steering, stop flags, registrations or graph control,
against a controller-owned run, by path, by option value, by symlink alias or from inside the
run. The oracle is the CLI refusal, the structured policy's switch and run identity, and an
unchanged run tree and store. The positive control runs the same command on a legacy run: the
policy does not refuse it (the 1.1.0
command keeps working there, labelled NOT GOVERNED by the controller's receipts).
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import os
from pathlib import Path
import pty
import subprocess
import sys

import pytest

from nc_cases import CONTROLLER, ROOT, case, require_controller
from nc_controller import controller_run
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register

REFUSED = 'is refused for the controller-owned run'


def _tree(*roots):
    state = {}
    for root in roots:
        for path in sorted(Path(root).rglob('*')):
            if path.is_file() and not path.is_symlink():
                state[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            elif path.is_symlink():
                state[str(path)] = 'link'
    return state


def _cli(argv, *, cwd=None):
    from ravel import cli
    err, out = io.StringIO(), io.StringIO()
    previous = os.getcwd()
    if cwd is not None:
        os.chdir(cwd)
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            try:
                status = cli.main(list(argv))
            except SystemExit as exc:
                status = exc.code if isinstance(exc.code, int) else 1
    finally:
        os.chdir(previous)
    return status, out.getvalue() + err.getvalue()


def _legacy(nc, name='legacy-run'):
    run = nc.root / 'legacy' / name
    (run / 'inputs').mkdir(parents=True)
    (run / 'inputs' / 'task_contract.json').write_text('{"schema_version": 1}')
    return run


def _assert_refused(nc, argv, switch, *, cwd=None, runs=()):
    store, run_dir = runs or controller_run(nc)
    before = _tree(run_dir, store.root)
    from ravel.controller import command_policy
    arguments = argv(run_dir)
    scoped_cwd = cwd(run_dir) if callable(cwd) else cwd
    status, text = _cli(arguments, cwd=scoped_cwd)
    assert status != 0 and REFUSED in text, (status, text[-600:])
    previous = os.getcwd()
    if scoped_cwd is not None:
        os.chdir(scoped_cwd)
    try:
        refusal = command_policy.refusal(list(arguments))
    finally:
        os.chdir(previous)
    assert refusal is not None
    if switch is not None:
        assert refusal['switch'] == switch
    assert refusal['run_id'] == store.run_id
    assert _tree(run_dir, store.root) == before, 'a refused command changed the run or its store'
    return store, run_dir


def _assert_not_refused_on_legacy(nc, argv):
    legacy = _legacy(nc)
    status, text = _cli(argv(legacy))
    assert REFUSED not in text, text[-600:]


def _policy_off(original):
    return lambda argv: None


register(Mutation('M22', ('ravel.controller.command_policy:check',), _policy_off, ('SW01', 'SW02', 'SW05'),
                  binding=MUTATION_CONTROLLER, why='the command policy never refuses'))
for _switch in ('SW01', 'SW02', 'SW03', 'SW04', 'SW05', 'SW11', 'SW13'):
    register(Mutation(_switch, ('ravel.controller.command_policy:check',), _policy_off, (_switch,),
                      binding=MUTATION_CONTROLLER, why='the command policy never refuses'))


PTY_APPROVE = r'''
import os, pty, subprocess, sys
master, slave = pty.openpty()
proc = subprocess.run([sys.executable, '-B', '-m', 'ravel.cli', *sys.argv[1:]], stdin=slave, stdout=slave,
                      stderr=subprocess.PIPE, text=True)
os.close(slave)
print(proc.returncode)
sys.stderr.write(proc.stderr)
'''


@case('SW01', binding=CONTROLLER)
def test_SW01_approve_and_go_are_refused_for_a_controller_run_and_never_labelled_human(nc):
    require_controller('command_policy')
    from ravel.workflow import approval_authority
    store, run_dir = _assert_refused(nc, lambda r: ['approve', '--rundir', str(r), '--plan', 'smoke',
                                                    '--quote', 'Approved (fictional).'], 'SW01')
    _assert_refused(nc, lambda r: ['go', '--rundir', str(r)], 'SW01', runs=(store, run_dir))
    _assert_refused(nc, lambda r: ['workflow_state', 'approve', '--rundir', str(r)], 'SW01', runs=(store, run_dir))
    # An agent with a pseudo-terminal and no session markers: still refused, by the same policy.
    env = {k: v for k, v in os.environ.items() if k not in approval_authority.AGENT_MARKERS}
    child = subprocess.run([sys.executable, '-c', PTY_APPROVE, 'approve', '--rundir', str(run_dir), '--plan', 'smoke',
                            '--quote', 'Approved (fictional).'], capture_output=True, text=True, env=env, timeout=120)
    assert child.stdout.strip() != '0' and REFUSED in child.stderr, (child.stdout, child.stderr[-400:])
    # On a legacy run a terminal is never evidence of a human: the label is unattested.
    assert approval_authority.classify(interactive=True, agent_session=None) != 'human_operator'
    assert approval_authority.authority({'authority': 'human_operator'}) != 'human_operator'
    _assert_not_refused_on_legacy(nc, lambda r: ['approve', '--rundir', str(r), '--plan', 'smoke',
                                                 '--quote', 'Approved (fictional).'])


@case('SW02', binding=CONTROLLER)
def test_SW02_respond_cannot_answer_a_controller_run_check_in(nc):
    require_controller('command_policy')
    _assert_refused(nc, lambda r: ['respond', '--rundir', str(r), '--approve', 'CASE-1'], 'SW02')
    _assert_not_refused_on_legacy(nc, lambda r: ['respond', '--rundir', str(r), '--approve', 'CASE-1'])


@case('SW03', binding=CONTROLLER)
def test_SW03_steer_cannot_change_a_controller_run_policy_or_ceilings(nc):
    require_controller('command_policy')
    _assert_refused(nc, lambda r: ['steer', '--rundir', str(r), 'policy', '--max-events', '1000000000'], 'SW03')
    _assert_not_refused_on_legacy(nc, lambda r: ['steer', '--rundir', str(r), 'policy', '--max-events', '1'])


@case('SW04', binding=CONTROLLER)
def test_SW04_drive_respond_and_the_legacy_lifecycle_cannot_answer_a_controller_run(nc):
    require_controller('command_policy')
    store, run_dir = _assert_refused(nc, lambda r: ['drive', 'respond', '--rundir', str(r), '--decision', 'approve',
                                                    '--record', str(r / 'record.json')], 'SW04')
    _assert_refused(nc, lambda r: ['drive', '--rundir', str(r)], 'SW04', runs=(store, run_dir))


@case('SW05', binding=CONTROLLER)
def test_SW05_clear_stop_cannot_release_a_controller_run_stop(nc):
    authority = require_controller('authority')
    require_controller('command_policy')
    from nc_controller import operator
    store, run_dir = controller_run(nc, mode='autonomous')
    status, text = operator(nc)('stop', '--run', store.run_id, '--reason', 'fictional stop by the operator')
    assert status == 0, text
    for argv, switch in ((['graph', 'run', '--scope', str(run_dir), '--clear-stop'], 'SW05'),
                         (['fictional-hidden-command', str(run_dir), '--clear-stop'], 'SW05'),
                         (['drive', '--rundir', str(run_dir), '--clear-stop'], None),
                         (['graph_substrate', 'release-stop', '--scope', str(run_dir)], None)):
        _assert_refused(nc, lambda r, argv=argv: argv, switch, runs=(store, run_dir))
    assert authority.stop_state(store) == 'stop_requested', 'the stop survives every worker-reachable command'
    status, text = operator(nc)('resume', '--run', store.run_id, '--reason', 'fictional resume by the operator')
    assert status == 0 and authority.stop_state(store) == 'running'  # positive control: the operator resumes


@case('SW11', binding=CONTROLLER)
def test_SW11_releasing_the_session_registration_changes_nothing_for_a_controller_run(nc):
    require_controller('command_policy')
    _assert_refused(nc, lambda r: ['active_run', 'release', '--rundir', str(r)], 'SW11')


@case('SW13', binding=CONTROLLER)
def test_SW13_hidden_and_unreleased_commands_are_refused_for_a_controller_run_by_path_alias_or_cwd(nc):
    require_controller('command_policy')
    store, run_dir = _assert_refused(nc, lambda r: ['graph', 'respond', '--scope', str(r)], 'SW13')
    alias = nc.root / 'alias-of-run'
    alias.symlink_to(run_dir, target_is_directory=True)
    _assert_refused(nc, lambda r: ['fictional-hidden-command', '--rundir', str(alias)], 'SW13',
                    runs=(store, run_dir))
    _assert_refused(nc, lambda r: ['fictional-hidden-command', 'write'], 'SW13', cwd=lambda r: r,
                    runs=(store, run_dir))
    # Read-only commands stay available on the controller run.
    status, text = _cli(['status', '--run', store.run_id])
    assert REFUSED not in text
