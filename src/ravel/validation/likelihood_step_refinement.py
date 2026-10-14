"""Supplied failed-coordinate refinements without rewriting original verdicts."""
from pathlib import Path
import hashlib
import json
import math
import time

from ravel.validation import likelihood_candidate_check as candidate
from ravel.validation import likelihood_parity as parity
from ravel.validation import likelihood_profile_probe as profile
from ravel.workflow.state_io import atomic_json
from ravel.validation import diagnostic_plan as plans



def require(value, message):
    if not value:
        raise ValueError(message)


def validate(task):
    candidate.validate(task)


def select_failed(report, expected, reference, compiled, probe, plan):
    pairs=plans.required(plan,'failed_pairs')
    require(type(pairs) is list and pairs and len({tuple(x) for x in pairs})==len(pairs),'unique supplied failed pairs required')
    require(report['status']=='passed' and report['diagnostic_delivery_complete'] and report['runtime_before_passed'] and report['runtime_after_passed'],'complete origin diagnostic and runtime custody required')
    require(all(report.get(k)==v for k,v in plans.required(plan,'origin_properties').items()),'original verdicts differ')
    require(len(report['candidates'])==len(expected),'complete candidate denominator required')
    require(report['budget']['calls']==candidate.evaluator_census(expected,probe),'origin derived evaluator census differs')
    require(report['compiled_identity']=={k:compiled[k] for k in candidate.IDENTITY_KEYS},'origin compiled identity differs')
    require(report['data']==probe['data'] and report['bounds']==probe['bounds'] and report['fixed_coordinates']==probe['fixed_coordinates'],'origin conditional problem differs')
    require(report['reference']['parameters']==reference and report['reference']['passed'],'verified original reference required')
    found=[];result=[];n=len(probe['bounds'])
    for index,(row,original) in enumerate(zip(report['candidates'],expected)):
        require(all(row[k]==original[k] for k in original),'literal candidate changed')
        require(len(row['finite_difference'])==len(row['analytic_gradient'])==n and [r['index'] for r in row['finite_difference']]==list(range(n)),'all derivative coordinates required')
        require(all(r['masked'] or r['absolute_residual']<=r['tolerance'] for r in row['gradient_parity']['coordinates']),'only convergence-only component failures admitted')
        for r in row['gradient_parity']['coordinates']:
            if r['passed']:continue
            coordinate=r['index'];found.append([index,coordinate]);fd=row['finite_difference'][coordinate]
            require(fd['rule']=='central' and fd['h']>0,'original central step required')
            result.append({'candidate_index':index,'backend':row['backend'],'seed_index':row['seed_index'],'coordinate':coordinate,'original_h':fd['h'],'original_h_gradient':fd['h_gradient'],'original_half_gradient':fd['half_gradient'],'retained_jax_gradient':row['analytic_gradient'][coordinate]})
    require(found==pairs,'complete supplied failed-coordinate census differs')
    return result


def document(task, base):
    from ravel.workflow.science import regular
    from ravel.workflow.execution import receipt_digest
    validate(task)
    path = regular(task['input'], base)
    d = json.loads(path.read_text())
    plan=plans.selected(d, ('failed_pairs','origin_properties'))
    plans.fields(d, ('plan','schema_version', 'operation', 'candidate_input', 'origin_execution',
                    'origin_result', 'origin_source', 'grounding', 'limits', 'criteria'),
                 'retained step-refinement input')
    require(d['schema_version'] == 1 and d['operation'] == 'retained_failed_gradient_step_refinement',
            'explicit step-refinement operation required')
    require(plans.limits(d['limits'],('adapter_seconds','numerical_seconds','evaluator_calls')) and validate_criteria(d['criteria']), 'predeclared work/criteria differ')
    bound = {k: parity._pin(d[k], path.parent) for k in
             ('candidate_input', 'origin_execution', 'origin_result', 'origin_source')}
    original = candidate.document({'input': str(bound['candidate_input'][0])}, path.parent)
    _, _, _, pp, pd, retained, compiled, probe, reference, expected = original
    record = bound['origin_execution'][1]
    require(record['status'] == 'succeeded' and record['exit_code'] == 0 and
            record['receipt_sha256'] == receipt_digest(record), 'completed origin receipt required')
    candidate._snapshot_pin(record['input_snapshot'], d['candidate_input'])
    candidate._snapshot_pin(record['input_snapshot'], d['origin_source'])
    candidate._snapshot_pin(record['output_snapshot'], d['origin_result'])
    report = bound['origin_result'][1]
    pairs = select_failed(report, expected, reference, compiled, probe, plan)
    return path, d, bound, pp, pd, compiled, probe, report, pairs


