"""Pinned Higgs-sector file protocol, without importing the external Higgs package.

The ordinary science worker calls run(task, base, output). H-19 registers the
operation fragments; H-16 provides doctor checks and the dedicated interpreter.
Native results retain their limited source scope, never physics certification.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
import os
from pathlib import Path
import re

from ravel.workflow.state_io import atomic_json, read_json

OPERATIONS = ('higgs-bounds', 'higgs-signals')
SCHEMA = Path(__file__).resolve().parents[1] / 'data/higgs/schemas/higgs-sector-bundle.json'
WORKER = Path(__file__).with_name('higgstools_worker.py')


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _number(value, label, minimum=None):
    _need(type(value) in (int, float) and math.isfinite(value), 'finite ' + label + ' required')
    _need(minimum is None or value >= minimum, label + ' below declared domain')
    return value


def _finite(value):
    if isinstance(value, dict):
        for v in value.values(): _finite(v)
    elif isinstance(value, list):
        for v in value: _finite(v)
    elif isinstance(value, float):
        _need(math.isfinite(value), 'nonfinite bundle value')


def doctor_pins(report):
    """Consume H-16's existing doctor report shape, never run doctor probes."""
    rows = [r for g in report.get('groups', []) if g.get('group') == 'higgstools'
            for r in g.get('checks', [])]
    pins = {}
    for key in ('higgstools-python', 'hbdataset', 'hsdataset'):
        matches = [r for r in rows if r.get('id') == key]
        _need(len(matches) == 1 and matches[0].get('status') == 'ready', 'doctor check not ready: ' + key)
        row = matches[0]
        _need(isinstance(row.get('found'), str) and row['found'], 'doctor-observed pin required: ' + key)
        if key != 'higgstools-python':
            _need(re.fullmatch('[0-9a-f]{40}', row['found']) is not None, 'dataset commit required')
        pins[key] = row['found']
    return pins


def validate_bundle(bundle, doctor_report=None):
    """Strict shape plus cross-field input laws, independent of the native tool."""
    from jsonschema import Draft202012Validator
    _finite(bundle)
    errors = sorted(Draft202012Validator(read_json(SCHEMA)).iter_errors(bundle), key=lambda e:str(e.path))
    _need(not errors, 'invalid higgs-sector-bundle: ' + ('; '.join(e.message for e in errors[:4])))
    if doctor_report is not None:
        pins = doctor_pins(doctor_report)
        for key in ('hbdataset', 'hsdataset'):
            _need(bundle['datasets'][key]['commit'] == pins[key], 'dataset commit differs from doctor pin: ' + key)
    particles = bundle['neutral_scalars'] + bundle['charged_scalars']
    ids = [p['id'] for p in particles]
    _need(len(ids) == len(set(ids)), 'duplicate particle id')
    for particle in particles:
        _need(particle['mass_gev'] > 0, 'positive scalar mass required')
        _need(sum(particle['branching_ratios'].values()) <= 1 + 1e-12, 'branching ratios exceed one')
        if particle in bundle['charged_scalars']:
            _need(not particle['couplings'] and bool(particle['rates']), 'charged scalar requires declared sigma times BR inputs')
        if bundle['input_kind'] == 'direct-rates':
            _need(not particle['couplings'] and bool(particle['rates']), 'direct-rate input requires rates without implicit effective-coupling predictions')
        keys = []
        for rate in particle['rates']:
            key = (rate['collider'], rate['production'], rate['decay'])
            _need(key not in keys, 'duplicate direct rate'); keys.append(key)
            # A factorization, when supplied, must be explicit and consistent.
            if 'production_pb' in rate:
                _need(rate['decay'] in particle['branching_ratios'], 'rate factorization needs declared BR')
                _need(math.isclose(rate['sigma_br_pb'], rate['production_pb'] * particle['branching_ratios'][rate['decay']],
                                   rel_tol=1e-12, abs_tol=1e-15), 'sigma times BR factorization mismatch')
        if bundle['input_kind'] == 'effective-couplings' and particle in bundle['neutral_scalars']:
            _need(bool(particle['couplings']), 'effective-coupling input needs declared normalized couplings')
    window = bundle['mass_assignment']['window_gev']
    choices = {}
    neutral_ids = {p['id'] for p in bundle['neutral_scalars']}
    for choice in bundle['mass_assignment']['choices']:
        pair = tuple(sorted(choice['particle_ids']))
        _need(len(set(pair)) == 2 and set(pair) <= neutral_ids and pair not in choices, 'invalid/duplicate mass assignment pair')
        choices[pair] = choice
    neutral = bundle['neutral_scalars']
    for i, a in enumerate(neutral):
        for b in neutral[i+1:]:
            if abs(a['mass_gev'] - b['mass_gev']) <= window:
                _need(tuple(sorted((a['id'], b['id']))) in choices, 'overlapping scalar masses require declared assignment choice')
    # This bridge does not synthesize joint experimental likelihoods for nearby states.
    _need(all(c['choice'] == 'native' for c in choices.values()), 'only explicit native mass assignment is supported')
    dof = bundle.get('degrees_of_freedom')
    _need(dof is None or type(dof['value']) is int, 'integer degrees of freedom required')
    return deepcopy(bundle)


