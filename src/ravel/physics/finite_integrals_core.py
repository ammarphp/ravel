"""Closed finite massive scalar triangle/box dialect and lossless return checks.

No backend imports. pySecDec owns parameterization and integration.
"""
from __future__ import annotations
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re

from ravel.validation.numerical_reference import exact, ratio, _json
from ravel.physics.source_tables import bounded_read
from ravel.workflow import operation_resources

VERSION='1.6.6'
SCOPE='finite_scalar_integral_delivery'
LIMIT=8*1024**2
PRESCRIPTION='q_squared-minus-mass_squared-plus-i0'
NORMALIZATION='integral d^Dk/(i*pi^(D/2)); D=4-2*eps; eps^0; additional_prefactor=1'
ERROR_MEANING='pySecDec QMC estimated standard deviations of real and imaginary components; not certified enclosures'


def keys(d,names,label):
    if type(d) is not dict or set(d)!=set(names):raise ValueError('closed '+label+' required')

def text(x):
    if type(x) is not str or not x.strip() or len(x)>4096:raise ValueError('bounded nonempty text required')
    return x

def ident(x):
    if type(x) is not str or re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,63}',x) is None:raise ValueError('simple unique identifier required')
    return x

def number(x):
    y=exact(x)
    try:converted=float(y)
    except (OverflowError,ValueError):raise ValueError('finite representable number required') from None
    if not math.isfinite(converted) or (y and converted==0):raise ValueError('finite representable nonzero number required')
    return y

def read(p):return _json(bounded_read(Path(p),LIMIT))

def write(p,d):
    raw=(json.dumps(d,indent=2,allow_nan=False)+'\n').encode()
    if len(raw)>LIMIT:raise ValueError('bounded integral JSON exceeded')
    from ravel.workflow.state_io import atomic_json
    atomic_json(p,d)
    return hashlib.sha256(raw).hexdigest()

def pairs(n):return [(i,j) for i in range(n) for j in range(i+1,n)]

def parameter_names(n):return ['s'+str(i)+str(j) for i,j in pairs(n)]+[v for i in range(n) for v in ('m'+str(i)+'_re','m'+str(i)+'_im')]+['scale2','mu']

def point_values(p,n):
    keys(p,('id','invariants_gev2','masses_squared_gev2','scale_squared_gev2','mu_gev'),'point')
    ident(p['id']);inv=p['invariants_gev2'];mass=p['masses_squared_gev2']
    keys(inv,['s'+str(i)+str(j) for i,j in pairs(n)],'complete (q_i-q_j)^2 invariant census')
    if type(mass) is not list or len(mass)!=n:raise ValueError('complete ordered propagator mass-squared population required')
    answer={k:number(v) for k,v in inv.items()}
    for i,m in enumerate(mass):
        keys(m,('real','imag'),'complex mass squared')
        answer['m'+str(i)+'_re']=number(m['real']);answer['m'+str(i)+'_im']=number(m['imag'])
        if answer['m'+str(i)+'_re']<=0:raise ValueError('strictly positive real mass squared; IR/massless route unsupported')
    answer['scale2']=number(p['scale_squared_gev2']);answer['mu']=number(p['mu_gev'])
    if answer['scale2']<=0 or answer['mu']<=0:raise ValueError('positive scale squared and dimensional-regularization scale required')
    # The finite epsilon-zero coefficient has no mu dependence: poles absent.
    for k,v in answer.items():
        if k not in ('scale2','mu'):
            z=v/answer['scale2']
            if abs(z)>1000000 or (z and abs(z)<Fraction(1,10**12)):raise ValueError('normalized kinematics outside declared numerical range')
    return answer

