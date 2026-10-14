"""Per-event observables computed from selected objects and missing momentum.

Each observable is ``{"name", "op", ...}`` with an optional ``unit``, a natural-language
``label`` and ``only_if`` (an expression over earlier observables; other events get no
value, which saves time for expensive quantities such as MT2W). An object reference is
``"name[i]"``, the i-th object (0 = highest pT) of a selected collection. A quantity that
cannot be formed in an event (too few objects, no qualifying pair, no MT2W solution) has no
value (NaN); a cut that uses it fails and a histogram counts it as undefined.

Operations:

- ``count`` (collection), ``field`` (object, field), ``met``, ``met_phi``;
- ``scalar_sum`` and ``vector_sum_pt`` (collections, max_objects, include_met), which give
  H_T, S_T, m_eff and photon sums such as S_T^gamma and H_T^gamma;
- ``mass`` (objects: references or ``{"collection", "max_objects", "min_objects"}``);
- ``mt`` (object or objects, ``massless`` default true), ``delta_phi`` (a, b; either may be
  ``"met"``), ``delta_r``, ``delta_eta``, ``min_delta_phi_met`` (collection, max_objects);
- ``ossf_pair_mass`` and ``pair_mass`` (collection, choose: closest-to-mass with
  target_mass and source, leading, highest-mass, closest-in-phi, closest-in-r);
- ``min_pair_mass`` (object, candidates, max_objects, combine min or max) for M_lb;
- ``mass_sum`` (assignments of groups, minimum over assignments) for sums such as Sigma m_lb;
- ``mt2`` (assignments of two visible groups, invisible_mass, source, extra_invisible),
  covering MT2(ll), MT2(lb,lb) and similar;
- ``mt2w`` (lepton, candidates, max_objects, w_mass, source, no_solution_value);
- ``modified_topness`` (lepton, candidates, max_objects, w_mass, top_mass, w_resolution,
  top_resolution, source, floor);
- ``neutrino_pz`` (lepton, w_mass, source), ``aplanarity`` (collections, max_objects);
- ``expr`` (an expression over earlier observables).
"""
import re
from dataclasses import dataclass

import awkward as ak
import numpy as np

from . import kinematics as kin
from . import mt2 as mt2_lib
from .expressions import compile_expression

NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,63}$')
REF = re.compile(r'^([A-Za-z_][A-Za-z0-9_]{0,63})\[(\d{1,3})\]$')
CHOICES = ('closest-to-mass', 'leading', 'highest-mass', 'closest-in-phi', 'closest-in-r')


@dataclass
class Observable:
    name: str
    op: str
    spec: dict
    unit: object
    label: object
    only_if: object
    expression: object = None


def _keys(spec, required, optional, label):
    allowed = {'name', 'op', 'unit', 'label', 'only_if', 'description'} | set(required) | set(optional)
    missing, extra = set(required) - set(spec), set(spec) - allowed
    if missing or extra:
        raise ValueError(f'{label} ({spec.get("op")}): missing {sorted(missing)} or unexpected {sorted(extra)}')


def _ref(value, fields, label):
    m = REF.match(value) if isinstance(value, str) else None
    if not m:
        raise ValueError(f'{label}: object reference {value!r} must look like name[0]')
    if m.group(1) not in fields:
        raise ValueError(f'{label}: unknown object {m.group(1)!r} in {value!r}')
    return m.group(1), int(m.group(2))


def _collection(value, fields, label):
    if value not in fields:
        raise ValueError(f'{label}: unknown object {value!r}')
    return value


def _positive_int(value, label, minimum=1):
    if type(value) is not int or not minimum <= value <= 1000:
        raise ValueError(f'{label} must be an integer from {minimum} to 1000')
    return value


def _source(spec, label):
    if not isinstance(spec.get('source'), str) or not spec['source'].strip():
        raise ValueError(f'{label}: physics constants need a source (where the value comes from)')


def _mass_param(spec, key, label):
    value = spec.get(key)
    if type(value) not in (int, float) or not np.isfinite(value) or value < 0:
        raise ValueError(f'{label}: {key} must be a non-negative number')


