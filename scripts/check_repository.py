#!/usr/bin/env python3
"""Check the shipped repository layout, names, and exact Markdown destinations.

Historical collection records retain their original text and are exempt from
navigation checks. This validates local links, not remote availability or the
scientific meaning of a page. GitHub-style heading fragments are checked for
Markdown targets; fragments for PDFs, binaries, and other renderers are not.

Public mode (`--public`, automatic in this repository) also rejects a registry with fields
beyond the distribution selection. Every shipped document may link only to files that ship.
"""
import argparse
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ravel import evidence_layout
from ravel.paths import WORKFLOW_INSTRUCTIONS, workflow_instruction

# Indexes that a shipped document may link to only in public mode.
PUBLIC_INDEXES = {'DIRECTORY.md'}
CONVENTIONAL = {'README.md', 'CONTRIBUTING.md', 'AGENTS.md', 'CLAUDE.md', 'GEMINI.md', 'DIRECTORY.md', 'CHANGELOG.md',
                'SKILL.md', 'THIRD-PARTY-NOTICES.md', 'ATTRIBUTION.md'}
# Host entry documents whose upper-case name is the host's own convention, named by full path.
CONVENTIONAL_PATHS = {'.antigravity/RAVEL.md', '.opencode/RAVEL.md'}
LOCAL_TOOL_DIRS = {'.git', '.pytest_cache', '.ruff_cache', '__pycache__', 'dist', 'build', 'local-runs', 'logs'}
PUBLIC_ROOTS = {
    'src', 'tests', 'docs', 'native', 'environment', 'scripts', 'distribution.json', 'export-provenance.json',
    '.github', '.claude', '.agents', 'README.md', 'CONTRIBUTING.md', 'AGENTS.md', 'CLAUDE.md', 'DIRECTORY.md',
    'CITATION.cff', 'LICENSE', 'NOTICE', 'THIRD-PARTY-NOTICES.md', 'CHANGELOG.md', 'Makefile', 'pyproject.toml',
    'hatch_build.py', 'requirements-replay.txt', 'requirements-replay.lock', 'requirements-full.txt',
    'requirements-site.txt', 'requirements-site-wms.txt', 'requirements-site-wms.in', 'requirements-site-wms.lock',
    '.gitignore',
    '.codex', '.gemini', '.opencode', '.antigravity', '.ravel', 'addons', 'GEMINI.md',
}


def prose_only(text):
    """Discard fenced/inline code and comments while retaining line positions."""
    out, fence = [], None
    for line in text.splitlines(keepends=True):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            out.append('\n')
        else:
            out.append('\n' if fence else line)
    text = ''.join(out)
    text = re.sub(r'<!--.*?-->', lambda m: '\n' * m[0].count('\n'), text, flags=re.S)
    return re.sub(r'(`+)(.*?)\1', lambda m: '\n' * m[0].count('\n'), text, flags=re.S)


def markdown_links(text):
    text = prose_only(text)
    patterns = [
        r'!?\[[^\]\n]*\]\(\s*(?:<([^>\n]+)>|([^\s)]+))(?:\s+["\'][^\n]*?["\'])?\s*\)',
        r'^ {0,3}\[[^\]\n]+\]:\s*(?:<([^>\n]+)>|(\S+))',
        r'<(?:a|img)\b[^>]*?\b(?:href|src)=["\']([^"\']+)["\']',
    ]
    found = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.M | re.I):
            target = next(group for group in match.groups() if group is not None)
            found.append((text.count('\n', 0, match.start()) + 1, target))
    return found


def heading_ids(text):
    ids, seen = set(), {}
    # Keep inline code's visible heading text; discard fences and HTML comments.
    text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    in_fence = False
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.match(r'^ {0,3}(?:`{3,}|~{3,})', line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r'^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$', line)
        if match:
            title = match[1]
        elif line.strip() and index + 1 < len(lines) \
                and re.fullmatch(r' {0,3}(?:=+|-+)\s*', lines[index + 1]):
            title = line.strip()
        else:
            continue
        title = re.sub(r'!?\[([^\]]+)\]\([^)]*\)', r'\1', title)
        title = re.sub(r'<[^>]+>', '', title).replace('`', '').lower()
        slug = re.sub(r'[^\w\- ]', '', title, flags=re.UNICODE).replace(' ', '-')
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        ids.add(slug + (f'-{count}' if count else ''))
    ids.update(re.findall(r'<a\b[^>]*\b(?:id|name)=["\']([^"\']+)', text, re.I))
    return ids


def _exact_case(path, root):
    current = root.resolve()
    try:
        parts = path.relative_to(current).parts
    except ValueError:
        return False
    for part in parts:
        if not current.is_dir() or part not in {p.name for p in current.iterdir()}:
            return False
        current /= part
    return True


