"""Explicit literal-UFO dependent mass/width and MG2.9.27 card-writer contract.

This is a source projection, not a model import or amplitude oracle. The complete
original free point is authoritative. A tolerance never authorizes an arbitrary
nearby value: only the exact released binary64/default-writer projection matches.
"""
import ast
import cmath
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re

from ravel.physics.model_event_weights import require

MODE = 'mg5_2_9_27_literal_dependent_writer'
MODEL_FILES = {'parameters': 'parameters.py', 'particles': 'particles.py',
               'functions': 'function_library.py'}
# Released implementations whose parser/update/writer semantics this mode uses.
PRIMARY_SHA256 = {
    'models/check_param_card.py': '010d7f1d36ff010ce93bbb470079deec9112e1074ca65776749be9b6a0d9d049',
    'models/model_reader.py': 'ba50053d834ef8c18c2a49ddde528dd2f495c28203516919491d59933928af70',
    'models/import_ufo.py': '7992794aa7b0bcd2178892ac511400982ee20c6a61e9d7785a640377be02ce45',
    'madgraph/interface/common_run_interface.py': '0e915210fffd2fddead6b36ed06390d528e378664daba7555bce3d86c1ba1d98',
}
MAX_ROWS = 32768
MAX_PARAMETERS = 4096
MAX_EVALUATIONS = 65536
MAX_ROW_REPORT_BYTES = 8 * 1024**2
FUNCTIONS = {name: getattr(cmath, name) for name in
             ('sqrt', 'sin', 'cos', 'tan', 'acos', 'asin', 'atan',
              'exp', 'log', 'log10', 'sinh', 'cosh', 'tanh')}
REAL_FUNCTIONS = {name: getattr(math, name) for name in FUNCTIONS}


def _decimal(value):
    require(type(value) is str and len(value) <= 512,
            'bounded explicit decimal representation required')
    try:
        v = Decimal(value)
    except Exception as exc:
        raise ValueError('finite decimal representation required') from exc
    require(v.is_finite() and len(v.as_tuple().digits) <= 256
            and abs(v.as_tuple().exponent) <= 400,
            'decimal exceeds finite arithmetic domain')
    return v


def validate(contract):
    from ravel.physics import model_tool_bridge as bridge
    bridge._keys(contract, ('schema_version', 'mode', 'model_sources',
        'maximum_relative_error', 'complex_mass_scheme'), 'parameter observation')
    require(type(contract['schema_version']) is int and contract['schema_version'] == 1
            and contract['mode'] == MODE, 'explicit MG2.9.27 dependent-writer mode required')
    bridge._keys(contract['model_sources'], MODEL_FILES, 'literal model sources')
    require(all(type(x) is str and re.fullmatch('[0-9a-f]{64}', x)
                for x in contract['model_sources'].values()), 'exact model source digests required')
    error = _decimal(contract['maximum_relative_error'])
    require(0 < error <= Decimal('0.000001'), 'prospective writer error bound must be in (0,1e-6]')
    require(contract['complex_mass_scheme'] is False,
            'this source projection supports explicit real-mass scheme only')
    return contract


def source_inputs(contract, modelroot, mgroot):
    """Authenticate consumed source bytes under already admitted full trees."""
    from ravel.physics.model_events import authenticated_text
    validate(contract)
    paths = []
    sources = {}
    for label, name in MODEL_FILES.items():
        p = Path(modelroot) / name
        sources[label] = authenticated_text(p, contract['model_sources'][label])
        paths.append(p)
    for name, digest in PRIMARY_SHA256.items():
        p = Path(mgroot) / name
        authenticated_text(p, digest)
        paths.append(p)
    return sources, paths


def _keywords(call):
    require(not call.args and all(k.arg is not None for k in call.keywords)
            and len({k.arg for k in call.keywords}) == len(call.keywords),
            'canonical literal UFO declaration keywords required')
    return {k.arg: k.value for k in call.keywords}


def _literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError) as exc:
        raise ValueError('literal UFO declaration field required') from exc


