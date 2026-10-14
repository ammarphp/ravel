"""Complete, fixed-law quantitative evidence inside an approved ordinary study.

Authentication is not calibration. This consumer supplies diagnostics and
explicit task-declared selection objectives, never scientific acceptance.
"""
from copy import deepcopy
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import time

from . import candidate_experiments as ce

MAX_EXACT_COUNT = 2**53
DEFAULT_LIMITS = {'coordinates':64, 'sources':256, 'single_bytes':8*1024**2,
    'unique_bytes':64*1024**2, 'matrix_elements':4*64**2, 'work_units':64**3*16,
    'hypothesis_pairs':16, 'finite_states':16}
CALCULATIONS = {'raw_residual','fixed_poisson_deviance','fixed_poisson_upper_tail',
    'fixed_poisson_threshold_power','fixed_poisson_kl','known_gaussian_mahalanobis',
    'known_gaussian_mean_separation'}
SCOPE = 'conditional_fixed_law_quantitative_diagnostics'


def _keys(value, required, optional=()):
    if type(value) is not dict or set(value) != set(required) | (set(value) & set(optional)):
        raise ValueError('exact quantitative object fields required: '+','.join(sorted(required)))


def _text(value):
    if type(value) is not str or not value.strip() or len(value.encode())>4096:
        raise ValueError('bounded explicit quantitative text required')
    return value


def _number(value):
    try: valid=type(value) in (int,float) and math.isfinite(value)
    except OverflowError: valid=False
    if not valid: raise ValueError('finite nonboolean numeric operand required')
    return value


def _integer(value, maximum=None):
    if type(value) is not int or value<0 or maximum is not None and value>maximum:
        raise ValueError('strict exact nonnegative integer within qualified bound required')
    return value


