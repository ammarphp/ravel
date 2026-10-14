"""Evaluate declared closed-form formulas over parameter grids.

The language is a restricted subset of Python expression syntax, checked node by
node before anything is evaluated. Nothing is passed to ``eval``. Allowed:

- numbers, declared names (parameters, constants, earlier definitions) and ``pi``;
- ``+ - * / ** %``, unary minus, comparisons, ``and``/``or``/``not``;
- ``a if condition else b`` (piecewise, evaluated elementwise);
- the functions in ``FUNCTIONS`` with fixed arity.

Constants carry a unit string and an origin: ``cited`` (with a citation) or
``requester-assumption`` (with the requester's statement). Units are carried as
declared labels; no dimensional algebra is attempted. Nonfinite results are
reported by index and never clipped.
"""
from __future__ import annotations

import ast
import math
import re

import numpy as np

MAX_EXPRESSION = 4000
MAX_NODES = 2000
MAX_GRID_POINTS = 1_000_000
NAME = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,63}')

FUNCTIONS = {
    'sqrt': (np.sqrt, 1), 'exp': (np.exp, 1), 'log': (np.log, 1), 'log10': (np.log10, 1),
    'sin': (np.sin, 1), 'cos': (np.cos, 1), 'tan': (np.tan, 1), 'asin': (np.arcsin, 1),
    'acos': (np.arccos, 1), 'atan': (np.arctan, 1), 'atan2': (np.arctan2, 2), 'sinh': (np.sinh, 1),
    'cosh': (np.cosh, 1), 'tanh': (np.tanh, 1), 'abs': (np.abs, 1), 'min': (np.minimum, 2),
    'max': (np.maximum, 2), 'pow': (np.power, 2), 'where': (np.where, 3),
}
BUILTIN_CONSTANTS = {'pi': math.pi}
RESERVED = set(FUNCTIONS) | set(BUILTIN_CONSTANTS)
ORIGINS = ('cited', 'requester-assumption')

_BINARY = {ast.Add: np.add, ast.Sub: np.subtract, ast.Mult: np.multiply, ast.Div: np.divide,
           ast.Pow: np.power, ast.Mod: np.mod}
_COMPARE = {ast.Lt: np.less, ast.LtE: np.less_equal, ast.Gt: np.greater, ast.GtE: np.greater_equal,
            ast.Eq: np.equal, ast.NotEq: np.not_equal}


def _text(value, label):
    if type(value) is not str or not value.strip():
        raise ValueError(label + ' must be nonblank text')
    return value


def _unit(value, label):
    if type(value) is not str:
        raise ValueError(label + ' must state a unit string ("" for dimensionless)')
    return value


def _name(value, label, taken):
    if type(value) is not str or not NAME.fullmatch(value):
        raise ValueError(label + ' must be a simple identifier')
    if value in RESERVED:
        raise ValueError(f'{label} {value!r} would redefine a built-in function or constant')
    if value in taken:
        raise ValueError(f'{label} {value!r} would redefine an existing name')
    return value


def _number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(label + ' must be a finite number')
    return float(value)


class Expression:
    """One checked expression; ``names`` are the free names it uses."""

    def __init__(self, source, known):
        _text(source, 'expression')
        if len(source) > MAX_EXPRESSION:
            raise ValueError('expression exceeds the length limit')
        try:
            tree = ast.parse(source, mode='eval')
        except SyntaxError as exc:
            raise ValueError(f'expression is not valid syntax: {exc.msg}') from None
        nodes = list(ast.walk(tree))
        if len(nodes) > MAX_NODES:
            raise ValueError('expression exceeds the node limit')
        self.source, self.tree, self.names = source, tree.body, set()
        self._check(tree.body, known)

    def _check(self, node, known):
        if isinstance(node, ast.Constant):
            if type(node.value) not in (int, float) or not math.isfinite(node.value):
                raise ValueError('only finite numeric literals are allowed')
        elif isinstance(node, ast.Name):
            if node.id in BUILTIN_CONSTANTS:
                return
            if node.id not in known:
                raise ValueError(f'expression uses undeclared name {node.id!r}')
            self.names.add(node.id)
        elif isinstance(node, ast.BinOp):
            if type(node.op) not in _BINARY:
                raise ValueError('operator is not allowed')
            self._check(node.left, known); self._check(node.right, known)
        elif isinstance(node, ast.UnaryOp):
            if type(node.op) not in (ast.USub, ast.UAdd, ast.Not):
                raise ValueError('unary operator is not allowed')
            self._check(node.operand, known)
        elif isinstance(node, ast.Compare):
            if any(type(op) not in _COMPARE for op in node.ops):
                raise ValueError('comparison is not allowed')
            for child in (node.left, *node.comparators):
                self._check(child, known)
        elif isinstance(node, ast.BoolOp):
            for child in node.values:
                self._check(child, known)
        elif isinstance(node, ast.IfExp):
            for child in (node.test, node.body, node.orelse):
                self._check(child, known)
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                raise ValueError('only the listed functions may be called')
            if node.keywords or any(isinstance(a, ast.Starred) for a in node.args):
                raise ValueError('function calls take positional arguments only')
            if len(node.args) != FUNCTIONS[node.func.id][1]:
                raise ValueError(f'{node.func.id} takes {FUNCTIONS[node.func.id][1]} argument(s)')
            for child in node.args:
                self._check(child, known)
        else:
            raise ValueError(f'syntax element {type(node).__name__} is not allowed')

    def evaluate(self, scope):
        with np.errstate(all='ignore'):
            return np.asarray(self._eval(self.tree, scope), dtype=float)

    def _eval(self, node, scope):
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            return BUILTIN_CONSTANTS[node.id] if node.id in BUILTIN_CONSTANTS else scope[node.id]
        if isinstance(node, ast.BinOp):
            return _BINARY[type(node.op)](self._eval(node.left, scope), self._eval(node.right, scope))
        if isinstance(node, ast.UnaryOp):
            value = self._eval(node.operand, scope)
            return (np.negative(value) if isinstance(node.op, ast.USub)
                    else np.logical_not(value) if isinstance(node.op, ast.Not) else value)
        if isinstance(node, ast.Compare):
            left, result = self._eval(node.left, scope), True
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval(comparator, scope)
                result = np.logical_and(result, _COMPARE[type(op)](left, right))
                left = right
            return result
        if isinstance(node, ast.BoolOp):
            values = [self._eval(v, scope) for v in node.values]
            combine = np.logical_and if isinstance(node.op, ast.And) else np.logical_or
            result = values[0]
            for value in values[1:]:
                result = combine(result, value)
            return result
        if isinstance(node, ast.IfExp):
            return np.where(self._eval(node.test, scope), self._eval(node.body, scope),
                            self._eval(node.orelse, scope))
        function = FUNCTIONS[node.func.id][0]
        return function(*[self._eval(a, scope) for a in node.args])


