"""Supplied full likelihoods with declared coupling or cross-section parameters.

Point multipliers are supplied formulas, never inferred physics inputs. Native
recipes are read-only: execution belongs to the admitted scientific lifecycle.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import time

import numpy as np

MODE = 'higgs-published-likelihood'
REGISTRY = Path(__file__).parents[1] / 'data/higgs/combine-physics-models.json'
MAX_POINTS = 10000
MAX_SECONDS = 86400
ACQUISITION = Path(__file__).parents[1] / 'data/higgs/registration/higgs-published-likelihood.json'


class InterfaceUnavailable(RuntimeError):
    """A required upstream adapter has not supplied its declared seam."""


def _keys(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError(label + ' declaration requires exactly ' + ', '.join(sorted(fields)))


def _finite(value, label):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.number)) or not math.isfinite(value):
        raise ValueError('finite ' + label + ' required')
    return float(value)


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('nonblank ' + label + ' required')
    return value


def _ceiling(value):
    if type(value) is not int or not 1 <= value <= MAX_SECONDS:
        raise ValueError('bounded integer time ceiling required')
    return value


def _json(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def admitted_model(declaration, *, admitted=None):
    """Match exact release, POI population and ordered options before any work."""
    _keys(declaration, {'id', 'combine_release', 'pois', 'options'}, 'physics model')
    registry = _json(REGISTRY.read_bytes()) if admitted is None else deepcopy(admitted)
    if registry.get('schema_version') != 1 or not isinstance(registry.get('models'), list):
        raise ValueError('admitted physics model registry required')
    if declaration['combine_release'] != registry['combine_release']:
        raise ValueError('physics model release differs from pinned Combine release')
    matches = [row for row in registry['models'] if row['id'] == declaration['id']]
    if len(matches) != 1:
        raise ValueError('physics model is not uniquely admitted')
    model = matches[0]
    if (model['combine_release'] != registry['combine_release'] or
            declaration['pois'] != model['pois'] or declaration['options'] != model['options']):
        raise ValueError('physics model release, POIs or options differ from admitted declaration')
    if (not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', model['module']) or
            not re.fullmatch(r'[A-Za-z_]\w*', model['model']) or
            not isinstance(model['pois'], list) or not model['pois'] or
            len(set(model['pois'])) != len(model['pois']) or
            any(not re.fullmatch(r'[A-Za-z_]\w*', p) for p in model['pois']) or
            not isinstance(model['options'], list) or any(not isinstance(v, str) or not v or '\x00' in v for v in model['options'])):
        raise ValueError('invalid admitted model declaration')
    return {**model, 'image_digest': registry['image_digest']}


def combine_commands(config, tools, work, declaration, *, admitted=None):
    """Construct an exact recipe through the existing native command builder.

    An externally supplied registry is useful for read-only recipe qualification;
    it cannot authorize native execution or change the shipped admission list.
    """
    selected = admitted_model(declaration, admitted=admitted)
    from . import native_likelihood
    if (config['runtime']['expected']['combine_version'] != selected['combine_release'] or
            config['runtime']['transport'].get('manifest_digest') != selected['image_digest']):
        raise ValueError('native runtime release/image differs from admitted model')
    if config['fit']['method'] != 'MultiDimFit' or config['fit']['poi'] not in selected['pois']:
        raise ValueError('declared physics model requires its admitted profile POI')
    if config['model'].get('physics_model') is not None or 'construction' in config['model'] or 'source_graph' in config['model']:
        raise ValueError('physics model cannot replace an existing native construction')
    build, fit = native_likelihood.commands(config, tools, Path(work))
    if '-P' in build or fit is None:
        raise ValueError('physics model requires an unmodified native scan recipe')
    build += ['-P', selected['module'] + ':' + selected['model']]
    for option in selected['options']:
        build += ['--PO', option]
    fit[fit.index('--redefineSignalPOIs') + 1] = ','.join(selected['pois'])
    return build, fit


def parse_combine_scan(log, fit):
    """Preserve native tree coverage, sentinel and saved-fit diagnostic checks."""
    from .native_likelihood import extract_native_result
    return extract_native_result(log, fit)


def run_combine(task, base, out, declaration, *, admitted=None):
    """Production dispatch waits for the native owner's model-option seam."""
    selected = admitted_model(declaration, admitted=admitted)
    from . import native_likelihood
    runner = getattr(native_likelihood, 'run_with_physics_model', None)
    if runner is None:
        raise InterfaceUnavailable('native physics-model run interface awaits owner integration')
    # A qualification registry must never grant execution authority.
    selected = admitted_model(declaration)
    from .backend_driver import calling_authority
    calling_authority()
    return runner(task, base, out, physics_model=selected)


