"""Stage 'calc': an evidence-binding arithmetic record over bound artifact values (WP12 design §3.3).

The broker resolves each binding (a name, an artifact handle and a field of that artifact's content) to its
value, refuses a null value or a limit whose status is not ``resolved``, checks the expression, and places
the request as ``inputs/params.json``: ``{expression, bindings: [{name, handle, field, value}], unit,
label}``. This worker, which runs only under the RAVEL stage supervisor, checks the request again,
evaluates it and writes ``outputs/calc/calc.json``: the expression, the bindings, the literal, the
declared unit, the label and the result. The broker records the union of the bound artifacts'
``derived_from`` beside it.

The grammar combines the bound values as plain numbers; there is no dimensional analysis, and the declared
unit is a label, never checked:

    expression := factor (("*" | "/") factor)*
    factor     := name | "sqrt(" expression ")" | "(" expression ")" | literal
    literal    := "10^" k  or  "10^(" k ")",  k an integer from -6 to 6 ("-" only as its sign)

- Only products and quotients: no "+", no "-" (a minus sign is allowed only as the sign of a literal's
  exponent), no other operator and no number other than one power of ten.
- At most one literal, used as a multiplicative factor: at the top level of the expression (never inside
  parentheses or sqrt, where it would form a literal-only subexpression) and never directly after "/"
  (write 10^-3, not / 10^3).
- Every parenthesized group, every sqrt argument and the expression itself contain a bound name, so no
  subexpression is literal-only.
- Every name is bound and every binding is used; ``sqrt`` is not a name.

Evaluation is exact (fractions.Fraction of the bound floats and the literal) except sqrt, which takes the
float square root of its argument; the result is its nearest float. A zero divisor, the square root of a
negative number or a non-finite result fails the stage. Standard library only; the broker imports the
checking functions from this module.
"""
import math
import os
import re
import sys
from fractions import Fraction
from pathlib import Path

STAGE = "calc"
UNITS = ("events", "fb", "pb", "fb^-1", "pb^-1", "GeV", "dimensionless")
MAX_EXPRESSION = 512
MAX_BINDINGS = 16
MAX_LABEL = 200
EXPONENTS = range(-6, 7)
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
FIELD = re.compile(r"([A-Za-z_][A-Za-z0-9_]{0,63})(?:\[([0-9])\])?")
_TOKEN = re.compile(r"\s*(?:(?P<literal>10\^(?:\((?P<pk>-?[0-9]+)\)|(?P<k>-?[0-9]+)))"
                    r"|(?P<name>[A-Za-z_][A-Za-z0-9_]*)|(?P<op>[*/()])|(?P<other>\S))")


class CalcError(ValueError):
    """An expression or request outside the grammar (a subject-visible message)."""


def tokens(expression):
    """[(kind, text, exponent)] of an expression; CalcError for anything outside the token set."""
    if not isinstance(expression, str) or not expression.strip():
        raise CalcError("the expression must be nonblank text")
    if len(expression) > MAX_EXPRESSION:
        raise CalcError(f"the expression is longer than {MAX_EXPRESSION} characters")
    found, at = [], 0
    while at < len(expression):
        match = _TOKEN.match(expression, at)
        if match is None:           # only trailing whitespace is left
            break
        at = match.end()
        if match.group("literal"):
            k = int(match.group("pk") if match.group("pk") is not None else match.group("k"))
            if k not in EXPONENTS:
                raise CalcError("a literal is a power of ten 10^k with k from -6 to 6")
            found.append(("literal", match.group("literal"), k))
        elif match.group("name"):
            found.append(("name", match.group("name"), None))
        elif match.group("op"):
            found.append(("op", match.group("op"), None))
        else:
            char = match.group("other")
            if char == "+":
                raise CalcError("addition is not supported: only products and quotients of bound values")
            if char == "-":
                raise CalcError("subtraction and negation are not supported: only products and quotients of "
                                "bound values (a minus sign may only be the sign of a literal's exponent)")
            if char.isdigit() or char == ".":
                raise CalcError("the only number allowed is one power of ten, 10^k with k from -6 to 6")
            if char == "^":
                raise CalcError("^ appears only in the literal 10^k")
            raise CalcError(f"unsupported character {char!r}")
    return found


