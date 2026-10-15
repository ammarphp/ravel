"""Streaming raw-column skims with pinned custody and reference-only manifests.

Reserved columns preserve the source entry/file identity and nominal weight product.
Replaying uses original raw weights, so the stored product is never applied twice.
"""
from pathlib import Path
import hashlib
import json
import math

import awkward as ak
import numpy as np

RESERVED = ('ravel_event_number', 'ravel_source_entry', 'ravel_file_index', 'ravel_weight')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def declared_branches(descriptor, *, required_only=False):
    """Raw branches of the descriptor; ``required_only`` leaves out optional collections and fields."""
    if not required_only:
        return sorted({spec['branch'] for _, spec, _ in
                       descriptor._specs(list(descriptor.collections), list(descriptor.event)) if 'branch' in spec})
    collections = [c for c in descriptor.collections if not descriptor.doc['collections'][c].get('optional')]
    # An empty file population makes every optional field absent, so only required leaves remain.
    return sorted({spec['branch'] for _, spec, _ in
                   descriptor._specs(collections, list(descriptor.event), frozenset(), None) if 'branch' in spec})


def _needed(descriptor, collections, event_fields, available, variation=None):
    """Branches a read needs: required fields always, optional ones only where ``available`` holds them."""
    collections = descriptor._present_collections(list(collections), available)
    return {descriptor._branch(spec['branch'], variation, available) for _, spec, _ in
            descriptor._specs(collections, event_fields, available, variation) if 'branch' in spec}


class InputDescriptor:
    """Keep the format descriptor unchanged while admitting custody JSON as input.

    Frontend validation uses check_file before the engine dispatches skim reading.
    Raw ROOT/LHE inputs retain their existing reader and validation behavior.
    """
    def __init__(self, descriptor):
        self.descriptor = descriptor

    def __getattr__(self, name):
        return getattr(self.descriptor, name)

    def check_file(self, path, *, variations=(), collections=None, event_fields=None):
        if not str(path).startswith('root://') and Path(path).suffix.lower() == '.json':
            from types import SimpleNamespace
            plan = SimpleNamespace(descriptor=self.descriptor, source_collections=(list(self.collections)
                                   if collections is None else collections), event_fields=(list(self.event)
                                   if event_fields is None else event_fields), variations=variations, skim=None)
            checked, _ = _manifest(path, plan)
            return {'entries': checked['entries_out'], 'input_kind': 'columnar-skim', 'sha256': digest(path)}
        return self.descriptor.check_file(path, variations=variations, collections=collections, event_fields=event_fields)


def compile_skim(spec, descriptor, regions, steps):
    if not isinstance(spec, dict) or set(spec) != {'region', 'branches', 'format'}:
        raise ValueError('skim needs region, branches and format')
    if descriptor.format != 'root':
        raise ValueError('raw-column skims require a ROOT format descriptor')
    if spec['region'] not in regions:
        raise ValueError('skim region must be a declared region (an empty-cut region is a pre-selection)')
    if spec['format'] not in ('root', 'parquet'):
        raise ValueError('skim format must be root or parquet')
    allowed = declared_branches(descriptor)
    branches = spec['branches']
    if isinstance(branches, str) and branches == 'all-declared':
        # Optional descriptor fields may be absent from a source; the export carries the required ones.
        branches = declared_branches(descriptor, required_only=True)
    if (not isinstance(branches, list) or not branches or any(not isinstance(b, str) for b in branches)
            or len(set(branches)) != len(branches) or set(branches) - set(allowed)):
        raise ValueError('skim branches must be unique declared raw branch names or all-declared')
    if set(allowed) & set(RESERVED):
        raise ValueError('descriptor uses reserved skim identity/weight columns')
    if any(s.kind == 'efficiency' and s.spec['application'] == 'enumerate' for s in steps):
        raise ValueError('skim refuses enumerated efficiency replicas; declare a physical-event selection')
    return {**spec, 'branches': sorted(branches)}


class _Sum:
    """Streaming expansion, retaining cancellation terms for a final fsum."""
    def __init__(self):
        self.parts = []

    def add(self, values):
        for x in values:
            x = float(x)
            if not math.isfinite(x):
                raise ValueError('skim weight product must be finite')
            parts = []
            for y in self.parts:
                if abs(x) < abs(y):
                    x, y = y, x
                hi = x + y
                lo = y - (hi - x)
                if lo:
                    parts.append(lo)
                x = hi
            self.parts = parts + [x]

    def value(self):
        return math.fsum(self.parts)


