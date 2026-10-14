"""Released-wheel census and dependency-closure runtime admission for eft-toolchain.

Synthetic site trees exercise the closure rules without importing scientific
packages. One optional test runs a real flavio prediction through the ordinary
plan/approve/run lifecycle when the pinned releases are installed.
"""
import copy
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys

import pytest

from ravel.physics import eft_toolchain as adapter, eft_toolchain_core as core

ROOT = Path(__file__).resolve().parents[2]


def pin(p):
    return {'path': str(p), 'sha256': hashlib.sha256(Path(p).read_bytes()).hexdigest()}


def save(p, value):
    p.write_text(json.dumps(value))
    return pin(p)


def dist(site, name, version, files, requires=()):
    """Write a minimal installed distribution with an exact RECORD."""
    info = site / f'{name}-{version}.dist-info'
    info.mkdir(parents=True)
    meta = [f'Metadata-Version: 2.1', f'Name: {name}', f'Version: {version}']
    meta += [f'Requires-Dist: {r}' for r in requires]
    (info / 'METADATA').write_text('\n'.join(meta) + '\n')
    rows = []
    for rel, text in files.items():
        p = site / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        rows.append(f'{rel},sha256=x,{len(text)}')
    rows += [f'{info.name}/METADATA,,', f'{info.name}/RECORD,,']
    (info / 'RECORD').write_text('\n'.join(rows) + '\n')
    return info


def synthetic_site(tmp):
    site = tmp / 'site'
    dist(site, 'wilson', '9.1', {'wilson/__init__.py': '# wilson', 'wilson/data/table.json': '{}'},
         requires=['numpy>=1', 'nose; extra == "testing"', 'colorama; sys_platform == "win32"'])
    dist(site, 'numpy', '1.0', {'numpy/__init__.py': '# numpy', 'numpy/core/x.py': '# x'})
    dist(site, 'unrelated', '2.0', {'unrelated/__init__.py': '# never admitted'})
    return site


def test_declared_release_pins_match_the_shipped_api_census():
    api = json.loads(adapter.API.read_text())
    assert api['schema_version'] == 2
    pins = {}
    for path in (ROOT / 'pyproject.toml', ROOT / 'requirements-full.txt'):
        for name, version in re.findall(r'"?\b(wilson|flavio|smelli)==([0-9][0-9A-Za-z.]*)', path.read_text()):
            assert pins.setdefault(name, version) == version, path
    assert set(api['releases']) == set(api['required_package_files']) == {'wilson', 'flavio', 'smelli'}
    assert api['releases'] == pins


def test_shipped_census_equals_installed_released_wheels():
    api = json.loads(adapter.API.read_text())
    for name, version in api['releases'].items():
        try:
            installed = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            pytest.skip(name + ' is not installed in this environment')
        if installed.version != version:
            pytest.skip(name + ' installed version differs from the reviewed release')
        site = Path(installed.locate_file(''))
        for rel, sha in api['required_package_files'][name].items():
            p = site / name / rel
            assert p.is_file(), p
            assert hashlib.sha256(p.read_bytes()).hexdigest() == sha, p


def test_dependency_closure_reads_metadata_only_and_skips_extras_and_inactive_markers(tmp_path):
    site = synthetic_site(tmp_path)
    files, versions = adapter.runtime_census([site], ['wilson'])
    names = {p.relative_to(site).parts[0] for p in files}
    assert names == {'wilson', 'numpy', 'wilson-9.1.dist-info', 'numpy-1.0.dist-info'}
    assert versions == {'wilson': '9.1', 'numpy': '1.0'}


def test_missing_unconditional_dependency_refuses(tmp_path):
    site = tmp_path / 'site'
    dist(site, 'wilson', '9.1', {'wilson/__init__.py': '#'}, requires=['scipy'])
    with pytest.raises(ValueError, match='scipy'):
        adapter.runtime_census([site], ['wilson'])


def test_recorded_file_absent_from_disk_refuses(tmp_path):
    site = synthetic_site(tmp_path)
    (site / 'numpy/core/x.py').unlink()
    with pytest.raises(ValueError, match='recorded'):
        adapter.runtime_census([site], ['wilson'])


