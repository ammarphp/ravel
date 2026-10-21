"""Installed routes must declare the inputs their actual mandatory validators consume.

Use the controller's effective validator population, including producer self-checks
owed to reviewing cards. Declarations belong to parameters.check_inputs; merely
naming a validator or relying on a default run-tree path supplies no evidence.
The original value-presence oracle failed before typed sources were introduced;
the same mandatory input population now requires resolvable, type-correct sources.
"""
from __future__ import annotations

from copy import deepcopy

from ravel.controller.step import validate
from ravel.controller.routes import validator_inputs
from ravel.workflow import review_projection_checks as documents
from ravel.workflow import role_registry, run_validator_checks as runs


RUN_INPUTS = {
    **{check: () for check in runs.STATE_CHECKS},
    runs.TRAP_CHECK: ('sweep',),
    'check:validation.validate_run_state.check_resource_census': ('census',),
    'check:validation.validate_task_contract.validate': (),
    'check:physics.normalization_ledger.check': ('ledger',),
    'check:validation.validate_cutflow': (
        'signal', 'routine', 'sigma_pb', 'lumi_fb', 'tables_dir', 'grid', 'm_parent', 'm_lsp', 'srs'),
    'check:validation.input_closure.check': ('fit', 'reference'),
    'check:validation.verify_pack.check_deviations_ledger': (),
    runs.FIGURES_CHECK: ('figures',),
    'check:validation.certificates.validate_certificate': ('path', 'kind'),
    'ravel.validation.calibration_checks': ('spec',),
    **{check: ('spec',) for check in runs.CALIBRATION_SPEC_CHECKS},
    **{check: ('receipt',) for check in runs.CALIBRATION_RECEIPT_CHECKS},
}


def _roles(step):
    return sorted({role for role in (step.get('role'), *step.get('review', ())) if role})


def _requirements(check):
    if check in documents.ML_RESULT_CHECKS:
        return ('record_id', 'spec_sha256', 'subject_sha256')
    if check in runs.ADAPTERS:
        return RUN_INPUTS[check]
    # This is the same document branch as controller.step.validate.run_validators.
    return ('document',)


def missing_inputs(spec):
    problems = []
    for step in spec['steps']:
        bindings = (step.get('parameters') or {}).get('check_inputs') or {}
        for role in _roles(step):
            checks, _ = validate.validator_ids(role_registry.load(role))
            for check in checks:
                required = _requirements(check)
                if not required:
                    continue
                values = bindings.get(check)
                absent = [key for key in required if validator_inputs.source_errors(
                    values.get(key) if type(values) is dict else None,
                    validator_inputs.requirements(check)[key], step=step, steps=spec['steps'], check=check)]
                if absent:
                    problems.append((spec['id'], step['id'], role, check, tuple(absent)))
    return problems


def test_every_run_adapter_has_an_explicit_input_contract():
    assert set(RUN_INPUTS) == set(runs.ADAPTERS)
    assert {check: tuple(validator_inputs.requirements(check)) for check in runs.ADAPTERS} == RUN_INPUTS


def test_contract_pin_sources_require_the_schema_to_declare_both_custody_fields():
    step = {'id': 'inspect'}
    ref = {'source': 'contract', 'field': '/execution_plan', 'type': 'pin'}
    assert validator_inputs.source_errors(ref, 'pin', step=step, steps=[step], check='check:validation.input_closure.check') == []
    ref['field'] = '/task_requirements'
    assert validator_inputs.source_errors(ref, 'pin', step=step, steps=[step], check='check:validation.input_closure.check')
    assert validator_inputs.typed(10 ** 10000, 'number') is False


def test_every_installed_route_declares_its_mandatory_validator_inputs():
    # Import by module name because routes exports a select function as well.
    from importlib import import_module
    selection = import_module('ravel.controller.routes.select')
    problems = [problem for spec in selection.installed_specs() for problem in missing_inputs(spec)]
    assert not problems, '\n'.join(map(str, problems))


