"""Adopt an external Snakefile as one governed stage.

`adopt` pins the Snakefile and every file it includes by reading them as text, and
plans an inspection study. Parsing a Snakefile executes its Python, so Snakemake
first reads the file inside that approved, supervised inspection: `--list-rules`,
`--dag` and `--summary` in dry-run mode, and a dry run that prints every shell
command. `plan_run` turns a passed inspection into the run study, whose CHECK-IN 1
shows the rule roster and every shell command. Once approved, the workflow runs as
one supervised stage under the machine lease, and its outputs are copied into the
stage output and pinned. A pinned file that changed is refused by name.

Both studies are ordinary science studies of the `external-workflow` mode: planning,
approval, the method decision, the lease and the receipts are the existing ones.
This module approves nothing and starts Snakemake only inside the science worker.
"""
import argparse
import ast
from contextvars import ContextVar
import fnmatch
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import tokenize

from . import wms_runtime
from .state_io import atomic_json, read_json

MODE = 'external-workflow'
RECORD = 'adoption.json'
INSPECTION = 'inspection.json'
RECEIPT = 'receipt.json'
STUDY_KEYS = ('source', 'assumptions', 'max_seconds', 'approval_mode', 'review_policy')
ACTIONS = ('shell', 'run', 'script', 'notebook', 'wrapper', 'cwl', 'template_engine')
# Files a directive names: resolved against the working directory or the file that names them.
REFERENCES = {'configfile': 'workdir', 'script': 'file', 'notebook': 'file', 'conda': 'file'}
PROFILE_VARIABLE = 'SNAKEMAKE_PROFILE'
_CUSTODY = ContextVar('ravel_adopted_workflow_custody', default=None)
_WATCHED = ('include', 'snakefile', 'meta_wrapper', *REFERENCES, *ACTIONS)
SCOPE = 'An external Snakemake workflow run as written; RAVEL pins, inspects and supervises it'
LIMITATIONS = [
    'The workflow is third-party code. Its rules, scripts and results carry no RAVEL validation.',
    'Pins cover the Snakefile, its literal includes and module Snakefiles, workflow members named with '
    '--member, literal configfile, script, notebook and conda files, and files named with --pin. Python '
    'modules the Snakefile imports and programs its commands call are pinned only when named with --pin.',
    'Snakemake reads the pinned files in place. They are checked before and after each call, and each '
    'include is checked against the adoption record before Snakemake parses it.',
]
_REMOTE = re.compile(r'[A-Za-z][A-Za-z0-9+.-]*://')
_RULE_NAME = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)(?: \((.*)\))?')
_JOB_HEADER = re.compile(r'(?:local)?(?:rule|checkpoint) (\S+):')
_TIMESTAMP = re.compile(r'\[\w{3} \w{3} [ \d]\d \d\d:\d\d:\d\d \d{4}\]')
_SKIPPED = (tokenize.ENCODING, tokenize.NL, tokenize.COMMENT, tokenize.DEDENT, tokenize.ENDMARKER)


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _pin(path):
    raw = Path(path).read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def _write_new(path, value):
    """Write a JSON record that must not exist yet."""
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    return _pin(path)


def _regular(value, label):
    path = Path(value).expanduser().absolute().resolve()
    _require(path.is_file(), f'{label} {path} is not a regular file')
    return path


def _folder(value):
    path = Path(value).expanduser().absolute().resolve()
    _require(path.is_dir(), f'root {path} is not a folder')
    return path


# ----------------------------------------------------------------- static closure (no parse)
def _statements(path):
    """(indented, tokens) for each logical line, read as text. Nothing is executed."""
    try:
        tokens = list(tokenize.tokenize(io.BytesIO(path.read_bytes()).readline))
    except (tokenize.TokenError, SyntaxError, ValueError) as exc:
        raise ValueError(f'{path} cannot be read as Snakefile text ({exc}); nothing was parsed') from exc
    line, indented = [], False
    for token in tokens:
        if token.type == tokenize.INDENT:
            indented = True
        elif token.type == tokenize.NEWLINE:
            if line:
                yield indented, line
            line, indented = [], False
        elif token.type not in _SKIPPED:
            line.append(token)
    if line:
        yield indented, line


def _literal(tokens):
    """The string a directive names when it is written as a plain string literal, else None."""
    if not tokens or any(token.type != tokenize.STRING for token in tokens):
        return None
    try:
        value = ast.literal_eval(' '.join(token.string for token in tokens))
    except (ValueError, SyntaxError):
        return None
    return value if type(value) is str and value else None


def _is(token, kind, text=None):
    return token.type == kind and (text is None or token.string == text)


def _inside(path, roots):
    return any(path == root or root in path.parents for root in roots)


def _api_includes(tokens):
    """`workflow.include(...)` calls in one statement: (line, the tokens of the first argument)."""
    found = []
    for index in range(len(tokens) - 3):
        if (_is(tokens[index], tokenize.NAME, 'workflow') and _is(tokens[index + 1], tokenize.OP, '.')
                and _is(tokens[index + 2], tokenize.NAME, 'include') and _is(tokens[index + 3], tokenize.OP, '(')):
            argument, depth = [], 0
            for token in tokens[index + 4:]:
                if token.type == tokenize.OP and token.string in '([{':
                    depth += 1
                elif token.type == tokenize.OP and token.string in ')]}':
                    if depth == 0:
                        break
                    depth -= 1
                elif depth == 0 and _is(token, tokenize.OP, ','):
                    break
                argument.append(token)
            found.append((tokens[index].start[0], argument))
    return found


def _include(includes, where, name, target, line, role):
    _require(target is not None, f'{where}: `{name}` is not a literal path, so the file it reads cannot be '
             'pinned; nothing was parsed. Write the path as a plain string')
    _require(not _REMOTE.match(target), f'{where}: `{name}` names remote code ({target}); nothing was '
             'parsed. Adopt a local copy')
    includes.append({'path': target, 'line': line, 'role': role})


