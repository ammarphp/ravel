"""Pinned schema-driven tree-to-array export through the ordinary science worker.

Required readers are imported in the approved worker. All source rows, raw
values and positional order survive; shapes and output formats are supplied,
either inline or by the identifier of a packaged public-format layout template
(:func:`library_layout`).
"""
from copy import deepcopy
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import stat

from ravel.physics.ma5_pad import InputCapture
from ravel.physics.ma5_saf import _keys, _json, _identity

SCOPE = 'source_bound_tree_raw_array_delivery'
LIBRARY = Path(__file__).resolve().parents[1] / 'data' / 'columnar' / 'array_layouts'


class MissingArrayInput(ValueError):
    """A supplied export contract omitted a required input."""
    code = 'missing_input'

    def __init__(self, fields):
        self.fields = sorted(fields)
        super().__init__('missing array inputs: ' + ', '.join(self.fields))


def require(ok, message):
    if not ok:
        raise ValueError(message)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _closed(value, names, label):
    if type(value) is dict and set(names) - set(value):
        raise MissingArrayInput(set(names) - set(value))
    _keys(value, names, label)


def _text(value, label):
    require(type(value) is str and value.strip() == value and value and len(value.encode()) <= 4096,
            'bounded literal ' + label + ' required')
    return value


def validate(task):
    _closed(task, ('input', 'input_sha256'), 'array task')
    _text(task['input'], 'array request pathname')
    require(type(task['input_sha256']) is str and len(task['input_sha256']) == 64 and
            all(c in '0123456789abcdef' for c in task['input_sha256']), 'literal request SHA256 required')


def _relative(value):
    _text(value, 'output destination')
    path = Path(value)
    require(not path.is_absolute() and value == path.as_posix() and
            all(part not in ('', '.', '..') for part in value.split('/')),
            'canonical relative output destination required')
    require(path.parts[0] not in ('completion.json', 'delivery.json', 'filename-handoff.json'),
            'array destination collides with delivery metadata')
    return value


def _numeric(value):
    import math
    require(type(value) in (int, float) and math.isfinite(value), 'finite real supplied number required')
    # The output contract is float64; constant and padding conversion must also
    # be exact, rather than silently rounding an integer before conversion.
    require(float(value) == value, 'supplied number not representable as float64')


def layout_names():
    """Identifiers of the packaged array layout templates."""
    return sorted(p.stem for p in LIBRARY.glob('*.json'))


def library_layout(name):
    """One packaged layout by identifier, validated like a supplied layout."""
    import re
    require(type(name) is str and re.fullmatch('[a-z0-9][a-z0-9._-]{0,95}', name), 'layout library identifier required')
    path = LIBRARY / (name + '.json')
    require(path.is_file(), 'no packaged array layout named ' + repr(name) + '; available: ' + ', '.join(layout_names()))
    doc = _json(path.read_bytes())
    _keys(doc, ('schema_version', 'kind', 'name', 'source', 'layout'), 'packaged array layout')
    require(doc['schema_version'] == 1 and doc['kind'] == 'tree-array-layout' and doc['name'] == name and
            type(doc['source']) is str and doc['source'].strip(), 'packaged array layout identity required')
    return validate_layout(doc['layout'])


def validate_layout(value):
    if type(value) is str: value = library_layout(value)
    _closed(value, ('dtype', 'columns', 'jagged_groups', 'padding', 'overflow'), 'array layout')
    require(value['dtype'] == 'float64', 'supported float64 output dtype required')
    require(value['overflow'] in ('truncate', 'refuse'), 'explicit object overflow policy required')
    if value['padding'] is not None: _numeric(value['padding'])
    require(type(value['columns']) is list and 1 <= len(value['columns']) <= 4096, 'bounded supplied column population required')
    names, jagged, scalars = set(), set(), set()
    for column in value['columns']:
        if type(column) is not dict or 'kind' not in column: raise MissingArrayInput(['column.kind'])
        kind = column['kind']
        require(kind in ('scalar', 'jagged', 'constant'), 'supported column kind required')
        fields = ('name', 'kind', 'unit', 'value') if kind == 'constant' else ('name', 'kind', 'unit', 'branch')
        if kind == 'jagged': fields += ('index',)
        _closed(column, fields, 'array column')
        name = _text(column['name'], 'column name'); _text(column['unit'], 'source unit')
        require(name not in names, 'unique column names required'); names.add(name)
        if kind == 'constant':
            if column['value'] is not None: _numeric(column['value'])
        else:
            branch = _text(column['branch'], 'branch name')
            (jagged if kind == 'jagged' else scalars).add(branch)
            if kind == 'jagged':
                require(type(column['index']) is int and 0 <= column['index'] < 4096, 'bounded positional object index required')
    require(not jagged & scalars, 'one source shape per branch required')
    groups = value['jagged_groups']
    require(type(groups) is list, 'explicit corresponding jagged groups required')
    grouped = []
    for group in groups:
        require(type(group) is list and group and all(type(b) is str for b in group), 'nonempty jagged branch group required')
        grouped.extend(group)
    require(len(grouped) == len(set(grouped)) and set(grouped) == jagged,
            'each jagged branch must belong to exactly one corresponding-field group')
    require(jagged or scalars, 'at least one supplied source branch required')
    return deepcopy(value)