def _encoded(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()


def _pin(value):
    _keys(value,('path','sha256','size'));_text(value['path']);ce.sha(value['sha256']);_integer(value['size'])
    return value


def _locator(value):
    _keys(value,('source','pointer'));_pin(value['source'])
    if type(value['pointer']) is not str or (value['pointer'] and not value['pointer'].startswith('/')):
        raise ValueError('literal RFC6901 pointer required')


def default_resources(*, wall_seconds=10, max_rss_mib=256):
    """Prospective declaration only; ordinary planning/approval admits it."""
    return {'schema_version':1,'kind':'quantitative_resource_allocation',
        'limits':deepcopy(DEFAULT_LIMITS),'wall_seconds':wall_seconds,'max_rss_mib':max_rss_mib}


def validate_resources(value):
    _keys(value,('schema_version','kind','limits','wall_seconds','max_rss_mib'))
    if type(value['schema_version']) is not int or value['schema_version']!=1 or value['kind']!='quantitative_resource_allocation':
        raise ValueError('versioned prospective quantitative allocation required')
    _keys(value['limits'],DEFAULT_LIMITS)
    for v in value['limits'].values():
        if type(v) is not int or v<1:raise ValueError('positive integer quantitative resource limits required')
    for k in ('wall_seconds','max_rss_mib'):
        if type(value[k]) is not int or value[k]<1:raise ValueError('positive checking wall and memory ceilings required')
    return deepcopy(value)


def validate_binding(value):
    _keys(value,('contract','resources'));_pin(value['contract']);_pin(value['resources'])
    if any(not Path(value[k]['path']).is_absolute() for k in ('contract','resources')):
        raise ValueError('binding pins use canonical absolute source locators; nested sources resolve at contract parent')
    return deepcopy(value)


def quantitative(observable):
    return type(observable) is dict and observable.get('kind')=='quantitative'


def _dimension(value):
    if type(value) is not dict:raise ValueError('explicit dimension-power map required')
    for k,v in value.items():
        _text(k)
        if type(v) is not list or len(v)!=2 or type(v[0]) is not int or type(v[1]) is not int or v[1]<=0:
            raise ValueError('literal rational dimension powers required')


def validate_contract(c):
    _keys(c,('schema_version','kind','check_id','experiment_id','goal_binding','premise_bindings',
        'population','observed','conditions','hypotheses','comparison','noise','nuisances','exposure',
        'numerics','decision_family','selection_inputs','source_provenance','requested_limits'))
    if type(c['schema_version']) is not int or c['schema_version']!=1 or c['kind']!='prospective_quantitative_predictive_check':
        raise ValueError('quantitative check/v1 required')
    for k in ('check_id','experiment_id'):ce.identity(c[k])
    if type(c['premise_bindings']) is not dict:raise ValueError('exact current premise bindings required')
    for k,v in c['premise_bindings'].items():ce.identity(k);ce.sha(v)
    if not isinstance(c['conditions'],dict):raise ValueError('complete supplied conditions required')
    pop=c['population']
    if type(pop) is not list or not pop:raise ValueError('whole nonempty coordinate population required')
    ids=[]
    for row in pop:
        _keys(row,('id','cell_id','quantity','unit','dimension','representation','support','normalization'))
        for k in ('id','cell_id'):ce.identity(row[k])
        for k in ('quantity','unit'):_text(row[k])
        _dimension(row['dimension'])
        if row['representation'] not in {'raw_count','continuous_value','weighted_estimator','derived_value'}:
            raise ValueError('explicit coordinate representation required')
        if not row['support'] or not row['normalization']:raise ValueError('explicit full support/normalization required')
        ids.append(row['id'])
    if len(set(ids))!=len(ids):raise ValueError('distinct complete coordinate IDs required')
    o=c['observed'];_keys(o,('result_path','records_pointer','representation'))
    if o['result_path']!='outputs/attempt-1/result.json':raise ValueError('exact ordinary first-attempt result required')
    _locator({'source':{'path':'selector','sha256':'0'*64,'size':0},'pointer':o['records_pointer']})
    if o['representation'] not in {'observed_realization','expected_asimov','supplied_estimate'}:
        raise ValueError('observed/expected representation required')
    hypotheses=c['hypotheses']
    if type(hypotheses) is not list or len(hypotheses)<2:raise ValueError('complete rival hypothesis roster required')
    hids=[]
    for h in hypotheses:
        _keys(h,('hypothesis_id','prediction','parameters','applicability','qualification','numerical_error'))
        ce.identity(h['hypothesis_id']);hids.append(h['hypothesis_id'])
        if 'unknown' in h['prediction']:
            _keys(h['prediction'],('unknown',));_text(h['prediction']['unknown'])
        else:_locator(h['prediction'])
        for k in ('parameters','applicability'):
            if type(h[k]) is not dict:raise ValueError('explicit fixed states and applicability required')
        _text(h['qualification'])
        if type(h['numerical_error']) is not dict or h['numerical_error'].get('status') not in {'exact','supplied_bound','unknown'}:raise ValueError('explicit numerical error status required')
    if len(set(hids))!=len(hids):raise ValueError('distinct hypothesis IDs required')
    comp=c['comparison'];_keys(comp,('null_id','alternative_ids','calculation','direction'),('threshold','alpha'))
    if comp['null_id'] not in hids or type(comp['alternative_ids']) is not list or len(set(comp['alternative_ids']))!=len(comp['alternative_ids']) or set(comp['alternative_ids'])!=set(hids)-{comp['null_id']}:
        raise ValueError('complete null/alternative comparison roster required')
    if comp['calculation'] not in CALCULATIONS or comp['direction'] not in {'diagnostic_only','upper_tail'}:
        raise ValueError('supported explicit fixed calculation/direction required')
    if comp['calculation']=='fixed_poisson_threshold_power':
        _integer(comp.get('threshold'),MAX_EXACT_COUNT)
        if not 0<_number(comp.get('alpha'))<1:raise ValueError('prospective alpha strictly between zero and one required')
    elif 'threshold' in comp or 'alpha' in comp:raise ValueError('threshold/alpha only for explicit prospective count test')
    if comp['calculation'] in {'fixed_poisson_threshold_power','fixed_poisson_upper_tail'} and len(pop)!=1:
        raise ValueError('no automatic multibin count ordering/tail law')
    noise=c['noise'];_keys(noise,('kind','source','independence','conditioning','qualification','unknown_reasons'),('covariance',))
    _pin(noise['source']);_text(noise['independence']);_text(noise['qualification'])
    if noise['kind'] not in {'unknown','independent_fixed_poisson','known_fixed_joint_gaussian_residual'}:
        raise ValueError('unsupported law; supply an existing separately calibrated operation')
    if noise['conditioning'] not in {'fixed_supplied_truth','conditional_fitted_state','unconditional_complete_experiment','posterior_predictive','unknown'}:
        raise ValueError('explicit conditioning required')
    if type(noise['unknown_reasons']) is not list:raise ValueError('complete unresolved law reasons required')
    for v in noise['unknown_reasons']:_text(v)
    if noise['kind']=='known_fixed_joint_gaussian_residual':_locator(noise.get('covariance'))
    elif 'covariance' in noise:raise ValueError('no guessed covariance for a different law')
    n=c['nuisances'];_keys(n,('treatment','state','constraints','fit_evidence','fit_data_exposure','generative_scope'))
    if n['treatment'] not in {'fixed_supplied','fitted_to_same_data','fitted_to_independent_data','finite_supplied_states','posterior_integrated_existing','unknown'}:
        raise ValueError('explicit fixed/fitted nuisance treatment required')
    if type(n['state']) is not list or type(n['fit_data_exposure']) is not list:raise ValueError('complete nuisance/state/exposure roster required')
    if n['fit_evidence'] is not None:_pin(n['fit_evidence'])
    e=c['exposure'];_keys(e,('kind','record_ids','fit_record_ids','confirmation_record_ids','replicate_cluster_ids','source'))
    if e['kind'] not in {'adaptive_screen','adaptive_full','withheld_confirmation'}:raise ValueError('actual evaluation exposure required')
    _pin(e['source'])
    for k in ('record_ids','fit_record_ids','confirmation_record_ids','replicate_cluster_ids'):
        if type(e[k]) is not list:raise ValueError('complete actual exposure roster required')
        for v in e[k]:_text(v)
    if len(set(e['record_ids']))!=len(e['record_ids']):raise ValueError('duplicate sampled record IDs')
    if e['kind']=='withheld_confirmation' and (set(e['record_ids']) & set(e['fit_record_ids']) or not set(e['record_ids'])<=set(e['confirmation_record_ids'])):
        raise ValueError('withheld confirmation cannot reuse fit records')
    num=c['numerics'];_keys(num,('method','runtime_requirements','absolute_tolerance','relative_tolerance','bounds','method_source','uncertainty_status'))
    if num['method']!='fixed_binary64_scipy_1.14.1_numpy_1.26.4':raise ValueError('exact reviewed numerical method required')
    _pin(num['method_source'])
    runtime=num['runtime_requirements'];_keys(runtime,('versions','files'))
    if runtime['versions']!={'numpy':'1.26.4','scipy':'1.14.1'} or type(runtime['files']) is not list:
        raise ValueError('exact reviewed numerical runtime version/source declarations required')
    for pin in runtime['files']:_pin(pin)
    for k in ('absolute_tolerance','relative_tolerance'):
        if _number(num[k])<0:raise ValueError('nonnegative requested tolerance required')
    _keys(num['bounds'],('max_exact_count','equilibrated_condition_max','symmetry_absolute_tolerance','symmetry_relative_tolerance'))
    if num['bounds']['max_exact_count']!=MAX_EXACT_COUNT:raise ValueError('qualified exact integer domain is 0..2**53')
    if _number(num['bounds']['equilibrated_condition_max'])<1:raise ValueError('explicit dimensionless condition policy required')
    for k in ('symmetry_absolute_tolerance','symmetry_relative_tolerance'):
        if _number(num['bounds'][k])<0:raise ValueError('explicit symmetry error policy required')
    if num['uncertainty_status'] not in {'exact_analytic_definition_numerical_evaluation','supplied_numeric_error_bound','unknown'}:
        raise ValueError('explicit numerical uncertainty status required')
    f=c['decision_family'];_keys(f,('family_id','planned_tests','selection','stopping','multiplicity','inferential_scope'))
    ce.identity(f['family_id'])
    if type(f['planned_tests']) is not list or len(set(f['planned_tests']))!=len(f['planned_tests']) or c['check_id'] not in f['planned_tests']:
        raise ValueError('intact original planned test denominator required')
    for k in ('selection','stopping','multiplicity','inferential_scope'):_text(f[k])
    s=c['selection_inputs'];_keys(s,('candidate_id','obligation_ids','utility_declaration','cost','feasibility','coverage'))
    ce.identity(s['candidate_id'])
    if type(s['obligation_ids']) is not list or not s['obligation_ids']:raise ValueError('original objective obligations required')
    for i in s['obligation_ids']:ce.identity(i)
    _keys(s['cost'],('status','vector','source'));_pin(s['cost']['source'])
    if s['cost']['status'] not in {'actual','estimated','unknown'}:raise ValueError('actual/estimated/unknown cost required')
    if s['cost']['vector'] is not None:
        _keys(s['cost']['vector'],('calls','output_tokens','wall_seconds','native_attempts'))
        for v in s['cost']['vector'].values():_integer(v)
    if type(s['feasibility']) is not dict or type(s['coverage']) is not dict:raise ValueError('explicit feasibility and check coverage required')
    if s['utility_declaration'] is not None:
        u=s['utility_declaration'];_keys(u,('objective_id','source','metric','reduction','direction','definition','assumptions'))
        ce.identity(u['objective_id']);_pin(u['source']);_text(u['definition']);_text(u['assumptions'])
        if u['metric'] not in {'directed_poisson_kl','gaussian_d2','poisson_threshold_power'} or u['reduction'] not in {'minimum_alternative','maximum_alternative'} or u['direction']!='maximize':
            raise ValueError('supported explicit task objective required; no default reward')
    if type(c['source_provenance']) is not list:raise ValueError('complete source provenance required')
    for p in c['source_provenance']:_pin(p)
    _keys(c['requested_limits'],DEFAULT_LIMITS)
    for v in c['requested_limits'].values():
        if type(v) is not int or v<1:raise ValueError('positive requested resource limit required')
    _encoded(c)
    return deepcopy(c)


class Capture:
    """One bounded authenticated snapshot per source; finite ending checkpoints."""
    def __init__(self,base,resources):
        self.base=Path(base);self.resources=resources;self.rows={};self.raw={};self.started=time.monotonic()
    def checkpoint(self):
        if time.monotonic()-self.started>self.resources['wall_seconds']:
            raise ValueError('quantitative checking wall allocation exhausted')
    def read(self,pin):
        from .research_cycle import _bounded_source_snapshot
        _pin(pin);limits=self.resources['limits'];path=Path(pin['path'])
        path=(path if path.is_absolute() else self.base/path).absolute()
        key=str(path);canonical={**pin,'path':key}
        if key in self.rows:
            if self.rows[key]!=canonical:raise ValueError('source alias has conflicting quantitative identity')
            return self.raw[key]
        if (pin['size']>limits['single_bytes'] or len(self.rows)+1>limits['sources'] or
                sum(p['size'] for p in self.rows.values())+pin['size']>limits['unique_bytes']):
            raise ValueError('complete quantitative source population exceeds admitted allocation')
        self.checkpoint();_,raw=_bounded_source_snapshot(path,limits['single_bytes'])
        if len(raw)!=pin['size'] or hashlib.sha256(raw).hexdigest()!=pin['sha256']:
            raise ValueError('quantitative source bytes differ from prospective commitment')
        self.rows[key]=canonical;self.raw[key]=raw
        return raw
    def document(self,pin):
        from .review_context import _strict_json_bytes
        return _strict_json_bytes(self.read(pin))
    def locate(self,locator):
        from .research_cycle import _pointer
        _locator(locator);value=self.document(locator['source'])
        return value if locator['pointer']=='' else _pointer(value,locator['pointer'])
    def finish(self):
        from .research_cycle import _bounded_source_snapshot
        for key,p in self.rows.items():
            self.checkpoint();_,raw=_bounded_source_snapshot(Path(key),self.resources['limits']['single_bytes'])
            if raw!=self.raw[key]:raise ValueError('quantitative source changed at ending checkpoint')


def _all_pins(value):
    if type(value) is dict:
        if set(value)=={'path','sha256','size'}:
            yield _pin(value)
        else:
            for child in value.values():yield from _all_pins(child)
    elif type(value) is list:
        for child in value:yield from _all_pins(child)


def _effective_resources(c,allocation):
    """One original-request/allocation minimum for every declared limit."""
    effective=deepcopy(allocation)
    effective['limits']={key:min(c['requested_limits'][key],allocation['limits'][key]) for key in DEFAULT_LIMITS}
    return effective


def _load(binding,base):
    from .research_presentation import document
    validate_binding(binding)
    resources=validate_resources(document(binding['resources'],base,8*1024**2))
    capture=Capture(Path(binding['contract']['path']).parent,resources)
    capture.read(binding['resources'])
    c=validate_contract(capture.document(binding['contract']))
    # Admit the entire declared byte census before reading a prediction payload.
    pins=[binding['contract'],binding['resources'],*list(_all_pins(c))]
    canonical={}
    for p in pins:
        path=Path(p['path']);key=str((path if path.is_absolute() else capture.base/path).absolute())
        if key in canonical and canonical[key]!={**p,'path':key}:raise ValueError('conflicting quantitative source aliases')
        canonical[key]={**p,'path':key}
    # The two bootstrap documents were bounded by the original allocation
    # (and the resource declaration's fixed8MiB parser bound). Once the
    # contract is known, apply its stricter policy before any source payload.
    effective=_effective_resources(c,resources);lim=effective['limits']
    if len(canonical)>lim['sources'] or sum(p['size'] for p in canonical.values())>lim['unique_bytes'] or any(p['size']>lim['single_bytes'] for p in canonical.values()):
        raise ValueError('complete source census exceeds the original requested/allocation minimum; retain whole population and admit a sufficient declaration')
    capture.resources=effective
    for p in pins:capture.read(p)
    capture.finish()
    return c,resources,capture


def requirements(c,resources):
    effective=_effective_resources(c,resources)
    n=len(c['population']);h=len(c['hypotheses']);gaussian=c['noise']['kind']=='known_fixed_joint_gaussian_residual'
    required={'coordinates':n,'hypothesis_pairs':h-1,'finite_states':max(1,len(c['nuisances']['state'])),
        'matrix_elements':4*n*n if gaussian else 0,'work_units':n**3+n*n*(2*h-1)+n*h if gaussian else n*(2*h-1)}
    reasons=[]
    estimated_memory_bytes=128*1024**2 + sum(p['size'] for p in _all_pins(c))*4 + (n*n*8*12 if gaussian else n*h*64)
    if estimated_memory_bytes>resources['max_rss_mib']*1024**2:
        reasons.append('complete conservative memory estimate exceeds admitted checking RAM')
    for key,v in required.items():
        allowed=effective['limits'][key]
        if v>allowed:reasons.append(key+': complete required '+str(v)+' exceeds admitted '+str(allowed))
    return {'required':required,'estimated_memory_bytes':estimated_memory_bytes,'memory_estimate_not_measurement':True,'requested':deepcopy(c['requested_limits']),'allocation':deepcopy(resources),'effective':effective,
        'status':'pending_resources' if reasons else 'admitted','reasons':reasons,'population_truncated':False}


def inputs(binding,base_dir):
    c,r,cap=_load(binding,base_dir)
    return [Path(p['path']) for p in cap.rows.values()]


def guidance(binding,base_dir):
    c,r,cap=_load(binding,base_dir)
    return {'contract':binding['contract'],'resources':binding['resources'],'requirements':requirements(c,r),
        'planned_coordinates':[x['id'] for x in c['population']],'planned_hypotheses':[h['hypothesis_id'] for h in c['hypotheses']],
        'whole_goal':c['goal_binding'],'scope':SCOPE,'scientific_acceptance':False}


def admit_design(state,e,spec):
    observable=e['observable'];_keys(observable,('schema_version','kind','contract'))
    if type(observable['schema_version']) is not int or observable['schema_version']!=2 or observable['kind']!='quantitative':
        raise ValueError('quantitative observable/v2 required')
    binding=spec.get('quantitative_check')
    if binding is None or observable['contract']!=binding['contract']:raise ValueError('quantitative observable must bind the exact ordinary planned check')
    c,r,cap=_load(binding,state['base_dir'])
    from .research_cycle import _bindings
    if c['experiment_id']!=e['id'] or c['premise_bindings']!=_bindings(state,e['premise_ids']) or c['goal_binding']!=state['contract'].get('goal_binding'):
        raise ValueError('quantitative check must preserve exact experiment, original goal and current premises')
    if set(e['predictions'])!={h['hypothesis_id'] for h in c['hypotheses']} or any(v is not None for v in e['predictions'].values()):
        raise ValueError('complete quantitative hypotheses require null categorical predictions')
    if c['selection_inputs']['candidate_id']!=e['id'] or (c['selection_inputs']['cost']['vector'] is not None and c['selection_inputs']['cost']['vector']!=e['cost']):
        raise ValueError('quantitative selection must retain exact existing experiment/cost vector')
    if r['wall_seconds']>=spec['max_seconds']:raise ValueError('quantitative checking must fit inside the whole ordinary stage ceiling')
    return {'binding':deepcopy(binding),'guidance':guidance(binding,state['base_dir'])}


def _records(records,c,*,counts=False,expected=False):
    if type(records) is not list or len(records)!=len(c['population']):raise ValueError('complete ordered quantitative records required')
    values=[]
    for actual,coordinate in zip(records,c['population']):
        _keys(actual,('id','value','quality','unit','quantity','dimension','support','normalization'))
        for k in ('id','unit','quantity','dimension','support','normalization'):
            if _encoded(actual[k])!=_encoded(coordinate[k]):raise ValueError('coordinate identity/unit/support/normalization differs')
        if not (actual['quality'] is True or type(actual['quality']) is str and actual['quality']=='passed'):
            raise ValueError('every planned quantitative record requires actual successful quality')
        v=_number(actual['value'])
        if counts:
            if coordinate['representation']!='raw_count':raise ValueError('Poisson cannot consume weighted/effective counts')
            if expected:
                if v<0 or v>MAX_EXACT_COUNT:raise ValueError('bounded nonnegative expected count required')
            else:_integer(v,MAX_EXACT_COUNT)
        values.append(v)
    return values


def _boundary(status,**extra):
    return {'value':None,'status':status,**extra}


def _finite(value):
    if not math.isfinite(value):return _boundary('numerical_overflow')
    if value<0:return _boundary('negative_numerical_result_unresolved',raw_value=value)
    return {'value':value,'status':'evaluated','numerical_error':'unknown'}


def poisson_core(x,mu):
    """x log(x/mu)-x+mu, with exact support and stable small-delta series."""
    x=_number(x);mu=_number(mu)
    if x<0 or mu<0:raise ValueError('nonnegative Poisson operands required')
    if x==0:return {'value':mu,'status':'evaluated','numerical_error':'unknown'}
    if mu==0:return _boundary('structural_zero_support',mathematical_value='positive_infinity')
    if x==mu:return {'value':0.0,'status':'evaluated','numerical_error':'unknown'}
    delta=(x-mu)/mu
    if math.isfinite(delta) and abs(delta)<=0.125:
        # Through degree18. For |delta|<=1/8 the omitted absolute core is
        # bounded by mu*|delta|**19/(19*18*(1-|delta|)); roundoff is not certified.
        core=math.fsum(((-1)**j)*delta**j/(j*(j-1)) for j in range(2,19))
        result=_finite(mu*core)
        result['analytic_series_remainder_bound']=mu*abs(delta)**19/(19*18*(1-abs(delta)))
        result['floating_point_error']='unknown'
        return result
    try:value=x*(math.log(x)-math.log(mu))-x+mu
    except OverflowError:return _boundary('numerical_overflow')
    return _finite(value)


def _sum_stats(rows,scale=1):
    if any(r['status']=='structural_zero_support' for r in rows):return _boundary('structural_zero_support',mathematical_value='positive_infinity')
    if any(r['value'] is None for r in rows):return _boundary('numerically_unresolved',terms=rows)
    try:return _finite(scale*math.fsum(r['value'] for r in rows))
    except OverflowError:return _boundary('numerical_overflow')


def _runtime(requirements,cap):
    import numpy as np
    from scipy import stats
    expected={'numpy':'1.26.4','scipy':'1.14.1'}
    actual={k:importlib.metadata.version(k) for k in expected}
    if actual!=expected:raise ValueError('quantitative numerical runtime differs from the reviewed method')
    source=[]
    from scipy import special
    from numpy.linalg import _umath_linalg
    from numpy.core import _multiarray_umath,overrides
    from numpy.linalg import linalg as linalg_implementation
    import inspect
    public=np.linalg.solve
    # The released public callable is a compiled dispatcher. inspect.unwrap
    # follows its documented __wrapped__ chain before Python source lookup;
    # physical implementation/extension/factory files remain fully admitted.
    implementation=inspect.unwrap(public)
    if not inspect.isfunction(implementation) or implementation.__name__!='solve':
        raise ValueError('NumPy solve lacks the declared unwrapped Python implementation')
    if linalg_implementation.solve is not public:
        raise ValueError('NumPy solve export differs from its actual implementation module')
    implementation_path=Path(inspect.getfile(implementation)).absolute()
    if implementation_path!=Path(linalg_implementation.__file__).absolute():
        raise ValueError('NumPy solve implementation has a different physical module owner')
    for module in (np,np.linalg,implementation,_umath_linalg,_multiarray_umath,overrides,stats,stats.poisson.__class__,stats.chi2.__class__,stats.rv_continuous,special._ufuncs):
        path=Path(inspect.getfile(module));raw=path.read_bytes()
        source.append({'path':str(path.absolute()),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)})
    declared={str(Path(p['path']).absolute()):p for p in requirements['files']}
    if any(declared.get(p['path'])!=p for p in source):
        raise ValueError('actual selected numerical module/extension sources lack admitted exact pins')
    for pin in source:cap.read(pin)
    return np,stats,{'versions':actual,'source_files':source,
        'numpy_solve_observation':{'dispatcher_type':type(public).__module__+'.'+type(public).__name__,
            'public_export_matches_implementation_module':True,'unwrapped_python_implementation':True,
            'implementation_source':next(p for p in source if p['path']==str(implementation_path)),
            'dispatcher_extension_source':next(p for p in source if p['path']==str(Path(_multiarray_umath.__file__).absolute())),
            'wrapper_factory_source':next(p for p in source if p['path']==str(Path(overrides.__file__).absolute()))},
        'source_scope':'selected executed modules/extensions and typed wrapper identities, not complete ABI qualification','floating_point_error':'unknown'}


