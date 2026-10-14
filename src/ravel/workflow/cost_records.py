"""Cost observations and forecasts with separate units and explicit missing data.

This module records evidence. It grants no execution or scientific authority.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path

from .state_io import file_lock, read_json

DIMENSIONS = ('wall_hours', 'cpu_hours', 'peak_ram_gb', 'disk_gb', 'events',
              'model_calls', 'model_tokens', 'queue_hours')
STATUSES = ('calibrated', 'historical', 'uncalibrated', 'unknown')
CONTRACT_DIMENSIONS = ('wall_hours', 'cpu_hours', 'disk_gb', 'events', 'model_calls')


def resource_vector(**values):
    """Missing dimensions remain null; zero requires an explicit observation."""
    if set(values) - set(DIMENSIONS):
        raise ValueError('unknown resource dimension')
    for key, value in values.items():
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise ValueError(f'{key} requires a finite nonnegative number or null')
    return {key: values.get(key) for key in DIMENSIONS}


def aggregate_resources(vectors):
    """Sum each additive dimension separately; take maxima for RAM and disk.

Disk is a usage/footprint observation, not cumulative bytes written. Unknown
members propagate; an empty census establishes no measured total.
"""
    vectors = [resource_vector(**v) for v in vectors]
    result = resource_vector()
    for key in DIMENSIONS:
        values = [v[key] for v in vectors]
        if values and all(v is not None for v in values):
            result[key] = max(values) if key in ('peak_ram_gb', 'disk_gb') else sum(values)
    return result


def make_record(cost_class, status, profile, basis, *, uncertainty=None, **resources):
    """The contract's five scalar dimensions are projections of one full vector."""
    if not isinstance(cost_class, str) or not cost_class or status not in STATUSES:
        raise ValueError('cost class and calibration status required')
    if not isinstance(basis, str) or not basis:
        raise ValueError('plain-language cost basis required')
    profile = deepcopy(profile) if profile is not None else {k: None for k in ('process', 'configuration', 'machine')}
    if not isinstance(profile, dict) or set(profile) != {'process', 'configuration', 'machine'}:
        raise ValueError('cost profile requires process, configuration and machine')
    vector = resource_vector(**resources)
    intervals = deepcopy(uncertainty)
    if intervals is not None:
        if not isinstance(intervals, dict) or set(intervals) - set(DIMENSIONS):
            raise ValueError('uncertainty intervals require resource dimensions')
        for key, bounds in intervals.items():
            if not isinstance(bounds, list) or len(bounds) != 2:
                raise ValueError('uncertainty interval requires lower and upper bounds')
            resource_vector(**{key: bounds[0]}); resource_vector(**{key: bounds[1]})
            if None in bounds or bounds[0] > bounds[1] or vector[key] is None or not bounds[0] <= vector[key] <= bounds[1]:
                raise ValueError('uncertainty interval requires an observed dimension and ordered bounds')
    return {'cost_class': cost_class, 'status': status, 'resource_vector': vector,
            'profile': profile, 'uncertainty': intervals, 'basis': basis,
            **{k: vector[k] for k in CONTRACT_DIMENSIONS}}


def render(record):
    """Plain-language display never formats an unknown value as zero."""
    return '\n'.join([f"Cost class: {record['cost_class']}; status: {record['status']}."] +
        [f'{key}: ' + ('unknown' if value is None else str(value))
         for key, value in record['resource_vector'].items()])


def observation_profile(observation):
    # Existing profile_sha256 binds process and all non-variable configuration.
    return {'process': observation.get('mode'), 'configuration': observation['profile_sha256'],
            'machine': deepcopy(observation['machine'])}


def _validate_observation(observation):
    if observation.get('kind') != 'supervised_pilot_observation' or not observation.get('receipts'):
        raise ValueError('completed pilot receipt evidence required for the catalogue')
    if any(type(observation.get(key)) not in (int, float) or not math.isfinite(observation[key])
           or observation[key] < 0 for key in ('wall_seconds', 'output_bytes')):
        raise ValueError('finite measured duration and output bytes required')
    resource_vector(wall_hours=observation['wall_seconds'] / 3600,
                    disk_gb=observation['output_bytes'] / 1e9)
    if (type(observation.get('units')) not in (int, float) or not math.isfinite(observation['units'])
            or observation['units'] <= 0 or observation['wall_seconds'] <= 0):
        raise ValueError('positive observed units and duration required')
    elapsed = 0
    seen = set()
    successful = True
    for pin in observation['receipts']:
        path = Path(pin['path'])
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != pin['sha256'] or len(raw) != pin['size']:
            raise ValueError('observed receipt changed')
        if str(path.resolve()) in seen:
            raise ValueError('duplicate observed receipt')
        seen.add(str(path.resolve()))
        receipt = read_json(path)
        if receipt.get('status') not in ('succeeded', 'failed', 'interrupted'):
            raise ValueError('completed terminal receipt required')
        successful = successful and receipt['status'] == 'succeeded'
        seconds = (datetime.fromisoformat(receipt['finished_utc']) - datetime.fromisoformat(receipt['started_utc'])).total_seconds()
        if seconds <= 0:
            raise ValueError('positive receipt duration required')
        elapsed += seconds
    if not math.isclose(elapsed, observation['wall_seconds']):
        raise ValueError('observation wall duration differs from completed receipts')
    return successful


