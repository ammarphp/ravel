"""Read source-bound retained Contur 3.1.5 SQLite results without inference.

The native field named CLs/combined_exclusion stores exclusion confidence in
this source. Its complement is reported separately. Neither retained fit
parameters nor the imported confidence are recalculated or calibrated here.
"""
from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sqlite3

from ravel.physics.measurement import _load
from ravel.physics.quantities import _keys, _text, _unique
from ravel.workflow.state_io import atomic_json

VERSION = '3.1.5'
COMMIT = '3d3ccb52188acc86940f3881c98251ea904bb9e0'
SOURCE_ROLES = ('database_reader', 'depot_export', 'point_results', 'confidence_semantics')
MODES = ('SMBG', 'EXP', 'HLEXP')
FULL_MODES = ('DATABG', *MODES)
NO_EXP_MODES = ('SMBG', 'HLEXP')


def mode_population(modes=MODES):
    """One explicit complete source-defined profile, never a discovered subset."""
    if type(modes) not in (tuple, list) or tuple(modes) not in (MODES, FULL_MODES, NO_EXP_MODES):
        raise ValueError('exact ordered legacy3, full4 or no-exp2 Contur population required')
    return tuple(modes)
REQUIRED_COLUMNS = {
    'model_point': ('id', 'model_id', 'run_point', 'yoda_files'),
    'parameter_value': ('model_point_id', 'name', 'value'),
    'run': ('id', 'model_point_id', 'map_id', 'events_num', 'stat_type', 'combined_exclusion',
            'nll', 'llr', 'mu_lower_limit', 'mu_upper_limit', 'mu_hat', 'addition_argument'),
    'exclusions': ('id', 'run_id', 'pool_name', 'stat_type', 'exclusion', 'histos', 'nll', 'llr',
                   'mu_lower_limit', 'mu_upper_limit', 'mu_hat'),
}


def validate(spec):
    _keys(spec, ('schema_version', 'input'), label='cached Contur import task')
    if type(spec['schema_version']) is not int or spec['schema_version'] != 1:
        raise ValueError('unsupported cached Contur import schema')
    _text(spec['input'], 'cached Contur input')
    return dict(spec)


def _pin(pin):
    _keys(pin, ('path', 'sha256'), label='Contur file identity')
    _text(pin['path'], 'Contur file path')
    if not isinstance(pin['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', pin['sha256']):
        raise ValueError('Contur file requires a SHA256 identity')


def _contract(document):
    _keys(document, ('schema_version', 'database', 'source', 'modes', 'run_selection', 'scope'),
          label='cached Contur input')
    if type(document['schema_version']) is not int or document['schema_version'] not in (1, 2, 3):
        raise ValueError('unsupported cached Contur input schema')
    _pin(document['database'])
    source = document['source']
    _keys(source, ('version', 'commit', *SOURCE_ROLES), label='Contur semantic source')
    if source['version'] != VERSION or source['commit'] != COMMIT:
        raise ValueError('cached importer semantics are scoped to the declared Contur 3.1.5 source commit')
    for role in SOURCE_ROLES:
        _pin(source[role])
    expected = {1: MODES, 2: FULL_MODES, 3: NO_EXP_MODES}[document['schema_version']]
    if document['modes'] != list(expected):
        raise ValueError('all three explicit native statistical modes are required' if document['schema_version'] == 1
                         else 'explicit schema/profile requires its complete ordered native statistical modes')
    if document['run_selection'] != {'policy': 'latest_id_per_point_and_stat_type'}:
        raise ValueError('explicit native latest-run selection policy required')
    _text(document['scope'], 'cached-result source scope')
    return document


def inputs(spec, base):
    from ravel.workflow.science import regular
    path = regular(validate(spec)['input'], base)
    document, _ = _load(path)
    _contract(document)
    files = [path]
    for pin in [document['database'], *(document['source'][r] for r in SOURCE_ROLES)]:
        source = regular(pin['path'], path.parent)
        if hashlib.sha256(source.read_bytes()).hexdigest() != pin['sha256']:
            raise ValueError('cached Contur database or semantic source bytes changed')
        files.append(source)
    if len(set(files)) != len(files):
        raise ValueError('cached Contur source identities repeat a file')
    return files


def _numeric(value, label, *, confidence=False):
    if value is None:
        return
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'nonfinite or nonnumeric cached Contur {label}')
    if confidence and not 0 <= value <= 1:
        raise ValueError(f'cached Contur {label} is outside exclusion-confidence range')


