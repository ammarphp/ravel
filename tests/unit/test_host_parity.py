"""Synthetic host events, generated configurations and inert native executables."""
import json
import os
from pathlib import Path
import subprocess
import shlex
import sys

import pytest

from ravel.workflow import host_guards, host_hooks, native_shims, role_registry

HOSTS = ('claude', 'codex', 'gemini', 'opencode', 'antigravity')
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.delenv('RAVEL_PROTECTED_CARD_ROOT', raising=False)
    for key in ('CLAUDE_PROJECT_DIR', 'CLAUDE_CODE_SESSION_ID', 'RAVEL_SESSION_ID', 'CLAUDECODE'):
        monkeypatch.delenv(key, raising=False)


def event(host, path=None, command=None):
    shell = {'gemini': 'run_shell_command', 'opencode': 'bash'}.get(host, 'Bash')
    write = {'gemini': 'write_file', 'opencode': 'write'}.get(host, 'Write')
    return {'tool_name': shell if command is not None else write,
            'tool_input': {'command': command} if command is not None else {'file_path': str(path)}}


@pytest.mark.parametrize('host', HOSTS)
def test_every_adapter_refuses_unapproved_generation(host, tmp_path):
    for command in ('mg5_aMC cards.dat', 'DelphesHepMC config input output', 'snakemake --cores 1'):
        assert host_guards.check(event(host, command=command), host, tmp_path)
    assert host_guards.check(event(host, path=tmp_path / 'notes.md'), host, tmp_path) == []


@pytest.mark.parametrize('host', HOSTS)
def test_every_adapter_requires_deviation_record(host, tmp_path):
    path = tmp_path / 'run/inputs/task_contract.json'
    path.parent.mkdir(parents=True)
    path.write_text('{}')
    assert host_guards.check(event(host, path=path), host, tmp_path) == []
    assert host_guards.check(event(host, path=path), host, tmp_path, phase='post')
    (path.parent.parent / 'DEVIATIONS.md').write_text('task_contract.json: synthetic edit and reason')
    assert host_guards.check(event(host, path=path), host, tmp_path, phase='post') == []


def test_projections_reproduce_in_clean_destination(tmp_path):
    for host in role_registry.SURFACES:
        for name, body in role_registry.render(host).items():
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
    assert role_registry.check_rendered(tmp_path) == []
    for host in HOSTS:
        name, body = role_registry.gate_shim(host)
        assert (tmp_path / name).read_text() == body
    assert json.loads((tmp_path / '.codex/hooks.json').read_text())['hooks']['PreToolUse']
    assert json.loads((tmp_path / '.gemini/settings.json').read_text())['hooks']['BeforeTool']
    assert 'tool.execute.before' in (tmp_path / '.opencode/plugins/ravel-guards.js').read_text()


def test_native_shims_refuse_then_exec_only_with_real_approval(tmp_path):
    from test_site_tool_admission import approve, call
    project = tmp_path / 'project'; project.mkdir()
    real_bin = tmp_path / 'real'; real_bin.mkdir()
    from ravel.workflow import agent_surface
    report = agent_surface.install(project, skills_from=REPO, include_software=False)
    assert not report['conflicts']
    assert agent_surface.check(project) == []
    activation = subprocess.run(['/bin/sh', '-c', '. "$1/.ravel/activate.sh"; command -v mg5_aMC',
                                 'sh', str(project)], text=True, capture_output=True)
    assert activation.stdout.strip() == str(project / '.ravel/bin/mg5_aMC')
    env = dict(os.environ, PATH=str(project / '.ravel/bin') + os.pathsep + str(real_bin) + os.pathsep + os.environ['PATH'])
    for name in native_shims.executables():
        real = real_bin / name
        real.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\nexit 7\n'); real.chmod(0o755)
        denied = subprocess.run([name, 'argument with spaces', 'literal;$x'], cwd=project, env=env, capture_output=True, text=True)
        assert denied.returncode == 2 and 'BLOCKED' in denied.stderr
        # This deliberately demonstrates the documented PATH boundary.
        bypass = subprocess.run([str(real), 'absolute'], cwd=project, env=env, capture_output=True, text=True)
        assert bypass.returncode == 7 and bypass.stdout == 'absolute\n'
    rd = approve(project, call())
    for name in native_shims.executables():
        allowed = subprocess.run([name, 'argument with spaces', 'literal;$x'], cwd=rd, env=env, capture_output=True, text=True)
        assert allowed.returncode == 7, allowed.stdout + allowed.stderr
        assert allowed.stdout == 'argument with spaces\nliteral;$x\n'
    # Byte-bound approval is checked again on every invocation.
    (rd / 'inputs/task_contract.json').write_text('{}')
    denied = subprocess.run(['mg5_aMC'], cwd=rd, env=env, capture_output=True, text=True)
    assert denied.returncode == 2