def test_late_bound_execution_roles_keep_their_actual_validator_sources():
    from importlib import import_module
    selection = import_module('ravel.controller.routes.select')
    spec = next(s for s in selection.installed_specs() if s['id'] == 'study')
    step = deepcopy(next(s for s in spec['steps'] if s['id'] == 'operate'))
    step['role'] = 'calculation'
    validator_inputs.declare_role_inputs(step)
    checks = {check for role in _roles(step) for check in validate.validator_ids(role_registry.load(role))[0]}
    assert 'check:validation.input_closure.check' in checks
    assert validator_inputs.declaration_errors(step, [step], checks) == []
    # A newly owed source is still a reference; declaring it manufactures no fit or reference value.
    assert step['parameters']['check_inputs']['check:validation.input_closure.check']['fit'] == {
        'source': 'output', 'step': 'operate', 'path': 'outputs/result.json',
        'field': '/validator_inputs/check:validation.input_closure.check/fit', 'type': 'pin'}


def test_missing_inputs_includes_producer_inherited_checks_and_requires_the_schema_location():
    step = {'id': 'inspect', 'role': 'analysis-author', 'review': [], 'parameters': {},
            'outputs': [{'path': 'outputs/result.json', 'kind': 'document', 'required': True}]}
    spec = {'id': 'fictional', 'steps': [step]}
    checks, _ = validate.validator_ids(role_registry.load('analysis-author'))
    assert 'check:validation.validate_cutflow' in checks
    bindings = {check: {key: {'source': 'output', 'step': 'inspect', 'path': 'outputs/result.json',
                            'field': '/' + key, 'type': kind}
                        for key, kind in validator_inputs.requirements(check).items()} for check in checks}
    step['parameters']['validator_exports'] = {'outputs/result.json': {
        '/' + key: kind for check in checks for key, kind in validator_inputs.requirements(check).items()}}
    step['parameters']['check_inputs'] = bindings
    assert missing_inputs(spec) == []
    damaged = deepcopy(spec)
    damaged['steps'][0]['check_inputs'] = damaged['steps'][0]['parameters'].pop('check_inputs')
    assert any(problem[3] == 'check:validation.validate_cutflow' for problem in missing_inputs(damaged))
    damaged = deepcopy(spec)
    del damaged['steps'][0]['parameters']['check_inputs']['check:validation.validate_cutflow']['sigma_pb']
    assert any(problem[3:] == ('check:validation.validate_cutflow', ('sigma_pb',))
               for problem in missing_inputs(damaged))
    damaged = deepcopy(spec)
    damaged['steps'][0]['parameters']['check_inputs']['check:validation.validate_cutflow']['sigma_pb']['type'] = 'string'
    assert any(problem[3:] == ('check:validation.validate_cutflow', ('sigma_pb',))
               for problem in missing_inputs(damaged))
    damaged = deepcopy(spec)
    damaged['steps'][0]['parameters']['check_inputs']['check:validation.validate_cutflow']['sigma_pb'] = 1.0
    assert missing_inputs(damaged)  # A literal value cannot stand in for a declared source.


def test_mandatory_trap_sweeps_have_a_declared_producer_and_dependency():
    from importlib import import_module
    selection = import_module('ravel.controller.routes.select')
    problems = []
    for spec in selection.installed_specs():
        by_id = {step['id']: step for step in spec['steps']}
        for step in spec['steps']:
            checks = {check for role in _roles(step)
                      for check in validate.validator_ids(role_registry.load(role))[0]}
            if runs.TRAP_CHECK not in checks:
                continue
            # A reviewer may check its parent's own staged sweep; the producer's
            # self-check also runs after adoption. Otherwise it needs a predecessor.
            produced = any(output.get('kind') == 'validation:trap-sweep' and output.get('required', True)
                           for output in step.get('outputs', ()))
            for item in step.get('inputs', ()):
                source, sep, path = item.get('artifact', '').partition(':')
                producer = by_id.get(source)
                if sep and producer and source in step.get('depends_on', ()):
                    produced |= any(output.get('path') == path and output.get('kind') == 'validation:trap-sweep'
                                    and output.get('required', True) for output in producer.get('outputs', ()))
            if not produced:
                problems.append((spec['id'], step['id']))
    assert not problems, '\n'.join(map(str, problems))
