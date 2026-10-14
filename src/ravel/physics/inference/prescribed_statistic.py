"""Science mode ``prescribed-statistic``: evaluate the statistic a request prescribes.

The requester's wording is recorded verbatim in ``statistic.verbatim``; the
result of that statistic is the primary result. RAVEL's 95% CLs can be added
alongside (``companion``) and never replaces it.

``statistic.kind: closed-form`` evaluates a declared formula (for example a
significance such as 2(sqrt(S+B) - sqrt(B))) on a grid. Fields: ``grid``,
``program`` (see ``formula-grid``), ``statistic_output``, ``threshold`` and
``region`` (``at-or-above`` or ``at-or-below``). A one-axis grid gives
bracketed crossings; a two-axis grid gives contour lines.

``statistic.kind: binned-profile`` builds a per-bin Poisson likelihood from
channel tables (observed, background, background uncertainty) with a declared
nuisance form, sums channels (for example experiments), and scans one
parameter. Fields: ``parameter``, ``domain``, ``scan``, ``test_statistic``
(``two-sided``, ``one-sided-upper`` or ``discovery``), ``threshold`` (on
Delta(-2 ln L)), ``nuisance_form``, ``background_floor``, ``channels``, and
``signal`` (linear, power-law ``(g/g0)^k`` or a polynomial coupling morph per
channel) or a list of ``hypotheses`` each with its own ``signal``. Optional:
``expected: true`` adds the background-only Asimov expectation, ``null`` sets the
discovery null value, ``companion: {"cls": true, "level": 0.05}`` adds CLs.
"""
from __future__ import annotations

import math

import numpy as np

from . import common, contours, counting, formula, gof, intervals, record

MODE = 'prescribed-statistic'
KINDS = ('closed-form', 'binned-profile')
TEST_STATISTICS = ('two-sided', 'one-sided-upper', 'discovery')


def validate(task):
    common.validate(task)


def _number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(label + ' must be a finite number')
    return float(value)


def _statistic(doc):
    st = doc.get('statistic')
    if type(st) is not dict or set(st) - {'verbatim', 'kind', 'name'} or st.get('kind') not in KINDS:
        raise ValueError('statistic needs verbatim and kind closed-form or binned-profile')
    if type(st.get('verbatim')) is not str or not st['verbatim'].strip():
        raise ValueError('the prescribed statistic must be recorded verbatim from the request')
    return st


# ---------------------------------------------------------------------- closed form
def _load_closed(ctx, doc):
    allowed = {'schema_version', 'kind', 'description', 'statistic', 'grid', 'program', 'statistic_output',
               'threshold', 'region', 'contour_axes'}
    if set(doc) - allowed or not {'grid', 'program', 'statistic_output', 'threshold', 'region'} <= set(doc):
        raise ValueError('a closed-form statistic needs grid, program, statistic_output, threshold and region')
    grid = formula.grid(doc['grid'])
    program = formula.Program(doc['program'], grid.parameters)
    if doc['statistic_output'] not in program.labels:
        raise ValueError('statistic_output must name a declared program output')
    if doc['region'] not in ('at-or-above', 'at-or-below'):
        raise ValueError('region must be at-or-above or at-or-below')
    if grid.axes is None or len(grid.axes) not in (1, 2):
        raise ValueError('a closed-form statistic needs a one- or two-axis product grid')
    return {'grid': grid, 'program': program, 'output': doc['statistic_output'],
            'threshold': _number(doc['threshold'], 'threshold'), 'region': doc['region'],
            'axes': doc.get('contour_axes')}