def test_native_guard_is_fail_closed_on_verifier_failure(tmp_path, monkeypatch):
    from ravel.workflow import host_gate
    monkeypatch.setattr(host_gate, '_approval_errors', lambda *args: ['unavailable'])
    assert native_shims.admit(tmp_path, 'mg5_aMC', rundir=tmp_path) == ['unavailable']


def test_host_report_never_attests_configuration_as_execution():
    rows = host_hooks.enforcement_levels()
    assert set(rows) == set(HOSTS)
    for row in rows.values():
        assert row['runtime_verified'] is False
        assert row['ravel_guards'] and row['prompt_only']
    assert rows['gemini']['version'] is None and rows['opencode']['version'] is None


@pytest.mark.parametrize('host', ('codex', 'gemini'))
def test_generated_command_hooks_deny_before_fake_tool_execution(host, tmp_path):
    from ravel.workflow import agent_surface
    agent_surface.install(tmp_path, skills_from=REPO, include_software=False)
    config = json.loads(next(iter(host_hooks.render(host).values())))
    event_name = 'PreToolUse' if host == 'codex' else 'BeforeTool'
    command = config['hooks'][event_name][0]['hooks'][0]['command']
    data = event(host, command='mg5_aMC cards.dat')
    done = subprocess.run(['/bin/sh', '-c', command], input=json.dumps(data), cwd=tmp_path,
                          text=True, capture_output=True)
    assert done.returncode == 2 and 'BLOCKED' in done.stderr


def test_write_gate_deviations_are_separate_from_protected_paths(tmp_path):
    path = tmp_path / 'run/inputs/task_contract.json'; path.parent.mkdir(parents=True); path.write_text('{}')
    argv = [sys.executable, '-m', 'ravel', 'gate', '--project', str(tmp_path), '--action',
            'deviation_check', '--path', str(path), '--json']
    denied = subprocess.run(argv, text=True, capture_output=True)
    assert denied.returncode == 2
    (path.parent.parent / 'DEVIATIONS.md').write_text('task_contract.json: synthetic change and reason')
    allowed = subprocess.run(argv, text=True, capture_output=True)
    assert allowed.returncode == 0


def test_check_cli_reports_all_enforcement_levels(tmp_path):
    from ravel.workflow import agent_surface
    agent_surface.install(tmp_path, skills_from=REPO, include_software=False)
    done = subprocess.run([sys.executable, '-m', 'ravel', 'agent-surface', 'check', '--project', str(tmp_path)],
                          text=True, capture_output=True)
    assert done.returncode == 0, done.stdout + done.stderr
    report = json.loads(done.stdout)
    assert report['passed'] and set(report['enforcement']) == set(HOSTS)
    assert report['enforcement']['antigravity']['enforcement_level'] == 'explicit-gate-and-path-shims'
    assert report['enforcement']['codex']['runtime_verified'] is False


@pytest.mark.parametrize('host', HOSTS)
def test_every_adapter_protects_enforcement(host, tmp_path):
    (tmp_path / 'logs').mkdir()
    (tmp_path / 'logs/.route-pending-shared').touch()
    data = event(host, path=tmp_path / '.opencode/ravel-gate.sh')
    data['session_id'] = 'shared'
    assert host_guards.check(data, host, tmp_path)


@pytest.mark.parametrize('host', ('codex', 'gemini'))
def test_command_hook_import_failure_is_a_blocking_exit(host, tmp_path):
    missing = tmp_path / 'missing-runtime'; missing.write_text('#!/bin/sh\nexit 1\n'); missing.chmod(0o755)
    done = subprocess.run(['/bin/sh', '-c', host_hooks.command(host, 'pre')], cwd=tmp_path,
                          input='{}', text=True, capture_output=True,
                          env={**os.environ, 'RAVEL_PYTHON': str(missing)})
    assert done.returncode == 2 and 'BLOCKED' in done.stderr


@pytest.mark.parametrize('host', ('codex', 'gemini'))
def test_prompt_routing_failure_never_blocks_the_prompt(host, tmp_path):
    # The prompt router is advisory on every host; the hard blocks live in the tool guards.
    missing = tmp_path / 'missing-runtime'; missing.write_text('#!/bin/sh\nexit 1\n'); missing.chmod(0o755)
    done = subprocess.run(['/bin/sh', '-c', host_hooks.command(host, 'prompt')], cwd=tmp_path,
                          input='{"prompt": "x"}', text=True, capture_output=True,
                          env={**os.environ, 'RAVEL_PYTHON': str(missing)})
    assert done.returncode == 0 and 'unavailable' in done.stderr