def _declarations(raw, factory):
    require(type(raw) is str and len(raw.encode('utf-8')) <= 2*1024**2,
            'bounded literal UFO source required')
    rows = {}
    for stmt in ast.parse(raw).body:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and type(stmt.value.value) is str:
            continue
        require(isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name),
                'dynamic UFO source unsupported by literal dependent projection')
        name = stmt.targets[0].id
        value = stmt.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == factory:
            require(name not in rows, 'duplicate UFO declaration')
            fields = _keywords(value)
            rows[name] = {'fields': fields, 'source_line': stmt.lineno}
        elif factory == 'Particle' and isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr == 'anti':
            require(isinstance(value.func.value, ast.Name) and value.func.value.id in rows
                    and not value.args and not value.keywords and name not in rows,
                    'only declared particle antiparticle references supported')
            # abs(PDG) uses the same mass/width entry, so retain the reference.
            rows[name] = rows[value.func.value.id]
        else:
            _literal(value)  # metadata only; never execute source statements
    require(rows and len(rows) <= MAX_PARAMETERS, 'bounded complete literal UFO declarations required')
    return rows


def card_values(raw):
    """Reuse the existing literal card parser; canonicalize only writer semantics."""
    from ravel.physics.model_events import parameter_values
    require(type(raw) is str and len(raw.encode('utf-8')) <= 2*1024**2, 'parameter card exceeds 2MiB bound')
    lines = []
    qnames = {}
    for line in raw.splitlines():
        tokens = line.split('#', 1)[0].split()
        if len(tokens) >= 2 and tokens[0].lower() == 'block' and tokens[1].lower() == 'qnumbers':
            require(len(tokens) == 3 and re.fullmatch('-?[0-9]+', tokens[2]),
                    'literal QNUMBERS particle identity required')
            pdg = str(int(tokens[2]))
            name = 'qnumbers__' + pdg
            qnames[name] = 'qnumbers ' + pdg
            line = 'BLOCK ' + name
        lines.append(line)
    original = parameter_values('\n'.join(lines))
    require(len(original) <= MAX_ROWS, 'parameter population exceeds bound')
    result = {}
    for (block, codes), value in original.items():
        value = _decimal(str(value))
        require(len(codes) <= 64 and len(block) <= 128, 'card address exceeds declared population bounds')
        if block == '@branch':
            # MG load_decay sorts daughters and keys by full multiplicity.
            codes = (codes[0], *sorted(codes[2:]))
        block = qnames.get(block, block)
        key = (block, codes)
        require(key not in result, 'duplicate canonical branching/parameter identity')
        result[key] = value
    return result


def _card_lexemes(raw, values):
    """The released reader lowercases text, then tries float on scalar tokens.

    Decimal admission alone does not establish native scalar type: D exponents
    remain strings in Parameter.load_str. Scales and branching rows instead use
    float directly and have no string fallback. The existing parser supplies
    the complete admitted numeric population; this records its writer classes.
    """
    result = {}
    block = decay = None
    for line in raw.splitlines():
        raw_tokens = line.split('#', 1)[0].split()
        tokens = [token.lower() for token in raw_tokens]
        if not tokens:
            continue
        head = tokens[0]
        if head == 'block':
            block, decay = tokens[1], None
            if block == 'qnumbers':
                block = 'qnumbers ' + str(int(tokens[2]))
                continue
            if len(tokens) == 2:
                continue
            key, token = ('@scale', (block,)), ''.join(tokens[2:])[2:]
        elif head == 'decay':
            decay, block = int(tokens[1]), None
            key, token = ('decay', (decay,)), tokens[2]
        elif block is not None:
            key, token = (block, tuple(int(x) for x in tokens[:-1])), tokens[-1]
        else:
            key, token = ('@branch', (decay, *sorted(map(int, tokens[2:])))), tokens[0]
        raw_token = (''.join(raw_tokens[2:])[2:] if head == 'block' else
                     raw_tokens[2] if head == 'decay' else
                     raw_tokens[-1] if block is not None else raw_tokens[0])
        try:
            float(token)
            kind = 'int' if key[0] == 'modsel' else 'float'
        except ValueError:
            require(key[0] not in ('@scale', '@branch'),
                    'released scale/branch parser requires a native float token')
            kind = 'str'
        require(key not in result, 'duplicate canonical native writer identity')
        result[key] = {'format': kind, 'lexeme': token, 'original_lexeme': raw_token}
    require(set(result) == set(values), 'native writer lexeme census differs from admitted card')
    return result