def _run_closed(spec, statistic):
    grid, program, name = spec['grid'], spec['program'], spec['output']
    values = program.evaluate(grid.columns)
    stat = values[name]
    label, t = program.labels[name], spec['threshold']
    sign = -1.0 if spec['region'] == 'at-or-above' else 1.0
    bad = formula.nonfinite_points(stat)
    results = [record.result('grid-values', 'primary', name=name, label=label, unit=program.units[name],
                             values=stat, nonfinite_points=bad,
                             summary=f'{label} evaluated at {grid.size} grid points')]
    for other, _ in program.outputs:
        if other != name:
            results.append(record.result('grid-values', 'diagnostic', name=other, label=program.labels[other],
                                         unit=program.units[other], values=values[other]))
    relation = '>=' if sign < 0 else '<='
    if len(grid.axes) == 1:
        axis = grid.axes[0]
        def refine(x):
            return sign * float(program.evaluate({axis['name']: np.array([x])})[name][0])
        region = intervals.allowed_regions(axis['values'], sign * stat, sign * t, refine)
        for row in region['intervals']:
            for edge in (row['low'], row['high']):
                if 'statistic_at_value' in edge:
                    edge['statistic_at_value'] *= sign
        results.append(record.result(
            'contour', 'primary', kind='interval', level=t,
            relation=relation, parameter=axis['name'], region=region,
            summary=f'{label} {relation} {t:g}: ' + intervals.describe(region, axis.get('label', axis['name']))))
        status = 'passed' if region['status'] in ('resolved', 'empty') and not bad else 'failed'
    else:
        axes = spec['axes'] or {'x': grid.axes[0]['name'], 'y': grid.axes[1]['name']}
        lines = contours.level_lines(grid, stat, t, x=axes['x'], y=axes['y'])
        inside = np.asarray(sign * stat <= sign * t)
        results.append(record.result(
            'contour', 'primary', kind='level-set', level=t, relation=relation, x=axes['x'], y=axes['y'],
            series=contours.series(lines, identifier=f'{name}-{t:g}', label=f'{label} = {t:g}'),
            fraction_of_grid_in_region=float(inside.mean()),
            summary=f'{label} = {t:g} contour: {len(lines)} line(s); {inside.mean():.1%} of the grid has {label} {relation} {t:g}'))
        status = 'passed' if not bad else 'failed'
    return results, status, grid.describe(), program


# ---------------------------------------------------------------------- binned profile
def _signal(ctx, spec, channels, parameter):
    if type(spec) is not dict:
        raise ValueError('signal must be an object')
    kind = spec.get('kind')
    if kind in ('linear', 'power'):
        templates = spec.get('templates')
        if type(templates) is not dict or set(templates) != set(channels):
            raise ValueError('signal templates must cover exactly the declared channels')
        resolved = {k: ctx.vector(v, f'signal template {k}').tolist() for k, v in templates.items()}
        if kind == 'linear':
            if set(spec) - {'kind', 'templates', 'source'}:
                raise ValueError('a linear signal has kind and templates')
            return counting.Signal.linear(parameter, resolved)
        if set(spec) - {'kind', 'templates', 'reference', 'power', 'source'}:
            raise ValueError('a power-law signal has kind, templates, reference and power')
        return counting.Signal.power(parameter, reference=spec.get('reference'), power=spec.get('power'),
                                     templates=resolved)
    if kind == 'polynomial':
        if set(spec) - {'kind', 'morphs', 'fixed', 'source'} or type(spec.get('morphs')) is not dict:
            raise ValueError('a polynomial signal has kind, morphs and optional fixed values')
        if set(spec['morphs']) != set(channels):
            raise ValueError('signal morphs must cover exactly the declared channels')
        morphs = {k: ctx.morph(v) for k, v in spec['morphs'].items()}
        signal = counting.Signal.polynomial(morphs, fixed=spec.get('fixed'))
        if signal.parameters != [parameter]:
            raise ValueError('the morph must leave exactly the scanned parameter free')
        return signal
    raise ValueError('signal kind must be linear, power or polynomial')


