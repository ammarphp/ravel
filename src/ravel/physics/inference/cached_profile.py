"""Bounded cached profiles through the differential-likelihood adapter.

Profiles are conditional objective differences, not calibrated intervals. Every
scheduled start/cell and every issued evaluation remains in the result journal.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import time

import numpy as np
from scipy import optimize

from .. import amplitude_basis as ab, amplitude_response
from . import common, differential, record


class BudgetExceeded(RuntimeError):
    pass


def parameter_contract(parameters, starts, cells):
    ab.require(type(parameters) is list and parameters, 'profile parameters required')
    names = []
    for row in parameters:
        required = {'name', 'unit', 'label', 'value', 'min', 'max', 'constant'}
        ab.require(type(row) is dict and required <= set(row) <= required | {'error'},
                   'complete profile coordinate state required')
        common.parameter({k: row[k] for k in ('name', 'unit', 'label')})
        names.append(row['name'])
        for key in ('value', 'min', 'max'):
            ab.real(row[key], key)
        ab.require(row['min'] < row['max'] and row['min'] <= row['value'] <= row['max']
                   and type(row['constant']) is bool, 'ordered finite coordinate bounds required')
    ab.require(len(set(names)) == len(names), 'unique fit coordinates required')
    ab.require(type(starts) is list and starts and type(cells) is list, 'declared starts and profile cells required')
    for start in starts:
        ab.require(type(start) is dict and set(start) == set(names), 'complete independent start required')
        for row in parameters:
            value = ab.real(start[row['name']])
            ab.require(row['min'] <= value <= row['max'] and (not row['constant'] or value == row['value']),
                       'start outside declared domain or changes constant')
    ids = {'global'}
    for cell in cells:
        ab.require(type(cell) is dict and set(cell) == {'id', 'fixed'}, 'profile cell needs id and fixed')
        ab.text(cell['id'], 'cell id')
        ab.require(cell['id'] not in ids, 'unique cell ids required; global is reserved')
        ids.add(cell['id'])
        ab.require(type(cell['fixed']) is dict and cell['fixed'] and set(cell['fixed']) <= set(names), 'cell fixes declared coordinates')
        for name, value in cell['fixed'].items():
            row = parameters[names.index(name)]
            ab.require(not row['constant'] and row['min'] <= ab.real(value) <= row['max'], 'invalid profile fixed value')
    return names


def profile(model, parameters, starts, cells, *, max_evaluations, max_seconds, tolerance, clock=time.monotonic,
            native_minimizer=None):
    """Independent bounded L-BFGS-B starts, with explicit failures and raw status."""
    names = parameter_contract(parameters, starts, cells)
    ab.require(type(max_evaluations) is int and max_evaluations > 0, 'positive objective evaluation budget required')
    ab.require(ab.real(max_seconds) > 0 and 0 < ab.real(tolerance) < 1, 'positive wall budget and numerical tolerance required')
    begin = clock()
    deadline = begin + max_seconds
    journal, rows = [], []
    schedule = [(cell, index) for cell in [{'id': 'global', 'fixed': {}}, *cells] for index in range(len(starts))]
    exhausted = False

    def evaluate(point, cell, index):
        if len(journal) >= max_evaluations or clock() >= deadline:
            raise BudgetExceeded('objective evaluation or wall budget exhausted')
        try:
            score = model.evaluate(point)
        except (ValueError, ArithmeticError, np.linalg.LinAlgError) as exc:
            score = {'status': 'evaluation_failed', 'failure': str(exc), 'twice_nll': None}
        journal.append({'cell': cell, 'start_index': index, 'point': dict(point), 'score': record.clean(score)})
        if clock() >= deadline:
            raise BudgetExceeded('wall budget exhausted during evaluation')
        return score

    for cell, index in schedule:
        point = {**starts[index], **cell['fixed']}
        free = [p for p in parameters if not p['constant'] and p['name'] not in cell['fixed']]
        row = {'cell': cell['id'], 'start_index': index, 'start': deepcopy(point), 'fixed': dict(cell['fixed']),
               'delivery': 'unissued', 'accepted_numerical_status': False, 'q': None}
        rows.append(row)
        if exhausted:
            row['failure'] = 'operation budget exhausted before this fit'
            continue
        try:
            def state(x):
                return {**point, **dict(zip([p['name'] for p in free], map(float, x)))}

            def objective(x):
                score = evaluate(state(x), cell['id'], index)
                return score['twice_nll'] if score['status'] == 'accepted' else 1e100

            if native_minimizer is not None:
                def native_value(candidate):
                    score = evaluate(candidate, cell['id'], index)
                    return score['twice_nll'] if score['status'] == 'accepted' else float('nan')
                fitted, raw, accepted = native_minimizer(parameters, point, cell['fixed'], native_value, len(rows)-1)
                score = evaluate(fitted, cell['id'], index)
                accepted = accepted and score['status'] == 'accepted'
                fit_return = raw.get('fit', {})
                if accepted and fit_return.get('performed'):
                    accepted = abs(2*fit_return['min_nll']-score['twice_nll']) <= tolerance*(1+abs(score['twice_nll']))
                row['raw_optimizer'] = record.clean(raw)
            elif free:
                result = optimize.minimize(objective, [point[p['name']] for p in free], method='L-BFGS-B',
                                           bounds=[(p['min'], p['max']) for p in free],
                                           options={'ftol': tolerance*1e-3, 'gtol': tolerance, 'maxfun': max_evaluations})
                fitted = state(result.x)
                score = evaluate(fitted, cell['id'], index)
                gradient = np.asarray(result.jac, float)
                projected = gradient.copy()
                for i, p in enumerate(free):
                    x = fitted[p['name']]
                    if (x <= p['min'] and gradient[i] >= 0) or (x >= p['max'] and gradient[i] <= 0):
                        projected[i] = 0.
                raw = {'engine': 'scipy-L-BFGS-B', 'success': bool(result.success), 'status': int(result.status),
                       'message': str(result.message), 'fun': float(result.fun), 'jac': gradient.tolist(),
                       'nfev': int(result.nfev), 'nit': int(result.nit),
                       'inverse_hessian_approximation': result.hess_inv.todense().tolist()}
                stationary = bool(np.isfinite(projected).all() and np.max(np.abs(projected)) <= tolerance)
                accepted = result.success and stationary and score['status'] == 'accepted'
                if score['status'] == 'accepted':
                    accepted = accepted and abs(result.fun-score['twice_nll']) <= tolerance*(1+abs(score['twice_nll']))
                row.update(raw_optimizer=record.clean(raw), projected_gradient=projected.tolist())
            else:
                fitted = point
                score = evaluate(fitted, cell['id'], index)
                accepted = score['status'] == 'accepted'
                row['raw_optimizer'] = {'performed': False, 'reason': 'all_coordinates_fixed'}
            ab.require(set(fitted) == set(names), 'optimizer returned an incomplete coordinate state')
            for p in parameters:
                value = ab.real(fitted[p['name']], 'fitted coordinate')
                ab.require(p['min'] <= value <= p['max'], 'optimizer left declared domain')
                if p['constant'] or p['name'] in cell['fixed']:
                    ab.require(value == point[p['name']], 'optimizer changed a fixed coordinate')
            row.update(delivery='returned', point=fitted, score=record.clean(score),
                       accepted_numerical_status=bool(accepted),
                       at_bounds=[p['name'] for p in parameters if fitted[p['name']] in (p['min'], p['max'])])
        except BudgetExceeded as exc:
            exhausted = True
            row.update(delivery='failed', failure=str(exc))
        except (ValueError, RuntimeError, ArithmeticError) as exc:
            row.update(delivery='failed', failure=str(exc))
    accepted = [r for r in rows if r['cell'] == 'global' and r['accepted_numerical_status']]
    best = min(accepted, key=lambda row: row['score']['twice_nll']) if accepted else None
    for row in rows:
        if best is not None and row['accepted_numerical_status']:
            row['q'] = row['score']['twice_nll']-best['score']['twice_nll']
            if row['q'] < -tolerance*(1+abs(best['score']['twice_nll'])):
                row.update(accepted_numerical_status=False, failure='profile below best declared global multistart; globality unresolved')
    return {'fits': rows, 'best_known_global': None if best is None else deepcopy(best), 'evaluations': journal,
            'scheduled_fit_calls': len(schedule), 'objective_evaluations': len(journal),
            'status': 'passed' if best is not None and all(r['accepted_numerical_status'] for r in rows) else 'failed',
            'elapsed_seconds': clock()-begin, 'optimizer_globality_qualified': False,
            'threshold': None, 'intervals': None, 'calibration_qualified': False}


def _pin(ctx, spec):
    ab.require(type(spec) is dict and set(spec) == {'path', 'sha256'}, 'source requires path and sha256')
    path = ctx.path(spec['path'])
    raw = ctx.raw(path)
    ab.require(hashlib.sha256(raw).hexdigest() == spec['sha256'], 'source bytes differ')
    return path


def load(ctx, doc):
    from pathlib import Path
    from .. import amplitude_store, amplitude_selection, amplitude_predictions, amplitude_records
    from . import documents
    started = time.monotonic()
    code = [Path(__file__), *[Path(module.__file__) for module in (
        ab, amplitude_response, amplitude_store, amplitude_selection, amplitude_predictions, amplitude_records, differential, documents)]]
    for path in code:
        ctx.pins[str(path)] = amplitude_response.observation(path)['sha256']
    required = {'schema_version', 'kind', 'operation', 'statistic', 'response', 'measurement', 'reference',
                'covariance', 'parameters', 'fit', 'mc_policy', 'max_condition', 'resources'}
    ab.require(required <= set(doc) <= required | {'auxiliary', 'description', 'runtime'}, 'cached-profile document fields differ')
    ab.require(doc['operation'] == 'cached-profile', 'cached-profile operation required')
    st = doc['statistic']
    ab.require(type(st) is dict and set(st) == {'verbatim', 'objective'} and st['objective'] in differential.OBJECTIVES,
               'cached profiles require a prescribed objective, no implicit exclusion statistic')
    ab.text(st['verbatim'], 'requested statistic')
    resources = doc['resources']
    ab.require(type(resources) is dict and set(resources) == {'max_cache_bytes', 'max_evaluations', 'max_seconds', 'max_output_bytes'},
               'complete cache, evaluation, wall and output budgets required')
    for key in resources:
        ab.require(type(resources[key]) is int and resources[key] > 0, 'positive integer resources required')
    fit = doc['fit']
    ab.require(type(fit) is dict and {'starts', 'profile_cells', 'tolerance'} <= set(fit)
               <= {'starts', 'profile_cells', 'tolerance', 'engine'}, 'complete profile policy required')
    engine = fit.get('engine', 'scipy')
    ab.require(engine in ('scipy', 'roofit'), 'profile engine must be scipy or roofit')
    native_inputs = []
    if engine == 'roofit':
        from . import cached_native
        native_inputs = cached_native.runtime_inputs(ctx, doc.get('runtime'))
        for p in doc['parameters']:
            ab.require(ab.real(p.get('error'), 'native initial error') > 0, 'positive native initial errors required')
    else:
        ab.require('runtime' not in doc, 'native runtime is only used by roofit')
    names = parameter_contract(doc['parameters'], fit['starts'], fit['profile_cells'])
    ab.require(0 < ab.real(fit['tolerance']) < 1, 'profile tolerance must lie between zero and one')
    spec = doc['response']
    ab.require(type(spec) is dict and {'prediction', 'hypothesis', 'bindings', 'estimator'} <= set(spec)
               <= {'prediction', 'hypothesis', 'bindings', 'estimator', 'fiducial', 'replay'}, 'cached response fields differ')
    prediction_path = _pin(ctx, spec['prediction'])
    fiducial = ctx.json(_pin(ctx, spec['fiducial'])) if 'fiducial' in spec else None
    replay_path = _pin(ctx, spec['replay']) if 'replay' in spec else None
    replay = ctx.json(replay_path) if replay_path is not None else None
    response = amplitude_response.CachedResponse({'input': str(prediction_path)}, ctx.root, hypothesis=spec['hypothesis'],
                bindings=spec['bindings'], estimator=spec['estimator'], max_cache_bytes=resources['max_cache_bytes'], fiducial=fiducial,
                replay=replay, replay_base=None if replay_path is None else replay_path.parent)
    ab.require(type(spec['bindings']) is list, 'binding list required')
    bound_names = {name for binding in spec['bindings'] for name in binding['coefficients']}
    auxiliary = None
    if 'auxiliary' in doc:
        auxiliary = ctx.json(_pin(ctx, doc['auxiliary']))
    auxiliary_names = set(auxiliary['parameters']) if auxiliary else set()
    ab.require(bound_names | auxiliary_names == set(names) and not bound_names & auxiliary_names,
               'every coordinate must have exactly an amplitude or auxiliary role')
    for start in fit['starts']:
        amplitude_response.bind(response.template, response.bindings, start, response.basis)
    measurement, reference = doc['measurement'], doc['reference']
    ab.require(set(measurement) == {'values', 'unit', 'bin_edges'} and set(reference) == {'values', 'description'},
               'measurement and reference fields differ')
    ab.text(reference['description'], 'reference source description')
    ab.require(np.array_equal(ab.edges_from(measurement['bin_edges']), response.edges), 'measurement and response binning differ')
    norm, observable = response.ctx['doc']['normalization'], response.ctx['doc']['observable']
    unit = norm['unit'] + ('/' + observable['unit'] if norm['representation'] == 'differential' else '')
    ab.require(measurement['unit'] == unit, 'measurement and response units differ')
    components = []
    for c in doc['covariance']:
        ab.require(set(c) == {'name', 'law', 'matrix'}, 'covariance component fields differ')
        matrix = c['matrix']
        if isinstance(matrix, dict) and matrix.get('format') == 'hepdata':
            ab.require('bin_edges' not in matrix or matrix['bin_edges'] == measurement['bin_edges'], 'covariance binning differs')
            matrix = {**matrix, 'bin_edges': measurement['bin_edges']}
        components.append({**c, 'matrix': ctx.matrix(matrix, c['name'])})

    def vector(value, label):
        if isinstance(value, dict) and value.get('format') == 'hepdata':
            axes = ctx._table(ctx.path(value['path']))['independent_variables']
            expected = [{'low': float(lo), 'high': float(hi)} for lo, hi in zip(response.edges[:-1], response.edges[1:])]
            ab.require(len(axes) == 1 and axes[0]['values'] == expected, label + ' source binning differs')
        return ctx.vector(value, label)

    model = differential.CachedModel(response=response, measured=vector(measurement['values'], 'measurement'),
               reference=vector(reference['values'], 'reference'), components=components, parameters=names,
               mc_policy=doc['mc_policy'], auxiliary=auxiliary, objective=st['objective'], max_condition=doc['max_condition'])
    planned = len(fit['starts'])*(1+len(fit['profile_cells']))
    # Reserve the complete evaluation journal and shared-state kernel before
    # issuing fits; the exact serialized size is checked again at publication.
    journal_bound = resources['max_evaluations']*(4096+256*model.bins**2+256*len(names))
    kernel_bound = planned*(planned+1)//2*(3*response.width)**2*32
    ab.require(journal_bound+kernel_bound < resources['max_output_bytes'], 'complete journal/kernel exceeds output budget')
    ab.require(time.monotonic()-started < resources['max_seconds'], 'cache capture exhausted operation wall budget')
    return {'doc': doc, 'model': model, 'response': response, 'started': started,
            'inputs': sorted({str(p) for p in [*common.inputs(ctx), *native_inputs]} | {p['path'] for p in response.inputs})}


def run(ctx, spec, output, *, task=None):
    import json
    from pathlib import Path
    d, model, response = spec['doc'], spec['model'], spec['response']
    started = spec['started']
    inputs = [amplitude_response.observation(p) for p in spec['inputs']]
    expected = {p['path']: p['sha256'] for p in [*ctx.inputs(), *response.inputs]}
    ab.require(all(p['sha256'] == expected[p['path']] for p in inputs), 'profile inputs changed after loading')
    fit, resources = d['fit'], d['resources']
    native_minimizer = None
    native_before = []
    native_failure = None
    if fit.get('engine') == 'roofit':
        from . import cached_native
        ab.require(task is not None, 'native profile requires its admitted task')
        cached_native.authorized(task, output)
        native_dir = Path(output)/'native'
        native_dir.mkdir(parents=True, exist_ok=False)
        try:
            ROOT, native_before, loaded = cached_native.load(d['runtime'])
            native_minimizer = lambda parameters, point, fixed, evaluate, index: cached_native.minimize(
                ROOT, parameters, point, fixed, evaluate, native_dir/f'fit-{index:04d}.root', fit['tolerance'])
        except (ImportError, OSError, ValueError, RuntimeError) as exc:
            native_failure = str(exc)
    remaining = resources['max_seconds']-(time.monotonic()-started)
    ab.require(remaining > 0, 'cache capture exhausted operation wall budget')
    if native_failure is None:
        result = profile(model, d['parameters'], fit['starts'], fit['profile_cells'],
                         max_evaluations=resources['max_evaluations'], max_seconds=remaining, tolerance=fit['tolerance'],
                         native_minimizer=native_minimizer)
    else:
        rows = [{'cell': cell['id'], 'start_index': i, 'start': {**start, **cell['fixed']},
                 'delivery': 'unissued', 'accepted_numerical_status': False, 'q': None, 'failure': native_failure}
                for cell in [{'id': 'global', 'fixed': {}}, *fit['profile_cells']] for i, start in enumerate(fit['starts'])]
        result = {'fits': rows, 'best_known_global': None, 'evaluations': [], 'status': 'failed',
                  'scheduled_fit_calls': len(rows), 'objective_evaluations': 0, 'native_setup_failure': native_failure,
                  'optimizer_globality_qualified': False, 'threshold': None, 'intervals': None, 'calibration_qualified': False}
    if native_minimizer is not None:
        result['native_artifacts'] = [amplitude_response.observation(p) for p in sorted(native_dir.iterdir()) if p.is_file()]
        result['loaded_libraries'] = cached_native.libraries(ROOT, d['runtime'])
        ab.require([amplitude_response.observation(p['path']) for p in native_before] == native_before, 'native runtime ending identity changed')
    responses, states, response_failures = [], [], []
    for row in result['fits']:
        if row['delivery'] == 'returned':
            identity = {'cell': row['cell'], 'start_index': row['start_index']}
            try:
                value = response.evaluate(row['point'])
            except (ValueError, ArithmeticError, np.linalg.LinAlgError) as exc:
                response_failures.append({**identity, 'failure': str(exc)})
                result['status'] = 'failed'
            else:
                states.append(identity)
                responses.append(value)
    kernel = {'states': states, 'upper_triangle': [], 'semantics': 'shared-block covariance; lower triangle is transpose'}
    for i, left in enumerate(responses):
        for j in range(i, len(responses)):
            kernel['upper_triangle'].append({'left': i, 'right': j, 'matrix': amplitude_response.cross_covariance(left, responses[j])})
    result.update(cross_state_covariance=kernel, responses=responses, response_failures=response_failures,
                  component_diagnostics=model.component_diagnostics, estimator=response.estimator,
                  parameters=d['parameters'], initial_state={p['name']: p['value'] for p in d['parameters']},
                  physics_validated=False)
    response.finish()
    ab.require([amplitude_response.observation(p['path']) for p in inputs] == inputs, 'ending profile input identity changed')
    ab.require(time.monotonic()-started < resources['max_seconds'], 'complete profile delivery wall budget exceeded')
    parameters = [{k: p[k] for k in ('name', 'unit', 'label')} for p in d['parameters']]
    inference = record.build(mode='differential-likelihood', engine='cached-amplitude-profile',
                statistic=record.statistic('prescribed', verbatim=d['statistic']['verbatim'], definition=d['statistic']),
                parameters=parameters, results=[record.result('delta-nll-scan', 'primary', **result,
                summary='Conditional cached profiles; failed/unissued fits retained; no calibrated interval.')],
                inputs=[{k: p[k] for k in ('path', 'sha256')} for p in inputs], status=result['status'],
                limitations=['Bounded local multistart is not a proof of globality or coverage.',
                             'Supplied Born selection and reference-baseline applicability require independent qualification.',
                             'MC covariance is an estimate from independent equal-exposure blocks; no proposal-adequacy certificate.',
                             'SciPy numerical status is not a native saved-fit or Hessian-error certification; the optional RooFit bridge requires separate runtime qualification.'])
    raw = json.dumps(inference, allow_nan=False).encode()
    ab.require(len(raw) <= resources['max_output_bytes'], 'profile result exceeds output byte budget')
    delivered = common.deliver(output, inference, scope='Conditional profiles on captured amplitude blocks', review=ctx.review)
    ab.require(amplitude_response.observation(Path(output)/'inference.json')['sha256'] == delivered['inference_sha256'],
               'profile publication bytes changed')
    ab.require(sum(p.stat().st_size for p in Path(output).rglob('*') if p.is_file()) <= resources['max_output_bytes'],
               'final delivery exceeds output byte budget')
    response.finish()
    ab.require([amplitude_response.observation(p['path']) for p in inputs] == inputs, 'profile inputs changed during publication')
    ab.require(time.monotonic()-started < resources['max_seconds'], 'complete publication wall budget exceeded')
    return delivered
