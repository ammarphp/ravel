"""Native WCxf/Wilson/flavio/smelli API composition; imports are caller supplied.

This module implements transport and population checks, never RGE or likelihood
formulae. Completed calls are journalled before dependent checks. Numerical
accuracy, physical matching and statistical calibration require separate evidence.
"""
import contextlib
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import pickle
import re
import stat
import sys

MAX_JSON = 16 * 1024 * 1024
OPTIONS = ('smeft_accuracy','qed_order','qcd_order','smeft_matching_order',
           'smeft_matchingscale','mb_matchingscale','mc_matchingscale','parameters')
EFTS = ('SMEFT','WET','WET-4','WET-3')
SCOPE = 'eft-toolchain-fixed-point-delivery'


def keys(value, expected, label):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError('closed ' + label + ' required')


def text(value, label):
    if type(value) is not str or not value.strip() or len(value.encode()) > 4096:
        raise ValueError('explicit bounded ' + label + ' required')
    return value


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value):
        raise ValueError('finite real number required')
    return float(value)


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('bounded integer required')


def _pairs(rows):
    d = {}
    for k,v in rows:
        if k in d: raise ValueError('duplicate JSON key: ' + k)
        d[k] = v
    return d


def read_json(path, cap=MAX_JSON):
    p = Path(path).absolute()
    if any(x.is_symlink() for x in (p,*p.parents)):
        raise ValueError('aliased JSON path')
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > cap: raise ValueError('JSON size/type')
        with os.fdopen(fd,'rb',closefd=False) as f: raw = f.read(cap+1)
        after = os.fstat(fd); end = p.lstat()
        ident = lambda s:(s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
        if len(raw)>cap or ident(before)!=ident(after) or ident(after)!=ident(end):
            raise ValueError('JSON changed/oversized during bounded read')
    finally: os.close(fd)
    return json.loads(raw,object_pairs_hook=_pairs,parse_constant=lambda s:(_ for _ in ()).throw(ValueError('nonfinite JSON')))


def write_json(path, value, cap=MAX_JSON):
    data = json.dumps(value,allow_nan=False,sort_keys=True,indent=2).encode()
    if len(data)>cap: raise ValueError('JSON output ceiling exceeded')
    p=Path(path); tmp=p.with_name(p.name+'.tmp')
    with tmp.open('xb') as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,p)


def complex_value(value):
    if type(value) is dict:
        if not value or not set(value)<= {'Re','Im'}: raise ValueError('WCxf complex Re/Im required')
        return complex(number(value.get('Re',0)),number(value.get('Im',0)))
    return complex(number(value),0)


def wc_document(doc):
    keys(doc,('eft','basis','scale','values'),'WCxf point')
    if doc['eft'] not in EFTS or number(doc['scale'])<=0: raise ValueError('known EFT/positive GeV scale required')
    text(doc['basis'],'basis')
    if type(doc['values']) is not dict or len(doc['values'])>10000: raise ValueError('bounded sparse coefficient map required')
    for k,v in doc['values'].items(): text(k,'coefficient'); complex_value(v)
    return doc


def options(value):
    keys(value,OPTIONS,'Wilson options')
    if value['smeft_accuracy'] not in ('integrate','leadinglog'): raise ValueError('explicit RGE accuracy required')
    for k in ('qed_order','qcd_order','smeft_matching_order'): integer(value[k],0,1)
    for k in ('smeft_matchingscale','mb_matchingscale','mc_matchingscale'):
        if number(value[k])<=0: raise ValueError('positive matching threshold required')
    if not value['mc_matchingscale'] < value['mb_matchingscale'] < value['smeft_matchingscale']:
        raise ValueError('ordered charm/bottom/electroweak matching thresholds required')
    numeric_map(value['parameters'])
    return value


def numeric_map(value):
    if type(value) is not dict or len(value)>10000: raise ValueError('bounded parameter map required')
    for k,v in value.items():text(k,'parameter');number(v)


