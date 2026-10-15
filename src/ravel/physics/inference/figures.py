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
    if not row.get('series') and not row.get('reference_contour'):
        return
    fig, ax = plt.subplots(figsize=(7, 6))
    colors = ['#0072B2', '#D55E00', '#009E73', '#CC79A7']
    for k, s in enumerate(row['series']):
        x = [r['x'] for r in s['records']]; y = [r['y'] for r in s['records']]
        ax.plot(x, y, color=colors[k % len(colors)] if k < len(colors) else colors[0],
                label=s['label'] if k == 0 else None)
    _reference_overlay(ax, row.get('reference_contour'))
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


def _reference_overlay(ax, reference):
    if reference:
        for k, s in enumerate(reference['series']):
            ax.plot([r['x'] for r in s['records']], [r['y'] for r in s['records']],
                    color='black', linestyle='--', label=s['label'] if k == 0 else None)


def _search_summary(plt, doc, out, figures, lint):
    predictions = next((r['regions'] for r in doc['results'] if r['quantity'] == 'post-fit-predictions'), [])
    if not predictions or not all('processes' in r for r in predictions):
        return
    fit = next((r for r in doc['results'] if r['quantity'] == 'fitted-parameters'), None)
    norms = [] if fit is None else [p for p in fit['parameters'] if not p['prefit']['constrained']]
    fig, axes = plt.subplots(3, 1, figsize=(9, 10), gridspec_kw={'height_ratios': [2.5, 1, 1]})
    ax = axes[0]
    x = np.arange(len(predictions))
    colors = plt.get_cmap('tab10')
    processes = sorted({p['name'] for r in predictions for p in r['processes']})
    for phase, shift, hatch in (('prefit', -0.2, '//'), ('postfit', 0.2, None)):
        bottom = np.zeros(len(x))
        for i, name in enumerate(processes):
            values = np.array([sum(sum(p[phase]) for p in r['processes'] if p['name'] == name) for r in predictions])
            ax.bar(x+shift, values, width=0.36, bottom=bottom, color=colors(i % 10), hatch=hatch,
                   label=name.replace('_', ' ') if phase == 'postfit' else None)
            bottom += values
    for i, r in enumerate(predictions):
        ax.errorbar(i+0.2, sum(r['prediction']), yerr=r.get('total_prediction_uncertainty', 0),
                    fmt='none', color='black', label='Post-fit uncertainty' if i == 0 else None)
        if r.get('data') is not None:
            ax.plot(i, sum(r['data']), 'ko', label='Simulated pseudo-data' if i == 0 and
                    doc['diagnostics']['data_mode'] == 'mc-pseudo-data' else 'Data' if i == 0 else None)
    ax.set_xticks(x, [r['region'].replace('_', ' ') for r in predictions])
    ax.set_ylabel('Background events')
    ax.set_title('Pre-fit (hatched) and post-fit backgrounds')
    ax.legend(loc='upper left', bbox_to_anchor=(1.02, 1), frameon=False)
    ax = axes[1]
    if norms:
        ax.errorbar(np.arange(len(norms)), [p['value'] for p in norms], yerr=[p['error'] for p in norms],
                    fmt='ko', elinewidth=1.3, capsize=3)
        ax.set_xticks(np.arange(len(norms)), [p['name'].replace('_', ' ') for p in norms])
        ax.set_xlim(-0.5, len(norms)-0.5)
    ax.axhline(1, color='0.5', linestyle='--')
    ax.set_ylabel('Normalisation factor')
    ax = axes[2]
    vr = [(r['region'], i, value) for r in predictions if r['role'] == 'VR'
          for i, value in enumerate(r.get('residuals', [])) if value is not None and np.isfinite(value)]
    if vr:
        ax.plot(np.arange(len(vr)), [v for _, _, v in vr], 'ko')
        ax.set_xticks(np.arange(len(vr)), [f'{r.replace("_", " ")} bin {i+1}' for r, i, _ in vr])
        bound = max(3., 1.2 * max(abs(v) for _, _, v in vr if v is not None))
        ax.set_ylim(-bound, bound)
    ax.axhline(0, color='0.5')
    ax.set_ylabel('Validation residual')
    ax.set_title('Residual = (data − prediction) / total uncertainty', fontsize=11)
    fig.suptitle(doc['diagnostics']['data_statement'])
    fig.tight_layout()
    _save(fig, out, 'search-background-summary', figures, lint)