def test_prompt_route_record_is_best_effort_and_contract_is_validated(tmp_path, monkeypatch, capsys):
    from ravel.workflow import active_run, route_prompt, workflow_state
    prompt = {'prompt': 'Reproduce the 95% CLs limit for a 200 GeV top partner', 'session_id': 's1', 'cwd': str(tmp_path)}
    monkeypatch.setattr(active_run, 'resolve', lambda *args: tmp_path)

    def broken(args):
        print('stdout noise')
        raise OSError('ledger unavailable')
    monkeypatch.setattr(workflow_state, 'cmd_record', broken)
    assert host_guards.check(prompt, 'codex', tmp_path, phase='prompt') == []
    out = capsys.readouterr().out
    assert json.loads(out)['hookSpecificOutput']['additionalContext'].startswith('ROUTING (G1)')
    (tmp_path / 'logs/.route-pending-s1').unlink()
    monkeypatch.setattr(route_prompt, 'validate', lambda contract: ['invalid'])
    with pytest.raises(ValueError):
        host_guards.check(prompt, 'codex', tmp_path, phase='prompt')
    assert capsys.readouterr().out == '' and not (tmp_path / 'logs/.route-pending-s1').exists()


def test_installed_claude_hook_uses_the_claude_project_dir(tmp_path):
    from ravel.workflow import agent_surface
    outer = tmp_path / 'outer'; project = outer / 'project'; project.mkdir(parents=True)
    subprocess.run(['git', 'init', '-q', str(outer)], check=True)
    agent_surface.install(project, skills_from=REPO, include_software=False)
    fake = tmp_path / 'fakebin'; fake.mkdir()
    (fake / 'python3').write_text('#!/bin/sh\nexit 1\n'); (fake / 'python3').chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in ('RAVEL_PYTHON', 'PYTHONPATH')}
    env.update(PATH=str(fake) + os.pathsep + env['PATH'], CLAUDE_PROJECT_DIR=str(project))
    settings = json.loads((project / '.claude/settings.json').read_text())
    command = next(h['command'] for g in settings['hooks']['PreToolUse'] for h in g['hooks']
                   if 'ravel.workflow.host_guards' in h['command'])
    done = subprocess.run(['/bin/sh', '-c', command], cwd=project, env=env, text=True, capture_output=True,
                          input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 'ls'}}))
    assert done.returncode == 0, done.stderr


def test_reinstall_refreshes_host_guard_hooks_and_check_requires_them(tmp_path):
    from ravel.workflow import agent_surface
    agent_surface.install(tmp_path, skills_from=REPO, include_software=False)
    path = tmp_path / '.claude/settings.json'
    settings = json.loads(path.read_text())
    for event in ('PreToolUse', 'PostToolUse'):
        for group in settings['hooks'][event]:
            for hook in group['hooks']:
                if 'ravel.workflow.host_guards' in hook['command']:
                    hook['command'] = 'python3 -m ravel.workflow.host_guards --stale'
    path.write_text(json.dumps(settings))
    agent_surface.install(tmp_path, skills_from=REPO, include_software=False)
    commands = [h['command'] for event in ('PreToolUse', 'PostToolUse') for g in json.loads(path.read_text())['hooks'][event]
                for h in g['hooks'] if 'ravel.workflow.host_guards' in h['command']]
    assert len(commands) == 2 and not any('--stale' in c for c in commands)
    settings = json.loads(path.read_text())
    settings['hooks']['PostToolUse'] = [g for g in settings['hooks']['PostToolUse']
                                        if not any('ravel.workflow.host_guards' in h['command'] for h in g['hooks'])]
    path.write_text(json.dumps(settings))
    assert any('host guard hook missing for PostToolUse' in e for e in agent_surface.check(tmp_path))


