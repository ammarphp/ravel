"""Original calculation completion through its actual applicable scientific law.

A result JSON alone is insufficient. The child must retain the exact calculation
source, prepared runtime, CHECK-IN1 approval and successful supervised stage.
Only authenticated complete literal arithmetic uses the deterministic shortcut.
Other calculations retain the existing scoped child and whole-parent reviews,
including their actual units, source evidence, delivery recipe and current gates.
"""
from copy import deepcopy
from pathlib import Path
from . import science, execution
from .task_completion import _Inputs, _contract


def completion_route(parent_contract, *, base_dir):
    """Select from the exact original operation, never a caller's exemption label."""
    from ravel.physics import literal_calculation
    observed = _Inputs(base_dir)
    try:
        contract, _, _, _ = _contract(parent_contract, observed)
        if contract['task_mode'] != 'calculation':
            raise ValueError('actual original calculation parent required')
        literal = False
        try:
            expression = literal_calculation.expression_from_prompt(contract['prompt'])
            literal_calculation.validate_parent(
                {'parent_contract': parent_contract, 'expression': expression,
                 'unit': literal_calculation.exact_value(expression)['unit']}, base_dir)
            literal = True
        except ValueError:
            # A valid physical/symbolic question or additional scientific
            # obligations requires scientific completion, not a reduced answer.
            pass
        observed.finish()
        return {'kind': 'calculation-completion-route', 'parent_contract': deepcopy(parent_contract),
            'original_request': contract['prompt'], 'literal': literal,
            'child_schema_version': 1 if literal else 2,
            'collection_api': 'ravel.workflow.calculation_completion.collect' if literal else None,
            'completion_api': ('ravel.validation.validate_run_state.evaluate' if literal
                               else 'ravel.workflow.task_completion.require_final'),
            'completion_path': 'inputs/calculation_delivery.json' if literal else 'inputs/task_completion.json',
            'execution_authorized': False, 'parent_task_accepted': False}
    finally:
        observed.close()


def _evaluate_scientific_parent(rundir, contract, stage_limit):
    from . import task_completion
    observed = _Inputs(rundir)
    accepted = False; parent_valid = False; artifact = None; checks = []
    try:
        parent_path = Path(rundir) / 'inputs/task_contract.json'
        parent_pin = observed.capture(parent_path)
        current, _, _, _ = _contract(parent_pin, observed)
        if current != contract or current['task_mode'] != 'calculation':
            raise ValueError('caller differs from the exact original scientific calculation')
        parent_valid = True
        if stage_limit != 'task_contract':
            artifact = str(Path(rundir) / 'inputs/task_completion.json')
            completion_pin = observed.capture(Path(artifact))
            request = observed.document(completion_pin)
            if request.get('contract') != parent_pin:
                raise ValueError('scientific calculation completion must bind this exact original parent')
            # All public whole-parent/CI3 gates still run. The nested consumer
            # owns the same current sessions through the final return check.
            result = task_completion.require_final(completion_pin, base_dir=rundir, _inputs=observed)
            accepted = result['parent_task_accepted']
            checks.append({'name': 'whole-task', 'level': 'PASS',
                'msg': 'Current scoped child and whole-parent reviews capture the complete original calculation, scientific quantities and delivery recipe'})
            # The public completion consumer owns the final shared observation
            # and closes its contributing review sessions before returning.
        else:
            observed.finish()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        accepted = False
        checks.append({'name': 'whole-task', 'level': 'FAIL', 'msg': str(exc)})
    finally:
        observed.close()
    stages = [{'name': 'task_contract', 'required': 'R', 'status': 'PASS' if parent_valid else 'FAIL',
               'artifact': 'inputs/task_contract.json', 'checks': []}]
    if stage_limit != 'task_contract':
        stages += [
            {'name': 'result_pack', 'required': 'R', 'status': 'PASS' if accepted else 'FAIL', 'artifact': artifact, 'checks': checks},
            {'name': 'basis_manifest', 'required': 'N/A', 'status': 'N/A', 'artifact': None,
             'checks': [{'name': 'applicability', 'level': 'INFO',
                         'msg': 'Scientific child/parent review owns any actual comparison obligations; calculation does not fabricate curves'}]},
            {'name': 'verification', 'required': 'R', 'status': 'PASS' if accepted else 'FAIL', 'artifact': artifact, 'checks': checks}]
    passed = parent_valid if stage_limit == 'task_contract' else accepted
    return {'rundir': str(rundir), 'task_mode': 'calculation', 'compute_plan': contract['compute_plan'],
        'stat_mode': contract['stat_mode'], 'legacy': False, 'stages': stages,
        'invariants': [] if stage_limit == 'task_contract' else [
            {'name': 'scientific-whole-parent-completion', 'status': 'PASS' if accepted else 'FAIL',
             'detail': 'Existing actual scoped child and whole-parent reviews, original units, sources and report remain required'}],
        'completion_scope': 'original_task_completion', 'parent_task_accepted': accepted,
        'physics_validated': False, 'verdict': 'PASS' if passed else 'FAIL', 'exit': 0 if passed else 1}


