"""Software skill files that describe the processing software a project's workflow may use.

``generate(project, manifest)`` returns ``{relative path: text}`` for one skill per Python
distribution and native executable the agent surface names (``data/agent_surface/surface.json``),
per toolchain group, and for RAVEL itself with its runtime dependency tree. Every file states what
the tool is for in this project, its exact version, the import names and entry points it exposes,
the commands the workflow reaches it through, its licence and its upstream documentation link when
the distribution metadata carries one. Nothing is invented: a field the metadata lacks says so.

The text is deterministic for one installed environment (no paths, times or ordering that varies),
so a tracked skill file changes only when an installed version, licence or entry point does, and the
change shows as a diff of exactly those lines. A tool that is not installed has no skill.

``covered(name)`` is the question the execution guard asks: does an installed skill describe this
program? A project's own additions are read from ``workflow/policy.json`` key ``software``.
"""
import functools
import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import subprocess

from ravel import __version__
from ravel.paths import package_data_path

DISTRIBUTION = 'ravel-hep'
BASES = ('.claude/skills', '.agents/skills')
UNDECLARED = 'not declared in the distribution metadata'
PROBE_SECONDS = 10


def canonical(name):
    return re.sub(r'[-_.]+', '-', str(name)).strip('-').lower()


def identity(name):
    return 'software-' + re.sub(r'[^a-z0-9]+', '-', str(name).lower()).strip('-')


def purposes():
    return json.loads(package_data_path('agent_surface', 'software.json').read_text())['tools']


def _surface():
    return json.loads(package_data_path('agent_surface', 'surface.json').read_text())


def declared(project):
    """Extra distributions and executables a project's workflow policy declares."""
    path = Path(project) / 'workflow' / 'policy.json' if project is not None else None
    if path is None or not path.is_file():
        return [], []
    try:
        section = json.loads(path.read_text()).get('software') or {}
    except ValueError:
        return [], []
    rows = [[str(n) for n in section.get(key, []) if isinstance(n, str)] for key in ('python_packages', 'executables')]
    return rows[0], rows[1]


def candidates(project=None, *, packages=None, executables=None):
    """The distribution and executable names this project's skills may describe, sorted."""
    surface = _surface()
    extra_packages, extra_executables = declared(project)
    packages = surface['python_packages'] if packages is None else packages
    executables = surface['executables'] if executables is None else executables
    return sorted(set(packages) | set(extra_packages)), sorted(set(executables) | set(extra_executables))


# ------------------------------------------------------------------ metadata

def _distribution(name):
    try:
        return importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return None


@functools.lru_cache(maxsize=1)
def _import_names():
    names = {}
    for module, dists in importlib.metadata.packages_distributions().items():
        for dist in dists:
            names.setdefault(canonical(dist), set()).add(module)
    return {k: sorted(v) for k, v in names.items()}


def _licence(metadata):
    expression = (metadata.get('License-Expression') or '').strip()
    if expression:
        return expression
    text = ' '.join((metadata.get('License') or '').split())
    if text and text.upper() != 'UNKNOWN' and len(text) <= 80:
        return text
    classifiers = sorted(c.rsplit('::', 1)[-1].strip() for c in metadata.get_all('Classifier') or []
                         if c.startswith('License ::') and not c.endswith(':: OSI Approved'))
    if classifiers:
        return '; '.join(classifiers)
    return UNDECLARED


def _documentation(metadata):
    rows = {}
    for entry in metadata.get_all('Project-URL') or []:
        label, _, url = entry.partition(',')
        if url.strip():
            rows.setdefault(label.strip().lower(), url.strip())
    for label in ('documentation', 'docs', 'homepage', 'home', 'home page', 'source', 'repository', 'source code'):
        if label in rows:
            return rows[label]
    home = (metadata.get('Home-page') or '').strip()
    return home if home and home.upper() != 'UNKNOWN' else None


def describe_distribution(name):
    """The metadata-derived facts of one installed distribution, or None."""
    dist = _distribution(name)
    if dist is None:
        return None
    metadata = dist.metadata
    scripts = sorted(f'{ep.name} = {ep.value}' for ep in dist.entry_points if ep.group == 'console_scripts')
    summary = ' '.join((metadata.get('Summary') or '').split())
    return {'name': metadata.get('Name') or name, 'version': dist.version, 'summary': summary,
            'imports': _import_names().get(canonical(name), []), 'entry_points': scripts,
            'licence': _licence(metadata), 'documentation': _documentation(metadata)}