def poisson_tail(mu,k,stats):
    _number(mu);_integer(k,MAX_EXACT_COUNT)
    if mu<0:raise ValueError('nonnegative fixed mean required')
    if k==0:return {'value':1.0,'log_value':0.0,'status':'evaluated'}
    if mu==0:return {'value':0.0,'log_value':None,'status':'structural_zero_support','mathematical_log_value':'negative_infinity'}
    value=float(stats.poisson.sf(k-1,mu));log=float(stats.poisson.logsf(k-1,mu))
    if not math.isfinite(value) or not 0<=value<=1:return _boundary('numerically_unresolved')
    return {'value':value,'log_value':log if math.isfinite(log) else None,
        'status':'numerical_underflow' if value==0 else 'evaluated','numerical_error':'unknown'}


def poisson_mass(mu,n,stats):
    _number(mu);_integer(n,MAX_EXACT_COUNT)
    if mu<0:raise ValueError('nonnegative fixed mean required')
    if mu==0:
        return {'value':1.0,'log_value':0.0,'status':'evaluated'} if n==0 else {
            'value':0.0,'log_value':None,'status':'structural_zero_support','mathematical_log_value':'negative_infinity'}
    value=float(stats.poisson.pmf(n,mu));log=float(stats.poisson.logpmf(n,mu))
    if not math.isfinite(value) or not 0<=value<=1:return _boundary('numerically_unresolved')
    return {'value':value,'log_value':log if math.isfinite(log) else None,
        'status':'numerical_underflow' if value==0 else 'evaluated','numerical_error':'unknown'}