def _build(kind, neutral_scalars, charged_scalars, **metadata):
    bundle = dict(schema_version=1, kind='higgs-sector-bundle', input_kind=kind,
                  neutral_scalars=deepcopy(neutral_scalars), charged_scalars=deepcopy(charged_scalars), **metadata)
    return validate_bundle(bundle)


def build_effective_couplings(neutral_scalars, charged_scalars, **metadata):
    return _build('effective-couplings', neutral_scalars, charged_scalars, **metadata)


def build_direct_rates(neutral_scalars, charged_scalars, **metadata):
    return _build('direct-rates', neutral_scalars, charged_scalars, **metadata)


def build_slha(raw, producer, particle_map, **metadata):
    """Use explicit PDGs and coupling selectors; infer no CP or missing decay law.

    particle_map rows declare charge, CP, PDG, coupling block/code/scale selectors,
    and decay-channel daughter PDGs. All four producers share the same SLHA law.
    An extended-scalar point may also use either already-normalized builder.
    """
    from ravel.physics.model_specific_spectrum import inventory, scalar, number
    _need(producer in ('FlexibleSUSY', 'SPheno', '2HDMC', 'extended-scalar-point'), 'declared SLHA producer required')
    doc = inventory(raw)
    _need(not doc['native_error_rows'], 'SLHA contains native errors')
    neutral, charged = [], []
    for declaration in particle_map:
        pdg = declaration['pdg']
        _need(type(pdg) is int, 'explicit particle PDG required')
        charge = declaration['charge']
        _need(charge in ('neutral', 'charged'), 'explicit scalar charge required')
        row = {'id':declaration['id'], 'mass_gev':float(number(scalar(doc, {'block':'MASS', 'codes':[pdg], 'scale':None}))),
               'width_gev':float(number(scalar(doc, {'block':'DECAY', 'codes':[pdg], 'scale':None}))),
               'couplings':{}, 'branching_ratios':{}, 'rates':deepcopy(declaration.get('rates', []))}
        if charge == 'neutral':
            _need('cp' in declaration, 'declared neutral CP property required')
            row['cp'] = declaration['cp']
        for name, selector in declaration.get('coupling_selectors', {}).items():
            row['couplings'][name] = float(number(scalar(doc, selector)))
        decay = [s for s in doc['sections'] if s['kind'] == 'decay' and s['pdg'] == pdg]
        _need(len(decay) == 1, 'unique declared decay section required')
        for channel, daughters in declaration.get('decay_channels', {}).items():
            values = []
            for r in decay[0]['rows']:
                tokens = r['source_text'].split('#', 1)[0].split()
                if len(tokens) >= 2 and int(tokens[1]) == len(daughters) and sorted(map(int, tokens[2:])) == sorted(daughters):
                    values.append(float(number(tokens[0])))
            _need(len(values) == 1, 'missing or duplicate declared SLHA decay channel')
            row['branching_ratios'][channel] = values[0]
        (neutral if charge == 'neutral' else charged).append(row)
    metadata['provenance'] = {**metadata['provenance'], 'producer':producer, 'slha_sha256':hashlib.sha256(raw).hexdigest()}
    return _build('slha', neutral, charged, **metadata)


