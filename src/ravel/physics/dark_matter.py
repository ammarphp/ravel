"""Supplied dark-matter models, strict driver transport and cited comparisons.

No upstream code is imported. A source-reviewed per-model binding implements
micrOMEGAs calls in a separate executable; its version and binary are pinned.
Native execution is available only inside an admitted ordinary science worker.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, localcontext
import hashlib
import math
from pathlib import Path
import re

from ravel.physics.dataset_query_quantities_core import Capture, keys, pin, strict, text
from ravel.physics.supplied_contracts import output_contract, publish
from ravel.validation.qualification_rows import validate_row

MODE = 'dark-matter-observables'
SCOPE = 'supplied-dark-matter-observables'
MAX_OUTPUT_BYTES = 8 * 1024**2
SCALARS = {
    'omega_h2': '1', 'xf': '1',
    'sigma_si_p_cm2': 'cm^2', 'sigma_si_n_cm2': 'cm^2',
    'sigma_sd_p_cm2': 'cm^2', 'sigma_sd_n_cm2': 'cm^2',
    'sigma_v_today_cm3_s': 'cm^3/s',
}


class DarkMatterInputError(ValueError):
    """An incomplete model, source, convention or numerical comparison."""
    reason = 'dark-matter-input'


def number(value, label, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or positive and value <= 0:
        raise DarkMatterInputError('finite ' + ('positive ' if positive else 'nonnegative ') + label + ' required')
    return value


def astrophysics(value):
    keys(value, ('local_density_gev_cm3', 'velocity_distribution', 'density_fraction'), 'astrophysical conventions')
    number(value['local_density_gev_cm3'], 'local density', positive=True)
    number(value['density_fraction'], 'density fraction', positive=True)
    if value['density_fraction'] > 1:
        raise DarkMatterInputError('density fraction must not exceed one')
    law = value['velocity_distribution']
    if type(law) is not dict or 'family' not in law or len(law) < 2:
        raise DarkMatterInputError('complete supplied velocity distribution required')
    text(law['family'], 'velocity distribution')
    # The source may use any supplied law; preserve its full parameterisation.
    strict(__import__('json').dumps(law, allow_nan=False))
    return deepcopy(value)


def validate_request(document):
    keys(document, ('schema_version', 'study_id', 'model', 'parameters', 'calculation', 'astrophysics', 'report'), 'dark-matter request')
    if type(document['schema_version']) is not int or document['schema_version'] != 1:
        raise DarkMatterInputError('dark-matter request schema1 required')
    text(document['study_id'], 'supplied study identity')
    model = document['model']
    keys(model, ('id', 'format', 'candidate', 'particles', 'coannihilation_partners', 'delta_m_fraction', 'coupling_conventions'), 'model')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}', text(model['id'], 'model id')):
        raise DarkMatterInputError('safe per-model directory identifier required')
    if model['format'] not in ('calchep', 'ufo'):
        raise DarkMatterInputError('CalcHEP or UFO model source required')
    text(model['candidate'], 'dark-matter candidate')
    text(model['coupling_conventions'], 'supplied coupling conventions')
    number(model['delta_m_fraction'], 'co-annihilation fractional mass threshold')
    if type(model['particles']) is not list or not 1 <= len(model['particles']) <= 10000:
        raise DarkMatterInputError('complete bounded particle inventory required')
    particles = {}
    for row in model['particles']:
        keys(row, ('name', 'mass_gev', 'odd'), 'particle')
        name = text(row['name'], 'particle name')
        number(row['mass_gev'], 'particle mass')
        if name in particles or type(row['odd']) is not bool:
            raise DarkMatterInputError('distinct particles with explicit parity required')
        particles[name] = row
    candidate = particles.get(model['candidate'])
    if candidate is None or not candidate['odd'] or candidate['mass_gev'] <= 0:
        raise DarkMatterInputError('massive odd candidate missing from model particle list')
    if type(model['coannihilation_partners']) is not list:
        raise DarkMatterInputError('explicit co-annihilation partner population required')
    seen = set()
    for partner in model['coannihilation_partners']:
        keys(partner, ('name', 'mass_gev'), 'declared co-annihilation partner')
        name = text(partner['name'], 'partner name')
        mass = number(partner['mass_gev'], 'partner mass', positive=True)
        if name in seen or name == model['candidate']:
            raise DarkMatterInputError('distinct declared co-annihilation partners required')
        seen.add(name)
        close = abs(mass - candidate['mass_gev']) / candidate['mass_gev'] <= model['delta_m_fraction']
        if close and name not in particles:
            raise DarkMatterInputError(f'co-annihilation partner {name} missing within declared threshold {model["delta_m_fraction"]}')
        if name in particles and (not particles[name]['odd'] or particles[name]['mass_gev'] != mass):
            raise DarkMatterInputError('co-annihilation partner mass/parity differs: ' + name)
    if type(document['parameters']) is not dict or not document['parameters']:
        raise DarkMatterInputError('supplied model parameters required')
    for name, value in document['parameters'].items():
        text(name, 'parameter name')
        if type(value) not in (int, float) or not math.isfinite(value):
            raise DarkMatterInputError('finite supplied parameter required: ' + name)
    calculation = document['calculation']
    keys(calculation, ('freeze_out', 'today_velocity_c', 'today_rate_definition', 'channel_fraction_cutoff'), 'calculation conventions')
    text(calculation['freeze_out'], 'freeze-out prescription')
    text(calculation['today_rate_definition'], 'today rate prescription')
    number(calculation['today_velocity_c'], 'today velocity')
    number(calculation['channel_fraction_cutoff'], 'channel cutoff')
    if calculation['today_velocity_c'] >= 1 or calculation['channel_fraction_cutoff'] >= 1:
        raise DarkMatterInputError('sub-luminal velocity and fractional channel cutoff required')
    astrophysics(document['astrophysics'])
    output_contract(document['report'])
    return deepcopy(document)


def parse_driver_output(raw, request):
    """One closed UTF-8 JSON object, explicit units and no invented observables."""
    request = validate_request(request)
    if type(raw) not in (str, bytes):
        raise DarkMatterInputError('driver bytes required')
    raw = raw.encode('utf-8') if isinstance(raw, str) else raw
    if len(raw) > MAX_OUTPUT_BYTES:
        raise DarkMatterInputError('driver output exceeds bounded transport')
    result = strict(raw)
    keys(result, ('schema_version', 'status', 'candidate', 'mass_gev', 'channels', 'channel_fraction_remainder', *SCALARS), 'driver output')
    if type(result['schema_version']) is not int or result['schema_version'] != 1 or result['status'] != 'ok':
        raise DarkMatterInputError('successful driver schema1 required')
    model = request['model']
    candidate = next(p for p in model['particles'] if p['name'] == model['candidate'])
    if result['candidate'] != model['candidate'] or number(result['mass_gev'], 'returned mass', positive=True) != candidate['mass_gev']:
        raise DarkMatterInputError('driver candidate/mass differs from supplied model')
    for name in SCALARS:
        number(result[name], name, positive=name == 'xf')
    channels = result['channels']
    if type(channels) is not list or not 1 <= len(channels) <= 10000:
        raise DarkMatterInputError('bounded annihilation channel population required')
    names = {p['name'] for p in model['particles'] if p['odd']}
    seen = set()
    for channel in channels:
        keys(channel, ('fraction', 'incoming', 'outgoing'), 'annihilation channel')
        fraction = number(channel['fraction'], 'channel fraction')
        if fraction > 1:
            raise DarkMatterInputError('channel fraction must not exceed one')
        for key in ('incoming', 'outgoing'):
            if type(channel[key]) is not list or len(channel[key]) != 2:
                raise DarkMatterInputError('two incoming and outgoing channel states required')
            for state in channel[key]: text(state, 'channel state')
        if not set(channel['incoming']) <= names:
            raise DarkMatterInputError('incoming channel state absent from odd particle inventory')
        identity = (tuple(sorted(channel['incoming'])), tuple(sorted(channel['outgoing'])))
        if identity in seen:
            raise DarkMatterInputError('duplicate channel fraction')
        seen.add(identity)
    remainder = number(result['channel_fraction_remainder'], 'omitted channel fraction')
    if remainder > 1 or not math.isclose(math.fsum(c['fraction'] for c in channels) + remainder, 1., rel_tol=0., abs_tol=1e-9):
        raise DarkMatterInputError('complete channel fractions plus remainder must sum to one')
    return {'schema_version': 1, 'operation': MODE, 'status': 'passed', 'status_scope': SCOPE,
            'study_id': request['study_id'], 'model': deepcopy(model),
            'parameters': deepcopy(request['parameters']), 'calculation': deepcopy(request['calculation']),
            'astrophysics': deepcopy(request['astrophysics']), 'observables': result,
            'units': dict(SCALARS, mass_gev='GeV', channel_fraction_remainder='1'),
            'driver_sha256': hashlib.sha256(raw).hexdigest(),
            'physics_validated': False, 'execution_authorized': False, 'original_task_complete': False}


def compare_reference(value, row, *, units, conditions, relative_tolerance, text):
    """General numerical comparator; source values and scope are supplied inputs."""
    if row.get('status') != 'filled':
        raise DarkMatterInputError('reference value pending source extraction')
    validate_row(row, text=text)
    if row['units'] != units or row['conditions'] != conditions:
        raise DarkMatterInputError('reference units/conditions differ from computed units/conditions')
    for scalar, label in ((value, 'computed value'), (row['value'], 'reference value')):
        if type(scalar) not in (int, float) or not math.isfinite(scalar):
            raise DarkMatterInputError('finite numerical ' + label + ' required')
    number(relative_tolerance, 'relative tolerance')
    if row['value'] == 0:
        raise DarkMatterInputError('nonzero reference required for relative tolerance')
    # Compare the supplied decimal representations without float subtraction
    # moving an exactly-on-boundary value outside the declared tolerance.
    with localcontext() as decimal_context:
        decimal_context.prec = 50
        difference = abs(Decimal(str(value)) - Decimal(str(row['value'])))
        reference_size = abs(Decimal(str(row['value'])))
        outside = difference > Decimal(str(relative_tolerance)) * reference_size
        residual = float(difference / reference_size)
    if outside:
        raise DarkMatterInputError(f'reference tolerance failed: residual {residual} > {relative_tolerance}')
    return {'reference_id': row['id'], 'relative_residual': residual,
            'relative_tolerance': relative_tolerance, 'status': 'passed'}


def compare_direct_detection(result, row, *, text):
    """Exact supplied curve node; no extrapolation or hidden halo rescaling."""
    if row.get('status') != 'filled':
        raise DarkMatterInputError('direct-detection limit pending source extraction')
    validate_row(row, text=text)
    conditions = row['conditions']
    halo = astrophysics(conditions.get('astrophysics'))
    computed = astrophysics(result['astrophysics'])
    for key in computed:
        if computed[key] != halo[key]:
            raise DarkMatterInputError(f'{key} conventions differ: computed {computed[key]!r}; limit {halo[key]!r}')
    interaction, nucleon = conditions.get('interaction'), conditions.get('nucleon')
    if interaction not in ('si', 'sd') or nucleon not in ('p', 'n'):
        raise DarkMatterInputError('explicit limit interaction and nucleon required')
    if row['quantity'] != 'sigma-' + interaction + '-' + nucleon:
        raise DarkMatterInputError('limit quantity differs from interaction/nucleon')
    if row['units'] != 'cm^2' or conditions.get('mass_gev') != result['observables']['mass_gev']:
        raise DarkMatterInputError('limit units/mass differ; supply a cited exact curve node')
    limit = number(row['value'], 'direct-detection limit', positive=True)
    prediction = number(result['observables'][f'sigma_{interaction}_{nucleon}_cm2'], 'computed cross section')
    return {'reference_id': row['id'], 'source': deepcopy(row['source']), 'locator': row['locator'],
            'conditions': deepcopy(conditions), 'prediction_cm2': prediction,
            'limit_cm2': limit, 'ratio': prediction / limit, 'above_limit': prediction > limit,
            'scope': 'Comparison with supplied cited limit; confidence and applicability are source conventions'}


def model_sources(files, base):
    """Authenticate supplied CalcHEP/UFO members; never import model Python."""
    if type(files) is not dict or not files or len(files) > 20000:
        raise DarkMatterInputError('complete supplied model file manifest required')
    capture = Capture(); result = {}
    for name, declaration in files.items():
        path = Path(name)
        if type(name) is not str or path.is_absolute() or path.as_posix() != name or '..' in path.parts:
            raise DarkMatterInputError('ordinary relative model member required')
        result[name] = capture.read(declaration, base)
    capture.finish()
    return result


def validate(task):
    keys(task, ('config',), 'dark-matter ordinary task'); pin(task['config'])
    return deepcopy(task)


def _load(task, base, capture):
    validate(task)
    path, raw = capture.read(task['config'], base)
    config = strict(raw)
    keys(config, ('schema_version', 'request', 'tool', 'model_files', 'binding_sources', 'binary', 'resources', 'limits'), 'dark-matter execution config')
    if type(config['schema_version']) is not int or config['schema_version'] != 1:
        raise DarkMatterInputError('execution config schema1 required')
    request = validate_request(capture.document(config['request'], path.parent))
    keys(config['tool'], ('root', 'decision'), 'tool source')
    text(config['tool']['root'], 'tool source root')
    decision = capture.document(config['tool']['decision'], path.parent)
    source_root = Path(config['tool']['root'])
    if not source_root.is_absolute(): source_root = path.parent / source_root
    decision_path = Path(config['tool']['decision']['path'])
    if not decision_path.is_absolute(): decision_path = path.parent / decision_path
    sources = source_decision(decision, decision_path.parent)
    for name, (member, raw) in sources.items():
        if member != source_root / name:
            raise DarkMatterInputError('source root differs from pinned tool decision')
        capture.read({'path': str(member), 'size': len(raw),
                      'sha256': hashlib.sha256(raw).hexdigest()}, path.parent)
    for population in ('model_files', 'binding_sources'):
        members = model_sources(config[population], path.parent)
        for member in members.values():
            capture.read({'path': str(member[0]), 'size': len(member[1]),
                          'sha256': hashlib.sha256(member[1]).hexdigest()}, path.parent)
    binary, _ = capture.read(config['binary'], path.parent, limit=64 * 1024**2)
    if not binary.stat().st_mode & 0o111:
        raise DarkMatterInputError('executable per-model binary required')
    keys(config['resources'], ('max_seconds', 'max_ram_mib', 'max_output_bytes'), 'native resource ceilings')
    for name, low, high in (('max_seconds', 1, 3600), ('max_ram_mib', 128, 8192), ('max_output_bytes', 1, MAX_OUTPUT_BYTES)):
        value = config['resources'][name]
        if type(value) is not int or not low <= value <= high:
            raise DarkMatterInputError('bounded integer resource required: ' + name)
    if type(config['limits']) is not list or len(config['limits']) > 10000:
        raise DarkMatterInputError('bounded supplied limit rows required')
    for limit in config['limits']:
        keys(limit, ('row', 'text'), 'cited limit source')
        row = capture.document(limit['row'], path.parent)
        _, extracted = capture.read(limit['text'], path.parent)
        # Validate conventions and citations before spending native work.
        synthetic = {'astrophysics': request['astrophysics'], 'observables': {
            'mass_gev': next(p['mass_gev'] for p in request['model']['particles'] if p['name'] == request['model']['candidate']),
            **{k: 0. for k in SCALARS}}}
        compare_direct_detection(synthetic, row, text=extracted.decode('utf-8'))
    return path, config, request, binary


def inputs(task, base):
    capture = Capture(); _load(task, base, capture); capture.finish()
    return list(capture.rows)


def context_inputs(task, base):
    return inputs(task, base)


def context(task, base):
    capture = Capture(); _, config, request, _ = _load(task, base, capture); capture.finish()
    return {'operation': MODE, 'request': request, 'resources': config['resources'],
            'inputs': list(capture.rows.values()), 'execution_authorized': False, 'physics_validated': False}


def execution_seconds(task, base):
    capture = Capture(); _, config, _, _ = _load(task, base, capture); capture.finish()
    return config['resources']['max_seconds']


def validate_scope(spec):
    policy = spec.get('review_policy', {}).get('policy', {})
    scopes = policy.get('claim_scopes', {})
    if (spec.get('schema_version') != 2 or spec.get('max_attempts') != 1
            or policy.get('max_redos') != 0 or set(scopes) != {SCOPE}
            or scopes[SCOPE].get('actions') != ['delivery']):
        raise DarkMatterInputError('one-attempt delivery-only dark-matter scope required')
    return spec


def specification(task, *, source, assumptions, actors, max_seconds, approval_mode='physicist'):
    validate(task)
    keys(actors, ('proposer', 'executor', 'physics_critic', 'skeptical_verifier', 'physics_decider'), 'actual role actors')
    for actor in actors.values(): text(actor, 'actual actor')
    checks = [{'id': 'integrity', 'kind': 'integrity'},
              {'id': 'model_completeness', 'kind': 'scientific'},
              {'id': 'observable_conventions', 'kind': 'scientific'}]
    value = {'schema_version': 2, 'mode': MODE, 'source': source,
             'assumptions': assumptions, 'task': task, 'approval_mode': approval_mode,
             'max_attempts': 1, 'max_seconds': max_seconds,
             'review_policy': {'schema_version': 1, 'policy': {
                 'schema_version': 1, 'actors': actors, 'max_redos': 0,
                 'allowed_changed_paths': [], 'allowed_stages': ['science'],
                 'required_checks': checks, 'claim_scopes': {
                     SCOPE: {'checks': [c['id'] for c in checks], 'actions': ['delivery']}}},
                 'correction_contract': {'task_fields': [], 'input_slots': []}}}
    from ravel.workflow import science
    science.validate(value)
    return value


def _approved(task, output):
    from ravel.workflow import science
    for rundir in (output, *output.parents):
        if (rundir / 'inputs/science-plan.json').is_file():
            plan = science.verify_worker(rundir)
            spec = science.execution_spec(rundir)
            validate_scope(spec)
            if spec['mode'] != MODE or spec['task'] != task or output != (rundir / plan['output_directory'] / MODE).absolute():
                raise DarkMatterInputError('approved selected dark-matter worker differs')
            return plan
    raise DarkMatterInputError('actual approved ordinary dark-matter worker required')


def _output_census(root, maximum):
    from ravel.workflow.research_cycle import _bounded_source_snapshot
    result = {}; total = 0
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise DarkMatterInputError('ordinary native output members required')
        if path.is_dir(): continue
        if len(result) >= 10000 or path.stat().st_size > maximum - total:
            raise DarkMatterInputError('complete native output population exceeds ceiling')
        _, raw = _bounded_source_snapshot(path, maximum - total)
        total += len(raw)
        result[path.relative_to(root).as_posix()] = {
            'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    return result


def run(task, base, output):
    """Approved binary execution through the existing bounded native supervisor.

    Dispatcher integration belongs to registration. Calling this function
    directly never bypasses science.verify_worker or the selected-output check.
    """
    output = Path(output).absolute(); plan = _approved(task, output)
    capture = Capture(); path, config, request, binary = _load(task, base, capture)
    if config['resources']['max_seconds'] > plan['max_seconds']:
        raise DarkMatterInputError('native budget exceeds admitted science plan')
    capture.finish()
    if output.exists() or any(p.is_symlink() for p in (output, *output.parents)):
        raise DarkMatterInputError('fresh ordinary output directory required')
    output.mkdir(parents=True)
    native = output / 'native'; native.mkdir()
    request_path = native / 'request.json'
    from ravel.physics.parameter_space_sampling_core import Emitted, emission_bytes
    emitted = Emitted(native)
    emitted.bytes(request_path, emission_bytes(request))
    # The admitted binding writes to this exact fresh path. No shell, importer
    # or fallback physics tool is invoked in the Ravel process.
    from ravel.physics.reinterpret_db import execute_native
    import shutil
    if shutil.disk_usage(native).free < 25 * 1024**3 + config['resources']['max_output_bytes']:
        raise DarkMatterInputError('25 GiB free-disk floor plus admitted output reserve required')
    try:
        receipt = execute_native([str(binary), str(request_path), str(native / 'driver.json')], native, config['resources'])
    except ValueError as exc:
        # The executor refuses a nonzero exit or a resource violation itself.
        raise DarkMatterInputError('micrOMEGAs driver failed; native logs retained: ' + str(exc)) from exc
    emitted.finish(); capture.finish()
    if receipt['returncode'] != 0:
        raise DarkMatterInputError('micrOMEGAs driver failed; native logs retained')
    from ravel.workflow.research_cycle import _bounded_source_snapshot
    raw_census = _output_census(native, config['resources']['max_output_bytes'])
    raw_path, raw = _bounded_source_snapshot(native / 'driver.json', config['resources']['max_output_bytes'])
    result = parse_driver_output(raw, request)
    returned = Capture()
    returned.read({'path': str(raw_path), 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}, native)
    result['comparisons'] = []
    for limit in config['limits']:
        row = capture.document(limit['row'], path.parent)
        _, extracted = capture.read(limit['text'], path.parent)
        result['comparisons'].append(compare_direct_detection(result, row, text=extracted.decode('utf-8')))
    result['tool_version'] = capture.document(config['tool']['decision'], path.parent)['version']
    result['native_receipt'] = receipt
    result['raw_census'] = raw_census
    result['input_commitments'] = list(capture.rows.values())
    publish(output, result, request['report'])
    emitted.finish(); returned.finish(); capture.finish()
    if _output_census(native, config['resources']['max_output_bytes']) != raw_census:
        raise DarkMatterInputError('ending native output census differs')
    return result


def write_report(result, out):
    """The selected report is already published by run under its supplied name."""
    if result.get('status_scope') != SCOPE or result.get('physics_validated') is not False:
        raise DarkMatterInputError('scoped dark-matter delivery required')
    return result


def source_decision(record, base):
    """Offline pinned source/licence evidence, before any queued build command."""
    keys(record, ('tool', 'version', 'files', 'licence', 'licence_sha256', 'redistribute'), 'source decision')
    if record['tool'] != 'micromegas' or record['redistribute'] is not False:
        raise DarkMatterInputError('micrOMEGAs external-program nonredistribution decision required')
    text(record['version'], 'owner-selected tool version')
    sources = model_sources(record['files'], base)
    licence = record['licence']
    if licence not in sources or hashlib.sha256(sources[licence][1]).hexdigest() != record['licence_sha256']:
        raise DarkMatterInputError('source licence bytes differ from decision')
    return sources


def prepare_model(document, base, data_root):
    """Cold on-demand source staging into a fresh data-root/model directory.

    A supplied buildable CalcHEP package or a UFO conversion build recipe is
    copied as authenticated bytes. No model Python or converter is imported.
    The supplied Makefile must compile main.c with driver.h and its reviewed
    native binding against MICROMEGAS_ROOT, producing main in this directory.
    """
    keys(document, ('model', 'files', 'binding_files'), 'per-model build package')
    model = document['model']
    if type(model) is not str or re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}', model) is None:
        raise DarkMatterInputError('safe per-model identifier required')
    model_files = model_sources(document['files'], base)
    bindings = model_sources(document['binding_files'], base)
    if set(model_files) & set(bindings) or 'Makefile' not in model_files:
        raise DarkMatterInputError('disjoint model and binding members with supplied Makefile required')
    if {'main.c', 'driver.h', 'main'} & (set(model_files) | set(bindings)):
        raise DarkMatterInputError('model package overlaps owned driver/output')
    data_root = Path(data_root).absolute()
    target = data_root / model
    if target.exists() or any(p.is_symlink() for p in (target, *target.parents)):
        raise DarkMatterInputError('fresh ordinary per-model data directory required')
    # A supplied model is a data-root build, never a repository code import.
    import shutil
    ancestor = data_root
    while not ancestor.exists(): ancestor = ancestor.parent
    total = sum(len(raw) for _, raw in [*model_files.values(), *bindings.values()])
    if shutil.disk_usage(ancestor).free < 25 * 1024**3 + total + 300 * 1024**2:
        raise DarkMatterInputError('25 GiB free-disk floor plus per-model build reserve required')
    from ravel.physics.parameter_space_sampling_core import Emitted
    staged = Emitted(target)
    for name, (_, raw) in {**model_files, **bindings}.items(): staged.bytes(target / name, raw)
    driver = Path(__file__).with_name('micromegas_driver')
    staged.bytes(target / 'main.c', (driver / 'main.c.in').read_bytes())
    staged.bytes(target / 'driver.h', (driver / 'driver.h').read_bytes())
    staged.finish()
    # Source mutation during staging is refused; failed staged files remain
    # visible and are never accepted as a replacement source baseline.
    model_sources(document['files'], base); model_sources(document['binding_files'], base)
    return target


def build_preflight(source, decision):
    source = Path(source).absolute()
    from ravel.setup.manifest import read_json
    sources = source_decision(read_json(decision), Path(decision).parent)
    for name, (path, _) in sources.items():
        if path != source / name:
            raise DarkMatterInputError('source root differs from pinned source decision')
    import shutil
    if shutil.disk_usage(source).free < 25 * 1024**3 + 600 * 1024**2:
        raise DarkMatterInputError('25 GiB free-disk floor plus tool build reserve required')
    return source


def main(argv=None):
    """Cold helpers consumed by the queued native build recipe; no launch CLI."""
    import argparse
    from ravel.setup.manifest import read_json
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    check = commands.add_parser('build-preflight')
    check.add_argument('--source', required=True, type=Path)
    check.add_argument('--decision', required=True, type=Path)
    stage = commands.add_parser('prepare-model')
    stage.add_argument('--package', required=True, type=Path)
    stage.add_argument('--data-root', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.action == 'build-preflight':
        print(build_preflight(args.source, args.decision))
    else:
        print(prepare_model(read_json(args.package), args.package.parent, args.data_root))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
