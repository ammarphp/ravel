"""Explicit selected-environment replay before ordinary study admission.

This capsule stores values, not approval or executable authority. It does not
re-exec Python, adjust imported modules, set unselected variables or launch work.
"""
from contextlib import contextmanager, nullcontext
from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import sys
import threading

from . import execution
from .state_io import read_json

KEYS = {'schema_version', 'kind', 'environment', 'runtime', 'interpreter',
        'stage_fingerprint', 'source_snapshot_sha256'}
MAX_CAPSULE_BYTES = 256 * 1024
_active = False


def _environment(value):
    # Reuse the exact selected-key and digest rules of execution receipts.
    execution._validate_runtime_environment({'runtime_environment': value,
        'runtime': {'environment_sha256': execution.digest(value)}})
    if any(v is not None and '\x00' in v for v in value.values()):
        raise ValueError('prepared environment values cannot contain NUL')
    if len(json.dumps(value).encode()) > MAX_CAPSULE_BYTES // 2:
        raise ValueError('selected environment exceeds capsule limit')
    return deepcopy(value)


def _interpreter(binding):
    spelling = binding['command'][0]
    if spelling != sys.executable or not Path(spelling).is_absolute():
        raise ValueError('use the exact planned Python interpreter spelling; replay never re-execs')
    binary = str(Path(spelling).resolve(strict=True))
    sha = execution.file_hash(binary)
    source = binding['input_snapshot'].get(binary)
    if (type(source) is not dict or source.get('kind') != 'file'
            or len(source.get('files', [])) != 1
            or source['files'][0].get('name') != '.'
            or source['files'][0].get('sha256') != sha):
        raise ValueError('planned interpreter is missing or changed in the input snapshot')
    return {'spelling': spelling, 'resolved': binary, 'sha256': sha}


def capture(binding, *, environment=None):
    """Capture current values or explicit historical values; require planned hash.

    No old plan is rewritten. A caller lacking the original selected values
    cannot recover them from the hash and must prepare a new study instead.
    """
    env = _environment(execution.runtime_environment() if environment is None else environment)
    if execution.digest(env) != binding['runtime']['environment_sha256']:
        raise ValueError('supplied selected values differ from the planned runtime environment hash')
    result = {'schema_version': 1, 'kind': 'prepared-runtime-environment/v1',
              'environment': env, 'runtime': deepcopy(binding['runtime']),
              'interpreter': _interpreter(binding),
              'stage_fingerprint': binding['fingerprint'],
              'source_snapshot_sha256': execution.digest(binding['input_snapshot'])}
    validate(result, binding)
    return result


def validate(capsule, binding, *, live_interpreter=True):
    """Check exact capsule/binding association; ordinary admission checks all sources."""
    if (type(capsule) is not dict or set(capsule) != KEYS
            or type(capsule['schema_version']) is not int or capsule['schema_version'] != 1
            or capsule['kind'] != 'prepared-runtime-environment/v1'):
        raise ValueError('closed prepared runtime capsule schema required')
    if binding['fingerprint'] != execution.digest({k: v for k, v in binding.items() if k != 'fingerprint'}):
        raise ValueError('planned stage fingerprint is inconsistent')
    _environment(capsule['environment'])
    execution._validate_runtime_environment({'runtime_environment': capsule['environment'],
                                            'runtime': binding['runtime']})
    interpreter = capsule['interpreter']
    if (type(interpreter) is not dict or set(interpreter) != {'spelling', 'resolved', 'sha256'}
            or interpreter['spelling'] != binding['command'][0]
            or any(type(v) is not str or not v for v in interpreter.values())
            or not Path(interpreter['spelling']).is_absolute()
            or not Path(interpreter['resolved']).is_absolute()):
        raise ValueError('closed planned interpreter binding required')
    source = binding['input_snapshot'].get(interpreter['resolved'])
    if (type(source) is not dict or source.get('kind') != 'file'
            or len(source.get('files', [])) != 1
            or source['files'][0].get('name') != '.'
            or source['files'][0].get('sha256') != interpreter['sha256']):
        raise ValueError('capsule interpreter differs from the planned input snapshot')
    if (capsule['runtime'] != binding['runtime']
            or capsule['stage_fingerprint'] != binding['fingerprint']
            or capsule['source_snapshot_sha256'] != execution.digest(binding['input_snapshot'])
            or live_interpreter and capsule['interpreter'] != _interpreter(binding)):
        raise ValueError('prepared capsule differs from planned source/runtime/interpreter binding')
    return deepcopy(capsule)


