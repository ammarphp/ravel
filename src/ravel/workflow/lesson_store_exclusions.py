"""Scoped negative knowledge: exclusion records with refutation signatures (P09, S3).

A negative result is one of four kinds. ``prediction_mismatch`` is a categorical disagreement with
a supplied prediction (``experiment_allocator.update`` emits these) and is not a rejection.
``rejected_in_scope`` additionally carries a comparator and a sensitivity or power receipt inside
a complete signature {manipulation, held inputs, comparator, sensitivity, statistic, domain,
counterexample pin}; only this kind can become an exclusion. ``execution_failure`` and
``untested`` never exclude anything.

The reopening trigger is a typed predicate in the lesson-trigger grammar, never free text.
Reopening requires a receipt whose facts satisfy it and creates a request, not support.
A re-proposal is refused unless its ``what_is_new`` differs from the signature.
"""
from __future__ import annotations

from .knowledge_atlas import digest, encode
from .knowledge_lessons import FACTS, PREDICATES, trigger_fires
from .lesson_store import _receipt_ok, origin_errors

KINDS = ('prediction_mismatch', 'rejected_in_scope', 'execution_failure', 'untested')
SIGNATURE = ('manipulation', 'held_inputs', 'comparator', 'sensitivity', 'statistic', 'domain', 'counterexample')
REOPEN_FACTS = SIGNATURE + FACTS + ('receipt_kind', 'statistics', 'grid')


def predicate_errors(predicate) -> list[str]:
    """A reopening trigger is ``{"all": [{"fact": <declared>, "equals"|"in"|"contains": ...}]}``."""
    if not isinstance(predicate, dict) or set(predicate) != {'all'} or not isinstance(predicate['all'], list) \
            or not predicate['all']:
        return ['reopening_trigger must be a typed predicate {"all": [...]}, not free text']
    errors = []
    for row in predicate['all']:
        if not isinstance(row, dict) or row.get('fact') not in REOPEN_FACTS \
                or len(set(row) & set(PREDICATES)) != 1 or set(row) - {'fact', *PREDICATES}:
            errors.append('reopening predicate needs a declared fact and one of ' + '/'.join(PREDICATES))
        elif 'in' in row and (not isinstance(row['in'], list) or not row['in']):
            errors.append('reopening "in" needs a nonempty list')
    return errors


def _complete(signature):
    """True when every signature field is present and the comparator, sensitivity and
    counterexample each carry a receipt."""
    return isinstance(signature, dict) and all(signature.get(k) not in (None, '', [], {}) for k in SIGNATURE) \
        and all(isinstance(signature[k], dict) and _receipt_ok(signature[k].get('receipt'))
                for k in ('comparator', 'sensitivity', 'counterexample'))


def negative_record(*, hypothesis_id, origin, reopening_trigger, mismatch=None, execution=None, signature=None) -> dict:
    """Classify one negative observation. ``mismatch`` is an allocator refutation row; ``execution``
    is ``{"status": "passed"|"failed", "receipt": {...}}`` for the run that produced it."""
    errors = origin_errors(origin) + predicate_errors(reopening_trigger)
    if not isinstance(hypothesis_id, str) or not hypothesis_id.strip():
        errors.append('hypothesis_id is required')
    if errors:
        raise ValueError('negative record refused: ' + '; '.join(errors))
    if isinstance(execution, dict) and execution.get('status') != 'passed':
        kind = 'execution_failure'
    elif mismatch is None:
        kind = 'untested'
    elif _complete(signature):
        kind = 'rejected_in_scope'
    else:
        kind = 'prediction_mismatch'
    value = {'schema_version': 1, 'kind': kind, 'hypothesis_id': hypothesis_id, 'signature': signature,
             'mismatch': mismatch, 'execution': execution, 'reopening_trigger': reopening_trigger,
             'origin': origin, 'status': 'recorded'}
    value['record_sha256'] = digest(encode(value))
    return value


def exclusion_errors(record) -> list[str]:
    """``check:excluded_has_signature``: what an exclude/park record must carry."""
    errors = origin_errors(record.get('origin')) + predicate_errors(record.get('reopening_trigger'))
    kind = record.get('kind')
    if kind == 'execution_failure' or (isinstance(record.get('execution'), dict)
                                       and record['execution'].get('status') != 'passed'):
        errors.append('a failed execution produces no exclusion')
    elif kind != 'rejected_in_scope':
        errors.append('a prediction mismatch is not a rejection without a comparator and sensitivity receipt'
                      if kind == 'prediction_mismatch' else f'{kind} is not an exclusion')
    if not _complete(record.get('signature')):
        errors.append('exclusion needs a complete signature with comparator, sensitivity and counterexample receipts')
    if record.get('mismatch') is None:
        errors.append('exclusion needs the observed mismatch')
    return list(dict.fromkeys(errors))


def exclude(record) -> dict:
    """Move a ``rejected_in_scope`` record to ``excluded``; every other kind is refused."""
    errors = exclusion_errors(record)
    if errors:
        raise ValueError('exclusion refused: ' + '; '.join(errors))
    value = {**record, 'status': 'excluded'}
    value.pop('record_sha256', None)
    value['record_sha256'] = digest(encode(value))
    return value


def reproposal_errors(exclusion, proposal) -> list[str]:
    """A re-proposal of an excluded hypothesis must say what differs from the refutation signature."""
    new = proposal.get('what_is_new') if isinstance(proposal, dict) else None
    if not isinstance(new, dict) or not new or set(new) - set(SIGNATURE):
        return ['re-proposal needs what_is_new over signature fields ' + ', '.join(SIGNATURE)]
    if all(exclusion['signature'].get(k) == v for k, v in new.items()):
        return ['re-proposal repeats the excluded signature']
    return []


def reopen(exclusion, *, facts, receipt) -> dict:
    """A receipt whose facts satisfy the typed trigger yields a reopening request (not support)."""
    if exclusion.get('status') != 'excluded' or not _receipt_ok(receipt):
        raise ValueError('reopening needs an excluded record and a receipt')
    if not isinstance(facts, dict) or not trigger_fires(exclusion['reopening_trigger'], facts):
        raise ValueError('the receipt does not satisfy the reopening trigger')
    return {'schema_version': 1, 'kind': 'reopening-request', 'exclusion_sha256': exclusion['record_sha256'],
            'hypothesis_id': exclusion['hypothesis_id'], 'receipt': receipt, 'facts': facts, 'support': None}