class Writer:
    """One bounded-memory data file and one custody JSON per partition."""
    def __init__(self, directory, plan):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=False)
        self.plan = plan
        self.path = self.directory / ('events.' + plan.skim['format'])
        self.handle = None
        self.tree = None
        self.entries_in = self.entries_out = 0
        self.sum_in, self.sum_out = _Sum(), _Sum()
        # Import before reading a population, so a missing optional runtime fails early.
        if plan.skim['format'] == 'parquet':
            import pyarrow.parquet  # noqa: F401

    def append(self, chunk, view, mask, weight, file_index):
        number = np.asarray(chunk.extra.get('event_numbers', view.event.get('number', view.entries)))
        if not np.all(np.isfinite(number)) or not np.all(number == number.astype(np.int64)):
            raise ValueError('skim event number must be a finite int64 identifier')
        arrays = {name: chunk.arrays[name][mask] for name in self.plan.skim['branches']}
        arrays.update(ravel_event_number=number.astype(np.int64)[mask],
                      ravel_source_entry=np.asarray(view.entries, np.int64)[mask],
                      ravel_file_index=np.full(int(mask.sum()), file_index, np.int64),
                      ravel_weight=np.asarray(weight, np.float64)[mask])
        arrays = {k: ak.Array(v) for k, v in arrays.items()}
        self.entries_in += len(mask)
        self.entries_out += int(mask.sum())
        self.sum_in.add(weight)
        self.sum_out.add(np.asarray(weight)[mask])
        if self.plan.skim['format'] == 'root':
            import uproot
            if self.handle is None:
                self.handle = uproot.recreate(self.path)
                self.handle.mktree(self.plan.descriptor.doc['tree'], {k: v.type for k, v in arrays.items()})
                self.tree = self.handle[self.plan.descriptor.doc['tree']]
            if mask.any():
                self.tree.extend(arrays)
        else:
            import pyarrow.parquet as pq
            table = ak.to_arrow_table(ak.Array(arrays), extensionarray=False)
            if self.handle is None:
                self.handle = pq.ParquetWriter(self.path, table.schema)
            if mask.any():
                self.handle.write_table(table)

    def close(self):
        if self.handle is not None:
            self.handle.close()
            self.handle = None

    def finish(self, inputs):
        self.close()
        if not self.path.exists():
            raise ValueError('skim needs at least one input chunk to establish the output schema')
        record = {'schema_version': 1, 'kind': 'columnar-skim-partition',
                  'recipe_sha256': self.plan.recipe_sha256, 'plan_identity': self.plan.identity,
                  'descriptor_sha256': self.plan.descriptor.sha256,
                  'region': self.plan.skim['region'], 'format': self.plan.skim['format'],
                  'tree': self.plan.descriptor.doc['tree'], 'branches': self.plan.skim['branches'],
                  'reserved_columns': list(RESERVED), 'inputs': inputs,
                  'entries_in': self.entries_in, 'entries_out': self.entries_out,
                  'sum_weights_in': self.sum_in.value(), 'sum_weights_out': self.sum_out.value(),
                  'data': {'path': self.path.name, 'sha256': digest(self.path), 'size_bytes': self.path.stat().st_size}}
        path = self.directory / 'custody.json'
        with path.open('x') as stream:
            json.dump(record, stream, indent=2, allow_nan=False)
            stream.write('\n')
        return {'path': str(path), 'sha256': digest(path), 'size_bytes': path.stat().st_size}


def _data_chunks(record, branches, step):
    path = record['data']['path']
    if record['format'] == 'root':
        import uproot
        with uproot.open(path) as source:
            tree = source[record['tree']]
            if tree.num_entries == 0:
                arrays = tree.arrays(branches, entry_start=0, entry_stop=0, library='ak')
                yield {b: arrays[b] for b in branches}
            for start in range(0, int(tree.num_entries), step):
                arrays = tree.arrays(branches, entry_start=start, entry_stop=start + step, library='ak')
                yield {b: arrays[b] for b in branches}
    elif record['format'] == 'parquet':
        import pyarrow.parquet as pq
        source = pq.ParquetFile(path)
        if source.metadata.num_rows == 0:
            arrays = ak.from_arrow(source.read(columns=branches))
            yield {b: arrays[b] for b in branches}
        for batch in source.iter_batches(batch_size=step, columns=branches):
            arrays = ak.from_arrow(batch)
            yield {b: arrays[b] for b in branches}
    else:
        raise ValueError('unknown skim data format')


