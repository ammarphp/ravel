"""Declared generation/fit conventions and literal coupling-order coherence.

No model-name lookup, amplitude calculation, basis map or EFT-validity inference.
Terms denote possible monomials under the study's supplied order-group mapping;
selection rules or zero coefficients require separate source evidence.
"""
from dataclasses import asdict, dataclass
import hashlib
from itertools import combinations_with_replacement, product
import json
from pathlib import Path
import re

from . import model_tool_bridge as custody
from ravel.workflow.state_io import read_json


@dataclass(frozen=True)
class CouplingOrder:
    group: str
    level: str
    comparison: str
    value: int
    raw: str


@dataclass(frozen=True)
class GenerationConvention:
    schema_version: int
    kind: str
    process_card: dict
    raw_process_card: str
    model: dict
    basis_identifier: str | None
    ew_input_scheme: str | None
    validity_cutoff: str | None
    operator_groups: dict | None
    processes: list
    terms: list | None


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _text(value, label):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError('explicit ' + label + ' required')


def declaration(value):
    """Missing fields remain null, including an undeclared cutoff (not infinity)."""
    fields = {'basis_identifier', 'ew_input_scheme', 'validity_cutoff', 'operator_groups'}
    if type(value) is not dict or not set(value) <= fields:
        raise ValueError('closed generation convention declaration required')
    result = {key: value.get(key) for key in fields}
    for key in fields - {'operator_groups'}:
        if result[key] is not None:
            _text(result[key], key)
    groups = result['operator_groups']
    if groups is not None:
        if type(groups) is not dict or not 1 <= len(groups) <= 8:
            raise ValueError('bounded declared operator order groups required')
        axes = []
        for name, members in groups.items():
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name):
                raise ValueError('literal coupling-order group required')
            if type(members) is not list or not members:
                raise ValueError('nonempty operator group required')
            for axis in members:
                if type(axis) is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', axis):
                    raise ValueError('literal operator axis required')
            axes.extend(members)
        if len(axes) > 32 or len(set(axes)) != len(axes):
            raise ValueError('unique bounded operator axes required')
    return result


_ORDER = re.compile(r'(?<![\w^])([A-Za-z][A-Za-z0-9_]*)(\s*\^\s*2)?\s*(==|<=|>=|=|<|>)\s*(-?\d+)(?![\w.])')


def _nested(line):
    expression = _ORDER.sub('', line)
    return ',' in expression or expression.count('>') != 1


def parse_process_card(raw):
    """Observe MG amplitude orders (= means <=) versus squared-order sums.

    Exported cards join backslash continuations before stripping comments.
    Import/output/set lines are retained in raw custody, never executed here.
    """
    if type(raw) is not str or len(raw.encode()) > 2 * 1024**2:
        raise ValueError('bounded literal process card required')
    from .model_events import exported_process_commands
    rows = []
    for line in exported_process_commands(raw):
        if not line.startswith(('generate ', 'add process ')):
            continue
        orders = []
        for match in _ORDER.finditer(line):
            group, squared, comparison, number = match.groups()
            # MG squared '=' uses the same upper-bound convention as orders.
            orders.append(asdict(CouplingOrder(group, 'squared' if squared else 'amplitude',
                                               '<=' if comparison == '=' else comparison,
                                               int(number), match.group())))
        remainder = _ORDER.sub('', line)
        if '^' in remainder or re.search(r'\b[A-Za-z][\w]*\s*(?:==|<=|>=|=)\s*[-\d]', remainder):
            raise ValueError('unparsed coupling-order constraint: ' + line)
        # Decay-chain subprocesses carry their own orders; implied_terms leaves them undeclared.
        if not _nested(line) and len({(o['group'], o['level']) for o in orders}) != len(orders):
            raise ValueError('duplicate coupling-order constraint: ' + line)
        rows.append({'raw': line, 'constraints': orders})
    if not rows:
        raise ValueError('generation convention needs an actual generate/add process command')
    return rows


def _accept(order, value):
    return {'<=': value <= order['value'], '==': value == order['value'],
            '>=': value >= order['value'], '<': value < order['value'], '>': value > order['value']}[order['comparison']]


