"""Explicit background Asimov construction and bounded native conditioning.

No ROOT import at module load. ``prepare`` receives the already source-bound
workspace/NLL and ROOT facade from native_likelihood's existing native worker.
This route is an asymptotic expected CLs projection, never an observed limit.
"""
from fractions import Fraction
from copy import deepcopy
import json
import hashlib
import math
from statistics import NormalDist
from pathlib import Path

KIND = 'regional-background-asimov/v1'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def keys(x, fields, label):
    require(type(x) is dict and set(x) == set(fields), label+' fields differ')


def number(x):
    require(type(x) is str, 'exact rational source number required')
    q = Fraction(x)
    require(math.isfinite(float(q)), 'finite binary64 source number required')
    return q


def validate_request(request, parameters, auxiliary, source_ids):
    """No observed-law admission is weakened by declaring an expected route."""
    keys(request, ('kind','conditioning','point','source','statement','fit')+(('crossing',) if 'crossing' in request else ()), 'expected data')
    crossing_policy({'expected_data':request})
    require(request['kind']==KIND and request['conditioning'] in ('supplied_nominal','fit_observed_background'), 'explicit nominal or observed background conditioning required')
    require(request['source'] in source_ids and isinstance(request['statement'],str) and request['statement'].strip(), 'source-bound generating-state rationale required')
    coords = [p['name'] for p in parameters]+['ravel_aux_'+str(i) for i in range(len(auxiliary['names']))]
    keys(request['point'], coords, 'complete physical/whitened generating or fit-start state')
    q = {n:number(v) for n,v in request['point'].items()}
    poi = next(p for p in parameters if p['role']=='poi')
    require(number(poi['bounds'][0])==0 and q[poi['name']]==0, 'expected upper limits require background strength zero and lower bound zero')
    for p in parameters:
        require(number(p['bounds'][0])<=q[p['name']]<=number(p['bounds'][1]), 'expected state outside physical domain')
        require(not p['fixed'] or q[p['name']]==number(p['initial']), 'expected state changed fixed physical value')
    for i,b in enumerate(auxiliary['eta_bounds']):
        require(number(b[0])<=q['ravel_aux_'+str(i)]<=number(b[1]), 'expected state outside auxiliary domain')
    if request['conditioning']=='supplied_nominal':
        require(request['fit'] is None, 'nominal expectation cannot carry hidden conditioning fit')
    else:
        f=request['fit']; keys(f,('strategy','tolerance','max_calls','max_iterations','max_edm'), 'conditioning fit')
        require(type(f['strategy']) is int and f['strategy'] in (0,1,2), 'bounded Minuit2 strategy required')
        for n in ('max_calls','max_iterations'):
            require(type(f[n]) is int and 1<=f[n]<=100000, 'bounded conditioning minimizer calls/iterations required')
        require(number(f['tolerance'])>0 and number(f['max_edm'])>0, 'positive conditioning tolerance/EDM gate required')
    return request


def validate(document):
    d=document; r=d['expected_data']; pars=d['parameters']; aux=d['auxiliary']
    validate_request(r,pars,aux,{x['id'] for x in d['sources']})
    nominal=r['conditioning']=='supplied_nominal'
    require(all(b['observed'] is None for b in d['bins']) if nominal else all(type(b['observed']) is int and b['observed']>=0 for b in d['bins']), 'nominal has no observed data; conditional route requires actual complete integer counts')
    # Constructive sufficient family: b(theta)+mu*s(theta), all contributions
    # nonnegative throughout declared rectangular physical/eta domain.
    poi=next(p['name'] for p in pars if p['role']=='poi')
    bounds={p['name']:tuple(map(number,p['bounds'])) for p in pars}
    for i,name in enumerate(aux['names']):
        lo=hi=number(aux['observed'][i])
        for j,c in enumerate(aux['factor'][i]):
            a,b=map(number,aux['eta_bounds'][j]); v=number(c)
            lo+=min(v*a,v*b);hi+=max(v*a,v*b)
        bounds[name]=(lo,hi)
    signal=False
    for t in d['terms']:
        power=t['powers'].get(poi,0)
        require(power in (0,1), 'nonlinear/interfering strength needs a separate interval construction')
        require(not ('shape' in t and t['shape']['slope_parameter']==poi), 'POI-dependent shape is not a monotone rate upper-limit family')
        co=list(map(number,t['coefficients']))
        require(all(x>=0 for x in co), 'signed mean pieces do not imply monotone strength limits')
        for name,p in t['powers'].items():
            require(p%2==0 or bounds[name][0]>=0, 'signed factor domain cannot certify nonnegative signal/background')
        if power:
            require(t['basis']=='bsm' and 'shape' not in t, 'only explicit nonnegative linear BSM strength supported')
            signal = signal or any(v>0 for v in co)
        else:
            require(t['basis'] in ('background','sm'), 'every non-background contribution must carry the strength')
    require(signal, 'nonzero source signal family required')
    return r


def validate_fit(document, fit):
    validate(document)
    poi=next(p for p in document['parameters'] if p['role']=='poi')
    require(fit['method']=='AsymptoticLimits' and fit['data']=='asimov_background' and fit['poi']==poi['name'] and list(map(number,fit['domain']))==list(map(number,poi['bounds'])), 'expected construction requires exact AsymptoticLimits background strength/domain')
    require(fit['points'] is None and 'saved_fit' not in fit and 'absolute_nll' not in fit, 'expected CLs route is separate from saved/profile fits')


def _finite(x, label):
    require(type(x) in (int,float) and math.isfinite(x), 'nonfinite '+label)
    return float(x)


def _state(w, response):
    result={}
    for name in response['coordinates']:
        v=w.var(name);require(bool(v), 'missing expected coordinate '+name)
        result[name]={'value':_finite(v.getVal(),name),'minimum':_finite(v.getMin(),name),'maximum':_finite(v.getMax(),name),'constant':bool(v.isConstant())}
    return result