def _version_line(path, args):
    if not args:
        return None
    try:
        done = subprocess.run([path, *args], capture_output=True, text=True, timeout=PROBE_SECONDS, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in (done.stdout + '\n' + done.stderr).splitlines():
        if line.strip():
            return line.strip()[:120]
    return None


def describe_executable(name, *, probe=True):
    path = shutil.which(name)
    if path is None:
        return None
    args = purposes().get(name, {}).get('version_args')
    return {'name': name, 'version': _version_line(path, args) if probe and args else None}


# ------------------------------------------------------------ dependency tree

def _requirement_name(text):
    return re.match(r'\s*([A-Za-z0-9][A-Za-z0-9._-]*)', text).group(1)


def _applies(text):
    """True when a requirement string applies without extras in this environment."""
    if ';' not in text:
        return True
    try:
        from packaging.requirements import Requirement
        marker = Requirement(text).marker
        return True if marker is None else bool(marker.evaluate({'extra': ''}))
    except Exception:
        return 'extra ==' not in text.replace('"', "'").replace("'", '"') and 'extra==' not in text


def _root_requirements():
    dist = _distribution(DISTRIBUTION)
    if dist is not None and dist.requires:
        return list(dist.requires)
    from ravel.paths import repository_root
    root = repository_root()
    if root is not None and (root / 'pyproject.toml').is_file():
        import tomllib
        return list(tomllib.loads((root / 'pyproject.toml').read_text())['project'].get('dependencies', []))
    return []


def runtime_dependencies():
    """Installed distributions in RAVEL's required-dependency closure, sorted by name."""
    seen, queue = {}, [r for r in _root_requirements() if _applies(r)]
    while queue:
        name = canonical(_requirement_name(queue.pop()))
        if name in seen or name == canonical(DISTRIBUTION):
            continue
        dist = _distribution(name)
        if dist is None:
            seen[name] = None
            continue
        seen[name] = dist
        queue.extend(r for r in dist.requires or [] if _applies(r))
    return sorted(n for n, d in seen.items() if d is not None)


# --------------------------------------------------------------------- text

def _skill_text(name, description, body):
    return f'---\nname: {name}\ndescription: {" ".join(description.split())}\n---\n\n{body.rstrip()}\n'


def _purpose(name, summary=''):
    row = purposes().get(name)
    if row:
        return row['purpose']
    return f'RAVEL runtime dependency. Upstream summary: {summary}' if summary else 'RAVEL runtime dependency.'


def _tool_skill(name, dist, exe):
    row = purposes().get(name, {})
    lines = [f'# {name}', '']
    if dist:
        lines.append(f'Version: {dist["version"]}')
    elif exe:
        lines.append(f'Version: {exe["version"] or "not reported by the tool; see the environment capture"}')
    if dist and exe:
        lines.append(f'Executable version: {exe["version"] or "not reported by the tool; see the environment capture"}')
    kinds = [k for k, v in (('Python distribution', dist), ('native executable', exe)) if v]
    lines += [f'Kind: {" and ".join(kinds)}', f'Purpose in this project: {_purpose(name, dist["summary"] if dist else "")}', '']
    if dist:
        lines.append('Import names: ' + (', '.join(f'`{i}`' for i in dist['imports']) or 'none recorded'))
        lines.append('Entry points: ' + ('; '.join(f'`{e}`' for e in dist['entry_points']) or 'none'))
    if exe:
        lines.append(f'Executable: `{name}` (resolved from PATH at run time)')
    commands = row.get('commands') or []
    lines += ['', 'Commands the workflow reaches it through:']
    lines += [f'- `{c}`' for c in commands] or ['- none of its own: it runs inside the stage a workflow rule launches']
    if dist:
        lines += ['', f'Licence: {dist["licence"]}', f'Upstream documentation: {dist["documentation"] or UNDECLARED}']
    use = ('- Use it directly only through the commands listed above; any other use is a workflow step.' if row.get('direct')
           else '- Run it only inside steps of the project workflow, never as an ad-hoc command.')
    lines += ['', 'Rules:', use, '- Record this version in the environment capture of any submission.']
    description = (f'Use when a workflow step in this project uses {name} ({_purpose(name, dist["summary"] if dist else "").rstrip(".")}); '
                   'gives its exact version, import names, entry points, workflow commands and licence.')
    return {'SKILL.md': _skill_text(identity(name), description, '\n'.join(lines))}


def _group_skill(group, observed):
    keys = [k for k in group.get('version_contract', {}) if k != 'python']
    rows = '\n'.join(f'| {k} | {v} | {observed.get(k) or "not found here"} |' for k, v in group['version_contract'].items())
    checks = '\n'.join('    ' + c for c in group.get('readiness_commands', [])) or '    (none declared)'
    body = (f'# {group["title"]}\n\n| Component | Required version | Found here |\n|---|---|---|\n{rows}\n\n'
            f'Readiness checks declared by RAVEL\'s toolchain manifest:\n\n{checks}\n\n'
            '- Run these tools only inside steps of the project workflow.\n'
            '- A component marked "not found here" is not installed in this environment; install it before a step needs it.\n')
    description = (f'Use when a workflow step needs {group["title"]} ({", ".join(keys) or "python"}); '
                   'lists required and installed versions and readiness checks.')
    return {'SKILL.md': _skill_text(identity(group['id']), description, body)}


def _ravel_skill(dependencies):
    from ravel.cli import FOCUSED_COMMANDS
    commands = '\n'.join(f'- `ravel {c}`: {d}' for c, (_, d) in sorted(FOCUSED_COMMANDS.items()))
    body = (f'# ravel\n\nVersion: {__version__}\n'
            f'Kind: Python distribution and command line\nPurpose in this project: {purposes()["ravel"]["purpose"]}\n\n'
            'Interpreter: the project\'s pinned `RAVEL_PYTHON` (`.claude/settings.json`).\n\n'
            'Lifecycle: `ravel initiate`, `ravel plan`, `ravel approve`, then `ravel wms add` and `ravel wms launch` '
            'where the project requires the workflow manager (`ravel run` otherwise), then `ravel status`.\n\n'
            f'Focused commands:\n\n{commands}\n\n'
            f'The runtime dependency tree ({len(dependencies)} distributions) is listed in `dependencies.md` in this directory.\n\n'
            'Licence: Apache-2.0\n')
    description = (f'Use when running the ravel command-line tool for planning, approval, workflow-manager launch, '
                   'status, audit logs, agent sessions or submission export in this project.')
    rows = ['# RAVEL runtime dependencies', '',
            'Installed distributions in the required-dependency closure of `ravel-hep`. These run inside RAVEL\'s own code; '
            'none is a command the workflow invokes directly.', '',
            '| Distribution | Version | Licence | Entry points | Documentation | Purpose |', '|---|---|---|---|---|---|']
    for name in dependencies:
        info = describe_distribution(name)
        cells = [info['name'], info['version'], info['licence'].replace('|', '/'),
                 ', '.join(e.split(' = ')[0] for e in info['entry_points']) or 'none',
                 info['documentation'] or UNDECLARED, (info['summary'] or 'no summary').replace('|', '/')]
        rows.append('| ' + ' | '.join(cells) + ' |')
    return {'SKILL.md': _skill_text('software-ravel', description, body), 'dependencies.md': '\n'.join(rows) + '\n'}


# ---------------------------------------------------------------- interface

def build(manifest=None, *, project=None, packages=None, executables=None, probe=True, all_groups=False):
    """{skill name: {file name: text}} for the tools installed in this environment."""
    packages, executables = candidates(project, packages=packages, executables=executables)
    skills = {}
    for name in sorted(set(packages) | set(executables)):
        if name == 'ravel':
            continue
        dist = describe_distribution(name) if name in packages else None
        exe = describe_executable(name, probe=probe) if name in executables else None
        if dist or exe:
            skills[identity(name)] = _tool_skill(name, dist, exe)
    if manifest is not None:
        from ravel.setup.manifest import view, read_json
        path = Path(manifest)
        # A tree's main file is read with its group fragments; any other named file is read as given.
        document = (view(path.parents[2]) if path.parts[-3:] == ('native', 'setup', 'toolchain-manifest.json')
                    else read_json(path))
        for group in document.get('groups', []):
            keys = [k for k in group.get('version_contract', {}) if k != 'python']
            observed = {}
            for key in keys:
                dist = _distribution(key)
                if dist is not None:
                    observed[key] = dist.version
                elif shutil.which(key):
                    observed[key] = 'found on PATH'
            if observed or all_groups:
                skills[identity(group['id'])] = _group_skill(group, observed)
    skills['software-ravel'] = _ravel_skill(runtime_dependencies())
    return skills


def generate(project, manifest=None, **options):
    """{project-relative path: text} for every software skill, in the Claude and Codex locations."""
    files = {}
    for name, parts in build(manifest, project=project, **options).items():
        for base in BASES:
            for filename, text in parts.items():
                files[f'{base}/{name}/{filename}'] = text
    return dict(sorted(files.items()))


def covered(name, project=None):
    """True when an installed distribution or executable of this name has a software skill."""
    packages, executables = candidates(project)
    base = Path(name).name
    if base == 'ravel':
        return True
    if base in executables and shutil.which(base):
        return True
    return base in packages and _distribution(base) is not None