def _load_binned(ctx, doc):
    required = {'parameter', 'domain', 'scan', 'test_statistic', 'nuisance_form', 'background_floor', 'channels'}
    allowed = required | {'schema_version', 'kind', 'description', 'statistic', 'threshold', 'signal',
                          'hypotheses', 'expected', 'null', 'companion'}
    if set(doc) - allowed or not required <= set(doc):
        raise ValueError('a binned-profile statistic needs ' + ', '.join(sorted(required)))
    parameter = common.parameter(doc['parameter'])
    domain = doc['domain']
    if type(domain) is not list or len(domain) != 2 or any(v is not None and type(v) not in (int, float) for v in domain):
        raise ValueError('domain is [lower or null, upper or null]')
    scan = doc['scan']
    if type(scan) is not dict or set(scan) != {'min', 'max', 'points'}:
        raise ValueError('scan needs min, max and points')
    grid = formula.grid({'axes': [{'name': parameter['name'], 'unit': parameter['unit'], **scan}]}).axes[0]['values']
    ts = doc['test_statistic']
    if ts not in TEST_STATISTICS:
        raise ValueError('test_statistic must be two-sided, one-sided-upper or discovery')
    threshold = None if ts == 'discovery' and 'threshold' not in doc else _number(doc.get('threshold'), 'threshold')
    channels = []
    for raw in doc['channels']:
        if type(raw) is not dict:
            raise ValueError('channels must be objects')
        resolved = {**raw, **{k: ctx.vector(raw[k], f'{k} in {raw.get("name")}').tolist()
                              for k in ('observed', 'background', 'background_uncertainty') if k in raw}}
        channels.append(counting.channel_from_spec(resolved, form=doc['nuisance_form'], floor=doc['background_floor']))
    names = [c.name for c in channels]
    if ('signal' in doc) == ('hypotheses' in doc):
        raise ValueError('give either signal or hypotheses')
    hypotheses = []
    if 'signal' in doc:
        hypotheses.append({'id': 'nominal', 'coordinates': {}, 'signal': _signal(ctx, doc['signal'], names, parameter['name'])})
    else:
        for h in doc['hypotheses']:
            if type(h) is not dict or set(h) - {'id', 'coordinates', 'signal'} or 'signal' not in h:
                raise ValueError('hypotheses need id, coordinates and signal')
            hypotheses.append({'id': str(h['id']), 'coordinates': dict(h.get('coordinates') or {}),
                               'signal': _signal(ctx, h['signal'], names, parameter['name'])})
        if len({h['id'] for h in hypotheses}) != len(hypotheses):
            raise ValueError('hypothesis ids must be unique')
    companion = doc.get('companion') or {}
    if set(companion) - {'cls', 'level'}:
        raise ValueError('companion has cls and level')
    return {'parameter': parameter, 'domain': tuple(domain), 'grid': grid, 'test_statistic': ts,
            'threshold': threshold, 'channels': channels, 'hypotheses': hypotheses,
            'expected': bool(doc.get('expected', False)), 'null': _number(doc.get('null', 0.0), 'null'),
            'cls': bool(companion.get('cls', False)), 'cls_level': _number(companion.get('level', 0.05), 'CLs level'),
            'form': doc['nuisance_form'], 'floor': doc['background_floor']}


def _region(likelihood, spec):
    p, ts = spec['parameter']['name'], spec['test_statistic']
    scan = counting.scan_1d(likelihood, p, spec['grid'], domain=spec['domain'])
    best = scan['best_fit'][p]
    if ts == 'discovery':
        null_value = likelihood.twice_nll({p: spec['null']})
        q0 = max(0.0, null_value - scan['best_fit']['twice_nll']) if best > spec['null'] else 0.0
        return scan, {'q0': q0, 'significance': math.sqrt(q0), 'null': spec['null'], 'best_fit': best}
    if ts == 'one-sided-upper':
        statistic = intervals.one_sided(scan['grid'], scan['delta'], best)
        refine = lambda x: 0.0 if x < best else scan['refine'](x)
    else:
        statistic, refine = scan['delta'], scan['refine']
    region = intervals.allowed_regions(scan['grid'], statistic, spec['threshold'], refine, domain=spec['domain'])
    region['best_fit'] = scan['best_fit']
    region['other_local_minima'] = scan['other_local_minima']
    return scan, region


def _asimov(channels, signal):
    out = []
    for c in channels:
        out.append(counting.Channel(c.name, c.b.tolist(), c.b.tolist(), c.d.tolist(), form=c.form, floor=c.floor))
    return counting.Likelihood(out, signal)


