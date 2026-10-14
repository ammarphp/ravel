"""Source-defined IC/Nyx custody. No solver, scheduler or scientific inference."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import stat
import struct

TEXT_BYTES = 8 * 1024**2


class Publications:
    """Call-scoped exact intended outputs; no first-read rebaselining.

    Explicit updates first verify their previous published version. JSON bytes
    match the existing atomic writer. Observed native files remain separate.
    """
    def __init__(self, limits):
        self.limits = {'max_input_files': limits['max_output_files'], 'max_input_bytes': limits['max_output_bytes']}
        self.rows = {}

    def _check(self, row, captured):
        if identity(ordinary(row['pin']['path']).lstat()) != row['identity']:
            raise ValueError('published intended output identity changed')
        captured.read(row['pin'])

    def json(self, path, value):
        from ravel.workflow.state_io import atomic_json
        p = Path(path).absolute()
        if str(p) in self.rows: self._check(self.rows[str(p)], Capture(p.parent, self.limits))
        intended = deepcopy(value)
        raw = (json.dumps(intended, indent=2, allow_nan=False) + '\n').encode('utf-8')
        pin = {'path': str(p), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
        emitted = deepcopy(intended)
        atomic_json(p, emitted)
        if (json.dumps(emitted, indent=2, allow_nan=False) + '\n').encode('utf-8') != raw:
            raise ValueError('publication callback changed the intended document alias')
        observed = Capture(p.parent, self.limits); observed.read(pin, text=True); observed.finish()
        self.rows[str(p)] = {'pin': pin, 'identity': observed.files[str(p)]['identity']}
        return deepcopy(pin)

    def finish(self):
        observed = Capture(Path('/'), self.limits)
        for row in self.rows.values(): self._check(row, observed)
        observed.finish()

    def text(self, path, text):
        p = Path(path).absolute(); raw = text.encode('utf-8')
        pin = {'path': str(p), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open('xb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
        observed = Capture(p.parent, self.limits); observed.read(pin, text=True); observed.finish()
        self.rows[str(p)] = {'pin': pin, 'identity': observed.files[str(p)]['identity']}
        return deepcopy(self.rows[str(p)])


def keys(value, names, label):
    if type(value) is not dict or set(value) != set(names):
        raise ValueError('closed ' + label + ' fields required')


def integer(value, label, lower=1):
    if type(value) is not int or not lower <= value <= 2**63 - 1:
        raise ValueError('finite declared integer ' + label + ' required')
    return value


def number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('finite ' + label + ' required')
    return float(value)


def name(value):
    if type(value) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', value):
        raise ValueError('bounded identifier required')
    return value


def relative(value):
    if (type(value) is not str or not value or '\x00' in value or
            Path(value).is_absolute() or any(x in ('', '.', '..') for x in value.split('/'))):
        raise ValueError('ordinary relative output/member path required')
    return value


def identity(s):
    return (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def ordinary(path):
    p = Path(path).absolute()
    if any(q.is_symlink() for q in (p, *p.parents)):
        raise ValueError('source/output path aliases are refused')
    if not stat.S_ISREG(p.lstat().st_mode):
        raise ValueError('regular source/output file required')
    return p


def loads(raw):
    def unique(pairs):
        d = {}
        for k, v in pairs:
            if k in d: raise ValueError('duplicate JSON key')
            d[k] = v
        return d
    def bad(v): raise ValueError('nonfinite JSON')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
                      parse_constant=bad, parse_float=lambda v: number(float(v), 'JSON'))


class Capture:
    """Authenticate each consumed buffer and rebind all observed files at return.

    The byte/member envelopes are explicit resources, not physics grid limits.
    Large binary files are hashed in chunks; only requested bounded text/header
    buffers are retained. No cross-call cache or digest-as-content claim.
    """
    def __init__(self, base, limits):
        self.base = Path(base).absolute()
        self.limits = limits
        self.files = {}
        self.trees = {}
        self.bytes = 0

    def read(self, pin, *, text=False, head=0):
        keys(pin, ('path', 'sha256', 'size'), 'file commitment')
        if type(pin['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', pin['sha256']):
            raise ValueError('exact SHA256 required')
        integer(pin['size'], 'source bytes', 0)
        p = Path(pin['path']); p = ordinary(p if p.is_absolute() else self.base / p)
        # A change and restore within the current step of the stamping clock would keep the identity
        # recorded here, so the opening observation waits that step out (validation_io.settled).
        from ravel.workflow.validation_io import settled
        before = settled(p.lstat)
        if before.st_size != pin['size'] or text and before.st_size > TEXT_BYTES:
            raise ValueError('declared file size/text resource differs')
        if str(p) in self.files:
            old = self.files[str(p)]
            if old['sha256'] != pin['sha256'] or old['size'] != pin['size'] or old['identity'] != identity(before):
                raise ValueError('conflicting file commitment')
        else:
            if len(self.files) + 1 > self.limits['max_input_files'] or self.bytes + before.st_size > self.limits['max_input_bytes']:
                raise ValueError('complete input inventory exceeds declared resource envelope')
            self.bytes += before.st_size
        h = hashlib.sha256(); buf = bytearray()
        with p.open('rb') as f:
            if identity(os.fstat(f.fileno())) != identity(before): raise ValueError('opened source identity changed')
            consumed = 0
            while True:
                chunk = f.read(min(1024**2, before.st_size + 1 - consumed))
                if not chunk: break
                consumed += len(chunk)
                if consumed > before.st_size: raise ValueError('source grew beyond declared byte commitment')
                h.update(chunk)
                if text: buf.extend(chunk)
                elif len(buf) < head: buf.extend(chunk[:head - len(buf)])
            if identity(os.fstat(f.fileno())) != identity(before): raise ValueError('source changed while consumed')
        if identity(p.lstat()) != identity(before) or h.hexdigest() != pin['sha256']:
            raise ValueError('consumed source hash/identity differs')
        self.files[str(p)] = dict(path=str(p), sha256=pin['sha256'], size=pin['size'], identity=identity(before))
        return p, bytes(buf)

    def json(self, pin):
        _, raw = self.read(pin, text=True)
        return loads(raw)

    def tree(self, declaration):
        keys(declaration, ('root', 'files'), 'complete source tree')
        p = Path(declaration['root']); p = p if p.is_absolute() else self.base / p
        if not p.is_dir() or any(q.is_symlink() for q in (p, *p.parents)):
            raise ValueError('ordinary source root required')
        if type(declaration['files']) is not list or not declaration['files']:
            raise ValueError('complete finite source tree inventory required')
        declared = []
        for pin in declaration['files']:
            f, _ = self.read(pin)
            if not f.is_relative_to(p): raise ValueError('source member outside tree')
            declared.append(str(f))
        actual = self._tree_members(p)
        if len(set(declared)) != len(declared) or sorted(declared) != actual:
            raise ValueError('complete original source tree differs')
        self.trees[str(p)] = (actual, identity(p.lstat()))

    def _tree_members(self, p):
        result = []
        for root, dirs, files in os.walk(p, followlinks=False):
            if any((Path(root) / n).is_symlink() for n in dirs): raise ValueError('source tree directory alias')
            for n in files:
                result.append(str(ordinary(Path(root) / n)))
                if len(result) > self.limits['max_input_files']: raise ValueError('tree member envelope exceeded')
        return sorted(result)

    def check_identities(self):
        """Cheap intra-call guard; full hash/member closure still ends the call."""
        for row in self.files.values():
            if identity(ordinary(row['path']).lstat()) != row['identity']:
                raise ValueError('observed source identity changed')
        for root, (_, original) in self.trees.items():
            if identity(Path(root).lstat()) != original:
                raise ValueError('observed source root identity changed')

    def finish(self):
        self.check_identities()
        for row in list(self.files.values()):
            p = ordinary(row['path'])
            if identity(p.lstat()) != row['identity']: raise ValueError('ending source identity changed')
            self.read({k: row[k] for k in ('path', 'sha256', 'size')})
        for root, (members, original) in self.trees.items():
            if identity(Path(root).lstat()) != original or self._tree_members(Path(root)) != members:
                raise ValueError('ending source membership/root identity changed')

    def pins(self):
        return [{k: r[k] for k in ('path', 'sha256', 'size')} for _, r in sorted(self.files.items())]


def card(raw):
    """Retain ordered assignments and duplicates; never reinterpret arbitrary code."""
    rows = []
    for line in raw.decode('utf-8').splitlines():
        lex = shlex.shlex(line, posix=True); lex.whitespace_split = True; lex.commenters = '#'
        body = list(lex)
        if not body: continue
        joined = ' '.join(body)
        if '=' not in joined: raise ValueError('literal native card assignment required')
        key, value = joined.split('=', 1); key = key.strip(); value = value.strip()
        explicit_empty = bool(re.search(r'=\s*(?:""|\'\')\s*(?:#.*)?$', line))
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.]*', key) or not value and not explicit_empty:
            raise ValueError('malformed native card assignment')
        rows.append({'key': key, 'value': value})
    if not rows: raise ValueError('nonempty full native card required')
    return rows


def transfer(raw, contract):
    keys(contract, ('columns', 'units', 'redshift', 'normalization', 'file'), 'transfer contract')
    cols = contract['columns']
    if type(cols) is not list or len(cols) < 3 or len(cols) != len(set(cols)) or len(contract['units']) != len(cols):
        raise ValueError('complete named transfer columns/units required')
    if any(type(x) is not str or not x for x in [*cols, *contract['units']]): raise ValueError('explicit transfer semantics required')
    if number(contract['redshift'], 'transfer redshift') < 0: raise ValueError('nonnegative redshift required')
    rows = []
    for line in raw.decode('utf-8').splitlines():
        text = line.split('#', 1)[0].strip()
        if not text: continue
        row = [number(float(v), 'transfer entry') for v in text.split()]
        if len(row) != len(cols): raise ValueError('full transfer column population differs')
        rows.append(row)
    if not rows or any(r[0] <= 0 for r in rows) or any(a[0] >= b[0] for a, b in zip(rows, rows[1:])):
        raise ValueError('complete positive ordered transfer grid required')
    return {'columns': deepcopy(cols), 'units': deepcopy(contract['units']), 'rows': rows,
            'redshift': contract['redshift'], 'normalization_verified': False}


def binary_ic(capture, declaration, writer):
    keys(declaration, ('file_list', 'chunks', 'shape', 'reader_base'), 'IC population')
    if writer is None: raise ValueError('authentic CosmicIC generator/writer source contract is required; PrintFormat6 is unavailable')
    keys(writer, ('kind', 'byte_order', 'long_bytes', 'int_bytes', 'real_bytes', 'dimension', 'extra_values', 'source_evidence'), 'source-declared writer contract')
    if (any(type(writer[k]) is not int for k in ('long_bytes', 'int_bytes', 'real_bytes', 'dimension', 'extra_values')) or
            writer['kind'] != 'AMReX-BinaryFile' or writer['byte_order'] not in ('little', 'big') or writer['long_bytes'] not in (4, 8) or writer['int_bytes'] != 4 or writer['real_bytes'] not in (4, 8) or writer['dimension'] != 3 or writer['extra_values'] < 4):
        raise ValueError('explicit supported source-bound reader/writer ABI required')
    if not writer['source_evidence']: raise ValueError('actual writer source evidence required')
    for pin in writer['source_evidence']: capture.read(pin, text=True)
    path, raw = capture.read(declaration['file_list'], text=True)
    if not raw.endswith(b'\n'): raise ValueError('complete BinaryMetaFile final newline required')
    lines = raw.decode('utf-8').splitlines()
    if not lines or any(not x or x.strip() != x for x in lines) or len(lines) != len(set(lines)):
        raise ValueError('complete unique ordered IC file list required')
    declared = declaration['chunks']
    if len(lines) != len(declared): raise ValueError('full IC chunk population differs')
    shape = declaration['shape']
    if type(shape) is not list or len(shape) != 3: raise ValueError('complete three-dimensional IC population required')
    expected = math.prod(integer(v, 'IC dimension') for v in shape)
    prefix = '<' if writer['byte_order'] == 'little' else '>'
    fmt = prefix + ('q' if writer['long_bytes'] == 8 else 'i') + 'ii'
    header = struct.calcsize(fmt); total = 0; result = []; physical = set()
    for line, pin in zip(lines, declared):
        p, head = capture.read(pin, head=header)
        inode = identity(p.lstat())[:2]
        if inode in physical: raise ValueError('physical IC chunk alias repeats the population')
        physical.add(inode)
        native_base = Path(declaration['reader_base'])
        native_base = native_base if native_base.is_absolute() else capture.base / native_base
        selected = Path(line); selected = selected if selected.is_absolute() else native_base / selected
        if selected.absolute() != p: raise ValueError('ordered actual IC path differs')
        if len(head) != header: raise ValueError('complete native IC header required')
        count, dim, extra = struct.unpack(fmt, head)
        if count <= 0 or dim != writer['dimension'] or extra != writer['extra_values'] or pin['size'] != header + count * (dim + extra) * writer['real_bytes']:
            raise ValueError('native IC count/dimension/ABI/exact payload length differs')
        total += count; result.append({'path': str(p), 'particles': count, 'dimension': dim, 'extra_values': extra})
    if total != expected: raise ValueError('whole IC particle population/geometry differs')
    return {'shape': shape, 'particles': total, 'chunks': result, 'source_contract': writer, 'physics_verified': False}


def generated_ic(root, file_list, shape, writer, limits):
    """Authenticate the full fresh native products and source-written FileList.

    File names come from the actual bounded native FileList, never a predicted
    writer layout. The selected reader resolves entries from the native cwd.
    Every chunk must belong to the captured full generator product population.
    """
    root = Path(root).absolute(); inventory = output_inventory(root, limits)
    by_name = {r['path']: r for r in inventory}
    list_name = relative(file_list)
    if list_name not in by_name: raise ValueError('fresh generator FileList is missing')
    def pin(row): return {k: (str(root / row[k]) if k == 'path' else row[k]) for k in ('path', 'sha256', 'size')}
    captured = Capture(root, limits)
    captured.tree({'root': str(root), 'files': [pin(r) for r in inventory]})
    list_pin = pin(by_name[list_name]); _, raw = captured.read(list_pin, text=True)
    names = raw.decode('utf-8').splitlines(); chunks = []
    if len(names) > limits['max_output_files']: raise ValueError('full IC chunks exceed declared envelope')
    for line in names:
        q = Path(line); q = q if q.is_absolute() else root / q
        q = ordinary(q)
        if not q.is_relative_to(root) or q.relative_to(root).as_posix() not in by_name:
            raise ValueError('fresh IC chunk is outside original generator products')
        chunks.append(pin(by_name[q.relative_to(root).as_posix()]))
    declaration = {'file_list': list_pin, 'chunks': chunks, 'shape': shape, 'reader_base': str(root)}
    result = binary_ic(captured, declaration, writer)
    captured.finish()
    if output_inventory(root, limits) != inventory: raise ValueError('fresh IC products changed before receipt')
    return {'declaration': declaration, 'validation': result, 'inventory': inventory}


def output_inventory(root, limits):
    root = Path(root).absolute()
    if not root.is_dir() or any(q.is_symlink() for q in (root, *root.parents)):
        raise ValueError('ordinary complete output root required')
    result = []; total = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        if any((Path(directory) / n).is_symlink() for n in dirs): raise ValueError('output directory alias')
        for n in sorted(files):
            p = ordinary(Path(directory) / n); s = p.lstat(); total += s.st_size
            if len(result) + 1 > limits['max_output_files'] or total > limits['max_output_bytes']:
                raise ValueError('complete output exceeds declared resources; no clipping')
            h = hashlib.sha256()
            with p.open('rb') as f:
                consumed = 0
                while data := f.read(min(1024**2, s.st_size + 1 - consumed)):
                    consumed += len(data)
                    if consumed > s.st_size: raise ValueError('output grew beyond declared capture')
                    h.update(data)
                if identity(os.fstat(f.fileno())) != identity(s): raise ValueError('output changed during capture')
            if identity(p.lstat()) != identity(s): raise ValueError('output changed during capture')
            result.append({'path': p.relative_to(root).as_posix(), 'sha256': h.hexdigest(), 'size': s.st_size, 'identity': list(identity(s))})
    return sorted(result, key=lambda r: r['path'])


def check_outputs(root, contract, limits):
    """Complete files plus source-defined text markers, not numerical physics."""
    keys(contract, ('required_files', 'text_markers', 'scope'), 'full native output contract')
    if type(contract['required_files']) is not list or not contract['required_files'] or len(set(contract['required_files'])) != len(contract['required_files']):
        raise ValueError('complete distinct source-defined native outputs required')
    inventory = output_inventory(root, limits); by_name = {r['path']: r for r in inventory}
    for value in contract['required_files']:
        if relative(value) not in by_name: raise ValueError('required native output is missing: ' + value)
    for row in contract['text_markers']:
        keys(row, ('path', 'lines'), 'raw native output marker')
        p = Path(root) / relative(row['path'])
        if row['path'] not in by_name or p.stat().st_size > TEXT_BYTES: raise ValueError('bounded captured native text required')
        before = p.lstat()
        with p.open('rb') as f:
            raw = f.read(TEXT_BYTES + 1)
            if identity(os.fstat(f.fileno())) != identity(before): raise ValueError('native marker identity changed')
        if len(raw) > TEXT_BYTES or identity(p.lstat()) != identity(before): raise ValueError('native marker read boundary changed')
        if hashlib.sha256(raw).hexdigest() != by_name[row['path']]['sha256']: raise ValueError('consumed output marker changed')
        lines = raw.decode('utf-8').splitlines()
        if type(row['lines']) is not list or not row['lines'] or any(type(x) is not str or x not in lines for x in row['lines']):
            raise ValueError('complete requested native text fields/domain markers missing')
    if inventory != output_inventory(root, limits): raise ValueError('ending output inventory/identity changed')
    return {'scope': deepcopy(contract['scope']), 'inventory': inventory, 'complete_declared_outputs': True,
            'source_semantic_completeness_verified': False, 'physics_verified': False}
