"""Format descriptors and chunked readers for detector-level and parton-level events.

A *format descriptor* is JSON data that says where each physics field lives in a file.
No branch name is written in code; RAVEL ships one descriptor, ``delphes``, for the
standard Delphes 3.5 tree, and any other ntuple layout is described by a supplied
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
        if 'fixed' in spec:
            if set(spec) != {'fixed', 'source'} or type(spec['fixed']) not in (int, float):
                raise ValueError(f'{label}: a fixed value needs a number and its source')
            _text(spec['source'], f'{label} source')
            return {'fixed': spec['fixed']}
        if set(spec) - {'branch', 'scale', 'reduce'} or 'branch' not in spec:
            raise ValueError(f'{label}: a branch field has branch and optional scale and reduce')
        scale = spec.get('scale', 1.0)
        if type(scale) not in (int, float) or not np.isfinite(scale) or scale == 0:
            raise ValueError(f'{label}: scale must be a nonzero number')
        reduce = spec.get('reduce')
        if reduce not in (None, 'first') or (reduce and jagged):
            raise ValueError(f'{label}: reduce "first" applies to one-value-per-event fields only')
        return {'branch': _text(spec['branch'], label), 'scale': float(scale), 'reduce': reduce}

    def _validate_root(self):
        doc = self.doc
        allowed = {'schema_version', 'kind', 'name', 'source', 'format', 'tree', 'collections', 'met', 'event', 'variations'}
        if set(doc) - allowed or 'tree' not in doc or 'collections' not in doc:
            raise ValueError(f'a root descriptor accepts only {sorted(allowed)} and needs tree and collections')
        _text(doc['tree'], 'tree')
        self.collections = {}
        for name, spec in doc['collections'].items():
            _text(name, 'collection name')
            if not isinstance(spec, dict) or set(spec) != {'fields'} or not isinstance(spec['fields'], dict):
                raise ValueError(f'collection {name!r} needs fields')
            fields = {}
            for key, value in spec['fields'].items():
                if not _IDENT.match(key):
                    raise ValueError(f'collection {name!r}: field name {key!r} must be lower-case letters, digits and _')
                fields[key] = self._field(value, f'{name}.{key}', jagged=True)
            missing = {'pt', 'eta', 'phi', 'mass'} - set(fields)
            if missing:
                raise ValueError(f'collection {name!r} must declare {sorted(missing)} (a fixed mass needs its source)')
            if all('fixed' in f for f in fields.values()):
                raise ValueError(f'collection {name!r} needs at least one branch')
            self.collections[name] = fields
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

    def _specs(self, collections, event_fields):
        for c in collections:
            if c not in self.collections:
                raise ValueError(f'collection {c!r} is not in the format descriptor ({sorted(self.collections)})')
            for key, spec in self.collections[c].items():
                yield f'{c}.{key}', spec, True
        if self.met is not None:
            for key, spec in self.met.items():
                yield f'met.{key}', spec, False
        for f in event_fields:
            if f not in self.event:
                raise ValueError(f'event field {f!r} is not in the format descriptor ({sorted(self.event)})')
            yield f'event.{f}', self.event[f], False

    # ------------------------------------------------------------ files
    def check_file(self, path, *, variations=(), collections=None, event_fields=None):
        """Validate the declared branches against the file; return a typed report."""
        if self.format == 'lhe':
            return _lhe_report(path)
        import uproot
        collections = list(self.collections) if collections is None else list(collections)
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
            report = {'tree': self.doc['tree'], 'entries': int(tree.num_entries), 'branches': {}, 'variations': {}}
            for variation in (None, *variations):
                substitutions = {}
                for label, spec, jagged in self._specs(collections, event_fields):
                    if 'fixed' in spec:
                        continue
                    nominal = spec['branch']
                    branch = self._branch(nominal, variation, available)
                    if branch not in names:
                        raise ValueError(f'{label}: branch {branch!r} is not in tree {self.doc["tree"]!r} of {path}')
                    typename = names[branch].typename
                    is_jagged = '[]' in typename or 'vector<' in typename
                    if not re.search(r'(float|double|int|bool|short|long|char)', typename.lower()):
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

    def read(self, path, *, collections, event_fields, step, entry_start=None, entry_stop=None, variations=()):
        """Yield chunks with every branch needed for the nominal pass and the variations."""
        if type(step) is not int or step < 1:
            raise ValueError('chunk size must be a positive integer')
        if self.format == 'lhe':
            yield from _lhe_chunks(self, path, collections, event_fields, step, entry_start, entry_stop)
            return
        import uproot
        with uproot.open(path) as f:
            tree = f[self.doc['tree']]
            available = frozenset(b.name for b in tree.values(recursive=True))
            wanted = set()
            for variation in (None, *variations):
                for _, spec, _ in self._specs(collections, event_fields):
                    if 'branch' in spec:
                        wanted.add(self._branch(spec['branch'], variation, available))
            wanted = sorted(wanted)
            start = 0 if entry_start is None else int(entry_start)
            stop = tree.num_entries if entry_stop is None else min(int(entry_stop), tree.num_entries)
            if not 0 <= start <= stop:
                raise ValueError(f'entry range {start}-{stop} is outside the tree of {tree.num_entries} entries')
            if start == stop or not wanted:
                return
            for arrays, report in tree.iterate(filter_name=wanted, step_size=step, entry_start=start,
                                               entry_stop=stop, library='ak', report=True):
                data = {}
                for name in wanted:
                    key = name if name in arrays.fields else next((k for k in arrays.fields if k.endswith('/' + name)), None)
                    if key is None:
                        raise ValueError(f'branch {name!r} was not returned by the reader')
                    data[name] = arrays[key]
                yield Chunk(int(report.tree_entry_start), int(report.tree_entry_stop - report.tree_entry_start), data,
                            available, {'collections': list(collections), 'event_fields': list(event_fields)})

    def view(self, chunk, variation=None):
        if self.format == 'lhe':
            return _lhe_view(self, chunk)
        if variation is not None and variation not in self.variations:
            raise ValueError(f'variation {variation!r} is not in the format descriptor')
        n = chunk.length

        def value(spec, *, like=None):
            if 'fixed' in spec:
                fixed = spec['fixed']
                if like is None:
                    return np.full(n, fixed, dtype=np.int64 if type(fixed) is int else float)
                return ak.ones_like(like, dtype=np.int64 if type(fixed) is int else np.float64) * fixed
            raw = chunk.arrays[self._branch(spec['branch'], variation, chunk.available)]
            if spec['reduce'] == 'first':
                padded = ak.fill_none(ak.pad_none(raw, 1, axis=1, clip=True), np.nan)
                raw = ak.to_numpy(padded[:, 0]).astype(float)
            elif like is None:
                raw = ak.to_numpy(raw)
            if spec['scale'] != 1.0:
                raw = raw * spec['scale']
            elif like is not None and not np.issubdtype(_dtype(raw), np.integer):
                raw = ak.values_astype(raw, np.float64)
            return raw

        collections = {}
        for ordinal, name in enumerate(chunk.extra.get('collections', [])):
            fields = self.collections[name]
            first = next(k for k, s in fields.items() if 'branch' in s)
            reference = chunk.arrays[self._branch(fields[first]['branch'], variation, chunk.available)]
            columns = {}
            for key, spec in fields.items():
                columns[key] = value(spec, like=reference)
            try:
                record = ak.zip(columns)
            except ValueError:
                raise ValueError(f'collection {name!r}: its field branches have different lengths in some event') from None
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
        event = {f: value(self.event[f]).astype(float) for f in chunk.extra.get('event_fields', [])}
        return View(np.arange(chunk.entry_start, chunk.entry_start + n), collections, met_mag, met_phi, event)


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