def _covariance(c,cap,np):
    value=cap.locate(c['noise']['covariance']);ids=[r['id'] for r in c['population']];units=[r['unit'] for r in c['population']]
    _keys(value,('kind','coordinate_ids','product_units','known_fixed'),('covariance','observed_covariance','prediction_covariance','data_prediction_covariance'))
    if value['coordinate_ids']!=ids or value['product_units']!=[[[a,b] for b in units] for a in units] or type(value['known_fixed']) is not bool:
        raise ValueError('complete covariance order/product units and fixed-law identity required')
    n=len(ids);bound=c['numerics']['bounds']
    def matrix(raw,*,symmetric):
        if type(raw) is not list or len(raw)!=n or any(type(row) is not list or len(row)!=n for row in raw):raise ValueError('complete square covariance required')
        for row in raw:
            for v in row:_number(v)
        a=np.asarray(raw,dtype=float)
        if symmetric and not np.allclose(a,a.T,atol=bound['symmetry_absolute_tolerance'],rtol=bound['symmetry_relative_tolerance']):
            raise ValueError('covariance triangles disagree; no averaging')
        # Cholesky requires exact symmetry at the numerical representation.
        # A nonzero tolerated asymmetry is still unresolved, never averaged away.
        if symmetric and not np.array_equal(a,a.T):raise ValueError('covariance asymmetry requires explicit source correction')
        return a
    if value['kind']=='residual':
        _keys(value,('kind','coordinate_ids','product_units','known_fixed','covariance'));C=matrix(value['covariance'],symmetric=True)
    elif value['kind']=='components':
        _keys(value,('kind','coordinate_ids','product_units','known_fixed','observed_covariance','prediction_covariance','data_prediction_covariance'))
        cy=matrix(value['observed_covariance'],symmetric=True);cp=matrix(value['prediction_covariance'],symmetric=True)
        cross=matrix(value['data_prediction_covariance'],symmetric=False)
        C=cy+cp-cross-cross.T
        joint=np.block([[cy,cross],[cross.T,cp]])
        if not np.isfinite(joint).all() or float(np.linalg.eigvalsh(joint).min())<0:
            raise ValueError('supplied data/prediction joint covariance is not positive semidefinite')
    else:raise ValueError('residual covariance or full shared-noise components required')
    if not np.isfinite(C).all() or (np.diag(C)<=0).any():raise ValueError('residual covariance has invalid/degenerate variance')
    return C,value