def compiler_options(c):
    """One explicit grammar-compatibility mode; never arbitrary build flags."""
    if 'build_compatibility' not in c:return []
    mode=c['build_compatibility']
    keys(mode,('mode','compiler','reason','evidence'),'prospective build compatibility')
    if mode['mode']!='clang-template-keyword-without-argument-list/v1':raise ValueError('unsupported compiler compatibility mode')
    text(mode['reason'])
    compiler=mode['compiler'];keys(compiler,('path','sha256'),'compatibility compiler pin')
    if (type(compiler['path']) is not str or not Path(compiler['path']).is_absolute() or
        str(Path(compiler['path']))!=compiler['path'] or '..' in Path(compiler['path']).parts or
        type(compiler['sha256']) is not str or re.fullmatch('[0-9a-f]{64}',compiler['sha256']) is None or
        compiler!=c['runtime']['cxx']):raise ValueError('compatibility compiler must equal exact runtime compiler pin')
    evidence=mode['evidence']
    if type(evidence) is not list or not 1<=len(evidence)<=8:raise ValueError('bounded compiler compatibility evidence required')
    for item in evidence:
        keys(item,('path','sha256'),'compiler compatibility evidence pin');text(item['path'])
        if type(item['sha256']) is not str or re.fullmatch('[0-9a-f]{64}',item['sha256']) is None:raise ValueError('exact compiler compatibility evidence digest required')
    return ['-Wno-missing-template-arg-list-after-template-kw']

def config(c):
    names=('schema_version','kind','source','evidence','runtime','propagators','regime','prescription','normalization','axes','points','precision','max_seconds','max_ram_mib','max_output_bytes','operation_resources')
    if type(c) is dict and 'build_compatibility' in c:names+=('build_compatibility',)
    keys(c,names,'finite integral configuration')
    if type(c['schema_version']) is not int or c['schema_version']!=1 or c['kind']!='pysecdec-finite-one-loop':raise ValueError('finite integral schema1 required')
    text(c['source'])
    if type(c['evidence']) is not list or not 1<=len(c['evidence'])<=16:raise ValueError('source/convention evidence required')
    n=c['propagators']
    if type(n) is not int or n not in (3,4):raise ValueError('closed scalar triangle or box, unit propagator powers only')
    if c['prescription']!=PRESCRIPTION or c['normalization']!=NORMALIZATION:raise ValueError('explicit native Feynman prescription/normalization required')
    if c['regime'] not in ('euclidean_positive_masses','causal_complex_masses'):raise ValueError('finite proven nonzero-F regime required')
    if type(c['points']) is not list or not 1<=len(c['points'])<=64:raise ValueError('1..64 complete parameter points required')
    seen=set();values=[]
    for p in c['points']:
        v=point_values(p,n);values.append(v)
        if p['id'] in seen:raise ValueError('duplicate point ID')
        seen.add(p['id'])
        im=[v['m'+str(i)+'_im'] for i in range(n)]
        if c['regime']=='euclidean_positive_masses':
            if any(im) or any(v['s'+str(i)+str(j)]>0 for i,j in pairs(n)):raise ValueError('Euclidean regime requires real masses and nonpositive pair invariants')
        elif any(x>=0 for x in im):raise ValueError('every complex pole mass must have strictly negative imaginary mass squared; no implicit regulator/width')
    if type(c['axes']) is not list or not 1<=len(c['axes'])<=4 or len(set(c['axes']))!=len(c['axes']) or any(x not in parameter_names(n) for x in c['axes']):raise ValueError('1..4 explicit varying physical parameter axes required')
    if len({tuple(v[a] for a in c['axes']) for v in values})!=len(values):raise ValueError('duplicate physical coordinates')
    for k in parameter_names(n):
        if k not in c['axes'] and len({v[k] for v in values})!=1:raise ValueError('changing physical parameter omitted from declared axes: '+k)
    pr=c['precision'];keys(pr,('epsrel','epsabs','maxeval','minn','seed'),'requested QMC precision')
    if not 0<number(pr['epsrel'])<=Fraction(1,10) or number(pr['epsabs'])<=0:raise ValueError('positive requested precision, relative at most0.1')
    for k,lo,hi in (('maxeval',1000,10**10),('minn',100,10**7),('seed',1,2**31-1)):
        if type(pr[k]) is not int or not lo<=pr[k]<=hi:raise ValueError('bounded explicit QMC '+k)
    if pr['minn']>pr['maxeval']:raise ValueError('initial lattice exceeds requested evaluation budget')
    for k,lo,hi in (('max_seconds',1,86400),('max_ram_mib',512,32768),('max_output_bytes',1024**2,20*1024**3)):
        if type(c[k]) is not int or not lo<=c[k]<=hi:raise ValueError('bounded '+k+' required')
    expected={'schema_version':1,'kind':'solver','generated_events':0,'solver_evaluations':len(values),'max_seconds':c['max_seconds']}
    if operation_resources.validate(c['operation_resources'])!=expected:raise ValueError('exact explicit top-level point evaluation resource census required')
    rt=c['runtime'];keys(rt,('python','make','cxx','trees','site_roots','contrib_root','path','version'),'runtime')
    if rt['version']!=VERSION or type(rt['trees']) is not list or not 1<=len(rt['trees'])<=8:raise ValueError('released pySecDec1.6.6 complete runtime trees required')
    if type(rt['site_roots']) is not list or not 1<=len(rt['site_roots'])<=4 or type(rt['path']) is not list or not 1<=len(rt['path'])<=16:raise ValueError('explicit bounded runtime paths required')
    for x in [*rt['site_roots'],*rt['path'],rt['contrib_root']]:text(x)
    compiler_options(c)
    return c