def implied_terms(processes, groups):
    if groups is None:
        return None
    axes = sorted(axis for members in groups.values() for axis in members)
    axis_group = {axis: name for name, members in groups.items() for axis in members}
    population = set()
    for process in processes:
        if _nested(process['raw']):
            return None  # Nested subprocess orders need a separate supplied mapping.
        constraints = [o for o in process['constraints'] if o['group'] in groups]
        # Do not apply generator defaults or silently truncate higher insertions.
        for group in groups:
            bound = [o for o in constraints if o['group'] == group and o['comparison'] in ('<=', '<', '==')]
            if not any(0 <= o['value'] - (o['comparison'] == '<') <= (1 if o['level'] == 'amplitude' else 2) for o in bound):
                return None
        # Independent order groups can jointly admit degree four even when
        # each amplitude group is bounded by one. Never drop that population.
        maximum = 0
        for group in groups:
            relevant = [o for o in constraints if o['group'] == group]
            allowed = [a+b for a in range(3) for b in range(3) if all(
                _accept(o,a+b) if o['level']=='squared' else _accept(o,a) and _accept(o,b) for o in relevant)]
            if not allowed:
                break
            maximum += max(allowed)
        else:
            if maximum > 2:
                return None
        for degree in range(3):
            for term in combinations_with_replacement(axes, degree):
                for split in product((0, 1), repeat=degree):
                    left = {g: sum(axis_group[a] == g and s == 0 for a, s in zip(term, split)) for g in groups}
                    right = {g: sum(axis_group[a] == g and s == 1 for a, s in zip(term, split)) for g in groups}
                    if all(_accept(o, left[o['group']] + right[o['group']]) if o['level'] == 'squared'
                           else _accept(o, left[o['group']]) and _accept(o, right[o['group']]) for o in constraints):
                        population.add(term)
                        break
    return [list(t) for t in sorted(population, key=lambda t: (len(t), t))]


def build(raw, process_pin, model, declared=None):
    declared = declaration({} if declared is None else declared)
    if type(model) is not dict or set(model) != {'identifier', 'pin', 'restriction'}:
        raise ValueError('explicit model identifier, pin and restriction required')
    _text(model['identifier'], 'model identifier')
    if not re.fullmatch('[0-9a-f]{64}', str(model['pin'])):
        raise ValueError('actual model source digest required')
    if model['restriction'] is not None:
        _text(model['restriction'], 'model restriction')
    expected = hashlib.sha256(raw.encode()).hexdigest()
    if type(process_pin) is not dict or set(process_pin) != {'path', 'sha256'} or process_pin['sha256'] != expected:
        raise ValueError('generation convention process card differs from its pin')
    processes = parse_process_card(raw)
    return asdict(GenerationConvention(1, 'generation_convention', process_pin, raw, model,
                  declared['basis_identifier'], declared['ew_input_scheme'], declared['validity_cutoff'],
                  declared['operator_groups'], processes, implied_terms(processes, declared['operator_groups'])))


def model_events_record(config, raw, base=None):
    """Planning and ending receipt use the same declared and pinned source bytes."""
    process_pin = dict(config['cards']['process'])
    if base is not None:
        process_pin['path'] = str(custody._pin(process_pin, base))
    return build(raw, process_pin,
                 {'identifier': config['model_tree']['root'], 'pin': config['model_tree']['manifest']['sha256'],
                  'restriction': 'full'}, config.get('conventions'))


def fit_convention(semantic):
    eft = semantic['eft']
    axes = eft['target_basis']
    terms = [[], *[[a] for a in axes if eft['linear']],
             *[[a, a] for a in axes if eft['quadratic']], *[sorted(p) for p in eft['mixed_pairs']]]
    for key in ('basis_identifier', 'ew_input_scheme', 'validity_cutoff'):
        if eft.get(key) is not None:
            _text(eft[key], key)
    return {'basis_identifier': eft.get('basis_identifier'), 'ew_input_scheme': eft.get('ew_input_scheme'),
            'validity_cutoff': eft.get('validity_cutoff'),
            'terms': sorted(terms, key=lambda t: (len(t), t))}


