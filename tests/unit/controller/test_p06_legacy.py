"""P06: legacy authority commands keep working on legacy runs, never infer a human, and are refused
for controller-owned runs (SW01-SW04, A03).

``ravel approve`` under a pseudo-terminal with every agent marker unset records the legacy label
``terminal_operator_unattested`` (never ``human_operator``) on a legacy run, and is refused for a
controller-owned run before anything is written. ``respond``, ``steer`` (including policy,
acknowledgement and result disposition) and the CHECK-IN 1 response recorder refuse
controller-owned runs; a self-written record is never controller authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import textwrap

import pytest

from test_p06_support import autonomous, frozen_store, operator_home, ownership, view  # noqa: F401
from test_approval_chain import _rundir
from ravel.controller.authority import AuthorityRefused, verify
from ravel.workflow import approval_authority as aa, gate_wiring as gw, workflow_state as ws

PTY_APPROVE = textwrap.dedent(r'''
    import json, os, pty, re, sys, time
    rundir, owned = sys.argv[1], sys.argv[2] == 'owned'
    pid, master = pty.fork()
    if pid == 0:
        from ravel.workflow.approval_authority import AGENT_MARKERS
        for name in AGENT_MARKERS:
            os.environ.pop(name, None)
        if owned:
            from ravel.controller.authority import common
            target = os.path.realpath(rundir)
            common._OWNERSHIP = lambda path: 'run-pty' if os.path.realpath(path) == target else None
        from ravel.workflow import workflow_state
        rc = workflow_state.main(['approve', '--rundir', rundir, '--quote', 'GO ahead, approved as planned.',
                                  '--plan', 'smoke'])
        print(f'\nRC {rc} TTY {sys.stdin.isatty() and sys.stdout.isatty()}', flush=True)
        os._exit(0)
    seen = b''
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline and not re.search(rb'RC (\d+) TTY (\w+)', seen):
        try:
            chunk = os.read(master, 4096)
        except OSError:
            break
        if not chunk:
            break
        seen += chunk
    os.waitpid(pid, 0)
    match = re.search(rb'RC (\d+) TTY (\w+)', seen)
    print(json.dumps({'rc': int(match.group(1)), 'tty': match.group(2).decode(), 'output': seen.decode(errors='replace')}))
''')


def approve_under_pty(tmp_path, rundir, owned):
    script = tmp_path / 'pty_approve.py'
    script.write_text(PTY_APPROVE)
    done = subprocess.run([sys.executable, str(script), str(rundir), 'owned' if owned else 'legacy'],
                          capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL,
                          start_new_session=True, env=os.environ.copy())
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_SW01_A03_classify_never_infers_a_human_operator(monkeypatch):
    for name in aa.AGENT_MARKERS:
        monkeypatch.delenv(name, raising=False)
    assert aa.classify(agent_session=False, interactive=True) == 'terminal_operator_unattested'
    assert aa.classify(quote='Approved.', agent_session=False, interactive=True) == 'terminal_operator_unattested'
    assert aa.classify(agent_session=True, interactive=True) == 'unknown'
    assert aa.classify(scripted=True) == 'scripted_experiment' and aa.classify(delegated=True) == 'delegated_machine'
    assert aa.authority({'authority': 'human_operator'}) == 'terminal_operator_unattested'
    assert 'terminal_operator_unattested' in aa.AUTHORITIES and 'human_operator' in aa.AUTHORITIES


def test_SW01_A03_ravel_approve_under_a_pseudo_terminal_on_a_legacy_run(tmp_path):
    rundir = _rundir(tmp_path)
    out = approve_under_pty(tmp_path, rundir, owned=False)
    assert out['tty'] == 'True' and out['rc'] == 0, out['output']
    record = json.loads((rundir / 'inputs/checkin1_approval.json').read_text())
    assert record['authority'] == 'terminal_operator_unattested'
    assert [row['record']['authority'] for row in ws.approval_custody(rundir)] == ['terminal_operator_unattested']
    assert ws.verify_approval(str(rundir)) == []  # legacy gates accept the honest label


def test_SW01_A03_ravel_approve_under_a_pseudo_terminal_refused_for_a_controller_run(tmp_path):
    rundir = _rundir(tmp_path)
    out = approve_under_pty(tmp_path, rundir, owned=True)
    assert out['tty'] == 'True' and out['rc'] == 1
    assert 'controller-owned' in out['output'] and 'Nothing was recorded' in out['output']
    assert not (rundir / 'inputs/checkin1_approval.json').exists()
    assert ws.approval_custody(rundir) == []


def test_SW01_go_and_delegated_commands_refused_for_a_controller_run(operator_home, tmp_path, ownership, capsys):
    rundir = _rundir(tmp_path)
    ownership.register(rundir, frozen_store(tmp_path))
    assert ws.main(['go', '--rundir', str(rundir), '--quote', 'GO']) == 1
    assert ws.main(['delegated-approve', '--rundir', str(rundir), '--plan', 'smoke']) == 1
    assert ws.main(['delegated-go', '--rundir', str(rundir)]) == 1
    err = capsys.readouterr().err
    assert err.count('controller-owned') == 3
    assert not (rundir / 'inputs/checkin2_go.json').exists() and not (rundir / 'inputs/checkin1_approval.json').exists()


def test_SW02_SW03_respond_steer_and_response_recording_refused_for_a_controller_run(operator_home, tmp_path, ownership):
    rundir = tmp_path / 'run'
    (rundir / 'inputs').mkdir(parents=True)
    ownership.register(rundir, frozen_store(tmp_path))
    before = sorted(p.relative_to(rundir) for p in rundir.rglob('*'))
    attempts = [
        lambda: gw.respond(rundir, 'approve case C-0001', approve=['C-0001']),
        lambda: gw.record_steering(rundir, 'raise the ceiling', effect='requirement'),
        lambda: gw.set_steering_policy(rundir, {'autonomy': 'bounded_delegated'}, source_text='autonomy please'),
        lambda: gw.ack_steering(rundir, 'E1', interpretation='understood'),
        lambda: gw.record_result_disposition(rundir, 'accept', 'accept the result'),
        lambda: gw.record_checkin1(rundir, quote='approved'),
    ]
    for attempt in attempts:
        with pytest.raises(AuthorityRefused, match='controller-owned'):
            attempt()
    assert sorted(p.relative_to(rundir) for p in rundir.rglob('*')) == before
    assert gw.main(['respond', '--rundir', str(rundir), '--approve', 'C-0001', '--text', 'approve C-0001']) == 2
    assert gw.main(['steer', 'policy', '--rundir', str(rundir), '--set', 'flags', '--autonomy', 'bounded_delegated']) == 2
    from ravel.workflow import respond_cli
    assert respond_cli.main(['--rundir', str(rundir), '--approve', 'C-0001', '--text', 'approve C-0001']) == 2


def test_SW02_legacy_respond_still_reaches_its_own_validation(tmp_path):
    rundir = tmp_path / 'legacy'
    (rundir / 'inputs').mkdir(parents=True)
    with pytest.raises(ValueError) as caught:
        gw.respond(rundir, 'approve case C-0001', approve=['C-0001'])
    assert 'controller-owned' not in str(caught.value)


def test_SW04_a_self_written_checkin_record_is_never_controller_authority(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    record = tmp_path / 'run/inputs/checkin1_response.json'
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({'decision': 'approve', 'authority': 'human_operator'}))
    digest = hashlib.sha256(record.read_bytes()).hexdigest()
    for forged in (str(record), 'inputs/checkin1_response.json', digest):
        with pytest.raises(AuthorityRefused):
            verify(store, forged, kind='ci1')
