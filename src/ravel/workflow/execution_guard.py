"""Strict execution guard: an agent's shell may run only the workflow manager and described software.

The project's workflow policy (``workflow/policy.json``) selects a mode through the key
``execution_guard``: ``"strict"``, or absent. ``"wms_required": true`` without it is the
discipline mode owned by the workflow-manager launch package, which plugs into
``discipline_refusal`` below; this module never starts a stage.

In strict mode the Claude Code ``PreToolUse`` hook for the Bash tool runs ``decide`` on every
command. A command is allowed only when every statement of it is

- ``snakemake`` with listed flags, on a Snakefile (and the ``include:`` files and ``rules/*.smk``
  beside it) that is tracked in the project's git index and unmodified;
- ``ravel`` (or ``python -m ravel``) with a listed subcommand, for example ``status`` or
  ``wms add|launch|status``; ``ravel run`` is refused with the workflow-manager route;
- ``git`` with a read subcommand, ``add`` or ``commit``;
- a short read-only inspection program (``ls``, ``cat``, ``grep`` ...);

and every program of the first three classes has an installed software skill. Redirections,
subshells, command substitution, background jobs, ``cd``, environment prefixes and wrappers
(``env``, ``bash -c``, ``xargs``) are refused because they hide what runs.

Every decision is appended to the guard log (``.ravel/agent-audit/execution-guard.jsonl``), one
JSON object per line:

    {"schema_version": 1, "kind": "execution-guard-decision", "utc": ..., "mode": "strict"|"discipline"|"off",
     "decision": "allowed"|"refused", "rule": "<matched rule or refusing rule>", "segments": <int>,
     "command_sha256": ..., "session_id": ...}

The command text is not logged, only its hash. ``read_log`` and ``summary`` are the readers.

What this enforces: the shell tool of an agent session that loads the project's
``.claude/settings.json``. What it cannot: a person at a terminal, a session started without the
project settings, an agent host whose shell tool is not routed through this hook, or the file-write
tools (they are covered by the file hooks). It is a client-side control and a record.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

from ravel.paths import package_data_path

HOOK_MARK = 'ravel.workflow.execution_guard hook'
POLICY = Path('workflow') / 'policy.json'
MODES = ('off', 'discipline', 'strict')
ROUTE = ("Code in this project runs only through the workflow manager: add the approved stage with "
         "`ravel wms add`, launch it with `ravel wms launch`, or inspect it with `snakemake -n` on the "
         "tracked Snakefile.")
_PUNCT = set(';&|<>()')
_SEPARATORS = {';', '&&', '||', '|'}
_GIT_TIMEOUT = 20


def data():
    return json.loads(package_data_path('agent_surface', 'execution_guard.json').read_text())


# -------------------------------------------------------------------- policy

def _mode_of(path):
    """The mode one policy file selects; an unreadable existing file is strict (fail closed)."""
    if not path.is_file():
        return 'off'
    try:
        return mode_from_text(path.read_text())
    except OSError:
        return 'strict'


def mode_from_text(text):
    try:
        document = json.loads(text)
        if not isinstance(document, dict):
            raise ValueError
    except ValueError:
        return 'strict'
    if document.get('execution_guard') == 'strict':
        return 'strict'
    return 'discipline' if document.get('wms_required') is True else 'off'


def _stricter(*modes):
    return max(modes, key=MODES.index)


def _git(project, *args):
    git = shutil.which('git')
    if git is None:
        return None
    try:
        return subprocess.run([git, '-C', str(project), *args], capture_output=True, text=True,
                              timeout=_GIT_TIMEOUT, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None


def mode(project):
    """The effective mode: the stricter of the working-tree policy and the committed policy.

    An uncommitted edit of the policy file therefore cannot relax a committed strict mode.
    """
    project = Path(project)
    working = _mode_of(project / POLICY)
    done = _git(project, 'show', 'HEAD:' + POLICY.as_posix())
    committed = mode_from_text(done.stdout) if done is not None and done.returncode == 0 else 'off'
    return _stricter(working, committed)


def mode_for_path(path):
    """The mode of the nearest enclosing project that carries a workflow policy."""
    here = Path(path).absolute()
    for parent in (here, *here.parents):
        if (parent / POLICY).is_file():
            return mode(parent)
    return 'off'


def discipline_refusal(command, project):
    """The workflow-manager launch package's discipline check: a refusal text or None.

    ``agent_surface.guard_command`` refuses the common direct launch spellings where the
    project policy requires the workflow manager; the launch guard remains authoritative.
    """
    from .agent_surface import guard_command
    return guard_command(project, command)


# ------------------------------------------------------------------ parsing

class Unparsable(ValueError):
    """The command uses a shell construct the guard cannot analyse; it is refused."""


def _newlines_to_separators(command):
    out, quote, escape = [], None, False
    for ch in command.replace('\\\n', ''):
        if escape:
            out.append(ch)
            escape = False
        elif ch == '\\' and quote != "'":
            out.append(ch)
            escape = True
        elif quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            out.append(ch)
            quote = ch
        elif ch in '\n\r':
            out.append(' ; ')
        else:
            out.append(ch)
    return ''.join(out)


def statements(command):
    """The commands of a shell line as argv lists, or ``Unparsable`` for anything hidden."""
    lexer = shlex.shlex(_newlines_to_separators(command), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ''
    out, current = [], []
    try:
        for token in lexer:
            if token and set(token) <= _PUNCT:
                if token not in _SEPARATORS:
                    raise Unparsable(f'`{token}` (redirection, subshell or background job)')
                if current:
                    out.append(current)
                    current = []
                continue
            if '$(' in token or '`' in token or '${' in token:
                raise Unparsable('command substitution or parameter expansion')
            if '<' in token or '>' in token:
                raise Unparsable('redirection')
            current.append(token)
    except ValueError as exc:
        raise Unparsable(f'unbalanced quoting ({exc})') from None
    if current:
        out.append(current)
    return out


# ----------------------------------------------------------------- decisions

def _refused(rule, why):
    return {'allowed': False, 'rule': rule, 'why': why}


def _allowed(rule):
    return {'allowed': True, 'rule': rule, 'why': ''}


def _program(word):
    """(base name, why-not) of a program word; a path must resolve to the PATH program."""
    if '$' in word:
        return None, 'a program name built from a variable'
    base = os.path.basename(word)
    # The site branch checks the exact pinned shim, even when its prefix is not
    # on the agent's PATH. No other invocation of this name is admitted.
    if base == 'ravel-snakemake':
        return base, None
    if '/' not in word:
        return base, None
    pinned = {os.environ.get('RAVEL_PYTHON'), sys.executable}
    found = shutil.which(base)
    mine = os.path.realpath(word)
    if found and os.path.realpath(found) == mine or mine in {os.path.realpath(p) for p in pinned if p}:
        return base, None
    return None, f'path `{word}` is not the installed program of that name'


def _skill_missing(project, skill):
    return not (Path(project) / '.claude' / 'skills' / skill / 'SKILL.md').is_file()


def _tracked_problem(project, rel):
    """Why a workflow file may not be used as a target (None when it is tracked and unmodified)."""
    done = _git(project, 'ls-files', '--error-unmatch', '--', rel)
    if done is None:
        return f'`{rel}` cannot be checked: git is unavailable'
    if done.returncode != 0:
        return f'`{rel}` is not tracked in git (commit it first)'
    changed = _git(project, 'diff', '--quiet', '--', rel)
    if changed is None or changed.returncode != 0:
        return f'`{rel}` has uncommitted changes (stage or commit them first)'
    return None


def _snakefile_problem(project, cwd, explicit):
    project = Path(project).resolve()
    if explicit is not None:
        candidate = (Path(cwd) / explicit).resolve()
    else:
        found = [Path(cwd) / c for c in data()['snakefile_candidates'] if (Path(cwd) / c).is_file()]
        if not found:
            return 'no Snakefile in the working directory; name the project\'s tracked Snakefile with `-s`'
        candidate = found[0].resolve()
    if not candidate.is_file():
        return f'Snakefile `{explicit}` does not exist'
    if project != candidate and project not in candidate.parents:
        return 'the Snakefile is outside the project'
    related = [candidate]
    text = candidate.read_text(errors='replace')
    related += [(candidate.parent / m).resolve() for m in re.findall(r'^\s*include\s*:\s*["\']([^"\'*?]+)["\']', text, re.M)]
    related += sorted((candidate.parent / 'rules').glob('*.smk')) if (candidate.parent / 'rules').is_dir() else []
    for path in dict.fromkeys(related):
        if not path.is_file():
            continue
        if project not in path.parents:
            return f'`{path}` is outside the project'
        problem = _tracked_problem(project, path.relative_to(project).as_posix())
        if problem:
            return problem
    return None


def _snakemake(argv, project, cwd, rules):
    site_active = False
    config = Path(project) / 'workflow' / 'project.json'
    if config.exists():
        try:
            site_active = json.loads(config.read_bytes()).get('profile') == 'htcondor'
        except (OSError, ValueError, AttributeError):
            return _refused('snakemake-site-profile', 'unreadable workflow project configuration')
    inspect = any(t in argv for t in ('-n', '--dry-run', '--dryrun', '--version', '-h', '--help'))
    if (site_active and not inspect or os.path.basename(argv[0]) == 'ravel-snakemake'
            or any(t.split('=', 1)[0] in ('--profile', '--executor') for t in argv[1:])):
        try:
            from . import wms_site
            wms_site.admit_command(argv, project, cwd)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return _refused('snakemake-site-profile', str(exc))
        return _allowed('snakemake-governed-site')
    flags = rules['snakemake_flags']
    explicit, positional, i = None, [], 1
    while i < len(argv):
        token = argv[i]
        if token.startswith('-') and token != '-':
            name, equals, value = token.partition('=')
            if name in flags['valued']:
                if not equals:
                    i += 1
                    if i >= len(argv):
                        return _refused('snakemake-flag', f'`{name}` needs a value')
                    value = argv[i]
                if name in ('-s', '--snakefile'):
                    explicit = value
            elif name not in flags['switch'] or equals:
                return _refused('snakemake-flag', f'`snakemake {token}` is not an allowed option; '
                                'allowed: dry runs, targets, --cores, --until, --forcerun, -s')
        else:
            positional.append(token)
        i += 1
    if any(f in argv for f in ('--version', '-h', '--help')):
        return _allowed('snakemake-info')
    problem = _snakefile_problem(project, cwd, explicit)
    if problem:
        return _refused('snakemake-untracked-snakefile', problem)
    dry = any(f in argv for f in ('-n', '--dry-run', '--dryrun'))
    return _allowed('snakemake-dry-run' if dry else 'snakemake-target')


def _ravel(argv, rules):
    rest = argv[1:]
    subcommand = next((t for t in rest if not t.startswith('-')), None)
    if subcommand is None:
        return _allowed('ravel-info') if all(t in ('-h', '--help', '--version') for t in rest) else \
            _refused('ravel-subcommand', 'name a ravel subcommand')
    if subcommand in rules['ravel_refused_with_route']:
        return _refused('ravel-direct-run', f'`ravel {subcommand}` starts work directly. ' + ROUTE)
    allowed = rules['ravel_subcommands']
    if subcommand not in allowed:
        return _refused('ravel-subcommand', f'`ravel {subcommand}` is not an allowed command in strict mode. ' + ROUTE)
    detail = allowed[subcommand]
    if detail is not None:
        tail = rest[rest.index(subcommand) + 1:]
        verb = next((t for t in tail if not t.startswith('-')), None)
        if verb not in detail and not any(t in ('-h', '--help') for t in tail):
            return _refused('ravel-subcommand', f'`ravel {subcommand} {verb or ""}` is not allowed; '
                            f'allowed: {", ".join(detail)}')
    return _allowed(f'ravel-{subcommand}')


def _git_rule(argv, rules):
    tokens = argv[1:]
    if tokens and tokens[0] == '--no-pager':
        tokens = tokens[1:]
    if not tokens or tokens[0].startswith('-'):
        return _refused('git-subcommand', 'give a git subcommand without global options')
    sub, args = tokens[0], tokens[1:]
    allowed = rules['git_subcommands']
    if sub not in allowed:
        return _refused('git-subcommand', f'`git {sub}` is not allowed in strict mode '
                        f'(allowed: {", ".join(sorted(allowed))})')
    for token in args:
        if token.split('=', 1)[0] in rules['git_refused_flags']:
            return _refused('git-flag', f'`git {sub} {token}` is not allowed')
    if allowed[sub] is not None:
        for token in args:
            if token.startswith('-') and token not in allowed[sub]:
                return _refused('git-flag', f'`git {sub} {token}` is not allowed; list form only')
            if not token.startswith('-'):
                return _refused('git-flag', f'`git {sub} {token}` would change a branch; list form only')
    return _allowed(f'git-{sub}')


def _statement(argv, project, cwd, rules):
    if re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', argv[0]):
        return _refused('environment-prefix', 'an environment assignment before a command')
    base, why = _program(argv[0])
    if base is None:
        return _refused('program-path', why)
    if re.fullmatch(r'python(?:[0-9]+(?:[.][0-9]+)*)?', base):
        if argv[1:3] == ['-m', 'ravel']:
            base, argv = 'ravel', ['ravel', *argv[3:]]
        else:
            return _refused('direct-code', f'`{base}` runs code outside the workflow manager. ' + ROUTE)
    row = rules['programs'].get(base)
    if row is None:
        extra = ''
        if base in ('bash', 'sh', 'zsh', 'env', 'xargs', 'nohup', 'time', 'timeout', 'conda', 'cd'):
            extra = f' (`{base}` wraps or hides the command it starts)'
        return _refused('program-not-allowed', f'`{base}` is not an allowed program in strict mode{extra}. ' + ROUTE)
    if rules['classes'][row['class']]['requires_skill'] and _skill_missing(project, row['skill']):
        return _refused('no-skill', f'`{base}` has no software skill installed in this project '
                        f'(.claude/skills/{row["skill"]}/SKILL.md); run `ravel agent-surface install`.')
    for token in argv[1:]:
        if token.split('=', 1)[0] in row.get('refuse_flags', []):
            return _refused('program-flag', f'`{base} {token}` is not allowed')
    if base in ('snakemake', 'ravel-snakemake'):
        return _snakemake(argv, project, cwd, rules)
    if base == 'ravel':
        return _ravel(argv, rules)
    if base == 'git':
        return _git_rule(argv, rules)
    return _allowed(f'inspect-{base}')


def decide(command, project, cwd=None):
    """The guard's decision for one shell command: ``{mode, allowed, rule, why, segments}``."""
    project = Path(project)
    current = mode(project)
    result = {'mode': current, 'segments': 0}
    if current != 'strict':
        refusal = discipline_refusal(command, project) if current == 'discipline' else None
        if refusal:
            return {**result, 'allowed': False, 'rule': 'discipline', 'why': refusal}
        return {**result, 'allowed': True, 'rule': 'not-strict', 'why': ''}
    cwd = Path(cwd) if cwd else project
    rules = data()
    try:
        parts = statements(command)
    except Unparsable as exc:
        return {**result, **_refused('unparsable', f'{exc} hides what would run. ' + ROUTE)}
    if not parts:
        return {**result, **_refused('empty', 'an empty command')}
    matched = []
    for argv in parts:
        outcome = _statement(argv, project, cwd, rules)
        if not outcome['allowed']:
            return {**result, 'segments': len(parts), **outcome}
        matched.append(outcome['rule'])
    return {**result, 'segments': len(parts), 'allowed': True, 'rule': '+'.join(dict.fromkeys(matched)), 'why': ''}