def _finite(v):
    require(type(v) in (int, float, complex), 'finite scalar expression required')
    try:
        okay = math.isfinite(v.real) and math.isfinite(v.imag)
    except (OverflowError, TypeError):
        okay = False
    require(okay, 'nonfinite source-derived expression')
    return v


def _model(sources, original, lexemes):
    from ravel.physics.model_derivation_bridge import literal_external_card
    _, external = literal_external_card(sources['parameters'])
    parameters = _declarations(sources['parameters'], 'Parameter')
    named = {}
    for key, row in parameters.items():
        f = row['fields']
        name = _literal(f['name'])
        require(type(name) is str and name == key and name not in named,
                'canonical unique parameter variable/name required')
        nature = _literal(f['nature'])
        require(nature in ('external', 'internal'), 'unknown parameter nature')
        named[name] = {**row, 'nature': nature}
    require(not ({'locals', '__builtins__'} & set(named)),
            'parameter name shadows the released expression framework')
    values = {}
    external_by_address = {}
    for row in external:
        address = (row['block'], tuple(row['codes']))
        require(address in original, 'missing free source input; UFO default is not authority: ' + row['name'])
        require(lexemes[address]['format'] != 'str',
                'released model reader cannot consume a string free input: ' + row['name'])
        values[row['name']] = _binary(original[address])
        external_by_address[address] = row['name']
    functions = {}
    for variable, row in _declarations(sources['functions'], 'Function').items():
        f = row['fields']
        name, args, expression = [_literal(f[x]) for x in ('name', 'arguments', 'expression')]
        require(name == variable and type(args) in (tuple, list) and len(args) <= 8
                and len(set(args)) == len(args) and all(type(x) is str and x.isidentifier() for x in args),
                'bounded literal function arguments required')
        functions[name] = (args, expression)
    require(not ({'locals', '__builtins__'} & set(functions)),
            'function name shadows the released expression framework')
    require(not (set(named) & set(functions)),
            'parameter/function namespace collision requires released evaluation-order evidence')
    active = set()
    budget = [MAX_EVALUATIONS]

    def evaluate(expression, local=None, *, function_body=False):
        require(type(expression) is str and len(expression) <= 4096, 'bounded literal internal expression required')
        tree = ast.parse(expression, mode='eval')
        require(sum(1 for _ in ast.walk(tree)) <= 512, 'internal expression exceeds node bound')
        local = {} if local is None else local

        def binding(name):
            # Parameter expressions see all_params locals before module globals
            # and builtins. Function bodies see only arguments before those
            # globals: defining them in all_params does not capture that mapping.
            if name in local: return 'argument'
            if not function_body:
                if name in named: return 'parameter'
                if name in functions: return 'function'
            if name in ('cmath', 'math'): return 'module'
            if name == 'ZERO': return 'global_scalar'
            if name in ('complex', 'abs'): return 'builtin'
            return 'unsupported'

        def module(name):
            # Function definitions receive ModelReader globals, not all_params.
            # Their arguments can shadow modules; outer parameter expressions
            # instead resolve all_params before the source module globals.
            require(binding(name) == 'module',
                    'declared scalar/function shadows the released ' + name + ' module')
            return cmath if name == 'cmath' else math

        def visit(node, depth=0):
            budget[0] -= 1
            require(budget[0] >= 0 and depth <= 64, 'internal expression exceeds evaluation bound')
            sub = lambda x: visit(x, depth+1)
            if isinstance(node, ast.Constant):
                return _finite(node.value)
            if isinstance(node, ast.Name):
                kind = binding(node.id)
                if kind == 'argument':
                    return local[node.id]
                if kind == 'parameter':
                    return parameter(node.id)
                if kind == 'global_scalar':
                    return 0  # exact constant in the pinned ModelReader globals
                raise ValueError('released binding is not a supported scalar (' + kind + '): ' + node.id)
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                v = sub(node.operand)
                return _finite(v if isinstance(node.op, ast.UAdd) else -v)
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
                a, b = sub(node.left), sub(node.right)
                if isinstance(node.op, ast.Pow):
                    require(not isinstance(b, complex) and abs(b) <= 32, 'bounded real literal exponent required')
                    v = a**b
                elif isinstance(node.op, ast.Add): v = a+b
                elif isinstance(node.op, ast.Sub): v = a-b
                elif isinstance(node.op, ast.Mult): v = a*b
                else: v = a/b
                return _finite(v)
            if isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name) and node.value.id in ('cmath', 'math') and node.attr in ('pi', 'e'):
                    return getattr(module(node.value.id), node.attr)
                require(node.attr in ('real', 'imag'), 'unsupported internal expression attribute')
                return _finite(getattr(sub(node.value), node.attr))
            if isinstance(node, ast.Call):
                require(not node.keywords and len(node.args) <= 8, 'literal scalar call required')
                args = [sub(x) for x in node.args]
                if isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name) and node.func.value.id in ('cmath', 'math'):
                        which = node.func.value.id
                        module(which)
                        table = FUNCTIONS if which == 'cmath' else REAL_FUNCTIONS
                        require(node.func.attr in table, 'unsupported ' + which + ' function')
                        return _finite(table[node.func.attr](*args))
                    require(node.func.attr == 'conjugate' and not args, 'unsupported scalar method')
                    return _finite(sub(node.func.value).conjugate())
                require(isinstance(node.func, ast.Name), 'unsupported executable expression')
                name = node.func.id
                kind = binding(name)
                require(kind not in ('argument', 'parameter'),
                        'declared scalar is not a released callable: ' + name)
                if kind == 'function':
                    require('function:'+name not in active, 'cyclic literal function')
                    names, body = functions[name]
                    require(len(args) == len(names), 'literal function arity differs')
                    require(len(active) < 64, 'source dependency depth exceeds bound')
                    active.add('function:'+name)
                    try: return evaluate(body, dict(zip(names, args)), function_body=True)
                    finally: active.remove('function:'+name)
                if kind == 'builtin' and name == 'complex': return _finite(complex(*args))
                if kind == 'builtin' and name == 'abs': return _finite(abs(*args))
                raise ValueError('unsupported/unbound released callable: ' + name)
            raise ValueError('unsupported executable/internal expression syntax')
        try:
            return visit(tree.body)
        except (ArithmeticError, TypeError) as exc:
            raise ValueError('invalid finite source-derived expression') from exc

    def parameter(name):
        if name in values: return values[name]
        require(name in named and name not in active, 'unknown/cyclic internal parameter: ' + name)
        row = named[name]
        require(row['nature'] == 'internal', 'unbound external parameter')
        require(len(active) < 64, 'source dependency depth exceeds bound')
        active.add(name)
        try:
            values[name] = evaluate(_literal(row['fields']['value']))
        finally:
            active.remove(name)
        return values[name]

    dependent = {}
    for row in _declarations(sources['particles'], 'Particle').values():
        f = row['fields']
        if _literal(f.get('GhostNumber', ast.Constant(0))) != 0 or _literal(f.get('GoldstoneBoson', ast.Constant(False))):
            continue
        pdg = _literal(f['pdg_code'])
        require(type(pdg) is int and pdg != 0, 'literal physical particle PDG required')
        for label, block in (('mass', 'mass'), ('width', 'decay')):
            reference = f[label]
            require(isinstance(reference, ast.Attribute) and isinstance(reference.value, ast.Name)
                    and reference.value.id == 'Param' and reference.attr in named,
                    'literal declared physical mass/width parameter required')
            name = reference.attr
            if label == 'mass' and named[name]['nature'] == 'external': continue
            value = parameter(name)
            require(value.imag == 0, 'nonreal physical mass/width requires revised protocol')
            value = float(value.real)
            if label == 'width': value = abs(value)
            address = (block, (abs(pdg),))
            require(address not in original or lexemes[address]['format'] != 'str',
                    'released dependent updater cannot consume a string mass/width input')
            detail = {'parameter': name, 'nature': named[name]['nature'],
                      'source_line': named[name]['source_line'], 'particle_line': row['source_line'],
                      'value': value}
            require(address not in dependent or dependent[address]['value'] == value,
                    'inconsistent physical particle mass/width identity')
            dependent[address] = detail
    require(dependent, 'no literal physical dependent entries')
    return external_by_address, dependent


