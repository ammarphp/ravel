"""Scan-driver classification and the root-layout contract of the gate; no compute executes."""
import json

import pytest

from ravel.workflow import decision_gate, host_gate

ORCHESTRATOR = ('python3 src/ravel/workflow/scan_orchestrator.py', 'python -m ravel.workflow.scan_orchestrator',
                'conda run -n env python3 -u src/ravel/workflow/scan_orchestrator.py')
BABYSITTER = ('python3 src/ravel/workflow/scan_babysitter.py trial-runs/run1 --once',
              'python -m ravel.workflow.scan_babysitter trial-runs/run1',
              'conda run -n env python3 -u src/ravel/workflow/scan_babysitter.py trial-runs/run1',
              'bash src/ravel/workflow/scan_babysitter.py trial-runs/run1',
              'nohup python3 scan_babysitter.py trial-runs/run1 &',
              'python3 -c "from ravel.workflow import scan_babysitter; scan_babysitter.main()"')


@pytest.mark.parametrize('driver', ORCHESTRATOR)
@pytest.mark.parametrize('query', ['status trial-runs/run1', 'plan spec.json', 'plan spec.json --dry-run',
                                   'assemble trial-runs/run1', 'rebase trial-runs/run1 --transformation t.json'])
def test_orchestrator_queries_are_not_launches(driver, query):
    command = f'{driver} {query}'
    assert host_gate.classify(command) == 'none'
    assert not host_gate.explicit_scan(command) and host_gate._required_plan(command) is None


@pytest.mark.parametrize('driver', ORCHESTRATOR)
def test_orchestrator_launch_is_a_launch_and_only_go_needs_the_scan_tier(driver):
    dry, go = f'{driver} launch trial-runs/run1', f'{driver} launch trial-runs/run1 --go'
    assert host_gate.classify(dry) == host_gate.classify(go) == 'launch'
    assert host_gate.explicit_scan(dry) and host_gate.explicit_scan(go)
    assert host_gate._required_plan(dry) is None and host_gate._required_plan(go) == 'scan'


def test_orchestrator_script_and_registered_command_agree():
    for query in ('status s', 'plan s', 'assemble s', 'launch s', 'launch s --go'):
        script = 'python3 src/ravel/workflow/scan_orchestrator.py ' + query
        registered = 'ravel scan ' + query
        assert host_gate.classify(script) == host_gate.classify(registered), query
        assert host_gate._required_plan(script) == host_gate._required_plan(registered), query


@pytest.mark.parametrize('command', BABYSITTER)
def test_every_babysitter_run_needs_the_scan_tier(command):
    assert host_gate.classify(command) == 'launch'
    assert host_gate.explicit_scan(command)
    assert host_gate._required_plan(command) == 'scan'


@pytest.mark.parametrize('command', [
    'python3 src/ravel/workflow/scan_babysitter.py --help', 'python --help -m ravel.workflow.scan_babysitter s',
    'echo python3 src/ravel/workflow/scan_babysitter.py trial-runs/run1 --once',
    'grep scan_babysitter.py notes.md', 'python3 src/ravel/workflow/other_tool.py scan_babysitter.py',
])
def test_help_and_reader_text_about_the_babysitter_need_no_tier(command):
    assert host_gate.classify(command) == 'none' and host_gate._required_plan(command) is None


def test_a_later_babysitter_segment_still_raises_the_tier():
    command = 'ravel scan status s; python3 src/ravel/workflow/scan_babysitter.py s --once'
    assert host_gate.classify(command) == 'launch' and host_gate._required_plan(command) == 'scan'
    assert host_gate._required_plan('bash -c "python3 scan_babysitter.py s"') == 'scan'
    assert host_gate._required_plan('python -m ravel.workflow.stage_supervisor run x') is None


def test_a_root_layout_contract_is_epoch_one_for_the_decision_gate(tmp_path):
    run = tmp_path / 'run'
    run.mkdir()
    (run / 'task_contract.json').write_text(json.dumps({'schema_version': 1}))
    assert decision_gate._facts(run) == {'agent_layer_epoch': 1}
    assert decision_gate.check(run, 'launch', {'kind': 'tool_call'}) == []
    # These gates have no epoch-one decision: the earlier layout cannot pass them either.
    refused = decision_gate.check(run, 'unblind', {'kind': 'unblind'})
    assert [error.code for error in refused] == ['epoch_gate_unsupported']


@pytest.mark.parametrize('raw,message', [('null', 'task contract must be an object'), ('[1]', 'task contract must be an object'),
                                         ('{"agent_layer_epoch": 2}', 'cannot declare agent_layer_epoch two'),
                                         ('{"agent_layer_epoch": true}', 'cannot declare agent_layer_epoch two'),
                                         ('not JSON', 'Expecting value')])
def test_a_root_layout_contract_that_is_not_an_epoch_one_object_is_refused(tmp_path, raw, message):
    run = tmp_path / 'run'
    run.mkdir()
    (run / 'task_contract.json').write_text(raw)
    errors = decision_gate.check(run, 'launch', {'kind': 'tool_call'})
    assert errors and errors[0].code == 'gate_inputs_invalid' and message in errors[0].message


def test_the_inputs_contract_wins_over_a_root_copy_and_a_missing_contract_still_refuses(tmp_path):
    run = tmp_path / 'run'
    (run / 'inputs').mkdir(parents=True)
    (run / 'task_contract.json').write_text(json.dumps({'schema_version': 1}))
    (run / 'inputs' / 'task_contract.json').write_text('null')
    errors = decision_gate.check(run, 'launch', {'kind': 'tool_call'})
    assert errors[0].code == 'gate_inputs_invalid' and 'task contract must be an object' in errors[0].message
    empty = tmp_path / 'empty'
    empty.mkdir()
    errors = decision_gate.check(empty, 'launch', {'kind': 'tool_call'})
    assert errors[0].code == 'gate_inputs_invalid' and 'task_contract.json' in errors[0].message
