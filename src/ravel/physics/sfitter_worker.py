"""Pinned native child entrypoint. Importing this module performs no native work.

Only the ordinary supervised SFitter adapter dispatches main. Native numerical
code is unchanged; this boundary adds custody, progressive status and transport.
"""
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import pickle
import sys
import sysconfig
import types


# Exactly the two root singletons registered by released torch/__init__.py.
# Arbitrary torch.ops child namespaces, names and missing files are not admitted.
VIRTUAL_NAMESPACES = {
    'torch.ops': ('torch._ops', '_Ops', 'ops', '_ops.py'),
    'torch.classes': ('torch._classes', '_Classes', 'classes', '_classes.py'),
}


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(path, value):
    data = json.dumps(value, allow_nan=False, sort_keys=True, indent=2).encode()
    tmp = Path(str(path) + '.tmp')
    with tmp.open('wb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    os.replace(tmp, path)


def _check(files):
    for name, sha in files.items():
        path = Path(name)
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file() or _hash(path) != sha:
            raise ValueError('native declared dependency changed: ' + name)


def virtual_import_contract(name, request):
    """Closed observation contract tied to unique admitted physical Torch owners.

    This pure helper imports no Torch and invokes no namespace getattr/getter.
    Actual class/registry identity is observed separately in the native child.
    """
    if name not in VIRTUAL_NAMESPACES:
        raise ValueError('unsupported virtual Python namespace')
    owner_name, class_name, attribute, sentinel = VIRTUAL_NAMESPACES[name]
    candidates = []
    for root in request['config']['runtime']['site_roots']:
        root = Path(root)
        if not root.is_absolute() or root != root.resolve():
            raise ValueError('canonical runtime root required for virtual owner')
        owner = root / 'torch' / sentinel
        package = root / 'torch' / '__init__.py'
        if str(owner) in request['runtime_assets'] and str(package) in request['runtime_assets']:
            candidates.append((owner, package))
    if len(candidates) != 1:
        raise ValueError('one admitted physical virtual-namespace owner required')
    owner, package = candidates[0]
    owner_hash = request['runtime_assets'][str(owner)]
    package_hash = request['runtime_assets'][str(package)]
    _check({str(owner): owner_hash, str(package): package_hash})
    return {'kind': 'virtual_python_namespace', 'namespace': name, 'sentinel_file': sentinel,
            'type': {'module': owner_name, 'qualname': class_name},
            'registry': {'sys_modules_key': name, 'owner_module': owner_name,
                         'owner_attribute': attribute, 'package_module': 'torch',
                         'package_attribute': attribute},
            'owner': {'path': str(owner), 'sha256': owner_hash},
            'package_owner': {'path': str(package), 'sha256': package_hash},
            'identity_observation': 'exact_class_and_owner_package_sys_modules_singleton'}


def _virtual_import(name, module, request):
    cls = type(module)
    known_types = {(row[0], row[1]) for row in VIRTUAL_NAMESPACES.values()}
    if name not in VIRTUAL_NAMESPACES:
        if (cls.__module__, cls.__qualname__) in known_types:
            raise ValueError('canonical virtual singleton has an unregistered name')
        return None
    record = virtual_import_contract(name, request)
    owner_name, class_name, attribute, sentinel = VIRTUAL_NAMESPACES[name]
    owner = sys.modules.get(owner_name)
    package = sys.modules.get('torch')
    if type(owner) is not types.ModuleType or type(package) is not types.ModuleType:
        raise ValueError('canonical physical Torch owner modules required')
    owner_values, package_values = vars(owner), vars(package)
    canonical_class = owner_values.get(class_name)
    if (type(canonical_class) is not type or cls is not canonical_class
            or cls.__bases__ != (types.ModuleType,) or cls.__module__ != owner_name
            or cls.__qualname__ != class_name):
        raise ValueError('exact canonical virtual namespace class required')
    values = vars(module)
    if (values.get('__name__') != name or cls.__dict__.get('__file__') != sentinel
            or values.get('__file__', sentinel) != sentinel):
        raise ValueError('virtual namespace name/file marker changed')
    initializer = cls.__dict__.get('__init__')
    if (type(initializer) is not types.FunctionType
            or initializer.__globals__ is not owner_values
            or initializer.__module__ != owner_name
            or Path(initializer.__code__.co_filename).absolute() != Path(record['owner']['path'])):
        raise ValueError('virtual namespace initializer is not the physical canonical owner')
    if (owner_values.get('__name__') != owner_name or package_values.get('__name__') != 'torch'
            or owner_values.get('__file__') != record['owner']['path']
            or package_values.get('__file__') != record['package_owner']['path']):
        raise ValueError('virtual namespace physical owner origin changed')
    if (sys.modules.get(name) is not module or owner_values.get(attribute) is not module
            or package_values.get(attribute) is not module):
        raise ValueError('virtual namespace canonical singleton registries differ')
    return record


def _imports(request):
    """Observed Python imports, not a claim of full OS/shared-library closure."""
    standard = Path(sysconfig.get_path('stdlib')).resolve()
    sites = [Path(p).resolve() for p in request['config']['runtime']['site_roots']]
    package = Path(request['package_root']).resolve()
    assets = request['runtime_assets']
    sources = request['source_files']
    output = Path(request['output'])
    records = {}
    for name, module in list(sys.modules.items()):
        virtual = _virtual_import(name, module, request)
        if virtual is not None:
            records[name] = virtual
            continue
        raw = getattr(module, '__file__', None)
        if not raw:
            continue
        path = Path(raw).absolute()
        # Compiled stdlib extension modules are allowed only outside site roots.
        if path.is_relative_to(standard) and not any(path.is_relative_to(p) for p in sites) and 'site-packages' not in path.parts:
            continue
        sha = _hash(path)
        expected = sources.get(str(path)) if path.is_relative_to(package) else assets.get(str(path))
        if path == output / 'sfitter_results.py': expected = request['exporter_sha256']
        if path == output / 'driver.py': expected = request['driver_sha256']
        if expected != sha:
            raise ValueError('native Python import not an admitted exact asset: ' + str(path))
        records[name] = {'path': str(path), 'sha256': sha}
    return records


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1: raise ValueError('one native request required')
    request_path = Path(args[0]).absolute()
    request = json.loads(request_path.read_text())
    required = {'schema_version','config','package_root','run_card','output','basis','runtime_assets',
                'source_files','exporter_sha256','driver_sha256','selected_files'}
    if set(request) != required or request['schema_version'] != 1: raise ValueError('closed native request required')
    out = Path(request['output'])
    progress = {'schema_version': 1, 'operation': request['config']['operation'], 'phase': 'bootstrap',
                'completed': [], 'error': None, 'physics_validated': False}
    _write(out / 'progress.json', progress)
    runtime = request['config']['runtime']
    # -I -B is part of the ordinary argv. Site roots are explicit pinned inputs;
    # they are inserted here, never inferred from ambient PYTHONPATH/user site.
    try:
        if Path(sys.executable).resolve() != Path(runtime['python']['path']).resolve():
            raise ValueError('native interpreter identity differs')
        _check({runtime['python']['path']: runtime['python']['sha256']})
        _check(request['runtime_assets']); _check(request['source_files']); _check(request['selected_files'])
        _check({str(out/'driver.py'): request['driver_sha256'], str(out/'sfitter_results.py'): request['exporter_sha256']})
        sys.path[:0] = [request['package_root'], *runtime['site_roots']]
        os.chdir(request['package_root'])
        if runtime['device'] == 'cpu': os.environ['CUDA_VISIBLE_DEVICES'] = ''
        observed_versions = {name: importlib.metadata.version(name) for name in runtime['versions']}
        if observed_versions != runtime['versions']: raise ValueError('native distribution version differs')
        export_spec = importlib.util.spec_from_file_location('ravel_sfitter_export', out/'sfitter_results.py')
        export = importlib.util.module_from_spec(export_spec); sys.modules[export_spec.name] = export
        export_spec.loader.exec_module(export)
        import torch
        if str(torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')) != runtime['device']:
            raise ValueError('upstream automatic device selection differs from declared device')
        torch.set_num_threads(1); torch.set_default_dtype(torch.float64)
        from sfitter.util.documenter import Documenter
        doc, params = Documenter.from_param_file(request['run_card'])
        progress['completed'].append('runtime_and_card'); progress['phase'] = 'native_initialization'
        _write(out/'progress.json', progress)
        if request['config']['operation'] == 'fit':
            from sfitter.__main__ import init_run, Plots
            fitter, likelihood = init_run(doc, params, True)
        else:
            from sfitter.likelihood.full_likelihood import ProfileLikelihood
            likelihood = ProfileLikelihood(params, torch.device(runtime['device']))
        if list(likelihood.parameter_names) != request['basis'] or likelihood.dims_nuisance != 0:
            raise ValueError('native full top parameter population differs')
        _imports(request)
        _check(request['runtime_assets']); _check(request['source_files']); _check(request['selected_files'])
        origins=[{'path':name,'sha256':sha} for name,sha in request['source_files'].items()
                 if name.endswith('/sfitter/likelihood/full_likelihood.py')]
        if len(origins)!=1:raise ValueError('one exact initialized likelihood source required')
        # Completed initialization survives a later training, scoring or export failure.
        # These are the actual initialized attributes, never reconstructed from cards.
        initialized=export.initialized_state(likelihood,request['basis'],origins[0])
        _write(out/'initialized-state.json',initialized)
        if (out/'initialized-state.json').stat().st_size>request['config']['max_export_bytes']:
            raise ValueError('initialized native state exceeds declared byte bound')
        progress['completed'].append('initialized_state_retained')
        progress['completed'].append('native_initialization'); progress['phase'] = 'native_calculation'
        _write(out/'progress.json', progress)
        if request['config']['operation'] == 'fit':
            fitter.train(); fitter.save(); results = fitter.fit()
            # Preserve the native raw object before our transport can refuse it.
            with open(doc.add_file('results.pkl'), 'wb') as stream:
                pickle.dump(results, stream); stream.flush(); os.fsync(stream.fileno())
            progress['completed'].append('native_raw_result'); progress['phase'] = 'array_export'
            _write(out/'progress.json', progress)
            delivery = export.fit_result(results, request['basis'])
        else:
            vectors = request['config']['vectors']
            with torch.no_grad():
                scores = likelihood.log_likelihood(torch.tensor(vectors, device=runtime['device'], dtype=torch.float64))
            delivery = {'schema_version':1, 'kind':'sfitter_fixed_vectors', 'parameters':request['basis'],
                        'vectors':vectors, 'scores':export.array(scores.cpu().numpy()),
                        'native_tensors':initialized['native_tensors'],
                        'score_convention':'native_score=-Q', 'predictions':None,
                        'prediction_reason':'Native log_likelihood_top returns scores only; retained native tensors permit a separately reviewed diagnostic.',
                        'physics_validated':False}
        _write(out/'delivery.json', delivery)
        if (out/'delivery.json').stat().st_size > request['config']['max_export_bytes']:
            raise ValueError('serialized native export exceeds declared byte bound')
        progress['completed'].append('native_delivery'); progress['phase'] = 'native_plots' if request['config']['operation']=='fit' else 'final_custody'
        _write(out/'progress.json', progress)
        if request['config']['operation']=='fit': Plots.make_plots(doc, params, results)
        _check(request['runtime_assets']); _check(request['source_files']); _check(request['selected_files'])
        runtime_result = {'schema_version':1, 'versions':observed_versions, 'device':runtime['device'], 'precision':'double',
                          'imports':_imports(request), 'source_files':request['source_files'],
                          'runtime_assets':request['runtime_assets'], 'randomness':'unchanged upstream; no new deterministic-seed claim',
                          'physics_validated':False}
        _write(out/'runtime.json', runtime_result)
        progress['completed'].append('final_custody'); progress['phase']='complete'
        _write(out/'progress.json', progress)
        return 0
    except Exception as exc:
        progress['error']={'type':type(exc).__name__, 'message':str(exc)}
        _write(out/'progress.json', progress)
        raise


if __name__ == '__main__': raise SystemExit(main())