def _scan_file(path, workdir):
    """Includes, rules and file references that one Snakefile declares."""
    includes, rules, references, unpinned = [], [], [], []
    rule = module = waiting = None
    for indented, tokens in _statements(path):
        first, line, column = tokens[0], tokens[0].start[0], tokens[0].start[1]
        for call, argument in _api_includes(tokens):
            _include(includes, f'{path}:{call}', 'workflow.include()', _literal(argument), call, 'include')
        if rule is not None and column > rule['column']:
            rule['end'] = tokens[-1].end[0]
        if waiting is not None and indented:
            name, value, line = waiting[0], tokens, waiting[1]
            waiting = None
        else:
            waiting = None
            if rule is not None and column <= rule['column']:
                rule = None
            if module is not None and column <= module:
                module = None
            if not _is(first, tokenize.NAME):
                continue
            if first.string in ('rule', 'checkpoint') and len(tokens) >= 2 and (
                    _is(tokens[1], tokenize.OP, ':') or len(tokens) >= 3 and _is(tokens[1], tokenize.NAME)
                    and _is(tokens[2], tokenize.OP, ':')):
                rule = {'name': tokens[1].string if _is(tokens[1], tokenize.NAME) else None, 'file': str(path),
                        'line': line, 'column': column, 'end': tokens[-1].end[0], 'actions': []}
                rules.append(rule)
                continue
            if first.string == 'use' and len(tokens) >= 3 and _is(tokens[1], tokenize.NAME, 'rule'):
                names = [token.string for token in tokens]
                # `as other_*` names a pattern of rule names: the tokens up to `with` or the colon.
                renamed = names[names.index('as') + 1:] if 'as' in names[:-1] else [names[2]]
                renamed = renamed[:next((i for i, n in enumerate(renamed) if n in ('with', ':')), len(renamed))]
                rule = {'name': ''.join(renamed), 'file': str(path), 'line': line, 'column': column,
                        'end': tokens[-1].end[0], 'actions': ['use rule']}
                rules.append(rule)
                continue
            if first.string == 'module' and len(tokens) >= 3 and _is(tokens[2], tokenize.OP, ':'):
                module = column
                continue
            if len(tokens) < 2 or not _is(tokens[1], tokenize.OP, ':'):
                continue
            name, value = first.string, tokens[2:]
            if not value:
                # The value is the indented block below. Python's own `else:` or `try:` is not a directive.
                if name in _WATCHED:
                    waiting = (name, line)
                continue
        where = f'{path}:{line}'
        if name == 'include' or module is not None and name == 'snakefile':
            _include(includes, where, f'{name}:', _literal(value), line, 'include' if name == 'include' else 'module')
        elif module is not None and name == 'meta_wrapper':
            raise ValueError(f'{where}: `meta_wrapper:` names remote code; nothing was parsed. Adopt a local copy')
        elif name in REFERENCES:
            target = _literal(value)
            row = {'directive': name, 'file': str(path), 'line': line}
            base = workdir if REFERENCES[name] == 'workdir' else path.parent
            resolved = None if target is None else (Path(target) if os.path.isabs(target) else base / target).resolve()
            if target is None:
                unpinned.append({**row, 'reason': 'not a literal path'})
            elif '{' in target or _REMOTE.match(target):
                unpinned.append({**row, 'value': target, 'reason': 'a pattern or remote name'})
            elif not resolved.is_file():
                unpinned.append({**row, 'value': target, 'reason': 'no such file at adoption'})
            else:
                references.append({'path': resolved, 'line': line, 'role': name})
        if rule is not None and name in ACTIONS:
            rule['actions'].append(name)
            if name == 'wrapper':
                unpinned.append({'directive': name, 'file': str(path), 'line': line, 'reason': 'remote wrapper code',
                                 **({'value': _literal(value)} if _literal(value) else {})})
    text = path.read_text(errors='replace').splitlines(keepends=True)
    for row in rules:
        # The rule's own text, exactly as written: what CHECK-IN 1 shows of every rule, scheduled or not.
        row['source'] = ''.join(text[row['line'] - 1:row.pop('end')])
        del row['column']
    return includes, rules, references, unpinned


def default_roots(snakefile, workdir):
    """The folders adopted files may lie in: the Snakefile's folder and the working directory."""
    return [str(Path(snakefile).parent), str(workdir)]


def scan(snakefile, workdir, roots=(), members=()):
    """Static closure of a Snakefile: every file it includes, its rules and the files they name.

    The files are tokenized as text. An include that is not a literal local path is
    refused, because the file it would read could not be pinned. Every include and
    named file resolves inside the Snakefile's folder, the working directory or one of
    `roots`. `includes` keeps each include as written, with the file it resolved to.
    `members` are workflow files that the Snakefile's Python loads through an include
    it computes: each is scanned like an included file, so its rules are read too.
    """
    allowed = [Path(root).resolve() for root in (*default_roots(snakefile, workdir), *roots)]
    files, rules, unpinned, edges, pinned, scanned = [], [], [], [], set(), set()
    for member in members:
        _require(_inside(Path(member), allowed), f'workflow member {member} is outside the allowed roots '
                 f"{', '.join(map(str, allowed))}; nothing was parsed. Name its folder with --root")
    pending = [(Path(snakefile), 'snakefile', None, None), *((Path(member), 'member', None, None) for member in members)]
    while pending:
        path, role, parent, line = pending.pop(0)
        if path in scanned:
            continue
        scanned.add(path)
        if path not in pinned:
            pinned.add(path)
            files.append({'role': role, **_pin(path), 'included_by': parent, 'line': line})
        includes, declared, references, loose = _scan_file(path, Path(workdir))
        rules += declared
        unpinned += loose
        for row in includes:
            where = f"{path}:{row['line']}"
            target = (Path(row['path']) if os.path.isabs(row['path']) else path.parent / row['path']).resolve()
            _require(target.is_file(), f'{where}: included file {target} is not a regular file; nothing was parsed')
            _require(_inside(target, allowed), f'{where}: included file {target} is outside the allowed roots '
                     f"{', '.join(map(str, allowed))}; nothing was parsed. Name its folder with --root")
            edges.append({'file': str(path), 'line': row['line'], 'path': row['path'], 'role': row['role'],
                          'resolved': str(target)})
            pending.append((target, row['role'], str(path), row['line']))
        for row in references:
            _require(_inside(row['path'], allowed), f"{path}:{row['line']}: `{row['role']}:` file {row['path']} is "
                     f"outside the allowed roots {', '.join(map(str, allowed))}; nothing was parsed. Name its folder "
                     'with --root')
            if row['path'] not in pinned:
                pinned.add(row['path'])
                files.append({'role': row['role'], **_pin(row['path']), 'included_by': str(path), 'line': row['line']})
    return {'files': files, 'includes': edges, 'members': [str(member) for member in members], 'rules': rules,
            'unpinned_references': unpinned}


