"""Source-preserving fixed-prediction Gaussian ratio diagnostics.

Absolute ratios have no unit-area constraint. General predictions retain both
numerator and denominator. Optional supplied joint component covariance is
propagated with a declared first-order delta method; marginal prediction errors
never create that covariance. No fit, CLs or model-applicability certification.
"""
from __future__ import annotations
import hashlib, math, re
from pathlib import Path
from ravel.physics.measurement import _load, _matrix, _vector
from ravel.physics.quantities import _keys, _number, _text, validate_binning
from ravel.workflow.state_io import atomic_json


def validate(task):
    _keys(task, ('schema_version','input','signal_strength'), label='ratio measurement task')
    if type(task['schema_version']) is not int or task['schema_version']!=1:
        raise ValueError('unsupported ratio measurement task schema')
    _text(task['input'],'ratio input');_number(task['signal_strength'],'signal strength')
    return dict(task)


def _pins(document):
    pins=document.get('grounding',[])
    if not isinstance(pins,list):raise ValueError('ratio grounding must be a list')
    for pin in pins:
        _keys(pin,('path','sha256'),label='ratio grounding identity')
        _text(pin['path'],'grounding path')
        if not isinstance(pin['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',pin['sha256']):
            raise ValueError('ratio grounding requires SHA256')
    return pins


def inputs(task,base):
    from ravel.workflow.science import regular
    path=regular(validate(task)['input'],base);document,_=_load(path);files=[path]
    for pin in _pins(document):
        p=regular(pin['path'],path.parent)
        if hashlib.sha256(p.read_bytes()).hexdigest()!=pin['sha256']:
            raise ValueError('ratio grounding bytes differ')
        files.append(p)
    if len(set(files))!=len(files):raise ValueError('ratio grounding repeats an input')
    return files


def _basis(rows):
    if not isinstance(rows,list) or not rows:raise ValueError('nonempty exact ratio basis required')
    ids=[];groups={}
    for row in rows:
        _keys(row,('id','observable','axis','low','high'),label='ratio basis row')
        ids.append(_text(row['id'],'bin id'))
        name=_text(row['observable'],'observable');_keys(row['axis'],('name','unit'),label='ratio axis')
        for k,v in row['axis'].items():_text(v,'axis '+k)
        group=groups.setdefault(name,{'axis':row['axis'],'bins':[]})
        if group['axis']!=row['axis']:raise ValueError('an observable changes its axis')
        group['bins'].append({k:row[k] for k in ['id','low','high']})
    if len(set(ids))!=len(ids):raise ValueError('ratio basis repeats bin ids')
    for group in groups.values():validate_binning([group['axis']],group['bins'])
    return ids


def _components(record,ids,label,np):
    _keys(record,('bin_ids','values','units'),label=label)
    if (not isinstance(record['bin_ids'],list) or len(record['bin_ids'])!=len(ids)
            or set(record['bin_ids'])!=set(ids) or len(set(record['bin_ids']))!=len(ids)
            or not isinstance(record['values'],list) or len(record['values'])!=len(ids)
            or not isinstance(record['units'],list) or len(record['units'])!=len(ids)):
        raise ValueError('complete component values, units and exact bin ids required')
    order=[record['bin_ids'].index(i) for i in ids]
    values=np.array([_number(record['values'][i],label) for i in order])
    units=[_text(record['units'][i],label+' unit') for i in order]
    return values,units


def _joint(record,ids,units,np,*,bsm_only=False):
    required=('coordinate_ids','coordinate_units','matrix','source','method','experimental_independence')
    if bsm_only:required+=('sm_treatment',)
    _keys(record,required,label='joint component covariance')
    if bsm_only and record['sm_treatment']!='conditional_fixed_central_no_theory_covariance':
        raise ValueError('BSM-only covariance requires explicit conditional fixed-central SM treatment; theory uncertainty remains unknown')
    if record['method']!='first_order_delta_method' or record['experimental_independence']!='declared_independent':
        raise ValueError('explicit delta-method and experimental independence policy required')
    _text(record['source'],'joint covariance source')
    prefixes=['bsm_numerator','bsm_denominator'] if bsm_only else ['sm_numerator','sm_denominator','bsm_numerator','bsm_denominator']
    coordinates=[prefix+'/'+i for prefix in prefixes for i in ids]
    if (record['coordinate_ids']!=coordinates or record['coordinate_units']!=units*len(prefixes)):
        raise ValueError('joint covariance requires exact full component basis/units')
    n=len(coordinates);rows=record['matrix']
    if not isinstance(rows,list) or len(rows)!=n or any(not isinstance(row,list) or len(row)!=n for row in rows):
        raise ValueError('joint covariance matrix population differs')
    m=np.array([[_number(x,'joint covariance cell') for x in row] for row in rows])
    if not np.all(np.isfinite(m)) or not np.array_equal(m,m.T):
        raise ValueError('joint covariance requires a finite exactly symmetric full matrix')
    eigen=np.linalg.eigvalsh(m);scale=float(np.max(np.abs(m)))
    if not np.all(np.isfinite(eigen)):raise ValueError('joint covariance eigendiagnostic overflows')
    tolerance=scale*1e-12
    if float(eigen.min()) < -tolerance:raise ValueError('joint component covariance is not positive semidefinite')
    audit={'minimum_eigenvalue':float(eigen.min()),'numerical_psd_tolerance':tolerance,'matrix_modified':False}
    if bsm_only:audit.update(covariance_scope='supplied_BSM_numerator_denominator_only',sm_treatment=record['sm_treatment'],sm_or_theory_covariance_inferred=False)
    return m,audit


def _fixed_covariance(record,ids,np):
    _keys(record,('bin_ids','matrix','unit','source','method','experimental_independence'),label='fixed prediction covariance')
    if record['experimental_independence']!='declared_independent':
        raise ValueError('fixed prediction covariance requires explicit experimental independence')
    if record['method'] not in ['supplied_fixed_covariance','first_order_delta_method']:
        raise ValueError('fixed prediction covariance requires an explicit supported method')
    _text(record['source'],'fixed prediction covariance source')
    bare={k:record[k] for k in ['bin_ids','matrix','unit']}
    _matrix(bare,ids,'1','fixed prediction covariance',np)
    # Shared validation may average its private temporary matrix. Transport the
    # literal supplied entries instead, and require exact source symmetry.
    order=[record['bin_ids'].index(i) for i in ids]
    matrix=np.asarray(record['matrix'],dtype=float)[np.ix_(order,order)]
    if not np.array_equal(matrix,matrix.T):
        raise ValueError('fixed prediction covariance must be exactly symmetric; no repair')
    eigen=np.linalg.eigvalsh(matrix);scale=float(np.max(np.abs(matrix)))
    if not np.all(np.isfinite(eigen)):raise ValueError('fixed prediction covariance eigendiagnostic overflows')
    return matrix,{'minimum_eigenvalue':float(eigen.min()),'numerical_psd_tolerance':scale*1e-12,
                   'matrix_modified':False,'method':record['method'],'source':record['source'],
                   'experimental_independence':record['experimental_independence']}


def prepare(document,task):
    import numpy as np
    task=validate(task)
    _keys(document,('schema_version','analysis_id','basis','data','experimental_covariance','prediction','applicability','sources'),('grounding',),label='ratio measurement input')
    if type(document['schema_version']) is not int or document['schema_version']!=1:raise ValueError('unsupported ratio input schema')
    _text(document['analysis_id'],'analysis id');_pins(document)
    ids=_basis(document['basis']);n=len(ids);data=_vector(document['data'],ids,'1','data',np)
    _matrix(document['experimental_covariance'],ids,'1','experimental_covariance',np)
    record=document['experimental_covariance'];order=[record['bin_ids'].index(i) for i in ids]
    experimental=np.asarray(record['matrix'],dtype=float)[np.ix_(order,order)]
    if not np.array_equal(experimental,experimental.T):raise ValueError('experimental covariance must be exactly symmetric; no repair')
    _keys(document['applicability'],('scope','prompt_lepton_met_control_contamination','dilepton_efficiency_assumption','theory_covariance'),label='ratio applicability')
    if document['applicability']['scope']!='conditional_fixed_prediction_diagnostic':raise ValueError('explicit conditional fixed-prediction scope required')
    for k,v in document['applicability'].items():_text(v,'applicability '+k)
    _keys(document['sources'],('measurement','covariance','prediction','approximation'),label='ratio sources')
    for k,v in document['sources'].items():_text(v,k+' source')
    p=document['prediction'];mu=task['signal_strength'];prediction_cov=np.zeros((n,n));jacobian=None;domain_audit=[];joint_audit=None;fixed_audit=None;published=None
    if not isinstance(p,dict):raise ValueError('ratio prediction must be an object')
    if p.get('kind')=='fixed_ratio':
        _keys(p,('kind','ratio','baseline_convention'),('prediction_covariance',),label='fixed ratio prediction')
        if p['baseline_convention'] not in ['literal_published_ratio','supplied_derived_ratio'] or mu!=0:
            raise ValueError('fixed ratio requires explicit literal published or supplied derived baseline and mu0')
        values=_vector(p['ratio'],ids,'1','fixed ratio',np)
        if np.any(values<0):raise ValueError('fixed ratio prediction must be nonnegative')
        if 'prediction_covariance' in p:
            prediction_cov,fixed_audit=_fixed_covariance(p['prediction_covariance'],ids,np)
            prediction_scope='Literal supplied fixed ratio and full prediction covariance under its explicit method and declared experimental independence; no covariance inferred from marginal errors'
        else:prediction_scope='Literal supplied fixed ratio; central values only, no prediction covariance inferred'
    elif p.get('kind')=='numerator_denominator':
        _keys(p,('kind','sm_numerator','sm_denominator','bsm_numerator','bsm_denominator','coefficient_convention','signal_strength_domain','baseline_convention'),('published_sm_ratio','joint_component_covariance','bsm_component_covariance'),label='ratio component prediction')
        if p['baseline_convention']!='literal_num_den':raise ValueError('ratio components require literal numerator/denominator baseline')
        components=[_components(p[k],ids,k,np) for k in ['sm_numerator','sm_denominator','bsm_numerator','bsm_denominator']]
        if any(x[1]!=components[0][1] for x in components):raise ValueError('numerator/denominator component units differ')
        sn,sd,bn,bd=[x[0] for x in components];units=components[0][1]
        if np.any(sn<0) or np.any(sd<=0):raise ValueError('SM numerator must be nonnegative and denominator positive')
        convention=p['coefficient_convention'];domain=p['signal_strength_domain']
        if not isinstance(domain,list) or len(domain)!=2:raise ValueError('explicit finite closed signal-strength domain required')
        low,high=[_number(x,'domain bound') for x in domain]
        if low>high or not low<=mu<=high:raise ValueError('signal strength outside declared domain')
        if convention=='positive_additive':
            if low<0 or np.any(bn<0) or np.any(bd<0):raise ValueError('positive-additive contributions/domain must be nonnegative')
        elif convention!='signed_interference':raise ValueError('explicit positive or signed/interference convention required')
        for endpoint in [low,high]:
            numerator,denominator=sn+endpoint*bn,sd+endpoint*bd
            if not np.all(np.isfinite(numerator)) or not np.all(np.isfinite(denominator)) or np.any(numerator<0) or np.any(denominator<=0):
                raise ValueError('final numerator/denominator invalid over declared domain; no clipping')
            domain_audit.append({'signal_strength':endpoint,'numerator':numerator.tolist(),'denominator':denominator.tolist()})
        numerator,denominator=sn+mu*bn,sd+mu*bd;values=numerator/denominator
        jacobian=np.zeros((n,4*n));idx=np.arange(n)
        # Use R/D, rather than N/D**2: a finite domain can have D**2 overflow
        # even though both its ratio and every derivative remain representable.
        jacobian[idx,idx]=1/denominator;jacobian[idx,n+idx]=-values/denominator
        jacobian[idx,2*n+idx]=mu/denominator;jacobian[idx,3*n+idx]=-mu*(values/denominator)
        if not np.all(np.isfinite(jacobian)):raise ValueError('ratio delta-method Jacobian overflows')
        if 'published_sm_ratio' in p:
            published=_vector(p['published_sm_ratio'],ids,'1','published SM ratio',np)
        if 'joint_component_covariance' in p and 'bsm_component_covariance' in p:
            raise ValueError('supply one full joint or BSM-only covariance contract, never both')
        if 'joint_component_covariance' in p or 'bsm_component_covariance' in p:
            bsm_only='bsm_component_covariance' in p
            key='bsm_component_covariance' if bsm_only else 'joint_component_covariance'
            joint,joint_audit=_joint(p[key],ids,units,np,bsm_only=bsm_only)
            covariance_jacobian=jacobian[:,2*n:] if bsm_only else jacobian
            component_count=2 if bsm_only else 4
            # Each analytic entry has16 full-joint or4 BSM-only terms. Evaluate
            # once per symmetric pair and mirror the computed entry; never
            # alter or symmetrize either supplied source covariance matrix.
            for i in range(n):
                for j in range(i,n):
                    value=math.fsum(covariance_jacobian[i,g*n+i]*joint[g*n+i,h*n+j]*covariance_jacobian[j,h*n+j]
                                    for g in range(component_count) for h in range(component_count))
                    prediction_cov[i,j]=prediction_cov[j,i]=value
            prediction_scope=('Supplied full BSM numerator/denominator covariance, conditional fixed-central SM offsets, first-order delta method and declared experimental independence; unknown SM/theory covariance is neither padded nor inferred' if bsm_only else 'Supplied full joint SM/BSM numerator/denominator covariance, first-order delta method and declared independence from experimental data')
        else:prediction_scope='Literal numerator/denominator central values only; no covariance inferred from marginal prediction errors'
    else:raise ValueError('explicit fixed ratio or numerator_denominator prediction required')
    combined=experimental+prediction_cov
    if not np.all(np.isfinite(values)) or not np.all(np.isfinite(combined)):raise ValueError('ratio prediction/covariance overflows')
    # Both source matrices are retained. Only the explicitly derived combined
    # covariance enters this fixed Gaussian statistic; no unit-area projection.
    eigen=np.linalg.eigvalsh(combined)
    if not np.all(np.isfinite(eigen)):raise ValueError('combined ratio covariance eigendiagnostic overflows')
    if eigen.min()<=max(0.,eigen.max()*1e-12):raise ValueError('combined ratio covariance is singular/ill-conditioned; no regularization')
    return {'bin_ids':ids,'data':data,'prediction':values,'experimental_covariance':experimental,'prediction_covariance':prediction_cov,'combined_covariance':combined,'jacobian':jacobian,'domain_audit':domain_audit,'joint_audit':joint_audit,'fixed_audit':fixed_audit,'published_sm_ratio':published,'prediction_scope':prediction_scope,'degrees_of_freedom':n,'covariance_condition_number':float(eigen.max()/eigen.min())}


def diagnose(document,task):
    import numpy as np
    from scipy.stats import chi2
    model=prepare(document,task);residual=model['data']-model['prediction']
    z=np.linalg.solve(np.linalg.cholesky(model['combined_covariance']),residual);statistic=float(z@z)
    p=document['prediction'];baseline=None
    if p['kind']=='numerator_denominator':
        sn,_=_components(p['sm_numerator'],model['bin_ids'],'sm_numerator',np);sd,_=_components(p['sm_denominator'],model['bin_ids'],'sm_denominator',np)
        baseline={'literal_num_den_ratio':(sn/sd).tolist(),'published_expected_ratio':None if model['published_sm_ratio'] is None else model['published_sm_ratio'].tolist(),'published_rounding_residual':None if model['published_sm_ratio'] is None else (sn/sd-model['published_sm_ratio']).tolist(),'convention':'Literal num/den baseline is never replaced by independently rounded expectedRatio times denominator'}
    return {'schema_version':1,'kind':'fixed_prediction_gaussian_ratio_diagnostic','analysis_id':document['analysis_id'],'basis':document['basis'],'bin_ids':model['bin_ids'],'task':validate(task),'sources':document['sources'],'grounding':_pins(document),'input_data':model['data'].tolist(),'input_experimental_covariance':model['experimental_covariance'].tolist(),'prediction':{'values':model['prediction'].tolist(),'unit':'1','source_contract':p,'scope':model['prediction_scope'],'baseline':baseline,'domain_endpoint_audit':model['domain_audit']},'prediction_covariance':model['prediction_covariance'].tolist(),'combined_covariance':model['combined_covariance'].tolist(),'joint_covariance_audit':model['joint_audit'],'fixed_prediction_covariance_audit':model['fixed_audit'],'delta_method_jacobian':None if model['jacobian'] is None else model['jacobian'].tolist(),'normalization':'absolute_ratio_not_unit_area','goodness_of_fit':{'chi2':statistic,'degrees_of_freedom':model['degrees_of_freedom'],'p_value':float(chi2.sf(statistic,model['degrees_of_freedom'])),'scope':'Conditional fixed-hypothesis Gaussian diagnostic under declared covariance/linearized prediction uncertainty; no fitted statistic'},'covariance_condition_number':model['covariance_condition_number'],'applicability':document['applicability'],'fit':None,'inference':None,'status':'passed','physics_validated':False,'limitations':['Published experimental covariance and complete cross-distribution basis are retained without covariance repair or unit-area projection.','No theory/MC covariance is constructed from marginal SM or BSM errors. Supplied joint covariance is propagated only under an explicit first-order delta-method contract; supplied fixed output covariance retains its declared method and source.','Prompt-lepton/MET control contamination and dilepton efficiency corrections require separate source/model applicability review.','Conditional fixed-Gaussian p-values do not reconstruct a published likelihood or establish CLs, detector response or new-model exclusion.']}


def run(task,base,out):
    path=inputs(task,base)[0];document,digest=_load(path);result=diagnose(document,task)
    result['input']={'path':str(path),'sha256':digest};out=Path(out);out.mkdir(parents=True,exist_ok=False)
    atomic_json(out/'ratio-diagnostic.json',result);return result
