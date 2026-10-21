"""Check copied-file custody, package selections and observed component metadata."""
from email.message import Message
from fnmatch import fnmatchcase
from importlib import util
from pathlib import Path
import re
import subprocess
import sys
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/maintenance/render_component_inventory.py'
spec = util.spec_from_file_location('component_inventory', SCRIPT)
inventory = util.module_from_spec(spec)
spec.loader.exec_module(inventory)


def expand_braces(pattern):
    match = re.search(r'\{([^{}]+)\}', pattern)
    if match:
        for part in match.group(1).split(','):
            yield from expand_braces(pattern[:match.start()] + part + pattern[match.end():])
    else:
        yield pattern


def table_paths(root, text):
    """Require explicit existing paths/globs in both file columns of every row."""
    rows = []
    in_table = False
    for line in text.splitlines():
        if line.startswith('| Copied material |'):
            in_table = True
            continue
        if not in_table or not line.startswith('|') or line.startswith('|---'):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        assert len(cells) == 5, 'malformed copied-material row'
        selected = []
        for column in (cells[3], cells[4]):
            patterns = re.findall(r'`([^`]+)`', column)
            assert patterns, 'explicit file paths required in each file column'
            paths = set()
            for pattern in patterns:
                assert not Path(pattern).is_absolute() and '..' not in Path(pattern).parts
                for expanded in expand_braces(pattern):
                    matches = {p for p in root.glob(expanded + '/*' if expanded.endswith('/**') else expanded) if p.is_file()}
                    assert matches, 'missing copied-material path: ' + expanded
                    paths.update(matches)
            selected.append(paths)
        rows.append(tuple(selected))
    assert rows, 'copied-material table required'
    return rows


def package_selected(path, selections, exclusions=()):
    def matches(pattern):
        return path == pattern or path.startswith(pattern.rstrip('/') + '/') or fnmatchcase(path, pattern)
    return any(matches(p) for p in selections) and not any(matches(p) for p in exclusions)


def test_copied_material_paths_and_package_coverage():
    rows = table_paths(ROOT, (ROOT / 'THIRD-PARTY-NOTICES.md').read_text())
    config = tomllib.loads((ROOT / 'pyproject.toml').read_text())
    targets = config['tool']['hatch']['build']['targets']
    wheel, sdist = targets['wheel'], targets['sdist']
    named = set().union(*(files | notices for files, notices in rows))
    for path in (ROOT / 'src/ravel').rglob('*'):
        if path.is_file() and path.name.startswith(('LICENSE', 'COPYING', 'NOTICE', 'AUTHORS', 'ATTRIBUTION')):
            assert path in named, 'unlisted licence/notice: ' + str(path)
    for files, notices in rows:
        for path in files | notices:
            relative = path.relative_to(ROOT).as_posix()
            if relative.startswith('src/ravel/'):
                assert package_selected(relative, wheel['packages'], wheel.get('exclude', [])), relative
    assert 'THIRD-PARTY-NOTICES.md' in config['project']['license-files']
    assert 'THIRD-PARTY-NOTICES.md' in sdist['include']


def test_row_parser_refuses_missing_paths(tmp_path):
    (tmp_path / 'COPYING').write_text('fixture terms')
    text = ('| Copied material | Licence | Copyright | Files | Licence text |\n'
            '|---|---|---|---|---|\n'
            '| fixture | unknown | fixture | `absent/*` | `COPYING` |\n')
    with pytest.raises(AssertionError, match='missing copied-material path'):
        table_paths(tmp_path, text)
    (tmp_path / 'absent').mkdir()
    (tmp_path / 'absent/payload').write_text('fixture')
    assert table_paths(tmp_path, text)
    (tmp_path / 'COPYING').unlink()
    with pytest.raises(AssertionError, match='missing copied-material path'):
        table_paths(tmp_path, text)


def test_metadata_priority_and_missing_distribution(monkeypatch):
    record = Message()
    assert inventory.declared_license(record) == 'unknown'
    record['Classifier'] = 'License :: Example'
    record['Classifier'] = 'Topic :: Example'
    assert inventory.declared_license(record) == 'License :: Example'
    record['License'] = 'first line\nlong remaining text'
    assert inventory.declared_license(record) == 'first line'
    record['License-Expression'] = 'Example-1.0'
    assert inventory.declared_license(record) == 'Example-1.0'
    def missing(name):
        raise inventory.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(inventory.metadata, 'distribution', missing)
    assert inventory.distribution_record('fixture-tool==1.0') == ('metadata not installed', 'metadata not installed')


