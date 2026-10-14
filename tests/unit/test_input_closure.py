"""Synthetic transitive fit and candidate-selection independence controls."""
import hashlib
import importlib
import json

import pytest


def module():
    return importlib.import_module('ravel.validation.input_closure')


def pin(root, name, value):
    path = root / name
    path.write_text(json.dumps(value))
    return {'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def example(root, *, use_reference=False):
    reference = pin(root, 'reference.json', {'value': 3})
    independent = pin(root, 'design.json', {'value': 7})
    fit = pin(root, 'fit.json', {'inputs': [reference if use_reference else independent]})
    return fit, reference


@pytest.mark.parametrize('use_reference', [True, False])
def test_certifying_reference_in_fit_input_closure_refused(tmp_path, use_reference):
    fit, reference = example(tmp_path, use_reference=use_reference)
    report = module().check(tmp_path, fit, reference)
    assert report['independent'] is not use_reference
    assert bool(report['errors']) is use_reference


def test_transitive_selection_oracle_and_alias_cannot_certify(tmp_path):
    fit, reference = example(tmp_path)
    (tmp_path / 'alias.json').write_bytes((tmp_path / reference['path']).read_bytes())
    alias = {**reference, 'path': 'alias.json'}
    selection = pin(tmp_path, 'selection.json', {'inputs': [fit, alias]})
    assert not module().check(tmp_path, selection, reference)['independent']


@pytest.mark.parametrize('mutation', ['stale', 'escape', 'missing', 'cycle'])
def test_incomplete_or_invalid_closure_refused(tmp_path, mutation):
    fit, reference = example(tmp_path)
    if mutation == 'stale': (tmp_path / 'design.json').write_text('changed')
    if mutation == 'escape': fit['path'] = '../fit.json'
    if mutation == 'missing': (tmp_path / 'design.json').unlink()
    if mutation == 'cycle':
        # Reachable repeated path with inconsistent bytes cannot be a valid pin DAG.
        fit = pin(tmp_path, 'fit.json', {'inputs': [{'path': 'fit.json', 'sha256': 'a'*64}]})
    report = module().check(tmp_path, fit, reference)
    assert not report['independent'] and report['errors']


def test_verifier_gate_uses_run_bound_fit_not_action_override(tmp_path):
    from ravel.workflow import decision_gate
    fit, reference = example(tmp_path, use_reference=True)
    (tmp_path / 'inputs').mkdir()
    plan = pin(tmp_path, 'plan.json', {'nodes': [], 'claims': [], 'edges': [],
                                      'certifications': [{'fit': fit, 'reference': reference}]})
    (tmp_path / 'inputs/task_contract.json').write_text(json.dumps({'agent_layer_epoch': 2, 'request_plan': plan}))
    errors = decision_gate.check(tmp_path, 'checkin2_accept', {'certifications': []})
    assert any(e.code == 'reference_in_input_closure' for e in errors)


def test_schema_shaped_node_certification_metadata_cannot_be_erased(tmp_path):
    from ravel.workflow import decision_gate
    from ravel.validation import intake_records
    from ravel.validation.validate_task_contract import _schema_errors
    fit, reference = example(tmp_path, use_reference=True)
    fields = [{'pointer': '/review/certifications', 'value': [{'fit': fit, 'reference': reference}],
               'authority': 'supplied', 'evidence': None}]
    assert not _schema_errors(fields, intake_records.NODE['properties']['fields'], 'fields')
    (tmp_path / 'inputs').mkdir()
    request = pin(tmp_path, 'plan.json', {'nodes': [{'id': 'N1', 'kind': 'operation', 'operation': 'literal-calculation', 'fields': fields}], 'claims': [], 'edges': []})
    (tmp_path / 'inputs/task_contract.json').write_text(json.dumps({'agent_layer_epoch': 2, 'request_plan': request}))
    assert any(e.code == 'reference_in_input_closure' for e in decision_gate.check(tmp_path, 'checkin2_accept', {}))
