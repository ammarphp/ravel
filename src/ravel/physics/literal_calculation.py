"""Exact, finite unit-bearing arithmetic from the complete original request.

The ordinary science plan, CHECK-IN 1 and supervised worker own execution.
No Python eval, supplied code execution or statistical calibration is performed.
Decimal literals are exact rational inputs. Units written in the request are
tracked as length, time and energy dimensions with exact rational factors.
"""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re

from ravel.workflow.task_completion import _Inputs, _contract, initial_requirements

SCOPE = 'complete_literal_dimensionless_calculation'
MAX_EXPRESSION = 1024
MAX_NODES = 128
MAX_BITS = 4096


VERBS = r'\s*(?:(?:compute|calculate|evaluate|simplify|convert)\s+|what is\s+)(.+?)[?.]?\s*'

# Exact rational unit factors relative to the base units m, s and eV. Natural-unit
# conversions (hbar, c) are not rational and are therefore not performed.
_UNITS = {}
for _name, _factor, _dims in (
        ('m', 1, (1, 0, 0)), ('km', 1000, (1, 0, 0)), ('cm', Fraction(1, 100), (1, 0, 0)),
        ('mm', Fraction(1, 10**3), (1, 0, 0)), ('um', Fraction(1, 10**6), (1, 0, 0)),
        ('nm', Fraction(1, 10**9), (1, 0, 0)), ('fm', Fraction(1, 10**15), (1, 0, 0)),
        ('b', Fraction(1, 10**28), (2, 0, 0)), ('mb', Fraction(1, 10**31), (2, 0, 0)),
        ('ub', Fraction(1, 10**34), (2, 0, 0)), ('nb', Fraction(1, 10**37), (2, 0, 0)),
        ('pb', Fraction(1, 10**40), (2, 0, 0)), ('fb', Fraction(1, 10**43), (2, 0, 0)),
        ('ab', Fraction(1, 10**46), (2, 0, 0)),
        ('s', 1, (0, 1, 0)), ('ms', Fraction(1, 10**3), (0, 1, 0)), ('us', Fraction(1, 10**6), (0, 1, 0)),
        ('ns', Fraction(1, 10**9), (0, 1, 0)), ('ps', Fraction(1, 10**12), (0, 1, 0)),
        ('fs', Fraction(1, 10**15), (0, 1, 0)), ('min', 60, (0, 1, 0)), ('hour', 3600, (0, 1, 0)),
        ('day', 86400, (0, 1, 0)),
        ('eV', 1, (0, 0, 1)), ('keV', 10**3, (0, 0, 1)), ('MeV', 10**6, (0, 0, 1)),
        ('GeV', 10**9, (0, 0, 1)), ('TeV', 10**12, (0, 0, 1)), ('PeV', 10**15, (0, 0, 1))):
    _UNITS[_name] = (Fraction(_factor), _dims)
_ALIASES = {'μm': 'um', 'µm': 'um', 'μb': 'ub', 'µb': 'ub', 'μs': 'us', 'µs': 'us', 'barn': 'b',
            'sec': 's', 'hours': 'hour', 'days': 'day'}
_COUNTS = {'events': 'events', 'event': 'events', 'dimensionless': '1', '1': '1'}
_SUPERSCRIPT = str.maketrans('⁻⁰¹²³⁴⁵⁶⁷⁸⁹', '-0123456789')
_TOKEN = re.compile(r"""\s*(?:
    (?P<number>(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?)
  | (?P<op>\*\*|->|→|[-+*/^()×·])
  | (?P<word>[A-Za-zμµ]+)
  | (?P<super>[⁻⁰¹²³⁴⁵⁶⁷⁸⁹]+)
)""", re.X)
_CLAUSE = re.compile(r"""^(?P<expr>.+?)
  (?:\s*,?\s*(?:and\s+)?(?:give|express|report|return|state|quote)\s+(?:the\s+)?(?:result|answer|value|number)\s+
       (?:in\s+units\s+of|with\s+units\s+of|in|as)
    |\s*,?\s*expressed\s+in
    |\s+in\s+units\s+of|\s+with\s+units\s+of|\s+in|\s+to|\s+as|\s*->|\s*→)
  \s+(?P<target>[^,]+?)\s*$""", re.X | re.I | re.S)


class _Quantity:
    __slots__ = ('value', 'dims')

    def __init__(self, value, dims=(0, 0, 0)):
        self.value, self.dims = value, tuple(dims)