def validate_plan(proposal):
    """Optional field keeps historical proposals inspectable and unchanged."""
    if 'prepared_runtime' in proposal:
        validate(proposal['prepared_runtime'], proposal['stage_binding'])


def _ordinary(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('capsule path must not traverse symlinks')


def read_capsule(path):
    """Bound allocation; check descriptor/path identity and ending ancestor aliases."""
    path = Path(path).expanduser().absolute()
    _ordinary(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_CAPSULE_BYTES:
        raise ValueError('capsule must be a bounded regular file')
    ident = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    with path.open('rb') as stream:
        if ident(os.fstat(stream.fileno())) != ident(before):
            raise ValueError('capsule changed while opening')
        data = stream.read(MAX_CAPSULE_BYTES + 1)
        if len(data) > MAX_CAPSULE_BYTES or ident(os.fstat(stream.fileno())) != ident(before):
            raise ValueError('capsule changed or exceeded limit while reading')
    _ordinary(path)
    if ident(path.stat()) != ident(before):
        raise ValueError('capsule changed while reading')
    # Capsule schemas need at most three levels. Bound nesting before decoding,
    # independent of interpreter-specific JSON recursion behavior.
    depth, quoted, escaped = 0, False, False
    for char in data:
        if quoted:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                quoted = False
        elif char == 34:
            quoted = True
        elif char in (123, 91):
            depth += 1
            if depth > 32:
                raise ValueError('capsule JSON nesting exceeds 32 levels')
        elif char in (125, 93):
            depth -= 1
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError('duplicate capsule JSON key')
            out[key] = value
        return out
    try:
        return json.loads(data, object_pairs_hook=unique,
                          parse_constant=lambda v: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    except (RecursionError, UnicodeError) as exc:
        raise ValueError('capsule JSON nesting or encoding is invalid') from exc


def load_plan(rundir):
    rd = Path(rundir).expanduser().absolute()
    _ordinary(rd)
    paths = [rd / 'inputs/science-plan.json', rd / 'inputs/scoped-plan.json']
    existing = [p for p in paths if p.exists()]
    if len(existing) != 1:
        raise ValueError('exactly one ordinary science or scoped plan required')
    _ordinary(existing[0])
    return read_json(existing[0])


def for_plan(rundir, *, environment=None):
    """Inspect embedded values or explicitly capture values for a legacy plan."""
    p = load_plan(rundir)
    if 'prepared_runtime' in p and environment is None:
        return validate(p['prepared_runtime'], p['stage_binding'])
    return capture(p['stage_binding'], environment=environment)


@contextmanager
def replay(rundir, *, capsule_path=None):
    """Temporarily restore only eight keys for an explicitly opted-in operation.

    Calls must be on the main thread, non-nested, in a dedicated CLI process.
    Concurrent environment mutation is outside this API's contract. Normal
    approve/run still verifies command, packages, platform, source and inputs.
    """
    global _active
    if sys.flags.optimize or threading.current_thread() is not threading.main_thread() or _active:
        raise ValueError('runtime replay requires ordinary main-thread non-nested Python')
    proposal = load_plan(rundir)
    if capsule_path is None:
        if 'prepared_runtime' not in proposal:
            raise ValueError('legacy plan has no retained values; supply an exact explicit runtime capsule')
        candidate = proposal['prepared_runtime']
    else:
        candidate = read_capsule(capsule_path)
        if 'prepared_runtime' in proposal and candidate != proposal['prepared_runtime']:
            raise ValueError('external capsule cannot replace the retained prepared values')
    capsule = validate(candidate, proposal['stage_binding'])
    before = execution.runtime_environment()
    _active = True
    try:
        for key, value in capsule['environment'].items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield capsule
    finally:
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _active = False


def selected_context(rundir, *, enabled=False, capsule_path=None):
    if capsule_path is not None and not enabled:
        raise ValueError('--runtime-capsule requires explicit --replay-runtime')
    return replay(rundir, capsule_path=capsule_path) if enabled else nullcontext()