def gaussian_factor(C,bounds,np):
    scale=np.sqrt(np.diag(C));R=C/scale[:,None]/scale[None,:]
    raw_condition=float(np.linalg.cond(C));condition=float(np.linalg.cond(R))
    diagnostics={'raw_condition':raw_condition if math.isfinite(raw_condition) else None,
        'equilibrated_condition':condition if math.isfinite(condition) else None,'coordinate_scale':scale.tolist(),
        'rank':int(np.linalg.matrix_rank(R)),'full_dimension':len(C)}
    if not math.isfinite(condition) or condition>bounds['equilibrated_condition_max']:
        return _boundary('degenerate_or_unresolved_condition',diagnostics=diagnostics)
    try:L=np.linalg.cholesky(R)
    except np.linalg.LinAlgError:return _boundary('non_positive_definite_or_unresolved',diagnostics=diagnostics)
    return {'scale':scale,'L':L,'diagnostics':diagnostics,'status':'evaluated'}


def gaussian_distance(residual,C,bounds,np,*,factor=None):
    factor=gaussian_factor(C,bounds,np) if factor is None else factor
    if factor['status']!='evaluated':return deepcopy(factor)
    diagnostics=factor['diagnostics']
    whitened=np.linalg.solve(factor['L'],np.asarray(residual,dtype=float)/factor['scale'])
    result=_finite(float(np.dot(whitened,whitened)));result.update(diagnostics=diagnostics,whitened=whitened.tolist())
    if not all(math.isfinite(v) for v in result['whitened']):return _boundary('numerical_overflow',diagnostics=diagnostics)
    return result