def decode_database(path, *, modes=MODES):
    """Read the complete point/mode/pool population; keep every tied maximum.

    SQL lookup follows the retained native reader. A tied CSV maximum follows
    that reader's query order; it is not an independently selected LLR winner.
    Version and semantic source binding belongs to ``inputs``/``run``.
    """
    requested = mode_population(modes)
    path = Path(path).resolve()
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        for table, required in REQUIRED_COLUMNS.items():
            columns = {row['name'] for row in conn.execute(f'PRAGMA table_info({table})')}
            if not set(required) <= columns:
                raise ValueError(f'cached Contur {table} schema lacks required fields')
        points = []
        for point in conn.execute('SELECT * FROM model_point'):
            parameters = {}
            for row in conn.execute('SELECT name,value FROM parameter_value WHERE model_point_id=?', (point['id'],)):
                if row['name'] in parameters:
                    raise ValueError('duplicate cached Contur parameter identity')
                _text(row['name'], 'parameter name');_numeric(row['value'], 'parameter')
                if row['value'] is None:
                    raise ValueError('cached Contur parameter value is absent')
                parameters[row['name']] = row['value']
            if not parameters:
                raise ValueError('cached Contur point has no parameters')
            try:
                paths = ast.literal_eval(point['yoda_files'])
            except (ValueError, SyntaxError, TypeError) as exc:
                raise ValueError('cached Contur original YODA list is malformed') from exc
            if not isinstance(paths, list) or any(not isinstance(p, str) or not p for p in paths):
                raise ValueError('cached Contur original YODA list is malformed')
            latest = list(conn.execute('SELECT r.* FROM run r JOIN '
                '(SELECT stat_type,MAX(id) AS max_id FROM run WHERE model_point_id=? GROUP BY stat_type) latest '
                'ON r.id=latest.max_id', (point['id'],)))
            if {r['stat_type'] for r in latest} != set(requested) or len(latest) != len(requested):
                raise ValueError('cached Contur point does not cover exactly the three requested statistical modes'
                                 if requested == MODES else 'cached Contur point does not cover exactly its explicit requested statistical modes')
            runs = []
            for mode in requested:
                row = dict(next(r for r in latest if r['stat_type'] == mode))
                if type(row['events_num']) is not int or row['events_num'] < 0:
                    raise ValueError('invalid cached Contur event count')
                for key in ('combined_exclusion', 'nll', 'llr', 'mu_lower_limit', 'mu_upper_limit', 'mu_hat'):
                    _numeric(row[key], key, confidence=key == 'combined_exclusion')
                if row['combined_exclusion'] is None:
                    raise ValueError('cached Contur combined confidence is absent')
                pools = [dict(r) for r in conn.execute('SELECT * FROM exclusions WHERE run_id IN (?)', (row['id'],))]
                if not pools or len({p['pool_name'] for p in pools}) != len(pools):
                    raise ValueError('cached Contur pool identities are empty or duplicated')
                for pool in pools:
                    if pool['stat_type'] != mode:
                        raise ValueError('cached Contur pool mode differs from its run')
                    _text(pool['pool_name'], 'pool identity')
                    for key in ('exclusion', 'nll', 'llr', 'mu_lower_limit', 'mu_upper_limit', 'mu_hat'):
                        _numeric(pool[key], key, confidence=key == 'exclusion')
                    if pool['exclusion'] is None:
                        raise ValueError('absent cached pool confidence has no declared native maximum ordering')
                maximum = max(p['exclusion'] for p in pools)
                tied = [p for p in pools if p['exclusion'] == maximum]
                runs.append({'raw': row, 'native_exclusion_confidence': row['combined_exclusion'],
                             'conventional_cls_complement': 1-row['combined_exclusion'],
                             'pools': pools, 'dominant_candidates': tied, 'csv_dominant': tied[0]})
            points.append({'raw': dict(point), 'parameters': parameters, 'original_yoda_paths': paths, 'runs': runs})
        if not points or len({(p['raw']['model_id'], p['raw']['run_point']) for p in points}) != len(points):
            raise ValueError('cached Contur model-point population is empty or ambiguous')
    return points


def export_csv(points, *, modes=MODES):
    """Export native named columns and rounding; retain the native LLR-label bug."""
    requested = mode_population(modes)
    if requested != MODES and any(
            [r['raw']['stat_type'] for r in p['runs']] != list(requested) for p in points):
        raise ValueError('full Contur CSV needs exactly the declared ordered mode population')
    parameter_names = sorted(points[0]['parameters'])
    if any(set(p['parameters']) != set(parameter_names) for p in points):
        raise ValueError('cached Contur parameter basis changes between points')
    fields = list(parameter_names)
    for mode in requested:
        fields.extend(prefix+mode for prefix in ('CL', 'MULO', 'MUUP', 'MUHAT', 'LLR',
                       'dominant-pool', 'dominant-pool-histo', 'dominant-pool-llr'))
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n');writer.writeheader()
    for point in points:
        row = dict(point['parameters'])
        for run in point['runs']:
            native = run['raw'];mode = native['stat_type']
            row['CL'+mode] = run['native_exclusion_confidence']
            for prefix, key, digits in [('MULO', 'mu_lower_limit', 2), ('MUUP', 'mu_upper_limit', 2),
                                        ('MUHAT', 'mu_hat', 2), ('LLR', 'llr', 3)]:
                row[prefix+mode] = None if native[key] is None else round(native[key], digits)
            winner = run['csv_dominant']
            row['dominant-pool'+mode] = winner['pool_name']
            row['dominant-pool-histo'+mode] = row['dominant-pool-llr'+mode] = winner['histos']
        writer.writerow(row)
    return stream.getvalue()


