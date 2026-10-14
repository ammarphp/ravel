"""Inert ModuleType fixtures; no Torch/native/runtime import or numerical call."""
import copy
import hashlib
from pathlib import Path
import types

import pytest
from ravel.physics import sfitter_native as adapter, sfitter_worker as worker


def pinned(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = text.encode()
    path.write_bytes(raw)
    return str(path), hashlib.sha256(raw).hexdigest()


@pytest.fixture
def world(tmp_path, monkeypatch):
    site = tmp_path / 'site-packages'
    root_path, root_hash = pinned(site / 'torch/__init__.py', '# Inert Torch registry fixture, no engine.\n')
    root = types.ModuleType('torch'); root.__file__ = root_path
    modules = {'torch': root}; assets = {root_path: root_hash}
    for name, (owner_name, class_name, attribute, sentinel) in worker.VIRTUAL_NAMESPACES.items():
        text = ('import types\nclass ' + class_name + '(types.ModuleType):\n'
                '    __file__ = ' + repr(sentinel) + '\n'
                '    def __init__(self):\n        super().__init__(' + repr(name) + ')\n'
                + attribute + ' = ' + class_name + '()\n')
        path, sha = pinned(site / 'torch' / sentinel, text)
        owner = types.ModuleType(owner_name); owner.__file__ = path
        # Only this small authored standard-library fixture is executed.
        exec(compile(text, path, 'exec'), owner.__dict__)
        singleton = vars(owner)[attribute]
        setattr(root, attribute, singleton)
        modules[owner_name] = owner; modules[name] = singleton
        assets[path] = sha
    package = tmp_path / 'upstream/sfitter'
    likelihood_path, sha = pinned(package / 'sfitter/likelihood/full_likelihood.py', '# Inert likelihood origin.\n')
    likelihood = types.ModuleType('sfitter.likelihood.full_likelihood'); likelihood.__file__ = likelihood_path
    modules[likelihood.__name__] = likelihood
    request = {'config': {'runtime': {'site_roots': [str(site)], 'versions': {'torch': '2.14.0'}, 'device': 'cpu'}},
        'package_root': str(package), 'runtime_assets': assets, 'source_files': {likelihood_path: sha},
        'output': str(tmp_path / 'out'), 'exporter_sha256': 'e' * 64, 'driver_sha256': 'd' * 64}
    monkeypatch.setattr(worker, 'sys', types.SimpleNamespace(modules=modules))
    return request, modules


def runtime(request, imports):
    return {'schema_version': 1, 'versions': request['config']['runtime']['versions'],
        'device': 'cpu', 'precision': 'double', 'imports': imports,
        'source_files': request['source_files'], 'runtime_assets': request['runtime_assets'],
        'randomness': 'inert synthetic observations, no numerical authority', 'physics_validated': False}


def test_exact_two_virtual_roots_with_full_physical_owner_census(world):
    request, _ = world
    imports = worker._imports(request)
    assert len(imports) == 6
    assert {name for name, row in imports.items() if row.get('kind')} == {'torch.ops', 'torch.classes'}
    for name in worker.VIRTUAL_NAMESPACES:
        assert imports[name] == worker.virtual_import_contract(name, request)
        assert imports[name]['owner'] == imports[imports[name]['type']['module']]
        assert imports[name]['package_owner'] == imports['torch']
    assert adapter.validate_runtime(runtime(request, imports), request)['physics_validated'] is False


@pytest.mark.parametrize('name', ['torch.ops', 'torch.classes'])
@pytest.mark.parametrize('mutation', ['plain_type', 'subclass', 'wrong_name', 'instance_file',
    'class_file', 'owner_registry', 'package_registry', 'sys_registry', 'foreign_owner_file',
    'foreign_package_file', 'class_qualname', 'class_module', 'foreign_initializer'])
def test_forged_namespace_refused(world, name, mutation):
    request, modules = world
    owner_name, class_name, attribute, sentinel = worker.VIRTUAL_NAMESPACES[name]
    owner = modules[owner_name]; root = modules['torch']; namespace = modules[name]
    cls = vars(owner)[class_name]
    if mutation == 'plain_type':
        namespace = types.ModuleType(name); namespace.__file__ = sentinel
        modules[name] = namespace; setattr(owner, attribute, namespace); setattr(root, attribute, namespace)
    elif mutation == 'subclass':
        namespace = type('Alias', (cls,), {})()
        modules[name] = namespace; setattr(owner, attribute, namespace); setattr(root, attribute, namespace)
    elif mutation == 'wrong_name': namespace.__name__ = name + '.forged'
    elif mutation == 'instance_file': namespace.__file__ = '/foreign/file.py'
    elif mutation == 'class_file': cls.__file__ = sentinel + '.forged'
    elif mutation == 'owner_registry': setattr(owner, attribute, object())
    elif mutation == 'package_registry': setattr(root, attribute, object())
    elif mutation == 'sys_registry': modules[name] = object()
    elif mutation == 'foreign_owner_file': owner.__file__ = '/foreign/' + sentinel
    elif mutation == 'foreign_package_file': root.__file__ = '/foreign/__init__.py'
    elif mutation == 'class_qualname': cls.__qualname__ += 'Forged'
    elif mutation == 'class_module': cls.__module__ = 'foreign'
    elif mutation == 'foreign_initializer':
        def other(self): pass
        cls.__init__ = other
    with pytest.raises(ValueError):
        worker._virtual_import(name, namespace, request)


@pytest.mark.parametrize('name', ['torch.ops', 'torch.classes'])
def test_same_canonical_object_under_forged_registry_name_refused(world, name):
    request, modules = world
    with pytest.raises(ValueError, match='unregistered name'):
        worker._virtual_import(name + '.forged', modules[name], request)


@pytest.mark.parametrize('physical', ['owner', 'package'])
def test_admitted_physical_owner_drift_refused(world, physical):
    request, _ = world
    contract = worker.virtual_import_contract('torch.ops', request)
    key = 'owner' if physical == 'owner' else 'package_owner'
    path = Path(contract[key]['path']); path.write_bytes(path.read_bytes() + b'# drift\n')
    with pytest.raises(ValueError, match='dependency changed|not an admitted exact asset'):
        worker._imports(request)


def test_owner_alias_and_unadmitted_or_ambiguous_root_refused(world, tmp_path):
    request, _ = world
    key = str(Path(request['config']['runtime']['site_roots'][0]) / 'torch/_ops.py')
    missing = copy.deepcopy(request); del missing['runtime_assets'][key]
    with pytest.raises(ValueError, match='one admitted physical'):
        worker.virtual_import_contract('torch.ops', missing)
    duplicate = copy.deepcopy(request)
    duplicate['config']['runtime']['site_roots'] *= 2
    with pytest.raises(ValueError, match='one admitted physical'):
        worker.virtual_import_contract('torch.ops', duplicate)
    target = Path(key); content = target.read_bytes(); other = tmp_path / 'other.py'; other.write_bytes(content)
    target.unlink(); target.symlink_to(other)
    with pytest.raises(ValueError, match='dependency changed'):
        worker.virtual_import_contract('torch.ops', request)


@pytest.mark.parametrize('name,file', [('torch.ops.extra', '_ops.py'), ('opaque', 'torch.ops'),
                                      ('opaque', '/missing/physical.py')])
def test_unknown_marker_is_not_blanket_missing_file_exemption(world, name, file):
    request, modules = world
    module = types.ModuleType(name); module.__file__ = file
    modules[name] = module
    with pytest.raises((ValueError, FileNotFoundError)):
        worker._imports(request)


@pytest.mark.parametrize('field,value', [('namespace', 'torch.ops.other'), ('sentinel_file', 'other.py'),
    ('identity_observation', 'ignored_missing_file'), ('kind', 'opaque')])
def test_serialized_virtual_contract_refuses_forgery(world, field, value):
    request, _ = world
    imports = worker._imports(request); imports['torch.ops'][field] = value
    with pytest.raises(ValueError): adapter.validate_runtime(runtime(request, imports), request)


@pytest.mark.parametrize('field', ['type', 'registry', 'owner', 'package_owner'])
def test_serialized_nested_virtual_binding_refuses_forgery(world, field):
    request, _ = world
    imports = worker._imports(request)
    key = next(iter(imports['torch.ops'][field]))
    imports['torch.ops'][field][key] = 'forged'
    with pytest.raises(ValueError): adapter.validate_runtime(runtime(request, imports), request)


@pytest.mark.parametrize('missing', ['torch', 'torch._ops'])
def test_virtual_record_needs_physical_import_observations(world, missing):
    request, _ = world
    imports = worker._imports(request); del imports[missing]
    with pytest.raises(ValueError, match='physical owner imports'):
        adapter.validate_runtime(runtime(request, imports), request)


def test_virtual_name_cannot_claim_legacy_physical_record(world):
    request, _ = world
    imports = worker._imports(request); imports['torch.ops'] = imports['torch._ops']
    with pytest.raises(ValueError, match='typed observation'):
        adapter.validate_runtime(runtime(request, imports), request)


def test_physical_import_custody_remains_exact(world):
    request, modules = world
    imports = worker._imports(request)
    imports['sfitter.likelihood.full_likelihood']['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='unadmitted native import'):
        adapter.validate_runtime(runtime(request, imports), request)
    path = Path(modules['sfitter.likelihood.full_likelihood'].__file__)
    path.write_text('# changed physical source\n')
    with pytest.raises(ValueError, match='not an admitted exact asset'):
        worker._imports(request)


