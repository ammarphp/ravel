"""Author a FeynRules model extending the Standard Model from a typed ModelSpec.

A ModelSpec is the structured form of a supplied Lagrangian: new fields with
spin, colour and weak representation, exact-rational hypercharge and electric
charge, PDG code, mass and width; parameters with LHA block and index; and
Lagrangian terms, each with its LaTeX span, its FeynRules operator, the fields
it contains and the couplings it uses. The spec comes from the person or the
host agent reading the Lagrangian; it is confirmed at CHECK-IN 1 before any
model is generated.

From a spec this module

* renders a FeynRules ``.fr`` file that extends ``SM.fr`` (canonical kinetic
  and mass terms are generated for every new field; interaction terms are the
  declared operators);
* lints it (``fr_lint``) and checks charge neutrality of every declared
  monomial with exact rational arithmetic;
* writes a FeynRules run script that loads the model, evaluates
  CheckHermiticity, CheckDiagonalQuadraticTerms, CheckDiagonalMassTerms and
  CheckKineticTermNormalisation in both Feynman and unitary gauge, and writes a
  UFO; and adjudicates the typed verdicts (unitary gauge decides; Feynman-gauge
  Goldstone mixing is waived only when FeynRules reported it);
* checks the UFO statically (``ufo_check``), admits it (``model_admission``:
  vertex quantum numbers, conjugate vertices, Hermiticity, MadGraph gauge,
  Lorentz and permutation checks) and records a model card.

Templates for common extensions (scalar and vector leptoquarks, a neutral
vector with vector and axial couplings and optional kinetic mixing, an
axion-like particle with gauge couplings, generic singlet scalars, vectors and
vector-like fermions) build specs from supplied values. Physics values have no
defaults. Generated models are labelled ``generated_contract_checked``;
treating one as trusted needs a human review record.

Supported tier: new fields that are SU(2) singlets in the colour singlet,
triplet or octet representation, extending the Standard Model in its gauge
basis. SU(2) multiplets, anti-triplets written as such, new gauge groups and
higher-spin fields are refused with ``unsupported_features`` so the request can
go to the SARAH or derivation route instead.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
from fractions import Fraction
from pathlib import Path

from ravel.paths import package_data_path

SCHEMA = 1
LABEL = 'generated_contract_checked'
SCOPE = ('Generated FeynRules source from a confirmed ModelSpec with static lint, exact charge census, '
         'two-gauge FeynRules checks, static UFO checks and model admission')
TIER = 'SM-gauge-basis extension via FeynRules (SU(2)-singlet new fields; colour 1, 3 or 8)'
LIMITATIONS = [
    'The ModelSpec is the reading of the supplied Lagrangian; the charge census and lint check its internal '
    'consistency, not that it matches the paper.',
    'FeynRules checks are tree-level consistency checks of the generated Lagrangian, not a UV completion or '
    'loop-level validation.',
    'Generated sources stay generated_contract_checked until a human review record promotes them.',
]
IDENTIFIER = re.compile(r'[A-Za-z][A-Za-z0-9]*')
KINDS = ('scalar', 'vector', 'fermion')
SU3 = {'1': 0, '3': 1, '8': 0}
SU3_INDEX = {'1': None, '3': 'Colour', '8': 'Gluon'}
INDEX_TYPES = ('Generation', 'Colour', 'Gluon', 'SU2D', 'SU2W')
# Standard Model fields as declared in FeynRules SM.fr: colour representation,
# weak dimension, hypercharge (unbroken-phase fields), electric charge
# (physical fields), and whether the field is real.
SM_FIELDS = {
    'vl': {'su3': '1', 'Q': Fraction(0), 'real': False, 'kind': 'fermion'},
    'l': {'su3': '1', 'Q': Fraction(-1), 'real': False, 'kind': 'fermion'},
    'uq': {'su3': '3', 'Q': Fraction(2, 3), 'real': False, 'kind': 'fermion'},
    'dq': {'su3': '3', 'Q': Fraction(-1, 3), 'real': False, 'kind': 'fermion'},
    'A': {'su3': '1', 'Q': Fraction(0), 'real': True, 'kind': 'vector'},
    'Z': {'su3': '1', 'Q': Fraction(0), 'real': True, 'kind': 'vector'},
    'W': {'su3': '1', 'Q': Fraction(1), 'real': False, 'kind': 'vector'},
    'G': {'su3': '8', 'Q': Fraction(0), 'Y': Fraction(0), 'su2': 1, 'real': True, 'kind': 'vector'},
    'H': {'su3': '1', 'Q': Fraction(0), 'real': True, 'kind': 'scalar'},
    'G0': {'su3': '1', 'Q': Fraction(0), 'real': True, 'kind': 'scalar'},
    'GP': {'su3': '1', 'Q': Fraction(1), 'real': False, 'kind': 'scalar'},
    'B': {'su3': '1', 'Y': Fraction(0), 'su2': 1, 'real': True, 'kind': 'vector'},
    'Wi': {'su3': '1', 'Y': Fraction(0), 'su2': 3, 'real': True, 'kind': 'vector'},
    'LL': {'su3': '1', 'Y': Fraction(-1, 2), 'su2': 2, 'real': False, 'kind': 'fermion'},
    'lR': {'su3': '1', 'Y': Fraction(-1), 'su2': 1, 'real': False, 'kind': 'fermion'},
    'QL': {'su3': '3', 'Y': Fraction(1, 6), 'su2': 2, 'real': False, 'kind': 'fermion'},
    'uR': {'su3': '3', 'Y': Fraction(2, 3), 'su2': 1, 'real': False, 'kind': 'fermion'},
    'dR': {'su3': '3', 'Y': Fraction(-1, 3), 'su2': 1, 'real': False, 'kind': 'fermion'},
    'Phi': {'su3': '1', 'Y': Fraction(1, 2), 'su2': 2, 'real': False, 'kind': 'scalar'},
}
SM_GOLDSTONES = ('G0', 'GP')
# Additive quantum numbers SM.fr assigns (besides charges).
SM_QUANTUM_NUMBERS = {'LeptonNumber': {'l': 1, 'vl': 1, 'LL': 1, 'lR': 1}}
SM_PDGS = {1, 2, 3, 4, 5, 6, 11, 12, 13, 14, 15, 16, 21, 22, 23, 24, 25, 82, 250, 251, 9000001, 9000002,
           9000003, 9000004}
SM_CLASS_INDICES = {('V', 1), ('V', 2), ('V', 3), ('V', 4), ('V', 11), ('V', 12), ('U', 1), ('U', 2), ('U', 31),
                    ('U', 32), ('U', 4), ('U', 11), ('U', 12), ('F', 1), ('F', 2), ('F', 3), ('F', 4), ('F', 11),
                    ('F', 12), ('F', 13), ('F', 14), ('F', 15), ('S', 1), ('S', 2), ('S', 3), ('S', 11)}
SM_PARTICLE_NAMES = {'a', 'z', 'w+', 'w-', 'g', 'h', 'g0', 'g+', 'g-', 've', 'vm', 'vt', 've~', 'vm~', 'vt~', 'e-',
                     'mu-', 'ta-', 'e+', 'mu+', 'ta+', 'u', 'c', 't', 'u~', 'c~', 't~', 'd', 's', 'b', 'd~', 's~',
                     'b~', 'gha', 'ghz', 'ghwp', 'ghwm', 'ghg'}
SM_SYMBOLS = {'aEWM1', 'aEW', 'Gf', 'aS', 'ee', 'cw', 'sw', 'gw', 'g1', 'gs', 'vev', 'lam', 'muH', 'MZ', 'MW', 'MH',
              'MTA', 'MT', 'MB', 'Me', 'MMU', 'WZ', 'WW', 'WH', 'WT', 'yl', 'yu', 'yd', 'CKM', 'cabi', 'ymdo',
              'ymup', 'yms', 'ymc', 'ymb', 'ymt', 'yme', 'ymm', 'ymtau'}
CLASS_LETTER = {'scalar': 'S', 'vector': 'V', 'fermion': 'F'}
FIRST_CLASS_INDEX = 100
MAX_SECONDS = 900


class UnsupportedModel(ValueError):
    """The spec is outside the FeynRules SM-extension tier; route elsewhere."""


# ------------------------------------------------------------------ spec

def rational(value, name):
    if isinstance(value, bool):
        raise ValueError(f'{name} must be an exact rational number')
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, str) and re.fullmatch(r'-?\d+(/\d+)?', value.strip()):
        return Fraction(value.strip())
    raise ValueError(f'{name} must be an exact rational such as "1/3" (decimals are refused)')


def _finite(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    if positive and value <= 0:
        raise ValueError(f'{name} must be positive')
    if nonnegative and value < 0:
        raise ValueError(f'{name} must be nonnegative')
    return float(value)


def _identifier(value, name, *, min_length=1):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value) or len(value) > 32:
        raise ValueError(f'{name} must be a letter followed by letters or digits (at most 32)')
    if len(value) < min_length:
        raise ValueError(f'{name} {value!r} is too short: at least {min_length} characters')
    return value


def _keys(doc, required, optional, name):
    if not isinstance(doc, dict):
        raise ValueError(f'{name} must be an object')
    missing = [k for k in required if k not in doc]
    extra = sorted(set(doc) - set(required) - set(optional))
    if missing:
        raise ValueError(f'{name} needs {", ".join(missing)}')
    if extra:
        raise ValueError(f'{name} has unknown keys: {", ".join(extra)}')


def _unsupported(field):
    reasons = []
    if field.get('su2', 1) != 1:
        reasons.append(f'{field.get("name")}: SU(2) multiplet new field (dimension {field.get("su2")})')
    if field.get('su3') not in SU3:
        reasons.append(f'{field.get("name")}: colour representation {field.get("su3")!r} '
                       '(declare an anti-triplet as its conjugate triplet with opposite charges)')
    if field.get('kind') not in KINDS:
        reasons.append(f'{field.get("name")}: field kind {field.get("kind")!r}')
    return reasons


def validate_spec(spec):
    """Check a ModelSpec; raise UnsupportedModel outside the tier, ValueError otherwise."""
    _keys(spec, ('schema_version', 'name', 'fields', 'parameters', 'lagrangian_terms', 'required_couplings'),
          ('description', 'source', 'extends', 'interaction_orders', 'optional_couplings', 'unsupported_features',
           'template', 'conventions', 'approximations'), 'ModelSpec')
    if spec['schema_version'] != SCHEMA:
        raise ValueError('ModelSpec schema_version 1 required')
    _identifier(spec['name'], 'model name', min_length=2)
    if spec.get('extends', 'SM') != 'SM':
        raise UnsupportedModel('only extensions of the FeynRules SM.fr model are in this tier')
    declared = list(spec.get('unsupported_features') or [])
    if declared:
        raise UnsupportedModel('the spec declares features outside this tier: ' + '; '.join(declared))
    if not isinstance(spec['fields'], list) or not spec['fields']:
        raise ValueError('at least one new field is required')
    names, pdgs, symbols = set(), set(), set()
    reasons = []
    for field in spec['fields']:
        _keys(field, ('name', 'kind', 'self_conjugate', 'su3', 'hypercharge', 'pdg', 'mass', 'width'),
              ('su2', 'electric_charge', 'latex', 'full_name', 'particle_name', 'antiparticle_name',
               'fermion_type', 'kinetic', 'quantum_numbers'), f'field {field.get("name")!r}')
        reasons += _unsupported(field)
    if reasons:
        raise UnsupportedModel('outside the FeynRules SM-extension tier: ' + '; '.join(reasons))
    orders = spec.get('interaction_orders') or []
    order_names = {'QCD', 'QED'}
    for order in orders:
        _keys(order, ('name', 'hierarchy'), ('description',), 'interaction order')
        _identifier(order['name'], 'interaction order name', min_length=2)
        if type(order['hierarchy']) is not int or order['hierarchy'] < 1:
            raise ValueError('interaction order hierarchy must be a positive integer')
        order_names.add(order['name'])
    for field in spec['fields']:
        name = _identifier(field['name'], 'field name', min_length=2)
        if name in names or name in SM_FIELDS or name in SM_SYMBOLS:
            raise ValueError(f'field name {name} is duplicated or clashes with the Standard Model')
        names.add(name)
        if type(field['self_conjugate']) is not bool:
            raise ValueError(f'{name}: self_conjugate must be true or false')
        y = rational(field['hypercharge'], f'{name} hypercharge')
        q = rational(field.get('electric_charge', field['hypercharge']), f'{name} electric charge')
        if q != y:
            raise ValueError(f'{name}: an SU(2) singlet has electric charge equal to its hypercharge ({y})')
        if field['self_conjugate'] and (q != 0 or field['su3'] == '3'):
            raise ValueError(f'{name}: a self-conjugate field must be neutral and not a colour triplet')
        if field['kind'] == 'fermion':
            ftype = field.get('fermion_type', 'majorana' if field['self_conjugate'] else 'dirac')
            if ftype not in ('dirac', 'majorana') or (ftype == 'majorana') != field['self_conjugate']:
                raise ValueError(f'{name}: fermion_type dirac (not self-conjugate) or majorana (self-conjugate)')
        elif 'fermion_type' in field:
            raise ValueError(f'{name}: fermion_type applies to fermions only')
        pdg = field['pdg']
        if type(pdg) is not int or pdg <= 0 or pdg in SM_PDGS or pdg in pdgs:
            raise ValueError(f'{name}: PDG code must be a positive integer not used by the SM or another field')
        pdgs.add(pdg)
        _keys(field['mass'], ('symbol', 'value'), ('description',), f'{name} mass')
        _keys(field['width'], ('symbol', 'value'), ('auto', 'description'), f'{name} width')
        for key in ('mass', 'width'):
            symbol = _identifier(field[key]['symbol'], f'{name} {key} symbol', min_length=2)
            if symbol in symbols or symbol in SM_SYMBOLS:
                raise ValueError(f'{name}: {key} symbol {symbol} is duplicated or clashes with the SM')
            symbols.add(symbol)
        _finite(field['mass']['value'], f'{name} mass', positive=True)
        _finite(field['width']['value'], f'{name} width', nonnegative=True)
        if 'auto' in field['width'] and type(field['width']['auto']) is not bool:
            raise ValueError(f'{name}: width auto must be true or false')
        kinetic = field.get('kinetic', 'canonical')
        if kinetic not in ('canonical', 'declared'):
            raise ValueError(f'{name}: kinetic is "canonical" (generated) or "declared" (supplied as a term)')
    params = {}
    for p in spec['parameters']:
        _keys(p, ('symbol', 'nature'), ('block', 'index', 'indices', 'value', 'expression', 'complex',
                                        'interaction_order', 'latex', 'description', 'unit'), 'parameter')
        symbol = _identifier(p['symbol'], 'parameter symbol', min_length=2)
        if symbol in params or symbol in symbols or symbol in names or symbol in SM_SYMBOLS:
            raise ValueError(f'parameter symbol {symbol} is duplicated or clashes with a field, mass, width or SM symbol')
        params[symbol] = p
        if p.get('complex', False) is not False:
            raise UnsupportedModel(f'{symbol}: complex parameters are outside this tier')
        indices = p.get('indices', [])
        if not isinstance(indices, list) or any(i not in INDEX_TYPES for i in indices) or len(indices) > 2:
            raise ValueError(f'{symbol}: indices must be up to two of {", ".join(INDEX_TYPES)}')
        if p['nature'] == 'external':
            _identifier(p.get('block'), f'{symbol} block', min_length=2)
            if p['block'].upper() in ('MASS', 'DECAY', 'SMINPUTS', 'YUKAWA', 'CKMBLOCK', 'QNUMBERS'):
                raise ValueError(f'{symbol}: block {p["block"]} is reserved')
            if indices:
                if indices != ['Generation'] * len(indices):
                    raise ValueError(f'{symbol}: external tensor parameters are indexed by Generation')
                _matrix_value(p.get('value'), len(indices), symbol)
                if 'index' in p:
                    raise ValueError(f'{symbol}: an indexed parameter takes its LHA codes from its indices')
            else:
                index = p.get('index')
                if not isinstance(index, list) or not 1 <= len(index) <= 2 or any(type(i) is not int or i < 1 for i in index):
                    raise ValueError(f'{symbol}: LHA index must be a list of one or two positive integers')
                _finite(p.get('value'), f'{symbol} value')
            if 'expression' in p:
                raise ValueError(f'{symbol}: an external parameter has a value, not an expression')
        elif p['nature'] == 'internal':
            if not isinstance(p.get('expression'), str) or not p['expression'].strip():
                raise ValueError(f'{symbol}: an internal parameter needs an expression')
            if 'value' in p or 'block' in p:
                raise ValueError(f'{symbol}: an internal parameter has an expression, not a value or block')
        else:
            raise ValueError(f'{symbol}: nature is external or internal')
        order = p.get('interaction_order')
        if order is not None:
            if (not isinstance(order, list) or len(order) != 2 or order[0] not in order_names
                    or type(order[1]) is not int or order[1] < 1):
                raise ValueError(f'{symbol}: interaction_order is [declared order name, positive integer]')
    addresses = set()
    for p in params.values():
        if p['nature'] == 'external' and not p.get('indices'):
            address = (p['block'].upper(), tuple(p['index']))
            if address in addresses:
                raise ValueError(f'duplicate LHA address {address}')
            addresses.add(address)
    ids = set()
    if not isinstance(spec['lagrangian_terms'], list) or not spec['lagrangian_terms']:
        raise ValueError('at least one Lagrangian term is required')
    for term in spec['lagrangian_terms']:
        _keys(term, ('id', 'operator', 'fields', 'couplings', 'hc', 'kind'),
              ('latex', 'normalization', 'description', 'source_span'), 'Lagrangian term')
        if not isinstance(term['id'], str) or not term['id'] or term['id'] in ids:
            raise ValueError('every Lagrangian term needs a unique id')
        ids.add(term['id'])
        if not isinstance(term['operator'], str) or not term['operator'].strip():
            raise ValueError(f'term {term["id"]}: operator text required')
        if type(term['hc']) is not bool:
            raise ValueError(f'term {term["id"]}: hc must be true or false')
        if term['kind'] not in ('interaction', 'mass', 'kinetic'):
            raise ValueError(f'term {term["id"]}: kind is interaction, mass or kinetic')
        if not isinstance(term['fields'], list) or not term['fields']:
            raise ValueError(f'term {term["id"]}: list the fields it contains')
        for entry in term['fields']:
            _keys(entry, ('field',), ('conjugate', 'charge_conjugate'), f'term {term["id"]} field')
            if entry['field'] not in names and entry['field'] not in SM_FIELDS:
                raise ValueError(f'term {term["id"]}: unknown field {entry["field"]}')
        for c in term['couplings']:
            if c not in params:
                raise ValueError(f'term {term["id"]}: coupling {c} is not a declared parameter')
    for key in ('required_couplings', 'optional_couplings'):
        for c in spec.get(key) or []:
            if c not in params:
                raise ValueError(f'{key}: {c} is not a declared parameter')
    if not spec['required_couplings']:
        raise ValueError('declare at least one required coupling')
    if set(spec['required_couplings']) & set(spec.get('optional_couplings') or []):
        raise ValueError('a coupling cannot be both required and optional')
    return spec


def _matrix_value(value, rank, symbol):
    if rank == 1:
        if not isinstance(value, list) or len(value) != 3:
            raise ValueError(f'{symbol}: a Generation-indexed value is a list of three numbers')
        for v in value:
            _finite(v, f'{symbol} entry')
    else:
        if not isinstance(value, list) or len(value) != 3 or any(not isinstance(r, list) or len(r) != 3 for r in value):
            raise ValueError(f'{symbol}: a Generation x Generation value is a 3x3 list')
        for row in value:
            for v in row:
                _finite(v, f'{symbol} entry')


def fields_by_name(spec):
    table = {}
    for f in spec['fields']:
        table[f['name']] = {'su3': f['su3'], 'Q': rational(f.get('electric_charge', f['hypercharge']), 'Q'),
                            'Y': rational(f['hypercharge'], 'Y'), 'su2': f.get('su2', 1),
                            'real': f['self_conjugate'], 'kind': f['kind'], 'new': True}
    return table


def charge_census(spec):
    """Exact charge neutrality of every declared monomial.

    A term built from unbroken-phase fields must have zero total hypercharge and
    an even number of weak doublets; a term built from physical fields must have
    zero electric charge. Colour triality must vanish in both cases. New fields
    are SU(2) singlets and carry both charges.
    """
    table = {**SM_FIELDS, **fields_by_name(spec)}
    rows = []
    for term in spec['lagrangian_terms']:
        q = y = Fraction(0)
        triality = doublets = 0
        has_q = has_y = True
        for entry in term['fields']:
            f = table[entry['field']]
            sign = -1 if bool(entry.get('conjugate')) != bool(entry.get('charge_conjugate')) else 1
            if f['real']:
                sign = 1
            if 'Q' in f:
                q += sign * f['Q']
            else:
                has_q = False
            if 'Y' in f:
                y += sign * f['Y']
                doublets += 1 if f.get('su2', 1) == 2 else 0
            else:
                has_y = False
            triality += sign * SU3[f['su3']]
        problems = []
        if triality % 3:
            problems.append('colour triality does not vanish')
        if has_y:
            if y != 0:
                problems.append(f'hypercharge sums to {y}')
            if doublets % 2:
                problems.append('odd number of weak doublets')
        elif has_q:
            if q != 0:
                problems.append(f'electric charge sums to {q}')
        else:
            problems.append('mixes physical and unbroken-phase SM fields; charge neutrality is not decidable')
        new = {f['name']: f for f in spec['fields']}
        for qn in sorted({k for f in spec['fields'] for k in (f.get('quantum_numbers') or {})}):
            total = Fraction(0)
            for entry in term['fields']:
                sign = -1 if bool(entry.get('conjugate')) != bool(entry.get('charge_conjugate')) else 1
                name = entry['field']
                value = (rational(new[name].get('quantum_numbers', {}).get(qn, 0), qn) if name in new
                         else Fraction(SM_QUANTUM_NUMBERS.get(qn, {}).get(name, 0)))
                total += sign * value
            if total != 0:
                problems.append(f'{qn} sums to {total}')
        rows.append({'term': term['id'], 'electric_charge': str(q) if has_q else None,
                     'hypercharge': str(y) if has_y else None, 'passed': not problems, 'problems': problems})
    return {'passed': all(r['passed'] for r in rows), 'terms': rows}


def hermiticity_census(spec):
    """A term without +h.c. must contain each complex field as often as its conjugate."""
    table = {**SM_FIELDS, **fields_by_name(spec)}
    rows = []
    for term in spec['lagrangian_terms']:
        if term['hc']:
            rows.append({'term': term['id'], 'passed': True, 'reason': 'adds its Hermitian conjugate'})
            continue
        balance = {}
        for entry in term['fields']:
            name = entry['field']
            if table[name]['real']:
                continue
            conj = bool(entry.get('conjugate')) != bool(entry.get('charge_conjugate'))
            balance[name] = balance.get(name, 0) + (-1 if conj else 1)
        unbalanced = sorted(k for k, v in balance.items() if v)
        rows.append({'term': term['id'], 'passed': not unbalanced,
                     'reason': ('missing h.c.: complex fields ' + ', '.join(unbalanced) + ' appear without their conjugates')
                     if unbalanced else 'self-conjugate field content'})
    return {'passed': all(r['passed'] for r in rows), 'terms': rows}


def quadratic_census(spec):
    """Mass and kinetic terms must be diagonal and canonically normalized."""
    names = {f['name'] for f in spec['fields']}
    problems = []
    declared_kinetic = {f['name'] for f in spec['fields'] if f.get('kinetic', 'canonical') == 'declared'}
    seen_kinetic = set()
    for term in spec['lagrangian_terms']:
        content = {e['field'] for e in term['fields']}
        if term['kind'] in ('mass', 'kinetic') and len(content) > 1:
            problems.append(f'term {term["id"]}: off-diagonal {term["kind"]} term between {", ".join(sorted(content))}; '
                            'diagonalize to mass eigenstates first')
        if term['kind'] == 'kinetic':
            field = next(iter(content))
            if field not in names:
                problems.append(f'term {term["id"]}: kinetic terms of SM fields come from SM.fr')
                continue
            if field not in declared_kinetic:
                problems.append(f'term {term["id"]}: {field} already has a generated canonical kinetic term; '
                                'a second one makes it non-canonical')
                continue
            expected = canonical_kinetic_coefficient(next(f for f in spec['fields'] if f['name'] == field))
            norm = term.get('normalization')
            if type(norm) not in (int, float) or not math.isclose(norm, expected, rel_tol=1e-12):
                problems.append(f'term {term["id"]}: kinetic normalization {norm} is not canonical ({expected})')
            seen_kinetic.add(field)
    for field in declared_kinetic - seen_kinetic:
        problems.append(f'{field}: kinetic term declared but not supplied')
    return {'passed': not problems, 'problems': problems}


def canonical_kinetic_coefficient(field):
    """Coefficient of the kinetic operator as written in the generated term."""
    if field['kind'] == 'scalar':
        return 0.5 if field['self_conjugate'] else 1.0
    if field['kind'] == 'vector':
        return 0.25 if field['self_conjugate'] else 0.5
    return 0.5 if field['self_conjugate'] else 1.0


# ------------------------------------------------------------- rendering

def _wl_number(value):
    value = float(value)
    if value == int(value) and abs(value) < 1e15:
        return f'{int(value)}.'
    text = repr(value)
    if 'e' in text:
        mantissa, exponent = text.split('e')
        return f'{mantissa}*^{int(exponent)}'
    return text


def _wl_string(text):
    return '"' + str(text).replace('\\', '\\\\').replace('"', '\\"') + '"'


def _fraction_wl(value):
    f = Fraction(value)
    return str(f.numerator) if f.denominator == 1 else f'{f.numerator}/{f.denominator}'


def class_indices(spec):
    counters, out = {}, {}
    for f in spec['fields']:
        letter = CLASS_LETTER[f['kind']]
        counters[letter] = counters.get(letter, FIRST_CLASS_INDEX) + 1
        out[f['name']] = (letter, counters[letter])
    return out


def _particle_class(f, letter, number):
    y = rational(f['hypercharge'], 'Y')
    indices = [] if SU3_INDEX[f['su3']] is None else [f'Index[{SU3_INDEX[f["su3"]]}]']
    qn = [f'Q -> {_fraction_wl(y)}']
    for key, value in sorted((f.get('quantum_numbers') or {}).items()):
        qn.append(f'{_identifier(key, "quantum number", min_length=2)} -> {_fraction_wl(rational(value, key))}')
    prop = {'scalar': 'ScalarDash', 'vector': 'Sine', 'fermion': 'Straight'}[f['kind']]
    pname = f.get('particle_name', f['name'].lower())
    aname = f.get('antiparticle_name', pname if f['self_conjugate'] else pname + '~')
    lines = [f'  {letter}[{number}] == {{',
             f'    ClassName        -> {f["name"]},',
             f'    SelfConjugate    -> {"True" if f["self_conjugate"] else "False"},']
    if indices:
        lines.append(f'    Indices          -> {{{", ".join(indices)}}},')
    if not f['self_conjugate']:
        lines.append(f'    QuantumNumbers   -> {{{", ".join(qn)}}},')
    lines += [f'    Mass            -> {{{f["mass"]["symbol"]}, {_wl_number(f["mass"]["value"])}}},',
              f'    Width            -> {{{f["width"]["symbol"]}, {_wl_number(f["width"]["value"])}}},',
              f'    PDG              -> {f["pdg"]},',
              f'    PropagatorLabel  -> {_wl_string(f["name"])},',
              f'    PropagatorType   -> {prop},',
              f'    PropagatorArrow  -> {"None" if f["self_conjugate"] else "Forward"},',
              f'    ParticleName     -> {_wl_string(pname)},']
    if not f['self_conjugate']:
        lines.append(f'    AntiParticleName -> {_wl_string(aname)},')
    lines.append(f'    FullName         -> {_wl_string(f.get("full_name", f["name"]))}')
    lines.append('  }')
    return '\n'.join(lines)


def _parameter(p):
    lines = [f'  {p["symbol"]} == {{']
    body = []
    if p['nature'] == 'external':
        body.append('    ParameterType    -> External')
        body.append('    ComplexParameter -> False')
        indices = p.get('indices') or []
        if indices:
            body.append('    Indices          -> {' + ', '.join(f'Index[{i}]' for i in indices) + '}')
            body.append(f'    BlockName        -> {p["block"].upper()}')
            if len(indices) == 1:
                entries = [f'{p["symbol"]}[{i + 1}] -> {_wl_number(v)}' for i, v in enumerate(p['value'])]
            else:
                entries = [f'{p["symbol"]}[{i + 1},{j + 1}] -> {_wl_number(v)}'
                           for i, row in enumerate(p['value']) for j, v in enumerate(row)]
            body.append('    Value            -> {' + ', '.join(entries) + '}')
        else:
            body.append(f'    BlockName        -> {p["block"].upper()}')
            index = p['index']
            body.append(f'    OrderBlock       -> {index[0] if len(index) == 1 else "{" + ", ".join(map(str, index)) + "}"}')
            body.append(f'    Value            -> {_wl_number(p["value"])}')
    else:
        body.append('    ParameterType    -> Internal')
        body.append('    ComplexParameter -> False')
        if p.get('indices'):
            body.append('    Indices          -> {' + ', '.join(f'Index[{i}]' for i in p['indices']) + '}')
        body.append(f'    Value            -> {p["expression"]}')
    if p.get('interaction_order'):
        body.append(f'    InteractionOrder -> {{{p["interaction_order"][0]}, {p["interaction_order"][1]}}}')
    body.append(f'    Description      -> {_wl_string(p.get("description", p["symbol"]))}')
    lines.append(',\n'.join(body))
    lines.append('  }')
    return '\n'.join(lines)


def kinetic_operator(f):
    """Canonical kinetic plus mass operator for a new field, in FeynRules syntax.

    The colour part of the covariant derivative comes from FeynRules DC; the
    hypercharge part is written explicitly as -i g1 Y B_mu, so the physical
    field carries only its electric charge as a quantum number (FeynRules
    otherwise reports hypercharge non-conservation in every vertex with SM
    mass eigenstates). For SU(2) singlets Y equals Q. Bosons carry their colour
    index explicitly; FeynRules keeps suppressed boson colour indices as
    non-commuting products.
    """
    n, m = f['name'], f['mass']['symbol']
    y = rational(f['hypercharge'], 'Y')
    g = '' if y == 0 else f'g1 ({_fraction_wl(y)})'
    colour = {'1': '', '3': 'cc1', '8': 'aa'}[f['su3']]
    if f['kind'] == 'scalar':
        x = f'{n}[{colour}]' if colour else n
        xb = f'{n}bar[{colour}]' if colour else f'{n}bar'
        if f['self_conjugate']:
            return f'1/2 DC[{x},mu] DC[{x},mu] - 1/2 {m}^2 {x} {x}'
        if g:
            return f'(DC[{xb},mu] + I {g} B[mu] {xb}) (DC[{x},mu] - I {g} B[mu] {x}) - {m}^2 {xb} {x}'
        return f'DC[{xb},mu] DC[{x},mu] - {m}^2 {xb} {x}'
    if f['kind'] == 'fermion':
        if f['self_conjugate']:
            return f'I/2 {n}bar.Ga[mu].DC[{n},mu] - {m}/2 {n}bar.{n}'
        current = f' + {g} {n}bar.Ga[mu].{n} B[mu]' if g else ''
        return f'I {n}bar.Ga[mu].DC[{n},mu]{current} - {m} {n}bar.{n}'
    c = f',{colour}' if colour else ''
    if f['self_conjugate']:
        d = 'DC' if colour else 'del'
        return (f'-1/4 ({d}[{n}[nu{c}],mu] - {d}[{n}[mu{c}],nu]) ({d}[{n}[nu{c}],mu] - {d}[{n}[mu{c}],nu])'
                f' + 1/2 {m}^2 {n}[mu{c}] {n}[mu{c}]')

    def strength(field, sign):
        if not g:
            return f'(DC[{field}[nu{c}],mu] - DC[{field}[mu{c}],nu])'
        return (f'(DC[{field}[nu{c}],mu] {sign} I {g} B[mu] {field}[nu{c}] - DC[{field}[mu{c}],nu]'
                f' {"-" if sign == "+" else "+"} I {g} B[nu] {field}[mu{c}])')
    return (f'-1/2 {strength(n + "bar", "+")} {strength(n, "-")}'
            f' + {m}^2 {n}bar[mu{c}] {n}[mu{c}]')


LAGRANGIAN_NEW = 'LNew'
LAGRANGIAN_FULL = 'LFull'
DUMMIES = ('mu', 'nu', 'rho', 'sig', 'sp1', 'sp2', 'sp3', 'ff1', 'ff2', 'cc1', 'cc2', 'aa', 'ii')


def render_fr(spec):
    """FeynRules source extending SM.fr; LNew holds the new terms, LFull = LSM + LNew."""
    validate_spec(spec)
    numbers = class_indices(spec)
    orders = [('QCD', 1), *[(o['name'], o['hierarchy']) for o in spec.get('interaction_orders') or []], ('QED', 2)]
    head = [f'(* {spec["name"]}: model file from a confirmed ModelSpec. *)',
            '(* Load together with SM.fr: LoadModel["SM.fr", "' + spec['name'] + '.fr"]. *)',
            f'(* Provenance label: {LABEL}. *)', '',
            f'M$ModelName = {_wl_string(spec["name"])};', '',
            'M$Information = {',
            '  Authors -> {"RAVEL model-authoring kit"},',
            '  Version -> "1",',
            f'  References -> {{{_wl_string((spec.get("source") or {}).get("citation", "supplied Lagrangian"))}}}',
            '};', '',
            'M$InteractionOrderHierarchy = {' + ', '.join(f'{{{n}, {h}}}' for n, h in orders) + '};', '']
    classes = ',\n\n'.join(_particle_class(f, *numbers[f['name']]) for f in spec['fields'])
    params = ',\n\n'.join(_parameter(p) for p in spec['parameters'])
    head += ['M$ClassesDescription = {', classes, '};', '']
    head += ['M$Parameters = {', params, '};', ''] if spec['parameters'] else ['M$Parameters = {};', '']
    pieces = []
    for f in spec['fields']:
        if f.get('kinetic', 'canonical') == 'canonical':
            pieces.append(f'  (* kinetic and mass terms of {f["name"]} *)\n  {kinetic_operator(f)}')
    for term in spec['lagrangian_terms']:
        op = term['operator'].strip()
        label = f'  (* term {term["id"]} *)'
        pieces.append(f'{label}\n  ' + (f'({op}) + HC[{op}]' if term['hc'] else f'({op})'))
    body = '\n  +\n'.join(pieces)
    head += [f'{LAGRANGIAN_NEW} := Block[{{{", ".join(DUMMIES)}}}, ExpandIndices[',
             body, ', FlavorExpand -> {SU2W, SU2D}]];', '',
             f'{LAGRANGIAN_FULL} := LSM + {LAGRANGIAN_NEW};', '']
    return '\n'.join(head)


def restriction_free_model_files(spec):
    return ['SM.fr', f'{spec["name"]}.fr']


# --------------------------------------------------------------- templates

def template_catalogue():
    return json.loads(package_data_path('model_templates', 'catalogue.json').read_text())


def _template_entry(template_id):
    for t in template_catalogue()['templates']:
        if t['id'] == template_id:
            return t
    raise ValueError(f'unknown template {template_id!r}; see "ravel model templates"')


def _check_inputs(entry, values):
    declared = entry['inputs']
    unknown = sorted(set(values) - set(declared))
    if unknown:
        raise ValueError(f'template {entry["id"]} does not take: {", ".join(unknown)}')
    out = {}
    for key, decl in declared.items():
        if key not in values:
            if 'default' in decl:
                out[key] = copy.deepcopy(decl['default'])
                continue
            raise ValueError(f'template {entry["id"]} needs {key}: {decl["description"]}')
        v = values[key]
        kind = decl['type']
        if kind == 'identifier':
            _identifier(v, key, min_length=2)
        elif kind == 'number':
            _finite(v, key)
        elif kind == 'positive':
            _finite(v, key, positive=True)
        elif kind == 'nonnegative':
            _finite(v, key, nonnegative=True)
        elif kind == 'pdg':
            if type(v) is not int or v <= 0:
                raise ValueError(f'{key} must be a positive PDG code')
        elif kind == 'rational':
            rational(v, key)
        elif kind == 'matrix3':
            _matrix_value(v, 2, key)
        elif kind == 'choice':
            if v not in decl['choices']:
                raise ValueError(f'{key} must be one of {", ".join(decl["choices"])}')
        elif kind == 'boolean':
            if type(v) is not bool:
                raise ValueError(f'{key} must be true or false')
        else:
            raise ValueError(f'template input type {kind} is not known')
        out[key] = v
    return out


def _field(name, kind, *, self_conjugate, su3, charge, pdg, mass, width, width_auto=True, **extra):
    return {'name': name, 'kind': kind, 'self_conjugate': self_conjugate, 'su3': su3, 'su2': 1,
            'hypercharge': str(Fraction(charge)) if not isinstance(charge, str) else charge,
            'pdg': pdg, 'mass': {'symbol': 'M' + name, 'value': mass},
            'width': {'symbol': 'W' + name, 'value': width, 'auto': width_auto}, **extra}


def _leptoquark(v, *, vector):
    n, q, lep = v['name'], v['quark'], v['lepton']
    qq, ql = SM_FIELDS[q]['Q'], SM_FIELDS[lep]['Q']
    f2 = v['fermion_number'] == 2
    charge = qq + ql if f2 else qq - ql
    stated = rational(v['charge'], 'charge')
    if stated != charge:
        raise ValueError(f'the declared charge {stated} differs from the charge {charge} fixed by the '
                         f'{q}-{lep} coupling with fermion number {v["fermion_number"]}')
    # Lepton number of the field so that every coupling conserves it (FeynRules checks it vertex by vertex).
    field = _field(n, 'vector' if vector else 'scalar', self_conjugate=False, su3='3', charge=charge,
                   pdg=v['pdg'], mass=v['mass_GeV'], width=v['width_GeV'],
                   quantum_numbers={'LeptonNumber': 1 if f2 else -1})
    params, terms, required = [], [], []
    qbar = f'CC[{q}bar]' if f2 else f'{q}bar'
    lq = f'{n}bar' if f2 else n
    lorentz = 'Ga[mu,sp1,sp2] ' if vector else ''
    s2, s3 = ('sp2', 'sp3') if vector else ('sp1', 'sp2')
    lq_index = f'{lq}[mu,cc1]' if vector else f'{lq}[cc1]'
    block = v['block']
    for k, (chir, proj) in enumerate((('L', 'ProjM'), ('R', 'ProjP')), start=1):
        key = f'coupling_{chir}'
        matrix = v[key]
        if all(x == 0 for row in matrix for x in row):
            continue
        if chir == 'R' and lep == 'vl':
            raise ValueError('the Standard Model has no right-handed neutrinos; coupling_R must vanish for vl')
        sym = ('g' if vector else 'lam') + chir + n
        params.append({'symbol': sym, 'nature': 'external', 'block': f'{block}{chir}', 'indices': ['Generation', 'Generation'],
                       'value': matrix, 'interaction_order': ['NP', 1],
                       'description': f'{n} coupling to {chir}-handed {lep} and {q} (quark generation, lepton generation)'})
        op = (f'{sym}[ff1,ff2] {qbar}[sp1,ff1,cc1] {lorentz}{proj}[{s2},{s3}] {lep}[{s3},ff2] {lq_index}'
              if vector else
              f'{sym}[ff1,ff2] {qbar}[sp1,ff1,cc1] {proj}[sp1,sp2] {lep}[sp2,ff2] {lq_index}')
        terms.append({'id': f'{n}-{chir}', 'kind': 'interaction', 'hc': True, 'operator': op, 'couplings': [sym],
                      'fields': [{'field': q, 'conjugate': True, 'charge_conjugate': f2},
                                 {'field': lep}, {'field': n, 'conjugate': f2}]})
        required.append(sym)
    if not params:
        raise ValueError('at least one of coupling_L, coupling_R must be nonzero')
    if vector and v.get('kappa') is not None:
        params.append({'symbol': 'kappa' + n, 'nature': 'external', 'block': f'{block}K', 'index': [1],
                       'value': v['kappa'], 'description': f'{n} non-minimal gluon coupling (kappa = 1: Yang-Mills)'})
        terms.append({'id': f'{n}-kappa', 'kind': 'interaction', 'hc': False, 'couplings': ['kappa' + n],
                      'operator': f'-I gs (1 - kappa{n}) {n}bar[mu,cc1] T[aa,cc1,cc2] {n}[nu,cc2] FS[G,mu,nu,aa]',
                      'fields': [{'field': n, 'conjugate': True}, {'field': n}, {'field': 'G'}]})
    return [field], params, terms, required


def _zprime(v):
    n = v['name']
    field = _field(n, 'vector', self_conjugate=True, su3='1', charge=0, pdg=v['pdg'], mass=v['mass_GeV'],
                   width=v['width_GeV'])
    params, terms, required = [], [], []
    families = (('u', 'uq'), ('d', 'dq'), ('l', 'l'))
    for i, (tag, f) in enumerate(families):
        for kind, (vv, sign_op) in (('V', ('vector', '')), ('A', ('axial', '.Ga[5]'))):
            key = f'g{kind}_{tag}'
            sym = f'g{kind}{tag}{n}'
            params.append({'symbol': sym, 'nature': 'external', 'block': v['block'], 'index': [len(params) + 1],
                           'value': v[key], 'interaction_order': ['NP', 1],
                           'description': f'{n} {vv} coupling to {f}'})
            operator = (f'{sym} {n}[mu] {f}bar.Ga[mu].{f}' if kind == 'V'
                        else f'-{sym} {n}[mu] {f}bar.Ga[mu].Ga[5].{f}')
            terms.append({'id': f'{n}-{kind}-{tag}', 'kind': 'interaction', 'hc': False, 'operator': operator,
                          'couplings': [sym], 'fields': [{'field': f, 'conjugate': True}, {'field': f}, {'field': n}]})
            (required if v[key] != 0 else []).append(sym)
    sym = f'gLv{n}'
    params.append({'symbol': sym, 'nature': 'external', 'block': v['block'], 'index': [len(params) + 1],
                   'value': v['gL_v'], 'interaction_order': ['NP', 1],
                   'description': f'{n} coupling to left-handed neutrinos'})
    terms.append({'id': f'{n}-L-v', 'kind': 'interaction', 'hc': False, 'couplings': [sym],
                  'operator': f'{sym} {n}[mu] vlbar.Ga[mu].ProjM.vl',
                  'fields': [{'field': 'vl', 'conjugate': True}, {'field': 'vl'}, {'field': n}]})
    if v['gL_v'] != 0:
        required.append(sym)
    approximations = []
    eps = v.get('kinetic_mixing')
    if eps:
        sym = f'eps{n}'
        params.append({'symbol': sym, 'nature': 'external', 'block': v['block'], 'index': [len(params) + 1],
                       'value': eps, 'interaction_order': ['NP', 1],
                       'description': f'{n} kinetic mixing with hypercharge'})
        currents = (('u', 'uq', '1/6 ProjM + 2/3 ProjP'), ('d', 'dq', '1/6 ProjM - 1/3 ProjP'),
                    ('l', 'l', '-1/2 ProjM - ProjP'), ('v', 'vl', '-1/2 ProjM'))
        for tag, f, chiral in currents:
            terms.append({'id': f'{n}-kinetic-mixing-{tag}', 'kind': 'interaction', 'hc': False, 'couplings': [sym],
                          'operator': f'-{sym} g1 {n}[mu] {f}bar.Ga[mu].({chiral}).{f}',
                          'fields': [{'field': f, 'conjugate': True}, {'field': f}, {'field': n}]})
        required.append(sym)
        approximations.append('Kinetic mixing with hypercharge is applied to first order in epsilon after the '
                              'canonical field redefinition: the new vector couples to -epsilon g1 times the SM '
                              'fermion hypercharge current. Z-Zprime mass mixing and Higgs-current terms of order '
                              'epsilon are not included.')
    if not required:
        raise ValueError('at least one coupling of the neutral vector must be nonzero')
    return [field], params, terms, required, approximations


def _alp(v):
    n = v['name']
    field = _field(n, 'scalar', self_conjugate=True, su3='1', charge=0, pdg=v['pdg'], mass=v['mass_GeV'],
                   width=v['width_GeV'])
    params, terms, required = [], [], []
    for i, (key, boson, idx, desc) in enumerate((('g_GG', 'G', 'aa', 'gluons'), ('g_WW', 'Wi', 'ii', 'SU(2) bosons'),
                                                 ('g_BB', 'B', None, 'hypercharge boson')), start=1):
        if v[key] == 0:
            continue
        sym = f'{key.replace("_", "")}{n}'
        params.append({'symbol': sym, 'nature': 'external', 'block': v['block'], 'index': [i], 'value': v[key],
                       'interaction_order': ['NP', 1], 'unit': 'GeV^-1',
                       'description': f'{n} coupling to {desc} (dimension-five, GeV^-1)'})
        fs = (lambda a, b: f'FS[{boson},{a},{b},{idx}]') if idx else (lambda a, b: f'FS[{boson},{a},{b}]')
        terms.append({'id': f'{n}-{boson}', 'kind': 'interaction', 'hc': False, 'couplings': [sym],
                      'operator': f'-{sym}/8 {n} {fs("mu", "nu")} {fs("rho", "sig")} Eps[mu,nu,rho,sig]',
                      'fields': [{'field': n}, {'field': boson}, {'field': boson}]})
        required.append(sym)
    if not required:
        raise ValueError('at least one gauge coupling of the axion-like particle must be nonzero')
    return [field], params, terms, required, []


def _generic(v, kind):
    sc = v.get('self_conjugate', False)
    extra = {}
    if kind == 'fermion':
        extra['fermion_type'] = 'majorana' if sc else 'dirac'
    field = _field(v['name'], kind, self_conjugate=sc, su3=v['colour'], charge=v['charge'], pdg=v['pdg'],
                   mass=v['mass_GeV'], width=v['width_GeV'], **extra)
    return [field]


def instantiate(template_id, values):
    """Build a ModelSpec from a catalogue template and supplied values."""
    entry = _template_entry(template_id)
    v = _check_inputs(entry, values)
    approximations = []
    if template_id in ('scalar-leptoquark', 'vector-leptoquark'):
        fields, params, terms, required = _leptoquark(v, vector=template_id == 'vector-leptoquark')
    elif template_id == 'neutral-vector':
        fields, params, terms, required, approximations = _zprime(v)
    elif template_id == 'axion-like-particle':
        fields, params, terms, required, approximations = _alp(v)
    elif template_id in ('singlet-scalar', 'singlet-vector', 'vector-like-fermion'):
        kind = {'singlet-scalar': 'scalar', 'singlet-vector': 'vector', 'vector-like-fermion': 'fermion'}[template_id]
        fields = _generic(v, kind)
        extra = values.get('interactions')
        if extra is not None:
            raise ValueError('interactions are added to the instantiated spec, not passed as a template value')
        params, terms, required = [], [], []
    else:
        raise ValueError(f'template {template_id} has no builder')
    spec = {'schema_version': SCHEMA, 'name': v['model_name'], 'description': entry['title'],
            'template': {'id': template_id, 'values': v}, 'extends': 'SM',
            'source': {'lagrangian_latex': entry['lagrangian_latex'], 'citation': 'template ' + template_id},
            'conventions': entry.get('conventions', []), 'approximations': approximations,
            'interaction_orders': [{'name': 'NP', 'hierarchy': 1}] if params else [],
            'fields': fields, 'parameters': params, 'lagrangian_terms': terms,
            'required_couplings': required, 'optional_couplings': [], 'unsupported_features': []}
    return spec


# -------------------------------------------------- FeynRules run + verdicts

GAUGE_CHECKS = ('CheckHermiticity', 'CheckDiagonalQuadraticTerms', 'CheckDiagonalMassTerms',
                'CheckKineticTermNormalisation')


def gauge_check_script(full, new):
    """Wolfram snippet defining gaugeChecks: typed verdicts in Feynman and unitary gauge.

    Expects FeynRules loaded and the model in memory. Hermiticity and kinetic
    normalization are checked on the new terms (the SM part is fixed by SM.fr,
    whose left-handed neutrinos FeynRules reports as non-canonical); diagonal
    quadratic and mass terms are checked on the full Lagrangian. Printed
    FeynRules diagnostics are captured per check; off-diagonal quadratic field
    pairs and the declared Goldstone fields are returned for adjudication.
    """
    full, new = 'Global`' + full, 'Global`' + new
    return (
        'ravelCapture[expr_] := Module[{value, ok, printed = {}},\n'
        ' ok = Block[{Print = Function[Null, AppendTo[printed, StringJoin[Map[ToString, {##}]]]]},\n'
        '  CheckAbort[Check[value = expr; True, False], False]];\n'
        ' {value, ok, StringRiffle[printed, "\\n"]}];\n'
        'SetAttributes[ravelCapture, HoldFirst];\n'
        'ravelHolds[name_, v_] := If[name === "CheckHermiticity", ListQ[v] && Length[v] === 0, TrueQ[v]];\n'
        'ravelPairs[expr_] := Module[{terms},\n'
        ' If[expr === 0, {}, terms = If[Head[expr] === Plus, List @@ expr, {expr}];\n'
        '  Map[Map[ToString[#, InputForm]&, #]&,\n'
        '   Select[DeleteDuplicates[Sort /@ (FeynRules`GetFieldContent /@ terms)],\n'
        '    Length[#] === 2 && #[[1]] =!= FeynRules`anti[#[[2]]] &]]]];\n'
        'ravelRow[name_, r_] := <|"holds" -> ravelHolds[name, r[[1]]], "message_free" -> r[[2]],\n'
        ' "returned" -> ToString[Short[r[[1]], 20], InputForm], "printed" -> r[[3]]|>;\n'
        'ravelGauge[flag_] := Module[{lagFull, lagNew, out = <||>, quad},\n'
        ' Global`FeynmanGauge = flag; lagFull = ' + full + '; lagNew = ' + new + ';\n'
        ' out["CheckHermiticity"] = ravelRow["CheckHermiticity",\n'
        '  ravelCapture[FeynRules`CheckHermiticity[lagNew, FeynRules`FlavorExpand -> True]]];\n'
        ' out["CheckDiagonalQuadraticTerms"] = ravelRow["CheckDiagonalQuadraticTerms",\n'
        '  ravelCapture[FeynRules`CheckDiagonalQuadraticTerms[lagFull]]];\n'
        ' out["CheckDiagonalMassTerms"] = ravelRow["CheckDiagonalMassTerms",\n'
        '  ravelCapture[FeynRules`CheckDiagonalMassTerms[lagFull]]];\n'
        ' out["CheckKineticTermNormalisation"] = ravelRow["CheckKineticTermNormalisation",\n'
        '  ravelCapture[FeynRules`CheckKineticTermNormalisation[lagNew, FeynRules`FlavorExpand -> True]]];\n'
        ' quad = Quiet[Check[FeynRules`GetQuadraticTerms[lagFull], 0]];\n'
        ' out["offdiagonal_quadratic_pairs"] = ravelPairs[quad];\n'
        ' out];\n'
        'gaugeChecks = <|"feynman" -> ravelGauge[True], "unitary" -> ravelGauge[False],\n'
        ' "lagrangians" -> <|"hermiticity_and_kinetic" -> ' + json.dumps(new) + ', "diagonal" -> ' + json.dumps(full) + '|>,\n'
        ' "goldstones" -> Map[ToString[#, InputForm]&, Select[FeynRules`M$ClassesDescription[[All, 2, 1, 2]],\n'
        '   TrueQ[Quiet[FeynRules`GoldstoneQ[#]]]&]]|>;\n'
        'Global`FeynmanGauge = True;\n')


def _base_name(name):
    name = str(name)
    return name[:-3] if name.endswith('bar') and len(name) > 3 else name


def adjudicate_gauge_checks(native, *, extra_goldstones=()):
    """Unitary gauge decides; Feynman-gauge Goldstone mixing is waived only when reported."""
    if not isinstance(native, dict) or not {'feynman', 'unitary'} <= set(native):
        raise ValueError('two-gauge check record with feynman and unitary entries required')
    goldstones = {_base_name(g) for g in native.get('goldstones') or []} | set(SM_GOLDSTONES) | set(extra_goldstones)
    verdicts, waived, failures = {}, [], []
    for gauge in ('unitary', 'feynman'):
        record = native[gauge]
        verdicts[gauge] = {}
        for name in GAUGE_CHECKS:
            row = record.get(name)
            if not isinstance(row, dict) or type(row.get('holds')) is not bool:
                raise ValueError(f'{gauge} gauge {name} verdict missing')
            holds = row['holds'] and row.get('message_free') is True
            verdict = 'pass' if holds else 'fail'
            if not holds and gauge == 'feynman' and name in ('CheckDiagonalQuadraticTerms', 'CheckDiagonalMassTerms'):
                pairs = [list(p) for p in sorted({tuple(sorted(_base_name(a) for a in pair))
                                                  for pair in record.get('offdiagonal_quadratic_pairs') or []})]
                reported = 'Non diagonal' in (row.get('printed') or '')
                unitary_ok = native['unitary'][name]['holds'] is True
                if (pairs and reported and unitary_ok
                        and all(any(x in goldstones for x in pair) for pair in pairs)):
                    verdict = 'waived-goldstone-mixing'
                    waived.append({'gauge': gauge, 'check': name, 'pairs': pairs})
            verdicts[gauge][name] = verdict
            if verdict == 'fail':
                failures.append(f'{gauge} gauge: {name} fails')
    return {'passed': not failures, 'verdicts': verdicts, 'waived': waived, 'failures': failures,
            'rule': 'Every check must pass in unitary gauge. In Feynman gauge, a failed diagonal quadratic or mass '
                    'check is waived only when FeynRules reported non-diagonal terms, every off-diagonal pair '
                    'involves a Goldstone boson and the same check passes in unitary gauge.'}


def run_script(spec, *, feynrules_root, model_dir, ufo_dir, receipt):
    """Fixed FeynRules run: load SM + model, two-gauge checks, WriteUFO in Feynman gauge."""
    from ravel.physics import model_provider_bridge as provider
    q = lambda value: json.dumps(str(value), ensure_ascii=False)
    files = ', '.join(q(Path(model_dir) / name) for name in restriction_free_model_files(spec))
    return (provider.namespace_load_script(Path(feynrules_root)) +
            'If[!TrueQ[loaded], Export[' + q(receipt) + ', <|"status" -> "provider_load_failed"|>, "RawJSON"]; Exit[2]];\n'
            'SetDirectory[' + q(model_dir) + '];\n'
            'modelLoad = CheckAbort[Check[FeynRules`LoadModel[' + files + ']; True, False], False];\n'
            'modelMessages = ToString[#, InputForm]& /@ $MessageList;\n'
            'If[!TrueQ[modelLoad], Export[' + q(receipt) + ', <|"status" -> "model_load_failed",\n'
            ' "messages" -> modelMessages|>, "RawJSON"]; Exit[3]];\n'
            + gauge_check_script(LAGRANGIAN_FULL, LAGRANGIAN_NEW) +
            'ravelN0 = Length[$MessageList];\n'
            'vertexRules = FeynRules`FeynmanRules[Global`' + LAGRANGIAN_NEW + ', FeynRules`FlavorExpand -> True, FeynRules`ScreenOutput -> False];\n'
            'vertexCount = If[ListQ[vertexRules], Length[vertexRules], -1];\n'
            'vertexMessages = ToString[#, InputForm]& /@ Drop[$MessageList, ravelN0]; ravelN1 = Length[$MessageList];\n'
            'FeynRules`WriteUFO[Global`' + LAGRANGIAN_FULL + ', FeynRules`Output -> ' + q(ufo_dir) +
            ', FeynRules`AddDecays -> False, FeynRules`DialogBox -> Off];\n'
            'ufoMessages = ToString[#, InputForm]& /@ Drop[$MessageList, ravelN1];\n'
            'ufoOK = FileExistsQ[FileNameJoin[{' + q(ufo_dir) + ', "particles.py"}]];\n'
            'Export[' + q(receipt) + ', <|"status" -> "completed", "kernel_version" -> $VersionNumber,\n'
            ' "provider_version" -> ToString[FeynRules`FR$VersionNumber], "process_id" -> $ProcessID,\n'
            ' "model_name" -> ToString[FeynRules`M$ModelName], "model_load_messages" -> modelMessages,\n'
            ' "new_vertex_count" -> vertexCount, "vertex_messages" -> vertexMessages, "ufo_messages" -> ufoMessages,\n'
            ' "gauge_checks" -> gaugeChecks, "ufo_written" -> TrueQ[ufoOK],\n'
            ' "ufo_dir" -> ' + q(ufo_dir) + '|>, "RawJSON"];\nExit[0];\n')


# ------------------------------------------------------------------ author

def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_new(path, text):
    path = Path(path)
    with path.open('x') as handle:
        handle.write(text)
    return {'path': str(path), 'sha256': _sha(path)}


def feynrules_root(explicit=None):
    if explicit:
        return Path(explicit)
    if os.environ.get('FEYNRULES_ROOT'):
        return Path(os.environ['FEYNRULES_ROOT'])
    build = os.environ.get('RAVEL_NATIVE_BUILD')
    if build:
        return Path(build) / 'tools/feynrules-extract/feynrules-current'
    raise ValueError('set FEYNRULES_ROOT or RAVEL_NATIVE_BUILD, or pass --feynrules')


def author(spec, out_dir, *, feynrules=None):
    """Write the model tree, lint report, run script and bridge request; no native execution."""
    from ravel.physics import fr_lint
    validate_spec(spec)
    out = Path(out_dir).absolute()
    if out.exists():
        raise ValueError(f'{out} exists; authoring writes a fresh directory')
    root = feynrules_root(feynrules)
    sm = root / 'Models/SM/SM.fr'
    if not sm.is_file():
        raise ValueError(f'SM.fr not found under {root}')
    model = out / 'model'
    model.mkdir(parents=True)
    sm_pin = _write_new(model / 'SM.fr', sm.read_text())
    if sm_pin['sha256'] != _sha(sm):
        raise ValueError('SM.fr copy differs from the installed file')
    text = render_fr(spec)
    fr_pin = _write_new(model / f'{spec["name"]}.fr', text)
    spec_pin = _write_new(out / 'model-spec.json', json.dumps(spec, indent=2) + '\n')
    lint = fr_lint.lint(text, spec=spec, sm_text=sm.read_text())
    census = {'charges': charge_census(spec), 'hermiticity': hermiticity_census(spec),
              'quadratic': quadratic_census(spec)}
    lint_pin = _write_new(out / 'lint.json', json.dumps({'lint': lint, 'census': census}, indent=2) + '\n')
    ufo = out / 'ufo'
    script = run_script(spec, feynrules_root=root, model_dir=model, ufo_dir=ufo, receipt=out / 'native-checks.json')
    script_pin = _write_new(out / 'run.wl', script)
    request = {'schema_version': 1, 'operation': 'feynrules-source-ufo', 'model_tree': str(model),
               'model_files': restriction_free_model_files(spec), 'restrictions': [],
               'lagrangian_symbol': LAGRANGIAN_FULL, 'two_gauge_checks': {'new_terms_symbol': LAGRANGIAN_NEW},
               'ufo_python_compatibility': 'feynrules-2.3.49-literal-UFOError-raise-v1',
               'source_label': LABEL,
               'note': ('Plan with "ravel model-derivation-bridge plan --model <model_tree> --model-file SM.fr '
                        f'--model-file {spec["name"]}.fr --lagrangian {LAGRANGIAN_FULL} --two-gauge-checks {LAGRANGIAN_NEW}" and a '
                        'qualified FeynRules readiness run. --trust-model-source records that a person accepted '
                        'this generated source.')}
    request_pin = _write_new(out / 'derivation-request.json', json.dumps(request, indent=2) + '\n')
    passed = lint['passed'] and all(c['passed'] for c in census.values())
    record = {'schema_version': 1, 'status': 'authored' if passed else 'lint_failed', 'label': LABEL, 'tier': TIER,
              'model_name': spec['name'], 'spec': spec_pin, 'sm_fr': sm_pin, 'model_fr': fr_pin, 'lint': lint_pin,
              'run_script': script_pin, 'derivation_request': request_pin, 'feynrules_root': str(root),
              'lint_passed': lint['passed'], 'census_passed': all(c['passed'] for c in census.values()),
              'native_run_performed': False, 'scope': SCOPE, 'limitations': LIMITATIONS}
    _write_new(out / 'authoring.json', json.dumps(record, indent=2) + '\n')
    card = model_card(spec, record)
    _write_new(out / 'model-card.json', json.dumps(card, indent=2, default=str) + '\n')
    _write_new(out / 'model-card.md', model_card_markdown(card))
    return record


def run_native(out_dir, *, wolframscript='wolframscript', max_seconds=600, max_ram_mib=8192, runner=None,
               mg5=None, process=None, mg5_runner=None):
    """Execute run.wl, adjudicate two-gauge verdicts, convert, check and admit the UFO, write the model card.

    Model admission (``model_admission.admit``) is the postcondition: the run is
    ``checked`` only when the UFO is admitted, which needs MadGraph and a process
    for the gauge, Lorentz and permutation checks. Without them the status is
    ``admission_incomplete``.
    """
    from ravel.physics import model_admission, ufo_check
    out = Path(out_dir).absolute()
    record = json.loads((out / 'authoring.json').read_text())
    if record['status'] != 'authored':
        raise ValueError('authoring did not pass lint; fix the spec before running FeynRules')
    for key in ('spec', 'sm_fr', 'model_fr', 'run_script'):
        if _sha(record[key]['path']) != record[key]['sha256']:
            raise ValueError(f'{key} changed after authoring')
    if not 1 <= max_seconds <= MAX_SECONDS:
        raise ValueError(f'max_seconds must be 1..{MAX_SECONDS}')
    spec = json.loads((out / 'model-spec.json').read_text())
    if Path(str(wolframscript)).name == 'wolframscript':
        command = [str(wolframscript), '-file', str(out / 'run.wl')]
    else:
        command = [str(wolframscript), '-noinit', '-noprompt', '-script', str(out / 'run.wl')]
    native_dir = out / 'native'
    native_dir.mkdir()
    if runner is None:
        from ravel.physics.reinterpret_db import execute_native as runner
    try:
        execution = runner(command, native_dir, {'max_seconds': max_seconds, 'max_ram_mib': max_ram_mib})
    except ValueError as exc:
        execution = {'error': str(exc), 'stdout': str(native_dir / 'native-stdout.log'),
                     'stderr': str(native_dir / 'native-stderr.log')}
    receipt_path = out / 'native-checks.json'
    native = json.loads(receipt_path.read_text()) if receipt_path.is_file() else {'status': 'no_receipt'}
    result = {'schema_version': 1, 'label': LABEL, 'model_name': spec['name'], 'execution': execution,
              'native_status': native.get('status'), 'kernel_version': native.get('kernel_version'),
              'provider_version': native.get('provider_version')}
    checks = None
    if native.get('status') == 'completed':
        checks = adjudicate_gauge_checks(native['gauge_checks'])
        messages = list(native.get('vertex_messages') or []) + list(native.get('ufo_messages') or [])
        if messages:
            checks = {**checks, 'passed': False,
                      'failures': checks['failures'] + ['FeynRules reported messages while deriving vertices or '
                                                        'writing the UFO: ' + ', '.join(sorted(set(messages)))]}
        if not isinstance(native.get('new_vertex_count'), int) or native['new_vertex_count'] < 1:
            checks = {**checks, 'passed': False,
                      'failures': checks['failures'] + ['the new terms produce no vertices']}
        result['gauge_checks'] = checks
        result['new_vertex_count'] = native.get('new_vertex_count')
    ufo_report = None
    if native.get('ufo_written') and (out / 'ufo').is_dir():
        from ravel.physics import ufo_interop
        converted = out / 'ufo-python3'
        try:
            conversion = ufo_interop.convert_tree(out / 'ufo', converted, ufo_interop.POLICY)
        except (ValueError, SyntaxError) as exc:
            conversion, converted = {'error': str(exc)}, out / 'ufo'
        result['python_compatibility'] = {'policy': ufo_interop.POLICY, 'journal': conversion}
        ufo_report = ufo_check.check(converted, spec=spec)
        if mg5 and process:
            ufo_report['madgraph'] = ufo_check.madgraph_generate(converted, process, mg5=mg5, runner=mg5_runner,
                                                                 workdir=out / 'mg5-check')
            ufo_report['passed'] = ufo_report['passed'] and ufo_report['madgraph']['passed']
        result['ufo'] = str(converted)
        result['ufo_check'] = ufo_report
        admission = model_admission.admit(converted, spec=spec, native=native, mg5=mg5 if process else None,
                                          process=process, workdir=out / 'admission-mg5', mg5_runner=mg5_runner)
        admission_pin = _write_new(out / 'admission.json', json.dumps(admission, indent=2, default=str) + '\n')
        result['admission'] = {'decision': admission['decision'], 'refusals': admission['refusals'],
                               'not_evaluated': admission['not_evaluated'], 'record': admission_pin}
    generated = bool(checks and checks['passed'] and ufo_report and ufo_report['passed'])
    decision = (result.get('admission') or {}).get('decision')
    result['passed'] = generated and decision == 'admitted'
    result['status'] = ('checked' if result['passed'] else
                        'admission_incomplete' if generated and decision == 'incomplete' else 'failed')
    _write_new(out / 'native-result.json', json.dumps(result, indent=2, default=str) + '\n')
    card = model_card(spec, record, result)
    for name in ('model-card.json', 'model-card.md'):
        (out / name).unlink(missing_ok=True)
    _write_new(out / 'model-card.json', json.dumps(card, indent=2, default=str) + '\n')
    _write_new(out / 'model-card.md', model_card_markdown(card))
    return result


def model_card(spec, record, result=None):
    lint = json.loads(Path(record['lint']['path']).read_text())
    params = [{'symbol': p['symbol'], 'block': p.get('block'), 'index': p.get('index'), 'indices': p.get('indices'),
               'value': p.get('value', p.get('expression')), 'description': p.get('description')}
              for p in spec['parameters']]
    return {'schema_version': 1, 'model_name': spec['name'], 'label': LABEL,
            'review_status': 'not reviewed by a person; promotion to trusted needs a review record',
            'tier': TIER, 'description': spec.get('description'), 'source': spec.get('source'),
            'template': spec.get('template'), 'conventions': spec.get('conventions', []),
            'approximations': spec.get('approximations', []),
            'fields': [{'name': f['name'], 'kind': f['kind'], 'pdg': f['pdg'], 'colour': f['su3'],
                        'charge': f.get('electric_charge', f['hypercharge']), 'self_conjugate': f['self_conjugate'],
                        'mass': f['mass'], 'width': f['width']} for f in spec['fields']],
            'parameters': params, 'required_couplings': spec['required_couplings'],
            'optional_couplings': spec.get('optional_couplings', []),
            'provenance': {k: record[k] for k in ('spec', 'sm_fr', 'model_fr', 'run_script')},
            'feynrules_root': record['feynrules_root'],
            'lint': {'passed': lint['lint']['passed'], 'errors': lint['lint']['errors'],
                     'warnings': lint['lint']['warnings']},
            'census': {k: v['passed'] for k, v in lint['census'].items()},
            'native': None if result is None else {
                'status': result['status'], 'kernel_version': result.get('kernel_version'),
                'provider_version': result.get('provider_version'),
                'gauge_checks': (result.get('gauge_checks') or {}).get('verdicts'),
                'waived': (result.get('gauge_checks') or {}).get('waived'),
                'ufo': result.get('ufo'), 'ufo_check_passed': (result.get('ufo_check') or {}).get('passed'),
                'ufo_problems': (result.get('ufo_check') or {}).get('errors'),
                'madgraph': {k: ((result.get('ufo_check') or {}).get('madgraph') or {}).get(k)
                             for k in ('process', 'diagrams', 'passed')},
                'admission': result.get('admission')},
            'limitations': LIMITATIONS}


def model_card_markdown(card):
    lines = [f'# Model card: {card["model_name"]}', '',
             f'Status: {card["label"]} ({card["review_status"]}).', '',
             f'Tier: {card["tier"]}.', '']
    if card.get('description'):
        lines += [card['description'], '']
    src = card.get('source') or {}
    if src.get('lagrangian_latex'):
        lines += ['Lagrangian as supplied:', '', '$$' + src['lagrangian_latex'] + '$$', '']
    lines += ['## Fields', '', '| Field | Kind | PDG | Colour | Charge | Mass symbol | Mass (GeV) | Width symbol |',
              '|---|---|---|---|---|---|---|---|']
    for f in card['fields']:
        lines.append(f'| {f["name"]} | {f["kind"]} | {f["pdg"]} | {f["colour"]} | {f["charge"]} | '
                     f'{f["mass"]["symbol"]} | {f["mass"]["value"]} | {f["width"]["symbol"]} |')
    lines += ['', '## Parameters', '', '| Symbol | Block | Index | Value | Meaning |', '|---|---|---|---|---|']
    for p in card['parameters']:
        index = p['index'] if p['index'] is not None else p['indices']
        lines.append(f'| {p["symbol"]} | {p["block"] or "internal"} | {index} | {p["value"]} | {p["description"] or ""} |')
    lines += ['', f'Required couplings: {", ".join(card["required_couplings"])}.', '']
    for title, items in (('Conventions', card['conventions']), ('Approximations', card['approximations'])):
        if items:
            lines += [f'## {title}', ''] + [f'- {x}' for x in items] + ['']
    lines += ['## Checks', '', f'- Static lint: {"passed" if card["lint"]["passed"] else "failed"}.']
    for e in card['lint']['errors']:
        lines.append(f'  - error: {e}')
    for k, v in card['census'].items():
        lines.append(f'- {k} census: {"passed" if v else "failed"}.')
    native = card.get('native')
    if native:
        lines.append(f'- FeynRules {native.get("provider_version")} on Wolfram {native.get("kernel_version")}: '
                     f'{native["status"]}.')
        for gauge, rows in (native.get('gauge_checks') or {}).items():
            lines.append(f'  - {gauge} gauge: ' + ', '.join(f'{k} {v}' for k, v in rows.items()))
        lines.append(f'- UFO static check: {"passed" if native.get("ufo_check_passed") else "failed"}.')
        for e in native.get('ufo_problems') or []:
            lines.append(f'  - {e}')
        mg = native.get('madgraph') or {}
        if mg.get('process'):
            lines.append(f'- MadGraph import and generate "{mg["process"]}": {mg["diagrams"]} diagrams '
                         f'({"passed" if mg["passed"] else "failed"}).')
        admission = native.get('admission')
        if admission:
            lines.append(f'- Model admission: {admission["decision"]}.')
            for r in admission['refusals']:
                lines.append(f'  - refused by {r}')
            for r in admission['not_evaluated']:
                lines.append(f'  - not evaluated: {r}')
    else:
        lines.append('- FeynRules has not been run for this card.')
    lines += ['', '## Provenance', '']
    for k, pin in card['provenance'].items():
        lines.append(f'- {k}: `{Path(pin["path"]).name}` sha256 {pin["sha256"]}')
    lines += ['', '## Limitations', ''] + [f'- {x}' for x in card['limitations']]
    return '\n'.join(lines) + '\n'


# --------------------------------------------------- LO interference stages

def interference_processes(*, initial='p p', final, new_order='NP', order_in_amplitude, model):
    """MadGraph process lines that separate SM, interference and pure new-physics parts at LO.

    MadGraph squared-order syntax selects the power of the new coupling in
    |M|^2: 0 is the Standard Model, order_in_amplitude is the interference term,
    2 * order_in_amplitude is the pure new-physics term. order_in_amplitude is
    the number of new-coupling vertices in the new-physics amplitude, e.g. 2 for
    an s-channel resonance produced and decaying through its new couplings. The three samples add
    up to the full process; the interference sample can have negative weights.
    """
    if not isinstance(final, str) or not final.strip():
        raise ValueError('final state required, e.g. "l+ l-"')
    _identifier(new_order, 'coupling order', min_length=2)
    if type(order_in_amplitude) is not int or order_in_amplitude < 1:
        raise ValueError('order_in_amplitude must be a positive integer')
    k = order_in_amplitude
    proc = f'{initial} > {final}'
    rows = [('sm', f'{proc} {new_order}^2==0', 'Standard Model only'),
            ('interference', f'{proc} {new_order}^2=={k}', 'interference between SM and new physics; signed weights'),
            ('pure', f'{proc} {new_order}^2=={2 * k}', 'new physics squared'),
            ('full', f'{proc} {new_order}^2<={2 * k}', 'everything; equals the sum of the three parts')]
    return {'schema_version': 1, 'model': model, 'coupling_order': new_order, 'order_in_amplitude': k,
            'stages': [{'id': i, 'mg5_process': p, 'meaning': m,
                        'negative_weights_expected': i == 'interference'} for i, p, m in rows],
            'closure': 'sigma(full) = sigma(sm) + sigma(interference) + sigma(pure) within integration errors',
            'notes': ['Generate each part at the same parameter point, PDF and scales.',
                      'Use the interference sample only with weights kept (no unweighting to positive events).',
                      'The coupling scaling of each part is fixed: interference scales as g^k, pure as g^(2k).']}


def interference_closure(parts, *, rel_tol):
    """Check sigma(full) against the sum of SM, interference and pure parts (pb, with errors)."""
    for key in ('sm', 'interference', 'pure', 'full'):
        if key not in parts:
            raise ValueError(f'{key} cross section missing')
    total = math.fsum(parts[k]['sigma_pb'] for k in ('sm', 'interference', 'pure'))
    err = math.sqrt(math.fsum(parts[k].get('error_pb', 0.0) ** 2 for k in ('sm', 'interference', 'pure', 'full')))
    diff = parts['full']['sigma_pb'] - total
    passed = abs(diff) <= max(rel_tol * abs(parts['full']['sigma_pb']), 3 * err)
    return {'passed': passed, 'sum_of_parts_pb': total, 'full_pb': parts['full']['sigma_pb'], 'difference_pb': diff,
            'combined_error_pb': err, 'rel_tol': rel_tol}


# ---------------------------------------------------- science-mode adapter

def validate(task):
    from ravel.physics import declared_study
    return declared_study.validate_task(task)


def _request(task, base):
    from ravel.physics import declared_study
    path, request = declared_study.load_request(task, base)
    _keys(request, ('schema_version',), ('spec', 'template', 'values', 'native', 'process'), 'authoring request')
    if request['schema_version'] != 1:
        raise ValueError('authoring request schema_version 1 required')
    if ('spec' in request) == ('template' in request):
        raise ValueError('give either a ModelSpec (spec) or a template with values')
    if 'spec' in request:
        spec_path = declared_study.pinned(request['spec'], path.parent)
        spec = json.loads(Path(spec_path).read_text())
        extra = [spec_path]
    else:
        spec, extra = instantiate(request['template'], request.get('values') or {}), []
    validate_spec(spec)
    return path, request, spec, extra


def inputs(task, base):
    from ravel.physics import declared_study
    path, request, spec, extra = _request(task, base)
    root = feynrules_root((request.get('native') or {}).get('feynrules'))
    here = Path(__file__).resolve().parent
    return declared_study.inputs(path, [*extra, root / 'Models/SM/SM.fr', here / 'fr_lint.py', here / 'ufo_check.py',
                                        package_data_path('model_templates', 'catalogue.json')])


def run(task, base, output):
    path, request, spec, _ = _request(task, base)
    native = request.get('native')
    out = Path(output) / 'model-authoring'
    record = author(spec, out, feynrules=(native or {}).get('feynrules'))
    if native and record['status'] == 'authored':
        _keys(native, ('wolframscript',), ('feynrules', 'max_seconds', 'mg5'), 'native settings')
        result = run_native(out, wolframscript=native['wolframscript'], max_seconds=native.get('max_seconds', 600),
                            mg5=native.get('mg5'), process=request.get('process'))
        record = {**record, 'native_status': result['status'], 'native_passed': result['passed']}
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel model', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('templates', help='list model templates and their inputs')
    ins = sub.add_parser('instantiate', help='build a ModelSpec from a template and a values JSON')
    ins.add_argument('--template', required=True)
    ins.add_argument('--values', required=True, type=Path)
    ins.add_argument('--out', type=Path)
    ren = sub.add_parser('render', help='print the FeynRules source for a ModelSpec')
    ren.add_argument('--spec', required=True, type=Path)
    li = sub.add_parser('lint', help='lint a .fr file, optionally against its ModelSpec')
    li.add_argument('--fr', required=True, type=Path)
    li.add_argument('--spec', type=Path)
    au = sub.add_parser('author', help='write model tree, lint report, FeynRules run script and bridge request')
    au.add_argument('--spec', required=True, type=Path)
    au.add_argument('--out', required=True, type=Path)
    au.add_argument('--feynrules')
    au.add_argument('--run', action='store_true', help='also run FeynRules now (one native job)')
    au.add_argument('--wolframscript', default='wolframscript')
    au.add_argument('--max-seconds', type=int, default=600)
    au.add_argument('--mg5', help='MadGraph executable for the import-and-generate check')
    au.add_argument('--process', help='hard process that must produce at least one diagram')
    uc = sub.add_parser('check-ufo', help='static UFO checks, optionally against a ModelSpec')
    uc.add_argument('--ufo', required=True, type=Path)
    uc.add_argument('--spec', type=Path)
    from ravel.physics import model_admission
    model_admission.add_arguments(sub.add_parser(
        'admit', help='admit a UFO: vertex charges, conjugate vertices, Hermiticity, MadGraph gauge/lorentz/permutation'))
    it = sub.add_parser('interference', help='MadGraph process lines for SM, interference and pure parts')
    it.add_argument('--final', required=True)
    it.add_argument('--initial', default='p p')
    it.add_argument('--order', default='NP')
    it.add_argument('--order-in-amplitude', type=int, required=True,
                    help='new-coupling vertices in the new-physics amplitude (2 for s-channel production and decay)')
    it.add_argument('--model', required=True)
    from ravel.physics import declared_study
    declared_study.plan_arguments(sub.add_parser('plan', help='prepare an approvable model-authoring study'))
    args = parser.parse_args(argv)
    if args.command == 'templates':
        for t in template_catalogue()['templates']:
            print(f'{t["id"]}: {t["title"]}')
            for k, d in t['inputs'].items():
                print(f'    {k} ({d["type"]}{", default " + json.dumps(d["default"]) if "default" in d else ""}): '
                      f'{d["description"]}')
        return 0
    if args.command == 'instantiate':
        return declared_study.emit(instantiate(args.template, json.loads(args.values.read_text())), args.out)
    if args.command == 'render':
        print(render_fr(json.loads(args.spec.read_text())), end='')
        return 0
    if args.command == 'lint':
        from ravel.physics import fr_lint
        spec = json.loads(args.spec.read_text()) if args.spec else None
        report = fr_lint.lint(args.fr.read_text(), spec=spec)
        print(json.dumps(report, indent=2))
        return 0 if report['passed'] else 1
    if args.command == 'author':
        record = author(json.loads(args.spec.read_text()), args.out, feynrules=args.feynrules)
        if args.run and record['status'] == 'authored':
            result = run_native(args.out, wolframscript=args.wolframscript, max_seconds=args.max_seconds,
                                mg5=args.mg5, process=args.process)
            print(json.dumps({'status': result['status'], 'model_card': str(Path(args.out) / 'model-card.md')}, indent=2))
            return 0 if result['passed'] else 1
        print(json.dumps({k: record[k] for k in ('status', 'lint_passed', 'census_passed', 'label')}, indent=2))
        return 0 if record['status'] == 'authored' else 1
    if args.command == 'check-ufo':
        from ravel.physics import ufo_check
        spec = json.loads(args.spec.read_text()) if args.spec else None
        report = ufo_check.check(args.ufo, spec=spec)
        print(json.dumps(report, indent=2))
        return 0 if report['passed'] else 1
    if args.command == 'admit':
        return model_admission.command(args)
    if args.command == 'interference':
        print(json.dumps(interference_processes(initial=args.initial, final=args.final, new_order=args.order,
                                                order_in_amplitude=args.order_in_amplitude, model=args.model), indent=2))
        return 0
    return declared_study.prepare(args, mode='model-authoring',
                                  assumptions=['The ModelSpec (or template values) is the confirmed reading of the '
                                               'supplied Lagrangian.',
                                               'The generated model is labelled generated_contract_checked until a '
                                               'person reviews it.'])


if __name__ == '__main__':
    raise SystemExit(main())
