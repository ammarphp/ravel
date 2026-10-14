"""Same-data source-Asimov discovery profiles using the existing native profiler.

No ROOT import, optimizer, sampler or process launcher is defined here. execute
is called only by native_likelihood's bounded native worker with its ROOT facade.
All partial fits and unissued starts remain in the journal on failure.
"""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import time

KIND = 'same_dataset_source_graph_discovery_profiles/v1'


def require(ok, message):
    if not ok: raise ValueError(message)


def keys(x, fields, name):
    require(type(x) is dict and set(x) == set(fields), 'closed '+name+' required')


def finite(x):
    require(type(x) in (int, float) and math.isfinite(x), 'finite native return required')
    return float(x)


def exact(x):
    require(type(x) is str, 'literal rational source coordinate required')
    value=Fraction(x);finite(float(value));return value


def validate(request, cell, optimizer_policy):
    keys(request, ('kind','convention','starts','profile_policy','max_fit_calls',
                  'max_readbacks','absolute_nll_band','relative_nll_band','source','statement'), 'discovery request')
    require(request['kind']==KIND and request['convention']=='physical_nonnegative_domain',
            'source-declared nonnegative physical POI convention required')
    require('expected_data' in cell and 'calibration' not in cell and 'derivatives' not in cell and
            cell['expected_data']['conditioning']=='supplied_nominal', 'one supplied nominal source Asimov experiment required')
    pars=cell['law']['parameters']+cell['parameters']
    # Only law parameters carry a role. Graph coordinates of the cell are closed
    # name/domain rows and can never be the parameter of interest.
    poi=[p for p in cell['law']['parameters'] if p['role']=='poi'];require(len(poi)==1, 'one original POI required')
    poi=poi[0];require(not poi['fixed'] and exact(poi['bounds'][0])==0 and
        0<exact(cell['expected_data']['point'][poi['name']])<=exact(poi['bounds'][1]),
        'original nonnegative domain must contain null and positive generation')
    require(request['profile_policy']==optimizer_policy, 'reuse exact existing profile policy; no unreviewed optimizer')
    require(request['source'] in {s['id'] for s in cell['law']['sources']} and
            type(request['statement']) is str and request['statement'].strip(), 'source-bound discovery convention required')
    coords={p['name']:p for p in pars}
    for i,bounds in enumerate(cell['law']['auxiliary']['eta_bounds']):
        coords['ravel_aux_'+str(i)]={'bounds':bounds,'fixed':False,'initial':cell['law']['auxiliary']['observed'][i]}
    keys(request['starts'], ('free','null'), 'two profile roles')
    count=0
    for role,starts in request['starts'].items():
        require(type(starts) is list and 1<=len(starts)<=4, 'bounded complete prespecified starts required')
        count+=len(starts)
        for point in starts:
            keys(point, coords, 'complete original start coordinates')
            for name,par in coords.items():
                q=exact(point[name]);require(exact(par['bounds'][0])<=q<=exact(par['bounds'][1]), 'start outside original domain')
                if par['fixed']:require(q==exact(par['initial']), 'start changes fixed source coordinate')
            if role=='null':require(exact(point[poi['name']])==0, 'null start must fix original POI exactly zero')
    require(type(request['max_fit_calls']) is int and request['max_fit_calls']==count,
            'full planned fit population must equal exact cap')
    require(type(request['max_readbacks']) is int and request['max_readbacks']==1+2*count,
            'one generating readback plus two common readbacks per fit required')
    require(0<=exact(request['absolute_nll_band'])<=Fraction('1e-6') and
            0<=exact(request['relative_nll_band'])<=Fraction('1e-8'), 'bounded prespecified arithmetic band required')
    return deepcopy(request)


def contrast(free, null, generating, muhat, request):
    free,null,generating,muhat=map(finite,(free,null,generating,muhat))
    require(muhat>=0, 'profile returned POI outside admitted physical convention')
    band=float(exact(request['absolute_nll_band']))+float(exact(request['relative_nll_band']))*max(abs(null-free),abs(generating-free))
    require(free<=null+band and free<=generating+band, 'free profile worse than known null/generating candidate')
    raw=2*(null-free);require(raw>=-2*band, 'materially negative discovery contrast')
    q=max(0.,raw)
    return {'signed_common_nll_contrast':raw,'q0_asimov':q,'nll_band':band,
        'negative_contrast_clipped_within_band':raw<0,
        'local_expected_asymptotic_proxy':math.sqrt(q),'observed_significance':None,
        'global_significance':None,'coverage_qualified':False,'optimizer_globality_qualified':False,
        'physics_validated':False}


