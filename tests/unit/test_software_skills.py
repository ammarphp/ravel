"""Software skill files describe the installed software; they are deterministic and diff by version."""
import importlib
import json
import os
from pathlib import Path
import stat
import sys

import pytest

from ravel.workflow import agent_surface as surf, software_skills as skills

DIST = 'synthetic-histogrammer'


def write_distribution(root, version='1.2.0', licence='BSD-3-Clause'):
    """A synthetic installed distribution: metadata only, on a private path."""
    info = root / f'synthetic_histogrammer-{version}.dist-info'
    info.mkdir(parents=True, exist_ok=True)
    (info / 'METADATA').write_text(
        f'Metadata-Version: 2.1\nName: {DIST}\nVersion: {version}\nSummary: Fill synthetic histograms\n'
        f'License-Expression: {licence}\nProject-URL: Documentation, https://docs.example.org/synthetic\n'
        'Project-URL: Source, https://example.org/src\n')
    (info / 'entry_points.txt').write_text('[console_scripts]\nsynth-hist = synthetic_histogrammer.cli:main\n')
    (info / 'top_level.txt').write_text('synthetic_histogrammer\n')
    (root / 'synthetic_histogrammer').mkdir(exist_ok=True)
    (root / 'synthetic_histogrammer' / '__init__.py').write_text('')
    return info


@pytest.fixture
def site(tmp_path, monkeypatch):
    root = tmp_path / 'site'
    root.mkdir()
    write_distribution(root)
    monkeypatch.syspath_prepend(str(root))
    importlib.invalidate_caches()
    skills._import_names.cache_clear()
    yield root
    skills._import_names.cache_clear()


def build(**options):
    return skills.build(None, packages=[DIST], executables=[], probe=False, **options)


def test_a_skill_carries_purpose_version_entry_points_commands_and_licence(site):
    text = build()['software-synthetic-histogrammer']['SKILL.md']
    assert text.startswith('---\nname: software-synthetic-histogrammer\ndescription: ')
    for line in ('Version: 1.2.0', 'Import names: `synthetic_histogrammer`',
                 'Entry points: `synth-hist = synthetic_histogrammer.cli:main`', 'Licence: BSD-3-Clause',
                 'Upstream documentation: https://docs.example.org/synthetic',
                 'Purpose in this project: RAVEL runtime dependency. Upstream summary: Fill synthetic histograms',
                 'Commands the workflow reaches it through:'):
        assert line in text, line
    assert str(site) not in text and sys.executable not in text  # nothing machine-specific


def test_missing_metadata_is_stated_not_invented(site):
    info = write_distribution(site, '1.2.0')
    (info / 'METADATA').write_text(f'Metadata-Version: 2.1\nName: {DIST}\nVersion: 1.2.0\n')
    text = build()['software-synthetic-histogrammer']['SKILL.md']
    assert f'Licence: {skills.UNDECLARED}' in text and f'Upstream documentation: {skills.UNDECLARED}' in text


def test_regeneration_is_byte_identical_and_a_version_change_is_only_that_diff(site, tmp_path):
    first = skills.generate(tmp_path, packages=[DIST], executables=[], probe=False)
    assert first == skills.generate(tmp_path, packages=[DIST], executables=[], probe=False)
    path = '.claude/skills/software-synthetic-histogrammer/SKILL.md'
    assert path in first and first[path] == first[path.replace('.claude', '.agents')]
    import shutil
    shutil.rmtree(next(site.glob('*.dist-info')))
    write_distribution(site, '1.3.0')
    importlib.invalidate_caches()
    second = skills.generate(tmp_path, packages=[DIST], executables=[], probe=False)
    changed = {p for p in first if first[p] != second[p]}
    assert changed == {path, path.replace('.claude', '.agents')}
    before, after = first[path].splitlines(), second[path].splitlines()
    assert len(before) == len(after)
    assert [(a, b) for a, b in zip(before, after) if a != b] == [('Version: 1.2.0', 'Version: 1.3.0')]


def test_tools_that_are_not_installed_have_no_skill(site):
    built = skills.build(None, packages=[DIST, 'no-such-distribution-xyz'], executables=['no-such-exe-xyz'], probe=False)
    assert 'software-synthetic-histogrammer' in built and 'software-no-such-distribution-xyz' not in built
    assert 'software-no-such-exe-xyz' not in built and 'software-ravel' in built
    assert skills.covered(DIST, None) is False  # not named by the surface or the project policy
    assert skills.covered('no-such-exe-xyz') is False


def test_a_project_policy_can_declare_more_software_and_covered_follows(site, tmp_path):
    (tmp_path / 'workflow').mkdir()
    (tmp_path / 'workflow/policy.json').write_text(json.dumps({'software': {'python_packages': [DIST]}}))
    assert skills.covered(DIST, tmp_path) and skills.covered('ravel')
    assert 'software-synthetic-histogrammer' in skills.build(None, project=tmp_path, executables=[], probe=False)


def test_native_executables_are_described_without_a_path_and_with_a_probed_version(tmp_path, monkeypatch):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    fake = bin_dir / 'snakemake'
    fake.write_text('#!/bin/sh\necho "9.9.9"\n')
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv('PATH', f'{bin_dir}:/usr/bin:/bin')
    built = skills.build(None, packages=[], executables=['snakemake'], probe=True)
    text = built['software-snakemake']['SKILL.md']
    assert 'Version: 9.9.9' in text and 'Kind: native executable' in text and str(bin_dir) not in text
    assert '`snakemake -n`' in text and 'workflow manager' in text
    assert skills.covered('snakemake') and not skills.covered('snakemake-nonexistent')


def test_ravel_skill_lists_the_dependency_tree_from_installed_metadata(site):
    parts = skills.build(None, packages=[], executables=[], probe=False)['software-ravel']
    assert set(parts) == {'SKILL.md', 'dependencies.md'}
    assert 'Version: ' in parts['SKILL.md'] and 'dependencies.md' in parts['SKILL.md']
    table = parts['dependencies.md']
    assert table.startswith('# RAVEL runtime dependencies') and '| Distribution | Version | Licence |' in table
    names = skills.runtime_dependencies()
    assert 'numpy' in names and names == sorted(names)
    assert any(line.startswith('| numpy | ') for line in table.splitlines())


def test_install_writes_the_real_skills_and_check_passes(site, tmp_path, monkeypatch):
    from ravel.paths import repository_root
    monkeypatch.setattr(skills, 'candidates', lambda project=None, packages=None, executables=None: ([DIST], []))
    fork = tmp_path / 'fork'
    fork.mkdir()
    report = surf.install(fork, skills_from=repository_root())
    assert 'software-synthetic-histogrammer' in report['software_skills']
    for base in ('.claude/skills', '.agents/skills'):
        assert (fork / base / 'software-synthetic-histogrammer/SKILL.md').is_file()
        assert (fork / base / 'software-ravel/dependencies.md').is_file()
    assert surf.check(fork) == []
    # A version change regenerates the file through the installer, which owns it.
    import shutil
    shutil.rmtree(next(site.glob('*.dist-info')))
    write_distribution(site, '2.0.0')
    importlib.invalidate_caches()
    again = surf.install(fork, skills_from=repository_root())
    assert '.claude/skills/software-synthetic-histogrammer/SKILL.md' in again['written']
    assert 'Version: 2.0.0' in (fork / '.claude/skills/software-synthetic-histogrammer/SKILL.md').read_text()
    assert surf.check(fork) == []
