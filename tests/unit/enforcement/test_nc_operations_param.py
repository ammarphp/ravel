"""Operation rows: admission by the registered signature (TOOL) and execution by the registered production role (EXEC).

Both cases take their rows from the package data (``operation_signatures.json`` and ``roles/executors.json``)
through ``nc_cases.dimension_rows``, so an operation added to either table is covered the day it is installed.
The adversary is a plan step that names an artifact kind, an effect, a cost, a critical value or an executing
role its operation's registration does not allow. Oracles are written here from the package data and the rows'
specifications, never from the admission or executor check itself; each positive control is the step made to
conform. Declaring a signature grants no scientific support: these cases show only that a step outside it is
refused before launch. Both cases are bound to CONTROLLER and end with the declared ``pending-integration:`` skip
while ``ravel.controller`` is not installed.
"""
from __future__ import annotations

from copy import deepcopy
import json
import sys

import pytest

from nc_cases import CONTROLLER, dimension_case, dimension_rows, require_controller
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register, returns

FICTIONAL_KIND = 'undeclared-fixture-kind'
FICTIONAL_EFFECT = 'undeclared_fixture_effect'
CEILING = 10  # the cost ceiling every pointer resolves to in the conforming step, in the signature's own unit
WITHIN = 5


def _name(function, row):
    """The mutation-adequacy identifier of one parameterized row of ``function``."""
    return f'{function.__name__}[{row}]'


def _package_json(*parts):
    from ravel.paths import package_data_path
    return json.loads(package_data_path(*parts).read_text())


def _set(document, pointer, value):
    """Set the object path ``pointer`` (``/a/b``) of ``document``, creating the objects on the way."""
    parts = pointer.lstrip('/').split('/')
    for part in parts[:-1]:
        document = document.setdefault(part, {})
    document[parts[-1]] = value


def _unset(document, pointer):
    parts = pointer.lstrip('/').split('/')
    for part in parts[:-1]:
        document = document[part]
    del document[parts[-1]]


# ---------------------------------------------------------------- TOOL: admission by signature

def _conforming(name, signature):
    """A step the signature admits: a produced kind, declared effects only, a resolved ceiling and cost within it."""
    task = {}
    for field in signature['critical_fields']:
        _set(task, field, 'approved')
    parameters = {'task': task, 'effects': list(signature['effects'])}
    pointer = signature['cost']['ceiling_pointer']
    if pointer:
        _set(task, pointer, CEILING)
        parameters['cost'] = {'unit': signature['cost']['unit'], 'amount': WITHIN}
    return {'id': 's01', 'kind': 'operate', 'operation': name, 'depends_on': [], 'inputs': [],
            'outputs': [{'path': 'outputs/result.out', 'kind': signature['produces'][0]['kind'], 'required': True}],
            'parameters': parameters}


