"""Binned efficiency maps applied to reconstructed objects.

A map is read from a ROOT TH1/TH2/TH3 (numeric bin edges, or edges written as axis
labels such as ``(0,0.8)`` or ``20-35``), from a JSON grid, from a HEPData table whose
rows form a complete rectangular grid, or from a YODA Scatter2D/Scatter3D object. Bins are half-open, [low, high). Every lookup
outside an axis range follows the policy declared for that axis:

- ``refuse``: the analysis stops and names the axis and the number of objects;
- ``clamp``: the nearest edge bin is used;
- ``zero``: the efficiency is zero.

Every clamped or zeroed object is counted. Values must lie in [0, 1] unless the map
is a declared scale factor; a map in percent is refused.

Every map declares its ``semantics``:

- ``absolute``: the probability that the object is reconstructed and identified;
- ``conditional_on_reco``: the probability given that the detector simulation already
  reconstructed the object (it stacks on the card's reconstruction efficiency);
- ``scale_factor``: a data/simulation ratio that multiplies an efficiency already applied.

``card_modules`` names the detector-card efficiency modules the map corresponds to.
``check_card`` compares the semantics with those modules in the supplied card, so an
absolute map is refused when the card already applies a nontrivial efficiency to the
same objects, and a conditional map is refused when the card lacks the module it is
conditional on.

The recipe applies a map to an object collection before any selection uses it, in one
of three ways (see ``engine``): ``select`` keeps each object with probability equal to
its efficiency, using counter-based random numbers keyed by the seed, the input file,
the entry and the object, so the result does not depend on how the events are split;
``enumerate`` replaces each event by every keep/drop subset of the collection, weighted
by its probability, which gives the exact expectation of every later selection
(vetoes, multiplicities, leading-object choices); ``all-required-weight`` multiplies the
event weight by the product of the efficiencies, which is exact only when the selection
requires every object of the collection.
"""
import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np

POLICIES = ('refuse', 'clamp', 'zero')
SEMANTICS = ('absolute', 'conditional_on_reco', 'scale_factor')
_NUMBER = r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?'
_LABEL = re.compile(r'^\s*[\(\[]?\s*(' + _NUMBER + r')\s*(?:,|;|–|—|\bto\b|-)\s*(' + _NUMBER + r')\s*[\)\]]?\s*$')
MAX_MAP_BYTES = 64_000_000