def _bounded(value):
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > MAX_BITS:
        raise ValueError('exact rational representation exceeds4096bits')
    return value


def _tokens(text):
    position, out = 0, []
    while text[position:].strip():
        match = _TOKEN.match(text, position)
        if match is None or match.end() == position:
            raise ValueError('only literal numbers, units and arithmetic operators are supported')
        position = match.end()
        kind = match.lastgroup
        token = match.group(kind)
        if kind == 'super':
            out.extend([('op', '^'), ('number', token.translate(_SUPERSCRIPT).lstrip('-'))])
            if token.startswith('⁻'):
                out.insert(len(out) - 1, ('op', '-'))
        elif kind == 'word' and token.lower() == 'times':
            out.append(('op', '*'))
        else:
            out.append((kind, token))
        if len(out) > MAX_NODES:
            raise ValueError('arithmetic syntax exceeds declared finite node bound')
    return out


def _unit(word):
    name = _ALIASES.get(word, word)
    if name not in _UNITS:
        raise ValueError('unknown unit: ' + word)
    return name


def _render(names):
    return ' '.join(name if power == 1 else name + '^' + str(power) for name, power in names)


class _Parser:
    def __init__(self, tokens):
        self.tokens, self.i, self.literal_units = tokens, 0, []

    def peek(self, offset=0):
        j = self.i + offset
        return self.tokens[j] if j < len(self.tokens) else (None, None)

    def take(self):
        token = self.peek()
        self.i += 1
        return token

    def done(self):
        return self.i >= len(self.tokens)

    def is_unit(self, offset=0):
        kind, token = self.peek(offset)
        return kind == 'word' and _ALIASES.get(token, token) in _UNITS

    def exponent(self):
        sign = 1
        if self.peek() in (('op', '-'), ('op', '+')):
            sign = -1 if self.take()[1] == '-' else 1
        if self.peek() == ('op', '('):
            self.take()
            value = self.exponent()
            if self.take() != ('op', ')'):
                raise ValueError('unbalanced exponent parenthesis')
            return sign * value
        kind, token = self.take()
        if kind != 'number' or not re.fullmatch(r'[0-9]+', token or ''):
            raise ValueError('bounded integer exponent from-16to16 required')
        value = sign * int(token)
        if not -16 <= value <= 16:
            raise ValueError('bounded integer exponent from-16to16 required')
        return value

    def unit_sequence(self):
        """Juxtaposed unit factors, each with an optional integer exponent."""
        factor, dims, names = Fraction(1), (0, 0, 0), []
        while True:
            if self.is_unit():
                name, power = _unit(self.take()[1]), 1
            elif self.peek() == ('op', '/') and self.is_unit(1):
                self.take()
                name, power = _unit(self.take()[1]), -1
            else:
                break
            if self.peek() in (('op', '^'), ('op', '**')):
                self.take()
                power *= self.exponent()
            elif (self.peek() == ('op', '-') and self.peek(1) == ('number', '1')
                    and self.peek(2)[0] not in ('number', 'word')):
                # HEP convention: "fb-1" is fb^-1 when nothing operand-like follows.
                self.take(); self.take()
                power = -power
            unit_factor, unit_dims = _UNITS[name]
            factor *= unit_factor ** power
            dims = tuple(d + power * u for d, u in zip(dims, unit_dims))
            names.append((name, power))
        return (factor, dims, names) if names else None

    def expr(self):
        left = self.term()
        while self.peek() in (('op', '+'), ('op', '-')):
            op = self.take()[1]
            right = self.term()
            if left.dims != right.dims:
                raise ValueError('addition requires matching physical dimensions')
            left = _Quantity(_bounded(left.value + right.value if op == '+' else left.value - right.value), left.dims)
        return left

    def term(self):
        left = self.factor()
        while self.peek() in (('op', '*'), ('op', '/'), ('op', '×'), ('op', '·')):
            op = self.take()[1]
            right = self.factor()
            if op == '/':
                if not right.value:
                    raise ValueError('division by zero is undefined')
                left = _Quantity(_bounded(left.value / right.value), tuple(a - b for a, b in zip(left.dims, right.dims)))
            else:
                left = _Quantity(_bounded(left.value * right.value), tuple(a + b for a, b in zip(left.dims, right.dims)))
        return left

    def factor(self):
        if self.peek() in (('op', '+'), ('op', '-')):
            op = self.take()[1]
            inner = self.factor()
            return inner if op == '+' else _Quantity(-inner.value, inner.dims)
        return self.power()

    def power(self):
        base = self.atom()
        if self.peek() in (('op', '^'), ('op', '**')):
            self.take()
            n = self.exponent()
            try:
                base = _Quantity(_bounded(base.value ** n), tuple(d * n for d in base.dims))
            except ZeroDivisionError as exc:
                raise ValueError('zero to negative power is undefined') from exc
        units = self.unit_sequence()
        if units is not None:
            factor, dims, names = units
            self.literal_units.append((dims, names))
            base = _Quantity(_bounded(base.value * factor), tuple(a + b for a, b in zip(base.dims, dims)))
        return base

    def atom(self):
        kind, token = self.peek()
        if kind == 'number':
            self.take()
            exponent = re.search(r'[eE]([-+]?[0-9]+)$', token)
            if exponent and abs(int(exponent.group(1))) > 1024:
                raise ValueError('decimal exponent exceeds finite arithmetic bound')
            return _Quantity(_bounded(Fraction(token)))
        if (kind, token) == ('op', '('):
            self.take()
            inner = self.expr()
            if self.take() != ('op', ')'):
                raise ValueError('unbalanced parenthesis')
            # A parenthesized dimensionful group may be raised to a power.
            if self.peek() in (('op', '^'), ('op', '**')):
                self.take()
                n = self.exponent()
                inner = _Quantity(_bounded(inner.value ** n), tuple(d * n for d in inner.dims))
            return inner
        if self.is_unit():
            return _Quantity(Fraction(1))
        raise ValueError('only finite literal rational arithmetic is supported')