@pytest.mark.parametrize('host', ('claude', 'codex', 'gemini'))
@pytest.mark.parametrize('nested', (False, True))
@pytest.mark.parametrize('phase', ('pre', 'post', 'prompt'))
def test_command_hooks_find_nearest_project_runtime(host, nested, phase, tmp_path):
    from ravel.workflow import agent_surface
    outer = tmp_path / 'outer'
    outer.mkdir()
    subprocess.run(['git', 'init', '-q', str(outer)], check=True)
    project = outer / 'project with spaces' if nested else outer
    project.mkdir(exist_ok=True)
    if nested:
        (outer / '.claude').mkdir()
        (outer / '.claude/settings.json').write_text('{}')
    agent_surface.install(project, skills_from=REPO, include_software=False)
    child = project / 'work'
    child.mkdir()
    fake = tmp_path / 'fakebin'
    fake.mkdir()
    (fake / 'python3').write_text('#!/bin/sh\nexit 1\n')
    (fake / 'python3').chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in ('RAVEL_PYTHON', 'PYTHONPATH', 'CLAUDE_PROJECT_DIR')}
    env['PATH'] = str(fake) + os.pathsep + env['PATH']
    # Every phase must bootstrap through the nested runtime, including advisory prompts.
    runtime = project / '.ravel/hook-runtime.sh'
    runtime.write_text(runtime.read_text() + 'export RAVEL_RESOLVED_PROJECT="$RAVEL_PROJECT_DIR"\n')
    witness = project / 'runtime-witness'
    witness.write_text('#!/bin/sh\nprintf "%s\\n" "$RAVEL_RESOLVED_PROJECT"\n')
    witness.chmod(0o755)
    runtime.write_text(runtime.read_text() + 'export RAVEL_PYTHON=' + shlex.quote(str(witness)) + '\n')
    done = subprocess.run(['/bin/sh', '-c', host_hooks.command(host, phase)], cwd=child, env=env,
                          input=json.dumps(event(host, command='ls')), text=True, capture_output=True)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == str(project)


@pytest.mark.parametrize('host', ('claude', 'codex', 'gemini'))
@pytest.mark.parametrize('git', (False, True))
def test_command_hook_project_fallback(host, git, tmp_path):
    if git:
        subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    child = tmp_path / 'child'
    child.mkdir()
    witness = tmp_path / 'runtime-witness'
    witness.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    witness.chmod(0o755)
    done = subprocess.run(['/bin/sh', '-c', host_hooks.command(host, 'pre')], cwd=child,
                          env={**os.environ, 'RAVEL_PYTHON': str(witness)}, input='{}', text=True, capture_output=True)
    assert done.returncode == 0, done.stderr
    args = done.stdout.splitlines()
    assert args[args.index('--project') + 1] == str(tmp_path if git else child)


@pytest.mark.parametrize('host', ('claude', 'codex', 'gemini'))
def test_installed_public_hook_allows_cards_outside_checkout(host, tmp_path):
    from ravel.workflow import agent_surface
    project = tmp_path / 'checkout'
    project.mkdir()
    subprocess.run(['git', 'init', '-q', str(project)], check=True)
    agent_surface.install(project, skills_from=REPO, include_software=False)
    data = event(host, path=tmp_path / 'param_card_alpha.dat')
    done = subprocess.run(['/bin/sh', '-c', host_hooks.command(host, 'pre')], cwd=project,
                          input=json.dumps(data), text=True, capture_output=True)
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize('nested', (False, True))
def test_plugin_finds_nearest_project_runtime(nested, tmp_path):
    import shutil
    node = shutil.which('node')
    if node is None:
        pytest.skip('host JavaScript runtime unavailable')
    outer = tmp_path / 'outer'
    outer.mkdir()
    subprocess.run(['git', 'init', '-q', str(outer)], check=True)
    project = outer / 'project with spaces' if nested else outer
    if nested:
        (outer / '.claude').mkdir()
        (outer / '.claude/settings.json').write_text('{}')
    (project / '.claude').mkdir(parents=True)
    (project / '.claude/settings.json').write_text('{}')
    (project / '.ravel').mkdir()
    capture = tmp_path / 'args'
    witness = tmp_path / 'runtime-witness'
    witness.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > ' + shlex.quote(str(capture)) + '\n')
    witness.chmod(0o755)
    (project / '.ravel/agent-surface.local.json').write_text(json.dumps({'python': str(witness)}))
    child = project / 'work'
    child.mkdir()
    plugin = tmp_path / 'guards.mjs'
    plugin.write_text(next(iter(host_hooks.render('opencode').values())))
    runner = tmp_path / 'runner.mjs'
    runner.write_text("import { RavelGuards } from './guards.mjs';\n"
                      + 'const hooks = await RavelGuards({directory: ' + json.dumps(str(child)) + '});\n'
                      + "await hooks['tool.execute.before']({tool: 'write'}, {args: {}});\n")
    env = {k: v for k, v in os.environ.items() if k != 'RAVEL_PYTHON'}
    done = subprocess.run([node, str(runner)], env=env, text=True, capture_output=True)
    assert done.returncode == 0, done.stderr
    args = capture.read_text().splitlines()
    assert args[args.index('--project') + 1] == str(project)
