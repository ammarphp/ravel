"""Lesson records: a computable trigger, a confirming check and promotion evidence.

A lesson is accepted only when its trigger is a conjunction of exact predicates over run
facts and fires on the facts of its own ticket, it carries receipts and a confirming check,
and a promoted lesson carries its A/B impact record. Retrieval and promotion belong to the
lesson store; this module only judges a record.
"""
from __future__ import annotations

import re

from ravel.validation.check_protected_paths import suppression_rule

STATUSES = ('candidate', 'trial', 'promoted', 'revoked', 'dormant')
FACTS = ('operation', 'tool', 'tool_version', 'failure_class', 'stderr_family',
         'failed_check_id', 'basis', 'claim_kind', 'observable_tags', 'backend')
PREDICATES = ('equals', 'in', 'contains')
MAX_BODY_LINES = 40
IMPACT_FIELDS = ('arm_with', 'arm_without', 'tasks', 'metric')


def _holds(predicate, facts):
    value = facts.get(predicate['fact'])
    if value is None:
        return False
    if 'equals' in predicate:
        return value == predicate['equals']
    if 'in' in predicate:
        return value in predicate['in'] if not isinstance(value, list) else bool(set(value) & set(predicate['in']))
    return isinstance(value, list) and predicate['contains'] in value


def trigger_fires(trigger, facts) -> bool:
    """True when every predicate of the conjunction holds for the facts."""
    return bool(trigger['all']) and all(_holds(p, facts) for p in trigger['all'])


def _trigger_errors(trigger):
    if not isinstance(trigger, dict) or set(trigger) != {'all'} or not isinstance(trigger['all'], list) or not trigger['all']:
        return ['trigger must be a nonempty conjunction {"all": [...]}']
    errors = []
    for predicate in trigger['all']:
        if (not isinstance(predicate, dict) or predicate.get('fact') not in FACTS
                or len(set(predicate) & set(PREDICATES)) != 1 or set(predicate) - {'fact', *PREDICATES}):
            errors.append('trigger predicate needs a declared fact and one of ' + '/'.join(PREDICATES))
        elif 'in' in predicate and (not isinstance(predicate['in'], list) or not predicate['in']):
            errors.append('trigger "in" needs a nonempty list')
    return errors


def lesson_errors(lesson, *, check_ids=None) -> list[str]:
    """Reasons a lesson record is refused; an empty list means accepted."""
    if not isinstance(lesson, dict):
        return ['lesson must be an object']
    name = str(lesson.get('id', '?'))
    errors = []
    status = lesson.get('status')
    if status not in STATUSES:
        errors.append('status must be one of ' + '|'.join(STATUSES))
    trigger_problems = _trigger_errors(lesson.get('trigger'))
    errors += trigger_problems
    evidence = lesson.get('evidence')
    ticket = evidence.get('ticket') if isinstance(evidence, dict) else None
    if not isinstance(ticket, dict) or not ticket.get('id') or not isinstance(ticket.get('facts'), dict):
        errors.append('evidence needs a ticket with an id and facts')
    elif not trigger_problems and not trigger_fires(lesson['trigger'], ticket['facts']):
        errors.append('trigger does not fire on its own ticket facts')
    receipts = evidence.get('receipts') if isinstance(evidence, dict) else None
    if not isinstance(receipts, list) or not receipts or not all(
            isinstance(r, dict) and r.get('path') and re.fullmatch(r'[0-9a-f]{64}', str(r.get('sha256', ''))) for r in receipts):
        errors.append('evidence needs receipts with a path and sha256')
    check = lesson.get('confirming_check')
    if not isinstance(check, str) or not check.strip():
        errors.append('confirming_check is required')
    elif check_ids is not None and check not in check_ids:
        errors.append('confirming_check does not resolve to a known check: ' + check)
    body = lesson.get('body')
    if not isinstance(body, str) or not body.strip():
        errors.append('body is required')
    elif len(body.splitlines()) > MAX_BODY_LINES:
        errors.append(f'body exceeds {MAX_BODY_LINES} lines')
    errors += ['do-not-learn: weakens a check, trap, gate or threshold: ' + s
               for s in suppression_rule(' \n'.join(str(lesson.get(k) or '') for k in ('title', 'body')),
                                       known_ids=sorted(check_ids or ()))]
    scope = lesson.get('scope')
    if not isinstance(scope, dict) or not scope.get('tool') or not scope.get('tool_version') or not scope.get('ravel_version'):
        errors.append('scope needs tool, tool_version and ravel_version')
    if status == 'promoted':
        impact = lesson.get('impact')
        if (not isinstance(impact, dict) or any(not impact.get(f) for f in IMPACT_FIELDS)
                or not isinstance(impact['tasks'], list)):
            errors.append('promoted lesson requires impact with ' + ', '.join(IMPACT_FIELDS))
    return [name + ': ' + e for e in errors]
