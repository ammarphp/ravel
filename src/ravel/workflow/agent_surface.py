"""Install RAVEL's agent surface into another project without overriding its rules.

``ravel agent-surface install --project DIR`` adds, to an existing repository:
  - RAVEL's workflow skills in .claude/skills and the identical Codex mirror in
    .agents/skills, and RAVEL's rules as .claude/rules/ravel-*.md;
  - software skills for the tools actually installed here, generated from the
    toolchain manifest and the installed Python distributions, with versions;
  - prompt-logging hooks (UserPromptSubmit, Stop, SubagentStop) merged into
    .claude/settings.json, and a Codex notify snippet;
  - marked sections in CLAUDE.md (with an ``@AGENTS.md`` import first, so the
    project's own AGENTS.md is always loaded and stays the authority) and in
    AGENTS.md (appended; the project's text is never changed).

Existing files are never overwritten unless this installer wrote them and they
are unchanged since. ``ravel agent-surface check --project DIR`` (also
``python -m ravel.validation.check_agent_surface --project DIR``) verifies the
result. ``ravel agent-surface skills`` writes only the software skills.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys

from ravel import __version__
from ravel.paths import package_data_path, repository_root

MANIFEST = '.ravel/agent-surface.json'
BEGIN = '<!-- ravel:begin {name} -->'
END = '<!-- ravel:end {name} -->'
HOOK_EVENTS = ('UserPromptSubmit', 'Stop', 'SubagentStop')
HOOK_MARK = 'ravel.workflow.agent_audit hook'


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def surface():
    return json.loads(package_data_path('agent_surface', 'surface.json').read_text())


def _source_root(skills_from=None):
    if skills_from is not None:
        root = Path(skills_from).absolute()
        return root if (root / '.claude').is_dir() else root.parent.parent if root.name == 'skills' else root
    root = repository_root()
    if root is None or not (root / '.claude' / 'skills').is_dir():
        raise ValueError('RAVEL skills source not found; pass --skills-from <RAVEL checkout>')
    return root


def _python_command():
    """The interpreter and, for a source checkout, the import path, resolved now."""
    source = Path(__file__).resolve().parents[2]
    prefix = f'PYTHONPATH={shlex.quote(str(source))} ' if (source / 'ravel').is_dir() and source.name == 'src' else ''
    return prefix + shlex.quote(sys.executable)


# ------------------------------------------------------------- marked sections

def _section(text, name):
    begin, end = BEGIN.format(name=name), END.format(name=name)
    match = re.search(re.escape(begin) + r'.*?' + re.escape(end) + r'\n?', text, re.S)
    return match


def upsert_section(text, name, body, *, at_top=False):
    block = BEGIN.format(name=name) + '\n' + body.rstrip('\n') + '\n' + END.format(name=name) + '\n'
    match = _section(text, name)
    if match is not None:
        return text[:match.start()] + block + text[match.end():]
    if at_top:
        return block + ('\n' + text if text else '')
    return text + ('' if not text or text.endswith('\n') else '\n') + ('\n' if text else '') + block


def outside_sections(text):
    """The text that does not belong to RAVEL's marked sections."""
    return re.sub(r'<!-- ravel:begin ([a-z-]+) -->.*?<!-- ravel:end \1 -->\n?', '', text, flags=re.S).strip('\n')


def _first_instruction(text):
    return next((line.strip() for line in text.splitlines() if line.strip() and not line.startswith('<!-- ravel:')), None)


def _bundle_root():
    bundled = package_data_path('workflow')
    if (bundled / 'docs' / 'workflow' / 'start.md').is_file():
        return bundled
    root = repository_root()
    return root if root is not None else bundled


def guidance(skill_names, software_names, log_rel):
    docs = _bundle_root()
    return '\n'.join([
        '## RAVEL in this project',
        '',
        "This project's AGENTS.md is the authority. Where anything in this section differs from it, AGENTS.md wins.",
        '',
        f'RAVEL {__version__} is installed for the physics work in this repository.',
        f'- Start a physics request with {docs / "docs/workflow/start.md"}; the workflow documents it names are in {docs}.',
        '- RAVEL plan, approve and run keep their check-ins. A machine decision under delegation is recorded as a machine decision, never as human or physicist review.',
        '- Run analysis steps through the project\'s workflow manager. Use only software described in a skill.',
        '- Workflow skills: ' + ', '.join(skill_names) + '.',
        '- Software skills: ' + (', '.join(software_names) if software_names else 'none generated yet') + '.',
        f'- Every prompt is logged to {log_rel} by the hooks in .claude/settings.json. Keep them enabled; '
        '`ravel agent-audit build` turns the log into the submission prompt log.',
    ])