def finalize_result(raw, bundle, operation, request_sha256):
    """Recheck the external record before it can feed a scientific consumer."""
    _need(isinstance(raw, dict), 'worker response must be an object')
    _finite(raw)
    _need(type(raw.get('schema_version')) is int and raw['schema_version'] == 1 and raw.get('operation') == operation, 'worker protocol mismatch')
    _need(raw.get('request_sha256') == request_sha256, 'worker response belongs to another request')
    commits = {k:v['commit'] for k,v in bundle['datasets'].items()}
    _need(raw.get('datasets') == commits, 'worker dataset pin mismatch')
    result = deepcopy(raw)
    _need('p_value' not in raw, 'worker must not supply an undeclared p-value')
    if operation == 'higgs-bounds':
        rows = raw.get('particles')
        _need(isinstance(rows, list), 'per-particle bounds results required')
        ids = [p['id'] for p in bundle['neutral_scalars'] + bundle['charged_scalars']]
        _need(len(rows) == len(ids) and {r.get('id') for r in rows} == set(ids), 'worker particle population mismatch')
        for row in rows:
            _number(row.get('obsratio'), 'observed ratio', 0)
            _number(row.get('expected_ratio'), 'expected ratio', 0)
            _need(type(row.get('allowed')) is bool and row['allowed'] == (row['obsratio'] <= 1), 'bounds allowed flag contradicts selected ratio')
            _need(isinstance(row.get('selected_limit_id'), str) and bool(row['selected_limit_id']), 'selected limit id required')
        result['interpretation'] = 'One expected-sensitivity-selected limit per particle; no combined-channel exclusion.'
    else:
        _number(raw.get('chi2_total'), 'total chi2', 0)
        measurements = raw.get('measurements')
        _need(isinstance(measurements, list) and measurements, 'per-measurement chi2 required')
        _need(type(raw.get('n_obs')) is int and raw['n_obs'] > 0, 'native observation count required')
        _need(len({m.get('id') for m in measurements}) == len(measurements), 'duplicate measurement id')
        for m in measurements:
            _need(isinstance(m.get('id'), str) and m['id'], 'measurement id required')
            _number(m.get('chi2'), 'measurement chi2', 0)
        # A measurement can contain several observables; n_obs is native, not row count.
        sm = raw.get('sm_reference', {})
        _number(sm.get('chi2_total'), 'same-call SM reference chi2', 0)
        _need(type(sm.get('n_obs')) is int and sm['n_obs'] == raw['n_obs'] and sm.get('same_call') is True, 'same-call SM reference population required')
        _need(sm.get('input_sha256') == bundle['sm_reference']['sha256'], 'SM reference input changed')
        delta = raw['chi2_total'] - sm['chi2_total']
        _need('delta_chi2' not in raw or raw['delta_chi2'] == delta, 'incorrect delta chi2')
        result['delta_chi2'] = delta
        dof = bundle.get('degrees_of_freedom')
        if dof is not None:
            from scipy.stats import chi2
            result.update(degrees_of_freedom=deepcopy(dof), p_value=float(chi2.sf(raw['chi2_total'], dof['value'])))
    result['native_coupling_defaults'] = deepcopy(bundle['provenance'].get('native_coupling_defaults'))
    result.update(status='passed', physics_validated=False,
                  scope='Pinned external Higgs constraints for the declared sector and assignment',
                  limitations=['Native API and numerical physics require separate qualification.'])
    return result


