"""Bounded conditional-profile diagnostics from a supplied numerical plan."""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from ravel.validation import likelihood_parity as parity
from ravel.workflow.state_io import atomic_json
from ravel.validation import diagnostic_plan as plans

# Seconds of each backend allowance kept for writing a failed child report.
RETAIN_SECONDS=2
SCOPE='Conditional profile replay diagnostics; distinct scalar and analytic protocols, no exclusion or physics validation'


def require(value,message):
    if not value:raise ValueError(message)


def json_safe(value):
    if hasattr(value,'tolist'):value=value.tolist()
    if isinstance(value,dict):return {key:json_safe(item) for key,item in value.items()}
    if isinstance(value,(tuple,list)):return [json_safe(item) for item in value]
    return parity._finite_json(value)


def finite_difference_gradient(rows, tolerances):
    require([r['index'] for r in rows]==list(range(len(rows))),'every finite-difference coordinate required')
    gradient=[];converged=True
    for row in rows:
        if row['rule']=='fixed':gradient.append(0.);continue
        first,second=row['h_gradient'],row['half_gradient']
        require(math.isfinite(first) and math.isfinite(second),'nonfinite finite-difference derivative')
        gradient.append(second)
        converged &= abs(first-second)<=tolerances['gradient_atol']+tolerances['gradient_rtol']*abs(second)
    return gradient,converged


def validate(task):
    parity._keys(task,('input',),'conditional profile task')
    require(isinstance(task['input'],str) and task['input'],'profile input required')


def document(task,base):
    from ravel.workflow.science import regular
    validate(task);path=regular(task['input'],base);d=json.loads(path.read_text())
    plan=plans.selected(d, ('review_actors', 'probe_selector', 'reference_selector', 'engine_sha256', 'optimizer_maxiter'))
    plans.fields(d,('plan','schema_version','parity_input','parity_acceptance','parity_cycle','grounding','limits','tolerances','initial_escalation'),'profile input')
    require(d['schema_version']==1 and plans.limits(d['limits'], ('adapter_seconds','per_backend_seconds','calls_per_backend','witness_bytes')) and plans.tolerances(d['tolerances']),'fixed profile numerical/budget contract differs')
    require(set(d['initial_escalation'])=={'numpy','jax'} and all(type(v) is bool for v in d['initial_escalation'].values()),'explicit protocol states required')
    plans.positive(plan['optimizer_maxiter'],'optimizer_maxiter',integer=True)
    require(isinstance(plan['probe_selector'],dict) and plan['probe_selector'] and isinstance(plan['reference_selector'],dict) and plan['reference_selector'],'explicit probe/reference selectors required')
    require(len(plan['engine_sha256'])==64 and all(c in '0123456789abcdef' for c in plan['engine_sha256']),'engine source digest required')
    require(d['limits']['adapter_seconds']>2*d['limits']['per_backend_seconds'],'reserve whole-stage time beyond backend budgets')
    require(d['limits']['per_backend_seconds']>RETAIN_SECONDS,'backend budget must exceed its failure-retention reserve')
    votes=[parity._pin(p,path.parent)[1] for p in d['parity_acceptance']]
    actors=plan['review_actors']
    require(set(actors)=={'physics_critic','skeptical_verifier','physics_decider'} and len(set(actors.values()))==3,'distinct actual review actors required')
    require(len(votes)==3 and {v.get('role') for v in votes}==set(actors),'three actual parity review roles required')
    require(len({v.get('cycle_id') for v in votes})==1,'parity review cycle differs')
    for v in votes:
        require(v.get('event')=='review' and v.get('verdict')=='accept' and v.get('claim_scope')=='fixed_vector_numerics' and v.get('actor_id')==actors[v['role']],'accepted fixed-vector prerequisite not established')
    from ravel.workflow.execution import digest
    _,cycle=parity._pin(d['parity_cycle'],path.parent)
    require(cycle.get('event')=='cycle' and cycle.get('checkpoint') is False,'complete accepted parity cycle required')
    require(cycle.get('cycle_id')==votes[0]['cycle_id'] and all(v.get('run_id')==cycle.get('run_id') for v in votes),'accepted parity source/cycle differs')
    previous=cycle
    for event in [cycle,*sorted(votes,key=lambda v:v['sequence'])]:
        require(event.get('sha256')==digest({k:v for k,v in event.items() if k!='sha256'}),'parity event digest differs')
        if event is not cycle:
            require(event['previous_sha256']==previous['sha256'] and event['sequence']==previous['sequence']+1,'parity acceptance chain differs')
        previous=event
    pp,pd=parity._pin(d['parity_input'],path.parent)
    accepted={p['path']:p['sha256'] for p in cycle['snapshots']}
    require(accepted.get(str(pp))==d['parity_input']['sha256'],'parity input was not the accepted cycle input')
    for key in ('published_input','retained_inputs','compiled_reference','runtime_inventory'):
        p,_=parity._pin(pd[key],pp.parent)
        require(accepted.get(str(p))==pd[key]['sha256'],'accepted parity source differs: '+key)
    return path,d


