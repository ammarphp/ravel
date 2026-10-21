"""Science mode ``search-statistics``: SR/CR/VR search statistics with pyhf.

Input document (``kind: search-statistics``) holds the fields of ``search.run``
(regions, backgrounds, signal_points, mc_statistics, systematics, data,
computations, asimov_source, cls_level, mc_adequacy, contours) plus
``statistic``:

- ``{"origin": "default"}``: 95% CLs results are primary, discovery significance
  is reported alongside;
- ``{"origin": "prescribed", "verbatim": "...", "primary": "discovery"}``: the
  requested significance is primary and CLs is alongside.

``statistic.claim`` is ``local`` by default; ``global`` requests a scan-level
look-elsewhere diagnostic. The upcrossing trials factor applies to a scan over
one coordinate, ordered along it; ``independent_tests`` declares the premise
needed for a Sidak correction. ``statistics_choices`` maps detected situations
to ``{method, justification}``; each point receives only its detected choices.
Auditable statistics diagnostics and their qualification/hold labels accompany
the inference record; each CLs limit carries an uncertainty statement.

Region yields are ``{"values": [...], "sumw2": [...]}`` (lists or file
references) or a ``binned-values`` file reference that carries both. The
systematics registry can be inline or ``{"path": ...}``. ``contours`` takes
``x`` and ``y`` coordinate names and ``levels`` for
``expected_cls_at_nominal`` and/or ``expected_discovery_significance`` when the
signal points form a complete rectangular grid. Irregular grids use Delaunay
linear interpolation in declared coordinates without extrapolation. ``points.json``
is written even when a requested contour cannot be constructed.
"""
from __future__ import annotations

from pathlib import Path

from copy import deepcopy

import numpy as np

from . import common, record, search, situations

MODE = 'search-statistics'


def validate(task):
    common.validate(task)


def _yields(ctx, raw, label):
    if type(raw) is not dict:
        raise ValueError(label + ' yields must map regions to values')
    out = {}
    for region, row in raw.items():
        if type(row) is dict and 'path' in row:
            values, sumw2 = ctx.vector(row, f'{label} {region}', with_sumw2=True)
            out[region] = {'values': values.tolist(), **({'sumw2': sumw2.tolist()} if sumw2 is not None else {})}
        elif type(row) is dict:
            out[region] = {k: ctx.vector(v, f'{label} {region} {k}').tolist() for k, v in row.items()
                           if k in ('values', 'sumw2')}
            if set(row) - {'values', 'sumw2'}:
                raise ValueError(f'{label} yields in {region} have values and sumw2 only')
        else:
            raise ValueError(f'{label} yields in {region} must be an object')
    return out


def _systematics(ctx, raw):
    if raw is None:
        return None
    doc = ctx.json(ctx.path(raw['path'])) if type(raw) is dict and set(raw) == {'path'} else deepcopy(raw)
    for source in doc.get('sources', []):
        for key in ('alternative', 'alternative_up', 'alternative_down'):
            if type(source.get(key)) is dict:
                source[key] = {r: ctx.vector(v, f'{source.get("name")} {key} {r}').tolist()
                               for r, v in source[key].items()}
    return doc