def _outside(work, names):
    """Names among `names` that do not resolve inside the working directory, links followed."""
    return [name for name in names
            if not name or os.path.isabs(name) or not _inside((work / name).resolve(), [work]) or (work / name).resolve() == work]


def changed_files(record):
    """Pinned files that are missing or differ, and includes that resolve elsewhere, with the reason."""
    rows = []
    for row in record['files']:
        path = Path(row['path'])
        if not path.is_file():
            rows.append((row['path'], 'is missing'))
        elif _pin(path)['sha256'] != row['sha256']:
            rows.append((row['path'], 'changed'))
    if rows:
        return rows
    # Same bytes, same closure: each include, as written, still resolves to the file adopted for it.
    try:
        now = scan(record['snakefile']['path'], record['workdir'], record['roots'], record['members'])
    except ValueError as exc:
        return [(record['snakefile']['path'], f'no longer scans as adopted: {exc}')]
    adopted = {(row['file'], row['line'], row['path']): row['resolved'] for row in record['includes']}
    for row in now['includes']:
        key = (row['file'], row['line'], row['path'])
        if key not in adopted:
            rows.append((f"{row['file']}:{row['line']} include {row['path']}", 'is new'))
        elif adopted[key] != row['resolved']:
            rows.append((f"{row['file']}:{row['line']} include {row['path']}",
                         f"now resolves to {row['resolved']}, adopted as {adopted[key]}"))
    declared = {row['path'] for row in record['files'] if row['role'] == 'declared'}
    rows += [(path, 'is newly named by the workflow') for path in
             sorted({row['path'] for row in now['files']} - {row['path'] for row in record['files']} - declared)]
    work = Path(record['workdir'])
    if work.resolve() != work or not work.is_dir():
        rows.append((record['workdir'], 'no longer is the adopted working directory'))
    rows += [(name, 'is outside the working directory') for name in _outside(work, record['outputs'] or [])]
    return rows


def check_pins(record):
    """Refuse, naming each file, when a pinned file or an include changed since adoption."""
    rows = changed_files(record)
    _require(not rows, 'adopted workflow file ' + '; '.join(f'{path} {why}' for path, why in rows)
             + ' since adoption. Restore the pinned content, or adopt the workflow again so that the new files are '
             'inspected and approved')


# ----------------------------------------------------------------- commands
def _base(record):
    # `none` switches off the default and workflow profiles: a profile is an unpinned source of options.
    return [*record['snakemake'], '--snakefile', record['snakefile']['path'], '--directory', record['workdir'],
            '--profile', 'none', '--workflow-profile', 'none']


def _targets(record):
    return ['--', *record['targets']] if record['targets'] else []


def inspection_commands(record):
    """The four Snakemake calls of the inspection; none of them runs a job."""
    base, targets = _base(record), _targets(record)
    return {'rules': [*base, '--dry-run', '--list-rules'],
            'dag': [*base, '--dry-run', '--dag', 'dot', *targets],
            'summary': [*base, '--dry-run', '--summary', *targets],
            'jobs': [*base, '--dry-run', '--printshellcmds', '--cores', str(record['cores']), *targets]}


def run_command(record):
    return [*_base(record), '--cores', str(record['cores']), *_targets(record)]


def _call(record, argv, folder, name, outputs=()):
    """Run one Snakemake call; returns its exit code, its standard output and the pins of both streams.

    The pins, the include closure and the outputs are checked here, as the last step
    before the process starts.
    """
    from . import wms_launch
    require_launch_custody(record)
    paths = {stream: folder / f'{name}.{stream}.txt' for stream in ('stdout', 'stderr')}
    check_pins(record)
    outside = _outside(Path(record['workdir']), outputs)
    _require(not outside, 'output ' + ', '.join(outside) + ' is outside the working directory; Snakemake was not started')
    with paths['stdout'].open('xb') as out, paths['stderr'].open('xb') as err:
        code = wms_launch.launch_adopted(record, argv, folder, name, out, err, outputs)
    text = paths['stdout'].read_text(errors='replace')
    pins = {}
    for stream, path in paths.items():
        # The stage supervisor refuses an empty file among stage outputs, so a silent stream leaves no file.
        if path.stat().st_size:
            pins[stream] = _pin(path)
        else:
            path.unlink()
            pins[stream] = None
    return code, text, pins


def require_launch_custody(record):
    """Recheck the approved worker, method admission and WMS dispatch at each call."""
    from . import method_selection, wms_policy
    context = _CUSTODY.get()
    _require(context is not None, 'an adopted workflow launches only inside its approved supervised science worker')
    task, base, destination, pinned = context
    rd = _approved(task, destination)
    method_selection.require_launch(rd)
    wms_policy.require_custody(rd)
    path, current = _record(task, base)
    _require(_pin(path) == pinned and current == record, 'adoption record changed before supervised launch')


def _first_line_interpreter(path):
    """The interpreter command that a script's first line names; an `env` line is resolved on the search path now."""
    with path.open('rb') as stream:
        line = stream.readline(4096).decode('utf-8', 'replace').strip()
    words = shlex.split(line[2:]) if line.startswith('#!') else []
    if words and Path(words[0]).name == 'env':
        words = [word for word in words[1:] if word != '-S']
        found = shutil.which(words[0]) if words else None
        words = [os.path.abspath(found), *words[1:]] if found else []
    return words


