"""Typed official CAMB/CLASS/Cobaya operations on the ordinary science lifecycle.

No solver is imported during validation or preparation. Native code is trusted,
source/runtime bound and delegated by a live approved worker. Linear profiles
are explicit flat, massless-neutrino LCDM; Cobaya evaluates supplied models,
not samplers. Supplied covariance is carried to existing measurement intake.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = 'ravel.physics'
from ravel.workflow import science, execution, operation_resources
from ravel.workflow.state_io import atomic_json, _unique

VERSIONS = {'camb': '1.6.5', 'class': '3.4.1', 'cobaya': '3.6.2', 'camb+class': '1.6.5+3.4.1'}
MODULES = {'camb': 'camb', 'class': 'classy', 'cobaya': 'cobaya'}
ENGINES = {'camb': ('camb',), 'class': ('class',), 'cobaya': ('cobaya',), 'camb+class': ('camb', 'class')}
CMB_PROFILE = 'lensed-cmb-cl'
CMB_PARAMS = {'mnu_ev', 'num_massive_nu'}
CMB_SPECTRA = ('TT', 'EE', 'BB', 'TE')
CAMB_COLUMNS = {'TT': 0, 'EE': 1, 'BB': 2, 'TE': 3}
# CLASS massless-species count for one massive species at T_ncdm=0.71611 (CLASS explanatory.ini).
CLASS_NEFF_PER_MASSIVE = 1.0132
CMB_SCOPE = 'complete lensed CMB C_ell delivery'

SCOPE = 'complete finite supplied cosmology solver output delivery'
PARAMS = {'H0','omega_b','omega_cdm','A_s','n_s','tau','T_CMB','YHe','N_eff'}
C_KM_S = 299792.458

def _keys(v, names, label):
    if type(v) is not dict or set(v) != set(names): raise ValueError('closed '+label+' fields required')
def _num(v, label):
    if type(v) not in (int,float) or not math.isfinite(v): raise ValueError('finite '+label+' required')
    return float(v)
def _native_scalar(value,label):
    """Only actual real numeric NumPy scalars/0d arrays extend native returns.

    Closed JSON/parameter numbers still use _num. Bool, vector, object, complex
    and nonfinite native returns are never coerced into scientific numbers.
    """
    if type(value)in (int,float):return _num(value,label)
    if (type(value).__module__.split('.')[0]=='numpy'
            and getattr(value,'shape',None)==()
            and getattr(getattr(value,'dtype',None),'kind',None)in ('f','i','u')):
        return _num(value.item(),label)
    raise ValueError('finite real native scalar required: '+label)

def _camb_support(d,raw):
    _keys(raw,('kmin','kmax','zmin','zmax'),'actual CAMB interpolation support')
    limits={k:_native_scalar(v,'CAMB '+k)for k,v in raw.items()}
    if not (0<limits['kmin']<=limits['kmax'] and 0<=limits['zmin']<=limits['zmax']):
        raise ValueError('invalid actual CAMB interpolation support domain')
    requested={'k_h_mpc':deepcopy(d['grid']['k_h_mpc']),'redshifts':deepcopy(d['grid']['redshifts'])}
    if (any(not limits['kmin']<=k<=limits['kmax']for k in requested['k_h_mpc'])
            or any(not limits['zmin']<=z<=limits['zmax']for z in requested['redshifts'])):
        raise ValueError('requested grid outside actual CAMB interpolation support; no extrapolation')
    return {'status':'admitted','raw_support':_raw(raw),'limits':limits,
            'k_unit':'h/Mpc','z_unit':'1','requested':requested,'extrapolation':False}

def _name(v):
    if type(v) is not str or not re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,63}',v): raise ValueError('bounded identifier required')
    return v

def _read(path, expected=None):
    p=operation_resources.document_pin(path)
    if hashlib.sha256(p['text'].encode('utf-8')).hexdigest()!=p['sha256'] or expected is not None and p['sha256']!=expected: raise ValueError('consumed document digest differs')
    def bad(x): raise ValueError('nonfinite JSON constant')
    def number(x): return _num(float(x),'JSON number')
    return json.loads(p['text'],object_pairs_hook=_unique,parse_constant=bad,parse_float=number)

def _pin(value, base):
    _keys(value,('path','sha256'),'pin')
    if type(value['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}',value['sha256']): raise ValueError('SHA256 required')
    path=science.regular(value['path'],base)
    if execution.file_hash(path)!=value['sha256']: raise ValueError('source/runtime/scientific pin changed')
    return path

def _vector(v, label, lower, upper):
    if type(v) is not list or not 1<=len(v)<=256: raise ValueError('bounded nonempty '+label+' grid required')
    values=[_num(x,label) for x in v]
    if len(set(values))!=len(values) or values!=sorted(values) or any(not lower<=x<=upper for x in values): raise ValueError('strict ordered '+label+' grid/domain required')
    return values

def _linear_parameters(v):
    _keys(v,PARAMS,'flat massless LCDM parameter')
    d={k:_num(x,k) for k,x in v.items()}
    if not (20<=d['H0']<=100 and 0<d['omega_b']<1 and 0<d['omega_cdm']<1
            and 0<d['A_s']<=1e-7 and .5<=d['n_s']<=1.5 and 0<=d['tau']<=1
            and 1<=d['T_CMB']<=5 and 0<d['YHe']<1 and 0<=d['N_eff']<=10): raise ValueError('outside declared finite linear parameter domain')
    return d

def _cmb_parameters(v):
    _keys(v,PARAMS|CMB_PARAMS,'lensed CMB LCDM parameter')
    base=_linear_parameters({k:v[k] for k in PARAMS})
    m=_num(v['mnu_ev'],'mnu_ev');n=v['num_massive_nu']
    if type(n) is not int or n not in (0,1) or not 0<=m<=3 or (n==0)!=(m==0):raise ValueError('mnu_ev with num_massive_nu 1, or zero mass with 0, required')
    if n and base['N_eff']<CLASS_NEFF_PER_MASSIVE:raise ValueError('N_eff below the massive-species contribution')
    return {**base,'mnu_ev':m,'num_massive_nu':n}

def _cmb_grid(g):
    _keys(g,('ell_max','spectra'),'lensed CMB grid')
    if type(g['ell_max']) is not int or not 2<=g['ell_max']<=5000:raise ValueError('integer ell_max from 2 to 5000 required')
    s=g['spectra']
    if type(s) is not list or not s or len(set(s))!=len(s) or any(x not in CMB_SPECTRA for x in s):raise ValueError('distinct spectra from TT, EE, BB, TE required')
    return g

def _no_code(v):
    if type(v) is dict:
        for k,x in v.items():
            if k in {'external','python_path','class','install','sampler','output','resume','force','test'}: raise ValueError('dynamic code/install/sampling/output options not admitted')
            _no_code(x)
    elif type(v) is list:
        for x in v:_no_code(x)
    elif type(v) is str:
        if '__import__' in v or 'lambda' in v or '\x00' in v: raise ValueError('executable expression not admitted')
    elif type(v) in (float,int):_num(v,'literal')
    elif v is not None and type(v) is not bool:raise ValueError('JSON configuration required')

def validate_document(d):
    _keys(d,('schema_version','engine','source','profile','points','grid','model','components',
             'runtime','trusted_runtime','operation_resources','max_ram_mib','measurement'),'cosmology operation')
    if type(d['schema_version']) is not int or d['schema_version']!=1 or d['engine'] not in VERSIONS:raise ValueError('supported schema1 official engine required')
    if d['profile']==CMB_PROFILE:return _validate_cmb(d)
    if d['engine']=='camb+class':raise ValueError('the cross-engine comparison is defined for the lensed CMB profile')
    if type(d['source']) is not str or not d['source'].strip() or d['trusted_runtime'] is not True:raise ValueError('attributed trusted source/runtime required')
    r=operation_resources.validate(d['operation_resources'])
    if not 1<=r['solver_evaluations']<=64 or r['max_seconds']>900:raise ValueError('finite64-evaluation/900s solver ceiling')
    if type(d['max_ram_mib']) is not int or not 512<=d['max_ram_mib']<=8192:raise ValueError('512..8192MiB sampled RSS bound required')
    _keys(d['runtime'],('python','manifest'),'runtime')
    if type(d['points']) is not list or len(d['points'])!=r['solver_evaluations']:raise ValueError('complete declared per-point solver evaluation count required')
    ids=[]
    for p in d['points']:
        _keys(p,('id','parameters'),'point');ids.append(_name(p['id']))
        if d['engine']=='cobaya':
            if type(p['parameters']) is not dict or not p['parameters']:raise ValueError('explicit sampled parameter values required')
            for k,v in p['parameters'].items():_name(k);_num(v,k)
        else:_linear_parameters(p['parameters'])
    if len(set(ids))!=len(ids):raise ValueError('distinct point identities required')
    if d['engine']=='cobaya':
        if d['profile']!='logposterior' or d['grid'] is not None or d['measurement'] is not None:raise ValueError('Cobaya posterior profile has no fabricated power grid/covariance')
        _keys(d['components'],('priors','likelihoods','derived','derived_units'),'complete expected Cobaya component')
        for k in ('priors','likelihoods','derived'):
            values=d['components'][k]
            if type(values) is not list or len(values)!=len(set(values)) or len(values)>256 or any(type(x)is not str or not re.fullmatch('[A-Za-z0-9_.-]{1,64}',x) for x in values):raise ValueError('complete named component list required')
        if not d['components']['priors'] or not d['components']['likelihoods']:raise ValueError('explicit priors/likelihoods required')
        if len(d['points'])*(1+sum(len(d['components'][k]) for k in ('priors','likelihoods','derived')))>4096:raise ValueError('4096 posterior cell ceiling')
        units=d['components']['derived_units']
        if type(units)is not dict or set(units)!=set(d['components']['derived']) or any(type(x)is not str or not x.strip() for x in units.values()):raise ValueError('explicit complete derived quantity units required')
    else:
        if d['profile']!='flat-massless-lcdm-linear' or d['model'] is not None or d['components'] is not None:raise ValueError('explicit first linear profile required')
        _keys(d['grid'],('k_h_mpc','redshifts','background_redshifts'),'observable grid')
        _vector(d['grid']['k_h_mpc'],'k/h',1e-5,10);_vector(d['grid']['redshifts'],'redshift',0,20);_vector(d['grid']['background_redshifts'],'background redshift',0,20)
        if len(d['points'])*(len(d['grid']['k_h_mpc'])*len(d['grid']['redshifts'])+2*len(d['grid']['background_redshifts']))>4096:raise ValueError('4096 observable cell ceiling')
    return deepcopy(d)

def _validate_cmb(d):
    if d['engine']=='cobaya':raise ValueError('lensed CMB profile uses CAMB, CLASS or camb+class')
    if type(d['source']) is not str or not d['source'].strip() or d['trusted_runtime'] is not True:raise ValueError('attributed trusted source/runtime required')
    r=operation_resources.validate(d['operation_resources'])
    if r['max_seconds']>900:raise ValueError('900s solver ceiling')
    if type(d['max_ram_mib']) is not int or not 512<=d['max_ram_mib']<=8192:raise ValueError('512..8192MiB sampled RSS bound required')
    _keys(d['runtime'],('python','manifest'),'runtime')
    if d['model'] is not None or d['components'] is not None or d['measurement'] is not None:raise ValueError('lensed CMB profile has no model, components or measurement bridge')
    _cmb_grid(d['grid'])
    if type(d['points']) is not list or not 1<=len(d['points'])<=16:raise ValueError('one to sixteen points required')
    if r['solver_evaluations']!=len(d['points'])*len(ENGINES[d['engine']]):raise ValueError('solver evaluations must equal points times engines')
    ids=[]
    for p in d['points']:
        _keys(p,('id','parameters'),'point');ids.append(_name(p['id']));_cmb_parameters(p['parameters'])
    if len(set(ids))!=len(ids):raise ValueError('distinct point identities required')
    return deepcopy(d)

def cmb_cells(d,pid,engine):
    g=d['grid']
    return [{'id':f'{pid}:{engine}:cl:{x}','quantity':'lensed_cl_'+x,'engine':engine,'ell_min':2,'ell_max':g['ell_max'],'unit':'muK^2'} for x in g['spectra']]

def _array(value,label):
    value=value.tolist() if hasattr(value,'tolist') else value
    if type(value) not in (list,tuple):raise ValueError('native array required: '+label)
    return value

def _execute_cmb(d,apis,write):
    """Lensed C_ell from each selected engine at each point, in muK^2 for ell=2..ell_max."""
    events=[];results=[];state={'declared_points':[p['id'] for p in d['points']],'points':results,'calls':events,'solver_calls_started':0,'solver_calls_returned':0,'interpolation_support':{},'status':'running'}
    def call(pid,op,fn,solver=False):
        row={'point':pid,'operation':op,'solver_evaluation':solver,'status':'started'};events.append(row)
        if solver:state['solver_calls_started']+=1
        write(deepcopy(state))
        try:value=fn()
        except BaseException as error:
            row.update(status='failed',error_type=type(error).__name__,error=str(error));write(deepcopy(state));raise
        row.update(status='returned',raw_return=_raw(value))
        if solver:state['solver_calls_returned']+=1
        write(deepcopy(state));return value
    lmax=d['grid']['ell_max'];engines=ENGINES[d['engine']]
    try:
        for point in d['points']:
            pid=point['id'];p=point['parameters'];cells=[]
            for engine in engines:
                api=apis[engine] if d['engine']=='camb+class' else apis
                columns=_cmb_native(engine,api,p,lmax,pid,call)
                for cell in cmb_cells(d,pid,engine):
                    values=columns[cell['quantity'][-2:]]
                    cells.append({**cell,'values':[_num(float(x),'C_ell') for x in values]})
            results.append({'id':pid,'parameters':deepcopy(p),'cells':cells});write(deepcopy(state))
        state['status']='passed'
    except BaseException as error:
        state['status']='failed';state['failure']={'type':type(error).__name__,'message':str(error)}
        raise
    finally:
        state['uncompleted_points']=[p['id'] for p in d['points'] if p['id']not in {r['id'] for r in results}]
        write(deepcopy(state))
    if state['solver_calls_started']!=d['operation_resources']['solver_evaluations'] or state['solver_calls_returned']!=state['solver_calls_started']:raise ValueError('actual solver invocation count differs')
    return state

def _cmb_native(engine,api,p,lmax,pid,call):
    """One engine solve; returns muK^2 columns for ell=2..lmax keyed by spectrum."""
    if engine=='camb':
        pars=api.CAMBparams()
        pars.set_cosmology(H0=p['H0'],ombh2=p['omega_b'],omch2=p['omega_cdm'],omk=0,mnu=p['mnu_ev'],num_massive_neutrinos=p['num_massive_nu'],nnu=p['N_eff'],YHe=p['YHe'],TCMB=p['T_CMB'],tau=p['tau'])
        pars.InitPower.set_params(As=p['A_s'],ns=p['n_s']);pars.set_for_lmax(lmax,lens_potential_accuracy=1)
        data=call(pid,'camb:get_results',lambda:api.get_results(pars),True)
        raw=call(pid,'camb:lensed_cls',lambda:data.get_cmb_power_spectra(pars,CMB_unit='muK',raw_cl=True,lmax=lmax,spectra=['total']))
        rows=_array(raw['total'],'CAMB total')
        if len(rows)<lmax+1:raise ValueError('CAMB returned fewer multipoles than requested')
        return {x:[_array(rows[l],'CAMB row')[c] for l in range(2,lmax+1)] for x,c in CAMB_COLUMNS.items()}
    data=api.Class()
    settings={'h':p['H0']/100,'omega_b':p['omega_b'],'omega_cdm':p['omega_cdm'],'A_s':p['A_s'],'n_s':p['n_s'],'tau_reio':p['tau'],
        'T_cmb':p['T_CMB'],'YHe':p['YHe'],'N_ur':p['N_eff']-CLASS_NEFF_PER_MASSIVE*p['num_massive_nu'],'N_ncdm':p['num_massive_nu'],
        'Omega_k':0,'output':'tCl,pCl,lCl','lensing':'yes','l_max_scalars':lmax+500}
    if p['num_massive_nu']:settings['m_ncdm']=p['mnu_ev']
    try:
        data.set(settings);call(pid,'class:compute',lambda:data.compute(),True)
        raw=call(pid,'class:lensed_cls',lambda:data.lensed_cl(lmax))
        factor=(p['T_CMB']*1e6)**2
        out={}
        for x in CMB_SPECTRA:
            column=_array(raw[x.lower()],'CLASS '+x)
            if len(column)<lmax+1:raise ValueError('CLASS returned fewer multipoles than requested')
            out[x]=[float(column[l])*factor for l in range(2,lmax+1)]
        return out
    finally:
        data.struct_cleanup();data.empty()

def _complete_cmb(d,result):
    if (result.get('status')!='passed' or result.get('engine')!=d['engine'] or result.get('version')!=VERSIONS[d['engine']]
        or result.get('operation_resources')!=d['operation_resources'] or result.get('physics_validated')is not False):raise ValueError('native delivery scope differs')
    if [r['id'] for r in result['points']]!=[p['id'] for p in d['points']] or result['uncompleted_points']:raise ValueError('complete point population required')
    engines=ENGINES[d['engine']];n=d['grid']['ell_max']-1
    if result['solver_calls_started']!=len(d['points'])*len(engines) or result['solver_calls_returned']!=result['solver_calls_started']:raise ValueError('actual parameter-point solver count differs')
    expected_calls=[];comparison=[]
    for original,point in zip(d['points'],result['points']):
        if point['parameters']!=original['parameters']:raise ValueError('native parameter point differs')
        cells=[]
        for engine in engines:
            cells+=cmb_cells(d,point['id'],engine)
            expected_calls+=[(point['id'],engine+(':get_results' if engine=='camb' else ':compute')),(point['id'],engine+':lensed_cls')]
        if len(point['cells'])!=len(cells):raise ValueError('complete spectrum population required')
        by={}
        for a,b in zip(point['cells'],cells):
            if {k:v for k,v in a.items() if k!='values'}!=b:raise ValueError('spectrum identity/order/unit differs')
            if type(a['values'])is not list or len(a['values'])!=n:raise ValueError('complete multipole population required')
            raw=next(r['raw_return'] for r in result['calls'] if r['point']==point['id'] and r['operation']==b['engine']+':lensed_cls')
            x=b['quantity'][-2:]
            if b['engine']=='camb':native=[raw['total'][l][CAMB_COLUMNS[x]] for l in range(2,n+2)]
            else:native=[v*(original['parameters']['T_CMB']*1e6)**2 for v in raw[x.lower()][2:n+2]]
            if [_num(v,'C_ell') for v in a['values']]!=native:raise ValueError('delivered C_ell differs from retained raw return')
            if x in ('TT','EE','BB') and any(v<0 for v in a['values']):raise ValueError('negative auto spectrum')
            by[(b['engine'],x)]=a['values']
        if len(engines)==2:comparison.append(_compare(point['id'],d['grid']['spectra'],by))
    if [(r.get('point'),r.get('operation')) for r in result['calls']]!=expected_calls:raise ValueError('complete retained native operation population differs')
    if len(engines)==2:result=dict(result,comparison=comparison)
    return result

def _compare(pid,spectra,by,reference='class',other='camb'):
    rows=[]
    for x in spectra:
        a,b=by[(other,x)],by[(reference,x)]
        if x=='TE':
            norm=[math.sqrt(t*e) for t,e in zip(by[(reference,'TT')] if (reference,'TT') in by else b,by[(reference,'EE')] if (reference,'EE') in by else b)]
            label='sqrt(C_TT C_EE) of the reference engine'
        else:norm=b;label='C_ell of the reference engine'
        rel=[abs(p-q)/abs(n) if n else math.inf for p,q,n in zip(a,b,norm)]
        worst=max(range(len(rel)),key=lambda i:rel[i])
        rows.append({'spectrum':x,'max_abs_relative_difference':rel[worst],'ell_at_max':worst+2,
            'rms_relative_difference':math.sqrt(sum(r*r for r in rel)/len(rel)),'normalization':label})
    return {'point':pid,'reference_engine':reference,'compared_engine':other,'spectra':rows,
        'definition':'|C_ell(camb)-C_ell(class)|/normalization for ell=2..ell_max'}

def validate(task):
    _keys(task,('input',),'cosmology-solver task')
    if type(task['input']) is not str or not task['input']:raise ValueError('explicit input path required')
    return deepcopy(task)

def _load(task,base):
    path=science.regular(validate(task)['input'],base)
    return path,validate_document(_read(path))

def _admission(task,base):
    path,d=_load(task,base);python=_pin(d['runtime']['python'],path.parent);mp=_pin(d['runtime']['manifest'],path.parent)
    m=_read(mp,d['runtime']['manifest']['sha256'])
    _keys(m,('schema_version','engine','version','files','site_roots','environment'),'finite runtime manifest')
    if type(m['schema_version'])is not int or m['schema_version']!=1 or m['engine']!=d['engine'] or m['version']!=VERSIONS[d['engine']]:raise ValueError('exact selected official API version required')
    if not os.access(python,os.X_OK) or type(m['files'])is not list or not m['files']:raise ValueError('executable interpreter and finite runtime inputs required')
    files=[path,python,mp]+[_pin(p,path.parent) for p in m['files']]
    if len({str(p) for p in files})!=len(files):raise ValueError('distinct runtime/document pins required')
    if type(m['site_roots'])is not list or not m['site_roots'] or len(set(m['site_roots']))!=len(m['site_roots']):raise ValueError('explicit import roots required')
    for root in m['site_roots']:
        p=Path(root)
        if not p.is_absolute() or not p.is_dir() or any(x.is_symlink() for x in (p,*p.parents)):raise ValueError('ordinary absolute import root required')
        if not any(q.is_relative_to(p) for q in files[3:]):raise ValueError('empty or unbound import root')
    if type(m['environment'])is not dict or any(k not in {'PATH','LD_LIBRARY_PATH','DYLD_LIBRARY_PATH'} or type(v)is not str for k,v in m['environment'].items()):raise ValueError('explicit closed selected startup environment required')
    if any(os.environ.get(k)!=v for k,v in m['environment'].items()):raise ValueError('selected startup environment differs')
    if d['engine']=='cobaya':
        model_path=_pin(d['model'],path.parent);model=_read(model_path,d['model']['sha256']);_no_code(model)
        if type(model)is not dict or not {'params','likelihood'}<=set(model)<= {'params','likelihood','theory','prior','packages_path'}:raise ValueError('explicit supplied Cobaya model component configuration required')
        if set(model['likelihood'])!=set(d['components']['likelihoods']):raise ValueError('complete expected likelihood population differs from model')
        files.append(model_path)
    if d['measurement'] is not None:
        measurement_path=_pin(d['measurement'],path.parent);bridge=_read(measurement_path,d['measurement']['sha256'])
        _keys(bridge,('model','point_id','quantity','cell_ids','bin_ids','role','task'),'measurement bridge')
        from ravel.physics import measurement
        measurement.prepare(bridge['model']);measurement.validate(bridge['task'])
        if bridge['point_id']not in {p['id'] for p in d['points']} or bridge['role']!='sm':raise ValueError('existing point and explicit new theoretical SM role required')
        expected=[c for c in linear_cells(d,bridge['point_id']) if c['quantity']==bridge['quantity']]
        if not expected or bridge['cell_ids']!=[c['id'] for c in expected] or bridge['bin_ids']!=bridge['model']['sm']['bin_ids'] or len(expected)!=len(bridge['bin_ids']) or any(c['unit']!=bridge['model']['sm']['unit'] for c in expected):raise ValueError('complete measurement cell/bin/unit binding differs')
        files.append(measurement_path)
    # Existing worker binds all core source; only these normal input paths are added.
    return path,d,m,sorted(set(files))

def inputs(task,base):return _admission(task,base)[-1]
def execution_seconds(task,base):return int(_load(task,base)[1]['operation_resources']['max_seconds'])+30

def linear_cells(d,pid):
    g=d['grid'];cells=[]
    for z in g['redshifts']:
        for k in g['k_h_mpc']:cells.append({'id':f'{pid}:pk:z={z}:kh={k}','quantity':'linear_total_matter_power','z':z,'k_h_mpc':k,'unit':'(Mpc/h)^3'})
    for z in g['background_redshifts']:
        cells.extend([{'id':f'{pid}:H:z={z}','quantity':'Hubble','z':z,'unit':'km/s/Mpc'}, {'id':f'{pid}:DA:z={z}','quantity':'angular_diameter_distance','z':z,'unit':'Mpc'}])
    return cells

def _raw(value):
    if hasattr(value,'tolist'):return _raw(value.tolist())
    if hasattr(value,'item'):return _raw(value.item())
    if type(value)is dict:return {str(k):_raw(v) for k,v in value.items()}
    if type(value)in (list,tuple):return [_raw(v) for v in value]
    if type(value)in (float,int) or hasattr(value,'item'):
        x=float(value)
        return x if math.isfinite(x) else {'nonfinite':'-inf' if x==-math.inf else '+inf' if x==math.inf else 'nan'}
    if value is None or type(value)in (bool,str):return value
    return {'native_return_type':type(value).__module__+'.'+type(value).__qualname__}

def _posterior_number(value,allow_minus_inf=False):
    if hasattr(value,'item'):value=value.item()
    if type(value)not in (int,float) or math.isnan(value) or value==math.inf or (value==-math.inf and not allow_minus_inf):raise ValueError('native posterior scalar has invalid type/domain')
    return value

def execute_points(d,api,write,model_configuration=None):
    """Official API translation; pure tests substitute APIs, never native physics."""
    d=validate_document(d)
    if d['profile']==CMB_PROFILE:return _execute_cmb(d,api,write)
    events=[];results=[];state={'declared_points':[p['id'] for p in d['points']],'points':results,'calls':events,'solver_calls_started':0,'solver_calls_returned':0,'interpolation_support':{},'status':'running'}
    def call(pid,op,fn,solver=False):
        row={'point':pid,'operation':op,'solver_evaluation':solver,'status':'started'};events.append(row)
        if solver:state['solver_calls_started']+=1
        write(deepcopy(state))
        try:value=fn()
        except BaseException as error:
            row.update(status='failed',error_type=type(error).__name__,error=str(error));write(deepcopy(state));raise
        row.update(status='returned',raw_return=_raw(value))
        if solver:state['solver_calls_returned']+=1
        write(deepcopy(state));return value
    try:
        for point in d['points']:
            pid=point['id'];p=point['parameters'];cells=[]
            if d['engine']=='camb':
                pars=api.CAMBparams();pars.WantCls=False;pars.set_cosmology(H0=p['H0'],ombh2=p['omega_b'],omch2=p['omega_cdm'],omk=0,mnu=0,num_massive_neutrinos=0,nnu=p['N_eff'],YHe=p['YHe'],TCMB=p['T_CMB'],tau=p['tau'])
                pars.InitPower.set_params(As=p['A_s'],ns=p['n_s']);pars.NonLinear=api.model.NonLinear_none
                pars.set_matter_power(redshifts=sorted(d['grid']['redshifts'],reverse=True),kmax=max(d['grid']['k_h_mpc'])*p['H0']/100*1.05)
                data=call(pid,'get_results',lambda:api.get_results(pars),True)
                pk=data.get_matter_power_interpolator(nonlinear=False,var1='delta_tot',var2='delta_tot',hubble_units=True,k_hunit=True,extrap_kmax=None)
                raw_support={k:getattr(pk,k,None)for k in ('kmin','kmax','zmin','zmax')}
                state['interpolation_support'][pid]={'status':'observed','raw_support':_raw(raw_support)}
                write(deepcopy(state))
                state['interpolation_support'][pid]=_camb_support(d,raw_support)
                write(deepcopy(state))
                for c in linear_cells(d,pid):
                    fn=(lambda c=c:pk.P(c['z'],c['k_h_mpc'],grid=False)) if c['quantity']=='linear_total_matter_power' else (lambda c=c:data.hubble_parameter(c['z'])) if c['quantity']=='Hubble' else (lambda c=c:data.angular_diameter_distance(c['z']))
                    cells.append({**c,'value':_native_scalar(call(pid,c['id'],fn),'native observable')})
            elif d['engine']=='class':
                data=api.Class();h=p['H0']/100
                settings={'h':h,'omega_b':p['omega_b'],'omega_cdm':p['omega_cdm'],'A_s':p['A_s'],'n_s':p['n_s'],'tau_reio':p['tau'],'T_cmb':p['T_CMB'],'YHe':p['YHe'],'N_ur':p['N_eff'],'N_ncdm':0,'Omega_k':0,'output':'mPk','P_k_max_h/Mpc':max(d['grid']['k_h_mpc'])*1.05,'z_pk':','.join(str(z) for z in sorted(d['grid']['redshifts'],reverse=True))}
                try:
                    data.set(settings);call(pid,'compute_fourier',lambda:data.compute(['fourier']),True)
                    for c in linear_cells(d,pid):
                        if c['quantity']=='linear_total_matter_power':raw=call(pid,c['id'],lambda c=c:data.pk_lin(c['k_h_mpc']*h,c['z']));value=_native_scalar(raw,'native P(Mpc^3)')*h**3
                        elif c['quantity']=='Hubble':raw=call(pid,c['id'],lambda c=c:data.Hubble(c['z']));value=_native_scalar(raw,'native H(1/Mpc)')*C_KM_S
                        else:value=_native_scalar(call(pid,c['id'],lambda c=c:data.angular_distance(c['z'])),'native DA')
                        cells.append({**c,'value':_num(value,'converted observable')})
                finally:
                    data.struct_cleanup();data.empty()
            else:
                model=api.get_model(model_configuration,stop_at_error=True)
                try:
                    if set(model.parameterization.sampled_params())!=set(p):raise ValueError('complete sampled parameter population differs')
                    answer=call(pid,'logposterior',lambda:model.logposterior(p,as_dict=True,make_finite=False,return_derived=True,cached=False),True)
                    _keys(answer,('logpost','logpriors','loglikes','derived'),'native posterior result')
                    _posterior_number(answer['logpost'],True)
                    for values in (answer['logpriors'],answer['loglikes']):
                        if type(values)is not dict:raise ValueError('native named prior/likelihood dictionary required')
                        for v in values.values():_posterior_number(v,True)
                    for v in answer['derived'].values():_posterior_number(v)
                    outside_prior=any(v==-math.inf for v in answer['logpriors'].values()) and answer['logpost']==-math.inf
                    for key,names in [('logpriors','priors'),('loglikes','likelihoods'),('derived','derived')]:
                        if type(answer[key])is not dict:raise ValueError('native component dictionary required')
                        if set(answer[key])!=set(d['components'][names]) and not (outside_prior and key!='logpriors' and not answer[key]):raise ValueError('complete native posterior component population differs')
                    # Infinity is retained raw, not converted into a huge finite score.
                    cells=[{'id':pid+':logpost','quantity':'logpost','unit':'1','value':_raw(answer['logpost'])}]
                    for key,names in [('logpriors','priors'),('loglikes','likelihoods'),('derived','derived')]:
                        for name in d['components'][names]:
                            value=_raw(answer[key][name]) if name in answer[key] else {'not_computed':'outside_prior'}
                            cells.append({'id':pid+':'+key+':'+name,'quantity':key,'unit':d['components']['derived_units'][name] if key=='derived' else '1','value':value})
                finally:model.close()
            results.append({'id':pid,'parameters':deepcopy(p),'cells':cells});write(deepcopy(state))
        state['status']='passed'
    except BaseException as error:
        state['status']='failed';state['failure']={'type':type(error).__name__,'message':str(error)}
        raise
    finally:
        state['uncompleted_points']=[p['id'] for p in d['points'] if p['id']not in {r['id'] for r in results}]
        write(deepcopy(state))
    if state['solver_calls_started']!=d['operation_resources']['solver_evaluations'] or state['solver_calls_returned']!=state['solver_calls_started']:raise ValueError('actual solver invocation count differs')
    return state

def loaded_modules(d,m,base):
    """Declared observed nonstdlib modules; not full OS/shared-library closure."""
    allowed={str(_pin(p,base)):p['sha256'] for p in m['files']};found={}
    stdlib=Path(os.__file__).resolve().parent
    for name,module in list(sys.modules.items()):
        origin=getattr(module,'__file__',None)
        if not origin:continue
        path=Path(origin).resolve()
        core=Path(__file__).resolve().parents[1]
        if name=='__main__' and path==Path(__file__).resolve():continue
        if (name=='ravel' or name.startswith('ravel.')) and path.is_relative_to(core):continue
        if path.is_relative_to(stdlib) and not {'site-packages','dist-packages'}&set(path.parts):continue
        if str(path)not in allowed or execution.file_hash(path)!=allowed[str(path)]:raise ValueError('loaded dependency origin absent/changed in finite runtime: '+str(path))
        found[name]={'path':str(path),'sha256':allowed[str(path)]}
    for engine in ENGINES[d['engine']]:
        if MODULES[engine] not in found:raise ValueError('native official engine origin not observed')
    return found

def _delegated(rd,path,out):
    rd=science.root(rd);proposal=_read(rd/science.PLAN);spec=science.execution_spec(rd)
    attempt=_read(rd/'execution_attempt.json');record=execution.load_execution(rd)['stages'].get('science',{})
    approval=_read(rd/science.APPROVAL)
    expected=rd/proposal['stages'][0]['outputs'][0]/'cosmology-solver'/'native'
    if (spec['schema_version']!=2 or spec['mode']!='cosmology-solver' or spec['max_attempts']!=1 or attempt['attempt']!=1
        or record.get('status')!='running' or record.get('child_pid')!=os.getppid()
        or record.get('child_identity')!=execution.process_identity(os.getppid())
        or record.get('fingerprint')!=proposal['stage_binding']['fingerprint']
        or approval.get('plan_sha256')!=execution.file_hash(rd/science.PLAN)
        or Path(out).resolve()!=expected.resolve()):raise ValueError('native solver requires exact live ordinary worker delegation')
    original,_=_load(spec['task'],proposal['base_dir'])
    if Path(path).resolve()!=original:raise ValueError('native scientific input differs from exact approved ordinary task')
    return rd

def _optional_import(module):
    try:
        return importlib.import_module(module)
    except ImportError as error:
        raise ImportError(
            'Cosmology runtime import failed for '+module+
            '; install ravel-hep[cosmology] and verify its dependencies in the selected runtime.'
        ) from error

def native_worker(path,out,rd):
    if sys.flags.optimize:raise ValueError('optimized runtime not admitted')
    _delegated(rd,path,out)
    path,d,m,files=_admission({'input':str(path)},Path(path).parent)
    before={str(p):execution.file_hash(p) for p in files}
    for k,v in m['environment'].items():
        if os.environ.get(k)!=v:raise ValueError('selected startup environment differs')
    sys.path[1:1]=m['site_roots']
    modules={}
    for name in ENGINES[d['engine']]:
        modules[name]=_optional_import(MODULES[name])
        if str(getattr(modules[name],'__version__','')).lstrip('v')!=VERSIONS[name]:raise ValueError('loaded official engine version differs')
    api=_optional_import('cobaya.model') if d['engine']=='cobaya' else modules if d['engine']=='camb+class' else modules[d['engine']]
    imported_before=loaded_modules(d,m,path.parent)
    out=Path(out)
    atomic_json(out/'loaded-before.json',imported_before)
    model=_read(_pin(d['model'],path.parent),d['model']['sha256']) if d['model'] is not None else None
    value=execute_points(d,api,lambda value:atomic_json(out/'raw-calls-and-points.json',value),model)
    imported_after=loaded_modules(d,m,path.parent)
    if before!={str(p):execution.file_hash(p) for p in files}:raise ValueError('ending native scientific/runtime inputs changed')
    atomic_json(out/'native-result.json',{**value,'engine':d['engine'],'version':VERSIONS[d['engine']],
        'source':d['source'],'profile':d['profile'],'operation_resources':d['operation_resources'],
        'loaded_before':imported_before,'loaded_after':imported_after,
        'count_scope':'Explicit get_results/compute/logposterior parameter-point solves. Direct observable getter returns are retained; internal/native cached calls are not a hard OS evaluation quota.',
        'physics_validated':False})
    return 0

def complete_result(d,result):
    if d['profile']==CMB_PROFILE:return _complete_cmb(d,result)
    if (result.get('status')!='passed' or result.get('engine')!=d['engine'] or result.get('version')!=VERSIONS[d['engine']]
        or result.get('operation_resources')!=d['operation_resources'] or result.get('physics_validated')is not False):raise ValueError('native delivery scope differs')
    if [r['id'] for r in result['points']]!=[p['id'] for p in d['points']] or result['uncompleted_points']:raise ValueError('complete point population required')
    if result['solver_calls_started']!=len(d['points']) or result['solver_calls_returned']!=len(d['points']):raise ValueError('actual parameter-point solver count differs')
    solver_rows=[r for r in result['calls'] if r.get('solver_evaluation')is True]
    if len(solver_rows)!=len(d['points']) or any(r['status']!='returned' or r.get('operation')!={'class':'compute_fourier','camb':'get_results','cobaya':'logposterior'}[d['engine']] for r in solver_rows) or [r['point'] for r in solver_rows]!=[p['id'] for p in d['points']]:raise ValueError('retained solver call ledger differs')
    support=result.get('interpolation_support')
    if type(support)is not dict or set(support)!=({p['id']for p in d['points']}if d['engine']=='camb'else set()):raise ValueError('complete actual interpolation support population required')
    if d['engine']=='camb':
        for row in support.values():
            if type(row)is not dict or 'raw_support'not in row or row!=_camb_support(d,row['raw_support']):raise ValueError('retained actual interpolation support differs')
    expected_call_keys=[]
    for original,point in zip(d['points'],result['points']):
        expected_call_keys.append((point['id'],{'class':'compute_fourier','camb':'get_results','cobaya':'logposterior'}[d['engine']]))
        if point['parameters']!=original['parameters']:raise ValueError('native parameter point differs')
        if d['engine']!='cobaya':
            expected=linear_cells(d,point['id'])
            if len(point['cells'])!=len(expected):raise ValueError('complete observable population required')
            for a,b in zip(point['cells'],expected):
                if {k:v for k,v in a.items() if k!='value'}!=b:raise ValueError('observable identity/order/unit differs')
                expected_call_keys.append((point['id'],a['id']))
                rows=[r for r in result['calls'] if r.get('point')==point['id'] and r.get('operation')==a['id']]
                if len(rows)!=1 or rows[0].get('status')!='returned' or rows[0].get('solver_evaluation')is not False:raise ValueError('native observable return ledger differs')
                returned=_num(rows[0]['raw_return'],'raw native return')
                h=original['parameters']['H0']/100
                converted=returned*(h**3 if b['quantity']=='linear_total_matter_power' else C_KM_S if b['quantity']=='Hubble' else 1) if d['engine']=='class' else returned
                v=_num(a['value'],'native value')
                if v!=converted:raise ValueError('derived native cell differs from retained raw return')
                if v<0 or b['quantity']!='angular_diameter_distance' and v==0:raise ValueError('physical positive power/Hubble or nonnegative distance required')
        else:
            expected=[{'id':point['id']+':logpost','quantity':'logpost','unit':'1'}]
            for key,names in [('logpriors','priors'),('loglikes','likelihoods'),('derived','derived')]:
                expected.extend({'id':point['id']+':'+key+':'+name,'quantity':key,'unit':d['components']['derived_units'][name] if key=='derived' else '1'} for name in d['components'][names])
            if len(point['cells'])!=len(expected):raise ValueError('complete named posterior population required')
            raw=next(r['raw_return'] for r in solver_rows if r['point']==point['id'])
            _keys(raw,('logpost','logpriors','loglikes','derived'),'retained native posterior')
            for key,names in [('logpriors','priors'),('loglikes','likelihoods'),('derived','derived')]:
                if type(raw[key])is not dict:raise ValueError('retained named posterior dictionaries required')
                if set(raw[key])!=set(d['components'][names]) and not (raw['logpost']=={'nonfinite':'-inf'} and any(v=={'nonfinite':'-inf'} for v in raw['logpriors'].values()) and key!='logpriors' and not raw[key]):raise ValueError('retained native component population differs')
            raw_values=[raw['logpost']]+[raw[key].get(name,{'not_computed':'outside_prior'}) for key,names in [('logpriors','priors'),('loglikes','likelihoods'),('derived','derived')] for name in d['components'][names]]
            if [a['value'] for a in point['cells']]!=raw_values:raise ValueError('posterior cells differ from retained raw return')
            prior_cells=[a for a in point['cells'] if a['quantity']=='logpriors']
            outside=point['cells'][0]['value']=={'nonfinite':'-inf'} and any(a['value']=={'nonfinite':'-inf'} for a in prior_cells)
            for a,b in zip(point['cells'],expected):
                if {k:v for k,v in a.items() if k!='value'}!=b:raise ValueError('posterior identity/order/unit differs')
                value=a['value']
                if value=={'not_computed':'outside_prior'}:
                    if not outside or a['quantity']not in ('loglikes','derived'):raise ValueError('uncomputed posterior component without outside-prior reason')
                elif value=={'nonfinite':'-inf'}:
                    if a['quantity']=='derived':raise ValueError('nonfinite derived quantity')
                else:_num(value,'posterior component')
    if [(r.get('point'),r.get('operation')) for r in result['calls']]!=expected_call_keys:raise ValueError('complete retained native operation population differs')
    return result

def measurement_handoff(d,result,base):
    """New full-covariance ordinary model input; no inference or acceptance."""
    if d['measurement']is None:return None
    pin=d['measurement'];path=_pin(pin,base);bridge=_read(path,pin['sha256'])
    _keys(bridge,('model','point_id','quantity','cell_ids','bin_ids','role','task'),'measurement bridge')
    if bridge['role']!='sm' or bridge['quantity']not in ('linear_total_matter_power','Hubble','angular_diameter_distance'):raise ValueError('explicit prediction-as-SM ordinary measurement role required')
    from ravel.physics import measurement
    model=deepcopy(bridge['model']);measurement.prepare(model)
    points={p['id']:p for p in result['points']}
    if bridge['point_id']not in points:raise ValueError('bridge point absent')
    cells={c['id']:c for c in points[bridge['point_id']]['cells']}
    wanted=[c['id'] for c in points[bridge['point_id']]['cells'] if c['quantity']==bridge['quantity']]
    if bridge['cell_ids']!=wanted or bridge['bin_ids']!=model['sm']['bin_ids'] or len(wanted)!=len(model['sm']['bin_ids']):raise ValueError('complete selected quantity/cell population required')
    if any(cells[c]['unit']!=model['sm']['unit'] for c in wanted):raise ValueError('measurement unit differs from native observable')
    model['sm']['values']=[cells[c]['value'] for c in wanted]
    measurement.prepare(model)
    return {'kind':'new-unapproved-measurement-input','model':model,'native_cell_ids':wanted,
        'task':deepcopy(bridge['task']),'source_measurement_pin':pin,'covariance_changed':False,'inference_performed':False,'execution_authorized':False}

def run(task,base,out):
    path,d,m,files=_admission(task,base);out=Path(out)
    rd=out.parents[2];proposal=science.verify_worker(rd);spec=science.execution_spec(rd)
    if spec['mode']!='cosmology-solver' or Path(proposal['base_dir'])!=Path(base) or Path(out)!=rd/proposal['output_directory']/'cosmology-solver' or _load(spec['task'],base)[0]!=path:raise ValueError('solver launch requires exact current ordinary worker and destination')
    out.mkdir(parents=True,exist_ok=False)
    before={str(p):execution.file_hash(p) for p in files}
    # Parent science worker always binds/currently approves the new mode.
    rd=out.parents[2];native=out/'native';native.mkdir()
    python=_pin(d['runtime']['python'],path.parent)
    command=[str(python),'-I','-B',str(Path(__file__).resolve()),'--native',str(path),str(native),str(rd)]
    from ravel.physics.reinterpret_db import execute_native
    receipt=execute_native(command,native,{'max_seconds':d['operation_resources']['max_seconds'],'max_ram_mib':d['max_ram_mib']})
    value=complete_result(d,_read(native/'native-result.json'))
    if before!={str(p):execution.file_hash(p) for p in files}:raise ValueError('ending admitted cosmology inputs changed')
    bridge=measurement_handoff(d,value,path.parent)
    if bridge is not None:
        atomic_json(out/'measurement-model.json',bridge['model'])
        bridge['task']['input']=str((out/'measurement-model.json').absolute())
        from ravel.physics import measurement
        measurement.validate(bridge['task'])
        atomic_json(out/'measurement-task.json',bridge['task'])
        atomic_json(out/'new-measurement-input.json',bridge)
    result={'status':'passed','status_scope':SCOPE,'physics_validated':False,'engine':d['engine'],'version':VERSIONS[d['engine']],
        'native':value,'native_execution':receipt,'measurement_handoff':bridge,'generated_events':0,
        'limitations':['Linear matter-power profiles are flat massless LCDM; the lensed CMB profile adds one massive species and reports CAMB/CLASS differences without an equivalence claim.',
        'Cobaya evaluates complete supplied named components and preserves negative infinity; no sampler, installation or automatic data acquisition.',
        'Runtime imports are trusted; file origins do not prove every data/shared-library/OS read. No arbitrary callback is the public operation.',
        'Point solve counts describe direct source API operations, not arbitrary native internals. Physical cosmology and supplied data/covariance validity need independent review.']}
    atomic_json(out/'cosmology-result.json',result);return result

def prepare(input_path,policy_path,output,approval_mode='physicist'):
    path=Path(input_path).absolute();task={'input':str(path)};inputs(task,path.parent)
    d=_load(task,path.parent)[1]
    spec={'schema_version':2,'mode':'cosmology-solver','source':d['source'],
        'assumptions':[SCOPE,'Zero generated events; '+str(d['operation_resources']['solver_evaluations'])+' declared parameter-point solver evaluations. Native count scope is explicit.',
            'Official selected engine/runtime is trusted; data, covariance and physical applicability remain supplied.'],
        'task':task,'approval_mode':approval_mode,'max_seconds':execution_seconds(task,path.parent),
        'max_attempts':1,'review_policy':_read(science.regular(policy_path,path.parent))}
    science.validate(spec);atomic_json(output,spec);return spec

def runtime_manifest(engine,python,sites,environment=None):
    """Runtime manifest for the installed dependency closure of the selected engines."""
    from ravel.physics.eft_toolchain import runtime_census
    names=[MODULES[e] for e in ENGINES[engine]]
    files,versions=runtime_census([Path(s).absolute() for s in sites],names)
    for e in ENGINES[engine]:
        found=versions.get(MODULES[e]) or ''
        if found!=VERSIONS[e] and not found.startswith(VERSIONS[e]+'.'):raise ValueError('installed '+MODULES[e]+' '+str(versions.get(MODULES[e]))+' differs from '+VERSIONS[e])
    return {'schema_version':1,'engine':engine,'version':VERSIONS[engine],
            'files':[{'path':str(f),'sha256':execution.file_hash(f)} for f in files],
            'site_roots':[str(Path(s).absolute()) for s in sites],'environment':dict(environment or {})}

def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    if argv[:1]==['manifest']:
        p=argparse.ArgumentParser(prog='python -m ravel.physics.cosmology_solver manifest')
        p.add_argument('--engine',choices=('camb','class','camb+class'),required=True);p.add_argument('--site',action='append',required=True)
        p.add_argument('--python',default=sys.executable);p.add_argument('--out',required=True);a=p.parse_args(argv[1:])
        atomic_json(Path(a.out),runtime_manifest(a.engine,a.python,a.site));return 0
    p=argparse.ArgumentParser();p.add_argument('--native',action='store_true');p.add_argument('paths',nargs='+');a=p.parse_args(argv)
    if not a.native or len(a.paths)!=3:raise ValueError('native entry is delegated only; use prepare() for ordinary source planning')
    return native_worker(*a.paths)
if __name__=='__main__':raise SystemExit(main())
