"""A parameter grid from declared axes, given as data (WALKTHROUGH Δ-Wa4, SG-15).

The recipe states each axis by name, unit and either an explicit ordered list of values or
a range (``min``, ``max``, ``steps`` and ``spacing`` linear or log). Nothing here knows a
model family: axis names are the requester's own words, and the recipe never supplies an
axis, a unit or a value the recipe does not state. ``points`` expands the grid (the
Cartesian product in axis order, or ``combine: "zip"`` for paired lists), ``fan_out_axes``
returns the axes in the request plan's ``fan_out`` shape, and ``document`` returns the
grid artifact with the hash of its recipe::

    {"schema_version": 1, "kind": "grid-recipe",
     "axes": [{"name": "<axis>", "unit": "<unit or null>", "values": [...]},
              {"name": "<axis>", "unit": "<unit or null>",
               "range": {"min": 1, "max": 100, "steps": 5, "spacing": "log"}}],
     "combine": "product"}
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys

SCHEMA_VERSION = 1
KIND = 'grid-recipe'
GRID_KIND = 'parameter-grid'
COMBINE = ('product', 'zip')
SPACING = ('linear', 'log')
MAX_AXES = 8
MAX_POINTS = 10000
MAX_STEPS = 1000


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def errors(recipe):
    """Structural errors in a grid recipe; [] when it is complete."""
    if not isinstance(recipe, dict):
        return ['a grid recipe is a JSON object']
    found = []
    if recipe.get('schema_version') != SCHEMA_VERSION or recipe.get('kind') != KIND:
        found.append(f'a grid recipe has schema_version {SCHEMA_VERSION} and kind {KIND}')
    extra = set(recipe) - {'schema_version', 'kind', 'axes', 'combine', 'description'}
    if extra:
        found.append(f'unknown recipe fields: {sorted(extra)}')
    combine = recipe.get('combine', 'product')
    if combine not in COMBINE:
        found.append(f'combine is one of {COMBINE}')
    axes = recipe.get('axes')
    if not isinstance(axes, list) or not 1 <= len(axes) <= MAX_AXES:
        return found + [f'a grid recipe declares 1 to {MAX_AXES} axes']
    names = []
    for i, axis in enumerate(axes):
        where = f'axis {i + 1}'
        if not isinstance(axis, dict):
            found.append(f'{where} is an object')
            continue
        name = axis.get('name')
        if not isinstance(name, str) or not name.strip():
            found.append(f'{where} has a name')
        names.append(name)
        if 'unit' not in axis or not (axis['unit'] is None or isinstance(axis['unit'], str)):
            found.append(f'{where} states its unit (a string, or null for a dimensionless axis)')
        if set(axis) - {'name', 'unit', 'values', 'range', 'description'}:
            found.append(f'{where} has unknown fields: {sorted(set(axis) - {"name", "unit", "values", "range", "description"})}')
        if ('values' in axis) == ('range' in axis):
            found.append(f'{where} states either values or a range')
        elif 'values' in axis:
            values = axis['values']
            if not isinstance(values, list) or not values or not all(_number(v) for v in values):
                found.append(f'{where} values are a nonempty list of finite numbers')
            elif len(set(values)) != len(values):
                found.append(f'{where} values are distinct')
        else:
            found += _range_errors(where, axis['range'])
    if len([n for n in names if isinstance(n, str)]) != len({n for n in names if isinstance(n, str)}):
        found.append('axis names are distinct')
    if not found:
        sizes = [len(_values(a)) for a in axes]
        if combine == 'zip' and len(set(sizes)) != 1:
            found.append('combine "zip" needs axes of equal length')
        total = sizes[0] if combine == 'zip' else math.prod(sizes)
        if total > MAX_POINTS:
            found.append(f'the grid has {total} points; at most {MAX_POINTS}')
    return found


def _range_errors(where, spec):
    if not isinstance(spec, dict) or set(spec) - {'min', 'max', 'steps', 'spacing'}:
        return [f'{where} range has min, max, steps and optional spacing']
    found = []
    low, high, steps = spec.get('min'), spec.get('max'), spec.get('steps')
    spacing = spec.get('spacing', 'linear')
    if not (_number(low) and _number(high) and low < high):
        found.append(f'{where} range has finite min < max')
    if type(steps) is not int or not 2 <= steps <= MAX_STEPS:
        found.append(f'{where} range has an integer number of steps from 2 to {MAX_STEPS}')
    if spacing not in SPACING:
        found.append(f'{where} range spacing is one of {SPACING}')
    elif spacing == 'log' and _number(low) and low <= 0:
        found.append(f'{where} log range needs min > 0')
    return found


def _values(axis):
    if 'values' in axis:
        return list(axis['values'])
    spec = axis['range']
    low, high, steps = spec['min'], spec['max'], spec['steps']
    if spec.get('spacing', 'linear') == 'log':
        a, b = math.log10(low), math.log10(high)
        values = [10 ** (a + (b - a) * k / (steps - 1)) for k in range(steps)]
    else:
        values = [low + (high - low) * k / (steps - 1) for k in range(steps)]
    values[0], values[-1] = low, high
    return values


def _checked(recipe):
    found = errors(recipe)
    if found:
        raise ValueError('grid recipe: ' + '; '.join(found))
    return recipe


def axes(recipe):
    """The declared axes with their expanded values: [{name, unit, values}]."""
    _checked(recipe)
    return [{'name': a['name'], 'unit': a['unit'], 'values': _values(a)} for a in recipe['axes']]


def points(recipe):
    """The grid points in order: a list of {axis name: value}."""
    expanded = axes(recipe)
    names = [a['name'] for a in expanded]
    columns = [a['values'] for a in expanded]
    rows = zip(*columns) if recipe.get('combine', 'product') == 'zip' else itertools.product(*columns)
    return [dict(zip(names, row)) for row in rows]


def fan_out_axes(recipe, facts=None):
    """The axes in the request plan's ``fan_out.axes`` shape; ``facts`` maps an axis name to its reading fact id."""
    facts = facts or {}
    return [{'name': a['name'], 'unit': a['unit'], 'values': a['values'], 'fact': facts.get(a['name'])}
            for a in axes(recipe)]


def recipe_sha256(recipe):
    return hashlib.sha256(json.dumps(recipe, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def document(recipe):
    """The parameter-grid artifact: declared axes, ordered points and the recipe hash."""
    return {'schema_version': SCHEMA_VERSION, 'kind': GRID_KIND, 'recipe_sha256': recipe_sha256(_checked(recipe)),
            'combine': recipe.get('combine', 'product'), 'axes': axes(recipe), 'points': points(recipe)}


def main(argv=None):
    ap = argparse.ArgumentParser(prog='grid_recipe', description='Expand a declared-axes grid recipe.')
    ap.add_argument('recipe', type=Path)
    ap.add_argument('--check', action='store_true', help='only report recipe errors')
    args = ap.parse_args(argv)
    recipe = json.loads(args.recipe.read_text())
    found = errors(recipe)
    if found or args.check:
        for error in found:
            print(error, file=sys.stderr)
        return 1 if found else 0
    print(json.dumps(document(recipe), indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