def validate_partition(pin, *, expected_inputs=None):
    """Verify custody bytes, data bytes, source ranges and independently read totals."""
    path = Path(pin['path'])
    if digest(path) != pin['sha256']:
        raise ValueError('skim custody checksum differs')
    record = json.loads(path.read_bytes())
    if record.get('schema_version') != 1 or record.get('kind') != 'columnar-skim-partition':
        raise ValueError('invalid skim custody kind/schema')
    for key in ('recipe_sha256', 'plan_identity', 'descriptor_sha256'):
        value = record.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('skim custody needs recipe, plan and descriptor hashes')
    if record.get('reserved_columns') != list(RESERVED):
        raise ValueError('skim custody reserved columns differ')
    for key in ('entries_in', 'entries_out'):
        if type(record.get(key)) is not int or record[key] < 0:
            raise ValueError('skim custody entries must be nonnegative integers')
    if record['entries_out'] > record['entries_in']:
        raise ValueError('skim custody has more outputs than inputs')
    for key in ('sum_weights_in', 'sum_weights_out'):
        if type(record.get(key)) not in (int, float) or not math.isfinite(record[key]):
            raise ValueError('skim custody sums must be finite')
    inputs = record.get('inputs')
    if not isinstance(inputs, list) or not inputs:
        raise ValueError('skim custody needs input pins')
    if sum(i['entry_stop'] - i['entry_start'] for i in inputs) != record['entries_in']:
        raise ValueError('skim custody input entry totals differ')
    if any(not (i.get('sha256') or i.get('source_checksum') or i.get('skim_manifest_sha256')) for i in inputs):
        raise ValueError('skim custody requires checksum pins for every input')
    if expected_inputs is not None and inputs != expected_inputs:
        raise ValueError('skim custody inputs differ from partition inputs')
    data = record['data']
    target = Path(data['path'])
    if not target.is_absolute():
        target = path.parent / target
    if not target.is_file() or digest(target) != data['sha256'] or target.stat().st_size != data['size_bytes']:
        raise ValueError('skim data checksum differs from custody')
    record['data']['path'] = str(target.resolve())
    count, total = 0, _Sum()
    ranges = {}
    for i in [r for i in inputs for r in i.get('source_ranges', [i])]:
        ranges.setdefault(i['file_index'], []).append((i['entry_start'], i['entry_stop']))
    last = {}
    for arrays in _data_chunks(record, list(RESERVED), 100_000):
        entries = ak.to_numpy(arrays['ravel_source_entry'])
        indices = ak.to_numpy(arrays['ravel_file_index'])
        if entries.dtype.kind not in 'iu' or indices.dtype.kind not in 'iu':
            raise ValueError('skim event identity must be integer')
        for index in np.unique(indices):
            selected = entries[indices == index]
            inside = np.zeros(len(selected), bool)
            for a, b in ranges.get(int(index), []):
                inside |= (selected >= a) & (selected < b)
            if not inside.all():
                raise ValueError('skim event identity is outside custody inputs')
            if (np.diff(selected) <= 0).any() or int(selected[0]) <= last.get(int(index), -1):
                raise ValueError('skim event identities duplicate or are unordered')
            last[int(index)] = int(selected[-1])
        count += len(entries)
        total.add(ak.to_numpy(arrays['ravel_weight']))
    if count != record['entries_out'] or total.value() != record['sum_weights_out']:
        raise ValueError('skim entry/weight totals differ from custody')
    return record


def merge(pins, *, expected_inputs=None):
    """Reference the original files; never concatenate/copy a skim population."""
    pins = list(pins)
    if not pins:
        raise ValueError('nothing to merge')
    if len({str(Path(p['path']).resolve()) for p in pins}) != len(pins):
        raise ValueError('duplicate skim partition')
    records = [validate_partition(p, expected_inputs=None if expected_inputs is None else expected_inputs[n])
               for n, p in enumerate(pins)]
    first = records[0]
    for r in records[1:]:
        if any(r[k] != first[k] for k in ('recipe_sha256', 'plan_identity', 'descriptor_sha256', 'region',
                                         'format', 'tree', 'branches', 'reserved_columns')):
            raise ValueError('skim partitions have different custody contracts')
    ranges, identities = {}, {}
    for r in records:
        for i in r['inputs']:
            checksum = i.get('sha256') or i.get('source_checksum')
            if i['path'] in identities and identities[i['path']] != checksum:
                raise ValueError('skim custody saw different source checksums')
            identities[i['path']] = checksum
            key = (i['path'], i['file_index'])
            for a, b in ranges.setdefault(key, []):
                if i['entry_start'] < b and a < i['entry_stop']:
                    raise ValueError('skim custody input ranges overlap')
            ranges[key].append((i['entry_start'], i['entry_stop']))
    return {'schema_version': 1, 'kind': 'columnar-skim-manifest',
            **{k: first[k] for k in ('recipe_sha256', 'plan_identity', 'descriptor_sha256', 'region', 'format',
                                     'tree', 'branches', 'reserved_columns')},
            'partitions': [{**p, 'data': r['data'], 'entries_in': r['entries_in'], 'entries_out': r['entries_out'],
                            'sum_weights_in': r['sum_weights_in'], 'sum_weights_out': r['sum_weights_out']}
                           for p, r in zip(pins, records)],
            'entries_in': sum(r['entries_in'] for r in records), 'entries_out': sum(r['entries_out'] for r in records),
            'sum_weights_in': math.fsum(r['sum_weights_in'] for r in records),
            'sum_weights_out': math.fsum(r['sum_weights_out'] for r in records)}