def _validity(c,*,known_fixed=True):
    reasons=list(c['noise']['unknown_reasons'])
    if c['noise']['kind']=='unknown':reasons.append('unknown measurement law has no builtin reference distribution')
    if c['comparison']['calculation']=='raw_residual':reasons.append('raw residuals supply no reference-test distribution')
    if c['noise']['conditioning']!='fixed_supplied_truth':reasons.append('nonfixed conditioning has no builtin reference test law')
    if c['nuisances']['treatment']!='fixed_supplied':reasons.append('fitted/finite/posterior nuisance states have no builtin calibrated law')
    if c['exposure']['kind']!='withheld_confirmation':reasons.append('adaptive/selected exposure has no confirmatory family law')
    f=c['decision_family']
    if f['selection']!='predeclared' or f['stopping']!='fixed' or len(f['planned_tests'])!=1:
        reasons.append('selected/sequential/multiple family has no builtin global correction')
    if c['observed']['representation']!='observed_realization':reasons.append('expected/estimated values are not observed reference tests')
    if not known_fixed:reasons.append('estimated covariance is not a known fixed residual law')
    return {'status':'unknown' if reasons else 'conditional_on_declared_law','reasons':reasons,
        'law_qualification':c['noise']['qualification'],'global_coverage_qualified':False}


def _base(c,binding,resource):
    return {'schema_version':1,'kind':'source_bound_quantitative_predictive_evidence','status_scope':SCOPE,
        'check_id':c['check_id'],'contract':binding['contract'],'resource_allocation':binding['resources'],
        'complete_planned_population':{'coordinates':deepcopy(c['population']),'hypotheses':[h['hypothesis_id'] for h in c['hypotheses']],
            'planned_tests':deepcopy(c['decision_family']['planned_tests']),'original_goal':deepcopy(c['goal_binding'])},
        'delivery_status':'unresolved','calculation_status':'not_issued','law_qualification':c['noise']['qualification'],
        'test_validity':{'status':'unknown','reasons':['not evaluated']},'coordinates':[],'comparisons':[],
        'selection_evidence':None,'unresolved_reasons':[],'review_obligations':['Independent physical applicability and law assessment; ordinary scoped review remains mandatory.'],
        'resource_requirements':resource,'numerical_provenance':None,'input_pins':[],
        'observation':None,'scientific_acceptance':False,'physics_validated':False}


def _calculate(c,binding,resources,cap,observation,*,producer_success):
    from .research_cycle import _pointer
    required=requirements(c,resources);result=_base(c,binding,required)
    result['observation']=deepcopy(observation)
    result['coordinates']=[{**deepcopy(row),'observed':None,'predictions':{},'status':'not_issued'} for row in c['population']]
    result['comparisons']=[{'null_id':c['comparison']['null_id'],'alternative_id':i,'status':'not_issued','definition':c['comparison']['calculation']} for i in c['comparison']['alternative_ids']]
    if not producer_success:
        result['delivery_status']='failed';result['unresolved_reasons']=['actual ordinary producer did not deliver successful complete evidence']
        return result
    if required['status']!='admitted':result['unresolved_reasons']=required['reasons'];return result
    predictions={};errors=[]
    for h in c['hypotheses']:
        identity=h['hypothesis_id']
        try:
            if 'unknown' in h['prediction']:raise ValueError(h['prediction']['unknown'])
            v=_records(cap.locate(h['prediction']),c)
            if c['noise']['kind']=='independent_fixed_poisson' and (any(x<0 or x>MAX_EXACT_COUNT for x in v) or any(row['representation']!='raw_count' for row in c['population'])):raise ValueError('bounded nonnegative fixed raw-count means required')
            predictions[identity]=v
        except (ValueError,KeyError,IndexError,TypeError) as exc:errors.append(identity+': '+str(exc))
    observed=None
    if observation is not None:
        try:
            source=cap.document(observation);pointer=c['observed']['records_pointer']
            records=source if pointer=='' else _pointer(source,pointer)
            observed=_records(records,c,counts=c['noise']['kind']=='independent_fixed_poisson',expected=c['observed']['representation']!='observed_realization')
        except (ValueError,KeyError,IndexError,TypeError) as exc:errors.append('observed: '+str(exc))
    for i,row in enumerate(result['coordinates']):
        row.update(observed=None if observed is None else observed[i],predictions={h:v[i] for h,v in predictions.items()},
            status='evaluated' if not errors else 'unresolved')
    if errors:
        result['unresolved_reasons']=errors;result['delivery_status']='partial' if predictions or observed is not None else 'unresolved';return result
    calculation=c['comparison']['calculation'];noise=c['noise']['kind'];null=c['comparison']['null_id']
    result['test_validity']=_validity(c)
    np=stats=None;runtime={'method':'binary64 stable fixed-law algebra','floating_point_error':'unknown'}
    if noise=='known_fixed_joint_gaussian_residual' or calculation in {'fixed_poisson_upper_tail','fixed_poisson_threshold_power'}:
        np,stats,runtime=_runtime(c['numerics']['runtime_requirements'],cap)
    covariance=None;covdoc=None
    if noise=='known_fixed_joint_gaussian_residual':
        covariance,covdoc=_covariance(c,cap,np);result['test_validity']=_validity(c,known_fixed=covdoc['known_fixed'])
    factor=None;mahalanobis=None
    if covariance is not None:
        factor=gaussian_factor(covariance,c['numerics']['bounds'],np)
        if observed is not None:
            mahalanobis={h:gaussian_distance([y-m for y,m in zip(observed,v)],covariance,c['numerics']['bounds'],np,factor=factor) for h,v in predictions.items()}
    pairs=[]
    for alternative in c['comparison']['alternative_ids']:
        cap.checkpoint();m0=predictions[null];m1=predictions[alternative]
        pair={'null_id':null,'alternative_id':alternative,'definition':calculation,'scope':'pointwise supplied states; no global identifiability claim','status':'evaluated'}
        if calculation=='raw_residual':
            difference=[b-a for a,b in zip(m0,m1)]
            if not all(math.isfinite(v) for v in difference):pair.update(status='unsupported',reason='raw residual numerical overflow')
            else:pair['mean_difference']=difference
            if observed is not None:
                residuals={h:[y-m for y,m in zip(observed,v)] for h,v in predictions.items()}
                if not all(math.isfinite(x) for v in residuals.values() for x in v):pair.update(status='unsupported',reason='raw observed residual numerical overflow')
                else:pair['observed_residuals']=residuals
        elif noise=='independent_fixed_poisson' and calculation.startswith('fixed_poisson'):
            pair['directed_kl']=_sum_stats([poisson_core(a,b) for a,b in zip(m1,m0)])
            if observed is not None:
                pair['deviance']={h:_sum_stats([poisson_core(n,mu) for n,mu in zip(observed,v)],2) for h,v in predictions.items()}
            if calculation=='fixed_poisson_upper_tail':
                if observed is None or c['observed']['representation']!='observed_realization':pair['tail']=_boundary('not_an_observed_raw_count')
                else:
                    pair['tail']=poisson_tail(m0[0],observed[0],stats)
                    pair['point_probability']=poisson_mass(m0[0],observed[0],stats)
                    pair['probability_scope']='model-relative fixed-mean probability; reference-test validity is separate'
            if calculation=='fixed_poisson_threshold_power':
                k=c['comparison']['threshold'];size=poisson_tail(m0[0],k,stats);power=poisson_tail(m1[0],k,stats)
                pair.update(threshold=k,nominal_alpha=c['comparison']['alpha'],size=size,power=power,
                    size_attained=(size['value']<=c['comparison']['alpha']) if size['status'] in {'evaluated','structural_zero_support'} else None)
        elif noise=='known_fixed_joint_gaussian_residual' and calculation.startswith('known_gaussian'):
            pair['d2']=gaussian_distance([b-a for a,b in zip(m0,m1)],covariance,c['numerics']['bounds'],np,factor=factor)
            if observed is not None:
                pair['mahalanobis']=deepcopy(mahalanobis)
                if result['test_validity']['status']=='conditional_on_declared_law':
                    pair['conditional_chi_square_tails']={h:_gaussian_tail(q,len(observed),stats) for h,q in pair['mahalanobis'].items()}
            pair['kl_common_covariance']={'value':None if pair['d2']['value'] is None else pair['d2']['value']/2,'status':pair['d2']['status'],'not_power':True}
        else:pair.update(status='unsupported',reason='requested probabilistic calculation has no admitted matching law')
        pairs.append(pair)
    result.update(comparisons=pairs,delivery_status='complete',calculation_status='evaluated',numerical_provenance=runtime)
    result['selection_evidence']=_selection(c,pairs,known_fixed=covdoc is None or covdoc['known_fixed'])
    statistics=[]
    def collect(v):
        if type(v) is dict:
            if 'value' in v and 'status' in v:statistics.append(v)
            for child in v.values():collect(child)
        elif type(v) is list:
            for child in v:collect(child)
    collect(pairs)
    if any(v['status'] in {'numerical_overflow','numerically_unresolved','negative_numerical_result_unresolved','numerical_underflow'} for v in statistics):
        result['calculation_status']='numerically_unresolved'
        result['unresolved_reasons'].append('some full-population numerical information is unresolved; no fabricated error bound')
    elif any(v['status'] in {'degenerate_or_unresolved_condition','non_positive_definite_or_unresolved'} for v in statistics):
        result['calculation_status']='degenerate'
        result['unresolved_reasons'].append('residual covariance is singular or numerically unresolved under the declared policy')
    if any(p['status']=='unsupported' for p in pairs):
        result.update(calculation_status='unsupported',delivery_status='unresolved',unresolved_reasons=[p['reason'] for p in pairs if p['status']=='unsupported'])
    return result