def _target(text):
    text = text.strip()
    if text.lower() in _COUNTS:
        return (0, 0, 0), Fraction(1), _COUNTS[text.lower()]
    parser = _Parser(_tokens(text))
    units = parser.unit_sequence()
    if units is None or not parser.done():
        raise ValueError('result unit must be a product of known units')
    factor, dims, names = units
    return dims, factor, _render(names)


def _split_target(expression):
    match = _CLAUSE.match(expression)
    if match is None:
        return expression, None
    try:
        _target(match.group('target'))
    except ValueError:
        return expression, None
    return match.group('expr'), match.group('target').strip()


def _evaluate(expression):
    body, target = _split_target(expression)
    parser = _Parser(_tokens(body))
    if parser.done():
        raise ValueError('bounded complete arithmetic expression required')
    quantity = parser.expr()
    if not parser.done():
        raise ValueError('only finite literal rational arithmetic is supported')
    if target is not None:
        dims, factor, unit = _target(target)
        if dims != quantity.dims:
            raise ValueError('result unit has different physical dimensions; natural-unit conversions are not exact')
        return _bounded(quantity.value / factor), unit
    if quantity.dims == (0, 0, 0):
        return quantity.value, '1'
    for dims, names in parser.literal_units:
        if dims == quantity.dims:
            factor = Fraction(1)
            for name, power in names:
                factor *= _UNITS[name][0] ** power
            return _bounded(quantity.value / factor), _render(names)
    base = ('m', 's', 'eV')
    return quantity.value, _render([(base[i], d) for i, d in enumerate(quantity.dims) if d])


def _operation(text):
    match = re.fullmatch(VERBS, text, re.I | re.S)
    if match is None:
        return None
    value = match.group(1).strip()
    if not value or len(value) > MAX_EXPRESSION:
        return None
    try:
        _evaluate(value)
    except (ValueError, ZeroDivisionError, OverflowError, RecursionError):
        return None
    return value


def expression_from_prompt(prompt):
    if type(prompt) is not str:
        raise ValueError('literal original calculation request required')
    value = _operation(prompt)
    if value is None:
        # One authoritative full-context intent parser owns delegation semantics.
        # Its exact directive span is control intent; all remaining words must be
        # the complete operation. Quoted/negated/conditional authority is not cut.
        try:
            from ravel.workflow.scientific_autonomy import delegation_intent
        except ImportError as exc:
            raise ValueError('the shared full-context delegation parser is required for a nonliteral control clause') from exc
        span = delegation_intent(prompt)
        if span is not None:
            if (type(span) is not dict or set(span) != {'start', 'end', 'text'}
                    or type(span['start']) is not int or type(span['end']) is not int
                    or not 0 <= span['start'] < span['end'] <= len(prompt)
                    or prompt[span['start']:span['end']] != span['text']):
                raise ValueError('authoritative delegation span differs from complete original text')
            value = _operation(prompt[:span['start']] + prompt[span['end']:])
    if value is None:
        raise ValueError('complete request is not a literal arithmetic operation with known units')
    return value