def _counts(data, bins):
    require(int(data.numEntries())==1, 'one complete count vector required')
    row=data.get(0);require(float(data.weight())==1., 'unit dataset weight required');result={}
    for b in bins:
        v=row.find('n_obs_bin'+b['id']); require(bool(v),'missing observed count')
        result[b['id']]=_finite(v.getVal(),'count')
    return result


def _globals(w,d):
    result={}
    for i in range(len(d['auxiliary']['names'])):
        name='ravel_aux_'+str(i)+'_In';v=w.var(name)
        require(bool(v) and not v.hasMin() and not v.hasMax() and v.isConstant(), 'full-real constant Gaussian observation required')
        result[name]={'value':_finite(v.getVal(),'auxiliary observation'),'constant':True,'has_min':False,'has_max':False}
    return result


def conditioning_check(row, request):
    require(type(row) is dict,'complete conditioning result required')
    if request['conditioning']=='supplied_nominal':
        require(row=={'performed':False,'reason':'supplied_nominal'},'nominal data generation performed an unrequested fit')
    else:
        require(row.get('performed') is True and row.get('algorithm')=='RooMinimizer/Minuit2/Migrad' and row.get('migrad_status')==0 and row.get('hesse_status')==0 and row.get('status')==0 and row.get('cov_qual')==3 and row.get('invalid_nll')==0, 'conditioning optimizer diagnostics failed')
        require(0<=_finite(row.get('edm'),'EDM')<=float(number(request['fit']['max_edm'])),'conditioning EDM gate failed')
        _finite(row.get('min_nll'),'conditioning minimum')
        require(type(row.get('status_history')) is list and row['status_history'] and all(x['code']==0 for x in row['status_history']), 'conditioning optimizer history not clean')


def _json_evidence(value):
    # Retain a literal nonfinite native return without generating invalid JSON.
    # Such a value can never pass the finite scalar/array admission below.
    if type(value) is float and not math.isfinite(value):return {'nonfinite_native_float':repr(value)}
    if type(value) is dict:return {k:_json_evidence(v) for k,v in value.items()}
    if type(value) is list:return [_json_evidence(v) for v in value]
    return value


def prepare(ROOT,w,mc,data,nll,response,out):
    """Preserved regional entry: exact old source/background/endpoint policy."""
    return shared_native_prepare(ROOT,w,mc,data,nll,response,out,validate(response['document']))


def shared_native_prepare(ROOT,w,mc,data,nll,response,out,request,*,graph_mode=False):
    """Actual native operation; called only inside the supervised native worker.

    Original ROOT file is never updated. The caller saves the resulting workspace
    to a fresh path after this operation and preserves this journal on failure.
    """
    d=response['document'];r=deepcopy(request);out=Path(out)
    require(not out.exists(),'fresh Asimov preparation journal required')
    def save():
        out.write_text(json.dumps(_json_evidence(result),indent=2,sort_keys=True,allow_nan=False)+'\n')
    original=_state(w,response);original_counts=_counts(data,d['bins']);original_globals=_globals(w,d)
    result={'kind':('source-graph-asimov/v1' if graph_mode else KIND),'status':'preparing','conditioning':r['conditioning'],'request':r,'original_state':original,'original_counts':original_counts,'original_globals':original_globals,'dataset_name':'data_obs','data_semantics':('generated_source_graph_Asimov_not_observed' if graph_mode else 'generated_background_Asimov_not_observed'),'observed_endpoint':None,'coverage_qualified':False,'optimizer_globality_qualified':False}
    if graph_mode:
        result['initial_dataset_counts']=deepcopy(original_counts)
        result['original_counts']=deepcopy(response['source_observations'])
        result['build_observation_semantics']=response['build_observation_semantics']
        result['generating_request']=deepcopy(request)
        result['source_graph_cell']=response['cell']
        result['numerical_equivalence_qualified']=False
        result['expected_data_qualified']=False
    save()
    try:
        for name,value in r['point'].items():w.var(name).setVal(float(number(value)))
        poi=next(p['name'] for p in d['parameters'] if p['role']=='poi')
        w.var(poi).setConstant(True)
        if r['conditioning']!='supplied_nominal':
            f=r['fit'];m=ROOT.RooMinimizer(nll)
            m.setErrorLevel(.5);m.setStrategy(f['strategy']);m.setEps(float(number(f['tolerance'])))
            m.setMaxFunctionCalls(f['max_calls']);m.setMaxIterations(f['max_iterations'])
            a=int(m.minimize('Minuit2','Migrad'));b=int(m.hesse());fr=m.save()
            require(bool(fr),'conditioning fit result absent')
            target=ROOT.TFile.Open(str(out.with_suffix('.fit.root')),'RECREATE');require(bool(target),'conditioning result file absent')
            target.WriteTObject(fr,'conditioning_fit');target.Close() # raw ROOT before scalar checks/JSON
            history=[{'label':str(fr.statusLabelHistory(i)),'code':int(fr.statusCodeHistory(i))} for i in range(fr.numStatusHistory())]
            result['conditioning_fit']={'performed':True,'algorithm':'RooMinimizer/Minuit2/Migrad','migrad_status':a,'hesse_status':b,'status':int(fr.status()),'cov_qual':int(fr.covQual()),'edm':float(fr.edm()),'min_nll':float(fr.minNll()),'invalid_nll':int(fr.numInvalidNLL()),'status_history':history,'floating_parameters':[{ 'name':v.GetName(),'value':float(v.getVal()),'error':float(v.getError())} for v in fr.floatParsFinal()],'constant_parameters':[{ 'name':v.GetName(),'value':float(v.getVal())} for v in fr.constPars()],'covariance':[[float(fr.covarianceMatrix()[i][j]) for j in range(fr.floatParsFinal().getSize())] for i in range(fr.floatParsFinal().getSize())]}
            raw_fit=out.with_suffix('.fit.root');result['conditioning_fit']['raw_result']={'basename':raw_fit.name,'sha256':hashlib.sha256(raw_fit.read_bytes()).hexdigest(),'bytes':raw_fit.stat().st_size}
            result['conditioned_state']=_state(w,response);result['conditioning_counts']=_counts(data,d['bins']);result['conditioning_globals']=_globals(w,d);save()
        else:result['conditioning_fit']={'performed':False,'reason':'supplied_nominal'}
        checked=deepcopy(r)
        if graph_mode and checked['conditioning']=='fit_observed_at_fixed_poi': checked['conditioning']='fit_observed_background'
        conditioning_check(result['conditioning_fit'],checked)
        if r['conditioning']!='supplied_nominal':
            fit=result['conditioning_fit']
            for row in fit['floating_parameters']:
                _finite(row['value'],'conditioning parameter');require(_finite(row['error'],'conditioning error')>=0,'negative conditioning error')
            for row in fit['constant_parameters']:_finite(row['value'],'conditioning constant')
            for row in fit['covariance']:
                for value in row:_finite(value,'conditioning covariance')
        if r['conditioning']!='supplied_nominal':
            require(result['conditioning_counts']==original_counts and result['conditioning_globals']==original_globals,'conditioning fit changed observations/globals')
            if graph_mode:
                for name,row in original.items():
                    if row['constant']: require(result['conditioned_state'][name]==row,'conditioning changed fixed original coordinate')
        require(w.var(poi).getVal()==float(number(r['point'][poi]) if graph_mode else 0),'conditioning changed declared generating POI')
        w.var(poi).setConstant(original[poi]['constant'])
        result['generating_state']=_state(w,response)
        if graph_mode:
            result['integration_readback']=source_graph_integrals(w,response)
        means={}
        for i,b in enumerate(d['bins']):
            fn=w.function('ravel_mean_'+str(i));require(bool(fn),'source mean missing')
            raw=float(fn.getVal())
            if graph_mode:
                result.setdefault('native_mean_returns',{})[b['id']]=raw;save()
            v=_finite(raw,'Asimov mean');require(v>0,'strictly positive Asimov means required')
            means[b['id']]=v
        if graph_mode:
            domains={}
            for b in d['bins']:
                var=w.var('n_obs_bin'+b['id']);require(bool(var),'original native count observable absent')
                domains[b['id']]={'has_min':bool(var.hasMin()),'has_max':bool(var.hasMax()),'minimum':_finite(var.getMin(),'count minimum') if var.hasMin() else None,'maximum':_finite(var.getMax(),'count maximum') if var.hasMax() else None}
                domain=domains[b['id']]
                require((not domain['has_min'] or means[b['id']]>=domain['minimum']) and (not domain['has_max'] or means[b['id']]<=domain['maximum']),'generated count outside original native observable domain')
            result['count_domains']=domains
        result['generated_counts']=means;save() # retain native returns before dataset mutation/checks
        for i in range(len(d['auxiliary']['names'])):
            w.var('ravel_aux_'+str(i)+'_In').setVal(w.var('ravel_aux_'+str(i)).getVal())
        for b in d['bins']:w.var('n_obs_bin'+b['id']).setVal(means[b['id']])
        data.reset();data.add(mc.GetObservables())
        result['dataset_counts']=_counts(data,d['bins']);result['dataset_weight']=float(data.weight())
        result['generated_globals']=_globals(w,d);result['final_state']=_state(w,response)
        require(result['dataset_counts']==means and result['final_state']==result['generating_state'],'native Asimov count/state readback differs')
        result['status']='passed';save();return result
    except BaseException as exc:
        result['status']='failed';result['error']={'type':type(exc).__name__,'message':str(exc)};save();raise