def _pin(path, raw):
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def label_edges(labels, axis):
    """Contiguous numeric edges from bin labels such as '(0,0.8)' or '20-35'."""
    pairs = []
    for label in labels:
        match = _LABEL.match(str(label))
        if not match:
            raise ValueError(f'axis {axis!r}: bin label {label!r} does not state a low and high edge')
        lo, hi = float(match.group(1)), float(match.group(2))
        if not lo < hi:
            raise ValueError(f'axis {axis!r}: bin label {label!r} has low >= high')
        pairs.append((lo, hi))
    for (lo1, hi1), (lo2, _) in zip(pairs, pairs[1:]):
        if not math.isclose(hi1, lo2, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError(f'axis {axis!r}: label edges are not contiguous ({hi1} then {lo2})')
    return np.array([pairs[0][0]] + [hi for _, hi in pairs], float)


class EfficiencyMap:
    def __init__(self, name, axes, edges, values, policies, provenance, *, allow_above_one=False,
                 semantics='absolute', card_modules=()):
        self.semantics, self.card_modules = semantics, list(card_modules)
        self.name, self.axes, self.edges = name, axes, [np.asarray(e, float) for e in edges]
        self.values = np.asarray(values, float)
        self.policies, self.provenance = policies, provenance
        if self.values.shape != tuple(len(e) - 1 for e in self.edges):
            raise ValueError(f'efficiency map {name!r}: values do not match its {len(self.edges)} axes')
        for axis, e in zip(axes, self.edges):
            if len(e) < 2 or not np.all(np.isfinite(e)) or not np.all(np.diff(e) > 0):
                raise ValueError(f'efficiency map {name!r}: axis {axis["name"]!r} edges must increase')
        if not np.all(np.isfinite(self.values)):
            raise ValueError(f'efficiency map {name!r} contains non-finite values')
        if np.any(self.values < 0) or (not allow_above_one and np.any(self.values > 1)):
            hint = (' (the largest value is above 1.5: is the map in percent?)' if np.max(self.values) > 1.5 else '')
            raise ValueError(f'efficiency map {name!r}: values must lie between 0 and 1{hint}; '
                             'a scale factor declares semantics scale_factor and allow_above_one')

    def lookup(self, coordinates):
        """Efficiency for each object; returns (values, per-axis counts)."""
        if len(coordinates) != len(self.edges):
            raise ValueError(f'efficiency map {self.name!r} needs {len(self.edges)} coordinates')
        indices, zero = [], None
        counts = {}
        for axis, edges, x in zip(self.axes, self.edges, coordinates):
            name = axis['name']
            x = np.asarray(x, float)
            policy = self.policies[name]
            below, above = (x < edges[0]), (x >= edges[-1])
            nan = np.isnan(x)
            if nan.any():
                raise ValueError(f'efficiency map {self.name!r}: {int(nan.sum())} objects have no value for axis {name!r}')
            outside = below | above
            entry = {'below': int(below.sum()), 'above': int(above.sum()), 'clamped': 0, 'zeroed': 0}
            if outside.any():
                if policy == 'refuse':
                    raise ValueError(f'efficiency map {self.name!r}: {int(outside.sum())} objects lie outside axis '
                                     f'{name!r} [{edges[0]}, {edges[-1]}) and its declared policy is refuse')
                if policy == 'clamp':
                    entry['clamped'] = int(outside.sum())
                else:
                    entry['zeroed'] = int(outside.sum())
                    zero = outside if zero is None else zero | outside
            counts[name] = entry
            idx = np.clip(np.searchsorted(edges, x, side='right') - 1, 0, len(edges) - 2)
            indices.append(idx)
        values = self.values[tuple(indices)] if indices[0].size else np.zeros(0)
        if zero is not None:
            values = np.where(zero, 0.0, values)
        return values, counts


def _policies(spec, axes):
    policy = spec.get('out_of_range')
    names = [a['name'] for a in axes]
    if isinstance(policy, str):
        policy = {n: policy for n in names}
    if not isinstance(policy, dict) or set(policy) != set(names) or any(p not in POLICIES for p in policy.values()):
        raise ValueError(f'out_of_range must be one of {POLICIES} or a policy for each axis {names}')
    return policy


def _read_source(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'efficiency map source must be a regular file: {path}')
    raw = path.read_bytes()
    if not 0 < len(raw) <= MAX_MAP_BYTES:
        raise ValueError(f'efficiency map source {path} must be nonempty and at most 64 MB')
    return raw


def load_map(name, spec, base):
    """Load a declared map. `spec` follows the recipe's efficiency_maps entry."""
    allowed = {'source', 'axes', 'axis_edges', 'out_of_range', 'citation', 'semantics', 'card_modules',
               'allow_above_one', 'description'}
    if not isinstance(spec, dict) or set(spec) - allowed or not {'source', 'axes', 'out_of_range', 'citation', 'semantics'} <= set(spec):
        raise ValueError(f'efficiency map {name!r} needs source, axes, out_of_range, citation and semantics '
                         f'(allowed keys {sorted(allowed)})')
    if spec['semantics'] not in SEMANTICS:
        raise ValueError(f'efficiency map {name!r}: semantics must be one of {SEMANTICS}')
    if spec.get('allow_above_one') is True and spec['semantics'] != 'scale_factor':
        raise ValueError(f'efficiency map {name!r}: only a scale_factor map may exceed 1')
    modules = spec.get('card_modules', [])
    if not isinstance(modules, list) or any(not isinstance(m, str) or not re.fullmatch(r'[A-Za-z_][\w]*', m) for m in modules):
        raise ValueError(f'efficiency map {name!r}: card_modules is a list of detector-card module names')
    if not isinstance(spec['citation'], str) or not spec['citation'].strip():
        raise ValueError(f'efficiency map {name!r} needs a citation for its source')
    axes = spec['axes']
    if (not isinstance(axes, list) or not 1 <= len(axes) <= 3
            or any(not isinstance(a, dict) or set(a) != {'name', 'unit'} or not str(a['name']).strip() for a in axes)
            or len({a['name'] for a in axes}) != len(axes)):
        raise ValueError(f'efficiency map {name!r} needs 1-3 axes, each with a distinct name and a unit')
    source = spec['source']
    if not isinstance(source, dict) or source.get('format') not in ('root', 'json-grid', 'hepdata', 'yoda') or 'path' not in source:
        raise ValueError(f'efficiency map {name!r}: source needs format root, json-grid, hepdata or yoda and a path')
    path = (Path(base) / source['path']).resolve() if not Path(source['path']).is_absolute() else Path(source['path'])
    raw = _read_source(path)
    provenance = {**_pin(path, raw), 'format': source['format'], 'citation': spec['citation']}
    if source['format'] == 'root':
        edges, values = _from_root(name, path, source, spec, len(axes), provenance)
    elif source['format'] == 'json-grid':
        edges, values = _from_grid(name, raw, axes)
    elif source['format'] == 'yoda':
        edges, values = _from_yoda(name, raw, source, len(axes))
        provenance['object'] = source['object']
    else:
        edges, values = _from_hepdata(name, raw, source, len(axes))
    provenance.update(semantics=spec['semantics'], card_modules=list(modules))
    return EfficiencyMap(name, axes, edges, values, _policies(spec, axes), provenance,
                         allow_above_one=spec.get('allow_above_one') is True, semantics=spec['semantics'],
                         card_modules=modules)


def _from_root(name, path, source, spec, ndim, provenance):
    import uproot
    if set(source) != {'format', 'path', 'object'} or not isinstance(source['object'], str):
        raise ValueError(f'efficiency map {name!r}: a ROOT source needs path and object')
    mode = spec.get('axis_edges')
    if mode not in ('numeric', 'labels'):
        raise ValueError(f'efficiency map {name!r}: declare axis_edges as numeric or labels for a ROOT histogram')
    with uproot.open(path) as f:
        try:
            hist = f[source['object']]
        except KeyError:
            raise ValueError(f'efficiency map {name!r}: {source["object"]!r} is not in {path}') from None
        classname = hist.classname
        if not re.fullmatch(r'TH[123][DFIS]', classname):
            raise ValueError(f'efficiency map {name!r}: {source["object"]!r} is a {classname}, not a TH1/TH2/TH3')
        if int(classname[2]) != ndim:
            raise ValueError(f'efficiency map {name!r}: histogram has {classname[2]} axes but {ndim} are declared')
        values = np.asarray(hist.values(flow=False), float)
        edges, labels = [], []
        for i in range(ndim):
            axis = hist.axis(i)
            numeric = np.asarray(axis.edges(flow=False), float)
            text = axis.labels()
            labels.append(list(text) if text else None)
            if mode == 'labels':
                if not text:
                    raise ValueError(f'efficiency map {name!r}: axis {i} has no labels to read edges from')
                if len(text) != len(numeric) - 1:
                    raise ValueError(f'efficiency map {name!r}: axis {i} has {len(text)} labels for {len(numeric) - 1} bins')
                edges.append(label_edges(text, spec['axes'][i]['name']))
            else:
                if text:
                    parsed = None
                    try:
                        parsed = label_edges(text, spec['axes'][i]['name'])
                    except ValueError:
                        pass
                    if parsed is None or len(parsed) != len(numeric) or not np.allclose(parsed, numeric):
                        raise ValueError(f'efficiency map {name!r}: axis {i} carries bin labels that differ from its '
                                         'numeric edges; declare axis_edges labels if the labels hold the edges')
                edges.append(numeric)
        provenance.update(object=source['object'], classname=classname, axis_labels=labels, axis_edges=mode)
    return edges, values


def _from_grid(name, raw, axes):
    doc = json.loads(raw)
    if not isinstance(doc, dict) or set(doc) - {'axes', 'values', 'description'} or not {'axes', 'values'} <= set(doc):
        raise ValueError(f'efficiency map {name!r}: a JSON grid has axes and values')
    if [a.get('name') for a in doc['axes']] != [a['name'] for a in axes]:
        raise ValueError(f'efficiency map {name!r}: grid axes {[a.get("name") for a in doc["axes"]]} differ from the declaration')
    for a, declared in zip(doc['axes'], axes):
        if a.get('unit') != declared['unit']:
            raise ValueError(f'efficiency map {name!r}: axis {a["name"]!r} unit differs from the declaration')
    return [np.asarray(a['edges'], float) for a in doc['axes']], np.asarray(doc['values'], float)


def _from_hepdata(name, raw, source, ndim):
    import yaml
    if set(source) - {'format', 'path', 'dependent_variable'}:
        raise ValueError(f'efficiency map {name!r}: a HEPData source has path and dependent_variable')
    doc = yaml.safe_load(raw.decode('utf8'))
    ivs, dvs = doc.get('independent_variables'), doc.get('dependent_variables')
    if not isinstance(ivs, list) or len(ivs) != ndim or not isinstance(dvs, list) or not dvs:
        raise ValueError(f'efficiency map {name!r}: the table needs {ndim} independent variables')
    dep = source.get('dependent_variable', 0)
    if type(dep) is not int or not 0 <= dep < len(dvs):
        raise ValueError(f'efficiency map {name!r}: dependent_variable is outside the table')
    rows = [(tuple((float(iv['values'][r]['low']), float(iv['values'][r]['high'])) for iv in ivs),
             dvs[dep]['values'][r]['value']) for r in range(len(dvs[dep]['values']))]
    edges = []
    for axis in range(ndim):
        pairs = sorted({row[0][axis] for row in rows})
        for (lo1, hi1), (lo2, _) in zip(pairs, pairs[1:]):
            if not math.isclose(hi1, lo2):
                raise ValueError(f'efficiency map {name!r}: axis {axis} bins are not contiguous')
        edges.append(np.array([pairs[0][0]] + [hi for _, hi in pairs]))
    shape = tuple(len(e) - 1 for e in edges)
    values = np.full(shape, np.nan)
    for key, value in rows:
        index = tuple(int(np.searchsorted(e, lo)) for e, (lo, _) in zip(edges, key))
        if not np.isnan(values[index]):
            raise ValueError(f'efficiency map {name!r}: two rows fill the same bin')
        if type(value) not in (int, float):
            raise ValueError(f'efficiency map {name!r}: non-numeric efficiency {value!r}')
        values[index] = value
    if np.isnan(values).any():
        raise ValueError(f'efficiency map {name!r}: the table does not fill a complete rectangular grid')
    return edges, values


def _grid_from_points(name, points, ndim):
    """Edges and values from ((low, high) per axis, value) points that tile a rectangular grid."""
    edges = []
    for axis in range(ndim):
        pairs = sorted({p[0][axis] for p in points})
        for (lo1, hi1), (lo2, _) in zip(pairs, pairs[1:]):
            if not math.isclose(hi1, lo2, rel_tol=1e-9, abs_tol=1e-12):
                raise ValueError(f'efficiency map {name!r}: axis {axis} bins are not contiguous')
        edges.append(np.array([pairs[0][0]] + [hi for _, hi in pairs]))
    values = np.full(tuple(len(e) - 1 for e in edges), np.nan)
    for key, value in points:
        index = tuple(int(np.argmin(np.abs(e[:-1] - lo))) for e, (lo, _) in zip(edges, key))
        if not np.isnan(values[index]):
            raise ValueError(f'efficiency map {name!r}: two points fill the same bin')
        values[index] = value
    if np.isnan(values).any():
        raise ValueError(f'efficiency map {name!r}: the points do not fill a complete rectangular grid')
    return edges, values


def _from_yoda(name, raw, source, ndim):
    """A YODA Scatter2D (one axis) or Scatter3D (two axes) block; the errors give the bin edges."""
    if set(source) != {'format', 'path', 'object'} or not isinstance(source['object'], str):
        raise ValueError(f'efficiency map {name!r}: a YODA source needs path and object')
    if ndim not in (1, 2):
        raise ValueError(f'efficiency map {name!r}: a YODA map has one or two axes')
    kind = 'SCATTER2D' if ndim == 1 else 'SCATTER3D'
    block, inside = [], False
    for line in raw.decode('utf8').splitlines():
        text = line.strip()
        if text.startswith('BEGIN '):
            parts = text.split()
            inside = len(parts) >= 3 and parts[2] == source['object']
            if inside and not parts[1].startswith('YODA_' + kind):
                raise ValueError(f'efficiency map {name!r}: {source["object"]!r} is a {parts[1]}, not a {kind.title()}')
            continue
        if text.startswith('END '):
            if inside:
                break
            continue
        if inside and text and not text.startswith('#') and ':' not in text and text != '---':
            block.append([float(x) for x in text.split()])
    if not block:
        raise ValueError(f'efficiency map {name!r}: {source["object"]!r} is not in the YODA file or has no points')
    width = 3 * (ndim + 1)
    points = []
    for row in block:
        if len(row) != width:
            raise ValueError(f'efficiency map {name!r}: a {kind.title()} point has {width} numbers')
        bounds = tuple((row[3 * k] - row[3 * k + 1], row[3 * k] + row[3 * k + 2]) for k in range(ndim))
        points.append((bounds, row[3 * ndim]))
    return _grid_from_points(name, points, ndim)


# ---------------------------------------------------------------- detector-card guard
def card_modules(text):
    """{module name: {'class', 'formula'}} for every module of a Delphes card."""
    text = re.sub(r'#[^\n]*', '', text)
    modules = {}
    for match in re.finditer(r'^\s*module\s+(\w+)\s+(\w+)\s*\{', text, re.M):
        start = match.end()
        depth, i = 1, start
        while i < len(text) and depth:
            depth += {'{': 1, '}': -1}.get(text[i], 0)
            i += 1
        body = text[start:i - 1]
        formula = None
        found = re.search(r'set\s+EfficiencyFormula\s*\{', body)
        if found:
            j, level = found.end(), 1
            while j < len(body) and level:
                level += {'{': 1, '}': -1}.get(body[j], 0)
                j += 1
            formula = ' '.join(body[found.end():j - 1].split())
        modules[match.group(2)] = {'class': match.group(1), 'formula': formula}
    return modules


def _trivial(formula):
    if formula is None:
        return False
    bare = formula.replace('(', '').replace(')', '').replace(' ', '')
    try:
        return float(bare) == 1.0
    except ValueError:
        return False


def check_card(maps, card_path):
    """Compare each map's semantics with the efficiency modules of a Delphes card."""
    path = Path(card_path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'detector card must be a regular file: {path}')
    raw = path.read_bytes()
    modules = card_modules(raw.decode('utf8', errors='replace'))
    report = {'card': _pin(path.resolve(), raw), 'maps': {}}
    for name, emap in maps.items():
        rows = {}
        for module in emap.card_modules:
            entry = modules.get(module)
            rows[module] = ({'present': False} if entry is None else
                            {'present': True, 'class': entry['class'], 'formula': entry['formula'],
                             'trivial': _trivial(entry['formula'])})
        applied = [m for m, r in rows.items() if r['present'] and r.get('formula') is not None and not r['trivial']]
        if emap.semantics == 'absolute' and applied:
            raise ValueError(f'efficiency map {name!r} is absolute but the detector card already applies '
                             f'{", ".join(applied)}; use a map conditional on reconstruction or remove the card efficiency')
        if emap.semantics == 'conditional_on_reco':
            absent = [m for m, r in rows.items() if not r['present'] or r.get('formula') is None]
            if absent or not rows:
                raise ValueError(f'efficiency map {name!r} is conditional on reconstruction but the card has no '
                                 f'efficiency module {", ".join(absent) or "(none named in card_modules)"}')
        decision = ('stacks on the card efficiency' if emap.semantics == 'conditional_on_reco' else
                    'multiplies an applied efficiency' if emap.semantics == 'scale_factor' else
                    'no double counting' if rows else 'no card modules named')
        report['maps'][name] = {'semantics': emap.semantics, 'modules': rows, 'decision': decision}
    return report


# ---------------------------------------------------------------- reproducible random numbers
_MASK = np.uint64(0xFFFFFFFFFFFFFFFF)


def _splitmix(x):
    x = (x + np.uint64(0x9E3779B97F4A7C15)) & _MASK
    x = ((x ^ (x >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)) & _MASK
    x = ((x ^ (x >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)) & _MASK
    return x ^ (x >> np.uint64(31))


def uniforms(seed, file_index, entry, object_index, stream=0):
    """Uniform numbers in [0, 1) that depend only on their keys."""
    with np.errstate(over='ignore'):
        key = _splitmix(np.uint64(seed) ^ _splitmix(np.uint64(stream)))
        x = _splitmix(key ^ np.asarray(file_index, np.uint64))
        x = _splitmix(x ^ np.asarray(entry, np.uint64))
        x = _splitmix(x ^ np.asarray(object_index, np.uint64))
    return (x >> np.uint64(11)).astype(np.float64) * (1.0 / 9007199254740992.0)