def inputs(task,base,*,_session=None):
    path,d=document(task,base);p,_=parity._pin(d['parity_input'],path.parent)
    result=[path,*parity.inputs({'input':str(p)},p.parent,_session=_session)]
    for row in [d['parity_cycle'],*d['parity_acceptance'],*d['grounding']]:result.append(parity._pin(row,path.parent)[0])
    return list(dict.fromkeys(result))


def _validation_inputs(task,base,session):return inputs(task,base,_session=session)
def execution_seconds(task,base):return document(task,base)[1]['limits']['adapter_seconds']
def resource_bounds(task,base):return document(task,base)[1]['limits']


class ProbeBudget(BaseException):
    """Must escape the legacy optimizer's ordinary numerical-error fallbacks."""


class Counter:
    def __init__(self,deadline,limit):self.deadline=deadline;self.limit=limit;self.calls=0;self.categories={}
    def check(self,category=None):
        if time.monotonic()>=self.deadline:raise ProbeBudget('backend wall budget exhausted')
        if category is not None:
            if self.calls>=self.limit:raise ProbeBudget('backend evaluator call budget exhausted')
            self.calls+=1;self.categories[category]=self.categories.get(category,0)+1


def validate_probe(retained,compiled,plan):
    plans.required(plan, 'probe_selector')
    probe=retained['conditional_probe']
    require(all(probe.get(k)==v for k,v in plan['probe_selector'].items()),'selected profile identity differs')
    n=compiled['npars']
    require(type(n) is int and n>0 and len(compiled['observed_and_auxiliary_data'])==compiled['nmaindata']+compiled['nauxdata'],'source dimensions differ')
    require(compiled['parameter_names']==retained['parameter_names'] and compiled['parameter_order']==retained['parameter_order'],'ordered parameters differ')
    require(len(compiled['parameter_names'])==len(compiled['fixed'])==n,'complete model parameters required')
    require(compiled['model_compact_sha256']==retained['model_sha256'] and compiled['data_compact_sha256']==retained['data_sha256'],'source model/data identity differs')
    require(probe['data']==compiled['observed_and_auxiliary_data'],'observations differ')
    require(compiled['fixed']==retained['source_suggested_fixed'],'source fixed mask differs')
    fixed=probe['fixed_coordinates']
    require(len({i for i,v in fixed})==len(fixed) and all(type(i) is int and 0<=i<n and type(v) in (int,float) and math.isfinite(v) for i,v in fixed),'valid unique fixed coordinates required')
    require(all(any(i==j for j,v in fixed) for i,f in enumerate(compiled['fixed']) if f),'source fixed coordinate omitted')
    starts=probe['ordered_starts'];bounds=probe['bounds']
    require(hashlib.sha256(json.dumps(starts,separators=(',',':'),allow_nan=False).encode()).hexdigest()==probe['ordered_starts_compact_sha256'],'literal ordered start digest differs')
    require(starts and len({tuple(x) for x in starts})==len(starts) and len(bounds)==n,'distinct supplied start portfolio required')
    require(all(len(pair)==2 and all(type(v) in (int,float) and math.isfinite(v) for v in pair) and pair[0]<pair[1] for pair in bounds),'finite ordered bounds required')
    for seed in starts:
        require(len(seed)==n,'start dimension differs')
        require(all(type(x) in (int,float) and math.isfinite(x) and lo<=x<=hi for x,(lo,hi) in zip(seed,bounds)),'start outside exact bounds')
        require(all(seed[i]==v for i,v in fixed),'start changed fixed coordinate')
    return probe


