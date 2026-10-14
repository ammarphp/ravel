"""Figures for inference records, in the house style with natural-language labels.

Drawn from ``inference.json`` only:

- profile scans: Delta(-2 ln L) against the parameter, the threshold and the
  allowed intervals (one figure per hypothesis, up to ``MAX_SCANS``);
- hypothesis summaries: allowed-interval upper edges against one coordinate;
- contours: level sets in the two grid parameters;
- grid values: a curve (one axis) or a colour map (two axes);
- measured spectra: measurement, reference and best-fit prediction;
- background-only fits: parameter pulls.

Every figure is saved as PDF and PNG and checked by the label lint; layout
findings are recorded in ``figures.json``.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

MAX_SCANS = 12


def _axis(label, unit):
    from ravel.plotting.display_labels import unit_label
    return label if not unit else f'{label} [{unit_label(unit)}]'


def _save(fig, out, stem, figures, lint):
    import matplotlib.pyplot as plt
    from ravel.plotting.display_labels import figure_label_errors
    from ravel.plotting import mplhep_style as house
    errors = figure_label_errors(fig)
    if errors:
        plt.close(fig)
        raise ValueError('figure labels must be natural language: ' + '; '.join(errors))
    issues = house.lint_figure(fig)
    files = []
    for ext in ('pdf', 'png'):
        fig.savefig(out / f'{stem}.{ext}', bbox_inches='tight', dpi=150)
        files.append(f'{stem}.{ext}')
    plt.close(fig)
    figures.append({'stem': stem, 'files': files})
    if issues:
        lint[stem] = issues


def _parameters(doc):
    return {p['name']: p for p in doc.get('parameters', [])}


def _scan_figure(plt, row, region, params, out, figures, lint, index):
    p = params.get(row['parameter'], {'label': row['parameter'], 'unit': ''})
    grid = np.asarray(row['grid'], float)
    delta = np.array([np.nan if v is None else v for v in row['delta']], float)
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(grid, delta, color='#0072B2', label='Profile likelihood scan')
    if region is not None and region.get('threshold') is not None:
        t = region['threshold']
        ax.axhline(t, color='#D55E00', linestyle='--', label=f'Threshold {t:g}')
        for k, interval in enumerate(region.get('intervals', [])):
            lo = interval['low'].get('value', interval['low'].get('scan_edge'))
            hi = interval['high'].get('value', interval['high'].get('scan_edge'))
            if lo is not None and hi is not None:
                ax.axvspan(lo, hi, color='#009E73', alpha=0.15, label='Allowed region' if k == 0 else None)
        finite = delta[np.isfinite(delta)]
        if finite.size:
            ax.set_ylim(0, max(2.5 * t, min(float(finite.max()), 6 * t)))
    ax.set_xlabel(_axis(p['label'], p['unit']))
    ax.set_ylabel(r'$\Delta(-2\ln L)$')
    if row.get('hypothesis') not in (None, 'nominal'):
        ax.set_title('Hypothesis ' + str(row['hypothesis']).replace('_', ' '))
    ax.legend(loc='upper left', bbox_to_anchor=(1.02, 1.0), frameon=False)
    _save(fig, out, f'profile-scan-{index + 1}', figures, lint)


def _summary_figure(plt, regions, params, out, figures, lint):
    coords = [r.get('coordinates') or {} for r in regions]
    names = sorted({k for c in coords for k in c})
    if len(names) != 1 or len(regions) < 2:
        return
    name = names[0]
    xs, ys = [], []
    for r in regions:
        edges = [i['high'].get('value') for i in r.get('intervals', [])]
        edges = [e for e in edges if e is not None]
        if edges and name in (r.get('coordinates') or {}):
            xs.append(r['coordinates'][name]); ys.append(max(edges))
    if len(xs) < 2:
        return
    order = np.argsort(xs)
    p = params.get(regions[0]['parameter'], {'label': regions[0]['parameter'], 'unit': ''})
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(np.asarray(xs)[order], np.asarray(ys)[order], marker='o', color='#0072B2',
            label='Upper edge of the allowed region')
    ax.set_xlabel(name.replace('_', ' '))
    ax.set_ylabel(_axis(p['label'], p['unit']))
    ax.legend(loc='upper left', bbox_to_anchor=(1.02, 1.0), frameon=False)
    _save(fig, out, 'allowed-region-summary', figures, lint)


def _contour_figure(plt, row, params, out, figures, lint, index, grid=None):
    if not row.get('series'):
        return
    fig, ax = plt.subplots(figsize=(7, 6))
    colors = ['#0072B2', '#D55E00', '#009E73', '#CC79A7']
    for k, s in enumerate(row['series']):
        x = [r['x'] for r in s['records']]; y = [r['y'] for r in s['records']]
        ax.plot(x, y, color=colors[k % len(colors)] if k < len(colors) else colors[0],
                label=s['label'] if k == 0 else None)
    px = params.get(row['x'], {'label': row['x'], 'unit': ''})
    py = params.get(row['y'], {'label': row['y'], 'unit': ''})
    ax.set_xlabel(_axis(px.get('label', row['x']), px.get('unit', '')))
    ax.set_ylabel(_axis(py.get('label', row['y']), py.get('unit', '')))
    if grid and grid.get('kind') == 'product':
        ranges = {a['name']: (min(a['values']), max(a['values'])) for a in grid['axes']}
        if row['x'] in ranges and row['y'] in ranges:
            ax.set_xlim(*ranges[row['x']]); ax.set_ylim(*ranges[row['y']])
    ax.legend(loc='upper left', bbox_to_anchor=(1.02, 1.0), frameon=False)
    _save(fig, out, f'contour-{index + 1}', figures, lint)


def _grid_figure(plt, row, grid, params, out, figures, lint, index):
    if not grid or grid.get('kind') != 'product':
        return
    values = np.array(row['values'], dtype=float)
    axes = grid['axes']
    label = _axis(row['label'], row.get('unit', ''))
    fig, ax = plt.subplots(figsize=(7, 5.5))
    if len(axes) == 1:
        ax.plot(axes[0]['values'], values, color='#0072B2', label=row['label'])
        ax.set_xlabel(_axis(axes[0].get('label', axes[0]['name']), axes[0]['unit']))
        ax.set_ylabel(label)
        ax.legend(loc='upper left', bbox_to_anchor=(1.02, 1.0), frameon=False)
    elif len(axes) == 2:
        mesh = ax.pcolormesh(axes[0]['values'], axes[1]['values'], values.T, shading='auto', cmap='viridis')
        bar = fig.colorbar(mesh, ax=ax)
        bar.set_label(label)
        ax.set_xlabel(_axis(axes[0].get('label', axes[0]['name']), axes[0]['unit']))
        ax.set_ylabel(_axis(axes[1].get('label', axes[1]['name']), axes[1]['unit']))
    else:
        plt.close(fig)
        return
    _save(fig, out, f'grid-{index + 1}', figures, lint)


def _spectrum_figure(plt, row, doc, out, figures, lint):
    diag = doc.get('diagnostics', {})
    edges = diag.get('bin_edges')
    observable = diag.get('observable')
    if not edges or not observable or row.get('measured') is None:
        return
    edges = np.asarray(edges, float)
    centers = 0.5 * (edges[1:] + edges[:-1])
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.stairs(row['reference'], edges, color='#0072B2', label='Reference prediction')
    ax.stairs(row['prediction_at_best_fit'], edges, color='#D55E00', linestyle='--', label='Best-fit prediction')
    ax.plot(centers, row['measured'], 'o', color='black', label='Measurement')
    ax.set_xlabel(_axis(observable['label'], observable['unit']))
    ax.set_ylabel(_axis('Differential cross section', diag.get('measurement_unit', '')))
    ax.legend(loc='upper left', bbox_to_anchor=(1.02, 1.0), frameon=False)
    _save(fig, out, 'spectrum-best-fit', figures, lint)


def _pull_figure(plt, row, out, figures, lint):
    rows = [p for p in row['parameters'] if p.get('pull') is not None]
    if not rows:
        return
    fig, ax = plt.subplots(figsize=(7, 0.4 * len(rows) + 2))
    y = np.arange(len(rows))
    ax.errorbar([p['pull'] for p in rows], y, xerr=[p['error'] / p['prefit']['width'] if p['prefit']['width'] else 0
                                                   for p in rows], fmt='o', color='black', label='Post-fit pull')
    ax.axvline(0, color='0.5')
    ax.set_yticks(y, [str(p['name']).replace('_', ' ') for p in rows])
    ax.set_xlabel('Pull in units of the prior width')
    ax.legend(loc='upper left', bbox_to_anchor=(1.02, 1.0), frameon=False)
    _save(fig, out, 'background-fit-pulls', figures, lint)


def render(out):
    out = Path(out)
    path = out / 'inference.json'
    if not path.is_file():
        return {'status': 'not_applicable', 'figures': [], 'tables': [], 'scope': 'No inference record'}
    doc = json.loads(path.read_text())
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return {'status': 'unavailable', 'reason': 'matplotlib is required for figures', 'files': [],
                'tables': [{'stem': 'inference', 'files': ['inference.json']}]}
    from ravel.plotting import mplhep_style as house
    house.apply_style('ATLAS')
    params = _parameters(doc)
    figures, lint = [], {}
    regions = {r.get('hypothesis'): r for r in doc['results']
               if r['quantity'] == 'delta-nll-region' and r['role'] == 'primary'}
    scans = [r for r in doc['results'] if r['quantity'] == 'delta-nll-scan']
    for k, row in enumerate(scans[:MAX_SCANS]):
        _scan_figure(plt, row, regions.get(row.get('hypothesis')), params, out, figures, lint, k)
    _summary_figure(plt, list(regions.values()), params, out, figures, lint)
    for k, row in enumerate(r for r in doc['results'] if r['quantity'] == 'contour' and r.get('series')):
        _contour_figure(plt, row, params, out, figures, lint, k, doc.get('grid'))
    for k, row in enumerate(r for r in doc['results'] if r['quantity'] == 'grid-values' and r['role'] == 'primary'):
        _grid_figure(plt, row, doc.get('grid'), params, out, figures, lint, k)
    if doc['mode'] == 'differential-likelihood' and scans:
        _spectrum_figure(plt, scans[0], doc, out, figures, lint)
    for row in doc['results']:
        if row['quantity'] == 'fitted-parameters':
            _pull_figure(plt, row, out, figures, lint)
    return {'status': 'passed' if figures else 'not_applicable', 'figures': figures,
            'tables': [{'stem': 'inference', 'files': ['inference.json']}],
            **({'layout_findings': lint} if lint else {}),
            'scope': 'Figures drawn from the inference record; numbers are in inference.json'}