class Program:
    """Constants, ordered definitions and named outputs over declared parameters."""

    def __init__(self, spec, parameters):
        if type(spec) is not dict or not {'constants', 'definitions', 'outputs'} <= set(spec):
            raise ValueError('formula program needs constants, definitions and outputs')
        if set(spec) - {'constants', 'definitions', 'outputs'}:
            raise ValueError('formula program has unsupported fields')
        taken, self.units, self.constants = {}, {}, {}
        self.parameters = []
        for p in parameters:
            if type(p) is not dict or set(p) - {'name', 'unit', 'label'} or not {'name', 'unit'} <= set(p):
                raise ValueError('parameters need name, unit and optional label')
            _name(p['name'], 'parameter', taken)
            taken[p['name']] = 'parameter'; self.units[p['name']] = _unit(p['unit'], 'parameter unit')
            self.parameters.append(p['name'])
        self._constants = []
        for c in _list(spec['constants'], 'constants'):
            fields = {'name', 'value', 'unit', 'origin'}
            if type(c) is not dict or not fields <= set(c) or set(c) - fields - {'citation', 'statement'}:
                raise ValueError('constants need name, value, unit, origin and citation or statement')
            _name(c['name'], 'constant', taken)
            if c['origin'] not in ORIGINS:
                raise ValueError('constant origin must be cited or requester-assumption')
            if c['origin'] == 'cited' and (type(c.get('citation')) is not str or not c['citation'].strip()):
                raise ValueError(f'constant {c["name"]!r} is cited but has no citation')
            if c['origin'] == 'requester-assumption' and (type(c.get('statement')) is not str or not c['statement'].strip()):
                raise ValueError(f'constant {c["name"]!r} is a requester assumption without the requester statement')
            taken[c['name']] = 'constant'
            self.constants[c['name']] = _number(c['value'], 'constant value')
            self.units[c['name']] = _unit(c['unit'], 'constant unit')
            self._constants.append(dict(c))
        self.definitions = []
        for d in _list(spec['definitions'], 'definitions'):
            if type(d) is not dict or set(d) - {'name', 'expression', 'unit', 'label'} or not {'name', 'expression', 'unit'} <= set(d):
                raise ValueError('definitions need name, expression and unit')
            expression = Expression(d['expression'], set(taken))
            _name(d['name'], 'definition', taken)
            taken[d['name']] = 'definition'; self.units[d['name']] = _unit(d['unit'], 'definition unit')
            self.definitions.append((d['name'], expression))
        self.outputs, self.labels = [], {}
        outputs = _list(spec['outputs'], 'outputs')
        if not outputs:
            raise ValueError('at least one formula output is required')
        for o in outputs:
            if type(o) is not dict or set(o) != {'name', 'expression', 'unit', 'label'}:
                raise ValueError('outputs need name, expression, unit and a natural-language label')
            expression = Expression(o['expression'], set(taken))
            _name(o['name'], 'output', taken)
            taken[o['name']] = 'output'; self.units[o['name']] = _unit(o['unit'], 'output unit')
            self.labels[o['name']] = _text(o['label'], 'output label')
            self.outputs.append((o['name'], expression))

    def requester_assumptions(self):
        return [{'name': c['name'], 'value': c['value'], 'unit': c['unit'], 'statement': c['statement']}
                for c in self._constants if c['origin'] == 'requester-assumption']

    def citations(self):
        return [{'name': c['name'], 'value': c['value'], 'unit': c['unit'], 'citation': c['citation']}
                for c in self._constants if c['origin'] == 'cited']

    def evaluate(self, columns):
        missing = set(self.parameters) - set(columns)
        if missing:
            raise ValueError('missing parameter values: ' + ', '.join(sorted(missing)))
        scope = {name: np.asarray(columns[name], dtype=float) for name in self.parameters}
        scope.update(self.constants)
        shape = np.broadcast_shapes(*[np.shape(v) for v in scope.values()]) if scope else ()
        values = {}
        for name, expression in [*self.definitions, *self.outputs]:
            result = np.broadcast_to(expression.evaluate(scope), shape).copy()
            scope[name] = values[name] = result
        return values


