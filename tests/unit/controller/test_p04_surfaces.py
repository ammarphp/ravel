"""Rendering role surfaces keeps a project's own instruction documents unless asked to replace them."""
from __future__ import annotations

from ravel.workflow import role_registry


def test_writing_the_role_surfaces_keeps_a_projects_own_instructions(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    own = 'The project\'s own instructions.\n'
    (project / 'AGENTS.md').write_text(own)
    rendered = role_registry.render('claude')
    stale = rendered['CLAUDE.md'].replace('Use the registered', 'Use the formerly registered')
    (project / 'CLAUDE.md').write_text(stale)   # RAVEL's own generated text, now stale
    assert role_registry.main(['--write', '--project', str(project)]) == 0
    assert (project / 'AGENTS.md').read_text() == own
    assert (project / 'CLAUDE.md').read_text() == rendered['CLAUDE.md']
    assert role_registry.project_instructions(project / 'AGENTS.md') is True
    assert role_registry.main(['--write', '--project', str(project), '--replace-instructions']) == 0
    assert (project / 'AGENTS.md').read_text() == rendered['AGENTS.md']