def _binary(value):
    try: converted = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError('free input exceeds binary64 domain') from exc
    require(math.isfinite(converted) and (value == 0 or converted != 0),
            'free input overflows/underflows binary64 domain')
    return converted


def _address(key):
    return {'block': key[0], 'codes': list(key[1])}


def projection(contract, original_raw, sources):
    """Whole-population source/writer expectation, no native import or backfill."""
    validate(contract)
    require(set(sources) == set(MODEL_FILES), 'complete literal model source content required')
    require(all(hashlib.sha256(sources[k].encode('utf-8')).hexdigest() == contract['model_sources'][k]
                for k in MODEL_FILES), 'consumed literal model sources differ from contract')
    original = card_values(original_raw)
    lexemes = _card_lexemes(original_raw, original)
    external, dependent = _model(sources, original, lexemes)
    base = {k: _binary(v) for k, v in original.items() if lexemes[k]['format'] != 'str'}
    base.update({k: v['value'] for k, v in dependent.items()})
    rows, expected = [], {}
    bound = Fraction(_decimal(contract['maximum_relative_error']))
    for key in sorted(set(original) | set(base)):
        if key in original and lexemes[key]['format'] == 'str':
            expected[key] = original[key]
            rows.append({**_address(key), 'original': str(original[key]),
                'original_lexeme': lexemes[key]['original_lexeme'], 'writer_format': 'str',
                'writer_lexeme': lexemes[key]['lexeme'], 'binary64_hex': None,
                'writer_value': str(original[key]), 'binary64_conversion_error': None,
                'writer_error_numerator': '0', 'writer_error_denominator': '1',
                'relative_error_numerator': '0', 'relative_error_denominator': '1',
                'authority': 'original_free_or_preserved_supplied',
                'external_parameter': None, 'dependent_source': None})
            continue
        value = base[key]
        integer = key[0] == 'modsel' or key[0].startswith('qnumbers ')
        if integer:
            require(original[key] == Decimal(int(original[key])) and Fraction.from_float(value) == Fraction(original[key]),
                    'integer input cannot be truncated/rounded by native writer')
        written = Decimal(str(int(value))) if integer else Decimal('%.6e' % value)
        reference = Fraction.from_float(value) if key in dependent and dependent[key]['nature'] == 'internal' else Fraction(original[key])
        absolute = abs(Fraction(written)-reference)
        relative = absolute/abs(reference) if reference else Fraction(0)
        require((reference != 0 or written == 0) and relative <= bound,
                'exact native writer representation exceeds declared error at ' + str(key))
        expected[key] = written
        detail = dependent.get(key)
        rows.append({**_address(key), 'original': str(original[key]) if key in original else None,
            'original_lexeme': lexemes[key]['original_lexeme'] if key in original else None,
            'writer_format': 'int' if key[0] == 'modsel' else 'float', 'writer_lexeme': str(written),
            'binary64_hex': value.hex(), 'writer_value': str(written),
            'binary64_conversion_error': str(Fraction.from_float(value)-Fraction(original[key])) if key in original and not (detail and detail['nature']=='internal') else None,
            'writer_error_numerator': str(absolute.numerator), 'writer_error_denominator': str(absolute.denominator),
            'relative_error_numerator': str(relative.numerator), 'relative_error_denominator': str(relative.denominator),
            'authority': 'source_derived_internal' if detail and detail['nature']=='internal' else 'original_free_or_preserved_supplied',
            'external_parameter': external.get(key), 'dependent_source': {k:v for k,v in detail.items() if k!='value'} if detail else None})
    require(len(json.dumps(rows, separators=(',', ':'), allow_nan=False).encode('utf-8')) <= MAX_ROW_REPORT_BYTES,
            'complete parameter row report exceeds 8MiB bound')
    # A raw unchanged card is admissible only if all dependent entries are present
    # and exactly agree at native binary64. Never accept a skipped stale update.
    unchanged_consistent = set(original) == set(expected) and all(_binary(original[k]) == d['value'] for k,d in dependent.items())
    return original, expected, rows, unchanged_consistent


