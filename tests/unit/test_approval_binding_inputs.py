"""Prospective byte binding on synthetic lifecycle operation plans."""
import json
from pathlib import Path

import pytest

from ravel.workflow import launch_authorization, workflow_state as ws
from ravel.workflow.state_io import atomic_json
from ravel.validation import validate_run_state as vrs
from test_approval_chain import _rundir


def lifecycle(tmp_path):
    rd = _rundir(tmp_path)
    files = ['config/native.toml', 'inputs/detector.tcl', 'config/shower.cfg', 'inputs/generator.dat']
    for rel in files:
        path = rd / rel
        path.parent.mkdir(exist_ok=True)
        path.write_text('synthetic setting = 1\n')
    plan = {'stages': [{'stage': 'generate', 'inputs': files,
                        'outputs': ['output/events.bin']},
                       {'stage': 'detector', 'inputs': ['output/events.bin', files[1]],
                        'outputs': ['output/selected.bin']}], 'sources': [], 'rendered': {}}
    atomic_json(rd / 'inputs/executable-plan.json', plan)
    contract_path = rd / 'inputs/task_contract.json'
    contract = json.loads(contract_path.read_text())
    contract['execution_plan'] = {'path': 'inputs/executable-plan.json', 'sha256':
                                  __import__('hashlib').sha256((rd / 'inputs/executable-plan.json').read_bytes()).hexdigest()}
    atomic_json(contract_path, contract)
    return rd, files


def repin_plan(rd):
    path = rd / 'inputs/task_contract.json'
    contract = json.loads(path.read_text())
    contract['execution_plan']['sha256'] = __import__('hashlib').sha256((rd / contract['execution_plan']['path']).read_bytes()).hexdigest()
    atomic_json(path, contract)


def approve(rd):
    repin_plan(rd)
    assert ws.main(['approve', '--rundir', str(rd), '--quote', 'Approve these exact inputs',
                    '--plan', 'smoke']) == 0


@pytest.mark.parametrize('index', range(4), ids=['native-toml', 'detector-tcl', 'shower-cfg', 'generator-card'])
def test_changed_operation_input_refuses_next_launch(tmp_path, index):
    rd, files = lifecycle(tmp_path)
    approve(rd)
    (rd / files[index]).write_text('synthetic setting = 2\n')
    with pytest.raises(ValueError, match=files[index]):
        launch_authorization._capture(rd, 'smoke', command=['/bin/sleep', '0'])


def test_new_operation_file_class_is_bound_automatically(tmp_path):
    rd, files = lifecycle(tmp_path)
    new = 'inputs/response.unseen_format'
    (rd / new).write_bytes(b'novel input bytes')
    p = rd / 'inputs/executable-plan.json'
    plan = json.loads(p.read_text())
    plan['stages'].append({'stage': 'custom', 'inputs': [new], 'outputs': ['output/custom.bin']})
    atomic_json(p, plan)
    approve(rd)
    assert str(rd / new) in ws.approval_input_paths(str(rd))
    (rd / new).write_bytes(b'changed novel input bytes')
    assert any(new in e for e in ws.verify_approval(str(rd), required_plan='smoke'))
    assert str(rd / 'output/events.bin') not in ws.approval_input_paths(str(rd))


def test_amendment_reapproval_records_deviation_and_restores_launch(tmp_path):
    rd, files = lifecycle(tmp_path)
    approve(rd)
    (rd / files[2]).write_text('synthetic setting = 2\n')
    assert ws.verify_approval(str(rd), disclose=True)
    # A deviation is disclosure, not permission to execute changed bytes.
    assert files[2] in (rd / 'DEVIATIONS.md').read_text()
    assert ws.verify_approval(str(rd))
    assert ws.main(['approve', '--rundir', str(rd), '--quote', 'Approve amended shower settings',
                    '--plan', 'smoke']) == 0
    assert not ws.verify_approval(str(rd), required_plan='smoke')
    assert launch_authorization._capture(rd, 'smoke')['approval']
    text = (rd / 'DEVIATIONS.md').read_text()
    assert 'Approve amended shower settings' in text and files[2] in text
    assert files[2] in vrs.baselined_inputs_changed(str(rd))


def test_redo_replacement_seam_classifies_approved_byte_change(tmp_path):
    from ravel.workflow import approval_inputs
    rd, files = lifecycle(tmp_path)
    approve(rd)
    row = approval_inputs.classify_replacement(rd, files[3], 'replacement card bytes\n')
    assert row['classification'] == 'approved-input-change'
    assert row['requires_reapproval'] is True
    assert row['path'] == files[3]
    unchanged = approval_inputs.classify_replacement(rd, files[3], (rd / files[3]).read_text())
    assert unchanged['requires_reapproval'] is False
    # Classification is prospective and never writes replacement bytes.
    assert (rd / files[3]).read_text() == 'synthetic setting = 1\n'


