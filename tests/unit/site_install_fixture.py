"""Synthetic site lock and inert installers; no package or facility execution."""
import importlib.util
import json
from pathlib import Path
import shutil
import types

SOURCE = Path(__file__).parents[2]
VERSIONS = {'snakemake': '9.27.0', 'packaging': '25.0',
            'snakemake-executor-plugin-cluster-generic': '1.0.9',
            'snakemake-interface-executor-plugins': '9.3.9'}


def lock_text():
    return '# Synthetic lock: hashes are inert fixture data.\n' + ''.join(
        f'{name}=={version} \\\n    --hash=sha256:{"a" * 64}\n' for name, version in VERSIONS.items())


def fixture(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('site_install_control', SOURCE / 'scripts/setup/site_installation.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    root = tmp_path / 'checkout'
    (root / 'src/ravel').mkdir(parents=True)
    (root / 'src/ravel/__init__.py').write_text('# synthetic\n')
    for name in ('requirements-full.txt', 'requirements-site.txt', 'requirements-site-wms.txt',
                 'environment/site-profiles.json', 'pyproject.toml', 'scripts/setup/site_installation.py'):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / name, target)
    (root / 'requirements-site-wms.lock').write_text(lock_text())
    monkeypatch.setattr(helper.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(helper.sys, 'version_info', (3, 12))
    monkeypatch.setattr(helper,'lcg_views',lambda:[])
    if hasattr(helper, 'release_id'):
        monkeypatch.setattr(helper, 'release_id', lambda root: 'synthetic-release-a')
    class InstallHost:
        def which(self, name):return None
        def exists(self, path):return Path(path).exists()
        def run(self, argv):
            return 0, 'Filesystem 1024-blocks Used Available Capacity Mounted on\nsynthetic 40000000 1 20000000 1% /work\n'
    monkeypatch.setattr(helper, 'Host', InstallHost)
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if 'venv' in argv:
            path = Path(argv[-1])
            (path / 'bin').mkdir(parents=True)
            (path / 'bin/python').write_text('inert interpreter\n')
            if path.name == 'site-wms':
                snake = path / 'bin/snakemake'
                snake.write_text('#!/bin/sh\nif [ "$1" = --version ]; then echo 9.27.0; else env; fi\n')
                snake.chmod(0o755)
        if '-c' in argv:
            if 'sys.base_prefix' in argv[-1]:
                return types.SimpleNamespace(stdout=json.dumps([str(Path(argv[0]).parents[1]),
                    '/synthetic/base', [3, 12], 'Linux', 'CPython']))
            return types.SimpleNamespace(stdout=json.dumps(VERSIONS))
        if argv[-1]=='--version':return types.SimpleNamespace(stdout='9.27.0\n')
        return types.SimpleNamespace(stdout='synthetic==1\n')

    monkeypatch.setattr(helper.subprocess, 'run', run)
    return helper, root, calls
