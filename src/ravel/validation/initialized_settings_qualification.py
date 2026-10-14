"""Compile and qualify one read-only initialized-settings witness on retained LHE.

The existing native_event_io shower-original CLI performs every shower and full
LHA/content join. This module composes that operation, never a second producer.
Scientific source, runtime, event protocol and output receipt are separately bound.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import platform
import re
import time
from ravel.workflow.state_io import atomic_json
from ravel.validation import mpi_observer as native
from ravel.validation import initialized_settings_checks as checks

SCOPE = 'Initialized settings witness noninterference and current wrapper continuity on32 retained original events'
ARM_IDS = ['mpi_on_disabled', 'mpi_on_enabled', 'mpi_off_disabled', 'mpi_off_enabled']


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def pin_rows(value):
    if isinstance(value, dict):
        if {'path', 'sha256'} <= set(value):
            yield value
        for item in value.values():
            yield from pin_rows(item)
    elif isinstance(value, list):
        for item in value:
            yield from pin_rows(item)


def validate(task):
    require(isinstance(task, dict) and set(task) == {'input', 'sha256'}, 'exact qualification task required')
    require(isinstance(task['input'], str) and task['input'] and isinstance(task['sha256'], str)
            and re.fullmatch('[0-9a-f]{64}', task['sha256']), 'pinned qualification input required')


def document(task, base):
    from ravel.workflow.science import regular
    validate(task)
    p = regular(task['input'], base)
    require(0 < p.stat().st_size <= 1024**2, 'bounded qualification document required')
    require(native.digest(p) == task['sha256'], 'qualification document changed')
    d = checks.strict(p.read_bytes())
    require(set(d) == {'schema_version', 'scope', 'recipe', 'runtime_inventory', 'sources', 'python',
                       'environment', 'resources', 'platform', 'assumptions'}, 'qualification fields differ')
    require(type(d['schema_version']) is int and d['schema_version'] == 1 and d['scope'] == SCOPE,
            'qualification schema/scope differs')
    require(d['platform'] == platform.platform(), 'native platform differs')
    recipe_path = regular(d['recipe']['path'], p.parent)
    require(native.digest(recipe_path) == d['recipe']['sha256'], 'reviewed recipe changed')
    recipe = checks.strict(recipe_path.read_bytes())
    require(recipe['native_counts'] == dict(compiles=1, shower_calls=4, shower_exposures=128,
            new_hard_events=0, detectors=0, conversions=0, analyses=0, fits=0, retries=0), 'scientific call census differs')
    require([(row['mpi'], row['settings_observation'], row['events'], row['encoding'], row['sidecar'])
             for row in recipe['matrix']] == [(a, s, 32, 'gzip', True)
             for a in ('on', 'off') for s in ('disabled', 'enabled')], 'exact four32event matrix required')
    require(recipe['compile']['id'] == 'build' and recipe['compile']['max_seconds'] == 120 and
            recipe['compile']['outputs'] == ['build/pythia_initialized'], 'exact reviewed build output required')
    require(recipe['compile']['argv'].count(recipe['source']['path']) == 1 and
            recipe['compile']['argv'][-2:] == ['-o', '{OUTPUT}/build/pythia_initialized'], 'compiled source/output differ')
    require(isinstance(d['sources'], list) and 1 <= len(d['sources']) <= 256, 'bounded supporting source census required')
    require(Path(d['python']).is_absolute() and any(row['path'] == d['python'] for row in d['sources']),
            'explicit pinned actual interpreter required')
    require(isinstance(d['environment'], dict) and all(isinstance(k, str) and isinstance(v, str)
            for k, v in d['environment'].items()), 'literal complete child environment required')
    for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS',
                'PYTHONDONTWRITEBYTECODE', 'DYLD_PRINT_LIBRARIES'):
        require(d['environment'].get(key) == '1', 'single thread and loader evidence required')
    r = d['resources']
    require(set(r) == {'max_seconds', 'workers', 'attempts', 'retained_bytes', 'free_floor_bytes', 'headroom_bytes',
                       'inherited_bytes', 'lineage_ceiling_bytes', 'resource_root'}, 'resource fields differ')
    require(all(type(v) is int for k, v in r.items() if k != 'resource_root'), 'exact resource integers required')
    require(r['max_seconds'] == 600 and r['workers'] == r['attempts'] == 1, 'one bounded scientific attempt required')
    require(r['retained_bytes'] == 512*1024**2 and r['free_floor_bytes'] >= 32*1024**3 and
            16*1024**2 <= r['headroom_bytes'] < r['retained_bytes'] and r['inherited_bytes'] >= 0 and
            r['inherited_bytes'] + r['retained_bytes'] <= r['lineage_ceiling_bytes'], 'storage envelope differs')
    require(Path(r['resource_root']).is_absolute(), 'absolute owned resource root required')
    require(isinstance(d['assumptions'], list) and len(d['assumptions']) >= 4 and
            all(isinstance(v, str) and v for v in d['assumptions']), 'scope/custody assumptions required')
    return p, d, recipe


def inputs(task, base, *, _session=None):
    from ravel.workflow.science import regular
    p, d, recipe = document(task, base)
    paths = [p]
    for row in [d['recipe'], d['runtime_inventory'], *d['sources'], *pin_rows(recipe)]:
        require(isinstance(row['path'], str) and re.fullmatch('[0-9a-f]{64}', row['sha256']), 'exact source pin required')
        path = regular(row['path'], p.parent, _session=_session)
        digest = _session.hash_file(path) if _session is not None else native.digest(path)
        require(digest == row['sha256'], 'qualification input bytes differ: ' + str(path))
        if 'bytes' in row:
            require(type(row['bytes']) is int and path.stat().st_size == row['bytes'], 'source byte count differs')
        paths.append(path)
    inventory = checks.strict(Path(d['runtime_inventory']['path']).read_bytes())
    for alias in inventory.get('aliases', []):
        require(set(alias) == {'path', 'resolved'} and Path(alias['path']).is_absolute() and
                str(Path(alias['path']).resolve(strict=True)) == alias['resolved'], 'runtime alias changed')
    paths.extend(native.observer_runtime_files(inventory, _session=_session))
    return list(dict.fromkeys(paths))


def _validation_inputs(task, base, session):
    return inputs(task, base, _session=session)


def input_snapshot(task, base):
    # Each invocation creates and finishes its own fresh observation. No session
    # or cached byte identity is shared with calculation, controller or end census.
    from ravel.workflow.execution import _validation_session
    session = _validation_session(base, task)
    try:
        result = {str(p): session.hash_file(p) for p in inputs(task, base, _session=session)}
        errors = session.finish()
        require(not errors, '; '.join(errors))
        return result
    finally:
        session.close()


def execution_seconds(task, base):
    return document(task, base)[1]['resources']['max_seconds']


def resource_bounds(task, base):
    _, d, recipe = document(task, base)
    return {**{k: v for k, v in d['resources'].items() if k != 'resource_root'}, **recipe['native_counts']}


def shower_stage(d, recipe, arm, state):
    ident = f'mpi_{arm}_{state}'
    require(ident in ARM_IDS, 'unknown shower arm')
    root = '{OUTPUT}/' + ident
    args = [d['python'], '-m', 'ravel.physics.native_event_io', 'shower-original',
            '--binary', '{OUTPUT}/build/pythia_initialized', '--card', recipe['cards'][arm]['path'],
            '--events', '32', '--lhe', recipe['selected_lhe']['path'], '--wrapper-source', recipe['source']['path'],
            '--run-card', recipe['selected_exposure_run_card']['path'], '--encoding', 'gzip',
            '--output', root+'/events.hepmc.gz', '--sidecar', root+'/original-lhe.jsonl',
            '--verification', root+'/transport-verification.json']
    outputs = [ident+'/events.hepmc.gz', ident+'/events.hepmc.gz.storage.json',
               ident+'/original-lhe.jsonl', ident+'/transport-verification.json']
    if state == 'enabled':
        args += ['--initialized-settings', root+'/initialized-settings.json']
        outputs.append(ident+'/initialized-settings.json')
    return {'id': ident, 'argv': args, 'outputs': outputs, 'max_seconds': 60}


def loader_census(out, stages, bound):
    generated = native.filepin(out/'build/pythia_initialized')
    known = set(bound) | {generated['path']}
    observed, system, unknown, counts = set(), set(), set(), {}
    for stage in stages:
        text = (out/'native-logs'/(stage['id']+'.log')).read_text(errors='replace')
        images = re.findall(r'^dyld\[\d+\]: <[0-9A-Fa-f-]+> (/[^\r\n]+)$', text, re.MULTILINE)
        counts[stage['id']] = len(images)
        require(images, 'actual native loader observation missing')
        for raw in images:
            if raw.startswith(('/usr/lib/', '/System/Library/', '/System/Volumes/Preboot/Cryptexes/')):
                system.add(raw)
            else:
                path = str(Path(raw).resolve())
                (observed if path in known else unknown).add(path)
    result = dict(built_candidate=generated, observed_bound_images=sorted(observed),
                  system_platform_bound_images=sorted(system), unbound_images=sorted(unknown), stage_trace_counts=counts)
    atomic_json(out/'loader-census.json', result)
    require(not unknown, 'unbound actual native image')
    return result


def run(task, base, output_dir):
    start = time.monotonic()
    out = Path(output_dir).resolve()
    require(not out.exists() or (out.is_dir() and not any(out.iterdir())), 'fresh empty qualification output required')
    out.mkdir(parents=True, exist_ok=True)
    p, d, recipe = document(task, base)
    require(out.is_relative_to(Path(d['resources']['resource_root']).resolve()), 'output outside measured resource root')
    (out/'native-logs').mkdir()
    guard = native.Guard(d['resources'], out/'resource-telemetry.jsonl')
    stages = [recipe['compile']] + [shower_stage(d, recipe, a, s) for a in ('on', 'off') for s in ('disabled', 'enabled')]
    result = {'status': 'failed', 'scope': SCOPE, 'physics_validated': False, 'successful_end_custody': False,
              'planned_native_counts': recipe['native_counts'], 'commands': [], 'transports': {}, 'snapshots': {}, 'pairs': {}}
    def save():
        result['elapsed_seconds'] = time.monotonic()-start
        atomic_json(out/'initialized-settings-qualification.json', result)
    save()
    try:
        before = input_snapshot(task, base)
        schema = checks.strict(Path(recipe['schema']['path']).read_bytes())
        deadline = start + d['resources']['max_seconds'] - 20
        for stage in stages:
            result['active_stage'] = stage['id']; save()
            receipt = native.child(stage, out, d['environment'], deadline, guard)
            result['commands'].append(receipt); save()
            if stage['id'] != 'build':
                arm, state = stage['id'].split('_')[1:]
                folder = out/stage['id']
                report = checks.strict((folder/'transport-verification.json').read_bytes())
                command = report['producer']['command']
                require(command[:2] == [str(out/'build/pythia_initialized'), recipe['cards'][arm]['path']] and
                        command[3] == '32', 'actual producer binary/card/count differs')
                result['transports'][stage['id']] = checks.transport(report, events=32, command=command); save()
                if state == 'enabled':
                    result['snapshots'][arm] = checks.snapshot(folder/'initialized-settings.json', schema,
                        command=command, compiled_source_path=recipe['source']['path'],
                        expected_settings=recipe['post_init_expected_per_arm'][arm],
                        expected_masses=recipe['source_bound_mass_expectations_GeV']); save()
                    def files(name):
                        return {'hepmc': out/name/'events.hepmc.gz', 'sidecar': out/name/'original-lhe.jsonl'}
                    reference = {k: v['path'] for k, v in recipe['accepted_current_references'][arm].items()}
                    result['pairs'][arm] = checks.pair(files(f'mpi_{arm}_disabled'), files(stage['id']), reference, encoding='gzip'); save()
        result['loader_census'] = loader_census(out, stages, before); save()
        require(before == input_snapshot(task, base), 'qualification source/runtime changed')
        require(time.monotonic() < start+d['resources']['max_seconds'], 'qualification total deadline exceeded')
        result.update(status='passed', successful_end_custody=True, input_pins=before, active_stage=None)
    except Exception as exc:
        result['error'] = {'type': type(exc).__name__, 'message': str(exc)}
    # Include started and failed child receipts rather than only returned calls.
    result['commands'] = [checks.strict(q.read_bytes()) for stage in stages
                          if (q := out/'native-logs'/(stage['id']+'.command.json')).is_file()]
    result['limits'] = ['One compile/four32event showers only; future populations/cards require their own full transport and settings witness.',
                        'Same-seed byte equality qualifies this observation path, not detector response, MPI effect, historical settings or final author execution.',
                        'Guard samples disk usage; the common supervisor owns the inherited child group and final process cleanup.',
                        'Snapshot RNG/PID/version fields are observations, with independent source/runtime/binary/exit custody required.']
    save()
    try:
        guard.check(final=True)
    except Exception as exc:
        result.update(status='failed', successful_end_custody=False, postcondition_error={'type':type(exc).__name__, 'message':str(exc)})
        save()
    return result
