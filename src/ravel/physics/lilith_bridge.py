"""Source-bound reduced-coupling transport for a dedicated likelihood interpreter.

run(task, base, output) is the admitted science adapter. The registration fragment
carries its integration contract. Transport checks establish no physics validity.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from ravel.workflow.state_io import atomic_json, read_json

WORKER = Path(__file__).with_name('lilith_worker.py')
COUPLINGS = ('tt', 'bb', 'cc', 'tautau', 'mumu', 'WW', 'ZZ', 'gg', 'gammagamma', 'Zgamma')


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _number(value, label):
    _need(type(value) in (int, float) and math.isfinite(value), 'finite ' + label + ' required')
    return value


def _text(value, label):
    _need(isinstance(value, str) and bool(value.strip()), label + ' required')
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                                separators=(',', ':')).encode()).hexdigest()


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _ids(values):
    _need(isinstance(values, list) and bool(values), 'nonempty measurement census required')
    _need(all(isinstance(v, str) and bool(v.strip()) for v in values), 'measurement identities required')
    _need(len(values) == len(set(values)), 'duplicate measurement identity')
    return set(values)


def validate_database(database):
    _need(isinstance(database, dict), 'database metadata required')
    _text(database.get('version'), 'database version')
    _need(re.fullmatch('[0-9a-f]{64}', database.get('sha256', '')) is not None, 'database sha256 required')
    window = database.get('mass_window_gev')
    _need(isinstance(window, list) and len(window) == 2, 'database mass window required')
    lo, hi = [_number(v, 'mass window') for v in window]
    _need(0 < lo < hi, 'invalid database mass window')
    _ids(database.get('measurement_ids'))
    return deepcopy(database)


def reduced_couplings_xml(bundle, database, mapping):
    """Explicit amplitude/BR selectors; omitted or unsupported inputs fail closed."""
    database = validate_database(database)
    _need(bundle.get('input_kind') in ('effective-couplings', 'slha'), 'reduced couplings required; direct rates unsupported')
    _need(not bundle.get('charged_scalars'), 'charged scalars unsupported by reduced-coupling likelihood')
    _need(bundle.get('provenance', {}).get('coupling_normalization') == 'SM amplitude', 'explicit SM amplitude normalization required')
    _need(isinstance(mapping, dict) and set(mapping) == {'couplings', 'branching_ratios', 'precision'}, 'closed coupling mapping required')
    _need(set(mapping['couplings']) == set(COUPLINGS), 'complete reduced coupling selectors required')
    _need(set(mapping['branching_ratios']) == {'invisible', 'undetected'}, 'explicit invisible and undetected BR selectors required')
    _need(mapping['precision'] in ('LO', 'BEST-QCD'), 'declared likelihood precision required')
    for selector in (*mapping['couplings'].values(), *mapping['branching_ratios'].values()):
        _text(selector, 'input selector')
    rows = bundle.get('neutral_scalars')
    _need(isinstance(rows, list) and rows, 'neutral scalar population required')
    _ids([r.get('id') for r in rows])
    root = ET.Element('lilithinput')
    for row in rows:
        _need(row.get('cp') == 'even', 'only real CP-even reduced couplings supported')
        _need(not row.get('rates'), 'direct rates cannot be silently discarded')
        mass = _number(row.get('mass_gev'), 'scalar mass')
        _need(database['mass_window_gev'][0] <= mass <= database['mass_window_gev'][1], 'scalar outside database mass window')
        scalar = ET.SubElement(root, 'reducedcouplings', {'part': row['id']})
        ET.SubElement(scalar, 'mass').text = str(mass)
        for target, source in mapping['couplings'].items():
            _need(source in row['couplings'], 'missing coupling selector: ' + source)
            ET.SubElement(scalar, 'C', {'to': target}).text = str(_number(row['couplings'][source], 'coupling'))
        extra = ET.SubElement(scalar, 'extraBR')
        total = 0.
        for target, source in mapping['branching_ratios'].items():
            _need(source in row['branching_ratios'], 'missing BR selector: ' + source)
            value = _number(row['branching_ratios'][source], 'branching ratio')
            _need(0 <= value <= 1, 'BR outside probability domain')
            total += value
            ET.SubElement(extra, 'BR', {'to': target}).text = str(value)
        _need(total <= 1, 'invisible and undetected BR sum exceeds one')
        ET.SubElement(scalar, 'precision').text = mapping['precision']
    return ET.tostring(root, encoding='unicode')


def build_request(bundle, sm_bundle, database, mapping, *, sector_validator=None):
    # Dependency seam: retain the upstream schema validator as the authority.
    if sector_validator is None:
        try:
            from ravel.physics.higgstools_bridge import validate_bundle
        except ImportError as exc:
            raise ValueError('sector validation provider is unavailable') from exc
        sector_validator = validate_bundle
    bundle = sector_validator(bundle)
    sm_bundle = sector_validator(sm_bundle)
    xml = reduced_couplings_xml(bundle, database, mapping)
    sm_xml = reduced_couplings_xml(sm_bundle, database, mapping)
    return {'schema_version': 1, 'operation': 'higgs-lilith', 'xml': xml, 'sm_xml': sm_xml,
            'database': validate_database(database), 'comparison_input_sha256': comparison_input_digest(bundle, sm_bundle)}


def comparison_input_digest(bundle, sm_bundle):
    """Shared engine seam binding the sector/reference pair without database settings."""
    comparison = [{k: value[k] for k in ('neutral_scalars', 'charged_scalars', 'provenance')}
                  for value in (bundle, sm_bundle)]
    return _digest(comparison)


def finalize_result(raw, request, request_sha256):
    _need(isinstance(raw, dict), 'worker response object required')
    _need(raw.get('schema_version') == 1 and type(raw['schema_version']) is int
          and raw.get('operation') == 'higgs-lilith', 'worker protocol mismatch')
    _need(raw.get('request_sha256') == request_sha256, 'worker request identity mismatch')
    _need(raw.get('database') == request['database'], 'worker database mismatch')
    _need(raw.get('comparison_input_sha256') == request['comparison_input_sha256'], 'worker comparison input mismatch')
    value = _number(raw.get('minus2_log_likelihood'), 'minus2 log likelihood')
    sm = raw.get('sm_reference', {})
    reference = _number(sm.get('minus2_log_likelihood'), 'SM minus2 log likelihood')
    _need(type(raw.get('n_obs')) is int and raw['n_obs'] > 0, 'native n_obs required')
    _need(sm.get('same_call') is True and type(sm.get('n_obs')) is int and sm['n_obs'] == raw['n_obs']
          and sm.get('input_sha256') == hashlib.sha256(request['sm_xml'].encode()).hexdigest(), 'same-call SM reference required')
    delta = value - reference
    _need('delta_chi2' not in raw or raw['delta_chi2'] == delta, 'incorrect delta chi2')
    _need('p_value' not in raw, 'undeclared p-value refused')
    if 'runtime_version' in request:
        _need(raw.get('runtime_version') == request['runtime_version'], 'worker runtime version mismatch')
    if request.get('delegation') is not None:
        rows = raw.get('imported_sources')
        _need(isinstance(rows, list) and rows, 'native imported-source census required')
        allowed = request['delegation']['input_hashes']
        seen = set()
        for row in rows:
            _need(isinstance(row, dict) and set(row) == {'path', 'sha256'}, 'imported-source row required')
            _need(row['path'] not in seen and allowed.get(row['path']) == row['sha256'], 'unbound imported source')
            seen.add(row['path'])
    return {**deepcopy(raw), 'delta_chi2': delta, 'status': 'passed', 'physics_validated': False,
            'scope': 'Pinned reduced-coupling likelihood and same-call supplied SM reference',
            'limitations': ['Pinned native API, database applicability and numerical accuracy require qualification.']}


def cross_engine(signals, likelihood):
    """Compare signed differences from each engine's supplied SM reference."""
    _need(signals.get('operation') == 'higgs-signals' and likelihood.get('operation') == 'higgs-lilith', 'engine pair mismatch')
    identity = signals.get('comparison_input_sha256')
    _need(isinstance(identity, str) and re.fullmatch('[0-9a-f]{64}', identity) is not None
          and identity == likelihood.get('comparison_input_sha256'), 'same physical comparison input required')
    _need(all(r.get('status') == 'passed' for r in (signals, likelihood)), 'failed engine result refused')
    a = _number(signals.get('delta_chi2'), 'signals delta chi2')
    b = _number(likelihood.get('delta_chi2'), 'likelihood delta chi2')
    left = _ids([r.get('id') for r in signals.get('measurements', [])])
    right = _ids(likelihood.get('database', {}).get('measurement_ids'))
    tolerance = max(1., .15 * abs(a))
    difference = abs(a - b)
    return {'check': 'check:higgs.cross_engine', 'status': 'passed' if difference <= tolerance else 'finding',
            'difference': difference, 'tolerance': tolerance, 'primary_delta_chi2': a,
            'independent_delta_chi2': b, 'comparison_input_sha256': identity,
            'only_higgs_signals': sorted(left - right), 'only_lilith': sorted(right - left),
            'databases': {'higgs_signals': deepcopy(signals.get('datasets')), 'lilith': deepcopy(likelihood['database'])},
            'physics_validated': False}


