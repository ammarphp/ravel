"""Bounded fixed-point derivative stencils for existing native evaluators.

No likelihood, native runtime, optimizer, covariance or sampling is created here.
The kernel plans explicit complete coordinate assignments, then reduces supplied
native NLL rows with exact rational arithmetic on their returned binary64 values.
Ordinary source/execution/review custody must authenticate those observations.
"""
from copy import deepcopy
from fractions import Fraction
import hashlib
import itertools
import json
import math
import re

NAME=re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')
MAX_PARAMETERS=4096
MAX_AXES=7
MAX_POINTS=256
ROLES={'poi','nuisance','observable','global_observable','fixed'}

def _keys(v, names, label):
    if type(v) is not dict or set(v)!=set(names):
        raise ValueError('closed '+label+' fields required')

def _number(v, label):
    if type(v) not in (int,float):raise ValueError('finite binary64 '+label+' required')
    try:x=float(v)
    except (OverflowError,ValueError) as exc:raise ValueError('representable '+label+' required') from exc
    if not math.isfinite(x) or type(v) is int and int(x)!=v:
        raise ValueError('exactly representable finite '+label+' required')
    return x

def _hash(v):
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def _float(v, label):
    try:x=float(v)
    except (OverflowError,ValueError) as exc:raise ValueError('nonrepresentable '+label) from exc
    if not math.isfinite(x) or v and x==0:raise ValueError('nonrepresentable '+label)
    return x

def _fraction(v):return Fraction.from_float(float(v))

def _rat(v):return {'numerator':str(v.numerator),'denominator':str(v.denominator)}

def _weights(nodes, anchor):
    """Lagrange first/second derivatives at anchor, using actual assigned nodes."""
    xs=[_fraction(x)-_fraction(anchor) for x in nodes]
    first=[];second=[]
    for i,xi in enumerate(xs):
        polynomial=[Fraction(1)];denom=Fraction(1)
        for j,xj in enumerate(xs):
            if i==j:continue
            product=[Fraction(0)]*(len(polynomial)+1)
            for k,a in enumerate(polynomial):product[k]-=xj*a;product[k+1]+=a
            polynomial=product;denom*=xi-xj
        first.append(polynomial[1]/denom);second.append(2*polynomial[2]/denom)
    if sum(first)!=0 or sum(second)!=0:raise ValueError('invalid stencil constant cancellation')
    return first,second

def _nodes(parameter, step):
    x=parameter['value'];lower=parameter['bounds']['min'];upper=parameter['bounds']['max']
    def trial(offsets):
        try:
            nodes=[x if k==0 else _float(_fraction(x)+k*_fraction(step),'stencil assignment') for k in offsets]
        except ValueError:
            return None
        if len(set(nodes))!=3:return None
        if any(lower is not None and v<lower or upper is not None and v>upper for v in nodes):return None
        return nodes
    for mode,offsets in [('central',[-1,0,1]),('forward',[0,1,2]),('backward',[-2,-1,0])]:
        nodes=trial(offsets)
        if nodes is not None:return mode,nodes
    raise ValueError('three distinct in-domain nodes unavailable; no clipping or enlarged domain: '+parameter['name'])

