"""Supervised fresh shower of a complete retained nominal unmerged LHE cohort.

The existing original-LHA producer/publication path owns transport verification.
An initialized snapshot does not prove shower completion or model applicability.
No compilation, generator, detector, analysis or likelihood is launched here.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil

from ravel.physics import lhe_provenance, native_event_io
from ravel.workflow.state_io import atomic_json

SCOPE = 'Complete retained-LHE fresh shower and original-LHA transport with separately observed initialized settings'
INITIALIZED_SCHEMA_SHA256 = 'cac4d6765a2ed2c78b723b11eb4325735c03acd60d5f596b144e03564b4ceb92'
IDS = [1000011, 2000011, 1000013, 2000013, 1000015, 2000015, 1000022, 15]


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def keys(value, required, optional=()):
    require(isinstance(value, dict) and set(required) <= set(value) <= set(required) | set(optional),
            'missing or unknown retained-shower fields')


def validate(task):
    keys(task, ('input', 'contract_sha256'))
    require(isinstance(task['input'], str) and task['input'] and isinstance(task['contract_sha256'], str)
            and len(task['contract_sha256']) == 64, 'pinned shower contract required')
    return task


def document(task, base):
    from ravel.workflow.science import regular
    validate(task)
    path = regular(task['input'], base)
    require(0 < path.stat().st_size <= 1024**2, 'bounded shower contract required')
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == task['contract_sha256'], 'shower contract bytes differ')
    value = lhe_provenance.strict_json(raw)
    keys(value, ('schema_version', 'kind', 'scope', 'sources', 'roles', 'producer', 'runtime_inventory',
                 'environment', 'resources', 'encoding', 'post_init_expectations', 'platform', 'assumptions'))
    require(type(value['schema_version']) is int and value['schema_version'] == 1 and
            value['kind'] == 'retained-shower-contract' and value['scope'] == SCOPE, 'shower contract scope differs')
    require(value['platform'] == platform.platform(), 'native platform differs')
    require(value['encoding'] in ('plain', 'gzip'), 'explicit shower encoding required')
    require(isinstance(value['sources'], list) and 7 <= len(value['sources']) <= 256, 'bounded source graph required')
    ids = set()
    for row in value['sources']:
        keys(row, ('id', 'path', 'sha256', 'size'))
        require(isinstance(row['id'], str) and row['id'] and row['id'] not in ids, 'unique source identity required')
        ids.add(row['id'])
        require(isinstance(row['path'], str) and isinstance(row['sha256'], str) and len(row['sha256']) == 64 and
                type(row['size']) is int and row['size'] >= 0, 'exact source pin required')
    keys(value['roles'], ('binary', 'wrapper_source', 'lhe', 'run_card', 'shower_card', 'settings_schema', 'producer_evidence'))
    require(len(set(value['roles'].values())) == 7 and set(value['roles'].values()) <= ids,
            'complete distinct producer/event/card/schema/evidence roles required')
    require(value['runtime_inventory'] in ids, 'bound runtime inventory required')
    keys(value['producer'], ('binary_sha256', 'wrapper_source_sha256', 'compiled_source_path',
                             'compiled_header_version_integer', 'qualification_status'))
    require(value['producer']['compiled_header_version_integer'] == 8312 and
            type(value['producer']['compiled_header_version_integer']) is int and
            value['producer']['qualification_status'] == 'supplied_evidence_requires_scope_review' and
            isinstance(value['producer']['compiled_source_path'], str) and value['producer']['compiled_source_path'],
            'explicit source/version/evidence boundary required')
    resources = value['resources']
    keys(resources, ('events', 'workers', 'attempts', 'builds', 'generation', 'analyses', 'max_seconds',
                     'retained_bytes', 'free_floor_bytes', 'storage_guard'))
    require(all(type(resources[k]) is int for k in resources if k != 'storage_guard'), 'exact resource integers required')
    require(1 <= resources['events'] <= 20000 and resources['workers'] == resources['attempts'] == 1 and
            resources['builds'] == resources['generation'] == resources['analyses'] == 0 and
            1 <= resources['max_seconds'] <= 86400 and resources['retained_bytes'] > 0 and
            resources['free_floor_bytes'] >= 0 and resources['storage_guard'] == 'pre_and_post_checks_not_quota',
            'retained shower resource scope differs')
    require(isinstance(value['environment'], dict) and all(isinstance(k, str) and k and
            (v is None or isinstance(v, str)) for k, v in value['environment'].items()), 'explicit native environment required')
    for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
        require(value['environment'].get(name) == '1', 'single-thread native environment required')
    expected = value['post_init_expectations']
    keys(expected, ('flags', 'modes', 'parms', 'words'))
    require(all(isinstance(v, dict) for v in expected.values()), 'typed observed-setting expectations required')
    for section, required in {'flags': ('PartonLevel:MPI', 'SLHA:useDecayTable', 'Random:setSeed'),
                              'modes': ('Tune:pp', 'SLHA:readFrom', 'Beams:frameType', 'Random:seed'),
                              'parms': (), 'words': ('Beams:LHEF', 'SLHA:file')}.items():
        require(set(required) <= set(expected[section]), 'explicit MPI/SLHA/seed/beam observation expectations required')
    require(isinstance(value['assumptions'], list) and len(value['assumptions']) >= 3 and
            all(isinstance(v, str) and v.strip() for v in value['assumptions']), 'source/application/uncertainty assumptions required')
    return path, value


def inputs(task, base, *, _session=None):
    from ravel.workflow.science import regular
    from ravel.validation.mpi_observer import observer_runtime_files
    path, value = document(task, base)
    files = [path]
    resolved = {}
    for row in value['sources']:
        source = regular(row['path'], path.parent, _session=_session)
        require(source not in files, 'source graph aliases or repeats a path')
        observed = _session.hash_file(source) if _session is not None else lhe_provenance.pin(source)['sha256']
        require(source.stat().st_size == row['size'] and observed == row['sha256'], 'shower source pin differs')
        files.append(source)
        resolved[row['id']] = source
    roles = {name: resolved[ident] for name, ident in value['roles'].items()}
    require(value['producer']['binary_sha256'] == next(r['sha256'] for r in value['sources'] if r['id'] == value['roles']['binary'])
            and value['producer']['wrapper_source_sha256'] == next(r['sha256'] for r in value['sources'] if r['id'] == value['roles']['wrapper_source']),
            'producer source/binary declarations differ from supplied pins')
    require(os.access(roles['binary'], os.X_OK), 'executable supplied producer required')
    from jsonschema import Draft202012Validator
    require(lhe_provenance.pin(roles['settings_schema'])['sha256'] == INITIALIZED_SCHEMA_SHA256,
            'exact reviewed initialized witness schema required')
    schema = lhe_provenance.strict_json(roles['settings_schema'].read_bytes())
    Draft202012Validator.check_schema(schema)
    require(schema.get('properties', {}).get('type', {}).get('const') == 'pythia_initialized_settings',
            'initialized witness schema required')
    for section, expected in value['post_init_expectations'].items():
        fields = schema['properties']['post_init_settings']['properties'][section]['properties']
        require(set(expected) <= set(fields), 'unobserved post-init expectation field')
        for key, item in expected.items():
            Draft202012Validator(fields[key]).validate(item)
            _finite(item)
    require(value['post_init_expectations']['words']['Beams:LHEF'] == str(roles['lhe']) and
            value['post_init_expectations']['modes']['Beams:frameType'] == 4,
            'post-init LHE/beam expectations differ from bound original input')
    inventory = lhe_provenance.strict_json(resolved[value['runtime_inventory']].read_bytes())
    for alias in inventory.get('aliases', []):
        keys(alias, ('path', 'resolved'))
        require(Path(alias['path']).is_absolute() and str(Path(alias['path']).resolve(strict=True)) == alias['resolved'],
                'supplied native runtime alias changed')
    runtime = observer_runtime_files(inventory, _session=_session)
    return list(dict.fromkeys([*files, *runtime]))


def _validation_inputs(task, base, session):
    return inputs(task, base, _session=session)


def execution_seconds(task, base):
    return document(task, base)[1]['resources']['max_seconds']


def _finite(value):
    if type(value) is float:
        require(math.isfinite(value), 'nonfinite initialized snapshot value')
    elif isinstance(value, dict):
        for item in value.values():
            _finite(item)
    elif isinstance(value, list):
        for item in value:
            _finite(item)


def verify_initialized(value, schema, contract, *, card, events, expected_argv):
    from jsonschema import Draft202012Validator
    Draft202012Validator(schema).validate(value)
    _finite(value)
    require(value['request'] == {'config_path': str(card), 'count_override': str(events), 'argv': expected_argv},
            'actual initialized request differs')
    require(value['producer']['compiled_source_path'] == contract['producer']['compiled_source_path'] and
            value['producer']['compiled_header_version_integer'] == contract['producer']['compiled_header_version_integer'],
            'observed compiled source/version differs from declared producer evidence')
    particles = value['post_init_particles']
    require([row['pdg_id'] for row in particles] == IDS, 'all eight ordered particle observations required')
    for particle in particles:
        if particle['present']:
            channels = particle['channels']
            require(particle['channel_count'] == len(channels) and
                    [row['index'] for row in channels] == list(range(len(channels))), 'particle channel census differs')
    for section, expected in contract['post_init_expectations'].items():
        observed = value['post_init_settings'][section]
        require(set(expected) <= set(observed) and all(type(observed[key]) is type(target) and observed[key] == target
                for key, target in expected.items()), 'post-init selected setting differs')
    require(value['internal_rng']['unchanged_by_snapshot'] is True, 'read-only RNG snapshot required')
    return {'complete': True, 'phase': value['phase'], 'observed_expectations': contract['post_init_expectations'],
            'particle_ids': IDS, 'event_generation_complete': False,
            'pid_is_supplementary_observation_not_independent_authentication': True}


def run(task, base, out):
    path, contract = document(task, base)
    before = {str(p): lhe_provenance.pin(p) for p in inputs(task, base)}
    require(all(os.environ.get(key) == value for key, value in contract['environment'].items()),
            'actual native environment differs from prospective contract')
    out = Path(out).resolve()
    require(not out.exists() and not out.is_symlink(), 'fresh retained-shower output directory required')
    out.mkdir(parents=True, exist_ok=False)
    resources = contract['resources']
    require(shutil.disk_usage(out).free >= resources['free_floor_bytes'], 'declared free-space floor unavailable')
    sources = {row['id']: Path(row['path']) if Path(row['path']).is_absolute() else path.parent/row['path']
               for row in contract['sources']}
    roles = {name: sources[ident].resolve() for name, ident in contract['roles'].items()}
    from ravel.validation.lhe_check import check_science
    check_science(roles['lhe'], output=out / 'shower-input.lhe_check.json')
    events = out / ('events.hepmc.gz' if contract['encoding'] == 'gzip' else 'events.hepmc')
    snapshot_path = out/'initialized-settings.json'
    native_event_io.shower_original(roles['binary'], roles['shower_card'], events, resources['events'],
        lhe=roles['lhe'], sidecar=out/'original-lhe.jsonl', verification=out/'transport-verification.json',
        wrapper_source=roles['wrapper_source'], run_card=roles['run_card'], encoding=contract['encoding'],
        initialized_settings=snapshot_path)
    transport = lhe_provenance.strict_json((out/'transport-verification.json').read_bytes())
    require(transport['status'] == 'content_verified' and transport['joined_events'] == resources['events'] and
            transport['producer']['returncode'] == 0, 'complete actual original-LHA transport required')
    schema = lhe_provenance.strict_json(roles['settings_schema'].read_bytes())
    observed_snapshot, observed_pin = native_event_io.read_initialized_settings(snapshot_path)
    require(observed_pin == transport['initialized_settings'], 'published initialized snapshot differs from transport receipt')
    initialized = verify_initialized(observed_snapshot, schema, contract,
        card=roles['shower_card'], events=resources['events'], expected_argv=transport['producer']['command'])
    require(before == {str(p): lhe_provenance.pin(p) for p in inputs(task, base)}, 'source/runtime changed during shower')
    artifacts = [lhe_provenance.pin(p) for p in sorted(out.iterdir()) if p.is_file()]
    require(sum(row['bytes'] for row in artifacts) <= resources['retained_bytes'] and
            shutil.disk_usage(out).free >= resources['free_floor_bytes'], 'post-shower storage scope exceeded')
    result = {'status': 'passed', 'physics_validated': False, 'scope': SCOPE,
              'input': {'path': str(path), 'sha256': task['contract_sha256']}, 'input_pins': list(before.values()),
              'events': resources['events'], 'encoding': contract['encoding'], 'artifacts': artifacts,
              'transport_verified': True, 'initialized_settings': initialized,
              'binary_compilation_provenance_inferred': False, 'producer_evidence': lhe_provenance.pin(roles['producer_evidence']),
              'resources': resources, 'native_effective_scope': 'Only schema-enumerated post-init getters; card is retained separately',
              'limitations': ['New supplied binary/source/runtime evidence needs actual scoped independent review.',
                  'Initialization getters/header presence do not establish all decay tables were imported; retain warnings and channel snapshots.',
                  'No detector, event selection, fiducial efficiency, covariance law, likelihood or model applicability is certified.',
                  'Storage checks are pre/post observations, not a quota or peak RSS measurement; supervisor owns deadline and process cleanup.',
                  'No prior shower settings/history or full-model inclusive cross section is inferred from this fresh declared cohort.']}
    completion = out/'retained-shower.json'
    atomic_json(completion, result)
    # The completion record is itself retained output. Check the actual final
    # directory after publication, rather than accepting only its payload files.
    retained_total = sum(p.stat().st_size for p in out.iterdir() if p.is_file())
    free_bytes = shutil.disk_usage(out).free
    if retained_total > resources['retained_bytes'] or free_bytes < resources['free_floor_bytes']:
        result.update(status='failed', failure='post-publication storage scope exceeded',
                      storage_postcondition={'retained_bytes_observed': retained_total,
                                             'free_bytes_observed': free_bytes,
                                             'completion_record_included': True})
        atomic_json(completion, result)
        require(False, 'post-publication storage scope exceeded')
    return result
