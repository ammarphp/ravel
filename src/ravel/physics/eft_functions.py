"""Static, exact one-coefficient CMS PhysicsModel response bridge.

No upstream Python is imported or executed. This deliberately closed grammar
preserves the source RooFit expressions and all polynomial orders. Algebraic
agreement is neither a native likelihood fit nor an EFT-validity statement.
"""
from __future__ import annotations

import ast
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re

from ravel.workflow.state_io import atomic_json, read_json


IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"
NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"


def rational(value):
    """Read decimal/rational text without first rounding it through binary64."""
    if isinstance(value, Fraction):
        return value
    if type(value) is int:
        return Fraction(value)
    if not isinstance(value, str) or len(value) > 512 or not re.fullmatch(NUMBER + r"|[+-]?\d+/[1-9]\d*", value):
        raise ValueError("exact finite decimal or rational text required")
    exponent = re.search(r"[eE]([+-]?\d+)$", value)
    if exponent and abs(int(exponent[1])) > 128:
        raise ValueError("decimal exponent exceeds the exact-arithmetic bound")
    return Fraction(value)


def _ratio(value):
    return str(value.numerator) + "/" + str(value.denominator)


def _expression(expression, max_degree):
    if not isinstance(expression, str) or len(expression) > 20000 or "@0" not in expression:
        raise ValueError("bounded one-coefficient @0 expression required")
    text = expression.replace("@0", "x")
    try:
        tree = ast.parse(text, mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise ValueError("unsupported response syntax") from exc
    if len(list(ast.walk(tree))) > 2000:
        raise ValueError("response AST exceeds bound")

    def polynomial(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            literal = ast.get_source_segment(text, node)
            if len(literal) > 128:
                raise ValueError("decimal literal exceeds the exact-arithmetic bound")
            return [rational(literal)]
        if isinstance(node, ast.Name) and node.id == "x":
            return [Fraction(0), Fraction(1)]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            sign = -1 if isinstance(node.op, ast.USub) else 1
            return [sign * c for c in polynomial(node.operand)]
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            a, b = polynomial(node.left), polynomial(node.right)
            if isinstance(node.op, ast.Mult):
                c = [Fraction(0)] * (len(a) + len(b) - 1)
                if len(c) > max_degree + 1:
                    raise ValueError("polynomial degree exceeds declared bound")
                for i, av in enumerate(a):
                    for j, bv in enumerate(b):
                        c[i + j] += av * bv
                return c
            c = [Fraction(0)] * max(len(a), len(b))
            for i, av in enumerate(a):
                c[i] += av
            for i, bv in enumerate(b):
                c[i] += (-1 if isinstance(node.op, ast.Sub) else 1) * bv
            return c
        raise ValueError("unsupported response operator, call or variable")

    coefficients = polynomial(tree.body)
    literals = [ast.get_source_segment(text, n) for n in ast.walk(tree) if isinstance(n, ast.Constant)]
    return tree.body, text, tuple(coefficients), literals


def _direct(node, text, point):
    # Independent direct AST traversal, without using collected coefficients.
    if isinstance(node, ast.Constant):
        return rational(ast.get_source_segment(text, node))
    if isinstance(node, ast.Name):
        return point
    if isinstance(node, ast.UnaryOp):
        result = _direct(node.operand, text, point)
        return -result if isinstance(node.op, ast.USub) else result
    a, b = _direct(node.left, text, point), _direct(node.right, text, point)
    if isinstance(node.op, ast.Add):
        return a + b
    if isinstance(node.op, ast.Sub):
        return a - b
    return a * b


def _literal(node):
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        raise ValueError("literal source string required")
    return node.value


def _docstring(node):
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def _builder_call(node):
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        raise ValueError("unsupported PhysicsModel statement")
    call = node.value
    if call.keywords or not isinstance(call.func, ast.Attribute) or not isinstance(call.func.value, ast.Attribute) or not isinstance(call.func.value.value, ast.Name) or call.func.value.value.id != "self" or call.func.value.attr != "modelBuilder":
        raise ValueError("unsupported PhysicsModel builder call")
    return call.func.attr, call.args


def parse_source(raw, *, max_degree=5):
    """Return a JSON-safe lossless contract for the admitted source subset."""
    if type(max_degree) is not int or not 1 <= max_degree <= 12:
        raise ValueError("degree bound must be an integer between one and twelve")
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if not isinstance(raw, bytes) or len(raw) > 1000000:
        raise ValueError("bounded UTF-8 PhysicsModel bytes required")
    try:
        source = raw.decode("utf-8")
        tree = ast.parse(source)
    except (UnicodeError, SyntaxError, RecursionError) as exc:
        raise ValueError("invalid PhysicsModel source") from exc
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    if len(classes) != 1:
        raise ValueError("exactly one PhysicsModel class required")
    cls = classes[0]
    if cls.decorator_list or cls.keywords or len(cls.bases) != 1 or not isinstance(cls.bases[0], ast.Name) or cls.bases[0].id != "PhysicsModel":
        raise ValueError("unsupported model inheritance or decoration")
    methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
    if len(methods) != 2 or sum(isinstance(n, ast.FunctionDef) for n in cls.body) != 2 or set(methods) != {"doParametersOfInterest", "getYieldScale"} or any(not isinstance(n, ast.FunctionDef) and not _docstring(n) for n in cls.body):
        raise ValueError("only parameter and yield-scale methods are admitted")
    for name, arguments in (("doParametersOfInterest", ["self"]), ("getYieldScale", ["self", "bin", "process"])):
        method = methods[name]
        a = method.args
        if method.decorator_list or method.returns or a.posonlyargs or a.kwonlyargs or a.vararg or a.kwarg or a.defaults or a.kw_defaults or [x.arg for x in a.args] != arguments or any(x.annotation for x in a.args):
            raise ValueError("unsupported PhysicsModel method signature")
    instance = None
    for node in tree.body:
        if node is cls or _docstring(node):
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "HiggsAnalysis.CombinedLimit.PhysicsModel" and node.level == 0 and [(n.name, n.asname) for n in node.names] == [("*", None)]:
            continue
        if isinstance(node, ast.Import) and [(n.name, n.asname) for n in node.names] == [("re", None)]:
            continue
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == cls.name and not node.value.args and not node.value.keywords and instance is None:
            instance = node.targets[0].id
            continue
        raise ValueError("unsupported top-level PhysicsModel code")
    if instance is None:
        raise ValueError("explicit exported model instance required")
    domain, poi, poi_set, functions = None, None, None, {}
    for node in methods["doParametersOfInterest"].body:
        if _docstring(node):
            continue
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "pois" and poi is None:
            poi = _literal(node.value)
            continue
        name, args = _builder_call(node)
        if name == "doVar" and len(args) == 1 and domain is None:
            literal = _literal(args[0])
            match = re.fullmatch(r"(" + IDENTIFIER + r")\[\s*(" + NUMBER + r")\s*,\s*(" + NUMBER + r")\s*,\s*(" + NUMBER + r")\s*\]", literal)
            if not match:
                raise ValueError("one explicit coefficient initial value and signed domain required")
            coefficient, initial, lower, upper = match.groups()
            if not rational(lower) < rational(upper) or not rational(lower) <= rational(initial) <= rational(upper):
                raise ValueError("invalid coefficient domain")
            domain = {"name": coefficient, "initial": initial, "lower": lower, "upper": upper, "literal": literal, "source_line": node.lineno}
        elif name == "doSet" and len(args) == 2 and _literal(args[0]) == "POI" and isinstance(args[1], ast.Name) and args[1].id == "pois" and poi_set is None:
            poi_set = poi
        elif name == "factory_" and len(args) == 1:
            literal = _literal(args[0])
            match = re.fullmatch(r'expr::(' + IDENTIFIER + r')\("([^"\n]+)",\s*(' + IDENTIFIER + r')\)', literal)
            if not match:
                raise ValueError("unsupported RooFit factory expression")
            fn, expression, argument = match.groups()
            if fn in functions or domain is None or argument != domain["name"]:
                raise ValueError("duplicate response or different coefficient dependency")
            _, _, coefficients, literals = _expression(expression, max_degree)
            functions[fn] = {"factory": literal, "expression": expression, "argument": argument,
                             "decimal_literals": literals, "coefficients": [_ratio(c) for c in coefficients],
                             "degree": len(coefficients) - 1, "source_line": node.lineno,
                             "source_segment": ast.get_source_segment(source, node)}
        else:
            raise ValueError("unsupported or repeated parameter construction")
    if domain is None or poi != domain["name"] or poi_set != poi or not functions:
        raise ValueError("inconsistent coefficient/POI construction")
    mappings = {}

    def mapping_return(node):
        if not isinstance(node, ast.Return):
            raise ValueError("yield mapping must be a literal return")
        if isinstance(node.value, ast.Constant) and type(node.value.value) is int and node.value.value in (0, 1):
            return node.value.value
        return _literal(node.value)

    def branch(node):
        test = node.test
        if not isinstance(test, ast.Compare) or not isinstance(test.left, ast.Name) or test.left.id != "process" or len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq) or len(test.comparators) != 1 or len(node.body) != 1:
            raise ValueError("only explicit process equality mappings are admitted")
        process = _literal(test.comparators[0])
        if process in mappings:
            raise ValueError("duplicate process mapping")
        mappings[process] = {"scale": mapping_return(node.body[0]), "source_line": node.lineno}
        if node.orelse:
            if len(node.orelse) != 1 or not isinstance(node.orelse[0], ast.If):
                raise ValueError("mapping else must be an elif; explicit final default required")
            branch(node.orelse[0])
    statements = [n for n in methods["getYieldScale"].body if not _docstring(n)]
    if len(statements) != 2 or not isinstance(statements[0], ast.If) or mapping_return(statements[1]) != 1:
        raise ValueError("explicit process chain and default return one required")
    branch(statements[0])
    return {"schema_version": 1, "source_sha256": hashlib.sha256(raw).hexdigest(),
            "class": cls.name, "instance": instance, "domain": domain, "functions": functions,
            "process_mappings": mappings, "default_scale": 1, "max_degree": max_degree,
            "scope": "Exact one-coefficient response algebra; native nuisances and EFT validity unverified"}


def parse_datacard(raw):
    """Census the literal card columns; keep source ordering and rate tokens."""
    if isinstance(raw, str):
        raw = raw.encode()
    lines = [line.split("#", 1)[0].split() for line in raw.decode().splitlines()]
    rows = [(i + 1, tokens) for i, tokens in enumerate(lines) if tokens]
    process = [(i, t[1:]) for i, t in rows if t[0] == "process"]
    rates = [(i, t[1:]) for i, t in rows if t[0] == "rate"]
    if len(process) != 2 or len(rates) != 1:
        raise ValueError("card requires two process rows and one rate row")
    id_rows = [(i, t) for i, t in process if all(re.fullmatch(r"-?\d+", x) for x in t)]
    if len(id_rows) != 1:
        raise ValueError("unambiguous integer process IDs required")
    ids_line, ids = id_rows[0]
    names_line, names = next((i, t) for i, t in process if i != ids_line)
    bins = [(i, t[1:]) for i, t in rows if t[0] == "bin" and i < min(ids_line, names_line)]
    if not bins or not min(ids_line, names_line) < rates[0][0] or not len(names) == len(ids) == len(rates[0][1]) == len(bins[-1][1]) or not names:
        raise ValueError("card column counts/order disagree")
    columns = []
    for i, (channel, name, pid, rate) in enumerate(zip(bins[-1][1], names, ids, rates[0][1])):
        if not re.fullmatch(IDENTIFIER + r"[.\-]*|[A-Za-z0-9_.-]+", channel) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise ValueError("unsupported card channel/process identity")
        value = rational(rate)
        if value < 0 and value != -1:
            raise ValueError("invalid literal rate")
        columns.append({"index": i, "channel": channel, "process": name, "process_id": int(pid), "rate": rate})
    if len({(c["channel"], c["process"]) for c in columns}) != len(columns):
        raise ValueError("duplicate card channel/process column")
    return {"sha256": hashlib.sha256(raw).hexdigest(), "columns": columns, "rate_line": rates[0][0],
            "channels": list(dict.fromkeys(c["channel"] for c in columns))}


def bind_card(model, card):
    """Used unresolved responses fail; unused undefined entries stay visible."""
    used = set()
    columns = []
    for original in card["columns"]:
        row = dict(original)
        process = row["process"]
        mapping = model["process_mappings"].get(process)
        if row["process_id"] <= 0 and mapping is None:
            raise ValueError("used signal process lacks an explicit coefficient mapping: " + process)
        scale = mapping["scale"] if mapping else model["default_scale"]
        if isinstance(scale, str) and scale not in model["functions"]:
            raise ValueError("used process refers to an undefined response: " + process)
        if mapping:
            used.add(process)
        row["scale"] = scale
        row["mapping"] = "explicit" if mapping else "source_default"
        columns.append(row)
    unused = [{"process": p, **m} for p, m in model["process_mappings"].items() if p not in used]
    return {"card_sha256": card["sha256"], "columns": columns, "channels": card["channels"],
            "unused_mappings": unused,
            "unused_undefined_mappings": [m for m in unused if isinstance(m["scale"], str) and m["scale"] not in model["functions"]]}


def evaluate(model, point, *, direct=False):
    point = rational(point)
    domain = model["domain"]
    if not rational(domain["lower"]) <= point <= rational(domain["upper"]):
        raise ValueError("coefficient outside the published signed domain")
    result = {}
    for name, fn in model["functions"].items():
        if direct:
            node, text, _, _ = _expression(fn["expression"], model["max_degree"])
            value = _direct(node, text, point)
        else:
            value = Fraction(0)
            for coefficient in reversed(fn["coefficients"]):
                value = value * point + rational(coefficient)
        result[name] = value
    return result


def algebra_witness(model):
    domain = model["domain"]
    lower, upper = rational(domain["lower"]), rational(domain["upper"])
    points = {lower, lower + (upper - lower) / 4, (lower + upper) / 2,
              lower + 3 * (upper - lower) / 4, upper, rational(domain["initial"])}
    if lower <= 0 <= upper:
        points.add(Fraction(0))
    rows = []
    for point in sorted(points):
        collected, direct = evaluate(model, point), evaluate(model, point, direct=True)
        if collected != direct:
            raise ValueError("direct expression versus polynomial disagreement")
        rows.append({"point": _ratio(point), "scales": {k: _ratio(v) for k, v in collected.items()},
                     "nonpositive_responses": [k for k, v in collected.items() if v <= 0]})
    return {"passed": True, "arithmetic": "exact rational", "points": rows,
            "scope": "Frozen-point algebra parity only; not likelihood, positivity-domain or EFT certification"}


def native_bridge_source(model):
    """Generate the admitted builder operations verbatim for native Combine.

    Callers obtain ``model`` from ``parse_source`` against bound original bytes.
    The bridge retains every literal factory and the source's default scale.
    """
    lines = ["from HiggsAnalysis.CombinedLimit.PhysicsModel import PhysicsModel",
             "class SourceResponse(PhysicsModel):", "    def doParametersOfInterest(self):",
             "        self.modelBuilder.doVar(" + repr(model["domain"]["literal"]) + ")",
             "        self.modelBuilder.doSet('POI', " + repr(model["domain"]["name"]) + ")"]
    lines += ["        self.modelBuilder.factory_(" + repr(fn["factory"]) + ")" for fn in model["functions"].values()]
    lines += ["    def getYieldScale(self, bin, process):",
              "        return " + repr({p: m["scale"] for p, m in model["process_mappings"].items()}) + ".get(process, 1)",
              "model = SourceResponse()", ""]
    return "\n".join(lines)


def _pin(pin, base):
    from ravel.workflow.science import regular
    if not isinstance(pin, dict) or set(pin) != {"path", "sha256"} or not isinstance(pin["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", pin["sha256"]):
        raise ValueError("exact file path and SHA256 required")
    path = regular(pin["path"], base)
    if hashlib.sha256(path.read_bytes()).hexdigest() != pin["sha256"]:
        raise ValueError("source input bytes changed")
    return path


def validate(task):
    if not isinstance(task, dict) or set(task) != {"input"} or not isinstance(task["input"], str) or not task["input"]:
        raise ValueError("eft-functions task requires exactly input")


def _configuration(task, base):
    from ravel.workflow.science import regular
    validate(task)
    path = regular(task["input"], base)
    doc = read_json(path)
    if not isinstance(doc, dict) or set(doc) != {"schema_version", "model", "cards", "coefficient_unit", "one_coefficient_basis", "evaluation_points"} or type(doc["schema_version"]) is not int or doc["schema_version"] != 1:
        raise ValueError("invalid eft-functions/v1 input")
    if not isinstance(doc["coefficient_unit"], str) or not doc["coefficient_unit"].strip() or not isinstance(doc["one_coefficient_basis"], str) or not doc["one_coefficient_basis"].strip():
        raise ValueError("explicit physical units and one-coefficient basis evidence required")
    if not isinstance(doc["cards"], list) or not doc["cards"] or not isinstance(doc["evaluation_points"], list) or len(doc["evaluation_points"]) > 1000:
        raise ValueError("bounded evaluation points and nonempty card list required")
    model_path = _pin(doc["model"], path.parent)
    card_paths = [_pin(c, path.parent) for c in doc["cards"]]
    if len(set(card_paths)) != len(card_paths):
        raise ValueError("duplicate datacard")
    model = parse_source(model_path.read_bytes())
    cards = [bind_card(model, parse_datacard(c.read_bytes())) for c in card_paths]
    for point in doc["evaluation_points"]:
        evaluate(model, point)
    return doc, path, model_path, card_paths, model, cards


def inputs(task, base):
    _, path, model_path, card_paths, _, _ = _configuration(task, base)
    return [path, model_path, *card_paths]


def run(task, base, out):
    doc, path, model_path, card_paths, model, cards = _configuration(task, base)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    witness = algebra_witness(model)
    values = [{"point": _ratio(rational(p)), "scales": {k: _ratio(v) for k, v in evaluate(model, p).items()}}
              for p in doc["evaluation_points"]]
    result = {"status": "passed", "physics_validated": False, "scope": model["scope"],
              "coefficient_unit": doc["coefficient_unit"], "one_coefficient_basis": doc["one_coefficient_basis"],
              "model": model, "cards": cards, "algebra_witness": witness, "evaluations": values,
              "limitations": ["No native likelihood or nuisance profiling was executed.",
                              "No multidimensional EFT response, truncation validity or physical domain is inferred.",
                              "Full source expressions are preserved without renormalizing the zero-coefficient value."]}
    atomic_json(out / "eft-functions.json", result)
    if _configuration(task, base)[4:] != (model, cards):
        raise ValueError("inputs changed during algebra delivery")
    return result
