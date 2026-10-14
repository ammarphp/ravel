"""Source-bound finite 1D derived quantities and conditional delta covariance.

This module performs no event processing or inference. Independent group vectors
define the uncentred Poissonized covariance sum_g v_g v_g^T, never fixed-N sample
covariance. A supplied covariance requires a complete explicit joint basis.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import numpy as np


class DerivedQuantityError(ValueError):
    """The declared source, basis, or transform cannot be admitted."""


def _require(condition, message):
    if not condition:
        raise DerivedQuantityError(message)


def _keys(obj, required, optional=()):
    _require(isinstance(obj, dict), 'object required')
    _require(set(required) <= set(obj) <= set(required) | set(optional), 'missing or unknown keys')


def _text(value):
    _require(isinstance(value, str) and bool(value.strip()), 'nonempty identity required')
    return value


def _number(value):
    _require(type(value) in (float, int), 'finite number required')
    try: converted=float(value)
    except (OverflowError, ValueError) as exc: raise DerivedQuantityError('finite number required') from exc
    _require(math.isfinite(converted), 'finite number required')
    return converted


def _finite_json(value):
    if isinstance(value, dict):
        _require(all(isinstance(k, str) for k in value), 'JSON string keys required')
        for v in value.values(): _finite_json(v)
    elif isinstance(value, list):
        for v in value: _finite_json(v)
    elif isinstance(value, float): _number(value)
    else: _require(value is None or type(value) in (str, int, bool), 'JSON values required')


def _json_bytes(raw):
    def unique(pairs):
        d={}
        for k,v in pairs:
            _require(k not in d, 'duplicate JSON key'); d[k]=v
        return d
    doc=json.loads(raw, object_pairs_hook=unique, parse_constant=lambda x: (_ for _ in ()).throw(DerivedQuantityError('nonfinite JSON')))
    _finite_json(doc)
    return doc


def _sources(sources, base_dir):
    _require(isinstance(sources, list) and 1 <= len(sources) <= 64, 'bounded source pins required')
    found={}
    for pin in sources:
        _keys(pin, ('id','path','sha256','size'))
        ident=_text(pin['id']); _require(ident not in found, 'duplicate source identity')
        path=Path(_text(pin['path']))
        if not path.is_absolute(): path=Path(base_dir)/path
        _require(path.is_file() and not path.is_symlink(), 'regular nonsymlink source required')
        _require(type(pin['size']) is int and 0 <= pin['size'] <= 8_000_000, 'bounded source size required')
        _require(path.stat().st_size == pin['size'], 'source size mismatch')
        raw=path.read_bytes()
        _require(hashlib.sha256(raw).hexdigest() == pin['sha256'], 'source digest mismatch')
        found[ident]=raw
    return found


def _geometry(quantity):
    _keys(quantity, ('axis','bins','unit','representation'))
    _keys(quantity['axis'], ('name','unit'))
    _text(quantity['axis']['name']); _text(quantity['axis']['unit']); _text(quantity['unit'])
    _require(quantity['representation'] in ('integrated','differential'), 'explicit histogram representation required')
    bins=quantity['bins']; _require(isinstance(bins,list) and 1 <= len(bins) <= 128, 'finite 1D bin geometry required')
    ids=[]; previous=None
    for b in bins:
        _keys(b, ('id','low','high')); ident=_text(b['id'])
        _require(ident not in ids and ident not in ('underflow','overflow'), 'duplicate/reserved bin identity')
        low=_number(b['low']); high=_number(b['high'])
        _require(low < high and (previous is None or low == previous), 'ordered contiguous exact bin edges required')
        previous=high; ids.append(ident)
    return ids


def _definition(value, sources):
    _keys(value, ('source','first_line','last_line','text'))
    _require(value['source'] in sources, 'unbound definition source')
    start=value['first_line']; end=value['last_line']
    _require(type(start) is int and type(end) is int and 1 <= start <= end, 'source line interval required')
    try: lines=sources[value['source']].decode('utf-8').splitlines()
    except UnicodeError as exc: raise DerivedQuantityError('definition requires text source') from exc
    _require('\n'.join(lines[start-1:end]) == value['text'] and end <= len(lines), 'definition excerpt mismatch')


def _basis_key(row):
    _keys(row, ('weight','component','bin'))
    return (_text(row['weight']),_text(row['component']),_text(row['bin']))


def _matrix(value, n):
    _require(isinstance(value,list) and len(value)==n and all(isinstance(r,list) and len(r)==n for r in value), 'complete full joint covariance required')
    for row in value:
        for v in row: _number(v)
    C=np.array(value,dtype=float)
    # Do not symmetrize or repair supplied input covariance.
    scale=max(float(np.max(np.abs(C))),np.finfo(float).tiny)
    # A plain float: the diagnostic is public JSON, and a NumPy scalar is not a JSON type.
    tolerance=float(64*np.finfo(float).eps*n*scale)
    _require(bool(np.array_equal(C,C.T)), 'asymmetric covariance')
    eigenvalues=np.linalg.eigvalsh(C)
    _require(bool(np.all(np.isfinite(eigenvalues))),'finite covariance eigendiagnostics required')
    minimum=float(eigenvalues[0])
    _require(minimum >= -tolerance, 'non-positive-semidefinite covariance')
    return C, {'minimum_eigenvalue':minimum,'roundoff_tolerance':tolerance,'matrix_repaired':False}


def _upper(value):
    _require(math.isfinite(value) and value>=0,'finite arithmetic bound required')
    return math.nextafter(value,math.inf)


def _gamma(n):
    """Upward gamma_n for binary64 multiplication/addition error budgets."""
    nu=n*2.**-53
    return _upper(nu/(1.-nu))


def _positive_sum(*values):
    total=0.
    for value in values: total=_upper(total+value)
    return total


def _positive_product(a,b):
    return _upper(a*b)


def _sumabs(row):
    # fsum's occasional platform double-rounding is covered by four final ulps.
    value=math.fsum(abs(float(v)) for v in row)
    return _upper(value+4*math.ulp(value))


def derive(contract: dict, joint: dict, *, base_dir='.') -> dict:
    """Return exact declared central transforms and full J C J^T.

    The input basis includes both flow bins for every component and named weight.
    Flows and all their cross-covariances are retained, but finite-bin transforms
    do not derive flow ratios. Offsets are explicitly fixed conditional inputs.
    """
    _finite_json(contract); _finite_json(joint)
    _keys(contract, ('schema_version','kind','analysis_id','sources','joint_source','weights','components','outputs','output_census','flow_policy','exposure','unsupported_transforms'))
    _require(type(contract['schema_version']) is int and contract['schema_version']==1 and contract['kind']=='derived-quantity-contract', 'unsupported contract schema')
    _text(contract['analysis_id'])
    _require(contract['flow_policy']=='retain_inputs_not_derived', 'unsupported flow policy')
    _require(isinstance(contract['unsupported_transforms'],list) and all(isinstance(v,str) for v in contract['unsupported_transforms']), 'unsupported transform census required')
    sources=_sources(contract['sources'],base_dir)
    _require(contract['joint_source'] in sources and _json_bytes(sources[contract['joint_source']])==joint, 'joint document is not source-bound')
    weights=[]
    for w in contract['weights']:
        _keys(w, ('id','nuisance','direction','source'))
        ident=_text(w['id']); _require(ident not in weights and w['source'] in sources, 'duplicate/unbound weight identity')
        _require(w['direction'] in ('nominal','up','down','alternative'), 'named variation direction required')
        _require((w['direction']=='nominal') == (ident=='nominal') and (w['nuisance'] is None if ident=='nominal' else isinstance(w['nuisance'],str) and bool(w['nuisance'])), 'nominal/nuisance identity mismatch')
        weights.append(ident)
    _require(weights and weights[0]=='nominal' and len(weights)<=16, 'nominal-first bounded weights required')
    _require(isinstance(contract['exposure'],dict) and set(contract['exposure'])==set(weights), 'exact per-weight exposure required')
    for w,e in contract['exposure'].items():
        _keys(e, ('groups','sumw','sumw2','normalization','source','weight_policy'))
        _require(type(e['groups']) is int and e['groups']>0 and e['source'] in sources, 'positive bound group exposure required')
        _number(e['sumw']); _require(_number(e['sumw2'])>=0, 'negative sumw2')
        _text(e['normalization']); _require(e['weight_policy'] in ('nonnegative','signed'), 'explicit weight policy required')
    components={}; bin_ids={}
    for c in contract['components']:
        _keys(c, ('id','path','quantity','scale','definition'))
        ident=_text(c['id']); _require(ident not in components,'duplicate component')
        _text(c['path']); bin_ids[ident]=_geometry(c['quantity']); _definition(c['definition'],sources)
        _require(isinstance(c['scale'],dict) and set(c['scale'])==set(weights), 'exact weight scales required')
        for value in c['scale'].values(): _require(_number(value)>0,'positive declared scale required')
        components[ident]=c
    _require(1 <= len(components) <= 64,'bounded component census required')
    expected={(w,c,b) for w in weights for c in components for b in ['underflow',*bin_ids[c],'overflow']}
    _require(len(expected)<=768,'joint basis exceeds finite adapter budget')
    _keys(joint, ('schema_version','basis','values','uncertainty'), ('native_finalized',))
    _require(type(joint['schema_version']) is int and joint['schema_version']==1 and isinstance(joint['basis'],list), 'unsupported joint schema')
    keys=[_basis_key(r) for r in joint['basis']]
    _require(len(keys)==len(set(keys)) and set(keys)==expected, 'complete exact weight/component/finite/flow basis required')
    n=len(keys); lookup={k:i for i,k in enumerate(keys)}
    _require(isinstance(joint['values'],list) and len(joint['values'])==n,'complete central vector required')
    x=np.array([_number(v) for v in joint['values']])
    uncertainty=joint['uncertainty']; _require(isinstance(uncertainty,dict),'joint uncertainty required')
    groups=None
    if uncertainty.get('kind')=='supplied_covariance':
        _keys(uncertainty, ('kind','matrix','semantics'))
        _text(uncertainty['semantics']); C,diagnostics=_matrix(uncertainty['matrix'],n)
    elif uncertainty.get('kind')=='independent_group_moments':
        _keys(uncertainty, ('kind','groups','semantics'))
        _require(uncertainty['semantics']=='poissonized_independent_groups_uncentred_second_moment', 'unsupported group covariance interpretation')
        _require(isinstance(uncertainty['groups'],list) and 1 <= len(uncertainty['groups'])<=4096,'bounded independent groups required')
        ids=[]; vectors=[]
        for g in uncertainty['groups']:
            _keys(g, ('id','vector')); ident=_text(g['id']); _require(ident not in ids,'duplicate independent group')
            ids.append(ident); _require(isinstance(g['vector'],list) and len(g['vector'])==n,'complete group contribution vector required')
            vectors.append([_number(v) for v in g['vector']])
        groups=np.array(vectors)
        sums=[math.fsum(row[i] for row in vectors) for i in range(n)]
        _require(np.allclose(x,sums,rtol=16*np.finfo(float).eps,atol=0),'group sums disagree with centrals')
        _require(all(e['groups']==len(groups) for e in contract['exposure'].values()),'group exposure mismatch')
        C=groups.T@groups; C,diagnostics=_matrix(C.tolist(),n)
    else: raise DerivedQuantityError('full joint covariance or independent group vectors required; marginal errors cannot determine covariance')
    for (w,c,b),i in lookup.items():
        if contract['exposure'][w]['weight_policy']=='nonnegative':
            _require(x[i]>=0 and (groups is None or bool(np.all(groups[:,i]>=0))), 'negative contribution violates weight policy')
    outputs={}; rows=[]; values=[]; jac=[]; denominators=[]
    for o in contract['outputs']:
        _keys(o, ('id','path','quantity','operation','left','right','denominator_policy','definition','subset_evidence'))
        ident=_text(o['id']); _require(ident not in outputs,'duplicate output')
        _text(o['path']); ids=_geometry(o['quantity']); _definition(o['definition'],sources)
        _require(o['quantity']['unit']=='1' and o['quantity']['representation']=='integrated','dimensionless bin-local output required')
        _require(o['operation'] in ('ratio','efficiency','asymmetry'),'unsupported derived transform')
        _require(o['denominator_policy'] in ('positive','nonzero_signed'),'explicit denominator policy required')
        _require(o['subset_evidence'] is None if o['operation']!='efficiency' else o['subset_evidence'] in sources,'efficiency subset evidence required')
        operand_units=[]
        for form in (o['left'],o['right']):
            _keys(form, ('terms','offset'))
            _require(isinstance(form['terms'],list) and bool(form['terms']),'explicit linear operands required')
            _require(isinstance(form['offset'],list) and len(form['offset'])==len(ids),'explicit fixed offset per finite bin required')
            for z in form['offset']: _number(z)
            seen=set()
            for term in form['terms']:
                _keys(term, ('component','coefficient')); c=term['component']
                _require(c in components and c not in seen,'duplicate/unknown operand component'); seen.add(c)
                _number(term['coefficient']); q=components[c]['quantity']
                _require(q['axis']==o['quantity']['axis'] and q['bins']==o['quantity']['bins'],'exact axis/bin identity join required')
                operand_units.append((q['unit'],q['representation']))
        _require(len(set(operand_units))==1,'operand units/representation mismatch')
        if o['operation']=='efficiency':
            _require(o['denominator_policy']=='positive' and all(e['weight_policy']=='nonnegative' for e in contract['exposure'].values()),'efficiency requires nonnegative weights and positive denominator')
            _require(all(v==0 for f in (o['left'],o['right']) for v in f['offset']) and all(t['coefficient']>=0 for f in (o['left'],o['right']) for t in f['terms']),'efficiency requires nonnegative operands and zero fixed offsets')
        outputs[ident]=o
        for w in weights:
            for bi,b in enumerate(ids):
                def linear(form):
                    row=np.zeros(n)
                    for t in form['terms']: row[lookup[(w,t['component'],b)]]=t['coefficient']*components[t['component']]['scale'][w]
                    return float(row@x)+form['offset'][bi],row
                left,lrow=linear(o['left']); right,rrow=linear(o['right'])
                numerator,nrow=(left,lrow) if o['operation']!='asymmetry' else (left-right,lrow-rrow)
                denominator,drow=(right,rrow) if o['operation']!='asymmetry' else (left+right,lrow+rrow)
                _require(denominator>0 if o['denominator_policy']=='positive' else denominator!=0,'inadmissible/zero denominator')
                if o['operation']=='efficiency':
                    _require(0<=left<=right,'efficiency subset central domain violated')
                    if groups is not None:
                        _require(bool(np.all(groups@lrow <= groups@rrow)), 'supplied groups violate efficiency subset')
                v=numerator/denominator
                with np.errstate(over='ignore',invalid='ignore'):
                    row=nrow/denominator-v*(drow/denominator)
                _require(math.isfinite(v) and bool(np.all(np.isfinite(row))),'nonfinite transform/Jacobian')
                rows.append({'weight':w,'output':ident,'bin':b}); values.append(v); jac.append(row)
                with np.errstate(over='ignore',invalid='ignore'):
                    variance=float(drow@C@drow)
                    relative_variance=float((drow/denominator)@C@(drow/denominator))
                _require(math.isfinite(relative_variance),'nonfinite relative denominator variance')
                denominators.append({'weight':w,'output':ident,'bin':b,'value':denominator,'input_variance':variance if math.isfinite(variance) else None,'variance_scope':'Supplied covariance contraction; absolute binary64 overflow is represented as null, with relative variance retained.','relative_input_variance':relative_variance,'policy':o['denominator_policy']})
    _require(outputs,'derived output census required')
    census=contract['output_census']; _require(isinstance(census,list),'complete booked output census required')
    seen=set(); expected_paths={c['path']:'component' for c in components.values()} | {o['path']:'derived' for o in outputs.values()}
    _require(len(expected_paths)==len(components)+len(outputs),'duplicate component/output path')
    for r in census:
        _keys(r, ('path','kind','visibility')); _require(r['path'] not in seen and expected_paths.get(r['path'])==r['kind'] and r['visibility'] in ('public','internal'),'output census mismatch')
        seen.add(r['path'])
    _require(seen==set(expected_paths),'incomplete booked output census')
    native=joint.get('native_finalized')
    if native is not None:
        _keys(native, ('semantics','basis','values','errors_low','errors_high'))
        _text(native['semantics'])
        _require(native['basis']==rows,'native finite output basis must match exactly')
        for field in ('values','errors_low','errors_high'):
            _require(isinstance(native[field],list) and len(native[field])==len(rows),'complete native finalized finite vector required')
            for value in native[field]: _number(value)
        _require(all(v<=0 for v in native['errors_low']) and all(v>=0 for v in native['errors_high']),'signed native errors required')
    J=np.array(jac)
    sparse=[[(i,float(v)) for i,v in enumerate(row) if v!=0.] for row in J]
    factor_residual=None; forward_bound=None
    if groups is not None:
        vectors=groups.T
        arithmetic='Compensated gradient-group contributions phi_i,g=sum_j J_i,j v_g,j, then upper-pair sum_g phi_i,g phi_k,g mirrored. Original groups and input C are retained.'
    else:
        try:
            vectors=np.linalg.cholesky(C)
            factor_residual=float(np.max(np.abs(vectors@vectors.T-C)))
            # A source-factor residual enclosure follows the standard gamma_n
            # floating dot-product bound, without changing source C or its
            # eigenvalues. It concerns the emitted binary64 J and supplied C.
            lnorm=max(_sumabs(row) for row in vectors)
            input_scale=float(np.max(np.abs(C)))
            source_roundoff=_positive_sum(_positive_product(_gamma(n+4),_positive_product(lnorm,lnorm)),_positive_product(_gamma(4),input_scale),n*math.ulp(0.))
            residual_bound=_positive_sum(factor_residual,source_roundoff)
            arithmetic='Numerical Cholesky factor of supplied C; compensated gradient-factor contributions, then upper-pair Gram mirrored. No source/output eigenvalue clipping or input C replacement; factor reconstruction residual retained.'
        except np.linalg.LinAlgError:
            vectors=None
            arithmetic='Nonfactorable supplied C: upper bilinear form computed once by math.fsum over nonzero gradient entries and mirrored; numerical output PSD admission required. Input C is retained without repair.'
    phi=None
    if vectors is not None:
        phi=[[math.fsum(v*float(vectors[j,g]) for j,v in row) for g in range(vectors.shape[1])] for row in sparse]
        if factor_residual is not None:
            jnorm=max(_sumabs(row) for row in J)
            fmax=float(np.max(np.abs(vectors))); phimax=max(abs(v) for row in phi for v in row)
            phi_error=_positive_sum(_positive_product(_gamma(n+4),_positive_product(jnorm,fmax)),n*math.ulp(0.))
            phi_gram=_positive_product(n,_positive_sum(_positive_product(_positive_product(2.,phimax),phi_error),_positive_product(phi_error,phi_error)))
            round_gram=_positive_product(_gamma(n+4),_positive_product(n,_positive_product(phimax,phimax)))
            gram_error=_positive_sum(phi_gram,round_gram,n*math.ulp(0.))
            forward_bound=_positive_sum(_positive_product(_positive_product(jnorm,jnorm),residual_bound),gram_error)
    output_cov=np.zeros((len(J),len(J)))
    for i,left in enumerate(sparse):
        for k in range(i,len(sparse)):
            value=(math.fsum(a*b for a,b in zip(phi[i],phi[k])) if phi is not None else
                   math.fsum(a*float(C[j,l])*b for j,a in left for l,b in sparse[k]))
            output_cov[i,k]=output_cov[k,i]=value
    _require(bool(np.all(np.isfinite(output_cov))),'nonfinite propagated covariance')
    _,output_diagnostics=_matrix(output_cov.tolist(),len(J))
    return copy.deepcopy({'schema_version':1,'kind':'derived-quantity-result','analysis_id':contract['analysis_id'],'sources':contract['sources'],'joint_source':contract['joint_source'],'weights':contract['weights'],'components':contract['components'],'outputs':contract['outputs'],'exposure':contract['exposure'],'output_census':census,'quantities':{k:v['quantity'] for k,v in outputs.items()},'input_basis':joint['basis'],'input_values':joint['values'],'input_covariance':C.tolist(),'input_uncertainty':joint['uncertainty'],'output_basis':rows,'values':values,'output_covariance':output_cov.tolist(),'jacobian':J.tolist(),'denominators':denominators,'covariance_diagnostics':diagnostics,'output_covariance_diagnostics':output_diagnostics,'source_factor_residual_max_abs':factor_residual,'factor_covariance_forward_error_bound':forward_bound,'forward_error_scope':'When factorized: scalar maximum-entry enclosure of numerical covariance versus exact-real J C J^T for the emitted binary64 J and supplied binary64 C. It does not bound source decimal rounding, derivative modelling, or physical uncertainty.','derived_covariance_arithmetic':arithmetic,'native_finalized_separate':native,'flow_policy':contract['flow_policy'],'unsupported_transforms':contract['unsupported_transforms'],'uncertainty_scope':'Conditional first-order delta covariance J C J^T; not calibrated sparse-event inference or native YODA marginal-error parity. Fixed scales/offsets are conditional, with no inferred uncertainty.','inference':None,'physics_validated':False})


def derive_from_file(path, *, expected_sha256: str) -> dict:
    """Admit an externally pinned contract and its internally pinned joint data."""
    path=Path(path)
    _require(path.is_file() and not path.is_symlink() and path.stat().st_size<=1_000_000,'bounded regular contract file required')
    raw=path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest()==expected_sha256,'contract digest mismatch')
    contract=_json_bytes(raw)
    sources=_sources(contract.get('sources'),path.parent)
    _require(contract.get('joint_source') in sources,'bound joint source required')
    return derive(contract,_json_bytes(sources[contract['joint_source']]),base_dir=path.parent)


def prediction_slice(result: dict, basis: list[dict]) -> dict:
    """Project one named-weight prediction with caller-declared exact ordering.

    This is a structural seam to a separate measurement adapter. It does not
    combine experimental covariance, assert independence, or compute a statistic.
    """
    _require(result.get('kind')=='derived-quantity-result','derived result required')
    _require(isinstance(basis,list) and bool(basis),'explicit prediction basis required')
    def key(row):
        _keys(row, ('weight','output','bin'))
        return tuple(_text(row[k]) for k in ('weight','output','bin'))
    available=[key(row) for row in result['output_basis']]; requested=[key(row) for row in basis]
    _require(len(set(requested))==len(requested) and len({r[0] for r in requested})==1,'unique single-weight prediction basis required')
    _require(set(requested)<=set(available),'unknown prediction output/bin identity')
    indices=[available.index(row) for row in requested]
    _require(len(result['values'])==len(available),'prediction central vector mismatch')
    covariance,_=_matrix(result['output_covariance'],len(available))
    return copy.deepcopy({'schema_version':1,'kind':'fixed-derived-ratio-prediction','analysis_id':result['analysis_id'],'basis':basis,'values':[result['values'][i] for i in indices],'covariance':covariance[np.ix_(indices,indices)].tolist(),'projection_indices':indices,'quantities':result['quantities'],'sources':result['sources'],'joint_source':result['joint_source'],'uncertainty_scope':result['uncertainty_scope'],'experimental_independence':None,'statistical_inference':None,'physics_validated':False})


def validate(spec: dict) -> dict:
    """Closed scientific-operation task; the contract digest is mandatory."""
    _keys(spec, ('schema_version','input','contract_sha256'))
    _require(type(spec['schema_version']) is int and spec['schema_version']==1,'unsupported derived task schema')
    _text(spec['input'])
    digest=spec['contract_sha256']
    _require(isinstance(digest,str) and len(digest)==64 and all(c in '0123456789abcdef' for c in digest),'exact contract digest required')
    return copy.deepcopy(spec)


def inputs(spec: dict, base) -> list[Path]:
    """Return the complete admitted contract/source/joint graph, without execution."""
    from ravel.workflow.science import regular
    spec=validate(spec); path=regular(spec['input'],base)
    _require(path.stat().st_size<=1_000_000,'bounded contract file required')
    raw=path.read_bytes(); _require(hashlib.sha256(raw).hexdigest()==spec['contract_sha256'],'contract digest mismatch')
    document=_json_bytes(raw); _sources(document.get('sources'),path.parent)
    files=[path]
    for pin in document['sources']:
        source=regular(pin['path'],path.parent)
        _require(source not in files,'repeated operation input path')
        files.append(source)
    _require(document.get('joint_source') in {p['id'] for p in document['sources']},'bound joint source required')
    return files


def run(spec: dict, base, out) -> dict:
    """Normal operation seam: source admission, deterministic arithmetic, fresh output."""
    from ravel.workflow.state_io import atomic_json
    path=inputs(spec,base)[0]
    result=derive_from_file(path,expected_sha256=spec['contract_sha256'])
    result['status']='passed'
    result['status_scope']='Source-bound finite derived quantities and conditional supplied joint delta covariance only'
    result['input']={'path':str(path),'sha256':spec['contract_sha256']}
    out=Path(out)
    _require(not out.exists() and not out.is_symlink(),'fresh derived output directory required')
    out.mkdir(parents=True,exist_ok=False)
    atomic_json(out/'derived-quantities.json',result)
    return result


def readonly_inputs(task, base, context):
    return inputs(task, base)


def readonly_calculate(spec, base, context):
    path = inputs(spec, base)[0]
    result = derive_from_file(path, expected_sha256=spec['contract_sha256'])
    result['status'] = 'passed'
    result['status_scope'] = 'Source-bound finite derived quantities and conditional supplied joint delta covariance only'
    result['input'] = {'path': str(path), 'sha256': spec['contract_sha256']}
    return result


def readonly_materialize(result, specification, context):
    from ravel.workflow.readonly_preparation import _bytes
    return (('derived-quantities.json', _bytes(result)),)


from ravel.workflow.readonly_preparation import ReadOnlyAdapterV1
READONLY_WORKER_V1 = ReadOnlyAdapterV1(
    (('inputs', inputs), ('_validation_inputs', None), ('run', run), ('derive_from_file', derive_from_file),
     ('readonly_inputs', readonly_inputs), ('readonly_calculate', readonly_calculate),
     ('readonly_materialize', readonly_materialize)),
    readonly_inputs, readonly_calculate, readonly_materialize, True)