def load(task, base):
    ctx, doc = common.context(task, base, MODE, goodness_of_fit=True)
    statistic = doc.get('statistic')
    if type(statistic) is not dict or statistic.get('origin') not in ('default', 'prescribed'):
        raise ValueError('statistic origin must be default or prescribed')
    if set(statistic) - {'origin', 'verbatim', 'primary', 'claim', 'independent_tests'}:
        raise ValueError('unsupported search statistic fields')
    if statistic.get('claim', 'local') not in ('local', 'global'):
        raise ValueError('statistic claim must be local or global')
    if type(statistic.get('independent_tests', False)) is not bool:
        raise ValueError('statistic independent_tests must be a boolean')
    if statistic['origin'] == 'prescribed':
        if type(statistic.get('verbatim')) is not str or not statistic['verbatim'].strip():
            raise ValueError('a prescribed statistic must be recorded verbatim')
        if statistic.get('primary') not in ('discovery', 'cls'):
            raise ValueError('a prescribed search statistic names primary: discovery or cls')
    body = {k: v for k, v in doc.items() if k not in ('schema_version', 'kind', 'statistic', 'description')}
    body['backgrounds'] = [{**b, 'yields': _yields(ctx, b.get('yields'), f'background {b.get("name")}')}
                           for b in body.get('backgrounds', [])]
    body['signal_points'] = [{**p, 'yields': _yields(ctx, p.get('yields'), f'signal point {p.get("id")}')}
                             for p in body.get('signal_points', [])]
    body['regions'] = [{**r, **({'observed': ctx.vector(r['observed'], f'observed in {r.get("name")}').tolist()}
                                if r.get('observed') is not None else {})} for r in body.get('regions', [])]
    for region in body['regions']:
        if region.get('role') == 'abcd':
            closure = region['abcd']['closure']
            for key in ('x_pass', 'y_pass'):
                closure[key] = ctx.vector(closure[key], 'abcd simulated closure ' + key).tolist()
    body['systematics'] = _systematics(ctx, body.get('systematics'))
    if 'background_covariance' in body:
        if statistic.get('primary') == 'discovery':
            raise ValueError('discovery is not supported with a background covariance')
        spec = body.get('contours') or {}
        if 'expected_discovery_significance' in (spec.get('levels') or {}):
            raise ValueError('discovery contours are not supported with a background covariance')
        if ctx.goodness_of_fit is not None:
            raise ValueError('goodness_of_fit is not supported with a background covariance')
    if body.get('reference_contour') is not None:
        ref = body['reference_contour']
        if type(ref) is not dict or set(ref) != {'path', 'sha256'}:
            raise ValueError('reference_contour needs a path and sha256 pin')
        path = ctx.path(ref['path'])
        reference = ctx.json(path)
        pin = next(p for p in ctx.inputs() if p['path'] == str(path))
        if pin['sha256'] != ref['sha256']:
            raise ValueError('reference contour source pin mismatch')
        spec = body.get('contours')
        if not spec or reference.get('kind') != 'plot-coordinate-series':
            raise ValueError('reference contour needs contours and a plot-coordinate-series document')
        if any(reference['axes'][a]['name'] != spec[a] for a in ('x', 'y')):
            raise ValueError('reference contour axes must match declared contour axes')
        rows = reference.get('series')
        if type(rows) is not list or not rows:
            raise ValueError('reference contour needs at least one coordinate series')
        for row in rows:
            if row.get('geometry') != 'polyline' or not row.get('label') or len(row.get('records', [])) < 2:
                raise ValueError('reference contour needs labelled polylines')
            for point in row['records']:
                if any(type(point.get(k)) not in (int, float) or not np.isfinite(point[k]) for k in ('x', 'y')):
                    raise ValueError('reference contour coordinates must be finite')
        body['reference_contour'] = {'series': rows, 'source_pin': pin}
    spec = body.get('contours')
    if spec:
        from . import contours
        if (type(spec) is not dict or set(spec) - {'x', 'y', 'levels', 'interpolation'}
                or not {'x', 'y', 'levels'} <= set(spec) or spec['x'] == spec['y']):
            raise ValueError('contours need distinct x/y axes, levels and optional interpolation')
        if type(spec['levels']) is not dict or not spec['levels']:
            raise ValueError('contour levels must be a nonempty quantity map')
        for quantity, level in spec['levels'].items():
            if quantity not in ('expected_cls_at_nominal', 'expected_discovery_significance'):
                raise ValueError('unsupported contour quantity ' + quantity)
            if type(level) not in (int, float) or not np.isfinite(level):
                raise ValueError('contour levels must be finite')
        try:
            xy = contours.interpolation_coordinates(spec, body['signal_points'])
            axes = np.asarray([[p['coordinates'][spec['x']], p['coordinates'][spec['y']]]
                               for p in body['signal_points']], float)
        except KeyError as exc:
            raise ValueError('a declared contour coordinate is missing') from exc
        if not np.all(np.isfinite(xy)) or not np.all(np.isfinite(axes)):
            raise ValueError('contour coordinates must be finite')
    model = search.SearchModel(body)  # full validation before approval
    choices = body.get('statistics_choices', {})
    if type(choices) is not dict:
        raise ValueError('statistics_choices must be an object keyed by situation')
    if any(type(row) is not dict for row in choices.values()):
        raise ValueError('statistics_choices entries need a method and nonblank justification')
    if choices:
        detected = set()
        # The unconditional points table also computes discovery for pyhf models.
        model.document['computations']['discovery'] = 'background_covariance' not in body
        for point in model.points:
            if model.background_covariance is not None:
                facts = model.simplified_statistics_facts(point)
            else:
                pyhf, engine = search._pyhf()
                spec = model.workspace(point)
                likelihood = pyhf.Model(spec, poi_name=search.POI, modifier_settings=engine.MODIFIER_SETTINGS)
                pars = np.asarray(likelihood.config.suggested_init(), float)
                pars[likelihood.config.poi_index] = 0.0
                facts = model.statistics_facts(likelihood, model._data_for(likelihood, pars))
            assessment = situations.assess(facts)
            present = {r['situation'] for r in assessment['situations']}
            detected |= present
            situations.decide(assessment, {k: v for k, v in choices.items() if k in present})
        if model.document['computations'].get('discovery') and len(model.points) >= 2:
            assessment = situations.assess(_scan_facts(statistic, model.points))
            detected.add('look-elsewhere')
            situations.decide(assessment, {k: v for k, v in choices.items() if k == 'look-elsewhere'})
        unknown = set(choices) - detected
        if unknown:
            raise ValueError('statistics_choices name situations not detected: ' + ', '.join(sorted(unknown)))
    return ctx, statistic, body