def generator_spec(c):
    n=c['propagators'];real=['s'+str(i)+str(j) for i,j in pairs(n)]
    replacements=[['q'+str(i)+'**2','s0'+str(i)] for i in range(1,n)]
    replacements += [['q'+str(i)+'*q'+str(j),'(s0'+str(i)+'+s0'+str(j)+'-s'+str(i)+str(j)+')/2'] for i in range(1,n) for j in range(i+1,n)]
    return {'name':'finite_integral','propagators':['k**2-m0']+['(k+q'+str(i)+')**2-m'+str(i) for i in range(1,n)],
            'loop_momenta':['k'],'external_momenta':['q'+str(i) for i in range(1,n)],'replacement_rules':replacements,
            'dimensionality':'4-2*eps','powerlist':[1]*n,'real_parameters':real,
            'complex_parameters':['m'+str(i) for i in range(n)],'requested_orders':[0],
            'contour_deformation':False,'additional_prefactor':1,'enforce_complex':True,
            'decomposition_method':'iterative','form_threads':1,'processes':1,'pylink_qmc_transforms':['korobov3x3']}

def numerical_arguments(c,p):
    v=point_values(p,c['propagators']);q=v['scale2'];factor=q**(2-c['propagators'])
    real=[float(v['s'+str(i)+str(j)]/q) for i,j in pairs(c['propagators'])]
    masses=[[float(v['m'+str(i)+'_re']/q),float(v['m'+str(i)+'_im']/q)] for i in range(c['propagators'])]
    epsabs=number(c['precision']['epsabs'])/abs(factor)
    if not math.isfinite(float(epsabs)) or float(epsabs)==0:raise ValueError('unrepresentable scaled requested precision')
    return {'real_parameters':real,'complex_parameters':masses,'dimensionful_factor':ratio(factor),'epsabs_native':float(epsabs),
            'coordinates':[ratio(v[a]) for a in c['axes']]}

# A deliberately closed independent parser for precisely one finite epsilon-zero
# coefficient. Preserve raw strings separately; no eval or regex omission of poles.
TOKEN=r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?'
PAIR=r'\(\s*('+TOKEN+r')\s*,\s*('+TOKEN+r')\s*\)'
FINITE=re.compile(r'\s*\+?\s*\(\s*'+PAIR+r'\s*\+/-\s*'+PAIR+r'\s*\)\s*(?:\*eps\^0)?\s*(?:\+\s*O\(eps(?:\^1)?\))?\s*')

def parse_finite(raw):
    if type(raw) is not str or len(raw)>100000:raise ValueError('bounded literal native series required')
    match=FINITE.fullmatch(raw)
    if not match:raise ValueError('expected one complex finite coefficient plus optional O(eps); poles/extra terms refused')
    values=[number(s) for s in match.groups()]
    if min(values[2:])<0:raise ValueError('nonnegative QMC component errors required')
    return {'real':ratio(values[0]),'imag':ratio(values[1]),'error_real':ratio(values[2]),'error_imag':ratio(values[3])}

