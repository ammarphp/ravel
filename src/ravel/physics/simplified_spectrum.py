"""Declarative simplified-model spectra written as SLHA2 cards, with a decay-closure check.

A spectrum request declares the masses of the states that take part, the mass
of decoupled states, mixing matrices (explicit, or the identity for pure gauge
states), decay tables with branching fractions or partial widths (two- and
three-body rows), the stable invisible states and the states produced in the
hard process. The builder writes ``MODSEL``, ``MASS``, mixing blocks and
``DECAY`` tables; an optional pinned base card (for example a generator's
default MSSM_SLHA2 parameter card) supplies every other block unchanged.

``check_card`` inspects any parsed card:

* ``MODSEL`` is present;
* no produced or intermediate state has a width-only table;
* branching fractions are nonnegative and sum to one;
* every channel is kinematically open (sum of daughter masses below the parent);
* every decay chain from the produced states ends in Standard Model particles or
  declared stable states, and declared invisible states have zero width;
* masses needed for these checks come from the card or the declared Standard
  Model masses; a missing mass is reported, never assumed.
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import json
import math
import re
from pathlib import Path

SCOPE = 'Declared simplified-model spectrum, SLHA2 card and decay-closure checks'
LIMITATIONS = [
    'Masses, mixing and decay tables are declared inputs; no spectrum calculator or width calculation is run.',
    'Kinematic checks use the card and declared Standard Model masses; light quarks, leptons, neutrinos, '
    'photons and gluons are treated as massless unless the card gives a mass.',
    'Generator-level decay handling (Pythia, MadSpin) must still be checked against the produced events.',
]
SPARTICLES = (1000001, 1000002, 1000003, 1000004, 1000005, 1000006, 2000001, 2000002, 2000003, 2000004,
              2000005, 2000006, 1000011, 1000012, 1000013, 1000014, 1000015, 1000016, 2000011, 2000013,
              2000015, 1000021, 1000022, 1000023, 1000025, 1000035, 1000024, 1000037)
MIXING_SIZES = {'NMIX': 4, 'UMIX': 2, 'VMIX': 2, 'STOPMIX': 2, 'SBOTMIX': 2, 'STAUMIX': 2}
MASSLESS_SM = {1, 2, 3, 4, 11, 12, 13, 14, 16, 21, 22}
MASSIVE_SM = {5, 6, 15, 23, 24, 25}


# ----------------------------------------------------------------- SLHA text

def _number(token):
    try:
        return int(token)
    except ValueError:
        try:
            return float(token.replace('d', 'e').replace('D', 'E'))
        except ValueError:
            return token


def parse_slha(text):
    blocks, decays = {}, {}
    current = None
    for raw in text.splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        tokens = line.split()
        head = tokens[0].upper()
        if head == 'BLOCK':
            name = tokens[1].upper()
            q = None
            match = re.search(r'Q\s*=\s*([-+0-9.eEdD]+)', line, re.I)
            if match:
                q = _number(match.group(1))
            current = ('block', name)
            blocks[name] = {'q': q, 'entries': {}}
        elif head == 'DECAY':
            pdg = int(tokens[1])
            current = ('decay', pdg)
            decays[pdg] = {'width': float(_number(tokens[2])), 'channels': []}
        elif current is None:
            raise ValueError(f'SLHA data line outside a block: {raw!r}')
        elif current[0] == 'block':
            values = [_number(t) for t in tokens]
            keys = []
            while len(values) > 1 and type(values[0]) is int:
                keys.append(values.pop(0))
            value = values[0] if len(values) == 1 else ' '.join(str(v) for v in values)
            blocks[current[1]]['entries'][tuple(keys)] = value
        else:
            br, nda = float(_number(tokens[0])), int(tokens[1])
            daughters = tuple(int(t) for t in tokens[2:2 + nda])
            if len(daughters) != nda:
                raise ValueError(f'decay row has fewer daughters than declared: {raw!r}')
            decays[current[1]]['channels'].append((br, daughters))
    return {'blocks': blocks, 'decays': decays}


def _format_value(value):
    if isinstance(value, float):
        return f'{value: .6e}'
    return f'{value}'


def write_slha(doc, *, comments=None):
    lines = []
    for line in comments or []:
        lines.append('# ' + line)
    for name, block in doc['blocks'].items():
        header = f'BLOCK {name}' + (f' Q= {block["q"]:.6e}' if block.get('q') is not None else '')
        lines.append(header)
        for keys, value in block['entries'].items():
            lines.append('  ' + ' '.join(f'{k:>9d}' if len(keys) == 1 else f'{k:>3d}' for k in keys)
                         + '   ' + _format_value(value))
    for pdg, decay in doc['decays'].items():
        lines.append(f'DECAY   {pdg:d}   {decay["width"]:.6e}')
        for br, daughters in decay['channels']:
            lines.append(f'   {br:.6e}   {len(daughters)}   ' + '   '.join(f'{d:d}' for d in daughters))
    return '\n'.join(lines) + '\n'


# ------------------------------------------------------------------ builder

def _pdg(value):
    if isinstance(value, bool):
        raise ValueError('PDG code must be an integer')
    try:
        code = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'invalid PDG code {value!r}') from exc
    if str(code) != str(value).strip() and value != code:
        raise ValueError(f'invalid PDG code {value!r}')
    return code


def _positive(value, name, allow_zero=False):
    if isinstance(value, bool) or type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    if value < 0 or (value == 0 and not allow_zero):
        raise ValueError(f'{name} must be positive')
    return float(value)


def _matrix(name, value):
    if value == 'identity':
        if name not in MIXING_SIZES:
            raise ValueError(f'no identity preset for {name}; give an explicit matrix')
        n = MIXING_SIZES[name]
        return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    if not isinstance(value, dict) or set(value) != {'matrix', 'source'}:
        raise ValueError(f'{name} needs "identity" or {{"matrix": [[...]], "source": "..."}}')
    if not isinstance(value['source'], str) or not value['source'].strip():
        raise ValueError(f'{name} matrix needs its source')
    rows = value['matrix']
    if not isinstance(rows, list) or not rows or any(not isinstance(r, list) or len(r) != len(rows) for r in rows):
        raise ValueError(f'{name} must be a square matrix')
    values = [[x for x in row] for row in rows]
    if any(isinstance(x, bool) or type(x) not in (int, float) or not math.isfinite(x) for row in values for x in row):
        raise ValueError(f'{name} entries must be finite numbers')
    return [[float(x) for x in row] for row in values]


def _decay_table(pdg, decay, tolerance):
    allowed = {'width_GeV', 'channels', 'source'}
    if not isinstance(decay, dict) or set(decay) - allowed or 'channels' not in decay:
        raise ValueError(f'decay table {pdg} keys: ' + ', '.join(sorted(allowed)))
    channels = decay['channels']
    if not isinstance(channels, list):
        raise ValueError(f'decay table {pdg} channels must be a list')
    partial = [c for c in channels if 'partial_width_GeV' in c]
    if partial and len(partial) != len(channels):
        raise ValueError(f'decay table {pdg} mixes partial widths and branching fractions')
    rows = []
    if partial:
        widths = [_positive(c['partial_width_GeV'], f'partial width in {pdg}', allow_zero=True) for c in channels]
        total = math.fsum(widths)
        if total <= 0:
            raise ValueError(f'decay table {pdg} has zero total width')
        if 'width_GeV' in decay and not math.isclose(decay['width_GeV'], total, rel_tol=tolerance):
            raise ValueError(f'decay table {pdg}: declared width differs from the sum of partial widths')
        for c, w in zip(channels, widths):
            rows.append((w / total, tuple(_pdg(d) for d in c['daughters'])))
        return total, rows
    width = _positive(decay.get('width_GeV'), f'width of {pdg}', allow_zero=True)
    for c in channels:
        if set(c) != {'br', 'daughters'}:
            raise ValueError(f'decay rows of {pdg} need br and daughters')
        daughters = c['daughters']
        if not isinstance(daughters, list) or not 2 <= len(daughters) <= 6:
            raise ValueError(f'decay rows of {pdg} need two to six daughters')
        rows.append((_positive(c['br'], f'branching fraction in {pdg}', allow_zero=True),
                     tuple(_pdg(d) for d in daughters)))
    if rows:
        total = math.fsum(r[0] for r in rows)
        if not math.isclose(total, 1.0, rel_tol=0, abs_tol=tolerance):
            raise ValueError(f'branching fractions of {pdg} sum to {total:.6g}, not 1')
    return width, rows


def validate_spec(spec):
    allowed = {'schema_version', 'basis', 'modsel', 'masses', 'decoupled', 'mixing', 'decays', 'invisible',
               'stable', 'produced', 'sm_masses_GeV', 'base_card', 'source', 'br_tolerance', 'model_pdgs'}
    if not isinstance(spec, dict) or spec.get('schema_version') != 1:
        raise ValueError('simplified spectrum schema_version 1 required')
    extra = set(spec) - allowed
    if extra:
        raise ValueError('unknown spectrum keys: ' + ', '.join(sorted(extra)))
    for key in ('modsel', 'masses', 'decays', 'invisible', 'produced', 'source'):
        if key not in spec:
            raise ValueError(f'spectrum request needs {key}')
    if spec.get('basis', 'generic-SLHA') not in ('generic-SLHA', 'MSSM_SLHA2'):
        raise ValueError('basis must be generic-SLHA or MSSM_SLHA2')
    if spec.get('basis') == 'MSSM_SLHA2' and 'base_card' not in spec:
        raise ValueError('an MSSM_SLHA2 card needs a pinned base_card supplying the remaining blocks')
    if not isinstance(spec['modsel'], dict) or not spec['modsel']:
        raise ValueError('MODSEL entries are required')
    if not isinstance(spec['source'], str) or not spec['source'].strip():
        raise ValueError('a source or synthetic-control description is required')
    if 'model_pdgs' in spec and (not isinstance(spec['model_pdgs'], list) or not spec['model_pdgs']
                                or any(type(p) is not int or p == 0 for p in spec['model_pdgs'])):
        raise ValueError('model_pdgs must list nonzero integer UFO particle identities')
    return spec


def build_document(spec, *, base_dir=None):
    validate_spec(spec)
    tolerance = spec.get('br_tolerance', 1e-6)
    base_dir = Path(base_dir or Path.cwd())
    if 'base_card' in spec:
        from ravel.physics import declared_study
        doc = parse_slha(declared_study.pinned(spec['base_card'], base_dir).read_text())
    else:
        doc = {'blocks': {}, 'decays': {}}
    blocks = doc['blocks']
    blocks['MODSEL'] = {'q': None, 'entries': {(int(k),): _number(str(v)) for k, v in spec['modsel'].items()}}
    mass = blocks.setdefault('MASS', {'q': None, 'entries': {}})['entries']
    declared = {_pdg(k): float(v) for k, v in spec['masses'].items()}
    for pdg, value in declared.items():
        if not math.isfinite(value):
            raise ValueError(f'mass of {pdg} must be finite')
        mass[(pdg,)] = value
    decoupled = []
    if 'decoupled' in spec:
        d = spec['decoupled']
        heavy = _positive(d.get('mass_GeV'), 'decoupled mass')
        if d.get('pdgs') == 'all-other-sparticles':
            decoupled = [p for p in SPARTICLES if p not in declared]
        elif isinstance(d.get('pdgs'), list):
            decoupled = [_pdg(p) for p in d['pdgs']]
        else:
            raise ValueError('decoupled.pdgs must be a list or "all-other-sparticles"')
        for pdg in decoupled:
            if pdg in declared:
                raise ValueError(f'{pdg} is both declared and decoupled')
            mass[(pdg,)] = heavy
            doc['decays'][pdg] = {'width': 0.0, 'channels': []}
    blocks['MASS']['entries'] = dict(sorted(mass.items()))
    for name, value in (spec.get('mixing') or {}).items():
        name = name.upper()
        matrix = _matrix(name, value)
        blocks[name] = {'q': None, 'entries': {(i + 1, j + 1): matrix[i][j]
                                               for i in range(len(matrix)) for j in range(len(matrix))}}
    for key, decay in spec['decays'].items():
        width, rows = _decay_table(_pdg(key), decay, tolerance)
        doc['decays'][_pdg(key)] = {'width': width, 'channels': rows}
    for pdg in [*spec['invisible'], *spec.get('stable', [])]:
        doc['decays'].setdefault(_pdg(pdg), {'width': 0.0, 'channels': []})
    return doc


def build(spec, *, base_dir=None, check=True):
    doc = build_document(spec, base_dir=base_dir)
    if check:
        report = check_card(doc, invisible=spec['invisible'], stable=spec.get('stable', []),
                            produced=spec['produced'], sm_masses=spec.get('sm_masses_GeV', {}),
                            model_pdgs=spec.get('model_pdgs'),
                            tolerance=spec.get('br_tolerance', 1e-6))
        if not report['passed']:
            raise ValueError('spectrum fails its closure checks: '
                             + '; '.join(f['message'] for f in report['findings'] if f['severity'] == 'error'))
    return write_slha(doc, comments=['Simplified-model spectrum from a declared request.',
                                     'Source: ' + spec['source'].replace('\n', ' ')])


# ----------------------------------------------------------------- checks

def check_card(doc, *, invisible, produced, sm_masses, stable=(), tolerance=1e-4, model_pdgs=None):
    findings = []
    def error(code, message, pdg=None):
        findings.append({'severity': 'error', 'code': code, 'pdg': pdg, 'message': message})
    invisible = {abs(int(p)) for p in invisible}
    stable = {abs(int(p)) for p in stable} | invisible
    if 'MODSEL' not in doc['blocks'] or not doc['blocks']['MODSEL']['entries']:
        error('modsel_missing', 'MODSEL block is missing')
    masses = {k[0]: v for k, v in doc['blocks'].get('MASS', {}).get('entries', {}).items() if len(k) == 1}

    def mass_of(pdg):
        a = abs(pdg)
        if a in masses and isinstance(masses[a], (int, float)):
            return abs(float(masses[a]))
        if str(a) in sm_masses:
            return float(sm_masses[str(a)])
        if a in sm_masses:
            return float(sm_masses[a])
        if a in MASSLESS_SM:
            return 0.0
        return None

    decays = doc['decays']
    outside = []
    if model_pdgs is not None:
        model = {abs(_pdg(p)) for p in model_pdgs}
        mentioned = set(masses) | set(decays) | {abs(p) for d in decays.values() for _, ds in d['channels'] for p in ds}
        outside = sorted(mentioned - model - MASSLESS_SM - MASSIVE_SM)
        for pdg in outside:
            table = decays.get(pdg)
            if pdg not in stable or pdg not in invisible:
                error('outside_model_undeclared', f'outside-model state {pdg} must be declared stable and invisible', pdg)
            if table is None or table['width'] != 0 or table['channels']:
                error('outside_model_unstable', f'outside-model state {pdg} needs an explicit zero-width DECAY table', pdg)
            if mass_of(pdg) is None:
                error('mass_unknown', f'outside-model state {pdg} needs a declared mass', pdg)
        for pdg in produced:
            if abs(pdg) not in model:
                error('outside_model_produced', f'produced state {pdg} is outside the generator model', pdg)
    for pdg in sorted(stable):
        if pdg in decays and (decays[pdg]['width'] > 0 or decays[pdg]['channels']):
            error('invisible_decays' if pdg in invisible else 'stable_decays',
                  f'declared stable state {pdg} has a nonzero width or decay rows', pdg)
    visited, census, queue = set(), set(), [abs(int(p)) for p in produced]
    while queue:
        pdg = queue.pop(0)
        if pdg in visited:
            continue
        visited.add(pdg)
        if pdg in stable:
            census.add(pdg)
            continue
        table = decays.get(pdg)
        if table is None or (table['width'] == 0 and not table['channels']):
            if pdg < 1000000 and pdg not in (35, 36, 37):
                continue  # Standard Model particle: decayed by the shower
            error('undeclared_stable', f'{pdg} has no decay table and is not declared stable or invisible', pdg)
            continue
        if not table['channels']:
            error('width_only', f'{pdg} has a width-only decay table; generators import no channels', pdg)
            continue
        if table['width'] <= 0:
            error('zero_width_with_channels', f'{pdg} lists decay rows with zero total width', pdg)
        brs = [br for br, _ in table['channels']]
        if any(br < 0 for br in brs):
            error('negative_branching', f'{pdg} has a negative branching fraction', pdg)
        total = math.fsum(brs)
        if not math.isclose(total, 1.0, rel_tol=0, abs_tol=tolerance):
            error('branching_sum', f'branching fractions of {pdg} sum to {total:.6g}', pdg)
        parent = mass_of(pdg)
        for br, daughters in table['channels']:
            if br == 0:
                continue
            values = [mass_of(d) for d in daughters]
            if parent is None or any(v is None for v in values):
                missing = [d for d, v in zip(daughters, values) if v is None] + ([pdg] if parent is None else [])
                error('mass_unknown', f'masses unknown for {sorted(set(abs(m) for m in missing))}; '
                                      'declare them in the card or sm_masses_GeV', pdg)
            elif math.fsum(values) >= parent:
                error('closed_channel', f'{pdg} -> {list(daughters)} is kinematically closed '
                                        f'({math.fsum(values):.6g} >= {parent:.6g} GeV)', pdg)
            for d in daughters:
                queue.append(abs(d))
    return {'passed': not any(f['severity'] == 'error' for f in findings), 'findings': findings,
            'reached_states': sorted(visited), 'invisible_census': sorted(census & invisible),
            'stable_census': sorted(census),
            **({'outside_model': outside} if model_pdgs is not None else {})}


def ufo_particle_pdgs(directory):
    """Read literal UFO Particle PDGs without importing or executing the model."""
    path = Path(directory) / 'particles.py'
    if not path.is_file():
        raise ValueError('model membership requires UFO particles.py')
    tree = ast.parse(path.read_text())
    codes = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, 'attr', None)
        if name != 'Particle':
            continue
        values = [kw.value for kw in node.keywords if kw.arg == 'pdg_code']
        if len(values) != 1:
            raise ValueError('UFO Particle requires a literal pdg_code for membership')
        try:
            value = ast.literal_eval(values[0])
        except (ValueError, TypeError) as exc:
            raise ValueError('UFO Particle pdg_code is not a literal integer') from exc
        if type(value) is not int or value == 0:
            raise ValueError('UFO Particle pdg_code must be a nonzero literal integer')
        codes.add(abs(value))
    if not codes:
        raise ValueError('UFO particles.py supplies no literal Particle PDGs')
    return sorted(codes)


def generator_document(doc, outside_model):
    """A generation-only copy excludes shower states and their decay channels.

    Full decay tables stay in the separate shower SLHA. The retained parent width
    is a declared input; no replacement decay or width is calculated.
    """
    outside = set(outside_model)
    result = deepcopy(doc)
    mass = result['blocks'].get('MASS', {}).get('entries', {})
    for key in list(mass):
        if len(key) == 1 and abs(key[0]) in outside:
            del mass[key]
    for pdg in list(result['decays']):
        if abs(pdg) in outside:
            del result['decays'][pdg]
        elif any(abs(p) in outside for _, ds in result['decays'][pdg]['channels'] for p in ds):
            result['decays'][pdg]['channels'] = []
    return result


def compare_banner(lhe_text, card_doc, *, rel_tol=1e-6):
    """Compare the SLHA block embedded in an LHE header with the intended card."""
    match = re.search(r'<slha>(.*?)</slha>', lhe_text, re.S | re.I)
    if not match:
        raise ValueError('no <slha> section in the event-file header')
    banner = parse_slha(match.group(1))
    differences = []
    for pdg, decay in card_doc['decays'].items():
        other = banner['decays'].get(pdg)
        if other is None:
            differences.append({'pdg': pdg, 'field': 'decay table', 'card': decay['width'], 'banner': None})
            continue
        if not math.isclose(decay['width'], other['width'], rel_tol=rel_tol, abs_tol=1e-300):
            differences.append({'pdg': pdg, 'field': 'width', 'card': decay['width'], 'banner': other['width']})
        a = sorted((tuple(sorted(d)), br) for br, d in decay['channels'])
        b = sorted((tuple(sorted(d)), br) for br, d in other['channels'])
        if [x[0] for x in a] != [x[0] for x in b] or any(not math.isclose(x[1], y[1], rel_tol=rel_tol, abs_tol=1e-12)
                                                         for x, y in zip(a, b)):
            differences.append({'pdg': pdg, 'field': 'channels', 'card': a, 'banner': b})
    card_mass = card_doc['blocks'].get('MASS', {}).get('entries', {})
    banner_mass = banner['blocks'].get('MASS', {}).get('entries', {})
    for key, value in card_mass.items():
        if key not in banner_mass or not math.isclose(float(value), float(banner_mass[key]), rel_tol=rel_tol):
            differences.append({'pdg': key[0], 'field': 'mass', 'card': value, 'banner': banner_mass.get(key)})
    return {'passed': not differences, 'differences': differences}


# ------------------------------------------------------- science-mode adapter

def validate(task):
    from ravel.physics import declared_study
    return declared_study.validate_task(task)


def inputs(task, base):
    from ravel.physics import declared_study
    path, spec = declared_study.load_request(task, base)
    build_document(spec, base_dir=path.parent)
    extra = [__file__]
    if 'base_card' in spec:
        extra.append(declared_study.pinned(spec['base_card'], path.parent))
    return declared_study.inputs(path, extra)


def run(task, base, output):
    from ravel.physics import declared_study
    path, spec = declared_study.load_request(task, base)
    text = build(spec, base_dir=path.parent, check=False)
    report = check_card(parse_slha(text), invisible=spec['invisible'], stable=spec.get('stable', []),
                        produced=spec['produced'], sm_masses=spec.get('sm_masses_GeV', {}),
                        model_pdgs=spec.get('model_pdgs'),
                        tolerance=spec.get('br_tolerance', 1e-6))
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'simplified-spectrum.slha').open('x') as handle:
        handle.write(text)
    return declared_study.deliver(out, 'simplified-spectrum.json', {
        'status': 'passed' if report['passed'] else 'failed', 'physics_validated': False, 'scope': SCOPE,
        'request': {'path': str(path), 'sha256': declared_study.sha256(path)},
        'card': {'path': str(out / 'simplified-spectrum.slha'), 'sha256': declared_study.sha256(out / 'simplified-spectrum.slha')},
        'closure': report, 'assumptions': {'source': spec['source'], 'invisible': spec['invisible'],
                                           'decoupled': spec.get('decoupled'), 'mixing': spec.get('mixing')},
        'limitations': LIMITATIONS})


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel simplified-spectrum', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    b = sub.add_parser('build', help='write an SLHA2 card from a spectrum request and check its closure')
    b.add_argument('--spec', required=True, type=Path)
    b.add_argument('--out', required=True, type=Path)
    c = sub.add_parser('check', help='check decay closure of an existing SLHA card')
    c.add_argument('--card', required=True, type=Path)
    c.add_argument('--invisible', type=int, action='append', default=[])
    c.add_argument('--stable', type=int, action='append', default=[])
    c.add_argument('--produced', type=int, action='append', required=True)
    c.add_argument('--sm-masses', type=Path, help='JSON map of PDG code to mass in GeV')
    cb = sub.add_parser('compare-banner', help='compare the SLHA in an event-file header with a card')
    cb.add_argument('--lhe', required=True, type=Path)
    cb.add_argument('--card', required=True, type=Path)
    from ravel.physics import declared_study
    declared_study.plan_arguments(sub.add_parser('plan', help='prepare an approvable spectrum study'))
    args = parser.parse_args(argv)
    if args.command == 'plan':
        return declared_study.prepare(args, mode='simplified-spectrum',
                                      assumptions=['Masses, mixing and decay tables are declared inputs.',
                                                   'Invisible and stable states are declared explicitly.'])
    if args.command == 'build':
        spec = json.loads(args.spec.read_text())
        text = build(spec, base_dir=args.spec.resolve().parent)
        with args.out.open('x') as handle:
            handle.write(text)
        print(f'wrote {args.out}')
        return 0
    if args.command == 'check':
        sm = json.loads(args.sm_masses.read_text()) if args.sm_masses else {}
        report = check_card(parse_slha(args.card.read_text()), invisible=args.invisible, stable=args.stable,
                            produced=args.produced, sm_masses=sm)
        print(json.dumps(report, indent=2))
        return 0 if report['passed'] else 1
    report = compare_banner(args.lhe.read_text(errors='replace'), parse_slha(args.card.read_text()))
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