def inputs(task, base):
    return common.inputs(load(task, base)[0])


def _contours(body, points):
    spec = body.get('contours')
    if not spec:
        return []
    from . import contours, formula
    x, y = spec['x'], spec['y']
    xs = sorted({p['coordinates'][x] for p in points})
    ys = sorted({p['coordinates'][y] for p in points})
    rectangular = (len(xs) * len(ys) == len(points) and len(xs) >= 2 and len(ys) >= 2
                   and len({(p['coordinates'][x], p['coordinates'][y]) for p in points}) == len(points))
    irregular = not rectangular or spec.get('interpolation') is not None
    grid = None if irregular else formula.grid({'axes': [{'name': x, 'unit': '', 'values': xs},
                                                       {'name': y, 'unit': '', 'values': ys}]})
    out = []
    for quantity, level in spec['levels'].items():
        z = None if irregular else np.full((len(xs), len(ys)), np.nan)
        values = []
        for p in points:
            value = np.nan
            if quantity == 'expected_cls_at_nominal' and 'cls_at_nominal' in p:
                value = p['cls_at_nominal']['expected'][2]
            elif quantity == 'expected_discovery_significance' and 'discovery' in p:
                value = p['discovery']['expected_significance']
            values.append(value)
            if z is not None:
                i, j = xs.index(p['coordinates'][x]), ys.index(p['coordinates'][y])
                z[i, j] = value
        extra = {}
        try:
            if not np.all(np.isfinite(values)):
                raise ValueError('requested contour quantity is unavailable at one or more points')
            if irregular:
                xy = contours.interpolation_coordinates(spec, points)
                lines, triangulation = contours.irregular_lines(xy, values, float(level))
                original = np.asarray([[p['coordinates'][x], p['coordinates'][y]] for p in points], float)
                affine, _, _, _ = np.linalg.lstsq(np.c_[xy, np.ones(len(xy))], original, rcond=None)
                if not np.allclose(np.c_[xy, np.ones(len(xy))] @ affine, original, rtol=1e-10, atol=1e-10):
                    raise ValueError('interpolation coordinates must preserve the declared axes by an invertible affine map')
                lines = [np.c_[line, np.ones(len(line))] @ affine for line in lines]
                extra = {'status': 'interpolated', 'interpolation': spec.get('interpolation') or
                         {'method': 'delaunay-linear', 'coordinates': [x, y]},
                         'triangulation': {**triangulation, 'point_ids': [p['id'] for p in points]}}
            else:
                lines = contours.level_lines(grid, z, float(level), x=x, y=y)
        except ValueError as exc:
            out.append(record.result('contour', 'diagnostic', quantity_name=quantity,
                                     status='not_interpolable', reason=str(exc)))
            continue
        label = ('Expected CLs at nominal signal' if quantity == 'expected_cls_at_nominal'
                 else 'Expected discovery significance')
        if irregular:
            label += ' (interpolated)'
        out.append(record.result('contour', 'primary' if quantity == 'expected_cls_at_nominal' else 'companion',
                                 kind='level-set', quantity_name=quantity, level=float(level), x=x, y=y,
                                 grid=None if irregular else z, values=values,
                                 points=[{'id': p['id'], 'x': p['coordinates'][x], 'y': p['coordinates'][y]}
                                         for p in points], **extra,
                                 reference_contour=body.get('reference_contour'),
                                 series=contours.series(lines, identifier=quantity, label=f'{label} = {float(level):g}'),
                                 summary=f'{label} = {float(level):g} contour: {len(lines)} line(s)'))
    return out


