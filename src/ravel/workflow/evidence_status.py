"""Receipt-derived quantity evidence, distinct from scientific claim authority.

Only current supervised outputs are executed. Known validators are recomputed;
an arbitrary receipt's successful status cannot certify a quantity. Reference
validation describes exactly the supplied reference and declared tolerance.
"""
from pathlib import Path
import math
from . import execution, physics_review


def _number(document, pointer):
    if type(pointer) is not str or not pointer.startswith('/'):
        raise ValueError('quantity requires an explicit JSON pointer')
    value = document
    for part in pointer[1:].split('/'):
        key = part.replace('~1', '/').replace('~0', '~')
        value = value[int(key)] if type(value) is list else value[key]
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('finite numerical quantity required')
    return value


def derive(root, *, quantity, execution_receipts, validator_receipts, _inputs=None):
    from .task_completion import _Inputs
    observed = _inputs or _Inputs(root); own = _inputs is None
    root = Path(root).absolute()
    try:
        subject = observed.canonical(quantity); document = observed.document(subject)
        if type(execution_receipts) is not list or not execution_receipts or len(execution_receipts) > 128:
            raise ValueError('current successful execution receipts required')
        emitted = False
        session = observed.review_session(root)
        for pin in execution_receipts:
            _, path = observed.file(pin)
            if not path.is_relative_to(root): raise ValueError('execution receipt must belong to quantity run')
            physics_review._receipt(root, str(path), _session=session)
            record = observed.document(pin)
            for output, snapshot in record['output_snapshot'].items():
                for entry in snapshot['files']:
                    artifact = Path(output) if entry['name'] == '.' else Path(output) / entry['name']
                    if str(artifact) == subject['path'] and entry['sha256'] == subject['sha256'] and entry['size'] == subject['size']:
                        emitted = True
        if not emitted: raise ValueError('successful receipt does not bind this delivered quantity')
        if type(validator_receipts) is not list or len(validator_receipts) > 128:
            raise ValueError('finite validator receipt census required')
        identifiers = []; validations = []
        for pin in validator_receipts:
            validator = observed.document(pin)
            if (type(validator) is not dict or validator.get('schema_version') != 1
                    or validator.get('kind') not in {'finite-quantity', 'reference-comparison'}
                    or type(validator.get('id')) is not str or not validator['id']
                    or validator['id'] in identifiers or observed.canonical(validator.get('subject')) != subject):
                raise ValueError('distinct known validators binding exact delivered quantity required')
            identifiers.append(validator['id'])
            value = _number(document, validator['pointer'])
            if validator['kind'] == 'reference-comparison':
                reference = observed.canonical(validator['reference'])
                if reference['path'] == subject['path']:
                    raise ValueError('independent reference artifact required')
                expected = _number(observed.document(reference), validator['reference_pointer'])
                tolerance = validator.get('tolerance')
                if (type(tolerance) is not dict or set(tolerance) != {'absolute', 'relative'}
                        or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in tolerance.values())):
                    raise ValueError('explicit finite nonnegative reference tolerance required')
                if abs(value - expected) > tolerance['absolute'] + tolerance['relative'] * abs(expected):
                    raise ValueError('reference comparison fails declared tolerance')
                validations.append({'reference': reference, 'tolerance': tolerance, 'validator_id': validator['id']})
        result = ({'state': 'executed'} if not identifiers else
                  {'state': 'checked', 'validator_ids': identifiers} if not validations else
                  {'state': 'validated', 'validator_ids': identifiers,
                   'reference': validations[0]['reference'], 'tolerance': validations[0]['tolerance'],
                   'validations': validations})
        if own: observed.finish()
        return result
    finally:
        if own: observed.close()


def certified(status):
    """Use only a fresh derive() result, never a caller-supplied status string."""
    return status.get('state') == 'validated'