def _child(parent_pin, child_root, observed):
    from ravel.physics import literal_calculation
    rd = science.root(child_root)
    for name in (science.SPEC, science.PLAN, science.APPROVAL, 'execution_attempt.json', execution.STATE_NAME,
                 'outputs/result.json', 'outputs/verification.json', 'outputs/recipe.json', 'outputs/checkin2.json'):
        observed.capture(rd / name)
    proposal = science.verify_plan(rd, approved=True)
    spec = observed.document(observed.capture(rd / science.SPEC))
    if spec['mode'] != 'literal-calculation' or spec['schema_version'] != 1 or spec['task']['parent_contract'] != parent_pin:
        raise ValueError('actual child must bind this complete original literal calculation')
    # One session covers native ledger/input/output custody through the final read.
    session = observed.review_session(rd)
    errors = execution.validate_completed_execution(rd, proposal['stages'], _session=session)
    if errors: raise ValueError('ordinary calculation stage is not complete: ' + '; '.join(errors))
    view = science.packet(rd)
    if view['lifecycle_verdict'] != 'PASS' or view['execution']['status'] != 'completed':
        raise ValueError('actual approved ordinary calculation delivery is not current')
    result_pin = observed.capture(rd / 'outputs/result.json')
    result = literal_calculation.validate_result(observed.document(result_pin), spec['task'], proposal['base_dir'])
    return {'child_root': str(rd), 'parent_contract': deepcopy(parent_pin), 'result': result_pin,
            'quantity': deepcopy(result['quantity']), 'expression': result['expression'],
            'ordinary_approval_required': True, 'ordinary_stage_complete': True,
            'parent_task_accepted': True, 'scope': literal_calculation.SCOPE,
            'physics_validated': False, 'calibration_claimed': False}


def collect(parent_contract, child_root, output_path, *, base_dir):
    from .intake_planner import _write
    observed = _Inputs(base_dir)
    try:
        contract, _, _, _ = _contract(parent_contract, observed)
        if contract['task_mode'] != 'calculation': raise ValueError('actual calculation parent required')
        expected_path = Path(parent_contract['path']).parent / 'calculation_delivery.json'
        if Path(output_path).absolute() != expected_path:
            raise ValueError('calculation completion belongs beside its original parent contract')
        value = {'schema_version': 1, 'kind': 'calculation-parent-delivery',
            'original_request': contract['prompt'], **_child(parent_contract, child_root, observed)}
        pin = _write(expected_path, value, observed)
        if value != {'schema_version': 1, 'kind': 'calculation-parent-delivery',
                     'original_request': contract['prompt'], **_child(parent_contract, child_root, observed)}:
            raise ValueError('ordinary calculation changed during parent publication')
        observed.finish()
        return deepcopy(pin)
    finally: observed.close()


