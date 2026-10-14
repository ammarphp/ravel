"""Full Python dependency declarations and required isolated-engine setup.

Installation prepares dependencies. It grants no execution, native admission,
license, provider access or scientific authority. No scientific packages import
while inspecting this manifest.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import venv
import tomllib

from .physics.source_tables import bounded_read

MANIFEST = 'environment/python/installation.json'
SETUP_TREES = ('environment', 'native/scripts', 'native/setup', 'scripts/setup')
SETUP_LIMIT = 16 * 1024 * 1024
SITE_MANIFEST = 'environment/site-profiles.json'
SITE_REQUIREMENTS = ('requirements-site.txt', 'requirements-site-wms.txt')


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate installation manifest key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('finite JSON required')))


def _path(root, logical):
    if (type(logical) is not str or '\\' in logical or logical.startswith('/')
            or any(p in ('', '.', '..') for p in logical.split('/'))):
        raise ValueError('ordinary relative installation asset required')
    return root / logical


def _read(root, logical):
    return bounded_read(_path(root, logical), limit=1024 * 1024)


def declarations(source_root=None):
    """Authenticate the finite manifest/assets, using canonical TOML in a source tree.

    An installed wheel carries the same projections; its normal Requires-Dist
    metadata remains the pip authority. This is a fresh per-call observation.
    """
    root = (Path(source_root).absolute() if source_root is not None
            else Path(__file__).parent / 'data/installation')
    manifest = _json(_read(root, MANIFEST))
    if (manifest.get('schema_version') != 1 or manifest.get('kind') != 'full_python_installation'
            or manifest.get('requires_python') != '>=3.11,<3.13'
            or manifest.get('default_python') != '3.12'
            or manifest.get('canonical') != 'pyproject.toml'
            or manifest.get('host_requirements') != 'requirements-full.txt'
            or manifest.get('helper') != 'scripts/setup/python_installation.py'):
        raise ValueError('full Python installation contract required')
    deps = manifest['dependencies']
    if not deps or len(deps) != len(set(deps)) or any(type(d) is not str for d in deps):
        raise ValueError('unique complete host dependencies required')
    requirements = _read(root, manifest['host_requirements']).decode('utf-8')
    rows = [line.strip() for line in requirements.splitlines()
            if line.strip() and not line.lstrip().startswith('#')]
    if rows != deps + ['.']:
        raise ValueError('literal full requirements differ from canonical dependency projection')
    if source_root is not None:
        project = tomllib.loads(_read(root, 'pyproject.toml').decode('utf-8'))['project']
        if project['dependencies'] != deps or project['requires-python'] != manifest['requires_python']:
            raise ValueError('full dependency manifest differs from canonical pyproject')
    profiles = manifest['isolated_required']
    if [p['name'] for p in profiles] != ['smodels', 'sfitter']:
        raise ValueError('complete required isolated Python environments required')
    expected_assets = {manifest['host_requirements']}
    for profile in profiles:
        if profile['directory'] != '.venv-' + profile['name']:
            raise ValueError('project-local isolated environment required')
        expected_assets.add(profile['requirements'])
        if 'replay_lock' in profile:
            expected_assets.add(profile['replay_lock'])
    if set(manifest['asset_pins']) != expected_assets:
        raise ValueError('complete installation requirement asset census required')
    for logical, pin in manifest['asset_pins'].items():
        raw = _read(root, logical)
        if (set(pin) != {'sha256', 'size'} or type(pin['size']) is not int
                or pin['size'] != len(raw) or pin['sha256'] != hashlib.sha256(raw).hexdigest()):
            raise ValueError('installation requirement asset changed: ' + logical)
    return manifest


def validate_aliases(source_root):
    """Validate legacy PEP508 aliases after build tooling is available.

    The installer bootstrap deliberately does not import packaging. Pip checks
    dependency metadata when installing; this source check also runs in the
    custom build hook where Hatchling already requires packaging.
    """
    root = Path(source_root)
    manifest = declarations(root)
    deps = manifest['dependencies']
    project = tomllib.loads(_read(root, 'pyproject.toml').decode('utf-8'))['project']
    # Existing aliases select compatible named capabilities in the full host;
    # they no longer indicate an incomplete default installation.
    from packaging.requirements import Requirement
    host = {Requirement(d).name.lower().replace('_', '-'): Requirement(d) for d in deps}
    for values in project['optional-dependencies'].values():
        for value in values:
            alias = Requirement(value)
            name = alias.name.lower().replace('_', '-')
            if name not in host:
                raise ValueError('legacy capability alias absent from full host: ' + name)
            exact = [s.version for s in host[name].specifier if s.operator == '==']
            if exact and exact[0] not in alias.specifier:
                raise ValueError('legacy alias conflicts with full host: ' + name)
    return True


def setup_files(source_root):
    """Finite ordinary source assets for both wheel and sdist; no tool binaries."""
    root = Path(source_root)
    declarations(root)
    # Workflow documents already have canonical source/bundle authority in the
    # existing hook. A force_include dictionary cannot give one source key two
    # destinations; keep those docs there and export setup-only assets here.
    from .paths import WORKFLOW_INSTRUCTIONS
    site_profile_plan(root)
    selected = {'requirements-full.txt', *SITE_REQUIREMENTS}
    total = 0
    for logical in SETUP_TREES:
        directory = root / logical
        if not directory.exists():
            # A separately owned native setup package can join this source tree
            # without changing the Python profile or admitting a native runtime.
            continue
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError('ordinary setup source directory required')
        for path in directory.rglob('*'):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError('ordinary setup source membership required')
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                if relative not in WORKFLOW_INSTRUCTIONS:
                    selected.add(relative)
    if MANIFEST not in selected or 'scripts/setup/python_installation.py' not in selected or len(selected) > 512:
        raise ValueError('complete bounded Python setup assets required')
    for logical in sorted(selected):
        total += len(_read(root, logical))
        if total > SETUP_LIMIT:
            raise ValueError('bounded setup source aggregate required')
    return sorted(selected)



def site_profile_plan(source_root=None):
    """Inspect the required site profiles without running their installer."""
    root = (Path(source_root).absolute() if source_root is not None
            else Path(__file__).parent / 'data/installation')
    manifest = _json(_read(root, SITE_MANIFEST))
    profiles = manifest.get('profiles', {})
    expected = {
        'site-analysis': ['requirements-full.txt', 'requirements-site.txt'],
        'site-wms': ['requirements-site-wms.txt'],
    }
    if (manifest.get('schema_version') != 1
            or manifest.get('required_for') != ['root-stream', 'site-workflow']
            or manifest.get('platform', {}).get('execution_os') != 'Linux'
            or manifest.get('platform', {}).get('python') != '3.12'
            or set(profiles) != set(expected)
            or any(profiles[name].get('requirements') != values
                   for name, values in expected.items())
            or profiles['site-analysis'].get('installs_ravel') is not True
            or profiles['site-wms'].get('installs_ravel') is not False
            or profiles['site-wms'].get('calls_exact_site_analysis_python') is not True):
        raise ValueError('complete required Linux site profiles required')
    assets = [SITE_MANIFEST, 'scripts/setup/site_installation.py',
              'requirements-full.txt', *SITE_REQUIREMENTS]
    pins = []
    for logical in assets:
        raw = _read(root, logical)
        pins.append({'path': logical, 'sha256': hashlib.sha256(raw).hexdigest(),
                     'size': len(raw)})
    helper = str(root / 'scripts/setup/site_installation.py')
    return {'required_for': manifest['required_for'], 'execution_os': 'Linux',
            'python': '3.12', 'profiles': profiles, 'source_assets': pins,
            'source_checkout_required': source_root is None,
            'linux_install_argv': (['python3.12', helper, '--install']
                                   if source_root is not None else None),
            'remote_plan_argv': (['python3.12', helper, '--plan', '--linux-root',
                                  'ABSOLUTE_LINUX_CHECKOUT']
                                 if source_root is not None else None),
            'runtime_or_site_data_qualified': False}


def plan(source_root=None):
    root = (Path(source_root).absolute() if source_root is not None
            else Path(__file__).parent / 'data/installation')
    manifest = declarations(source_root)
    host_dir = root / '.venv' if source_root is not None else None
    return {'schema_version': 1, 'kind': 'python_installation_plan',
            'requires_python': manifest['requires_python'], 'complete_setup_python': '3.12',
            'source_root': str(root), 'host_directory': str(host_dir) if host_dir else None,
            'host_command': ['python', '-m', 'pip', 'install', '-r', str(root / 'requirements-full.txt')],
            'host_command_cwd': str(root) if source_root is not None else 'source checkout required for the literal dot entry',
            'isolated_required': [{**p, 'requirements_path': str(root / p['requirements'])}
                                  for p in manifest['isolated_required']],
            'required_site_profiles': site_profile_plan(source_root),
            'limitations': manifest['limitations'], 'compute_authorized': False,
            'physics_validated': False}


def _environment(root, logical):
    target = root / logical
    if target.exists():
        if target.is_symlink() or not target.is_dir() or not (target / 'pyvenv.cfg').is_file():
            raise ValueError('existing project-local virtual environment required: ' + str(target))
    else:
        venv.EnvBuilder(with_pip=True).create(target)
    python = target / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    # venv interpreters normally symlink to their base interpreter. Validate their
    # observed sys.prefix instead of mistaking that standard link for a global env.
    check = 'import sys,json;print(json.dumps([sys.prefix,list(sys.version_info[:2])]))'
    prefix, version = json.loads(subprocess.check_output([str(python), '-I', '-c', check], text=True))
    if Path(prefix).resolve() != target.resolve() or version != [3, 12]:
        raise ValueError('project-local Python 3.12 venv required before installing')
    return python


def install(source_root, *, host_only=False):
    """Prepare the full Python environments without altering global Python.

    No native programs or scientific study execute here. Source-bound engines,
    licenses and provider access are still installed/admitted separately.
    """
    if sys.version_info[:2] != (3, 12):
        raise ValueError('use python3.12 scripts/setup/python_installation.py')
    root = Path(source_root).absolute()
    manifest = declarations(root)
    targets = [('.venv', manifest['host_requirements'])]
    if not host_only:
        targets += [(p['directory'], p['requirements']) for p in manifest['isolated_required']]
    for logical, requirements in targets:
        python = _environment(root, logical)
        declarations(root)
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(root / requirements)],
                       cwd=root, check=True)
    return {'python_environments_prepared': [p for p, _ in targets],
            'complete_python_profile': not host_only, 'native_admitted': False,
            'compute_authorized': False, 'physics_validated': False}


def main(argv=None, *, source_root=None):
    parser = argparse.ArgumentParser(description='Full Python host and required isolated-engine environments')
    parser.add_argument('--plan', action='store_true', help='inspect exact dependencies without installing')
    parser.add_argument('--host-only', action='store_true', help='advanced: prepare only the full host; isolated engines remain missing')
    args = parser.parse_args(argv)
    if args.plan:
        print(json.dumps(plan(source_root), indent=2))
    elif source_root is None:
        parser.error('installed package: use --plan for assets; run setup from a source checkout')
    else:
        print(json.dumps(install(source_root, host_only=args.host_only), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