def parse(expression):
    """The syntax tree of an expression, checked against the grammar (module docstring); CalcError otherwise.

    Nodes: ("name", text), ("literal", k), ("sqrt", node), ("group", node), ("product", [(op, node), ...])
    where the first op is "*"."""
    items, at = tokens(expression), 0

    def peek():
        return items[at] if at < len(items) else (None, None, None)

    def take(text):
        nonlocal at
        if peek()[1] != text:
            raise CalcError(f"expected {text!r} at token {at + 1}")
        at += 1

    def product(depth):
        nonlocal at
        terms, op = [], "*"
        while True:
            terms.append((op, factor(depth, op)))
            if peek()[1] in ("*", "/"):
                op = peek()[1]
                at += 1
                continue
            return ("product", terms)

    def factor(depth, op):
        nonlocal at
        kind, text, k = peek()
        if kind == "literal":
            if depth:
                raise CalcError("the literal is a multiplicative factor at the top level: not inside parentheses "
                                "or sqrt (no literal-only subexpression)")
            if op == "/":
                raise CalcError("the literal is a multiplicative factor: write 10^-k instead of dividing by 10^k")
            at += 1
            return ("literal", k)
        if kind == "name" and text == "sqrt" and at + 1 < len(items) and items[at + 1][1] == "(":
            at += 2
            inner = product(depth + 1)
            take(")")
            if not names_of(inner):
                raise CalcError("sqrt needs a bound name in its argument (no literal-only subexpression)")
            return ("sqrt", inner)
        if kind == "name":
            if text == "sqrt":
                raise CalcError("sqrt is a function: sqrt(...)")
            at += 1
            return ("name", text)
        if text == "(":
            at += 1
            inner = product(depth + 1)
            take(")")
            if not names_of(inner):
                raise CalcError("a parenthesized group needs a bound name (no literal-only subexpression)")
            return ("group", inner)
        raise CalcError(f"expected a bound name, sqrt(...), (...) or the literal at token {at + 1}")

    tree = product(0)
    if at != len(items):
        raise CalcError(f"unexpected {items[at][1]!r} at token {at + 1}")
    literals = [node for node in walk(tree) if node[0] == "literal"]
    if len(literals) > 1:
        raise CalcError("at most one literal (one power of ten) is allowed")
    if not names_of(tree):
        raise CalcError("the expression needs a bound name (no literal-only expression)")
    return tree


def walk(node):
    yield node
    if node[0] in ("sqrt", "group"):
        yield from walk(node[1])
    elif node[0] == "product":
        for _, child in node[1]:
            yield from walk(child)


def names_of(node):
    return {child[1] for child in walk(node) if child[0] == "name"}


def literal_of(tree, expression):
    """{text, exponent} of the expression's literal, or None."""
    for node in walk(tree):
        if node[0] == "literal":
            text = next(t for kind, t, k in tokens(expression) if kind == "literal")
            return {"text": text, "exponent": node[1]}
    return None


def field_path(field):
    """(key, index or None) of a binding's field: a top-level key of the artifact content, optionally [0-9]."""
    match = FIELD.fullmatch(field) if isinstance(field, str) else None
    if match is None:
        raise CalcError("a binding's field is a content key, optionally with an index such as exp_limits_events[2]")
    return match.group(1), None if match.group(2) is None else int(match.group(2))