def compile_observable(spec, *, fields, previous, label):
    if not isinstance(spec, dict) or not isinstance(spec.get('name'), str) or not NAME.match(spec['name']):
        raise ValueError(f'{label}: name must be letters, digits and _ (it is used in expressions)')
    label = f'{label} {spec["name"]!r}'
    op = spec.get('op')
    expression = None
    if op == 'count':
        _keys(spec, ('collection',), (), label); _collection(spec['collection'], fields, label)
    elif op == 'field':
        _keys(spec, ('object', 'field'), (), label)
        name, _ = _ref(spec['object'], fields, label)
        if spec['field'] not in fields[name]:
            raise ValueError(f'{label}: object {name!r} has no field {spec["field"]!r}')
    elif op in ('met', 'met_phi'):
        _keys(spec, (), (), label)
    elif op in ('scalar_sum', 'vector_sum_pt'):
        _keys(spec, ('collections',), ('max_objects', 'include_met'), label)
        if not isinstance(spec['collections'], list) or not spec['collections']:
            raise ValueError(f'{label}: collections must be a nonempty list')
        for c in spec['collections']:
            _collection(c, fields, label)
        if 'max_objects' in spec:
            _positive_int(spec['max_objects'], f'{label} max_objects')
        if type(spec.get('include_met', False)) is not bool:
            raise ValueError(f'{label}: include_met must be true or false')
    elif op == 'mass':
        _keys(spec, ('objects',), (), label)
        if not isinstance(spec['objects'], list) or not spec['objects']:
            raise ValueError(f'{label}: objects must be a nonempty list')
        for item in spec['objects']:
            if isinstance(item, dict):
                if set(item) - {'collection', 'max_objects', 'min_objects'} or 'collection' not in item:
                    raise ValueError(f'{label}: a collection item has collection, max_objects and min_objects')
                _collection(item['collection'], fields, label)
                for k in ('max_objects', 'min_objects'):
                    if k in item:
                        _positive_int(item[k], f'{label} {k}')
            else:
                _ref(item, fields, label)
    elif op == 'mt':
        _keys(spec, (), ('object', 'objects', 'massless'), label)
        refs = [spec['object']] if 'object' in spec else spec.get('objects')
        if not isinstance(refs, list) or not refs or ('object' in spec and 'objects' in spec):
            raise ValueError(f'{label}: give object or objects')
        for r in refs:
            _ref(r, fields, label)
        if type(spec.get('massless', True)) is not bool:
            raise ValueError(f'{label}: massless must be true or false')
    elif op in ('delta_phi', 'delta_r', 'delta_eta'):
        _keys(spec, ('a', 'b'), (), label)
        for k in ('a', 'b'):
            if spec[k] == 'met' and op == 'delta_phi':
                continue
            _ref(spec[k], fields, label)
    elif op == 'min_delta_phi_met':
        _keys(spec, ('collection',), ('max_objects',), label); _collection(spec['collection'], fields, label)
        if 'max_objects' in spec:
            _positive_int(spec['max_objects'], f'{label} max_objects')
    elif op in ('ossf_pair_mass', 'pair_mass'):
        _keys(spec, ('collection', 'choose'), ('target_mass', 'source', 'max_objects'), label)
        name = _collection(spec['collection'], fields, label)
        allowed = CHOICES[:3] if op == 'ossf_pair_mass' else CHOICES
        if spec['choose'] not in allowed:
            raise ValueError(f'{label}: choose must be one of {allowed}')
        if spec['choose'] == 'closest-to-mass':
            _mass_param(spec, 'target_mass', label); _source(spec, label)
        if op == 'ossf_pair_mass' and {'charge', 'flavour'} - fields[name]:
            raise ValueError(f'{label}: {name!r} needs charge and flavour fields for same-flavour opposite-charge pairs')
        if 'max_objects' in spec:
            _positive_int(spec['max_objects'], f'{label} max_objects', 2)
    elif op == 'min_pair_mass':
        _keys(spec, ('object', 'candidates'), ('max_objects', 'combine'), label)
        _ref(spec['object'], fields, label); _collection(spec['candidates'], fields, label)
        if spec.get('combine', 'min') not in ('min', 'max'):
            raise ValueError(f'{label}: combine is min or max')
        if 'max_objects' in spec:
            _positive_int(spec['max_objects'], f'{label} max_objects')
    elif op in ('mass_sum', 'mt2'):
        required = ('assignments',) + (('invisible_mass', 'source') if op == 'mt2' else ())
        _keys(spec, required, ('extra_invisible',) if op == 'mt2' else (), label)
        if op == 'mt2':
            _mass_param(spec, 'invisible_mass', label); _source(spec, label)
            for r in spec.get('extra_invisible', []):
                _ref(r, fields, label)
        assignments = spec['assignments']
        if not isinstance(assignments, list) or not assignments:
            raise ValueError(f'{label}: assignments must be a nonempty list')
        for a in assignments:
            if not isinstance(a, list) or (op == 'mt2' and len(a) != 2) or not a:
                raise ValueError(f'{label}: each assignment is a list of {"two " if op == "mt2" else ""}groups of object references')
            for group in a:
                if not isinstance(group, list) or not group:
                    raise ValueError(f'{label}: each group is a nonempty list of object references')
                for r in group:
                    _ref(r, fields, label)
    elif op == 'mt2w':
        _keys(spec, ('lepton', 'candidates', 'max_objects', 'w_mass', 'source'), ('no_solution_value',), label)
        _ref(spec['lepton'], fields, label); _collection(spec['candidates'], fields, label)
        _positive_int(spec['max_objects'], f'{label} max_objects', 2)
        _mass_param(spec, 'w_mass', label); _source(spec, label)
        if 'no_solution_value' in spec:
            _mass_param(spec, 'no_solution_value', label)
    elif op == 'modified_topness':
        _keys(spec, ('lepton', 'candidates', 'max_objects', 'w_mass', 'top_mass', 'w_resolution', 'top_resolution', 'source'),
              ('floor',), label)
        _ref(spec['lepton'], fields, label); _collection(spec['candidates'], fields, label)
        _positive_int(spec['max_objects'], f'{label} max_objects')
        for k in ('w_mass', 'top_mass', 'w_resolution', 'top_resolution'):
            _mass_param(spec, k, label)
        if spec['w_resolution'] <= 0 or spec['top_resolution'] <= 0:
            raise ValueError(f'{label}: resolutions must be positive')
        _source(spec, label)
        if 'floor' in spec and (type(spec['floor']) not in (int, float) or spec['floor'] <= 0):
            raise ValueError(f'{label}: floor must be positive')
    elif op == 'neutrino_pz':
        _keys(spec, ('lepton', 'w_mass', 'source'), (), label)
        _ref(spec['lepton'], fields, label); _mass_param(spec, 'w_mass', label); _source(spec, label)
    elif op == 'aplanarity':
        _keys(spec, ('collections',), ('max_objects',), label)
        for c in spec['collections']:
            _collection(c, fields, label)
        if 'max_objects' in spec:
            _positive_int(spec['max_objects'], f'{label} max_objects')
    elif op == 'expr':
        _keys(spec, ('expr',), (), label)
        expression = compile_expression(spec['expr'], allowed=previous)
    else:
        raise ValueError(f'{label}: unknown op {op!r}')
    only_if = None
    if 'only_if' in spec:
        only_if = compile_expression(spec['only_if'], allowed=previous)
    unit = spec.get('unit')
    if unit is not None and (not isinstance(unit, str) or not unit.strip()):
        raise ValueError(f'{label}: unit must be nonempty text')
    lab = spec.get('label')
    if lab is not None:
        from .recipe import natural_label
        natural_label(lab, f'{label} label')
    return Observable(spec['name'], op, dict(spec), unit, lab, only_if, expression)