def _cls(spec, signal, channels):
    if signal.kind not in ('linear', 'power'):
        return {'status': 'not_available', 'reason': 'CLs on a signal strength needs a linear or power-law signal'}
    if spec['form'] == 'lognormal':
        return {'status': 'not_available', 'reason': 'the lognormal per-bin form has no exact pyhf counterpart here'}
    import pyhf
    from ravel.physics import pyhf_exclude
    pyhf.set_backend('numpy', pyhf_exclude.robust_optimizer(maxiter=200000))
    p = spec['parameter']['name']
    channels_spec, data = [], []
    s_ref = signal({p: signal.reference})
    for c in channels:
        modifiers = []
        if spec['form'] == 'gaussian-linear':
            modifiers.append({'name': f'staterror_{c.name}', 'type': 'staterror', 'data': c.d.tolist()})
        elif spec['form'] == 'poisson-gamma':
            modifiers.append({'name': f'shapesys_{c.name}', 'type': 'shapesys', 'data': c.d.tolist()})
        channels_spec.append({'name': c.name, 'samples': [
            {'name': 'signal', 'data': np.asarray(s_ref[c.name]).ravel().tolist(),
             'modifiers': [{'name': 'mu', 'type': 'normfactor', 'data': None}]},
            {'name': 'background', 'data': c.b.tolist(), 'modifiers': modifiers}]})
        data += c.n.tolist()
    model = pyhf.Model({'channels': channels_spec}, poi_name='mu', modifier_settings=pyhf_exclude.MODIFIER_SETTINGS)
    full = data + model.config.auxdata
    result = pyhf_exclude.compute(model, full, level=spec['cls_level'])
    def convert(mu):
        if mu is None:
            return None
        return mu if signal.kind == 'linear' else signal.reference * mu ** (1.0 / signal.power)
    return {'status': 'computed', 'level': spec['cls_level'], 'statistic': 'asymptotic CLs with qtilde (pyhf)',
            'signal_strength': {'observed': result['obs_limit'], 'expected': result['exp_limits'],
                                'status': result['limit_status']},
            'parameter_limit': {'observed': convert(result['obs_limit']),
                                'expected': [convert(x) for x in result['exp_limits']]},
            'flags': {k: bool(result.get(k)) for k in ('median_at_cap', 'band_degenerate', 'at_mu_floor')}}


def _run_binned(spec, statistic):
    p = spec['parameter']
    results, failed = [], False
    for h in spec['hypotheses']:
        likelihood = counting.Likelihood(spec['channels'], h['signal'])
        scan, region = _region(likelihood, spec)
        tag = '' if h['id'] == 'nominal' else f' [{h["id"]}]'
        results.append(record.result('delta-nll-scan', 'diagnostic', hypothesis=h['id'], coordinates=h['coordinates'],
                                     parameter=p['name'], grid=scan['grid'], twice_nll=scan['twice_nll'],
                                     delta=scan['delta'],
                                     per_channel_at_best_fit=likelihood.per_channel({p['name']: scan['best_fit'][p['name']]})))
        best_point = {p['name']: scan['best_fit'][p['name']]}
        goodness = gof.evaluate(
            scan['best_fit']['twice_nll'], ndf=sum(c.bins for c in spec['channels']) - 1,
            toy=gof.counting_toy(likelihood, p['name'], spec['grid'], spec['domain'], best_point),
            request=spec['goodness_of_fit'], statistic='saturated -2 ln lambda at the best fit',
            data_description='observed')
        results.append({**goodness, 'hypothesis': h['id'], 'coordinates': h['coordinates']})
        if spec['test_statistic'] == 'discovery':
            results.append(record.result('significance', 'primary', hypothesis=h['id'], coordinates=h['coordinates'],
                                         **region, summary=f'significance {region["significance"]:.4g}{tag}'))
        else:
            ok = region['status'] in ('resolved', 'empty')
            failed |= not ok
            results.append(record.result(
                'delta-nll-region', 'primary', hypothesis=h['id'], coordinates=h['coordinates'], parameter=p['name'],
                test_statistic=spec['test_statistic'], dataset='observed', **region,
                summary=f'Delta(-2 ln L) <= {spec["threshold"]:g}{tag}: ' + intervals.describe(region, p['label'])
                        + f'; best fit {p["label"]} = {region["best_fit"][p["name"]]:.6g}'))
            if spec['expected']:
                _, expected = _region(_asimov(spec['channels'], h['signal']), spec)
                results.append(record.result(
                    'delta-nll-region', 'companion', hypothesis=h['id'], coordinates=h['coordinates'],
                    parameter=p['name'], test_statistic=spec['test_statistic'],
                    dataset='background-only Asimov', **expected,
                    summary=f'expected (background-only Asimov){tag}: ' + intervals.describe(expected, p['label'])))
        if spec['cls']:
            cls = _cls(spec, h['signal'], spec['channels'])
            summary = None
            if cls['status'] == 'computed' and cls['parameter_limit']['observed'] is not None:
                summary = (f'95% CLs upper limit{tag}: {p["label"]} < {cls["parameter_limit"]["observed"]:.6g} '
                           f'(expected {cls["parameter_limit"]["expected"][2]:.6g})') if math.isclose(spec['cls_level'], 0.05) else (
                           f'CLs upper limit at level {spec["cls_level"]:g}{tag}: {cls["parameter_limit"]["observed"]:.6g}')
            results.append(record.result('cls-limit', 'companion', hypothesis=h['id'], coordinates=h['coordinates'],
                                         parameter=p['name'], **cls, **({'summary': summary} if summary else {})))
    grid = {'kind': 'scan', 'parameter': p, 'values': spec['grid'], 'domain': list(spec['domain'])}
    return results, 'failed' if failed else 'passed', grid


