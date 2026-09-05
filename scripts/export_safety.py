#!/usr/bin/env python3
"""Non-destructive staging and portable text sanitization for distribution exports."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys


def prepare(stage, repo):
    raw, repo = Path(stage).absolute(), Path(repo).resolve()
    # An existing symlink is never a staging directory, even if it points at an empty one.
    if raw.is_symlink() or any(p.is_symlink() for p in raw.parents):
        raise ValueError('staging path must not contain symlinks')
    path = raw.resolve()
    if path in (Path('/'), Path.home().resolve(), repo) or path in repo.parents:
        raise ValueError('refusing repository, home, filesystem root, or repository ancestor')
    if path.is_relative_to(repo):
        raise ValueError('staging directory must be outside the source repository')
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError('staging directory must be new or empty; existing contents are never deleted')
    path.mkdir(parents=True, exist_ok=True)
    return path


def replacements_for(home, self_url=None):
    if not Path(home).is_absolute() or Path(home) == Path('/'):
        raise ValueError('home redaction requires an absolute non-root home directory')
    replacements = [(str(home) + '/Documents/DSRLab', '$DSRLAB_ROOT'),
                    (str(home), '$OPERATOR_HOME')]
    if self_url:
        url = self_url.removesuffix('.git').removeprefix('https://').removeprefix('http://')
        if (not re.fullmatch(r'github\.com/[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+', url)
                or url.rsplit('/', 1)[-1] in ('.', '..')):
            raise ValueError('--self-url must name a github.com repository')
        replacements.append(('github.com/ashen' + 'joy/hep-agentic-pipeline', url))
    return replacements


def sanitize_bytes(data, replacements):
    if b'\0' in data:
        return data
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return data
    for source, target in replacements:
        text = text.replace(source, target)
    return text.encode('utf-8')


def sanitize(stage, home, self_url=None):
    stage = Path(stage)
    if stage.is_symlink() or not stage.is_dir():
        raise ValueError('sanitization requires a real staging directory')
    replacements = replacements_for(home, self_url)
    changed = []
    for path in sorted(stage.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'export must not contain symlinks: {path.relative_to(stage)}')
        if not path.is_file():
            continue
        data = path.read_bytes()
        cleaned = sanitize_bytes(data, replacements)
        if cleaned != data:
            path.write_bytes(cleaned)
            changed.append(str(path.relative_to(stage)))
    return changed


def evidence_path(root, relative):
    """Evidence bindings never follow a manifest outside its tree, even through symlinks."""
    if (not isinstance(relative, str) or not relative or '\\' in relative or '\0' in relative
            or Path(relative).is_absolute()
            or any(part in ('', '.', '..') for part in relative.split('/'))):
        raise ValueError(f'evidence path must be normalized and repository-relative: {relative!r}')
    root = Path(root).resolve()
    path = root / relative
    if any(parent.is_symlink() for parent in (path, *path.parents) if parent != root):
        raise ValueError(f'evidence path must not contain symlinks: {relative}')
    if not path.resolve().is_relative_to(root):
        raise ValueError(f'evidence path escapes its repository: {relative}')
    return path


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate key in source evidence manifest: {key}')
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f'nonfinite number in source evidence manifest: {value}')


def bind_evidence(stage, source, home, self_url=None):
    """Rebind only the deterministic redaction of already verified source evidence.

    Never bless arbitrary staged bytes by merely regenerating their hashes.
    Every shipped artifact must equal the exact allowed transformation of its
    source, and the source must still match the original evidence pin.
    """
    stage, source = Path(stage), Path(source)
    replacements = replacements_for(home, self_url)
    source_manifest = evidence_path(source, 'evidence_manifest.json').read_bytes()
    staged_manifest = evidence_path(stage, 'evidence_manifest.json').read_bytes()
    if staged_manifest != sanitize_bytes(source_manifest, replacements):
        raise ValueError('staged manifest differs from the allowed redaction of the source manifest')
    manifest = json.loads(staged_manifest, object_pairs_hook=unique_object, parse_constant=reject_constant)
    if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int
            or manifest['schema_version'] != 1
            or not isinstance(manifest.get('claims'), list) or not manifest['claims']):
        raise ValueError('source evidence manifest has an invalid structure')
    transformations = []
    for claim in manifest['claims']:
        if (not isinstance(claim, dict) or not isinstance(claim.get('artifacts'), list)
                or not claim['artifacts']):
            raise ValueError('source evidence claim has an invalid artifact list')
        for artifact in claim['artifacts']:
            if not isinstance(artifact, dict) or type(artifact.get('shipped')) is not bool:
                raise ValueError('source evidence artifact must have a boolean shipped field')
            if not artifact['shipped']:
                continue
            rel = artifact.get('path')
            raw = evidence_path(source, rel).read_bytes()
            if hashlib.sha256(raw).hexdigest() != artifact.get('sha256'):
                raise ValueError(f'source evidence changed before export: {rel}')
            if type(artifact.get('bytes')) is not int or artifact['bytes'] != len(raw):
                raise ValueError(f'source evidence byte count differs from its pin: {rel}')
            actual = evidence_path(stage, rel).read_bytes()
            if actual != sanitize_bytes(raw, replacements):
                raise ValueError(f'staged evidence differs from allowed redaction: {rel}')
            digest = hashlib.sha256(actual).hexdigest()
            if digest != artifact['sha256']:
                transformations.append({'path': rel, 'source_sha256': artifact['sha256'],
                                        'export_sha256': digest})
            artifact.update(sha256=digest, bytes=len(actual))
    (stage / 'evidence_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    spec = importlib.util.spec_from_file_location('ravel_export_evidence', source / 'framework/build_evidence.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (stage / 'EVIDENCE.md').write_text(module.render_evidence_md(manifest))
    provenance = {'schema_version': 1, 'source_commit': manifest.get('source_commit'),
                  'operation': 'deterministic home-path and repository-URL redaction only',
                  'artifact_transformations': transformations}
    (stage / 'results/export-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    return transformations


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('stage')
    prep.add_argument('repo')
    clean = sub.add_parser('sanitize')
    clean.add_argument('stage')
    clean.add_argument('home')
    clean.add_argument('--self-url')
    bind = sub.add_parser('bind-evidence')
    bind.add_argument('stage')
    bind.add_argument('repo')
    bind.add_argument('home')
    bind.add_argument('--self-url')
    args = ap.parse_args()
    try:
        if args.command == 'prepare':
            print(prepare(args.stage, args.repo))
        elif args.command == 'sanitize':
            print(f'Sanitized {len(sanitize(args.stage, args.home, args.self_url))} text files')
        else:
            changes = bind_evidence(args.stage, args.repo, args.home, args.self_url)
            print(f'Verified staged evidence; {len(changes)} deterministic redactions rebound')
    except (ValueError, OSError) as exc:
        print(f'export safety: FAIL: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