def full_mode_delivery(out, name, result, points):
    """Commit intended new-profile JSON/CSV bytes, then check both at return."""
    from ravel.workflow.science import regular
    out = Path(out)
    payloads = {name: (json.dumps(result, indent=2, allow_nan=False)+'\n').encode(),
                'native-columns.csv': export_csv(points, modes=FULL_MODES).encode()}
    expected = {key: hashlib.sha256(value).hexdigest() for key, value in payloads.items()}
    # The writer receives detached committed content, not the live returned object.
    atomic_json(out/name, json.loads(payloads[name]))
    (out/'native-columns.csv').write_bytes(payloads['native-columns.csv'])
    verify_full_mode_delivery(out, name, result, expected)
    return expected


def verify_full_mode_delivery(out, name, result, expected):
    """Retain the original commitments across later ending-input reads."""
    from ravel.workflow.science import regular
    if hashlib.sha256((json.dumps(result, indent=2, allow_nan=False)+'\n').encode()).hexdigest() != expected[name]:
        raise ValueError('full Contur returned result changed from original commitment')
    for key, digest in expected.items():
        path = regular(Path(out)/key, out)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('full Contur generated delivery bytes changed before return')



def mode_delivery(out, name, result, points, *, modes):
    """New explicit profiles use the reviewed detached JSON/CSV commitments."""
    requested = mode_population(modes)
    if any([r['raw']['stat_type'] for r in p['runs']] != list(requested) for p in points):
        raise ValueError('new Contur delivery requires the complete ordered profile')
    out = Path(out)
    payloads = {name: (json.dumps(result, indent=2, allow_nan=False)+'\n').encode(),
                'native-columns.csv': export_csv(points, modes=requested).encode()}
    expected = {key: hashlib.sha256(value).hexdigest() for key, value in payloads.items()}
    atomic_json(out/name, json.loads(payloads[name]))
    (out/'native-columns.csv').write_bytes(payloads['native-columns.csv'])
    verify_full_mode_delivery(out, name, result, expected)
    return expected


def run(spec, base, out):
    files = inputs(spec, base)
    document, digest = _load(files[0])
    full = document['schema_version'] in (2, 3)
    modes = tuple(document['modes'])
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files} if full else None
    if full:
        from ravel.workflow.science import regular
        _contract(document)
        if before[str(files[0])] != digest:
            raise ValueError('consumed full-mode input differs from admitted input bytes')
        pins = [document['database'], *(document['source'][r] for r in SOURCE_ROLES)]
        for path, pin in zip(files[1:], pins):
            if regular(pin['path'], files[0].parent) != path or before[str(path)] != pin['sha256']:
                raise ValueError('consumed full-mode identities differ from admitted files')
    points = decode_database(files[1], modes=modes) if full else decode_database(files[1])
    result = {'schema_version': 1, 'kind': 'cached_contur_result_import', 'points': points,
              'input': {'path': str(files[0]), 'sha256': digest}, 'database': document['database'],
              'source': document['source'], 'run_selection': document['run_selection'], 'scope': document['scope'],
              'source_identity_scope': 'Content SHA256 pins are verified. Version/commit labels are caller declarations requiring independent source admission; this importer does not authenticate a Git release.',
              'support_tier': 'source-bound cached numerical-result import and native-column serialization only',
              'quantity_semantics': 'Native combined_exclusion/CL stores exclusion confidence; conventional CLs complement is separately named. No fresh statistical calculation.',
              'serialization_semantics': 'mu values round2dp and LLR3dp. dominant-pool-llr repeats the dominant histogram name in this native source; tied maximum selection follows native SQL order.',
              'original_yoda_scope': 'Original producer path strings retained; YODA bytes/event-analysis custody are not established by this result import.',
              'inference': None, 'physics_validated': False, 'fresh_inference': False, 'status': 'passed'}
    out = Path(out);out.mkdir(parents=True, exist_ok=False)
    if full:
        result['mode_population'] = list(modes)
        commitments = (full_mode_delivery(out, 'cached-contur-results.json', result, points)
                       if document['schema_version'] == 2 else mode_delivery(out, 'cached-contur-results.json', result, points, modes=modes))
        if before != {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs(spec, base)}:
            raise ValueError('full Contur bound inputs changed before return')
        verify_full_mode_delivery(out, 'cached-contur-results.json', result, commitments)
        return result
    atomic_json(out/'cached-contur-results.json', result)
    (out/'native-columns.csv').write_text(export_csv(points))
    return result