def config(c):
    keys(c,('schema_version','source','runtime','wcxf','conventions','wilson_options','targets',
            'observables','parameter_overrides','smelli','max_seconds','max_ram_mib','max_export_bytes'),'EFT toolchain config')
    if type(c['schema_version']) is not int or c['schema_version']!=1: raise ValueError('schema 1 required')
    text(c['source'],'source'); options(c['wilson_options']);numeric_map(c['parameter_overrides'])
    conv=c['conventions']
    keys(conv,('input_kind','scale_unit','coefficient_normalization','flavour_assumptions','truncation','domain','evidence'),'conventions')
    if (conv['input_kind']!='new_physics' or conv['scale_unit']!='GeV' or
        conv['coefficient_normalization']!='native_wcxf_basis' or conv['truncation']!='upstream_native_no_additional_linearization'):
        raise ValueError('explicit native WCxf normalization and upstream truncation required')
    for k in ('flavour_assumptions','domain'):text(conv[k],k)
    if type(conv['evidence']) is not list or not conv['evidence']:raise ValueError('convention evidence required')
    rt=c['runtime'];keys(rt,('python','site_roots','assets','versions'),'runtime')
    if type(rt['site_roots']) is not list or not 1<=len(rt['site_roots'])<=8 or len(set(rt['site_roots']))!=len(rt['site_roots']):raise ValueError('unique runtime roots required')
    if type(rt['assets']) is not list or not 1<=len(rt['assets'])<=100000:raise ValueError('complete bounded runtime assets required')
    if type(rt['versions']) is not dict or not {'wilson','numpy'}<=set(rt['versions']):raise ValueError('actual runtime package versions required')
    for k,v in rt['versions'].items():text(k,'distribution');text(v,'version')
    ids={'input'}
    if type(c['targets']) is not list or len(c['targets'])>16:raise ValueError('bounded targets required')
    for row in c['targets']:
        keys(row,('id','eft','basis','scale'),'target')
        if not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,63}',row['id']) or row['id'] in ids:raise ValueError('unique target identity required')
        ids.add(row['id']);wc_document({**{k:row[k] for k in ('eft','basis','scale')},'values':{}})
    if type(c['observables']) is not list or len(c['observables'])>128:raise ValueError('bounded observable population required')
    seen=set()
    for row in c['observables']:
        keys(row,('id','name','arguments','unit','coefficient_source'),'observable')
        if row['id'] in seen:raise ValueError('duplicate observable ID')
        seen.add(text(row['id'],'observable ID'));text(row['name'],'observable');text(row['unit'],'declared output unit')
        numeric_map(row['arguments'])
        if row['coefficient_source'] not in ids:raise ValueError('unknown coefficient source')
    if c['observables'] and 'flavio' not in rt['versions']:raise ValueError('flavio version required')
    s=c['smelli']
    if s is not None:
        keys(s,('coefficient_source','include_likelihoods','fix_ckm','ckm_scheme','covariance_cache'),'smelli selection')
        if s['coefficient_source'] not in ids or type(s['fix_ckm']) is not bool:raise ValueError('explicit smelli point and CKM policy required')
        if s['ckm_scheme']!='CKMSchemeRmuBtaunuBxlnuDeltaM':raise ValueError('reviewed CKM scheme required')
        groups=s['include_likelihoods']
        if type(groups) is not list or not groups or len(groups)!=len(set(groups)) or len(groups)>32:raise ValueError('explicit unique smelli population required')
        for group in groups:
            if not re.fullmatch('[A-Za-z0-9_]+[.]yaml',group):raise ValueError('named built-in likelihood required')
        if not {'flavio','smelli'}<=set(rt['versions']):raise ValueError('smelli/flavio versions required')
    if not c['targets'] and not c['observables'] and s is None:raise ValueError('nonempty scientific operation required')
    for k in set(c['wilson_options']['parameters']) & set(c['parameter_overrides']):
        if c['wilson_options']['parameters'][k]!=c['parameter_overrides'][k]:raise ValueError('conflicting explicit running/prediction parameter')
    integer(c['max_seconds'],1,86400);integer(c['max_ram_mib'],128,8192);integer(c['max_export_bytes'],65536,MAX_JSON)
    return c