def retained_reference(retained,probe,plan):
    rows=[row for row in retained['saved_fixed_vector_references'] if all(row.get(k)==v for k,v in plans.required(plan,'reference_selector').items())]
    require(len(rows)==1,'one exact retained observed conditional reference required')
    row=rows[0];point=row['parameters']
    require(row['data']==probe['data'] and row['fit_bounds']==probe['bounds'],'retained feasible reference problem differs')
    require(len(point)==len(probe['bounds']) and all(type(x) in (int,float) and math.isfinite(x) and lo<=x<=hi for x,(lo,hi) in zip(point,probe['bounds'])),'retained reference outside fixed bounds')
    require(all(point[i]==v for i,v in probe['fixed_coordinates']),'retained reference fixed coordinates differ')
    require(math.isfinite(probe['recorded_best_twice_nll']),'retained reference objective nonfinite')
    return point


def reference_guard(independent,point,recorded,best,tolerances):
    value=independent(point)
    require(math.isfinite(value),'retained reference has nonfinite independent objective')
    residual=abs(value-recorded);delta=best-value
    return {'parameters':point,'recorded_twice_nll':recorded,'independent_twice_nll':value,
            'independent_density_residual':residual,'best_minus_reference':delta,
            'passed':residual<=tolerances['independent_density'] and delta<=tolerances['objective_agreement']}


