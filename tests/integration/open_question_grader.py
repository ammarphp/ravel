"""Grader for the open-question fixtures: a strict score beside the raw score.

``raw`` credits each reference field the answer matches: the verdict, and the quantity within
the declared tolerance. It asks nothing about where the answer came from.

``strict`` is 1 only when all of these hold:

- the grading declaration is the one pinned before the run (verdict vocabulary, reference and
  tolerance), so a tolerance cannot move after the answer is seen;
- the verdict is in the declared vocabulary and equals the reference verdict;
- the quantity is the declared one and lies within the declared tolerance;
- the quantity's evidence pin is an artifact the run itself committed, its bytes are unchanged,
  and the value at its pointer equals the reported value.

ABC probes (an empty output, a copied reference and a format-only output) must score 0 strictly.
A copied reference can score on ``raw``; that gap is what the strict metric exists to close.
No LLM judge is used here, so no judge-agreement record applies to these synthetic fixtures.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

FIELDS = ('verdict', 'quantity')


def declaration(fixture):
    """The grading declaration fixed before a run, with its digest."""
    value = {'question': fixture['id'], 'quantity': fixture['quantity']['id'], **fixture['grading']}
    raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    return {'declaration': value, 'sha256': hashlib.sha256(raw).hexdigest()}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _pointer(document, pointer):
    for part in pointer.split('/')[1:]:
        document = document[int(part)] if isinstance(document, list) else document[part]
    return document


def _within(value, reference, tolerance):
    return _number(value) and abs(value - reference) <= tolerance['absolute']


def raw_score(answer, declared):
    """Fraction of reference fields matched; no provenance, no vocabulary check."""
    d = declared['declaration']
    if not isinstance(answer, dict):
        return 0.0
    quantity = answer.get('quantity') if isinstance(answer.get('quantity'), dict) else {}
    hits = [answer.get('verdict') == d['reference']['verdict'],
            _within(quantity.get('value'), d['reference']['value'], d['tolerance'])]
    return sum(hits) / len(hits)


def strict_score(answer, declared, *, pinned_sha256, committed, root):
    """1.0 or 0.0, with the reasons for a zero."""
    d = declared['declaration']
    reasons = []
    if declared['sha256'] != pinned_sha256:
        reasons.append('grading_declaration_changed_after_pin')
    if not isinstance(answer, dict) or not answer:
        return 0.0, reasons + ['empty_output']
    if answer.get('verdict') not in d['verdicts']:
        reasons.append('verdict_outside_declared_vocabulary')
    elif answer['verdict'] != d['reference']['verdict']:
        reasons.append('verdict_differs')
    quantity = answer.get('quantity')
    if not isinstance(quantity, dict) or quantity.get('id') != d['quantity']:
        reasons.append('quantity_not_declared')
        quantity = {}
    if not _within(quantity.get('value'), d['reference']['value'], d['tolerance']):
        reasons.append('quantity_outside_declared_tolerance')
    reasons.extend(_provenance(quantity, committed, root))
    return (0.0, reasons) if reasons else (1.0, [])


def _provenance(quantity, committed, root):
    evidence = quantity.get('evidence')
    if not isinstance(evidence, dict) or not {'path', 'sha256', 'pointer'} <= set(evidence):
        return ['quantity_without_run_evidence']
    if (evidence['path'], evidence['sha256']) not in committed:
        return ['evidence_not_committed_by_run']
    path = Path(evidence['path'])
    if not path.resolve().is_relative_to(Path(root).resolve()) or not path.is_file():
        return ['evidence_outside_run']
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != evidence['sha256']:
        return ['evidence_bytes_changed']
    try:
        observed = _pointer(json.loads(raw), evidence['pointer'])
    except (KeyError, IndexError, ValueError, TypeError):
        return ['evidence_pointer_unresolved']
    return [] if observed == quantity.get('value') else ['reported_value_differs_from_evidence']


def score(answer, fixture, *, pinned_sha256, committed, root):
    declared = declaration(fixture)
    strict, reasons = strict_score(answer, declared, pinned_sha256=pinned_sha256, committed=committed, root=root)
    return {'question': fixture['id'], 'declaration_sha256': declared['sha256'], 'raw': raw_score(answer, declared),
            'strict': strict, 'strict_reasons': reasons}


def probes(fixture):
    """The ABC trivial outputs: empty, copied reference and format-only."""
    reference = fixture['grading']['reference']
    return {
        'empty': {},
        'copied_reference': {'verdict': reference['verdict'],
                             'quantity': {'id': fixture['quantity']['id'], 'value': reference['value'],
                                          'unit': fixture['quantity']['unit']}},
        'format_only': {'verdict': '', 'quantity': {'id': fixture['quantity']['id'], 'value': None,
                                                    'unit': fixture['quantity']['unit'],
                                                    'evidence': {'path': '', 'sha256': '', 'pointer': ''}}},
    }