def compare(record, fit):
    """Return exact differences and CHECK-IN flags, never equate unknown values."""
    differences, flags = {}, []
    for key in ('basis_identifier', 'ew_input_scheme', 'validity_cutoff', 'terms'):
        a, b = record[key], fit[key]
        if a is None or b is None:
            flags.append('CHECK-IN: ' + key + ' undeclared on ' + ('generation and fit' if a is None and b is None else 'generation' if a is None else 'fit'))
        elif a != b:
            differences[key] = {'generation': a, 'fit': b}
    return differences, flags


def _transport(exception, record, fit, base, pin, read):
    """Recompute the existing algebra and require its actual ordinary approval."""
    from . import eft_conventions
    from ravel.workflow import science
    rd = custody._regular(exception['approval_run'], base, directory=True)
    plan = science.verify_plan(rd, approved=True)
    spec = science.execution_spec(rd)
    if spec['mode'] != 'eft-convention-transport':
        raise ValueError('approved convention transport operation required')
    rp = pin(exception['transport_request'], base)
    result_path = pin(exception['transport_result'], base)
    if spec['task'] != {'request': str(rp)} or result_path != (rd / plan['output_directory'] / 'eft-convention-transport.json').resolve():
        raise ValueError('transport approval does not bind the supplied request/result')
    result = eft_conventions.verify_result({'request': str(rp)}, rp.parent, read(result_path))
    for side, wanted in (('source_convention', record), ('target_convention', fit)):
        c = result[side]
        axes = sorted({a for t in wanted['terms'] for a in t})
        if c['basis'] != wanted['basis_identifier'] or sorted(c['axes']) != axes:
            raise ValueError('approved transport differs from generation/fit basis or axes')
    request = read(rp)
    polynomial = read(pin(request['polynomial'], rp.parent))
    source_terms = {(), *[(a['axis'],) for o in polynomial['observables'] for a in o['linear']],
                    *[tuple(sorted(a['axes'])) for o in polynomial['observables'] for a in o['quadratic']]}
    target_terms = {tuple(sorted(t['axes'])) for o in result['binary64_projection'] for t in o['terms']}
    if source_terms != {tuple(t) for t in record['terms']} or target_terms != {tuple(t) for t in fit['terms']}:
        raise ValueError('approved transport differs from complete generation/fit term population')
    return [rd / science.PLAN, rd / science.APPROVAL, rd / 'inputs/checkin1.json', rp, result_path,
            *eft_conventions.inputs({'request': str(rp)}, rp.parent)]