def validate_delivery(result,response):
    from ravel.physics import statistical_construction as regional
    d=response['document'];r=validate(d)
    require(result.get('kind')==KIND and result.get('status')=='passed' and result.get('request')==r and result.get('conditioning')==r['conditioning'], 'complete current Asimov preparation required')
    require(result.get('data_semantics')=='generated_background_Asimov_not_observed' and result.get('dataset_name')=='data_obs' and result.get('observed_endpoint') is None and result.get('coverage_qualified') is False and result.get('optimizer_globality_qualified') is False,'expected/observed or statistical qualification claims changed')
    require(result.get('original_counts')=={b['id']:(0. if b['observed'] is None else float(b['observed'])) for b in d['bins']},'conditioning input counts differ')
    conditioning_check(result.get('conditioning_fit'),r)
    initial=result.get('original_state',{});regional.native_witness(response,initial)
    require({n:row['value'] for n,row in initial.items()}=={n:float(number(v)) for n,v in regional.initial_point(d).items()},'original native parameter state differs from source')
    state=result.get('generating_state',{})
    means=regional.native_witness(response,state)
    require(result.get('final_state')==state and state[next(p['name'] for p in d['parameters'] if p['role']=='poi')]['value']==0.,'background generating state changed')
    if r['conditioning']=='supplied_nominal':
        require({k:v['value'] for k,v in state.items()}=={k:float(number(v)) for k,v in r['point'].items()},'nominal generating state differs')
    if r['conditioning']=='fit_observed_background':
        poi=next(p['name'] for p in d['parameters'] if p['role']=='poi')
        conditioned={n:dict(v) for n,v in state.items()};conditioned[poi]['constant']=True
        require(result.get('conditioning_counts')==result['original_counts'] and result.get('conditioning_globals')==result['original_globals'],'conditioning original count/auxiliary law changed')
        require(result.get('conditioned_state')==conditioned,'retained conditioning state differs from generating point')
        fit=result['conditioning_fit'];free={n for n,v in conditioned.items() if not v['constant']}
        floats=fit.get('floating_parameters',[]);const=fit.get('constant_parameters',[])
        require(len(floats)==len(free) and {x['name'] for x in floats}==free,'conditioning floating population differs')
        for x in floats:
            require(_finite(x['value'],'fitted value')==state[x['name']]['value'] and _finite(x['error'],'fit error')>=0,'fitted parameter/state mismatch')
        require(len({x['name'] for x in const})==len(const) and all(next((x['value'] for x in const if x['name']==n),None)==v['value'] for n,v in conditioned.items() if v['constant']),'fixed conditioning parameter census differs')
        cov=fit.get('covariance',[]);require(len(cov)==len(floats) and all(type(x) is list and len(x)==len(floats) for x in cov),'conditioning covariance geometry differs')
        for i,row in enumerate(cov):
            for j,v in enumerate(row):require(_finite(v,'fit covariance')==cov[j][i],'fit covariance symmetry differs')
    counts=result.get('generated_counts',{})
    require(set(counts)=={b['id'] for b in d['bins']} and counts==result.get('dataset_counts') and result.get('dataset_weight')==1.,'generated count population/readback differs')
    for name,source in means.items():
        b=response['functions'][name]['bin'];v=_finite(counts[b],'Asimov count')
        require(v>0 and abs(v-source)<=1e-10+1e-8*abs(source),'native Asimov count differs from supplied source law')
    globals_={'ravel_aux_'+str(i)+'_In':{'value':state['ravel_aux_'+str(i)]['value'],'constant':True,'has_min':False,'has_max':False} for i in range(len(d['auxiliary']['names']))}
    require(result.get('generated_globals')==globals_,'Asimov auxiliary expectations/support differ')
    require(result.get('original_globals')=={n:{**v,'value':0.} for n,v in globals_.items()},'original supplied Gaussian measurement changed')
    return result


