"""Which RAVEL code a controller runs, and whether controller mode may run it.

Controller mode runs installed or sealed RAVEL code only. A source checkout or an editable
install can be changed by anything that writes the checkout, and a user-writable installation by
anything that runs as its user, so each is refused with the commands that fix it.
``ravel governed-runtime seal`` copies the imported package into a read-only runtime in the
controller home (``<controller home>/runtime/<id>/site/ravel``, outside every worker's reach) and
records its digests in ``SEAL.json`` beside it. Code that runs from such a runtime is ``sealed``
while its live source and bytecode still equal that record; every admission recomputes them.
``RAVEL_ROOT`` (which redirects data lookups to a checkout) and the other selectors are refused
the same way. The toolchain and addon selectors are recorded with the identity; confined launches
never receive them. ``development=True`` is an internal labelling mode (no controller entry
offers it): the identity is returned labelled ``NOT GOVERNED`` instead of refused.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import stat
import sysconfig
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

NOT_GOVERNED = 'NOT GOVERNED'
SELECTORS = ('RAVEL_ROOT', 'RAVEL_ADDON_PATH', 'RAVEL_NATIVE_BIN', 'RAVEL_NATIVE_BUILD', 'BUILD_DIR')
# The distribution name pyproject.toml declares first, then the import name.
DISTRIBUTIONS = ('ravel-hep', 'ravel')
GOVERNED_KINDS = ('installed', 'sealed')
# A sealed runtime is <controller home>/runtime/<first 16 hex of its tree digest>/ with SEAL.json,
# site/ravel and bin/ravel (ravel.setup.governed_runtime writes it).
RUNTIME_DIRECTORY = 'runtime'
SEAL_FILE = 'SEAL.json'
SEAL_SCHEMA = 'ravel-governed-runtime.v1'
SEAL_COMMAND = 'ravel governed-runtime seal'
MAX_SEAL_BYTES = 1024 * 1024


class UngovernedInstall(ValueError):
    """Controller mode refuses this RAVEL installation; nothing was started.

    ``problems`` lists what is wrong and ``fix`` is the first command of the remedy."""

    def __init__(self, message, *, problems=(), fix=None):
        super().__init__(message)
        self.problems, self.fix = list(problems), fix


def _distribution():
    for name in DISTRIBUTIONS:
        try:
            return importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return None


def _editable(distribution, package):
    """True when ``distribution`` is an editable install of the project that holds ``package``.

    An editable install records the project directory it points at (``direct_url.json``). A package
    elsewhere is a checkout of its own, whatever else is installed in the environment."""
    if distribution is None:
        return False
    try:
        text = distribution.read_text('direct_url.json')
    except (OSError, ValueError):
        text = None
    if not text:
        return False
    try:
        record = json.loads(text)
        if record.get('dir_info', {}).get('editable') is not True:
            return False
        url = urlparse(record.get('url') or '')
    except (ValueError, AttributeError):
        return True
    if url.scheme != 'file':
        return True
    return package.is_relative_to(Path(os.path.realpath(url2pathname(unquote(url.path)))))


def _site_directories():
    roots = {sysconfig.get_path(name) for name in ('purelib', 'platlib')}
    import site
    roots |= set(site.getsitepackages() if hasattr(site, 'getsitepackages') else ())
    roots.add(site.getusersitepackages())
    return [Path(os.path.realpath(r)) for r in roots if r]


def _checkout(package):
    """The source checkout that holds ``package`` (``<checkout>/src/ravel``), or None."""
    for parent in package.parents:
        if (parent / '.git').exists() or ((parent / 'pyproject.toml').is_file() and (parent / 'src').is_dir()):
            return parent
    return None


def _tree_digest(package):
    rows = []
    for path in sorted(package.rglob('*')):
        if path.is_file() and not path.is_symlink() and '__pycache__' not in path.parts:
            rows.append([path.relative_to(package).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()])
    return hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()


def _bytecode_digest(package):
    """The digest of every file in the ``__pycache__`` directories of ``package`` (what imports execute)."""
    rows = []
    for path in sorted(package.rglob('*')):
        relative = path.relative_to(package)
        if '__pycache__' in relative.parts and path.is_file() and not path.is_symlink():
            rows.append([relative.as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()])
    return 'bytecode:' + hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()


def runtime_root():
    """``<controller home>/runtime``, where sealed runtimes live (the controller home is outside every sandbox).

    Neither the controller home nor its runtime directory may be a symbolic link: a link would move
    the seals somewhere a worker might write."""
    from ravel.controller.authority.operator import controller_home
    home = controller_home()
    for path in (home, home / RUNTIME_DIRECTORY):
        if path.is_symlink():
            raise ValueError(f'{path} must not be a symbolic link')
    return Path(os.path.realpath(home / RUNTIME_DIRECTORY))


def runtime_id(digest):
    """The directory name of the runtime that seals ``digest`` (``tree:<sha256>``): its first 16 hex digits."""
    kind, _, value = str(digest).partition(':')
    if kind != 'tree' or len(value) != 64 or value.strip('0123456789abcdef'):
        raise ValueError('a sealed runtime is named by a tree digest')
    return value[:16]


def read_seal(runtime):
    """The ``SEAL.json`` record of ``runtime``: a bounded regular file, never read through a link."""
    path = Path(runtime) / SEAL_FILE
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SEAL_BYTES:
            raise ValueError(f'{path} is not a bounded regular file')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            raw = stream.read(MAX_SEAL_BYTES + 1)
    finally:
        os.close(descriptor)
    seal = json.loads(raw)
    if type(seal) is not dict or seal.get('schema') != SEAL_SCHEMA:
        raise ValueError(f'{path} is not a {SEAL_SCHEMA} record')
    return seal


def _runtime_of(package):
    """The runtime directory when ``package`` is ``<runtime root>/<id>/site/ravel``; else None."""
    if package.name != 'ravel' or package.parent.name != 'site':
        return None
    runtime = package.parent.parent
    try:
        return runtime if runtime.parent == runtime_root() else None
    except (OSError, ValueError):
        return None


def _sealed(package, runtime, tree):
    """The seal of ``runtime`` when ``package``'s live tree and bytecode still equal it; else None."""
    try:
        seal = read_seal(runtime)
        name = runtime_id(tree)
    except (OSError, ValueError):
        return None
    if (seal.get('digest') != tree or seal.get('runtime_id') != name or runtime.name != name
            or (seal.get('bytecode') or {}).get('digest') != _bytecode_digest(package)):
        return None
    return seal