def derived(c,p,raw):
    if type(raw) is not list or len(raw)!=3 or any(type(v) is not str or len(v)>100000 for v in raw):raise ValueError('all three literal native strings required')
    value=parse_finite(raw[2]);args=numerical_arguments(c,p);factor=exact(args['dimensionful_factor'])
    scaled={k:ratio(exact(x)*(abs(factor) if k.startswith('error_') else factor)) for k,x in value.items()}
    thresholds={k:ratio(max(number(c['precision']['epsabs']),number(c['precision']['epsrel'])*abs(exact(scaled[k])))) for k in ('real','imag')}
    return {'id':p['id'],'coordinates':args['coordinates'],'native_arguments':args,'values':scaled,'requested_component_bands':thresholds,
            'estimated_precision_met':all(exact(scaled['error_'+k])<=exact(thresholds[k]) for k in ('real','imag')),
            'error_meaning':ERROR_MEANING,'qualified_enclosure':False}

def delivery_check(c,d):
    if d.get('status')!='returned' or d.get('version')!=VERSION or d.get('generator_spec')!=generator_spec(c):raise ValueError('complete native generator/return identity required')
    if any(type(d.get(x)) is not int for x in ('calls_started','calls_returned')) or len(d.get('rows',[]))!=len(c['points']) or d.get('calls_started')!=len(c['points']) or d.get('calls_returned')!=len(c['points']):raise ValueError('complete exact integral call population required')
    for p,row in zip(c['points'],d['rows']):
        if row.get('id')!=p['id'] or row.get('point')!=p or row.get('status')!='returned' or row.get('derived')!=derived(c,p,row.get('raw')):raise ValueError('raw integral return differs from complete reported values/errors/point')
    if [(r.get('name'),r.get('status')) for r in d.get('phases',[])]!=[('generate','returned'),('build','returned')] or d['phases'][1].get('returncode')!=0:raise ValueError('successful generation and build phase receipts required')
    if d.get('operation_resources')!=c['operation_resources']:raise ValueError('native evaluation/resource declaration differs')
    return all(row['derived']['estimated_precision_met'] for row in d['rows'])

def reference_document(c,d):
    delivery_check(c,d)
    return {'schema_version':1,'kind':'finite-integral-reported-values','backend':'pySecDec','version':VERSION,
            'configuration':c,'generator_spec':generator_spec(c),'rows':d['rows'],
            'error_meaning':ERROR_MEANING,'qualified_enclosure':False,'physics_validated':False}


def numerical_context(c):
    values=[point_values(p,c['propagators']) for p in c['points']]
    fixed={k:ratio(values[0][k]) for k in parameter_names(c['propagators']) if k not in c['axes']}
    return {'quantity':'finite scalar '+str(c['propagators'])+'-point epsilon-zero integral','model':c['source'],
            'process':json.dumps({'propagators':generator_spec(c)['propagators'],'fixed_parameters':fixed},sort_keys=True,separators=(',',':')),
            'normalization':NORMALIZATION,'domain':c['regime']+'; '+PRESCRIPTION,'basis':'complex scalar: real,imag'}


def comparison_deck(c,*,heldout_ids,atol,rtol):
    """Create a prospective source-complete deck; labels do not prove withholding."""
    config(c)
    if len(set(heldout_ids))!=len(heldout_ids) or not heldout_ids or not set(heldout_ids)<={p['id'] for p in c['points']}:raise ValueError('explicit nonempty held-out subset of complete original points required')
    if number(atol)<0 or number(rtol)<0:raise ValueError('nonnegative fixed engineering bands required')
    rows=[{'id':p['id'],'coordinates':numerical_arguments(c,p)['coordinates']} for p in c['points']]
    return {'schema_version':1,'kind':'numerical-reference-deck','context':numerical_context(c),
            'axes':[{'id':a,'unit':'GeV' if a=='mu' else 'GeV^2'} for a in c['axes']],
            'components':[{'id':k,'unit':'GeV^'+str(4-2*c['propagators']),'convention':NORMALIZATION+'; '+k,'atol':atol,'rtol':rtol} for k in ('real','imag')],
            'training_points':[r for r in rows if r['id'] not in heldout_ids],'heldout_points':[r for r in rows if r['id'] in heldout_ids]}
