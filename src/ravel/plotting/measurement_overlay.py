"""Measurement overlays: data with full uncertainties, predictions, ratio and the official figure.

A specification declares:

- ``axes``: x and y (natural-language label, unit, linear or log scale) and the ratio label;
- ``data``: a binned source (HEPData table, binned_values result, inline or file series)
  drawn as points with total and, when supplied, statistical uncertainties;
- ``predictions``: binned sources drawn as lines with their uncertainty bands. A prediction
  with ``delta_from`` holds a signed difference from another prediction (for example
  signal-background interference) and is drawn as the total; negative differences are kept
  and listed, never clipped;
- ``ratio``: the denominator (a prediction name or ``data``) for the ratio panel;
- ``difference_panel``: an optional panel with the signed difference of each prediction
  from the denominator on a linear axis;
- ``official``: the published figure's series (digitised or HEPData) drawn on the same axes;
- ``side_by_side``: an extra figure with the published series and this result in two panels
  with identical axes;
- ``comparison``: a saved comparison object (``path``) or a comparison computed here between a
  prediction and ``data`` or ``official`` (``agent``, ``reference``, ``tolerances``,
  ``systematics``). Its summary is shown on the figure and stored in the receipt.

Each source may carry ``transformations`` (the declared operations of ``reference_metrics``).
Bins must match the data exactly. Every label is checked for natural language and every
figure passes the house plot lint.
"""
from pathlib import Path
import argparse
import json
import sys

import numpy as np

from . import reference_metrics as rm
from .figure_io import (axis_title, code_identity, load_spec, natural_label, new_output_dir, pin, resolve,
                        save_figure, scale_of, write_new_json)

DATA_COLOUR = '#000000'
PREDICTION_COLOURS = ('#0072B2', '#D55E00', '#009E73', '#CC79A7', '#E69F00', '#56B4E9')
OFFICIAL_COLOUR = '#7f7f7f'


def _load_binned(entry, base, recorder, what, context=None):
    if not isinstance(entry, dict) or 'source' not in entry:
        raise ValueError(f'{what} needs a source')
    series = rm.load_source(entry['source'], base, context, recorder=recorder)
    if 'edges' not in series:
        raise ValueError(f'{what} must be a binned series')
    series, records = rm.transform(series, entry.get('transformations'))
    return series, records


def _same_bins(series, edges, what):
    if len(series['edges']) != len(edges) or not np.allclose(series['edges'], edges, rtol=rm.EDGE_RTOL, atol=1e-12):
        raise ValueError(f'{what} bins differ from the data bins; declare a rebin transformation')


def _errors(series):
    n = len(series['values'])
    if 'error_low' in series:
        return np.array(series['error_low']), np.array(series['error_high'])
    if 'errors' in series:
        e = np.array(series['errors'])
        return e, e
    if 'covariance' in series:
        e = np.sqrt(np.diag(np.array(series['covariance'])))
        return e, e
    return np.zeros(n), np.zeros(n)


def _steps(edges, values):
    return np.asarray(edges), np.append(values, values[-1])


def _load_inputs(spec, base, recorder, context=None):
    data_entry = spec.get('data')
    data, data_ops = _load_binned(data_entry, base, recorder, 'data', context)
    data_label = natural_label(data_entry.get('label', 'Data'), 'data label')
    edges = np.array(data['edges'])
    preds, order = {}, []
    for entry in spec.get('predictions') or []:
        name = entry.get('name')
        if not isinstance(name, str) or not name or name in preds or name in ('data', 'official'):
            raise ValueError('each prediction needs a unique name other than data or official')
        label = natural_label(entry.get('label', ''), f'prediction {name} label')
        series, ops = _load_binned(entry, base, recorder, f'prediction {name}', context)
        _same_bins(series, edges, f'prediction {name}')
        if (series['quantity'], series['unit']) != (data['quantity'], data['unit']):
            raise ValueError(f'prediction {name} is {series["quantity"]} in {series["unit"]!r} but the data are '
                             f'{data["quantity"]} in {data["unit"]!r}; declare the transformation')
        values = np.array(series['values'])
        lo, hi = _errors(series)
        record = {'label': label, 'transformations': ops}
        if 'delta_from' in entry:
            parent = entry['delta_from']
            if parent not in preds:
                raise ValueError(f'prediction {name} is a difference from {parent!r}, which must be declared first')
            record['delta'] = values.tolist()
            record['negative_delta_bins'] = [int(i) for i in np.nonzero(values < 0)[0]]
            record['delta_from'] = parent
            values = preds[parent]['array'] + values
            lo = np.hypot(lo, preds[parent]['err'][0])
            hi = np.hypot(hi, preds[parent]['err'][1])
        record.update({'values': values.tolist(), 'array': values, 'err': (lo, hi)})
        preds[name] = record
        order.append(name)
    if not order:
        raise ValueError('declare at least one prediction')
    return data, data_ops, data_label, edges, preds, order