# ----------------------------------------------------------------------- log

def log_path(project):
    return Path(project) / data()['log']


def record(project, command, result, session_id=''):
    row = {'schema_version': 1, 'kind': 'execution-guard-decision',
           'utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'mode': result['mode'],
           'decision': 'allowed' if result['allowed'] else 'refused', 'rule': result['rule'],
           'segments': result['segments'], 'command_sha256': hashlib.sha256(command.encode()).hexdigest(),
           'session_id': session_id or ''}
    path = log_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(row, sort_keys=True) + '\n')
    return row


def read_log(project):
    path = log_path(project)
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            rows.append({'kind': 'unreadable-line'})
    return rows


def summary(project):
    rows = read_log(project)
    refused = [r for r in rows if r.get('decision') == 'refused']
    return {'decisions': len(rows), 'allowed': sum(r.get('decision') == 'allowed' for r in rows),
            'refused': len(refused), 'unreadable': sum(r.get('kind') == 'unreadable-line' for r in rows),
            'modes': sorted({r.get('mode') for r in rows if r.get('mode')}),
            'refusal_rules': sorted({r.get('rule') for r in refused})}


# ---------------------------------------------------------------------- hook

def hook(raw, project):
    """The PreToolUse-on-Bash decision: ``(allowed, message)``. Other tools pass untouched."""
    try:
        event = json.loads(raw or '{}')
    except ValueError:
        event = {}
    if (event.get('tool_name') or '') != 'Bash':
        return True, ''
    command = ((event.get('tool_input') or {}).get('command') or '')
    result = decide(command, project, event.get('cwd') or None)
    record(project, command, result, event.get('session_id') or '')
    if result['allowed']:
        return True, ''
    return False, f'BLOCKED (strict execution guard, rule {result["rule"]}): {result["why"]}'