def basis_metadata(wcxf, eft, basis):
    b=wcxf.Basis[eft,basis]
    rows={k:v for sector in b.sectors.values() for k,v in sector.items()}
    if len(rows)!=len(b.all_wcs) or set(rows)!=set(b.all_wcs):raise ValueError('basis coordinate census inconsistent')
    return b,rows


def checked_values(doc, wcxf):
    wc_document(doc);_,meta=basis_metadata(wcxf,doc['eft'],doc['basis'])
    if not set(doc['values'])<=set(meta):raise ValueError('unknown coefficient in explicit WCxf basis')
    values={k:complex_value(v) for k,v in doc['values'].items()}
    if any(meta[k].get('real',False) and v.imag!=0 for k,v in values.items()):raise ValueError('imaginary component for real WCxf coefficient')
    return values


def pack_wc(wc, wcxf):
    b,meta=basis_metadata(wcxf,wc.eft,wc.basis)
    raw={k:{'Re':float(complex(v).real),'Im':float(complex(v).imag)} for k,v in wc.dict.items()}
    doc={'eft':wc.eft,'basis':wc.basis,'scale':float(wc.scale),'values':raw}
    checked_values(doc,wcxf)
    return {'wcxf':doc,'ordered_basis':list(b.all_wcs),'basis_metadata':copy.deepcopy(getattr(b,'metadata',{})),
            'coordinate_metadata':copy.deepcopy(meta),'omitted_coefficients':'zero_in_this_basis',
            'complete_values':{k:raw.get(k,{'Re':0.0,'Im':0.0}) for k in b.all_wcs}}


def new_wilson(api, doc, settings):
    values=checked_values(doc,api.wcxf)
    if not set(settings['parameters'])<=set(api.parameters.p):raise ValueError('unknown Wilson running parameter')
    w=api.Wilson(values,scale=doc['scale'],eft=doc['eft'],basis=doc['basis'])
    # smelli changes Wilson class defaults on import; every option is explicit.
    for k in OPTIONS:w.set_option(k,copy.deepcopy(settings[k]))
    if {k:w.get_option(k) for k in OPTIONS}!=settings:raise ValueError('Wilson options differ after initialization')
    return w


