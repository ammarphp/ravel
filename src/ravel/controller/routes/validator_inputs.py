"""Typed validator sources, compiled into run parameters without manufacturing evidence.

References live in ``parameters.check_inputs``. Output fields have an independently
declared type in the producer's ``parameters.validator_exports``. Contract fields
use the task-contract schema; controller records use their owner's closed interface.
Compilation resolves available contract values and retains future references. The
validator boundary resolves those references against custody, never a guessed path.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import re

from ravel.workflow import review_projection_checks as documents, run_validator_checks as runs

INPUT_TYPES = {
    **{check: {} for check in runs.STATE_CHECKS},
    runs.TRAP_CHECK: {'sweep': 'path'},
    runs.CENSUS_CHECK: {'census': 'path'},
    'check:validation.validate_task_contract.validate': {},
    'check:physics.normalization_ledger.check': {'ledger': 'path'},
    'check:validation.validate_cutflow': {
        'signal': 'path', 'routine': 'string', 'sigma_pb': 'number', 'lumi_fb': 'number',
        'tables_dir': 'path', 'grid': 'string', 'm_parent': 'number', 'm_lsp': 'number', 'srs': 'string'},
    'check:validation.input_closure.check': {'fit': 'pin', 'reference': 'pin'},
    'check:validation.verify_pack.check_deviations_ledger': {},
    runs.FIGURES_CHECK: {'figures': 'path'},
    'check:validation.certificates.validate_certificate': {'path': 'path', 'kind': 'string'},
    'ravel.validation.calibration_checks': {'spec': 'path'},
    **{check: {'spec': 'path'} for check in runs.CALIBRATION_SPEC_CHECKS},
    **{check: {'receipt': 'pin'} for check in runs.CALIBRATION_RECEIPT_CHECKS},
    **{check: {'record_id': 'string', 'spec_sha256': 'sha256', 'subject_sha256': 'sha256'}
       for check in documents.ML_RESULT_CHECKS},
}
TYPES = {'path', 'pin', 'string', 'number', 'sha256'}


class BindingError(ValueError):
    """A declared source cannot supply the requested typed input."""

    def __init__(self, reason, detail):
        self.reason = reason
        super().__init__(detail)


def requirements(check):
    return INPUT_TYPES.get(check, {'document': 'path'})


def declare_role_inputs(step):
    """A late-bound execution role owes its actual checks, not its template role's.

    The declared JSON report must export the missing inputs. This creates no value
    or verdict: ordinary output/custody and validator checks still have to succeed.
    """
    from ravel.controller.step.validate import validator_ids
    from ravel.workflow import role_registry
    roles = {role for role in (step.get('role'), *step.get('review', ())) if role}
    checks = {check for role in roles for check in validator_ids(role_registry.load(role))[0]}
    report = next((o for o in step.get('outputs', ())
                   if o['path'].endswith('.json') and o.get('required', True)), None)
    parameters = step.setdefault('parameters', {})
    for check in sorted(checks):
        for key, kind in requirements(check).items():
            fields = parameters.setdefault('check_inputs', {}).setdefault(check, {})
            if key in fields:
                continue
            if report is None:
                raise BindingError('validator_source_unresolved', 'the execution role needs a declared JSON input report')
            field = '/validator_inputs/' + check.replace('~', '~0').replace('/', '~1') + '/' + key
            fields[key] = {'source': 'output', 'step': step['id'], 'path': report['path'], 'field': field, 'type': kind}
            parameters.setdefault('validator_exports', {}).setdefault(report['path'], {})[field] = kind
    return step


def pointer(document, field):
    if field == '':
        return document
    if type(field) is not str or not field.startswith('/'):
        raise BindingError('validator_source_invalid', 'a field is a JSON pointer')
    for part in field[1:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        if type(document) is dict and part in document:
            document = document[part]
        elif type(document) is list and part.isdecimal() and int(part) < len(document):
            document = document[int(part)]
        else:
            raise BindingError('validator_source_unresolved', f'field {field} is unavailable')
    return document


def typed(value, kind):
    if kind == 'number':
        try:
            return type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            return False
    if kind == 'pin':
        return (type(value) is dict and set(value) == {'path', 'sha256'}
                and typed(value['path'], 'path') and typed(value['sha256'], 'sha256'))
    if type(value) is not str or not value.strip():
        return False
    if kind == 'sha256':
        return re.fullmatch('[0-9a-f]{64}', value) is not None
    if kind == 'path':
        return not Path(value).is_absolute() and '..' not in Path(value).parts and not value.startswith('~')
    return kind == 'string'


def _contract_schema(field):
    from ravel.validation.validate_task_contract import SCHEMA
    schema = SCHEMA
    for key in field.lstrip('/').split('/'):
        key = key.replace('~1', '/').replace('~0', '~')
        schema = schema.get('properties', {}).get(key, {})
    return schema



OPTIONAL_INPUT_TYPES = {
    'check:physics.normalization_ledger.check': {'delivered': 'path'},
    'check:validation.validate_cutflow': {'driving_sr_override': 'string'},
    runs.FIGURE_CONTRACT_CHECK: {'target': 'path'},
}


def parameter_type(check, key):
    """Required and explicitly registered optional inputs share the same custody types."""
    return requirements(check).get(key, OPTIONAL_INPUT_TYPES.get(check, {}).get(key))


def source_errors(ref, expected, *, step, steps, check):
    """Check source identity, producer declaration, dependency and type independently."""
    if type(ref) is not dict or ref.get('type') != expected or expected not in TYPES:
        return ['validator_source_type: expected ' + str(expected)]
    source = ref.get('source')
    if source == 'contract':
        if (set(ref) != {'source', 'field', 'type'} or type(ref.get('field')) is not str
                or not ref['field'].startswith('/')):
            return ['validator_source_invalid: contract field required']
        schema = _contract_schema(ref['field'])
        actual = schema.get('type')
        compatible = {'path': {'string'}, 'sha256': {'string'}, 'pin': {'object'},
                      'number': {'number', 'integer'}}.get(expected, {expected})
        if actual not in compatible:
            return ['validator_source_type: contract field does not declare ' + expected]
        if expected == 'pin' and (not {'path', 'sha256'} <= set(schema.get('required', ()))
                                  or any(schema.get('properties', {}).get(key, {}).get('type') != 'string'
                                         for key in ('path', 'sha256'))):
            return ['validator_source_type: contract field does not declare a custody pin']
    elif source == 'output':
        if (set(ref) - {'source', 'step', 'path', 'field', 'type'} or not {'step', 'path'} <= set(ref)
                or type(ref['step']) is not str or not typed(ref['path'], 'path')
                or ('field' in ref and (type(ref['field']) is not str
                                       or not ref['field'].startswith('/')))):
            return ['validator_source_invalid: output step and path required']
        producer = next((s for s in steps if s['id'] == ref['step']), None)
        if producer is None:
            return ['validator_source_missing: unknown producer']
        if ref['step'] != step['id']:
            artifact = ref['step'] + ':' + ref['path']
            if ref['step'] not in step.get('depends_on', ()) or not any(
                    i.get('artifact') == artifact for i in step.get('inputs', ())):
                return ['validator_source_missing: output needs its declared input and dependency']
        if not any(o['path'] == ref['path'] and o.get('required', True) for o in producer.get('outputs', ())):
            return ['validator_source_missing: required declared output absent']
        field = ref.get('field')
        if field is None:
            if expected not in ('path', 'pin'):
                return ['validator_source_type: an output artifact supplies a path or pin']
        elif (producer.get('parameters', {}).get('validator_exports', {}).get(ref['path'], {}).get(field)
              != expected):
            return ['validator_source_type: producer field export differs']
    elif source == 'record':
        if (set(ref) != {'source', 'kind', 'field', 'type'}
                or ref.get('kind') != documents.ML_OBSERVATION_KIND
                or check not in documents.ML_RESULT_CHECKS
                or ref.get('field') not in requirements(check)
                or requirements(check)[ref['field']] != expected):
            return ['validator_source_type: no matching controller record field']
    else:
        return ['validator_source_missing: output, contract or controller record required']
    return []


def declaration_errors(step, steps, checks):
    values = (step.get('parameters') or {}).get('check_inputs') or {}
    values = values if type(values) is dict else {}
    problems = []
    for check in checks:
        fields = values.get(check)
        for key, kind in requirements(check).items():
            ref = fields.get(key) if type(fields) is dict else None
            for error in source_errors(ref, kind, step=step, steps=steps, check=check):
                problems.append((check, key, error))
    return problems


def compile_inputs(steps, contract):
    """Bind present contract values; retain future output/record references in the plan."""
    for step in steps:
        values = (step.get('parameters') or {}).get('check_inputs') or {}
        if type(values) is not dict:
            continue
        for check, fields in values.items():
            if type(fields) is not dict:
                continue
            for key, ref in list(fields.items()):
                if type(ref) is not dict or 'source' not in ref:
                    continue  # Ordinary caller-authored plans keep their existing value interface.
                errors = source_errors(ref, parameter_type(check, key), step=step, steps=steps, check=check)
                if errors:
                    raise BindingError('validator_source_invalid', f'{step["id"]} {check}.{key}: {errors}')
                if ref['source'] == 'contract':
                    try:
                        value = pointer(contract, ref['field'])
                    except BindingError:
                        continue
                    if not typed(value, ref['type']):
                        raise BindingError('validator_source_type', f'{check}.{key} has the wrong contract type')
                    fields[key] = deepcopy(value)
    return steps


def _bound_file(run_dir, pin):
    from ravel.workflow.world_digest import read_bound
    raw, sha = read_bound(run_dir, pin['path'])
    if sha != pin['sha256']:
        raise BindingError('validator_source_changed', 'source bytes differ from their custody')
    return raw


def _output(ref, step, store, run_dir):
    from ravel.controller.step import custody
    artifact = ref['step'] + ':' + ref['path']
    own = ref['step'] == step['id']
    inputs = {row['artifact']: row for row in step.get('inputs', ())}
    seat_of = (step.get('parameters') or {}).get('seat_of')
    index = custody.custody_index(store)
    inherited = False
    if seat_of and artifact not in inputs:
        # The seat reviews the parent's exact outputs and their authenticated input
        # closure. A predecessor reference remains tied to that reviewed closure;
        # it cannot turn into an arbitrary run-tree read or a seat-owned output.
        for name, reviewed in inputs.items():
            subject = index.get(name)
            if (subject is None or subject.get('step_id') != seat_of
                    or reviewed.get('sha256') != subject.get('sha256')
                    or custody._verify(index, name, run_dir, set(), 0, store)):
                continue
            pending, seen = list(subject.get('inputs') or ()), set()
            while pending and len(seen) <= custody.MAX_DEPTH:
                parent = pending.pop()
                if parent in seen:
                    continue
                seen.add(parent)
                if parent == artifact:
                    inherited = True
                    break
                pending.extend((index.get(parent) or {}).get('inputs') or ())
    if not own and artifact not in inputs and not inherited:
        raise BindingError('validator_source_unresolved', 'source is outside the step inputs')
    if not own and ref['step'] not in step.get('depends_on', ()) and not inherited:
        raise BindingError('validator_source_unresolved', 'source is outside the step dependencies')
    row = index.get(artifact)
    if (row is None or row.get('step_id') != ref['step'] or row.get('path') != ref['path']
            or row.get('destination') != custody.attempt_destination(ref['step'], ref['path'], row.get('attempt', 1))
            or row.get('status') not in ({'staged', 'accepted'} if own else {'accepted'})):
        raise BindingError('validator_source_unresolved', 'source has no current adopted custody')
    if seat_of == ref['step'] and (inputs[artifact].get('sha256') != row['sha256']):
        raise BindingError('validator_source_changed', 'source differs from the reviewed subject')
    if not own and custody._verify(index, artifact, run_dir, set(), 0, store):
        raise BindingError('validator_source_changed', 'source input closure differs from custody')
    pin = {'path': row['destination'], 'sha256': row['sha256']}
    raw = _bound_file(run_dir, pin)
    if 'field' in ref:
        return pointer(json.loads(raw), ref['field'])
    return pin if ref['type'] == 'pin' else pin['path']


def _record(ref, check, fields, store):
    """Select the exact observed computation; never choose the latest passing row."""
    if (ref.get('kind') != documents.ML_OBSERVATION_KIND or check not in documents.ML_RESULT_CHECKS
            or ref.get('field') not in requirements(check)):
        raise BindingError('validator_source_invalid', 'unregistered controller observation source')
    selector = fields.get('record_id')
    if type(selector) is dict and selector.get('source') == 'record':
        raise BindingError('validator_source_unresolved', 'the run must bind an exact computation record id')
    if type(selector) is not str:
        raise BindingError('validator_source_unresolved', 'computation record id absent')
    row = store.read(ref['kind'], selector)
    row = row.get('record', row)
    if row.get('check_id') != check:
        raise BindingError('validator_source_changed', 'computation observation is for another validator')
    return selector if ref['field'] == 'record_id' else row.get(ref['field'])


def resolve_inputs(values, step, *, run_dir, store=None):
    """Resolved values and per-check typed refusals. No unresolved reference reaches a validator."""
    result, errors = deepcopy(values), {}
    for check, fields in result.items():
        if type(fields) is not dict:
            continue
        original = deepcopy(fields)
        # Record fields may depend on an exact id exported by the adopted output.
        for key, ref in sorted(original.items(), key=lambda item: (
                type(item[1]) is dict and item[1].get('source') == 'record')):
            if type(ref) is not dict or 'source' not in ref:
                continue
            try:
                expected = parameter_type(check, key)
                if ref.get('type') != expected:
                    raise BindingError('validator_source_type', f'{check}.{key} has an incompatible source type')
                if ref['source'] == 'contract':
                    # A missing compile-time contract field cannot gain authority from a later file edit.
                    raise BindingError('validator_source_unresolved', 'contract field was not bound in the compiled plan')
                if store is None:
                    raise BindingError('validator_source_unresolved', 'the controller store is unavailable')
                if ref['source'] == 'output':
                    value = _output(ref, step, store, run_dir)
                elif ref['source'] == 'record':
                    value = _record(ref, check, fields, store)
                else:
                    raise BindingError('validator_source_invalid', 'unknown validator source')
                if not typed(value, expected):
                    raise BindingError('validator_source_type', f'{check}.{key} resolved to the wrong type')
                fields[key] = deepcopy(value)
            except (BindingError, OSError, ValueError, KeyError, TypeError) as exc:
                errors[check] = {'reason': getattr(exc, 'reason', 'validator_source_unresolved'), 'detail': str(exc)}
    return result, errors