def admitted(tmp_path, monkeypatch):
    site = synthetic_site(tmp_path)
    api = tmp_path / 'api.json'
    save(api, {'schema_version': 2, 'releases': {'wilson': '9.1'},
               'required_package_files': {'wilson': {'__init__.py': pin(site / 'wilson/__init__.py')['sha256']}}})
    monkeypatch.setattr(adapter, 'API', api)
    runtime = adapter.runtime_block(Path(sys.executable).resolve(), [site], ['wilson'])
    from test_eft_toolchain import cfg, POINT
    c = cfg()
    c['runtime'] = runtime
    c['observables'] = []
    c['wcxf'] = save(tmp_path / 'point.json', POINT)
    proof = tmp_path / 'proof'
    proof.write_text('synthetic')
    c['conventions']['evidence'] = [pin(proof)]
    save(tmp_path / 'config.json', c)
    return {'config': str(tmp_path / 'config.json')}, c, site


def test_generated_runtime_block_is_admitted_and_excludes_unrelated_packages(tmp_path, monkeypatch):
    task, c, site = admitted(tmp_path, monkeypatch)
    assert c['runtime']['versions'] == {'wilson': '9.1', 'numpy': '1.0'}
    paths = {Path(a['path']) for a in c['runtime']['assets']}
    assert site / 'unrelated/__init__.py' not in paths
    files = adapter.inputs(task, tmp_path)
    assert site / 'numpy/core/x.py' in files
    (site / 'unrelated/extra.py').write_text('# unrelated packages do not change admission')
    adapter.inputs(task, tmp_path)


@pytest.mark.parametrize('change', ['package_extra', 'dependency_extra', 'release', 'declared_version'])
def test_closure_drift_and_release_mismatch_refuse(tmp_path, monkeypatch, change):
    task, c, site = admitted(tmp_path, monkeypatch)
    if change == 'package_extra':
        (site / 'wilson/planted.py').write_text('# unrecorded')
    elif change == 'dependency_extra':
        (site / 'numpy/planted.py').write_text('# unrecorded')
    elif change == 'release':
        api = json.loads(adapter.API.read_text())
        api['releases']['wilson'] = '9.0'
        save(adapter.API, api)
    else:
        c['runtime']['versions']['numpy'] = '0.9'
        save(tmp_path / 'config.json', c)
    with pytest.raises(ValueError):
        adapter.inputs(task, tmp_path)


def test_worker_ending_census_covers_admitted_package_trees_only(tmp_path):
    from ravel.physics import eft_toolchain_worker as worker
    site = synthetic_site(tmp_path)
    files, _ = adapter.runtime_census([site], ['wilson'])
    request = {'sites': [str(site)], 'runtime_assets': {str(p): pin(p)['sha256'] for p in files}}
    assert worker.census(request) == set(request['runtime_assets'])
    (site / 'unrelated/later.py').write_text('#')
    assert worker.census(request) == set(request['runtime_assets'])
    cache = site / 'wilson/__pycache__'
    cache.mkdir()
    (cache / 'x.cpython-312.pyc').write_bytes(b'ignored cache; the worker uses an empty pycache prefix')
    assert worker.census(request) == set(request['runtime_assets'])
    (site / 'numpy/new.py').write_text('#')
    assert worker.census(request) != set(request['runtime_assets'])


def installed_site():
    try:
        versions = {n: importlib.metadata.version(n) for n in ('wilson', 'flavio')}
    except importlib.metadata.PackageNotFoundError:
        return None
    api = json.loads(adapter.API.read_text())
    if any(api.get('releases', {}).get(n) != v for n, v in versions.items()):
        return None
    return Path(importlib.metadata.distribution('flavio').locate_file('')).resolve()


@pytest.mark.skipif(installed_site() is None or os.environ.get('RAVEL_TEST_REAL_TOOLCHAIN') != '1',
                    reason='set RAVEL_TEST_REAL_TOOLCHAIN=1 with the pinned wilson/flavio releases installed (about 5 minutes)')