def _official(spec, base, recorder, context=None):
    entry = spec.get('official')
    if entry is None:
        return None
    label = natural_label(entry.get('label', ''), 'official label')
    source = rm.load_source(entry.get('source'), base, context, recorder=recorder)
    if 'edges' in source:
        source, ops = rm.transform(source, entry.get('transformations'))
        edges = np.array(source['edges'])
        lo, hi = _errors(source)
        return {'label': label, 'kind': 'binned', 'series': source, 'transformations': ops,
                'x': ((edges[1:] + edges[:-1]) / 2).tolist(), 'y': source['values'],
                'xerr': (np.diff(edges) / 2).tolist(), 'err': (lo.tolist(), hi.tolist())}
    if 'x' in source and 'y' in source:
        u = source.get('y_uncertainty') or [0.0] * len(source['x'])
        return {'label': label, 'kind': 'curve', 'series': source, 'x': source['x'], 'y': source['y'],
                'err': (u, u)}
    raise ValueError('the official source must be a binned series or a curve')


def _comparison(spec, base, recorder, data, preds, official, context=None):
    rule = spec.get('comparison')
    if rule is None:
        return None
    if 'path' in rule or 'operation' in rule:
        if 'operation' in rule:
            if not context or rule['operation'] not in context:
                raise ValueError(f'unknown operation {rule["operation"]!r}')
            doc = context[rule['operation']]
        else:
            doc = recorder.read(resolve(base, rule['path']))
        if not isinstance(doc, dict) or doc.get('kind') != 'reference-comparison':
            raise ValueError('the comparison file must be a reference-comparison object')
        if not doc.get('summary'):
            doc['summary'] = rm.summary_lines(doc)
        return doc
    agent_name, ref_name = rule.get('agent'), rule.get('reference', 'data')
    if agent_name not in preds:
        raise ValueError(f'comparison agent {agent_name!r} is not a declared prediction')
    p = preds[agent_name]
    lo, hi = p['err']
    agent = rm.binned(data['edges'], p['values'], error_low=lo.tolist(), error_high=hi.tolist(),
                      quantity=data['quantity'], unit=data['unit'])
    if ref_name == 'data':
        reference = data
    elif ref_name == 'official' and official and official['kind'] == 'binned':
        reference = official['series']
    else:
        raise ValueError('a comparison reference must be data or a binned official series')
    result = rm.compare_binned(agent, reference, rule.get('tolerances'), systematics=rule.get('systematics'))
    result.update({'schema_version': 1, 'kind': 'reference-comparison', 'comparison_kind': 'binned',
                   'agent': p['label'], 'reference': 'data' if ref_name == 'data' else official['label'],
                   'machine_review_only': True})
    result['summary'] = rm.summary_lines(result)
    return result