def evaluate_parent(rundir, contract, stage_limit=None):
    # The full original parent determines the shortcut. A source-development
    # proposal, physical quantity or merely self-labelled answer cannot select it.
    parent_path = Path(rundir) / 'inputs/task_contract.json'
    selector = _Inputs(rundir)
    try:
        parent_pin = selector.capture(parent_path)
        route = completion_route(parent_pin, base_dir=rundir)
        selector.finish()
    except (OSError, ValueError, KeyError, TypeError):
        # The scientific consumer reports the actual missing/changed contract;
        # this fallback never confers deterministic authority or acceptance.
        return _evaluate_scientific_parent(rundir, contract, stage_limit)
    finally:
        selector.close()
    if not route['literal']:
        return _evaluate_scientific_parent(rundir, contract, stage_limit)
    observed = _Inputs(rundir)
    checks = []; accepted = False; artifact = None; parent_valid = False
    try:
        parent_path = Path(rundir) / 'inputs/task_contract.json'
        pin = observed.capture(parent_path)
        current, _, _, _ = _contract(pin, observed)
        if current != contract: raise ValueError('caller contract differs from exact original calculation')
        parent_valid = True
        if stage_limit == 'task_contract':
            observed.finish()
            return {'rundir': str(rundir), 'task_mode': 'calculation', 'compute_plan': contract['compute_plan'],
                'stat_mode': contract['stat_mode'], 'legacy': False, 'stages': [
                    {'name': 'task_contract', 'required': 'R', 'status': 'PASS', 'artifact': str(parent_path), 'checks': []}],
                'invariants': [], 'verdict': 'PASS', 'exit': 0}
        artifact_path = parent_path.parent / 'calculation_delivery.json'
        if not artifact_path.exists():
            checks.append({'name': 'actual-operation', 'level': 'FAIL',
                'msg': 'Prepare, approve and execute the bound literal calculation child, then collect its actual delivery'})
        else:
            artifact = str(artifact_path)
            value = observed.document(observed.capture(artifact_path))
            expected = {'schema_version': 1, 'kind': 'calculation-parent-delivery',
                'original_request': contract['prompt'], **_child(pin, value['child_root'], observed)}
            from .intake_planner import _bytes
            if _bytes(value) != _bytes(expected): raise ValueError('parent delivery differs from exact actual approved operation')
            checks.append({'name': 'actual-operation', 'level': 'PASS',
                'msg': 'Exact original expression, dimensionless units, current runtime/source, approved plan and completed stage agree'})
            accepted = True
        observed.finish()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        accepted = False; checks.append({'name': 'actual-operation', 'level': 'FAIL', 'msg': str(exc)})
    finally: observed.close()
    return {'rundir': str(rundir), 'task_mode': 'calculation', 'compute_plan': contract['compute_plan'],
        'stat_mode': contract['stat_mode'], 'legacy': False,
        'stages': [{'name': 'task_contract', 'required': 'R', 'status': 'PASS' if parent_valid else 'FAIL', 'artifact': 'inputs/task_contract.json', 'checks': []},
            {'name': 'result_pack', 'required': 'R', 'status': 'PASS' if accepted else 'FAIL', 'artifact': artifact, 'checks': checks},
            {'name': 'basis_manifest', 'required': 'N/A', 'status': 'N/A', 'artifact': None,
             'checks': [{'name': 'applicability', 'level': 'INFO', 'msg': 'Literal calculation has no comparison curves'}]},
            {'name': 'verification', 'required': 'R', 'status': 'PASS' if accepted else 'FAIL', 'artifact': artifact, 'checks': checks}],
        'invariants': [{'name': 'approved-source-bound-operation', 'status': 'PASS' if accepted else 'FAIL',
                        'detail': 'Actual ordinary child authority and complete literal result required'}],
        'completion_scope': 'complete_literal_dimensionless_calculation',
        'parent_task_accepted': accepted, 'physics_validated': False,
        'verdict': 'PASS' if accepted else 'FAIL', 'exit': 0 if accepted else 1}
