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


def irregular_lines(coordinates, values, level):
    """Exact level segments of a linear field on a Delaunay triangulation.

    Segments stay in individual triangles, hence never leave the convex hull.
    Vertex indices refer to the supplied point order; no smoothing or extrapolation.
    """
    from scipy.spatial import Delaunay, QhullError
    xy, z = np.asarray(coordinates, float), np.asarray(values, float)
    if xy.ndim != 2 or xy.shape[1] != 2 or z.shape != (len(xy),):
        raise ValueError('irregular contour needs coordinate pairs and one value per point')
    if not np.all(np.isfinite(xy)) or not np.all(np.isfinite(z)) or not np.isfinite(level):
        raise ValueError('irregular contour inputs must be finite')
    if len(np.unique(xy, axis=0)) != len(xy):
        raise ValueError('duplicate contour coordinates')
    if len(xy) < 3 or np.linalg.matrix_rank(xy - xy[0]) < 2:
        raise ValueError('irregular contour needs at least three non-collinear points')
    try:
        tri = Delaunay(xy)
    except QhullError as exc:
        raise ValueError('irregular contour triangulation failed') from exc
    segments, seen = [], set()
    for triangle in tri.simplices:
        hits = []
        for i, j in ((triangle[0], triangle[1]), (triangle[1], triangle[2]), (triangle[2], triangle[0])):
            a, b = z[i] - level, z[j] - level
            if a == 0:
                hits.append(xy[i])
            if b == 0:
                hits.append(xy[j])
            if (a < 0 < b) or (b < 0 < a):
                hits.append(xy[i] + (-a / (b - a)) * (xy[j] - xy[i]))
        hits = np.unique(np.asarray(hits).reshape(-1, 2), axis=0)
        if len(hits) == 3:
            raise ValueError('contour level equals a whole triangle; level set is not a line')
        if len(hits) == 2:
            key = tuple(sorted(map(tuple, hits)))
            if key not in seen:
                seen.add(key)
                segments.append(hits)
    return segments, {'coordinates': xy.tolist(), 'simplices': tri.simplices.tolist(),
                      'convex_hull': tri.convex_hull.tolist(), 'extrapolation': False}


def interpolation_coordinates(spec, points):
    """Declared axes or affine coordinates (including differences); never evaluate code."""
    interpolation = spec.get('interpolation')
    if interpolation is None:
        return np.asarray([[p['coordinates'][spec['x']], p['coordinates'][spec['y']]] for p in points], float)
    if type(interpolation) is not dict or set(interpolation) - {'method', 'coordinates'}:
        raise ValueError('interpolation needs method and optional coordinates')
    if interpolation.get('method') != 'delaunay-linear':
        raise ValueError('interpolation method must be delaunay-linear')
    coordinates = interpolation.get('coordinates', [spec['x'], spec['y']])
    if type(coordinates) is not list or len(coordinates) != 2:
        raise ValueError('interpolation coordinates must contain two names or affine maps')
    def value(raw, point):
        if type(raw) is str:
            return float(point[raw])
        if type(raw) is not dict or set(raw) != {'terms', 'offset'} or type(raw['terms']) is not dict or not raw['terms']:
            raise ValueError('an affine coordinate needs terms and offset')
        numbers = [raw['offset'], *raw['terms'].values()]
        if any(type(v) not in (float, int) or not np.isfinite(v) for v in numbers):
            raise ValueError('affine coefficients must be finite numbers')
        return raw['offset'] + sum(v * point[k] for k, v in raw['terms'].items())
    return np.asarray([[value(c, p['coordinates']) for c in coordinates] for p in points], float)
