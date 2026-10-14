"""Find separately licensed programs (for example GPL programs) outside the RAVEL package.

RAVEL is Apache-2.0. Programs derived from GPL sources are kept in separately licensed directories: the
installer fetches and builds them, and RAVEL only exchanges files with the built
program. A component is a directory ``<name>/`` holding ``addon.json``::

    {"schema_version": 1, "name": "<name>", "license": "<SPDX id>", "summary": "...",
     "files": {"<member>": "<sha256>", ...}}

Search order (first match wins):

1. each directory in ``RAVEL_ADDON_PATH`` (``os.pathsep``-separated);
2. ``$RAVEL_NATIVE_BUILD/addons``;
3. the shared native build, ``${XDG_DATA_HOME:-~/.local/share}/ravel-native/addons``;
4. ``addons/gpl`` and ``addons`` in a RAVEL source checkout.

Every declared member is checked against its sha256 and must not be a symlink.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re

ENV = 'RAVEL_ADDON_PATH'
MANIFEST = 'addon.json'
_NAME = re.compile(r'^[a-z0-9][a-z0-9._-]{0,63}$')
_SHA = re.compile(r'^[0-9a-f]{64}$')


class AddonNotFound(FileNotFoundError):
    pass


@dataclass(frozen=True)
class Addon:
    name: str
    root: Path
    license: str
    manifest: dict = field(repr=False)

    def path(self, member):
        if member not in self.manifest['files']:
            raise KeyError(f'{member!r} is not a declared member of component {self.name}')
        return self.root / member

    def members(self):
        return {name: self.root / name for name in self.manifest['files']}

    def identity(self):
        return {'name': self.name, 'root': str(self.root), 'license': self.license,
                'manifest_sha256': hashlib.sha256((self.root / MANIFEST).read_bytes()).hexdigest(),
                'files': dict(self.manifest['files'])}


def search_roots(env=None, *, include_defaults=True):
    env = os.environ if env is None else env
    roots = [Path(p).expanduser() for p in env.get(ENV, '').split(os.pathsep) if p.strip()]
    if env.get('RAVEL_NATIVE_BUILD'):
        roots.append(Path(env['RAVEL_NATIVE_BUILD']).expanduser() / 'addons')
    if include_defaults:
        from ravel.paths import repository_root, shared_native_build
        roots.append(shared_native_build() / 'addons')
        checkout = repository_root()
        if checkout is not None:
            roots += [checkout / 'addons/gpl', checkout / 'addons']
    unique = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def load(directory, name=None):
    """Read and verify one component directory."""
    directory = Path(directory)
    if any(p.is_symlink() for p in (directory, directory / MANIFEST)):
        raise ValueError(f'component {directory} must not be a symlink')
    manifest = json.loads((directory / MANIFEST).read_text(encoding='utf-8'))
    required = {'schema_version', 'name', 'license', 'summary', 'files'}
    if type(manifest) is not dict or not required <= set(manifest) or manifest['schema_version'] != 1:
        raise ValueError(f'{directory / MANIFEST} needs schema_version 1, name, license, summary and files')
    if not isinstance(manifest['name'], str) or not _NAME.fullmatch(manifest['name']):
        raise ValueError(f'{directory / MANIFEST} has an invalid name')
    if manifest['name'] != directory.name or (name is not None and manifest['name'] != name):
        raise ValueError(f'component name {manifest["name"]!r} does not match its directory {directory.name!r}')
    if not isinstance(manifest['license'], str) or not manifest['license'].strip():
        raise ValueError(f'{directory / MANIFEST} must declare its license')
    files = manifest['files']
    if type(files) is not dict or not files:
        raise ValueError(f'{directory / MANIFEST} must list its files with sha256')
    for member, sha in files.items():
        if (not isinstance(member, str) or not member or member.startswith('/')
                or any(part in ('', '.', '..') for part in member.split('/'))):
            raise ValueError(f'component member {member!r} must be a relative path')
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise ValueError(f'component member {member} needs a sha256')
        path = directory / member
        if path.is_symlink() or any(p.is_symlink() for p in path.relative_to(directory).parents if str(p) != '.'):
            raise ValueError(f'component member {path} must not be a symlink')
        if not path.is_file():
            raise ValueError(f'component member {path} is missing')
        if _sha256(path) != sha:
            raise ValueError(f'component member {path} differs from its declared sha256')
    return Addon(manifest['name'], directory.resolve(), manifest['license'], manifest)


def resolve(name, *, roots=None, env=None, include_defaults=True):
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError(f'invalid component name {name!r}')
    searched = list(roots) if roots is not None else search_roots(env, include_defaults=include_defaults)
    for root in searched:
        candidate = Path(root) / name
        if (candidate / MANIFEST).is_file():
            return load(candidate, name)
    raise AddonNotFound(
        f'component {name!r} was not found in ' + (', '.join(str(r) for r in searched) or 'any search root') +
        f'. Install it with the RAVEL installer, or point {ENV} at the directory that contains {name}/.')