def _imported_package():
    import ravel
    return Path(os.path.realpath(ravel.__file__)).parent


def code_identity(*, digest=True):
    """The running RAVEL code: location, kind (installed, sealed, editable, checkout or unpackaged), writability, digest."""
    return package_identity(_imported_package(), digest=digest)


def package_identity(package, *, digest=True):
    """The identity of the RAVEL package at ``package``, as ``code_identity`` reports the imported one.

    ``sealed`` needs the live tree digest, so it is computed for a runtime layout even when
    ``digest`` is False (and then not reported)."""
    package = Path(os.path.realpath(package))
    runtime = _runtime_of(package)
    tree = 'tree:' + _tree_digest(package) if digest or runtime is not None else None
    seal = _sealed(package, runtime, tree) if runtime is not None else None
    distribution = None if seal is not None else _distribution()
    installed = seal is None and any(package.is_relative_to(root) for root in _site_directories())
    # The distribution's metadata describes the imported package only when it is the one installed there.
    editable = _editable(distribution, package) and not installed
    checkout = None if installed or seal is not None else _checkout(package)
    if seal is not None:
        kind = 'sealed'
    elif editable:
        kind = 'editable'
    elif installed:
        kind = 'installed'
    else:
        kind = 'checkout' if checkout is not None else 'unpackaged'
    record = None
    if distribution is not None and installed:
        try:
            record = distribution.read_text('RECORD')
        except (OSError, ValueError):
            record = None
    if seal is not None:
        version = seal.get('ravel_version')
    else:
        version = distribution.version if distribution is not None else None
    identity = {'package_dir': str(package), 'kind': kind, 'version': version,
                'checkout': str(checkout) if checkout is not None else None,
                'writable_by_controller_user': any(os.access(p, os.W_OK) for p in (package, package.parent))
                    or any(os.access(p, os.W_OK) for p in package.rglob('*') if '__pycache__' not in p.parts),
                'symlinks': sorted(str(p.relative_to(package)) for p in package.rglob('*') if p.is_symlink()),
                'selectors': {name: os.environ[name] for name in SELECTORS if os.environ.get(name)}}
    if seal is not None:
        identity['runtime_id'] = runtime.name
        identity['runtime_dir'] = str(runtime)
        source = seal.get('source') if isinstance(seal.get('source'), dict) else {}
        identity['sealed_from'] = {'package_dir': source.get('package_dir'), 'kind': source.get('kind')}
    if digest:
        # RECORD is distribution metadata; it does not prove the bytes currently imported.
        identity['digest'] = tree
        sealed_record = ((seal or {}).get('distribution') or {}).get('record_sha256')
        if record:
            identity['distribution_record_sha256'] = hashlib.sha256(record.encode()).hexdigest()
        elif sealed_record:
            identity['distribution_record_sha256'] = sealed_record
    return identity