def observation_expectation(result):
    return {'counts':result['generated_counts'],'dataset_weight':1.0,'auxiliary':{n:{'value':v['value'],'constant':True} for n,v in result['generated_globals'].items()}}


def endpoint_plan(inference,fit):
    require(type(inference.get('passed')) is bool,'complete native expected rows required')
    require('observed' not in inference.get('quantiles',{}),'observed endpoint forbidden for expected-only route')
    rows=inference.get('rows',[])
    require(len(rows)==5 and all(abs(row['quantileExpected']-p)<1e-6 for row,p in zip(rows,QUANTILES)), 'complete ordered expected quantile census required')
    lo,hi=map(lambda x:float(number(x)),fit['domain']);plan=[]
    previous=lo
    for row,p in zip(rows,QUANTILES):
        v=_finite(row['limit'],'expected CLs endpoint')
        require(previous<v<hi,'expected endpoint reaches declared physical domain or is unordered; unresolved, no automatic range extension')
        previous=v
        # Released crossing half-width, plus the source's float32 return rounding.
        # This defines an engineering bracket, NOT an error or confidence enclosure.
        radius=max(.0005,.005*v)+2**-23*abs(v)
        left=max(lo,v-radius);right=min(hi,v+radius)
        require(left<v<right,'no representable endpoint bracket inside source domain')
        normal=NormalDist();target=(normal.inv_cdf(p)+normal.inv_cdf(1-.05*p))**2
        plan.append({'quantile':p,'reported_endpoint':v,'target_q':target,'radius':radius,'points':{'lower':left,'reported':v,'upper':right}})
    return plan


QUANTILES=(.025,.16,.5,.84,.975)
CROSSING_KIND='regional-expected-crossings/v1'
PROFILE_POLICY={'strategy':1,'tolerance':'1/100000','max_calls':50000,'max_iterations':10000,'max_edm':'1/100000'}


def _restore(w,state):
    for name,row in state.items():
        v=w.var(name)
        require(v.getMin()==row['minimum'] and v.getMax()==row['maximum'],'profile changed parameter bounds')
        v.setVal(row['value']);v.setConstant(row['constant'])


def _errors(w,state):
    result={}
    for name in state:
        v=w.var(name)
        result[name]={'has_error':bool(v.hasError()),'error':_finite(v.getError(),'Minuit error'),
            'has_asymmetric_error':bool(v.hasAsymError()),'low':_finite(v.getAsymErrorLo(),'low error'),'high':_finite(v.getAsymErrorHi(),'high error')}
    return result


def _restore_errors(w,errors):
    for name,e in errors.items():
        v=w.var(name)
        if e['has_error']:v.setError(e['error'])
        else:v.removeError()
        if e['has_asymmetric_error']:v.setAsymError(e['low'],e['high'])
        else:v.removeAsymError()


def _profile_fit(ROOT,nll,w,response,path,state):
    """A declared bounded fit, no warm starts or fit-status inference from logs."""
    free={n for n,row in state.items() if not row['constant']}
    if not free:return {'performed':False,'reason':'no_floating_nuisance'}
    f=PROFILE_POLICY;m=ROOT.RooMinimizer(nll)
    m.setErrorLevel(.5);m.setStrategy(f['strategy']);m.setEps(float(number(f['tolerance'])))
    m.setMaxFunctionCalls(f['max_calls']);m.setMaxIterations(f['max_iterations'])
    a=int(m.minimize('Minuit2','Migrad'));b=int(m.hesse());fr=m.save()
    require(bool(fr),'profile fit result absent')
    require(not path.exists(),'fresh raw profile result required')
    target=ROOT.TFile.Open(str(path),'RECREATE');require(bool(target),'profile result file absent')
    target.WriteTObject(fr,'profile_fit');target.Close()  # complete raw result BEFORE checks
    return {'performed':True,'algorithm':'RooMinimizer/Minuit2/Migrad','migrad_status':a,'hesse_status':b,
        'status':int(fr.status()),'cov_qual':int(fr.covQual()),'edm':float(fr.edm()),'min_nll':float(fr.minNll()),
        'invalid_nll':int(fr.numInvalidNLL()),'status_history':[{'label':str(fr.statusLabelHistory(i)),'code':int(fr.statusCodeHistory(i))} for i in range(fr.numStatusHistory())],
        'floating_parameters':[{'name':v.GetName(),'value':float(v.getVal()),'error':float(v.getError())} for v in fr.floatParsFinal()],
        'constant_parameters':[{'name':v.GetName(),'value':float(v.getVal())} for v in fr.constPars()],
        'covariance':[[float(fr.covarianceMatrix()[i][j]) for j in range(fr.floatParsFinal().getSize())] for i in range(fr.floatParsFinal().getSize())],
        'raw_result':{'basename':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}}


