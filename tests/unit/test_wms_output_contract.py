"""Explicit output semantics bound to statically pinned workflow adoptions."""
from copy import deepcopy
import json

import pytest

from ravel.workflow import science, wms_adopt
from test_wms_adopt import study, workflow  # noqa: F401
from test_wms_adopt_governed import _prepare, _request


@pytest.mark.parametrize('contract,outputs', [
    ({}, ['final.txt']), (None, ['final.txt']), ([], ['final.txt']),
    ({'final.txt': 'unknown-artifact-kind'}, ['final.txt']),
    ({'final.txt': ['event_sample']}, ['final.txt']),
    ({'other.txt': 'event_sample'}, ['final.txt']),
    ({'final.txt': 'event_sample'}, ['final.txt', 'first.txt']),
    ({'final.txt': 'event_sample'}, None),
    ({'../final.txt': 'event_sample'}, ['../final.txt']),
])
def test_request_rejects_malformed_or_incomplete_contracts(contract, outputs):
    task = _request(output_contract=contract)
    if outputs is not None:
        task['outputs'] = outputs
    with pytest.raises(ValueError):
        wms_adopt.validate(task)


def test_only_declared_registered_kinds_are_exposed():
    task = _request(outputs=['opaque', 'unrelated.txt'],
                    output_contract={'opaque': 'event_sample', 'unrelated.txt': 'binned_values'})
    wms_adopt.validate(task)
    assert wms_adopt.declared_output_kinds(task) == ['binned_values', 'event_sample']
    assert wms_adopt.declared_output_kinds(_request(outputs=['events.lhe'])) == []


def test_governed_preparation_preserves_explicit_contract_and_pins_bytes(workflow):
    contract = {'final.txt': 'event_sample'}
    result, child, root = _prepare(workflow, _request(outputs=['final.txt'], output_contract=contract))
    record_path = root / 'adoption/adoption.json'
    record = json.loads(record_path.read_text())
    task = json.loads((child / science.SPEC).read_text())['task']
    inspect = json.loads((root / 'adoption/inspect.science.json').read_text())['task']
    assert result['output_contract'] == record['output_contract'] == task['output_contract'] == contract
    assert inspect['output_contract'] == contract
    assert result['adoption'] == wms_adopt._pin(record_path)
    for prepared in (task, inspect):
        wms_adopt.validate(prepared)
        assert record_path in wms_adopt.inputs(prepared, record_path.parent)
        for mutation in ('alter', 'drop'):
            damaged = deepcopy(prepared)
            if mutation == 'alter':
                damaged['output_contract']['final.txt'] = 'binned_values'
            else:
                damaged.pop('output_contract')
            with pytest.raises(ValueError, match='different output_contract'):
                wms_adopt.inputs(damaged, record_path.parent)
    workflow['snakefile'].write_text(workflow['snakefile'].read_text() + '\n# changed bytes\n')
    with pytest.raises(ValueError, match='changed'):
        wms_adopt.inputs(task, record_path.parent)


def test_adopt_run_constructor_retains_contract_and_refuses_changes(workflow):
    contract = {'final.txt': 'event_sample'}
    wms_adopt.adopt(workflow['snakefile'], workflow['workdir'], workflow['rundir'], study(),
                    outputs=['final.txt'], output_contract=contract, snakemake=workflow['snakemake'])
    root = workflow['rundir']
    record = json.loads((root / wms_adopt.RECORD).read_text())
    inspection = {'status': 'passed', 'adoption': wms_adopt._pin(root / wms_adopt.RECORD), 'roster': {}}
    path = root / 'synthetic-inspection.json'
    path.write_text(json.dumps(inspection))
    task = wms_adopt._run_task(root, record, path, inspection)
    assert task['output_contract'] == contract
    wms_adopt.validate(task)
    assert path in wms_adopt.inputs(task, root)
    for changed in ({'final.txt': 'binned_values'}, None):
        damaged = deepcopy(task)
        if changed is None:
            damaged.pop('output_contract')
        else:
            damaged['output_contract'] = changed
        with pytest.raises(ValueError, match='different output_contract'):
            wms_adopt.inputs(damaged, root)


def test_legacy_adoption_does_not_gain_an_implicit_contract(workflow):
    wms_adopt.adopt(workflow['snakefile'], workflow['workdir'], workflow['rundir'], study(),
                    outputs=['final.txt'], snakemake=workflow['snakemake'])
    record = json.loads((workflow['rundir'] / wms_adopt.RECORD).read_text())
    task = wms_adopt._governed_task(record)
    assert 'output_contract' not in task and 'output_contract' not in record
    assert wms_adopt.declared_output_kinds(task) == []
    task['output_contract'] = {'final.txt': 'event_sample'}
    with pytest.raises(ValueError, match='different output_contract'):
        wms_adopt.inputs(task, workflow['rundir'])