def parameterization_program(bundle):
    """Convert the upstream parameterization bundle by its explicit interface."""
    try:
        from . import higgs_parameterization
    except ImportError as exc:
        raise InterfaceUnavailable('awaits parameterization interface') from exc
    convert = getattr(higgs_parameterization, 'published_likelihood_program', None)
    if convert is None:
        raise InterfaceUnavailable('awaits parameterization published_likelihood_program interface')
    return convert(bundle)


def _program(declaration):
    from .inference.formula import Program
    _keys(declaration, {'framework', 'parameters', 'program', 'rates'}, 'parameterization')
    if declaration['framework'] not in ('kappa', 'stxs'):
        raise ValueError('declared kappa or stxs framework required')
    parameters = declaration['parameters']
    if not isinstance(parameters, list) or not parameters:
        raise ValueError('nonempty parameter population required')
    names, bounds, initial = [], [], []
    formula_parameters = []
    for row in parameters:
        _keys(row, {'name', 'bounds', 'initial', 'unit', 'label'}, 'parameter')
        if not isinstance(row['bounds'], list) or len(row['bounds']) != 2:
            raise ValueError('two finite parameter bounds required')
        lo, hi = [_finite(v, 'parameter bound') for v in row['bounds']]
        start = _finite(row['initial'], 'parameter initial value')
        if lo >= hi or not lo <= start <= hi:
            raise ValueError('parameter initial value outside ordered domain')
        names.append(row['name']); bounds.append((lo, hi)); initial.append(start)
        formula_parameters.append({k: row[k] for k in ('name', 'unit', 'label')})
    program = Program(declaration['program'], formula_parameters)
    rates = {}
    if not isinstance(declaration['rates'], list) or not declaration['rates']:
        raise ValueError('nonempty production decay rate population required')
    for row in declaration['rates']:
        _keys(row, {'production', 'decay', 'output'}, 'rate')
        key = (_text(row['production'], 'production'), _text(row['decay'], 'decay'))
        if key in rates or row['output'] not in program.labels:
            raise ValueError('duplicate rate or undeclared formula output')
        rates[key] = row['output']
    return program, rates, names, bounds, initial


def _factors(program, rates, names, point):
    if not isinstance(point, dict) or set(point) != set(names):
        raise ValueError('point must supply every declared parameter exactly')
    values = program.evaluate({name: _finite(point[name], 'point coordinate') for name in names})
    factors = {key: _finite(values[output].item(), 'signal multiplier') for key, output in rates.items()}
    if any(value < 0 for value in factors.values()):
        raise ValueError('negative signal multiplier')
    return factors


