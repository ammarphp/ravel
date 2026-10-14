"""Parameter-plane figures from declared grids, limit curves and references.

A specification declares the axes (natural-language label, unit, linear or log
scale, optional range) and one or more panels. A panel can hold:

- ``grid``: surfaces on a rectangular x-y grid (``observed``, ``expected``,
  ``expected_1sigma``/``expected_2sigma`` low and high surfaces) with the
  exclusion ``level`` and whether points ``below`` or ``above`` it are excluded.
  Contours are traced with contourpy in the declared axis scales; the excluded
  region is shaded and the expected bands are filled between their contours.
- ``colour_map``: one surface drawn as a colour map with a labelled colour bar.
- ``limit_curves``: a one-dimensional limit (observed, expected and bands) along x.
- ``intervals``: disjoint excluded intervals in y for each x.
- ``theory``: prediction curves with an optional uncertainty band.
- ``references``: digitised, HEPData or inline curves and contours drawn on the
  same axes. A reference may carry ``compare`` to compute the declared
  comparison object (``reference_metrics``) against the drawn contour or curve.
- ``points``: labelled benchmark points.

Every label is checked for natural language, every figure passes the house plot
lint, and a receipt (``<name>.json``) records the traced contours, legend,
excluded fraction, comparisons and pinned inputs. Machine checks only.
"""
from pathlib import Path
import argparse
import json
import math
import sys

import numpy as np

from . import reference_metrics as rm
from .figure_io import (axis_title, code_identity, finite_list, load_spec, natural_label, new_output_dir, pin,
                        save_figure, scale_of, write_new_json)

OBSERVED = '#000000'
EXPECTED = '#000000'
BAND_1 = '#5cb85c'
BAND_2 = '#f0d43a'
EXCLUDED = '#56B4E9'
REFERENCE_COLOURS = ('#D55E00', '#0072B2', '#CC79A7', '#009E73', '#E69F00')
THEORY_COLOURS = ('#CC79A7', '#009E73', '#E69F00', '#0072B2')
SURFACES = ('observed', 'expected')
BANDS = ('expected_1sigma', 'expected_2sigma')
PANEL_FIELDS = {'title', 'axes', 'grid', 'colour_map', 'limit_curves', 'intervals', 'theory', 'references', 'points'}


# ===================================================================== geometry
def _forward(scale):
    return (lambda v: np.log10(np.asarray(v, float))) if scale == 'log' else (lambda v: np.asarray(v, float))


def _backward(scale):
    return (lambda v: np.power(10.0, v)) if scale == 'log' else (lambda v: np.asarray(v, float))


def grid_contours(x, y, z, level, xscale='linear', yscale='linear', surface_scale='linear'):
    """Trace the ``level`` contour of z[y, x] in the declared axis scales; return segments."""
    import contourpy
    x, y, z = np.asarray(x, float), np.asarray(y, float), np.asarray(z, float)
    if z.shape != (len(y), len(x)):
        raise ValueError(f'surface shape {z.shape} does not match the grid (len(y), len(x)) = {(len(y), len(x))}')
    for scale, values, name in ((xscale, x, 'x'), (yscale, y, 'y')):
        if scale == 'log' and np.any(values <= 0):
            raise ValueError(f'a logarithmic {name} axis needs positive grid values')
    zz, lv = z, float(level)
    if surface_scale == 'log':
        if np.any(z <= 0) or level <= 0:
            raise ValueError('a logarithmic surface needs positive values and level')
        zz, lv = np.log10(z), math.log10(level)
    gen = contourpy.contour_generator(_forward(xscale)(x), _forward(yscale)(y), np.ma.masked_invalid(zz))
    segments = []
    for line in gen.lines(lv):
        line = np.asarray(line)
        if len(line) < 2:
            continue
        segments.append({'x': _backward(xscale)(line[:, 0]).tolist(), 'y': _backward(yscale)(line[:, 1]).tolist()})
    return segments