def _branches(value):
    return list(dict.fromkeys(c['branch'] for c in value['columns'] if c['kind'] != 'constant'))


def export_contract(d):
    _closed(d, ('schema_version', 'study_id', 'parameter_grid', 'sources', 'datasets', 'layout',
                'source_premises', 'max_seconds', 'max_ram_mib'), 'array export request')
    require(type(d['schema_version']) is int and d['schema_version'] == 2, 'supplied array export schema2 required')
    _text(d['study_id'], 'supplied study label')
    for k, high in (('max_seconds', 86400), ('max_ram_mib', 65536)):
        require(type(d[k]) is int and 1 <= d[k] <= high, 'explicit finite ' + k + ' required')
    grid = d['parameter_grid']
    _closed(grid, ('axes', 'points'), 'supplied parameter grid')
    require(type(grid['axes']) is list and 1 <= len(grid['axes']) <= 32, 'bounded supplied grid axes required')
    axis_names = []
    for axis in grid['axes']:
        _closed(axis, ('name', 'unit'), 'parameter axis')
        axis_names.append(_text(axis['name'], 'parameter axis')); _text(axis['unit'], 'parameter unit')
    require(len(axis_names) == len(set(axis_names)), 'unique parameter axes required')
    require(type(grid['points']) is list and 1 <= len(grid['points']) <= 100000, 'finite supplied parameter points required')
    for point in grid['points']:
        _closed(point, axis_names, 'parameter point')
        for v in point.values(): _numeric(v)
    require(len({encode(v) for v in grid['points']}) == len(grid['points']), 'unique supplied parameter points required')
    require(type(d['sources']) is list and 1 <= len(d['sources']) <= 256, 'supplied source commitments required')
    _closed(d['source_premises'], ('units', 'ordering', 'weight_semantics'), 'source premises')
    for name, value in d['source_premises'].items(): _text(value, name)
    d = {**d, 'layout': validate_layout(d['layout'])}
    require(type(d['datasets']) is list and 1 <= len(d['datasets']) <= 256, 'nonempty supplied dataset population required')
    ids, destinations = set(), set()
    for row in d['datasets']:
        _closed(row, ('id', 'pin', 'tree', 'destination', 'format', 'consumer'), 'supplied dataset')
        name = _text(row['id'], 'dataset identifier'); _text(row['tree'], 'tree name')
        destination = _relative(row['destination'])
        require(row['format'] in ('npy', 'npz') and Path(destination).suffix == '.' + row['format'],
                'explicit supported output format and matching extension required')
        if row['consumer'] is not None: _text(row['consumer'], 'consumer association')
        require(name not in ids and destination not in destinations, 'distinct dataset identifiers and destinations required')
        require(not any(Path(destination).is_relative_to(Path(v)) or Path(v).is_relative_to(Path(destination)) for v in destinations),
                'array file/directory destinations overlap')
        ids.add(name); destinations.add(destination)
    return deepcopy(d)


def _load(task, base):
    validate(task)
    c = InputCapture(); path, raw = c.read(task['input'], base, task['input_sha256'])
    d = export_contract(_json(raw))
    for source in d['sources']: c.pin(source, path.parent)
    paths = [c.stream_pin(row['pin'], path.parent) for row in d['datasets']]
    require(len(paths) == len(set(paths)) and len({c.streams[p][0][0][:2] for p in paths}) == len(paths),
            'distinct supplied input files required; aliases refused')
    census = [{'position': i, 'file_id': row['id'], 'source': deepcopy(row['pin'])} for i, row in enumerate(d['datasets'])]
    return path, d, paths, census, c