def patch_workspace(workspace, sample_map, factors, *, measurement, signal_modifier):
    """Replace each source signal-strength modifier by a fixed point multiplier.

    Fixed normfactors multiply the complete nuisance-varied sample, preserving
    histosys, MC-constraint and correlated nuisance semantics at zero rate too.
    Every sample carrying the declared signal normfactor is a signal sample.
    No background or observation is changed. The source input remains intact.
    """
    import pyhf
    original = pyhf.Workspace(deepcopy(workspace))
    measurements = [m for m in original['measurements'] if m['name'] == measurement]
    if len(measurements) != 1 or measurements[0]['config']['poi'] != signal_modifier:
        raise ValueError('measurement must declare the source signal modifier as its POI')
    signals, all_samples = set(), set()
    for channel in original['channels']:
        for sample in channel['samples']:
            key = (channel['name'], sample['name'])
            if key in all_samples:
                raise ValueError('duplicate channel/sample identity')
            all_samples.add(key)
            modifiers = [m for m in sample['modifiers'] if m['name'] == signal_modifier]
            if modifiers:
                if len(modifiers) != 1 or modifiers[0]['type'] != 'normfactor':
                    raise ValueError('source signal modifier must be a unique normfactor')
                signals.add(key)
    if not signals:
        raise ValueError('no declared signal samples')
    mapped = {}
    if not isinstance(sample_map, list):
        raise ValueError('sample map must be an explicit list')
    for row in sample_map:
        _keys(row, {'channel', 'sample', 'production', 'decay'}, 'sample map')
        key = (_text(row['channel'], 'channel'), _text(row['sample'], 'sample'))
        pair = (_text(row['production'], 'production'), _text(row['decay'], 'decay'))
        if key in mapped or key not in signals:
            raise ValueError('duplicate, unknown or background sample in signal map')
        if pair not in factors:
            raise ValueError('missing production decay multiplier')
        value = _finite(factors[pair], 'signal multiplier')
        if value < 0:
            raise ValueError('negative signal multiplier')
        mapped[key] = value
    if signals != set(mapped):
        raise ValueError('unmapped signal samples: ' + repr(sorted(signals - set(mapped))))
    patched = deepcopy(dict(original))
    reserved = {m['name'] for c in patched['channels'] for s in c['samples'] for m in s['modifiers']}
    reserved.update(p['name'] for m in patched['measurements'] for p in m['config']['parameters'])
    parameters, patches = [], []
    for ci, channel in enumerate(patched['channels']):
        for si, sample in enumerate(channel['samples']):
            key = (channel['name'], sample['name'])
            if key not in mapped:
                continue
            name = 'ravel_point_multiplier_' + str(len(parameters))
            if name in reserved:
                raise ValueError('point multiplier name collides with source parameter')
            value = mapped[key]
            parameters.append({'name': name, 'inits': [value], 'bounds': [[0.0, max(1.0, value * 2)]], 'fixed': True})
            for mi, modifier in enumerate(sample['modifiers']):
                if modifier['name'] == signal_modifier:
                    modifier['name'] = name
                    patches.append({'op': 'replace', 'path': f'/channels/{ci}/samples/{si}/modifiers/{mi}/name', 'value': name})
    chosen = deepcopy(measurements[0])
    chosen['config']['parameters'] = [p for p in chosen['config']['parameters'] if p['name'] != signal_modifier] + parameters
    chosen['config']['poi'] = parameters[0]['name']
    patched['measurements'] = [chosen]
    patches.append({'op': 'replace', 'path': '/measurements', 'value': deepcopy(patched['measurements'])})
    # Independent application validates the emitted per-point JSON Patch.
    from jsonpatch import JsonPatch
    applied = JsonPatch(patches).apply(dict(original))
    if applied != patched:
        raise ValueError('point patch differs from declared replacement')
    return patched, patches