def native_value(value):
    """JSON transport, retaining exceptional scalar observations explicitly."""
    if hasattr(value,'tolist'):return native_value(value.tolist())
    if isinstance(value,dict):return {str(k):native_value(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [native_value(v) for v in value]
    if isinstance(value,complex):return {'Re':native_value(value.real),'Im':native_value(value.imag)}
    if isinstance(value,float) and not math.isfinite(value):return {'nonfinite_binary64':repr(value)}
    if value is None or isinstance(value,(str,bool,int,float)):return value
    raise ValueError('unsupported native return type '+type(value).__name__)


def sum_semantics():
    """Identify the unchanged interpreter's ordered builtin-float reduction.

    CPython changed float summation in 3.12. Cross-minor/runtime reductions are
    refused here rather than replaced with a tolerance or a custom algorithm.
    """
    if sys.implementation.name != 'cpython':
        raise ValueError('source-bound CPython builtin sum semantics required')
    return {'implementation':sys.implementation.name,
            'python_major_minor':list(sys.version_info[:2]),
            'float_format':[sys.float_info.radix,sys.float_info.mant_dig,sys.float_info.max_exp],
            'operation':'builtins.sum(ordered native component float values)'}


class Journal:
    def __init__(self,path,cap):
        self.path=Path(path);self.cap=cap
        self.value={'schema_version':1,'status':'running','calls':[],'result':{},'error':None,'physics_validated':False}
        self.save()
    def save(self):write_json(self.path,self.value,self.cap)
    def call(self,identity,function):
        row={'identity':identity,'status':'started'};self.value['calls'].append(row);self.save()
        try:
            answer=function()
            row['return']=native_value(answer)
            if isinstance(answer,dict):row['return_key_order']=list(answer)
            if identity=='smelli:NP_minus_SM':row['sum_semantics']=sum_semantics()
            row['status']='returned';self.save()
            return answer
        except BaseException as exc:
            row['error']=type(exc).__name__+': '+str(exc);row['status']='failed';self.save();raise
    def retain(self,key,value):self.value['result'][key]=native_value(value);self.save()


def cache_document(doc):
    keys(doc,('schema_version','source','parameters','fix_ckm','ckm_scheme','groups'),'covariance cache')
    if doc['schema_version']!=1 or type(doc['fix_ckm']) is not bool:raise ValueError('cache schema/CKM policy')
    text(doc['source'],'covariance provenance');numeric_map(doc['parameters']);text(doc['ckm_scheme'],'CKM scheme')
    if type(doc['groups']) is not dict:raise ValueError('complete fast likelihood cache population required')
    for name,row in doc['groups'].items():
        keys(row,('observables','experimental_central','experimental_covariance','sm_covariance'),'fast covariance group')
        n=len(row['observables'])
        if not 1<=n<=2000:raise ValueError('bounded covariance population')
        obs=[json.dumps(o,sort_keys=True,allow_nan=False) for o in row['observables']]
        if len(set(obs))!=n:raise ValueError('duplicate cache observable')
        for o in row['observables']:
            if type(o) is str:text(o,'cache observable')
            elif type(o) is list and o and type(o[0]) is str:
                for v in o[1:]:number(v)
            else:raise ValueError('native observable identity required')
        if len(row['experimental_central'])!=n:raise ValueError('cache central population')
        for v in row['experimental_central']:number(v)
        for field in ('experimental_covariance','sm_covariance'):
            a=row[field]
            if type(a) is not list or len(a)!=n or any(type(r) is not list or len(r)!=n for r in a):raise ValueError('full covariance matrix required')
            for i in range(n):
                for j in range(n):
                    number(a[i][j])
                    if a[i][j]!=a[j][i]:raise ValueError('exact symmetric supplied covariance required')
                if a[i][i]<0:raise ValueError('negative covariance diagonal')
    return doc


@contextlib.contextmanager
def no_covariance_sampling(likelihood_module):
    classes=(likelihood_module.SMCovariance,likelihood_module.MeasurementCovariance)
    originals=[cls.compute for cls in classes]
    def refuse(*a,**kw):raise ValueError('undeclared covariance sampling refused; complete supplied cache required')
    try:
        for cls in classes:cls.compute=refuse
        yield
    finally:
        for cls,method in zip(classes,originals):cls.compute=method


def smelli_score(c,doc,cache,api,flavio,smelli,np,journal,out):
    s=c['smelli'];cache_document(cache)
    if doc['eft'] not in ('SMEFT','WET'):raise ValueError('smelli supports SMEFT/WET points only')
    expected_parameters=flavio.default_parameters.get_central_all();expected_parameters.update(c['parameter_overrides'])
    if (cache['fix_ckm']!=s['fix_ckm'] or cache['ckm_scheme']!=s['ckm_scheme'] or cache['parameters']!=expected_parameters):raise ValueError('cache declared full central-parameter/CKM assumptions differ')
    fast=[g for g in s['include_likelihoods'] if g.startswith('fast_likelihood_')]
    if set(cache['groups'])!=set(fast):raise ValueError('exact requested fast cache population required')
    sm=out/'sm-covariances';exp=out/'experimental-covariances';sm.mkdir();exp.mkdir()
    for name,row in cache['groups'].items():
        obs=[tuple(o) if isinstance(o,list) else o for o in row['observables']]
        arrays={k:np.asarray(row[k],dtype=float) for k in ('experimental_central','experimental_covariance','sm_covariance')}
        for k in ('experimental_covariance','sm_covariance'):
            if float(np.linalg.eigvalsh(arrays[k]).min())<0:raise ValueError('supplied covariance is not positive semidefinite')
        suffix='_fix_ckm' if s['fix_ckm'] else '_'+s['ckm_scheme']
        # Only locally constructed plain arrays/dicts are pickled; supplied pickle is never loaded.
        with (sm/(name+suffix+'.p')).open('xb') as f:pickle.dump({'observables':obs,'covariance':arrays['sm_covariance']},f)
        with (exp/(name+'.p')).open('xb') as f:pickle.dump({'observables':obs,'central':arrays['experimental_central'],'covariance':arrays['experimental_covariance']},f)
    from_module=flavio.statistics.likelihood
    with no_covariance_sampling(from_module):
        likelihood=smelli.GlobalLikelihood(eft=doc['eft'],basis=doc['basis'],par_dict=c['parameter_overrides'],
            include_likelihoods=s['include_likelihoods'],exclude_likelihoods=None,Nexp=0,
            exp_cov_folder=str(exp),sm_cov_folder=str(sm),custom_likelihoods=None,
            fix_ckm=s['fix_ckm'],ckm_scheme=s['ckm_scheme'])
        journal.retain('smelli_initialized',{'groups':list(likelihood.fast_likelihoods)+list(likelihood.likelihoods),
            'sm_cov_loaded':likelihood._sm_cov_loaded,'default_parameters':likelihood.par_dict_default})
        if set(likelihood.fast_likelihoods)|set(likelihood.likelihoods)!=set(s['include_likelihoods']):raise ValueError('native likelihood population differs')
        likelihood._check_sm_cov_loaded()
        census={}
        for name,lh in {**likelihood.fast_likelihoods,**likelihood.likelihoods}.items():
            ml=lh.full_measurement_likelihood if name in likelihood.fast_likelihoods else lh.measurement_likelihood
            census[name]={'observables':native_value(lh.observables),'measurements':sorted(ml.get_measurements)}
            if name in cache['groups'] and {json.dumps(o,sort_keys=True) for o in native_value(lh.observables)}!={json.dumps(o,sort_keys=True) for o in cache['groups'][name]['observables']}:
                raise ValueError('cache and actual observable population differ')
        journal.retain('smelli_population',census)
        initialized_covariances={}
        for name,lh in likelihood.fast_likelihoods.items():
            initialized_covariances[name]={'observables':native_value(lh.observables),
                'experimental_central_and_covariance':native_value(lh.exp_covariance.get(force=False)),
                'sm_covariance':native_value(lh.sm_covariance.get(force=False))}
            journal.retain('smelli_initialized_covariances',initialized_covariances)
        w=new_wilson(api,doc,c['wilson_options']);point=likelihood.parameter_point(w)
        baseline=journal.call('smelli:SM_reference',lambda:likelihood.log_likelihood_sm)
        # Keep the unchanged upstream delta-log-likelihood API and its global reduction.
        score=journal.call('smelli:NP_minus_SM',point.log_likelihood_dict)
        journal.retain('smelli_parameters',{'sm':likelihood.par_dict_sm,'np':point.par_dict_np,
            'wilson_options_after_ckm':{k:point.w.get_option(k) for k in OPTIONS}})
        if set(score)!=set(s['include_likelihoods'])|{'global'} or set(baseline)!=set(s['include_likelihoods']):raise ValueError('score population mismatch')
        for v in [*score.values(),*baseline.values()]:number(float(v))
        return {'delta_log_likelihood':native_value(score),'sm_native_reference':native_value(baseline),
                'definition':'logL(NP)-logL(SM); global is selected upstream component sum',
                'sampling_performed':False,'covariance_source':cache['source'],'cross_domain_independence':'unqualified'}


def evaluate(c,point,cache,api,flavio,smelli,np,journal,out):
    config(c);wc_document(point);settings=c['wilson_options'];docs={'input':copy.deepcopy(point)}
    w=new_wilson(api,point,settings)
    journal.retain('input_coefficients',pack_wc(w.wc,api.wcxf))
    journal.retain('running_parameters',w.parameters)
    journal.retain('wilson_options',{k:w.get_option(k) for k in OPTIONS})
    targets={}
    for row in c['targets']:
        # pack only after retaining native WC fields, then enforce complete basis/real constraints.
        def transform(row=row):
            wc=w.match_run(row['scale'],row['eft'],row['basis'],sectors='all')
            return {k:getattr(wc,k) for k in ('eft','basis','scale','values')}
        returned=journal.call('match_run:'+row['id'],transform)
        native={k:returned[k] for k in ('eft','basis','scale','values')}
        if any(native[k]!=row[k] for k in ('eft','basis','scale')):raise ValueError('native target identity differs')
        obj=api.wcxf.WC(**native);targets[row['id']]=pack_wc(obj,api.wcxf);docs[row['id']]=native
        journal.retain('targets',targets)
    predictions=[]
    if c['observables']:
        par=flavio.default_parameters.get_central_all()
        if not set(c['parameter_overrides'])<=set(par):raise ValueError('unknown flavio parameter override')
        par.update(c['parameter_overrides']);journal.retain('prediction_parameters',par)
        for row in c['observables']:
            observable=flavio.Observable[row['name']]
            if set(row['arguments'])!=set(observable.arguments or []):raise ValueError('observable arguments mismatch')
            doc=docs[row['coefficient_source']]
            wp=new_wilson(api,doc,settings);zero={**doc,'values':{}};ws=new_wilson(api,zero,settings)
            sm=journal.call('observable:'+row['id']+':SM',lambda:observable.prediction_par(par,ws,**row['arguments']))
            npvalue=journal.call('observable:'+row['id']+':NP',lambda:observable.prediction_par(par,wp,**row['arguments']))
            number(float(sm));number(float(npvalue))
            predictions.append({**row,'sm':float(sm),'np':float(npvalue),'difference':float(npvalue-sm),
                'description':getattr(observable,'description',''),'uncertainty':'not_computed'})
            journal.retain('predictions',predictions)
    likelihood=None
    if c['smelli'] is not None:
        if not set(c['parameter_overrides'])<=set(flavio.default_parameters.get_central_all()):raise ValueError('unknown smelli parameter override')
        likelihood=smelli_score(c,docs[c['smelli']['coefficient_source']],cache,api,flavio,smelli,np,journal,out)
        journal.retain('likelihood',likelihood)
    return {'targets':targets,'predictions':predictions,'likelihood':likelihood,
            'wrapper_return_count':sum(r['status']=='returned' for r in journal.value['calls']),
            'internal_solver_evaluation_count':'not_instrumented','physics_validated':False}


def delivery_check(delivery,c,point):
    """Complete request/result population check; not an independent RGE oracle."""
    if (delivery.get('status')!='completed' or delivery.get('error') is not None or
        delivery.get('physics_validated') is not False):raise ValueError('incomplete native delivery')
    expected=['match_run:'+r['id'] for r in c['targets']]
    for row in c['observables']:expected.extend(['observable:'+row['id']+':SM','observable:'+row['id']+':NP'])
    if c['smelli'] is not None:expected.extend(['smelli:SM_reference','smelli:NP_minus_SM'])
    calls=delivery['calls']
    if [r['identity'] for r in calls]!=expected or any(r['status']!='returned' or 'return' not in r for r in calls):raise ValueError('complete ordered native call population required')
    result=delivery['result'];data=result['completed_quantities'];returns={row['identity']:row for row in calls}
    if data['physics_validated'] is not False or data['wrapper_return_count']!=len(expected) or data['internal_solver_evaluation_count']!='not_instrumented':raise ValueError('native count/scope mismatch')
    if result['wilson_options']!=c['wilson_options']:raise ValueError('effective Wilson options differ')
    check_points={'input':point,**{r['id']:r for r in c['targets']}}
    if set(data['targets'])!=set(check_points)-{'input'}:raise ValueError('target population mismatch')
    for name,source in check_points.items():
        packed=result['input_coefficients'] if name=='input' else data['targets'][name]
        doc=wc_document(packed['wcxf'])
        if any(doc[k]!=source[k] for k in ('eft','basis','scale')):raise ValueError('target identity mismatch')
        order=packed['ordered_basis'];complete=packed['complete_values'];meta=packed['coordinate_metadata']
        if type(order) is not list or len(order)!=len(set(order)) or set(order)!=set(meta) or set(order)!=set(complete) or not set(doc['values'])<=set(order) or packed['omitted_coefficients']!='zero_in_this_basis':raise ValueError('complete coefficient population mismatch')
        for k in order:
            val=complex_value(complete[k]);sparse=complex_value(doc['values'].get(k,0))
            if val!=sparse or (meta[k].get('real',False) and val.imag!=0):raise ValueError('sparse/complete/real coefficient mismatch')
        literal=point if name=='input' else wc_document(returns['match_run:'+name]['return'])
        if any(literal[k]!=doc[k] for k in ('eft','basis','scale')):raise ValueError('literal WCxf return identity differs')
        if {k:complex_value(v) for k,v in doc['values'].items()}!={k:complex_value(v) for k,v in literal['values'].items()}:
            raise ValueError('literal coefficient values differ from packed result')
    if result.get('targets',{})!=data['targets']:raise ValueError('retained target records differ')
    if len(data['predictions'])!=len(c['observables']):raise ValueError('observable population mismatch')
    for row,request in zip(data['predictions'],c['observables']):
        if any(row[k]!=v for k,v in request.items()):raise ValueError('observable request identity mismatch')
        number(row['sm']);number(row['np']);number(row['difference'])
        sm=number(returns['observable:'+request['id']+':SM']['return'])
        npvalue=number(returns['observable:'+request['id']+':NP']['return'])
        if row['sm']!=sm or row['np']!=npvalue or row['difference']!=npvalue-sm or row['uncertainty']!='not_computed':
            raise ValueError('literal prediction returns differ from summary')
    if result.get('predictions',[])!=data['predictions']:raise ValueError('retained prediction records differ')
    if result.get('likelihood')!=data['likelihood']:raise ValueError('retained likelihood records differ')
    if c['smelli'] is None:
        if data['likelihood'] is not None:raise ValueError('undeclared likelihood')
    else:
        score=data['likelihood'];groups=set(c['smelli']['include_likelihoods'])
        if set(score['delta_log_likelihood'])!=groups|{'global'} or set(score['sm_native_reference'])!=groups or score['sampling_performed'] is not False:raise ValueError('likelihood population/sampling differs')
        for v in [*score['delta_log_likelihood'].values(),*score['sm_native_reference'].values()]:number(v)
        if set(result['smelli_population'])!=groups:raise ValueError('actual likelihood population missing')
        baseline=returns['smelli:SM_reference']['return'];literal=returns['smelli:NP_minus_SM']
        if baseline!=score['sm_native_reference'] or literal['return']!=score['delta_log_likelihood']:
            raise ValueError('literal likelihood returns differ from summary')
        order=literal.get('return_key_order')
        if (type(order) is not list or not order or order[-1]!='global' or
            len(order)!=len(set(order)) or set(order)!=groups|{'global'}):
            raise ValueError('complete native component reduction order required')
        if literal.get('sum_semantics')!=sum_semantics():
            raise ValueError('native/checker builtin sum semantics differ; no cross-runtime reduction qualification')
        # Exact pinned smelli _delta_log_likelihood; no custom likelihoods are
        # constructed by this adapter, and the source filter is retained verbatim.
        total=sum([number(literal['return'][name]) for name in order[:-1] if 'custom_' not in name])
        if not math.isfinite(total) or total!=number(literal['return']['global']):
            raise ValueError('native global differs from source-defined ordered component sum')
    return data