def _list(value, label):
    if type(value) is not list:
        raise ValueError(label + ' must be a list')
    return value


def nonfinite_points(values):
    flat = np.asarray(values, dtype=float).ravel()
    return [int(i) for i in np.flatnonzero(~np.isfinite(flat))]


class Grid:
    """A product grid (``axes``) or an explicit point list (``points``)."""

    def __init__(self, parameters, columns, shape, axes):
        self.parameters, self.columns, self.shape, self.axes = parameters, columns, shape, axes

    @property
    def size(self):
        return int(np.prod(self.shape)) if self.shape else 1

    def describe(self):
        if self.axes is not None:
            return {'kind': 'product', 'axes': [{'name': a['name'], 'unit': a['unit'],
                                                 'label': a.get('label', a['name']),
                                                 'values': [float(v) for v in a['values']]} for a in self.axes]}
        return {'kind': 'points', 'parameters': self.parameters,
                'points': [{p['name']: float(self.columns[p['name']][i]) for p in self.parameters}
                           for i in range(self.size)]}


def _axis_values(axis):
    if 'values' in axis:
        if set(axis) - {'name', 'unit', 'label', 'values'}:
            raise ValueError('an axis lists values or min/max/points, not both')
        values = [_number(v, 'axis value') for v in _list(axis['values'], 'axis values')]
        if not values or len(values) != len(set(values)) or values != sorted(values):
            raise ValueError('axis values must be unique and increasing')
        return np.array(values)
    if set(axis) - {'name', 'unit', 'label', 'min', 'max', 'points', 'spacing'} or not {'min', 'max', 'points'} <= set(axis):
        raise ValueError('a range axis needs min, max, points and optional spacing')
    lo, hi, n = _number(axis['min'], 'axis min'), _number(axis['max'], 'axis max'), axis['points']
    if type(n) is not int or not 2 <= n <= MAX_GRID_POINTS or not lo < hi:
        raise ValueError('axis needs min < max and an integer point count within the grid limit')
    spacing = axis.get('spacing', 'linear')
    if spacing == 'linear':
        return np.linspace(lo, hi, n)
    if spacing == 'log':
        if lo <= 0:
            raise ValueError('log spacing needs a positive minimum')
        return np.geomspace(lo, hi, n)
    raise ValueError('axis spacing must be linear or log')


def grid(spec):
    if type(spec) is not dict:
        raise ValueError('grid must be an object')
    if 'axes' in spec:
        if set(spec) != {'axes'}:
            raise ValueError('a product grid has only axes')
        axes = []
        names = set()
        for axis in _list(spec['axes'], 'grid axes'):
            if type(axis) is not dict:
                raise ValueError('grid axes must be objects')
            name = _name(axis.get('name'), 'axis', names); names.add(name)
            _unit(axis.get('unit'), 'axis unit')
            axes.append({**axis, 'values': _axis_values(axis)})
        if not axes:
            raise ValueError('grid needs at least one axis')
        shape = tuple(len(a['values']) for a in axes)
        if int(np.prod(shape)) > MAX_GRID_POINTS:
            raise ValueError('grid exceeds the point limit')
        mesh = np.meshgrid(*[a['values'] for a in axes], indexing='ij')
        parameters = [{'name': a['name'], 'unit': a['unit'], **({'label': a['label']} if 'label' in a else {})} for a in axes]
        return Grid(parameters, {a['name']: m for a, m in zip(axes, mesh)}, shape, axes)
    if set(spec) != {'points', 'parameters'}:
        raise ValueError('grid needs axes, or points with parameters')
    parameters = _list(spec['parameters'], 'grid parameters')
    names = set()
    for p in parameters:
        if type(p) is not dict or not {'name', 'unit'} <= set(p) or set(p) - {'name', 'unit', 'label'}:
            raise ValueError('grid parameters need name and unit')
        _name(p['name'], 'parameter', names); names.add(p['name'])
    points = _list(spec['points'], 'grid points')
    if not 1 <= len(points) <= MAX_GRID_POINTS:
        raise ValueError('grid needs between one point and the point limit')
    columns = {}
    for p in parameters:
        if any(type(point) is not dict or set(point) != names for point in points):
            raise ValueError('every point must give exactly the declared parameters')
        columns[p['name']] = np.array([_number(point[p['name']], 'point value') for point in points])
    return Grid(parameters, columns, (len(points),), None)