def scan_pyhf(workspace, sample_map, parameterization, points, *, measurement, signal_modifier, tolerance=1e-9,
              diagnostic_record=None, deadline=None):
    """Profile unchanged source nuisances and fit the declared parameter domain.

    Delta(-2 ln L) uses a separate continuous bounded fit, never a grid minimum.
    Returned optimizer convergence is a local diagnostic, not globality proof.
    A monotonic deadline is checked before each profile; it cannot interrupt one.
    """
    import pyhf
    from scipy.optimize import minimize
    from .pyhf_exclude import MODIFIER_SETTINGS, robust_optimizer
    from .published_model import canonical_background_digest
    program, rates, names, bounds, initial = _program(parameterization)
    tolerance = _finite(tolerance, 'fit tolerance')
    if tolerance <= 0 or not isinstance(points, list) or not 0 < len(points) <= MAX_POINTS:
        raise ValueError('positive tolerance and bounded nonempty point population required')
    for point in points:
        _factors(program, rates, names, point)
        if any(not lo <= point[name] <= hi for name, (lo, hi) in zip(names, bounds)):
            raise ValueError('scan point outside declared parameter domain')
    # Complete mapping validation precedes optimizer setup or any evaluation.
    patch_workspace(workspace, sample_map, _factors(program, rates, names, dict(zip(names, initial))),
                    measurement=measurement, signal_modifier=signal_modifier)
    cache = {}
    diagnostics = diagnostic_record if diagnostic_record is not None else {}
    diagnostics['profile_attempts'] = []
    counters = ('n_fits', 'n_fallback', 'n_nan_flagged', 'n_escalated')
    start = {key: getattr(robust_optimizer, key) for key in counters}

    def guard():
        counts = {key: getattr(robust_optimizer, key) - start[key] for key in counters}
        return {'n_minimizations': counts.pop('n_fits'), **counts, 'escalated': bool(robust_optimizer.escalated)}
    previous_backend = pyhf.get_backend()
    pyhf.set_backend('numpy', robust_optimizer(tolerance=tolerance, maxiter=20000), precision='64b')
    try:
        def profile(coordinates):
            key = tuple(float(v) for v in coordinates)
            if key in cache:
                return cache[key]
            if deadline is not None and time.monotonic() > deadline:
                raise RuntimeError('declared time ceiling reached before the profile population completed')
            point = dict(zip(names, key))
            patched, patch = patch_workspace(workspace, sample_map, _factors(program, rates, names, point),
                                              measurement=measurement, signal_modifier=signal_modifier)
            ws = pyhf.Workspace(patched)
            model = ws.model(measurement_name=measurement, modifier_settings=MODIFIER_SETTINGS)
            data = ws.data(model)
            inits = model.config.suggested_init()
            fixed = model.config.suggested_fixed()
            if all(fixed):
                pars = inits
                value = -2 * np.asarray(model.logpdf(pars, data)).item()
                optimizer = 'all-source-parameters-fixed'
            else:
                pars, value = pyhf.infer.mle.fit(data, model, init_pars=inits,
                    par_bounds=model.config.suggested_bounds(), fixed_params=fixed, return_fitted_val=True)
                value = np.asarray(value).item()
                optimizer = 'conditional-source-nuisance-fit'
            result = {'coordinates': point, 'twice_nll': _finite(value, 'profile NLL'),
                      'parameters': dict(zip(model.config.par_names, [float(v) for v in pars])),
                      'patch': patch, 'optimizer': optimizer}
            cache[key] = result
            diagnostics['profile_attempts'].append(deepcopy(result))
            return result
        fit = minimize(lambda x: profile(x)['twice_nll'], initial, bounds=bounds, method='Powell',
                       options={'xtol': tolerance, 'ftol': tolerance, 'maxiter': 1000})
        diagnostics['parameter_optimizer'] = {'success': bool(fit.success), 'message': str(fit.message),
                                              'evaluations': int(fit.nfev)}
        if not fit.success or not math.isfinite(fit.fun):
            raise RuntimeError('declared parameter fit failed: ' + str(fit.message))
        best = dict(profile(fit.x))
        rows = [dict(profile([p[n] for n in names])) for p in points]
        for row in rows:
            delta = row['twice_nll'] - best['twice_nll']
            if delta < -max(1e-6, 10 * tolerance):
                raise RuntimeError('scan point improves continuous best fit; fit requires review')
            row['delta_twice_nll'] = delta
        return {'schema_version': 1, 'mode': MODE, 'engine': 'pyhf', 'status': 'passed',
                'physics_validated': False, 'framework': parameterization['framework'],
                'workspace_sha256': canonical_background_digest(workspace),
                'parameterization': deepcopy(parameterization), 'sample_map': deepcopy(sample_map),
                'best_fit': best, 'scan': rows, 'fit_diagnostics': {'success': bool(fit.success),
                    'message': str(fit.message), 'evaluations': int(fit.nfev), 'globality_qualified': False,
                    'optimizer_guard': guard()},
                'statistic': 'Delta(-2 ln L) to continuous bounded best fit',
                'limitations': ['Local optimizer diagnostics only; no coverage or physics qualification.',
                                'Physics rate formulas, parameter domains and sample assignments are supplied inputs.']}
    finally:
        diagnostics['optimizer_guard'] = guard()
        pyhf.set_backend(*previous_backend)