def exchange(request, output, command, *, launch, resources):
    """File transport with an injected launcher; never grants launch authority."""
    from ravel.workflow.science import regular
    out = Path(output).absolute()
    _need(not any(p.is_symlink() for p in (out, *out.parents)), 'regular output required')
    out.mkdir(parents=True, exist_ok=False)
    path = out / 'request.json'
    atomic_json(path, request)
    before = _sha(path)
    launch([*command, str(path), str(out / 'response.json')], out, resources)
    _need(_sha(path) == before, 'worker mutated request')
    result = finalize_result(read_json(regular('response.json', out)), request, before)
    atomic_json(out / 'lilith-result.json', result)
    return result


def validate(task):
    _need(isinstance(task, dict) and set(task) == {'input'}, 'likelihood task requires input document')
    _text(task['input'], 'input path')
    return deepcopy(task)


def _pin(binding, base):
    from ravel.workflow.science import regular
    _need(isinstance(binding, dict) and set(binding) == {'path', 'sha256'}, 'file pin required')
    path = regular(binding['path'], base)
    _need(_sha(path) == binding['sha256'], 'bound input changed')
    return path


def _load(task, base):
    from ravel.workflow.science import regular
    validate(task)
    path = regular(task['input'], base)
    doc = read_json(path)
    _need(set(doc) == {'schema_version', 'operation', 'bundle', 'sm_bundle', 'database', 'mapping', 'runtime', 'doctor_report', 'max_seconds', 'max_ram_mib'}, 'closed likelihood input document required')
    _need(type(doc['schema_version']) is int and doc['schema_version'] == 1 and doc['operation'] == 'higgs-lilith', 'unsupported likelihood operation')
    for name in ('max_seconds', 'max_ram_mib'):
        _need(_number(doc[name], name) > 0, 'positive resource ceiling required')
    pins = [_pin(doc[key], path.parent) for key in ('bundle', 'sm_bundle', 'database', 'doctor_report')]
    bundle, sm_bundle, database, doctor = [read_json(p) for p in pins]
    request = build_request(bundle, sm_bundle, database, doc['mapping'])
    runtime = doc['runtime']
    _need(set(runtime) == {'python', 'version', 'files'}, 'complete runtime pins required')
    _need(isinstance(runtime['python'], dict) and set(runtime['python']) == {'path', 'sha256'}, 'interpreter file pin required')
    # A venv interpreter normally is a symlink. Pin its target bytes while preserving its venv path.
    python = Path(runtime['python']['path'])
    if not python.is_absolute():
        python = path.parent / python
    _need(python.parts[-3:] == ('.venv-lilith', 'bin', 'python') and python.is_file()
          and os.access(python, os.X_OK) and _sha(python) == runtime['python']['sha256'], 'dedicated interpreter pin mismatch')
    rows = [r for group in doctor.get('groups', []) if group.get('group') == 'lilith' for r in group.get('checks', [])]
    for key, expected in (('lilith-python', runtime['version']), ('lilith-database', database['sha256'])):
        match = [r for r in rows if r.get('id') == key]
        _need(len(match) == 1 and match[0].get('status') == 'ready' and match[0].get('found') == expected, 'doctor pin not ready: ' + key)
    _text(runtime['version'], 'runtime version')
    _need(isinstance(runtime['files'], list) and runtime['files'], 'runtime source/dependency inventory required')
    runtime_files = [_pin(row, path.parent) for row in runtime['files']]
    _need('list_file' in database and 'files' in database, 'database list and member pins required')
    list_file = _pin(database['list_file'], pins[2].parent)
    _need(_sha(list_file) == database['sha256'], 'database list identity mismatch')
    _need(isinstance(database['files'], list) and database['files'], 'database member pins required')
    db_files = [_pin(row, pins[2].parent) for row in database['files']]
    _need(list_file in db_files and len(set(db_files)) == len(db_files), 'unique database inventory including list required')
    # The declared list format has one relative measurement XML path per line.
    entries = []
    for line in list_file.read_text().splitlines():
        value = line.split('#', 1)[0].strip()
        if not value:
            continue
        relative = Path(value)
        _need(not relative.is_absolute() and '..' not in relative.parts, 'relative database list member required')
        entries.append(regular(value, list_file.parent))
    _need(entries and len(set(entries)) == len(entries) and set(entries) <= set(db_files), 'complete unique database list inventory required')
    request.update(database_list=str(list_file), runtime_version=runtime['version'])
    files = [path, *pins, python, *runtime_files, *db_files, Path(__file__), WORKER]
    return doc, request, python, files