def inputs(task, base, *, _session=None):
    path, d, bound, *_ = document(task, base)
    result = [path, *candidate.inputs({'input': str(bound['candidate_input'][0])}, path.parent, _session=_session)]
    result += [p for p, _ in bound.values()]
    result += [parity._pin(row, path.parent)[0] for row in d['grounding']]
    for row in bound['origin_source'][1]['files']:
        p = Path(row['path'])
        require(p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest() == row['sha256'],
                'origin frozen source changed')
        result.append(p)
    return list(dict.fromkeys(result))


def _validation_inputs(task, base, session):
    return inputs(task, base, _session=session)


def execution_seconds(task, base):
    return document(task,base)[1]['limits']['adapter_seconds']


def resource_bounds(task, base):
    _,d,*_=document(task,base)
    selected={i for i,j in d['plan']['failed_pairs']}
    calls=2*(len(selected)+1)+2*len(d['criteria']['step_divisors'])*len(d['plan']['failed_pairs'])
    require(calls<=d['limits']['evaluator_calls'],'refinement evaluator ceiling insufficient')
    return {**d['limits'],'planned_evaluator_calls':calls,'worker_processes':1,'optimizer_calls':0,'events':0,'roots':0}


def validate_criteria(criteria):
    plans.tolerances(plans.required(criteria,'tolerances'))
    divisors=plans.required(criteria,'step_divisors')
    require(type(divisors) is list and len(divisors)==2 and 1<divisors[0]<divisors[1],'two ordered refinement divisors required')
    require(all(type(v) in (int,float) and math.isfinite(v) for v in divisors),'finite divisors required')
    interval=plans.required(criteria,'coarse_to_quarter_drift_ratio')
    require(len(interval)==2 and all(type(v) in (int,float) and math.isfinite(v) for v in interval) and interval[0]<=interval[1],'ordered supplied drift interval required')
    plans.positive(plans.required(criteria,'fine_drift_at_most_coarse_fraction'),'fine_drift_at_most_coarse_fraction')
    return True


def poisson_difference(n, plus, minus):
    """Algebraic log-ratio form, avoiding lgamma/constant subtraction."""
    require(math.isfinite(n+plus+minus) and n >= 0 and plus > 0 and minus > 0,
            'strictly positive finite retained Poisson means required')
    delta = plus-minus
    return 2*(delta - n*math.log1p(delta/minus))


def stable_difference(plus, minus, data, layout):
    """Twice-NLL(plus) minus twice-NLL(minus), using retained main means."""
    require(len(plus['main_means']) == len(minus['main_means']) and
            len(data) == len(plus['main_means'])+len(layout), 'complete stable-difference components required')
    terms = [poisson_difference(n, a, b) for n,a,b in
             zip(data[:len(plus['main_means'])], plus['main_means'], minus['main_means'])]
    a, b = plus['density']['auxiliary_expected'], minus['density']['auxiliary_expected']
    require(len(a) == len(b) == len(layout), 'all auxiliary means required')
    for row,n,x,y in zip(layout,data[len(plus['main_means']):],a,b):
        if row['pdf'] == 'normal':
            terms.append((x-y)*(x+y-2*n)/row['sigma']**2)
        elif row['pdf'] == 'poisson':
            terms.append(poisson_difference(n,x,y))
        else:
            raise ValueError('unknown auxiliary type')
    return {'difference': math.fsum(terms), 'term_differences': terms}


