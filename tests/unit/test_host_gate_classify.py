"""Argv classification and Claude/CLI parity controls; no compute executes."""
import json
import pytest
from ravel.workflow import host_gate

MODULE_COMMANDS = [
    'python -m ravel.workflow.scan_orchestrator launch s --go',
    'python3 -m ravel.workflow.stage_supervisor ...',
    'python -m ravel.workflow.scan_babysitter s',
    'python3 -c "import ravel.workflow.stage_supervisor as s; s.main()"',
    'ravel scan launch s',
]
GEN_COMMANDS = [
    './bin/generate_events run', 'mg5_aMC cards.dat', 'python pythia_shower.py --input x',
    'bash native/scripts/run-pipeline-native.sh run cfg.toml', 'ravel run --rundir run',
]

@pytest.mark.parametrize('command', MODULE_COMMANDS + GEN_COMMANDS)
def test_launch_forms(command):
    assert host_gate.classify(command) == 'launch'

@pytest.mark.parametrize('command', [
    'ravel stage --help', 'ravel stage -h', 'ravel stage run --help',
    'echo "ravel stage run"', 'grep "ravel stage" notes.md',
    'printf "%s" "generate_events"', 'rg "mg5_aMC" notes.md',
    'cat "ravel stage run"', 'ravel stage list', 'ravel stage show foo',
    'ravel stage status foo', 'python -m ravel.workflow.stage_supervisor -h',
    'python --help -m ravel.workflow.scan_babysitter s',
    'echo "ravel approve"', 'grep "ravel result-pack" notes.md',
])
def test_read_only_and_quoted_text(command):
    assert host_gate.classify(command) == 'none'

@pytest.mark.parametrize('command', [
    'echo "ravel stage run"; ravel scan launch s',
    'ravel stage --help && ./bin/generate_events run',
    'python -m ravel.workflow.scan_orchestrator launch s --go # note\necho --help',
    'conda run -n env python3 -m ravel.workflow.stage_supervisor ...',
])
def test_segment_and_wrapper_forms(command):
    assert host_gate.classify(command) == 'launch'

@pytest.mark.parametrize('command', MODULE_COMMANDS + GEN_COMMANDS + ['ls', 'echo "mg5_aMC"'])
def test_claude_hook_and_verdict_parity(tmp_path, monkeypatch, command):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    payload = {'tool_name': 'Bash', 'tool_input': {'command': command}, 'session_id': 'parity', 'cwd': str(tmp_path)}
    result = host_gate.verdict(None, 'tool_call', command, session_id='parity', cwd=str(tmp_path), project=tmp_path)
    hook = host_gate.hook_bash(json.dumps(payload), tmp_path)
    assert hook.startswith('block:') == (result['decision'] == 'deny')
    if result['decision'] == 'deny':
        assert hook == 'block:' + result['errors'][0]['message']

@pytest.mark.parametrize('command,plan', [
    ('ravel scan launch s', None), ('ravel scan launch s --go', 'scan'),
    ('python -m ravel.workflow.scan_orchestrator launch s --go', 'scan'),
    ('echo "ravel scan launch s --go"', None), ('ravel scan launch s --go --help', None),
])
def test_go_sets_only_required_scan_plan(command, plan):
    assert host_gate._required_plan(command) == plan

@pytest.mark.parametrize('command', [
    'python -m ravel scan launch s --go',
    'bash -c "ravel scan launch s --go"',
])
def test_wrapped_scan_keeps_required_plan(command):
    assert host_gate.classify(command) == 'launch'
    assert host_gate.explicit_scan(command)
    assert host_gate._required_plan(command) == 'scan'

@pytest.mark.parametrize('command', [
    'time mg5_aMC run.mg5', 'time -p ./bin/generate_events run',
    'nice -n 10 ./bin/generate_events run', 'nice -5 mg5_aMC x',
    'caffeinate -i python -m ravel.workflow.stage_supervisor run x',
    'caffeinate -t 60 mg5_aMC x', 'command mg5_aMC x', 'exec pythia_shower a.cmnd',
    'env -u FOO mg5_aMC x', 'env -i PATH=/bin mg5_aMC x', 'stdbuf -oL ./bin/madevent',
    'nohup nice mg5_aMC x &', 'time conda run -n mg5 python -m ravel.workflow.stage_supervisor run',
    'python3 -c "from ravel.workflow import stage_supervisor; stage_supervisor.main()"',
])
def test_prefix_wrappers_do_not_hide_a_launch(command):
    assert host_gate.classify(command) == 'launch'

@pytest.mark.parametrize('command', ['command -v mg5_aMC', 'time ls', 'nice -n 5 echo "mg5_aMC"'])
def test_prefix_wrappers_keep_non_launches(command):
    assert host_gate.classify(command) == 'none'

def test_wrapped_scan_driver_keeps_required_plan():
    assert host_gate.explicit_scan('caffeinate -i python3 -c "from ravel.workflow import scan_orchestrator"')
    assert host_gate._required_plan('time ravel scan launch s --go') == 'scan'


@pytest.mark.parametrize('command', [
    'ravel gate-wiring respond --rundir r --text "I approve c1" --approve c1',
    'ravel gate-wiring steer --rundir r --text "x" --effect note',
    'ravel gate-wiring checkin1 --rundir r --quote ok',
    'python -m ravel.workflow.gate_wiring respond --rundir r --text t --reopen d',
])
def test_gate_wiring_operator_commands_are_approvals(command):
    """The operator's response, steering and CHECK-IN 1 commands are denied to agents like approve."""
    assert host_gate.classify(command) == 'approve_plan'


def test_gate_wiring_cost_report_is_read_only():
    assert host_gate.classify('ravel gate-wiring cost --rundir r') == 'none'