def append_observation(catalogue, observation):
    """Append an immutable receipt-backed observation; repeats are idempotent."""
    successful = _validate_observation(observation)
    from .execution import digest
    path = Path(catalogue)
    row = {'schema_version': 1, 'profile': observation_profile(observation),
           'observation': deepcopy(observation), 'sha256': digest(observation),
           'completed_successfully': successful}
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path.with_suffix(path.suffix + '.lock')):
        rows = _catalogue_rows(path) if path.exists() else []
        receipt_ids = sorted(p['sha256'] for p in observation['receipts'])
        for old in rows:
            if sorted(p['sha256'] for p in old['observation']['receipts']) == receipt_ids:
                if old != row:
                    raise ValueError('catalogue receipt already has a conflicting observation')
                return row['sha256']
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + '\n')
            stream.flush(); os.fsync(stream.fileno())
    return row['sha256']


def _catalogue_rows(path):
    from .execution import digest
    rows = []
    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            if (row.get('schema_version') != 1 or row.get('sha256') != digest(row['observation'])
                    or row['profile'] != observation_profile(row['observation'])):
                raise ValueError('catalogue observation changed')
            if _validate_observation(row['observation']) != row['completed_successfully']:
                raise ValueError('catalogue receipt outcome changed')
            rows.append(row)
    return rows


def catalogue_observations(catalogue, profile_sha256, machine):
    """Other profiles stay in the catalogue; they cannot calibrate this target."""
    rows = [r for r in _catalogue_rows(catalogue)
            if r['observation']['profile_sha256'] == profile_sha256]
    observations = [r['observation'] for r in rows]
    if not observations:
        raise ValueError('no matching profile in observed-cost catalogue')
    keys = ('system', 'machine', 'hostname', 'logical_cpus')
    if any(any(o['machine'].get(k) != machine.get(k) for k in keys) for o in observations):
        raise ValueError('catalogue profile was measured on another machine')
    successful = [r['observation'] for r in rows if r['completed_successfully']]
    if not successful:
        raise ValueError('no completed successful attempts for this profile')
    return successful


def forecast_for(method_decision: dict, study: dict) -> dict:
    """Selected-rung forecast plus cheaper records with explicit matching data.

    Study inputs: cost_profiles[method] and cost_records[method], or a local
    observed_cost_catalogue and cost_targets[method] with spec/route/margin. A record must
    match process, configuration and machine exactly. A missing record/profile
    stays unknown. Neither a declared ceiling nor the ladder index is a forecast.
    """
    selected = method_decision['selected']
    profiles = study.get('cost_profiles', {})
    records = study.get('cost_records', {})
    targets = study.get('cost_targets', {})
    catalogue = study.get('observed_cost_catalogue')

    def for_rung(rung):
        method = rung['method']
        profile = profiles.get(method)
        source = records.get(method)
        if source is None and catalogue is not None and method in targets:
            from .pilot_cost import forecast_from_catalogue
            target = targets[method]
            source = forecast_from_catalogue(catalogue, target['spec'], route=target['route'],
                margin=target['margin'], base=target.get('base'), ceiling_seconds=target.get('ceiling_seconds'))
            source['cost_class'] = method
        if source is None:
            return make_record(method, 'unknown', profile, 'No matching cost observation or historical reference.')
        if (profile is None or any(profile.get(k) is None for k in ('process', 'configuration', 'machine'))
                or source.get('profile') != profile):
            raise ValueError(f'cost profile for {method} does not match process, configuration and machine')
        if source.get('status') == 'calibrated':
            from .pilot_cost import machine_identity
            here = machine_identity()
            if not isinstance(profile['machine'], dict) or any(profile['machine'].get(k) != here[k]
                    for k in ('system', 'machine', 'hostname', 'logical_cpus')):
                raise ValueError('calibrated cost profile belongs to another machine')
        if source.get('cost_class') != method:
            raise ValueError('cost record belongs to a different method rung')
        result = make_record(method, source['status'], profile, source.get('forecast_basis', source['basis']),
                             uncertainty=source.get('uncertainty'), **source['resource_vector'])
        if any(source.get(k) != result[k] for k in CONTRACT_DIMENSIONS):
            raise ValueError('cost record scalar projections differ from resource vector')
        return result

    result = for_rung(selected)
    result['alternatives'] = []
    for rung in sorted(method_decision.get('alternatives', []), key=lambda r: r['rung']):
        if rung['rung'] < selected['rung'] and (rung['method'] in records or catalogue is not None and rung['method'] in targets):
            result['alternatives'].append({'method': rung['method'], 'rung': rung['rung'], **for_rung(rung)})
    return result


def contract_forecast(record):
    """Exact shared method-decision cost_forecast shape, without rich extensions."""
    result = {key: deepcopy(record[key]) for key in ('status', *CONTRACT_DIMENSIONS)}
    result['basis'] = deepcopy(record.get('forecast_basis', record['basis']))
    return result