def check_hb_selection(result, claims):
    """check:higgs.hb_selection refuses exclusions read from other channels."""
    _need(result.get('operation') == 'higgs-bounds', 'bounds result required')
    rows = {r['id']:r for r in result['particles']}
    _need(isinstance(claims, list) and claims, 'declared per-particle claims required')
    seen = set()
    for claim in claims:
        identity = claim.get('particle_id')
        _need(identity in rows and identity not in seen, 'unknown/duplicate particle claim'); seen.add(identity)
        row = rows[identity]
        _need(claim.get('limit_id') == row['selected_limit_id'], 'exclusion must use the expected-sensitivity selected limit')
        _need(type(claim.get('excluded')) is bool and claim['excluded'] == (row['obsratio'] > 1), 'claim contradicts selected observed ratio')
        _need(claim.get('combined_channels', False) is False, 'selected limit is not a combined-channel statistic')
    return {'check':'check:higgs.hb_selection', 'status':'passed', 'physics_validated':False}


def exchange(bundle, operation, doctor_report, output, command, *, launch=None, resources=None, delegation=None):
    """Bound JSON files around a child. Tests inject an inert launcher/command.

    Production run() supplies the dedicated command and shared resource launcher;
    this protocol helper never grants scientific execution approval.
    """
    _need(operation in OPERATIONS, 'unknown HiggsTools operation')
    bundle = validate_bundle(bundle, doctor_report)
    _need(operation != 'higgs-signals' or 'sm_reference' in bundle, 'explicit SM reference required for signals')
    out = Path(output).absolute()
    _need(not any(p.is_symlink() for p in (out, *out.parents)), 'output traverses symlink')
    out.mkdir(parents=True, exist_ok=False)
    request = out / 'request.json'
    atomic_json(request, {'schema_version':1, 'operation':operation, 'bundle':bundle,
                          'doctor_pins':doctor_pins(doctor_report), 'delegation':delegation})
    before = hashlib.sha256(request.read_bytes()).hexdigest()
    if launch is None:
        # This helper is explicitly for synthetic protocol tests. Production must
        # have ordinary-worker approval and use execute_native via run().
        _need(delegation is None, 'delegated calls require the supervised launcher')
        import subprocess
        subprocess.run([*command, str(request), str(out / 'response.json')], check=True, timeout=30)
    else:
        launch([*command, str(request), str(out / 'response.json')], out, resources)
    _need(hashlib.sha256(request.read_bytes()).hexdigest() == before, 'worker mutated request')
    from ravel.workflow.science import regular
    response = regular('response.json', out)
    result = finalize_result(read_json(response), bundle, operation, before)
    atomic_json(out / 'higgstools-result.json', result)
    return result


def validate(task):
    _need(isinstance(task, dict) and set(task) == {'input'} and isinstance(task['input'], str) and task['input'], 'HiggsTools task requires input document')
    return deepcopy(task)


def _pin(binding, base):
    from ravel.workflow.science import regular
    _need(isinstance(binding, dict) and set(binding) == {'path', 'sha256'}, 'file pin required')
    path = regular(binding['path'], base)
    _need(hashlib.sha256(path.read_bytes()).hexdigest() == binding['sha256'], 'bound input changed: ' + str(path))
    return path


