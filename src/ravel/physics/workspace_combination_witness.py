"""Structural joined-law witness, using component means and scalar auxiliary laws.

This does not independently validate pyhf interpolation. The caller owns source,
runtime, resource and scientific admission; this kernel performs no optimization.
"""
from copy import deepcopy
import math
import time


def _poisson(observed, mean):
    if not math.isfinite(mean) or mean < 0 or not math.isfinite(observed) or observed < 0:
        raise ValueError('invalid Poisson argument')
    if mean == 0:
        if observed != 0:
            raise ValueError('nonfinite Poisson density')
        return 0.
    return observed * math.log(mean) - mean - math.lgamma(observed + 1)


def _retained(value):
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite_float": repr(value)}
    if isinstance(value, dict):
        return {key: _retained(item) for key,item in value.items()}
    if isinstance(value, (list,tuple)):
        return [_retained(item) for item in value]
    return value


def qualify(components, policy, point_design, *, compiler, record,
            max_calls=20, max_seconds=60., mean_atol=1e-9, density_atol=1e-7):
    """Compare a complete join against component means and one auxiliary union.

Five declared vectors are supported: nominal, poi_zero, poi_two, plus/minus.
The last two displace every free constrained coordinate by min(0.2 width,
0.25 distance to either bound), retaining fixed parameters. All points, returned
values and failures are delivered to the caller's progressive recorder. Calls
count only mean/density evaluations; for two inputs the reviewed compiler and
this witness perform eight model compilations, separately declared by a caller.
    """
    import pyhf
    if point_design != ['nominal', 'poi_zero', 'poi_two', 'plus', 'minus']:
        raise ValueError('exact five-point protocol required')
    if (type(max_calls) is not int or max_calls != 20 or not math.isfinite(max_seconds)
            or type(max_seconds) not in (int, float) or max_seconds <= 0
            or any(type(x) not in (int, float) or not math.isfinite(x) or x <= 0 for x in (mean_atol,density_atol))):
        raise ValueError('invalid bounded witness protocol')
    if len(components) != 2 or pyhf.get_backend()[0].name != 'numpy':
        raise ValueError('two components and numpy backend required')
    started = time.monotonic()
    state = {'scope': 'fixed-vector workspace-combination structural law parity only',
             'status': 'running', 'fits': 0, 'calls': 0, 'journal': [], 'points': []}
    def save():
        record(deepcopy(state))
    def bound():
        if time.monotonic() - started > max_seconds:
            raise TimeoutError('mathematical witness deadline expired')
    def call(label, function, *, numerical=False):
        bound()
        if numerical:
            if state['calls'] >= max_calls:
                raise ValueError('numerical call ceiling reached')
            state['calls'] += 1
        row = {'label': label, 'status': 'running'}
        state['journal'].append(row)
        save()
        try:
            value = function()
            row.update(status='returned', value=_retained(value))
            save()  # A completed return survives any later time/check failure.
            bound()
            return value
        except BaseException as exc:
            row['error'] = {'type': type(exc).__name__, 'message': str(exc)}
            if row['status'] != 'returned':
                row['status'] = 'failed'
            save()
            raise
    try:
        result = call('compile_combination', lambda: compiler(components, policy))
        state['combination_report'] = result['report']
        laws = result['report']['parameters']
        component_models = []
        for row in components:
            workspace = pyhf.Workspace(row['workspace'])
            model = workspace.model(measurement_name=row['measurement'])
            component_models.append((row, workspace, model))
        joint_ws = pyhf.Workspace(result['workspace'])
        joint_model = joint_ws.model(measurement_name=policy['measurement'])
        observed = {c['name']: c['data'] for row in components for c in row['workspace']['observations']}
        if {c['name']: c['data'] for c in result['workspace']['observations']} != observed:
            raise ValueError('joined observations differ from source populations')
        nominal = {name: list(law['initial']) for name, law in laws.items()}
        for label in point_design:
            point = deepcopy(nominal)
            if label in ('poi_zero', 'poi_two'):
                point[policy['poi']] = [0. if label == 'poi_zero' else 2.]
            if label in ('plus', 'minus'):
                sign = 1. if label == 'plus' else -1.
                for name, law in laws.items():
                    if not law['constrained']:
                        continue
                    widths = law['sigma'] if law['pdf'] == 'normal' else [1/math.sqrt(x) for x in law['factors']]
                    for i, (x, fixed, bounds, width) in enumerate(zip(law['initial'], law['fixed'], law['bounds'], widths)):
                        if fixed:
                            continue
                        step = min(.2*width, .25*(x-bounds[0]), .25*(bounds[1]-x))
                        if not math.isfinite(step) or step <= 0:
                            raise ValueError('free constrained coordinate lacks two-sided interior witness')
                        point[name][i] = x + sign*step
            for name, law in laws.items():
                if len(point[name]) != law['dimension']:
                    raise ValueError('point dimension differs')
                for x, initial, fixed, bounds in zip(point[name],law['initial'],law['fixed'],law['bounds']):
                    if not math.isfinite(x) or not bounds[0] <= x <= bounds[1] or (fixed and x != initial):
                        raise ValueError('point outside original domain or fixed state')
            current = {'name': label, 'parameters': point, 'status': 'running'}
            state['points'].append(current);save()
            def vector(model, mapping):
                values = []
                for name in model.config.par_order:
                    values.extend(point[mapping[name]])
                return values
            source_means = {}
            for row, workspace, model in component_models:
                pars = vector(model,row['parameter_map'])
                means = call(label+':component:'+row['id'], lambda m=model,p=pars: m.expected_actualdata(p).tolist(), numerical=True)
                if any(not math.isfinite(x) for x in means):
                    raise ValueError('nonfinite component mean')
                current.setdefault('component_means', {})[row['id']] = means;save()
                for channel in model.config.channels:
                    source_means[channel] = means[model.config.channel_slices[channel]]
            joined_pars = vector(joint_model, {n:n for n in joint_model.config.par_order})
            joined_means = call(label+':joined_means', lambda: joint_model.expected_actualdata(joined_pars).tolist(), numerical=True)
            if any(not math.isfinite(x) for x in joined_means):
                raise ValueError('nonfinite joined mean')
            current['joined_means'] = joined_means;save()
            ordered_expected = [v for c in joint_model.config.channels for v in source_means[c]]
            if len(joined_means) != len(ordered_expected):
                raise ValueError('mean population differs')
            current['mean_residual'] = max(abs(a-b) for a,b in zip(joined_means,ordered_expected))
            main = math.fsum(_poisson(n,m) for c in joint_model.config.channels for n,m in zip(observed[c],source_means[c]))
            aux = []
            for name, law in laws.items():
                if not law['constrained']:
                    continue
                if law['pdf'] == 'normal':
                    aux.extend(-.5*((n-x)/s)**2-math.log(s)-.5*math.log(2*math.pi) for n,x,s in zip(law['observed'],point[name],law['sigma']))
                else:
                    aux.extend(_poisson(n,f*x) for n,f,x in zip(law['observed'],law['factors'],point[name]))
            oracle = main + math.fsum(aux)
            current.update(independent_main=main, independent_auxiliary=math.fsum(aux), auxiliary_terms=len(aux), independent_logpdf=oracle);save()
            density = call(label+':joined_density', lambda: float(joint_model.logpdf(joined_pars,joint_ws.data(joint_model))[0]), numerical=True)
            if not math.isfinite(density):
                raise ValueError('nonfinite joined density')
            current.update(joined_logpdf=density,density_residual=abs(density-oracle))
            current['passed'] = (math.isfinite(density) and current['mean_residual'] <= mean_atol
                                 and current['density_residual'] <= density_atol
                                 and len(aux) == result['report']['auxiliary_terms'])
            current['status'] = 'completed';save()
        state['passed'] = state['calls'] == max_calls and all(p['passed'] for p in state['points'])
        state['status'] = 'completed';save();return state
    except BaseException as exc:
        state.update(status='failed',error={'type':type(exc).__name__,'message':str(exc)})
        save();raise
