"""Prefix, hashes, isolation and refusals with inert synthetic tools."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from site_install_fixture import fixture, lock_text, SOURCE, VERSIONS


def test_hash_locked_plugin_prefix_and_record(tmp_path, monkeypatch):
    helper, root, calls = fixture(tmp_path, monkeypatch)
    prefix = tmp_path / 'work'
    helper.install(root, prefix=prefix, lcg_view='none')
    pip = [argv for argv, _ in calls if 'pip' in argv and 'install' in argv]
    assert '--require-hashes' in pip[1]
    assert pip[1][-1] == str(root / 'requirements-site-wms.lock')
    record = json.loads((prefix / '.ravel-site/wms.json').read_text())
    assert record['version'] == VERSIONS['snakemake']
    assert record['plugins'] == {'snakemake-executor-plugin-cluster-generic': '1.0.9'}
    assert record['release'] == 'synthetic-release-a'
    assert record['snakemake'] == str(prefix / '.ravel-site/site-wms/bin/snakemake')
    assert len(record['lock_sha256']) == 64
    assert (prefix / '.ravel-site/site-analysis/bin/python').is_file()
    assert not (root / '.ravel-site').exists()


def test_shim_clears_facility_python_and_runtime_uses_record(tmp_path, monkeypatch):
    helper, root, _ = fixture(tmp_path, monkeypatch)
    prefix = tmp_path / 'work'
    helper.install(root, prefix=prefix, lcg_view='none')
    monkeypatch.undo()  # execute only the inert shell Snakemake, not the fake pip
    monkeypatch.setenv('RAVEL_NATIVE_BUILD', str(prefix))
    monkeypatch.delenv('RAVEL_SNAKEMAKE', raising=False)
    monkeypatch.delenv('RAVEL_TEST_SNAKEMAKE', raising=False)
    from ravel.workflow.wms_runtime import snakemake_argv
    shim = prefix / 'bin/ravel-snakemake'
    assert snakemake_argv() == [str(shim)]
    env = dict(os.environ, PYTHONPATH='/fake/view', PYTHONHOME='/fake/view', PYTHONSTARTUP='/fake/start')
    result = subprocess.run([str(shim)], env=env, capture_output=True, text=True, check=True)
    assert not any(line.startswith(key + '=') for key in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP')
                   for line in result.stdout.splitlines())
    assert 'PYTHONNOUSERSITE=1' in result.stdout


def test_different_release_refuses_before_pip(tmp_path, monkeypatch):
    helper, root, calls = fixture(tmp_path, monkeypatch)
    prefix = tmp_path / 'work'
    helper.install(root, prefix=prefix, lcg_view='none')
    calls.clear()
    monkeypatch.setattr(helper, 'release_id', lambda root: 'synthetic-release-b')
    with pytest.raises(ValueError, match='synthetic-release-a.*synthetic-release-b.*new prefix.*campaign ends'):
        helper.install(root, prefix=prefix, lcg_view='none')
    assert not calls


@pytest.mark.parametrize('choice', [None, 'auto'])
def test_no_implicit_lcg_choice_installs_nothing(tmp_path, monkeypatch, choice):
    helper, root, calls = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(helper, 'lcg_views', lambda: [dict(path='/synthetic/view', release='LCG_200', platform='x86_64-opt')])
    with pytest.raises(ValueError, match='--lcg-view.*none'):
        helper.install(root, prefix=tmp_path / 'work', lcg_view=choice)
    assert not calls


def test_explicit_lcg_view_and_none_are_recorded(tmp_path, monkeypatch):
    helper, root, _ = fixture(tmp_path, monkeypatch)
    view = tmp_path / 'views/LCG_200/x86_64-el9-gcc-opt'
    view.mkdir(parents=True)
    (view / 'setup.sh').write_text('# synthetic\n')
    for choice, name in ((str(view), 'work-view'), ('none', 'work-none')):
        prefix = tmp_path / name
        helper.install(root, prefix=prefix, lcg_view=choice)
        record = json.loads((prefix / '.ravel-site/lcg-view.json').read_text())
        assert record['path'] == (None if choice == 'none' else str(view))
        assert record['release'] == (None if choice == 'none' else 'LCG_200')


def test_installer_children_use_prefix_caches_and_tmp(tmp_path, monkeypatch):
    helper, root, calls = fixture(tmp_path, monkeypatch)
    prefix = tmp_path / 'work'
    helper.install(root, prefix=prefix, lcg_view='none')
    for _, kwargs in calls:
        for key in ('APPTAINER_CACHEDIR', 'APPTAINER_TMPDIR', 'TMPDIR', 'PIP_CACHE_DIR'):
            assert Path(kwargs['env'][key]).is_relative_to(prefix)


def test_missing_or_unhashed_lock_refuses_before_venv(tmp_path, monkeypatch):
    helper, root, calls = fixture(tmp_path, monkeypatch)
    (root / 'requirements-site-wms.lock').write_text('snakemake==9.27.0\n')
    with pytest.raises(ValueError, match='hash'):
        helper.install(root, prefix=tmp_path / 'work', lcg_view='none')
    assert not calls


def test_lock_generator_uses_fake_uv(tmp_path):
    root = tmp_path / 'checkout'
    (root / 'scripts/setup').mkdir(parents=True)
    shutil_source = SOURCE / 'scripts/setup/lock-site-wms.sh'
    (root / 'scripts/setup/lock-site-wms.sh').write_text(shutil_source.read_text())
    (root / 'requirements-site-wms.in').write_text('snakemake==9.27.0\n')
    tools = tmp_path / 'tools'; tools.mkdir()
    uv = tools / 'uv'
    uv.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$UV_ARGS"\nwhile [ "$#" -gt 0 ]; do\n'
                  ' if [ "$1" = --output-file ]; then shift; echo "# inert lock" > "$1"; fi\n shift\ndone\n')
    uv.chmod(0o755)
    result = subprocess.run(['bash', str(root / 'scripts/setup/lock-site-wms.sh')],
        env=dict(os.environ, PATH=str(tools) + ':' + os.environ['PATH'], UV_ARGS=str(tmp_path / 'args')),
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    argv = (tmp_path / 'args').read_text().splitlines()
    assert argv[:2] == ['pip', 'compile'] and '--generate-hashes' in argv
    assert str(root / 'requirements-site-wms.in') in argv
    assert (root / 'requirements-site-wms.lock').is_file()


def test_site_profile_trimmed_and_tester_qualification(tmp_path):
    from ravel.setup import manifest
    value, _ = manifest.load(SOURCE)
    groups = manifest.profile_groups(value, 'site')
    assert 'root-combine' not in groups and 'tex' not in groups and 'ml' in groups
    assert value['profiles']['site']['disk_gb'] == 12
    assert sum(manifest.by_id(value)[name]['size_gb'] for name in groups) <= 12
    for name in ('site-root-wms', 'site-access'):
        assert manifest.by_id(value)[name]['qualification']['status'] == 'tester-qualification'


def test_setup_children_env_file_and_wrapper_use_prefix_caches(tmp_path):
    from ravel.setup.steps import subprocess_environment
    from ravel.setup.installer import Installer
    from ravel.setup import manifest
    prefix = tmp_path / 'work'
    env = subprocess_environment(prefix, {'JOBS': '1', 'PLATFORM': 'linux-x86_64'}, {'APPTAINER_CACHEDIR': '/fake/home', 'TMPDIR': '/tmp'})
    assert env['APPTAINER_CACHEDIR'] == str(prefix / 'cache/apptainer')
    assert env['APPTAINER_TMPDIR'] == str(prefix / 'tmp/apptainer')
    assert env['TMPDIR'] == str(prefix / 'tmp')
    value, catalog = manifest.load(SOURCE)
    installer = Installer(SOURCE, prefix, platform_key='linux-x86_64', manifest=value, catalog=catalog, environ={})
    installer._write_env_file()
    text = (prefix / 'config/ravel-env.sh').read_text()
    assert 'export APPTAINER_CACHEDIR=' + str(prefix / 'cache/apptainer') in text
    assert 'export APPTAINER_TMPDIR=' + str(prefix / 'tmp/apptainer') in text
    wrapper = (SOURCE / 'native/setup/wrappers/container-run.sh.in').read_text()
    assert 'APPTAINER_CACHEDIR="@PREFIX@/cache/apptainer"' in wrapper
    assert 'APPTAINER_TMPDIR="@PREFIX@/tmp/apptainer"' in wrapper


def test_install_parser_and_manifest_carry_view_and_prefix(tmp_path):
    from ravel.setup.installer import parser
    from ravel.setup import manifest
    args = parser().parse_args(['--profile','site','--prefix',str(tmp_path),'--lcg-view','none'])
    assert args.lcg_view == 'none'
    value, _ = manifest.load(SOURCE)
    step = manifest.by_id(value)['site-root-wms']['steps'][0]
    assert step['env']['RAVEL_LCG_VIEW'] == '{LCG_VIEW}'
    assert '--prefix' in step['argv'] and '{P}' in step['argv']
    assert 'auto' not in step['argv']


def test_universal_lock_ignores_other_platform_entries(tmp_path):
    from ravel.workflow.site_contract import lock_packages
    lock=tmp_path/'universal.lock'
    lock.write_text(lock_text()+f'fictional-windows-package==1.0 ; sys_platform == "win32" \\\n    --hash=sha256:{"b"*64}\n')
    assert 'fictional-windows-package' not in lock_packages(lock)


def test_auto_view_cli_lists_candidates_and_exact_rerun_before_install(tmp_path,monkeypatch,capsys):
    helper,root,calls=fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(helper,'lcg_views',lambda:[dict(path='/synthetic/views/LCG_200/x86_64-opt')])
    assert helper.main(['--install','--prefix',str(tmp_path/'work'),'--lcg-view','auto'])==2
    error=capsys.readouterr().err
    assert '/synthetic/views/LCG_200/x86_64-opt' in error
    assert '--prefix '+str(tmp_path/'work') in error and '--lcg-view none' in error
    assert not calls


def test_site_instruction_contract_is_declared():
    from workflow_instruction_inventory_fixture import assert_site_installation_instruction
    assert_site_installation_instruction(SOURCE)


def test_temporary_directory_moves_into_the_prefix_only_on_linux(tmp_path):
    # macOS container tooling keeps its sockets under TMPDIR, where a long prefix path exceeds the socket limit.
    from ravel.setup.steps import subprocess_environment
    from ravel.setup.installer import Installer
    from ravel.setup import manifest
    prefix = tmp_path / 'work'
    source = {'TMPDIR': '/synthetic/tmp'}
    linux = subprocess_environment(prefix, {'JOBS': '1', 'PLATFORM': 'linux-x86_64'}, source)
    assert linux['TMPDIR'] == str(prefix / 'tmp')
    mac = subprocess_environment(prefix, {'JOBS': '1', 'PLATFORM': 'macos-arm64'}, source)
    assert mac['TMPDIR'] == '/synthetic/tmp'
    assert mac['APPTAINER_TMPDIR'] == str(prefix / 'tmp/apptainer')
    value, catalog = manifest.load(SOURCE)
    for platform_key, expected in (('linux-x86_64', True), ('macos-arm64', False)):
        target = tmp_path / platform_key
        installer = Installer(SOURCE, target, platform_key=platform_key, manifest=value, catalog=catalog, environ={})
        installer._write_env_file()
        text = (target / 'config/ravel-env.sh').read_text()
        assert ('export TMPDIR=' + str(target / 'tmp') in text) is expected


def test_empty_view_choice_asks_for_an_explicit_choice(tmp_path, monkeypatch):
    helper, _, _ = fixture(tmp_path, monkeypatch)
    for value in (None, '', 'auto'):
        with pytest.raises(ValueError, match='Choose an explicit LCG view'):
            helper.lcg_choice(value, prefix=tmp_path / 'work')


def test_installed_version_query_normalises_distribution_names(monkeypatch, capsys):
    import importlib.metadata
    import types
    from ravel.workflow.site_contract import versions_script
    rows = [types.SimpleNamespace(metadata={'Name': 'Synthetic.Dotted_Name'}, version='1.2.3')]
    monkeypatch.setattr(importlib.metadata, 'distributions', lambda: rows)
    exec(versions_script(['synthetic-dotted-name', 'synthetic-absent']), {})
    assert json.loads(capsys.readouterr().out) == {'synthetic-dotted-name': '1.2.3', 'synthetic-absent': None}


def test_source_without_version_control_is_refused_in_plain_words(tmp_path, monkeypatch):
    import importlib.util
    import types
    spec = importlib.util.spec_from_file_location('site_install_release', SOURCE / 'scripts/setup/site_installation.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)

    def run(argv, **kwargs):
        if kwargs.get('check'):
            raise subprocess.CalledProcessError(128, argv)
        return types.SimpleNamespace(returncode=128, stdout='', stderr='synthetic')

    monkeypatch.setattr(helper.subprocess, 'run', run)
    with pytest.raises(ValueError, match='git checkout'):
        helper.release_id(tmp_path)