@dimension_case('TOOL', binding=CONTROLLER)
@pytest.mark.parametrize('row', dimension_rows('TOOL'), ids=str)
def test_tool_admission_refuses_an_undeclared_artifact_effect_cost_or_changed_critical_value(nc, row):
    operations = require_controller('step.operations')
    name = row.split('-', 1)[1]
    signature = _package_json('operation_signatures.json')['operations'][name]
    step = _conforming(name, signature)
    approved = deepcopy(step)

    def codes(errors):
        return [error['code'] for error in errors]

    # Positive control: the conforming step, bound to its approved copy, is admitted.
    assert operations.admission_errors(step, approved=approved) == [], name

    # An output of a kind the operation does not produce.
    undeclared = deepcopy(step)
    undeclared['outputs'].append({'path': 'outputs/extra.out', 'kind': FICTIONAL_KIND, 'required': True})
    errors = operations.admission_errors(undeclared, approved=approved)
    assert codes(errors) == ['operation_artifact_undeclared'], (name, errors)
    assert (errors[0]['direction'], errors[0]['kind']) == ('output', FICTIONAL_KIND), errors
    # An input artifact of a kind the operation does not consume (and one it does consume is admitted). An operation
    # that declares no consumed kind at all is left out: the admission check skips the input kinds for it.
    if signature['consumes']:
        foreign = [{'artifact': 's00:outputs/x.out', 'kind': FICTIONAL_KIND}]
        errors = operations.admission_errors(step, inputs_custody=foreign, approved=approved)
        assert codes(errors) == ['operation_artifact_undeclared'], (name, errors)
        assert (errors[0]['direction'], errors[0]['kind']) == ('input', FICTIONAL_KIND), errors
        consumed = [{'artifact': 's00:outputs/x.out', 'kind': signature['consumes'][0]['kind']}]
        assert operations.admission_errors(step, inputs_custody=consumed, approved=approved) == []
    # An effect the operation does not declare.
    effect = deepcopy(step)
    effect['parameters']['effects'] = [*signature['effects'], FICTIONAL_EFFECT]
    errors = operations.admission_errors(effect, approved=approved)
    assert codes(errors) == ['operation_effect_undeclared'] and errors[0]['effects'] == [FICTIONAL_EFFECT], errors
    # A requested cost above the ceiling the approved task sets; at the ceiling it is within; with no ceiling in
    # the task the cost cannot be bounded at all.
    pointer = signature['cost']['ceiling_pointer']
    if pointer:
        above = deepcopy(step)
        above['parameters']['cost']['amount'] = CEILING + 1
        errors = operations.admission_errors(above, approved=approved)
        assert codes(errors) == ['operation_cost_above_ceiling'], (name, errors)
        assert (errors[0]['requested'], errors[0]['ceiling']) == (CEILING + 1, CEILING), errors
        at = deepcopy(step)
        at['parameters']['cost']['amount'] = CEILING
        assert operations.admission_errors(at, approved=approved) == []
        unbounded = deepcopy(step)
        _unset(unbounded['parameters']['task'], pointer)
        assert codes(operations.admission_errors(unbounded)) == ['operation_ceiling_unresolved'], name
    # A critical value of the task that differs from the approved one, whichever of them it is.
    for field in signature['critical_fields']:
        changed = deepcopy(step)
        _set(changed['parameters']['task'], field, 'changed after approval')
        errors = operations.admission_errors(changed, approved=approved)
        assert codes(errors) == ['operation_critical_field_changed'] and errors[0]['field'] == field, (name, errors)
    # A command operation runs the module its signature names, and no other program.
    implementation = signature['implementation']
    if implementation['kind'] == 'command' and implementation.get('module'):
        other = deepcopy(step)
        other['parameters']['launch'] = {'argv': [sys.executable, '-c', 'pass']}
        errors = operations.admission_errors(other, approved=approved)
        assert codes(errors) == ['operation_implementation_mismatch'], (name, errors)
        same = deepcopy(step)
        same['parameters']['launch'] = {'argv': [sys.executable, '-m', implementation['module']]}
        assert operations.admission_errors(same, approved=approved) == []


register(Mutation('M07', 'ravel.controller.step.operations:admission_errors', returns(lambda: []),
                  (_name(test_tool_admission_refuses_an_undeclared_artifact_effect_cost_or_changed_critical_value,
                         'TOOL-acquire-published'),),
                  binding=MUTATION_CONTROLLER, why='a step is admitted whatever its signature declares'))


# ---------------------------------------------------------------- EXEC: execution by the production role

@dimension_case('EXEC', binding=CONTROLLER)
@pytest.mark.parametrize('row', dimension_rows('EXEC'), ids=str)
def test_exec_compute_operation_runs_only_through_its_registered_production_role(nc, row):
    operations = require_controller('step.operations')
    from ravel.workflow import role_registry
    name = row.split('-', 1)[1]
    required = _package_json('roles', 'executors.json')['operations'][name]
    roles = sorted(card['id'] for card in role_registry.all_cards())
    assert required in roles, f'{name} names a production role the registry does not hold'

    tasks = [(required, {})]
    if name == 'external-workflow':
        request = {'schema_version': 1, 'operation': 'run', 'snakefile': 'Snakefile',
                   'targets': [], 'cores': 1}
        tasks = [(required, {**request, 'outputs': ['opaque'],
                             'output_contract': {'opaque': 'event_sample'}}),
                 ('calculation', request)]
    for expected, task in tasks:
        step = {'operation': name, 'parameters': {'task': task}}
        # Positive control: the declared product's production role runs the operation.
        assert operations.executor_errors({**step, 'role': expected}) == []
        # Every other registered role and no worker remain refused for each contract.
        for named in [*(role for role in roles if role != expected), None]:
            errors = operations.executor_errors({**step, 'role': named})
            assert [(e['code'], e['operation'], e['required'], e['named']) for e in errors] == [
                ('executor_role_mismatch', name, expected, named)], (name, named, errors)
        assert [e['code'] for e in operations.executor_errors(step)] == ['executor_role_mismatch']


register(Mutation('M06', 'ravel.controller.step.operations:executor_errors', returns(lambda: []),
                  (_name(test_exec_compute_operation_runs_only_through_its_registered_production_role,
                         'EXEC-amplitude-crosscheck'),),
                  binding=MUTATION_CONTROLLER, why='any role, or none, runs a compute operation'))