def test_rendered_card_materialization_is_allowed_but_edit_is_refused(tmp_path):
    rd, files = lifecycle(tmp_path)
    p = rd / 'inputs/executable-plan.json'
    plan = json.loads(p.read_text())
    plan['rendered'] = {'run_card.dat': 'rendered setting = 1\n'}
    plan['stages'].insert(0, {'stage': 'prepare', 'inputs': files,
                              'outputs': ['output/run_card.dat']})
    plan['stages'][1]['inputs'].append('output/run_card.dat')
    atomic_json(p, plan)
    approve(rd)
    (rd / 'output').mkdir()
    (rd / 'output/run_card.dat').write_text(plan['rendered']['run_card.dat'])
    assert not ws.verify_approval(str(rd))
    (rd / 'output/run_card.dat').write_text('rendered setting = 2\n')
    assert any('output/run_card.dat' in e for e in ws.verify_approval(str(rd)))


def test_bound_native_input_edit_guard_requires_reapproval(tmp_path, capsys):
    rd, files = lifecycle(tmp_path)
    approve(rd)
    (rd / files[0]).write_text('changed native bytes')
    assert vrs.edit_guard(str(rd / files[0])) == 1
    assert files[0] in capsys.readouterr().err


# ---- CJ-F: execution-added reads and producer order -------------------------------------------

def _edit_plan(rd, mutate):
    p = rd / 'inputs/executable-plan.json'
    plan = json.loads(p.read_text())
    mutate(plan)
    atomic_json(p, plan)


def test_stage_executable_and_argument_script_are_bound(tmp_path):
    import sys
    rd, _ = lifecycle(tmp_path)
    (rd / 'scripts').mkdir()
    (rd / 'scripts/step.py').write_text('print("synthetic step")\n')
    _edit_plan(rd, lambda plan: plan['stages'][0].update(command=[sys.executable, 'scripts/step.py', '--flag']))
    approve(rd)
    paths = ws.approval_input_paths(str(rd))
    assert str((rd / 'scripts/step.py').resolve()) in paths
    assert str(Path(sys.executable).resolve()) in paths
    (rd / 'scripts/step.py').write_text('print("changed step")\n')
    assert any('scripts/step.py' in e for e in ws.verify_approval(str(rd), required_plan='smoke'))


def test_early_read_of_a_later_output_is_bound(tmp_path):
    rd, _ = lifecycle(tmp_path)
    (rd / 'output').mkdir(exist_ok=True)
    (rd / 'output/seed.bin').write_bytes(b'pre-existing seed')
    _edit_plan(rd, lambda plan: (plan['stages'][0]['inputs'].append('output/seed.bin'),
                                 plan['stages'][1]['outputs'].append('output/seed.bin')))
    approve(rd)
    assert str(rd / 'output/seed.bin') in ws.approval_input_paths(str(rd))


def test_read_of_an_undeclared_dependency_output_is_bound(tmp_path):
    rd, _ = lifecycle(tmp_path)
    (rd / 'output').mkdir(exist_ok=True)
    (rd / 'output/events.bin').write_bytes(b'pre-existing events')
    _edit_plan(rd, lambda plan: [plan['stages'][0].update(depends_on=[]),
                                 plan['stages'][1].update(depends_on=[])])
    approve(rd)
    assert str(rd / 'output/events.bin') in ws.approval_input_paths(str(rd))
    _edit_plan(rd, lambda plan: plan['stages'][1].update(depends_on=['generate']))
    repin_plan(rd)
    assert str(rd / 'output/events.bin') not in ws.approval_input_paths(str(rd))


def test_every_run_file_named_in_a_stage_command_is_bound(tmp_path):
    import sys
    rd, _ = lifecycle(tmp_path)
    (rd / 'macros').mkdir()
    for rel in ('macros/run.mac', 'macros/fit.R', 'macros/settings.json', 'macros/tool.py'):
        (rd / rel).write_text('synthetic content\n')
    (rd / 'output').mkdir(exist_ok=True)
    (rd / 'output/selected.bin').write_bytes(b'the stage writes this')
    command = [sys.executable, '-m', 'macros.tool', 'macros/run.mac', '--config=macros/settings.json',
               '--script', 'macros/fit.R', '--out', 'output/selected.bin']
    _edit_plan(rd, lambda plan: plan['stages'][1].update(command=command))
    approve(rd)
    paths = ws.approval_input_paths(str(rd))
    for rel in ('macros/run.mac', 'macros/fit.R', 'macros/settings.json', 'macros/tool.py'):
        assert str((rd / rel).resolve()) in paths, rel
    assert str((rd / 'output/selected.bin').resolve()) not in paths
    (rd / 'macros/run.mac').write_text('changed macro\n')
    assert any('macros/run.mac' in e for e in ws.verify_approval(str(rd), required_plan='smoke'))