def _manifest(path, plan):
    document = json.loads(Path(path).read_bytes())
    if document.get('kind') == 'columnar-skim-partition':
        pins = [{'path': str(Path(path).resolve()), 'sha256': digest(path)}]
    elif document.get('kind') == 'columnar-skim-manifest':
        pins = document['partitions']
    else:
        raise ValueError('input JSON must be a skim custody or skim manifest')
    checked = merge(pins)
    if document.get('kind') == 'columnar-skim-manifest' and checked != document:
        raise ValueError('skim manifest differs from its partition custody')
    if checked['descriptor_sha256'] != plan.descriptor.sha256:
        raise ValueError('skim input descriptor differs from its custody')
    needed = _needed(plan.descriptor, plan.source_collections, plan.event_fields, frozenset(checked['branches']))
    if needed - set(checked['branches']):
        raise ValueError('skim is missing branches required by the later recipe')
    if plan.variations:
        raise ValueError('skim replay of branch variations requires explicitly retained variation columns')
    if plan.skim is not None:
        if set(plan.skim['branches']) - set(checked['branches']):
            raise ValueError('skim is missing branches required by the later export')
    return checked, checked['partitions']


def read_manifest(path, plan, step):
    """Validated skims as an input population; yield raw chunks and original identities."""
    from .formats import Chunk
    checked, pins = _manifest(path, plan)
    needed = _needed(plan.descriptor, plan.source_collections, plan.event_fields, frozenset(checked['branches']))
    if plan.skim is not None:
        needed.update(plan.skim['branches'])
    for pin in pins:
        record = {**checked, 'data': pin['data']}
        for arrays in _data_chunks(record, sorted(needed) + list(RESERVED), step):
            indices = ak.to_numpy(arrays['ravel_file_index'])
            if len(indices) == 0:
                data = {b: arrays[b] for b in needed}
                yield Chunk(0, 0, data, frozenset(data),
                            {'collections': plan.source_collections, 'event_fields': plan.event_fields,
                             'decoded_bytes_read': 0, 'columns_read': sorted(arrays),
                             'event_numbers': np.zeros(0, np.int64)}), np.zeros(0, np.int64), 0
                continue
            # Keep file identities separate for deterministic efficiency selection.
            boundaries = [0, *list(np.flatnonzero(np.diff(indices)) + 1), len(indices)]
            for start, stop in zip(boundaries, boundaries[1:]):
                if start == stop:
                    continue
                data = {b: arrays[b][start:stop] for b in needed}
                entries = ak.to_numpy(arrays['ravel_source_entry'][start:stop])
                yield Chunk(0, stop - start, data, frozenset(data),
                            {'collections': plan.source_collections, 'event_fields': plan.event_fields,
                             'decoded_bytes_read': sum(a[start:stop].nbytes for a in arrays.values()),
                             'columns_read': sorted(arrays),
                             'event_numbers': ak.to_numpy(arrays['ravel_event_number'][start:stop])}), entries, int(indices[start])


def source_chunks(path, plan, *, step, entry_start, entry_stop):
    """Read required analysis and export columns together, without a second event pass."""
    import uproot
    from .formats import Chunk
    descriptor = plan.descriptor
    event_fields = list(plan.event_fields)
    if 'number' in descriptor.event and 'number' not in event_fields:
        event_fields.append('number')
    with uproot.open(path) as source:
        tree = source[descriptor.doc['tree']]
        available = frozenset(b.name for b in tree.values(recursive=True))
        wanted = set(plan.skim['branches'])
        for variation in (None, *plan.variations):
            wanted |= _needed(descriptor, plan.source_collections, event_fields, available, variation)
        if wanted - available:
            raise ValueError('skim declared branches missing from the source tree')
        if entry_start == entry_stop:
            arrays = tree.arrays(sorted(wanted), entry_start=entry_start, entry_stop=entry_stop, library='ak')
            yield Chunk(entry_start, 0, {b: arrays[b] for b in wanted}, available,
                        {'collections': plan.source_collections, 'event_fields': event_fields})
        for start in range(entry_start, entry_stop, step):
            arrays = tree.arrays(sorted(wanted), entry_start=start, entry_stop=min(start + step, entry_stop), library='ak')
            yield Chunk(start, len(arrays), {b: arrays[b] for b in wanted}, available,
                        {'collections': plan.source_collections, 'event_fields': event_fields})