# ------------------------------------------------------------- software skills

def _distribution_version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def observe(names, executables=()):
    """Installed Python distributions and executables on PATH, with versions."""
    found = {}
    for name in names:
        version = _distribution_version(name)
        if version is not None:
            found[name] = {'kind': 'python-distribution', 'version': version}
    for name in executables:
        path = shutil.which(name)
        if path:
            found[name] = {'kind': 'executable', 'path': path}
    return found


def _skill_text(name, description, body):
    description = ' '.join(description.split())
    return f'---\nname: {name}\ndescription: {description}\n---\n\n{body.rstrip()}\n'


def software_skills(manifest=None, *, packages=None, executables=None, all_groups=False):
    """{skill name: SKILL.md text} for installed tools; never for absent ones."""
    data = surface()
    packages = data['python_packages'] if packages is None else packages
    executables = data['executables'] if executables is None else executables
    found = observe(packages, executables)
    skills = {}
    for name, row in sorted(found.items()):
        identity = 'software-' + re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
        if row['kind'] == 'python-distribution':
            body = (f'# {name} {row["version"]}\n\nInstalled Python distribution `{name}` version {row["version"]} '
                    f'(interpreter {sys.executable}, Python {sys.version.split()[0]}).\n\n'
                    '- Run it only inside steps of the project workflow, never as an ad-hoc command.\n'
                    '- Record this version in the environment lock of any submission.\n')
            description = f'Use when code in this project imports {name}; installed version {row["version"]}. Run it only through the workflow.'
        else:
            body = (f'# {name}\n\nExecutable `{name}` found at {row["path"]}.\n\n'
                    '- Run it only inside steps of the project workflow.\n'
                    '- Record its version from its own version command in the environment capture.\n')
            description = f'Use when a workflow step runs the {name} executable installed at {row["path"]}; run it only through the workflow.'
        skills[identity] = _skill_text(identity, description, body)
    if manifest is not None:
        document = json.loads(Path(manifest).read_text())
        for group in document.get('groups', []):
            keys = [k for k in group.get('version_contract', {}) if k != 'python']
            observed = {k: v for k, v in observe(keys, keys).items()}
            if not observed and not all_groups:
                continue
            identity = 'software-' + group['id']
            rows = '\n'.join(f'| {k} | {v} | {observed.get(k, {}).get("version") or observed.get(k, {}).get("path") or "not found here"} |'
                             for k, v in group['version_contract'].items())
            checks = '\n'.join('    ' + c for c in group.get('readiness_commands', [])) or '    (none declared)'
            body = (f'# {group["title"]}\n\n| Component | Required version | Found here |\n|---|---|---|\n{rows}\n\n'
                    f'Readiness checks declared by RAVEL\'s toolchain manifest:\n\n{checks}\n\n'
                    '- Run these tools only inside steps of the project workflow.\n'
                    '- A component marked "not found here" is not installed in this environment; install it before a step needs it.\n')
            description = (f'Use when a workflow step needs {group["title"]} ({", ".join(group["version_contract"])}); '
                           'lists required and installed versions and readiness checks.')
            skills[identity] = _skill_text(identity, description, body)
    from ravel.cli import FOCUSED_COMMANDS
    commands = '\n'.join(f'- `ravel {c}`: {d}' for c, (_, d) in sorted(FOCUSED_COMMANDS.items()))
    skills['software-ravel'] = _skill_text(
        'software-ravel', f'Use when running the ravel command-line tool (version {__version__}) for planning, approval, '
        'execution, audit logs, agent sessions or submission export in this project.',
        f'# ravel {__version__}\n\nInterpreter: {sys.executable}\n\n'
        'Lifecycle: `ravel initiate`, `ravel plan`, `ravel approve`, `ravel run`, `ravel status`.\n\n'
        f'Focused commands:\n\n{commands}\n')
    return skills


