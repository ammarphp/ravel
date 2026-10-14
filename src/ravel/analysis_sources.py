"""Immutable declared source/layout/dependency capsules, without importing code.

This verifies supplied bytes and declared closure. It cannot infer every dynamic
C++ dependency, authenticate an asserted Git history, or certify physics.
"""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import re

from ravel.workflow.state_io import read_json

ROLES = {'compile', 'header', 'model', 'preprocessing', 'reference', 'calibration',
         'configuration', 'license', 'build', 'data'}
DEPENDENCY_KINDS = {'source', 'asset', 'submodule', 'runtime', 'package'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relative_path(value, *, directory=False):
    if directory and value == '.':
        return value
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('source path must be a normalized relative path')
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or str(p) != value or value == '.':
        raise ValueError('source path must be a normalized relative path')
    return value


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('exact SHA256 required')


def validate_capsule(capsule):
    required = {'schema_version', 'kind', 'framework', 'routine', 'source', 'root',
                'files', 'layout', 'dependencies', 'dependency_review', 'submodules'}
    if not isinstance(capsule, dict) or set(capsule) != required or type(capsule['schema_version']) is not int or capsule['schema_version'] != 1 or capsule['kind'] != 'analysis-source-capsule':
        raise ValueError('invalid analysis-source-capsule/v1 fields')
    if capsule['framework'] not in ('rivet', 'simpleanalysis', 'cpp') or not isinstance(capsule['routine'], str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]*', capsule['routine']):
        raise ValueError('invalid source framework or routine identity')
    source = capsule['source']
    if not isinstance(source, dict) or set(source) != {'repository', 'revision', 'description'} or not isinstance(source['description'], str) or not source['description'].strip():
        raise ValueError('source needs repository, revision and description')
    if source['repository'] == 'supplied':
        if source['revision'] is not None:
            raise ValueError('supplied file source has no asserted Git revision')
    elif not isinstance(source['repository'], str) or not source['repository'].startswith('https://') or not isinstance(source['revision'], str) or not re.fullmatch('[0-9a-f]{40}', source['revision']):
        raise ValueError('Git source requires HTTPS repository and exact commit')
    if not isinstance(capsule['root'], str) or not capsule['root']:
        raise ValueError('source root required')
    facts = capsule['files']
    if not isinstance(facts, list) or not facts:
        raise ValueError('nonempty declared source file inventory required')
    paths = set()
    for fact in facts:
        if not isinstance(fact, dict) or set(fact) != {'path', 'sha256', 'role'}:
            raise ValueError('source fact needs path, SHA256 and role')
        relative_path(fact['path']); _hash(fact['sha256'])
        if fact['role'] not in ROLES or fact['path'] in paths:
            raise ValueError('duplicate source path or invalid source role')
        paths.add(fact['path'])
    layout = capsule['layout']
    if not isinstance(layout, dict) or set(layout) != {'include_dirs', 'asset_dirs'}:
        raise ValueError('explicit include and asset layout required')
    for values in layout.values():
        if not isinstance(values, list) or len(set(values)) != len(values):
            raise ValueError('unique layout directories required')
        for value in values:
            relative_path(value, directory=True)
            if value != '.' and not any(p.startswith(value + '/') for p in paths):
                raise ValueError('layout directory has no declared files: ' + value)
    deps = capsule['dependencies']
    if not isinstance(deps, list):
        raise ValueError('explicit dependency inventory required')
    names = set()
    for dep in deps:
        if not isinstance(dep, dict) or set(dep) != {'name', 'kind', 'status', 'files', 'reason'} or not isinstance(dep['name'], str) or not dep['name'].strip() or dep['name'] in names:
            raise ValueError('invalid or duplicate dependency identity')
        names.add(dep['name'])
        if dep['kind'] not in DEPENDENCY_KINDS or dep['status'] not in ('resolved', 'unresolved') or not isinstance(dep['reason'], str) or not dep['reason'].strip():
            raise ValueError('dependency needs kind, status and reason')
        if not isinstance(dep['files'], list) or len(set(dep['files'])) != len(dep['files']) or set(dep['files']) - paths:
            raise ValueError('dependency files must reference declared source files')
        if dep['status'] == 'resolved' and dep['kind'] in ('source', 'asset', 'submodule') and not dep['files']:
            raise ValueError('resolved file dependency needs bound files')
    review = capsule['dependency_review']
    if not isinstance(review, dict) or set(review) != {'complete', 'description'} or type(review['complete']) is not bool or not isinstance(review['description'], str) or not review['description'].strip():
        raise ValueError('explicit supplied dependency review required')
    if review['complete'] and any(d['status'] == 'unresolved' for d in deps):
        raise ValueError('dependency review cannot be complete with unresolved requirements')
    if not isinstance(capsule['submodules'], list):
        raise ValueError('explicit submodule inventory required')
    subs = set()
    for sub in capsule['submodules']:
        if not isinstance(sub, dict) or set(sub) != {'path', 'repository', 'revision'}:
            raise ValueError('submodule needs path, repository and revision')
        relative_path(sub['path'])
        if sub['path'] in subs or not isinstance(sub['repository'], str) or not sub['repository'].startswith('https://') or not isinstance(sub['revision'], str) or not re.fullmatch('[0-9a-f]{40}', sub['revision']):
            raise ValueError('invalid submodule identity')
        subs.add(sub['path'])
        if not any(p.startswith(sub['path'] + '/') for p in paths):
            raise ValueError('submodule identity needs declared content files')
    return capsule


def load_capsule(path):
    return validate_capsule(read_json(path))


def from_catalogue(catalogue, row, root):
    """Seed a reviewable capsule from pinned facts, without conferring closure.

    External callers can instead supply the same schema for an unknown routine.
    Catalogue-derived paths/bytes are verified, including reference and literal
    asset blobs; Git identity itself still needs separately retained provenance.
    """
    root = Path(root).resolve()
    facts = [(f, 'compile') for f in row['source_files']]
    facts += [(f, 'reference') for f in row['reference_files']]
    if 'metadata_file' in row:
        facts.append((row['metadata_file'], 'configuration'))
    for asset in row.get('external_assets', []):
        for f in asset['matches']:
            role = 'model' if f['path'].endswith('.onnx') else 'preprocessing' if f['path'].endswith('.json') else 'data'
            facts.append((f, role))
    if not row['source_files']:
        raise ValueError('catalogue source implementation is unresolved')
    files = {}
    for fact, role in facts:
        relative_path(fact['path'])
        p = root / fact['path']
        if not p.is_file() or any(q.is_symlink() for q in [p, *p.parents] if q.is_relative_to(root)):
            raise ValueError('catalogue source/asset is missing or linked: ' + fact['path'])
        raw = p.read_bytes()
        if hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() != fact['git_blob']:
            raise ValueError('catalogue source/asset blob differs: ' + fact['path'])
        sha = hashlib.sha256(raw).hexdigest()
        if 'sha256' in fact and sha != fact['sha256']:
            raise ValueError('catalogue source digest differs: ' + fact['path'])
        files[fact['path']] = {'path': fact['path'], 'sha256': sha, 'role': role}
    dependencies = [{'name': 'literal:' + a['literal'], 'kind': 'asset',
                     'status': 'resolved' if len(a['matches']) == 1 else 'unresolved',
                     'files': [f['path'] for f in a['matches']],
                     'reason': 'Literal scan only; dynamic/helper/resolver dependencies require separate review.'}
                    for a in row.get('external_assets', [])]
    capsule = {'schema_version': 1, 'kind': 'analysis-source-capsule',
               'framework': row['framework'], 'routine': row['name'],
               'source': {'repository': catalogue['sources'][row['source_id']]['repository'],
                          'revision': catalogue['sources'][row['source_id']]['revision'],
                          'description': 'Catalogue seed; selected known source/metadata/reference/literal assets only.'},
               'root': str(root), 'files': list(files.values()),
               'layout': {'include_dirs': [], 'asset_dirs': sorted({str(PurePosixPath(p).parent) for p, f in files.items() if f['role'] != 'compile'})},
               'dependencies': dependencies,
               'dependency_review': {'complete': False, 'description': 'Transitive helper, dynamic asset, submodule and runtime dependency review is still required.'},
               'submodules': []}
    return validate_capsule(capsule)


def source_files(capsule, base):
    """Verify every declared file; no Git command, builder, or runtime is called."""
    validate_capsule(capsule)
    candidate = Path(base) / capsule['root']
    if candidate.is_symlink() or not candidate.is_dir():
        raise ValueError('source root must be an existing ordinary directory')
    root = candidate.resolve()
    files = []
    for fact in capsule['files']:
        p = root / fact['path']
        if not p.resolve().is_relative_to(root) or any(q.is_symlink() for q in [p, *p.parents] if q.is_relative_to(root)) or not p.is_file():
            raise ValueError('source is missing, a symlink, or escapes its root: ' + fact['path'])
        raw = p.read_bytes()
        if raw.startswith(b'version https://git-lfs.github.com/spec/v1\n'):
            raise ValueError('Git LFS pointer is not the declared source/asset content: ' + fact['path'])
        if hashlib.sha256(raw).hexdigest() != fact['sha256']:
            raise ValueError('source bytes differ from capsule: ' + fact['path'])
        files.append(p)
    return root, files


def inventory(capsule, base):
    root, files = source_files(capsule, base)
    return {'schema_version': 1, 'kind': 'analysis-source-inventory',
            'framework': capsule['framework'], 'routine': capsule['routine'],
            'source': capsule['source'], 'root': str(root), 'files': capsule['files'],
            'layout': capsule['layout'], 'dependencies': capsule['dependencies'],
            'dependency_review': capsule['dependency_review'], 'submodules': capsule['submodules'],
            'declared_files_verified': len(files), 'physics_validated': False,
            'scope': 'Declared file bytes and layout only; supplied dependency review and Git identities are assertions, not independently authenticated closure.'}


def staged_inventory(inventory, root):
    """Observe the actual build inputs, preserving source-relative identities.

    This is an explicit measurement at the worker boundary, not a claim that an
    adversarial filesystem cannot change and restore bytes during compilation.
    """
    root = Path(root).absolute()
    if any(p.is_symlink() for p in (root, *root.parents)) or not root.is_dir():
        raise ValueError('staged source root must be an ordinary directory')
    facts = []
    for expected in inventory['files']:
        relative_path(expected['path'])
        p = root / expected['path']
        if any(q.is_symlink() for q in (p, *p.parents)) or not p.is_file():
            raise ValueError('staged source is missing or linked: ' + expected['path'])
        raw = p.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if sha != expected['sha256']:
            raise ValueError('staged source bytes differ: ' + expected['path'])
        facts.append({'path': expected['path'], 'sha256': sha, 'bytes': len(raw),
                      'role': expected['role']})
    return {'root': str(root), 'files': facts}


def routine_bindings(capsule, base, compile_units):
    """Positive literal registration bindings for source-booked Rivet entries.

    This is not a complete C++ parser. A dynamically registered secondary name
    needs an explicit source contract rather than admission by its name alone.
    The primary capsule retains its declared source scope when no literal exists.
    """
    root, _ = source_files(capsule, base)
    bindings = {}
    tokens = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/'
    for fact in capsule['files']:
        if fact['path'] not in compile_units and fact['role'] != 'header':
            continue
        code = re.sub(tokens, ' ', (root / fact['path']).read_text(errors='replace'))
        code = re.sub(r'(?m)^[ \t]*#[ \t]*define[^\n]*(?:\\\n[^\n]*)*', ' ', code)
        registrations = [(name, None) for name in re.findall(r'\bRIVET_DECLARE_PLUGIN\s*\(\s*([A-Za-z][A-Za-z0-9_]*)\s*\)', code)]
        if fact['path'] in compile_units:
            registrations += re.findall(r'\bRIVET_DECLARE_ALIASED_PLUGIN\s*\(\s*([A-Za-z][A-Za-z0-9_]*)\s*,\s*([A-Za-z][A-Za-z0-9_]*)\s*\)', code)
        for name, alias in registrations:
            binding = bindings.setdefault(name, {'registration': 'literal-RIVET_DECLARE_PLUGIN',
                'source_files': [], 'supporting_files': []})
            if alias is not None:
                if binding['registration'] != 'literal-RIVET_DECLARE_PLUGIN' or binding['source_files']:
                    raise ValueError('ambiguous repeated canonical/aliased plugin registration')
                binding['registration'] = 'literal-RIVET_DECLARE_ALIASED_PLUGIN'
                binding['aliases'] = [alias]
            if fact not in binding['source_files']:
                binding['source_files'].append(fact)
    if capsule['routine'] not in bindings:
        bindings[capsule['routine']] = {'registration': 'declared-capsule-primary',
            'source_files': [f for f in capsule['files'] if f['path'] in compile_units], 'supporting_files': []}
    for name, binding in bindings.items():
        binding['supporting_files'] = [f for f in capsule['files'] if
            Path(f['path']).name in {name + '.info', name + '.plot', name + '.yoda', name + '.yoda.gz'}]
    return bindings


def dependency_cues(capsule, base):
    """Conservative literal/helper cues, never a complete C++ dependency parser."""
    root, _ = source_files(capsule, base)
    code = '\n'.join((root / f['path']).read_text(errors='replace') for f in capsule['files'] if f['role'] in ('compile', 'header'))
    tokens = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/'
    code = re.sub(tokens, lambda m: ' ' if m[0].startswith('/') else m[0], code)
    return {'onnx_model': bool(re.search(r'\b(?:addONNX|getONNX|getONNXFilePath|RivetONNXrt)\b|analysisDataPath\s*\(\s*"onnx"', code)),
            'scope': 'Conservative helper/include cues only; absence is not evidence of no dependency.'}