def _profile_check(row,initial,poi,mu):
    state=row['state'];keys(state,initial,'profile state')
    for name,s in state.items():
        old=initial[name];keys(s,old,'profile coordinate')
        v=_finite(s['value'],'profile coordinate')
        require(s['minimum']==old['minimum'] and s['maximum']==old['maximum'] and s['constant']==(True if name==poi else old['constant']), 'profile range/fixed state changed')
        require(old['minimum']<=v<=old['maximum'],'profile coordinate outside declared domain')
        require(not old['constant'] or v==old['value'],'profile changed fixed source parameter')
    require(state[poi]['value']==mu,'fixed profile POI changed')
    free={n for n,s in state.items() if not s['constant']};fit=row['fit']
    if not free:
        require(fit=={'performed':False,'reason':'no_floating_nuisance'},'unrequested profile fit')
    else:
        conditioning_check(fit,{'conditioning':'fit_observed_background','fit':PROFILE_POLICY})
        floats=fit.get('floating_parameters',[]);const=fit.get('constant_parameters',[])
        require(len(floats)==len(free) and {x['name'] for x in floats}==free,'profile floating population differs')
        require(len({x['name'] for x in const})==len(const),'duplicate profile constant')
        for x in const:_finite(x['value'],'profile constant')
        for name,s in state.items():
            if s['constant']:require(next((x['value'] for x in const if x['name']==name),None)==s['value'],'profile fixed population differs')
        for x in floats:
            require(_finite(x['value'],'profile fit coordinate')==state[x['name']]['value'] and _finite(x['error'],'profile error')>=0,'profile fitted state differs')
        cov=fit.get('covariance',[])
        require(len(cov)==len(free) and all(type(x) is list and len(x)==len(free) for x in cov),'profile covariance geometry differs')
        for i,r in enumerate(cov):
            for j,v in enumerate(r):require(_finite(v,'profile covariance')==cov[j][i] and (i!=j or v>=0),'profile covariance symmetry/diagonal differs')
        require(abs(fit['min_nll']-_finite(row['nll'],'profile NLL'))<=1e-8+1e-8*abs(row['nll']),'profile saved minimum/NLL differs')
        raw=fit.get('raw_result',{})
        require(type(raw.get('basename')) is str and Path(raw['basename']).name==raw['basename'] and raw['basename'].startswith('ravel_expected_profile_') and raw['basename'].endswith('.root') and type(raw.get('bytes')) is int and raw['bytes']>0 and type(raw.get('sha256')) is str and len(raw['sha256'])==64,'complete raw profile fit pin required')


def crossing_policy(document):
    request=document['expected_data'].get('crossing',{'mode':'verify_only','max_profile_evaluations':15})
    keys(request,('mode','max_profile_evaluations'),'crossing policy')
    require(request['mode'] in ('verify_only','verify_or_refine'),'explicit crossing mode required')
    cap=request['max_profile_evaluations']
    require(type(cap) is int and (cap==15 if request['mode']=='verify_only' else 16<=cap<=200),'bounded total profile-point budget required')
    return dict(request)


def _resolution(mu):
    return max(.0005,.005*abs(mu))+2**-23*abs(mu)


def _margin(nll,nll0):
    # 32 conservative binary64 ulps plus a fixed engineering separation. This
    # is neither an optimizer error bound nor a rigorous rounding enclosure.
    return max(1e-6,max(abs(nll),abs(nll0),1.)*2**-47)


def _bracket_ok(left,right,target,nll0):
    return 2*(left['nll']-nll0)<target-_margin(left['nll'],nll0) and 2*(right['nll']-nll0)>target+_margin(right['nll'],nll0)


