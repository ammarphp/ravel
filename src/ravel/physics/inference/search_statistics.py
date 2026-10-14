"""Science mode ``search-statistics``: SR/CR/VR search statistics with pyhf.

Input document (``kind: search-statistics``) holds the fields of ``search.run``
(regions, backgrounds, signal_points, mc_statistics, systematics, data,
computations, asimov_source, cls_level, mc_adequacy, contours) plus
``statistic``:

- ``{"origin": "default"}``: 95% CLs results are primary, discovery significance
  is reported alongside;
- ``{"origin": "prescribed", "verbatim": "...", "primary": "discovery"}``: the
  requested significance is primary and CLs is alongside.

Region yields are ``{"values": [...], "sumw2": [...]}`` (lists or file
references) or a ``binned-values`` file reference that carries both. The
systematics registry can be inline or ``{"path": ...}``. ``contours`` takes
``x`` and ``y`` coordinate names and ``levels`` for
``expected_cls_at_nominal`` and/or ``expected_discovery_significance`` when the
signal points form a complete rectangular grid.
"""
from __future__ import annotations

from pathlib import Path

from copy import deepcopy

import numpy as np

from . import common, record, search

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
    body['systematics'] = _systematics(ctx, body.get('systematics'))
    search.SearchModel(body)  # full validation before approval
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
    if len(xs) * len(ys) != len(points) or len(xs) < 2 or len(ys) < 2:
        return [record.result('contour', 'diagnostic', status='not_rectangular',
                              reason='signal points do not form a complete rectangular grid')]
    grid = formula.grid({'axes': [{'name': x, 'unit': '', 'values': xs}, {'name': y, 'unit': '', 'values': ys}]})
    out = []
    for quantity, level in spec['levels'].items():
        z = np.full((len(xs), len(ys)), np.nan)
        for p in points:
            i, j = xs.index(p['coordinates'][x]), ys.index(p['coordinates'][y])
            if quantity == 'expected_cls_at_nominal' and 'cls_at_nominal' in p:
                z[i, j] = p['cls_at_nominal']['expected'][2]
            elif quantity == 'expected_discovery_significance' and 'discovery' in p:
                z[i, j] = p['discovery']['expected_significance']
        lines = contours.level_lines(grid, z, float(level), x=x, y=y)
        label = ('Expected CLs at nominal signal' if quantity == 'expected_cls_at_nominal'
                 else 'Expected discovery significance')
        out.append(record.result('contour', 'primary' if quantity == 'expected_cls_at_nominal' else 'companion',
                                 kind='level-set', quantity=quantity, level=float(level), x=x, y=y, grid=z,
                                 series=contours.series(lines, identifier=quantity, label=f'{label} = {float(level):g}'),
                                 summary=f'{label} = {float(level):g} contour: {len(lines)} line(s)'))
    return out


def run(task, base, output):
    ctx, statistic, body = load(task, base)
    raw = search.run(body, goodness_of_fit=ctx.goodness_of_fit)
    discovery_primary = statistic['origin'] == 'prescribed' and statistic['primary'] == 'discovery'
    results = []
    for p in raw['points']:
        tag = f' [{p["id"]}]'
        if 'discovery' in p:
            d = p['discovery']
            text = f'expected discovery significance {d["expected_significance"]:.3g}{tag}'
            if 'observed_significance' in d:
                text += f'; observed {d["observed_significance"]:.3g}'
            results.append(record.result('significance', 'primary' if discovery_primary else 'companion',
                                         hypothesis=p['id'], coordinates=p['coordinates'], **d, summary=text))
        if 'cls_at_nominal' in p:
            c = p['cls_at_nominal']
            results.append(record.result('cls-values', 'companion' if discovery_primary else 'primary',
                                         hypothesis=p['id'], coordinates=p['coordinates'], **c,
                                         summary=f'CLs at the nominal signal{tag}: expected median {c["expected"][2]:.3g}'
                                                 + (f', observed {c["observed"]:.3g}' if c['observed'] is not None else '')))
        if 'cls_limits' in p:
            c = p['cls_limits']
            text = (f'{1 - c["level"]:.0%} CL CLs upper limit on the signal strength{tag}: '
                    f'expected median {c["expected"]["values"][2]:.3g}')
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
    if raw['systematics'] is not None:
        results.append(record.result('systematics', 'diagnostic', registry=raw['systematics'],
                                     alternative_sample_comparison=raw.get('alternative_sample_comparison', {}),
                                     selfcheck=raw.get('systematics_selfcheck'),
                                     selfcheck_document='systematics_selfcheck.json'))
        Path(output).mkdir(parents=True, exist_ok=True)
        record.write(Path(output) / 'systematics_selfcheck.json', raw['systematics_selfcheck'])
    if statistic['origin'] == 'prescribed':
        st = record.statistic('prescribed', verbatim=statistic['verbatim'],
                              definition={'primary': statistic['primary'], 'cls_level': body['cls_level']})
    else:
        st = record.statistic('default', definition={'primary': 'CLs', 'test_statistic': 'qtilde',
                                                     'cls_level': body['cls_level']})
    coordinates = sorted({k for p in raw['points'] for k in p['coordinates']})
    limitations = ['Asymptotic formulae are used for CLs and significances.',
                   'Yields, MC moments and systematic sources are as supplied.']
    if raw['blinded_signal_regions']:
        limitations.append('Signal regions without data (' + ', '.join(raw['blinded_signal_regions'])
                           + ') use the background prediction; only expected quantities are reported there.')
    if raw['mc_adequacy_flags']:
        limitations.append(f'{len(raw["mc_adequacy_flags"])} MC-statistics adequacy flag(s) are listed in the record.')
    inference = record.build(
        mode=MODE, engine='pyhf-search', statistic=st,
        parameters=[{'name': 'mu', 'unit': '', 'label': 'Signal strength'}]
                   + [{'name': c, 'unit': '', 'label': c} for c in coordinates],
        results=results, inputs=ctx.inputs(), status=status,
        grid={'kind': 'points', 'points': [{'id': p['id'], **p['coordinates']} for p in raw['points']]},
        diagnostics={'data_mode': raw['data_mode'], 'injections': raw['injections'], 'regions': raw['regions'],
                     'asimov_source': body['asimov_source'], 'mc_statistics': body['mc_statistics']},
        limitations=limitations)
    return common.deliver(output, inference, review=ctx.review, scope='SR/CR/VR search statistics on supplied yields with pyhf')
