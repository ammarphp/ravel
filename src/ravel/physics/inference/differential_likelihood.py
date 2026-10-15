"""Science mode ``differential-likelihood``: reinterpret a measured differential spectrum.

Input document (``kind: differential-likelihood``)::

    {"schema_version": 1, "kind": "differential-likelihood",
     "statistic": {"verbatim": "...", "test_statistic": "two-sided", "threshold": 3.84,
                   "objective": "chi2", "toys": {"n": 1000, "seed": 1, "method": "neyman",
                   "points": [...], "confidence_level": 0.95}},
     "observable": {"name": "mass", "unit": "GeV", "label": "Invariant mass"},
     "measurement": {"values": <vector>, "unit": "fb/GeV", "bin_edges": [...]},
     "reference": {"values": <vector>, "description": "published SM prediction"},
     "signal": {"convention": "difference-to-reference", "difference_reference": "...",
                "parameters": [{"name": "kappa", "unit": "", "label": "Coupling modifier"}],
                "terms": [{"powers": {"kappa": 2}, "values": <vector>, "kind": "interference"}, ...]},
     "hypotheses": [{"id": "M700_W10", "coordinates": {...}, "terms": [...]}],
     "covariance": [{"name": "systematic", "law": "ratio", "matrix": <matrix>}, ...],
     "mc_covariance": <matrix> | null,
     "nuisances": [{"name": ..., "applies_to": "reference" | "term:0" | "absolute", "relative": ...,
                    "origin": "cited", "citation": ...}],
     "scan": {"parameter": "kappa", "min": 0, "max": 3, "points": 301}, "domain": [0, null],
     "max_condition": 1e10,
     "applicability": {"unfolding": {"max_relative_deviation": 0.3, "citation": "..."}}}

``signal.terms`` may instead be ``signal.morph: {"path": ...}`` with optional
``fixed`` values; the morph coefficient covariance becomes the MC covariance.
With ``statistic.verbatim`` the requested statistic is primary. Without it the
RAVEL default is used: toy CLs (``toys.method: cls``) is primary and the
asymptotic region is reported alongside.
"""
from __future__ import annotations

import math

import numpy as np

from . import applicability, common, differential, formula, gof, intervals, record

MODE = 'differential-likelihood'


def validate(task):
    common.validate(task)


def _number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(label + ' must be a finite number')
    return float(value)


def _terms(ctx, raw, n, parameters, label):
    terms = []
    for k, term in enumerate(raw):
        if type(term) is not dict or not {'powers', 'values'} <= set(term) or set(term) - {'powers', 'values', 'kind', 'scale', 'label'}:
            raise ValueError(f'{label} term {k} needs powers and values (optional kind, scale, label)')
        if term.get('kind', 'other') not in ('interference', 'pure-signal', 'other'):
            raise ValueError(f'{label} term {k} kind must be interference, pure-signal or other')
        values = ctx.vector(term['values'], f'{label} term {k}')
        if values.shape != (n,):
            raise ValueError(f'{label} term {k} has {len(values)} bins; the measurement has {n}')
        if term.get('scale') is not None:
            applicability._cited(term['scale'], f'{label} term {k} scale factor')
            _number(term['scale'].get('value'), f'{label} term {k} scale value')
        terms.append({**term, 'values': values})
    return terms


def _morph_terms(ctx, spec, n):
    morph = ctx.morph(spec['morph'])
    fixed = dict(spec.get('fixed') or {})
    if morph.bins != n:
        raise ValueError('the morph has a different number of bins from the measurement')
    free = [p for p in morph.parameters if p not in fixed]
    terms = []
    for k, powers in enumerate(morph.basis):
        factor = 1.0
        mapping = {}
        for p, power in zip(morph.parameters, powers):
            if p in fixed:
                factor *= float(fixed[p]) ** power
            elif power:
                mapping[p] = power
        terms.append({'powers': mapping, 'values': factor * morph.coefficients[k]})
    mc = None
    if morph.covariance is not None:
        K = len(morph.basis)
        mc = np.zeros((K * n, K * n))
        for i in range(n):
            for a in range(K):
                for b in range(K):
                    fa = np.prod([float(fixed[p]) ** pw for p, pw in zip(morph.parameters, morph.basis[a]) if p in fixed])
                    fb = np.prod([float(fixed[p]) ** pw for p, pw in zip(morph.parameters, morph.basis[b]) if p in fixed])
                    mc[a * n + i, b * n + i] = fa * fb * morph.covariance[i, a, b]
    return free, terms, mc