def _gaussian_tail(stat,dimension,stats):
    if stat['value'] is None:
        # No full-rank Gaussian statistic exists to transform into a reference
        # tail here. Preserve its actual covariance/numerical cause, rather
        # than manufacture a new tail-evaluation failure that masks it.
        unavailable=deepcopy(stat)
        unavailable.update(reference_tail_evaluation='not_evaluated',
            interpretation='conditional known fixed full-rank Gaussian reference tail requires an available statistic')
        return unavailable
    value=float(stats.chi2.sf(stat['value'],dimension));log=float(stats.chi2.logsf(stat['value'],dimension))
    if not math.isfinite(value) or not 0<=value<=1:return _boundary('numerically_unresolved')
    return {'value':value,'log_value':log if math.isfinite(log) else None,
        'status':'numerical_underflow' if value==0 else 'evaluated','numerical_error':'unknown',
        'interpretation':'conditional known fixed full-rank Gaussian reference probability; applicability remains declared'}


def _selection(c,pairs,*,known_fixed=True):
    supplied=c['selection_inputs'];u=supplied['utility_declaration'];values=[];reason='no explicit task objective'
    if u is not None:
        field={'directed_poisson_kl':'directed_kl','gaussian_d2':'d2','poisson_threshold_power':'power'}[u['metric']]
        for pair in pairs:
            stat=pair.get(field)
            if not stat or stat.get('status')!='evaluated' or stat.get('value') is None:reason='complete finite objective metric unresolved';break
            if field=='power' and pair.get('size_attained') is not True:reason='prospective threshold does not attain declared size';break
            values.append(stat['value'])
        if len(values)==len(pairs) and pairs:reason=None
    if c['noise']['conditioning']!='fixed_supplied_truth' or c['nuisances']['treatment']!='fixed_supplied' or c['noise']['unknown_reasons']:
        reason='full fixed-law/nuisance separation assumptions unresolved'
    if not known_fixed:reason='estimated covariance has no known fixed-law separation utility'
    if supplied['feasibility'].get('status')!='feasible':reason='declared feasibility unresolved'
    value=None if reason is not None else (min(values) if u['reduction']=='minimum_alternative' else max(values))
    # No automatic division by cost, KL-to-power conversion or inferred prior.
    return {**deepcopy(supplied),'hypothesis_ids':[h['hypothesis_id'] for h in c['hypotheses']],
        'cell_ids':[r['cell_id'] for r in c['population']],'prospective_separation':deepcopy(pairs),
        'utility':{'value':value,'status':'unknown' if value is None else 'declared_objective_diagnostic','reason':reason},
        'comparability':None if u is None else {'objective':u,'noise':deepcopy(c['noise']),
            'nuisances':deepcopy(c['nuisances']),'population':deepcopy(c['population']),'decision_family':deepcopy(c['decision_family'])},
        'global_identifiability_qualified':False,'scientific_acceptance':False}


def evaluate(binding,observation_pin,*,base_dir,producer_success=True):
    c,r,cap=_load(binding,base_dir)
    value=_calculate(c,binding,r,cap,observation_pin,producer_success=producer_success)
    cap.finish();value['input_pins']=list(cap.rows.values());_encoded(value)
    return value


