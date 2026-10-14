"""Science mode ``coupling-morphing``: polynomial coupling dependence from N runs.

Input document (``kind: coupling-morphing``)::

    {"schema_version": 1, "kind": "coupling-morphing",
     "parameters": [{"name": "g1", "unit": "", "label": "Coupling g1"}, ...],
     "quantity": {"name": "xsec", "unit": "pb", "label": "Cross section"},
     "basis": [{"g1": 2}, {"g1": 1, "g2": 1}, {"g2": 2}],
     "amplitudes": [{"g1": 1}, {"g2": 1}],          (optional; or "degree")
     "method": "exact" | "weighted-least-squares", "max_condition": 1e6,
     "runs": [{"id": "r1", "point": {"g1": 0.1, "g2": 0.0}, "value": 1.2, "uncertainty": 0.01}, ...],
     "holdout": [...], "closure_tolerance_sigma": 3,
     "width": {"treatment": "fixed", "value": 1.5, "unit": "GeV", "source": "..."},
     "evaluate": {"axes": [...]}}

The basis is declared, or derived from the coupling orders of the amplitude
terms (every product of two terms, so interference of mixed degree is included)
or from a total ``degree``. When the basis and coupling orders are both given they
must agree. At least one held-out run is required. The width declaration is
required: ``fixed`` (value, unit, source), ``morphed`` (its own runs and held-out
runs, fitted with the same core) or ``not-applicable`` (reason).

Runs may give per-bin ``values``/``uncertainties`` as lists or as file
references (a binned_values result supplies uncertainties from sumw2). The
fitted morph is written to ``coupling-morph.json``; other modes load it only when
every held-out comparison passed (``usable``). A failed closure test makes the
study fail; the coefficients are still written.
"""
from __future__ import annotations

import numpy as np

from ravel.physics import coupling_polynomial as cp

from . import common, formula, morphing, record

MODE = 'coupling-morphing'


def validate(task):
    common.validate(task)


def _resolve_rows(ctx, rows, label):
    out = []
    for row in rows or []:
        if type(row) is not dict:
            raise ValueError(label + ' must be objects')
        row = dict(row)
        if 'values' in row and type(row['values']) is dict:
            values, sumw2 = ctx.vector(row['values'], label + ' values', with_sumw2=True)
            row['values'] = values.tolist()
            if 'uncertainties' not in row and sumw2 is not None:
                row['uncertainties'] = np.sqrt(sumw2).tolist()
        if 'uncertainties' in row and type(row['uncertainties']) is dict:
            row['uncertainties'] = ctx.vector(row['uncertainties'], label + ' uncertainties').tolist()
        out.append(row)
    return out


WIDTH_TREATMENTS = ('fixed', 'morphed', 'not-applicable')


def _basis(doc, names):
    """The declared basis, or the one implied by amplitude coupling orders or a total degree."""
    declared = doc.get('basis')
    if declared is None:
        if 'amplitudes' in doc:
            derived = cp.basis_from_amplitudes(names, doc['amplitudes'])
        elif 'degree' in doc:
            degree = doc['degree']
            if type(degree) is not dict or set(degree) != {'total', 'homogeneous'}:
                raise ValueError('degree is {"total": n, "homogeneous": true|false}')
            derived = cp.basis_of_degree(names, degree['total'], homogeneous=degree['homogeneous'])
        else:
            raise ValueError('declare the basis, the amplitude coupling orders or a total degree')
        return [dict((p, n) for p, n in zip(names, powers) if n) for powers in derived]
    powers = morphing._basis(declared, names)
    cp.check_basis(names, powers, amplitudes=doc.get('amplitudes'), degree=doc.get('degree'))
    return declared


def _width(ctx, raw, names, basis, method, ceiling):
    """A width declaration is mandatory: fixed, morphed with the same core, or not applicable."""
    if type(raw) is not dict or raw.get('treatment') not in WIDTH_TREATMENTS:
        raise ValueError('declare the width treatment: fixed (value, unit, source), morphed (unit, runs, '
                         'holdout) or not-applicable (reason)')
    treatment = raw['treatment']
    if treatment == 'fixed':
        if set(raw) != {'treatment', 'value', 'unit', 'source'} or type(raw['value']) not in (int, float) \
                or not raw['value'] >= 0 or type(raw['unit']) is not str or type(raw['source']) is not str \
                or not raw['source'].strip():
            raise ValueError('a fixed width needs a nonnegative value, its unit and its source')
        return dict(raw), None
    if treatment == 'not-applicable':
        if set(raw) != {'treatment', 'reason'} or type(raw['reason']) is not str or not raw['reason'].strip():
            raise ValueError('a not-applicable width needs a stated reason')
        return dict(raw), None
    allowed = {'treatment', 'unit', 'basis', 'runs', 'holdout', 'closure_tolerance_sigma'}
    if not {'treatment', 'unit', 'runs', 'holdout'} <= set(raw) or set(raw) - allowed:
        raise ValueError('a morphed width needs unit, runs and holdout (basis defaults to the quantity basis)')
    fit = morphing.fit({'parameters': names, 'basis': raw.get('basis', basis),
                        'method': 'exact' if len(raw['runs']) == len(raw.get('basis', basis)) else method,
                        'max_condition': ceiling, 'runs': _resolve_rows(ctx, raw['runs'], 'width runs'),
                        'holdout': _resolve_rows(ctx, raw['holdout'], 'width holdout'),
                        'closure_tolerance_sigma': raw.get('closure_tolerance_sigma', 3)})
    document = fit.document()
    return {'treatment': 'morphed', 'unit': raw['unit'],
            'fit': {k: document[k] for k in ('basis', 'monomial_labels', 'coefficients', 'covariance',
                                             'condition_number', 'closure', 'usable')}}, fit


