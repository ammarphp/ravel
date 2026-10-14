"""Governed authored analysis step: lint, sandbox, pinned attempts and the repair loop."""
import json
import platform
import shutil
from pathlib import Path

import pytest

from ravel.physics import authored_analysis as authored

HAS_SANDBOX = (platform.system() == 'Darwin' and Path('/usr/bin/sandbox-exec').is_file()) or \
    (platform.system() == 'Linux' and shutil.which('bwrap'))
needs_sandbox = pytest.mark.skipif(not HAS_SANDBOX, reason='no sandbox on this machine')

GOOD = '''
import json
from ravel.toolkit import asimov_significance
step = json.load(open("step-inputs.json"))
events = json.load(open(step["inputs"]["events"]))
threshold = step["parameters"]["met_threshold"]
passed = [e for e in events if e["met"] > threshold]
json.dump({"signal_region": {"yield": float(len(passed)), "weights": [1.0] * len(passed),
           "significance": asimov_significance(len(passed), 10.0)}}, open("yields.json", "w"))
'''


def _task(**changes):
    task = {'purpose': 'The selection needs an event-level combinatoric choice that the recipe cannot state.',
            'specification': 'spec.md', 'code': 'attempt.py',
            'io_contract': {'inputs': [{'name': 'events', 'path': 'events.json'}],
                            'outputs': [{'path': 'yields.json', 'kind': 'json', 'postconditions': [
                                {'pointer': '/signal_region/yield', 'check': 'positive'},
                                {'pointer': '/signal_region/weights', 'check': 'not_all_zero'}]}]},
            'parameters': [{'name': 'met_threshold', 'value': 100, 'expected_sensitivity': 'the yield falls as it rises'}],
            'budget': 3, 'timeout_seconds': 60, 'reference_paths': ['reference']}
    task.update(changes)
    return task


@pytest.fixture
def base(tmp_path):
    base = (tmp_path / 'study').resolve()
    base.mkdir()
    (base / 'spec.md').write_text('Count events with missing momentum above the threshold.\n')
    (base / 'events.json').write_text(json.dumps([{'met': 50}, {'met': 150}, {'met': 250}]))
    (base / 'reference').mkdir()
    (base / 'reference/published.json').write_text('{"yield": 2}')
    (base / 'attempt.py').write_text(GOOD)
    return base


def _rundir(tmp_path, task):
    rd = tmp_path / 'run'
    (rd / 'inputs').mkdir(parents=True)
    (rd / 'inputs/science.json').write_text(json.dumps({'mode': 'authored-analysis', 'task': task}))
    (rd / 'inputs/science-approval.json').write_text(json.dumps({'schema_version': 1, 'quote': 'yes'}))
    return rd


@pytest.mark.parametrize('change, message', [
    ({'purpose': 'too short'}, 'purpose'),
    ({'budget': 0}, 'budget'),
    ({'io_contract': {'inputs': [], 'outputs': [{'path': '../escape.json', 'kind': 'json'}]}}, 'inside'),
    ({'parameters': [{'name': 'x', 'value': 1}]}, 'sensitivity'),
])
def test_task_structure(change, message):
    with pytest.raises(ValueError, match=message):
        authored.validate(_task(**change))


def test_lint_rules():
    task = _task()
    findings = authored.lint('import subprocess\nfor i in range(len(xs)):\n    pass\n'
                             'def delta_r(a, b):\n    return 0\n', task)
    rules = {f['rule']: f['severity'] for f in findings}
    assert rules['forbidden-module'] == 'error'
    assert rules['per-entry-loop'] == 'warning'
    assert rules['toolkit-reimplementation'] == 'warning'
    assert rules['unused-parameter'] == 'error'
    assert not [f for f in authored.lint(GOOD, task) if f['severity'] == 'error']
    assert authored.lint('def broken(:\n', task)[0]['rule'] == 'syntax'
    assert any(f['rule'] == 'forbidden-call' for f in authored.lint('import os\nos.system("ls")\n'))


