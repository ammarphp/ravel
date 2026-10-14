"""Tree-level two-body widths and branching ratios of a resonance into fermion pairs.

A spin-0 or spin-1 resonance couples to each declared fermion channel through
chiral couplings, L = X f-bar (gL P_L + gR P_R) f (spin 0) or
L = X_mu f-bar gamma^mu (gL P_L + gR P_R) f (spin 1). Couplings are declared
directly, as vector/axial pairs, or from the sequential Standard-Model pattern
with declared electroweak inputs. Branching ratios are over the declared
channel set; the total width is the sum of the declared channels.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

from ravel.physics.ufo_decay import tree_reference

SCOPE = 'declared_channel_tree_level_width'
# Fermion quantum numbers (third weak-isospin component, electric charge, colour).
FERMIONS = {'e': (-.5, -1, 1), 'mu': (-.5, -1, 1), 'tau': (-.5, -1, 1),
            've': (.5, 0, 1), 'vm': (.5, 0, 1), 'vt': (.5, 0, 1),
            'u': (.5, 2 / 3, 3), 'c': (.5, 2 / 3, 3), 't': (.5, 2 / 3, 3),
            'd': (-.5, -1 / 3, 3), 's': (-.5, -1 / 3, 3), 'b': (-.5, -1 / 3, 3)}
FORMULA = {
    1: ('Gamma = N_c p / (8 pi M^2) * (1/3) * [(|gL|^2+|gR|^2)(2M^2 - m1^2 - m2^2 - (m1^2-m2^2)^2/M^2) '
        '+ 12 Re(gL gR*) m1 m2]; massless limit Gamma = N_c M (|gL|^2+|gR|^2) / (24 pi)'),
    0: ('Gamma = N_c p / (8 pi M^2) * [(|gL|^2+|gR|^2)(M^2 - m1^2 - m2^2) - 4 Re(gL gR*) m1 m2]; '
        'massless limit Gamma = N_c M (|gL|^2+|gR|^2) / (16 pi)')}


def _keys(value, required, optional=(), label='object'):
    if type(value) is not dict or set(required) - set(value) or set(value) - set(required) - set(optional):
        raise ValueError(label + ' requires ' + ', '.join(sorted(required))
                         + (' and optional ' + ', '.join(sorted(optional)) if optional else ''))


def _num(value, label, positive=False, nonnegative=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('finite ' + label + ' required')
    if positive and value <= 0 or nonnegative and value < 0:
        raise ValueError(('positive ' if positive else 'nonnegative ') + label + ' required')
    return float(value)


def _coupling(value, label):
    if type(value) is dict:
        _keys(value, (), ('Re', 'Im'), label)
        return complex(_num(value.get('Re', 0.), label), _num(value.get('Im', 0.), label))
    return complex(_num(value, label), 0.)


def _pair(z):
    return {'Re': z.real, 'Im': z.imag}


def couplings(document):
    """Chiral couplings per channel from the declared scheme."""
    scheme = document['couplings']
    _keys(scheme, ('scheme',), ('sin2_theta_w', 'alpha_em', 'scale_factor'), 'couplings')
    answer = {}
    if scheme['scheme'] == 'declared':
        if set(scheme) != {'scheme'}:
            raise ValueError('declared couplings are given per channel')
        for row in document['channels']:
            if {'gL', 'gR'} <= set(row):
                gl, gr = _coupling(row['gL'], 'gL'), _coupling(row['gR'], 'gR')
            elif {'gV', 'gA'} <= set(row):
                gv, ga = _coupling(row['gV'], 'gV'), _coupling(row['gA'], 'gA')
                gl, gr = gv + ga, gv - ga
            else:
                raise ValueError('declared channel ' + row['id'] + ' needs gL/gR or gV/gA')
            answer[row['id']] = (gl, gr)
        return answer, {'scheme': 'declared', 'convention_vector_axial': 'gL = gV + gA, gR = gV - gA'}
    if scheme['scheme'] != 'sequential_sm':
        raise ValueError('coupling scheme must be declared or sequential_sm')
    if document['resonance']['spin'] != 1:
        raise ValueError('the sequential Standard-Model pattern is defined for a spin-1 resonance')
    _keys(scheme, ('scheme', 'sin2_theta_w', 'alpha_em'), ('scale_factor',), 'sequential_sm couplings')
    s2 = _num(scheme['sin2_theta_w'], 'sin2_theta_w', positive=True)
    alpha = _num(scheme['alpha_em'], 'alpha_em', positive=True)
    k = _num(scheme.get('scale_factor', 1.), 'scale_factor')
    if s2 >= 1:
        raise ValueError('sin2_theta_w must be below 1')
    g_z = math.sqrt(4 * math.pi * alpha) / math.sqrt(s2 * (1 - s2))
    for row in document['channels']:
        if row['fermion'] not in FERMIONS:
            raise ValueError('sequential couplings need a Standard-Model fermion: ' + ', '.join(sorted(FERMIONS)))
        if {'gL', 'gR', 'gV', 'gA'} & set(row):
            raise ValueError('sequential couplings are derived; do not also declare them per channel')
        t3, q, _ = FERMIONS[row['fermion']]
        answer[row['id']] = (complex(k * g_z * (t3 - q * s2)), complex(-k * g_z * q * s2))
    return answer, {'scheme': 'sequential_sm', 'g_over_cos_theta_w': g_z, 'sin2_theta_w': s2, 'alpha_em': alpha,
                    'scale_factor': k, 'pattern': 'gL = k (g/cos theta_W)(T3 - Q sin2_theta_W), gR = -k (g/cos theta_W) Q sin2_theta_W'}


def validate_document(d):
    _keys(d, ('schema_version', 'source', 'resonance', 'couplings', 'channels'), ('groups',), 'resonance-width input')
    if d['schema_version'] != 1 or type(d['source']) is not str or not d['source'].strip():
        raise ValueError('schema 1 and a source description required')
    r = d['resonance']
    _keys(r, ('name', 'spin', 'mass_gev'), (), 'resonance')
    if r['spin'] not in (0, 1) or type(r['spin']) is not int:
        raise ValueError('resonance spin must be 0 or 1')
    _num(r['mass_gev'], 'resonance mass', positive=True)
    rows = d['channels']
    if type(rows) is not list or not 1 <= len(rows) <= 64:
        raise ValueError('one to 64 channels required')
    ids = []
    for row in rows:
        _keys(row, ('id', 'fermion', 'mass_gev'), ('color', 'gL', 'gR', 'gV', 'gA'), 'channel')
        if type(row['id']) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_+\-]{0,31}', row['id']):
            raise ValueError('channel id must be a short identifier')
        ids.append(row['id'])
        _num(row['mass_gev'], 'fermion mass', nonnegative=True)
        color = row.get('color', FERMIONS.get(row['fermion'], (0, 0, None))[2])
        if color not in (1, 3):
            raise ValueError('channel color must be 1 or 3 (declare it for a non-Standard-Model fermion)')
    if len(set(ids)) != len(ids):
        raise ValueError('channel ids must be unique')
    groups = d.get('groups', {})
    if type(groups) is not dict or any(type(v) is not list or not v or set(v) - set(ids) for v in groups.values()):
        raise ValueError('groups map names to nonempty lists of declared channel ids')
    couplings(d)
    return deepcopy(d)


def calculate(d):
    d = validate_document(d)
    m = d['resonance']['mass_gev']
    family = 'VFF' if d['resonance']['spin'] == 1 else 'SFF'
    values, convention = couplings(d)
    channels = []
    for row in d['channels']:
        color = row.get('color', FERMIONS.get(row['fermion'], (0, 0, None))[2])
        gl, gr = values[row['id']]
        mf = row['mass_gev']
        if m <= 2 * mf:
            width, reference = 0., {'closed': True}
        else:
            reference = tree_reference(family, [m, mf, mf], {'gL': gl, 'gR': gr}, color)
            width = reference['partial_width_GeV']
        channels.append({'id': row['id'], 'fermion': row['fermion'], 'fermion_mass_gev': mf, 'color': color,
                         'gL': _pair(gl), 'gR': _pair(gr), 'partial_width_gev': width,
                         'open': m > 2 * mf})
    total = sum(c['partial_width_gev'] for c in channels)
    if total <= 0:
        raise ValueError('no open declared channel has a nonzero coupling')
    for c in channels:
        c['branching_ratio'] = c['partial_width_gev'] / total
    groups = {name: {'channels': members, 'partial_width_gev': sum(c['partial_width_gev'] for c in channels if c['id'] in members),
                     'branching_ratio': sum(c['branching_ratio'] for c in channels if c['id'] in members)}
              for name, members in d.get('groups', {}).items()}
    return {'resonance': d['resonance'], 'family': family, 'formula': FORMULA[d['resonance']['spin']],
            'coupling_convention': convention, 'channels': channels, 'groups': groups,
            'total_width_gev': total, 'width_over_mass': total / m,
            'branching_ratio_basis': 'sum of the declared channels',
            'order': 'tree level, on-shell two-body; no QCD/electroweak corrections or interference'}


def validate(task):
    _keys(task, ('input',), (), 'resonance-width task')
    if type(task['input']) is not str or not task['input']:
        raise ValueError('input path required')
    return deepcopy(task)


def _path(task, base):
    p = Path(validate(task)['input'])
    p = p if p.is_absolute() else Path(base) / p
    if p.is_symlink() or not p.is_file():
        raise ValueError('resonance-width input must be a regular file')
    return p.resolve()


def _load(path):
    from ravel.workflow.state_io import _unique

    def nonfinite(value):
        raise ValueError('nonfinite JSON constant')
    raw = path.read_bytes()
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=nonfinite), hashlib.sha256(raw).hexdigest()


def inputs(task, base):
    path = _path(task, base)
    validate_document(_load(path)[0])
    return [path]


def execution_seconds(task, base):
    return 30


def run(task, base, output):
    path = _path(task, base)
    document, digest = _load(path)
    value = calculate(document)
    result = {'schema_version': 1, 'kind': 'resonance-width', 'status': 'passed', 'status_scope': SCOPE,
              'input': {'path': str(path), 'sha256': digest}, 'source': document['source'], **value,
              'physics_validated': False,
              'limitations': ['Widths are tree-level and on shell for the declared channels and couplings.',
                              'Branching ratios are normalized to the declared channel set; undeclared channels '
                              '(for example bosonic or new-physics decays) change them.']}
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'resonance-width.json').open('x') as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n')
    return result
