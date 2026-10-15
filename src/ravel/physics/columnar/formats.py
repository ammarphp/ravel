"""Format descriptors and chunked readers for detector-level and parton-level events.

A *format descriptor* is JSON data that says where each physics field lives in a file.
No branch name is written in code; RAVEL ships ``delphes`` and ``nanoaod``
descriptors, and any other ntuple layout is described by a supplied
descriptor. Two formats are read:

``root`` (Delphes trees, flat ntuples, PHYSLITE-like trees), read with uproot::

    {"schema_version": 1, "kind": "columnar-format", "name": "...", "source": "...",
     "format": "root", "tree": "nominal",
     "collections": {"el": {"fields": {"pt": {"branch": "el_pt", "scale": 0.001},
                                       "eta": "el_eta", "phi": "el_phi",
                                       "mass": {"fixed": 0.000511, "source": "..."}}}},
     "met": {"magnitude": "met_met", "phi": "met_phi"},
     "event": {"mc": "weight_mc", "pileup": "weight_pileup"},
     "variations": {"jet energy scale up": {"replace": ["_NOSYS", "_JES__1up"]}}}

A field is a branch name, ``{"branch", "scale", "reduce"}`` (``reduce: "first"`` takes the
single entry of a length-one jagged branch, as Delphes stores MissingET and Event), or
``{"fixed", "source"}``. Collection fields must be jagged with a common length per event;
event fields must be one value per event. ``met`` may also be given as ``px``/``py``.
A collection's mass may be ``{"from_energy": <field spec>, "tolerance": <relative tolerance>}``.
The energy input is a branch specification or another declared field's key; its scale
must give the same units as pt. The default tolerance is zero (strict). With an explicit
finite tolerance in [0, 1), negative m² is clamped only when
``-m² <= tolerance * max(E², (pt*cosh(eta))²)``. Nonfinite or unphysical inputs fail.
Each view's ``summary`` and its chunk's ``extra`` report ``negative_mass_squared``
counts by collection. Pass a dict as ``read(..., summary=...)`` to collect counts across
evaluated chunks and variations; evaluating the same chunk/variation again counts once.
A variation renames branches (``replace`` substitutes text in every branch name that has a
varied counterpart in the file, or ``branches`` maps names explicitly).

``lhe`` (Les Houches event files, plain or gzip)::

    {"format": "lhe", "collections": {"photons": {"pdg": [22], "status": [1]},
                                       "leptons": {"pdg": [11, -11], "charge_from_pdg_sign": -1}},
     "invisible": {"pdg": [12, -12, 14, -14, 16, -16], "source": "..."},
     "event": {"weight": "nominal", "scale up": {"lhe_weight_id": "muR2"}}}

The missing transverse momentum of an LHE event is the vector sum of the declared
invisible final-state particles. Every collection exposes ``pt``, ``eta``, ``phi`` and
``mass`` (GeV) plus its declared fields; leptons with ``pdg_id`` also get ``flavour``.
"""
import gzip
import hashlib
import json
import re
from copy import copy
from dataclasses import dataclass, field
from pathlib import Path

import awkward as ak
import numpy as np

DATA = Path(__file__).resolve().parents[2] / 'data' / 'columnar'
_IDENT = re.compile(r'^[a-z][a-z0-9_]{0,63}$')
MAX_DESCRIPTOR_BYTES = 1_000_000


def builtin(name):
    path = DATA / f'{name}.json'
    if not re.fullmatch(r'[a-z0-9-]+', name) or not path.is_file():
        raise ValueError(f'no built-in format descriptor named {name!r}; available: {sorted(p.stem for p in DATA.glob("*.json"))}')
    return json.loads(path.read_text())


def load_descriptor(value, base=None):
    """A built-in name, a path to a JSON descriptor, or an inline descriptor object."""
    if isinstance(value, dict):
        return Descriptor(value, origin={'kind': 'inline'})
    if isinstance(value, str) and value.startswith('builtin:'):
        value = value.removeprefix('builtin:')
    if isinstance(value, str) and re.fullmatch(r'[a-z0-9-]+', value) and (DATA / f'{value}.json').is_file():
        raw = (DATA / f'{value}.json').read_bytes()
        return Descriptor(json.loads(raw), origin={'kind': 'builtin', 'name': value, 'sha256': hashlib.sha256(raw).hexdigest()})
    path = Path(value) if base is None or Path(value).is_absolute() else Path(base) / value
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'format descriptor must be a built-in name or a regular file: {value}')
    raw = path.read_bytes()
    if len(raw) > MAX_DESCRIPTOR_BYTES:
        raise ValueError('format descriptor is larger than 1 MB')
    return Descriptor(json.loads(raw), origin={'kind': 'file', 'path': str(path.resolve()),
                                               'sha256': hashlib.sha256(raw).hexdigest()})


