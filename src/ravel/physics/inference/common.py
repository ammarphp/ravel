"""Adapter plumbing shared by the inference science modes."""
from __future__ import annotations

from pathlib import Path

from . import documents, record

SCOPE = 'declared-inference'
LIMITATION = ('The record evaluates the declared inputs and statistic. It does not establish detector '
              'fidelity, the correctness of supplied yields or covariances, asymptotic coverage unless toys '
              'were run, or a physics certification.')


def validate(task):
    documents.task_document(task)


def context(task, base, kind, *, goodness_of_fit=False):
    """Load the input document; ``review`` and ``goodness_of_fit`` blocks are taken off here.

    ``review`` (threshold overrides with a recorded basis, declared references) is
    available to every mode. ``goodness_of_fit`` (toys, seed, max_seconds) only to
    modes that compute one.
    """
    from ravel.validation import regression_triggers
    from . import gof
    ctx = documents.Context(documents.task_document(task), base)
    doc = ctx.document
    if type(doc) is not dict or doc.get('schema_version') != 1 or doc.get('kind') != kind:
        raise ValueError(f'the input document must have schema_version 1 and kind {kind!r}')
    ctx.review = regression_triggers.validate_review(doc.get('review')) or None
    if 'goodness_of_fit' in doc and not goodness_of_fit:
        raise ValueError(f'{kind} does not compute a goodness of fit; remove goodness_of_fit')
    ctx.goodness_of_fit = gof.options(doc['goodness_of_fit']) if 'goodness_of_fit' in doc else None
    doc = {k: v for k, v in doc.items() if k not in ('review', 'goodness_of_fit')}
    return ctx, doc


def inputs(ctx):
    return [Path(p['path']) for p in ctx.inputs()]


def parameter(spec, label='parameter'):
    if type(spec) is not dict or not {'name', 'unit', 'label'} <= set(spec) or set(spec) - {'name', 'unit', 'label'}:
        raise ValueError(label + ' needs name, unit and a natural-language label')
    for key in ('name', 'label'):
        if type(spec[key]) is not str or not spec[key].strip():
            raise ValueError(label + f' {key} must be nonblank text')
    if type(spec['unit']) is not str:
        raise ValueError(label + ' unit must be text ("" for dimensionless)')
    return dict(spec)


def deliver(output, doc, *, scope, review=None):
    """Attach the computed review checks, write ``inference.json`` and return the adapter result."""
    from ravel.validation import regression_triggers
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    doc = dict(doc)
    if review:
        doc['review'] = review
    doc['computed_checks'] = record.clean(regression_triggers.evaluate(doc, review=review or {}))
    doc['computed_check_summary'] = regression_triggers.summary(doc['computed_checks'])
    from ravel.physics.yield_hub import delivery_checks
    doc['check_results'] = delivery_checks(output, path='inference.json')
    doc['coverage'] = {'status': 'not_evaluated', 'general_likelihood_coverage_validated': False}
    record.validate(doc)
    pin = record.write(output / 'inference.json', doc)
    primary = [r for r in doc['results'] if r['role'] == 'primary']
    return {'status': doc['status'], 'physics_validated': False, 'status_scope': SCOPE, 'mode': doc['mode'],
            'engine': doc['engine'], 'scope': scope, 'inference': 'inference.json',
            'inference_sha256': pin['sha256'], 'statistic_origin': doc['statistic']['origin'],
            'summary': record.summary_lines(doc),
            'primary_results': [r.get('summary') for r in primary if r.get('summary')],
            'computed_checks': doc['computed_check_summary'],
            'check_results': doc['check_results'], 'coverage': doc['coverage'],
            'limitations': [*doc['limitations'], LIMITATION]}