def worker_shell_refusal(belt, argv, agent, rundir):
    """Why a RAVEL worker may not launch under a strict policy (None when its tools hold no shell).

    The broker's toolbelt names only read, write, knowledge, check and workflow-manager actions;
    a belt with any other action, or a Claude worker whose built-in tool list is not empty, offers
    a general shell. Other CLIs' built-in shells are not visible in argv; their tools come only
    through the broker's MCP face and the sandbox declared by the transport.
    """
    if mode_for_path(rundir) != 'strict':
        return None
    allowed = {'read', 'write', 'knowledge query', 'check run'}
    extra = sorted({t['executes_through']['action'] for t in belt['tools']
                    if t['executes_through']['action'] and t['executes_through']['action'] not in allowed
                    and not str(t['executes_through']['action']).startswith('wms ')})
    if extra:
        return f'the toolbelt offers action(s) {", ".join(extra)} beyond the workflow-manager tools'
    if agent == 'claude' and not ('--tools' in argv and argv[argv.index('--tools') + 1:][:1] == ['']):
        return 'the claude worker does not disable its built-in tools (--tools \'\'), so it would have a general shell'
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel.workflow.execution_guard', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='action', required=True)
    h = commands.add_parser('hook', help='PreToolUse hook: tool-call JSON on stdin; exit 2 blocks')
    h.add_argument('--project', type=Path, default=None)
    d = commands.add_parser('decide', help='print the decision for one command')
    d.add_argument('--project', type=Path, required=True)
    d.add_argument('--command', required=True)
    s = commands.add_parser('summary', help='summarise the guard log')
    s.add_argument('--project', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == 'summary':
        print(json.dumps(summary(args.project), indent=2, sort_keys=True))
        return 0
    if args.action == 'decide':
        print(json.dumps(decide(args.command, args.project), indent=2, sort_keys=True))
        return 0
    project = args.project or Path(os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd())
    try:
        allowed, message = hook(sys.stdin.read(), project)
    except Exception as exc:  # noqa: BLE001 - a guard that fails must not fail open under a strict policy
        try:
            strict = mode(project) == 'strict'
        except Exception:  # noqa: BLE001
            strict = True
        if strict:
            print(f'BLOCKED (strict execution guard): the guard failed ({type(exc).__name__}: {exc}).', file=sys.stderr)
            return 2
        return 0
    if not allowed:
        print(message, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