# ------------------------------------------------------------- install / check

def _load_manifest(project):
    path = project / MANIFEST
    return json.loads(path.read_text()) if path.is_file() else {'files': {}}


def _write_owned(project, rel, raw, previous, report):
    """Write a file this installer owns; leave foreign or user-edited files alone."""
    path = project / rel
    if path.exists():
        current = _sha(path.read_bytes())
        recorded = previous['files'].get(rel)
        if recorded is None:
            if current != _sha(raw):
                report['conflicts'].append(rel)
                return None
        elif recorded != current:
            report['user_modified'].append(rel)
            return recorded
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or _sha(path.read_bytes()) != _sha(raw):
        path.write_bytes(raw)
        report['written'].append(rel)
    return _sha(raw)


def _merge_hooks(settings, command):
    hooks = settings.setdefault('hooks', {})
    for event in HOOK_EVENTS:
        groups = hooks.setdefault(event, [])
        present = any(HOOK_MARK in h.get('command', '') for g in groups for h in g.get('hooks', []))
        if not present:
            groups.append({'matcher': '', 'hooks': [{'type': 'command', 'command': command, 'timeout': 30}]})
    return settings


def install(project, *, skills_from=None, manifest=None, include_software=True, all_groups=False):
    project = Path(project).absolute()
    if not project.is_dir():
        raise ValueError('project directory must exist')
    data = surface()
    source = _source_root(skills_from)
    previous = _load_manifest(project)
    report = {'written': [], 'conflicts': [], 'user_modified': [], 'skipped_skills': []}
    files = {}
    installed = []
    for name in data['skills']:
        skill_dir = source / '.claude' / 'skills' / name
        if not (skill_dir / 'SKILL.md').is_file():
            report['skipped_skills'].append(name)
            continue
        conflicts = len(report['conflicts'])
        for path in sorted(p for p in skill_dir.rglob('*') if p.is_file() and p.name != '.DS_Store'):
            relative = path.relative_to(skill_dir).as_posix()
            raw = path.read_bytes()
            for base in ('.claude/skills', '.agents/skills'):
                rel = f'{base}/{name}/{relative}'
                digest = _write_owned(project, rel, raw, previous, report)
                if digest:
                    files[rel] = digest
        if len(report['conflicts']) == conflicts:
            installed.append(name)
        else:
            report['skipped_skills'].append(name)
    for rule in data['rules']:
        path = source / '.claude' / 'rules' / rule
        if path.is_file():
            rel = f'.claude/rules/ravel-{rule}'
            digest = _write_owned(project, rel, path.read_bytes(), previous, report)
            if digest:
                files[rel] = digest
    from . import role_registry
    for host in role_registry.SURFACES:
        for rel, text in role_registry.render(host).items():
            # Project routing rules remain authoritative and are merged below.
            if rel in ('AGENTS.md', 'CLAUDE.md'):
                continue
            digest = _write_owned(project, rel, text.encode(), previous, report)
            if digest:
                files[rel] = digest
    if manifest is None and repository_root() is not None:
        candidate = repository_root() / 'native' / 'setup' / 'toolchain-manifest.json'
        manifest = candidate if candidate.is_file() else None
    software = software_skills(manifest, all_groups=all_groups) if include_software else {}
    for name, text in software.items():
        for base in ('.claude/skills', '.agents/skills'):
            rel = f'{base}/{name}/SKILL.md'
            digest = _write_owned(project, rel, text.encode(), previous, report)
            if digest:
                files[rel] = digest
    log_rel = data['audit_log']
    command = f'{_python_command()} -m {HOOK_MARK} --log "$CLAUDE_PROJECT_DIR/{log_rel}"'
    settings_path = project / '.claude' / 'settings.json'
    settings = json.loads(settings_path.read_text()) if settings_path.is_file() else {}
    if 'env' in settings and not isinstance(settings['env'], dict):
        raise ValueError('.claude/settings.json env must be a JSON object')
    merged = _merge_hooks(json.loads(json.dumps(settings)), command)
    # This installer is already importing ravel through this interpreter. Pin it for
    # hand-maintained Claude hooks instead of relying on the host's Python PATH.
    merged.setdefault('env', {})['RAVEL_PYTHON'] = sys.executable
    if merged != settings:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(merged, indent=2) + '\n')
        report['written'].append('.claude/settings.json')
    notify = ['/bin/sh', '-c', f'{_python_command()} -m ravel.workflow.agent_audit codex-notify --log {shlex.quote(str(project / log_rel))} "$1"', 'ravel-notify']
    snippet = '# Add to your Codex config.toml to log each completed Codex turn for this project.\nnotify = ' + json.dumps(notify) + '\n'
    digest = _write_owned(project, '.ravel/codex-notify.toml', snippet.encode(), previous, report)
    if digest:
        files['.ravel/codex-notify.toml'] = digest
    body = guidance(installed, sorted(software), log_rel)
    agents_path, claude_path = project / 'AGENTS.md', project / 'CLAUDE.md'
    agents_text = agents_path.read_text() if agents_path.is_file() else ''
    original_agents = outside_sections(agents_text)
    new_agents = upsert_section(agents_text, 'agent-surface',
                                body.replace("This project's AGENTS.md is the authority. Where anything in this section differs from it, AGENTS.md wins.",
                                             'These RAVEL notes add to the rules above and never relax them. Where they differ, the rules above win.'))
    if new_agents != agents_text:
        agents_path.write_text(new_agents)
        report['written'].append('AGENTS.md')
    claude_text = claude_path.read_text() if claude_path.is_file() else ''
    new_claude = claude_text
    if _first_instruction(claude_text) != '@AGENTS.md':
        new_claude = upsert_section(new_claude, 'agents-import', '@AGENTS.md', at_top=True)
    new_claude = upsert_section(new_claude, 'agent-surface', body)
    if new_claude != claude_text:
        claude_path.write_text(new_claude)
        report['written'].append('CLAUDE.md')
    record = {'schema_version': 1, 'kind': 'ravel-agent-surface-install', 'ravel_version': __version__,
              'role_registry_sha256': role_registry.registry_sha256(),
              'installed_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'python': sys.executable, 'hook_command': command, 'audit_log': log_rel,
              'skills': installed, 'software_skills': sorted(software), 'files': dict(sorted(files.items())),
              'agents_md_project_text_sha256': _sha(original_agents.encode()),
              'claude_md_project_text_sha256': _sha(outside_sections(claude_text).encode())}
    (project / MANIFEST).parent.mkdir(parents=True, exist_ok=True)
    (project / MANIFEST).write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    return {**report, 'manifest': str(project / MANIFEST), 'skills': installed, 'software_skills': sorted(software)}