def _draw_main(ax, edges, data, data_label, preds, order, official, logy, handles):
    from matplotlib.lines import Line2D
    centres = (edges[1:] + edges[:-1]) / 2
    half = np.diff(edges) / 2
    for i, name in enumerate(order):
        p = preds[name]
        colour = PREDICTION_COLOURS[i % len(PREDICTION_COLOURS)]
        if logy and np.any(p['array'] <= 0):
            bad = [int(j) for j in np.nonzero(p['array'] <= 0)[0]]
            raise ValueError(f'prediction {p["label"]!r} is not positive in bins {bad}; a logarithmic y axis '
                             'cannot show it, use a linear axis or the difference panel')
        x, y = _steps(edges, p['array'])
        ax.step(x, y, where='post', color=colour, lw=2, ls='-' if 'delta_from' not in p else '--', zorder=3)
        lo, hi = p['err']
        if np.any(lo > 0) or np.any(hi > 0):
            low = p['array'] - lo
            if logy:
                low = np.maximum(low, p['array'] * 1e-3)
            ax.fill_between(x, np.append(low, low[-1]), np.append(p['array'] + hi, (p['array'] + hi)[-1]),
                            step='post', color=colour, alpha=0.25, lw=0, zorder=2)
        handles.append((Line2D([], [], color=colour, lw=2, ls='-' if 'delta_from' not in p else '--'), p['label']))
    if official is not None:
        if official['kind'] == 'binned':
            ax.errorbar(official['x'], official['y'], xerr=official['xerr'], yerr=official['err'], fmt='s',
                        mfc='none', color=OFFICIAL_COLOUR, ms=6, zorder=4)
            handles.append((Line2D([], [], color=OFFICIAL_COLOUR, marker='s', mfc='none', ls=''), official['label']))
        else:
            ax.plot(official['x'], official['y'], ':', color=OFFICIAL_COLOUR, lw=2.4, zorder=4)
            handles.append((Line2D([], [], color=OFFICIAL_COLOUR, ls=':', lw=2.4), official['label']))
    lo, hi = _errors(data)
    values = np.array(data['values'])
    ax.errorbar(centres, values, xerr=half, yerr=[lo, hi], fmt='o', color=DATA_COLOUR, ms=5, capsize=0,
                zorder=5)
    if 'stat_errors' in data:
        stat = np.array(data['stat_errors'])
        ax.errorbar(centres, values, yerr=stat, fmt='none', ecolor=DATA_COLOUR, capsize=4, lw=0, capthick=1.5,
                    zorder=5)
        data_label_full = data_label + ' (caps: statistical)'
    else:
        data_label_full = data_label
    handles.insert(0, (Line2D([], [], color=DATA_COLOUR, marker='o', ls=''), data_label_full))
    return {'values': values.tolist(), 'error_low': lo.tolist(), 'error_high': hi.tolist()}


def _wrap(text, width=18):
    """Break a long panel label over lines so it fits a short panel."""
    import textwrap
    return '\n'.join(textwrap.wrap(text, width)) if '$' not in text else text


def _ratio_values(denominator, numerator):
    with np.errstate(divide='ignore', invalid='ignore'):
        r = numerator / denominator
    return [float(v) if np.isfinite(v) else None for v in r]


def _legend(ax, handles, title_lines):
    title = '\n'.join(title_lines) if title_lines else None
    legend = ax.legend([h for h, _ in handles], [l for _, l in handles], loc='upper left',
                       bbox_to_anchor=(1.02, 1.0), borderaxespad=0.0, fontsize=10, title=title,
                       title_fontsize=10, frameon=False, alignment='left')
    legend.set_zorder(10)