def qualify_crossings(ROOT,w,mc,data,nll,response,request,out):
    """Bounded native verification/refinement; all original endpoints survive.

    Native worker uses only stdlib plus its supplied ROOT facade. The host also
    recomputes each contrast from the complete source Poisson/Gaussian law.
    """
    keys(request,('inference','fit','preparation'),'crossing request')
    d=response['document'];validate_fit(d,request['fit']);policy=crossing_policy(d)
    prep=request['preparation'];out=Path(out)
    require(not out.exists(),'fresh crossing journal required')
    initial=_state(w,response);counts=_counts(data,d['bins']);globals_=_globals(w,d)
    errors=_errors(w,initial)
    require(initial==prep['generating_state'] and counts==prep['generated_counts'] and globals_==prep['generated_globals'],'crossing workspace differs from prepared Asimov')
    plan=endpoint_plan(request['inference'],request['fit']);poi=request['fit']['poi']
    result={'kind':CROSSING_KIND,'status':'running','policy':PROFILE_POLICY,'crossing_policy':policy,'plan':plan,'initial_state':initial,'counts':counts,'globals':globals_,
        'reference':{},'profiles':[],'solutions':[],'original_crossings':[],'initial_errors':errors,
        'optimizer_globality_qualified':False,'coverage_qualified':False,'error_enclosure_qualified':False}
    def save():out.write_text(json.dumps(_json_evidence(result),sort_keys=True,indent=2,allow_nan=False)+'\n')
    save()
    def observe(mu,quantile,role):
        require(len(result['profiles'])<policy['max_profile_evaluations'],'declared profile-point budget exhausted; unresolved')
        _restore(w,initial)
        _restore_errors(w,errors)
        w.var(poi).setVal(mu);w.var(poi).setConstant(True);start=_state(w,response)
        idx=len(result['profiles'])
        row={'index':idx,'quantile':quantile,'role':role,'mu':mu,'start_state':start,'start_errors':_errors(w,initial),
             'fit':_profile_fit(ROOT,nll,w,response,out.parent/('ravel_expected_profile_'+str(idx)+'.root'),start)}
        row.update(state=_state(w,response),nll=float(nll.getVal()),counts=_counts(data,d['bins']),globals=_globals(w,d))
        result['profiles'].append(row);save()
        _profile_check(row,initial,poi,mu);_finite(row['nll'],'profile NLL')
        require(row['counts']==counts and row['globals']==globals_,'profile changed observations/global observables')
        return idx
    try:
        result['reference']={'state':_state(w,response),'nll':float(nll.getVal()),'basis':'source_Asimov_termwise_minimum'};save()
        nll0=_finite(result['reference']['nll'],'Asimov reference NLL')
        # Complete original five-quantile diagnostic precedes any repair.
        for item in plan:
            for role,mu in item['points'].items():observe(mu,item['quantile'],role)
        for i,item in enumerate(plan):
            left=result['profiles'][3*i];right=result['profiles'][3*i+2]
            passed=_bracket_ok(left,right,item['target_q'],nll0)
            result['original_crossings'].append({'quantile':item['quantile'],'passed':passed,
                'lower_index':3*i,'reported_index':3*i+1,'upper_index':3*i+2})
        save()
        for i,item in enumerate(plan):
            p=item['quantile'];target=item['target_q'];original=result['original_crossings'][i]
            if original['passed']:
                solution={'quantile':p,'source':'verified_Combine_endpoint','endpoint':item['reported_endpoint'],
                          'lower_index':3*i,'upper_index':3*i+2}
            else:
                require(policy['mode']=='verify_or_refine','native expected endpoint is unbracketed; unresolved under verify-only contract')
                # Reference at physical zero has q=0 exactly by the admitted
                # Asimov law; upper endpoint must ACTUALLY cross, even at rMax.
                lower=None;lo=0.;hi=float(number(request['fit']['domain'][1]))
                upper=observe(hi,p,'refinement_domain_upper')
                require(2*(result['profiles'][upper]['nll']-nll0)>target+_margin(result['profiles'][upper]['nll'],nll0),'no confidence crossing in original physical domain; unresolved')
                while True:
                    mid=lo+(hi-lo)/2
                    require(lo<mid<hi,'refinement grid exhausted binary64 representability; unresolved')
                    if lower is not None and (hi-lo)/2<=_resolution(mid) and _bracket_ok(result['profiles'][lower],result['profiles'][upper],target,nll0):break
                    index=observe(mid,p,'refinement_bisection');row=result['profiles'][index];q=2*(row['nll']-nll0)
                    margin=_margin(row['nll'],nll0)
                    if q<target-margin:lo=mid;lower=index
                    elif q>target+margin:hi=mid;upper=index
                    else:
                        # Do not treat near-equality as a proven crossing. Take
                        # two distinct nearby profiles with strict opposite signs.
                        radius=min(_resolution(mid)/2,(hi-lo)/4)
                        a=observe(mid-radius,p,'refinement_near_lower');b=observe(mid+radius,p,'refinement_near_upper')
                        require(_bracket_ok(result['profiles'][a],result['profiles'][b],target,nll0),'unresolved numerical threshold equality')
                        lo=mid-radius;hi=mid+radius;lower=a;upper=b
                solution={'quantile':p,'source':'bounded_native_profile_refinement','endpoint':lo+(hi-lo)/2,
                          'lower_index':lower,'upper_index':upper}
            result['solutions'].append(solution);save()
        _restore(w,initial)
        _restore_errors(w,errors)
        result['final_errors']=_errors(w,initial)
        result['final_state']=_state(w,response);result['final_nll']=float(nll.getVal());save()
        validate_crossings(result,response,request,source_check=False)
        result['status']='passed';save();return result
    except BaseException as exc:
        result['status']='failed';result['error']={'type':type(exc).__name__,'message':str(exc)};save();raise


def _poisson_deviance(mean,count):
    require(mean>0 and count>0,'positive Asimov/count means required')
    x=(mean-count)/count
    if abs(x)<.01:
        delta=math.fsum(((-1.)**k)*x**k/k for k in range(2,18))
    else:delta=x-math.log(mean/count)
    return 2*count*delta


