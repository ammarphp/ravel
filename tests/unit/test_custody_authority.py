"""Custody-registered authority for run files: synthetic receipts, never a tool execution."""
import hashlib
import json
import sys

import pytest

from rdj_fixtures import Run
from ravel.workflow import custody_authority as ca, rdj_custody


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def test_registered_tool_output_is_authority(tmp_path):
    run = Run(tmp_path / 'run')
    anchor = run.stage('probe', 'output/versions.json', {'engine': '2.0'})
    found = ca.stage_output(run.root, anchor['binding']['receipt_id'], 'output/versions.json',
                            anchor['binding']['sha256'])
    assert found['producer'][0] == 'module' and found['path'] == 'output/versions.json'


def test_agent_written_file_is_never_authority(tmp_path):
    run = Run(tmp_path / 'run')
    anchor = run.stage('probe', 'output/versions.json', {'engine': '2.0'})
    pin = run.put('scratch/notes.json', {'engine': '2.0'})
    with pytest.raises(ca.AuthorityError, match='does not list'):
        ca.stage_output(run.root, anchor['binding']['receipt_id'], pin['path'], pin['sha256'])


def test_unregistered_receipt_and_authored_script_are_refused(tmp_path):
    run = Run(tmp_path / 'run')
    anchor = run.stage('probe', 'output/a.json', {'v': 1}, register=False)
    with pytest.raises(ca.AuthorityError, match='registered'):
        ca.stage_output(run.root, anchor['binding']['receipt_id'], 'output/a.json', anchor['binding']['sha256'])
    run.put('scripts/make.py', 'print(1)\n')
    anchor = run.stage('script', 'output/b.json', {'v': 2}, command=[sys.executable, 'scripts/make.py'],
                       inputs=['scripts/make.py'])
    with pytest.raises(ca.AuthorityError, match='recognized'):
        ca.stage_output(run.root, anchor['binding']['receipt_id'], 'output/b.json', anchor['binding']['sha256'])


def test_changed_bytes_after_registration_are_refused(tmp_path):
    run = Run(tmp_path / 'run')
    anchor = run.stage('probe', 'output/a.json', {'v': 1})
    (run.root / 'output/a.json').write_text('{"v": 3}')
    with pytest.raises(ca.AuthorityError):
        ca.stage_output(run.root, anchor['binding']['receipt_id'], 'output/a.json',
                        sha(b'{"v": 3}'))


def test_run_relative_path_resolves_through_a_symlinked_root(tmp_path):
    run = Run(tmp_path / 'run')
    alias = tmp_path / 'alias'
    alias.symlink_to(run.root)
    assert ca.run_relative(alias, alias / 'output/x.json') == 'output/x.json'
    assert ca.run_relative(run.root, str(alias / 'output/x.json')) == 'output/x.json'
    assert ca.run_relative(run.root, tmp_path / 'elsewhere.json') is None


def test_registered_check_and_acquisition(tmp_path):
    run = Run(tmp_path / 'run')
    run.check_result('signal_model_complete_before_calibration', status='passed')
    rel = 'checks/signal_model_complete_before_calibration.json'
    value = ca.registered_check(run.root, rel, sha((run.root / rel).read_bytes()),
                                'signal_model_complete_before_calibration')
    assert value['status'] == 'passed'
    forged = run.put('checks/forged.json', json.loads((run.root / rel).read_text()))
    with pytest.raises(ca.AuthorityError, match='registered'):
        ca.registered_check(run.root, forged['path'], forged['sha256'], 'signal_model_complete_before_calibration')
    pin = run.put('inputs/band.json', {'low': 0.9, 'high': 1.1})
    with pytest.raises(ca.AuthorityError, match='acquisition'):
        ca.acquisition(run.root, pin['path'], pin['sha256'])
    rdj_custody.register_acquisition(run.root, pin['path'], source='acquisition')
    assert ca.acquisition(run.root, pin['path'], pin['sha256'])['source'] == 'acquisition'