def _surface(grid, key, shape):
    value = grid.get(key)
    if value is None:
        return None
    if isinstance(value, np.ndarray):
        if value.shape != shape:
            raise ValueError(f'{key} surface shape {value.shape} does not match the grid {shape}')
        return value
    if isinstance(value, dict):
        raise ValueError(f'{key} must be a two-dimensional array')
    arr = np.array([finite_list(row, f'{key} row') for row in value]) if value and isinstance(value[0], list) \
        else np.array([])
    if arr.shape != shape:
        raise ValueError(f'{key} surface shape {arr.shape} does not match the grid {shape}')
    return arr


def _band(grid, key, shape):
    value = grid.get(key)
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'low', 'high'}:
        raise ValueError(f'{key} needs low and high surfaces')
    return _surface(value, 'low', shape), _surface(value, 'high', shape)


# ===================================================================== drawing
def _check_axes(axes):
    if not isinstance(axes, dict) or not {'x', 'y'} <= set(axes):
        raise ValueError('declare x and y axes')
    out = {}
    for k in ('x', 'y'):
        a = axes[k]
        out[k] = {'title': axis_title(a, f'{k} axis'), 'scale': scale_of(a, f'{k} axis'),
                  'range': finite_list(a['range'], f'{k} range', minimum=2) if 'range' in a else None,
                  'label': a['label'], 'unit': a.get('unit', '')}
        if out[k]['range'] and out[k]['scale'] == 'log' and min(out[k]['range']) <= 0:
            raise ValueError(f'a logarithmic {k} range must be positive')
    return out


def _in_scale(values, scale):
    values = np.asarray(values, float)
    if scale == 'log':
        if np.any(values <= 0):
            raise ValueError('a logarithmic surface needs positive values')
        return np.log10(values)
    return values


def _fill_below(ax, x, y, field, threshold, colour, alpha, zorder):
    """Fill the region where a continuous field is below the threshold (smooth boundary)."""
    lo = float(np.nanmin(field))
    if lo >= threshold:
        return
    ax.contourf(x, y, field, levels=[lo - 1.0, threshold], colors=[colour], alpha=alpha, zorder=zorder)


def _excluded_mask(z, level, side):
    return z < level if side == 'below' else z > level


def _grid_from_inference(grid, base, recorder):
    """Resolve a grid declared from a statistics inference record (values indexed [x][y])."""
    from .figure_io import resolve
    allowed = {'inference', 'x', 'y', 'surfaces', 'bands', 'level', 'excluded', 'surface_scale', 'shade',
               'excluded_label'}
    if set(grid) - allowed:
        raise ValueError(f'unknown inference grid fields: {sorted(set(grid) - allowed)}')
    doc = recorder.read(resolve(base, grid['inference']))
    product = doc.get('grid') or {}
    if product.get('kind') != 'product' or len(product.get('axes', [])) != 2:
        raise ValueError('the inference record needs a two-axis product grid')
    names = [a['name'] for a in product['axes']]
    for key in ('x', 'y'):
        if grid.get(key) not in names:
            raise ValueError(f'grid {key} {grid.get(key)!r} is not an axis of the inference grid {names}')
    transpose = names[0] == grid['x']
    xs = product['axes'][names.index(grid['x'])]['values']
    ys = product['axes'][names.index(grid['y'])]['values']
    missing = 0

    def surface(name):
        nonlocal missing
        row = rm.inference_result(doc, name, 'grid-values')
        arr = np.array([[np.nan if v is None else float(v) for v in r] for r in row['values']], float)
        arr = arr.T if transpose else arr
        missing += int(np.sum(~np.isfinite(arr)))
        return arr
    out = {k: grid[k] for k in ('level', 'excluded', 'surface_scale', 'shade', 'excluded_label') if k in grid}
    out.update({'x': xs, 'y': ys})
    for key, name in (grid.get('surfaces') or {}).items():
        if key not in SURFACES:
            raise ValueError(f'surface {key!r} must be one of {SURFACES}')
        out[key] = surface(name)
    for key, pair in (grid.get('bands') or {}).items():
        if key not in BANDS or not isinstance(pair, dict) or set(pair) != {'low', 'high'}:
            raise ValueError(f'band {key!r} must be one of {BANDS} with low and high results')
        out[key] = {'low': surface(pair['low']), 'high': surface(pair['high'])}
    return out, {'inference': str(resolve(base, grid['inference'])), 'x': grid['x'], 'y': grid['y'],
                 'missing_values': missing}