def validate_crossings(result,response,request,source_check=True):
    if source_check:
        from ravel.physics import statistical_construction as regional
        prep=validate_delivery(request['preparation'],response)
    else:prep=request['preparation']  # source checking also occurs independently on the host
    plan=endpoint_plan(request['inference'],request['fit']);initial=prep['generating_state'];poi=request['fit']['poi'];policy=crossing_policy(response['document'])
    require(result.get('kind')==CROSSING_KIND and result.get('status') in ('running','passed') and result.get('policy')==PROFILE_POLICY and result.get('crossing_policy')==policy and result.get('plan')==plan,'exact crossing plan/policy required')
    require(all(result.get(k) is False for k in ('optimizer_globality_qualified','coverage_qualified','error_enclosure_qualified')),'crossing check cannot confer globality, coverage or an error enclosure')
    require(result.get('initial_state')==initial and result.get('final_state')==initial and result.get('counts')==prep['generated_counts'] and result.get('globals')==prep['generated_globals'],'complete Asimov crossing state/data/restore differs')
    errors=result.get('initial_errors',{});keys(errors,initial,'initial Minuit step errors')
    for value in errors.values():
        keys(value,('has_error','error','has_asymmetric_error','low','high'),'Minuit errors')
        require(type(value['has_error']) is bool and type(value['has_asymmetric_error']) is bool,'error presence flags required')
        for k in ('error','low','high'):_finite(value[k],'Minuit step error')
        require(value['error']>=0 and (value['has_error'] or value['error']==0) and value['low']<=0<=value['high'] and (value['has_asymmetric_error'] or value['low']==value['high']==0),'error presence/value semantics differ')
    require(result.get('final_errors')==errors,'restored Minuit step errors differ')
    ref=result.get('reference',{});require(ref.get('state')==initial and ref.get('basis')=='source_Asimov_termwise_minimum','source Asimov minimum reference required')
    nll0=_finite(ref.get('nll'),'reference NLL');require(_finite(result.get('final_nll'),'restored NLL')==nll0,'restored Asimov NLL changed')
    profiles=result.get('profiles',[]);require(15<=len(profiles)<=policy['max_profile_evaluations'],'complete bounded profile returns required')
    original_specs=[(item['quantile'],role,mu) for item in plan for role,mu in item['points'].items()]
    values=[]
    for i,row in enumerate(profiles):
        require(row.get('index')==i,'profile index changed')
        mu=_finite(row.get('mu'),'profile point')
        require(float(number(request['fit']['domain'][0]))<=mu<=float(number(request['fit']['domain'][1])),'profile point outside original domain')
        if i<15:require((row.get('quantile'),row.get('role'),mu)==original_specs[i],'original profile point/quantile order differs')
        else:require(policy['mode']=='verify_or_refine' and row.get('quantile') in QUANTILES and row.get('role') in ('refinement_domain_upper','refinement_bisection','refinement_near_lower','refinement_near_upper'),'undeclared refinement profile')
        expected={n:dict(s) for n,s in initial.items()};expected[poi].update(value=mu,constant=True)
        require(row.get('start_state')==expected and row.get('start_errors')==errors,'profile inherited another fit instead of full state/step-error reset')
        require(row.get('counts')==prep['generated_counts'] and row.get('globals')==prep['generated_globals'],'profile observation/global state differs')
        _profile_check(row,initial,poi,mu)
        native_q=2*(_finite(row['nll'],'profile NLL')-nll0)
        value={'q':native_q,'engineering_guard':_margin(row['nll'],nll0)}
        if source_check:
            source_state={n:dict(s) for n,s in row['state'].items()};source_state[poi]['constant']=initial[poi]['constant']
            means=regional.native_witness(response,source_state)
            components=[_poisson_deviance(v,prep['generated_counts'][response['functions'][name]['bin']]) for name,v in means.items()]
            components += [(row['state'][name[:-3]]['value']-g['value'])**2 for name,g in prep['generated_globals'].items()]
            source_q=math.fsum(components)
            require(math.isfinite(source_q) and source_q>=0 and abs(native_q-source_q)<=1e-8+1e-7*abs(source_q),'native profile contrast differs from complete source Poisson/Gaussian law')
            value['source_q']=source_q
        values.append(value)
    originals=[]
    for i,item in enumerate(plan):
        require(values[3*i]['q']<=values[3*i+1]['q']<=values[3*i+2]['q'],'original profile likelihood is not monotone on endpoint bracket; unresolved')
        originals.append({'quantile':item['quantile'],'passed':_bracket_ok(profiles[3*i],profiles[3*i+2],item['target_q'],nll0),'lower_index':3*i,'reported_index':3*i+1,'upper_index':3*i+2})
    require(result.get('original_crossings')==originals,'original crossing diagnostics changed')
    solutions=result.get('solutions',[]);require(len(solutions)==5,'all five resolved endpoint brackets required')
    audit=[];previous=0.
    for i,(sol,item) in enumerate(zip(solutions,plan)):
        keys(sol,('quantile','source','endpoint','lower_index','upper_index'),'resolved endpoint')
        require(sol['quantile']==item['quantile'],'resolved quantile changed')
        a=sol['lower_index'];b=sol['upper_index']
        require(type(a) is int and type(b) is int and 0<=a<len(profiles) and 0<=b<len(profiles),'complete resolved bracket indices required')
        left=profiles[a];right=profiles[b];v=_finite(sol['endpoint'],'resolved endpoint')
        require(left['quantile']==right['quantile']==item['quantile'] and left['mu']<v<right['mu'],'resolved bracket/quantile differs')
        require(previous<v<float(number(request['fit']['domain'][1])),'resolved expected bands unordered/outside original domain')
        previous=v
        require(max(v-left['mu'],right['mu']-v)<=_resolution(v)*(1+1e-12),'resolved bracket exceeds declared endpoint resolution')
        require(_bracket_ok(left,right,item['target_q'],nll0),'expected endpoint lacks actual lower/upper threshold crossing; unresolved')
        if originals[i]['passed']:
            require(sol=={'quantile':item['quantile'],'source':'verified_Combine_endpoint','endpoint':item['reported_endpoint'],'lower_index':3*i,'upper_index':3*i+2},'verified original endpoint replaced')
        else:
            require(policy['mode']=='verify_or_refine' and sol['source']=='bounded_native_profile_refinement' and a>=15 and b>=15 and v==left['mu']+(right['mu']-left['mu'])/2,'undeclared or inconsistent refined endpoint')
        audit.append({'quantile':item['quantile'],'endpoint':v,'source':sol['source'],'target_q':item['target_q'],'bracket':[left['mu'],right['mu']],'profile_values':[values[a],values[b]]})
    return audit


def check_limits(inference,fit,crossing=None,response=None,preparation=None):
    original=deepcopy(inference.get('combine_result',inference))
    endpoint_plan(original,fit)
    require(type(crossing) is dict and crossing.get('status')=='passed' and response is not None and preparation is not None,'native profile crossing evidence required; interior rows alone are unresolved')
    audit=validate_crossings(crossing,response,{'inference':original,'fit':fit,'preparation':preparation})
    labels=('minus2sigma','minus1sigma','median','plus1sigma','plus2sigma')
    resolved={name:row['endpoint'] for name,row in zip(labels,audit)}
    comparisons=[]
    if fit['reference_quantiles'] is not None:
        ref=fit['reference_quantiles']
        for name,value in ref['values'].items():
            diff=resolved[name]-value;tol=ref['absolute_tolerance']+ref['relative_tolerance']*abs(value)
            comparisons.append({'name':name,'actual':resolved[name],'reference':value,'difference':diff,'tolerance':tol,'passed':abs(diff)<=tol})
    # Preserve original Combine values in an exact separate payload. Canonical
    # quantiles must not expose rejected raw endpoints to downstream consumers.
    inference.update({'data_semantics':'expected_only_background_Asimov','conditioning_qualified_by_source_and_diagnostics_only':True,'observed_endpoint':None,'coverage_qualified':False,'internal_asimov_dataset_independently_exposed':False,'internal_generation':'Combine9.2.1 AsymptoticLimits --run blind regenerates its nominal Asimov at the retained prepared state; no second observed conditioning fit'})
    inference.update({'combine_result':original,'combine_result_passed':original['passed'],'quantiles':resolved,'reference_comparisons':comparisons,'quantile_provenance':{name:row['source'] for name,row in zip(labels,audit)},'rows_semantics':'literal_original_Combine_tree_rows; canonical_quantiles_are_crossing_qualified','crossing_qualification':audit,'resolved_quantiles':resolved,'resolved_reference_comparisons':comparisons,'passed':all(c['passed'] for c in comparisons),'optimizer_globality_qualified':False,'error_enclosure_qualified':False,'crossing_scope':'Numerical nuisance-profile crossing brackets on the separately retained source Asimov, within released endpoint resolution; local fit diagnostics, no globality/coverage/error certificate.'})
    return inference