def exact_value(expression):
    """Exact rational value and unit of a literal expression.

    Literals may carry HEP units (b to ab, fb^-1, eV to PeV, m, s and decimal
    prefixes). Dimensions are tracked exactly; sums require matching dimensions
    and a requested result unit must have the same dimensions as the value.
    """
    if type(expression) is not str or not 1 <= len(expression) <= MAX_EXPRESSION:
        raise ValueError('bounded expression required')
    try:
        value, unit = _evaluate(expression)
    except RecursionError as exc:
        raise ValueError('arithmetic syntax exceeds declared finite node bound') from exc
    return {'numerator': str(value.numerator), 'denominator': str(value.denominator),
            'unit': unit, 'representation': 'exact_rational', 'rounding': 'none'}


def validate(task):
    if type(task) is not dict or set(task) != {'parent_contract', 'expression', 'unit'} or type(task['unit']) is not str:
        raise ValueError('literal calculation requires exact parent pin, expression and result unit')
    if type(task['parent_contract']) is not dict or not Path(task['parent_contract'].get('path', '')).is_absolute():
        raise ValueError('absolute original parent contract pin required')
    if exact_value(task['expression'])['unit'] != task['unit']:
        raise ValueError('declared result unit differs from the exact unit of the expression')


def _capture(task, base):
    validate(task)
    inputs = _Inputs(base)
    try:
        contract, req, _, changes = _contract(task['parent_contract'], inputs)
        if contract['task_mode'] != 'calculation' or contract.get('intake', {}).get('kind') != 'calculation':
            raise ValueError('literal operation requires an actual calculation intake')
        if changes or req['obligations'] != initial_requirements(contract['prompt'])['obligations']:
            raise ValueError('compact arithmetic cannot discharge additional or amended scientific obligations')
        if expression_from_prompt(contract['prompt']) != task['expression']:
            raise ValueError('operation must consume the complete original numerical request')
        value = exact_value(task['expression'])
        inputs.finish()
        return inputs, contract, value
    except Exception:
        inputs.close(); raise


def validate_parent(task, base):
    """Authenticate the exact numerical parent; confer no approval or execution."""
    captured, contract, value = _capture(task, base)
    try:
        captured.finish()
        return {'parent_contract': deepcopy(task['parent_contract']),
                'original_request': contract['prompt'], 'expression': task['expression'],
                'unit': value['unit'], 'quantity': deepcopy(value), 'scope': SCOPE,
                'execution_authorized': False, 'physics_validated': False}
    finally: captured.close()


def inputs(task, base):
    captured, _, _ = _capture(task, base)
    try: return [Path(row['path']) for row in captured.pins.values()]
    finally: captured.close()


def run(task, base, output):
    captured, contract, value = _capture(task, base)
    try:
        result = {'schema_version': 1, 'kind': 'literal-calculation-result', 'status': 'passed',
            'status_scope': SCOPE, 'parent_contract': deepcopy(task['parent_contract']),
            'original_request': contract['prompt'], 'expression': task['expression'], 'quantity': value,
            'input_pins': deepcopy(list(captured.pins.values())), 'physics_validated': False,
            'calibration_claimed': False, 'limitations': ['Exact literal arithmetic with tracked units; natural-unit conversions, numerical models and calibrated inference need their own bound operations.']}
        captured.finish()
        return deepcopy(result)
    finally: captured.close()


def validate_result(result, task, base):
    captured, contract, value = _capture(task, base)
    try:
        expected = run(task, base, None)
        if type(result) is not dict or json.dumps(result, sort_keys=True, allow_nan=False) != json.dumps(expected, sort_keys=True, allow_nan=False):
            raise ValueError('calculation result differs from complete source-bound exact operation')
        captured.finish()
        return deepcopy(result)
    finally: captured.close()


class Publications:
    """Commit common worker products before emission and retain ending identity."""
    def __init__(self, output):
        self.observed = _Inputs(output)

    def json(self, path, value):
        from ravel.workflow.intake_planner import _write
        return _write(path, value, self.observed)

    def text(self, path, value):
        raw = value.encode('utf-8'); path = Path(path).absolute()
        pin = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
        with path.open('xb') as stream: stream.write(raw)
        self.observed.file(pin)

    def finish(self):
        try: self.observed.finish()
        finally: self.observed.close()