def _draw_grid(ax, panel, axes, record, handles, base=None, recorder=None):
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    grid = panel['grid']
    if 'inference' in grid:
        grid, record['grid_source'] = _grid_from_inference(grid, base, recorder)
    x = np.array(finite_list(grid.get('x'), 'grid x', minimum=2))
    y = np.array(finite_list(grid.get('y'), 'grid y', minimum=2))
    if np.any(np.diff(x) <= 0) or np.any(np.diff(y) <= 0):
        raise ValueError('grid x and y must increase')
    shape = (len(y), len(x))
    level = float(grid.get('level', 1.0))
    side = grid.get('excluded', 'below')
    if side not in ('below', 'above'):
        raise ValueError('grid "excluded" must be below or above the level')
    sscale = grid.get('surface_scale', 'linear')
    if sscale not in ('linear', 'log'):
        raise ValueError('surface_scale must be linear or log')
    surfaces = {k: _surface(grid, k, shape) for k in SURFACES}
    bands = {k: _band(grid, k, shape) for k in BANDS}
    if all(v is None for v in surfaces.values()):
        raise ValueError('a grid needs an observed or expected surface')
    xs, ys = axes['x']['scale'], axes['y']['scale']
    contours = {}
    for key, colour, width in (('expected_2sigma', BAND_2, None), ('expected_1sigma', BAND_1, None)):
        if bands[key] is None:
            continue
        low, high = bands[key]
        lo_s, hi_s = _in_scale(np.minimum(low, high), sscale), _in_scale(np.maximum(low, high), sscale)
        lv = _in_scale(level, sscale)
        # Smooth band: the region where the low surface is below the level and the high surface above it.
        _fill_below(ax, x, y, np.maximum(lo_s - lv, lv - hi_s), 0.0, colour, 0.9, 1)
        contours[key] = {'low': {'segments': grid_contours(x, y, low, level, xs, ys, sscale)},
                         'high': {'segments': grid_contours(x, y, high, level, xs, ys, sscale)}}
        label = 'Expected ±1σ' if key == 'expected_1sigma' else 'Expected ±2σ'
        handles.append((Patch(facecolor=colour, edgecolor='none'), label))
    primary = 'observed' if surfaces['observed'] is not None else 'expected'
    z = surfaces[primary]
    mask = _excluded_mask(z, level, side)
    record['excluded_fraction'] = float(mask[np.isfinite(z)].mean())
    if grid.get('shade', True):
        zs, lv = _in_scale(z, sscale), _in_scale(level, sscale)
        _fill_below(ax, x, y, zs - lv if side == 'below' else lv - zs, 0.0, EXCLUDED, 0.25, 0)
        handles.append((Patch(facecolor=EXCLUDED, alpha=0.25, edgecolor='none'),
                        natural_label(grid.get('excluded_label', 'Excluded region'), 'excluded-region label')))
    for key, style in (('expected', '--'), ('observed', '-')):
        if surfaces[key] is None:
            continue
        segments = grid_contours(x, y, surfaces[key], level, xs, ys, sscale)
        contours[key] = {'segments': segments}
        for seg in segments:
            ax.plot(seg['x'], seg['y'], style, color=OBSERVED if key == 'observed' else EXPECTED, lw=2.2, zorder=4)
        label = 'Observed limit' if key == 'observed' else 'Expected limit'
        handles.append((Line2D([], [], color=OBSERVED, ls=style, lw=2.2), label))
    record['contours'] = contours
    record['level'] = level
    record['excluded_side'] = side
    cmap = panel.get('colour_map')
    if cmap:
        name = cmap.get('surface')
        source = surfaces.get(name)
        if source is None:
            raise ValueError(f'colour map surface {name!r} is not one of the grid surfaces')
        from matplotlib.colors import LogNorm, Normalize
        norm = LogNorm() if cmap.get('scale') == 'log' else Normalize()
        mesh = ax.pcolormesh(x, y, source, shading='nearest', cmap='viridis', norm=norm, alpha=0.55, zorder=-1,
                             rasterized=True)
        bar = ax.figure.colorbar(mesh, ax=ax, location='top', pad=0.02, shrink=0.9)
        bar.set_label(natural_label(cmap.get('label', ''), 'colour-map label'))
        record['colour_map'] = {'surface': name, 'scale': cmap.get('scale', 'linear')}
    return {'x': [float(x[0]), float(x[-1])], 'y': [float(y[0]), float(y[-1])]}


