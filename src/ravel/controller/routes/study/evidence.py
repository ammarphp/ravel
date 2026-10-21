"""Custody-bound scientific row checks at ordinary-study dispatch and adoption.

Expected descriptors are approved input artifacts, never numbers reconstructed
from a mode name. A missing validator leaves a durable unqualified label; a
failed existing check refuses adoption. Neither agreement nor review certifies
physical applicability beyond the supplied contracts.
"""
from __future__ import annotations

from copy import deepcopy

from .contracts import adopted_json, digest, execution_errors, pinned_json, quantity_errors, records

FIELDS = {
    'P05': ('basis', 'units', 'sign_convention', 'covariance', 'population'),
    'E07': ('pdf_member', 'generation_settings'),
    'E08': ('spectrum', 'invisible_states'),
    'E10': ('beam_energy', 'seed'),
    'E13': ('weight_names', 'reentrant'),
    'E17': ('bin_ids',),
    'E18': ('perturbative_order', 'process_basis'),
    'R08': ('units', 'statistic'),
}
ROWS = (*FIELDS, 'E09')


def requirements(step):
    """Closed controller-authored row bindings, carried by the approved step."""
    values = (step.get('parameters') or {}).get('evidence_requirements', [])
    if type(values) is not list:
        raise ValueError('scientific evidence requirements are a list')
    seen = set()
    for row in values:
        if (type(row) is not dict or set(row) - {'row', 'expected', 'observed', 'review', 'validator', 'entry_ids',
                                                'expected_fields', 'observed_fields'}
                or row.get('row') not in ROWS or type(row.get('expected')) is not str):
            raise ValueError('a scientific row binds its known id and adopted expected artifact')
        if row['row'] in seen:
            raise ValueError('a scientific row has one unambiguous binding per step')
        if row['row'] != 'E09' and type(row.get('observed')) is not str:
            raise ValueError('an executed evidence row names its observed artifact')
        if row['row'] != 'E09' and row['observed'] == row['expected']:
            raise ValueError('the observed artifact must differ from the approved expected artifact')
        seen.add(row['row'])
    return deepcopy(values)


def _observed(context, artifact):
    if not context.get('allow_staged_evidence'):
        return adopted_json(context, artifact)
    found = [row for row in records(context['store'], 'custody') if row.get('artifact') == artifact]
    if not found or found[-1].get('status') not in ('staged', 'accepted'):
        raise ValueError('the controller has not staged the observed artifact')
    row = found[-1]
    return pinned_json(context['run_dir'], {'path': row['destination'], 'sha256': row['sha256']}), row


def _projection(document, mapping):
    """Select source fields by approved JSON pointers without numerical changes."""
    if mapping is None:
        return document
    if type(mapping) is not dict or not mapping:
        raise ValueError('descriptor projections are explicit nonempty field-to-pointer mappings')
    projected = {}
    for field, pointer in mapping.items():
        if type(pointer) is not str or not pointer.startswith('/'):
            raise ValueError('a descriptor projection is a JSON pointer')
        value = document
        for part in pointer[1:].split('/'):
            part = part.replace('~1', '/').replace('~0', '~')
            value = value[int(part)] if type(value) is list else value[part]
        projected[field] = deepcopy(value)
    return projected


def _descriptor(document, row):
    if type(document) is not dict:
        raise ValueError('scientific descriptors are objects')
    for field in FIELDS[row]:
        if field not in document or document[field] is None:
            raise ValueError(row + ' requires an explicit ' + field + ' descriptor')
    digest(document)
    return document


def _recipe(context, step, document):
    if (type(document) is not dict or document.get('kind') != 'external-generation-recipe'
            or document.get('schema_version') != 1 or document.get('operation') != step.get('operation')
            or type(document.get('instructions')) is not str or not document['instructions'].strip()
            or type(document.get('sources')) is not list or not document['sources']):
        raise ValueError('retain an operation-bound external recipe and its actual source artifacts before generation')
    for artifact in document['sources']:
        if type(artifact) is not str:
            raise ValueError('recipe sources name adopted source artifacts')
        adopted_json(context, artifact)


