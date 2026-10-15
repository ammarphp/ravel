"""Offline source binding, isolated environments and synthetic readiness controls."""
import copy
import json
from pathlib import Path

import pytest

from ravel.setup import manifest as mf

ROOT = Path(__file__).resolve().parents[2]


def test_restricted_environment_command_is_refused():
    doc = mf.view(ROOT)
    doc['groups'].append({'id': 'fictional-tool', 'title': 'Fictional tool', 'depends_on': ['python-host'],
                         'size_gb': 0.1, 'minutes': 1,
                         'licenses': [{'component': 'fictional-tool', 'spdx': 'GPL-3.0-only'}],
                         'steps': [{'id': 'environment', 'kind': 'command',
                                    'argv': ['{HOST_PYTHON}', '-m', 'venv', '{REPO}/.venv'],
                                    'outputs': ['{REPO}/.venv/bin/python']}],
                         'checks': [{'id': 'fictional-ready', 'kind': 'file', 'path': '{P}/fictional'}]})
    with pytest.raises(mf.ManifestError, match='gpl_isolation'):
        mf.validate(doc)


@pytest.mark.parametrize('missing', ['sha256', 'licence'])
def test_source_binding_missing_evidence_refused(tmp_path, missing):
    from ravel.setup.pin_sources import resolve
    setup = tmp_path / 'native/setup'
    setup.mkdir(parents=True)
    row = {'tool': 'fictional-tool', 'kind': 'archive', 'url': 'https://example.invalid/source.tar.gz',
           'version': '1.0', 'status': 'filled', 'sha256': 'a' * 64, 'size': 123,
           'licence_file': 'COPYING', 'licence_text_sha256': 'b' * 64,
           'fetched_utc': '2026-01-01T00:00:00Z',
           'licence': {'spdx': 'GPL-3.0-only', 'evidence_status': 'verified',
                       'redistribute': False, 'import_into_ravel': 'never', 'container_publish': 'never'}}
    row.pop(missing)
    (setup / 'fictional-pins.json').write_text(json.dumps({'schema_version': 1, 'tools': {'source': row}}))
    doc = {'groups': [{'id': 'fictional-tool', 'pin_file': 'native/setup/fictional-pins.json',
                      'licenses': [{'component': 'fictional-tool', 'tool_key': 'source', 'spdx': 'GPL-3.0-only'}],
                      'steps': [{'id': 'source', 'kind': 'archive', 'pin': 'source', 'dest': '{TOOLS}/fictional'}]}]}
    with pytest.raises(mf.ManifestError):
        resolve(doc, tmp_path)


def test_scanner_recipe_disables_fetching():
    text = (ROOT / 'native/setup/recipes/build-scanners.sh').read_text()
    assert '-DFETCHCONTENT_FULLY_DISCONNECTED=ON' in text
    assert '-DFETCHCONTENT_UPDATES_DISCONNECTED=ON' in text
    assert '-DHiggsTools_ROOT="$HIGGSTOOLS"' in text
    assert '-DCMAKE_PREFIX_PATH="$HIGGSTOOLS;$ENV"' in text