def _overlay_figure(spec, axes, edges, data, data_label, preds, order, official, comparison):
    import matplotlib.pyplot as plt
    from . import mplhep_style as house
    logy = axes['y']['scale'] == 'log'
    want_diff = bool(spec.get('difference_panel'))
    ratios = [3, 1.2] + ([1.2] if want_diff else [])
    fig, axs = plt.subplots(len(ratios), 1, figsize=(10.5, 7.5 + (1.6 if want_diff else 0)), sharex=True,
                            gridspec_kw={'height_ratios': ratios, 'hspace': 0.06}, layout='constrained')
    ax, axr = axs[0], axs[1]
    handles = []
    drawn = _draw_main(ax, edges, data, data_label, preds, order, official, logy, handles)
    denominator = (spec.get('ratio') or {}).get('denominator', order[0])
    if denominator == 'data':
        den = np.array(data['values'])
    elif denominator in preds:
        den = preds[denominator]['array']
    else:
        raise ValueError(f'ratio denominator {denominator!r} is not data or a declared prediction')
    ratio = {}
    centres = (edges[1:] + edges[:-1]) / 2
    for i, name in enumerate(order):
        r = _ratio_values(den, preds[name]['array'])
        ratio[name] = r
        x, y = _steps(edges, np.array([v if v is not None else np.nan for v in r]))
        axr.step(x, y, where='post', color=PREDICTION_COLOURS[i % len(PREDICTION_COLOURS)], lw=2,
                 ls='-' if 'delta_from' not in preds[name] else '--')
    dlo, dhi = _errors(data)
    ratio['data'] = _ratio_values(den, np.array(data['values']))
    with np.errstate(divide='ignore', invalid='ignore'):
        axr.errorbar(centres, ratio['data'], xerr=np.diff(edges) / 2, yerr=[dlo / den, dhi / den], fmt='o',
                     color=DATA_COLOUR, ms=4)
    axr.axhline(1.0, color='0.4', lw=1, ls=':')
    rng = (axes.get('ratio') or {}).get('range')
    if rng:
        axr.set_ylim(*rng)
    axr.set_ylabel(_wrap(axes['ratio_title']), fontsize=12)
    difference = None
    if want_diff:
        axd = axs[2]
        difference = {}
        for i, name in enumerate(order):
            if name == denominator:
                continue
            d = preds[name]['array'] - den
            difference[name] = d.tolist()
            x, y = _steps(edges, d)
            axd.step(x, y, where='post', color=PREDICTION_COLOURS[i % len(PREDICTION_COLOURS)], lw=2,
                     ls='-' if 'delta_from' not in preds[name] else '--')
        axd.axhline(0.0, color='0.4', lw=1, ls=':')
        unit = data['unit'] if data['unit'] not in ('', '1') else ''
        axd.set_ylabel(_wrap(axes['difference_title']) + (f'\n[{unit}]' if unit else ''), fontsize=12)
        house.tick_hygiene(axd)
        house.publication_axes(axd)
        bottom = axd
    else:
        bottom = axr
    ax.set_yscale(axes['y']['scale'])
    ax.set_xscale(axes['x']['scale'])
    ax.set_xlim(edges[0], edges[-1])
    ax.set_ylabel(axes['y']['title'])
    bottom.set_xlabel(axes['x']['title'])
    house.tick_hygiene(ax, axr=axr, logy=logy, logx=axes['x']['scale'] == 'log')
    for a in axs:
        house.publication_axes(a)
    for a in axs[:-1]:
        for lab in a.get_xticklabels():
            lab.set_visible(False)
    fig.align_ylabels(list(axs))
    title = [natural_label(t, 'annotation') for t in spec.get('annotation') or []]
    if comparison is not None:
        title.append('Comparison: ' + comparison.get('agent', 'this result') + ' versus '
                     + comparison.get('reference', 'the reference'))
        title.extend('  ' + natural_label(t, 'comparison summary') for t in comparison['summary'])
    _legend(ax, handles, title)
    return fig, {'data': drawn, 'ratio': ratio, 'difference': difference, 'legend': [l for _, l in handles],
                 'ratio_denominator': denominator}


def _side_by_side(axes, edges, data, data_label, preds, order, official):
    import matplotlib.pyplot as plt
    from . import mplhep_style as house
    if official is None:
        raise ValueError('a side-by-side figure needs the official series')
    logy = axes['y']['scale'] == 'log'
    fig, (left, right) = plt.subplots(1, 2, figsize=(16, 6.2), sharey=True, layout='constrained')
    handles = []
    _draw_main(left, edges, data, data_label, {}, [], official, logy, handles)
    _legend(left, handles, ['Published figure'])
    handles = []
    _draw_main(right, edges, data, data_label, preds, order, None, logy, handles)
    _legend(right, handles, ['This result'])
    for a in (left, right):
        a.set_yscale(axes['y']['scale'])
        a.set_xscale(axes['x']['scale'])
        a.set_xlim(edges[0], edges[-1])
        a.set_xlabel(axes['x']['title'])
        house.tick_hygiene(a, logy=logy, logx=axes['x']['scale'] == 'log')
        house.publication_axes(a)
    left.set_ylabel(axes['y']['title'])
    return fig