def check_link(root, document, target, *, public=None, shipped_paths=None):
    root = Path(root).resolve()
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        return None
    path, fragment = unquote(parsed.path), unquote(parsed.fragment)
    if '\\' in path or '\0' in path:
        return 'invalid local link path'
    # A leading slash denotes the repository root here, never an arbitrary local
    # filesystem root. Relative paths resolve only beside the referring document.
    relative = os.path.normpath(path.lstrip('/') if path.startswith('/')
                                else str(Path(document).parent / path) if path
                                else document).replace(os.sep, '/')
    if relative in ('.', ''):
        resolved = root
    else:
        try:
            resolved = evidence_layout.safe_path(root, relative)
        except (ValueError, OSError) as exc:
            return str(exc)
    if not _exact_case(resolved, root):
        return 'missing destination or incorrect filename case'
    if shipped_paths is not None and relative not in ('.', ''):
        if relative not in shipped_paths and not (resolved.is_dir() and
                any(path.startswith(relative.rstrip('/') + '/') for path in shipped_paths)):
            return 'destination exists in source but is absent from the public selection'
    if fragment:
        page = resolved / 'README.md' if resolved.is_dir() else resolved
        if page.suffix.lower() == '.md' and page.is_file():
            # GitHub also offers line anchors when viewing Markdown as source.
            if re.fullmatch(r'L\d+(?:-L\d+)?', fragment):
                return None
            if fragment.removeprefix('user-content-') not in heading_ids(page.read_text()):
                return f'missing Markdown heading #{fragment}'
    return None


def navigation_document(root, destination):
    """An authenticated instruction mirror retains its canonical logical base.

    These byte-exact runtime resources are not a standalone browser document tree.
    Checkout-only auxiliary links still need their selected canonical destinations.
    Undeclared or changed mirrors refuse rather than suppress navigation checks.
    """
    prefix = 'src/ravel/data/workflow/'
    if not destination.startswith(prefix):
        return destination
    logical = destination.removeprefix(prefix)
    if logical not in WORKFLOW_INSTRUCTIONS:
        raise ValueError('undeclared packaged workflow instruction: ' + logical)
    canonical = workflow_instruction(logical, source_root=root)
    copied = workflow_instruction(logical, source_root=Path(root) / prefix)
    if (canonical['sha256'], canonical['size']) != (copied['sha256'], copied['size']):
        raise ValueError('packaged workflow instruction differs from canonical source: ' + logical)
    return logical


def check(root=ROOT, public=False):
    root = Path(root).resolve()
    evidence_layout.load_registry(root)
    selection = evidence_layout.selected_files(root)
    errors = []
    public = public or evidence_layout.is_public_tree(root)
    if public:
        for path in root.iterdir():
            if path.name in LOCAL_TOOL_DIRS or path.name == '.venv' or path.name.startswith('.venv-'):
                continue
            if path.name not in PUBLIC_ROOTS:
                errors.append(f'{path.name}: forbidden public root entry')
        leaked = evidence_layout.source_fields(evidence_layout.load_registry(root)['distribution'])
        if leaked:
            errors.append(f'{evidence_layout.REGISTRY}: a public registry carries undistributed declarations {leaked}')
        checked, transforms, layout = selection, {}, None
    else:
        checked = evidence_layout.selected_files(root, include_internal=True)
        layout = evidence_layout.source_module(root)
        transforms = layout.load_public_transforms(root) if layout else {}
        if layout:
            errors.extend(layout.declaration_errors(root))
            errors.extend(layout.transformation_errors(root, selection, transforms))
    markdown_count = link_count = mirrored_count = 0
    shipped_paths = {destination for _source, destination in selection}
    checked_paths = {destination for _source, destination in checked}
    for source, destination in checked:
        name, suffix = Path(destination).name, Path(destination).suffix
        if suffix == '.py' and not re.fullmatch(r'[a-z_][a-z0-9_]*\.py', name):
            errors.append(f'{destination}: Python filename must use snake_case')
        if suffix in ('.sh', '.md') and name not in CONVENTIONAL and destination not in CONVENTIONAL_PATHS \
                and not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*\.(?:sh|md)', name):
            errors.append(f'{destination}: document/shell filename must use lowercase kebab-case')
        if suffix != '.md':
            continue
        markdown_count += 1
        try:
            document = navigation_document(root, destination)
        except (ValueError, OSError) as exc:
            errors.append(f'{destination}: {exc}')
            continue
        if document != destination and document not in checked_paths:
            errors.append(f'{destination}: canonical instruction is absent from the public selection')
            continue
        mirrored_count += document != destination
        raw = (root / source).read_text()
        # (label, text, allowed destinations): the text of an undistributed document may reach
        # the whole checked surface; every distributed text may reach only shipped files.
        if destination not in shipped_paths or (not public and destination in PUBLIC_INDEXES):
            versions = [(destination, raw, checked_paths)]
        elif destination in transforms:
            try:
                exported = layout.public_bytes(root, source, destination, transforms).decode()
            except (ValueError, OSError):
                exported = None  # reported by transformation_errors
            versions = [(destination, raw, checked_paths)]
            if exported is not None:
                versions.append((destination + ' (public copy)', exported, shipped_paths))
        else:
            versions = [(destination, raw, shipped_paths)]
        for label, text, allowed in versions:
            for line, target in markdown_links(text):
                link_count += 1
                error = check_link(root, document, target, public=public, shipped_paths=allowed)
                if error:
                    errors.append(f'{label}:{line}: {target!r}: {error}')
    return errors, {'files': len(selection), 'checked': len(checked), 'markdown': markdown_count,
                    'links': link_count, 'public': public, 'canonical_workflow_mirrors': mirrored_count}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--public', action='store_true')
    args = parser.parse_args(argv)
    try:
        errors, counts = check(args.root, args.public)
    except (ValueError, OSError) as exc:
        errors, counts = [str(exc)], {}
    for error in errors:
        print(f'[FAIL] repository: {error}')
    print(f'repository hygiene: {"FAIL" if errors else "OK"} ({counts})')
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