def test_scanner_generated_command_uses_existing_prefix(tmp_path):
    import os
    import subprocess
    import sys
    env = tmp_path / 'env'
    (env / 'conda-meta').mkdir(parents=True)
    (env / 'bin').mkdir()
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'CMakeLists.txt').write_text('')
    prefix = tmp_path / 'dependency'
    (prefix / 'lib/cmake').mkdir(parents=True)
    log = tmp_path / 'commands.jsonl'
    out = tmp_path / 'out'
    fake = env / 'bin/cmake'
    fake.write_text('#!' + sys.executable + '\n' + '''import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['SYNTHETIC_COMMAND_LOG'], 'a') as f:
    f.write(json.dumps(args) + '\\n')
if '-S' in args:
    target = next(a.split('=', 1)[1] for a in args if a.startswith('-DCMAKE_INSTALL_PREFIX='))
    pathlib.Path(os.environ['SYNTHETIC_PREFIX_FILE']).write_text(target)
if '--install' in args:
    target = pathlib.Path(os.environ['SYNTHETIC_PREFIX_FILE']).read_text()
    (pathlib.Path(target) / 'bin').mkdir(parents=True)
''')
    fake.chmod(0o755)
    result = subprocess.run(['/bin/bash', str(ROOT / 'native/setup/recipes/build-scanners.sh'),
                             '--src', str(source), '--env', str(env), '--higgstools', str(prefix),
                             '--out', str(out)], capture_output=True, text=True,
                            env=dict(os.environ, SYNTHETIC_COMMAND_LOG=str(log),
                                     SYNTHETIC_PREFIX_FILE=str(tmp_path / 'prefix-file')))
    assert result.returncode == 0, result.stderr
    command = json.loads(log.read_text().splitlines()[0])
    assert '-DFETCHCONTENT_FULLY_DISCONNECTED=ON' in command
    assert '-DFETCHCONTENT_UPDATES_DISCONNECTED=ON' in command
    assert '-DHiggsTools_ROOT=' + str(prefix) in command
    assert '-DCMAKE_PREFIX_PATH=' + str(prefix) + ';' + str(env) in command


def test_archive_without_sha_or_licence_fails_validator():
    base = mf.view(ROOT)
    group = {'id': 'fictional-tool', 'title': 'Fictional tool', 'depends_on': [],
             'size_gb': .1, 'minutes': 1,
             'licenses': [{'component': 'fictional-tool', 'spdx': 'MIT'}],
             'steps': [{'id': 'source', 'kind': 'archive', 'url': 'https://example.invalid/source.tar.gz',
                        'dest': '{TOOLS}/fictional', 'sha256': 'a' * 64}],
             'checks': [{'id': 'fictional-ready', 'kind': 'file', 'path': '{TOOLS}/fictional/file'}]}
    for missing in ['sha256', 'licenses']:
        doc = copy.deepcopy(base)
        row = copy.deepcopy(group)
        if missing == 'sha256':
            row['steps'][0].pop(missing)
        else:
            row.pop(missing)
        doc['groups'].append(row)
        with pytest.raises(mf.ManifestError):
            mf.validate(doc)


def positioned_group_view(document, order):
    """Preserve the original split's identity assertion while admitting new held groups."""
    doc = copy.deepcopy(document)
    additions = {g['id'] for g in doc['groups']} - set(order)
    doc['groups'] = [g for g in doc['groups'] if g['id'] not in additions]
    held = doc.get('unreleased', {})
    held['groups'] = [r for r in held.get('groups', []) if r['id'] not in additions]
    held['operations'] = [r for r in held.get('operations', []) if not set(r['groups']) <= additions]
    return doc