def classify(pair, criteria):
    tol = criteria['tolerances']
    def close(a,b):
        return abs(a-b) <= tol['gradient_atol']+tol['gradient_rtol']*max(abs(a),abs(b))
    large, small = pair['refined_steps']
    original_drift = pair['original_h_gradient']-pair['original_half_gradient']
    pair['cancellation_passed'] = all(close(r['whole_objective_gradient'],r['stable_term_gradient']) for r in (large,small))
    pair['retained_jax_agreement_passed'] = all(close(r[k],pair['retained_jax_gradient'])
        for r in (large,small) for k in ('whole_objective_gradient','stable_term_gradient'))
    pair['convergence_passed'] = all(abs(large[k]-small[k]) <= tol['gradient_atol']+tol['gradient_rtol']*abs(small[k])
                                    for k in ('whole_objective_gradient','stable_term_gradient'))
    pair['fine_drift_reduction_passed'] = all(abs(large[k]-small[k]) <= criteria['fine_drift_at_most_coarse_fraction']*abs(original_drift)
                                             for k in ('whole_objective_gradient','stable_term_gradient'))
    ratio = (pair['original_half_gradient']-large['stable_term_gradient'])/original_drift if original_drift else None
    pair['coarse_to_quarter_drift_ratio'] = ratio
    lo,hi = criteria['coarse_to_quarter_drift_ratio']
    pair['quadratic_scaling_consistent'] = ratio is not None and lo <= ratio <= hi
    pair['refined_coordinate_checks_passed'] = all(pair[k] for k in
        ('cancellation_passed','retained_jax_agreement_passed','convergence_passed','fine_drift_reduction_passed','quadratic_scaling_consistent'))