def test_planning_refuses_code_that_fails_lint(base):
    (base / 'attempt.py').write_text('import socket\n')
    with pytest.raises(ValueError, match='lint'):
        authored.inputs(_task(), base)


def test_sandbox_is_required(monkeypatch, tmp_path):
    monkeypatch.setattr(authored.platform, 'system', lambda: 'Plan9')
    with pytest.raises(ValueError, match='no sandbox'):
        authored.sandbox_command(tmp_path, [])


@needs_sandbox
def test_repair_loop_pins_attempts_and_builds_the_designer_packet(base, tmp_path):
    ledger = authored.Ledger.create(tmp_path / 'ledger', _task(), base)
    (tmp_path / 'a1.py').write_text('import json\nstep = json.load(open("step-inputs.json"))\n'
                                    'x = step["parameters"]["met_threshold"]\nprint(undefined_name)\n')
    ledger.submit(tmp_path / 'a1.py')
    first = ledger.run()
    assert first['failure_class'] == 'coding' and first['decision'] == 'repair'
    packet = ledger.packet()
    assert set(packet) == {'spec_pin', 'io_contract', 'previous_code_pin', 'previous_diff', 'observation'}
    assert packet['previous_diff'] is None and 'NameError' in packet['observation']['stderr_tail']
    assert all(set(p) <= {'output', 'check', 'pointer', 'passed', 'class', 'message'} for p in packet['observation']['postconditions'])
    # Attempt 2 writes all-zero weights: a coding failure that may be repaired.
    zero = GOOD.replace('[1.0] * len(passed)', '[0.0] * len(passed)')
    (tmp_path / 'a2.py').write_text(zero)
    ledger.submit(tmp_path / 'a2.py')
    second = ledger.run()
    assert second['failure_class'] == 'coding'
    assert ledger.packet()['previous_diff'].startswith('--- attempt-1')
    (tmp_path / 'a3.py').write_text(GOOD)
    ledger.submit(tmp_path / 'a3.py')
    third = ledger.run()
    assert third['failure_class'] is None and ledger.doc['status'] == 'accepted'
    assert third['outputs'][0]['sha256']
    with pytest.raises(ValueError, match='accepted'):
        ledger.submit(tmp_path / 'a3.py')
    # Attempts are never overwritten and tampering is detected.
    assert (tmp_path / 'ledger/attempts/001/code.py').read_text().endswith('print(undefined_name)\n')
    (tmp_path / 'ledger/attempts/002/code.py').write_text('changed')
    with pytest.raises(ValueError, match='changed'):
        authored.Ledger(tmp_path / 'ledger')


@needs_sandbox
def test_budget_exhaustion_goes_to_failed_stage_review(base, tmp_path):
    ledger = authored.Ledger.create(tmp_path / 'ledger', _task(budget=1), base)
    (tmp_path / 'bad.py').write_text('import json\nstep = json.load(open("step-inputs.json"))\n'
                                     'met_threshold = step["parameters"]["met_threshold"]\nraise RuntimeError("x")\n')
    ledger.submit(tmp_path / 'bad.py')
    assert ledger.run()['decision'] == 'failed_stage_review'
    with pytest.raises(ValueError, match='failed_stage_review'):
        ledger.submit(tmp_path / 'bad.py')