def _refinement(parameters, levels):
    """Observe refinement of assigned grids, independently of requested h.

    Exact radii/spans avoid a second rounding decision. These fields describe
    geometry only: even a contracted grid and identical derivatives cannot
    bound native evaluator bias or establish smoothness/truncation accuracy.
    """
    byname={p['name']:p for p in parameters};axes=[]
    for coarse,fine in zip(levels[0]['axes'],levels[1]['axes']):
        anchor=_fraction(byname[coarse['name']]['value'])
        def geometry(spec):
            xs=[_fraction(v) for v in spec['nodes']]
            return max(abs(v-anchor) for v in xs),max(xs)-min(xs)
        cr,cs=geometry(coarse);fr,fs=geometry(fine)
        repeated=[v.hex() for v in coarse['nodes']]==[v.hex() for v in fine['nodes']]
        contracted=not repeated and fr<cr and fs<cs
        axes.append({'name':coarse['name'],'coarse_mode':coarse['mode'],'fine_mode':fine['mode'],
            'coarse_nodes':coarse['nodes'],'fine_nodes':fine['nodes'],
            'coarse_radius':_rat(cr),'fine_radius':_rat(fr),'coarse_span':_rat(cs),'fine_span':_rat(fs),
            'repeated_node_grid':repeated,'radius_contracts':fr<cr,'span_contracts':fs<cs,
            'mode_changed':coarse['mode']!=fine['mode'],
            'effective_refinement':contracted,
            'status':'repeated_grid' if repeated else 'contracted_grid' if contracted else 'changed_noncontracting_grid',
            'uses_one_sided_stencil':coarse['mode']!='central' or fine['mode']!='central',
            'nominal_uniform_node_orders':{'central':{'first_derivative':2,'second_derivative':2},
                                          'one_sided':{'first_derivative':2,'second_derivative':1}}})
    return {'axes':axes,'all_selected_axes_effectively_refined':all(a['effective_refinement'] for a in axes),
            'repeated_axes':[a['name'] for a in axes if a['repeated_node_grid']],
            'h_h2_agreement_has_accuracy_authority':False,
            'nominal_orders_require_sufficient_smoothness_and_uniform_contracting_nodes':True,
            'actual_rounding_asymmetry_and_boundary_mode_changes_have_no_automatic_order_guarantee':True}

def compile_stencil(request):
    """Compile a fresh prospective ordered population; every point is explicit.

    Bounds are physical coordinate bounds supplied by the source adapter. Null
    means source-declared unbounded; it does not relax finite assignments. Fixed,
    observed/global and discrete coordinates cannot become derivative axes.
    """
    request=deepcopy(request)
    _keys(request,{'schema_version','kind','identity','parameters','axes','max_points'},'stencil request')
    if type(request['schema_version']) is not int or request['schema_version']!=1 or request['kind']!='native-likelihood-stencil':
        raise ValueError('native-likelihood-stencil/v1 required')
    identity=request['identity'];_keys(identity,{'model_sha256','runtime_binding_sha256','evaluation_definition_sha256'},'native evaluation identity')
    if any(type(v) is not str or not re.fullmatch('[0-9a-f]{64}',v) for v in identity.values()):
        raise ValueError('literal source/runtime/evaluation-definition digests required')
    parameters=request['parameters'];axes=request['axes']
    if type(parameters) is not list or not 1<=len(parameters)<=MAX_PARAMETERS:
        raise ValueError('bounded complete ordered parameter population required')
    names=[];byname={}
    for p in parameters:
        _keys(p,{'name','value','constant','kind','role','bounds'},'source coordinate')
        name=p['name']
        if type(name) is not str or not NAME.fullmatch(name) or name in byname:raise ValueError('unique native coordinate name required')
        if (type(p['constant']) is not bool or type(p['kind']) is not str or p['kind'] not in {'continuous','discrete'}
            or type(p['role']) is not str or p['role'] not in ROLES):
            raise ValueError('explicit coordinate type/role/constant state required')
        p['value']=_number(p['value'],'source value')
        _keys(p['bounds'],{'min','max'},'source physical bounds')
        for key in ('min','max'):
            if p['bounds'][key] is not None:p['bounds'][key]=_number(p['bounds'][key],'source bound')
        lo,hi=p['bounds']['min'],p['bounds']['max']
        if lo is not None and hi is not None and lo>hi:raise ValueError('ordered physical bounds required')
        if lo is not None and p['value']<lo or hi is not None and p['value']>hi:raise ValueError('anchor outside physical domain')
        names.append(name);byname[name]=p
    if type(axes) is not list or not 1<=len(axes)<=MAX_AXES:raise ValueError('one to seven ordered derivative axes required')
    axis_names=[]
    for axis in axes:
        _keys(axis,{'name','step'},'derivative axis')
        if type(axis['name']) is not str or axis['name'] not in byname or axis['name'] in axis_names:raise ValueError('unique existing source axes required')
        p=byname[axis['name']]
        if p['constant'] or p['kind']!='continuous' or p['role'] not in {'poi','nuisance'}:raise ValueError('only floating continuous POI/nuisance may be an axis')
        axis['step']=_number(axis['step'],'positive derivative step')
        if axis['step']<=0:raise ValueError('positive derivative step required')
        axis_names.append(axis['name'])
    if type(request['max_points']) is not int or not 1<=request['max_points']<=MAX_POINTS:raise ValueError('explicit one-to-256 point bound required')
    anchor=[p['value'] for p in parameters];points=[];indices={}
    def point(overrides):
        values=list(anchor)
        for name,value in overrides.items():values[names.index(name)]=value
        key=tuple(v.hex() for v in values)
        if key not in indices:
            if len(points)>=request['max_points']:raise ValueError('complete stencil exceeds prospective point budget')
            row={'id':'stencil_'+str(len(points)), 'parameters':[{'name':p['name'],'value':v,'constant':p['constant']} for p,v in zip(parameters,values)]}
            indices[key]=row['id'];points.append(row)
        return indices[key]
    anchor_id=point({});levels=[]
    for scale in (1.0,0.5):
        specs=[]
        for axis in axes:
            step=axis['step']*scale
            if step<=0:raise ValueError('refinement step underflows')
            p=byname[axis['name']];mode,nodes=_nodes(p,step);first,second=_weights(nodes,p['value'])
            ids=[point({axis['name']:v}) for v in nodes]
            specs.append({'name':axis['name'],'requested_step':step,'mode':mode,'nodes':nodes,'point_ids':ids,
                          'first_weights':[_rat(v) for v in first],'second_weights':[_rat(v) for v in second]})
        mixed=[]
        for i,j in itertools.combinations(range(len(axes)),2):
            rows=[]
            wi,_=_weights(specs[i]['nodes'],byname[axis_names[i]]['value']);wj,_=_weights(specs[j]['nodes'],byname[axis_names[j]]['value'])
            for a,b in itertools.product(range(3),repeat=2):
                coefficient=wi[a]*wj[b]
                if coefficient==0:continue
                ident=point({axis_names[i]:specs[i]['nodes'][a],axis_names[j]:specs[j]['nodes'][b]})
                rows.append({'point_id':ident,'coefficient':_rat(coefficient)})
            mixed.append({'axes':[axis_names[i],axis_names[j]],'terms':rows})
        levels.append({'step_scale':scale,'axes':specs,'mixed':mixed})
    body={'schema_version':1,'kind':'native-likelihood-stencil-plan','request':request,'identity':identity,
          'parameter_order':names,'axis_order':axis_names,'anchor_id':anchor_id,'points':points,'levels':levels,
          'effective_refinement':_refinement(parameters,levels),
          'nll_convention':'NLL_not_minus_two_log_likelihood','native_calls':0,'fit_calls':0,
          'numerical_scope':'Finite-difference estimates of the supplied native NLL; no stationarity, covariance, enclosure or inference authority.'}
    return {**body,'plan_sha256':_hash(body)}