def _runs(python):
    return bool(python) and Path(python[0]).is_absolute() and Path(python[0]).is_file() and os.access(python[0], os.X_OK)


def bind_interpreter(argv, explicit=None):
    """The Python interpreter and the console entry that run the adopted manager.

    `adopt` resolves both once and writes them into the adoption record, so the
    inspection and the run start the interpreter that was found at adoption. The
    interpreter is `explicit`, or the one the entry's first line names, by absolute
    path or through `env`; the shim of an installed site prefix stands for the
    manager entry that the prefix's own record names.
    """
    _require(len(argv) == 1, 'adopted manager requires a Python console entry')
    manager = Path(argv[0])
    if explicit is not None:
        found = shutil.which(str(explicit))
        _require(found, f'interpreter {explicit} is not an executable file')
        return {'python': [os.path.abspath(found)], 'entry': str(manager)}
    refusal = (f'adopted manager {manager} must name its Python interpreter by absolute path or through `env` in its '
               'first line, be the shim of an installed site prefix, or be adopted with --interpreter')
    python = _first_line_interpreter(manager)
    if not python or 'python' not in Path(python[0]).name:
        # Otherwise only an installed site shim is accepted. The record of its own prefix, validated
        # against that prefix, names the isolated manager that the shim starts.
        from .site_contract import read_wms_record
        try:
            installed = read_wms_record(manager.absolute().parent.parent)
        except ValueError:
            installed = None
        _require(installed is not None and manager.absolute() == Path(installed['shim']), refusal)
        manager = Path(installed['snakemake'])
        python = _first_line_interpreter(manager)
    _require(_runs(python) and 'python' in Path(python[0]).name, refusal)
    return {'python': python, 'entry': str(manager)}


def interpreter_command(record, argv, folder, name):
    """Run the pinned manager's Python entry under the before-load include wrapper."""
    _require(argv[:len(record['snakemake'])] == record['snakemake'], 'adopted manager command differs')
    # An adoption record binds the interpreter; a record without the binding resolves it by the same rule now.
    bound = record.get('interpreter') or bind_interpreter(record['snakemake'])
    python, manager = bound['python'], Path(bound['entry'])
    _require(_runs(python), f"adopted interpreter {' '.join(python)} is no longer an executable file; adopt the "
             'workflow again')
    snapshot = folder / f'{name}.include-record.json'
    pin = _write_new(snapshot, record)
    snapshot.chmod(0o444)
    # The same check for every interpreter the manager starts itself: a copy of the bootstrap,
    # alone in its folder, which those interpreters run first.
    bootstrap = Path(__file__).with_name('wms_include.py')
    hook = folder / f'{name}.include-hook'
    hook.mkdir()
    shutil.copyfile(bootstrap, hook / 'sitecustomize.py')
    (hook / 'sitecustomize.py').chmod(0o444)
    return [*python, '-B', str(bootstrap),
            '--record', str(snapshot), '--record-sha256', pin['sha256'], '--hook', str(hook),
            '--manager', str(manager), '--', *argv[1:]]


def export_binding(rundir, plan, manifest):
    """Bind an adopted study and its generated export when the shared launcher adds it."""
    from . import science
    spec = science.execution_spec(rundir)
    if spec['mode'] != MODE:
        return None
    path, record = _record(spec['task'], plan.get('base_dir', rundir))
    check_pins(record)
    return {'manifest': manifest, 'adoption': _pin(path)}


def check_launch_binding(entry):
    """Refuse either changed member of an indexed emitted/adopted record pair."""
    from . import science, site_workflow
    spec = science.execution_spec(entry['rundir'])
    binding = entry.get('workflow_binding')
    if spec['mode'] != MODE and binding is None:
        return
    _require(type(binding) is dict and binding.get('manifest') == entry['export'],
             'adoption/export binding is missing or changed; add a fresh approved task')
    for name in ('manifest', 'adoption'):
        pin = binding[name]
        _require(Path(pin['path']).is_file() and _pin(pin['path']) == pin,
                 f"{name} record {pin['path']} changed from its indexed digest")
    site_workflow.verify(binding['manifest']['path'], binding['manifest']['sha256'])
    record = read_json(binding['adoption']['path'])
    check_pins(record)


# ----------------------------------------------------------------- reading Snakemake's own output
def parse_rules(text, declared=()):
    """Rule names from `--list-rules`, lines the Snakefile printed, and listed names no adopted file declares.

    The Snakefile writes to the same stream, so a listed name counts as a rule only when
    an adopted file declares it, by name or by a `use rule ... as` pattern.
    """
    actions = {}
    for row in declared:
        if row['name']:
            actions.setdefault(row['name'], []).extend(row['actions'])
    rules, other, undeclared = [], [], []
    for line in text.splitlines():
        match = _RULE_NAME.fullmatch(line)
        if match is None:
            if line.strip():
                other.append(line)
            continue
        name = match.group(1)
        patterns = [pattern for pattern in actions if pattern == name or '*' in pattern and fnmatch.fnmatchcase(name, pattern)]
        if not patterns:
            undeclared.append(name)
            continue
        rules.append({'name': name, 'docstring': match.group(2),
                      'declared_actions': sorted({action for pattern in patterns for action in actions[pattern]})})
    return rules, other, undeclared


def parse_summary(text):
    """Rows of `--summary`: one per file the workflow creates for the targets."""
    lines = text.splitlines()
    header = next((i for i, line in enumerate(lines) if line.startswith('output_file\t')), None)
    _require(header is not None, 'the Snakemake summary has no header row')
    names = [name.replace('-', '_').replace('(s)', 's') for name in lines[header].split('\t')]
    rows = []
    for line in lines[header + 1:]:
        cells = line.split('\t')
        if len(cells) == len(names):
            rows.append(dict(zip(names, cells)))
    return rows


def parse_dag(text):
    start = text.find('digraph ')
    _require(start >= 0, 'the Snakemake DAG output holds no graph')
    return text[start:].rstrip() + '\n'