@needs_sandbox
def test_sandbox_hides_references_blocks_writes_and_network(base, tmp_path):
    probe = '''
import json, socket
step = json.load(open("step-inputs.json"))
met_threshold = step["parameters"]["met_threshold"]
out = {}
for key, action in (("reference", lambda: open(%r).read()), ("outside", lambda: open(%r, "w").write("x")),
                    ("network", lambda: socket.create_connection(("1.1.1.1", 80), timeout=2))):
    try:
        action(); out[key] = "allowed"
    except Exception:
        out[key] = "denied"
json.dump({"signal_region": {"yield": 1.0, "weights": [1.0]}, "probe": out}, open("yields.json", "w"))
''' % (str(base / 'reference/published.json'), str(tmp_path / 'escaped.txt'))
    # socket is a forbidden module for authored code; this probe bypasses the lint deliberately.
    raw = authored.execute(_write(tmp_path / 'probe.py', probe), tmp_path / 'work', _task(), base)
    assert raw['exit_code'] == 0, raw['stderr_tail']
    probe_out = json.loads((tmp_path / 'work/yields.json').read_text())['probe']
    assert probe_out == {'reference': 'denied', 'outside': 'denied', 'network': 'denied'}
    assert not (tmp_path / 'escaped.txt').exists()


def _write(path, text):
    path.write_text(text)
    return path


@needs_sandbox
def test_timeout_is_infrastructure_and_unresolved_is_scientific(base, tmp_path):
    ledger = authored.Ledger.create(tmp_path / 'slow', _task(timeout_seconds=1), base)
    ledger.submit(_write(tmp_path / 'slow.py', 'import time\nmet_threshold = 1\ntime.sleep(20)\n'))
    attempt = ledger.run()
    assert attempt['failure_class'] == 'infrastructure' and attempt['decision'] == 'repair'
    ledger = authored.Ledger.create(tmp_path / 'open', _task(), base)
    ledger.submit(_write(tmp_path / 'q.py', 'import json\nmet_threshold = 1\n'
                         'json.dump({"question": "the specification does not say which jets enter"}, open("unresolved.json", "w"))\n'))
    attempt = ledger.run()
    assert attempt['failure_class'] == 'scientific_unresolved' and ledger.doc['status'] == 'failed_stage_review'


@needs_sandbox
def test_science_mode_and_command_line_continue_an_approved_step(base, tmp_path, capsys):
    from ravel import cli
    from ravel.workflow import science
    from test_science_capability_integration import specification
    task = _task()
    spec = specification('authored-analysis', task)
    assert science.adapter(spec) is authored and science._new_capability(spec)
    science.validate(spec)
    assert {p.name for p in science.task_inputs(spec, base)} == {'spec.md', 'attempt.py', 'events.json'}
    result = authored.run(task, base, tmp_path / 'worker-ok')
    assert result['status'] == 'passed' and result['outputs'][0]['path'].endswith('yields.json')
    # A failing first attempt stops the worker; the command line continues within the approval.
    (base / 'attempt.py').write_text('met_threshold = 1\nraise SystemExit(3)\n')
    with pytest.raises(ValueError, match='coding'):
        authored.run(task, base, tmp_path / 'worker-fail')
    rd = _rundir(tmp_path, task)
    ledger_dir = tmp_path / 'continued'
    assert cli.main(['authored-analysis', 'new', '--rundir', str(rd), '--ledger', str(ledger_dir),
                     '--from', str(tmp_path / 'worker-fail/authored-analysis')]) == 0
    capsys.readouterr()
    assert cli.main(['authored-analysis', 'packet', '--ledger', str(ledger_dir)]) == 0
    assert json.loads(capsys.readouterr().out)['observation']['failure_class'] == 'coding'
    (tmp_path / 'fixed.py').write_text(GOOD)
    assert cli.main(['authored-analysis', 'submit', '--ledger', str(ledger_dir), '--code', str(tmp_path / 'fixed.py')]) == 0
    assert cli.main(['authored-analysis', 'run', '--ledger', str(ledger_dir)]) == 0
    capsys.readouterr()
    assert authored.Ledger(ledger_dir).doc['status'] == 'accepted'
    # A different task is not authorised by this approval.
    other = _rundir(tmp_path / 'x', _task(budget=2))
    with pytest.raises(SystemExit):
        cli.main(['authored-analysis', 'new', '--rundir', str(other), '--ledger', str(tmp_path / 'y'),
                  '--from', str(ledger_dir)])
