"""Actual supervised ordinary results must have current RDJ tool custody."""
from pathlib import Path
import sys

import pytest

from ravel.paths import module_command
from ravel.workflow import rdj_anchor, rdj_custody, science, research_cycle as cycle
from method_decision_fixture import admit_method
from test_research_full_cycle_contract import prepared_harness


def test_supervised_child_result_is_a_current_registered_tool_anchor(tmp_path):
    root, rd = prepared_harness(tmp_path)
    admit_method(rd)
    science.approve(rd, 'Execute the exact fictional supplied arithmetic.', scripted=True)
    assert cycle.run_experiment(root, 'paired') == 0
    record = science.execution.load_execution(rd)['stages']['science']
    assert rdj_custody.stage_receipt_registered(rd, 'science', record['attempt_id'], record)
    result = rd/'outputs/attempt-1/result.json'
    anchor = {'kind': 'tool_output', 'binding': {
        'receipt_id': 'stage:science:'+record['attempt_id'],
        'output_path': str(result.relative_to(rd)), 'sha256': cycle._pin(result)['sha256']}, 'locator': ''}
    assert rdj_anchor.verify(anchor, rd) == 'external'
    result.write_bytes(result.read_bytes() + b'\n')
    assert rdj_anchor.verify(anchor, rd) == 'invalid'


@pytest.mark.parametrize('mutation', ['foreign_bootstrap', 'unknown_module', 'shadow_module'])
def test_bootstrap_tool_recognition_preserves_original_producer_refusals(tmp_path, mutation):
    command = module_command('ravel.physics.science_worker', tmp_path)
    if mutation == 'foreign_bootstrap':
        foreign = tmp_path/'_bootstrap.py'
        foreign.write_bytes(Path(command[1]).read_bytes())
        command[1] = str(foreign)
    elif mutation == 'unknown_module':
        command[2] = 'unregistered.worker'
    else:
        (tmp_path/'ravel.py').write_text('raise RuntimeError("shadow")\n')
    assert rdj_anchor.producer(tmp_path, {'command': command, 'cwd': str(tmp_path)}) is None


def test_canonical_bootstrap_matches_the_recognized_module(tmp_path):
    assert rdj_anchor.producer(tmp_path, {'command': module_command('ravel.physics.science_worker', tmp_path),
        'cwd': str(tmp_path)}) == ('module', 'ravel.physics.science_worker')


def test_bare_library_finish_never_gets_supervisor_custody(tmp_path):
    from rdj_fixtures import Run
    run = Run(tmp_path/'run')
    anchor = run.stage('arithmetic', 'outputs/number.json', {'value': 3},
        command=[sys.executable, '-m', 'ravel.physics.science_worker'], register=False)
    assert rdj_anchor.verify(anchor, run.root) == 'generated'
