"""Source-bound candidate checks with a supplied no-refit diagnostic plan."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import time

from ravel.validation import likelihood_parity as parity
from ravel.validation import likelihood_profile_probe as profile
from ravel.workflow.state_io import atomic_json
from ravel.validation import diagnostic_plan as plans

SCOPE = 'Retained candidate numerical checks; no refit, completed paired profile, globality or physics claim'
IDENTITY_KEYS = ('modifier_settings', 'measurement', 'parameter_order', 'channel_order',
                 'channel_slices', 'sample_order', 'nmaindata', 'parameter_names', 'bounds',
                 'inits', 'fixed', 'npars', 'nauxdata', 'auxdata', 'constraints',
                 'observed_and_auxiliary_data', 'model_compact_sha256', 'data_compact_sha256')


def require(value, message):
    if not value:
        raise ValueError(message)


def validate(task):
    profile.validate(task)


def _snapshot_pin(snapshot, pin):
    """Match the literal file within an already pinned completed receipt."""
    path = str(Path(pin['path']).resolve())
    matches = []
    for name, tree in snapshot.items():
        for row in tree['files']:
            target = name if tree['kind'] == 'file' else str(Path(name) / row['name'])
            if target == path:
                matches.append(row['sha256'])
    require(matches == [pin['sha256']], 'origin receipt does not uniquely bind input/output: ' + str(path))


def select_candidates(children, probe, compiled, plan):
    selectors=plans.required(plan,'candidate_selectors')
    statuses=plans.required(plan,'trial_statuses')
    require(isinstance(selectors,list) and selectors and len({tuple(x) for x in selectors})==len(selectors),'unique supplied candidate selectors required')
    expected_identity = {'model_sha256': compiled['model_compact_sha256'],
                         'data_sha256': compiled['data_compact_sha256'],
                         'bounds': probe['bounds'], 'fixed_coordinates': probe['fixed_coordinates'],
                         'ordered_starts': probe['ordered_starts']}
    require(set(children)==set(statuses),'complete supplied backend population required')
    selected=[]
    for backend,child in children.items():
        require(child['backend']==backend and child['compiled_identity']==expected_identity,'retained child compiled problem differs')
        require(child['seed_denominator']==len(probe['ordered_starts']) and len(child['trials'])==len(probe['ordered_starts']),'complete start denominator required')
        require([r['seed_index'] for r in child['trials']]==list(range(len(probe['ordered_starts']))),'retained seed order differs')
        require([r['status'] for r in child['trials']]==statuses[backend],'supplied trial census differs')
        require(all(r['seed']==seed for r,seed in zip(child['trials'],probe['ordered_starts'])),'retained starting vector differs')
    for backend,index in selectors:
        require(backend in children and type(index) is int and 0<=index<len(probe['ordered_starts']),'invalid candidate selector')
        trial=children[backend]['trials'][index]
        require(trial['status']=='succeeded','selected candidate was not completed')
        result=trial['result'];point=result['parameters'];value=result['objective']
        require(result['success'] is True and type(value) in (int,float) and math.isfinite(value),'finite successful optimizer result required')
        require(len(point)==len(probe['bounds']) and all(type(x) in (int,float) and math.isfinite(x) and lo<=x<=hi for x,(lo,hi) in zip(point,probe['bounds'])),'candidate outside retained domain')
        require(all(point[i]==v for i,v in probe['fixed_coordinates']),'candidate changed fixed values')
        selected.append({'backend':backend,'seed_index':index,'parameters':list(point),'recorded_twice_nll':value})
    for backend,child in children.items():
        successful=[r['result'] for r in child['trials'] if r['status']=='succeeded']
        if successful and 'best' in child:
            require(child['best'] in successful and child['best']['objective']==min(r['objective'] for r in successful),'retained selected best differs')
    return selected


def document(task, base):
    from ravel.workflow.science import regular
    from ravel.workflow.execution import receipt_digest
    validate(task)
    path = regular(task['input'], base)
    d = json.loads(path.read_text())
    plan=plans.selected(d, ('candidate_selectors','trial_statuses','origin_properties','origin_commands'))
    plans.fields(d, ('plan','schema_version', 'operation', 'profile_input', 'origin_execution',
                    'origin_result', 'origin_numpy', 'origin_jax', 'origin_source',
                    'grounding', 'limits', 'tolerances'), 'retained candidate input')
    require(d['schema_version'] == 1 and d['operation'] == 'retained_profile_candidates_no_refit',
            'explicit no-refit operation required')
    require(plans.limits(d['limits'], ('adapter_seconds','numerical_seconds','numpy_and_fd_seconds','jax_seconds','evaluator_calls')) and plans.tolerances(d['tolerances']),
            'original numerical tolerances and explicit candidate work contract required')
    bound = {k: parity._pin(d[k], path.parent) for k in
             ('profile_input', 'origin_execution', 'origin_result', 'origin_numpy', 'origin_jax', 'origin_source')}
    pp, pd = profile.document({'input': str(bound['profile_input'][0])}, path.parent)
    parity_path, parity_doc = parity._pin(pd['parity_input'], pp.parent)
    retained = parity._pin(parity_doc['retained_inputs'], parity_path.parent)[1]
    literal = parity._pin(parity_doc['compiled_reference'], parity_path.parent)[1]
    compiled, _ = parity.compiled_reference_identity(literal)
    probe = profile.validate_probe(retained, compiled, pd['plan'])
    reference = profile.retained_reference(retained, probe, pd['plan'])
    record = bound['origin_execution'][1]
    require(record['status'] == 'succeeded' and record['exit_code'] == 0 and
            record['receipt_sha256'] == receipt_digest(record), 'completed origin custody receipt required')
    _snapshot_pin(record['input_snapshot'], d['profile_input'])
    _snapshot_pin(record['input_snapshot'], d['origin_source'])
    for key in ('origin_result', 'origin_numpy', 'origin_jax'):
        _snapshot_pin(record['output_snapshot'], d[key])
    origin = bound['origin_result'][1]
    children = {name: bound['origin_' + name][1] for name in ('numpy', 'jax')}
    require(all(origin.get(k)==v for k,v in plan['origin_properties'].items()),'supplied origin diagnostic identity differs')
    require(origin['backend_results']==children and origin['diagnostic_delivery_complete'] is True,'origin backend custody differs')
    require(origin['runtime_before_passed'] is True and origin['runtime_after_passed'] is True,'origin runtime custody incomplete')
    require(origin['backend_commands']==plan['origin_commands'],'supplied child failure classifications differ')
    candidates = select_candidates(children, probe, compiled, plan)
    require(evaluator_census(candidates,probe)<=d['limits']['evaluator_calls'],'supplied candidate evaluator budget insufficient')
    return path, d, bound, parity_path, parity_doc, retained, compiled, probe, reference, candidates


def inputs(task, base, *, _session=None):
    path, d, bound, *_ = document(task, base)
    result = [path, *profile.inputs({'input': str(bound['profile_input'][0])}, path.parent, _session=_session)]
    result += [p for p, _ in bound.values()]
    for row in d['grounding']:
        result.append(parity._pin(row, path.parent)[0])
    for row in bound['origin_source'][1]['files']:
        p = Path(row['path'])
        require(p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest() == row['sha256'],
                'retained original source capsule changed')
        result.append(p)
    return list(dict.fromkeys(result))


def _validation_inputs(task, base, session):
    return inputs(task, base, _session=session)


def execution_seconds(task, base):
    return document(task, base)[1]['limits']['adapter_seconds']


def evaluator_census(rows,probe):
    fixed={i for i,v in probe['fixed_coordinates']}
    return sum(6 if point['parameters'][i] in (lo,hi) else 4 for point in rows for i,(lo,hi) in enumerate(probe['bounds']) if i not in fixed)+3*(len(rows)+1)


def resource_bounds(task, base):
    _,d,_,_,_,_,_,probe,_,rows=document(task,base)
    free=len(probe['bounds'])-len(probe['fixed_coordinates'])
    calls=evaluator_census(rows,probe)
    require(calls<=d['limits']['evaluator_calls'],'planned evaluator ceiling insufficient')
    return {**d['limits'], 'planned_evaluator_calls':calls,
            'free_coordinates_per_candidate':free, 'candidate_vectors':len(rows),
            'model_compilations':2, 'worker_processes':1, 'optimizer_calls':0,'events':0,'roots':0}


class CheckBudget(RuntimeError):
    pass


class Counter:
    def __init__(self, limits, clock=time.monotonic):
        self.clock, self.limits = clock, limits
        self.started = clock()
        self.deadline = self.started + limits['numerical_seconds']
        self.phase_deadline = self.started
        self.phase = None
        self.calls, self.categories = 0, {}

    def begin(self, name, seconds):
        self.phase = name
        self.phase_deadline = min(self.deadline, self.clock() + seconds)

    def check(self, category=None):
        if self.clock() >= self.phase_deadline:
            raise CheckBudget('reserved ' + str(self.phase) + ' verification phase exhausted')
        if category is not None:
            if self.calls >= self.limits['evaluator_calls']:
                raise CheckBudget('retained-candidate evaluator ceiling exhausted')
            self.calls += 1
            self.categories[category] = self.categories.get(category, 0) + 1

    def snapshot(self):
        return {'calls': self.calls, 'categories': dict(self.categories), 'phase': self.phase,
                'elapsed_seconds': self.clock() - self.started, 'limit': self.limits['evaluator_calls']}


def qualify(row, reference_value, tolerances):
    """Separate arithmetic agreement from local stationarity/reference quality."""
    tol = tolerances
    row['independent_density_residual'] = abs(row['independent_twice_nll'] - row['recorded_twice_nll'])
    row['numpy_jax_residual'] = abs(row['numpy_twice_nll'] - row['jax_twice_nll'])
    row['scalar_numpy_residual'] = abs(row['independent_twice_nll'] - row['numpy_twice_nll'])
    row['best_minus_reference'] = row['independent_twice_nll'] - reference_value
    row['arithmetic_passed'] = all(row[k] <= tol['independent_density'] for k in
        ('independent_density_residual', 'numpy_jax_residual', 'scalar_numpy_residual')) and row['gradient_parity']['passed']
    row['stationary'] = row['step_convergence_passed'] and row['fd_projected_gradient'] <= tol['stationarity'] and row['analytic_projected_gradient'] <= tol['stationarity']
    row['reference_quality_passed'] = row['best_minus_reference'] <= tol['objective_agreement']
    row['candidate_checks_passed'] = row['arithmetic_passed'] and row['stationary'] and row['reference_quality_passed']


def run(task, base, output_dir):
    started = time.monotonic()
    path, d, bound, pp, pd, retained, reference, probe, known, candidates = document(task, base)
    limits=d['limits'];tolerances=d['tolerances'];plan=d['plan']
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    require(not any(out.iterdir()), 'fresh candidate-check output required')
    report = {'schema_version': 1, 'status': 'failed', 'scope': SCOPE, 'physics_validated': False,
              'limits': limits, 'tolerances': tolerances, 'optimizer_calls': 0,
              'root_searches': 0, 'generated_events': 0, 'candidates': [], 'timing': {},
              'original_comparison_passed': bound['origin_result'][1]['comparison_passed'], 'paired_profile_completed': all(all(x=='succeeded' for x in states) for states in plan['trial_statuses'].values()),
              'arithmetic_parity_passed': False}
    report.update(plans.metadata(plan),output_format=plan['output']['format'])
    counter = None

    def save():
        report['elapsed_seconds'] = time.monotonic() - started
        if counter is not None:
            report['budget'] = counter.snapshot()
        plans.publish(out,plan,profile.json_safe(report))

    save()
    runtime = None
    try:
        path, d, bound, pp, pd, retained, reference, probe, known, candidates = document(task, base)
        runtime = parity._pin(pd['runtime_inventory'], pp.parent)[1]
        parity.runtime_files(runtime)
        report['runtime_before_passed'] = True
        report['origin_pins'] = {key: d[key] for key in ('profile_input', 'origin_execution', 'origin_result', 'origin_numpy', 'origin_jax', 'origin_source')}
        report['candidates'] = candidates
        report['reference'] = {'parameters': known, 'recorded_twice_nll': probe['recorded_best_twice_nll']}
        counter = Counter(limits)
        counter.begin('numpy_density_and_all_free_fd', limits['numpy_and_fd_seconds'])
        began = time.monotonic()
        import numpy as np
        import pyhf
        from ravel.physics import published_model, pyhf_exclude as engine
        require(hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest() == profile.document({'input':str(bound['profile_input'][0])},path.parent)[1]['plan']['engine_sha256'],
                'source projected-gradient/original-objective helpers changed')
        report['timing']['imports_seconds'] = time.monotonic() - began
        published_path, published = parity._pin(pd['published_input'], pp.parent)
        contract = published_model.load_published_model(published, published_path.parent)

        def compile_model(name):
            began = time.monotonic()
            counter.check()
            pyhf.set_backend(name, precision='64b')
            model, _, compiled = published_model.compile_published_model(contract)
            compiled = parity.compiled_json_identity(compiled)
            require(all(compiled[k] == reference[k] for k in IDENTITY_KEYS), 'compiled original model/data identity differs')
            counter.check()
            report['timing'][name + '_compile_seconds'] = time.monotonic() - began
            return model

        model = compile_model('numpy')
        layout = parity.constraint_layout(model)
        report['constraint_layout'] = layout
        report['data'] = probe['data']
        report['bounds'] = probe['bounds']
        report['fixed_coordinates'] = probe['fixed_coordinates']
        report['compiled_identity'] = {k: reference[k] for k in IDENTITY_KEYS}
        data = np.asarray(probe['data'], dtype=float)

        def independent(point, *, retained_terms=False):
            counter.check('independent_scalar_density')
            means = np.asarray(model.expected_actualdata(point), dtype=float).tolist()
            terms = parity.scalar_density(means, list(point), probe['data'], layout)
            counter.check()
            return {'main_means': means, 'density': terms} if retained_terms else terms['twice_nll']

        for row in [*report['candidates'], report['reference']]:
            counter.check('numpy_objective')
            row['numpy_twice_nll'] = float(np.asarray(pyhf.infer.mle.twice_nll(row['parameters'], data, model)).reshape(-1)[0])
            counter.check()
            evidence = independent(row['parameters'], retained_terms=True)
            row['independent_twice_nll'] = evidence['density']['twice_nll']
            row['independent_density_components'] = evidence
            save()
        report['reference']['density_residual'] = abs(report['reference']['independent_twice_nll'] - report['reference']['recorded_twice_nll'])
        report['reference']['passed'] = report['reference']['density_residual'] <= tolerances['independent_density']
        began = time.monotonic()
        for row in report['candidates']:
            row['finite_difference'] = parity.finite_difference(independent, row['parameters'], probe['bounds'], probe['fixed_coordinates'], step_scale=tolerances['step_scale'])
            gradient, converged = profile.finite_difference_gradient(row['finite_difference'],tolerances)
            row['step_convergence_passed'] = converged
            row['fd_projected_gradient'] = engine.robust_optimizer.projected_gradient(row['parameters'], gradient, probe['bounds'], probe['fixed_coordinates'])
            save()
        report['timing']['all_free_fd_seconds'] = time.monotonic() - began
        counter.begin('jax_values_and_analytic_gradients', limits['jax_seconds'])
        import jax
        require(jax.config.x64_enabled and all(d.platform == 'cpu' for d in jax.devices()), 'float64 CPU JAX required')
        model = compile_model('jax')
        objective = jax.jit(jax.value_and_grad(lambda point: pyhf.infer.mle.twice_nll(point, data, model)[0]))
        began = time.monotonic()
        for row in [*report['candidates'], report['reference']]:
            counter.check('jax_value_and_gradient')
            value, gradient = objective(np.asarray(row['parameters'], dtype=float))
            row['jax_twice_nll'], gradient = float(np.asarray(value)), np.asarray(gradient, dtype=float).tolist()
            counter.check()
            row['analytic_gradient'] = gradient
            if 'backend' in row:
                row['gradient_parity'] = parity.compare_gradients(row['finite_difference'], gradient,
                    atol=tolerances['gradient_atol'], rtol=tolerances['gradient_rtol'])
                row['analytic_projected_gradient'] = engine.robust_optimizer.projected_gradient(row['parameters'], gradient, probe['bounds'], probe['fixed_coordinates'])
                qualify(row, report['reference']['independent_twice_nll'],tolerances)
            save()
        report['timing']['jax_synchronized_values_and_gradients_seconds'] = time.monotonic() - began
        ref = report['reference']
        ref['passed'] &= max(abs(ref['jax_twice_nll'] - ref['numpy_twice_nll']), abs(ref['numpy_twice_nll'] - ref['independent_twice_nll'])) <= tolerances['independent_density']
        report['arithmetic_parity_passed'] = bool(ref['passed'] and all(row['arithmetic_passed'] for row in report['candidates']))
        report['all_candidate_checks_passed'] = bool(ref['passed'] and all(r['candidate_checks_passed'] for r in report['candidates']))
        report['original_portfolio'] = {backend: {'completed':sum(x=='succeeded' for x in states),'required':len(states),'statuses':states} for backend,states in plan['trial_statuses'].items()}
        require(counter.calls == resource_bounds(task,base)['planned_evaluator_calls'],'derived vector call census differs')
        report['diagnostic_delivery_complete'] = True
        report['status'] = 'passed'
    except Exception as error:
        report['error'] = {'type': type(error).__name__, 'message': str(error)}
        report['arithmetic_parity_passed'] = False
        report['all_candidate_checks_passed'] = False
    finally:
        if runtime is not None:
            try:
                parity.runtime_files(runtime)
                report['runtime_after_passed'] = True
            except Exception as error:
                report.update(status='failed', arithmetic_parity_passed=False, all_candidate_checks_passed=False,
                              runtime_after_error={'type': type(error).__name__, 'message': str(error)})
        if time.monotonic() - started >= limits['adapter_seconds']:
            report.update(status='failed', arithmetic_parity_passed=False, all_candidate_checks_passed=False,
                          error={'type': 'CheckBudget', 'message': 'total adapter wall ceiling exhausted'})
        save()
    return report
