"""One-call observational verification. No persistent cache or atomic-snapshot claim."""
from pathlib import Path
import hashlib
import os
import stat
import re
import json
import math
import sys
import time
from copy import deepcopy
from .state_io import _unique


def identity(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def directory_identity(value):
    """A directory on a path: its size and times change with every unrelated entry another
    process creates or removes in it; a replaced directory changes its device or inode."""
    return (value.st_dev, value.st_ino, value.st_mode)


# Linux stamps inode times from CLOCK_REALTIME_COARSE, which advances once per timer tick.
_LINUX_COARSE_REALTIME = 5
SETTLE_LIMIT_NS = 1_500_000_000


def _stamp_clock_ns():
    """The clock a local filesystem stamps a change with."""
    if sys.platform.startswith('linux'):
        try:
            return time.clock_gettime_ns(_LINUX_COARSE_REALTIME)
        except OSError:
            pass
    return time.time_ns()


def _stamp_step_ns(stamp):
    """The step of a filesystem's stamps, read from the stamp: whole seconds, milli- or microseconds."""
    return next((unit for unit in (1_000_000_000, 1_000_000, 1_000) if stamp % unit == 0), 1)


def settled(observe):
    """An opening observation that a later change cannot leave unchanged.

    ``observe`` is a stat call. A later write is seen through the change time, and the
    kernel takes that time from a clock that advances in steps (one timer tick on Linux,
    a whole second on some filesystems). A file changed within the current step can be
    rewritten to the same size, or changed and restored, and keep every observed field.
    The observation is therefore repeated until the stamping clock has passed the file's
    change time by one step of its stamps; from then on any change gets a later stamp.
    For a local filesystem this waits at most one step, and only for a file changed
    within it. The wait is bounded: a change time further ahead than the limit comes from
    another clock, cannot be compared, and is returned as observed, without this assurance.
    This is an observation, not a lock.
    """
    started = time.monotonic_ns()
    while True:
        value = observe()
        wait = value.st_ctime_ns + _stamp_step_ns(value.st_ctime_ns) - _stamp_clock_ns()
        if wait <= 0 or wait > SETTLE_LIMIT_NS or time.monotonic_ns() - started > SETTLE_LIMIT_NS:
            return value
        time.sleep(wait / 1_000_000_000)


_EMPTY_SHA = hashlib.sha256(b'').hexdigest()


def _source_pin_bytes(pin, *, limit=8 * 1024 * 1024):
    """One bounded ordinary-file observation of the exact consumed source bytes."""
    if (type(pin) is not dict or set(pin) != {'path', 'sha256', 'size'}
            or type(pin['size']) is not int or not 0 < pin['size'] <= limit
            or type(pin['sha256']) is not str or not re.fullmatch(r'[0-9a-f]{64}', pin['sha256'])
            or type(pin['path']) is not str or not pin['path'].startswith('/')
            or '\\' in pin['path'] or any(p in ('', '.', '..') for p in pin['path'][1:].split('/'))):
        raise ValueError('closed bounded canonical source pin required')
    path = Path(pin['path'])
    opened = identity(settled(path.lstat))
    ancestry = [(p, directory_identity(p.lstat())) for p in path.parents]
    if (not stat.S_ISREG(opened[2]) or opened[3] != pin['size']
            or any(not stat.S_ISDIR(value[2]) for _, value in ancestry)):
        raise ValueError('source pin requires an ordinary exact-size file and ancestry')
    with path.open('rb') as stream:
        if identity(os.fstat(stream.fileno())) != opened:
            raise ValueError('source pin descriptor changed')
        data = stream.read(pin['size'] + 1)
        if identity(os.fstat(stream.fileno())) != opened:
            raise ValueError('source pin changed during read')
    if (identity(path.lstat()) != opened or any(directory_identity(p.lstat()) != value for p, value in ancestry)
            or len(data) != pin['size'] or hashlib.sha256(data).hexdigest() != pin['sha256']):
        raise ValueError('source pin bytes or ancestry changed')
    return data


def _checkmate_source_copies(rundir, paths, policy, resolve_path, input_snapshot, input_paths, require_input_binding):
    """Opaque upstream source JSON, never a generated result/control JSON role."""
    rows = policy.get('verbatim_input_source_copies', [])
    if type(rows) is not list or len(rows) > 1024:
        raise ValueError('bounded explicit source-copy list required')
    directories = [resolve_path(rundir, value, output=True) for value in paths]
    result, inventories, declared = {}, {}, None
    for entry in rows:
        if (type(entry) is not dict or set(entry) != {'path', 'role', 'relative', 'inventory', 'source'}
                or entry['role'] != 'checkmate252_prefix_source'):
            raise ValueError('closed CheckMATE source-copy role required')
        relative = entry['relative']
        if (type(relative) is not str or not relative.startswith('data/') or not relative.endswith('.json')
                or '\\' in relative or any(p in ('', '.', '..') for p in relative.split('/'))
                or entry['path'] != 'outputs/attempt-1/prefix/' + relative):
            raise ValueError('exact inventory-derived copied-source destination required')
        inventory = entry['inventory']
        # Cache only identical inventory pins within this call, never across calls.
        key = json.dumps(inventory, sort_keys=True)
        if key not in inventories:
            data = _source_pin_bytes(inventory)
            def finite(value):
                number = float(value)
                if not math.isfinite(number): raise ValueError('non-finite source inventory')
                return number
            inv = json.loads(data, object_pairs_hook=_unique, parse_float=finite,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError('non-finite source inventory')))
            if (type(inv) is not dict or set(inv) != {'schema_version', 'kind', 'original_root', 'revision', 'files'}
                    or type(inv['schema_version']) is not int or inv['schema_version'] != 1
                    or inv['kind'] != 'checkmate252-preserved-prefix-source'
                    or inv['revision'] != 'bacf9d17ff8e844e3b40851849e21f0dd0f0638c'
                    or type(inv['files']) is not list or len(inv['files']) > 50000
                    or type(inv['original_root']) is not str):
                raise ValueError('exact preserved CheckMATE2.5.2 input inventory required')
            inventories[key] = inv
        inv = inventories[key]
        matches = [row for row in inv['files'] if type(row) is dict and row.get('relative') == relative]
        source = entry['source']
        if (len(matches) != 1 or set(matches[0]) != {'relative', 'sha256', 'size', 'mode', 'link'}
                or type(source) is not dict
                or source != {'path': inv['original_root'] + '/' + relative,
                              'sha256': matches[0]['sha256'], 'size': matches[0]['size']}):
            raise ValueError('copy must bind its exact original inventory source row')
        _source_pin_bytes(source, limit=64 * 1024 * 1024)
        if require_input_binding and (input_snapshot is None or input_paths is None):
            raise ValueError('source copy requires approved stage input binding')
        if input_snapshot is not None or input_paths is not None:
            if type(input_snapshot) is not dict or type(input_paths) not in (list, tuple):
                raise ValueError('source copy requires exact input snapshot and paths')
            if declared is None:
                declared = {str(resolve_path(rundir, value)) for value in input_paths}
            for pin in (inventory, source):
                expected = {'kind': 'file', 'files': [{'name': '.', 'size': pin['size'], 'sha256': pin['sha256']}]}
                if (pin['path'] not in declared or input_snapshot.get(pin['path']) != expected
                        or type(input_snapshot[pin['path']]['files'][0]['size']) is not int):
                    raise ValueError('source copy requires exact captured singleton stage inputs')
        target = resolve_path(rundir, entry['path'], output=True)
        if not any(target != directory and target.is_relative_to(directory) for directory in directories):
            raise ValueError('source copy must be a child of a declared output directory')
        if target in result:
            raise ValueError('duplicate source-copy destination')
        result[target] = source
    return result