def snapshot(w):
    """All native real variables, with explicit absent bounds and all errors."""
    result={}
    for v in w.allVars():
        name=str(v.GetName());require(name not in result, 'duplicate native variable')
        result[name]={'value':finite(v.getVal()),'constant':bool(v.isConstant()),
            'has_min':bool(v.hasMin()),'minimum':finite(v.getMin()) if v.hasMin() else None,
            'has_max':bool(v.hasMax()),'maximum':finite(v.getMax()) if v.hasMax() else None,
            'has_error':bool(v.hasError()),'error':finite(v.getError()),
            'has_asymmetric_error':bool(v.hasAsymError()),
            'low':finite(v.getAsymErrorLo()),'high':finite(v.getAsymErrorHi())}
    return result


def restore(w, saved):
    require(set(snapshot(w))==set(saved), 'whole native variable population changed')
    for name,row in saved.items():
        v=w.var(name)
        require(bool(v) and bool(v.hasMin())==row['has_min'] and bool(v.hasMax())==row['has_max'] and
            (not row['has_min'] or finite(v.getMin())==row['minimum']) and
            (not row['has_max'] or finite(v.getMax())==row['maximum']), 'native profile changed a source domain')
        v.setVal(row['value']);v.setConstant(row['constant'])
        if row['has_error']:v.setError(row['error'])
        else:v.removeError()
        if row['has_asymmetric_error']:v.setAsymError(row['low'],row['high'])
        else:v.removeAsymError()
    require(snapshot(w)==saved, 'complete native state/error restoration differs')


