"""``ravel governed-runtime``: the sealed, read-only RAVEL runtime that controller mode admits.

``seal`` copies the imported ``ravel`` package (the bytes ``confine.identity`` digests) into
``<controller home>/runtime/<id>/site/ravel``, where ``<id>`` is the first 16 hex digits of its
tree digest. It byte-compiles the copy (hash-checked bytecode), writes the seal record
``SEAL.json`` (schema ``ravel-governed-runtime.v1``) and the launcher ``bin/ravel`` beside
``site/``, removes every write bit bottom-up (files 0444, the launcher and directories 0555) and
records the runtime as current in the regular file ``<controller home>/runtime/CURRENT``. The
launcher runs the sealing interpreter isolated (``-I``) with the sealed ``site`` first on
``sys.path``. Sealing identical bytes again reuses the runtime.

``status`` reports the current runtime, whether it holds the imported package's bytes, and the
admission ``ravel ask`` and ``ravel drive --request-file`` get (``admission``): the imported code
when it is governed; else the current runtime when it holds the same tree digest and passes the
same identity check (the entries then re-execute through its launcher); else the refusal and its
fix. Neither command reads a request or starts a run.

The controller home is fixed by the password database and lies outside every worker sandbox, so
worker writes cannot reach the copy, its seal or the pointer, and every admission recomputes the
copy's digests against its seal. A process running unconfined as the same user can restore write
bits; the digest check then refuses the changed copy. Like the rest of this package, the module
imports only the standard library at import time.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import py_compile
import re
import shlex
import shutil
import stat
import sys
import tempfile

STATUS_SCHEMA = 'ravel-governed-runtime-status.v1'
CURRENT = 'CURRENT'
LOCK = '.seal.lock'
NAME = re.compile(r'[0-9a-f]{16}')
LAYOUT = ('SEAL.json', 'bin', 'site')
FILE_MODE, LAUNCHER_MODE, DIRECTORY_MODE = 0o444, 0o555, 0o555
MODE_PROBLEM = 'modes differ from the seal on '


class SealRefused(ValueError):
    """Nothing was sealed or made current; the message names the fix."""


def _identity():
    from ravel.controller.confine import identity
    return identity


# ---- sealing ----------------------------------------------------------------------------------

def _members(package):
    """``(directories, files)`` of the tree ``identity`` digests, relative to ``package``; links refuse."""
    if not (package / '__init__.py').is_file():
        raise SealRefused(f'{package} is not a ravel package')
    directories, files = [], []
    for path in sorted(package.rglob('*')):
        relative = path.relative_to(package)
        if '__pycache__' in relative.parts:
            continue
        if path.is_symlink():
            raise SealRefused(f'{path} is a symbolic link and a sealed runtime holds regular files only; reinstall '
                              'RAVEL (`bash scripts/setup/install.sh` in the checkout) and seal again')
        if path.is_dir():
            directories.append(relative)
        elif path.is_file():
            files.append(relative)
        else:
            raise SealRefused(f'{path} is neither a regular file nor a directory')
    return directories, files


def launcher_text(python, runtime):
    """The launcher of ``runtime``: its sealing interpreter, isolated, with the sealed site first on the path."""
    runtime = Path(runtime)
    site, launcher = runtime / 'site', runtime / 'bin' / 'ravel'
    code = (f'import sys; sys.argv[0] = {json.dumps(str(launcher))}; sys.path.insert(0, {json.dumps(str(site))}); '
            'from ravel.cli import main; raise SystemExit(main())')
    return ('#!/bin/sh\n'
            '# RAVEL governed runtime: the sealed package in ../site, run by the interpreter that sealed it\n'
            '# in isolated mode (no PYTHON* variables, user site or working directory on the path).\n'
            f'exec {shlex.quote(python)} -I -c {shlex.quote(code)} "$@"\n').encode()


def _compile(package, files, final):
    """Write hash-checked bytecode for every module; returns the modules that do not compile."""
    tag = sys.implementation.cache_tag
    modules = [relative for relative in files if relative.suffix == '.py']
    if tag is None:
        return [relative.as_posix() for relative in modules]
    failed = []
    for relative in modules:
        source = package / relative
        target = source.parent / '__pycache__' / f'{source.stem}.{tag}.pyc'
        try:
            py_compile.compile(str(source), cfile=str(target), dfile=str(final / relative), doraise=True,
                               invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)
        except py_compile.PyCompileError:
            failed.append(relative.as_posix())
    return failed


def _record(source, name, tree, python, bytecode, failed):
    identity = _identity()
    import ravel
    found = identity.package_identity(source)
    distribution = None
    if found['kind'] == 'installed':
        located = identity._distribution()
        if located is not None:
            distribution = {'name': located.metadata['Name'], 'version': located.version,
                            'record_sha256': found.get('distribution_record_sha256')}
    elif found['kind'] == 'sealed':
        distribution = identity.read_seal(Path(found['runtime_dir'])).get('distribution')
    version = ravel.__version__ if source == identity._imported_package() else found.get('version')
    return {'schema': identity.SEAL_SCHEMA, 'runtime_id': name, 'digest': tree,
            'bytecode': {'digest': bytecode, 'invalidation': 'checked-hash', 'cache_tag': sys.implementation.cache_tag,
                         'not_compiled': failed},
            'ravel_version': version, 'source': {'package_dir': str(source), 'kind': found['kind']},
            'distribution': distribution,
            'python': {'executable': python, 'version': platform.python_version(),
                       'implementation': sys.implementation.name},
            'created_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}


def _expected_mode(runtime, path):
    if path.is_dir():
        return DIRECTORY_MODE
    return LAUNCHER_MODE if path == runtime / 'bin' / 'ravel' else FILE_MODE


def _read_only(runtime, *, top):
    """Set the sealed modes bottom-up (files 0444, the launcher and directories 0555)."""
    for parent, directories, files in os.walk(runtime, topdown=False):
        for name in files + directories:
            path = Path(parent, name)
            os.chmod(path, _expected_mode(runtime, path))
    if top:
        os.chmod(runtime, DIRECTORY_MODE)


def _discard(path):
    """Remove a staging tree this seal made, restoring the write bits its removal needs."""
    if os.path.islink(path) or not os.path.isdir(path):
        return
    for parent, _, _ in os.walk(path):
        os.chmod(parent, 0o700)
    shutil.rmtree(path, ignore_errors=True)


def _set_aside(runtime):
    quoted = shlex.quote(str(runtime))
    return (f'it is kept as evidence and was not made current; move it aside with `chmod -R u+w {quoted} && mv '
            f'{quoted} {shlex.quote(str(runtime) + ".set-aside")}` and run `ravel governed-runtime seal` again')


def _build(source, runtime, tree, directories, files, python):
    identity = _identity()
    staging = Path(tempfile.mkdtemp(prefix=f'.seal-{runtime.name}-', dir=runtime.parent))
    try:
        package = staging / 'site' / 'ravel'
        package.mkdir(parents=True)
        for relative in directories:
            (package / relative).mkdir(parents=True, exist_ok=True)
        for relative in files:
            shutil.copyfile(source / relative, package / relative, follow_symlinks=False)
        if 'tree:' + identity._tree_digest(package) != tree:
            raise SealRefused(f'{source} changed while it was copied; nothing was sealed; seal again')
        failed = _compile(package, files, runtime / 'site' / 'ravel')
        record = _record(source, runtime.name, tree, python, identity._bytecode_digest(package), failed)
        (staging / identity.SEAL_FILE).write_text(json.dumps(record, indent=2, sort_keys=True) + '\n',
                                                  encoding='utf-8')
        (staging / 'bin').mkdir()
        (staging / 'bin' / 'ravel').write_bytes(launcher_text(python, runtime))
        _read_only(staging, top=False)
        # A directory without write permission cannot be renamed on every platform: the top one is sealed last.
        os.rename(staging, runtime)
    except BaseException:
        _discard(staging)
        raise
    os.chmod(runtime, DIRECTORY_MODE)
    problems = verify(runtime)
    if problems:
        raise SealRefused(f'the new runtime {runtime} does not verify ({"; ".join(problems)}); ' + _set_aside(runtime))


def _reuse(runtime, python):
    identity = _identity()
    try:
        recorded = (identity.read_seal(runtime).get('python') or {}).get('executable')
    except (OSError, ValueError):
        recorded = None
    if recorded is not None and recorded != python:
        raise SealRefused(f'the runtime {runtime} holding these bytes was sealed for the interpreter {recorded}, '
                          f'not {python}; ' + _set_aside(runtime))
    problems = verify(runtime)
    if problems and all(problem.startswith(MODE_PROBLEM) for problem in problems):
        _read_only(runtime, top=True)  # the bytes still equal their seal; only the modes changed
        problems = verify(runtime)
    if problems:
        raise SealRefused(f'the runtime {runtime} holding these bytes no longer verifies ({"; ".join(problems)}); '
                          + _set_aside(runtime))


def _point(root, runtime):
    """Record ``runtime`` as current: a regular file naming its directory, replaced atomically."""
    temporary = root / f'.{CURRENT}.{os.getpid()}'
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        stream.write(str(runtime) + '\n')
    os.replace(temporary, root / CURRENT)


def seal(*, package=None):
    """Seal ``package`` (default: the imported ``ravel``) and make it the current runtime; returns its record."""
    identity = _identity()
    source = Path(os.path.realpath(package)) if package is not None else identity._imported_package()
    python = sys.executable
    if not python or not os.path.isabs(python) or not os.access(python, os.X_OK):
        raise SealRefused('the interpreter that seals RAVEL needs an absolute, executable path')
    directories, files = _members(source)
    tree = 'tree:' + identity._tree_digest(source)
    name = identity.runtime_id(tree)
    root = identity.runtime_root()
    from ravel.controller.authority.operator import private_dir
    from ravel.workflow.state_io import file_lock
    private_dir(root)
    with file_lock(root / LOCK):
        runtime = root / name
        reused = os.path.lexists(runtime)
        if reused:
            _reuse(runtime, python)
        else:
            _build(source, runtime, tree, directories, files, python)
        _point(root, runtime)
    return {'runtime_id': name, 'runtime_dir': str(runtime), 'launcher': str(runtime / 'bin' / 'ravel'),
            'current': str(root / CURRENT), 'reused': reused, 'seal': identity.read_seal(runtime)}


# ---- inspection -------------------------------------------------------------------------------

def verify(runtime):
    """Every way ``runtime`` differs from what its seal wrote; empty when it verifies."""
    identity = _identity()
    runtime = Path(runtime)
    try:
        info = os.lstat(runtime)
    except OSError as exc:
        return [f'{runtime} is missing ({exc.strerror})']
    if not stat.S_ISDIR(info.st_mode):
        return [f'{runtime} is not a directory']
    try:
        seal = identity.read_seal(runtime)
    except (OSError, ValueError) as exc:
        return [f'its seal record is unreadable ({exc})']
    entries = sorted(os.listdir(runtime))
    if entries != sorted(LAYOUT):
        return [f'it holds {", ".join(entries)} instead of {", ".join(LAYOUT)}']
    links = sorted(str(p.relative_to(runtime)) for p in runtime.rglob('*') if p.is_symlink())
    if links:
        return ['it contains symbolic links: ' + ', '.join(links[:5])]
    package, launcher = runtime / 'site' / 'ravel', runtime / 'bin' / 'ravel'
    try:
        layout = os.listdir(runtime / 'site') == ['ravel'] == os.listdir(runtime / 'bin')
    except OSError:
        layout = False
    if not layout or not package.is_dir() or not launcher.is_file():
        return ['it must hold exactly the directory site/ravel and the file bin/ravel']
    problems = []
    try:
        named = identity.runtime_id(seal.get('digest'))
    except ValueError:
        named = None
    if named != runtime.name or seal.get('runtime_id') != runtime.name:
        problems.append('it is not named by its seal digest')
    if 'tree:' + identity._tree_digest(package) != seal.get('digest'):
        problems.append('its source differs from the seal digest')
    if identity._bytecode_digest(package) != (seal.get('bytecode') or {}).get('digest'):
        problems.append('its bytecode differs from the seal digest')
    python = (seal.get('python') or {}).get('executable')
    if type(python) is not str or launcher.read_bytes() != launcher_text(python, runtime):
        problems.append('its launcher differs from the one the seal wrote')
    elif not os.access(python, os.X_OK):
        problems.append(f'its interpreter {python} is missing')
    changed = [p for p in (runtime, *runtime.rglob('*'))
               if stat.S_IMODE(os.lstat(p).st_mode) != (DIRECTORY_MODE if p == runtime else _expected_mode(runtime, p))]
    if changed:
        shown = ', '.join(str(p.relative_to(runtime.parent)) for p in changed[:3])
        problems.append(MODE_PROBLEM + shown + (f' and {len(changed) - 3} more' if len(changed) > 3 else ''))
    return problems


def _unusable(pointer, why):
    return {'runtime_id': None, 'runtime_dir': None, 'package_dir': None, 'launcher': None, 'seal': None,
            'problems': [f'the current-runtime pointer {pointer} {why}']}


def current():
    """The current runtime ``{runtime_id, runtime_dir, package_dir, launcher, seal, problems}``; None when none."""
    identity = _identity()
    root = identity.runtime_root()
    pointer = root / CURRENT
    try:
        descriptor = os.open(pointer, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError as exc:
        return _unusable(pointer, f'cannot be read as a regular file ({exc.strerror})')
    try:
        info = os.fstat(descriptor)
        raw = os.read(descriptor, 4096) if stat.S_ISREG(info.st_mode) else b''
    finally:
        os.close(descriptor)
    named = Path(raw.decode('utf-8', 'replace').strip()) if raw.strip() else None
    if named is None or named.parent != root or not NAME.fullmatch(named.name):
        return _unusable(pointer, f'does not name a runtime directory in {root}')
    found = {'runtime_id': named.name, 'runtime_dir': str(named), 'package_dir': str(named / 'site' / 'ravel'),
             'launcher': str(named / 'bin' / 'ravel'), 'seal': None, 'problems': verify(named)}
    try:
        found['seal'] = identity.read_seal(named)
    except (OSError, ValueError):
        pass
    return found


def _decision(status, runs, found, *, runtime_id=None, launcher=None, reason=None, fix=None):
    return {'status': status, 'runs': runs, 'package_dir': found.get('package_dir'), 'kind': found.get('kind'),
            'runtime_id': runtime_id, 'launcher': launcher, 'reason': reason,
            'fix': None if status == 'ready' else fix or _identity().SEAL_COMMAND}


def admission(check=None):
    """The admission ``ravel ask`` and ``ravel drive --request-file`` get for the code they would run.

    ``check`` is the identity check (``confine.identity.require_governed_install`` unless the
    controller's confinement service supplies another). Returns ``{status: ready|not-ready, runs:
    imported|sealed, package_dir, kind, runtime_id, launcher, reason, fix}``; ``runs: sealed`` with
    ``ready`` means the entry re-executes through ``launcher``."""
    identity = _identity()
    check = check or identity.require_governed_install
    try:
        admitted = check()
    except ValueError as exc:
        refusal, fix = str(exc), getattr(exc, 'fix', None)
    else:
        return _decision('ready', 'imported', admitted, runtime_id=admitted.get('runtime_id'))
    package = identity._imported_package()
    note = None
    try:
        runtime = current()
    except (OSError, ValueError) as exc:
        runtime, note = None, f'the sealed runtimes cannot be read: {exc}'
    if runtime is not None and runtime['package_dir'] != str(package):
        if runtime['problems']:
            note = 'the current sealed runtime does not verify: ' + '; '.join(runtime['problems'])
        elif (runtime['seal'] or {}).get('digest') != 'tree:' + identity._tree_digest(package):
            sealed = runtime['seal'] or {}
            note = (f'the current sealed runtime {runtime["runtime_id"]} holds RAVEL {sealed.get("ravel_version")} '
                    f'sealed {sealed.get("created_utc")}, not the bytes imported here')
        else:
            try:
                sealed = check(identity=identity.package_identity(runtime['package_dir']))
            except ValueError as exc:
                return _decision('not-ready', 'sealed', {'package_dir': runtime['package_dir'], 'kind': None},
                                 runtime_id=runtime['runtime_id'], reason=str(exc), fix=getattr(exc, 'fix', None))
            return _decision('ready', 'sealed', sealed, runtime_id=runtime['runtime_id'], launcher=runtime['launcher'])
    return _decision('not-ready', 'imported', {'package_dir': str(package), 'kind': None},
                     reason=refusal + (f' ({note})' if note else ''), fix=fix)


def status():
    """The current runtime, whether it holds the imported package's bytes, and the admission decision."""
    identity = _identity()
    imported = identity.code_identity()
    runtime = current()
    holds = (runtime is not None and not runtime['problems']
             and (runtime['seal'] or {}).get('digest') == imported.get('digest'))
    return {'schema': STATUS_SCHEMA,
            'imported': {key: imported.get(key) for key in ('package_dir', 'kind', 'version', 'digest', 'runtime_id',
                                                            'writable_by_controller_user')},
            'current': runtime, 'matches_imported': holds, 'admission': admission()}


def parser():
    ap = argparse.ArgumentParser(prog='ravel governed-runtime',
                                 description='Seal RAVEL into the read-only runtime controller mode admits, or show it.')
    sub = ap.add_subparsers(dest='command', required=True)
    sub.add_parser('seal', help='copy the imported RAVEL into a sealed read-only runtime in the controller home '
                                'and make it current')
    sub.add_parser('status', help='show the current runtime, whether it holds the imported RAVEL and what '
                                  'controller admission decides')
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = seal() if args.command == 'seal' else status()
    except (OSError, ValueError) as exc:
        print(f'ravel governed-runtime {args.command}: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if args.command == 'seal' or result['admission']['status'] == 'ready' else 1


if __name__ == '__main__':
    raise SystemExit(main())