def check_request(params):
    """The parse tree of a calc request {expression, bindings, unit, label} (module docstring); CalcError otherwise."""
    if not isinstance(params, dict) or set(params) != {"expression", "bindings", "unit", "label"}:
        raise CalcError("a calc request has exactly: expression, bindings, unit, label")
    tree = parse(params["expression"])
    bindings = params["bindings"]
    if not isinstance(bindings, list) or not 1 <= len(bindings) <= MAX_BINDINGS:
        raise CalcError(f"between 1 and {MAX_BINDINGS} bindings are required")
    names = []
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) != {"name", "handle", "field", "value"}:
            raise CalcError("a binding has exactly: name, handle, field, value")
        if not (isinstance(binding["name"], str) and NAME.fullmatch(binding["name"])) or binding["name"] == "sqrt":
            raise CalcError("a binding name is an identifier other than sqrt")
        field_path(binding["field"])
        value = binding["value"]
        if type(value) not in (int, float) or not math.isfinite(value):
            raise CalcError(f"binding {binding['name']}: a finite number is required")
        names.append(binding["name"])
    if len(set(names)) != len(names):
        raise CalcError("duplicate binding name")
    used = names_of(tree)
    if used - set(names):
        raise CalcError("unbound name(s): " + ", ".join(sorted(used - set(names))))
    if set(names) - used:
        raise CalcError("binding(s) not used in the expression: " + ", ".join(sorted(set(names) - used)))
    if params["unit"] not in UNITS:
        raise CalcError(f"the declared unit is one of {', '.join(UNITS)}")
    label = params["label"]
    if label is not None and not (isinstance(label, str) and label.strip() and len(label) <= MAX_LABEL
                                  and "\n" not in label and "\r" not in label):
        raise CalcError(f"a label is one nonblank line of at most {MAX_LABEL} characters, or null")
    return tree


def evaluate(tree, values):
    """The value of a checked tree with {name: number} (exact except sqrt); CalcError on a domain error."""
    kind = tree[0]
    if kind == "name":
        return Fraction(values[tree[1]])
    if kind == "literal":
        return Fraction(10) ** tree[1]
    if kind == "group":
        return evaluate(tree[1], values)
    if kind == "sqrt":
        inner = evaluate(tree[1], values)
        if inner < 0:
            raise CalcError("the square root of a negative value")
        return Fraction(math.sqrt(inner))
    result = Fraction(1)
    for op, child in tree[1]:
        value = evaluate(child, values)
        if op == "/":
            if value == 0:
                raise CalcError("division by zero")
            result /= value
        else:
            result *= value
    return result


def compute(params):
    """The calc record of a checked request (module docstring)."""
    tree = check_request(params)
    result = float(evaluate(tree, {b["name"]: b["value"] for b in params["bindings"]}))
    if not math.isfinite(result):
        raise CalcError("the result is not a finite number")
    return {"schema_version": 1, "expression": params["expression"],
            "bindings": sorted((dict(b) for b in params["bindings"]), key=lambda b: b["name"]),
            "literal": literal_of(tree, params["expression"]), "declared_unit": params["unit"],
            "label": params["label"], "result": result,
            "rule": "combines the bound values as plain numbers; no dimensional analysis"}


def require_supervised(rd):
    from ravel.workflow.execution import load_execution
    record = load_execution(rd)["stages"].get(STAGE, {})
    if record.get("status") != "running" or record.get("supervisor_pid") != os.getppid():
        raise SystemExit(f"{STAGE} worker must be launched by the RAVEL stage supervisor")


def main():
    rd = Path(sys.argv[1]).resolve()
    require_supervised(rd)
    from ravel.workflow.state_io import atomic_json, read_json
    out = rd / "outputs" / STAGE
    out.mkdir(parents=True, exist_ok=False)
    try:
        atomic_json(out / "calc.json", compute(read_json(rd / "inputs/params.json")))
    except Exception as exc:
        atomic_json(out / "failure.json", {"type": type(exc).__name__, "error": str(exc)})
        raise


if __name__ == "__main__":
    main()