# ---------------------------------------------------------------- evaluation
class Context:
    """Objects, missing momentum and the observables computed so far for one chunk."""

    def __init__(self, objects, met, met_phi):
        self.objects, self.met, self.met_phi = objects, np.asarray(met, float), np.asarray(met_phi, float)
        self.n = len(self.met)
        self.values = {}

    def padded(self, name, count, attribute):
        array = self.objects[name][attribute]
        return ak.to_numpy(ak.fill_none(ak.pad_none(array, count, axis=1, clip=True), np.nan)).astype(float)

    def vector(self, ref):
        """(n, 4) four-vectors of a referenced object; NaN rows where it is missing."""
        name, index = ref
        cols = [self.padded(name, index + 1, f)[:, index] for f in ('pt', 'eta', 'phi', 'mass')]
        return np.stack(kin.p4(*cols), axis=1)

    def vectors(self, name, count):
        """(n, count, 4) four-vectors of the first `count` objects (NaN padding)."""
        cols = [self.padded(name, count, f) for f in ('pt', 'eta', 'phi', 'mass')]
        return np.stack(kin.p4(*cols), axis=2)

    def met_vector(self):
        return np.stack([self.met * np.cos(self.met_phi), self.met * np.sin(self.met_phi)], axis=1)


def _parse(ref):
    m = REF.match(ref)
    return m.group(1), int(m.group(2))