def load(task, base):
    ctx, doc = common.context(task, base, MODE)
    required = {'schema_version', 'kind', 'parameters', 'quantity', 'method', 'max_condition', 'runs', 'width'}
    optional = {'description', 'basis', 'amplitudes', 'degree', 'holdout', 'closure_tolerance_sigma', 'evaluate'}
    if 'width' not in doc:
        raise ValueError('a width declaration is required (fixed, morphed or not-applicable)')
    if not required <= set(doc) or set(doc) - required - optional:
        raise ValueError('coupling-morphing documents need ' + ', '.join(sorted(required - {'schema_version', 'kind'})))
    if not doc.get('holdout'):
        raise ValueError('at least one held-out run is required; it must agree with the fitted polynomial '
                         'within the combined uncertainty')
    parameters = [common.parameter(p) for p in doc['parameters']]
    quantity = common.parameter(doc['quantity'], 'quantity')
    names = [p['name'] for p in parameters]
    basis = _basis(doc, names)
    spec = {'parameters': names, 'basis': basis, 'method': doc['method'],
            'max_condition': doc['max_condition'], 'runs': _resolve_rows(ctx, doc['runs'], 'runs'),
            'holdout': _resolve_rows(ctx, doc['holdout'], 'holdout'),
            'closure_tolerance_sigma': doc.get('closure_tolerance_sigma')}
    morph = morphing.fit(spec)
    morph.width, width_fit = _width(ctx, doc['width'], names, basis, doc['method'], doc['max_condition'])
    grid = None
    if doc.get('evaluate') is not None:
        grid = formula.grid(doc['evaluate'])
        if {p['name'] for p in grid.parameters} != set(spec['parameters']):
            raise ValueError('the evaluation grid must cover exactly the morph parameters')
    return ctx, parameters, quantity, morph, grid, width_fit


def inputs(task, base):
    return common.inputs(load(task, base)[0])


def run(task, base, output):
    ctx, parameters, quantity, morph, grid, width_fit = load(task, base)
    from pathlib import Path
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    morph_pin = record.write(output / 'coupling-morph.json', {**morph.document(), 'quantity': quantity})
    labels = morph.document()['monomial_labels']
    results = [record.result(
        'morph-coefficients', 'primary', monomials=labels, coefficients=morph.coefficients,
        covariance=morph.covariance, condition_number=morph.condition_number,
        raw_condition_number=morph.raw_condition_number, method=morph.method, ndf=morph.ndf,
        chi2=morph.chi2, document='coupling-morph.json', document_sha256=morph_pin['sha256'],
        summary=f'{quantity["label"]} = ' + ' + '.join(f'c[{m}]*{m}' for m in labels)
                + f' fitted from {len(morph.runs)} runs (condition number {morph.condition_number:.3g})')]
    failed = [c for c in morph.closure if not c['passed']]
    if width_fit is not None:
        failed += [{**c, 'id': 'width:' + c['id']} for c in width_fit.closure if not c['passed']]
    if morph.closure:
        results.append(record.result(
            'morph-closure', 'primary', checks=morph.closure,
            summary=f'closure on {len(morph.closure)} held-out run(s): '
                    + ('all within tolerance' if not failed else f'{len(failed)} outside tolerance')))
    if grid is not None:
        predicted, variance = morph.predict(grid.columns, with_variance=True)
        results.append(record.result(
            'grid-values', 'primary', name=quantity['name'], label=quantity['label'], unit=quantity['unit'],
            values=predicted, variance=variance,
            summary=f'{quantity["label"]} predicted at {grid.size} grid points'))
    inference = record.build(
        mode=MODE, engine='coupling-morphing', statistic=record.statistic('not-applicable'),
        parameters=parameters, results=results, grid=None if grid is None else grid.describe(),
        inputs=ctx.inputs(), status='failed' if failed else 'passed',
        diagnostics={'runs': morph.runs, 'width': morph.width, 'usable': not failed},
        limitations=['The polynomial form and basis are declared; terms outside the basis are not detected '
                     'except through held-out closure.'])
    return common.deliver(output, inference, review=ctx.review, scope='Declared monomial-basis morphing of supplied runs')