def _frontmatter_errors(path, name):
    text = path.read_text(encoding='utf-8')
    match = re.match(r'^---\n(.*?)\n---\n', text, re.S)
    if not match:
        return [f'{name}: no frontmatter']
    errors = []
    found = re.search(r'^name:\s*(\S+)\s*$', match.group(1), re.M)
    if not found or found.group(1) != name:
        errors.append(f'{name}: frontmatter name differs from its directory')
    description = re.search(r'^description:\s*(.+?)(?=^\w+:|\Z)', match.group(1), re.M | re.S)
    if not description or len(' '.join(description.group(1).split())) < 40:
        errors.append(f'{name}: description missing or too short to trigger')
    return errors


def check(project):
    """Errors in an installed agent surface; an empty list means it passes."""
    project = Path(project).absolute()
    path = project / MANIFEST
    if not path.is_file():
        return [f'{MANIFEST} missing: run ravel agent-surface install']
    record = json.loads(path.read_text())
    errors = []
    from . import role_registry
    if record.get('role_registry_sha256') != role_registry.registry_sha256():
        errors.append('installed role registry is stale: re-run agent-surface install')
    errors.extend(role_registry.check_rendered(project, exclude=('AGENTS.md', 'CLAUDE.md')))
    for rel, digest in record['files'].items():
        target = project / rel
        if not target.is_file():
            errors.append(f'installed file missing: {rel}')
        elif _sha(target.read_bytes()) != digest:
            errors.append(f'installed file changed: {rel}')
    for name in [*record['skills'], *record['software_skills']]:
        source = project / '.claude/skills' / name / 'SKILL.md'
        mirror = project / '.agents/skills' / name / 'SKILL.md'
        if not source.is_file():
            errors.append(f'skill missing: {name}')
            continue
        errors.extend(_frontmatter_errors(source, name))
        left = {p.relative_to(source.parent).as_posix(): p.read_bytes() for p in source.parent.rglob('*') if p.is_file()}
        right = {p.relative_to(mirror.parent).as_posix(): p.read_bytes() for p in mirror.parent.rglob('*') if p.is_file()} if mirror.parent.is_dir() else {}
        if left != right:
            errors.append(f'Codex mirror differs for skill {name}')
    agents = (project / 'AGENTS.md').read_text() if (project / 'AGENTS.md').is_file() else ''
    claude = (project / 'CLAUDE.md').read_text() if (project / 'CLAUDE.md').is_file() else ''
    if _sha(outside_sections(agents).encode()) != record['agents_md_project_text_sha256']:
        errors.append("AGENTS.md project text changed since install; re-run the installer after reviewing it")
    for name, text in (('AGENTS.md', agents), ('CLAUDE.md', claude)):
        if text.count('<!-- ravel:begin ') != text.count('<!-- ravel:end '):
            errors.append(f'{name}: unbalanced RAVEL section markers')
        if _section(text, 'agent-surface') is None:
            errors.append(f'{name}: RAVEL section missing')
    if (project / 'AGENTS.md').is_file() and _first_instruction(claude) != '@AGENTS.md':
        errors.append('CLAUDE.md must import @AGENTS.md before any other instruction')
    settings_path = project / '.claude/settings.json'
    settings = json.loads(settings_path.read_text()) if settings_path.is_file() else {}
    for event in HOOK_EVENTS:
        commands = [h.get('command', '') for g in settings.get('hooks', {}).get(event, []) for h in g.get('hooks', [])]
        if not any(HOOK_MARK in c for c in commands):
            errors.append(f'prompt-log hook missing for {event}')
    if not Path(record['python']).exists():
        errors.append('hook interpreter no longer exists: ' + record['python'])
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel agent-surface', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    i = commands.add_parser('install', help='install skills, hooks and rules into a project')
    i.add_argument('--project', type=Path, required=True)
    i.add_argument('--skills-from', type=Path, help='RAVEL checkout providing .claude/skills and .claude/rules')
    i.add_argument('--toolchain-manifest', type=Path)
    i.add_argument('--all-groups', action='store_true', help='also describe toolchain groups not found here')
    c = commands.add_parser('check', help='verify an installed agent surface')
    c.add_argument('--project', type=Path, required=True)
    p = commands.add_parser('profiles', help='resolve the installed verification-panel profiles')
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--host', choices=('claude', 'codex', 'gemini', 'antigravity', 'opencode', 'governed-node', 'hookless'), required=True)
    r = commands.add_parser('render', help='regenerate canonical role surfaces in a checkout')
    r.add_argument('--project', type=Path, required=True)
    s = commands.add_parser('skills', help='print or write software skills for installed tools')
    s.add_argument('--toolchain-manifest', type=Path)
    s.add_argument('--out', type=Path, help='skills directory to write into (new skill directories only)')
    args = parser.parse_args(argv)
    try:
        if args.command == 'install':
            result = install(args.project, skills_from=args.skills_from, manifest=args.toolchain_manifest,
                             all_groups=args.all_groups)
        elif args.command == 'check':
            errors = check(args.project)
            print(json.dumps({'passed': not errors, 'errors': errors}, indent=2))
            return 1 if errors else 0
        elif args.command == 'profiles':
            from .role_registry import resolve_panel
            result = resolve_panel(args.project, args.host)
        elif args.command == 'render':
            from .role_registry import main as render_main
            return render_main(['--write', '--project', str(args.project)])
        else:
            skills = software_skills(args.toolchain_manifest)
            if args.out:
                for name, text in skills.items():
                    target = args.out / name / 'SKILL.md'
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open('x', encoding='utf-8') as stream:
                        stream.write(text)
            result = {'skills': sorted(skills)}
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'agent surface: {exc}\n')
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