def validate_delivery(result,response,request,optimizer):
    """Read-only host law/fit/state audit, separate from file/ordinary custody."""
    cell=next(x for x in response['recipe']['cells'] if x['id']==response['cell'])
    request=validate(request,cell,optimizer.PROFILE_POLICY)
    require(result['kind']==KIND and result['status']=='passed' and result['request']==request and
            result['cell']==response['cell'] and result['profile_policy']==optimizer.PROFILE_POLICY,
            'complete exact native pair request/delivery required')
    planned=[(role+'_'+str(i),role,point) for role in ('free','null') for i,point in enumerate(request['starts'][role])]
    rows=result['profiles'];require(len(rows)==len(planned) and
        [(r['id'],r['role'],r['point']) for r in rows]==planned and all(r['status']=='passed' for r in rows),
        'failed, unissued, missing or reordered fit population cannot pass')
    require(result['fit_calls']==request['max_fit_calls'] and result['readback_calls']==request['max_readbacks'] and
            result['ending_whole_state']==result['initial_whole_state'] and
            result['ending_model_state']==result['initial_model_state'], 'complete calls and source reset required')
    preparation=result['generation'];require(result['counts']==preparation['dataset_counts'] and
        result['globals']==preparation['generated_globals'] and result['dataset_weight']==1., 'same actual generated data/globals required')
    require(result['source_recipe_sha256']==hashlib.sha256(json.dumps(response['recipe'],sort_keys=True,allow_nan=False).encode()).hexdigest() and
            result['initial_coordinates']==preparation['final_state'] and preparation['request']==cell['expected_data'], 'exact original source/generating state required')
    initial=result['initial_coordinates'];poi=next(p['name'] for p in cell['law']['parameters'] if p['role']=='poi')
    raw_names=set();whole=result['initial_whole_state'];model=result['initial_model_state']
    require({r['name'] for r in model['parameters'] if r['kind']=='continuous'}==set(whole), 'whole native real variable census differs')
    for row in rows:
        require(set(row['whole_state'])==set(whole) and set(row['start_whole_state'])==set(whole) and
            row['model_state']['categories']==model['categories'] and row['model_state']['model_config']==model['model_config'], 'whole native/category/model options census differs')
        for name,old in whole.items():
            now=row['whole_state'][name];start=row['start_whole_state'][name]
            keys(now,old,'whole fitted native state');keys(start,old,'whole starting native state')
            for k in ('has_min','minimum','has_max','maximum'):
                require(now[k]==old[k] and start[k]==old[k], 'native source domain changed')
            require(start['value']==(float(exact(row['point'][name])) if name in initial else old['value']) and
                start['constant']==(row['role']=='null' if name==poi else old['constant']) and
                all(start[k]==old[k] for k in ('has_error','error','has_asymmetric_error','low','high')), 'complete prescribed start/error reset differs')
            if name not in initial:require(now==old, 'nonprofile native state changed')
            for k in ('value','error','low','high'):finite(now[k])
        original_model_rows={p['name']:p for p in model['parameters']}
        current_model_rows={p['name']:p for p in row['model_state']['parameters']}
        require(len(current_model_rows)==len(row['model_state']['parameters']) and set(current_model_rows)==set(original_model_rows), 'complete original model coordinate population differs')
        for name,p in current_model_rows.items():
            old=original_model_rows[name];keys(p,old,'whole model coordinate')
            require(all(p[k]==old[k] for k in old if k not in ('value','constant')), 'native model role/domain/type changed')
            if p['kind']!='continuous':require(p==old, 'native category state changed')
        model_real={r['name']:r for r in row['model_state']['parameters'] if r['kind']=='continuous'}
        require(set(model_real)==set(whole) and all(model_real[n]['value']==x['value'] and model_real[n]['constant']==x['constant'] for n,x in row['whole_state'].items()), 'model and full error/state census disagree')
        keys(row['errors'],initial,'complete fitted error census')
        for name,error in row['errors'].items():
            now=row['whole_state'][name]
            require(error=={k:now[k] for k in ('has_error','error','has_asymmetric_error','low','high')}, 'fitted error readback differs')
        keys(row['state'],initial,'complete fitted coordinates')
        free={n for n,s in row['state'].items() if not s['constant']}
        for name,s in row['state'].items():
            old=initial[name];keys(s,old,'fitted coordinate')
            require(s['minimum']==old['minimum'] and s['maximum']==old['maximum'] and
                s['constant']==(row['role']=='null' if name==poi else old['constant']) and
                old['minimum']<=finite(s['value'])<=old['maximum'] and
                (not old['constant'] or s['value']==old['value']), 'source parameter/domain/fixed population differs')
            require(row['whole_state'][name]['value']==s['value'] and row['whole_state'][name]['constant']==s['constant'],
                    'profile and complete native state disagree')
        require(row['role']!='null' or row['state'][poi]['value']==0., 'null POI must remain zero')
        fit=row['fit']
        if free:
            optimizer.conditioning_check(fit,{'conditioning':'fit_observed_background','fit':optimizer.PROFILE_POLICY})
            floats=fit['floating_parameters'];const=fit['constant_parameters']
            require(len(floats)==len(free) and {x['name'] for x in floats}==free and
                    len({x['name'] for x in const})==len(const), 'raw fit parameter census differs')
            for p in floats:
                require(finite(p['value'])==row['state'][p['name']]['value'] and finite(p['error'])==row['errors'][p['name']]['error'] and p['error']>=0,
                        'raw fit values/errors differ')
            for name,s in row['state'].items():
                if s['constant']:require(next((p['value'] for p in const if p['name']==name),None)==s['value'],
                                         'raw fixed fitted source population differs')
            cov=fit['covariance'];require(len(cov)==len(free) and all(len(x)==len(free) for x in cov), 'complete fit covariance required')
            for i,r in enumerate(cov):
                for j,x in enumerate(r):require(finite(x)==cov[j][i] and (i!=j or x>=0), 'fit covariance symmetry/diagonal differs')
            raw=fit['raw_result'];require(Path(raw['basename']).name==raw['basename'] and
                raw['basename'].startswith('ravel_discovery_heldout_') and raw['basename'].endswith('.root') and
                raw['basename'] not in raw_names and type(raw['bytes']) is int and raw['bytes']>0 and
                type(raw['sha256']) is str and len(raw['sha256'])==64, 'complete unique raw RooFitResult identity required')
            raw_names.add(raw['basename'])
            require(abs(finite(fit['min_nll'])-finite(row['nll']))<=1e-8+1e-8*abs(row['nll']), 'saved fit and common evaluator minima differ')
        else:require(fit=={'performed':False,'reason':'no_floating_nuisance'}, 'unrequested empty fit')
        require(finite(row['common_nll'])==row['nll'] and set(row['means'])=={b['id'] for b in cell['law']['bins']} and
                all(finite(x)>0 for x in row['means'].values()), 'same NLL readback and full positive source means required')
    winners={role:min((r for r in rows if r['role']==role),key=lambda r:r['common_nll']) for role in ('free','null')}
    require(result['selected_profile_ids']=={role:r['id'] for role,r in winners.items()}, 'best-known role selection differs')
    expected=contrast(winners['free']['common_nll'],winners['null']['common_nll'],result['generating_nll'],
                      winners['free']['state'][poi]['value'],request)
    require(result['diagnostic']==expected, 'q0/common offset or discovery interpretation differs')
    return expected