def _draw_limit_curves(ax, panel, record, handles):
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    lc = panel['limit_curves']
    x = np.array(finite_list(lc.get('x'), 'limit x', minimum=2))
    n = len(x)

    def vec(value, label):
        v = np.array(finite_list(value, label, minimum=n))
        if len(v) != n:
            raise ValueError(f'{label} shape does not match the {n} x values')
        return v
    for key, colour, label in (('expected_2sigma', BAND_2, 'Expected ±2σ'), ('expected_1sigma', BAND_1, 'Expected ±1σ')):
        if key in lc:
            lo, hi = vec(lc[key].get('low'), f'{key} low'), vec(lc[key].get('high'), f'{key} high')
            ax.fill_between(x, lo, hi, color=colour, lw=0, zorder=1)
            handles.append((Patch(facecolor=colour, edgecolor='none'), label))
    for key, style, label in (('expected', '--', 'Expected limit'), ('observed', '-', 'Observed limit')):
        if key in lc:
            ax.plot(x, vec(lc[key], key), style, color=OBSERVED, lw=2.2, zorder=4,
                    marker='o' if key == 'observed' else None, ms=4)
            handles.append((Line2D([], [], color=OBSERVED, ls=style, lw=2.2), label))
    if not any(k in lc for k in ('expected', 'observed')):
        raise ValueError('limit curves need an expected or observed curve')
    record['limit_curves'] = sorted(k for k in lc if k != 'x')
    ys = [vec(lc[k], k) for k in ('expected', 'observed') if k in lc]
    return {'x': [float(x.min()), float(x.max())], 'y': [float(min(v.min() for v in ys)), float(max(v.max() for v in ys))]}


def _draw_intervals(ax, panel, record, handles):
    from matplotlib.patches import Patch, Rectangle
    iv = panel['intervals']
    x = np.array(finite_list(iv.get('x'), 'interval x'))
    columns = iv.get('excluded')
    if not isinstance(columns, list) or len(columns) != len(x):
        raise ValueError('intervals need one list of excluded [low, high] pairs per x value')
    if len(x) > 1:
        mids = (x[1:] + x[:-1]) / 2
        lefts = np.concatenate([[x[0] - (mids[0] - x[0])], mids])
        rights = np.concatenate([mids, [x[-1] + (x[-1] - mids[-1])]])
    else:
        lefts, rights = x - 0.5, x + 0.5
    drawn = []
    for xi, lo_edge, hi_edge, col in zip(x, lefts, rights, columns):
        pairs = []
        for pair in col:
            lo, hi = finite_list(pair, 'excluded interval', minimum=2)
            if hi <= lo:
                raise ValueError('each excluded interval needs low < high')
            ax.add_patch(Rectangle((lo_edge, lo), hi_edge - lo_edge, hi - lo, facecolor=EXCLUDED, alpha=0.6,
                                   edgecolor='none', zorder=2))
            pairs.append([lo, hi])
        drawn.append({'x': float(xi), 'excluded': pairs})
    label = natural_label(iv.get('label', 'Excluded'), 'interval label')
    handles.append((Patch(facecolor=EXCLUDED, alpha=0.6, edgecolor='none'), label))
    record['intervals'] = drawn
    ys = [v for c in drawn for p in c['excluded'] for v in p] or [0.0, 1.0]
    return {'x': [float(lefts[0]), float(rights[-1])], 'y': [min(ys), max(ys)]}