def hs3_formula_request(model, parameterization, bindings, points):
    """Declare RooFit formula-function replacement for the repaired owner seam."""
    program, rates, names, bounds, _ = _program(parameterization)
    if not isinstance(model, dict) or not isinstance(bindings, list) or not bindings:
        raise ValueError('HS3 model and explicit formula bindings required')
    functions = []
    seen = set()
    for binding in bindings:
        _keys(binding, {'function', 'production', 'decay'}, 'HS3 binding')
        name = _text(binding['function'], 'HS3 function')
        pair = (binding['production'], binding['decay'])
        if name in seen or pair not in rates:
            raise ValueError('duplicate HS3 function or missing production decay formula')
        seen.add(name)
        functions.append({'name': name, 'output': rates[pair]})
    if not isinstance(points, list) or not 0 < len(points) <= MAX_POINTS:
        raise ValueError('bounded HS3 point population required')
    for point in points:
        _factors(program, rates, names, point)
        if any(not lo <= point[n] <= hi for n, (lo, hi) in zip(names, bounds)):
            raise ValueError('HS3 point outside declared parameter domain')
    return {'model': deepcopy(model), 'parameterization': deepcopy(parameterization),
            'formula_functions': functions, 'points': deepcopy(points), 'physics_validated': False}


def run_hs3(task, base, out, request):
    from . import hs3_likelihood
    runner = getattr(hs3_likelihood, 'run_with_formula_functions', None)
    if runner is None:
        raise InterfaceUnavailable('awaits HS3 repair')
    from .backend_driver import calling_authority
    calling_authority()
    return runner(task, base, out, reparameterization=request)


def validate(task):
    _keys(task, {'input'}, 'likelihood task')
    _text(task['input'], 'input path')


def acquisition_configuration(record_identifiers, *, fetch_requested=False):
    """Configure existing acquisition on supplied records; never fetch here."""
    if (not isinstance(record_identifiers, list) or not record_identifiers or
            any(not isinstance(v, str) or not v.strip() for v in record_identifiers) or
            len(set(record_identifiers)) != len(record_identifiers) or
            type(fetch_requested) is not bool):
        raise ValueError('explicit unique nonblank record population and boolean fetch request required')
    config = _json(ACQUISITION.read_bytes())['acquire_published_configuration']
    return {'operation': 'acquire-published', 'record_identifiers': list(record_identifiers),
            'fetch_requested': fetch_requested, 'resource_detection': deepcopy(config['resource_detection'])}


