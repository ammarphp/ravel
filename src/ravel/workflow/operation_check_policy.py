"""Applicability of producer checks from a pinned operation's declared products.

This supplies policy evidence, never a validator result or replacement input.
Unknown products remain subject to the physical checks. An adopted workflow's
declared output contract decides both ways (its physical outputs add the checks).
Any other registered operation is classified only when every product its signature
declares is non-physical: the physical checks then do not apply to that step. A
registered operation with a physical product keeps its executor card's checks as they are.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

NORMALIZATION = 'check:physics.normalization_ledger.check'
CUTFLOW = 'check:validation.validate_cutflow'
TRAPS = 'check:validation.validate_run_state.check_trap_sweep'
CHECKS = frozenset((NORMALIZATION, CUTFLOW, TRAPS))
NONPHYSICAL = frozenset(('document', 'figure', 'expression', 'parameter_point'))
# The input-closure check certifies a fitted or certified value against its reference. It is classified only for a
# card that already owes it; a declared parameter point may be a fit result, so only products that are all
# documents, figures or expressions carry no value for it to certify.
INPUT_CLOSURE = 'check:validation.input_closure.check'
NO_CERTIFIED_VALUE = frozenset(('document', 'figure', 'expression'))
# Cutflow and acceptance checks bind to event-level outputs: a sample, selection, binned yields, a cutflow, or a
# table (which may carry yields). Products known to carry no event-level content dispose them; any other or
# unclassified kind keeps them (decision D1: producer checks follow the step's declared outputs).
ACCEPTANCE = 'check:validation.certify_acceptance'
EVENT_CHECKS = frozenset((CUTFLOW, ACCEPTANCE))
NON_EVENT_LEVEL = frozenset((*NONPHYSICAL, 'comparison', 'judgment-record', 'answer', 'protocol-evidence',
                             'scalar', 'inference', 'statistical_model', 'model'))


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def products(operation, task):
    """Resolve an adopted-workflow output contract, or its registered receipt scope."""
    from . import wms_adopt
    if operation != wms_adopt.MODE:
        return None
    from ravel.validation.validate_request_plan import signatures
    signature = signatures()[operation]
    kinds = wms_adopt.declared_output_kinds(task)
    declared = task.get('output_contract')
    if declared is not None:
        # Both request and prepared forms must obey the adapter's typed contract.
        wms_adopt.validate(task)
    return {'kinds': kinds or [row['kind'] for row in signature['produces']],
            'declaration': deepcopy(declared), 'signature_sha256': _digest(signature),
            'source': 'task.output_contract' if declared is not None else 'operation_signature.produces'}


def registered_products(operation):
    """The products a registered operation's signature declares, or None (unregistered, or none declared)."""
    from ravel.validation.validate_request_plan import signatures
    signature = signatures().get(operation) if type(operation) is str else None
    kinds = [row.get('kind') for row in (signature or {}).get('produces') or () if type(row) is dict]
    if not kinds or not all(type(kind) is str and kind for kind in kinds):
        return None
    return {'kinds': kinds, 'declaration': None, 'signature_sha256': _digest(signature),
            'source': 'operation_signature.produces'}


def executor(operation, task, default):
    found = products(operation, task)
    if found is None:
        return default
    return 'calculation' if set(found['kinds']) <= NONPHYSICAL else 'analysis-author'


def _rows(step, check_ids, found, policy):
    applies = not found['kinds'] or not set(found['kinds']) <= NONPHYSICAL
    evidence = {'step_id': step['id'], 'operation': step.get('operation'),
                'step_sha256': _digest(step), 'products': found, 'policy': policy}
    result = {check: {'applies': applies,
                      'reason': 'physical_or_unclassified_outputs' if applies else 'no_declared_physical_outputs',
                      'evidence': evidence}
              for check in check_ids if check in CHECKS}
    if INPUT_CLOSURE in check_ids:
        certifies = not found['kinds'] or not set(found['kinds']) <= NO_CERTIFIED_VALUE
        result[INPUT_CLOSURE] = {
            'applies': certifies,
            'reason': 'certified_or_unclassified_outputs' if certifies else 'no_declared_certified_value',
            'evidence': {**evidence, 'policy': 'declared_certified_values_require_input_closure'}}
    return result


def classify(step, check_ids):
    """An adopted workflow's dispositions both ways: its physical outputs add the checks to its producer."""
    task = (step.get('parameters') or {}).get('task') or {}
    found = products(step.get('operation'), task)
    if found is None:
        return {}
    return _rows(step, check_ids, found, 'declared_physical_products_require_producer_checks')


def declared_outputs(step):
    """The output kinds a step without an operation declares, or None (none declared, or one is untyped)."""
    kinds = [row.get('kind') if type(row) is dict else None for row in step.get('outputs') or ()]
    if not kinds or not all(type(kind) is str and kind for kind in kinds):
        return None
    return {'kinds': kinds, 'declaration': deepcopy(step.get('outputs')), 'signature_sha256': None,
            'source': 'step.outputs'}


def dispositions(step, check_ids):
    """``classify``, else the not-applicable rows of a step whose declared products are all non-physical: a
    registered operation's signature products, or a step without an operation by its declared output kinds.
    These rows never add a check; they only decide checks the producer already owes."""
    found = classify(step, check_ids)
    if found:
        return found
    if step.get('operation'):
        declared = registered_products(step['operation'])
        policy = 'registered_nonphysical_products_owe_no_physical_checks'
    else:
        declared = declared_outputs(step)
        policy = 'declared_nonphysical_outputs_owe_no_physical_checks'
    if declared is None:
        return {}
    if set(declared['kinds']) <= NONPHYSICAL:
        return _rows(step, check_ids, declared, policy)
    return _event_rows(step, check_ids, declared)


def _event_rows(step, check_ids, found):
    """The not-applicable cutflow and acceptance rows of a step whose declared products include a physical one but
    none that is event-level (every declared kind is known to carry no event-level content). An event-level or
    unclassified output keeps them owed: no row is returned, so these rows never add a check."""
    if not set(found['kinds']) <= NON_EVENT_LEVEL:
        return {}
    evidence = {'step_id': step['id'], 'operation': step.get('operation'), 'step_sha256': _digest(step),
                'products': found, 'policy': 'event_level_checks_follow_declared_outputs'}
    return {check: {'applies': False, 'reason': 'no_declared_event_level_outputs', 'evidence': evidence}
            for check in check_ids if check in EVENT_CHECKS}
