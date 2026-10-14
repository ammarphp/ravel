"""Exact, supplied same-scale real coefficient-convention transport.

This substitutes c_source = M c_target in a complete quadratic response. It
never derives a physical basis map, evolves a scale, normalizes predictions,
changes uncertainties or evaluates a likelihood. Scientific validity stays
unknown. Decimal/rational source coefficients remain exact; any binary64 card
projection includes its exact rounding residual and declared-domain bound.
"""
from fractions import Fraction
import hashlib
import math
from pathlib import Path
import re

from ravel.physics import eft_functions, model_tool_bridge as custody
from ravel.workflow.state_io import atomic_json, read_json

SCOPE = 'eft-convention-algebra-delivery'
MAX_INPUT_BYTES = 1024 * 1024
MAX_PRODUCTS = 2_000_000


def _closed(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('closed ' + label + ' required')


def _text(value):
    if type(value) is not str or not value.strip() or len(value.encode()) > 4096:
        raise ValueError('bounded explicit convention description required')


def _q(value):
    # Numeric JSON floats are refused: their lexical source has already rounded.
    value = eft_functions.rational(value)
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > 4096:
        raise ValueError('exact arithmetic exceeds rational bit bound')
    return value


def _s(value):
    value = _q(value)
    return str(value.numerator) + '/' + str(value.denominator)


def _axes(value):
    if (type(value) is not list or not 1 <= len(value) <= 32 or
        any(type(v) is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', v) for v in value) or
        len(set(value)) != len(value)):
        raise ValueError('complete unique ordered real coefficient axes required')
    return value


def _convention(value):
    _closed(value, ('basis', 'axes', 'flavour', 'coefficient_unit', 'lambda_unit',
                    'lambda_gev', 'renormalization_scale_gev', 'coefficient_kind'), 'coefficient convention')
    _axes(value['axes'])
    for key in ('basis', 'flavour', 'coefficient_unit', 'lambda_unit'):
        _text(value[key])
    if value['coefficient_kind'] != 'real' or any(_q(value[k]) <= 0 for k in ('lambda_gev','renormalization_scale_gev')):
        raise ValueError('positive exact scales and real coefficient convention required')
    return value


def _vector(value, length):
    if type(value) is not list or len(value) != length:
        raise ValueError('complete ordered exact coefficient vector required')
    return [_q(v) for v in value]


def _box(value, axes):
    if type(value) is not list or len(value) != len(axes):
        raise ValueError('whole ordered coefficient-coordinate box required')
    box = []
    for row, axis in zip(value, axes):
        _closed(row, ('axis','lower','upper'), 'coefficient interval')
        lo, hi = _q(row['lower']), _q(row['upper'])
        if row['axis'] != axis or lo > hi:
            raise ValueError('ordered nonempty coefficient-coordinate interval required')
        box.append((lo,hi))
    return box


def _inverse(matrix):
    n = len(matrix)
    rows = [list(row) + [Fraction(int(i==j)) for j in range(n)] for i,row in enumerate(matrix)]
    for col in range(n):
        pivot = next((i for i in range(col,n) if rows[i][col]), None)
        if pivot is None:
            raise ValueError('singular/projection map refused: no omitted coefficient directions')
        rows[col],rows[pivot] = rows[pivot],rows[col]
        scale = rows[col][col]
        rows[col] = [_q(v / scale) for v in rows[col]]
        for i in range(n):
            if i == col:continue
            scale = rows[i][col]
            rows[i] = [_q(a - scale*b) for a,b in zip(rows[i],rows[col])]
    return [row[n:] for row in rows]


def validate(task):
    _closed(task, ('request',), 'EFT transport task')
    _text(task['request'])
    return task


def validate_scope(spec):
    policy = spec.get('review_policy',{}).get('policy',{})
    scopes = policy.get('claim_scopes',{})
    if (spec.get('schema_version') != 2 or spec.get('max_attempts') != 1 or
        policy.get('max_redos') != 0 or set(scopes) != {SCOPE} or scopes[SCOPE].get('actions') != ['delivery']):
        raise ValueError('EFT algebra requires version 2 one-attempt delivery-only policy')


def _load(task, base):
    validate(task)
    path = custody._regular(task['request'],base)
    if path.stat().st_size > MAX_INPUT_BYTES:raise ValueError('bounded transport request required')
    request = read_json(path)
    _closed(request, ('schema_version','source','polynomial','map','binary64_policy',
                      'max_abs_coefficient_rounding'), 'EFT transport request')
    if type(request['schema_version']) is not int or request['schema_version'] != 1:
        raise ValueError('transport schema version required')
    _text(request['source'])
    if request['binary64_policy'] != 'nearest_recorded' or _q(request['max_abs_coefficient_rounding']) < 0:
        raise ValueError('explicit binary64 rounding ceiling required')
    docs = []
    for key in ('polynomial','map'):
        p = custody._pin(request[key],path.parent)
        if p.stat().st_size > MAX_INPUT_BYTES:raise ValueError('bounded convention source required')
        docs.append((p,read_json(p)))
    return path,request,*docs


def _read(task, base):
    path,request,(pp,poly),(mp,mapping) = _load(task,base)
    _closed(poly, ('schema_version','convention','quadratic','observables','sources'), 'source polynomial')
    _closed(mapping, ('schema_version','source_convention','target_convention','direction','matrix',
                      'source_domain','target_domain','rge_policy','sources'), 'supplied coefficient map')
    if (type(poly['schema_version']) is not int or poly['schema_version'] != 1 or
        type(mapping['schema_version']) is not int or mapping['schema_version'] != 1 or
        type(poly['quadratic']) is not bool):raise ValueError('explicit polynomial/map schema and truncation required')
    source = _convention(poly['convention']);target = _convention(mapping['target_convention'])
    if mapping['source_convention'] != source or len(source['axes']) != len(target['axes']):
        raise ValueError('exact complete source convention differs')
    if (mapping['direction'] != 'source_coefficients=matrix*target_coefficients' or
        mapping['rge_policy'] != 'not_applied_same_scale' or
        any(source[k] != target[k] for k in ('coefficient_unit','lambda_unit','lambda_gev','renormalization_scale_gev'))):
        raise ValueError('same exact units/scales only; no inferred scale evolution')
    n = len(source['axes'])
    if type(mapping['matrix']) is not list or len(mapping['matrix']) != n:
        raise ValueError('complete square supplied map required')
    matrix = [_vector(row,n) for row in mapping['matrix']]
    inverse = _inverse(matrix)
    source_box = _box(mapping['source_domain'],source['axes']);target_box = _box(mapping['target_domain'],target['axes'])
    for row,(lo,hi) in zip(matrix,source_box):
        mapped_lo = sum(min(a*l,a*h) for a,(l,h) in zip(row,target_box))
        mapped_hi = sum(max(a*l,a*h) for a,(l,h) in zip(row,target_box))
        if mapped_lo < lo or mapped_hi > hi:
            raise ValueError('target coordinate box maps outside declared source box')
    observations = poly['observables']
    if type(observations) is not list or not 1 <= len(observations) <= 32:
        raise ValueError('finite complete observable population required')
    identities=[];bins=0;products=0
    for obs in observations:
        _closed(obs, ('ID','name','bins','unit','sm','linear','quadratic'), 'whole polynomial observable')
        for key in ('ID','name','unit'):_text(obs[key])
        if (type(obs['bins']) is not list or not 1 <= len(obs['bins']) <= 64 or
            len(set(obs['bins'])) != len(obs['bins'])):raise ValueError('whole unique observable bins required')
        for label in obs['bins']:_text(label)
        count=len(obs['bins']);bins+=count;identities.append(obs['ID'])
        _vector(obs['sm'],count)
        if type(obs['linear']) is not list or len(obs['linear']) != n:
            raise ValueError('complete ordered signed linear terms required')
        for row,axis in zip(obs['linear'],source['axes']):
            _closed(row,('axis','data'),'signed linear term')
            if row['axis']!=axis:raise ValueError('linear coefficient order differs')
            _vector(row['data'],count);products+=count*sum(bool(v) for v in matrix[source['axes'].index(axis)])
        pairs=[(i,j) for i in range(n) for j in range(i,n)] if poly['quadratic'] else []
        if type(obs['quadratic']) is not list or len(obs['quadratic'])!=len(pairs):
            raise ValueError('complete ordered absolute square/cross monomials required')
        for row,(i,j) in zip(obs['quadratic'],pairs):
            _closed(row,('axes','data'),'absolute quadratic monomial')
            if row['axes']!=[source['axes'][i],source['axes'][j]]:raise ValueError('quadratic alias/order differs')
            coeffs=_vector(row['data'],count)
            products+=sum(bool(v) for v in coeffs)*sum(bool(v) for v in matrix[i])*sum(bool(v) for v in matrix[j])
    if len(set(identities))!=len(identities) or bins>256 or products>MAX_PRODUCTS:
        raise ValueError('duplicate/oversized whole polynomial population')
    evidence=[]
    for document,p in ((poly,pp),(mapping,mp)):
        if type(document['sources']) is not list or not document['sources']:
            raise ValueError('actual polynomial and map evidence pins required')
        evidence.extend(custody._pin(pin,p.parent) for pin in document['sources'])
    return path,request,poly,mapping,matrix,inverse,target_box,sorted(set([path,pp,mp,*evidence]))


def inputs(task,base):return _read(task,base)[-1]


def compile_transport(task,base):
    path,request,poly,mapping,matrix,inverse,box,paths = _read(task,base)
    n=len(matrix);target=mapping['target_convention'];axes=target['axes']
    sparse=[[(a,value) for a,value in enumerate(row) if value] for row in matrix]
    rows=[];native=[];rounding=[]
    ceiling=_q(request['max_abs_coefficient_rounding'])
    def project(value):
        value=_q(value)
        try:number=float(value)
        except OverflowError as exc:raise ValueError('native coefficient projection overflows') from exc
        if not math.isfinite(number):raise ValueError('native coefficient projection nonfinite')
        delta=_q(Fraction.from_float(number)-value)
        if abs(delta)>ceiling:raise ValueError('native coefficient rounding exceeds declared ceiling')
        return number,_s(delta)
    for obs in poly['observables']:
        count=len(obs['bins']);linear=[[Fraction(0) for _ in range(count)] for _ in axes]
        quad={(a,b):[Fraction(0) for _ in range(count)] for a in range(n) for b in range(a,n)} if poly['quadratic'] else {}
        for i,row in enumerate(obs['linear']):
            for a,weight in sparse[i]:
                for k,value in enumerate(row['data']):linear[a][k]=_q(linear[a][k]+_q(value)*weight)
        for row in obs['quadratic']:
            i,j=[poly['convention']['axes'].index(axis) for axis in row['axes']]
            for a,wa in sparse[i]:
                for b,wb in sparse[j]:
                    values=quad[min(a,b),max(a,b)]
                    for k,value in enumerate(row['data']):
                        value=_q(value)
                        if value:values[k]=_q(values[k]+value*wa*wb)
        output={'ID':obs['ID'],'name':obs['name'],'bins':obs['bins'],'unit':obs['unit'],
           'sm':[_s(v) for v in obs['sm']],
           'linear':[{'axis':axis,'data':[_s(v) for v in linear[a]]} for a,axis in enumerate(axes)],
           'quadratic':[{'axes':[axes[a],axes[b]],'data':[_s(v) for v in values]} for (a,b),values in quad.items()]}
        rows.append(output)
        terms=[([],output['sm'])]+[([r['axis']],r['data']) for r in output['linear']]
        terms.extend((r['axes'],r['data']) for r in output['quadratic'])
        projection=[];errors=[];bound=[Fraction(0) for _ in range(count)]
        for monomial,data in terms:
            converted=[project(v) for v in data]
            projection.append({'axes':monomial,'data':[v for v,_ in converted]})
            errors.append({'axes':monomial,'residual_binary64_minus_exact':[d for _,d in converted]})
            factor=math.prod(max(abs(lo),abs(hi)) for lo,hi in [box[axes.index(a)] for a in monomial])
            for k,(_,delta) in enumerate(converted):bound[k]=_q(bound[k]+abs(_q(delta))*factor)
        native.append({'ID':obs['ID'],'name':obs['name'],'terms':projection})
        rounding.append({'ID':obs['ID'],'terms':errors,'absolute_response_error_bound_on_declared_box':[_s(v) for v in bound]})
    return {'schema_version':1,'kind':'eft_coefficient_transport','status':'passed','status_scope':SCOPE,
        'source_convention':poly['convention'],'target_convention':target,'quadratic':poly['quadratic'],
        'direction':mapping['direction'],'inverse_matrix':[[_s(v) for v in row] for row in inverse],
        'source_domain':mapping['source_domain'],'target_domain':mapping['target_domain'],
        'observables':rows,'binary64_projection':native,'rounding':rounding,
        'source_pins':[{'path':str(p),'sha256':custody._hash(p)} for p in paths],
        'rge_applied':False,'normalization_applied':False,'uncertainties_changed':False,
        'physical_basis_equivalence':'unknown','eft_applicability':'unknown','physics_validated':False,
        'execution_authorized':False,'limits':['Exact supplied coordinate algebra and recorded binary64 projection only.',
          'Map provenance and physical operator/flavour/basis equivalence require independent review.',
          'Coordinate-box inclusion is algebraic; it does not establish an EFT-valid domain.',
          'No Taylor normalization, RGE, likelihood replacement, threshold, fit or covariance transformation.']}


def verify_result(task,base,result):
    if result!=compile_transport(task,base):raise ValueError('transport result differs from current exact source calculation')
    return result


def _identity(paths):
    rows={}
    for p in paths:
        p=custody._regular(p,Path.cwd());s=p.stat()
        rows[str(p)]=(custody._hash(p),s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_mode)
    return rows


def run(task,base,output):
    from ravel.workflow import science
    out=Path(output).absolute();plan=None
    for rd in (out,*out.parents):
        if (rd/'inputs/science-plan.json').is_file():
            plan=science.verify_worker(rd);spec=science.execution_spec(rd);validate_scope(spec)
            if spec['mode']!='eft-convention-transport' or spec['task']!=task or out!=(rd/plan['output_directory']).resolve():
                raise ValueError('exact ordinary EFT algebra approval required')
            break
    if plan is None:raise ValueError('approved ordinary EFT algebra worker required')
    if any(p.is_symlink() for p in (out,*out.parents)) or (out/'eft-convention-transport.json').exists():
        raise ValueError('fresh ordinary EFT algebra output without aliases required')
    paths=inputs(task,base);before=_identity(paths)
    result=compile_transport(task,base)
    if before!=_identity(paths):raise ValueError('EFT convention source identity changed during transport')
    atomic_json(out/'eft-convention-transport.json',result)
    return result