def _point_significance(plt, doc, params, out, figures, lint):
    rows = [r for r in doc.get('diagnostics', {}).get('points', [])
            if r.get('asimov_discovery_significance') is not None]
    if not rows:
        return
    contours = [r for r in doc['results'] if r['quantity'] == 'contour' and 'x' in r]
    names = sorted({k for p in rows for k in p['coordinates']})
    if contours:
        x, y = contours[0]['x'], contours[0]['y']
    elif len(names) == 2:
        x, y = names
    else:
        return
    fig, ax = plt.subplots(figsize=(7, 6))
    dots = ax.scatter([p['coordinates'][x] for p in rows], [p['coordinates'][y] for p in rows],
                      c=[p['asimov_discovery_significance'] for p in rows], cmap='viridis', s=60)
    fig.colorbar(dots, ax=ax).set_label('Asimov discovery significance')
    for row in contours:
        for k, line in enumerate(row.get('series', [])):
            ax.plot([r['x'] for r in line['records']], [r['y'] for r in line['records']],
                    color='#D55E00', label=line['label'] if k == 0 else None)
    if contours:
        _reference_overlay(ax, contours[0].get('reference_contour'))
    for name, setter in ((x, ax.set_xlabel), (y, ax.set_ylabel)):
        p = params.get(name, {'label': name.replace('_', ' '), 'unit': ''})
        setter(_axis(p['label'], p['unit']))
    if ax.get_legend_handles_labels()[0]:
        ax.legend(loc='lower center', bbox_to_anchor=(0.5, 1.02), frameon=False)
    ax.margins(x=0.08, y=0.08)
    fig.tight_layout()
    _save(fig, out, 'search-significance-map', figures, lint)


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
    search_fonts = {'font.size': 11, 'axes.labelsize': 11, 'axes.titlesize': 12,
                    'figure.titlesize': 13, 'legend.fontsize': 10,
                    'xtick.labelsize': 10, 'ytick.labelsize': 10}
    with plt.rc_context(search_fonts if doc['mode'] == 'search-statistics' else {}):
        for k, row in enumerate(r for r in doc['results'] if r['quantity'] == 'contour'
                                and (r.get('series') or r.get('reference_contour'))):
            _contour_figure(plt, row, params, out, figures, lint, k, doc.get('grid'))
    for k, row in enumerate(r for r in doc['results'] if r['quantity'] == 'grid-values' and r['role'] == 'primary'):
        _grid_figure(plt, row, doc.get('grid'), params, out, figures, lint, k)
    if doc['mode'] == 'differential-likelihood' and scans:
        _spectrum_figure(plt, scans[0], doc, out, figures, lint)
    for row in doc['results']:
        if row['quantity'] == 'fitted-parameters':
            _pull_figure(plt, row, out, figures, lint)
    if doc['mode'] == 'search-statistics':
        with plt.rc_context(search_fonts):
            _search_summary(plt, doc, out, figures, lint)
            _point_significance(plt, doc, params, out, figures, lint)
    return {'status': 'passed' if figures else 'not_applicable', 'figures': figures,
            'tables': [{'stem': 'inference', 'files': ['inference.json']}]
                      + ([{'stem': 'points', 'files': ['points.json']}] if (out / 'points.json').is_file() else []),
            **({'layout_findings': lint} if lint else {}),
            'scope': 'Figures drawn from the inference record; numbers are in inference.json'}
