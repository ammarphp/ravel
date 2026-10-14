"""Declared add-on path resolution (GPL programs live outside the Apache package)."""
import hashlib
import json
from pathlib import Path

import pytest

from ravel import addons

REPO = Path(__file__).resolve().parents[2]


def _addon(root, name='demo-addon', files=None, license='GPL-3.0-or-later'):
    directory = root / name
    directory.mkdir(parents=True)
    files = files or {'bridge.f90': b'program demo\nend program\n'}
    for member, raw in files.items():
        (directory / member).write_bytes(raw)
    manifest = {'schema_version': 1, 'name': name, 'license': license, 'summary': 'demo',
                'files': {m: hashlib.sha256(raw).hexdigest() for m, raw in files.items()}}
    (directory / 'addon.json').write_text(json.dumps(manifest))
    return directory


def test_environment_path_takes_precedence(tmp_path):
    first = _addon(tmp_path / 'first')
    _addon(tmp_path / 'second')
    found = addons.resolve('demo-addon', env={'RAVEL_ADDON_PATH': f'{tmp_path / "first"}:{tmp_path / "second"}'},
                           include_defaults=False)
    assert found.root == first.resolve()
    assert found.path('bridge.f90').read_bytes().startswith(b'program')
    assert found.license == 'GPL-3.0-or-later'


def test_native_build_root_is_searched(tmp_path):
    directory = _addon(tmp_path / 'native' / 'addons')
    found = addons.resolve('demo-addon', env={'RAVEL_NATIVE_BUILD': str(tmp_path / 'native')}, include_defaults=False)
    assert found.root == directory.resolve()


def test_missing_addon_names_the_installer(tmp_path):
    with pytest.raises(addons.AddonNotFound) as error:
        addons.resolve('demo-addon', env={'RAVEL_ADDON_PATH': str(tmp_path)}, include_defaults=False)
    assert 'installer' in str(error.value) and 'RAVEL_ADDON_PATH' in str(error.value)


def test_changed_member_is_refused(tmp_path):
    directory = _addon(tmp_path)
    (directory / 'bridge.f90').write_bytes(b'tampered\n')
    with pytest.raises(ValueError, match='sha256'):
        addons.resolve('demo-addon', env={'RAVEL_ADDON_PATH': str(tmp_path)}, include_defaults=False)


def test_undeclared_member_cannot_be_requested(tmp_path):
    _addon(tmp_path)
    found = addons.resolve('demo-addon', env={'RAVEL_ADDON_PATH': str(tmp_path)}, include_defaults=False)
    with pytest.raises(KeyError):
        found.path('other.f90')


def test_manifest_name_must_match_directory(tmp_path):
    directory = _addon(tmp_path)
    manifest = json.loads((directory / 'addon.json').read_text())
    manifest['name'] = 'other'
    (directory / 'addon.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='name'):
        addons.resolve('demo-addon', env={'RAVEL_ADDON_PATH': str(tmp_path)}, include_defaults=False)


def test_symlinked_member_is_refused(tmp_path):
    directory = _addon(tmp_path)
    (directory / 'bridge.f90').unlink()
    target = tmp_path / 'elsewhere.f90'
    target.write_bytes(b'program demo\nend program\n')
    (directory / 'bridge.f90').symlink_to(target)
    with pytest.raises(ValueError, match='symlink'):
        addons.resolve('demo-addon', env={'RAVEL_ADDON_PATH': str(tmp_path)}, include_defaults=False)


def test_checkout_holds_the_mcfm_overlay_outside_the_package():
    found = addons.resolve('mcfm-amplitudes', env={}, include_defaults=True)
    assert found.root == (REPO / 'addons/gpl/mcfm-amplitudes').resolve()
    assert found.license == 'GPL-3.0-or-later'
    for member in ('ravel_bridge.f90', 'ravel_driver.f90', 'lowint-capture.patch', 'CMakeLists-ravel.cmake',
                   'upstream-api.json'):
        assert found.path(member).is_file()
    assert not (REPO / 'src/ravel/data/four_lepton_mcfm').exists()
    for license_file in ('LICENSE', 'COPYING.GPL-3.txt', 'README.md'):
        assert (found.root / license_file).is_file()


def test_no_gpl_source_ships_in_the_python_package():
    package = REPO / 'src/ravel'
    offenders = [p.relative_to(REPO).as_posix() for p in package.rglob('*')
                 if p.is_file() and p.suffix in ('.py', '.f90', '.cxx', '.cc', '.cmake', '.patch')
                 and 'SPDX-License-Identifier: GPL' in p.read_text(errors='ignore')]
    assert offenders == []


def test_source_distribution_leaves_add_ons_out():
    import tomllib
    config = tomllib.loads((REPO / 'pyproject.toml').read_text())
    builds = config['tool']['hatch']['build']['targets']
    assert not any(entry.startswith('addons') for entry in builds['sdist']['include'])
    assert builds['wheel']['packages'] == ['src/ravel']