def child_backend(input_path,backend,out,numpy_report):
    """One isolated backend within the supplied deadline."""
    start=time.monotonic();out=Path(out);out.mkdir(exist_ok=False)
    report={'status':'running','backend':backend,'scope':SCOPE,'physics_validated':False,'timing':{},'trials':[],'strategy_passes':[],
            'profile_calls':1,'root_searches':0,'asimov_generating_fits':0,'initial_escalation':None,
            'deadline_note':'Supplied backend budget includes startup; the internal deadline keeps two seconds for retaining failure. No retry.'}
    counter=None
    def save():
        report['elapsed_seconds']=time.monotonic()-start
        if counter is not None:report['counter']={'calls':counter.calls,'categories':counter.categories}
        starts=report.get('compiled_identity',{}).get('ordered_starts')
        report['seed_denominator']=None if starts is None else len(starts)
        report['started_seed_trials']=len(report['trials'])
        report['unattempted_seed_indices']=[] if starts is None else list(range(len(report['trials']),len(starts)))
        atomic_json(out/'profile.json',json_safe(report))
    try:
        path,d=document({'input':str(input_path)},Path(input_path).parent)
    except Exception as exc:
        report.update(status='failed',error={'type':type(exc).__name__,'message':str(exc)});save()
        return 3
    limits=d['limits'];tolerances=d['tolerances'];plan=d['plan'];report['initial_escalation']=d['initial_escalation'][backend]
    counter=Counter(start+limits['per_backend_seconds']-RETAIN_SECONDS,limits['calls_per_backend'])
    witness=None;old_migrad=None;Minuit=None
    save()
    try:
        path,d=document({'input':str(input_path)},Path(input_path).parent)
        pp,pd=parity._pin(d['parity_input'],path.parent)
        bound={k:parity._pin(pd[k],pp.parent) for k in ('published_input','retained_inputs','compiled_reference')}
        import numpy as np
        import pyhf
        import scipy.optimize as so
        from iminuit import Minuit
        from ravel.physics import pyhf_exclude as engine,published_model
        require(hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest()==plan['engine_sha256'],'existing robust optimizer source changed')
        report['timing']['imports_seconds']=time.monotonic()-start
        contract=published_model.load_published_model(bound['published_input'][1],bound['published_input'][0].parent)
        reference,representation=parity.compiled_reference_identity(bound['compiled_reference'][1]);report['source_representation']=representation
        def compile_model(name):
            began=time.monotonic();counter.check();pyhf.set_backend(name,precision='64b')
            model,data,compiled=published_model.compile_published_model(contract);compiled=parity.compiled_json_identity(compiled)
            for key in ('modifier_settings','measurement','parameter_order','channel_order','channel_slices','sample_order','nmaindata','parameter_names','bounds','inits','fixed','npars','nauxdata','auxdata','constraints','observed_and_auxiliary_data','model_compact_sha256','data_compact_sha256'):
                require(compiled[key]==reference[key],'compiled reference differs: '+key)
            report['timing'][name+'_compile_seconds']=time.monotonic()-began
            return model,compiled
        model,compiled=compile_model(backend);probe=validate_probe(bound['retained_inputs'][1],compiled,plan)
        reference_point=retained_reference(bound['retained_inputs'][1],probe,plan)
        report['compiled_identity']={'model_sha256':compiled['model_compact_sha256'],'data_sha256':compiled['data_compact_sha256'],'bounds':probe['bounds'],'fixed_coordinates':probe['fixed_coordinates'],'ordered_starts':probe['ordered_starts']}
        data=np.asarray(probe['data'],dtype=float);layout=parity.constraint_layout(model)
        report['threads_before_profile']=parity._thread_snapshot()
        if backend=='jax':
            import jax
            require(jax.config.x64_enabled and all(d.platform=='cpu' for d in jax.devices()),'float64 CPU JAX required')
            raw=jax.jit(jax.value_and_grad(lambda x:pyhf.infer.mle.twice_nll(x,data,model)[0]))
            def objective(x):
                counter.check('analytic_value_and_gradient');value,gradient=raw(x)
                value=float(np.asarray(value));gradient=np.asarray(gradient,dtype=float);counter.check()
                if counter.calls%1000==0:save()
                return value,gradient
        else:
            def objective(x):
                counter.check('scalar_objective');value=float(np.asarray(pyhf.infer.mle.twice_nll(x,data,model)).reshape(-1)[0]);counter.check()
                if counter.calls%1000==0:save()
                return value
        began=time.monotonic();objective(np.asarray(probe['ordered_starts'][0],dtype=float));report['timing']['first_synchronized_evaluation_seconds']=time.monotonic()-began
        record={};witness=engine._ProfileWitnessRecorder(record,max_evaluations=1,max_minimizations=len(probe['ordered_starts']),max_bytes=limits['witness_bytes'],journal_path=out/'optimizer-witness.jsonl')
        opt=engine.robust_optimizer(maxiter=plan['optimizer_maxiter'],tolerance=tolerances['fit_requested']);opt.begin_model();opt._profile_frozen=True;opt._witness=witness;opt._witness_evaluation=1
        engine.robust_optimizer.escalated=d['initial_escalation'][backend]
        for key in ('n_fits','n_fallback','n_escalated','n_nan_flagged'):setattr(engine.robust_optimizer,key,0)
        engine.robust_optimizer._announced=False
        witness.start('profile_calls',status='running',evaluation_index=1,nominal_seed=probe['ordered_starts'][0],bounds=probe['bounds'],fixed_coordinates=probe['fixed_coordinates'],selected_seeds=probe['ordered_starts'],analytic_gradient=backend=='jax',pool_frozen=True,scope='Exact retained supplied starts; no current-data re-ranking or adaptive pool evolution')
        old_migrad=Minuit.migrad
        def timed_migrad(instance,*args,**kwargs):
            counter.check();began=time.monotonic();row={'status':'running','seed_index':len(report['trials'])-1,'strategy':int(instance.strategy.strategy),'tolerance':float(instance.tol),'ncall':kwargs.get('ncall'),'nfcn_before':instance.nfcn,'ngrad_before':instance.ngrad}
            report['strategy_passes'].append(row);save()
            try:
                result=old_migrad(instance,*args,**kwargs);row.update(status='returned',valid=bool(instance.valid),edm=float(instance.fmin.edm));return result
            except BaseException as exc:row.update(status='failed',error={'type':type(exc).__name__,'message':str(exc)});raise
            finally:
                row.update(seconds=time.monotonic()-began,nfcn_after=instance.nfcn,ngrad_after=instance.ngrad);save()
        Minuit.migrad=timed_migrad
        successful=[];began_profile=time.monotonic()
        for index,seed in enumerate(probe['ordered_starts']):
            counter.check();began=time.monotonic();row={'seed_index':index,'seed':seed,'status':'running','escalated_before':bool(engine.robust_optimizer.escalated),'calls_before':counter.calls};report['trials'].append(row);save()
            witness.start('minimizations',status='running',profile_call_index=0,evaluation_index=1,seed=seed,escalated_before=bool(engine.robust_optimizer.escalated));opt._witness_trial=index
            try:
                result=opt._minimize_once(so.minimize,objective,np.asarray(seed,dtype=float),backend=='jax',probe['bounds'],probe['fixed_coordinates'],{})
                observed=engine.robust_optimizer._result_witness(result);observed.update(njev=getattr(result,'njev',None),nit=getattr(result,'nit',None))
                row.update(status='succeeded',result=observed);successful.append(result);witness.update('minimizations',index,status='succeeded',result=observed,escalated_after=bool(engine.robust_optimizer.escalated))
            except (RuntimeError,ValueError) as exc:
                row.update(status='failed',error={'type':type(exc).__name__,'message':str(exc)});witness.update('minimizations',index,status='failed',error=row['error'])
            except BaseException as exc:
                row.update(status='interrupted',error={'type':type(exc).__name__,'message':str(exc)});witness.update('minimizations',index,status='interrupted',error=row['error']);raise
            finally:
                row.update(seconds=time.monotonic()-began,calls_after=counter.calls,escalated_after=bool(engine.robust_optimizer.escalated));save()
        report['timing']['portfolio_profile_seconds']=time.monotonic()-began_profile
        report['optimizer_counts']={k:getattr(engine.robust_optimizer,k) for k in ('n_fits','n_fallback','n_escalated','n_nan_flagged')}
        require(successful,'no successful supplied start')
        best=min(successful,key=lambda r:float(r.fun));report['best']=engine.robust_optimizer._result_witness(best)
        report['retained_reference_objective']=probe['recorded_best_twice_nll']
        report['best_minus_retained_reference']=float(best.fun)-probe['recorded_best_twice_nll']
        witness.update('profile_calls',0,status='succeeded',chosen_result=report['best'])
        if backend=='jax':
            value,gradient=objective(np.asarray(best.x));report['best_analytic_gradient']=gradient
            report['analytic_projected_gradient']=engine.robust_optimizer.projected_gradient(best.x,gradient,probe['bounds'],probe['fixed_coordinates'])
            # Independent arithmetic uses a newly compiled NumPy phase after
            # the analytic profile, within the supplied backend allowance.
            model,unused=compile_model('numpy');layout=parity.constraint_layout(model)
        def independent(x):
            counter.check('independent_scalar_density');means=np.asarray(model.expected_actualdata(x),dtype=float).tolist()
            return parity.scalar_density(means,x.tolist() if hasattr(x,'tolist') else x,probe['data'],layout)['twice_nll']
        def check_point(parameters,objective_value,label):
            scalar=independent(np.asarray(parameters,dtype=float));fd=parity.finite_difference(independent,parameters,probe['bounds'],probe['fixed_coordinates'],step_scale=tolerances['step_scale'])
            gradient,converged=finite_difference_gradient(fd,tolerances);projected=engine.robust_optimizer.projected_gradient(parameters,gradient,probe['bounds'],probe['fixed_coordinates'])
            return {'label':label,'parameters':parameters,'reported_objective':objective_value,'independent_twice_nll':scalar,'independent_density_residual':abs(scalar-objective_value),'finite_difference':fd,'step_convergence_passed':converged,'projected_gradient_max':projected,'stationary':converged and projected<=tolerances['stationarity']}
        report['retained_reference_check']=reference_guard(independent,reference_point,probe['recorded_best_twice_nll'],float(best.fun),tolerances)
        report['reference_guard_passed']=report['retained_reference_check']['passed']
        report['best_independent_check']=check_point(report['best']['parameters'],report['best']['objective'],backend+'_best')
        if backend=='jax':
            report['best_gradient_parity']=parity.compare_gradients(report['best_independent_check']['finite_difference'],report['best_analytic_gradient'],atol=tolerances['gradient_atol'],rtol=tolerances['gradient_rtol'])
        if backend=='jax' and numpy_report and Path(numpy_report).exists():
            previous=json.loads(Path(numpy_report).read_text())
            if previous.get('best') is not None:
                report['numpy_best_crosscheck']=check_point(previous['best']['parameters'],previous['best']['objective'],'numpy_best')
        require(report['best_independent_check']['independent_density_residual']<=tolerances['independent_density'],'independent objective differs')
        report.update(status='completed',starts_finished=len(report['trials'])==len(probe['ordered_starts']) and all(t['status'] in ('succeeded','failed') for t in report['trials']),finite_stationary_best=report['best_independent_check']['stationary'] and (backend!='jax' or report['analytic_projected_gradient']<=tolerances['stationarity'] and report['best_gradient_parity']['passed']))
        witness.finish('succeeded');witness=None
    except BaseException as exc:
        report.update(status='failed',error={'type':type(exc).__name__,'message':str(exc)})
        if witness is not None:
            try:witness.finish('failed',exc)
            except BaseException as final_error:report['witness_terminal_error']={'type':type(final_error).__name__,'message':str(final_error)}
    finally:
        if old_migrad is not None:Minuit.migrad=old_migrad
        report['threads_after']=parity._thread_snapshot();save()
    return 0 if report['status']=='completed' else 3