def validate_plan(plan):
    if type(plan) is not dict or 'request' not in plan or compile_stencil(plan['request'])!=plan:
        raise ValueError('stencil plan differs from deterministic source request')

def native_point_overrides(plan, original_anchor_overrides):
    """Feed the ordinary evaluator's point API; retain all original anchor overrides."""
    validate_plan(plan)
    if type(original_anchor_overrides) is not dict:raise ValueError('literal anchor overrides required')
    anchor={p['name']:p for p in plan['points'][0]['parameters']}
    for n,v in original_anchor_overrides.items():
        if n not in anchor or anchor[n]['constant'] or _number(v,'anchor override').hex()!=anchor[n]['value'].hex():
            raise ValueError('anchor overrides differ from complete source point')
    result=[]
    for row in plan['points']:
        overrides=deepcopy(original_anchor_overrides)
        for p in row['parameters']:
            if p['name'] in plan['axis_order']:overrides[p['name']]=p['value']
        result.append({'id':row['id'],'parameters':overrides})
    return result

def reduce_observations(plan, observations):
    """Reduce complete ordered observations; no stale/substituted rows are accepted."""
    validate_plan(plan)
    _keys(observations,{'schema_version','kind','identity','plan_sha256','rows'},'native observations')
    if type(observations['schema_version']) is not int or observations['schema_version']!=1 or observations['kind']!='native-likelihood-stencil-observations' or observations['identity']!=plan['identity'] or observations['plan_sha256']!=plan['plan_sha256']:
        raise ValueError('observed source/runtime/definition/plan identity differs')
    rows=observations['rows']
    if type(rows) is not list or len(rows)!=len(plan['points']):raise ValueError('complete native point denominator required')
    values={}
    for row,point in zip(rows,plan['points']):
        _keys(row,{'id','parameters','nll'},'native NLL row')
        if row['id']!=point['id'] or type(row['parameters']) is not list or len(row['parameters'])!=len(point['parameters']):raise ValueError('native point order/coordinate population differs')
        for actual,expected in zip(row['parameters'],point['parameters']):
            _keys(actual,{'name','value','constant'},'native assignment')
            if actual['name']!=expected['name'] or type(actual['constant']) is not bool or actual['constant']!=expected['constant'] or _number(actual['value'],'native assignment').hex()!=expected['value'].hex():
                raise ValueError('native complete assignment/constant state differs')
        values[row['id']]=_fraction(_number(row['nll'],'native NLL'))
    baseline=values[plan['anchor_id']]
    def rational(v):return Fraction(int(v['numerator']),int(v['denominator']))
    def apply(terms):return sum((w*(values[n]-baseline) for n,w in terms),Fraction(0))
    results=[];exact=[]
    for level in plan['levels']:
        n=len(level['axes']);gradient=[];hessian=[[Fraction(0)]*n for _ in range(n)]
        for i,axis in enumerate(level['axes']):
            gradient.append(apply(zip(axis['point_ids'],map(rational,axis['first_weights']))))
            hessian[i][i]=apply(zip(axis['point_ids'],map(rational,axis['second_weights'])))
        for pair in level['mixed']:
            i,j=map(plan['axis_order'].index,pair['axes'])
            v=apply((r['point_id'],rational(r['coefficient'])) for r in pair['terms']);hessian[i][j]=hessian[j][i]=v
        results.append({'step_scale':level['step_scale'],'gradient':[_float(v,'gradient estimate') for v in gradient],
                        'hessian':[[_float(v,'Hessian estimate') for v in row] for row in hessian]})
        exact.append((gradient,hessian))
    dg=[_float(b-a,'h/2-minus-h gradient difference') for a,b in zip(exact[0][0],exact[1][0])]
    dh=[[_float(b-a,'h/2-minus-h Hessian difference') for a,b in zip(ra,rb)] for ra,rb in zip(exact[0][1],exact[1][1])]
    return {'schema_version':1,'kind':'native-likelihood-finite-difference-estimates','status':'estimated',
            'identity':deepcopy(plan['identity']),'plan_sha256':plan['plan_sha256'],'observations_sha256':_hash(observations),
            'parameter_order':plan['parameter_order'],'axis_order':plan['axis_order'],'point_count':len(rows),
            'method':'three_actual_node_Lagrange_derivatives_exact_rational_reduction_of_returned_binary64_NLL',
            'levels':results,'h2_minus_h':{'gradient':dg,'hessian':dh},'raw_nll_range':[float(min(values.values())),float(max(values.values()))],
            'effective_refinement':deepcopy(plan['effective_refinement']),
            'all_returned_nll_values_identical':min(values.values())==max(values.values()),
            'native_evaluation_error_bound':None,'evaluator_noise_qualified':False,'profiler_derivative_qualified':False,
            'stationarity_qualified':False,'covariance_qualified':False,'truncation_error_enclosed':False,'physics_validated':False,
            'limitations':['h/h2 differences are diagnostics, not an error bound or convergence proof.',
                           'Exact reduction cannot recover information lost in native NLL evaluation/rounding.',
                           'Observation document identity does not authenticate execution or full runtime closure; ordinary source/review custody remains required.',
                           'A finite-difference Hessian is not a RooFit covariance, a global optimum or an inference/calibration witness.',
                           'Halving requested h can repeat every actual node; inspect effective_refinement before interpreting agreement.',
                           'One-sided three-node second derivatives have nominal O(h), not O(h^2), bias on a smooth uniform grid.',
                           'Affine evaluator bias can shift both gradients equally and remain invisible to h/h2 agreement.',
                           'Smoothness, native numerical error and derivative accuracy require separate qualification before profiler use.']}
