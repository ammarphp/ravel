"""A small, closed expression language for selections and derived quantities.

Expressions are parsed with Python's grammar and then restricted to: numbers, the
names the caller allows, arithmetic (+ - * / ** %), comparisons (including chains such
as ``80 < mll < 100``), ``and``/``or``/``not`` and a fixed set of element-wise functions.
Nothing else is accepted: no attributes, indexing, strings, conditionals or other calls.
Evaluation is element-wise on NumPy arrays (one value per event) or Awkward arrays (one
value per object).

A *cut* is an expression with a true/false value. Where any name it uses is undefined
(NaN) the cut fails, whatever the expression says; ``not (x > 1)`` therefore does not
pass an event without ``x``.
"""
import ast

import awkward as ak
import numpy as np

MAX_LENGTH = 4000
FUNCTIONS = {
    'abs': np.abs, 'sqrt': np.sqrt, 'log': np.log, 'log10': np.log10, 'exp': np.exp,
    'sin': np.sin, 'cos': np.cos, 'tan': np.tan, 'sinh': np.sinh, 'cosh': np.cosh, 'tanh': np.tanh,
    'arctan2': np.arctan2, 'floor': np.floor, 'ceil': np.ceil,
    'min': np.minimum, 'max': np.maximum,
}
ARITY = {'arctan2': 2, 'min': 2, 'max': 2}
_BINARY = {ast.Add: np.add, ast.Sub: np.subtract, ast.Mult: np.multiply, ast.Div: np.true_divide,
           ast.Pow: np.power, ast.Mod: np.mod}
_COMPARE = {ast.Lt: np.less, ast.LtE: np.less_equal, ast.Gt: np.greater, ast.GtE: np.greater_equal,
            ast.Eq: np.equal, ast.NotEq: np.not_equal}


class Expression:
    def __init__(self, text, tree, names):
        self.text, self._tree, self.names = text, tree, frozenset(names)

    def __repr__(self):
        return f'Expression({self.text!r})'

    def evaluate(self, namespace):
        with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
            return _eval(self._tree.body, namespace)

    def defined(self, namespace):
        """True where every referenced name has a value (not NaN)."""
        mask = None
        for name in sorted(self.names):
            value = namespace[name]
            ok = ~np.isnan(value) if _is_float(value) else _true_like(value)
            mask = ok if mask is None else mask & ok
        return mask

    def evaluate_cut(self, namespace):
        value = self.evaluate(namespace)
        if not _is_bool(value):
            raise ValueError(f'selection {self.text!r} must evaluate to true/false values')
        mask = self.defined(namespace)
        return value if mask is None else value & mask


def _is_float(value):
    if isinstance(value, ak.Array):
        return np.issubdtype(_leaf_dtype(value), np.floating)
    return np.issubdtype(np.asarray(value).dtype, np.floating)


def _is_bool(value):
    if isinstance(value, ak.Array):
        return _leaf_dtype(value) == np.bool_
    return np.asarray(value).dtype == np.bool_


def _leaf_dtype(array):
    layout = ak.to_layout(array)
    while not hasattr(layout, 'dtype'):
        layout = layout.content
    return layout.dtype


def _true_like(value):
    return value == value


def _eval(node, ns):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return ns[node.id]
    if isinstance(node, ast.BinOp):
        return _BINARY[type(node.op)](_eval(node.left, ns), _eval(node.right, ns))
    if isinstance(node, ast.UnaryOp):
        operand = _eval(node.operand, ns)
        if isinstance(node.op, ast.Not):
            return ~_as_bool(operand)
        return np.negative(operand) if isinstance(node.op, ast.USub) else operand
    if isinstance(node, ast.BoolOp):
        values = [_as_bool(_eval(v, ns)) for v in node.values]
        out = values[0]
        for v in values[1:]:
            out = (out & v) if isinstance(node.op, ast.And) else (out | v)
        return out
    if isinstance(node, ast.Compare):
        left, out = _eval(node.left, ns), None
        for op, right_node in zip(node.ops, node.comparators):
            right = _eval(right_node, ns)
            part = _COMPARE[type(op)](left, right)
            out = part if out is None else out & part
            left = right
        return out
    if isinstance(node, ast.Call):
        return FUNCTIONS[node.func.id](*[_eval(a, ns) for a in node.args])
    raise ValueError('unsupported expression element')            # unreachable after validation


def _as_bool(value):
    if isinstance(value, (bool, np.bool_)):
        return np.bool_(value)
    if isinstance(value, ak.Array) or np.asarray(value).dtype == np.bool_:
        return value
    raise ValueError('and/or/not need true/false operands')


def compile_expression(text, *, allowed):
    """Parse and validate `text`; `allowed` is the set of names it may use."""
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_LENGTH:
        raise ValueError('an expression must be nonempty text of at most 4000 characters')
    try:
        tree = ast.parse(text.strip(), mode='eval')
    except SyntaxError as exc:
        raise ValueError(f'expression {text!r} is not valid: {exc.msg}') from None
    names = set()

    def check(node):
        if isinstance(node, ast.Constant):
            if type(node.value) not in (int, float, bool):
                raise ValueError(f'expression {text!r}: only numeric and true/false constants are allowed')
            return
        if isinstance(node, ast.Name):
            if node.id in ('True', 'False'):
                return
            if node.id not in allowed:
                raise ValueError(f'expression {text!r} uses unknown name {node.id!r}; known: {sorted(allowed)}')
            names.add(node.id)
            return
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            check(node.left); check(node.right); return
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.USub, ast.UAdd)):
            check(node.operand); return
        if isinstance(node, ast.BoolOp):
            for v in node.values:
                check(v)
            return
        if isinstance(node, ast.Compare) and all(type(op) in _COMPARE for op in node.ops):
            check(node.left)
            for c in node.comparators:
                check(c)
            return
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS
                and not node.keywords and len(node.args) == ARITY.get(node.func.id, 1)):
            for a in node.args:
                check(a)
            return
        raise ValueError(f'expression {text!r} contains an unsupported element ({type(node).__name__}); '
                         'use numbers, declared names, arithmetic, comparisons, and/or/not and '
                         + ', '.join(sorted(FUNCTIONS)))
    check(tree.body)
    return Expression(text.strip(), tree, names)