def _review(context, query, expected_sha):
    from ravel.workflow.review_independence import decide
    if type(query) is not dict or query.get('subject_sha256') != expected_sha:
        raise ValueError('review must name the exact executed evidence digest')
    # P13 owns the closed query schema. Never add fields to an authenticated
    # binding: that would change the exact query and silently erase credit.
    decision = decide(deepcopy(query))
    if decision.get('independent') is not True:
        raise ValueError('the executed spectrum needs authenticated independent review')
    return decision


def _review_collection(context, step, binding, query, actual_pin):
    """Authenticate a collection review's exact observed-artifact membership."""
    from pathlib import Path
    from ravel.workflow.review_independence import decide

    def refuse(message):
        raise ValueError('review must name the exact executed evidence digest or credited collection membership: ' + message)

    attempt = context.get('attempt')
    store = context['store']
    if (type(query) is not dict or type(attempt) is not int or attempt < 1
            or query.get('run') != str(Path(context['run_dir']).resolve())
            or actual_pin.get('artifact') != binding['observed']
            or actual_pin.get('step_id') != step['id'] or actual_pin.get('attempt') != attempt
            or actual_pin.get('status') != 'accepted'):
        refuse('current producer, attempt and accepted observed custody are required')
    entries = list(store.scan('step-credit'))
    credits = [(entry.get('id'), entry.get('record', entry)) for entry in entries
               if entry.get('record', entry).get('step_id') == step['id']
               and entry.get('record', entry).get('attempt') == attempt]
    if not credits:
        refuse('the current producer attempt has no protected credit')
    credit_id, credit = credits[-1]
    if (not credit_id or sum(entry.get('id') == credit_id for entry in entries) != 1
            or credit.get('credited') is not True):
        refuse('the latest protected producer credit is not unambiguous and credited')
    seats = [seat for seat in credit.get('seats') or () if seat.get('query') == query]
    if len(seats) != 1:
        refuse('one child seat must carry the exact collection query')
    seat = seats[0]
    if (seat.get('credited') is not True or seat.get('status') != 'completed' or seat.get('verdict') != 'accept'
            or seat.get('attempt') != attempt or not seat.get('session_id') or not seat.get('receipt_sha256')
            or seat.get('role') != query.get('role') or seat.get('subject_sha256') != query.get('subject_sha256')):
        refuse('the exact child seat must have accepted this collection independently')
    sessions = [(entry.get('id'), entry.get('record', entry)) for entry in store.scan('worker-session')
                if entry.get('record', entry).get('run_id') == store.run_id
                and entry.get('record', entry).get('seat') == seat.get('seat')
                and entry.get('record', entry).get('attempt') == attempt
                and entry.get('record', entry).get('session_id') == seat['session_id']
                and entry.get('record', entry).get('receipt_sha256') == seat['receipt_sha256']]
    if len(sessions) != 1 or not sessions[0][0]:
        refuse('one observed worker session must match the credited child receipt')
    session_id, session = sessions[0]
    review_step = session.get('step_spec') or {}
    parameters = review_step.get('parameters') or {}
    if (review_step.get('kind') != 'review' or review_step.get('operation')
            or review_step.get('role') != seat.get('role') or session.get('step') != review_step.get('id')
            or (session.get('card') or {}).get('id') != seat.get('role')
            or parameters.get('seat_of') != step['id'] or parameters.get('purpose') != 'review'):
        refuse('the observed session is not this producer child review')
    for inputs in (review_step.get('inputs') or (), session.get('inputs') or ()):
        members = [row for row in inputs if row.get('artifact') == binding['observed']]
        if len(members) != 1 or members[0].get('sha256') != actual_pin['sha256']:
            refuse('the actual review inputs do not contain the exact observed artifact and digest')
    decision = decide(deepcopy(query))
    if decision.get('independent') is not True:
        refuse('the collection needs authenticated independent review')
    return {**decision, 'membership': {'credit': credit_id, 'session': session_id,
        'producer_step': step['id'], 'attempt': attempt, 'artifact': binding['observed'],
        'sha256': actual_pin['sha256'], 'review_step': review_step['id'], 'seat': seat['seat']}}


