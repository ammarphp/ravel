"""The strict execution guard: the shell runs only the workflow manager and described software."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ravel.workflow import agent_surface as surf, execution_guard as guard, role_registry, sandbox
from ravel.workflow import agent_worker as worker
from ravel.workflow.transports import cli_worker
from ravel.paths import repository_root

from test_cli_worker_adapter import cli, ready, spec  # noqa: F401 - the fake-CLI fixture of the adapter suite

SKILLS = ('software-snakemake', 'software-git', 'software-ravel')
# The workflow policy document of the launch package; the guard adds its optional key.
POLICY = {'schema_version': 1, 'wms_required': True, 'engine': 'snakemake'}


def git(root, *args):
    subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.org', '-C', str(root), *args],
                   check=True, capture_output=True)


def make_project(root, policy='strict', skills=SKILLS):
    (root / 'workflow/rules').mkdir(parents=True)
    (root / 'workflow/Snakefile').write_text('include: "rules/a.smk"\nrule all:\n    input: "a.txt"\n')
    (root / 'workflow/rules/a.smk').write_text('rule a:\n    output: "a.txt"\n    shell: "true"\n')
    if policy is not None:
        (root / 'workflow/policy.json').write_text(json.dumps({**POLICY, **policy} if isinstance(policy, dict)
                                                              else {**POLICY, 'execution_guard': policy}))
    for name in skills:
        (root / '.claude/skills' / name).mkdir(parents=True)
        (root / '.claude/skills' / name / 'SKILL.md').write_text(f'---\nname: {name}\n---\n')
    git(root, 'init', '-q')
    git(root, 'add', '-A')
    git(root, 'commit', '-q', '-m', 'project')
    return root


@pytest.fixture
def project(tmp_path):
    return make_project(tmp_path / 'proj')


def allowed(project, command, cwd=None):
    return guard.decide(command, project, cwd)


# ---- 1. negative first: without the strict declaration nothing is guarded ---------------------------------

def test_without_a_strict_policy_direct_code_is_allowed(tmp_path):
    root = make_project(tmp_path / 'open', policy=None)
    result = allowed(root, 'python analysis.py')
    assert result['allowed'] and result['rule'] == 'not-strict' and result['mode'] == 'off'
    wms_only = make_project(tmp_path / 'wms', policy={'wms_required': True})
    assert allowed(wms_only, 'python analysis.py')['mode'] == 'discipline'  # the launch package owns this mode


def test_discipline_mode_refuses_direct_launches_through_the_same_hook(tmp_path):
    root = make_project(tmp_path / 'discipline', policy={'wms_required': True})
    refused = allowed(root, 'ravel run --rundir ANA-0001')
    assert not refused['allowed'] and refused['rule'] == 'discipline' and 'ravel wms launch' in refused['why']
    assert allowed(root, 'ravel wms launch --project . --task ANA-0001')['allowed']
    assert allowed(root, 'python analysis.py')['allowed']  # discipline is not strict


def test_strict_refuses_direct_code_shells_and_one_liners(project):
    for command in ('python analysis.py', 'python3 -c "import uproot; print(1)"', "bash -c 'ls'", 'sh run.sh',
                    'uproot -h', 'env FOO=1 ls', 'FOO=1 git status', 'xargs ls', 'conda run -n x python a.py',
                    'echo x > f.txt', 'cat < f', 'ls $(pwd)', 'ls `pwd`', 'ls &', 'cd workflow && ls', './snakemake -n',
                    'ls\nrm -rf x', 'git status; python a.py', 'git log | python -c "pass"', 'rm -rf x', '(ls)'):
        result = allowed(project, command)
        assert not result['allowed'], command
        assert result['why'], command
    assert 'ravel wms' in allowed(project, 'python analysis.py')['why']


def test_strict_allows_the_workflow_manager_ravel_git_reads_and_inspection(project):
    for command in ('snakemake -n', 'snakemake --dry-run -s workflow/Snakefile', 'snakemake --cores 1 a.txt',
                    'snakemake -n --until a', 'git status', 'git log --oneline -3', 'git diff', 'git add -A',
                    'git commit -m "x"', 'ravel status --rundir r --write', 'ravel wms add --rundir r',
                    'ravel wms launch --task t', 'ravel wms status', 'ravel agent-surface check --project .',
                    'python -m ravel status', 'git log | head -5', 'git status && ls -la', 'cat workflow/Snakefile',
                    'grep -n rule workflow/Snakefile', 'git commit -m "multi\nline message"'):
        result = allowed(project, command)
        assert result['allowed'], (command, result)


def test_direct_ravel_run_is_refused_with_the_workflow_manager_route(project):
    result = allowed(project, 'ravel run --rundir r')
    assert not result['allowed'] and result['rule'] == 'ravel-direct-run' and 'ravel wms launch' in result['why']
    assert not allowed(project, 'ravel approve-everything')['allowed']
    assert not allowed(project, 'ravel wms rm')['allowed']


def test_snakemake_options_are_listed_not_assumed(project):
    for command in ('snakemake --shell-executable /bin/sh a.txt', 'snakemake --use-conda a.txt', 'snakemake --profile p',
                    'snakemake --configfile c.yaml', 'snakemake -d /tmp a.txt', 'snakemake --cores'):
        assert not allowed(project, command)['allowed'], command


# ---- an allowed program with no skill ---------------------------------------------------------------------

def test_an_allowed_program_without_a_skill_is_refused(tmp_path):
    root = make_project(tmp_path / 'noskill', skills=('software-ravel', 'software-snakemake'))
    result = allowed(root, 'git status')
    assert not result['allowed'] and result['rule'] == 'no-skill' and 'software-git' in result['why']
    assert allowed(root, 'ls')['allowed']  # inspection programs need no skill
    assert allowed(root, 'snakemake -n')['allowed']
    no_ravel = make_project(tmp_path / 'noravel', skills=('software-git', 'software-snakemake'))
    assert allowed(no_ravel, 'ravel status')['rule'] == 'no-skill'


# ---- 4. tracked Snakefile ----------------------------------------------------------------------------------

def test_an_untracked_snakefile_is_refused_as_a_target(project):
    (project / 'other.smk').write_text('rule x:\n    shell: "true"\n')
    result = allowed(project, 'snakemake -s other.smk')
    assert not result['allowed'] and result['rule'] == 'snakemake-untracked-snakefile' and 'not tracked' in result['why']
    assert not allowed(project, 'snakemake -s /elsewhere/Snakefile -n')['allowed']
    assert allowed(project, 'snakemake -s workflow/Snakefile -n')['allowed']


def test_a_modified_or_untracked_workflow_file_is_refused(project):
    (project / 'workflow/rules/new.smk').write_text('rule evil:\n    shell: "true"\n')
    untracked = allowed(project, 'snakemake -n')
    assert not untracked['allowed'] and 'new.smk' in untracked['why']
    (project / 'workflow/rules/new.smk').unlink()
    (project / 'workflow/Snakefile').write_text('rule all:\n    shell: "true"\n')
    modified = allowed(project, 'snakemake -n')
    assert not modified['allowed'] and 'uncommitted changes' in modified['why']
    git(project, 'add', 'workflow/Snakefile')
    assert allowed(project, 'snakemake -n')['allowed']  # staged is tracked and equal to the index


def test_no_snakefile_in_the_working_directory_is_refused(project, tmp_path):
    empty = tmp_path / 'proj' / 'docs'
    empty.mkdir()
    assert not allowed(project, 'snakemake -n', cwd=empty)['allowed']


# ---- every decision is logged -----------------------------------------------------------------------------

def test_every_decision_is_logged_with_hash_decision_and_rule(project):
    commands = ['snakemake -n', 'python analysis.py', 'git status', 'ravel run --rundir r']
    for command in commands:
        guard.hook(json.dumps({'tool_name': 'Bash', 'tool_input': {'command': command}, 'cwd': str(project),
                               'session_id': 's-1'}), project)
    guard.hook(json.dumps({'tool_name': 'Read', 'tool_input': {'file_path': 'x'}}), project)  # not a shell call
    rows = guard.read_log(project)
    assert [r['decision'] for r in rows] == ['allowed', 'refused', 'allowed', 'refused']
    assert [r['rule'] for r in rows] == ['snakemake-dry-run', 'direct-code', 'git-status', 'ravel-direct-run']
    import hashlib
    assert rows[1]['command_sha256'] == hashlib.sha256(b'python analysis.py').hexdigest()
    assert all(r['mode'] == 'strict' and r['session_id'] == 's-1' for r in rows)
    assert 'analysis.py' not in guard.log_path(project).read_text()
    assert guard.summary(project) == {'decisions': 4, 'allowed': 2, 'refused': 2, 'unreadable': 0, 'modes': ['strict'],
                                      'refusal_rules': ['direct-code', 'ravel-direct-run']}


def test_an_uncommitted_edit_cannot_relax_a_committed_strict_policy(project):
    (project / 'workflow/policy.json').write_text(json.dumps({'execution_guard': 'off'}))
    assert guard.mode(project) == 'strict'
    (project / 'workflow/policy.json').write_text('{ not json')
    assert guard.mode(project) == 'strict'


# ---- the hook entry point as the host runs it -------------------------------------------------------------

def run_hook(project, payload, extra_env=None):
    source = str(Path(guard.__file__).resolve().parents[2])
    env = {**os.environ, 'PYTHONPATH': source, 'CLAUDE_PROJECT_DIR': str(project), **(extra_env or {})}
    return subprocess.run([sys.executable, '-m', 'ravel.workflow.execution_guard', 'hook', '--project', str(project)],
                          input=json.dumps(payload), capture_output=True, text=True, env=env)


def test_hook_blocks_with_exit_2_and_names_the_route(project):
    blocked = run_hook(project, {'tool_name': 'Bash', 'tool_input': {'command': 'python analysis.py'}, 'cwd': str(project)})
    assert blocked.returncode == 2 and 'strict execution guard' in blocked.stderr and 'ravel wms launch' in blocked.stderr
    fine = run_hook(project, {'tool_name': 'Bash', 'tool_input': {'command': 'git status'}, 'cwd': str(project)})
    assert fine.returncode == 0 and fine.stderr == ''
    other = run_hook(project, {'tool_name': 'Edit', 'tool_input': {}})
    assert other.returncode == 0


def test_hook_fails_closed_under_strict_when_the_guard_crashes(project, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError('boom')
    monkeypatch.setattr(guard, 'decide', broken)
    monkeypatch.setattr(sys, 'stdin', __import__('io').StringIO(json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 'ls'}})))
    assert guard.main(['hook', '--project', str(project)]) == 2


# ---- install seam --------------------------------------------------------------------------------------

def test_install_adds_one_guard_hook_and_check_requires_it(tmp_path):
    fork = tmp_path / 'fork'
    fork.mkdir()
    (fork / 'AGENTS.md').write_text('# Rules\n\n- Run all code through the workflow manager.\n')
    report = surf.install(fork, skills_from=repository_root(), wms_guard=True)
    again = surf.install(fork, skills_from=repository_root(), wms_guard=True)
    settings = json.loads((fork / '.claude/settings.json').read_text())
    commands = [h['command'] for g in settings['hooks']['PreToolUse'] for h in g['hooks']]
    assert sum(guard.HOOK_MARK in c for c in commands) == 1
    assert report['wms_guard'] == {'hook': True, 'policy_mode': 'off'} and again['wms_guard']['hook']
    assert surf.check(fork) == []
    # Project instruction documents stay byte-identical; the guidance file states the guard.
    assert (fork / 'AGENTS.md').read_text() == '# Rules\n\n- Run all code through the workflow manager.\n'
    assert 'The execution guard is installed' in (fork / '.ravel/agent-guidance.md').read_text()
    settings['hooks']['PreToolUse'] = []
    (fork / '.claude/settings.json').write_text(json.dumps(settings))
    # One guard hook: the check names it with the workflow-manager guard message.
    assert 'workflow-manager guard hook missing' in surf.check(fork)


def test_install_without_the_flag_adds_no_guard_hook(tmp_path):
    fork = tmp_path / 'plain'
    fork.mkdir()
    surf.install(fork, skills_from=repository_root())
    settings = json.loads((fork / '.claude/settings.json').read_text())
    assert guard.HOOK_MARK not in json.dumps(settings)


# ---- 5. a worker under the declaration has no general shell ------------------------------------------------

def belt(*actions):
    return {'tools': [{'name': a or 'final', 'executes_through': {'action': a, 'fixed_args': {}}} for a in actions]}


def test_worker_refusal_unit(tmp_path):
    make_project(tmp_path / 'p')
    run = tmp_path / 'p' / 'run'
    run.mkdir()
    closed = ['claude', '--tools', '', '--allowedTools', 'mcp__ravel__ws_read']
    assert guard.worker_shell_refusal(belt('read', 'write', None, 'wms launch'), closed, 'claude', run) is None
    assert 'exec' in guard.worker_shell_refusal(belt('read', 'exec'), closed, 'claude', run)
    assert 'built-in tools' in guard.worker_shell_refusal(belt('read'), ['claude', '--tools', 'Bash'], 'claude', run)
    assert 'built-in tools' in guard.worker_shell_refusal(belt('read'), ['claude'], 'claude', run)
    assert guard.worker_shell_refusal(belt('read', 'exec'), ['claude'], 'claude', tmp_path) is None  # no policy here


def test_launch_under_a_strict_policy_has_no_shell_and_refuses_one(cli, monkeypatch):  # noqa: F811
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    (cli / 'workflow').mkdir()
    (cli / 'workflow/policy.json').write_text(json.dumps({**POLICY, 'execution_guard': 'strict'}))
    ready(cli)
    s = spec(cli)
    ws = worker.materialize(cli / 'run', s)
    d = cli_worker.prepare_launch(cli / 'run', s, ws)
    assert set(d['allowed_actions']) <= {'read', 'write', 'knowledge query', 'check run'}
    assert d['argv'][d['argv'].index('--tools') + 1] == ''
    tools = json.loads((ws / 'inputs/toolbelt.json').read_text())['tools']
    assert not any('exec' in (t['executes_through'].get('action') or '') for t in tools)
    real = cli_worker.toolbelt_for

    def with_shell(*args, **kwargs):
        result = real(*args, **kwargs)
        result['tools'].append({'name': 'shell', 'atlas_id': None, 'description': 'a general shell', 'executes_through': {'action': 'exec', 'fixed_args': {}}})
        return result
    monkeypatch.setattr(cli_worker, 'toolbelt_for', with_shell)
    s2 = spec(cli, attempt=2)
    ws2 = worker.materialize(cli / 'run', s2)
    with pytest.raises(cli_worker.LaunchRefused) as refused:
        cli_worker.prepare_launch(cli / 'run', s2, ws2)
    assert refused.value.missing == ['shell']


@pytest.mark.parametrize('arguments', [
    '-terse job.sub', 'job.sub', '-dry-run out.ads job.sub', '-dry-run /dev/null',
    '-dry-run /dev/null job.sub -queue 2', '-dry-run /dev/null job.sub x=y',
    '-dry /dev/null job.sub', '-dry-run /dev/null x=y', '-dry-run /dev/null -',
    '-dry-run /dev/null job.sub > output', '-dry-run /dev/null job.sub; condor_submit job.sub'])
def test_condor_validation_exception_does_not_allow_submissions(project, arguments):
    assert not allowed(project, 'condor_submit ' + arguments)['allowed']


def test_condor_dry_run_is_allowed_and_mock_never_submits(project, monkeypatch, tmp_path):
    tool = tmp_path / 'condor_submit'
    tool.write_text('#!/bin/sh\n[ "$1" = -dry-run ] && [ "$2" = /dev/null ] && [ "$#" = 3 ] || exit 90\nprintf "validated\\n"\n')
    tool.chmod(0o755)
    monkeypatch.setenv('PATH', str(tmp_path) + os.pathsep + os.environ['PATH'])
    command = 'condor_submit -dry-run /dev/null retained.sub'
    verdict = allowed(project, command)
    assert verdict['allowed'] and verdict['rule'] == 'condor-submit-dry-run'
    done = subprocess.run(command.split(), capture_output=True, text=True, check=True)
    assert done.stdout == 'validated\n'


@pytest.mark.parametrize('line', ['include : python generate.py |', 'INCLUDE: ./make-queue.sh |',
                                  'queue 1 from python rows.py |', 'include : "file.inc"|'])
def test_condor_dry_run_refuses_submit_files_that_run_commands_while_parsing(project, line):
    (project / 'job.sub').write_text('universe = vanilla\n' + line + '\nqueue 1\n')
    assert not allowed(project, 'condor_submit -dry-run /dev/null job.sub', cwd=project)['allowed']
    (project / 'job.sub').write_text('universe = vanilla\n# include : x |\nqueue 1\n')
    assert allowed(project, 'condor_submit -dry-run /dev/null job.sub', cwd=project)['allowed']


def test_condor_dry_run_refuses_an_oversized_submit_file(project):
    (project / 'job.sub').write_bytes(b'#' * (64 * 1024 + 1))
    assert not allowed(project, 'condor_submit -dry-run /dev/null job.sub', cwd=project)['allowed']