def inputs(task, base):
    _, _, _, _, c = _load(task, base); c.finish()
    return [*c.files, *c.streams, Path(__file__).absolute(),
            Path(__file__).with_name('ma5_pad.py'), Path(__file__).with_name('ma5_saf.py')]


def execution_seconds(task, base):
    _, d, _, _, c = _load(task, base); c.finish(); return d['max_seconds']


def context(task, base):
    _, d, _, census, c = _load(task, base); c.finish()
    return {'kind': 'tree-array-context', 'status_scope': SCOPE, 'file_census': census,
            'export_contract': d, 'columns': [v['name'] for v in d['layout']['columns']],
            'branches': _branches(d['layout']), 'execution_authorized': False,
            'physics_validated': False, 'runtime_required': ['numpy', 'awkward', 'uproot'],
            'row_selection': 'all actual tree entries; no inferred summary count'}

def _runtime():
    try:
        return tuple(importlib.import_module(name) for name in ('numpy', 'awkward', 'uproot'))
    except ImportError as exc:
        raise ValueError('Array export requires NumPy, Awkward and uproot from the full Python installation') from exc


def _vector(value, np):
    require(not np.ma.isMaskedArray(value) or not np.ma.getmaskarray(value).any(), 'source null scalar cannot stand for padding')
    a = np.asarray(value)
    require(a.ndim == 1 and a.dtype.kind in 'biuf', 'one real numeric value per scalar/flattened entry required')
    with np.errstate(over='ignore', invalid='ignore'):
        b = a.astype(np.float64)
        require(not np.isinf(b).any(), 'finite-or-source-NaN float64 values required')
        finite = ~np.isnan(b)
        # Integer cast-back can saturate at int64/uint64 extrema. Python's
        # float/integer equality compares the exact original integer instead.
        restored = b[finite].astype(object) if a.dtype.kind in 'iu' else b[finite].astype(a.dtype)
        original = a[finite].astype(object) if a.dtype.kind in 'iu' else a[finite]
        require(np.array_equal(restored, original), 'source value not representable as float64')
    return b


def convert(branches, count, *, np, ak, max_ram_mib, layout):
    """Vectorized source conversion governed entirely by the supplied layout."""
    value = validate_layout(layout)
    require(type(count) is int and count >= 0, 'actual tree entry count required')
    requested = _branches(value)
    require(set(branches.fields if hasattr(branches, 'fields') else branches) == set(requested),
            'complete exact requested branch population required')
    width = len(value['columns'])
    require(type(max_ram_mib) is int and max_ram_mib > 0 and count * width * 8 <= max_ram_mib * 1024**2,
            'complete array alone exceeds declared memory budget; no truncation')
    arr = np.empty((count, width), dtype=np.float64)
    sizes, matrices, truncated = {}, {}, {}
    pad_value = np.nan if value['padding'] is None else value['padding']
    for group in value['jagged_groups']:
        lengths = None
        for name in group:
            column = branches[name]
            require(len(column) == count, 'branch does not preserve all tree entries: ' + name)
            lengths_here = _vector(ak.to_numpy(ak.num(column, axis=1)), np)
            require(len(lengths_here) == count and (lengths is None or np.array_equal(lengths_here, lengths)),
                    'corresponding jagged field lengths differ: ' + name)
            lengths = lengths_here; sizes[name] = lengths_here
            original = ak.flatten(column, axis=1)
            require(not bool(ak.any(ak.is_none(original, axis=0))), 'source null item cannot stand for padding')
            _vector(ak.to_numpy(original), np)
        # Corresponding fields share an object domain even when only some
        # coordinates are requested at its highest supplied positional index.
        slots = 1 + max(c['index'] for c in value['columns'] if c['kind'] == 'jagged' and c['branch'] in group)
        for name in group:
            if value['overflow'] == 'refuse':
                require(not np.any(sizes[name] > slots), 'source object population exceeds supplied shape: ' + name)
            truncated[name] = int(np.maximum(sizes[name] - slots, 0).sum())
            matrix = ak.to_numpy(ak.fill_none(ak.pad_none(branches[name], slots, axis=1, clip=True), pad_value))
            require(matrix.shape == (count, slots), 'complete padded field matrix required')
            matrices[name] = matrix
    padding_counts, constant_counts, source_nan = [], [], []
    for target, column in enumerate(value['columns']):
        kind = column['kind']; padding = constant = 0
        if kind == 'constant':
            scalar = np.nan if column['value'] is None else column['value']
            arr[:, target] = scalar
            constant = count if column['value'] is None else 0
        elif kind == 'scalar':
            values = _vector(ak.to_numpy(branches[column['branch']]), np)
            require(len(values) == count, 'scalar branch does not preserve all tree entries: ' + column['branch'])
            arr[:, target] = values
        else:
            name, index = column['branch'], column['index']
            arr[:, target] = _vector(matrices[name][:, index], np)
            padding = int(np.count_nonzero(sizes[name] <= index))
        padding_counts.append(padding); constant_counts.append(constant)
        source_nan.append(int(np.isnan(arr[:, target]).sum()) - constant - (padding if value['padding'] is None else 0))
    return arr, {'shape': [count, width], 'dtype': str(arr.dtype),
                 'nan_counts': [int(x) for x in np.isnan(arr).sum(axis=0)],
                 'padding_counts': padding_counts,
                 'padding_nan_counts': padding_counts if value['padding'] is None else [0] * width,
                 'constant_nan_counts': constant_counts, 'source_nan_counts': source_nan,
                 'truncated_objects': truncated}