def parse_jobs(text):
    """Jobs of a dry run with `--printshellcmds`, and the job total Snakemake states."""
    lines, jobs, index = text.splitlines(), [], 0
    while index < len(lines):
        match = _JOB_HEADER.fullmatch(lines[index])
        index += 1
        if match is None:
            continue
        job = {'rule': match.group(1), 'jobid': None, 'input': [], 'output': [], 'shell': None}
        while index < len(lines) and lines[index].startswith('    '):
            key, _, value = lines[index].strip().partition(': ')
            if key == 'jobid':
                job['jobid'] = int(value)
            elif key in ('input', 'output'):
                job[key] = [item.strip() for item in value.split(', ') if item.strip()]
            index += 1
        if index < len(lines) and lines[index].startswith('Shell command:'):
            first = lines[index][len('Shell command:'):]
            body = [first[1:] if first.startswith(' ') else first]
            index += 1
            while index < len(lines) and not (_TIMESTAMP.fullmatch(lines[index]) or lines[index].startswith('Job stats:')):
                body.append(lines[index])
                index += 1
            if len(body) > 1 and body[-1] == '':
                body.pop()  # the blank line that separates two jobs
            # The command exactly as Snakemake printed it: indentation and blank lines are part of it.
            shell = '\n'.join(body)
            job['shell'] = None if shell == 'None' else shell
        jobs.append(job)
    totals = re.findall(r'^total\s+(\d+)\s*$', text, flags=re.MULTILINE)
    return jobs, int(totals[0]) if totals else 0


def roster(rules, jobs, undeclared=()):
    """What CHECK-IN 1 shows: every rule, every job of the targets and every shell command."""
    by_rule = {row['name']: row for row in rules}
    rows = sorted(jobs, key=lambda job: (job['jobid'] is None, job['jobid']))
    return {'rules': rules, 'listed_without_declaration': list(undeclared),
            'jobs': [{**job, 'declared_actions': by_rule.get(job['rule'], {}).get('declared_actions', [])} for job in rows],
            'shell_commands': sorted({job['shell'] for job in rows if job['shell'] is not None}),
            'jobs_without_shell_command': sorted({job['rule'] for job in rows if job['shell'] is None})}


# ----------------------------------------------------------------- the science adapter
def _record(task, base):
    path = Path(task['adoption'])
    path = path if path.is_absolute() else Path(base) / path
    record = read_json(path)
    _require(type(record) is dict and record.get('schema_version') == 1 and record.get('kind') == 'workflow-adoption',
             f'{path} is not a workflow adoption record')
    return path, record


def _inspection(task, base):
    path = Path(task['inspection'])
    path = path if path.is_absolute() else Path(base) / path
    return path, read_json(path)


def validate(task):
    _require(type(task) is dict and task.get('schema_version') == 1 and task.get('operation') in ('inspect', 'run'),
             'an external-workflow task names schema_version 1 and the operation inspect or run')
    names = {'schema_version', 'operation', 'adoption', 'files', 'unpinned_references', 'rules'} | (
        {'commands'} if task['operation'] == 'inspect' else {'command', 'inspection', 'roster'})
    _require(set(task) == names, 'an external-workflow task requires exactly ' + ', '.join(sorted(names)))
    for name in ('adoption', *(('inspection',) if task['operation'] == 'run' else ())):
        _require(type(task[name]) is str and task[name].strip(), f'{name} must be a path')


def _shown_files(record):
    return [{'role': row['role'], 'path': row['path'], 'sha256': row['sha256']} for row in record['files']]


def inputs(task, base):
    """Every pinned file, the adoption record and, for a run, the inspection it was approved on."""
    path, record = _record(task, base)
    check_pins(record)
    _require(task['files'] == _shown_files(record), 'the task shows different pinned files from the adoption record')
    _require(task['unpinned_references'] == record['unpinned_references'],
             'the task shows different unpinned references from the adoption record')
    _require(task['rules'] == record['rules'], 'the task shows different rules from the adoption record')
    files = [path, *(Path(row['path']) for row in record['files'])]
    if task['operation'] == 'inspect':
        _require(task['commands'] == inspection_commands(record), 'the task shows different inspection commands '
                 'from the adoption record')
        return files
    inspection_path, inspection = _inspection(task, base)
    _require(inspection.get('status') == 'passed', f'inspection {inspection_path} did not pass')
    _require(inspection['adoption'] == _pin(path), 'the inspection was made for a different adoption record')
    _require(task['roster'] == inspection['roster'], 'the task roster differs from the inspection')
    _require(task['command'] == run_command(record), 'the task shows a different run command from the adoption record')
    return [*files, inspection_path]


def _version(record):
    # Read through the interpreter bound at adoption, so that the version is the one of the manager that runs.
    bound = record.get('interpreter')
    return wms_runtime.snakemake_version([*bound['python'], bound['entry']] if bound else record['snakemake'])


def _inspect(path, record, folder):
    require_launch_custody(record)
    version = _version(record)
    commands, texts = [], {}
    for name, argv in inspection_commands(record).items():
        code, texts[name], streams = _call(record, argv, folder, name, record['outputs'] or ())
        commands.append({'name': name, 'argv': argv, 'exit_code': code, **streams})
    problems = [f"the `{row['name']}` call exited {row['exit_code']}; its output is in {folder}" for row in commands if row['exit_code'] != 0]
    problems += [f'{name} {why} during the inspection' for name, why in changed_files(record)]
    document = {'schema_version': 1, 'kind': 'workflow-inspection', 'adoption': _pin(path), 'pins': record['files'],
                'snakemake': {'argv': record['snakemake'], 'version': version}, 'commands': commands,
                'jobs_run': 0, 'execution_authorized': False}
    if not problems:
        rules, printed, undeclared = parse_rules(texts['rules'], record['rules'])
        jobs, total = parse_jobs(texts['jobs'])
        if total != len(jobs):
            problems.append(f'the dry run states {total} jobs and {len(jobs)} were read')
        (folder / 'dag.dot').write_text(parse_dag(texts['dag']))
        document.update(roster=roster(rules, jobs, undeclared), summary=parse_summary(texts['summary']), dag=_pin(folder / 'dag.dot'),
                        lines_printed_by_the_snakefile=printed, unpinned_references=record['unpinned_references'])
    document.update(status='failed' if problems else 'passed', problems=problems)
    _write_new(folder / INSPECTION, document)
    return document