def load(task, base):
    ctx, doc = common.context(task, base, MODE, goodness_of_fit=True)
    statistic = _statistic(doc)
    if statistic['kind'] == 'closed-form':
        if ctx.goodness_of_fit is not None:
            raise ValueError('a closed-form statistic has no fit; remove goodness_of_fit')
        spec = _load_closed(ctx, doc)
    else:
        spec = _load_binned(ctx, doc)
        spec['goodness_of_fit'] = ctx.goodness_of_fit
    return ctx, doc, statistic, spec


def inputs(task, base):
    return common.inputs(load(task, base)[0])


def run(task, base, output):
    ctx, doc, statistic, spec = load(task, base)
    assumptions = []
    if statistic['kind'] == 'closed-form':
        results, status, grid, program = _run_closed(spec, statistic)
        parameters = [{**g, 'label': g.get('label', g['name'])} for g in spec['grid'].parameters]
        definition = {'kind': 'closed-form', 'output': spec['output'], 'threshold': spec['threshold'],
                      'region': spec['region'],
                      'expressions': {n: e.source for n, e in [*program.definitions, *program.outputs]}}
        assumptions = program.requester_assumptions()
        engine = 'closed-form'
        limitations = ['The closed-form statistic is evaluated as written; its statistical meaning is the requester\'s.']
    else:
        results, status, grid = _run_binned(spec, statistic)
        parameters = [spec['parameter']]
        definition = {'kind': 'binned-profile', 'test_statistic': spec['test_statistic'],
                      'threshold': spec['threshold'], 'nuisance_form': spec['form'],
                      'background_floor': spec['floor'], 'channels': [c.name for c in spec['channels']],
                      'combination': 'sum of channel log-likelihoods (independent channels)',
                      'profiling': 'each bin nuisance profiled independently',
                      'signal': sorted({h['signal'].description for h in spec['hypotheses']})}
        engine = 'binned-profile'
        limitations = ['Channels are treated as statistically independent; bin nuisances are uncorrelated.',
                       'Delta(-2 ln L) thresholds are interpreted asymptotically unless toys are run separately.']
    inference = record.build(
        mode=MODE, engine=engine,
        statistic=record.statistic('prescribed', verbatim=statistic['verbatim'], definition=definition),
        parameters=parameters, results=results, grid=grid, inputs=ctx.inputs(), status=status,
        requester_assumptions=assumptions, limitations=limitations)
    return common.deliver(output, inference, review=ctx.review, scope='Requester-prescribed statistic as the primary result')