def _source_graph_request(response):
    require(response.get('kind')=='native-source-graph/v1','actual source graph response required')
    cell=next(c for c in response['recipe']['cells'] if c['id']==response['cell'])
    r=cell['expected_data'];keys(r,('kind','conditioning','point','source','statement','fit'),'source graph expected request')
    require(r==response['expected_data'] and r['kind']=='source-graph-asimov/v1' and r['conditioning'] in ('supplied_nominal','fit_observed_at_fixed_poi'),'exact original source generating prescription required')
    require(r['source'] in {s['id']for s in cell['law']['sources']} and isinstance(r['statement'],str) and bool(r['statement'].strip()),'source-bound generating statement required')
    d=response['document'];keys(r['point'],response['coordinates'],'complete source graph generating point')
    for p in d['parameters']:
        q=number(r['point'][p['name']]);require(number(p['bounds'][0])<=q<=number(p['bounds'][1]) and (not p['fixed'] or q==number(p['initial'])),'generating point changed original fixed value/domain')
    for i,bounds in enumerate(d['auxiliary']['eta_bounds']):
        q=number(r['point']['ravel_aux_'+str(i)]);require(number(bounds[0])<=q<=number(bounds[1]),'generating eta outside original bounds')
    require(response['source_observations']=={b['id']:b['observed']for b in cell['law']['bins']},'original source observations changed')
    if r['conditioning']=='supplied_nominal':require(r['fit']is None,'nominal request cannot hide conditioning')
    else:
        require(all(type(v)is int and v>=0 for v in response['source_observations'].values()),'conditioning requires actual complete observations')
        f=r['fit'];keys(f,('strategy','tolerance','max_calls','max_iterations','max_edm'),'conditioning fit')
        require(type(f['strategy'])is int and f['strategy']in(0,1,2),'bounded conditioning strategy required')
        for key in ('max_calls','max_iterations'):require(type(f[key])is int and 1<=f[key]<=100000,'bounded conditioning work required')
        require(number(f['tolerance'])>0 and number(f['max_edm'])>0,'positive conditioning tolerance/EDM required')
    return deepcopy(r)


def prepare_source_graph(ROOT,w,mc,data,nll,response,out):
    """Full source expectation/profile preparation; no regional numerical/CLs inference."""
    return shared_native_prepare(ROOT,w,mc,data,nll,response,out,_source_graph_request(response),graph_mode=True)


def source_graph_integrals(w,response, *, recorder=None):
    cell=next(c for c in response['recipe']['cells'] if c['id']==response['cell']);rows=[]
    for j,component in enumerate(cell['components']):
        names=component.get('observables',[component['observable']] if 'observable'in component else None)
        require(type(names)is list and names and len(names)==len(set(names)),'full original integral tuple required')
        root=w.function(component['node'])or w.pdf(component['node']);require(bool(root),'original integrand absent')
        # Native dependency identity is separately retained by the probe; no engine imported here.
        for name in ([('ravel_graph_den_'+str(j),None)] if component['normalization']=='full_domain' else [])+[( 'ravel_graph_int_'+str(j)+'_'+str(i),'ravel_graph_int_'+str(j)+'_'+str(i))for i in range(len(cell['law']['bins']))]:
            fn=w.function(name[0]);require(bool(fn) and bool(fn.isValid()),'original integral absent/invalid')
            sets={key:sorted(str(v.GetName())for v in getattr(fn,key)())for key in ('intVars','numIntRealVars','anaIntVars','numIntCatVars')}
            require(not sets['numIntCatVars'],'unexpected category integration')
            engine_variables=[]
            for variable in fn.intVars():
                identity=str(variable.GetName())
                originals=[identity]if identity in names else sorted(str(v.GetName())for v in variable.getObservables(w.allVars())if str(v.GetName())in names)
                engine_variables.append({'name':identity,'class':str(variable.ClassName()),'original_observables':originals})
            require(set().union(*(set(v['original_observables'])for v in engine_variables))==set(names),'actual joint original observable closure changed')
            sets['factoredVars']=sorted(set(sets['intVars'])-set(sets['numIntRealVars'])-set(sets['anaIntVars'])-set(sets['numIntCatVars']))
            dim=len(sets['numIntRealVars']);require(dim<=15,'released joint numerical engine cannot integrate this residual dimension')
            ranges={n:[float(w.var(n).getMin(name[1])) if name[1] is not None else float(w.var(n).getMin()),float(w.var(n).getMax(name[1])) if name[1] is not None else float(w.var(n).getMax())]for n in names}
            if recorder is not None:recorder.begin_scalar(name[0])
            raw_value=float(fn.getVal())
            if recorder is not None:recorder.returned_scalar(raw_value)
            value=_finite(raw_value,'joint raw source integral')
            if name[0].startswith('ravel_graph_den_'):require(value>0,'original density denominator is not positive')
            rows.append({'name':name[0],'component':component['id'],'observables':names,'range_name':str(fn.intRange()) if fn.intRange()else None,'ranges':ranges,'integrand':str(fn.integrand().GetName()),'value':value,**sets,'engine_variables':sorted(engine_variables,key=lambda v:v['name']),'numerical_dimension':dim,'requested':deepcopy(cell['integration']),'effective':{'eps_abs':0.0 if dim>=2 else float(number(cell['integration']['eps_abs'])),'eps_rel':float(number(cell['integration']['eps_rel'])),'max_warn':0 if dim>=2 else None,'method':'RooAdaptiveIntegratorND' if dim>=2 else 'RooIntegrator1D' if dim==1 else 'source_analytical'},'status':None,'error':None,'relative_error':None,'evaluations':None,'numerical_equivalence_qualified':False})
            if recorder is not None:recorder.returned_integrals(rows)
    return rows