def load(task, base):
    ctx, doc = common.context(task, base, MODE)
    if doc.get('operation') == 'cached-profile':
        from . import cached_profile
        return ctx, {'cached_profile': cached_profile.load(ctx, doc)}
    required = {'statistic', 'observable', 'measurement', 'reference', 'signal', 'covariance', 'scan', 'domain'}
    optional = {'schema_version', 'kind', 'description', 'hypotheses', 'mc_covariance', 'nuisances',
                'max_condition', 'applicability'}
    if not required <= set(doc) or set(doc) - required - optional:
        raise ValueError('differential-likelihood documents need ' + ', '.join(sorted(required)))
    st = doc['statistic']
    allowed = {'verbatim', 'test_statistic', 'threshold', 'objective', 'toys'}
    if type(st) is not dict or set(st) - allowed or st.get('test_statistic') not in ('two-sided', 'one-sided-upper'):
        raise ValueError('statistic needs test_statistic two-sided or one-sided-upper, threshold and objective')
    threshold = _number(st.get('threshold'), 'threshold')
    toys = st.get('toys')
    if st.get('verbatim') is None and (type(toys) is not dict or toys.get('method') != 'cls'):
        raise ValueError('without a prescribed statistic the default is CLs: declare statistic.toys with method cls')
    if toys is not None:
        if type(toys) is not dict or set(toys) - {'n', 'seed', 'method', 'points', 'confidence_level', 'null'}:
            raise ValueError('toys need n, seed, method, points, confidence_level and (for cls) null')
        _number(toys.get('confidence_level'), 'confidence level')
    observable = common.parameter(doc['observable'], 'observable')
    measurement = doc['measurement']
    if type(measurement) is not dict or 'values' not in measurement or type(measurement.get('unit')) is not str:
        raise ValueError('measurement needs values and unit')
    y = ctx.vector(measurement['values'], 'measured values')
    n = len(y)
    edges = measurement.get('bin_edges')
    if edges is not None:
        edges = [_number(e, 'bin edge') for e in edges]
        if len(edges) != n + 1 or any(b <= a for a, b in zip(edges, edges[1:])):
            raise ValueError('bin_edges must be increasing with one more entry than the bins')
    reference = doc['reference']
    if type(reference) is not dict or 'values' not in reference or not str(reference.get('description', '')).strip():
        raise ValueError('reference needs values and a description of its source')
    ref = ctx.vector(reference['values'], 'reference values')
    signal = doc['signal']
    if type(signal) is not dict or signal.get('convention') != 'difference-to-reference':
        raise ValueError('signal.convention must be difference-to-reference: supply model minus reference, '
                         'never a prediction that already contains the reference')
    if not str(signal.get('difference_reference', '')).strip():
        raise ValueError('signal.difference_reference must state which reference the difference was taken from')
    parameters = [common.parameter(p) for p in signal.get('parameters', [])]
    names = [p['name'] for p in parameters]
    if 'morph' in signal:
        free, terms, mc_from_morph = _morph_terms(ctx, signal, n)
        if free != names:
            raise ValueError('signal.parameters must list the morph parameters left free')
    else:
        terms, mc_from_morph = _terms(ctx, signal.get('terms') or [], n, names, 'signal'), None
    hypotheses = []
    for h in doc.get('hypotheses') or []:
        if type(h) is not dict or set(h) - {'id', 'coordinates', 'terms', 'mc_covariance'}:
            raise ValueError('hypotheses need id, coordinates, terms and optional mc_covariance')
        hypotheses.append({'id': str(h['id']), 'coordinates': dict(h.get('coordinates') or {}),
                           'terms': _terms(ctx, h['terms'], n, names, f'hypothesis {h["id"]}'),
                           'mc': None if h.get('mc_covariance') is None else ctx.matrix(h['mc_covariance'], 'MC covariance')})
    if not hypotheses:
        if not terms:
            raise ValueError('signal needs terms or a morph, or hypotheses with terms')
        hypotheses = [{'id': 'nominal', 'coordinates': {}, 'terms': terms,
                       'mc': None if doc.get('mc_covariance') is None else ctx.matrix(doc['mc_covariance'], 'MC covariance')}]
        if hypotheses[0]['mc'] is None:
            hypotheses[0]['mc'] = mc_from_morph
    components = []
    for c in doc['covariance']:
        if type(c) is not dict or set(c) - {'name', 'law', 'matrix', 'source'}:
            raise ValueError('covariance components need name, law and matrix')
        components.append({'name': c.get('name'), 'law': c.get('law'), 'matrix': ctx.matrix(c['matrix'], f'covariance {c.get("name")}')})
    nuisances = []
    for nu in doc.get('nuisances') or []:
        if type(nu) is not dict or not {'name', 'applies_to'} <= set(nu):
            raise ValueError('nuisances need name and applies_to')
        applicability._cited(nu, f'nuisance {nu["name"]}')
        row = {'name': nu['name'], 'applies_to': nu['applies_to']}
        if nu['applies_to'] == 'absolute':
            row['shift'] = ctx.vector(nu['shift'], f'nuisance {nu["name"]} shift')
        else:
            rel = nu.get('relative')
            row['relative'] = ctx.vector(rel, f'nuisance {nu["name"]}') if type(rel) in (list, dict) else _number(rel, 'relative size')
        nuisances.append(row)
    scan = doc['scan']
    if type(scan) is not dict or set(scan) != {'parameter', 'min', 'max', 'points'} or scan['parameter'] not in names:
        raise ValueError('scan needs parameter (a signal parameter), min, max and points')
    grid = formula.grid({'axes': [{'name': scan['parameter'], 'unit': '', 'min': scan['min'], 'max': scan['max'],
                                   'points': scan['points']}]}).axes[0]['values']
    domain = doc['domain']
    if type(domain) is not list or len(domain) != 2:
        raise ValueError('domain is [lower or null, upper or null]')
    others = [p for p in names if p != scan['parameter']]
    if others:
        raise ValueError('scan one parameter; fix the others through a morph with fixed values')
    guard = (doc.get('applicability') or {}).get('unfolding')
    models = []
    for h in hypotheses:
        models.append((h, differential.Model(
            measured=y, reference=ref, terms=h['terms'], components=components, parameters=names,
            nuisances=nuisances, mc_covariance=h['mc'], objective=st.get('objective', 'chi2'),
            max_condition=doc.get('max_condition', 1e12))))
    return ctx, {'statistic': st, 'threshold': threshold, 'observable': observable, 'measurement': measurement,
                 'edges': edges, 'reference': reference, 'parameters': parameters, 'scan': scan['parameter'],
                 'grid': grid, 'domain': tuple(domain), 'models': models, 'guard': guard, 'nuisances': nuisances,
                 'y': y, 'ref': ref}