def _group(ctx, refs):
    total = None
    for r in refs:
        v = ctx.vector(_parse(r))
        total = v if total is None else total + v
    return total


def _mass4(v):
    return kin.mass(v[..., 0], v[..., 1], v[..., 2], v[..., 3])


def _pairs(ctx, name, max_objects):
    """Index pairs (i < j) among the first max_objects and per-pair quantities."""
    count = max_objects or int(ak.max(ak.num(ctx.objects[name]), initial=0))
    count = max(count, 2)
    vec = ctx.vectors(name, count)
    ii, jj = np.triu_indices(count, 1)
    return ii, jj, vec


def _choose(values, valid, rule, target=None):
    """Pick one pair per event by rule; returns the chosen column (or -1)."""
    if rule == 'leading':
        score = np.where(valid, np.arange(values['mass'].shape[1])[None, :], np.inf)
    elif rule == 'highest-mass':
        score = np.where(valid, -values['mass'], np.inf)
    elif rule == 'closest-to-mass':
        score = np.where(valid, np.abs(values['mass'] - target), np.inf)
    elif rule == 'closest-in-phi':
        score = np.where(valid, values['dphi'], np.inf)
    else:
        score = np.where(valid, values['dr'], np.inf)
    best = np.argmin(score, axis=1) if score.shape[1] else np.zeros(len(score), int)
    found = np.isfinite(score[np.arange(len(score)), best]) if score.shape[1] else np.zeros(len(score), bool)
    return np.where(found, best, -1)


def pair_selection(ctx, name, *, rule, target=None, ossf=False, max_objects=None):
    """Chosen pair indices (i, j) per event (-1 where none) and their masses."""
    ii, jj, vec = _pairs(ctx, name, max_objects)
    count = vec.shape[1]
    exists = np.isfinite(vec[..., 3])
    valid = exists[:, ii] & exists[:, jj]
    if ossf:
        charge = ctx.padded(name, count, 'charge'); flavour = ctx.padded(name, count, 'flavour')
        valid &= (charge[:, ii] * charge[:, jj] < 0) & (flavour[:, ii] == flavour[:, jj])
    pair_sum = vec[:, ii, :] + vec[:, jj, :]
    values = {'mass': _mass4(pair_sum)}
    if rule in ('closest-in-phi', 'closest-in-r'):
        phi = ctx.padded(name, count, 'phi'); eta = ctx.padded(name, count, 'eta')
        values['dphi'] = kin.delta_phi(phi[:, ii], phi[:, jj])
        values['dr'] = kin.delta_r(eta[:, ii], phi[:, ii], eta[:, jj], phi[:, jj])
    column = _choose(values, valid, rule, target)
    rows = np.arange(ctx.n)
    safe = np.where(column >= 0, column, 0)
    mass = np.where(column >= 0, values['mass'][rows, safe] if len(ii) else np.nan, np.nan)
    first = np.where(column >= 0, ii[safe] if len(ii) else -1, -1)
    second = np.where(column >= 0, jj[safe] if len(jj) else -1, -1)
    return first, second, mass