def _read_tree(path, admitted, *, np, ak, uproot, max_ram_mib, tree, layout):
    # Descriptor authentication keeps the admitted pathname from authorizing a
    # substituted leaf, including a FIFO or symlink.
    require(_identity(path.lstat()) == admitted, 'input changed before ROOT reader open')
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        require(_identity(os.fstat(stream.fileno())) == admitted, 'ROOT descriptor differs from admitted file')
        with uproot.open(stream) as root:
            selected_tree = root[tree]
            count = selected_tree.num_entries
            require(type(count) is int and count >= 0, 'actual tree entry count required')
            require(count * len(layout['columns']) * 8 <= max_ram_mib * 1024**2,
                    'complete array alone exceeds declared memory budget; no truncation')
            branches = selected_tree.arrays(_branches(layout), library='ak')
            arr, metadata = convert(branches, count, np=np, ak=ak, max_ram_mib=max_ram_mib, layout=layout)
        require(_identity(os.fstat(stream.fileno())) == admitted and _identity(path.lstat()) == admitted,
                'ROOT input identity changed during conversion')
    return arr, metadata


def _dir_identity(path):
    s = path.lstat(); require(stat.S_ISDIR(s.st_mode), 'ordinary output directory required')
    return [s.st_dev, s.st_ino, s.st_mode]


def _pin(path):
    c = InputCapture(); sha = c._stream(path, False)[1]
    return {'path': str(path), 'sha256': sha, 'identity': list(_identity(path.lstat()))}


def _write(path, raw):
    expected = hashlib.sha256(raw).hexdigest()
    with path.open('xb') as f: f.write(raw)
    p = _pin(path); require(p['sha256'] == expected, 'published bytes differ from intended serialization')
    return p


def _check_pin(pin):
    path = Path(pin['path']); c = InputCapture()
    fact = c._stream(path, False)
    require(list(fact[0]) == pin['identity'] and fact[1] == pin['sha256'], 'ending file content/identity changed')


def _census(root):
    require(root.is_absolute() and '..' not in root.parts, 'canonical output root required')
    files, dirs = [], {}
    for parent in (*reversed(root.parents), root): _dir_identity(parent)
    for directory, child_dirs, child_files in os.walk(root, followlinks=False):
        p = Path(directory); dirs[str(p)] = _dir_identity(p)
        for name in child_dirs: _dir_identity(p / name)
        for name in child_files:
            leaf = p / name
            require(stat.S_ISREG(leaf.lstat().st_mode), 'ordinary generated member required')
            files.append(leaf.relative_to(root).as_posix())
    return sorted(files), dirs