def _launcher(identity):
    """The sealed launcher the seal of ``identity``'s bytes provides (its path once sealed)."""
    try:
        name = runtime_id(identity.get('digest'))
        return str(runtime_root() / name / 'bin' / 'ravel')
    except (OSError, ValueError):
        return '<controller home>/runtime/<id>/bin/ravel'


def remedy(identity):
    """``(text, first command)``: the commands that make ``identity`` admissible, each a real command."""
    steps = []
    if identity.get('selectors'):
        command = 'unset ' + ' '.join(sorted(identity['selectors']))
        steps.append((f'`{command}` (controller mode never takes code or toolchain locations from the environment)',
                      command))
    if identity.get('symlinks'):
        steps.append(('reinstall RAVEL without symbolic links (`bash scripts/setup/install.sh` in the checkout)',
                      'bash scripts/setup/install.sh'))
    if identity['kind'] not in GOVERNED_KINDS or identity.get('writable_by_controller_user') is not False:
        steps.append((f'seal this code with `{SEAL_COMMAND}`; ravel ask and ravel drive then run the sealed copy '
                      f'through its launcher `{_launcher(identity)}`', SEAL_COMMAND))
    if not steps:
        return '', None
    return 'To start a governed run, ' + '; '.join(text for text, _ in steps) + '.', steps[0][1]


def require_governed_install(*, development=False, identity=None):
    """The identity controller mode may run: installed or sealed code that is read-only, has no symbolic
    links and is not redirected by a selector; anything else is refused with the commands that fix it.

    With ``development=True`` the identity is returned with ``label = NOT GOVERNED`` instead.
    """
    identity = dict(identity or code_identity())
    problems = []
    if identity['kind'] not in GOVERNED_KINDS:
        problems.append(f'RAVEL runs from {identity["kind"]} code at {identity["package_dir"]}')
    if identity.get('writable_by_controller_user') is not False:
        problems.append('RAVEL installation or its containing directory is writable or unverified')
    if identity.get('symlinks'):
        problems.append('RAVEL installation contains symbolic links')
    if identity['selectors']:
        problems.append('environment selectors redirect installed code or toolchain: ' +
                        ', '.join(sorted(identity['selectors'])))
    if problems and not development:
        text, fix = remedy(identity)
        raise UngovernedInstall('controller mode runs only installed or sealed RAVEL code (' + '; '.join(problems)
                                + '); nothing was started. ' + text, problems=problems, fix=fix)
    identity['governed'] = not problems
    identity['label'] = NOT_GOVERNED if problems else None
    identity['problems'] = problems
    return identity
