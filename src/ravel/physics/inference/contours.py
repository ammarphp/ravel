"""Level-set contours on product grids, in plot-coordinate-series form."""
from __future__ import annotations

import numpy as np


def level_lines(grid, values, level, *, x, y):
    """Polylines of ``values == level`` on a two-axis product grid (``formula.Grid``)."""
    import contourpy
    if grid.axes is None or len(grid.axes) != 2:
        raise ValueError('contours need a two-axis product grid')
    names = [a['name'] for a in grid.axes]
    if {x, y} != set(names):
        raise ValueError('contour axes must be the two grid axes')
    z = np.asarray(values, float)
    if names[0] == x:  # values indexed [x, y]; contourpy wants [y, x]
        z = z.T
    xs = grid.axes[names.index(x)]['values']
    ys = grid.axes[names.index(y)]['values']
    masked = np.ma.masked_invalid(z)
    generator = contourpy.contour_generator(xs, ys, masked, line_type='Separate')
    return [np.asarray(line, float) for line in generator.lines(level) if len(line) >= 2]


def series(lines, *, identifier, label):
    """Contour lines as plot-coordinate-series rows (one polyline per connected line)."""
    rows = []
    for k, line in enumerate(lines):
        rows.append({'id': f'{identifier}-{k + 1}', 'label': label if k == 0 else f'{label} ({k + 1})',
                     'geometry': 'polyline',
                     'records': [{'id': f'p{i}', 'x': float(px), 'y': float(py), 'status': 'delivered'}
                                 for i, (px, py) in enumerate(line)]})
    return rows


def coordinate_document(rows, *, x_axis, y_axis, basis):
    """A complete plot-coordinate-series document when the physics basis is declared."""
    return {'schema_version': 1, 'kind': 'plot-coordinate-series', 'basis': basis,
            'axes': {'x': x_axis, 'y': y_axis}, 'series': rows}