def compare(contract, original_raw, observed_raw, sources, *, restriction_present=False):
    original, expected, rows, unchanged_consistent = projection(contract, original_raw, sources)
    observed = card_values(observed_raw)
    observed_lexemes = _card_lexemes(observed_raw, observed)
    expected_lexemes = {(r['block'], tuple(r['codes'])): r for r in rows}
    lexical_differences = {k for k in set(expected) & set(observed)
        if observed_lexemes[k]['format'] != expected_lexemes[k]['writer_format']
        or expected_lexemes[k]['writer_format'] == 'str'
        and observed_lexemes[k]['lexeme'] != expected_lexemes[k]['writer_lexeme']}
    exact_writer = observed == expected and not lexical_differences
    exact_unchanged = unchanged_consistent and observed == original and not lexical_differences
    differences = [dict(_address(k), expected=str(expected[k]) if k in expected else None,
                        observed=str(observed[k]) if k in observed else None)
                   for k in sorted(set(expected)|set(observed)) if expected.get(k) != observed.get(k) or k in lexical_differences]
    for difference in differences:
        key = (difference['block'], tuple(difference['codes']))
        if key in lexical_differences:
            difference['expected_native_format'] = expected_lexemes[key]['writer_format']
            difference['observed_native_format'] = observed_lexemes[key]['format']
            difference['expected_lexeme'] = expected_lexemes[key]['writer_lexeme']
            difference['observed_lexeme'] = observed_lexemes[key]['lexeme']
    return {'schema_version':1, 'kind':'source_bound_parameter_card_observation',
        'mode':MODE, 'matched':not restriction_present and (exact_writer or exact_unchanged),
        'representation':'exact_default_writer' if exact_writer else 'exact_original_consistent' if exact_unchanged else 'unmatched',
        'restriction_rule_present':bool(restriction_present),
        'original_sha256':hashlib.sha256(original_raw.encode('utf-8')).hexdigest(),
        'observed_sha256':hashlib.sha256(observed_raw.encode('utf-8')).hexdigest(),
        'model_sources':contract['model_sources'], 'released_source_sha256':PRIMARY_SHA256,
        'counts':{'original':len(original), 'expected':len(expected), 'observed':len(observed), 'differences':len(differences)},
        'maximum_relative_error':contract['maximum_relative_error'], 'rows':rows, 'differences':differences,
        'external_input_change_authorized':False, 'model_physics_validated':False,
        'compiled_include_consumption_independently_observed':False,
        'scope':'literal source consistency and exact released serialization only',
        'limitations':['Binary64 expression evaluation is source projection, not an independent high-precision physics calculation.',
            'Unknown scalar D-exponent lexemes remain native strings; they are not consumed numerical model inputs.',
            'Functions use the pinned ModelReader global scope, not a capture of model parameters/functions; unsupported namespace/evaluation-order collisions refuse.',
            'Restriction rules, automatic widths, complex-mass transforms and unsupported dynamic UFO expressions require a revised protocol.',
            'Unchanged cards require the full derived population and exact native-value consistency; a skipped update is not accepted.']}
