"""Execution-guard switches and code identity in controller mode (G10, G14, SW23, SW27, SW29)."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from test_p05_support import own


def strict_project(tmp_path):
    project = tmp_path / 'project'
    (project / 'workflow').mkdir(parents=True)
    (project / 'workflow' / 'policy.json').write_text(json.dumps(
        {'schema_version': 1, 'wms_required': True, 'engine': 'snakemake', 'execution_guard': 'strict'}))
    return project


@pytest.mark.parametrize('command', ['git status $HOME', 'snakemake -n $TARGET', 'ls $1', 'cat $@', 'echo $?',
                                     'ls ${HOME}', 'ls $(pwd)', 'ls `pwd`', 'ls > out', 'ls; rm -rf x &'])
def test_G10_hidden_expansion_redirection_and_substitution_refuse(tmp_path, command):
    from ravel.workflow import execution_guard
    decision = execution_guard.decide(command, strict_project(tmp_path))
    assert decision['mode'] == 'strict' and decision['allowed'] is False, decision


def test_a_trailing_anchor_and_plain_inspection_stay_allowed(tmp_path):
    from ravel.workflow import execution_guard
    project = strict_project(tmp_path)
    for command in ('ls -la', 'grep -n foo$ README'):
        assert execution_guard.decide(command, project)['allowed'] is True, command
    with pytest.raises(execution_guard.Unparsable, match='parameter expansion'):
        execution_guard.statements('ls $HOME')


def test_SW27_controller_uses_installed_rules_despite_project_policy(tmp_path, monkeypatch):
    from ravel.workflow import execution_guard
    project = tmp_path / 'project'
    run = project / 'trial-runs' / 'run'
    run.mkdir(parents=True)
    (project / 'workflow').mkdir()
    # A committed or working relaxation of the project policy cannot loosen a controller run.
    (project / 'workflow' / 'policy.json').write_text(json.dumps(
        {'schema_version': 1, 'wms_required': False, 'engine': 'snakemake'}))
    assert execution_guard.decide('bash -c "anything"', project, cwd=run)['allowed'] is True
    skill = project / '.claude' / 'skills' / 'software-git' / 'SKILL.md'
    skill.parent.mkdir(parents=True)
    skill.write_text('---\nname: software-git\n---\n')
    own(monkeypatch, tmp_path / 'store', {run: 'run-guard'})
    refused = execution_guard.decide('bash -c "anything"', project, cwd=run)
    assert refused['mode'] == 'strict' and refused['allowed'] is False
    for command in ('git add .', 'git commit -m relax', 'git -C . commit -m x'):
        decision = execution_guard.decide(command, project, cwd=run)
        assert decision['allowed'] is False, command
    assert execution_guard.decide('git commit -m x', project, cwd=run)['rule'] == 'git-write'
    assert execution_guard.decide('git status', project, cwd=run)['allowed'] is True


def test_G14_guard_decisions_are_recorded_in_the_store(tmp_path, monkeypatch):
    from ravel.workflow import execution_guard
    run = tmp_path / 'run'
    run.mkdir()
    stores = own(monkeypatch, tmp_path / 'store', {run: 'run-log'})
    result = execution_guard.decide('ls $HOME', run, cwd=run)
    row = execution_guard.record(run, 'ls $HOME', result, 'session-1')
    stored = [r['record'] for r in stores['run-log'].scan('execution-guard-decision')]
    assert stored == [row] and row['decision'] == 'refused'
    # Editing the local log does not change what the store recorded.
    log = execution_guard.log_path(run)
    log.write_text(json.dumps({**row, 'decision': 'allowed'}) + '\n')
    assert [r['record']['decision'] for r in stores['run-log'].scan('execution-guard-decision')] == ['refused']


def test_G14_hook_records_a_decision_found_through_the_working_directory(tmp_path, monkeypatch):
    from ravel.workflow import execution_guard
    project = tmp_path / 'project'
    run = project / 'trial-runs' / 'run'
    run.mkdir(parents=True)
    stores = own(monkeypatch, tmp_path / 'store', {run: 'run-hook'})
    event = {'tool_name': 'Bash', 'tool_input': {'command': 'git commit -m x'}, 'cwd': str(run),
             'session_id': 'session-2'}
    allowed, _ = execution_guard.hook(json.dumps(event), project)
    assert allowed is False
    stored = [r['record'] for r in stores['run-hook'].scan('execution-guard-decision')]
    assert [(r['decision'], r['rule'], r['session_id']) for r in stored] == [('refused', 'git-write', 'session-2')]


def test_a_checkout_or_editable_install_is_refused_in_controller_mode_unless_development(monkeypatch):
    from ravel.controller.confine import NOT_GOVERNED, UngovernedInstall, code_identity, require_governed_install
    identity = code_identity(digest=False)
    checkout = {**identity, 'kind': 'checkout', 'selectors': {}}
    # The refusal names the real remedy; no controller entry accepts a development switch.
    with pytest.raises(UngovernedInstall, match='ravel governed-runtime seal') as refused:
        require_governed_install(identity=checkout)
    assert '--development' not in str(refused.value) and refused.value.fix == 'ravel governed-runtime seal'
    labelled = require_governed_install(identity=checkout, development=True)
    assert labelled['governed'] is False and labelled['label'] == NOT_GOVERNED
    editable = {**identity, 'kind': 'editable', 'selectors': {}}
    with pytest.raises(UngovernedInstall):
        require_governed_install(identity=editable)
    installed = {**identity, 'kind': 'installed', 'selectors': {}, 'writable_by_controller_user': False, 'symlinks': []}
    assert require_governed_install(identity=installed)['governed'] is True
    redirected = {**installed, 'selectors': {'RAVEL_ROOT': '/elsewhere'}}
    with pytest.raises(UngovernedInstall, match='RAVEL_ROOT'):
        require_governed_install(identity=redirected)


def test_SW23_SW29_writable_install_requires_development():
    from ravel.controller.confine import require_governed_install, UngovernedInstall
    identity = {'package_dir': '/opt/runtime/ravel', 'kind': 'installed', 'selectors': {},
                'writable_by_controller_user': True, 'symlinks': []}
    with pytest.raises(UngovernedInstall, match='writable'):
        require_governed_install(identity=identity)
    labelled = require_governed_install(identity=identity, development=True)
    assert labelled['label'] == 'NOT GOVERNED' and labelled['governed'] is False
    identity['writable_by_controller_user'] = False
    assert require_governed_install(identity=identity)['governed'] is True
    identity['symlinks'] = ['policy.json']
    with pytest.raises(UngovernedInstall, match='symbolic links'):
        require_governed_install(identity=identity)


def test_code_identity_describes_the_running_code(tmp_path, monkeypatch):
    from ravel.controller.confine import code_identity
    import ravel
    monkeypatch.setenv('RAVEL_NATIVE_BIN', str(tmp_path))
    identity = code_identity()
    assert identity['package_dir'] == str(Path(ravel.__file__).resolve().parent)
    assert identity['kind'] in ('installed', 'editable', 'checkout', 'unpackaged')
    assert identity['selectors']['RAVEL_NATIVE_BIN'] == str(tmp_path)
    assert identity['digest'].split(':')[0] in ('record', 'tree') and len(identity['digest'].split(':')[1]) == 64
    if 'site-packages' not in identity['package_dir']:
        assert identity['kind'] != 'installed', 'code outside an installation is never called installed'


def test_a_sandbox_profile_quotes_non_ascii_and_quoted_paths_for_its_language():
    from ravel.workflow import sandbox
    assert sandbox.quote('/a/données') == '"/a/données"'
    assert sandbox.quote('/a/b"c') == '"/a/b\\"c"' and sandbox.quote('/x\\y') == '"/x\\\\y"'
    with pytest.raises(ValueError):
        sandbox.quote('/a\nb')


def test_worker_write_roots_can_narrow_but_never_widen_the_workspace(tmp_path):
    from ravel.workflow import sandbox
    ws = (tmp_path / 'worker').resolve()
    for name in ('inputs', 'outputs', 'scratch'):
        (ws / name).mkdir(parents=True)
    default = sandbox.macos_profile(ws, read_paths=['/usr'])
    assert default == sandbox.macos_profile(ws, read_paths=['/usr'], writable=[ws / 'outputs', ws / 'scratch'])
    narrowed = sandbox.macos_profile(ws, read_paths=['/usr'], writable=[ws / 'outputs'])
    assert '(allow file-write* (subpath ' + sandbox.quote(str(ws / 'scratch')) + '))' not in narrowed
    for wider in (ws, ws / 'inputs', tmp_path, ws / 'inputs' / 'x', ws / 'calls', ws / 'receipts'):
        with pytest.raises(sandbox.ReadRootRefused):
            sandbox.macos_profile(ws, writable=[wider])
        with pytest.raises(sandbox.ReadRootRefused):
            sandbox.linux_command(ws, ['/usr/bin/true'], read_paths=['/usr'], writable=[wider])
    command = sandbox.linux_command(ws, ['/usr/bin/true'], read_paths=['/usr'], writable=[ws / 'outputs'])
    binds = [command[i + 1] for i, part in enumerate(command) if part == '--bind']
    assert binds == [str(ws / 'outputs')]
