"""Install RAVEL's agent surface into another project without overriding its rules.

``ravel agent-surface install --project DIR`` adds, to an existing repository:
  - RAVEL's workflow skills in .claude/skills and the identical Codex mirror in
    .agents/skills, and RAVEL's rules as .claude/rules/ravel-*.md;
  - software skills for the tools actually installed here, generated from the
    toolchain manifest and the installed Python distributions, with versions;
  - prompt-logging hooks (UserPromptSubmit, Stop, SubagentStop) merged into
    .claude/settings.json, and a Codex notify snippet;
  - portable guidance in .ravel/agent-guidance.md; existing project instruction
    documents stay byte-identical. Load that guidance from the host session.
  - a shell discipline hook, on by default when project policy requires a
    workflow manager. It grants no approval and is not a security boundary.

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
LOCAL = '.ravel/agent-surface.local.json'
RUNTIME = '.ravel/hook-runtime.sh'
GUIDANCE = '.ravel/agent-guidance.md'
# One Bash hook: the execution guard. Its discipline mode (policy wms_required without strict) asks
# guard_command below through execution_guard.discipline_refusal.
GUARD_MARK = 'ravel.workflow.execution_guard hook'
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
    """Portable hook resolver; machine locations live in an ignored local file."""
    return ('CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"; '
            'if [ -f "$CLAUDE_PROJECT_DIR/.ravel/hook-runtime.sh" ]; then '
            '. "$CLAUDE_PROJECT_DIR/.ravel/hook-runtime.sh"; fi; '
            '"${RAVEL_PYTHON:-python3}"')


def _wms_required(project):
    """Use the launch policy owner when installed; otherwise read its file seam."""
    try:
        from .wms_policy import required
    except ModuleNotFoundError as exc:
        if exc.name != 'ravel.workflow.wms_policy':
            raise
    else:
        return required(project)
    required_here = False
    root = Path(project).resolve()
    for folder in (root, *root.parents):
        path = folder / 'workflow/policy.json'
        if not path.exists():
            continue
        row = json.loads(path.read_bytes())
        if (type(row) is not dict or not {'schema_version', 'wms_required', 'engine'} <= set(row)
                or set(row) - {'schema_version', 'wms_required', 'engine', 'execution_guard', 'software'}
                or type(row.get('schema_version')) is not int or row['schema_version'] != 1
                or type(row.get('wms_required')) is not bool or row.get('engine') != 'snakemake'):
            raise ValueError('malformed workflow policy: ' + str(path))
        required_here |= row['wms_required']
    return required_here


ROUTE = 'Use `ravel wms add` then `ravel wms launch`; never approve through the workflow manager.'
# Words that precede a command without changing which program starts.
_PREFIXES = {'env', 'exec', 'command', 'nohup', 'time', 'nice', 'then', 'do', 'else', 'elif', 'if', 'while', '!', '{'}
_UNPARSED = re.compile(r'(?:^|[\s;&|(/])ravel\s+run(?:\s|$)'
                       r'|-m\s+ravel(?:\.workflow\.science)?\s+(?:\S+\s+)*?run(?:\s|$)'
                       r'|(?:^|\s)run-step(?:\s|$)')


def guard_command(project, command):
    """Refusal text for common direct launch spellings; no shell is executed.

    This is agent discipline. Arbitrary programs, aliases and shell expansion
    cannot be policed by a lexical hook. The launch guard remains authoritative.
    """
    if not _wms_required(project):
        return None
    if not isinstance(command, str):
        raise ValueError('shell command must be a string')
    lexer = shlex.shlex(command.replace('\n', ';'), posix=True, punctuation_chars=';&|()')
    lexer.whitespace_split = True
    # A comment must not hide the commands on the lines after it.
    lexer.commenters = ''
    try:
        tokens = list(lexer)
    except ValueError:
        # Text this lexer cannot split (an unquoted here-document, a comment with
        # an apostrophe) is refused only when it spells a direct launch.
        return ROUTE if _UNPARSED.search(command) else None
    groups, group = [], []
    for token in tokens + [';']:
        if token and set(token) <= set(';&|()'):
            if group:
                groups.append(group)
                group = []
        else:
            group.append(token)
    for argv in groups:
        # Shell wrappers and assignment/env/exec prefixes are common in agent tools.
        while argv and (argv[0] in _PREFIXES or re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', argv[0])):
            argv = argv[1:]
        if not argv:
            continue
        executable = Path(argv[0]).name
        if executable in {'sh', 'bash', 'zsh'} and '-c' in argv:
            index = argv.index('-c') + 1
            if index < len(argv) and guard_command(project, argv[index]):
                return ROUTE
        direct = executable == 'ravel' and len(argv) > 1 and argv[1] == 'run'
        module = argv[argv.index('-m') + 1:] if '-m' in argv and argv.index('-m') + 1 < len(argv) else []
        direct |= executable.startswith('python') and module[:1] == ['ravel.workflow.science'] and 'run' in module[1:]
        direct |= executable.startswith('python') and module[:1] == ['ravel'] and module[1:2] == ['run']
        direct |= executable in {'ravel', 'ravel-site-workflow'} and 'run-step' in argv[1:]
        direct |= executable.startswith('python') and module[:1] == ['ravel.workflow.site_workflow'] and 'run-step' in module[1:]
        if direct:
            return ROUTE
    return None


def _guard_approval(project, path):
    if path is None:
        raise ValueError('disabling the workflow-manager guard requires a recorded --guard-approval')
    path = Path(path).resolve()
    row = json.loads(path.read_bytes())
    if (type(row) is not dict or type(row.get('schema_version')) is not int
            or row.get('schema_version') != 1 or row.get('action') != 'wms-guard-opt-out'
            or row.get('approved') is not True or not isinstance(row.get('approved_by'), str)
            or not row['approved_by'].strip() or not isinstance(row.get('reason'), str)
            or not row['reason'].strip() or not isinstance(row.get('project'), str)
            or not row['project'].strip() or Path(row['project']).resolve() != project.resolve()):
        raise ValueError('guard approval must record the project, action, approval, approved_by and reason')
    return {'path': str(path), 'sha256': _sha(path.read_bytes())}


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


def guidance(skill_names, software_names, log_rel, *, project=None, guard=False):
    route = "ravel wms launch" if project is not None and _wms_required(project) else "ravel run"
    return '\n'.join([
        '## RAVEL in this project',
        '',
        "This project's AGENTS.md is the authority. Where anything in this section differs from it, AGENTS.md wins.",
        '',
        f'RAVEL {__version__} is installed for the physics work in this repository.',
        '- Start with the packaged docs/workflow/start.md; resolve its location with `ravel.paths.workflow_instruction`.',
        f'- RAVEL plan and approve keep their check-ins; execute approved stages through `{route}`. Use only software described in a skill. Never approve through the workflow manager. A machine decision under delegation remains a machine decision.',
        '- MCP site tools follow .ravel/site-tools/<host>.json: check exact approved effects before calling and observe afterward; hookless hosts have no automatic pre-call guard.',
        '- Workflow skills: ' + ', '.join(skill_names) + '.',
        '- Software skills: ' + (', '.join(software_names) if software_names else 'none generated yet') + '.',
        f'- Every prompt is logged to {log_rel} by the hooks in .claude/settings.json. Keep them enabled; '
        '`ravel agent-audit build` turns the log into the submission prompt log.',
        *(['- The execution guard is installed. Where workflow/policy.json sets "execution_guard": "strict", the shell tool '
           'runs only the workflow manager, ravel and read-only inspection; where it only requires the workflow manager, '
           'direct stage launches are refused. Every decision is logged to .ravel/agent-audit/execution-guard.jsonl. '
           'It is a client-side hook: it covers this agent\'s shell tool when the project settings are loaded, not a '
           'person at a terminal or a session started without them, and it grants no approval.'] if guard else []),
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
            found.setdefault(name, {'kind': 'executable'})['path'] = path
    return found


def _skill_text(name, description, body):
    description = ' '.join(description.split())
    return f'---\nname: {name}\ndescription: {description}\n---\n\n{body.rstrip()}\n'


def _site_wms_version(project):
    """Version declared by the site-wms record of the project or the declared site prefix.

    Only the declaration is read. The record's owner validates its lock and paths
    when it resolves the shim; nothing is probed or executed here.
    """
    for root in (project, os.environ.get('RAVEL_SITE_PREFIX'), os.environ.get('RAVEL_NATIVE_BUILD')):
        record = Path(root) / '.ravel-site/wms.json' if root else None
        if record is None or not record.is_file():
            continue
        row = json.loads(record.read_bytes())
        version = row.get('version') if type(row) is dict else None
        if (type(row) is not dict or type(row.get('schema_version')) is not int or row['schema_version'] != 1
                or not isinstance(version, str) or not version.strip()):
            raise ValueError('site-wms record requires schema_version 1 and a version: ' + str(record))
        return version
    return None


def _snakemake_declaration(project, manifest, found):
    version = _site_wms_version(project)
    if version is not None:
        return version, 'Declared by the local site-wms record; not probed during guidance installation.'
    if manifest is not None:
        from ravel.setup.manifest import view, read_json
        path = Path(manifest)
        # A tree's main file is read with its fragments; any other named file is read as given.
        document = (view(path.parents[2]) if path.parts[-3:] == ('native', 'setup', 'toolchain-manifest.json')
                    else read_json(path))
        for group in document.get('groups', []):
            version = group.get('version_contract', {}).get('snakemake')
            if version:
                return str(version), 'Required by the toolchain manifest; local availability is not inferred.'
            for check in group.get('checks', []):
                if check.get('id') in {'snakemake', 'site-snakemake'} and check.get('probe', {}).get('expect'):
                    return str(check['probe']['expect']), 'Required by the toolchain manifest; local availability is not inferred.'
    if 'snakemake' in found:
        return found['snakemake'].get('version', 'unknown (PATH observation only)'), 'Observed in the current environment.'
    return None


def _snakemake_skill(version, source):
    return _skill_text('software-snakemake',
        'Use when designing or running approved RAVEL stages through Snakemake: DAGs, profiles, dry-run inspection, status and RAVEL retries.',
        f'# Snakemake {version}\n\n{source}\n\n'
        'Resolve the separate environment at runtime with the `ravel-snakemake` shim; '
        'no interpreter or installation path belongs in this skill.\n\n'
        '- `ravel wms init`: initialize project policy and workflow with supplied audit records.\n'
        '- `ravel wms add`: register an approved run and its dependency edges.\n'
        '- Inspect `ravel-snakemake --dry-run` with the generated Snakefile and profile first.\n'
        '- `ravel wms launch`: execute the approved registered task.\n'
        '- `ravel wms retry`: record a bounded RAVEL retry; no scheduler retry grants admission.\n'
        '- `ravel wms status`: read task and receipt status.\n'
        '- Keep plan and approve check-ins; never approve through the workflow manager.\n'
        '- Software presence, DAG parsing, native execution and physics qualification require distinct evidence.\n')


def _write_local_runtime(project, approval, report, runtime_python=None):
    runtime_python = runtime_python or sys.executable
    local = {'schema_version': 1, 'python': runtime_python, 'guard_approval': approval}
    source = Path(__file__).resolve().parents[2]
    runtime = '# Local runtime settings; never commit this file.\n'
    runtime += 'if [ -z "${RAVEL_PYTHON:-}" ]; then RAVEL_PYTHON=' + shlex.quote(runtime_python) + '; fi\nexport RAVEL_PYTHON\n'
    if source.name == 'src' and (source / 'ravel').is_dir():
        local['pythonpath'] = str(source)
        runtime += 'export PYTHONPATH=' + shlex.quote(str(source)) + '${PYTHONPATH:+:$PYTHONPATH}\n'
    for rel, text in ((LOCAL, json.dumps(local, indent=2) + '\n'), (RUNTIME, runtime)):
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.read_text() != text:
            path.write_text(text)
            report['written'].append(rel)
    ignored = project / '.ravel/.gitignore'
    text = ignored.read_text() if ignored.is_file() else ''
    for pattern in ('/agent-surface.local.json', '/hook-runtime.sh', '/agent-audit/'):
        if pattern not in text.splitlines():
            text = text.rstrip('\n') + '\n' + pattern + '\n'
    if not ignored.is_file() or ignored.read_text() != text:
        ignored.write_text(text)
        report['written'].append('.ravel/.gitignore')


def built_software(manifest=None, *, packages=None, executables=None, all_groups=False, project=None):
    """{skill name: {file name: text}} from ``software_skills.py``, with the Snakemake declaration.

    A site-wms record or a toolchain-manifest declaration of Snakemake replaces an observation,
    in that order; nothing is probed for the declaration.
    """
    from . import software_skills as generator
    built = generator.build(manifest, project=project, packages=packages, executables=executables, all_groups=all_groups)
    snakemake = _snakemake_declaration(project, manifest, {})
    if snakemake is not None:
        built['software-snakemake'] = {'SKILL.md': _snakemake_skill(*snakemake)}
    return built


def software_skills(manifest=None, *, packages=None, executables=None, all_groups=False, project=None):
    """{skill name: SKILL.md text} for installed or declared tools; never for absent ones."""
    built = built_software(manifest, packages=packages, executables=executables, all_groups=all_groups, project=project)
    return {name: parts['SKILL.md'] for name, parts in built.items()}


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
        present = False
        for group in groups:
            for hook in group.get('hooks', []):
                if HOOK_MARK in hook.get('command', ''):
                    hook['command'] = command
                    present = True
        if not present:
            groups.append({'matcher': '', 'hooks': [{'type': 'command', 'command': command, 'timeout': 30}]})
    from .site_tools import merge_claude_settings
    return merge_claude_settings(settings, python_command=_python_command())


def _guard_command():
    from . import execution_guard
    # Exit 2 is the guard's own refusal (strict or discipline mode) and always blocks. Any other failure
    # means the guard could not run: fail closed only where the project's policy asks for strict mode, so a
    # guard that cannot start neither locks a project whose policy is off nor opens one that is strict.
    return (f'{_python_command()} -m {execution_guard.HOOK_MARK} --project "$CLAUDE_PROJECT_DIR"; rc=$?; '
            'if [ "$rc" -ne 0 ] && [ "$rc" -ne 2 ]; then '
            'if grep -qs \'"strict"\' "$CLAUDE_PROJECT_DIR/workflow/policy.json"; then rc=2; else rc=0; fi; fi; '
            'exit "$rc"')


# The hook command of the earlier separate workflow-manager guard; a reinstall replaces it.
_RETIRED_GUARD_MARK = 'ravel.workflow.agent_surface wms-guard'


def install(project, *, skills_from=None, manifest=None, include_software=True, all_groups=False,
            wms_guard=None, guard_approval=None):
    project = Path(project).absolute()
    if not project.is_dir():
        raise ValueError('project directory must exist')
    required = _wms_required(project)
    guard_enabled = required if wms_guard is None else wms_guard
    approval = _guard_approval(project, guard_approval) if required and not guard_enabled else None
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
            # Existing project instruction documents remain byte-identical.
            if rel in ('AGENTS.md', 'CLAUDE.md'):
                continue
            digest = _write_owned(project, rel, text.encode(), previous, report)
            if digest:
                files[rel] = digest
    if manifest is None and repository_root() is not None:
        candidate = repository_root() / 'native' / 'setup' / 'toolchain-manifest.json'
        manifest = candidate if candidate.is_file() else None
    from . import software_skills as generator
    software = built_software(manifest, all_groups=all_groups, project=project) if include_software else {}
    for name, parts in software.items():
        for base in generator.BASES:
            for filename, text in parts.items():
                rel = f'{base}/{name}/{filename}'
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
    groups = merged.setdefault('hooks', {}).setdefault('PreToolUse', [])
    for group in groups:
        group['hooks'] = [h for h in group.get('hooks', []) if _RETIRED_GUARD_MARK not in h.get('command', '')]
    if guard_enabled:
        if not any(GUARD_MARK in h.get('command', '') for g in groups for h in g.get('hooks', [])):
            groups.append({'matcher': 'Bash', 'hooks': [{'type': 'command', 'timeout': 30, 'command': _guard_command()}]})
    else:
        # Only our hook can be removed, and policy-required removal has an approval.
        for group in groups:
            group['hooks'] = [h for h in group.get('hooks', []) if GUARD_MARK not in h.get('command', '')]
    runtime_python = merged.get('env', {}).get('RAVEL_PYTHON')
    if isinstance(runtime_python, str) and Path(runtime_python).is_absolute():
        del merged['env']['RAVEL_PYTHON']
    else:
        runtime_python = None
    if runtime_python is None and (project / LOCAL).is_file():
        runtime_python = json.loads((project / LOCAL).read_bytes()).get('python')
    _write_local_runtime(project, approval, report, runtime_python)
    if merged != settings:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(merged, indent=2) + '\n')
        report['written'].append('.claude/settings.json')
    notify = ['/bin/sh', '-c', f'{_python_command()} -m ravel.workflow.agent_audit codex-notify --log \"$CLAUDE_PROJECT_DIR/{log_rel}\" "$1"', 'ravel-notify']
    snippet = '# Add to your Codex config.toml to log each completed Codex turn for this project.\nnotify = ' + json.dumps(notify) + '\n'
    digest = _write_owned(project, '.ravel/codex-notify.toml', snippet.encode(), previous, report)
    if digest:
        files['.ravel/codex-notify.toml'] = digest
    body = guidance(installed, sorted(software), log_rel, project=project, guard=bool(guard_enabled))
    digest = _write_owned(project, GUIDANCE, (body + '\n').encode(), previous, report)
    if digest:
        files[GUIDANCE] = digest
    instructions = {name: _sha((project / name).read_bytes()) if (project / name).is_file() else None
                    for name in ('AGENTS.md', 'CLAUDE.md')}
    record = {'schema_version': 1, 'kind': 'ravel-agent-surface-install', 'ravel_version': __version__,
              'role_registry_sha256': role_registry.registry_sha256(),
              'installed_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'runtime_file': RUNTIME, 'hook_command': command, 'audit_log': log_rel,
              'wms_guard': guard_enabled, 'guard_approval_sha256': approval['sha256'] if approval else None,
              'skills': installed, 'software_skills': sorted(software), 'files': dict(sorted(files.items())),
              'instruction_sha256': instructions}
    (project / MANIFEST).parent.mkdir(parents=True, exist_ok=True)
    (project / MANIFEST).write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    from . import execution_guard
    return {**report, 'manifest': str(project / MANIFEST), 'skills': installed, 'software_skills': sorted(software),
            'wms_guard': {'hook': True, 'policy_mode': execution_guard.mode(project)} if guard_enabled else None}


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
    for name, digest in record.get('instruction_sha256', {}).items():
        target = project / name
        current = _sha(target.read_bytes()) if target.is_file() else None
        if current != digest:
            errors.append(f'{name} project text changed since install; review and re-install')
    required = _wms_required(project)
    if required and not record.get('wms_guard'):
        try:
            local = json.loads((project / LOCAL).read_text())
            approval = _guard_approval(project, (local.get('guard_approval') or {}).get('path'))
            if approval['sha256'] != record.get('guard_approval_sha256'):
                errors.append('workflow-manager guard opt-out approval changed')
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    expected_guidance = guidance(record['skills'], record['software_skills'], record['audit_log'], project=project,
                                 guard=bool(record.get('wms_guard'))) + '\n'
    if not (project / GUIDANCE).is_file() or (project / GUIDANCE).read_text() != expected_guidance:
        errors.append('project guidance differs from current policy; re-install')
    settings_path = project / '.claude/settings.json'
    settings = json.loads(settings_path.read_text()) if settings_path.is_file() else {}
    for event in HOOK_EVENTS:
        commands = [h.get('command', '') for g in settings.get('hooks', {}).get(event, []) for h in g.get('hooks', [])]
        if not any(HOOK_MARK in c for c in commands):
            errors.append(f'prompt-log hook missing for {event}')
    if required or record.get('wms_guard'):
        commands = [h.get('command', '') for g in settings.get('hooks', {}).get('PreToolUse', []) for h in g.get('hooks', [])]
        if record.get('wms_guard') and not any(GUARD_MARK in c for c in commands):
            errors.append('workflow-manager guard hook missing')
    for event, action in (("PreToolUse", "check"), ("PostToolUse", "observe")):
        groups = settings.get('hooks', {}).get(event, [])
        if not any(g.get('matcher') == 'mcp__.*' and
                   any(f'ravel.workflow.site_tools {action}' in h.get('command', '')
                       or (('pretooluse-mcp.sh' if action == 'check' else 'posttooluse-observer.sh') in h.get('command', ''))
                       for h in g.get('hooks', [])) for g in groups):
            errors.append(f'site-tool hook missing for {event}')
    local_path = project / LOCAL
    if not local_path.is_file():
        errors.append('local hook runtime settings missing: re-install')
    else:
        local = json.loads(local_path.read_text())
        if not Path(local['python']).exists():
            errors.append('hook interpreter no longer exists; re-install')
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
    guard = i.add_mutually_exclusive_group()
    guard.add_argument('--wms-guard', dest='wms_guard', action='store_true',
                       help='install the execution-guard PreToolUse hook (on by default where the workflow policy requires the manager)')
    guard.add_argument('--no-wms-guard', dest='wms_guard', action='store_false')
    i.set_defaults(wms_guard=None)
    i.add_argument('--guard-approval', type=Path)
    g = commands.add_parser('wms-guard', help='shell discipline hook; grants no approval')
    g.add_argument('--project', type=Path, required=True)
    c = commands.add_parser('check', help='verify an installed agent surface')
    c.add_argument('--project', type=Path, required=True)
    p = commands.add_parser('profiles', help='resolve the installed verification-panel profiles')
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--host', choices=('claude', 'codex', 'gemini', 'antigravity', 'opencode', 'governed-node', 'hookless'), required=True)
    r = commands.add_parser('render', help='regenerate canonical role surfaces in a checkout')
    r.add_argument('--project', type=Path, required=True)
    s = commands.add_parser('skills', help='print or write software skills for installed tools')
    s.add_argument('--toolchain-manifest', type=Path)
    s.add_argument('--project', type=Path, help='project containing a local site-wms record')
    s.add_argument('--out', type=Path, help='skills directory to write into (new skill directories only)')
    args = parser.parse_args(argv)
    try:
        if args.command == 'wms-guard':
            payload = json.load(sys.stdin)
            if not isinstance(payload, dict) or not isinstance(payload.get('tool_input'), dict):
                raise ValueError('shell hook requires a tool_input object')
            command = payload.get('tool_input', {}).get('command', '')
            reason = guard_command(args.project, command)
            if reason:
                print(reason, file=sys.stderr)
                return 2
            return 0
        if args.command == 'install':
            result = install(args.project, skills_from=args.skills_from, manifest=args.toolchain_manifest,
                             all_groups=args.all_groups, wms_guard=args.wms_guard, guard_approval=args.guard_approval)
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
            skills = software_skills(args.toolchain_manifest, project=args.project)
            if args.out:
                for name, text in skills.items():
                    target = args.out / name / 'SKILL.md'
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open('x', encoding='utf-8') as stream:
                        stream.write(text)
            result = {'skills': sorted(skills)}
    except (OSError, ValueError, KeyError) as exc:
        if args.command == 'wms-guard':
            print(f'workflow-manager guard refuses malformed input or policy: {exc}', file=sys.stderr)
            return 2
        parser.exit(1, f'agent surface: {exc}\n')
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
