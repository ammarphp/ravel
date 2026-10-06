"""Admission and execution of immutable existing events through preserved analyses.

Rivet source is compiled unmodified with one build worker in a private directory.
Reconstructed-object selections use the existing shared native primitives.
"""
import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import subprocess

from ravel.paths import module_command
from ravel.workflow.science import regular
from ravel.workflow.state_io import atomic_json, read_json
from ravel.workflow.execution import file_hash


ENVIRONMENT = {'PATH', 'SDKROOT', 'LIBRARY_PATH', 'LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'PYTHONPATH',
               'CXX', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS', 'PKG_CONFIG_PATH'}


def validate(task):
    if not isinstance(task, dict):
        raise ValueError('analysis task must be an object')
    backend = task.get('backend')
    if backend == 'simpleanalysis':
        from ravel.physics.simpleanalysis_adapter import validate as check
        check(task)
        return
    if backend == 'native-selection':
        if not {'backend', 'events', 'object_contract', 'selection'} <= task.keys() or set(task) - {'backend', 'events', 'object_contract', 'selection', 'reference', 'mapping'}:
            raise ValueError('invalid native-selection task fields')
        return
    required = {'backend', 'routine', 'source_root', 'events', 'metadata', 'runtime', 'observables', 'options', 'seed'}
    if backend != 'rivet' or set(task) != required:
        raise ValueError('analysis backend must be rivet or native-selection with its exact fields')
    runtime = task['runtime']
    if not isinstance(runtime, dict) or set(runtime) != {'python', 'executable', 'build', 'version', 'artifacts', 'environment'}:
        raise ValueError('Rivet needs exact Python, executable, build tool, version, dependency artifacts and environment')
    if not re.fullmatch(r'4\.[0-9]+\.[0-9]+', runtime['version']):
        raise ValueError('explicit supported Rivet 4 runtime version required')
    if not runtime['artifacts'] or not isinstance(runtime['artifacts'], list):
        raise ValueError('pin the runtime libraries/modules in artifacts')
    if not isinstance(runtime['environment'], dict) or set(runtime['environment']) - ENVIRONMENT or any(not isinstance(v, str) for v in runtime['environment'].values()):
        raise ValueError('unsupported runtime environment setting')
    if type(task['seed']) is not int or not 1 <= task['seed'] < 2**31:
        raise ValueError('explicit positive smearing seed required')
    if not isinstance(task['options'], dict) or any(not re.fullmatch(r'[A-Za-z0-9_]+', k) or not re.fullmatch(r'[A-Za-z0-9_.+\-]+', str(v)) for k, v in task['options'].items()):
        raise ValueError('invalid explicit Rivet analysis options')
    paths = set()
    if not isinstance(task['observables'], list) or not task['observables']:
        raise ValueError('declare every requested observable; an empty requested-output denominator is invalid')
    for obj in task['observables']:
        if set(obj) != {'path', 'axes', 'representation', 'normalization', 'unit'}:
            raise ValueError('observable needs path, axes, representation, normalization and output unit')
        if not isinstance(obj['path'], str) or not obj['path'].startswith('/') or obj['path'] in paths:
            raise ValueError('duplicate or invalid requested YODA path')
        paths.add(obj['path'])
        if obj['representation'] not in ('integrated', 'differential') or obj['normalization'] not in ('absolute', 'normalized'):
            raise ValueError('explicit bin representation and normalization required')
        if not isinstance(obj['axes'], list) or not 1 <= len(obj['axes']) <= 2 or any(set(a) != {'name', 'unit'} or not all(isinstance(v, str) and v for v in a.values()) for a in obj['axes']):
            raise ValueError('one or two explicit continuous axes required')
        if not isinstance(obj['unit'], str) or not obj['unit']:
            raise ValueError('observable unit required')
        from ravel.physics.rivet_export import validate_normalized_unit
        validate_normalized_unit(obj)


def reconcile_exposure(counters, exposure):
    """Rivet 4 RAW counters count independent groups, including empty selections."""
    for i, name in enumerate(exposure['weight_names']):
        key = '/RAW/_EVTCOUNT' + ('' if i == 0 else '[' + name + ']')
        if key not in counters:
            raise ValueError('missing exact global Rivet event counter: ' + key)
        actual = counters[key]
        expected = {'entries': exposure['independent_groups'], 'sumw': exposure['sumw'][i],
                    'sumw2': exposure['group_weight_second_moments'][i][i]}
        if any(not math.isfinite(actual[k]) or not math.isclose(actual[k], v, rel_tol=1e-9, abs_tol=1e-10)
               for k, v in expected.items()):
            raise ValueError('Rivet event population or weighted moments differ from the all-event census: ' + key)


def _source_files(task):
    from ravel.analysis_catalog import load_catalog, resolve, verify_source
    catalog = load_catalog()
    row = resolve(catalog, task['routine'])
    if row['framework'] != 'rivet':
        raise ValueError('Rivet backend requires an exact Rivet routine')
    check = verify_source(catalog, row, task['source_root'])
    if check['status'] != 'PASS':
        raise ValueError('routine source verification failed: ' + '; '.join(check['issues']))
    root = Path(task['source_root']).resolve()
    facts = row['source_files'] + row['reference_files'] + [row['metadata_file']]
    for asset in row.get('external_assets', []):
        facts += asset['matches']
    files = []
    for fact in facts:
        path = regular(fact['path'], root)
        content = path.read_bytes()
        if hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest() != fact['git_blob']:
            raise ValueError('selected source/reference bytes differ from catalogue: ' + fact['path'])
        files.append(path)
    if not row['reference_files']:
        raise ValueError('this adapter requires pinned reference binning; supply a dedicated adapter for source-booked-only routines')
    return catalog, row, files


def inputs(task, base):
    validate(task)
    if task['backend'] == 'simpleanalysis':
        from ravel.physics.simpleanalysis_adapter import inputs as selected_inputs
        return selected_inputs(task, base)
    if task['backend'] == 'native-selection':
        from ravel.physics.reconstructed_events import object_contract, selection_spec
        files = [regular(task[k], base) for k in ('events', 'object_contract', 'selection')]
        contract = object_contract(read_json(files[1]))
        selection_spec(read_json(files[2]), contract)
        files += [regular(p, base) for p in contract['response_evidence']]
        for key in ('reference', 'mapping'):
            if key in task:
                files.append(regular(task[key], base))
        if 'mapping' in task:
            files.append(regular(read_json(regular(task['mapping'], base))['workspace'], base))
        return files
    t = dict(task)
    t['source_root'] = str((Path(base) / task['source_root']).resolve())
    _, _, files = _source_files(t)
    files += [regular(task[k], base) for k in ('events', 'metadata')]
    for key in ('python', 'executable', 'build'):
        # Executable aliases (e.g. python -> python3.12) are resolved and their
        # target identity pinned; scientific data paths cannot use symlinks.
        p = (Path(base) / task['runtime'][key]).resolve()
        if not p.is_file():
            raise ValueError('missing runtime ' + key)
        files.append(p)
    for value in task['runtime']['artifacts']:
        p = (Path(base) / value).resolve()
        if not p.exists():
            raise ValueError('missing declared runtime artifact: ' + str(p))
        files.append(p)
    return files


def _call(command, cwd, env, logfile):
    with Path(logfile).open('wb') as stream:
        done = subprocess.run(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT)
        if stream.tell() == 0:
            stream.write(f'Process returned {done.returncode}; no console output.\n'.encode())
    if done.returncode:
        raise ValueError(f'upstream execution failed ({done.returncode}); inspect {Path(logfile).name}')


def run(task, base, out):
    validate(task)
    if task['backend'] == 'simpleanalysis':
        from ravel.physics.simpleanalysis_adapter import run as upstream
        return upstream(task, base, out)
    if task['backend'] == 'native-selection':
        from ravel.physics.reconstructed_events import run as select
        return select(task, base, out)
    from ravel.physics.event_census import census
    base, out = Path(base), Path(out)
    t = dict(task)
    t['source_root'] = str((base / task['source_root']).resolve())
    catalog, row, files = _source_files(t)
    metadata = read_json(regular(task['metadata'], base))
    exposure = census(regular(task['events'], base), metadata)
    atomic_json(out / 'event-census.json', exposure)
    if metadata['groups'] == 'correlated_event_number' and task['runtime']['version'] in ('4.0.0', '4.1.0', '4.1.1', '4.1.2'):
        raise ValueError('correlated-event adapter requires Rivet >=4.1.3 for documented subevent normalization fixes')
    runtime = task['runtime']
    py, executable, build = [(base / runtime[k]).resolve() for k in ('python', 'executable', 'build')]
    work = out.parent / 'work'
    work.mkdir(exist_ok=False)
    env = {k: v for k, v in os.environ.items() if not k.startswith('RIVET_')}
    env.update(runtime['environment'])
    env.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', RIVET_RANDOM_SEED=str(task['seed']), PYTHONDONTWRITEBYTECODE='1')
    version = subprocess.run([str(py), str(executable), '--version'], env=env, cwd=work, capture_output=True, text=True, timeout=15)
    if version.returncode or version.stdout.strip() != 'rivet v' + runtime['version']:
        raise ValueError('actual Rivet version differs from the declared runtime: ' + version.stdout.strip())
    # Copy the verified upstream bytes unchanged, with their reference binning.
    for path in files:
        target = work / path.name
        if target.exists():
            raise ValueError('upstream input basenames collide')
        shutil.copyfile(path, target)
    sources = [str(work / Path(f['path']).name) for f in row['source_files']]
    plugin = work / 'RivetFrozen.so'
    _call([str(build), '-j', '1', str(plugin), *sources], work, env, out / 'build.log')
    if not plugin.is_file():
        raise ValueError('upstream build exited without the requested plugin')
    if any(c.isspace() for c in str(plugin)):
        raise ValueError('Rivet plugin-list protocol requires a run path without whitespace')
    env.update(RIVET_ANALYSIS_PLUGINS=str(plugin), RIVET_ANALYSIS_PATH=str(work), RIVET_REF_PATH=str(work), RIVET_INFO_PATH=str(work))
    routine = row['name'] + ''.join(':' + k + '=' + str(v) for k, v in sorted(task['options'].items()))
    command = [str(py), str(executable), '-a', routine, '-o', str(out / 'histograms.yoda'),
               '-x', str(metadata['cross_section_pb']), '--weight-nominal', metadata['weight_names'][0], str(regular(task['events'], base))]
    _call(command, work, env, out / 'rivet.log')
    atomic_json(out / 'requested-observables.json', task['observables'])
    _call(module_command('ravel.physics.rivet_export', out / 'histograms.yoda', out / 'requested-observables.json', out / 'observables.json', python=py),
          work, env, out / 'export.log')
    quantities = read_json(out / 'observables.json')
    reconcile_exposure(quantities['event_counters'], exposure)
    return {'status': 'passed', 'physics_validated': False,
            'scope': 'Unmodified pinned Rivet routine on supplied events with explicit requested observables',
            'routine': row['id'], 'source_revision': catalog['sources']['rivet']['revision'],
            'runtime_version': runtime['version'], 'plugin_sha256': file_hash(plugin), 'census': exposure,
            'requested_observables': len(task['observables']), 'delivered_observables': len(quantities['observables']),
            'upstream_output': 'histograms.yoda', 'quantities': 'observables.json',
            'limitations': ['Rivet runtime and selected routine source can have different versions; both identities are recorded.',
                'Only declared runtime dependency artifacts are bound; this is not a hermetic operating-system image.',
                'Input event-level declaration, observable units/normalization and detector physics require scientific review.',
                'Retained YODA marginal variances do not provide a full bin covariance or an exclusion likelihood.']}