def test_complete_source_ledger_resolves_archive_and_image(tmp_path):
    from ravel.setup.pin_sources import resolve
    setup = tmp_path / 'native/setup'
    setup.mkdir(parents=True)
    licence = {'spdx': 'GPL-3.0-only', 'evidence_status': 'verified', 'redistribute': False,
               'import_into_ravel': 'never', 'container_publish': 'never'}
    row = {'tool': 'fictional-tool', 'kind': 'archive', 'url': 'https://example.invalid/source.tar.gz',
           'version': '1.0', 'status': 'filled', 'sha256': 'a' * 64, 'size': 123,
           'licence_file': 'COPYING', 'licence_text_sha256': 'b' * 64,
           'fetched_utc': '2026-01-01T00:00:00Z', 'licence': licence}
    image = dict(row, kind='image', url='example.invalid/fictional-image', digest='sha256:' + 'c' * 64)
    (setup / 'fictional-pins.json').write_text(json.dumps({'schema_version': 1, 'tools': {
        'source': row, 'image': image}}))
    doc = {'groups': [{'id': 'fictional-tool', 'pin_file': 'native/setup/fictional-pins.json',
                      'licenses': [{'component': 'fictional-tool', 'tool_key': 'source',
                                    'spdx': 'GPL-3.0-only'}],
                      'steps': [{'id': 'source', 'kind': 'archive', 'pin': 'source', 'dest': '{TOOLS}/fictional'}],
                      'checks': [{'id': 'fictional-image', 'kind': 'file', 'path': '{P}/receipt',
                                  'name': 'fictional', 'image_pin': 'image'},
                                 {'id': 'fictional-version', 'kind': 'executable', 'path': '{P}/fictional',
                                  'version_pin': 'source',
                                  'probe': {'argv': ['{path}', '--version'], 'regex': r'(\S+)'}}]}]}
    group = resolve(doc, tmp_path)['groups'][0]
    assert group['steps'][0]['sha256'] == 'a' * 64
    assert group['steps'][0]['size'] == 123
    assert group['checks'][0]['kind'] == 'container_image'
    assert group['checks'][0]['digest'] == 'sha256:' + 'c' * 64
    assert group['checks'][1]['probe']['expect'] == '1.0'
    from ravel.setup.doctor import Doctor
    manifest, catalog = mf.load(ROOT)
    doctor = Doctor(tmp_path, tmp_path / 'prefix', 'macos-arm64', manifest, catalog,
                    environ={'PATH': '/nonexistent'}, which=lambda name: None,
                    run_probe=lambda argv, **kwargs: (0, ''))
    assert doctor.evaluate_check(group, group['checks'][0])['status'] == 'ready'
    doctor.run_probe = lambda argv, **kwargs: (1, '')
    missing = doctor.evaluate_check(group, group['checks'][0])
    assert missing['status'] == 'missing' and missing['fix']
    executable = tmp_path / 'prefix/fictional'
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text('#!/bin/sh\nexit 0\n')
    executable.chmod(0o755)
    doctor.run_probe = lambda argv, **kwargs: (0, '2.0')
    assert doctor.evaluate_check(group, group['checks'][1])['status'] == 'version_mismatch'
    doctor.run_probe = lambda argv, **kwargs: (0, '1.0')
    assert doctor.evaluate_check(group, group['checks'][1])['status'] == 'ready'


def test_pending_sources_cannot_hide_host_environment_violation(tmp_path):
    from ravel.setup.pin_sources import resolve
    group = {'id': 'fictional-tool', 'pin_file': 'native/setup/fictional-pins.json',
             'licenses': [{'component': 'fictional-tool', 'spdx': 'GPL-3.0-only', 'tool_key': 'source'}],
             'steps': [{'id': 'source', 'kind': 'archive', 'pin': 'source', 'dest': '{TOOLS}/fictional'},
                       {'id': 'install', 'kind': 'pip', 'python': '{HOST_PYTHON}',
                        'requirements': ['fictional-tool==1.0']}]}
    with pytest.raises(mf.ManifestError, match='gpl_isolation'):
        resolve({'groups': [group]}, tmp_path)


@pytest.mark.xfail(reason='awaits image-builder', strict=True)
def test_container_build_interface_is_available():
    import importlib.util
    assert importlib.util.find_spec('ravel.execution_backend') is not None


def test_host_can_create_separate_interpreter_without_importing_tool():
    from ravel.setup.gpl_isolation import check
    assert not check({'groups': [{'id': 'fictional-tool',
                                 'licenses': [{'component': 'fictional-module', 'spdx': 'GPL-3.0-only'}],
                                 'steps': [{'id': 'environment', 'kind': 'command',
                                            'argv': ['{HOST_PYTHON}', '-m', 'venv', '{REPO}/.venv-fictional'],
                                            'outputs': ['{REPO}/.venv-fictional/bin/python']}]}]})


@pytest.mark.parametrize('argv', [
    ['bash', '{REPO}/native/setup/recipes/fictional.sh', '--python', '{REPO}/.venv/bin/python'],
    ['bash', '{REPO}/native/setup/recipes/fictional.sh', '--python', '{HOST_PYTHON}'],
    ['{HOST_PYTHON}', '-c', 'import fictional_module'],
])
def test_host_interpreter_cannot_reach_restricted_tool_through_a_command(argv):
    from ravel.setup.gpl_isolation import check
    assert check({'groups': [{'id': 'fictional-tool',
                              'licenses': [{'component': 'fictional-module', 'spdx': 'GPL-3.0-only'}],
                              'steps': [{'id': 'build', 'kind': 'command', 'argv': argv}]}]})