def inputs(task, base):
    ctx, spec = load(task, base)
    if 'cached_profile' in spec:
        from pathlib import Path
        return [Path(p) for p in spec['cached_profile']['inputs']]
    return common.inputs(ctx)


def run(task, base, output):
    ctx, spec = load(task, base)
    if 'cached_profile' in spec:
        from . import cached_profile
        return cached_profile.run(ctx, spec['cached_profile'], output, task=task)
    st, p = spec['statistic'], spec['scan']
    label = next(x['label'] for x in spec['parameters'] if x['name'] == p)
    prescribed = st.get('verbatim') is not None
    toys = st.get('toys')
    results, failed, findings = [], False, []
    traps = applicability.interpretation_traps()
    for h, model in spec['models']:
        tag = '' if h['id'] == 'nominal' else f' [{h["id"]}]'
        scan = model.scan_1d(p, spec['grid'], domain=spec['domain'])
        best = scan['best_fit'][p]
        if st['test_statistic'] == 'one-sided-upper':
            statistic = intervals.one_sided(scan['grid'], scan['delta'], best)
            refine = lambda x, scan=scan, best=best: 0.0 if x < best else scan['refine'](x)
        else:
            statistic, refine = scan['delta'], scan['refine']
        region = intervals.allowed_regions(scan['grid'], statistic, spec['threshold'], refine, domain=spec['domain'])
        region['best_fit'] = scan['best_fit']
        guard = None
        if spec['guard'] is not None:
            guard = applicability.unfolding_guard(model, p, scan['grid'], spec['guard'])
            applicability.mark_edges(region, guard, p)
        k_findings = applicability.k_factor_policy(h['terms'], spec['nuisances'])
        findings += [{**f, 'hypothesis': h['id']} for f in k_findings]
        asymptotic_role = 'primary' if prescribed else 'companion'
        if region['status'] not in ('resolved', 'empty') and asymptotic_role == 'primary':
            failed = True
        results.append(record.result(
            'delta-nll-region', asymptotic_role, hypothesis=h['id'], coordinates=h['coordinates'], parameter=p,
            test_statistic=st['test_statistic'], calibration='asymptotic', **region,
            summary=f'Delta(-2 ln L) <= {spec["threshold"]:g}{tag}: ' + intervals.describe(region, label)
                    + f'; best fit {label} = {best:.6g}'))
        prep = model._prepare({p: best})
        if prep['status'] == 'accepted':
            chi2 = float(model._value(prep, model.y)) - prep['logdet']
            goodness = gof.evaluate(chi2, ndf=model.bins - 1, request=None,
                                    statistic='chi-square at the best fit (nuisances profiled)',
                                    data_description='measured spectrum')
            goodness['asymptotic']['meaning'] = ('Gaussian likelihood: chi-square distribution, exact for a linear '
                                                 'prediction with fixed covariance and approximate otherwise')
            results.append({**goodness, 'hypothesis': h['id'], 'coordinates': h['coordinates']})
        results.append(record.result(
            'delta-nll-scan', 'diagnostic', hypothesis=h['id'], parameter=p, grid=scan['grid'],
            twice_nll=scan['twice_nll'], delta=scan['delta'], delta_to_reference=scan['delta_to_reference'],
            reference_point=scan['reference_point'], unavailable_points=scan['unavailable_points'],
            nuisances_at_best_fit=model.profile_nuisances({p: best}),
            prediction_at_best_fit=model.prediction({p: best}), measured=spec['y'], reference=spec['ref']))
        if toys is not None:
            points = toys.get('points') or [float(x) for x in scan['grid'][::max(1, len(scan['grid']) // 20)]]
            t = model.toys(p, scan['grid'], points=points, n=toys['n'], seed=toys['seed'], method=toys['method'],
                           null=None if toys.get('null') is None else {p: toys['null']}[p])
            alpha = 1 - toys['confidence_level']
            key = 'cls' if toys['method'] == 'cls' else 'p_value'
            kept = [row['value'] for row in t['points'] if row.get(key) is not None and row[key] > alpha]
            excluded = [row['value'] for row in t['points'] if row.get(key) is not None and row[key] <= alpha]
            role = 'companion' if prescribed else 'primary'
            results.append(record.result(
                'toy-p-values', role, hypothesis=h['id'], parameter=p, confidence_level=toys['confidence_level'],
                **t, not_excluded=kept, excluded=excluded,
                summary=f'toy {toys["method"]} at {toys["confidence_level"]:.0%} CL{tag}: {len(excluded)} of '
                        f'{len(t["points"])} tested {label} values excluded'
                        + (f' (smallest excluded {min(excluded):.6g})' if excluded else '')))
        if guard is not None:
            results.append(record.result('applicability', 'diagnostic', hypothesis=h['id'], unfolding=guard,
                                         **({'summary': f'unfolding validity exceeded for {label} >= {guard["first_flagged_value"]:.6g}{tag}'}
                                            if guard['fires'] else {})))
    if findings:
        results.append(record.result('applicability', 'diagnostic', findings=findings))
    statistic = (record.statistic('prescribed', verbatim=st['verbatim'], definition={
                     'test_statistic': st['test_statistic'], 'threshold': spec['threshold'],
                     'objective': st.get('objective', 'chi2'), 'toys': toys})
                 if prescribed else
                 record.statistic('default', definition={'primary': 'toy CLs', 'toys': toys,
                                                         'asymptotic_companion_threshold': spec['threshold']}))
    limitations = ['The measured spectrum, covariance components and their scaling laws are as supplied.',
                   'Interval edges marked outside_unfolding_validity rely on the unfolded measurement beyond its tested deviation range.']
    if spec['guard'] is None:
        limitations.append('No unfolding validity range was declared; large deviations are not checked against it.')
    if findings:
        limitations.append(f'{len(findings)} applicability finding(s) are listed in the record.')
    inference = record.build(
        mode=MODE, engine='gaussian-measurement', statistic=statistic, parameters=spec['parameters'],
        results=results, inputs=ctx.inputs(), status='failed' if failed else 'passed',
        grid={'kind': 'scan', 'parameter': p, 'values': spec['grid'], 'domain': list(spec['domain'])},
        diagnostics={'observable': spec['observable'], 'bin_edges': spec['edges'],
                     'measurement_unit': spec['measurement']['unit'],
                     'reference_description': spec['reference']['description'],
                     'interpretation_traps': traps},
        limitations=limitations)
    return common.deliver(output, inference, review=ctx.review, scope='Gaussian likelihood for a measured differential spectrum')