def separation(binding,*,base_dir):
    """Prospective source-bound comparison, not an observed outcome or power certificate."""
    c,r,cap=_load(binding,base_dir)
    value=_calculate(c,binding,r,cap,None,producer_success=True)
    cap.finish();value['input_pins']=list(cap.rows.values());_encoded(value)
    return value


class Delivery:
    """Keep original producer/result/evidence commitments through common delivery."""
    def __init__(self,binding,base,result_path,producer_success):
        from .research_cycle import _pin
        self.binding=deepcopy(binding);self.base=base;self.observation=_pin(result_path)
        self.value=evaluate(binding,self.observation,base_dir=base,producer_success=producer_success)
        self.intended=_encoded(self.value);self.output=None;self.report=None;self.report_bytes=markdown(self.value).encode()
    def write(self,path):
        from .state_io import atomic_json
        from .research_cycle import _pin
        if Path(path).exists():raise ValueError('fresh quantitative output required')
        atomic_json(path,deepcopy(self.value));self.output=_pin(path)
        report=Path(path).with_suffix('.md')
        if report.exists():raise ValueError('fresh quantitative report required')
        report.write_bytes(self.report_bytes);self.report=_pin(report);self.finish()
    def finish(self):
        from .research_presentation import document
        from .research_cycle import _check_pin
        if _encoded(self.value)!=self.intended:raise ValueError('returned quantitative result differs from intended commitment')
        for pin in [self.observation,*self.value['input_pins']]:_check_pin(pin,self.base)
        if self.report is not None:
            path,_=_check_pin(self.report,self.base)
            if path.read_bytes()!=self.report_bytes:raise ValueError('quantitative report differs from original intended bytes')
        if self.output is not None:
            delivered=document(self.output,self.base,64*1024**2)
            if _encoded(delivered)!=self.intended:raise ValueError('durable quantitative output differs from intended commitment')


def verify_value(binding,value,*,base_dir,observation_pin):
    from .research_presentation import document
    from .research_cycle import _check_pin
    c,r,cap=_load(binding,base_dir)
    if (value.get('kind')!='source_bound_quantitative_predictive_evidence' or value.get('contract')!=binding['contract'] or
            value.get('resource_allocation')!=binding['resources'] or value.get('observation')!=observation_pin or
            value.get('scientific_acceptance') is not False or value.get('physics_validated') is not False or
            _encoded(value.get('complete_planned_population'))!=_encoded(_base(c,binding,requirements(c,r))['complete_planned_population'])):
        raise ValueError('quantitative evidence differs from exact planned source/population/producer binding')
    if value.get('delivery_status')=='complete':
        derived={h['hypothesis_id']:_records(cap.locate(h['prediction']),c) for h in c['hypotheses']}
        observed=None
        if observation_pin is not None:
            from .research_cycle import _pointer
            source=cap.document(observation_pin);pointer=c['observed']['records_pointer']
            records=source if pointer=='' else _pointer(source,pointer)
            observed=_records(records,c,counts=c['noise']['kind']=='independent_fixed_poisson',expected=c['observed']['representation']!='observed_realization')
        coordinates=value.get('coordinates')
        if type(coordinates) is not list or len(coordinates)!=len(c['population']):raise ValueError('complete delivered quantitative coordinate roster required')
        for i,(row,coordinate) in enumerate(zip(coordinates,c['population'])):
            intended={**coordinate,'observed':None if observed is None else observed[i],
                'predictions':{h:values[i] for h,values in derived.items()},'status':'evaluated'}
            if _encoded(row)!=_encoded(intended):raise ValueError('delivered numeric types/values differ from actual full source population')
        pairs=value.get('comparisons')
        if type(pairs) is not list or [(p.get('null_id'),p.get('alternative_id'),p.get('definition')) for p in pairs]!=[(c['comparison']['null_id'],i,c['comparison']['calculation']) for i in c['comparison']['alternative_ids']]:
            raise ValueError('complete delivered comparison family differs')
    expected=list(cap.rows.values())
    for p in value['input_pins']:_check_pin(p,base_dir)
    actual={p['path']:p for p in value['input_pins']}
    if any(actual.get(p['path'])!=p for p in expected):raise ValueError('quantitative evidence lost required original source closure')
    if observation_pin is not None:_check_pin(observation_pin,base_dir)
    cap.finish()
    return value


def choose_declared(rows):
    """Use one explicit comparable objective only AFTER ordinary eligibility."""
    if not rows:return None
    evidence=[r.get('quantitative_selection') for r in rows]
    if any(e is None or e['utility']['value'] is None for e in evidence):return None
    identities=[_encoded(e['comparability']) for e in evidence]
    if len(set(identities))!=1:return None
    return min(rows,key=lambda r:(-r['quantitative_selection']['utility']['value'],r['cost']['native_attempts'],r['cost']['wall_seconds'],r['id']))


def verify_evidence(binding,evidence_pin,observation_pin,*,base_dir):
    from .research_presentation import document
    c,r,cap=_load(binding,base_dir)
    value=document(evidence_pin,base_dir,r['limits']['unique_bytes'])
    return verify_value(binding,value,base_dir=base_dir,observation_pin=observation_pin)


def markdown(value):
    """Entire diagnostic denominator, with no confidence/acceptance relabeling."""
    def cell(x):return str(x).replace('|','\\|').replace('\n',' ')
    lines=['# Quantitative predictive diagnostic','',
        'Scope: '+SCOPE+'. Scientific acceptance: false.',
        'Delivery: '+value['delivery_status']+'; calculation: '+value['calculation_status']+'.',
        'Reference-test validity: '+value['test_validity']['status']+'.',
        'Law qualification: '+value['law_qualification']+'.','',
        '| Coordinate | Quantity | Unit | Observation | Predictions | Status |',
        '|---|---|---|---|---|---|']
    for row in value['coordinates']:
        lines.append('| '+' | '.join(cell(row[k]) for k in ('id','quantity','unit','observed','predictions','status'))+' |')
    lines+=['','Complete comparison definitions/results:','']
    for row in value['comparisons']:lines.append('- '+cell(json.dumps(row,sort_keys=True,allow_nan=False)))
    lines+=['','Unresolved obligations:']+[('- '+cell(reason)) for reason in value['unresolved_reasons']]
    lines+=['','Selection is a caller-declared objective diagnostic. KL and Gaussian distance are not automatic power or universal utility.',
        'Original goal and all planned tests remain in quantitative-check.json/result.json. Independent review and authority gates remain required.']
    return '\n'.join(lines)+'\n'