def check_fit(semantic, base, *, pin=None, read=None, card=None):
    """Shared fit-handoff and native-statistics boundary with nested input custody."""
    pin = pin or custody._pin
    read = read or read_json
    fit = fit_convention(semantic)
    binding = semantic.get('generation_coherence')
    if binding is None:
        return {'status': 'flagged', 'flags': ['CHECK-IN: generation convention record undeclared',
                *['CHECK-IN: fit ' + k + ' undeclared' for k in ('basis_identifier', 'ew_input_scheme', 'validity_cutoff') if fit[k] is None]],
                'differences': {}, 'paths': []}
    if type(binding) is not dict or set(binding) != {'record', 'exception'}:
        raise ValueError('generation coherence needs record pin and explicit exception or null')
    path = pin(binding['record'], base)
    document = read(path)
    record = document if document.get('kind') == 'generation_convention' else document.get('generation_convention')
    if type(record) is not dict or set(record) != set(GenerationConvention.__dataclass_fields__):
        raise ValueError('complete generation convention record required')
    process_card = pin(record['process_card'], path.parent)
    from .model_events import authenticated_text
    raw = authenticated_text(process_card, record['process_card']['sha256'])
    rebuilt = build(raw, record['process_card'], record['model'], {k: record[k] for k in
                    ('basis_identifier', 'ew_input_scheme', 'validity_cutoff', 'operator_groups')})
    if rebuilt != record:
        raise ValueError('generation convention record differs from actual process card/declaration')
    if card is not None:
        expected = {tuple(t) for t in fit['terms']}
        names = {'x'.join(t): tuple(t) for t in fit['terms'] if t}
        names.update({'x'.join(reversed(t)): tuple(t) for t in fit['terms'] if len(t)==2})
        for row in card['predictions']:
            actual = {()}
            for modifier in row['modifiers']:
                if modifier.get('type', 'WC') != 'WC':
                    continue
                name = modifier['name']
                if name not in names:
                    raise ValueError('fit card term contradicts semantic convention: ' + name)
                if names[name] in actual:
                    raise ValueError('duplicate fit card polynomial term: ' + name)
                actual.add(names[name])
            if actual != expected:
                raise ValueError('fit card omits declared semantic terms: ' + repr(sorted(expected - actual)))
    differences, flags = compare(record, fit)
    paths = [path, process_card]
    exception = binding['exception']
    if exception is not None:
        ep = pin(exception, base); ex = read(ep); paths.append(ep)
        if type(ex) is not dict:
            raise ValueError('pinned convention exception document required')
        common = {'kind', 'generation_sha256', 'fit', 'effect', 'reason'}
        extra = {'approval_run', 'transport_request', 'transport_result'} if ex.get('kind') == 'convention_transport' else set()
        if set(ex) != common | extra or ex['generation_sha256'] != digest(record) or ex['fit'] != fit:
            raise ValueError('convention exception must bind exact generation and fit conventions')
        for k in ('effect', 'reason'):
            _text(ex[k], 'recorded convention ' + k)
        if ex['kind'] == 'declared_truncation':
            if set(differences) != {'terms'} or not {tuple(t) for t in fit['terms']} < {tuple(t) for t in record['terms']}:
                raise ValueError('declared truncation may only remove recorded generation terms')
        elif ex['kind'] == 'convention_transport':
            if not set(differences) <= {'basis_identifier', 'terms'} or flags:
                raise ValueError('convention transport cannot change scheme/cutoff or fill undeclared conventions')
            paths += _transport(ex, record, fit, base, pin, read)
        elif ex['kind'] != 'deviation':
            raise ValueError('known recorded convention exception required')
        flags.append('CHECK-IN: recorded ' + ex['kind'] + ': ' + ex['effect'])
    elif differences:
        detail = []
        for key, values in differences.items():
            if key == 'terms':
                gen, fitted = ({tuple(t) for t in values[k]} for k in ('generation', 'fit'))
                describe = lambda t: 'SM' if not t else ('linear' if len(t)==1 else 'square' if t[0]==t[1] else 'cross') + '(' + ','.join(t) + ')'
                detail.append('terms: fit adds ' + repr([describe(t) for t in sorted(fitted - gen)]) + '; fit omits ' + repr([describe(t) for t in sorted(gen - fitted)]))
            else:
                detail.append(key + ': generation=' + repr(values['generation']) + ', fit=' + repr(values['fit']))
        raise ValueError('generation/fit convention mismatch; ' + '; '.join(detail) + '. Record convention transport or a deviation with its effect.')
    return {'status': 'flagged' if flags else 'matched', 'flags': flags, 'differences': differences, 'paths': paths}


def checkin(spec, base):
    """Approval-bound disclosure, without new runtime or a registry projection."""
    if spec['mode'] == 'model-events':
        from . import model_events
        path, config = model_events._load(spec['task'], base)
        card = custody._pin(config['cards']['process'], path.parent)
        record = model_events_record(config, model_events.authenticated_text(card, config['cards']['process']['sha256']),path.parent)
        flags = ['CHECK-IN: generation ' + k + ' undeclared' for k in
                 ('basis_identifier', 'ew_input_scheme', 'validity_cutoff', 'terms') if record[k] is None]
        return {'generation_convention': record, 'flags': flags}
    if spec['mode'] == 'sfitter-native-fit':
        from . import sfitter_native
        path, config = sfitter_native._load(spec['task'], base)
        if config['semantic_manifest'] is not None:
            sp = custody._pin(config['semantic_manifest'], path.parent)
            result = check_fit(read_json(sp), sp.parent)
            return {k: v for k, v in result.items() if k != 'paths'}
    return {}
