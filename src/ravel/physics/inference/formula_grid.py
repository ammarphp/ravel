"""Science mode ``formula-grid``: evaluate declared formulas over a parameter grid.

Input document (``kind: formula-grid``)::

    {"schema_version": 1, "kind": "formula-grid",
     "grid": {"axes": [{"name": "M", "unit": "GeV", "label": "Mediator mass", "min": 500, "max": 3000, "points": 26}]},
     "program": {"constants": [...], "definitions": [...], "outputs": [...]},
     "contours": [{"output": "...", "levels": [2.0], "x": "...", "y": "..."}]}

Constants are ``cited`` (with a citation) or ``requester-assumption`` (with the
requester's statement). Every output is reported on the grid; nonfinite points
are listed. Contours need a two-axis product grid.
"""
from __future__ import annotations

import numpy as np

from . import common, contours, formula, record

MODE = 'formula-grid'


def validate(task):
    common.validate(task)


def load(task, base):
    ctx, doc = common.context(task, base, MODE)
    allowed = {'schema_version', 'kind', 'description', 'grid', 'program', 'contours'}
    if set(doc) - allowed or not {'grid', 'program'} <= set(doc):
        raise ValueError('formula-grid documents have grid, program and optional contours')
    grid = formula.grid(doc['grid'])
    program = formula.Program(doc['program'], grid.parameters)
    requests = doc.get('contours') or []
    for c in requests:
        if type(c) is not dict or set(c) != {'output', 'levels', 'x', 'y'} or c['output'] not in program.labels:
            raise ValueError('contours need output, levels, x and y naming a declared output and grid axes')
    return ctx, doc, grid, program, requests


def inputs(task, base):
    return common.inputs(load(task, base)[0])


def evaluate(grid, program, requests):
    values = program.evaluate(grid.columns)
    results = []
    for name, _ in program.outputs:
        bad = formula.nonfinite_points(values[name])
        results.append(record.result('grid-values', 'primary', name=name, label=program.labels[name],
                                     unit=program.units[name], values=values[name], nonfinite_points=bad,
                                     summary=f'{program.labels[name]} evaluated at {grid.size} grid points'
                                             + (f' ({len(bad)} nonfinite)' if bad else '')))
    for c in requests:
        for level in c['levels']:
            lines = contours.level_lines(grid, values[c['output']], float(level), x=c['x'], y=c['y'])
            results.append(record.result('contour', 'primary', output=c['output'], level=float(level),
                                         x=c['x'], y=c['y'],
                                         series=contours.series(lines, identifier=f'{c["output"]}-{level:g}',
                                                                label=f'{program.labels[c["output"]]} = {level:g}'),
                                         summary=f'{program.labels[c["output"]]} = {level:g}: {len(lines)} contour line(s)'))
    return values, results


def run(task, base, output):
    ctx, doc, grid, program, requests = load(task, base)
    _, results = evaluate(grid, program, requests)
    inference = record.build(
        mode=MODE, engine='formula-grid', statistic=record.statistic('not-applicable'),
        parameters=[{**p, 'label': p.get('label', p['name'])} for p in grid.parameters], results=results,
        grid=grid.describe(), inputs=ctx.inputs(), requester_assumptions=program.requester_assumptions(),
        diagnostics={'cited_constants': program.citations(), 'units': program.units},
        limitations=['Formulas, constants and units are as declared; units are labels, not checked dimensions.'])
    return common.deliver(output, inference, review=ctx.review, scope='Declared closed-form formulas evaluated on the declared grid')