def _bound_document(pin, base):
    from ravel.workflow.science import regular
    _keys(pin, {'path', 'sha256'}, 'input pin')
    if not isinstance(pin['sha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', pin['sha256']):
        raise ValueError('lowercase SHA256 input pin required')
    path = regular(pin['path'], base)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != pin['sha256']:
        raise ValueError('changed likelihood input bytes')
    return path, _json(raw)


def _load(task, base):
    from ravel.workflow.science import regular
    from .supplied_contracts import output_contract
    validate(task)
    path = regular(task['input'], base)
    raw = path.read_bytes()
    doc = _json(raw)
    common = {'schema_version', 'kind', 'engine', 'output'}
    if not isinstance(doc, dict) or type(doc.get('schema_version')) is not int or doc['schema_version'] != 1 or doc.get('kind') != MODE:
        raise ValueError('supplied likelihood configuration required')
    fields = {'pyhf': {'likelihood', 'measurement', 'signal_modifier', 'sample_map', 'parameterization', 'points', 'fit_tolerance',
                       'max_seconds'},
              'combine': {'native_configuration', 'physics_model'},
              'hs3': {'native_configuration', 'parameterization', 'formula_bindings', 'points'}}
    if doc.get('engine') not in fields:
        raise ValueError('declared combine, pyhf or hs3 likelihood engine required')
    _keys(doc, common | fields[doc['engine']], 'likelihood configuration')
    output_contract(doc['output'])
    if doc['engine'] == 'pyhf':
        _ceiling(doc['max_seconds'])
    pin = doc['likelihood'] if doc['engine'] == 'pyhf' else doc['native_configuration']
    payload_path, payload = _bound_document(pin, path.parent)
    if doc['engine'] == 'combine':
        admitted_model(doc['physics_model'])
        return path, raw, doc, payload_path, payload
    declaration = doc['parameterization']
    if isinstance(declaration, dict) and set(declaration) == {'bundle'}:
        declaration = parameterization_program(declaration['bundle'])
        doc['parameterization'] = declaration
    program, rates, names, bounds, initial = _program(declaration)
    if not isinstance(doc['points'], list) or not 0 < len(doc['points']) <= MAX_POINTS:
        raise ValueError('bounded nonempty scan points required')
    for point in doc['points']:
        _factors(program, rates, names, point)
        if any(not lo <= point[n] <= hi for n, (lo, hi) in zip(names, bounds)):
            raise ValueError('scan point outside declared domain')
    if doc['engine'] == 'pyhf':
        if _finite(doc['fit_tolerance'], 'fit tolerance') <= 0:
            raise ValueError('positive tolerance required')
        patch_workspace(payload, doc['sample_map'], _factors(program, rates, names, dict(zip(names, initial))),
                        measurement=doc['measurement'], signal_modifier=doc['signal_modifier'])
    else:
        _, model = _bound_document(payload['model'], payload_path.parent)
        hs3_formula_request(model, declaration, doc['formula_bindings'], doc['points'])
    return path, raw, doc, payload_path, payload


def _hs3_request(doc, payload_path, payload):
    _, model = _bound_document(payload['model'], payload_path.parent)
    return hs3_formula_request(model, doc['parameterization'], doc['formula_bindings'], doc['points'])


def inputs(task, base):
    path, _, doc, payload_path, payload = _load(task, base)
    shared = [path, payload_path, Path(__file__), REGISTRY, ACQUISITION]
    if doc['engine'] == 'pyhf':
        return shared + [Path(__file__).with_name('pyhf_exclude.py'), Path(__file__).with_name('published_model.py'),
                         Path(__file__).with_name('supplied_contracts.py'), Path(__file__).with_name('inference') / 'formula.py']
    if doc['engine'] == 'combine':
        from . import native_likelihood as owner
        observer = getattr(owner, 'inputs_with_physics_model', None)
        if observer is None:
            raise InterfaceUnavailable('native physics-model input interface awaits owner integration')
        selected = admitted_model(doc['physics_model'])
        extra = observer({'input': str(payload_path)}, payload_path.parent, physics_model=selected)
    else:
        from . import hs3_likelihood as owner
        observer = getattr(owner, 'inputs_with_formula_functions', None)
        if observer is None:
            raise InterfaceUnavailable('awaits HS3 repair')
        extra = observer({'input': str(payload_path)}, payload_path.parent,
                         reparameterization=_hs3_request(doc, payload_path, payload))
    return list(dict.fromkeys([*shared, *extra]))


def execution_seconds(task, base):
    """Declared ceiling: the pyhf configuration's own, or the native configuration's."""
    _, _, doc, _, payload = _load(task, base)
    return _ceiling((doc if doc['engine'] == 'pyhf' else payload).get('max_seconds'))


def run(task, base, out):
    """Adapter called by the common approved worker; native work repeats admission."""
    from .supplied_contracts import publish
    started = time.monotonic()
    path, raw, doc, payload_path, payload = _load(task, base)
    # Observe required owner inputs before creating any native attempt directory.
    if doc['engine'] != 'pyhf':
        inputs(task, base)
    out = Path(out)
    if any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError('ordinary owned output required')
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError('fresh output required')
    if doc['engine'] == 'pyhf':
        diagnostics = {}
        try:
            result = scan_pyhf(payload, doc['sample_map'], doc['parameterization'], doc['points'],
                              measurement=doc['measurement'], signal_modifier=doc['signal_modifier'],
                              tolerance=doc['fit_tolerance'], diagnostic_record=diagnostics,
                              deadline=started + doc['max_seconds'])
        except Exception as exc:
            result = {'schema_version': 1, 'mode': MODE, 'engine': 'pyhf', 'status': 'failed',
                      'physics_validated': False, 'diagnostics': diagnostics,
                      'error': {'type': type(exc).__name__, 'message': str(exc)},
                      'limitations': ['Unsuccessful numerical attempt retained; no profile result accepted.']}
    elif doc['engine'] == 'combine':
        result = run_combine({'input': str(payload_path)}, payload_path.parent, out / 'native', doc['physics_model'])
    else:
        result = run_hs3({'input': str(payload_path)}, payload_path.parent, out / 'native',
                        _hs3_request(doc, payload_path, payload))
    result['inputs'] = [*result.get('inputs', []),
                       {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()},
                       {'path': str(payload_path), 'sha256': (doc.get('likelihood') or doc['native_configuration'])['sha256']}]
    publish(out, result, doc['output'])
    return result
