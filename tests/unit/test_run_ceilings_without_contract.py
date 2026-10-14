"""Ceilings of a run directory that holds no task contract."""
import importlib
import os
import pytest
from test_review_points import run, write


def module(): return importlib.import_module('ravel.workflow.run_ceilings')


def test_run_without_contract_resolves_the_analysis_default(tmp_path):
    c = module()
    assert not (tmp_path/'inputs').exists()
    assert c.resolve(tmp_path) == c.default('analysis')
    assert not (tmp_path/'inputs').exists()


def test_run_without_contract_cannot_claim_the_research_default(tmp_path):
    c = module()
    write(tmp_path/c.RECORD, c.default('research'))
    assert c.resolve(tmp_path)['max_invocations'] == 72


def test_run_without_contract_ignores_an_unbound_response_record(tmp_path):
    c = module()
    value = c.default('analysis')
    value.update(source='checkin1_response', max_invocations=10**9, worker_wall_seconds={'producer': 10**6, 'reviewer': 10**6})
    write(tmp_path/c.RECORD, value)
    assert c.resolve(tmp_path) == c.default('analysis')


def test_run_without_contract_charges_against_the_analysis_default(tmp_path):
    c = module()
    c.charge(tmp_path, 'worker', 72)
    with pytest.raises(c.CeilingExceeded): c.charge(tmp_path, 'worker')
    assert len((tmp_path/c.LEDGER).read_text().splitlines()) == 1


def test_present_contract_still_decides_the_shape(tmp_path):
    c = module(); run(tmp_path, route='E')
    assert c.resolve(tmp_path)['max_invocations'] == 120


def test_unreadable_contract_is_refused_not_defaulted(tmp_path):
    c = module()
    write(tmp_path/'inputs/task_contract.json', [])
    with pytest.raises(ValueError, match='task contract must be an object'): c.resolve(tmp_path)
    (tmp_path/'inputs/task_contract.json').unlink()
    os.symlink(tmp_path/'absent.json', tmp_path/'inputs/task_contract.json')
    with pytest.raises(ValueError, match='task contract must be a regular file'): c.resolve(tmp_path)