def compute(obs, ctx):
    s = obs.spec
    op = obs.op
    if op == 'count':
        return ak.to_numpy(ak.num(ctx.objects[s['collection']], axis=1)).astype(float)
    if op == 'field':
        name, index = _parse(s['object'])
        return ctx.padded(name, index + 1, s['field'])[:, index]
    if op == 'met':
        return ctx.met.copy()
    if op == 'met_phi':
        return ctx.met_phi.copy()
    if op in ('scalar_sum', 'vector_sum_pt'):
        k = s.get('max_objects')
        sx = np.zeros(ctx.n); sy = np.zeros(ctx.n); st = np.zeros(ctx.n)
        for c in s['collections']:
            obj = ctx.objects[c] if k is None else ctx.objects[c][:, :k]
            st += ak.to_numpy(ak.sum(obj.pt, axis=1))
            sx += ak.to_numpy(ak.sum(obj.pt * np.cos(obj.phi), axis=1))
            sy += ak.to_numpy(ak.sum(obj.pt * np.sin(obj.phi), axis=1))
        if s.get('include_met'):
            st += ctx.met; sx += ctx.met * np.cos(ctx.met_phi); sy += ctx.met * np.sin(ctx.met_phi)
        return st if op == 'scalar_sum' else np.hypot(sx, sy)
    if op == 'mass':
        total = np.zeros((ctx.n, 4))
        for item in s['objects']:
            if isinstance(item, dict):
                obj = ctx.objects[item['collection']]
                if 'max_objects' in item:
                    obj = obj[:, :item['max_objects']]
                px, py, pz, e = kin.p4(obj.pt, obj.eta, obj.phi, obj.mass)
                part = np.stack([ak.to_numpy(ak.sum(x, axis=1)) for x in (px, py, pz, e)], axis=1)
                enough = ak.to_numpy(ak.num(obj, axis=1)) >= item.get('min_objects', 1)
                part[~enough] = np.nan
                total = total + part
            else:
                total = total + ctx.vector(_parse(item))
        return _mass4(total)
    if op == 'mt':
        refs = [s['object']] if 'object' in s else s['objects']
        v = _group(ctx, refs)
        pt, _, phi, mass = kin.from_cartesian(*v.T)
        return kin.mt(pt, phi, mass, ctx.met, ctx.met_phi, massless=s.get('massless', True))
    if op in ('delta_phi', 'delta_r', 'delta_eta'):
        def angles(ref):
            if ref == 'met':
                return np.full(ctx.n, np.nan), ctx.met_phi
            name, index = _parse(ref)
            return ctx.padded(name, index + 1, 'eta')[:, index], ctx.padded(name, index + 1, 'phi')[:, index]
        ea, pa = angles(s['a']); eb, pb = angles(s['b'])
        if op == 'delta_phi':
            return kin.delta_phi(pa, pb)
        if op == 'delta_eta':
            return np.abs(ea - eb)
        return kin.delta_r(ea, pa, eb, pb)
    if op == 'min_delta_phi_met':
        obj = ctx.objects[s['collection']]
        if 'max_objects' in s:
            obj = obj[:, :s['max_objects']]
        d = kin.delta_phi(obj.phi, ctx.met_phi)
        return ak.to_numpy(ak.fill_none(ak.min(d, axis=1), np.nan)).astype(float)
    if op in ('ossf_pair_mass', 'pair_mass'):
        _, _, mass = pair_selection(ctx, s['collection'], rule=s['choose'], target=s.get('target_mass'),
                                    ossf=op == 'ossf_pair_mass', max_objects=s.get('max_objects'))
        return mass
    if op == 'min_pair_mass':
        name, index = _parse(s['object'])
        k = s.get('max_objects') or max(int(ak.max(ak.num(ctx.objects[s['candidates']]), initial=0)), 1)
        a = ctx.vector((name, index))
        cands = ctx.vectors(s['candidates'], k)
        masses = _mass4(cands + a[:, None, :])
        same = _same_object(ctx, (name, index), s['candidates'], k)
        masses = np.where(same, np.nan, masses)
        with np.errstate(all='ignore'):
            reduce = np.fmin.reduce if s.get('combine', 'min') == 'min' else np.fmax.reduce
            return reduce(masses, axis=1) if masses.shape[1] else np.full(ctx.n, np.nan)
    if op == 'mass_sum':
        best = np.full(ctx.n, np.nan)
        for assignment in s['assignments']:
            total = sum(_mass4(_group(ctx, g)) for g in assignment)
            best = np.fmin(best, total)
        return best
    if op == 'mt2':
        miss = ctx.met_vector()
        for r in s.get('extra_invisible', []):
            miss = miss + ctx.vector(_parse(r))[:, :2]
        best = np.full(ctx.n, np.nan)
        chi = float(s['invisible_mass'])
        for a_refs, b_refs in s['assignments']:
            va, vb = _group(ctx, a_refs), _group(ctx, b_refs)
            ok = np.isfinite(va).all(1) & np.isfinite(vb).all(1) & np.isfinite(miss).all(1)
            value = np.full(ctx.n, np.nan)
            if ok.any():
                value[ok] = mt2_lib.mt2(_mass4(va[ok]), va[ok, 0], va[ok, 1], _mass4(vb[ok]), vb[ok, 0], vb[ok, 1],
                                        miss[ok, 0], miss[ok, 1], chi, chi)
            best = np.fmin(best, value)
        return best
    if op == 'mt2w':
        k = s['max_objects']
        lep = ctx.vector(_parse(s['lepton']))
        cands = ctx.vectors(s['candidates'], k)
        met = ctx.met_vector()
        best = np.full(ctx.n, np.nan)
        available = np.zeros(ctx.n, bool)
        for i in range(k):
            for j in range(k):
                if i == j:
                    continue
                ok = np.isfinite(lep).all(1) & np.isfinite(cands[:, i]).all(1) & np.isfinite(cands[:, j]).all(1) & np.isfinite(met).all(1)
                available |= ok
                if ok.any():
                    value = np.full(ctx.n, np.nan)
                    value[ok] = mt2_lib.mt2w(lep[ok], cands[ok, i], cands[ok, j], met[ok], w_mass=float(s['w_mass']))
                    best = np.fmin(best, value)
        if 'no_solution_value' in s:
            best = np.where(available & np.isnan(best), float(s['no_solution_value']), best)
        return best
    if op == 'modified_topness':
        k = s['max_objects']
        lep = ctx.vector(_parse(s['lepton']))
        cands = ctx.vectors(s['candidates'], k)
        met = ctx.met_vector()
        best = np.full(ctx.n, np.nan)
        for i in range(k):
            ok = np.isfinite(lep).all(1) & np.isfinite(cands[:, i]).all(1) & np.isfinite(met).all(1)
            if ok.any():
                value = np.full(ctx.n, np.nan)
                value[ok] = mt2_lib.topness_minimum(lep[ok], cands[ok, i], met[ok], m_w=s['w_mass'], m_top=s['top_mass'],
                                                    sigma_w=s['w_resolution'], sigma_top=s['top_resolution'])
                best = np.fmin(best, value)
        if 'floor' in s:
            best = np.where(np.isfinite(best), np.maximum(best, float(s['floor'])), best)
        with np.errstate(divide='ignore'):
            return np.log(best)
    if op == 'neutrino_pz':
        lep = ctx.vector(_parse(s['lepton']))
        ok = np.isfinite(lep).all(1)
        out = np.full(ctx.n, np.nan)
        if ok.any():
            out[ok] = kin.neutrino_pz(lep[ok], ctx.met_vector()[ok], w_mass=float(s['w_mass']))[0]
        return out
    if op == 'aplanarity':
        parts = []
        for c in s['collections']:
            k = s.get('max_objects') or max(int(ak.max(ak.num(ctx.objects[c]), initial=0)), 1)
            parts.append(np.nan_to_num(ctx.vectors(c, k), nan=0.0))
        v = np.concatenate(parts, axis=1)
        return kin.aplanarity(v[..., 0], v[..., 1], v[..., 2])
    if op == 'expr':
        return np.asarray(obs.expression.evaluate(ctx.values), float) * np.ones(ctx.n)
    raise ValueError(f'unknown op {op}')


def _same_object(ctx, ref, collection, count):
    name, index = ref
    src = ctx.padded(name, index + 1, '_src')[:, index]; idx = ctx.padded(name, index + 1, '_idx')[:, index]
    csrc = ctx.padded(collection, count, '_src'); cidx = ctx.padded(collection, count, '_idx')
    return (csrc == src[:, None]) & (cidx == idx[:, None])


def evaluate(obs, ctx):
    """Compute one observable, honouring only_if; stores and returns the values."""
    if obs.only_if is not None:
        keep = obs.only_if.evaluate_cut(ctx.values)
        keep = np.broadcast_to(np.asarray(keep, bool), (ctx.n,))
        values = np.full(ctx.n, np.nan)
        if keep.any():
            sub = Context({k: v[keep] for k, v in ctx.objects.items()}, ctx.met[keep], ctx.met_phi[keep])
            sub.values = {k: v[keep] for k, v in ctx.values.items()}
            values[keep] = compute(obs, sub)
    else:
        values = np.asarray(compute(obs, ctx), float)
    ctx.values[obs.name] = values
    return values