def _deliver(record, summary, folder):
    """Copy the workflow's outputs into the stage output and pin the copies."""
    work = Path(record['workdir'])
    required = record['outputs'] is not None
    names = record['outputs'] if required else sorted({row['output_file'] for row in summary})
    bound, absent = [], []
    for name in names:
        source = (work / name).resolve()
        if not name or os.path.isabs(name) or work not in source.parents:
            absent.append({'path': name, 'reason': 'outside the working directory'})
        elif source.is_file() or source.is_dir():
            members = [source] if source.is_file() else sorted(p for p in source.rglob('*') if p.is_file())
            # A member of an output folder is read only when it is itself inside that folder, links followed.
            leaving = [p for p in members if p.is_symlink() and not _inside(p.resolve(), [source])]
            absent += [{'path': (Path(name) / p.relative_to(source)).as_posix(), 'reason': 'outside the working directory'}
                       for p in leaving]
            for member in (p for p in members if p not in leaving):
                pin, copy = _pin(member), None
                if pin['size']:  # an empty file is bound by its pin alone: the supervisor refuses empty stage outputs
                    target = folder / 'delivered' / member.relative_to(work)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(member, target)
                    copy = _pin(target)
                bound.append({'output': name, 'source': pin, 'delivered': copy})
        else:
            absent.append({'path': name, 'reason': 'not present after the run'})
    return bound, absent, required


def _undisclosed(inspection, jobs):
    """Jobs of the dry run before launch whose rule and command the approved roster does not show."""
    shown = {(job['rule'], job['shell']) for job in inspection['roster']['jobs']}
    return [job for job in jobs if (job['rule'], job['shell']) not in shown]


def _run(path, record, inspection, folder):
    require_launch_custody(record)
    # The version is read first: every Snakemake call checks the pins as its last step before it starts.
    version = _version(record)
    _require(version == inspection['snakemake']['version'], f"Snakemake is now version {version}; the inspection "
             f"was made with {inspection['snakemake']['version']}. Adopt the workflow again")
    # Every file the workflow writes stays inside the working directory. The outputs that the adoption
    # names say what is delivered; they do not narrow this check.
    outputs = sorted({*(record['outputs'] or ()), *(row['output_file'] for row in inspection['summary'])})
    # The same dry run as the inspection, now: a job or command that the approved roster does not show refuses the launch.
    code, text, preflight = _call(record, inspection_commands(record)['jobs'], folder, 'preflight', outputs)
    _require(code == 0, f'the dry run before launch exited {code}; its output is in {folder}. Snakemake was not started')
    jobs = parse_jobs(text)[0]
    # These jobs are the ones about to run: an output that only this dry run shows is checked too.
    outputs = sorted({*outputs, *(name for job in jobs for name in job['output'])})
    extra = _undisclosed(inspection, jobs)
    _require(not extra, 'the dry run before launch schedules jobs that the approved roster does not show: '
             + '; '.join(f"{job['rule']} ({job['shell']})" for job in extra)
             + '. Snakemake was not started; adopt the workflow again so that the new jobs are inspected and approved')
    argv = run_command(record)
    start = _utc()
    code, _, streams = _call(record, argv, folder, 'snakemake', outputs)
    end = _utc()
    changed = changed_files(record)
    bound, absent, required = _deliver(record, inspection['summary'], folder)
    problems = ([f'Snakemake exited {code}'] if code != 0 else []) + [f'{name} {why} during the run' for name, why in changed]
    if required:
        problems += [f"declared output {row['path']} is {row['reason']}" for row in absent]
    mismatched = [row['output'] for row in bound if row['delivered'] and row['source']['sha256'] != row['delivered']['sha256']]
    problems += [f'output {name} changed while it was copied' for name in mismatched]
    receipt = {'schema_version': 1, 'kind': 'workflow-run-receipt', 'adoption': _pin(path), 'pins': record['files'],
               'pins_unchanged_after_run': not changed, 'inspection': inspection['adoption'],
               'snakemake': {'argv': record['snakemake'], 'version': version}, 'argv': argv, 'cores': record['cores'],
               'targets': record['targets'], 'workdir': record['workdir'], 'start_utc': start, 'end_utc': end,
               'exit_code': code, 'outputs': bound, 'absent_outputs': absent, 'outputs_declared_by': 'adoption' if required else 'workflow',
               'log': streams, 'preflight_log': preflight,
               'status': 'failed' if problems else 'passed', 'problems': problems,
               'records': 'delivery only', 'scientific_acceptance_inferred': False}
    _write_new(folder / RECEIPT, receipt)
    return receipt


def _approved(task, destination):
    """The study whose approved supervised worker this process is, for exactly this task and output."""
    from . import science
    out = Path(destination).absolute()
    for rd in (out, *out.parents):
        if (rd / science.PLAN).is_file():
            try:
                selected = science.verify_worker(rd)
                spec = science.execution_spec(rd)
            except (OSError, KeyError, ValueError) as exc:
                raise ValueError(f'an external workflow is inspected or run only by the approved supervised science '
                                 f'worker of {rd} ({exc}); nothing was parsed or run') from exc
            _require(spec['mode'] == MODE and spec['task'] == task
                     and out.resolve() == (rd / selected['output_directory']).resolve(),
                     'the external-workflow task or output differs from the approved supervised worker')
            return rd
    raise ValueError('an external workflow is inspected or run only by the approved supervised science worker; '
                     'nothing was parsed or run')