def _load(task, base):
    from ravel.workflow.science import regular
    validate(task)
    path = regular(task['input'], base)
    doc = read_json(path)
    _need(set(doc) == {'schema_version', 'operation', 'bundle', 'doctor_report', 'runtime', 'max_seconds', 'max_ram_mib'}, 'closed HiggsTools input document required')
    _need(type(doc['schema_version']) is int and doc['schema_version'] == 1 and doc['operation'] in OPERATIONS, 'unsupported HiggsTools operation')
    _number(doc['max_seconds'], 'seconds', 1); _number(doc['max_ram_mib'], 'RAM MiB', 1)
    report = _pin(doc['doctor_report'], path.parent)
    bundle = validate_bundle(doc['bundle'], read_json(report))
    _need(doc['operation'] != 'higgs-signals' or 'sm_reference' in bundle, 'explicit SM reference required for signals')
    runtime = doc['runtime']
    _need(set(runtime) == {'python', 'version'}, 'explicit dedicated runtime required')
    python = Path(runtime['python']['path'])
    if not python.is_absolute(): python = path.parent / python
    _need(python.parts[-3:] == ('.venv-higgstools', 'bin', 'python'), 'worker must use .venv-higgstools/bin/python')
    _need(python.is_file() and os.access(python, os.X_OK), 'dedicated interpreter unavailable: awaits H-16')
    _need(hashlib.sha256(python.read_bytes()).hexdigest() == runtime['python']['sha256'], 'interpreter pin mismatch')
    _need(runtime['version'] == doctor_pins(read_json(report))['higgstools-python'], 'HiggsTools version differs from doctor')
    files = [path, report, python, Path(__file__), WORKER, SCHEMA]
    _need(type(runtime['python']) is dict and set(runtime['python']) == {'path','sha256'}, 'interpreter file pin required')
    for dataset in bundle['datasets'].values():
        root = Path(dataset['path'])
        if not root.is_absolute(): root = path.parent / root
        _need(root.is_dir() and not any(p.is_symlink() for p in (root, *root.parents)), 'regular dataset tree required')
        declared = []
        for row in dataset['files']:
            relative = Path(row['path'])
            _need(not relative.is_absolute() and '..' not in relative.parts and '.git' not in relative.parts, 'relative dataset member required')
            declared.append(_pin(row, root))
        members = [p for p in root.rglob('*') if '.git' not in p.relative_to(root).parts]
        _need(all(not p.is_symlink() and (p.is_file() or p.is_dir()) for p in members), 'dataset symlink or special file refused')
        actual = [p.resolve() for p in members if p.is_file()]
        _need(len(declared) == len(set(declared)) and set(actual) == set(declared), 'complete dataset byte inventory required')
        files += declared
        dataset['path'] = str(root.absolute())
    if 'sm_reference' in bundle:
        sm = _pin(bundle['sm_reference'], path.parent); files.append(sm)
        bundle['sm_reference']['path'] = str(sm)
        reference = validate_bundle(read_json(sm))
        for key, dataset in reference['datasets'].items():
            root = Path(dataset['path'])
            if not root.is_absolute(): root = sm.parent / root
            dataset['path'] = str(root.absolute())
        _need(reference['datasets'] == bundle['datasets'] and reference['mass_assignment'] == bundle['mass_assignment'], 'SM reference must use identical dataset and assignment settings')
        _need('sm_reference' not in reference and 'degrees_of_freedom' not in reference, 'SM reference must be a terminal sector bundle')
    return path, doc, bundle, read_json(report), python.absolute(), files


def inputs(task, base):
    return _load(task, base)[-1]


def execution_seconds(task, base):
    return _load(task, base)[1]['max_seconds'] + 5


def _approved(task, output, operation):
    from ravel.workflow import science, execution
    out = Path(output).absolute()
    for rd in (out, *out.parents):
        if (rd / science.PLAN).is_file():
            plan = science.verify_worker(rd); spec = science.execution_spec(rd)
            _need(spec['mode'] == operation and spec['task'] == task and out == (rd / plan['output_directory']).resolve(), 'HiggsTools task/output differs from ordinary worker approval')
            state = execution.load_execution(rd)['stages'].get('science', {})
            _need(state.get('status') == 'running' and state.get('child_pid') == os.getpid()
                  and state.get('child_identity') == execution.process_identity(os.getpid()), 'live ordinary science worker required')
            return rd, plan, state
    raise ValueError('HiggsTools requires approved ordinary science worker')


def run(task, base, output):
    path, doc, bundle, report, python, files = _load(task, base)
    rd, plan, state = _approved(task, output, doc['operation'])
    _need(doc['max_seconds'] + 5 <= plan['max_seconds'], 'child budget exceeds ordinary approval')
    before = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    from ravel.physics.reinterpret_db import execute_native
    delegation = {'rundir':str(rd), 'parent_pid':os.getpid(), 'parent_identity':state['child_identity'],
                  'fingerprint':state['fingerprint'], 'output':str(Path(output).absolute()),
                  'version':doc['runtime']['version'], 'input_hashes':before}
    result = exchange(bundle, doc['operation'], report, Path(output) / 'higgstools',
        [str(python), '-B', str(WORKER)], launch=execute_native, resources=doc, delegation=delegation)
    _need(all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == sha for p,sha in before.items()), 'HiggsTools inputs changed during execution')
    return result