@dataclass
class Chunk:
    entry_start: int
    length: int
    arrays: dict
    available: frozenset = frozenset()
    extra: dict = field(default_factory=dict)


@dataclass
class View:
    """One chunk, one variation: named collections, missing momentum and event fields."""
    entries: np.ndarray
    collections: dict
    met_magnitude: np.ndarray
    met_phi: np.ndarray
    event: dict
    summary: dict = field(default_factory=dict)


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be nonempty text')
    return value


class Descriptor:
    def __init__(self, doc, origin=None):
        if not isinstance(doc, dict) or doc.get('schema_version') != 1 or doc.get('kind') != 'columnar-format':
            raise ValueError('a format descriptor needs schema_version 1 and kind columnar-format')
        self.doc = json.loads(json.dumps(doc))
        self.format = doc.get('format', 'root')
        self.origin = origin or {'kind': 'inline'}
        self.sha256 = hashlib.sha256(json.dumps(self.doc, sort_keys=True).encode()).hexdigest()
        _text(doc.get('name'), 'descriptor name'); _text(doc.get('source'), 'descriptor source')
        if self.format == 'root':
            self._validate_root()
        elif self.format == 'lhe':
            self._validate_lhe()
        else:
            raise ValueError('descriptor format must be root or lhe')

    # ------------------------------------------------------------ validation
    def _field(self, spec, label, *, jagged):
        if isinstance(spec, str):
            return {'branch': _text(spec, label), 'scale': 1.0, 'reduce': None}
        if not isinstance(spec, dict):
            raise ValueError(f'{label} must be a branch name or an object')
        if 'ratio' in spec or 'mass_from' in spec:
            key = 'ratio' if 'ratio' in spec else 'mass_from'
            if set(spec) - {key, 'optional'} or not jagged:
                raise ValueError(f'{label}: derived collection field required')
            self._optional(spec, label)
            values = spec[key]
            if key == 'ratio':
                if not isinstance(values, list) or len(values) != 2:
                    raise ValueError(f'{label}: ratio needs numerator and denominator')
                parsed = [self._field(v, label, jagged=True) for v in values]
            else:
                if not isinstance(values, dict) or set(values) != {'px', 'py', 'pz', 'e'}:
                    raise ValueError(f'{label}: mass_from needs px, py, pz and e')
                parsed = {k: self._field(v, label, jagged=True) for k, v in values.items()}
            return {key: parsed, 'optional': spec.get('optional', False)}
        if 'fixed' in spec:
            if set(spec) != {'fixed', 'source'} or type(spec['fixed']) not in (int, float):
                raise ValueError(f'{label}: a fixed value needs a number and its source')
            _text(spec['source'], f'{label} source')
            return {'fixed': spec['fixed']}
        if set(spec) - {'branch', 'scale', 'reduce', 'index', 'member', 'optional'} or 'branch' not in spec:
            raise ValueError(f'{label}: a branch field has branch and optional scale and reduce')
        scale = spec.get('scale', 1.0)
        if type(scale) not in (int, float) or not np.isfinite(scale) or scale == 0:
            raise ValueError(f'{label}: scale must be a nonzero number')
        reduce = spec.get('reduce')
        if reduce not in (None, 'first') or (reduce and jagged):
            raise ValueError(f'{label}: reduce "first" applies to one-value-per-event fields only')
        self._optional(spec, label)
        if 'index' in spec and (not jagged or type(spec['index']) is not int or not 0 <= spec['index'] < 1024):
            raise ValueError(f'{label}: index needs a bounded nonnegative collection array slot')
        member = spec.get('member')
        if 'member' in spec and (not jagged or type(member) is not list or not 1 <= len(member) <= 4
                                 or not all(isinstance(m, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', m) for m in member)):
            raise ValueError(f'{label}: member needs the nested member names of a collection record branch')
        return {'branch': _text(spec['branch'], label), 'scale': float(scale), 'reduce': reduce,
                **({'index': spec['index']} if 'index' in spec else {}),
                **({'member': tuple(member)} if member else {}), 'optional': spec.get('optional', False)}

    @staticmethod
    def _optional(spec, label):
        if type(spec.get('optional', False)) is not bool:
            raise ValueError(f'{label}: optional must be boolean')

    @staticmethod
    def _leaves(spec):
        if 'ratio' in spec:
            for s in spec['ratio']:
                yield from Descriptor._leaves(s)
        elif 'mass_from' in spec:
            for s in spec['mass_from'].values():
                yield from Descriptor._leaves(s)
        else:
            yield spec

    def requiring(self, names):
        """Bind requested ancillary fields without mutating the reusable descriptor."""
        result = copy(self)
        result.required_fields = frozenset(names)
        return result

    def _validate_root(self):
        doc = self.doc
        allowed = {'schema_version', 'kind', 'name', 'source', 'format', 'tree', 'collections', 'met', 'event', 'variations'}
        if set(doc) - allowed or 'tree' not in doc or 'collections' not in doc:
            raise ValueError(f'a root descriptor accepts only {sorted(allowed)} and needs tree and collections')
        _text(doc['tree'], 'tree')
        self.collections = {}
        self.counts = {}
        self.required_fields = frozenset()
        for name, spec in doc['collections'].items():
            _text(name, 'collection name')
            if not isinstance(spec, dict) or set(spec) - {'fields', 'count', 'optional'} or not isinstance(spec.get('fields'), dict):
                raise ValueError(f'collection {name!r} needs fields')
            self._optional(spec, name)
            fields = {}
            mass_from_energy = None
            for key, value in spec['fields'].items():
                if not _IDENT.match(key):
                    raise ValueError(f'collection {name!r}: field name {key!r} must be lower-case letters, digits and _')
                if isinstance(value, dict) and 'from_energy' in value:
                    if key != 'mass' or set(value) - {'from_energy', 'tolerance'}:
                        raise ValueError(f'{name}.{key}: from_energy is a mass field with optional tolerance')
                    tolerance = value.get('tolerance', 0.0)
                    if type(tolerance) not in (int, float) or not np.isfinite(tolerance) or not 0 <= tolerance < 1:
                        raise ValueError(f'{name}.mass: tolerance must be a finite relative number in [0, 1)')
                    mass_from_energy = value
                    fields[key] = {'tolerance': float(tolerance)}
                else:
                    fields[key] = self._field(value, f'{name}.{key}', jagged=True)
            if mass_from_energy is not None:
                energy = mass_from_energy['from_energy']
                if isinstance(energy, str) and energy in fields:
                    if energy == 'mass':
                        raise ValueError(f'{name}.mass: from_energy cannot reference mass itself')
                    fields['mass']['from_energy'] = fields[energy]
                else:
                    fields['mass']['from_energy'] = self._field(energy, f'{name}.mass.from_energy', jagged=True)
                if 'fixed' in fields['mass']['from_energy']:
                    raise ValueError(f'{name}.mass: from_energy needs a branch, not a fixed value')
            missing = {'pt', 'eta', 'phi', 'mass'} - set(fields)
            if missing:
                raise ValueError(f'collection {name!r} must declare {sorted(missing)} (a fixed mass needs its source)')
            if all('fixed' in f.get('from_energy', f) for f in fields.values()):
                raise ValueError(f'collection {name!r} needs at least one branch')
            self.collections[name] = fields
            if 'count' in spec:
                self.counts[name] = self._field(spec['count'], f'{name} count', jagged=False)
        met = doc.get('met')
        if met is None:
            self.met = None
        else:
            if not isinstance(met, dict) or set(met) not in ({'magnitude', 'phi'}, {'px', 'py'}):
                raise ValueError('met needs magnitude and phi, or px and py')
            self.met = {k: self._field(v, f'met.{k}', jagged=False) for k, v in met.items()}
        self.event = {}
        for key, value in (doc.get('event') or {}).items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError('event field names must be nonempty text')
            self.event[key] = self._field(value, f'event.{key}', jagged=False)
        self.variations = {}
        for key, value in (doc.get('variations') or {}).items():
            _text(key, 'variation name')
            if isinstance(value, dict) and set(value) == {'replace'} and isinstance(value['replace'], list) \
                    and len(value['replace']) == 2 and all(isinstance(x, str) and x for x in value['replace']):
                self.variations[key] = value
            elif isinstance(value, dict) and set(value) == {'branches'} and isinstance(value['branches'], dict):
                self.variations[key] = value
            else:
                raise ValueError(f'variation {key!r} needs replace [old, new] or a branches mapping')

    def _validate_lhe(self):
        doc = self.doc
        allowed = {'schema_version', 'kind', 'name', 'source', 'format', 'collections', 'invisible', 'event'}
        if set(doc) - allowed or 'collections' not in doc:
            raise ValueError(f'an lhe descriptor accepts only {sorted(allowed)} and needs collections')
        self.collections = {}
        for name, spec in doc['collections'].items():
            _text(name, 'collection name')
            if not isinstance(spec, dict) or set(spec) - {'pdg', 'status', 'charge_from_pdg_sign'} or 'pdg' not in spec:
                raise ValueError(f'collection {name!r} needs pdg and optional status and charge_from_pdg_sign')
            if not spec['pdg'] or any(type(p) is not int for p in spec['pdg']):
                raise ValueError(f'collection {name!r}: pdg must be a list of integer particle codes')
            status = spec.get('status', [1])
            if not status or any(type(s) is not int for s in status):
                raise ValueError(f'collection {name!r}: status must be a list of integers')
            sign = spec.get('charge_from_pdg_sign')
            if sign not in (None, 1, -1):
                raise ValueError(f'collection {name!r}: charge_from_pdg_sign must be 1 or -1')
            self.collections[name] = {'pdg': list(spec['pdg']), 'status': list(status), 'charge_sign': sign}
        invisible = doc.get('invisible')
        if invisible is not None:
            if not isinstance(invisible, dict) or set(invisible) != {'pdg', 'source'} or any(type(p) is not int for p in invisible['pdg']):
                raise ValueError('invisible needs a list of integer pdg codes and its source')
            _text(invisible['source'], 'invisible source')
        self.invisible = None if invisible is None else list(invisible['pdg'])
        self.met = {'invisible': True} if invisible is not None else None
        self.event = {}
        for key, value in (doc.get('event') or {}).items():
            if value == 'nominal' or (isinstance(value, dict) and set(value) == {'lhe_weight_id'} and isinstance(value['lhe_weight_id'], str)):
                self.event[key] = value
            else:
                raise ValueError(f'lhe event field {key!r} must be "nominal" or {{"lhe_weight_id": id}}')
        self.variations = {}

    # ------------------------------------------------------------ branch planning
    def _branch(self, name, variation, available):
        if variation is None:
            return name
        rule = self.variations[variation]
        if 'branches' in rule:
            return rule['branches'].get(name, name)
        old, new = rule['replace']
        varied = name.replace(old, new)
        return varied if varied in available else name

    def _specs(self, collections, event_fields, available=None, variation=None):
        for c in collections:
            if c not in self.collections:
                raise ValueError(f'collection {c!r} is not in the format descriptor ({sorted(self.collections)})')
            for key, spec in self.collections[c].items():
                leaves = list(self._leaves(spec.get('from_energy', spec)))
                if (spec.get('optional') and key not in self.required_fields and available is not None
                        and any('branch' in s and self._branch(s['branch'], variation, available) not in available for s in leaves)):
                    continue
                for leaf in leaves:
                    yield f'{c}.{key}', leaf, True
            if c in self.counts:
                yield f'{c} count', self.counts[c], False
        if self.met is not None:
            for key, spec in self.met.items():
                yield f'met.{key}', spec, False
        for f in event_fields:
            if f not in self.event:
                raise ValueError(f'event field {f!r} is not in the format descriptor ({sorted(self.event)})')
            yield f'event.{f}', self.event[f], False

    # ------------------------------------------------------------ files
    def _present_collections(self, collections, available):
        """Bulk inspection omits ancillary collections absent from this source."""
        return [c for c in collections if not self.doc['collections'][c].get('optional') or
                any('branch' in leaf and leaf['branch'] in available
                    for spec in self.collections[c].values() for leaf in self._leaves(spec))]

    def check_file(self, path, *, variations=(), collections=None, event_fields=None):
        """Validate the declared branches against the file; return a typed report."""
        if self.format == 'lhe':
            return _lhe_report(path)
        import uproot
        inspect_all = collections is None
        collections = list(self.collections) if inspect_all else list(collections)
        event_fields = list(self.event) if event_fields is None else list(event_fields)
        for v in variations:
            if v not in self.variations:
                raise ValueError(f'variation {v!r} is not in the format descriptor')
        with uproot.open(path) as f:
            try:
                tree = f[self.doc['tree']]
            except KeyError:
                raise ValueError(f'{path} has no tree {self.doc["tree"]!r}') from None
            names = {b.name: b for b in tree.values(recursive=True)}
            available = frozenset(names)
            if inspect_all:
                collections = self._present_collections(collections, available)
            report = {'tree': self.doc['tree'], 'entries': int(tree.num_entries), 'branches': {}, 'variations': {}}
            for variation in (None, *variations):
                substitutions = {}
                for label, spec, jagged in self._specs(collections, event_fields, available, variation):
                    if 'fixed' in spec:
                        continue
                    nominal = spec['branch']
                    branch = self._branch(nominal, variation, available)
                    if branch not in names:
                        raise ValueError(f'{label}: branch {branch!r} is not in tree {self.doc["tree"]!r} of {path}')
                    typename = names[branch].typename
                    is_jagged = '[]' in typename or 'vector<' in typename
                    numeric = re.search(r'(float|double|int|bool|short|long|char)', typename.lower())
                    if 'member' in spec and numeric:
                        raise ValueError(f'{label}: member needs a record branch, but {branch!r} has numeric type {typename}')
                    if 'member' not in spec and not numeric:
                        raise ValueError(f'{label}: branch {branch!r} has non-numeric type {typename}')
                    if jagged and not is_jagged:
                        raise ValueError(f'{label}: collection field branch {branch!r} must be jagged, found {typename}')
                    if not jagged and is_jagged and spec['reduce'] != 'first':
                        raise ValueError(f'{label}: branch {branch!r} is jagged ({typename}); declare reduce "first" '
                                         'for a length-one branch')
                    if not jagged and not is_jagged and spec['reduce'] == 'first':
                        raise ValueError(f'{label}: reduce "first" needs a jagged branch, found {typename}')
                    report['branches'][branch] = typename
                    if variation is not None and branch != nominal:
                        substitutions[nominal] = branch
                if variation is not None:
                    report['variations'][variation] = substitutions
        return report

    def read(self, path, *, collections, event_fields, step, entry_start=None, entry_stop=None, variations=(),
             summary=None):
        """Yield chunks; an optional summary dict accumulates evaluated-view diagnostics."""
        if type(step) is not int or step < 1:
            raise ValueError('chunk size must be a positive integer')
        if summary is not None:
            summary.setdefault('negative_mass_squared', {})
        if self.format == 'lhe':
            yield from _lhe_chunks(self, path, collections, event_fields, step, entry_start, entry_stop)
            return
        import uproot
        with uproot.open(path) as f:
            tree = f[self.doc['tree']]
            available = frozenset(b.name for b in tree.values(recursive=True))
            collections = self._present_collections(collections, available)
            wanted = set()
            for variation in (None, *variations):
                for _, spec, _ in self._specs(collections, event_fields, available, variation):
                    if 'branch' in spec:
                        wanted.add(self._branch(spec['branch'], variation, available))
            wanted = sorted(wanted)
            start = 0 if entry_start is None else int(entry_start)
            stop = tree.num_entries if entry_stop is None else min(int(entry_stop), tree.num_entries)
            if not 0 <= start <= stop:
                raise ValueError(f'entry range {start}-{stop} is outside the tree of {tree.num_entries} entries')
            if start == stop or not wanted:
                return
            # Literal names can contain array brackets; uproot's string filters
            # interpret those as shell patterns rather than exact branch names.
            for arrays, report in tree.iterate(filter_name=lambda name: name in wanted, step_size=step, entry_start=start,
                                               entry_stop=stop, library='ak', report=True):
                data = {}
                for name in wanted:
                    key = name if name in arrays.fields else next((k for k in arrays.fields if k.endswith('/' + name)), None)
                    if key is None:
                        raise ValueError(f'branch {name!r} was not returned by the reader')
                    data[name] = arrays[key]
                extra = {'collections': list(collections), 'event_fields': list(event_fields),
                         'negative_mass_squared': {}}
                if summary is not None:
                    extra['_read_summary'] = summary
                yield Chunk(int(report.tree_entry_start), int(report.tree_entry_stop - report.tree_entry_start), data,
                            available, extra)

    def view(self, chunk, variation=None):
        if self.format == 'lhe':
            return _lhe_view(self, chunk)
        if variation is not None and variation not in self.variations:
            raise ValueError(f'variation {variation!r} is not in the format descriptor')
        n = chunk.length

        def value(spec, *, like=None):
            if 'ratio' in spec:
                numerator, denominator = [value(s, like=like) for s in spec['ratio']]
                with np.errstate(divide='ignore', invalid='ignore'):
                    return ak.where(denominator != 0, numerator / denominator, np.nan)
            if 'mass_from' in spec:
                p = {k: value(s, like=like) for k, s in spec['mass_from'].items()}
                squared = p['e'] ** 2 - p['px'] ** 2 - p['py'] ** 2 - p['pz'] ** 2
                # TLorentzVector's signed mass convention also covers spacelike vectors.
                return ak.where(squared >= 0, np.sqrt(abs(squared)), -np.sqrt(abs(squared)))
            if 'fixed' in spec:
                fixed = spec['fixed']
                if like is None:
                    return np.full(n, fixed, dtype=np.int64 if type(fixed) is int else float)
                return ak.ones_like(like, dtype=np.int64 if type(fixed) is int else np.float64) * fixed
            raw = chunk.arrays[self._branch(spec['branch'], variation, chunk.available)]
            for member in spec.get('member', ()):
                # An unsplit object branch is read whole; its members are record fields.
                if member not in ak.fields(raw):
                    raise ValueError(f"branch {spec['branch']!r}: member {member!r} is unavailable")
                raw = raw[member]
            if 'index' in spec:
                try:
                    raw = raw[:, :, spec['index']]
                except (IndexError, ValueError):
                    raise ValueError(f"branch {spec['branch']!r}: fixed array index {spec['index']} is unavailable") from None
            if spec['reduce'] == 'first':
                padded = ak.fill_none(ak.pad_none(raw, 1, axis=1, clip=True), np.nan)
                raw = ak.to_numpy(padded[:, 0]).astype(float)
            elif like is None:
                raw = ak.to_numpy(raw)
            if spec['scale'] != 1.0:
                raw = raw * spec['scale']
            elif like is not None and _dtype(raw).kind not in 'biu':
                raw = ak.values_astype(raw, np.float64)
            return raw

        collections = {}
        negative_mass_squared = {}
        for ordinal, name in enumerate(chunk.extra.get('collections', [])):
            fields = self.collections[name]
            first = next(s.get('from_energy', s) for s in fields.values() if 'branch' in s.get('from_energy', s))
            reference = chunk.arrays[self._branch(first['branch'], variation, chunk.available)]
            columns = {}
            for key, spec in fields.items():
                source = spec.get('from_energy', spec)
                if spec.get('optional') and key not in self.required_fields and any(
                        'branch' in s and self._branch(s['branch'], variation, chunk.available) not in chunk.arrays
                        for s in self._leaves(source)):
                    continue
                # Temporarily put the energy input in the mass slot to validate its shape.
                columns[key] = value(source, like=reference)
                if ak.any(ak.num(columns[key], axis=1) != ak.num(reference, axis=1)):
                    raise ValueError(f'collection {name!r}: its field branches have different lengths in some event')
            if 'from_energy' in fields['mass']:
                energy = ak.values_astype(columns['mass'], np.float64)
                pt = ak.values_astype(columns['pt'], np.float64)
                eta = ak.values_astype(columns['eta'], np.float64)
                with np.errstate(over='ignore', invalid='ignore'):
                    energy2 = energy ** 2
                    momentum2 = (pt * np.cosh(eta)) ** 2
                    mass2 = energy2 - momentum2
                valid = np.isfinite(mass2) & (energy >= 0) & (pt >= 0)
                if ak.any(~ak.fill_none(valid, False)):
                    raise ValueError(f'collection {name!r}: from_energy needs finite nonnegative energy and pt '
                                     'and finite momentum squared')
                tolerance = fields['mass']['tolerance']
                if ak.any(mass2 < -tolerance * np.maximum(energy2, momentum2)):
                    raise ValueError(f'collection {name!r}: negative mass squared exceeds relative tolerance {tolerance}')
                negative_mass_squared[name] = int(ak.sum(mass2 < 0))
                columns['mass'] = np.sqrt(ak.where(mass2 < 0, 0.0, mass2))
            try:
                record = ak.zip(columns)
            except ValueError:
                raise ValueError(f'collection {name!r}: its field branches have different lengths in some event') from None
            if name in self.counts:
                count = value(self.counts[name])
                if not np.issubdtype(count.dtype, np.integer) or not np.array_equal(count, ak.to_numpy(ak.num(record, axis=1))):
                    raise ValueError(f'collection {name!r}: count branch differs from object lengths')
            if 'pdg_id' in columns:
                record = ak.with_field(record, abs(record.pdg_id), 'flavour')
            record = ak.with_field(record, ak.local_index(record.pt), '_idx')
            record = ak.with_field(record, ak.ones_like(record.pt, dtype=np.int64) * ordinal, '_src')
            collections[name] = record
        met_mag = met_phi = np.full(n, np.nan)
        if self.met is not None:
            if 'magnitude' in self.met:
                met_mag, met_phi = value(self.met['magnitude']).astype(float), value(self.met['phi']).astype(float)
            else:
                px, py = value(self.met['px']).astype(float), value(self.met['py']).astype(float)
                met_mag, met_phi = np.hypot(px, py), np.arctan2(py, px)
        event = {f: value(self.event[f]) for f in chunk.extra.get('event_fields', [])}
        # Retain counts per chunk and optionally across a read, without repeat-view inflation.
        identity = json.dumps([self.sha256, variation])
        counted = chunk.extra.setdefault('_mass_squared_views', {})
        if identity not in counted:
            totals = chunk.extra.setdefault('negative_mass_squared', {})
            read_summary = chunk.extra.get('_read_summary')
            for name, count in negative_mass_squared.items():
                totals[name] = totals.get(name, 0) + count
                if read_summary is not None:
                    read_totals = read_summary['negative_mass_squared']
                    read_totals[name] = read_totals.get(name, 0) + count
            counted[identity] = True
        return View(np.arange(chunk.entry_start, chunk.entry_start + n), collections, met_mag, met_phi, event,
                    {'negative_mass_squared': negative_mass_squared})


def _dtype(array):
    layout = ak.to_layout(array)
    while not hasattr(layout, 'dtype'):
        layout = layout.content
    return layout.dtype


# ---------------------------------------------------------------- LHE
_WGT = re.compile(r"<wgt\s+id\s*=\s*['\"]([^'\"]+)['\"]\s*>\s*([^<\s]+)\s*</wgt>")
_WEIGHT_ID = re.compile(r"<weight\s+[^>]*id\s*=\s*['\"]([^'\"]+)['\"]")


def _open_text(path):
    path = Path(path)
    with path.open('rb') as probe:
        magic = probe.read(2)
    return gzip.open(path, 'rt', encoding='utf8') if magic == b'\x1f\x8b' else path.open('r', encoding='utf8')


def _lhe_events(path):
    """Yield (header numbers, particle rows, named weights) for every event."""
    with _open_text(path) as stream:
        inside, lines = False, []
        for line in stream:
            stripped = line.strip()
            if stripped.startswith('<event'):
                inside, lines = True, []
                continue
            if stripped.startswith('</event'):
                inside = False
                body = [ln for ln in lines if ln and not ln.startswith('#')]
                numeric = []
                for ln in body:
                    if ln.startswith('<'):
                        break
                    numeric.append(ln.split('#', 1)[0].split())
                if not numeric or len(numeric[0]) != 6:
                    raise ValueError(f'{path}: malformed LHE event header')
                nup = int(numeric[0][0])
                if len(numeric) < 1 + nup:
                    raise ValueError(f'{path}: LHE event declares {nup} particles but lists {len(numeric) - 1}')
                rows = [r[:13] for r in numeric[1:1 + nup]]
                if any(len(r) < 13 for r in rows):
                    raise ValueError(f'{path}: malformed LHE particle line')
                weights = {m.group(1): float(m.group(2)) for m in _WGT.finditer('\n'.join(body))}
                yield float(numeric[0][2]), rows, weights
                continue
            if inside:
                lines.append(stripped)


def _lhe_report(path):
    with _open_text(path) as stream:
        head = []
        for line in stream:
            if line.lstrip().startswith('<event'):
                break
            head.append(line)
    text = ''.join(head)
    init = re.search(r'<init>\s*(.*?)</init>', text, re.S)
    xsec = None
    if init:
        rows = [r.split() for r in init.group(1).strip().splitlines() if r.strip() and not r.strip().startswith('#')]
        if len(rows) >= 2:
            xsec = sum(float(r[0]) for r in rows[1:])
    count = sum(1 for _ in _lhe_events(path))
    return {'format': 'lhe', 'entries': count, 'cross_section_pb': xsec, 'weight_ids': _WEIGHT_ID.findall(text),
            'cross_section_source': 'sum of XSECUP in the LHE init block' if xsec is not None else None}


def _lhe_chunks(descriptor, path, collections, event_fields, step, entry_start, entry_stop):
    for c in collections:
        if c not in descriptor.collections:
            raise ValueError(f'collection {c!r} is not in the format descriptor')
    for f in event_fields:
        if f not in descriptor.event:
            raise ValueError(f'event field {f!r} is not in the format descriptor')
    start = 0 if entry_start is None else int(entry_start)
    stop = None if entry_stop is None else int(entry_stop)
    buffer, first, seen = [], start, 0
    for i, event in enumerate(_lhe_events(path)):
        seen = i + 1
        if i < start:
            continue
        if stop is not None and i >= stop:
            break
        buffer.append(event)
        if len(buffer) == step:
            yield Chunk(first, len(buffer), {'events': buffer}, frozenset(),
                        {'collections': list(collections), 'event_fields': list(event_fields)})
            first, buffer = first + len(buffer), []
    if stop is not None and seen < stop:
        raise ValueError(f'{path} has {seen} events; the requested entry range ends at {stop}')
    if buffer:
        yield Chunk(first, len(buffer), {'events': buffer}, frozenset(),
                    {'collections': list(collections), 'event_fields': list(event_fields)})


def _lhe_view(descriptor, chunk):
    events = chunk.arrays['events']
    n = len(events)
    counts = [len(rows) for _, rows, _ in events]
    flat = np.array([r for _, rows, _ in events for r in rows], dtype=float).reshape(-1, 13)
    pdg = flat[:, 0].astype(np.int64); status = flat[:, 1].astype(np.int64)
    px, py, pz, e, m = flat[:, 6], flat[:, 7], flat[:, 8], flat[:, 9], flat[:, 10]
    from .kinematics import from_cartesian
    pt, eta, phi, _ = from_cartesian(px, py, pz, e)
    event_of = np.repeat(np.arange(n), counts)
    collections = {}
    for ordinal, name in enumerate(chunk.extra['collections']):
        spec = descriptor.collections[name]
        keep = np.isin(pdg, spec['pdg']) & np.isin(status, spec['status'])
        # Order each event's particles by decreasing pT.
        order = np.lexsort((-pt[keep], event_of[keep]))
        sel = np.flatnonzero(keep)[order]
        per_event = np.bincount(event_of[keep], minlength=n)
        columns = {'pt': pt[sel], 'eta': eta[sel], 'phi': phi[sel], 'mass': m[sel], 'e': e[sel],
                   'pdg_id': pdg[sel], 'flavour': np.abs(pdg[sel])}
        if spec['charge_sign'] is not None:
            columns['charge'] = np.sign(pdg[sel]) * spec['charge_sign']
        record = ak.unflatten(ak.zip(columns), per_event)
        record = ak.with_field(record, ak.local_index(record.pt), '_idx')
        record = ak.with_field(record, ak.ones_like(record.pt, dtype=np.int64) * ordinal, '_src')
        collections[name] = record
    met_mag = met_phi = np.full(n, np.nan)
    if descriptor.invisible is not None:
        inv = np.isin(pdg, descriptor.invisible) & (status == 1)
        sx = np.bincount(event_of[inv], weights=px[inv], minlength=n)
        sy = np.bincount(event_of[inv], weights=py[inv], minlength=n)
        met_mag, met_phi = np.hypot(sx, sy), np.arctan2(sy, sx)
    event = {}
    for name in chunk.extra['event_fields']:
        spec = descriptor.event[name]
        if spec == 'nominal':
            event[name] = np.array([w for w, _, _ in events], float)
        else:
            key = spec['lhe_weight_id']
            missing = [i for i, (_, _, named) in enumerate(events) if key not in named]
            if missing:
                raise ValueError(f'LHE event {chunk.entry_start + missing[0]} has no weight {key!r}')
            event[name] = np.array([named[key] for _, _, named in events], float)
    return View(np.arange(chunk.entry_start, chunk.entry_start + n), collections, met_mag, met_phi, event)