def _draw_theory(ax, panel, record, handles):
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    names = []
    for i, curve in enumerate(panel.get('theory') or []):
        label = natural_label(curve.get('label', ''), 'theory label')
        x = np.array(finite_list(curve.get('x'), 'theory x', minimum=2))
        y = np.array(finite_list(curve.get('y'), 'theory y', minimum=2))
        if len(x) != len(y):
            raise ValueError('theory x and y differ in length')
        colour = THEORY_COLOURS[i % len(THEORY_COLOURS)]
        ax.plot(x, y, '-.', color=colour, lw=2, zorder=3)
        if 'uncertainty' in curve:
            u = curve['uncertainty']
            lo = np.array(finite_list(u.get('low'), 'theory low', minimum=len(x)))
            hi = np.array(finite_list(u.get('high'), 'theory high', minimum=len(x)))
            ax.fill_between(x, lo, hi, color=colour, alpha=0.25, lw=0, zorder=2)
            handles.append((Patch(facecolor=colour, alpha=0.25, edgecolor='none'), label + ' uncertainty'))
        handles.append((Line2D([], [], color=colour, ls='-.', lw=2), label))
        names.append(label)
    record['theory'] = names


def _reference_shapes(source):
    if 'segments' in source:
        return source['segments']
    if 'x' in source and 'y' in source:
        return [{'x': source['x'], 'y': source['y']}]
    if 'polygons' in source:
        return [{'x': list(p['x']) + [p['x'][0]], 'y': list(p['y']) + [p['y'][0]]} for p in source['polygons']]
    if 'curve' in source:
        return [source['curve']]
    raise ValueError('a reference must resolve to a curve, contour or region')


def _draw_references(ax, panel, axes, base, recorder, record, handles, context=None):
    from matplotlib.lines import Line2D
    out = []
    for i, ref in enumerate(panel.get('references') or []):
        label = natural_label(ref.get('label', ''), 'reference label')
        source = rm.load_source(ref.get('source'), base, context, recorder=recorder)
        if 'edges' in source:
            edges = np.array(source['edges'])
            centres = (edges[1:] + edges[:-1]) / 2
            source = {'x': centres.tolist(), 'y': source['values']}
        shapes = _reference_shapes(source)
        colour = ref.get('colour') or REFERENCE_COLOURS[i % len(REFERENCE_COLOURS)]
        style = ref.get('style', 'line')
        for seg in shapes:
            if style == 'points':
                ax.plot(seg['x'], seg['y'], 's', color=colour, ms=5, zorder=5)
            else:
                ax.plot(seg['x'], seg['y'], ':', color=colour, lw=2.4, zorder=5)
        handles.append((Line2D([], [], color=colour, ls='' if style == 'points' else ':',
                               marker='s' if style == 'points' else None, lw=2.4), label))
        entry = {'label': label, 'segments': len(shapes)}
        if 'compare' in ref:
            entry['comparison'] = _compare_reference(ref['compare'], record, source, axes)
        out.append(entry)
    record['references'] = out


