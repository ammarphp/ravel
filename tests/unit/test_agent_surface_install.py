"""Installing RAVEL's agent surface into a foreign project keeps that project's rules."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ravel.workflow import agent_surface as surf
from ravel.workflow.agent_surface import LOCAL as LOCAL_SETTINGS
from ravel.paths import repository_root

GUARDRAILS = '# Submission rules\n\n- Never weaken these rules.\n- Run all code through the workflow manager.\n'
MANIFEST = {'schema_version': 1, 'groups': [
    {'id': 'present-tool', 'title': 'A present tool', 'version_contract': {'python': '3.12', 'git': 'any'},
     'readiness_commands': ['git --version']},
    {'id': 'absent-tool', 'title': 'An absent tool', 'version_contract': {'no-such-tool-xyz': '1.0'}, 'readiness_commands': []}]}


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'fork'
    root.mkdir()
    (root / 'AGENTS.md').write_text(GUARDRAILS)
    (root / '.claude').mkdir()
    (root / '.claude/settings.json').write_text(json.dumps({'hooks': {'PreToolUse': [{'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': 'their-guard'}]}]},
                                                          'permissions': {'deny': ['Bash(rm:*)']}}))
    return root


def install(project, tmp_path):
    manifest = tmp_path / 'toolchain.json'
    manifest.write_text(json.dumps(MANIFEST))
    return surf.install(project, skills_from=repository_root(), manifest=manifest)


def test_project_provider_default_install_check_and_deleted_default(project, tmp_path, capsys):
    from ravel.workflow import provider_policy as policy
    from ravel.workflow.state_io import atomic_json, read_json
    value = {'level': 'restricted', 'allowed_providers': [
        {'transport_id': 'claude-cli-worker', 'account_class': 'login:subscription'}]}
    atomic_json(project / policy.PROJECT_CONFIG, value)
    report = install(project, tmp_path)
    assert report['provider_policy']['data_classification'] == value
    assert read_json(project / policy.PROJECT_DECLARED) == policy.PROJECT_MARKER
    assert surf.check(project) == []
    assert surf.main(['check', '--project', str(project)]) == 0
    checked = json.loads(capsys.readouterr().out)
    assert checked['provider_policy']['data_classification'] == value
    assert checked['provider_policy']['project_defaults'][0]['sha256']
    # No run has yet existed: the installed project still remembers its default.
    (project / policy.PROJECT_CONFIG).unlink()
    assert surf.main(['check', '--project', str(project)]) == 1
    checked = json.loads(capsys.readouterr().out)
    assert checked['provider_policy'] is None
    assert any('provider policy' in e for e in checked['errors'])
    with pytest.raises(policy.PolicyRefused):
        policy.check(project / 'new', None, 'unknown')
    with pytest.raises(policy.PolicyRefused):
        install(project, tmp_path)


def test_agent_surface_check_reports_legacy_public_policy(project, tmp_path, capsys):
    from ravel.workflow import provider_policy as policy
    install(project, tmp_path)
    assert surf.main(['check', '--project', str(project)]) == 0
    checked = json.loads(capsys.readouterr().out)
    assert checked['provider_policy'] == {
        'data_classification': policy.PUBLIC, 'declared': False, 'project_defaults': []}
    assert not (project / policy.PROJECT_DECLARED).exists()


def test_project_reached_through_symlink_keeps_install_and_policy_report(project, tmp_path, capsys):
    from ravel.workflow import provider_policy as policy
    from ravel.workflow.state_io import atomic_json
    alias = tmp_path / 'alias'
    alias.symlink_to(project)
    # Installation through an alias and its policy report behave as at the real location.
    assert install(alias, tmp_path)['provider_policy']['declared'] is False
    assert surf.check(project) == []
    value = {'level': 'internal', 'allowed_providers': []}
    atomic_json(project / policy.PROJECT_CONFIG, value)
    assert install(alias, tmp_path)['provider_policy']['data_classification'] == value
    assert not any('provider policy' in e for e in surf.check(alias))
    surf.main(['check', '--project', str(alias)])
    assert json.loads(capsys.readouterr().out)['provider_policy']['data_classification'] == value


def test_install_preserves_guardrails_and_passes_check(project, tmp_path):
    report = install(project, tmp_path)
    agents = (project / 'AGENTS.md').read_text()
    assert agents == GUARDRAILS
    assert not (project / 'CLAUDE.md').exists()
    assert (project / surf.GUIDANCE).is_file()
    assert 'physicist-intake' in report['skills'] and not report['conflicts']
    assert surf.check(project) == []
    settings = json.loads((project / '.claude/settings.json').read_text())
    assert 'RAVEL_PYTHON' not in settings.get('env', {})
    assert json.loads((project / LOCAL_SETTINGS).read_text())['python'] == sys.executable
    assert settings['permissions'] == {'deny': ['Bash(rm:*)']}
    assert settings['hooks']['PreToolUse'][0]['hooks'][0]['command'] == 'their-guard'
    for event in ('UserPromptSubmit', 'Stop', 'SubagentStop'):
        assert any(surf.HOOK_MARK in h['command'] for g in settings['hooks'][event] for h in g['hooks'])


def test_check_agent_surface_project_mode_passes(project, tmp_path):
    install(project, tmp_path)
    done = subprocess.run([sys.executable, '-m', 'ravel.validation.check_agent_surface', '--project', str(project)],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert '[PASS] installed agent surface' in done.stdout


def test_reinstall_is_idempotent_and_keeps_one_hook_per_event(project, tmp_path):
    install(project, tmp_path)
    before = {p: p.read_bytes() for p in project.rglob('*') if p.is_file() and p.name != 'agent-surface.json'}
    report = install(project, tmp_path)
    after = {p: p.read_bytes() for p in project.rglob('*') if p.is_file() and p.name != 'agent-surface.json'}
    assert before == after and report['written'] == []
    settings = json.loads((project / '.claude/settings.json').read_text())
    assert len(settings['hooks']['Stop']) == 1


@pytest.mark.parametrize('env', [None, [], 'not-an-object', 3])
def test_install_refuses_invalid_settings_env_without_rewriting_settings(project, tmp_path, env):
    path = project / '.claude/settings.json'
    value = json.loads(path.read_text())
    value['env'] = env
    path.write_text(json.dumps(value))
    original = path.read_bytes()
    with pytest.raises(ValueError, match='env must be a JSON object'):
        install(project, tmp_path)
    assert path.read_bytes() == original


def test_existing_claude_md_and_foreign_skill_are_not_clobbered(project, tmp_path):
    (project / 'CLAUDE.md').write_text('# Project notes\n\nKeep the plots tidy.\n')
    foreign = project / '.claude/skills/run-stage/SKILL.md'
    foreign.parent.mkdir(parents=True)
    foreign.write_text('---\nname: run-stage\ndescription: the project own run-stage skill, which must never be replaced\n---\nmine\n')
    report = install(project, tmp_path)
    assert foreign.read_text().endswith('mine\n')
    assert '.claude/skills/run-stage/SKILL.md' in report['conflicts'] and 'run-stage' not in report['skills']
    claude = (project / 'CLAUDE.md').read_text()
    assert claude == '# Project notes\n\nKeep the plots tidy.\n'


def test_weakened_guardrails_or_removed_hook_fail_check(project, tmp_path):
    install(project, tmp_path)
    agents = project / 'AGENTS.md'
    agents.write_text(agents.read_text().replace('- Never weaken these rules.\n', ''))
    assert any('AGENTS.md project text changed' in e for e in surf.check(project))
    agents.write_text(GUARDRAILS + agents.read_text()[len(GUARDRAILS) - len('- Never weaken these rules.\n'):])
    settings = project / '.claude/settings.json'
    value = json.loads(settings.read_text())
    value['hooks'].pop('Stop')
    settings.write_text(json.dumps(value))
    assert any('Stop' in e for e in surf.check(project))


def test_software_skills_only_for_installed_tools(tmp_path):
    manifest = tmp_path / 'toolchain.json'
    manifest.write_text(json.dumps(MANIFEST))
    skills = surf.software_skills(manifest, packages=['numpy', 'definitely-not-installed-dist'], executables=[])
    assert 'software-numpy' in skills and 'software-definitely-not-installed-dist' not in skills
    assert 'software-present-tool' in skills and 'software-absent-tool' not in skills
    import numpy
    assert numpy.__version__ in skills['software-numpy']
    assert 'ravel agent-audit' not in skills['software-ravel'] or 'Focused commands' in skills['software-ravel']
    for name, text in skills.items():
        assert text.startswith(f'---\nname: {name}\ndescription: ')


def test_marked_section_helpers_replace_in_place():
    text = 'top\n'
    once = surf.upsert_section(text, 'x', 'one')
    twice = surf.upsert_section(once, 'x', 'two')
    assert twice.count('<!-- ravel:begin x -->') == 1 and 'two' in twice and 'one' not in twice
    assert surf.outside_sections(twice) == 'top'


def require_wms(project):
    folder = project / 'workflow'
    folder.mkdir(exist_ok=True)
    (folder / 'policy.json').write_text(json.dumps(
        {'schema_version': 1, 'wms_required': True, 'engine': 'snakemake'}))


def site_record(prefix, **changes):
    """The record shape the site installation writes under its prefix."""
    owned = prefix / '.ravel-site'
    owned.mkdir(parents=True)
    row = {'schema_version': 1, 'release': 'synthetic-release-a', 'version': '9.27.0',
           'shim': str(prefix / 'bin/ravel-snakemake'), 'snakemake': str(owned / 'site-wms/bin/snakemake')}
    row.update(changes)
    (owned / 'wms.json').write_text(json.dumps({k: v for k, v in row.items() if v is not None}))


@pytest.fixture
def no_site_prefix(monkeypatch):
    monkeypatch.delenv('RAVEL_SITE_PREFIX', raising=False)
    monkeypatch.delenv('RAVEL_NATIVE_BUILD', raising=False)


def test_site_record_generates_snakemake_without_path_or_distribution(project, tmp_path, monkeypatch, no_site_prefix):
    monkeypatch.setattr(surf, 'observe', lambda *a: {})
    site_record(project)
    report = install(project, tmp_path)
    assert 'software-snakemake' in report['software_skills']
    text = (project / '.claude/skills/software-snakemake/SKILL.md').read_text()
    for item in ('9.27.0', 'ravel-snakemake', 'ravel wms init', 'ravel wms add',
                 'ravel wms launch', 'ravel wms retry', 'ravel wms status', 'dry-run',
                 'never approve through the workflow manager'):
        assert item in text
    assert str(project) not in text and 'site-wms/bin' not in text


def test_site_record_under_declared_prefix_generates_snakemake(project, tmp_path, monkeypatch, no_site_prefix):
    monkeypatch.setattr(surf, 'observe', lambda *a: {})
    # The workflow manager is a declared runtime dependency, so an installed one may already have
    # its skill; before the site record none is declared by a site-wms record or carries its version.
    before = surf.software_skills(project=project).get('software-snakemake', '')
    assert '9.27.1' not in before and 'site-wms record' not in before
    prefix = tmp_path / 'prefix'
    site_record(prefix, version='9.27.1')
    monkeypatch.setenv('RAVEL_SITE_PREFIX', str(prefix))
    text = surf.software_skills(project=project)['software-snakemake']
    assert '9.27.1' in text and str(prefix) not in text


@pytest.mark.parametrize('changes', [{'version': None}, {'version': ' '}, {'schema_version': 2},
                                     {'schema_version': True}])
def test_malformed_site_record_is_refused(project, monkeypatch, no_site_prefix, changes):
    monkeypatch.setattr(surf, 'observe', lambda *a: {})
    site_record(project, **changes)
    with pytest.raises(ValueError, match='site-wms record'):
        surf.software_skills(project=project)


def test_manifest_declares_snakemake_without_current_environment(tmp_path, monkeypatch, no_site_prefix):
    monkeypatch.setattr(surf, 'observe', lambda *a: {})
    manifest = tmp_path / 'tools.json'
    manifest.write_text(json.dumps({'groups': [{'id': 'site-root-wms', 'title': 'Workflow manager',
        'version_contract': {'snakemake': '9.27.0'}}]}))
    assert '9.27.0' in surf.software_skills(manifest)['software-snakemake']


def test_required_policy_guidance_routes_only_through_wms(project, tmp_path):
    require_wms(project)
    install(project, tmp_path)
    text = (project / '.ravel/agent-guidance.md').read_text()
    assert 'ravel wms launch' in text
    assert 'ravel run' not in text
    assert 'plan' in text and 'approve' in text and 'check-ins' in text


def test_generated_portable_files_do_not_embed_machine_paths(project, tmp_path):
    install(project, tmp_path)
    files = [p for p in project.rglob('*') if p.is_file()
             and p.name not in {'agent-surface.local.json', 'settings.local.json', 'hook-runtime.sh'}]
    for path in files:
        text = path.read_text()
        assert sys.executable not in text, path
        assert str(Path.home()) not in text, path
        assert str(Path(surf.__file__).resolve().parents[2]) not in text, path


def test_instruction_documents_remain_byte_identical(project, tmp_path):
    (project / 'AGENTS.md').write_bytes(b'# Local rules\r\n\r\nKeep every byte.\r\n')
    (project / 'CLAUDE.md').write_bytes(b'# Local host rules\r\n')
    before = {name: (project / name).read_bytes() for name in ('AGENTS.md', 'CLAUDE.md')}
    install(project, tmp_path)
    assert before == {name: (project / name).read_bytes() for name in before}


def test_required_policy_installs_guard_by_default_and_checks_removal(project, tmp_path):
    require_wms(project)
    install(project, tmp_path)
    settings_path = project / '.claude/settings.json'
    settings = json.loads(settings_path.read_text())
    groups = settings['hooks']['PreToolUse']
    command = next(h['command'] for g in groups for h in g['hooks'] if surf.GUARD_MARK in h['command'])
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
    for spelling, code in [('ravel run --rundir ANA-0001', 2),
                           ('ravel wms launch --project . --task ANA-0001', 0)]:
        result = subprocess.run(['/bin/sh', '-c', command], env=env, text=True, capture_output=True,
            input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': spelling}}))
        assert result.returncode == code, result.stderr
    assert surf.check(project) == []
    for group in groups:
        group['hooks'] = [h for h in group['hooks'] if surf.GUARD_MARK not in h['command']]
    settings_path.write_text(json.dumps(settings))
    assert 'workflow-manager guard hook missing' in surf.check(project)


def test_guard_opt_out_requires_project_scoped_record_and_detects_drift(project, tmp_path):
    require_wms(project)
    with pytest.raises(ValueError, match='recorded'):
        surf.install(project, wms_guard=False)
    approval = tmp_path / 'approval.json'
    row = {'schema_version': 1, 'action': 'wms-guard-opt-out', 'approved': True,
           'project': str(project), 'approved_by': 'project owner', 'reason': 'Recorded discipline choice'}
    approval.write_text(json.dumps(row))
    surf.install(project, wms_guard=False, guard_approval=approval)
    assert surf.check(project) == []
    row['reason'] = 'Changed record'
    approval.write_text(json.dumps(row))
    assert 'workflow-manager guard opt-out approval changed' in surf.check(project)


def test_explicit_guard_without_policy_is_inert(project, tmp_path):
    surf.install(project, wms_guard=True)
    settings = json.loads((project / '.claude/settings.json').read_text())
    assert any(surf.GUARD_MARK in h['command'] for g in settings['hooks']['PreToolUse'] for h in g['hooks'])
    assert surf.guard_command(project, 'ravel run --rundir ANA-0001') is None


@pytest.mark.parametrize('recorded', [None, '', 7, 'elsewhere'])
def test_guard_opt_out_record_must_name_this_project(project, tmp_path, monkeypatch, recorded):
    require_wms(project)
    monkeypatch.chdir(project)
    approval = tmp_path / 'approval.json'
    row = {'schema_version': 1, 'action': 'wms-guard-opt-out', 'approved': True,
           'approved_by': 'project owner', 'reason': 'Recorded discipline choice'}
    if recorded is not None:
        row['project'] = str(tmp_path / recorded) if recorded == 'elsewhere' else recorded
    approval.write_text(json.dumps(row))
    with pytest.raises(ValueError, match='guard approval'):
        surf.install(project, wms_guard=False, guard_approval=approval)


def test_site_record_owner_reader_agrees(project, tmp_path, monkeypatch, no_site_prefix):
    """The record its owner validates is the record this guidance reads."""
    from ravel.workflow import site_contract
    monkeypatch.setattr(surf, 'observe', lambda *a: {})
    prefix = tmp_path / 'prefix'
    owned = prefix / '.ravel-site'
    owned.mkdir(parents=True)
    packages = {'snakemake': '9.27.0', 'packaging': '25.0', site_contract.PLUGIN: '1.0.9',
                site_contract.INTERFACE: '9.3.9'}
    lock = owned / 'requirements-site-wms.lock'
    lock.write_text(''.join(f'{name}=={version} \\\n    --hash=sha256:{"a" * 64}\n'
                            for name, version in packages.items()))
    row = {'schema_version': 1, 'release': 'synthetic-release-a', 'version': packages['snakemake'],
           'shim': str(prefix / 'bin/ravel-snakemake'), 'snakemake': str(owned / 'site-wms/bin/snakemake'),
           'analysis_python': str(owned / 'site-analysis/bin/python'), 'lock': str(lock),
           'lock_sha256': site_contract.sha256(lock), 'packages': packages,
           'plugins': {site_contract.PLUGIN: packages[site_contract.PLUGIN]}}
    (owned / 'wms.json').write_text(json.dumps(row))
    monkeypatch.setenv('RAVEL_SITE_PREFIX', str(prefix))
    version = site_contract.read_wms_record(prefix)['version']
    assert f'# Snakemake {version}\n' in surf.software_skills(project=project)['software-snakemake']