def _coordinates(points):
    return sorted({k for p in points for k in (p.get('coordinates') or {})})


def _scan_facts(statistic, points):
    scan = {'hypotheses': len(points), 'claim': statistic.get('claim', 'local'),
            'independent_tests': statistic.get('independent_tests', False)}
    if _coordinates(points):
        scan['dimensions'] = len(_coordinates(points))
    return situations.make_facts(deliverables=['discovery'], scan=scan)


def _scan_statistics(statistic, points, choices):
    from . import lee
    from scipy.stats import norm
    names = _coordinates(points)
    if len(names) == 1:
        # Upcrossings are counted along the scanned coordinate, not in document order.
        points = sorted(points, key=lambda p: p['coordinates'][names[0]])
    values = [p['discovery'].get('observed_q0', p['discovery']['expected_q0']) for p in points]

    def run(situation, method, evidence):
        if method == 'trials-factor':
            return {'look_elsewhere': lee.global_significance(values, reference_level=0.5)}
        if method == 'sidak-correction':
            return {'look_elsewhere': lee.sidak(min(float(norm.sf(np.sqrt(max(q, 0.0)))) for q in values), len(values))}
        return {}

    return situations.drive(_scan_facts(statistic, points), run,
                            choices={k: v for k, v in choices.items() if k == 'look-elsewhere'})


def _statistics_result(block, hypothesis):
    return record.result('statistics', 'diagnostic', hypothesis=hypothesis,
                         outcome=block['validity']['outcome'], labels=situations.labels(block), record=block)