def check(store, step, context, *, phase):
    """Run applicable rows, record their evidence, return refusal findings.

    P05/E07/E08/E10/E13/E17/E18 descriptors are supplied as approved artifact
    references under ``parameters.evidence_requirements``. E09 runs before any
    effect. The same checks run after result adoption before any next step can
    consume the result. Ledger entry ids come from the shared materialisation.
    """
    if phase not in ('dispatch', 'adopt', 'review'):
        raise ValueError('scientific checks run at dispatch, adoption or review')
    errors = []
    context = {**context, 'store': store}
    for binding in requirements(step):
        row = binding['row']
        if (phase == 'dispatch') != (row == 'E09'):
            continue
        body = {'step_id': step['id'], 'row': row, 'phase': phase, 'binding_sha256': digest(binding),
                'status': 'pending', 'labels': [], 'findings': []}
        try:
            expected, expected_pin = adopted_json(context, binding['expected'])
            body['expected_sha256'] = expected_pin['sha256']
            if row == 'E09':
                _recipe(context, step, expected)
            else:
                actual, actual_pin = _observed(context, binding['observed'])
                body['observed_sha256'] = actual_pin['sha256']
                expected = _descriptor(_projection(expected, binding.get('expected_fields')), row)
                actual = _descriptor(_projection(actual, binding.get('observed_fields')), row)
                differences = quantity_errors(expected, actual) if row in ('P05', 'R08') else execution_errors(expected, actual)
                if differences:
                    raise ValueError('; '.join(differences))
                if row == 'E08' and phase == 'review':
                    query = binding.get('review') or (context.get('review_queries') or {}).get(row)
                    body['credit'] = (_review(context, query, actual_pin['sha256'])
                                      if type(query) is dict and query.get('subject_sha256') == actual_pin['sha256']
                                      else _review_collection(context, step, binding, query, actual_pin))
                elif row == 'E08':
                    body['labels'].append('operation_review_pending')
                if binding.get('validator') is None:
                    # The comparison is a concrete descriptor validator. Its
                    # physical applicability remains an explicit limitation.
                    body['labels'].append('descriptor_integrity_only')
                elif binding['validator'] != 'descriptor-continuity':
                    body['labels'].append('scientific_validator_unavailable')
                    body['findings'].append('no implemented validator for ' + str(binding['validator']))
            body['status'] = ('satisfied' if not body['findings'] and 'operation_review_pending' not in body['labels']
                              else 'pending')
        except (ValueError, KeyError, OSError, TypeError) as exc:
            body['status'] = 'violated'
            body['findings'] = [str(exc)]
        record_id = store.append('study-evidence', body)
        # Pending is an observation, not a ledger transition. Its existing
        # obligation remains open until actual review or a concrete refusal.
        for entry_id in (binding.get('entry_ids', []) if body['status'] != 'pending' else []):
            from ravel.controller import ledger
            ledger.record(store, entry_id, body['status'], {'validator': 'study-descriptor-continuity',
                'record_id': record_id, 'row': row, 'findings': body['findings'],
                'expected_sha256': body.get('expected_sha256'), 'observed_sha256': body.get('observed_sha256'),
                **({'credit': body['credit']} if 'credit' in body else {}),
                **({'reason': '; '.join(body['findings']) or ', '.join(body['labels']),
                    'label': 'scientific_evidence_invalid'} if body['status'] == 'violated' else {})})
        if body['status'] != 'satisfied' and not (phase == 'adopt' and body['status'] == 'pending'
                and 'operation_review_pending' in body['labels']
                and set(body['labels']) <= {'operation_review_pending', 'descriptor_integrity_only'}):
            errors.append({'code': 'scientific_evidence_unresolved', 'row': row,
                           'message': '; '.join(body['findings']), 'record_id': record_id})
    return errors


def instruction_errors(store, step, context, final_record, outputs):
    """Validate actual acknowledgements, not merely the presence of doc paths."""
    from ravel.controller import instructions
    manifest = instructions.manifest(step, context.get('card'))
    packet = instructions.packet(manifest, context.get('card'), step, context.get('inputs', []))
    problems = list(instructions.check_ack(manifest, final_record, outputs))
    store.append('study-instructions', {'step_id': step['id'], 'manifest': manifest,
        'packet_sha256': packet['sha256'], 'errors': problems,
        'final_sha256': digest(final_record), 'output_paths': list(outputs)})
    return [{'code': 'instruction_ack_invalid', 'message': str(error)} for error in problems]


__all__ = ['FIELDS', 'ROWS', 'check', 'instruction_errors', 'requirements']
