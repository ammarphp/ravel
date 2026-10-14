"""Complete signed scan-rate extraction for the existing SFitterAgents workflow.

Port the released scalar/interference/mixed decomposition as one linear design;
no optimizer, event generation, bin assignment or Monte Carlo law is invented.
Full supplied joint covariance follows the actual linear map. Native multi-bin
normalization stays the exact rate polynomial divided by its integral.
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re

import numpy as np
from ravel.physics import coupling_polynomial as cp, derived_quantities as dq
from ravel.physics.ma5_saf import Capture, MAX_FILE, _identity
from ravel.physics.model_inputs import _fraction
from ravel.workflow import agent_graph, sfitter_workflow as workflow
from ravel.workflow.state_io import atomic_json

SCOPE = 'sfitter_signed_scan_extraction'
METHODS = ('sfitteragents/.claude/agents/sf-kappa-extractor.md',
           'sfitteragents/.claude/skills/sf-parameterize/SKILL.md',
           'sfitteragents/docs/eft/03_parameterization_methodology.md')
MAX_COORDINATES = 768
MAX_SOURCE_BYTES = 128*1024**2
LIMITS = [
    'Observed-rate and sample-origin declarations are supplier premises, not independently authenticated event consumption.',
    'Joint covariance and sampling law are supplied explicitly; sumw2 alone does not imply cross-point independence.',
    'Unweighted linear least squares is the declared extraction map, not an optimal estimator or a physical model test.',
    'All mixed polynomial coefficients multiply Ci*Cj once; a symmetric matrix would store half that coefficient off diagonal.',
    'Coefficients remain absolute integrated/differential rates. Native multi-bin normalization is exact; no Taylor shape transport.',
    'Coefficient Monte Carlo covariance is retained in full, not inserted as a Gaussian/RFit modifier in the native card.',
    'SM order, UFO/operator map, generated-coupling cleanliness, EFT applicability and fit/interval qualification require independent evidence.',
    'Covariance may be singular without design-rank loss; no regularization, whitening or data-dependent covariance weighting is performed.',
    'Residual bands are dimensionful declared criteria, not calibrated simultaneous statistical acceptance probabilities.',
    'Baseline/held-out independence and withholding chronology are declared, not proved by distinct files or sample labels.',
    'The emitted polynomial uses the separate SM template as a fixed offset; its unprovided sampling covariance is not inferred.',
]


def _keys(value, keys, label):
    workflow._closed(value, keys, label)


def _num(value):
    return dq._number(value)


def _array(value, label):
    result = np.asarray(value, dtype=float)
    if not bool(np.all(np.isfinite(result))):
        raise ValueError('nonfinite computed '+label)
    return result


def _vector(value, n, label):
    if type(value) is not list or len(value) != n:
        raise ValueError('complete '+label+' required')
    return [_num(v) for v in value]


def _coordinate(value):
    if type(value) is not str or len(value)>128:
        raise ValueError('literal finite bounded Wilson coordinate required')
    match=re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[EeDd]([+-]?[0-9]+))?',value)
    if match is None or (match.group(1) is not None and abs(int(match.group(1)))>100):
        raise ValueError('bounded decimal Wilson coordinate required')
    result=float(_fraction(value,'Wilson coordinate'))
    if not math.isfinite(result):raise ValueError('finite binary64 Wilson coordinate required')
    return result


def validate(task):
    _keys(task,('request',),'scan-extraction task')
    workflow.sfitter_native._text(task['request'],'request pathname')
    return copy.deepcopy(task)


def validate_scope(spec):
    policy=spec.get('review_policy',{}).get('policy',{})
    scopes=policy.get('claim_scopes',{})
    if (spec.get('schema_version')!=2 or spec.get('max_attempts')!=1 or
        policy.get('max_redos')!=0 or spec.get('max_seconds',61)>60 or set(scopes)!={SCOPE} or scopes[SCOPE].get('actions')!=['delivery']):
        raise ValueError('one-attempt delivery-only scan extraction required')


def _pins(capture):
    return [{'path':str(p),'sha256':hashlib.sha256(v[1]).hexdigest()} for p,v in sorted(capture.files.items())]


class _SourceCapture(Capture):
    """Reserve the remaining unique source budget before opening each payload."""
    def bounded(self, path):
        before=self.ordinary(path)
        if not 0<before[3]<=MAX_FILE:
            raise ValueError('bounded nonempty supplied file required')
        remaining=(MAX_FILE if path in self.files else
                   MAX_SOURCE_BYTES-sum(len(raw) for _,raw in self.files.values()))
        if before[3]>remaining:
            raise ValueError('complete scan source graph exceeds aggregate byte ceiling')
        limit=min(MAX_FILE,remaining)
        with path.open('rb') as stream:
            if _identity(os.fstat(stream.fileno()))!=before:
                raise ValueError('input replaced before capture')
            raw=stream.read(limit+1)
            if _identity(os.fstat(stream.fileno()))!=before:
                raise ValueError('input changed during capture')
        if self.ordinary(path)!=before or len(raw)!=before[3]:
            raise ValueError('input pathname changed during capture')
        return before,raw

    def pin(self, value, base):
        result=super().pin(value,base)
        if sum(len(raw) for _,raw in self.files.values())>MAX_SOURCE_BYTES:
            raise ValueError('complete scan source graph exceeds aggregate byte ceiling')
        return result


def _load(request, base):
    _keys(request,('schema_version','id','workflow','rates','scan_definition','coupling_sanity_evidence','criteria'),'scan-extraction request')
    if type(request['schema_version']) is not int or request['schema_version']!=1:
        raise ValueError('scan-extraction schema1 required')
    workflow.sfitter_native._text(request['id'],'extraction identity')
    capture=_SourceCapture();wp,raw=capture.pin(request['workflow'],base)
    wf=workflow._strict_document(raw);workflow.validate(wf)
    if set(wf['handoffs'])!={'extraction','sm_template'}:
        raise ValueError('exact full extraction/SM-template handoffs required')
    docs={}
    for phase in ('extraction','sm_template'):
        hp,hr=capture.pin(wf['handoffs'][phase],wp.parent)
        docs[phase]=workflow._strict_document(hr)
        for pin in workflow._refs(docs[phase]):capture.pin(pin,hp.parent)
        workflow._handoff(wf,docs[phase],hp.parent,phase)
    for pin in workflow.input_pins(wf,wp.parent):capture.pin(pin,wp.parent)
    root,_=workflow._knowledge(wf,wp.parent,'parameterization')
    for relative in METHODS:
        capture.pin({'path':str(root/relative),'sha256':workflow._known()[relative]},root)
    capture.pin(request['coupling_sanity_evidence'],base)
    definition_path,raw=capture.pin(request['scan_definition'],base);definition=workflow._strict_document(raw)
    _keys(definition,('schema_version','target_sha256','points','sources'),'complete original scan definition')
    if type(definition['schema_version']) is not int or definition['schema_version']!=1 or definition['target_sha256']!=agent_graph.digest(wf['target']):
        raise ValueError('source-defined scan population must bind exact target')
    if type(definition['sources']) is not list or not definition['sources']:raise ValueError('located original scan design required')
    for pin in definition['sources']:capture.pin(pin,definition_path.parent)
    rp,raw=capture.pin(request['rates'],base);rates=workflow._strict_document(raw)
    _keys(rates,('schema_version','kind','target_sha256','eft','process','perturbative_order',
                 'bins','points','joint_covariance','sampling','sources','normalization_uncertainty'),'observed scan-rate deck')
    target=wf['target'];basis=target['eft']['basis']
    if (type(rates['schema_version']) is not int or rates['schema_version']!=1 or
        rates['kind']!='supplied_observed_scan_rates' or rates['target_sha256']!=agent_graph.digest(target) or
        rates['eft']!=target['eft'] or rates['process']!=target['process'] or
        rates['perturbative_order']!=target['perturbative_order']):
        raise ValueError('observed rates must bind exact whole scientific target/convention/order')
    if type(rates['sources']) is not list or not 1<=len(rates['sources'])<=1024:
        raise ValueError('complete original rate/analysis/weight source pins required')
    for pin in rates['sources']:capture.pin(pin,rp.parent)
    if rates['normalization_uncertainty'] not in ('conditional_fixed_denominators','joint_delta_denominators'):
        raise ValueError('explicit fixed or complete joint-delta denominator uncertainty required')
    sampling=rates['sampling']
    _keys(sampling,('law','description','source_relationships'),'explicit Monte Carlo covariance premise')
    if sampling['law']!='supplied_joint_covariance':raise ValueError('no MC law inferred from weight sums')
    for key in ('description','source_relationships'):workflow.sfitter_native._text(sampling[key],key)
    wanted=[]
    for ob,ext in zip(target['observables'],docs['extraction']['payload']['rows']):
        for ident,width in zip(ob['bins'],ext['bin_widths']):
            wanted.append({'observable_id':ob['ID'],'bin_id':ident,'unit':ob['unit'],
                           'representation':ob['representation'],'bin_width':width})
    if rates['bins']!=wanted:raise ValueError('complete exact bin order/unit/width/representation required')
    b=len(wanted);points=rates['points']
    if type(points) is not list or not 2<=len(points)<=512 or len(points)*b>MAX_COORDINATES:
        raise ValueError('bounded complete joint point/bin population required')
    if type(definition['points']) is not list or len(definition['points'])!=len(points):raise ValueError('all source-defined scan points required')
    for original,row in zip(definition['points'],points):
        _keys(original,('id','component','role','values','selected_weight','weight_ids'),'source-defined point population')
        if {k:row.get(k) for k in ('id','component','role','values','selected_weight')}!={k:original[k] for k in ('id','component','role','values','selected_weight')} or original['weight_ids']!=[w.get('id') for w in row.get('weight_population',[])]:
            raise ValueError('observed point/component/role/coordinate/weight census differs from source definition')
    names=set();coordinates=[];factors=[];data=[];rows=[]
    for row in points:
        _keys(row,('id','component','role','values','rates','normalization','weight_population',
                   'selected_weight','sources','independence'),'observed rate point')
        identity=row['id'];workflow.sfitter_native._text(identity,'point identity')
        if identity in names:raise ValueError('duplicate observed scan point')
        names.add(identity)
        if row['component'] not in ('total','linear','quadratic','sm') or row['role'] not in ('training','held_out','sm_reference'):
            raise ValueError('explicit total/isolated component and point role required')
        if type(row['values']) is not dict or set(row['values'])!=set(basis):
            raise ValueError('all ordered native Wilson axes required; no omitted zero inference')
        values=[_coordinate(row['values'][axis]) for axis in basis]
        if row['component']=='sm' and any(values):raise ValueError('SM component requires all coefficients zero')
        if row['role']=='sm_reference' and (row['component']!='sm' or any(values)):
            raise ValueError('separate SM reference must be an explicit SM point')
        if row['component']=='quadratic' and not target['eft']['quadratic']:
            raise ValueError('isolated quadratic observation conflicts with truncation')
        _keys(row['independence'],('declared','basis'),'point independence declaration')
        if type(row['independence']['declared']) is not bool:raise ValueError('literal independence premise required')
        workflow.sfitter_native._text(row['independence']['basis'],'independence basis')
        if type(row['sources']) is not list or not row['sources']:raise ValueError('located point return/summary source required')
        for pin in row['sources']:
            source,_=capture.pin(pin,rp.parent)
            if source not in [Path(p['path']) if Path(p['path']).is_absolute() else rp.parent/p['path'] for p in rates['sources']]:
                raise ValueError('point source absent from complete raw-source population')
        weights=row['weight_population']
        if type(weights) is not list or not weights:raise ValueError('complete original weight census required')
        weight_ids=set()
        for weight in weights:
            _keys(weight,('id','events','positive','negative','zero','sumw','sumw2'),'original signed weight census')
            workflow.sfitter_native._text(weight['id'],'weight identity')
            if weight['id'] in weight_ids:raise ValueError('duplicate weight identity')
            weight_ids.add(weight['id'])
            for key in ('events','positive','negative','zero'):
                if type(weight[key]) is not int or not 0<=weight[key]<=10**12:raise ValueError('finite complete weight count required')
            if weight['events']!=weight['positive']+weight['negative']+weight['zero']:
                raise ValueError('signed weight denominator count differs')
            (_coordinate if type(weight['sumw']) is str else _num)(weight['sumw'])
            if (_coordinate if type(weight['sumw2']) is str else _num)(weight['sumw2'])<0:raise ValueError('nonnegative sumw2 required')
        if row['selected_weight'] not in weight_ids:raise ValueError('selected scan weight absent from original weight census')
        norm=row['normalization']
        _keys(norm,('scale','denominator','divide_by_bin_width','description'),'explicit point normalization')
        workflow.sfitter_native._text(norm['description'],'normalization basis')
        scale=_vector(norm['scale'],b,'normalization scales');denom=_vector(norm['denominator'],b,'normalization denominators')
        flags=([norm['divide_by_bin_width']]*b if type(norm['divide_by_bin_width']) is bool else norm['divide_by_bin_width'])
        if type(flags) is not list or any(type(flag) is not bool for flag in flags) or flags!=[x['representation']=='differential' for x in wanted]:
            raise ValueError('normalization must use exact declared bin representation')
        if any(v==0 for v in denom):raise ValueError('zero generator/luminosity normalization denominator')
        factor=_array([s/d/(x['bin_width'] if flag else 1.) for s,d,x,flag in zip(scale,denom,wanted,flags)],'normalization factors')
        raw_values=_vector(row['rates'],b,'raw signed rates')
        factors.extend(factor.tolist());data.append(raw_values);coordinates.append(values);rows.append(row)
    covariance=rates['joint_covariance']
    _keys(covariance,('coordinates','matrix','provenance'),'complete cross-point/bin covariance')
    rate_order=[{'point_id':r['id'],'observable_id':x['observable_id'],'bin_id':x['bin_id'],'quantity':'rate'} for r in points for x in wanted]
    order=rate_order+([{**row,'quantity':'denominator'} for row in rate_order] if rates['normalization_uncertainty']=='joint_delta_denominators' else [])
    if len(order)>MAX_COORDINATES:raise ValueError('bounded full normalization joint coordinate population required')
    if covariance['coordinates']!=order:raise ValueError('covariance must include every point/bin in exact order')
    workflow.sfitter_native._text(covariance['provenance'],'covariance origin')
    C,cov_diag=dq._matrix(covariance['matrix'],len(order))
    if not any(r['role']=='sm_reference' for r in rows) or not any(r['role']=='held_out' for r in rows):
        raise ValueError('whole separate SM reference and withheld residual population required')
    criteria=request['criteria']
    _keys(criteria,('rcond','max_condition','max_residual','max_sm_difference','max_baseline_difference'),'declared extraction criteria')
    if not 0<_num(criteria['rcond'])<1 or _num(criteria['max_condition'])<1:
        raise ValueError('positive rank tolerance and condition ceiling required')
    for key in ('max_residual','max_sm_difference','max_baseline_difference'):
        if any(v<0 for v in _vector(criteria[key],b,'dimensionful per-bin '+key)):
            raise ValueError('nonnegative declared dimensionful criterion required')
    if sum(len(raw) for _,raw in capture.files.values())>MAX_SOURCE_BYTES:
        raise ValueError('complete scan source graph exceeds aggregate byte ceiling')
    capture.finish()
    return capture,wf,docs,rates,coordinates,np.asarray(data),np.asarray(factors),C,cov_diag


def input_pins(request,base):
    capture,*_=_load(request,base);return _pins(capture)


def inputs(task,base,*,_session=None):
    validate(task);cap=Capture();p,raw=cap.read(task['request'],base)
    request=workflow._strict_document(raw);original,*_=_load(request,p.parent)
    original.finish();cap.finish()
    return [p,*original.files]


def _design(wf, points, coordinates):
    basis=wf['target']['eft']['basis'];terms=workflow._terms(wf['target']);rows=[]
    for point,values in zip(points,coordinates):
        row=[float(point['component'] in ('total','sm'))]
        for term in terms:
            axes=term.split('x')
            value=math.prod(values[basis.index(axis)] for axis in axes)
            if ((len(axes)==1 and point['component'] not in ('total','linear')) or
                (len(axes)==2 and point['component'] not in ('total','quadratic'))):value=0.
            row.append(value)
        rows.append(row)
    return _array(rows,'design matrix'),['SM',*terms]


# The covariance law, SVD extraction and held-out arithmetic are the shared
# coupling-polynomial core; this module keeps only the SFitter schema.
_covariance = cp.propagate_covariance


def _calculate(request, wf, docs, rates, coords, raw, factors, C, cov_diag):
    b=len(rates['bins']);n=len(rates['points']);criteria=request['criteria']
    D,terms=_design(wf,rates['points'],coords)
    Y=_array(raw.reshape(-1)*factors,'normalized rate population').reshape(n,b)
    normalization_map=np.diag(factors)
    if rates['normalization_uncertainty']=='joint_delta_denominators':
        denominator=np.asarray([v for p in rates['points'] for v in p['normalization']['denominator']])
        denominator_derivative=_array(-factors*raw.reshape(-1)/denominator,'delta denominator derivative')
        normalization_map=np.column_stack((normalization_map,np.diag(denominator_derivative)))
    Cn,normalized_diag=_covariance(normalization_map,C,'normalized joint covariance')
    train=[i for i,p in enumerate(rates['points']) if p['role']=='training']
    if not train:raise ValueError('training population required')
    X=D[train];extraction=cp.svd_extraction(X,criteria['rcond'],max_condition=criteria['max_condition'])
    s,rank,condition=extraction['singular_values'],extraction['rank'],extraction['condition']
    result={'schema_version':1,'kind':'sfitter_signed_scan_extraction','status_scope':SCOPE,
        'status':'failed','numerical_disposition':'unresolved','method':'unweighted_svd_linear_extraction','term_order':terms,
        'coefficient_coordinate_order':[{'term':term,**row} for term in terms for row in rates['bins']],
        'target_sha256':agent_graph.digest(wf['target']),'eft':wf['target']['eft'],
        'raw_point_population':rates['points'],'sampling':rates['sampling'],'normalization_uncertainty':rates['normalization_uncertainty'],
        'normalization_jacobian':normalization_map.tolist(),
        'normalization_uncertainty_scope':('conditional fixed divisors' if rates['normalization_uncertainty']=='conditional_fixed_denominators' else 'first-order delta ratio covariance; not exact finite-sample or calibrated inference'),
        'bins':rates['bins'],'normalized_rates':Y.tolist(),'normalized_joint_covariance':Cn.tolist(),
        'input_covariance_diagnostics':cov_diag,'normalized_covariance_diagnostics':normalized_diag,'criteria':criteria,
        'design':{'matrix':D.tolist(),'training_point_ids':[rates['points'][i]['id'] for i in train],
                  'rank':rank,'columns':len(terms),'singular_values':s.tolist(),'condition':condition},
        'coefficients':None,'linear_extraction_map':None,'coefficient_covariance':None,'residuals':[],
        'residual_covariance':None,'baseline_checks':[],'kappa':None,'handoff_eligible':False,
        'emitted_coefficients':None,'emitted_linear_response_map':None,'emitted_coefficient_covariance':None,
        'emitted_residual_map':None,'emitted_residuals':[],'emitted_residual_covariance':None,
        'emitted_covariance_scope':'conditional fixed independently supplied SM-template offset; full supplied return covariance retained',
        'physics_validated':False,'execution_authorized':False,'native_fit_completed':False,
        'independence_proven':False,'finite_mc_likelihood_transport':'unimplemented; full covariance retained',
        'normalization_law':'absolute rate polynomial; native exact integral ratio unchanged','limitations':LIMITS}
    if rank!=len(terms):result['reason']='rank_deficient_complete_polynomial';return result
    if condition is None or condition>criteria['max_condition']:
        result['reason']='declared_condition_ceiling_failed';return result
    A=_array(extraction['map'],'linear extraction map')
    coefficients=_array(A@Y[train],'signed polynomial coefficients')
    T=np.zeros((len(terms)*b,n*b))
    for j,i in enumerate(train):T[:,i*b:(i+1)*b]=np.kron(A[:,j:j+1],np.eye(b))
    coefficient_cov,coefficient_diag=_covariance(T,Cn,'full coefficient cross-covariance')
    # R maps all original observations to prediction-minus-observation, retaining
    # training/withheld correlations rather than claiming separate files independent.
    R=_array(np.kron(D,np.eye(b))@T-np.eye(n*b),'full residual map')
    residual=_array((R @ Y.reshape(-1)).reshape(n,b),'all training/held-out/SM residuals')
    residual_cov,residual_diag=_covariance(R,Cn,'full residual covariance')
    baseline=np.asarray([v for row in docs['sm_template']['payload']['rows'] for v in row['data']])
    _array(baseline,'whole SM baseline')
    # The delivered handoff keeps the separate SM template, not the free fitted
    # intercept. Diagnose that actual polynomial as well. Its fixed offset has
    # no invented Monte Carlo covariance; non-SM coefficients retain the same
    # fixed linear extraction map and all training/held-out cross terms.
    emitted=coefficients.copy();emitted[0]=baseline
    E=T.copy();E[:b]=0.
    emitted_cov,emitted_diag=_covariance(E,Cn,'emitted coefficient covariance')
    ER=_array(np.kron(D,np.eye(b))@E-np.eye(n*b),'emitted residual map')
    emitted_residual=_array((ER @ Y.reshape(-1)).reshape(n,b)+D[:,0:1]*baseline,
                            'actually emitted polynomial residuals')
    emitted_residual_cov,emitted_residual_diag=_covariance(ER,Cn,'emitted residual covariance')
    checks=[];ok=True
    for i,point in enumerate(rates['points']):
        passed=bool(np.all(np.abs(residual[i])<=criteria['max_residual']))
        ok=ok and passed
        result['residuals'].append({'point_id':point['id'],'role':point['role'],'component':point['component'],
            'residual':residual[i].tolist(),'passed':passed,'training':i in train})
        emitted_passed=bool(np.all(np.abs(emitted_residual[i])<=criteria['max_residual']))
        ok=ok and emitted_passed
        result['emitted_residuals'].append({'point_id':point['id'],'role':point['role'],'component':point['component'],
            'residual':emitted_residual[i].tolist(),'passed':emitted_passed,'training':i in train})
        if point['role']=='sm_reference':
            difference=_array(Y[i]-baseline,'SM reference difference')
            passed=bool(np.all(np.abs(difference)<=criteria['max_sm_difference']));ok=ok and passed
            checks.append({'point_id':point['id'],'difference':difference.tolist(),'passed':passed})
    difference=_array(coefficients[0]-baseline,'fitted intercept vs SM template')
    passed=bool(np.all(np.abs(difference)<=criteria['max_baseline_difference']));ok=ok and passed
    checks.append({'point_id':'fitted_intercept','difference':difference.tolist(),'passed':passed})
    kappas=[]
    for row in coefficients[1:]:
        kappas.append([None if denominator==0 else _num(float(value/denominator)) for value,denominator in zip(row,baseline)])
    result.update(numerical_disposition='identified',status='passed' if ok else 'failed',reason='declared_criteria_passed' if ok else 'retained_residual_or_baseline_failure',
        coefficients=coefficients.tolist(),linear_extraction_map=A.tolist(),coefficient_covariance=coefficient_cov.tolist(),
        residual_covariance=residual_cov.tolist(),baseline_checks=checks,kappa=kappas,handoff_eligible=ok,
        coefficient_covariance_diagnostics=coefficient_diag,residual_covariance_diagnostics=residual_diag,
        emitted_coefficients=emitted.tolist(),emitted_linear_response_map=E.tolist(),
        emitted_coefficient_covariance=emitted_cov.tolist(),emitted_residual_map=ER.tolist(),
        emitted_residual_covariance=emitted_residual_cov.tolist(),
        emitted_coefficient_covariance_diagnostics=emitted_diag,emitted_residual_covariance_diagnostics=emitted_residual_diag)
    return result


def extract(request,base):
    capture,wf,docs,rates,*numeric=_load(request,base)
    # All computations are checked before comparisons. Overflow never becomes
    # an Inf tolerance, NaN comparison or a passing numerical result.
    with np.errstate(all='raise'):
        try:result=_calculate(request,wf,docs,rates,*numeric)
        except (FloatingPointError,OverflowError,np.linalg.LinAlgError) as exc:
            raise ValueError('scan-extraction numerical arithmetic refused') from exc
    capture.finish();result['inputs']=_pins(capture)
    return result


def _write(path,value,out,capture):
    raw=(json.dumps(value,indent=2,allow_nan=False)+'\n').encode('utf-8')
    if len(raw)>8*1024**2:raise ValueError('bounded scientific output file exceeded')
    atomic_json(path,value);capture.read(path,out,hashlib.sha256(raw).hexdigest())
    return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()}


def materialize(request_pin,base,output,*,_approved_output=False):
    capture=Capture();rp,raw=capture.pin(request_pin,base);request=workflow._strict_document(raw)
    original,wf,docs,*_=_load(request,rp.parent)
    out=Path(output).absolute()
    if ('..' in out.parts or out.is_symlink() or any(p.is_symlink() for p in out.parents) or
        (out.exists() and (not _approved_output or not out.is_dir() or list(out.iterdir()))) or
        any(out.is_relative_to(p.parent) for p in (rp,*original.files))):
        raise ValueError('fresh output must preserve original scientific input directories')
    result=extract(request,rp.parent);original.finish();capture.finish()
    out.mkdir(parents=True,exist_ok=_approved_output);generated=Capture()
    report_pin=_write(out/'scan-extraction.json',result,out,generated)
    written={'scan-extraction.json'};handoff_pin=None;workflow_pin=None
    if result['handoff_eligible']:
        rows=[];offset=0
        for ob in wf['target']['observables']:
            count=len(ob['bins'])
            rows.append({'ID':ob['ID'],'name':ob['name'],'modifiers':[
                {'name':term,'data':values[offset:offset+count]} for term,values in
                zip(result['term_order'][1:],result['coefficients'][1:])],
                'scan_evidence':request['rates'],'coupling_sanity_evidence':request['coupling_sanity_evidence'],
                'fit_diagnostics':report_pin})
            offset+=count
        doc={'schema_version':1,'phase':'parameterization','target_sha256':result['target_sha256'],
            'sources':[request['rates'],request['coupling_sanity_evidence'],report_pin],
            'payload':{'rows':rows},'physics_validated':False,'execution_authorized':False}
        # Make all external evidence pins absolute before moving into a bundle.
        doc=workflow._absolute_pins(doc,rp.parent)
        workflow.apply_handoff(wf,doc,rp.parent)
        handoff_pin=_write(out/'parameterization.json',doc,out,generated)
        # The workflow's own relative references use its original parent.
        wp=Path(request['workflow']['path']);wp=wp if wp.is_absolute() else rp.parent/wp
        next_wf=workflow._absolute_pins(wf,wp.parent)
        next_wf['handoffs']['parameterization']=handoff_pin
        workflow._resolve(next_wf,out)
        workflow_pin=_write(out/'workflow.json',next_wf,out,generated)
        written|={'parameterization.json','workflow.json'}
    receipt={'schema_version':1,'kind':'sfitter_scan_extraction_materialization','report':report_pin,
             'parameterization':handoff_pin,'workflow':workflow_pin,'handoff_eligible':result['handoff_eligible'],
             'execution_authorized':False,'physics_validated':False,'native_fit_completed':False}
    _write(out/'extraction-receipt.json',receipt,out,generated);written.add('extraction-receipt.json')
    members=list(out.rglob('*'))
    if {p.relative_to(out).as_posix() for p in members}!=written:raise ValueError('ending extraction output member census differs')
    for p in members:generated.ordinary(p)
    original.finish();capture.finish();generated.finish()
    return receipt


def graph(request,base,request_pin):
    pins=list({p['path']:p for p in [request_pin,*input_pins(request,base)]}.values())
    if len(pins)>128:raise ValueError('whole extraction source population exceeds Graph input bound')
    return agent_graph.validate({'schema_version':1,'graph_id':request['id']+'_extract',
        'budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':1,'max_wall_seconds':60,'max_reworks':0},
        'nodes':[{'id':'extract','kind':'tool','role':'designer','depends_on':[],
          'inputs':[{'id':'request' if p['path']==request_pin['path'] else 'source'+str(i),**p} for i,p in enumerate(pins)],
          'packet':None,'action':'sfitter-scan-extract','parameters':{'request_input':'request'},'max_attempts':1}]})


def run(task,base,output):
    from ravel.workflow import science
    validate(task);out=Path(output).absolute();plan=None
    for rd in (out,*out.parents):
        if (rd/'inputs/science-plan.json').is_file():
            plan=science.verify_worker(rd);spec=science.execution_spec(rd);validate_scope(spec)
            if spec['mode']!='sfitter-scan-extraction' or spec['task']!=task or out!=(rd/plan['output_directory']).resolve():
                raise ValueError('exact approved scan-extraction task/output required')
            break
    if plan is None:raise ValueError('ordinary approved scan-extraction worker required')
    capture=Capture();rp,raw=capture.read(task['request'],base)
    receipt=materialize({'path':str(rp),'sha256':hashlib.sha256(raw).hexdigest()},base,out,_approved_output=True)
    returned=Capture();_,raw=returned.pin(receipt['report'],out)
    result=workflow._strict_document(raw);returned.finish()
    capture.finish()
    return result


def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--request',required=True);p.add_argument('--output',required=True)
    args=p.parse_args(argv);capture=Capture();rp,raw=capture.read(args.request,Path.cwd())
    materialize({'path':str(rp),'sha256':hashlib.sha256(raw).hexdigest()},Path.cwd(),args.output)
    capture.finish();return 0


if __name__=='__main__':raise SystemExit(main())