def test_real_flavio_angular_observable_shift_through_ordinary_lifecycle(tmp_path):
    from ravel.workflow import science
    site = installed_site()
    work = tmp_path / 'request'
    work.mkdir()
    runtime = adapter.runtime_block(Path(sys.executable).resolve(), [site], ['wilson', 'flavio'])
    point = save(work / 'point.json', {'eft': 'WET', 'basis': 'flavio', 'scale': 4.8, 'values': {'C9_bsmumu': -1.0}})
    note = work / 'conventions.txt'
    note.write_text('flavio WET basis; C9_bsmumu is the new-physics shift at the b-quark scale.\n')
    config = {'schema_version': 1, 'source': 'Exercise of the pinned flavio release for a one-coefficient shift.',
              'runtime': runtime, 'wcxf': point,
              'conventions': {'input_kind': 'new_physics', 'scale_unit': 'GeV', 'coefficient_normalization': 'native_wcxf_basis',
                              'flavour_assumptions': 'Only C9_bsmumu is nonzero.',
                              'truncation': 'upstream_native_no_additional_linearization',
                              'domain': 'Fixed point at the b-quark scale.', 'evidence': [pin(note)]},
              'wilson_options': {'smeft_accuracy': 'integrate', 'qed_order': 1, 'qcd_order': 1, 'smeft_matching_order': 0,
                                 'smeft_matchingscale': 91.1876, 'mb_matchingscale': 4.2, 'mc_matchingscale': 1.3, 'parameters': {}},
              'targets': [],
              'observables': [{'id': 'P5p_4_6', 'name': "<P5p>(B0->K*mumu)", 'arguments': {'q2min': 4.0, 'q2max': 6.0},
                               'unit': '1', 'coefficient_source': 'input'}],
              'parameter_overrides': {}, 'smelli': None, 'max_seconds': 600, 'max_ram_mib': 4096,
              'max_export_bytes': 16 * 1024 * 1024}
    save(work / 'config.json', config)
    scope = core.SCOPE
    policy = {'schema_version': 1, 'policy': {'schema_version': 1,
              'actors': {'proposer': 'p', 'executor': 'e', 'physics_critic': 'c', 'skeptical_verifier': 'v', 'physics_decider': 'd'},
              'max_redos': 0, 'allowed_changed_paths': [], 'allowed_stages': ['science'],
              'required_checks': [{'id': 'integrity', 'kind': 'integrity'}, {'id': 'population', 'kind': 'scientific'}],
              'claim_scopes': {scope: {'checks': ['integrity', 'population'], 'actions': ['delivery']}}},
              'correction_contract': {'task_fields': [], 'input_slots': []}}
    spec = {'schema_version': 2, 'mode': 'eft-toolchain', 'source': config['source'],
            'assumptions': ['Central flavio parameters; no theory uncertainty is computed.'],
            'max_seconds': 900, 'approval_mode': 'scripted_yes', 'max_attempts': 1,
            'task': {'config': 'config.json'}, 'review_policy': policy}
    save(work / 'science.json', spec)
    rd = tmp_path / 'study'
    science.plan(rd, work / 'science.json')
    science.approve(rd, 'Scripted authorization of this synthetic engineering check.', scripted=True)
    assert science.run(rd) == 0
    results = list(rd.rglob('eft-toolchain.json'))
    assert len(results) == 1
    result = json.loads(results[0].read_text())
    assert result['status'] == 'passed', result['errors']
    row = result['delivery']['result']['completed_quantities']['predictions'][0]
    assert -0.9 < row['sm'] < -0.6 and row['difference'] > 0.1


def test_site_startup_files_bring_their_distribution_into_the_closure(tmp_path):
    site = synthetic_site(tmp_path)
    dist(site, 'hooks', '1.0', {'hooks.pth': 'import hooks_impl\n', 'hooks_impl/__init__.py': '#'})
    files, versions = adapter.runtime_census([site], ['wilson'])
    assert versions['hooks'] == '1.0' and site / 'hooks_impl/__init__.py' in files and site / 'hooks.pth' in files