def run_spec(spec_path, out_dir, context=None):
    """Render the declared measurement overlay; write NAME.pdf/png, optional side-by-side and NAME.json."""
    import matplotlib.pyplot as plt
    from . import mplhep_style as house
    spec, base = load_spec(spec_path)
    allowed = {'schema_version', 'name', 'axes', 'data', 'predictions', 'ratio', 'difference_panel', 'official',
               'side_by_side', 'comparison', 'annotation', 'description'}
    if set(spec) - allowed:
        raise ValueError(f'unknown measurement-overlay fields: {sorted(set(spec) - allowed)}')
    name = spec.get('name') or Path(spec_path).stem
    if not isinstance(name, str) or not name.replace('-', '').replace('_', '').isalnum():
        raise ValueError('figure name must be letters, digits, hyphens or underscores')
    raw_axes = spec.get('axes') or {}
    axes = {}
    for k in ('x', 'y'):
        if k not in raw_axes:
            raise ValueError('declare x and y axes')
        axes[k] = {'title': axis_title(raw_axes[k], f'{k} axis'), 'scale': scale_of(raw_axes[k], f'{k} axis')}
    axes['ratio'] = raw_axes.get('ratio') or {}
    axes['ratio_title'] = natural_label(axes['ratio'].get('label', 'Ratio to prediction'), 'ratio label')
    axes['difference_title'] = natural_label((raw_axes.get('difference') or {}).get('label', 'Difference'),
                                             'difference label')
    recorder = rm._Recorder()
    recorder.pins[str(Path(spec_path).absolute())] = pin(spec_path)
    data, data_ops, data_label, edges, preds, order = _load_inputs(spec, base, recorder, context)
    official = _official(spec, base, recorder, context)
    comparison = _comparison(spec, base, recorder, data, preds, official, context)
    house.apply_style('ATLAS', required=True)
    fig, drawn = _overlay_figure(spec, axes, edges, data, data_label, preds, order, official, comparison)
    try:
        out = new_output_dir(out_dir)
        saved = save_figure(fig, out, name)
    finally:
        plt.close(fig)
    files = list(saved['files'])
    side = None
    if spec.get('side_by_side'):
        fig2 = _side_by_side(axes, edges, data, data_label, preds, order, official)
        try:
            files += save_figure(fig2, out, f'{name}-side-by-side')['files']
        finally:
            plt.close(fig2)
        side = {'panels': ['Published figure', 'This result'], 'stem': f'{name}-side-by-side'}
    predictions = {}
    for n in order:
        p = preds[n]
        predictions[n] = {k: v for k, v in p.items() if k not in ('array', 'err')}
        predictions[n]['error_low'], predictions[n]['error_high'] = (e.tolist() for e in p['err'])
    receipt = {'schema_version': 1, 'kind': 'measurement-overlay-figure', 'name': name, 'files': files,
               'plot_lint': 'PASS', 'edges': edges.tolist(), 'quantity': data['quantity'], 'unit': data['unit'],
               'data': {'label': data_label, 'transformations': data_ops, **drawn['data']},
               'predictions': predictions, 'ratio': drawn['ratio'], 'ratio_denominator': drawn['ratio_denominator'],
               'difference': drawn['difference'], 'legend': drawn['legend'],
               'official': None if official is None else {'label': official['label'], 'kind': official['kind']},
               'side_by_side': side, 'comparison': comparison,
               'inputs': list(recorder.pins.values()),
               'provenance': {'tool': 'ravel.plotting.measurement_overlay', 'code': code_identity(__file__)},
               'machine_review_only': True}
    write_new_json(out / f'{name}.json', receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel figure measurement', description=__doc__.split('\n')[0])
    parser.add_argument('--spec', required=True, help='measurement-overlay specification JSON')
    parser.add_argument('--out', required=True, help='new or empty output directory')
    args = parser.parse_args(argv)
    try:
        receipt = run_spec(args.spec, args.out)
    except (ValueError, OSError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    print(json.dumps({'figure': [f['path'] for f in receipt['files']], 'plot_lint': receipt['plot_lint'],
                      'comparison': (receipt['comparison'] or {}).get('verdict')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