def finalize(result, destination, *, common=None):
    """Revalidate the whole committed delivery after ordinary publication."""
    root = Path(destination).absolute(); cp = result['commitment']
    _keys(cp, ('path', 'sha256', 'identity'), 'canonical completion pin')
    require(cp['path'] == str(root / 'completion.json'), 'canonical completion required')
    _check_pin(cp)
    raw = Path(cp['path']).read_bytes()
    # Authenticate the buffer that is parsed, not a separate pathname read.
    require(hashlib.sha256(raw).hexdigest() == cp['sha256'] and len(raw) == cp['identity'][3],
            'parsed completion bytes differ from original commitment')
    _check_pin(cp)
    commitment = _json(raw)
    _keys(commitment, ('result_sha256', 'artifacts', 'inputs', 'ancestors', 'members', 'directories'),
          'complete original delivery commitment')
    require(type(result['input_pins']) is list and result['input_pins'], 'complete supplied input pins required')
    request_pin = result['input_pins'][0]
    task = {'input': request_pin['path'], 'input_sha256': request_pin['sha256']}
    _, d, _, expected_census, capture = _load(task, root.parent)
    capture.finish()
    expected_inputs = [_pin(path) for path in [*capture.files, *capture.streams]]
    require(expected_inputs == result['input_pins'] == commitment['inputs'], 'complete supplied input roster required')
    require(result['export_contract'] == d, 'delivered export contract differs from supplied request')
    require(result['file_census'] == expected_census, 'supplied dataset census changed')
    require(all(result[k] == v for k, v in d['source_premises'].items()), 'supplied source premises changed')
    expected_artifacts = [row['destination'] for row in d['datasets']] + ['filename-handoff.json', 'delivery.json']
    expected_members = sorted([*expected_artifacts, 'completion.json'])
    require(commitment['members'] == expected_members, 'complete supplied member roster required')
    require(type(commitment['artifacts']) is list and
            [pin['path'] for pin in commitment['artifacts']] == [str(root / name) for name in expected_artifacts],
            'all ordered supplied artifact pins required')
    require(type(result['arrays']) is list and len(result['arrays']) == len(d['datasets']), 'complete supplied array population required')
    for index, (row, supplied) in enumerate(zip(result['arrays'], d['datasets'])):
        require(row['file_id'] == supplied['id'] and row['source'] == supplied['pin'] and
                row['format'] == supplied['format'] and row['artifact'] == commitment['artifacts'][index] and
                row['shape'][1] == len(d['layout']['columns']) and row['dtype'] == d['layout']['dtype'],
                'supplied array correspondence changed')
    require(result['columns'] == [v['name'] for v in d['layout']['columns']] and
            result['study_id'] == d['study_id'] and result['parameter_grid'] == d['parameter_grid'],
            'supplied columns and study metadata changed')
    expected_handoff = _handoff(d, result['arrays'])
    require(result['filename_handoff'] == expected_handoff, 'supplied filename associations changed')
    expected_dirs = {str(root)}
    for name in expected_artifacts:
        parent = (root / name).parent
        expected_dirs.add(str(parent))
        expected_dirs.update(str(p) for p in parent.parents if p.is_relative_to(root))
    require(set(commitment['directories']) == expected_dirs, 'complete supplied output directories required')
    expected_ancestors = {str(parent) for pin in commitment['inputs'] for parent in Path(pin['path']).parents}
    require(set(commitment['ancestors']) == expected_ancestors, 'complete original input ancestor roster required')
    stripped = {k: v for k, v in result.items() if k != 'commitment'}
    require(hashlib.sha256(encode(stripped)).hexdigest() == commitment['result_sha256'], 'live result differs from committed intended result')
    files, dirs = _census(root)
    require(files == commitment['members'] and dirs == commitment['directories'], 'complete generated membership or directory identity changed')
    for pin in commitment['artifacts'] + commitment['inputs']: _check_pin(pin)
    for path, identity in commitment['ancestors'].items():
        require(_dir_identity(Path(path)) == identity, 'original ancestor identity changed')
    require(_json((root / 'delivery.json').read_bytes()) == stripped, 'durable returned delivery differs')
    if common is not None:
        common = Path(common).absolute()
        require(_json((common / 'result.json').read_bytes()) == result, 'ordinary result differs from complete delivery')
        report = _report(result)
        require((common / 'tree-array-report.json').read_bytes() == encode(report), 'ordinary report differs from intended full table')
    # Inventory after every admitted descriptor read, not before the last read.
    _check_pin(cp)
    files, dirs = _census(root)
    require(files == commitment['members'] and dirs == commitment['directories'], 'ending complete generated membership changed')
    for pin in commitment['artifacts'] + commitment['inputs']:
        require(list(_identity(Path(pin['path']).lstat())) == pin['identity'], 'ending leaf identity changed')
    for path, identity in commitment['ancestors'].items():
        require(_dir_identity(Path(path)) == identity, 'ending original ancestor changed')