def run(task, base, destination):
    """Science-worker entry: the approved inspection or the approved run, never both."""
    validate(task)
    _approved(task, destination)
    path, record = _record(task, base)
    inputs(task, base)
    folder = Path(destination) / MODE
    folder.mkdir(parents=True, exist_ok=False)
    token = _CUSTODY.set((task, base, destination, _pin(path)))
    try:
        if task['operation'] == 'inspect':
            document = _inspect(path, record, folder)
            delivered = {'inspection': _pin(folder / INSPECTION), 'rules': len(document.get('roster', {}).get('rules', [])),
                         'jobs': len(document.get('roster', {}).get('jobs', []))}
        else:
            document = _run(path, record, _inspection(task, base)[1], folder)
            delivered = {'receipt': _pin(folder / RECEIPT), 'exit_code': document['exit_code'],
                         'outputs': len(document['outputs'])}
    finally:
        _CUSTODY.reset(token)
    return {'status': document['status'], 'physics_validated': False, 'operation': task['operation'], 'scope': SCOPE,
            'limitations': LIMITATIONS, 'problems': document['problems'], 'pins': record['files'], **delivered}


# ----------------------------------------------------------------- planning (no parse, no launch)
def _study(study):
    _require(type(study) is dict and set(study) == set(STUDY_KEYS),
             'the study document requires exactly ' + ', '.join(STUDY_KEYS))
    return study


def _specification(study, task):
    return {'schema_version': 2, 'mode': MODE, 'max_attempts': 1, **study, 'task': task}


def _plain(values, label):
    values = list(values)
    for value in values:
        _require(type(value) is str and value and not value.startswith('-') and '\n' not in value,
                 f'{label} {value!r} must be a plain name that does not start with a dash')
    _require(len(set(values)) == len(values), f'distinct {label}s required')
    return values


def adopt(snakefile, workdir, rundir, study, *, targets=(), cores=1, outputs=None, pins=(), snakemake=None, roots=(),
          members=(), interpreter=None):
    """Pin an external Snakefile and plan its inspection. The Snakefile is not parsed.

    `rundir` is a new folder that receives adoption.json and the inspection study in
    `inspect/`. Approve and run that study with the ordinary commands; then `plan_run`.
    `roots` names further folders that included and referenced files may lie in.
    `members` names workflow files that the Snakefile loads through an include it
    computes; `pins` names other files, which are pinned and never loaded as includes.
    `interpreter` names the Python interpreter of the Snakemake console entry; without
    it the entry's own first line names one, and an entry that names none is refused.
    """
    from . import science
    source = _regular(snakefile, 'Snakefile')
    work = Path(workdir).expanduser().absolute().resolve()
    _require(work.is_dir(), f'working directory {work} must exist')
    root = Path(rundir).expanduser().absolute()
    _require(not os.path.lexists(root), f'adoption folder {root} already exists; one adoption per folder')
    _require(type(cores) is int and cores >= 1, 'cores must be a positive integer')
    study = _study(study)
    targets = _plain(targets, 'target')
    if outputs is not None:
        outputs = _plain(outputs, 'output')
        _require(outputs and all(not os.path.isabs(name) and '..' not in Path(name).parts for name in outputs),
                 'declared outputs are paths inside the working directory')
        outside = _outside(work, outputs)
        _require(not outside, 'declared output ' + ', '.join(outside) + ' is outside the working directory: '
                 'a link on its path leads elsewhere')
    roots = [str(_folder(root)) for root in roots]
    if snakemake is not None:
        # A named executable is used or refused; it never falls back to another one.
        argv = [shutil.which(str(snakemake))]
        _require(argv[0], f'Snakemake executable {snakemake} is not an executable file')
    else:
        argv = wms_runtime.snakemake_argv()
        _require(argv, 'no Snakemake executable found; set RAVEL_SNAKEMAKE or pass --snakemake')
    argv = [os.path.abspath(argv[0]), *argv[1:]]
    bound = bind_interpreter(argv, interpreter)
    members = [_regular(member, 'workflow member') for member in members]
    _require(len(set(members)) == len(members), 'distinct workflow members required')
    closure = scan(source, work, roots, members)
    known = {row['path'] for row in closure['files']}
    for extra in pins:
        path = _regular(extra, 'pinned file')
        if str(path) not in known:
            known.add(str(path))
            closure['files'].append({'role': 'declared', **_pin(path), 'included_by': None, 'line': None})
    root.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir()
    try:
        root = root.resolve()
        record = {'schema_version': 1, 'kind': 'workflow-adoption', 'snakefile': _pin(source), 'workdir': str(work),
                  'snakemake': argv, 'interpreter': bound,
                  'targets': targets, 'cores': cores, 'outputs': outputs, 'roots': roots, **closure,
                  'adopted_utc': _utc(), 'snakefile_parsed': False, 'execution_authorized': False}
        _write_new(root / RECORD, record)
        _write_new(root / 'study.json', study)
        task = {'schema_version': 1, 'operation': 'inspect', 'adoption': RECORD, 'files': _shown_files(record),
                'unpinned_references': record['unpinned_references'], 'rules': record['rules'],
                'commands': inspection_commands(record)}
        _write_new(root / 'inspect.science.json', _specification(study, task))
        science.plan(root / 'inspect', root / 'inspect.science.json')
    except BaseException:
        shutil.rmtree(root)  # nothing was parsed or run; a failed adoption leaves no folder behind
        raise
    return {'adoption': _pin(root / RECORD), 'inspection_study': str(root / 'inspect'), 'files': record['files'],
            'rules_declared': record['rules'], 'unpinned_references': record['unpinned_references'],
            'commands': task['commands'], 'snakefile_parsed': False, 'execution_authorized': False,
            'next': f"review {root / 'inspect' / 'CHECKIN1.md'}, then `ravel approve --rundir {root / 'inspect'}` "
                    f"and `ravel run --rundir {root / 'inspect'}`; then `ravel wms adopt-run --adoption {root}`"}


def _adoption(rundir):
    root = Path(rundir).expanduser().absolute().resolve()
    _require((root / RECORD).is_file(), f'{root} holds no {RECORD}; run `ravel wms adopt` first')
    return root, read_json(root / RECORD)