def test_generated_inventory_is_current_and_complete(tmp_path):
    output = tmp_path / 'component-inventory.md'
    command = [sys.executable, str(SCRIPT), '--output', str(output)]
    subprocess.run(command, check=True)
    generated = output.read_text()
    # Preserve full regeneration evidence in a failed test's captured log.
    checked = subprocess.run([sys.executable, str(SCRIPT), '--check'], capture_output=True, text=True)
    if checked.returncode:
        print('GENERATOR INTERPRETER:', sys.executable, sys.version)
        print('BEGIN REGENERATED COMPONENT INVENTORY\n' + generated + 'END REGENERATED COMPONENT INVENTORY')
    assert checked.returncode == 0, checked.stderr
    assert generated == (ROOT / inventory.OUTPUT).read_text()
    for line in (ROOT / 'requirements-full.txt').read_text().splitlines():
        requirement = line.split('#', 1)[0].strip()
        if requirement and requirement != '.':
            assert '| ' + inventory.cell(requirement) + ' |' in generated
    assert subprocess.run(command + ['--check'], capture_output=True).returncode == 0
    output.write_text(generated + '\nstale\n')
    assert subprocess.run(command + ['--check'], capture_output=True).returncode == 1
    output.unlink()
    assert subprocess.run(command + ['--check'], capture_output=True).returncode == 1


def test_native_groups_and_boundaries_are_declared():
    sys.path.insert(0, str(ROOT / 'src'))
    from ravel.setup import manifest as toolchain
    generated = inventory.render()
    merged = toolchain.view(ROOT)
    held = toolchain.unreleased_groups(merged)
    rows = generated.splitlines()
    for group in merged['groups']:
        released = [line for line in rows if line.startswith('| ' + group['id'] + ' |')]
        if group['id'] in held:
            assert released == [], 'a withheld group has an inventory row: ' + group['id']
            continue
        for entry in group.get('licenses', []):
            assert inventory.cell(entry['spdx']) in released[0]
    assert inventory.installation_boundary({'steps': [{'kind': 'conda_env', 'name': 'fixture'}]}) == 'own environment: {ENVS}/fixture'
    assert inventory.installation_boundary({'steps': [{'kind': 'pip', 'python': '{ENVS}/fixture/bin/python'}]}) == 'pip interpreter: {ENVS}/fixture/bin/python'
    assert inventory.installation_boundary({'steps': []}) == 'no install steps'


def test_built_artifacts_carry_inventory_and_retained_licences(tmp_path):
    import tarfile
    import zipfile
    built = subprocess.run([sys.executable, '-m', 'hatchling', 'build', '-t', 'wheel', '-t', 'sdist',
                            '-d', str(tmp_path)], cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert built.returncode == 0, built.stdout + built.stderr
    with zipfile.ZipFile(next(tmp_path.glob('*.whl'))) as archive:
        wheel = set(archive.namelist())
        notices = [p for p in wheel if p.endswith('.dist-info/licenses/THIRD-PARTY-NOTICES.md')]
        assert len(notices) == 1
        assert archive.read(notices[0]) == (ROOT / 'THIRD-PARTY-NOTICES.md').read_bytes()
    with tarfile.open(next(tmp_path.glob('*.tar.gz'))) as archive:
        members = archive.getnames()
        prefix = members[0].split('/')[0] + '/'
        sdist = {p[len(prefix):] for p in members if p.startswith(prefix)}
        assert 'THIRD-PARTY-NOTICES.md' in sdist
        # A separately licensed add-on is not part of the package: none of its files travel in the sdist.
        assert not any(p.startswith('addons/') for p in sdist), sorted(p for p in sdist if p.startswith('addons/'))
    rows = table_paths(ROOT, (ROOT / 'THIRD-PARTY-NOTICES.md').read_text())
    def selected(path):
        relative = path.relative_to(ROOT).as_posix()
        return relative in sdist or (relative.startswith('src/') and relative[4:] in wheel)
    for files, licences in rows:
        if any(selected(path) for path in files):
            for path in licences:
                assert selected(path), 'retained licence absent from artifacts: ' + path.relative_to(ROOT).as_posix()
