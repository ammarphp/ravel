#!/usr/bin/env python3
"""Non-destructive staging and portable text sanitization for distribution exports."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ravel import evidence_layout


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


def public_directory(selection):
    """An index of the actual public files, rather than the private workspace map."""
    lines = ['# Repository directory', '',
             'Generated from `evidence/collections.json` during distribution export.',
             'Historical evidence is read-only. New runs use a per-run `run_state.json` ledger.', '']
    files = sorted(destination for _source, destination in selection)
    lines += ['## Root files', '', '| File | Purpose |', '|---|---|']
    for relative in files:
        if '/' not in relative or relative in {'native/README.md', 'environment/README.md',
                                               'benchmarks/README.md', 'docs/README.md'}:
            lines.append(f'| `{relative}` | Project metadata, entry points, or policy |')
    lines += ['', '## Main directories', '', '| Directory | Contents | Files |', '|---|---|---|']
    domains = {
        'src/ravel/physics': 'Event processing and statistical engines',
        'src/ravel/workflow': 'Run lifecycle, approvals, provenance, and scan orchestration',
        'src/ravel/validation': 'Task validation, scientific checks, and benchmark replay',
        'src/ravel/plotting': 'Figures and comparisons',
        'src/ravel/data': 'Templates, fixtures, and reference inputs',
        'tests/unit': 'Focused regression tests',
        'tests/adversarial': 'Adversarial workflow scenarios',
        'tests/fixtures': 'Immutable test inputs',
        'benchmarks': 'Benchmark and capability registries',
        'native/src': 'Native C++ source',
        'native/scripts': 'Native build and execution scripts',
        'environment': 'Simulation environment setup',
        'scripts': 'Maintenance, documentation, and export commands',
        'docs/workflow': 'Physics workflow instructions',
        'docs/reference': 'Capabilities, contracts, and tool reference',
        'docs/validation': 'Scoped results, cases, and evidence descriptions',
        'docs/development': 'Contributor guidance and explicitly labeled history',
        'docs/research': 'Research and evaluation protocols',
        'docs/guides': 'Longer guides and sources',
        'evidence': 'Curated historical inputs, measurements, and provenance',
        '.claude': 'Agent skills, rules, and enforcement hooks',
        '.agents': 'Mirrored skills',
        '.github': 'Continuous integration',
    }
    for directory, purpose in domains.items():
        count = sum(f.startswith(directory + '/') for f in files)
        if count:
            lines.append(f'| `{directory}/` | {purpose} | {count} |')
    lines += ['', '## Workflow enforcement files', '', '| File | Purpose |', '|---|---|']
    key_names = {'workflow_state.py', 'provenance.py', 'progress_reporter.py', 'stop_dispatch.py',
                 'stage_supervisor.py', 'validate_parameters.py', 'validate_checkin.py',
                 'preflight_watcher.py', 'sr_plausibility.py', 'install-git-hooks.sh',
                 'hook-primacy.json', 'stop-dispatcher.sh', 'posttooluse-observer.sh',
                 'userpromptsubmit-router.sh', 'pretooluse-skill.sh'}
    for relative in files:
        if Path(relative).name in key_names:
            lines.append(f'| `{relative}` | Workflow enforcement or its regression fixture |')
    lines += ['', '## Curated evidence', '', '| Collection | Files |', '|---|---|']
    collections = sorted({str(Path(f).parents[len(Path(f).parts) - 4]) for f in files
                          if len(Path(f).parts) >= 4 and f.split('/')[0] == 'evidence'
                          and f.split('/')[1] in ('scans', 'benchmarks', 'native-validation', 'case-studies')})
    for collection in collections:
        lines.append(f'| `{collection}/` | {sum(f.startswith(collection + "/") for f in files)} |')
    lines.append('')
    return '\n'.join(lines)


def assemble(stage, source):
    """Copy the registry selection without modifying original archives."""
    stage, source = Path(stage), Path(source)
    if not stage.is_dir() or any(stage.iterdir()):
        raise ValueError('assembly requires an empty prepared staging directory')
    selection = evidence_layout.selected_files(source)
    for original, public in selection:
        destination = evidence_path(stage, public)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(evidence_path(source, original), destination)
    (stage / 'DIRECTORY.md').write_text(public_directory(selection))
    return selection


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate key in source evidence manifest: {key}')
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f'nonfinite number in source evidence manifest: {value}')


def source_git_head(source):
    """The exported checkout's actual HEAD, independently of claim provenance."""
    try:
        top = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=source,
                             capture_output=True, text=True, timeout=10)
        if top.returncode or Path(top.stdout.strip()).resolve() != Path(source).resolve():
            return None
        head = subprocess.run(['git', 'rev-parse', '--verify', 'HEAD'], cwd=source,
                              capture_output=True, text=True, timeout=10)
        revision = head.stdout.strip()
        if head.returncode == 0 and re.fullmatch(r'[0-9a-f]{40,64}', revision):
            return revision
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def bind_evidence(stage, source, home, self_url=None):
    """Rebind only the deterministic redaction of already verified source evidence.

    Never bless arbitrary staged bytes by merely regenerating their hashes.
    Every shipped artifact must equal the exact allowed transformation of its
    source, and the source must still match the original evidence pin.
    """
    stage, source = Path(stage), Path(source)
    replacements = replacements_for(home, self_url)
    # The staged mapping is itself fixed input. A substituted registry cannot reroute
    # a pin to some other file containing conveniently matching bytes.
    registry_bytes = evidence_path(source, evidence_layout.REGISTRY).read_bytes()
    if evidence_path(stage, evidence_layout.REGISTRY).read_bytes() != registry_bytes:
        raise ValueError('staged evidence registry differs from source registry')
    source_manifest = evidence_path(source, 'evidence/manifest.json').read_bytes()
    staged_manifest = evidence_path(stage, 'evidence/manifest.json').read_bytes()
    if staged_manifest != sanitize_bytes(source_manifest, replacements):
        raise ValueError('staged manifest differs from the allowed redaction of the source manifest')
    manifest = json.loads(staged_manifest, object_pairs_hook=unique_object, parse_constant=reject_constant)
    if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int
            or manifest['schema_version'] != 1
            or not isinstance(manifest.get('claims'), list) or not manifest['claims']):
        raise ValueError('source evidence manifest has an invalid structure')
    transformations, bindings = [], []
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
            if evidence_layout.public_path(rel, source) != rel:
                raise ValueError(f'source manifest must use the canonical public artifact path: {rel}')
            original = evidence_layout.source_path(rel, source)
            if artifact.get('source_path', original) != original:
                raise ValueError(f'artifact source_path differs from its registry mapping: {rel}')
            raw = evidence_layout.resolve(source, rel).read_bytes()
            if hashlib.sha256(raw).hexdigest() != artifact.get('sha256'):
                raise ValueError(f'source evidence changed before export: {rel}')
            if type(artifact.get('bytes')) is not int or artifact['bytes'] != len(raw):
                raise ValueError(f'source evidence byte count differs from its pin: {rel}')
            actual = evidence_path(stage, rel).read_bytes()
            if actual != sanitize_bytes(raw, replacements):
                raise ValueError(f'staged evidence differs from allowed redaction: {rel}')
            digest = hashlib.sha256(actual).hexdigest()
            binding = {'source_path': original, 'public_path': rel,
                       'source_sha256': artifact['sha256'], 'export_sha256': digest,
                       'source_bytes': len(raw), 'export_bytes': len(actual)}
            bindings.append(binding)
            if digest != artifact['sha256'] or original != rel:
                transformations.append(binding)
            artifact.update(sha256=digest, bytes=len(actual))
    # Account for every selected file, including unclaimed figures/configuration.
    # Generated indexes have named, deterministic producers; arbitrary staged edits
    # are never repaired by recomputing evidence hashes.
    selection = evidence_layout.selected_files(source)
    expected_files = {public for _original, public in selection} | {'DIRECTORY.md'}
    actual_files = {p.relative_to(stage).as_posix() for p in stage.rglob('*') if p.is_file()}
    if actual_files != expected_files:
        raise ValueError(f'staged file set differs from registry: missing={sorted(expected_files-actual_files)}, '
                         f'extra={sorted(actual_files-expected_files)}')
    file_bindings = []
    for original, public in selection:
        raw = evidence_path(source, original).read_bytes()
        expected = (public_directory(selection).encode() if public == 'DIRECTORY.md'
                    else sanitize_bytes(raw, replacements))
        actual = evidence_path(stage, public).read_bytes()
        if actual != expected:
            raise ValueError(f'staged file differs from declared export transformation: {public}')
        file_bindings.append({'source_path': original, 'public_path': public,
                              'source_sha256': hashlib.sha256(raw).hexdigest(),
                              'export_sha256': hashlib.sha256(actual).hexdigest()})
    (stage / 'evidence/manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    spec = importlib.util.spec_from_file_location('ravel_export_evidence', source / 'scripts/build_evidence.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (stage / 'docs/validation/evidence.md').write_text(module.render_evidence_md(manifest))
    provenance = {'schema_version': 2, 'source_commit': source_git_head(source),
                  'claim_manifest_source_commit': manifest.get('source_commit'),
                  'operation': 'explicit evidence relocation, deterministic home-path and repository-URL redaction, and generated public directory/evidence indexes',
                  'registry_sha256': hashlib.sha256(registry_bytes).hexdigest(),
                  'artifact_bindings': bindings, 'artifact_transformations': transformations,
                  'file_bindings_before_evidence_index_render': file_bindings}
    (stage / 'evidence/export-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    return transformations


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('stage')
    prep.add_argument('repo')
    copy = sub.add_parser('assemble')
    copy.add_argument('stage')
    copy.add_argument('repo')
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
        elif args.command == 'assemble':
            print(f'Assembled {len(assemble(args.stage, args.repo))} explicitly selected files')
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