def execute(ROOT,w,mc,data,nll,response,request,preparation,out,optimizer,graph_state,remaining):
    """Actual effects stay in the existing supervised native process only."""
    cell=next(x for x in response['recipe']['cells'] if x['id']==response['cell'])
    request=validate(request,cell,optimizer.PROFILE_POLICY)
    require(remaining>0 and response['kind']=='native-source-graph/v1', 'positive existing native budget and source graph required')
    require(preparation['kind']=='source-graph-asimov/v1' and preparation['status']=='passed' and
            preparation['request']==cell['expected_data'], 'same passed source generation required')
    out=Path(out);require(not out.exists(), 'fresh discovery journal required')
    initial=snapshot(w);coords=optimizer._state(w,response)
    model_state=graph_state.capture(w,mc);dataset=graph_state.data_census(data)
    global_policy=graph_state.global_source_semantics(
        {'definition':{'native_root_version':str(ROOT.gROOT.GetVersion())}},model_state,dataset)
    nonfit_observables=set(model_state['model_config']['observables'])|set().union(*(set(q.get('observables',[q['observable']] if 'observable' in q else [])) for q in cell['components']))
    require(all(row['constant'] or name in coords or name in nonfit_observables for name,row in initial.items()),
            'floating native variables outside source coordinates/declared observables refuse')
    counts=optimizer._counts(data,response['document']['bins']);globals_=optimizer._globals(w,response['document'])
    require(counts==preparation['dataset_counts'] and globals_==preparation['generated_globals'] and
            coords==preparation['final_state'] and float(data.weight())==1., 'actual generated experiment differs from preparation')
    poi=next(p['name'] for p in cell['law']['parameters'] if p['role']=='poi')
    end=time.monotonic()+remaining
    plans=[{'id':role+'_'+str(i),'role':role,'point':point,'status':'unissued'}
           for role in ('free','null') for i,point in enumerate(request['starts'][role])]
    result={'kind':KIND,'status':'running','request':request,'cell':response['cell'],
        'source_recipe_sha256':hashlib.sha256(json.dumps(response['recipe'],sort_keys=True,allow_nan=False).encode()).hexdigest(),
        'generation':deepcopy(preparation),'initial_whole_state':initial,'initial_coordinates':coords,
        'initial_model_state':model_state,'dataset':dataset,'global_source_semantics':global_policy,
        'native_pdf_nll_components':graph_state.components(mc,nll),
        'counts':counts,'globals':globals_,'dataset_weight':1.,'profiles':plans,
        'fit_calls':0,'readback_calls':0,'profile_policy':optimizer.PROFILE_POLICY,
        'native_nll_identity':'one ModelConfig PDF createNLL/data/globals/options object in this native process',
        'minimizer_internal_calls':'existing per-fit max_calls/max_iterations; Hesse/internal evaluations remain separately unknown',
        'coverage_qualified':False,'physics_validated':False}
    def save():out.write_text(json.dumps(optimizer._json_evidence(result),indent=2,sort_keys=True,allow_nan=False)+'\n')
    def budget():require(time.monotonic()<end, 'original native discovery wall exhausted')
    def identity():
        require(optimizer._counts(data,response['document']['bins'])==counts and
                optimizer._globals(w,response['document'])==globals_ and float(data.weight())==1. and
                graph_state.data_census(data)==dataset and graph_state.model_config(mc)==model_state['model_config'],
                'profile changed actual Asimov data/global observations')
    def reset(variables, model):
        # Each restoration is checked on its own return. The variable restoration
        # that follows must not repair, and so hide, a drift left by the first.
        graph_state.restore(w,mc,model)
        require(graph_state.capture(w,mc)==model, 'whole real/category/model population restoration differs')
        restore(w,variables)
        require(graph_state.capture(w,mc)==model, 'whole real/category/model population restoration differs')
    def readback():
        budget();require(result['readback_calls']<request['max_readbacks'], 'common NLL readback cap exhausted')
        result['readback_calls']+=1;value=float(nll.getVal());save();return finite(value)
    save()
    try:
        identity();result['generating_nll']=readback();save()
        for row in plans:
            budget();reset(initial,model_state);identity()
            for name,value in row['point'].items():w.var(name).setVal(float(exact(value)))
            w.var(poi).setConstant(row['role']=='null')
            start=optimizer._state(w,response);row['start_whole_state']=snapshot(w)
            row['status']='running';result['fit_calls']+=1;save()
            # _profile_fit saves the complete RooFitResult before scalar gates.
            row['fit']=optimizer._profile_fit(ROOT,nll,w,response,
                out.parent/('ravel_discovery_heldout_'+row['id']+'.root'),start)
            row['state']=optimizer._state(w,response);row['whole_state']=snapshot(w)
            row['model_state']=graph_state.capture(w,mc)
            row['errors']=optimizer._errors(w,row['state']);identity();row['nll']=readback()
            row['integrals']=optimizer.source_graph_integrals(w,response)
            row['means']={b['id']:finite(w.function('ravel_mean_'+str(i)).getVal())
                          for i,b in enumerate(response['document']['bins'])}
            save();require(all(x>0 for x in row['means'].values()), 'fitted source total means must be positive')
            for name,old in coords.items():
                now=row['state'][name]
                require(now['minimum']==old['minimum'] and now['maximum']==old['maximum'] and
                    now['constant']==(row['role']=='null' if name==poi else old['constant']) and
                    old['minimum']<=now['value']<=old['maximum'] and
                    (not old['constant'] or now['value']==old['value']), 'fit changed original coordinate/domain/fixed population')
            require(row['model_state']['categories']==model_state['categories'] and
                    all(row['whole_state'][name]==old for name,old in initial.items() if name not in coords),
                    'fit changed source categories or non-profile native state')
            if row['role']=='null':require(row['state'][poi]['value']==0., 'null profile moved fixed POI')
            free={n for n,s in row['state'].items() if not s['constant']}
            if free:
                optimizer.conditioning_check(row['fit'],{'conditioning':'fit_observed_background','fit':optimizer.PROFILE_POLICY})
                require({p['name'] for p in row['fit']['floating_parameters']}==free and
                    len(row['fit']['floating_parameters'])==len(free), 'full fitted floating population differs')
            else:require(row['fit']=={'performed':False,'reason':'no_floating_nuisance'}, 'unrequested empty fit')
            # Reevaluate on the same NLL after a complete state reset. Offsets
            # are not reconstructed from independent Combine deltaNLL trees.
            reset(initial,model_state);reset(row['whole_state'],row['model_state']);identity()
            row['common_nll']=readback();require(row['common_nll']==row['nll'], 'common NLL state readback differs')
            row['status']='passed';save()
        winners={role:min((r for r in plans if r['role']==role),key=lambda r:r['common_nll']) for role in ('free','null')}
        result['selected_profile_ids']={role:r['id'] for role,r in winners.items()}
        result['diagnostic']=contrast(winners['free']['common_nll'],winners['null']['common_nll'],
            result['generating_nll'],winners['free']['state'][poi]['value'],request)
        result['status']='passed';reset(initial,model_state);identity();result['ending_whole_state']=snapshot(w)
        result['ending_model_state']=graph_state.capture(w,mc);save()
        validate_delivery(result,response,request,optimizer)
        return result
    except BaseException as exc:
        for row in plans:
            if row['status']=='running':row['status']='failed';row['error']={'type':type(exc).__name__,'message':str(exc)}
        result['status']='failed';result['error']={'type':type(exc).__name__,'message':str(exc)};save();raise