def _verbatim_input_source_copies(rundir, paths, outputs, policy, resolve_path, *, input_snapshot=None, input_paths=None):
    if policy is None or policy.get('schema_version') != 2:
        return {}
    if not outputs: raise ValueError('output policy cannot alter input snapshots')
    return _checkmate_source_copies(rundir, paths, policy, resolve_path, input_snapshot, input_paths, True)


def _retained_build_marker(entry, input_snapshot, input_paths, rundir, require_input_binding):
    if set(entry) != {'path', 'role', 'marker_class', 'source'} or entry['marker_class'] != 'cmake_externalproject_stamp':
        raise ValueError('closed retained build-marker declaration required')
    prefix = 'outputs/attempt-1/container-input/dependency-checkpoint/work/build/'
    if not entry['path'].startswith(prefix):
        raise ValueError('build marker must be an exact retained dependency input copy')
    suffix = entry['path'][len(prefix):]
    relative = Path(suffix)
    parent, name = relative.parent.name, relative.name
    if parent.endswith('-stamp'):
        target = parent[:-6]
        stages = ('mkdir', 'download', 'update', 'patch', 'configure', 'build', 'install', 'libcopy', 'done')
        valid = bool(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', target)) and name in {target+'-'+stage for stage in stages}
    else:
        valid = parent == 'CMakeFiles' and bool(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*-complete', name))
    if not valid:
        raise ValueError('source-defined CMake ExternalProject stamp class required')
    source = entry['source']
    if type(source) is not dict or set(source) != {'path', 'sha256', 'size'} or source['size'] != 0 or type(source['size']) is not int or source['sha256'] != _EMPTY_SHA:
        raise ValueError('exact empty original build-marker source pin required')
    value = source['path']
    if (type(value) is not str or not value.startswith('/') or '\\' in value
            or any(part in ('', '.', '..') for part in value[1:].split('/'))
            or not value.endswith('/dependency-checkpoint/work/build/'+suffix)):
        raise ValueError('canonical original dependency marker source required')
    if require_input_binding and (input_snapshot is None or input_paths is None):
        raise ValueError('retained build marker requires approved stage input binding')
    if input_snapshot is not None or input_paths is not None:
        if (type(input_snapshot) is not dict or type(input_paths) not in (list, tuple)
                or any(type(p) is not str or not p for p in input_paths)):
            raise ValueError('retained build marker requires exact input snapshot and paths')
        declared = {str(Path(p) if Path(p).is_absolute() else Path(rundir)/p) for p in input_paths}
        expected = {'kind': 'file', 'files': [{'name': '.', 'size': 0, 'sha256': _EMPTY_SHA}]}
        captured = input_snapshot.get(value)
        if (value not in declared or captured != expected
                or type(captured['files'][0]['size']) is not int):
            raise ValueError('original build marker is not an exact captured singleton stage input')



_SFITTER6072_EMPTY_SOURCE_FILES = ('sfitter/sfitter/__init__.py', 'sfitter/sfitter/eval/__init__.py', 'sfitter/sfitter/fit/__init__.py', 'sfitter/sfitter/likelihood/__init__.py', 'sfitter/sfitter/util/__init__.py', 'sfitteragents/.claude/agent-memory/.gitkeep', 'sfitteragents/.claude/lead-memory/.gitkeep', 'src/launcher/__init__.py')


def _retained_source_file(entry,input_snapshot,input_paths,rundir,require_input_binding):
    """Only exact already-admitted empty SFitter6072 source file copies."""
    if (set(entry)!={'path','role','marker_class','relative','source'}
            or entry['marker_class']!='sfitter6072_empty_source_file'
            or entry['relative'] not in _SFITTER6072_EMPTY_SOURCE_FILES
            or entry['path']!='outputs/attempt-1/native/upstream/'+entry['relative']):
        raise ValueError('closed source-defined empty SFitter file copy required')
    source=entry['source'];relative=entry['relative']
    if (type(source) is not dict or set(source)!={'path','sha256','size'}
            or type(source['size']) is not int or source['size']!=0 or source['sha256']!=_EMPTY_SHA
            or type(source['path']) is not str or not source['path'].startswith('/')
            or not source['path'].endswith('/'+relative) or '\\' in source['path']
            or any(part in ('','.','..') for part in source['path'][1:].split('/'))):
        raise ValueError('canonical exact empty original file source pin required')
    if require_input_binding and (input_snapshot is None or input_paths is None):
        raise ValueError('source file requires approved input binding')
    if input_snapshot is not None or input_paths is not None:
        if type(input_snapshot) is not dict or type(input_paths) not in (list,tuple):
            raise ValueError('source file requires exact captured singleton inputs')
        declared={str(Path(v) if Path(v).is_absolute() else Path(rundir)/v) for v in input_paths}
        expected={'kind':'file','files':[{'name':'.','size':0,'sha256':_EMPTY_SHA}]}
        captured=input_snapshot.get(source['path'])
        if (source['path'] not in declared or captured!=expected
                or type(captured['files'][0]['size']) is not int):
            raise ValueError('empty file source is not its exact approved singleton input')

def _generated_sector_declaration(entry, input_snapshot, input_paths, rundir, require_input_binding):
    """Pure declaration checks, also usable on committed frozen review proofs."""
    prefix = 'outputs/attempt-1/finite-integrals/native/finite_integral/finite_integral_integral/codegen'
    if (type(entry) is not dict or set(entry) != {'path', 'role', 'marker_class', 'source', 'max_sectors'}
            or entry['role'] != 'generated_build_marker_family'
            or entry['marker_class'] != 'pysecdec166_sector_codegen_done'
            or entry['path'] != prefix
            or type(entry['max_sectors']) is not int or not 1 <= entry['max_sectors'] <= 256):
        raise ValueError('closed bounded pySecDec sector-marker family required')
    source = entry['source']
    if (type(source) is not dict or set(source) != {'path', 'sha256', 'size'}
            or source.get('sha256') != 'eaea4f42389af4011cb858ded7dc41f155958ba031e9240f24e86100ca97f9fa'
            or type(source.get('path')) is not str
            or not source['path'].startswith('/') or '\\' in source['path']
            or any(p in ('', '.', '..') for p in source['path'][1:].split('/'))
            or type(source.get('size')) is not int or not 0 < source['size'] <= 64 * 1024
            or not source['path'].endswith('/pySecDec/code_writer/templates/make_package/Makefile')):
        raise ValueError('exact released pySecDec1.6.6 producer template required')
    if require_input_binding and (input_snapshot is None or input_paths is None):
        raise ValueError('generated markers require approved producer input binding')
    if input_snapshot is not None or input_paths is not None:
        if (type(input_snapshot) is not dict or type(input_paths) not in (list, tuple)
                or any(type(p) is not str or not p for p in input_paths)):
            raise ValueError('generated markers require exact input snapshot and paths')
        declared = {str(Path(p) if Path(p).is_absolute() else Path(rundir) / p) for p in input_paths}
        expected = {'kind': 'file', 'files': [{'name': '.', 'size': source['size'], 'sha256': source['sha256']}]}
        if (source['path'] not in declared or input_snapshot.get(source['path']) != expected
                or type(input_snapshot[source['path']]['files'][0]['size']) is not int):
            raise ValueError('producer template is not an exact captured singleton stage input')
    return source


def _generated_sector_indices(entry, rows):
    """Complete bounded sector population from live or committed file metadata."""
    if (type(rows) is not list or len(rows) > 4 * entry['max_sectors'] + 16
            or any(type(r) is not dict or set(r) != {'name', 'size'}
                   or type(r['name']) is not str or '/' in r['name'] or '\\' in r['name']
                   or r['name'] in ('', '.', '..') or type(r['size']) is not int or r['size'] < 0 for r in rows)
            or len({r['name'] for r in rows}) != len(rows)):
        raise ValueError('bounded unique regular generated sector population required')
    groups = {'h': {}, 'info': {}, 'done': {}}
    for row in rows:
        match = re.fullmatch(r'sector([1-9][0-9]*)\.(h|info|done)', row['name'])
        if match:
            groups[match[2]][int(match[1])] = row
        elif row['name'].startswith('sector') and Path(row['name']).suffix in ('.h', '.info', '.done'):
            raise ValueError('unsupported generated sector filename')
    ids = set(groups['h'])
    if (not ids or len(ids) > entry['max_sectors'] or ids != set(range(1, len(ids) + 1))
            or ids != set(groups['info']) or ids != set(groups['done'])):
        raise ValueError('complete contiguous generated header/info/marker census required')
    if any(r['size'] <= 0 for k in ('h', 'info') for r in groups[k].values()):
        raise ValueError('nonempty generated header and sector metadata required')
    if any(r['size'] != 0 for r in groups['done'].values()):
        raise ValueError('source-defined sector stamps must retain empty bytes')
    names = frozenset(r['name'] for r in groups['done'].values())
    if any(r['size'] == 0 and r['name'] not in names for r in rows):
        raise ValueError('unlisted empty generated sector member')
    return names


def _generated_sector_markers(entry, input_snapshot, input_paths, rundir, require_input_binding, *, outputs=False):
    """Source-bound live observation; stamps remain custody, never physics data."""
    source = _generated_sector_declaration(entry, input_snapshot, input_paths, rundir, require_input_binding)
    _source_pin_bytes(source, limit=64 * 1024)
    if not outputs:
        return frozenset()
    root = Path(rundir) / entry['path']
    if any(p.is_symlink() for p in (root, *root.parents)) or not root.is_dir():
        raise ValueError('ordinary generated sector directory required')
    children = []
    for child in root.iterdir():
        if len(children) >= 4 * entry['max_sectors'] + 16:
            raise ValueError('generated sector population exceeds bound')
        children.append(child)
    children.sort()
    if any(p.is_symlink() or not p.is_file() for p in children):
        raise ValueError('bounded regular generated sector population required')
    names = _generated_sector_indices(entry, [{'name': p.name, 'size': p.stat().st_size} for p in children])
    return frozenset(root / name for name in names)


def validate_output_policy(rundir, paths, policy, resolve_path, *, input_snapshot=None, input_paths=None, require_input_binding=False):
    """Validate an explicit declaration without requiring future output files.

    An allowed member declares its ancestor output as a directory. Runtime
    snapshots still require an existing regular member of that directory.
    """
    keys = {'schema_version', 'allow_empty_directory_members'}
    if type(policy) is dict and policy.get('schema_version') == 2:
        keys.add('verbatim_input_source_copies')
    if (type(policy) is not dict or set(policy) != keys
            or type(policy['schema_version']) is not int or policy['schema_version'] not in (1, 2)
            or type(policy['allow_empty_directory_members']) is not list):
        raise ValueError('invalid explicit output policy')
    directories = [resolve_path(rundir, value, output=True) for value in paths]
    allowed = set()
    for entry in policy['allow_empty_directory_members']:
        if type(entry) is not dict or 'path' not in entry or 'role' not in entry:
            raise ValueError('invalid incidental output member')
        if entry['role'] not in ('retained_build_marker', 'generated_build_marker_family', 'retained_source_file') and set(entry) != {'path', 'role'}:
            raise ValueError('invalid incidental output member')
        value, role = entry['path'], entry['role']
        if (type(value) is not str or not value or value.startswith('/') or '\\' in value
                or any(part in ('', '.', '..') for part in value.split('/'))):
            raise ValueError('incidental output member must be a canonical run-relative path')
        path = resolve_path(rundir, value, output=True)
        if role == 'incidental_log':
            if path.suffix.lower() not in ('.log', '.out', '.stderr'):
                raise ValueError('incidental-log allowance cannot admit scientific result formats')
        elif role == 'python_package_marker':
            if path.name != '__init__.py':
                raise ValueError('package-marker allowance requires exact __init__.py')
        elif role == 'retained_build_marker':
            _retained_build_marker(entry, input_snapshot, input_paths, rundir, require_input_binding)
        elif role == 'retained_source_file':
            _retained_source_file(entry,input_snapshot,input_paths,rundir,require_input_binding)
        elif role == 'generated_build_marker_family':
            _generated_sector_declaration(entry, input_snapshot, input_paths, rundir, require_input_binding)
        else:
            raise ValueError('unknown incidental output role')
        if not any(path != directory and path.is_relative_to(directory) for directory in directories):
            raise ValueError('incidental member must be a child of a declared output directory')
        if path in allowed:
            raise ValueError('duplicate incidental output member')
        allowed.add(path)
    if policy['schema_version'] == 2:
        copies = _checkmate_source_copies(rundir, paths, policy, resolve_path, input_snapshot, input_paths, require_input_binding)
        if allowed.intersection(copies): raise ValueError('source-copy role cannot overlap an empty-member role')
    return frozenset(allowed)


def _empty_directory_members(rundir, paths, outputs, policy, resolve_path, *, input_snapshot=None, input_paths=None):
    """Strict default; explicitly named incidental zero members remain hashed."""
    if policy is None:
        return frozenset()
    if not outputs:
        raise ValueError('output policy cannot alter input snapshots')
    declared = validate_output_policy(rundir, paths, policy, resolve_path, input_snapshot=input_snapshot, input_paths=input_paths, require_input_binding=True)
    family_roots = {resolve_path(rundir, entry['path'], output=True) for entry in policy['allow_empty_directory_members']
                    if entry['role'] == 'generated_build_marker_family'}
    allowed = set(declared - family_roots)
    for entry in policy['allow_empty_directory_members']:
        if entry['role'] == 'generated_build_marker_family':
            allowed.update(_generated_sector_markers(entry, input_snapshot, input_paths, rundir, True, outputs=True))
    directories = [resolve_path(rundir, value, output=True) for value in paths]
    directories = [path for path in directories if path.is_dir()]
    for path in allowed:
        if (not path.is_file() or not any(path != directory and path.is_relative_to(directory) for directory in directories)):
            raise ValueError('incidental member must be an existing regular child of a declared output directory')
    for entry in policy['allow_empty_directory_members']:
        if entry['role'] in ('retained_build_marker','retained_source_file') and resolve_path(rundir, entry['path'], output=True).stat().st_size != 0:
            raise ValueError('retained build marker differs from original empty source')
    return frozenset(allowed)


class ValidationSession:
    def __init__(self, rundir, *, resolve_path, read_json, runtime_context, digest,
                 state_name, tracked=()):
        self.rundir = Path(rundir)
        self.resolve_path = resolve_path
        self.read_json = read_json
        self.runtime_context = runtime_context
        self.digest = digest
        self.runtime = runtime_context()
        self.tracked = [(obj, digest(obj)) for obj in tracked]
        self.hashes = {}
        self.files = {}
        self.queries = {}
        self.absent_inventory_paths = set()
        self.exists_states = {}
        self.path_identities = {}
        self.valid_json = set()
        self.stages = {}
        self.proofs = {}
        self.final_checks = []
        self.regular_paths = set()
        self.regular_resolutions = {}
        self.hash_bytes = 0
        self.hash_calls = 0
        self.closed = False
        self.ledger = self.rundir / state_name
        self.ledger_existed = self.ledger.exists()
        self.ledger_digest = self.hash_file(self.ledger) if self.ledger_existed else None

    def observe(self, path):
        previous = self.files.get(str(path))
        # The first observation of a file is the baseline every later one is compared with.
        value = identity(Path(path).stat() if previous is not None else settled(Path(path).stat))
        if not stat.S_ISREG(value[2]):
            raise ValueError('artifact is not a regular file: ' + str(path))
        if previous is not None and value != previous:
            raise ValueError('artifact identity changed during validation: ' + str(path))
        return value

    def require_regular(self, path):
        """Retain the science input's stricter no-symlink path contract."""
        if self.closed:
            raise ValueError('validation session is already closed')
        path = Path(path).absolute()
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
            raise ValueError('scientific input path changed or traverses a symlink: ' + str(path))
        self.regular_paths.add(path)

    def retain_final_check(self, check):
        """Retain another bounded observation until this call's final census."""
        if self.closed or getattr(self, '_readonly_frozen', False) or not callable(check):
            raise ValueError('a live callable final observation is required')
        self.final_checks.append(check)

    def track(self, value):
        if self.closed:
            raise ValueError('validation session is already closed')
        self.tracked.append((value, self.digest(value)))

    def regular_file(self, value, base):
        """Reuse strict input resolution only inside this observational call.

        Every reuse checks file identity. finish() still rechecks each literal
        ancestry for symlinks and every observed file before returning authority.
        The bounded map never survives this session or a launch/result boundary.
        """
        if self.closed:
            raise ValueError('validation session is already closed')
        candidate = Path(value).expanduser()
        candidate = (candidate if candidate.is_absolute() else Path(base) / candidate).absolute()
        previous = self.regular_resolutions.get(candidate)
        if previous is not None:
            path, observed = previous
            if self.observe(path) != observed:
                raise ValueError('scientific input identity changed during resolution reuse: ' + str(candidate))
            return path
        self.require_regular(candidate)
        path = candidate.resolve()
        if path != candidate:
            self.require_regular(path)
        observed = self.observe(path)
        self.files[str(path)] = observed
        # Large admitted populations retain their strict checks even if this
        # optimization's map is full; its bound never becomes an input ceiling.
        if len(self.regular_resolutions) < 50000:
            self.regular_resolutions[candidate] = (path, observed)
        return path

    def read_document(self, path):
        """Read strict JSON under the same observed file identity as its hash."""
        self.hash_file(path)
        before = self.observe(path)
        document = self.read_json(path)
        if self.observe(path) != before:
            raise ValueError('document changed while reading: ' + str(path))
        self.track(document)
        return document

    def hash_file(self, path):
        if self.closed:
            raise ValueError('validation session is already closed')
        path = Path(path)
        before = self.observe(path)
        if before not in self.hashes:
            value = hashlib.sha256()
            with path.open('rb') as stream:
                if identity(os.fstat(stream.fileno())) != before:
                    raise ValueError('artifact replaced before opening: ' + str(path))
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    value.update(block)
                    self.hash_bytes += len(block)
                if identity(os.fstat(stream.fileno())) != before:
                    raise ValueError('artifact changed while hashing: ' + str(path))
            self.hash_calls += 1
            if identity(path.stat()) != before:
                raise ValueError('artifact pathname changed while hashing: ' + str(path))
            self.hashes[before] = value.hexdigest()
        if self.observe(path) != before:
            raise ValueError('artifact changed during cache reuse: ' + str(path))
        self.files[str(path)] = before
        return self.hashes[before]

    def census(self, value, outputs):
        path = self.resolve_path(self.rundir, value, output=outputs)
        if not path.exists():
            raise ValueError('missing artifact: ' + value)
        if path.is_file():
            return path, ('file',), [path]
        if not path.is_dir():
            raise ValueError('unsupported artifact kind: ' + value)
        children = sorted(path.rglob('*'))
        if any(p.is_symlink() for p in children):
            raise ValueError('artifact directory contains an untracked symlink: ' + value)
        # Include directory identities and empty subdirectories in the ending
        # census; file content identities are checked separately using fstat.
        signature = [('root', identity(path.stat()))]
        files = []
        for child in children:
            mode = child.stat().st_mode
            if stat.S_ISDIR(mode):
                signature.append((child.relative_to(path).as_posix(), 'directory', identity(child.stat())))
            elif stat.S_ISREG(mode):
                signature.append((child.relative_to(path).as_posix(), 'file'))
                files.append(child)
            else:
                raise ValueError('unsupported artifact directory entry: ' + str(child))
        return path, tuple(signature), files

    def observe_exists(self, value):
        """Retain exact Path.exists semantics for one read-only owner boundary.

        Unlike inventory absence, a dangling link is still false. This does not
        grant file custody or change the public/default finish contract.
        """
        if self.closed:
            raise ValueError('validation session is already closed')
        path = Path(value).absolute()
        current = path.exists()
        if path in self.exists_states and self.exists_states[path] != current:
            raise ValueError('observed path existence changed during validation')
        self.exists_states[path] = current
        return current

    def require_inventory(self, value):
        """Track an observational directory census without requiring any files."""
        if self.closed:
            raise ValueError('validation session is already closed')
        candidate = Path(value).absolute()
        if any(p.is_symlink() for p in (candidate, *candidate.parents)):
            raise ValueError('observed inventory traverses a symlink')
        if not candidate.exists():
            self.absent_inventory_paths.add(candidate)
            return
        if candidate in self.absent_inventory_paths:
            raise ValueError('observed inventory appeared during validation')
        path, census, _ = self.census(str(candidate), False)
        query = (str(candidate), False)
        current = (str(path), census)
        if query in self.queries and self.queries[query] != current:
            raise ValueError('observed inventory changed during validation')
        self.queries[query] = current

    def retain_path_identity(self, value, expected):
        """Retain a typed reader's original lstat identity, without a census.

        Three fields identify an ordinary ancestor; six retain the original
        full leaf/owned-directory identity. This adds a plain fact, not a
        sampler or callback, and never replaces an earlier commitment.
        """
        if self.closed:
            raise ValueError('validation session is already closed')
        path = Path(value)
        if (not path.is_absolute() or type(expected) is not tuple
                or len(expected) not in (3, 6)
                or any(type(field) is not int for field in expected)):
            raise ValueError('original absolute typed path identity required')
        key = (path, len(expected))
        if (identity(path.lstat())[:len(expected)] != expected
                or (key in self.path_identities and self.path_identities[key] != expected)):
            raise ValueError('typed path identity changed during validation')
        self.path_identities[key] = expected

    def snapshot(self, paths, *, outputs=False, output_policy=None, input_snapshot=None, input_paths=None):
        paths = list(paths)
        allowed = _empty_directory_members(self.rundir, paths, outputs, output_policy, self.resolve_path, input_snapshot=input_snapshot, input_paths=input_paths)
        for entry in (output_policy or {}).get('allow_empty_directory_members', []):
            if entry['role'] == 'generated_build_marker_family':
                source = entry['source']
                self.require_regular(Path(source['path']))
                if self.hash_file(Path(source['path'])) != source['sha256']:
                    raise ValueError('generated marker producer changed during validation')
        copies = _verbatim_input_source_copies(self.rundir, paths, outputs, output_policy, self.resolve_path, input_snapshot=input_snapshot, input_paths=input_paths)
        if copies:
            for entry in output_policy['verbatim_input_source_copies']:
                for pin in (entry['inventory'], entry['source']):
                    self.require_regular(Path(pin['path']))
                    if self.hash_file(Path(pin['path'])) != pin['sha256']:
                        raise ValueError('source copy input changed during validation')
        result = {}
        for value in paths:
            if not isinstance(value, str) or not value.strip():
                raise ValueError('artifact paths must be nonblank strings')
            path, census, files = self.census(value, outputs)
            query = (value, outputs)
            seen = self.queries.get(query)
            current = (str(path), census)
            if seen is not None and seen != current:
                raise ValueError('artifact path or inventory changed during validation: ' + value)
            self.queries[query] = current
            if not files:
                raise ValueError('empty artifact: ' + value)
            entries = []
            for item in files:
                observed = self.observe(item)
                size = observed[3]
                if outputs and size == 0 and (item == path or item not in allowed):
                    raise ValueError('empty output: ' + str(item))
                content_digest = self.hash_file(item)
                if item in copies and (size != copies[item]['size'] or content_digest != copies[item]['sha256']):
                    raise ValueError('verbatim copied source differs from approved input')
                if outputs and item.suffix.lower() == '.json' and item not in copies and observed not in self.valid_json:
                    self.read_json(item)
                    if self.observe(item) != observed:
                        raise ValueError('JSON changed during validation: ' + str(item))
                    self.valid_json.add(observed)
                entries.append({'name': '.' if item == path else item.relative_to(path).as_posix(),
                                'size': size, 'sha256': content_digest})
            if outputs and path.is_dir() and not any(entry['size'] for entry in entries):
                raise ValueError('empty output directory: ' + value)
            if str(path) in result:
                raise ValueError('duplicate artifact path: ' + value)
            result[str(path)] = {'kind': 'file' if path.is_file() else 'directory', 'files': entries}
        if any(not path.is_file() for path in copies):
            raise ValueError('declared verbatim source copy is missing')
        if copies != _verbatim_input_source_copies(self.rundir, paths, outputs, output_policy, self.resolve_path, input_snapshot=input_snapshot, input_paths=input_paths):
            raise ValueError('source-copy declaration changed during validation')
        if allowed != _empty_directory_members(self.rundir, paths, outputs, output_policy, self.resolve_path, input_snapshot=input_snapshot, input_paths=input_paths):
            raise ValueError('empty-member declaration or family changed during validation')
        return result

    def close(self):
        self.closed = True
        self.hashes.clear()
        self.stages.clear()
        self.proofs.clear()
        self.final_checks.clear()
        self.regular_resolutions.clear()
        self.exists_states.clear()
        self.path_identities.clear()
        if hasattr(self, '_readonly_original'):
            self._readonly_original.clear()
            self._readonly_callbacks = ()

    def readonly_freeze(self):
        """Freeze callbacks while every original participant fact remains live."""
        if self.closed or getattr(self, '_readonly_frozen', False):
            raise ValueError('live unfrozen read-only participant required')
        self._readonly_frozen = True
        self._readonly_callbacks = tuple(self.final_checks)
        self._readonly_original = {
            'files': dict(self.files), 'hashes': dict(self.hashes), 'queries': deepcopy(self.queries),
            'regular_resolutions': dict(self.regular_resolutions),
            'regular_paths': frozenset(self.regular_paths),
            'absent': frozenset(self.absent_inventory_paths),
            'exists': dict(self.exists_states),
            'path_identities': dict(self.path_identities),
            'tracked': tuple(self.tracked), 'runtime': deepcopy(self.runtime),
            'ledger': (self.ledger_existed, self.ledger_digest),
            'functions': (self.resolve_path, self.read_json, self.runtime_context, self.digest),
        }

    def _readonly_roster(self):
        if self.closed or not getattr(self, '_readonly_frozen', False):
            raise ValueError('live frozen read-only participant required')
        checks = self._readonly_callbacks
        if (len(checks) != len(self.final_checks)
                or any(a is not b for a, b in zip(checks, self.final_checks))):
            raise ValueError('read-only callback roster changed after freeze')

    def readonly_drain(self):
        self._readonly_roster()
        if getattr(self, '_readonly_drained', False):
            raise ValueError('read-only callbacks already drained')
        self._readonly_drained = True
        for check in self._readonly_callbacks:
            check()
            self._readonly_roster()

    def readonly_terminal(self):
        """Fixed complete check; no callback, close or new intended baseline."""
        self._readonly_roster()
        if not getattr(self, '_readonly_drained', False):
            raise ValueError('all read-only callbacks must drain before terminal check')
        original = self._readonly_original
        if (any(getattr(self, name) is not function for name, function in zip(
                    ('resolve_path', 'read_json', 'runtime_context', 'digest'), original['functions']))
                or any(self.files.get(p) != v for p, v in original['files'].items())
                or any(self.hashes.get(p) != v for p, v in original['hashes'].items())
                or any(self.queries.get(p) != v for p, v in original['queries'].items())
                or any(self.regular_resolutions.get(p) != v for p, v in original['regular_resolutions'].items())
                or not original['regular_paths'] <= self.regular_paths
                or not original['absent'] <= self.absent_inventory_paths
                or any(self.exists_states.get(p) != v for p, v in original['exists'].items())
                or any(self.path_identities.get(p) != v for p, v in original['path_identities'].items())
                or len(self.tracked) < len(original['tracked'])
                or any(a is not b or d != e for (a, d), (b, e) in zip(original['tracked'], self.tracked))
                or self.runtime != original['runtime']
                or (self.ledger_existed, self.ledger_digest) != original['ledger']):
            raise ValueError('original read-only observation commitments changed')
        for path, expected in tuple(self.exists_states.items()):
            if path.exists() != expected:
                raise ValueError('observed path existence changed before read-only return')
        for path in tuple(self.absent_inventory_paths):
            if any(p.is_symlink() for p in (path, *path.parents)) or path.exists():
                raise ValueError('observed absent inventory appeared before read-only return')
        for path in tuple(self.regular_paths):
            self.require_regular(path)
        for (value, outputs), previous in tuple(self.queries.items()):
            path, census, _ = self.census(value, outputs)
            if (str(path), census) != previous:
                raise ValueError('complete read-only directory inventory changed')
        for path, previous in tuple(self.files.items()):
            if self.observe(path) != previous:
                raise ValueError('read-only file changed at terminal check')
        if self.ledger.exists() != original['ledger'][0]:
            raise ValueError('read-only ledger appeared or disappeared')
        if original['ledger'][0]:
            expected = self.files[str(self.ledger)]
            with self.ledger.open('rb') as stream:
                if identity(os.fstat(stream.fileno())) != expected:
                    raise ValueError('read-only ledger descriptor changed')
                actual = hashlib.sha256(stream.read()).hexdigest()
                if identity(os.fstat(stream.fileno())) != expected:
                    raise ValueError('read-only ledger changed during terminal read')
            if self.observe(self.ledger) != expected or actual != original['ledger'][1]:
                raise ValueError('read-only ledger differs from original commitment')
        if self.runtime_context() != original['runtime']:
            raise ValueError('read-only runtime changed before return')
        if any(self.digest(obj) != expected for obj, expected in self.tracked):
            raise ValueError('read-only argument, proposal or result changed')
        for (path, length), expected in tuple(self.path_identities.items()):
            if identity(path.lstat())[:length] != expected:
                raise ValueError('typed path identity changed before read-only return')
        self._readonly_roster()

    def finish(self):
        if self.closed:
            raise ValueError('validation session is already closed')
        try:
            original_path_identities = dict(self.path_identities)
            for path in tuple(self.absent_inventory_paths):
                if any(p.is_symlink() for p in (path, *path.parents)) or path.exists():
                    raise ValueError("observed absent inventory appeared or traverses a symlink before return")
            for path in tuple(self.regular_paths):
                self.require_regular(path)
            for (value, outputs), previous in self.queries.items():
                path, census, _ = self.census(value, outputs)
                if (str(path), census) != previous:
                    raise ValueError('artifact path or directory inventory changed before return: ' + value)
            for path, previous in self.files.items():
                if self.observe(path) != previous:
                    raise ValueError('artifact changed before return: ' + path)
            if self.ledger.exists() != self.ledger_existed:
                raise ValueError('execution ledger appeared or disappeared during validation')
            # A second small byte read binds ledger content as well as identity.
            if self.ledger_existed:
                expected_identity = self.files[str(self.ledger)]
                if self.observe(self.ledger) != expected_identity:
                    raise ValueError('execution ledger changed before final read')
                with self.ledger.open('rb') as stream:
                    if identity(os.fstat(stream.fileno())) != expected_identity:
                        raise ValueError('execution ledger replaced before final read')
                    final_digest = hashlib.sha256(stream.read()).hexdigest()
                    if identity(os.fstat(stream.fileno())) != expected_identity:
                        raise ValueError('execution ledger changed during final read')
                if self.observe(self.ledger) != expected_identity:
                    raise ValueError('execution ledger pathname changed during final read')
                if final_digest != self.ledger_digest:
                    raise ValueError('execution ledger changed during validation')
            if self.runtime_context() != self.runtime:
                raise ValueError('runtime changed during validation')
            if any(self.digest(obj) != before for obj, before in self.tracked):
                raise ValueError('supplied state or plan changed during validation')
            for check in self.final_checks:
                check()
            if self.final_checks:
                for path in tuple(self.regular_paths):
                    self.require_regular(path)
                # Nested readers may observe after the ledger/runtime read.
                # Close original and copied evidence together after those
                # callbacks, without another payload read or cross-call cache.
                for path, previous in self.files.items():
                    if self.observe(path) != previous:
                        raise ValueError('artifact changed during nested final observation: ' + path)
                for (value, outputs), previous in self.queries.items():
                    path, census, _ = self.census(value, outputs)
                    if (str(path), census) != previous:
                        raise ValueError('artifact inventory changed during nested final observation: ' + value)
            # Final callbacks may add facts, but cannot erase or rewrite an
            # earlier reader's typed commitment. Ordinary finish owns this
            # tail separately from readonly_terminal and closes afterward.
            for key, expected in original_path_identities.items():
                if self.path_identities.get(key) != expected:
                    raise ValueError('original typed path commitment changed during final callbacks')
            for (path, length), expected in tuple(self.path_identities.items()):
                if identity(path.lstat())[:length] != expected:
                    raise ValueError('typed path identity changed after final callbacks')
            return []
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return ['validation final census unavailable: ' + str(exc)]
        finally:
            # No reuse after this logical validation call, even following error.
            self.close()