def _compare_reference(rule, record, source, axes):
    """Build the declared comparison object for a drawn reference."""
    if not isinstance(rule, dict):
        raise ValueError('reference "compare" must be an object')
    target = rule.get('with', 'observed')
    kind = rule.get('kind', 'contour')
    if target in record.get('contours', {}) and 'segments' in record['contours'][target]:
        agent = {'segments': record['contours'][target]['segments']}
    else:
        raise ValueError(f'reference comparison target {target!r} was not drawn in this panel')
    metric_axes = {k: {'scale': axes[k]['scale'], **({'range': axes[k]['range']} if axes[k]['range'] else {})}
                   for k in ('x', 'y')}
    spec = {'schema_version': 1, 'kind': kind, 'agent': agent,
            'reference': {'segments': _reference_shapes(source)} if kind == 'contour' else source,
            'axes': metric_axes, 'tolerances': rule.get('tolerances')}
    for key in ('tip', 'at', 'label'):
        if key in rule:
            spec[key] = rule[key]
    unknown = set(rule) - {'with', 'kind', 'tolerances', 'tip', 'at', 'label'}
    if unknown:
        raise ValueError(f'unknown reference comparison fields: {sorted(unknown)}')
    if kind == 'curve':
        segs = agent['segments']
        spec['agent'] = {'x': [v for s in segs for v in s['x']], 'y': [v for s in segs for v in s['y']]}
    return rm.compare(spec, Path('.'))


def _draw_points(ax, panel, record):
    labels = []
    for p in panel.get('points') or []:
        label = natural_label(p.get('label', ''), 'point label')
        x, y = finite_list([p.get('x'), p.get('y')], 'point', minimum=2)
        ax.plot([x], [y], marker='*', color='#D55E00', ms=13, ls='', zorder=6)
        ax.annotate(label, (x, y), xytext=(6, 6), textcoords='offset points', fontsize=10)
        labels.append(label)
    record['points'] = labels


def _apply_axes(ax, axes, extent):
    from . import mplhep_style as house
    ax.set_xscale(axes['x']['scale'])
    ax.set_yscale(axes['y']['scale'])
    for k, setter in (('x', ax.set_xlim), ('y', ax.set_ylim)):
        rng = axes[k]['range']
        if rng is None and extent and k in extent:
            lo, hi = extent[k]
            if axes[k]['scale'] == 'log':
                lo, hi = lo / 1.3, hi * 1.3
            else:
                pad = 0.05 * (hi - lo or 1.0)
                lo, hi = lo - pad, hi + pad
            rng = [lo, hi]
        if rng is not None:
            setter(*rng)
    ax.set_xlabel(axes['x']['title'])
    ax.set_ylabel(axes['y']['title'])
    house.tick_hygiene(ax, logy=axes['y']['scale'] == 'log', logx=axes['x']['scale'] == 'log')
    house.publication_axes(ax)


def render_panel(ax, panel, axes, base, recorder, annotation=None, context=None):
    unknown = set(panel) - PANEL_FIELDS
    if unknown:
        raise ValueError(f'unknown panel fields: {sorted(unknown)}')
    record, handles, extent = {}, [], {}
    if panel.get('title'):
        record['title'] = natural_label(panel['title'], 'panel title')
        ax.set_title(record['title'], fontsize=13)
    if 'grid' in panel:
        extent = _draw_grid(ax, panel, axes, record, handles, base, recorder)
    if 'limit_curves' in panel:
        extent = _draw_limit_curves(ax, panel, record, handles)
    if 'intervals' in panel:
        extent = _draw_intervals(ax, panel, record, handles)
    if not ({'grid', 'limit_curves', 'intervals'} & set(panel)):
        raise ValueError('a panel needs a grid, limit curves or intervals')
    _draw_theory(ax, panel, record, handles)
    _draw_references(ax, panel, axes, base, recorder, record, handles, context)
    _draw_points(ax, panel, record)
    _apply_axes(ax, axes, extent)
    lines = [natural_label(t, 'annotation') for t in annotation or []]
    for ref in record.get('references', []):
        if 'comparison' in ref:
            lines.append(ref['label'] + ' versus this result')
            lines.extend('  ' + natural_label(t, 'comparison summary') for t in ref['comparison']['summary'])
    title = '\n'.join(lines) if lines else None
    legend = ax.legend([h for h, _ in handles], [l for _, l in handles], loc='upper left',
                       bbox_to_anchor=(1.02, 1.0), borderaxespad=0.0, fontsize=10, title=title,
                       title_fontsize=10, frameon=False, alignment='left')
    legend.set_zorder(10)
    record['legend'] = [l for _, l in handles]
    return record