def _handoff(d, rows):
    return [{'producer': supplied['destination'], 'consumer': supplied['consumer'], 'artifact': row['artifact']}
            for supplied, row in zip(d['datasets'], rows)]


def run(task, base, output):
    _, d, paths, census, c = _load(task, base)
    np, ak, uproot = _runtime()
    out = Path(output).absolute()
    require('..' not in out.parts and not out.exists() and not any(p.is_symlink() for p in (out, *out.parents)), 'fresh canonical output destination required')
    require(not any(p.is_relative_to(out) or out.is_relative_to(p) for p in [*c.files, *c.streams]), 'generated output may not overlap supplied inputs')
    original = [_pin(path) for path in [*c.files, *c.streams]]
    ancestors = {str(p): _dir_identity(p) for path in [*c.files, *c.streams] for p in path.parents}
    c.finish()
    out.mkdir(parents=True)
    root_identity = _dir_identity(out)
    artifacts, rows = [], []
    for path, supplied in zip(paths, d['datasets']):
        arr, metadata = _read_tree(path, c.streams[path][0][0], np=np, ak=ak, uproot=uproot,
                                  max_ram_mib=d['max_ram_mib'], tree=supplied['tree'], layout=d['layout'])
        buffer = io.BytesIO()
        if supplied['format'] == 'npy': np.save(buffer, arr, allow_pickle=False)
        else: np.savez(buffer, array=arr)
        destination = out / supplied['destination']; destination.parent.mkdir(parents=True, exist_ok=True)
        artifact = _write(destination, buffer.getvalue()); artifacts.append(artifact)
        rows.append({'file_id': supplied['id'], 'source': deepcopy(supplied['pin']), 'format': supplied['format'],
                     'artifact': artifact, **metadata})
        print(json.dumps({'path': artifact['path'], **metadata}, allow_nan=False))
    handoff = _handoff(d, rows)
    artifacts.append(_write(out / 'filename-handoff.json', encode({'schema_version': 1, 'associations': handoff})))
    result = {'schema_version': 2, 'kind': 'tree-array-delivery', 'status': 'passed', 'status_scope': SCOPE,
              'study_id': d['study_id'], 'parameter_grid': d['parameter_grid'], 'export_contract': d,
              'arrays': rows, 'columns': [v['name'] for v in d['layout']['columns']],
              'file_census': census, 'filename_handoff': handoff, 'input_pins': original,
              **d['source_premises'], 'physics_validated': False, 'execution_authorized': False,
              'preprocessing_executed': False, 'training_executed': False,
              'inference_executed': False, 'original_task_complete': False}
    artifacts.append(_write(out / 'delivery.json', encode(result)))
    c.finish()
    require(_dir_identity(out) == root_identity, 'output directory identity changed')
    files, dirs = _census(out)
    expected = sorted([row['destination'] for row in d['datasets']] + ['filename-handoff.json', 'delivery.json'])
    require(files == expected, 'uncommitted generated file or missing artifact')
    commitment = {'result_sha256': hashlib.sha256(encode(result)).hexdigest(), 'artifacts': artifacts,
                  'inputs': original, 'ancestors': ancestors, 'members': sorted([*expected, 'completion.json']), 'directories': dirs}
    result['commitment'] = _write(out / 'completion.json', encode(commitment))
    finalize(result, out)
    return result


def _report(result):
    return {'status_scope': SCOPE, 'arrays': result['arrays'], 'filename_handoff': result['filename_handoff'],
            'columns': result['columns'], 'export_contract': result['export_contract'],
            'physics_validated': False, 'preprocessing_executed': False, 'training_executed': False}


def delivery_scope():
    return 'Complete supplied tree arrays and consumer associations; no preprocessing, training or scientific qualification.'


def write_report(result, out):
    _write(Path(out) / 'tree-array-report.json', encode(_report(result)))
    return [{'stem': 'tree-array-report', 'files': ['tree-array-report.json'],
             'normalization': 'All source rows and source units retained; no rescale or preprocessing'}]


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    inspect = sub.add_parser('inspect', help='inspect complete source/column/file handoff without ROOT decoding')
    inspect.add_argument('--task', type=Path, required=True)
    args = ap.parse_args(argv)
    task = _json(args.task.read_bytes())
    print(json.dumps(context(task, args.task.absolute().parent), sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