def inputs(task, base):
    return _load(task, base)[-1]


def execution_seconds(task, base):
    return _load(task, base)[0]['max_seconds'] + 5


def _approved(task, output):
    from ravel.workflow import science, execution
    out = Path(output).absolute()
    for rd in (out, *out.parents):
        if (rd / science.PLAN).is_file():
            plan = science.verify_worker(rd)
            spec = science.execution_spec(rd)
            _need(spec['mode'] == 'higgs-lilith' and spec['task'] == task
                  and out == (rd / plan['output_directory']).resolve(), 'task/output differs from approval')
            state = execution.load_execution(rd)['stages'].get('science', {})
            _need(state.get('status') == 'running' and state.get('child_pid') == os.getpid()
                  and state.get('child_identity') == execution.process_identity(os.getpid()), 'live ordinary worker required')
            return rd, plan, state
    raise ValueError('likelihood execution requires approved ordinary science worker')


def run(task, base, output):
    rd, plan, state = _approved(task, output)
    doc, request, python, files = _load(task, base)
    _need(doc['max_seconds'] + 5 <= plan['max_seconds'], 'child budget exceeds approval')
    before = {str(p): _sha(p) for p in files}
    request['delegation'] = {'rundir': str(rd), 'parent_pid': os.getpid(),
        'parent_identity': state['child_identity'], 'fingerprint': state['fingerprint'],
        'output': str(Path(output).absolute()), 'input_hashes': before}
    from ravel.physics.reinterpret_db import execute_native
    result = exchange(request, Path(output) / 'lilith', [str(python), '-B', str(WORKER)],
                      launch=execute_native, resources=doc)
    _need(before == {str(p): _sha(p) for p in inputs(task, base)}, 'inputs changed during execution')
    return result
