"""Installing RAVEL's agent surface into a foreign project keeps that project's rules."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ravel.workflow import agent_surface as surf
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


def test_install_preserves_guardrails_and_passes_check(project, tmp_path):
    report = install(project, tmp_path)
    agents = (project / 'AGENTS.md').read_text()
    assert agents.startswith(GUARDRAILS) and '<!-- ravel:begin agent-surface -->' in agents
    claude = (project / 'CLAUDE.md').read_text()
    assert surf._first_instruction(claude) == '@AGENTS.md'
    assert 'physicist-intake' in report['skills'] and not report['conflicts']
    assert surf.check(project) == []
    settings = json.loads((project / '.claude/settings.json').read_text())
    assert settings['env']['RAVEL_PYTHON'] == sys.executable
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
    assert 'Keep the plots tidy.' in claude and surf._first_instruction(claude) == '@AGENTS.md'


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