def latest_inspection(rundir):
    """The inspection record of the highest attempt of the inspection study, or None."""
    root = Path(rundir).expanduser().absolute().resolve()
    found = sorted((root / 'inspect' / 'outputs').glob(f'attempt-*/{MODE}/{INSPECTION}'),
                   key=lambda p: int(p.parts[-3].rpartition('-')[2]))
    return found[-1] if found else None


def _produced(root, path):
    """Refuse an inspection that the current successful supervised attempt of the inspection study did not write."""
    from . import execution
    study = root / 'inspect'
    stage = execution.load_execution(study)['stages'].get('science')
    errors = execution.stage_errors(study, 'science') if stage else ['the inspection study has no supervised stage']
    _require(not errors and stage['status'] == 'succeeded'
             and path == (study / stage['outputs'][0] / MODE / INSPECTION).resolve(),
             f'inspection {path} is not the output of the successful supervised inspection attempt: '
             + '; '.join(errors or ['it lies in another attempt']))


def plan_run(rundir):
    """Plan the run study from a passed inspection; its CHECK-IN 1 carries the roster."""
    from . import science
    root, record = _adoption(rundir)
    check_pins(record)
    path = latest_inspection(root)
    _require(path is not None, f"no inspection yet: approve and run the inspection study {root / 'inspect'} first")
    _produced(root, path.resolve())
    inspection = read_json(path)
    _require(inspection.get('status') == 'passed', f"inspection {path} did not pass: {'; '.join(inspection.get('problems', []))}")
    _require(inspection['adoption'] == _pin(root / RECORD), f'inspection {path} was made for a different adoption record')
    _require(inspection['roster']['jobs'], 'the inspection found no job to run for the requested targets')
    task = {'schema_version': 1, 'operation': 'run', 'adoption': RECORD, 'files': _shown_files(record),
            'unpinned_references': record['unpinned_references'], 'rules': record['rules'],
            'inspection': path.relative_to(root).as_posix(), 'command': run_command(record),
            'roster': inspection['roster']}
    _require(not (root / 'run').exists(), f"the run study {root / 'run'} is already planned; adopt again for a new run")
    spec = root / 'run.science.json'
    atomic_json(spec, _specification(read_json(root / 'study.json'), task))
    science.plan(root / 'run', spec)
    return {'run_study': str(root / 'run'), 'roster': inspection['roster'], 'command': task['command'],
            'unpinned_references': record['unpinned_references'], 'execution_authorized': False,
            'next': f"review {root / 'run' / 'CHECKIN1.md'} and inputs/checkin1.json, then "
                    f"`ravel approve --rundir {root / 'run'}` and `ravel run --rundir {root / 'run'}`"}


def status(rundir):
    """Pins, inspection and run state of one adoption. Nothing is parsed or run."""
    root, record = _adoption(rundir)
    inspection = latest_inspection(root)
    receipts = sorted((root / 'run' / 'outputs').glob(f'attempt-*/{MODE}/{RECEIPT}'))
    return {'adoption': str(root / RECORD), 'files': len(record['files']),
            'changed_files': [{'path': path, 'state': why} for path, why in changed_files(record)],
            'inspection': None if inspection is None else {'path': str(inspection), 'status': read_json(inspection)['status']},
            'run_planned': (root / 'run').is_dir(),
            'receipts': [{'path': str(p), 'status': read_json(p)['status'], 'exit_code': read_json(p)['exit_code']} for p in receipts],
            'scientific_acceptance_inferred': False}


OPERATIONS = ('adopt', 'adopt-run', 'adopt-status')


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] not in (*OPERATIONS, '-h', '--help'):
        # Seam: every other `ravel wms` operation belongs to the workflow-manager launch module.
        try:
            from . import wms_launch
        except ImportError:
            raise ValueError(f"unknown `ravel wms` operation {arguments[0]!r}; available: {', '.join(OPERATIONS)}") from None
        return wms_launch.main(arguments)
    p = argparse.ArgumentParser(prog='ravel wms', description=__doc__)
    sub = p.add_subparsers(dest='operation', required=True)
    a = sub.add_parser('adopt', help='pin an external Snakefile and plan its inspection; the Snakefile is not parsed')
    a.add_argument('--snakefile', type=Path, required=True)
    a.add_argument('--workdir', type=Path, required=True, help='the working directory Snakemake runs the workflow in')
    a.add_argument('--rundir', type=Path, required=True, help='new folder for the adoption record and its two studies')
    a.add_argument('--study', type=Path, required=True,
                   help='JSON with ' + ', '.join(STUDY_KEYS) + ' for the inspection and run studies')
    a.add_argument('--target', action='append', default=[], help='Snakemake target; repeat for several')
    a.add_argument('--cores', type=int, default=1)
    a.add_argument('--output', action='append', help='required output inside the working directory; repeat for several')
    a.add_argument('--pin', action='append', default=[], type=Path,
                   help='another file to pin, never loaded as an include; repeat for several')
    a.add_argument('--member', action='append', default=[], type=Path,
                   help='workflow file that the Snakefile loads through an include it computes; it is pinned and '
                        'its rules are read and shown; repeat for several')
    a.add_argument('--snakemake', help='Snakemake executable')
    a.add_argument('--interpreter', help='Python interpreter that runs the Snakemake console entry; by default the '
                                         'one that its first line names')
    a.add_argument('--root', action='append', default=[], type=Path,
                   help='another folder that included and referenced files may lie in; repeat for several')
    r = sub.add_parser('adopt-run', help='plan the run study from a passed inspection; CHECK-IN 1 shows the roster')
    r.add_argument('--adoption', type=Path, required=True)
    s = sub.add_parser('adopt-status', help='show pins, inspection and run state of an adoption')
    s.add_argument('--adoption', type=Path, required=True)
    args = p.parse_args(arguments)
    if args.operation == 'adopt':
        value = adopt(args.snakefile, args.workdir, args.rundir, read_json(args.study), targets=args.target,
                      cores=args.cores, outputs=args.output, pins=args.pin, snakemake=args.snakemake, roots=args.root,
                      members=args.member, interpreter=args.interpreter)
    elif args.operation == 'adopt-run':
        value = plan_run(args.adoption)
    else:
        value = status(args.adoption)
    print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