def run(task, base, output_dir):
    started = time.monotonic()
    path,d,bound,pp,pd,compiled,probe,origin,pairs = document(task,base)
    limits=d['limits'];criteria=d['criteria'];plan=d['plan']
    selected=sorted({i for i,j in plan['failed_pairs']})
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    require(not any(out.iterdir()), 'fresh refinement output required')
    report = {'schema_version':1, 'status':'failed', 'physics_validated':False,
              'scope':'Supplied coordinate refinement diagnostics; original verdicts unchanged',
              'original_arithmetic_parity_passed':origin['arithmetic_parity_passed'], 'original_jax_best_checks_passed':origin['all_candidate_checks_passed'],
              'paired_profile_completed':origin['paired_profile_completed'], 'optimizer_calls':0, 'events':0, 'roots':0,
              'limits':limits, 'criteria':criteria, 'baseline_checks':[], 'pairs':[], 'evaluation_journal':[],
              'refinement_checks_passed':False}
    report.update(plans.metadata(plan),output_format=plan['output']['format'])
    counter = runtime = None
    def save():
        report['elapsed_seconds'] = time.monotonic()-started
        if counter is not None:
            report['budget'] = counter.snapshot()
        plans.publish(out,plan,profile.json_safe(report))
    save()
    try:
        path,d,bound,pp,pd,compiled,probe,origin,pairs = document(task,base)
        runtime = parity._pin(pd['runtime_inventory'],pp.parent)[1]
        parity.runtime_files(runtime)
        report['runtime_before_passed'] = True
        report['origin_pins'] = {k:d[k] for k in ('candidate_input','origin_execution','origin_result','origin_source')}
        report['original_candidate_summaries'] = [{k:r[k] for k in
            ('backend','seed_index','parameters','recorded_twice_nll','fd_projected_gradient','analytic_projected_gradient','stationary','reference_quality_passed','candidate_checks_passed')}
            for r in origin['candidates']]
        counter = candidate.Counter(limits)
        counter.begin('numpy_refined_coordinate_checks',limits['numerical_seconds'])
        import numpy as np
        import pyhf
        from ravel.physics import published_model
        pyhf.set_backend('numpy',precision='64b')
        p,doc = parity._pin(pd['published_input'],pp.parent)
        contract = published_model.load_published_model(doc,p.parent)
        model,_,identity = published_model.compile_published_model(contract)
        identity = parity.compiled_json_identity(identity)
        require(all(identity[k] == compiled[k] for k in candidate.IDENTITY_KEYS), 'compiled identity changed')
        counter.check()
        layout = parity.constraint_layout(model)
        require(layout == origin['constraint_layout'], 'origin auxiliary layout changed')
        report.update(constraint_layout=layout,data=probe['data'],bounds=probe['bounds'],fixed_coordinates=probe['fixed_coordinates'])
        def evaluate(category, point, context, function):
            event = {'sequence':len(report['evaluation_journal']), 'category':category,
                     'parameters':list(point), 'context':context, 'status':'pending',
                     'invocation_started':False}
            report['evaluation_journal'].append(event)
            save()
            try:
                counter.check(category)
                event.update(status='running',invocation_started=True)
                save()
                value = function()
                event.update(status='completed',result=value)
                save()
                counter.check()
                return value
            except Exception as error:
                error_record = {'type':type(error).__name__,'message':str(error)}
                if event['status'] == 'completed':
                    event['post_call_error'] = error_record
                else:
                    event.update(status='failed' if event['invocation_started'] else 'refused',error=error_record)
                save()
                raise
        def scalar_value(point):
            means = np.asarray(model.expected_actualdata(point),dtype=float).tolist()
            return {'main_means':means,'density':parity.scalar_density(means,point,probe['data'],layout)}
        def scalar(point, context):
            return evaluate('independent_scalar_density',point,context,lambda:scalar_value(point))
        for index in [*selected,None]:
            old = origin['reference'] if index is None else origin['candidates'][index]
            point = old['parameters']
            context = {'phase':'baseline','candidate_index':index}
            baseline = {'candidate_index':index,'parameters':point,'status':'running'}
            report['baseline_checks'].append(baseline)
            save()
            numpy_value = evaluate('numpy_baseline_objective',point,context,
                lambda:float(np.asarray(pyhf.infer.mle.twice_nll(point,probe['data'],model)).reshape(-1)[0]))
            baseline['numpy_twice_nll'] = numpy_value
            save()
            terms = scalar(point,context)
            baseline['independent'] = terms
            save()
            residual = max(abs(numpy_value-old['numpy_twice_nll']),abs(terms['density']['twice_nll']-old['independent_twice_nll']),abs(numpy_value-terms['density']['twice_nll']))
            baseline.update(status='completed',maximum_residual=residual,passed=residual<=criteria['tolerances']['independent_density'])
            save()
        require(all(r['passed'] for r in report['baseline_checks']), 'unchanged baseline objective check failed')
        for pair in pairs:
            row = dict(pair,refined_steps=[])
            report['pairs'].append(row)
            original_point = origin['candidates'][pair['candidate_index']]['parameters']
            for divisor in criteria['step_divisors']:
                h = pair['original_h']/divisor
                minus,plus = list(original_point),list(original_point)
                minus[pair['coordinate']] -= h
                plus[pair['coordinate']] += h
                lo,hi = probe['bounds'][pair['coordinate']]
                require(lo < minus[pair['coordinate']] < plus[pair['coordinate']] < hi, 'refinement point leaves original interior')
                step = {'divisor':divisor,'h':h,'minus_parameters':minus,'plus_parameters':plus,'status':'running'}
                row['refined_steps'].append(step)
                save()
                context = {'phase':'perturbation','candidate_index':pair['candidate_index'],
                           'coordinate':pair['coordinate'],'divisor':divisor,'h':h}
                left = scalar(minus,{**context,'direction':'minus'})
                step['minus'] = left
                save()
                right = scalar(plus,{**context,'direction':'plus'})
                step['plus'] = right
                save()
                direct = (right['density']['twice_nll']-left['density']['twice_nll'])/(2*h)
                stable = stable_difference(right,left,probe['data'],layout)
                step.update(status='completed',whole_objective_gradient=direct,stable_term_gradient=stable['difference']/(2*h),stable_term_differences=stable['term_differences'])
                save()
            classify(row,criteria)
            save()
        require(counter.calls == resource_bounds(task,base)['planned_evaluator_calls'], 'derived refinement call census differs')
        report['refinement_checks_passed'] = all(row['refined_coordinate_checks_passed'] for row in report['pairs'])
        report['diagnostic_delivery_complete'] = True
        report['status'] = 'passed'
    except Exception as error:
        report.update(error={'type':type(error).__name__,'message':str(error)},refinement_checks_passed=False)
    finally:
        if runtime is not None:
            try:
                parity.runtime_files(runtime)
                report['runtime_after_passed'] = True
            except Exception as error:
                report.update(status='failed',refinement_checks_passed=False,runtime_after_error={'type':type(error).__name__,'message':str(error)})
        if time.monotonic()-started >= limits['adapter_seconds']:
            report.update(status='failed',refinement_checks_passed=False,error={'type':'CheckBudget','message':'adapter wall ceiling exhausted'})
        save()
    return report
