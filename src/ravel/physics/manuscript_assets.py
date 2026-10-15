"""Complete supplied class custody and public redistribution refusal.

Bundle metadata survives private materialization. Public release is a separate
boundary: identical bytes under a different filename remain restricted.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from ravel.workflow import candidate_experiments as ce, report_integrity as custody

MAX_FILES = 20000


def supplied_bundle(folder):
    root = Path(folder).absolute()
    if not root.is_dir() or any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('regular supplied class folder required')
    files = []
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError('supplied class bundle contains an alias or special file')
        if path.is_file():
            raw = path.read_bytes()
            files.append({'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)})
            if len(files) > MAX_FILES:
                raise ValueError('supplied class file census exceeds capacity')
    record = {'kind': 'user-supplied-class', 'redistributable': False, 'files': files}
    pins([record], root, verify=True)
    return record


def pins(assets, base=None, *, verify=False, consumed=None):
    """Expand grouped records into exact pin3 leaves for custody consumers."""
    if type(assets) is not list:
        raise ValueError('complete template asset list required')
    result = []
    for asset in assets:
        if type(asset) is not dict:
            raise ValueError('template asset record required')
        if asset.get('kind') == 'user-supplied-class':
            ce.keys(asset, ['kind', 'redistributable', 'files'])
            if type(asset['redistributable']) is not bool or asset['redistributable'] is not False:
                raise ValueError('supplied class must retain non-redistributable provenance')
            leaves = asset['files']
            if type(leaves) is not list or not leaves:
                raise ValueError('nonempty complete supplied bundle required')
        else:
            leaves = [asset]
        for leaf in leaves:
            ce.keys(leaf, ['path', 'sha256', 'size'])
            if (type(leaf['path']) is not str or not leaf['path'] or
                    type(leaf['sha256']) is not str or len(leaf['sha256']) != 64 or
                    any(c not in '0123456789abcdef' for c in leaf['sha256']) or
                    type(leaf['size']) is not int or leaf['size'] < 0):
                raise ValueError('exact template path/SHA/size required')
            if verify:
                custody._raw(leaf, base, {} if consumed is None else consumed)
            result.append(deepcopy(leaf))
    if len(result) > MAX_FILES or len({p['path'] for p in result}) != len(result):
        raise ValueError('distinct bounded template file census required')
    return result


def placements(assets, base):
    """Preserve each bundle's directory hierarchy; reject all output collisions."""
    pins(assets, base, verify=True)
    result = []; names = set()
    for asset in assets:
        leaves = asset['files'] if asset.get('kind') == 'user-supplied-class' else [asset]
        paths = [custody._artifact_path(pin, base) for pin in leaves]
        root = Path(os.path.commonpath([str(path.parent) for path in paths]))
        for pin, path in zip(leaves, paths):
            relative = path.relative_to(root) if 'files' in asset else Path(path.name)
            if relative in names or '..' in relative.parts:
                raise ValueError('duplicate supplied template destination')
            names.add(relative); result.append((pin, relative))
    return result


def materialize(assets, base, root, emit):
    locations = {pin['path']: relative for pin, relative in placements(assets, base)}
    def copy(pin):
        return emit(Path(root) / locations[pin['path']], custody._raw(pin, base, {}))
    return [({**deepcopy(asset), 'files': [copy(pin) for pin in asset['files']]}
             if asset.get('kind') == 'user-supplied-class' else copy(asset)) for asset in assets]


def refuse_public_assets(staging, *, metadata=(), exclude=()):
    """One export guard, after staging and before publishing any output.

``exclude`` names staged folders that hold no supplied material: the vendored framework release,
whose files the tag authenticates and whose own data declares the supplied-class record shape.

Read bundled JSON and explicitly referenced metadata, not unrelated folders.
Follow local pin references so a formatting/package record cannot conceal its
bundle merely by storing the record in a separate declared JSON file.
"""
    stage = Path(staging)
    skipped = [stage / folder for folder in exclude]
    queue = [*[p for p in stage.rglob('*') if p.is_file() and not any(p.is_relative_to(s) for s in skipped)],
             *map(Path, metadata)]
    seen = set(); restricted = set()
    def visit(value, base):
        if type(value) is dict:
            if value.get('kind') == 'user-supplied-class':
                for pin in pins([value]):
                    restricted.add((pin['sha256'], pin['size']))
            if type(value.get('path')) is str:
                path = Path(value['path'])
                queue.append(path if path.is_absolute() else base / path)
            for row in value.values(): visit(row, base)
        elif type(value) is list:
            for row in value: visit(row, base)
    while queue:
        path = queue.pop()
        if path in seen or not path.is_file(): continue
        # A staged listing names vendored files by path; they stay outside the guard as well.
        if any(path.resolve().is_relative_to(s.resolve()) for s in skipped): continue
        if path.is_symlink(): raise ValueError('aliased supplied bundle metadata')
        seen.add(path)
        if len(seen) > MAX_FILES: raise ValueError('public bundle metadata census exceeds capacity')
        # Content, not a suffix, identifies JSON. Only inspect a small prefix of
        # binaries/non-JSON text; do not load large event or image assets here.
        with path.open('rb') as stream:
            prefix=b'';count=0
            while not prefix:
                block=stream.read(4096);count+=len(block)
                if not block:break
                prefix=block.lstrip()
                if count>custody.MAX_OPERATIONAL_METADATA_BYTES:
                    raise ValueError('public bundle metadata exceeds operational capacity')
        if not prefix.startswith((b'{',b'[')):continue
        if path.stat().st_size>custody.MAX_OPERATIONAL_METADATA_BYTES:
            raise ValueError('public bundle metadata exceeds operational capacity')
        try: value = json.loads(path.read_text())
        except (UnicodeError, json.JSONDecodeError): continue
        visit(value, path.parent)
    sizes = {size for _, size in restricted}
    for path in stage.rglob('*'):
        if not path.is_file() or path.stat().st_size not in sizes:continue
        digest=hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
        if (digest.hexdigest(), path.stat().st_size) in restricted:
            raise ValueError('public export refuses non-redistributable supplied bundle file: ' + str(path.relative_to(stage)))
