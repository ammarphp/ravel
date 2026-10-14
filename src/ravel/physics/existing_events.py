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
import time

from ravel.paths import module_command
from ravel.workflow.science import regular
from ravel.workflow.state_io import atomic_json, read_json
from ravel.workflow.execution import file_hash


ENVIRONMENT = {'PATH', 'SDKROOT', 'LIBRARY_PATH', 'LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'PYTHONPATH',
               'CXX', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS', 'PKG_CONFIG_PATH'}


def _weight_cap_arguments(task):
    """Only explicit cap0 is admitted; absence preserves upstream defaults."""
    if 'native_weight_cap' not in task:
        return []
    if type(task['native_weight_cap']) is not int or task['native_weight_cap'] != 0:
        raise ValueError('native_weight_cap permits only literal integer zero')
    return ['--weight-cap', '0']


def _nominal_selection(task, metadata):
    if 'nominal_weight' not in task:
        return None
    from .event_census import nominal_selection
    return nominal_selection(metadata['weight_names'], task['nominal_weight'],
                             rivet_version=task['runtime']['version'])


def _native_dispatch(task, metadata, events, out, cli_command, launched_command):
    """Retain exact dispatched arguments; no observed-weight credit."""
    if 'native_weight_cap' not in task and 'nominal_weight' not in task:
        return {}
    cap = {'native_weight_cap': 0} if 'native_weight_cap' in task else {}
    _weight_cap_arguments(task)
    selection = _nominal_selection(task, metadata)
    selected = {'nominal_weight_selection': selection} if selection else {}
    path = Path(out) / 'native-dispatch.json'
    atomic_json(path, {'schema_version': 1, 'kind': 'rivet-native-argument-declaration',
        'routine': task['routine'], 'declared_analysis_options': dict(task['options']),
        **cap, **selected, 'nominal_weight': task.get('nominal_weight', metadata['weight_names'][0]),
        'native_cli_command': cli_command, 'launched_command': launched_command,
        'events_sha256': file_hash(events), 'physics_validated': False,
        'native_effective_weights_observed': False,
        'scope': 'Exact dispatched arguments only; actual native weights, trace and RAW behavior require separate qualification.'})
    return {**cap, **selected, 'declared_analysis_options': dict(task['options']),
            'native_dispatch': {'path': path.name, 'sha256': file_hash(path)},
            'native_effective_weights_observed': False}


def validate(task):
    if not isinstance(task, dict):
        raise ValueError('analysis task must be an object')
    backend = task.get('backend')
    if backend == 'simpleanalysis-built':
        from ravel.physics.simpleanalysis_events import validate as check
        check(task)
        return
    if backend == 'simpleanalysis':
        from ravel.physics.simpleanalysis_adapter import validate as check
        check(task)
        return
    if backend == 'native-selection':
        if not {'backend', 'events', 'object_contract', 'selection'} <= task.keys() or set(task) - {'backend', 'events', 'object_contract', 'selection', 'reference', 'mapping'}:
            raise ValueError('invalid native-selection task fields')
        return
    required = {'backend', 'routine', 'source_root', 'events', 'metadata', 'runtime', 'observables', 'options', 'seed'}
    built = backend == 'rivet-built'
    if built:
        required = (required - {'source_root'}) | {'build_receipt', 'build_plan'}
    if backend not in ('rivet', 'rivet-built') or not required <= set(task) <= required | {'grounding','improvement_lineage','improvement_evaluation','native_weight_cap','centrality_preload','nominal_weight'}:
        raise ValueError('analysis backend must be rivet or native-selection with its exact fields')
    _weight_cap_arguments(task)
    if 'nominal_weight' in task:
        if type(task['nominal_weight']) is not str or not task['nominal_weight'].strip():
            raise ValueError('nominal_weight must be an explicit nonempty original name')
        if not isinstance(task['runtime'], dict) or task['runtime'].get('version') not in ('4.1.3', '4.1.4'):
            raise ValueError('explicit nominal selection requires source-bound Rivet 4.1.3 or 4.1.4 naming')
    from . import rivet_preload
    rivet_preload.validate(task)
    if ('improvement_lineage' in task) != ('improvement_evaluation' in task) or 'improvement_lineage' in task and not built:
        raise ValueError('native improvement needs built source and paired lineage/evaluation pins')
    for key in ('improvement_lineage','improvement_evaluation'):
        if key in task:
            pin=task[key]
            if type(pin) is not dict or set(pin)!={'path','sha256'} or not isinstance(pin['path'],str) or not re.fullmatch('[0-9a-f]{64}',pin['sha256']):
                raise ValueError('exact native improvement input pins required')
    if 'grounding' in task:
        pins = task['grounding']
        if not isinstance(pins, list) or not 1 <= len(pins) <= 256:
            raise ValueError('grounding requires one to 256 explicit evidence pins')
        names = set()
        for pin in pins:
            if (not isinstance(pin, dict) or set(pin) != {'path', 'sha256'}
                    or not isinstance(pin['path'], str) or not pin['path'].strip()
                    or not isinstance(pin['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', pin['sha256'])
                    or pin['path'] in names):
                raise ValueError('grounding requires distinct paths and exact SHA256 evidence pins')
            names.add(pin['path'])
    runtime = task['runtime']
    if built:
        if not isinstance(runtime, dict) or set(runtime) != {'python', 'version'}:
            raise ValueError('rivet-built runtime needs exactly bound Python and Rivet version')
        if any(not isinstance(task[k], str) or not task[k] for k in ('routine', 'build_receipt', 'build_plan', 'events', 'metadata')):
            raise ValueError('rivet-built needs explicit routine, receipt, plan, event and metadata paths')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', task['routine']):
            raise ValueError('explicit Rivet routine identifier required')
        if not isinstance(runtime['python'], str) or not runtime['python']:
            raise ValueError('bound runtime Python required')
    elif not isinstance(runtime, dict) or set(runtime) != {'python', 'executable', 'build', 'version', 'artifacts', 'environment'}:
        raise ValueError('Rivet needs exact Python, executable, build tool, version, dependency artifacts and environment')
    if not isinstance(runtime['version'], str) or not re.fullmatch(r'4\.[0-9]+\.[0-9]+', runtime['version']):
        raise ValueError('explicit supported Rivet 4 runtime version required')
    if not built and (not runtime['artifacts'] or not isinstance(runtime['artifacts'], list)):
        raise ValueError('pin the runtime libraries/modules in artifacts')
    if not built and (not isinstance(runtime['environment'], dict) or set(runtime['environment']) - ENVIRONMENT or any(not isinstance(v, str) for v in runtime['environment'].values())):
        raise ValueError('unsupported runtime environment setting')
    if type(task['seed']) is not int or not 1 <= task['seed'] < 2**31:
        raise ValueError('explicit positive smearing seed required')
    if not isinstance(task['options'], dict) or any(not re.fullmatch(r'[A-Za-z0-9_]+', k) or not re.fullmatch(r'[A-Za-z0-9_.+\-]+', str(v)) for k, v in task['options'].items()):
        raise ValueError('invalid explicit Rivet analysis options')
    paths = set()
    if not isinstance(task['observables'], list) or not task['observables']:
        raise ValueError('declare every requested observable; an empty requested-output denominator is invalid')
    for obj in task['observables']:
        if obj.get('quantity_kind') == 'native_cumulant':
            from ravel.physics.native_cumulant import validate_request
            validate_request(obj)
            if obj['path'] in paths:
                raise ValueError('duplicate requested YODA path')
            paths.add(obj['path'])
            continue
        if obj.get('quantity_kind') == 'native_categorical':
            from ravel.physics.native_categorical import validate_request
            validate_request(obj)
            if obj['path'] in paths:
                raise ValueError('duplicate requested YODA path')
            paths.add(obj['path'])
            continue
        if obj.get('quantity_kind') in ('native_derived_estimate','native_density_estimate'):
            from ravel.physics import native_estimate, native_density
            validator = native_density if obj['quantity_kind']=='native_density_estimate' else native_estimate
            validator.validate_request(obj)
            if obj['path'] in paths:
                raise ValueError('duplicate requested YODA path')
            paths.add(obj['path'])
            continue
        scalar = obj.get('quantity_kind') == 'scalar_counter'
        profile = obj.get('quantity_kind') == 'profile_mean'
        required_obj = {'path', 'axes', 'representation', 'normalization', 'unit'} | ({'quantity_kind'} if scalar or profile else set())
        if set(obj) != required_obj:
            raise ValueError('observable needs path, axes, representation, normalization and output unit')
        if not isinstance(obj['path'], str) or not obj['path'].startswith('/') or obj['path'] in paths:
            raise ValueError('duplicate or invalid requested YODA path')
        paths.add(obj['path'])
        if obj['representation'] not in (('mean',) if profile else ('integrated', 'differential')) or obj['normalization'] not in ('absolute', 'normalized'):
            raise ValueError('explicit bin representation and normalization required')
        if scalar and (obj['axes'] != [] or obj['representation'] != 'integrated' or obj['normalization'] != 'absolute'):
            raise ValueError('scalar_counter requires empty axes, integrated representation and absolute normalization')
        if not scalar and (not isinstance(obj['axes'], list) or not 1 <= len(obj['axes']) <= 2 or any(set(a) != {'name', 'unit'} or not all(isinstance(v, str) and v for v in a.values()) for a in obj['axes'])):
            raise ValueError('one or two explicit continuous axes required')
        if not isinstance(obj['unit'], str) or not obj['unit']:
            raise ValueError('observable unit required')
        from ravel.physics.rivet_export import validate_normalized_unit, validate_profile_request
        if profile:
            validate_profile_request(obj)
        elif not scalar:
            validate_normalized_unit(obj)

    if any(obj.get('quantity_kind')=='native_cumulant' for obj in task['observables']):
        from ravel.physics.native_cumulant import validate_operation
        validate_operation(task)



def reconcile_exposure(counters, exposure):
    """Rivet 4 RAW counters count independent groups, including empty selections."""
    selection = exposure.get('nominal_weight_selection')
    if selection is not None:
        from .event_census import nominal_selection, nominal_version
        if selection != nominal_selection(exposure['weight_names'], selection.get('nominal_weight'),
                                          rivet_version=nominal_version(selection)):
            raise ValueError('nominal selection differs from complete original weight census')
    for i, name in enumerate(exposure['weight_names']):
        suffix = selection['native_raw_suffixes'][i] if selection else ('' if i == 0 else '[' + name + ']')
        key = '/RAW/_EVTCOUNT' + suffix
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
    # Source-booked counters/histograms do not require a reference file.
    # Declared reference/assets above still require exact bytes. Geometry and
    # requested quantity type are verified against actual native output; native
    # initialization failures remain failures rather than fabricated binning.
    return catalog, row, files


def _grounding_inputs(task, base):
    """Bind comparison evidence without executing it or accepting its claims."""
    files = []
    for pin in task.get('grounding', []):
        path = regular(pin['path'], base)
        if path in files:
            raise ValueError('grounding paths resolve to duplicate evidence')
        if file_hash(path) != pin['sha256']:
            raise ValueError('grounding evidence bytes differ: ' + str(path))
        files.append(path)
    return files



def _native_derived_inputs(task, base):
    from ravel.physics import native_estimate, native_density, rivet_export
    files = []
    if any(obj.get('quantity_kind')=='native_cumulant' for obj in task.get('observables', [])):
        from ravel.physics.native_cumulant import quantity_inputs
        files += quantity_inputs(task['observables'], base)
    for obj in task.get('observables', []):
        if obj.get('quantity_kind') == 'native_derived_estimate':
            files += native_estimate.inputs(obj, base)
        elif obj.get('quantity_kind') == 'native_density_estimate':
            files += native_density.inputs(obj, base)
        elif obj.get('quantity_kind') == 'native_categorical':
            from ravel.physics.native_categorical import quantity_inputs
            files += quantity_inputs(obj, base)
    if files:
        files.append(Path(rivet_export.__file__).resolve())
    return list(dict.fromkeys(files))


def inputs(task, base):
    validate(task)
    if 'nominal_weight' in task:
        _nominal_selection(task, read_json(regular(task['metadata'], base)))
    if task['backend'] == 'simpleanalysis-built':
        from ravel.physics.simpleanalysis_events import inputs as selected_inputs
        return selected_inputs(task, base)
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
    if task['backend'] == 'rivet-built':
        built_files = _built_inputs(task, base)
        files = _grounding_inputs(task, base) + built_files + _native_derived_inputs(task, base)
        from . import rivet_preload
        files += rivet_preload.inputs(task, base, admitted_source_files=built_files)
        if 'improvement_lineage' in task:
            from ravel.physics import native_incumbent
            files += native_incumbent.event_inputs(task,base)
        return list(dict.fromkeys(files))
    t = dict(task)
    t['source_root'] = str((Path(base) / task['source_root']).resolve())
    _, _, files = _source_files(t)
    from . import rivet_preload
    files += rivet_preload.inputs(task, base, admitted_source_files=list(files))
    files += _grounding_inputs(task, base) + _native_derived_inputs(task, base)
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


def _call(command, cwd, env, logfile, *, work_deadline=None):
    with Path(logfile).open('wb') as stream:
        timeout=None if work_deadline is None else work_deadline-time.monotonic()
        if timeout is not None and timeout<=0:raise TimeoutError('native challenger event work deadline exhausted')
        done = subprocess.run(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT,
            **({} if timeout is None else {'timeout':timeout}))
        if stream.tell() == 0:
            stream.write(f'Process returned {done.returncode}; no console output.\n'.encode())
    if done.returncode:
        raise ValueError(f'upstream execution failed ({done.returncode}); inspect {Path(logfile).name}')


def _built_evidence(task, base):
    """Rebind the entire retained build without executing a tool or a probe."""
    from ravel.physics import routine_build
    receipt_path, plan_path = [regular(task[k], base) for k in ('build_receipt', 'build_plan')]
    if (receipt_path.name != 'build-receipt.json' or plan_path.name != 'build-plan.json'
            or receipt_path.parent != plan_path.parent):
        raise ValueError('rivet-built requires the delivered receipt and plan in their original output directory')
    plan, receipt = read_json(plan_path), read_json(receipt_path)
    plan_lineage, task_lineage = plan.get('improvement_lineage'), task.get('improvement_lineage')
    if (plan_lineage is None) != (task_lineage is None):
        raise ValueError('native event task cannot omit or transplant the observed challenger lineage')
    if plan_lineage is not None:
        from ravel.physics.native_incumbent import same_bound_pin
        if not same_bound_pin(plan_lineage,plan['base_dir'],task_lineage,base):
            raise ValueError('native event task cannot omit or transplant the observed challenger lineage')
    if plan.get('framework') != 'rivet':
        raise ValueError('selected source build is not a Rivet plugin')
    routine_build.verify_receipt(receipt, plan, plan['base_dir'], receipt_path.parent)
    routine_build.bound_routine(receipt, plan, receipt_path.parent, task['routine'])
    runtime = plan['runtime_identity']
    python = (Path(base) / task['runtime']['python']).resolve()
    facts = [*runtime['tools'].values(), *runtime['artifacts']]
    matching = [f for f in facts if Path(f['path']).resolve() == python]
    if not matching or not python.is_file() or not os.access(python, os.X_OK) or any(file_hash(python) != f['sha256'] for f in matching):
        raise ValueError('analysis Python must be an unchanged member of the bound build runtime')
    probe = runtime['tools'].get('probe')
    if probe is None or plan['probe_expectation']['executable'] != 'probe':
        raise ValueError('Rivet execution requires the same bound runtime probe executable')
    executable = Path(probe['path']).resolve()
    binary = receipt_path.parent / receipt['binary']['path']
    if any(c.isspace() for c in str(binary)):
        raise ValueError('Rivet plugin-list protocol requires a path without whitespace')
    return receipt_path, plan_path, receipt, plan, python, executable, binary


def _built_inputs(task, base):
    from ravel.physics import routine_build
    rp, pp, receipt, plan, py, _, binary = _built_evidence(task, base)
    root = rp.parent
    files = [rp, pp, root / 'source-inventory.json', binary, py,
             *[root / fact['path'] for fact in receipt.get('custody', {}).values()],
             *[root / fact['path'] for fact in receipt['logs'].values()],
             *[root / 'work/source' / fact['path'] for fact in plan['source_inventory']['files']],
             *routine_build.inputs({'backend': 'routine-build', 'input': plan['input']['path']}, plan['base_dir']),
             *[regular(task[k], base) for k in ('events', 'metadata')]]
    return list(dict.fromkeys(files))


def _run_built(task, base, out, *, work_deadline=None):
    """Consume one unchanged delivered plugin; rebuilding is never a fallback."""
    from ravel.physics.event_census import census
    rp, pp, receipt, plan, py, executable, binary = _built_evidence(task, base)
    from ravel.physics import routine_build
    selected_source = routine_build.bound_routine(receipt, plan, rp.parent, task['routine'])
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    atomic_json(out / 'selected-routine-source.json', {'schema_version': 1,
        'primary_routine': plan['routine'], 'selected_routine': task['routine'], 'binding': selected_source,
        'build_plan_sha256': file_hash(pp), 'build_receipt_sha256': file_hash(rp), 'physics_validated': False})
    events, meta_path = [regular(task[k], base) for k in ('events', 'metadata')]
    event_hash, metadata_hash = file_hash(events), file_hash(meta_path)
    metadata = read_json(meta_path)
    exposure = census(events, metadata, **({'nominal_weight': task['nominal_weight'],
        'rivet_version': task['runtime']['version']} if 'nominal_weight' in task else {}))
    atomic_json(out / 'event-census.json', exposure)
    version_declared = task['runtime']['version']
    if metadata['groups'] == 'correlated_event_number' and version_declared in ('4.0.0', '4.1.0', '4.1.1', '4.1.2'):
        raise ValueError('correlated-event adapter requires Rivet >=4.1.3 for documented subevent normalization fixes')
    work = out / 'work'
    work.mkdir(exist_ok=False)
    env = routine_build.isolated_process_environment(work / 'home', work / 'tmp')
    env.update(RIVET_RANDOM_SEED=str(task['seed']), PYTHONDONTWRITEBYTECODE='1')
    Path(env['HOME']).mkdir(); Path(env['TMPDIR']).mkdir()
    env.update(plan['runtime_identity']['environment'])
    source = rp.parent / 'work/source'
    assets = os.pathsep.join(str(source / d) for d in plan['source_inventory']['layout']['asset_dirs']) or str(source)
    env.update(RIVET_ANALYSIS_PLUGINS=str(binary), RIVET_ANALYSIS_PATH=str(source),
               RIVET_REF_PATH=assets, RIVET_INFO_PATH=assets, RIVET_DATA_PATH=assets)
    version_timeout = 15
    if work_deadline is not None:
        version_timeout = min(15, work_deadline-time.monotonic())
        if version_timeout <= 0:
            raise TimeoutError('native challenger event work deadline exhausted before version probe')
    version = subprocess.run([str(py), str(executable), '--version'], env=env, cwd=work,
                             capture_output=True, text=True, timeout=version_timeout)
    atomic_json(out / 'runtime-version.json', {'schema_version': 1,
        'command': [str(py), str(executable), '--version'], 'returncode': version.returncode,
        'stdout': version.stdout, 'stderr': getattr(version, 'stderr', '')})
    if version.returncode or version.stdout.strip() != 'rivet v' + version_declared:
        raise ValueError('actual Rivet version differs from the declared runtime: ' + version.stdout.strip())
    # Version probing can load interpreter libraries; rebind just before events.
    _built_evidence(task, base)
    from . import rivet_preload
    preload_args, preload_receipt = rivet_preload.arguments(task, base, admitted_source_files=(_built_inputs(task, base) if 'centrality_preload' in task else []), exposure=exposure)
    routine = task['routine'] + ''.join(':' + k + '=' + str(v) for k, v in sorted(task['options'].items()))
    command = [str(py), str(executable), '-a', routine, '-o', str(out / 'histograms.yoda'),
               '-x', str(metadata['cross_section_pb']), '--weight-nominal', task.get('nominal_weight', metadata['weight_names'][0]), *_weight_cap_arguments(task), *preload_args, str(events)]
    from ravel.physics import routine_build
    observation_path = out / 'loader-event-observation.json'
    native_cli_command = list(command)
    command = routine_build.rivet_loader_command(py, binary, task['routine'],
                                                 observation_path, executable, *command[2:])
    dispatch = _native_dispatch(task, metadata, events, out, native_cli_command, command)
    if preload_receipt is not None:
        atomic_json(out / 'centrality-preload.json', {**preload_receipt, 'native_cli_command': native_cli_command, 'launched_command': command})
        dispatch['centrality_preload'] = {'path': 'centrality-preload.json', 'sha256': file_hash(out / 'centrality-preload.json'), 'native_consumption_observed': False}
    _call(command, work, env, out / 'rivet.log',**({} if work_deadline is None else {'work_deadline':work_deadline}))
    # The image/registration witness and event CLI ran in the same process.
    # Missing, failed or ambiguous loader custody stops before output export.
    observation = read_json(observation_path)
    loader = routine_build.verify_loader_observation(observation, binary, task['routine'],
        env, work, (out / 'rivet.log').read_bytes(), '')
    if observation['runtime_version'] != version_declared:
        raise ValueError('event process Rivet version differs from declared runtime')
    if observation['python'] != {'path': str(py.resolve()), 'sha256': file_hash(py)}:
        raise ValueError('event process interpreter differs from bound build runtime')
    atomic_json(out / 'requested-observables.json', task['observables'])
    _call(module_command('ravel.physics.rivet_export', out / 'histograms.yoda', out / 'requested-observables.json',
                         out / 'observables.json', python=py), work, env, out / 'export.log',**({} if work_deadline is None else {'work_deadline':work_deadline}))
    quantities = read_json(out / 'observables.json')
    if set(quantities['observables']) != {obj['path'] for obj in task['observables']}:
        raise ValueError('delivered observables differ from the complete requested-output denominator')
    reconcile_exposure(quantities['event_counters'], exposure)
    if 'centrality_preload' in task:
        rivet_preload.inspect(task, base, admitted_source_files=_built_inputs(task, base))
    _built_evidence(task, base)
    if file_hash(events) != event_hash or file_hash(meta_path) != metadata_hash:
        raise ValueError('event or metadata bytes changed during Rivet execution')
    atomic_json(out / 'build-reuse.json', {'schema_version': 1, **dispatch, 'build_receipt': str(rp),
        'build_receipt_sha256': file_hash(rp), 'build_plan': str(pp), 'build_plan_sha256': file_hash(pp),
        'plugin_sha256': receipt['binary']['sha256'], 'events_sha256': event_hash,
        'metadata_sha256': metadata_hash, 'command': command,
        'loader_observation': {'path': observation_path.name, 'sha256': file_hash(observation_path)},
        'loader_custody': loader,
        'selected_routine_source': {'path': 'selected-routine-source.json', 'sha256': file_hash(out / 'selected-routine-source.json')},
        'rebuild': False, 'physics_validated': False})
    return {'status': 'passed', 'physics_validated': False, **dispatch,
            'scope': 'Observed unchanged Rivet plugin on supplied events with complete explicit output denominator',
            'routine': task['routine'], 'runtime_version': version_declared,
            'plugin_sha256': receipt['binary']['sha256'], 'build_receipt_sha256': file_hash(rp),
            'census': exposure, 'requested_observables': len(task['observables']),
            'delivered_observables': len(quantities['observables']), 'rebuild': False,
            'loader_custody': loader, 'loader_observation': observation_path.name,
            'selected_routine_source': 'selected-routine-source.json',
            'upstream_output': 'histograms.yoda', 'quantities': 'observables.json',
            'limitations': ['Supplied build evidence integrity is distinct from authenticated process custody and physics admission.',
                'Declared source/runtime assets are rebound; this is not a hermetic operating-system image.',
                'Event-level declarations, units, detector response and reference agreement require scientific review.',
                'Scalar counters retain marginal moments and finalized uncertainties; they supply no cross covariance or likelihood.']}


def execution_seconds(task,base):
    validate(task)
    if task['backend'] == 'simpleanalysis-built':
        from ravel.physics.simpleanalysis_events import execution_seconds as declared_seconds
        return declared_seconds(task,base)
    # Other supplied-event paths have no separately declared inner work ceiling;
    # their enclosing scientific-study supervisor remains the hard deadline.
    # The native incumbent path below has its own explicit work/custody budget.
    if 'improvement_lineage' not in task:return 1
    from ravel.physics import native_incumbent
    native_incumbent.event_inputs(task,base)
    return native_incumbent.execution_seconds(task['improvement_lineage'],base,180)


def run(task, base, out, *, worker_started=None):
    from ravel.physics import native_incumbent
    started=native_incumbent.worker_start(worker_started)
    validate(task)
    if task['backend'] == 'simpleanalysis-built':
        from ravel.physics.simpleanalysis_events import run as upstream
        return upstream(task, base, out)
    if task['backend'] == 'simpleanalysis':
        from ravel.physics.simpleanalysis_adapter import run as upstream
        return upstream(task, base, out)
    if task['backend'] == 'native-selection':
        from ravel.physics.reconstructed_events import run as select
        return select(task, base, out)
    _grounding_inputs(task, base)
    if task['backend'] == 'rivet-built':
        boundary=None
        if 'improvement_lineage' in task:
            from ravel.physics import native_incumbent
            native_incumbent.event_inputs(task,base)
            boundary=native_incumbent.WorkerBoundary(task['improvement_lineage'],base,out,
                work_seconds=180,worker_started=started)
        result=(_run_built(task,base,out) if boundary is None else
            _run_built(task,base,out,work_deadline=boundary.work_deadline))
        if 'improvement_lineage' in task:
            native_incumbent.event_inputs(task,base)
            result.update(improvement_lineage=task['improvement_lineage'],
                improvement_evaluation=task['improvement_evaluation'],prior_reviews_carried=[],
                challenger_replaces_incumbent=False)
            proof=boundary.finish()
            if proof is not None:result['historical_qualification']=proof
        return result
    from ravel.physics.event_census import census
    base, out = Path(base), Path(out)
    t = dict(task)
    t['source_root'] = str((base / task['source_root']).resolve())
    catalog, row, files = _source_files(t)
    events, meta_path = [regular(task[k], base) for k in ('events', 'metadata')]
    event_hash, metadata_hash = file_hash(events), file_hash(meta_path)
    metadata = read_json(meta_path)
    exposure = census(events, metadata, **({'nominal_weight': task['nominal_weight'],
        'rivet_version': task['runtime']['version']} if 'nominal_weight' in task else {}))
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
    from . import rivet_preload
    preload_args, preload_receipt = rivet_preload.arguments(task, base, admitted_source_files=files, exposure=exposure)
    routine = row['name'] + ''.join(':' + k + '=' + str(v) for k, v in sorted(task['options'].items()))
    command = [str(py), str(executable), '-a', routine, '-o', str(out / 'histograms.yoda'),
               '-x', str(metadata['cross_section_pb']), '--weight-nominal', task.get('nominal_weight', metadata['weight_names'][0]), *_weight_cap_arguments(task), *preload_args, str(regular(task['events'], base))]
    dispatch = _native_dispatch(task, metadata, regular(task['events'], base), out, command, command)
    if preload_receipt is not None:
        atomic_json(out / 'centrality-preload.json', {**preload_receipt, 'native_cli_command': command})
        dispatch['centrality_preload'] = {'path': 'centrality-preload.json', 'sha256': file_hash(out / 'centrality-preload.json'), 'native_consumption_observed': False}
    _call(command, work, env, out / 'rivet.log')
    atomic_json(out / 'requested-observables.json', task['observables'])
    _call(module_command('ravel.physics.rivet_export', out / 'histograms.yoda', out / 'requested-observables.json', out / 'observables.json', python=py),
          work, env, out / 'export.log')
    quantities = read_json(out / 'observables.json')
    reconcile_exposure(quantities['event_counters'], exposure)
    rivet_preload.inspect(task, base, admitted_source_files=files)
    if 'nominal_weight' in task and (file_hash(events) != event_hash or file_hash(meta_path) != metadata_hash):
        raise ValueError('event or metadata bytes changed during Rivet execution')
    return {'status': 'passed', 'physics_validated': False, **dispatch,
            'scope': 'Unmodified pinned Rivet routine on supplied events with explicit requested observables',
            'routine': row['id'], 'source_revision': catalog['sources']['rivet']['revision'],
            'runtime_version': runtime['version'], 'plugin_sha256': file_hash(plugin), 'census': exposure,
            'requested_observables': len(task['observables']), 'delivered_observables': len(quantities['observables']),
            'upstream_output': 'histograms.yoda', 'quantities': 'observables.json',
            'limitations': ['Rivet runtime and selected routine source can have different versions; both identities are recorded.',
                'Only declared runtime dependency artifacts are bound; this is not a hermetic operating-system image.',
                'Input event-level declaration, observable units/normalization and detector physics require scientific review.',
                'Retained YODA marginal variances do not provide a full bin covariance or an exclusion likelihood.']}


def run_in_worker(task,base,out,*,worker_started):
    """The ordinary science worker supplies its common pre-admission clock."""
    return run(task,base,out,worker_started=worker_started)


def helper_declaration(task, base_dir, output_dir, *, _session=None):
    if 'improvement_lineage' not in task:return None
    from . import native_incumbent
    return native_incumbent.helper_declaration(task['improvement_lineage'],base_dir,Path(output_dir)/'analysis',_session=_session)