def _figure(n_panels, columns, has_colour_bar):
    import matplotlib.pyplot as plt
    rows = math.ceil(n_panels / columns)
    width = 7.6 * columns + 0.6
    height = (6.6 if has_colour_bar else 5.6) * rows
    fig, grid = plt.subplots(rows, columns, figsize=(width, height), squeeze=False, layout='constrained')
    for extra in grid.ravel()[n_panels:]:
        extra.remove()
    return fig, grid.ravel()[:n_panels], rows


def run_spec(spec_path, out_dir, context=None):
    """Render the declared parameter-plane figure; write NAME.pdf, NAME.png and NAME.json.

    ``context`` maps earlier operation names to their digitized documents (``{"operation": name}`` sources).
    """
    import matplotlib.pyplot as plt
    from . import mplhep_style as house
    spec, base = load_spec(spec_path)
    allowed = {'schema_version', 'name', 'axes', 'panels', 'layout', 'annotation', 'description'}
    if set(spec) - allowed:
        raise ValueError(f'unknown parameter-plane fields: {sorted(set(spec) - allowed)}')
    name = spec.get('name') or Path(spec_path).stem
    if not isinstance(name, str) or not name.replace('-', '').replace('_', '').isalnum():
        raise ValueError('figure name must be letters, digits, hyphens or underscores')
    axes = _check_axes(spec.get('axes'))
    panels = spec.get('panels')
    if not isinstance(panels, list) or not panels:
        raise ValueError('declare at least one panel')
    columns = int((spec.get('layout') or {}).get('columns', 1))
    if columns < 1:
        raise ValueError('layout columns must be positive')
    columns = min(columns, len(panels))
    annotation = spec.get('annotation')
    if annotation is not None and (not isinstance(annotation, list) or not all(isinstance(a, str) for a in annotation)):
        raise ValueError('annotation must be a list of text lines')
    recorder = rm._Recorder()
    recorder.pins[str(Path(spec_path).absolute())] = pin(spec_path)
    house.apply_style('ATLAS', required=True)
    fig, axs, rows = _figure(len(panels), columns, any(p.get('colour_map') for p in panels))
    try:
        records = []
        for i, (ax, panel) in enumerate(zip(axs, panels)):
            panel_axes = _check_axes({**spec['axes'], **panel['axes']}) if panel.get('axes') else axes
            records.append(render_panel(ax, panel, panel_axes, base, recorder,
                                        annotation if i == 0 else None, context))
        out = new_output_dir(out_dir)
        saved = save_figure(fig, out, name)
    finally:
        plt.close(fig)
    receipt = {'schema_version': 1, 'kind': 'parameter-plane-figure', 'name': name,
               'files': saved['files'], 'plot_lint': saved['plot_lint'],
               'axes': {k: {'title': axes[k]['title'], 'scale': axes[k]['scale'], 'range': axes[k]['range']}
                        for k in ('x', 'y')},
               'layout': {'columns': columns, 'rows': rows}, 'panels': records,
               'inputs': list(recorder.pins.values()),
               'provenance': {'tool': 'ravel.plotting.parameter_plane', 'code': code_identity(__file__)},
               'machine_review_only': True}
    write_new_json(out / f'{name}.json', receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel figure plane', description=__doc__.split('\n')[0])
    parser.add_argument('--spec', required=True, help='parameter-plane specification JSON')
    parser.add_argument('--out', required=True, help='new or empty output directory')
    args = parser.parse_args(argv)
    try:
        receipt = run_spec(args.spec, args.out)
    except (ValueError, OSError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    print(json.dumps({'figure': [f['path'] for f in receipt['files']], 'plot_lint': receipt['plot_lint'],
                      'panels': len(receipt['panels'])}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