def run(task,base,output_dir):
    started=time.monotonic();path,d=document(task,base);limits=d['limits'];tolerances=d['tolerances'];plan=d['plan'];out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    require(not any(out.iterdir()),'fresh profile output required')
    pp,pd=parity._pin(d['parity_input'],path.parent);runtime=parity._pin(pd['runtime_inventory'],pp.parent)[1]
    report={'schema_version':1,'status':'failed','scope':SCOPE,'physics_validated':False,'backend_commands':[],'comparison_passed':False,'generated_events':0,'root_searches':0,'asimov_generating_fits':0,
        'limits':limits,'tolerances':tolerances,'limitations':['Supplied portfolio only; no global minimum proof.','Failed, interrupted and unattempted seeds remain visible.']}
    report.update(plans.metadata(plan),output_format=plan['output']['format'])
    def save():report['elapsed_seconds']=time.monotonic()-started;plans.publish(out,plan,json_safe(report))
    save()
    try:
        parity.runtime_files(runtime);report['runtime_before_passed']=True;save()
        bootstrap=Path(__file__).resolve().parents[1]/'_bootstrap.py'
        for backend in ('numpy','jax'):
            require(time.monotonic()-started<limits['adapter_seconds'],'adapter wall budget exhausted')
            target=out/backend;argv=[sys.executable,str(bootstrap),'ravel.validation.likelihood_profile_probe','child',str(path),backend,str(target),str(out/'numpy/profile.json')]
            row={'backend':backend,'argv':argv,'cwd':str(base),'timeout_seconds':limits['per_backend_seconds'],'status':'planned','timed_out':False};report['backend_commands'].append(row);save();began=time.monotonic()
            with (out/(backend+'.log')).open('xb') as stream:
                stream.write((json.dumps({'event':'backend_command_planned','backend':backend,'argv':argv,'timeout_seconds':limits['per_backend_seconds']},sort_keys=True)+'\n').encode('utf-8'));stream.flush()
                process=subprocess.Popen(argv,cwd=base,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT)
                row.update(status='running',pid=process.pid);save()
                try:row['returncode']=process.wait(timeout=min(limits['per_backend_seconds'],limits['adapter_seconds']-(time.monotonic()-started)))
                except subprocess.TimeoutExpired:
                    row['timed_out']=True;process.kill();row['returncode']=process.wait(timeout=2)
                row.update(status='returned',elapsed_seconds=time.monotonic()-began);save()
            result=target/'profile.json';row['result_present']=result.is_file()
            if result.is_file():row['result_sha256']=hashlib.sha256(result.read_bytes()).hexdigest()
        records={backend:json.loads((out/backend/'profile.json').read_text()) for backend in ('numpy','jax') if (out/backend/'profile.json').is_file()}
        report['backend_results']=records
        report['backend_commands_clean']=len(report['backend_commands'])==2 and all(r.get('status')=='returned' and r.get('returncode')==0 and r.get('timed_out') is False for r in report['backend_commands'])
        if report['backend_commands_clean'] and len(records)==2 and all(r.get('status')=='completed' and r.get('starts_finished') and r.get('finite_stationary_best') and r.get('reference_guard_passed') for r in records.values()):
            gap=abs(records['numpy']['best']['objective']-records['jax']['best']['objective'])
            cross=records['jax'].get('numpy_best_crosscheck',{})
            report['objective_absolute_difference']=gap
            report['comparison_passed']=gap<=tolerances['objective_agreement'] and cross.get('stationary') is True and cross.get('independent_density_residual',math.inf)<=tolerances['independent_density']
        parity.runtime_files(runtime);report['runtime_after_passed']=True
        require(time.monotonic()-started<limits['adapter_seconds'],'adapter wall budget exhausted')
        # Diagnostic delivery can be complete while numerical comparison fails.
        # Claim acceptance must inspect comparison_passed and all denominators.
        report['status']='passed';report['diagnostic_delivery_complete']=len(records)==2
        require(report['diagnostic_delivery_complete'],'backend result absent; preserve logs and interrupted evidence')
    except Exception as exc:report.update(status='failed',comparison_passed=False,error={'type':type(exc).__name__,'message':str(exc)})
    save();return report


def main():
    args=sys.argv[1:]
    require(len(args)==5 and args[0]=='child' and args[2] in ('numpy','jax'),'private exact backend worker arguments required')
    return child_backend(args[1],args[2],args[3],args[4])


if __name__=='__main__':raise SystemExit(main())