def run(task, base, output):
    ctx, statistic, body = load(task, base)
    execution = deepcopy(body)
    # The table is an unconditional deliverable, independent of which scalar
    # summaries were requested. Limit scans remain opt-in.
    covariance = 'background_covariance' in body
    execution['computations'].update(discovery=not covariance, cls_at_nominal=True)
    Path(output).mkdir(parents=True, exist_ok=True)
    raw = search.run(execution, goodness_of_fit=ctx.goodness_of_fit,
                     construction_folder=Path(output) / 'model_construction')
    statement = ('The fit uses simulated pseudo-data.' if raw['data_mode'] == 'mc-pseudo-data'
                 else 'The fit uses supplied observed data; blinded regions report expected quantities only.')
    table = {'schema_version': 1, 'kind': 'search-statistics-points', 'data_mode': raw['data_mode'],
             'statement': statement, 'inputs': ctx.inputs(), 'abcd': raw['abcd'], 'points': []}
    signal_regions = {r['name'] for r in body['regions'] if r['role'] in ('SR', 'abcd')}
    for p in raw['points']:
        c, d = p.get('cls_at_nominal', {}), p.get('discovery', {})
        table['points'].append({**p, 'expected_cls_at_nominal': (c.get('expected') or [None]*5)[2],
                                'observed_cls_at_nominal': c.get('observed'),
                                'observed_on_pseudo_data_cls_at_nominal': c.get('observed_on_pseudo_data'),
                                'asimov_discovery_significance': d.get('expected_significance'),
                                'signal_yield': sum(sum(v) for r, v in p['signal_yields'].items() if r in signal_regions),
                                'inputs': ctx.inputs()})
    table_pin = record.write(Path(output) / 'points.json', table)
    discovery_primary = statistic['origin'] == 'prescribed' and statistic['primary'] == 'discovery'
    results = []
    for p in raw['points']:
        tag = f' [{p["id"]}]'
        if 'discovery' in p and body['computations'].get('discovery'):
            d = p['discovery']
            text = f'expected discovery significance {d["expected_significance"]:.3g}{tag}'
            if 'observed_significance' in d:
                text += f'; observed {d["observed_significance"]:.3g}'
            if 'toys' in d:
                toy = d['toys']['expected']
                text += f'; conditional toy p-value {toy["p_value"]:.3g} ± {toy["p_value_mc_uncertainty"]:.2g}'
            results.append(record.result('significance', 'primary' if discovery_primary else 'companion',
                                         hypothesis=p['id'], coordinates=p['coordinates'], **d, summary=text))
        if 'cls_at_nominal' in p and body['computations'].get('cls_at_nominal'):
            c = p['cls_at_nominal']
            results.append(record.result('cls-values', 'companion' if discovery_primary else 'primary',
                                         hypothesis=p['id'], coordinates=p['coordinates'], **c,
                                         summary=f'CLs at the nominal signal{tag}: expected median {c["expected"][2]:.3g}'
                                                 + (f', observed {c["observed"]:.3g}' if c['observed'] is not None else '')))
        if 'cls_limits' in p:
            c = p['cls_limits']
            calculator = 'toy-based CLs' if (c.get('calculator') or {}).get('applied') == 'toybased' else 'asymptotic CLs'
            text = (f'{1 - c["level"]:.0%} CL CLs upper limit on the signal strength{tag}: '
                    f'expected median {c["expected"]["values"][2]:.3g} ({calculator})')
            if c['observed'] is not None:
                text += f', observed {c["observed"]["value"]:.3g}'
            results.append(record.result('cls-limit', 'companion' if discovery_primary else 'primary',
                                         hypothesis=p['id'], coordinates=p['coordinates'], **c, summary=text))
    results += _contours(body, raw['points'])
    status = 'passed'
    if 'background_only_fit' in raw:
        fit = raw['background_only_fit']
        results.append(record.result('fitted-parameters', 'diagnostic', fit='background-only (control regions)',
                                     status=fit['status'], parameters=fit['parameters'],
                                     correlation=fit['correlation'], parameter_order=fit['parameter_order'],
                                     edm=fit['edm'], minimizer=fit['minimizer'], fit_channels=fit['fit_channels']))
        results.append(record.result('post-fit-predictions', 'diagnostic', regions=fit['region_predictions']))
        results.append(fit['goodness_of_fit'])
        if fit['status'] != 'converged':
            status = 'failed'
    results.append(record.result('mc-adequacy', 'diagnostic', flags=raw['mc_adequacy_flags'],
                                 thresholds=body['mc_adequacy']))
    if raw['abcd']:
        results.append(record.result('applicability', 'diagnostic', method='ABCD external estimate',
                                     estimates=raw['abcd'],
                                     status='flagged' if any(a['closure']['status'] == 'flagged' for a in raw['abcd']) else 'passed'))
    if 'model_construction' in raw:
        construction = raw['model_construction']
        statuses = sorted({r['status'] for r in construction['records']})
        results.append(record.result('model-construction', 'diagnostic', builder=construction['builder'],
                                     parity_statuses=statuses, records=construction['records'],
                                     summary=f'model built with {construction["builder"]}; builder parity: ' + ', '.join(statuses)))
    if raw['systematics'] is not None:
        results.append(record.result('systematics', 'diagnostic', registry=raw['systematics'],
                                     alternative_sample_comparison=raw.get('alternative_sample_comparison', {}),
                                     selfcheck=raw.get('systematics_selfcheck'),
                                     selfcheck_document='systematics_selfcheck.json'))
        Path(output).mkdir(parents=True, exist_ok=True)
        record.write(Path(output) / 'systematics_selfcheck.json', raw['systematics_selfcheck'])
    results += [_statistics_result(p['statistics'], p['id']) for p in raw['points'] if 'statistics' in p]
    discovery_points = [p for p in raw['points'] if 'discovery' in p]
    if len(discovery_points) >= 2:
        results.append(_statistics_result(_scan_statistics(
            statistic, discovery_points, body.get('statistics_choices', {})), None))
    scan_definition = {k: statistic[k] for k in ('claim', 'independent_tests') if k in statistic}
    if statistic['origin'] == 'prescribed':
        st = record.statistic('prescribed', verbatim=statistic['verbatim'],
                              definition={'primary': statistic['primary'], 'cls_level': body['cls_level'],
                                          **scan_definition})
    else:
        st = record.statistic('default', definition={'primary': 'CLs', 'test_statistic': 'qtilde',
                                                     'cls_level': body['cls_level'], **scan_definition})
    coordinates = sorted({k for p in raw['points'] for k in p['coordinates']})
    limitations = ['CLs and Asimov significances use asymptotic formulae; requested discovery toys are conditional null ensembles.',
                   'Yields, MC moments and systematic sources are as supplied.']
    if covariance:
        limitations.append('Background uncertainties enter through the supplied covariance only; signal MC statistics and control regions are not represented.')
    calibrated = [p['cls_limits']['calculator']['toys'] for p in raw['points']
                  if p.get('cls_limits', {}).get('calculator', {}).get('applied') == 'toybased']
    if calibrated:
        options = sorted({(t['ntoys'], t['seed']) for t in calibrated})
        configuration = '; '.join(f'{n} toys, seed {seed}' for n, seed in options)
        limitations[0] = (f'CLs limits use toy-based calibration ({configuration}) at the recorded points; '
                          'finite-toy crossing MC intervals are recorded; coverage is not validated. '
                          'CLs values at nominal signal and Asimov significances use asymptotic formulae; '
                          'requested discovery toys are conditional null ensembles.')
        if len(calibrated) < sum('cls_limits' in p for p in raw['points']):
            limitations[0] += ' Other CLs limits use the recorded asymptotic calculator.'
    if raw['abcd']:
        limitations.append('ABCD uses independent supplied sideband estimates with a delta-method lognormal constraint; '
                           'this is not a simultaneous sideband Poisson fit or a coverage validation.')
    if raw['data_mode'] == 'mc-pseudo-data':
        limitations.append(statement + ' Observed-on-pseudo-data values are not experimental observations.')
    if raw['blinded_signal_regions']:
        limitations.append('Signal regions without data (' + ', '.join(raw['blinded_signal_regions'])
                           + ') use the background prediction; only expected quantities are reported there.')
    if raw['mc_adequacy_flags']:
        limitations.append(f'{len(raw["mc_adequacy_flags"])} MC-statistics adequacy flag(s) are listed in the record.')
    engine = 'spey-simplified-likelihood' if covariance else 'pyhf-search'
    if 'model_construction' in raw:
        from .model_construction import CABINETRY_VERSION
        engine = 'pyhf-search/' + raw['model_construction']['builder']
        limitations.append(f'The HistFactory model was built by the {raw["model_construction"]["builder"]} builder '
                           f'(cabinetry {CABINETRY_VERSION} and the native builder both ran); the parity record states '
                           'where the two representations agree exactly and where they agree only at the one-sigma '
                           'template points.')
    for row in results:
        if row['quantity'] == 'statistics':
            for label in row['labels']:
                if label not in limitations:
                    limitations.append(label)
    inference = record.build(
        mode=MODE, engine=engine, statistic=st,
        parameters=[{'name': 'mu', 'unit': '', 'label': 'Signal strength'}]
                   + [{'name': c, 'unit': '', 'label': c.replace('_', ' ')} for c in coordinates],
        results=results, inputs=ctx.inputs(), status=status,
        grid={'kind': 'points', 'points': [{'id': p['id'], **p['coordinates']} for p in raw['points']]},
        diagnostics={'data_mode': raw['data_mode'], 'injections': raw['injections'], 'regions': raw['regions'],
                     'data_statement': statement, 'points_table': {'path': 'points.json', 'sha256': table_pin['sha256']},
                     'points': table['points'], 'abcd': raw['abcd'],
                     'asimov_source': body['asimov_source'], 'mc_statistics': body['mc_statistics']},
        limitations=limitations)
    delivered = common.deliver(output, inference, review=ctx.review,
                              scope=('SR search statistics on supplied yields with a background covariance' if covariance
                                     else 'SR/CR/VR search statistics on supplied yields with pyhf'))
    delivered.update(points='points.json', points_sha256=table_pin['sha256'], data_statement=statement)
    return delivered
