"""Lossless named native-array transport; no NumPy/Torch imports or statistics.

Native score/profile conventions are preserved. Completion of serialization is
not evidence of stationarity, interval validity, EFT applicability or coverage.
"""
import base64
import hashlib
import math
import re
import struct

ARRAY_MAPS = ('marginal_1d', 'marginal_1d_bins', 'marginal_2d', 'marginal_2d_bins',
              'profile_1d', 'profile_1d_bins', 'profile_2d', 'profile_2d_bins',
              'marginal_1d_points', 'marginal_2d_points', 'profile_1d_points', 'profile_2d_points')
WEIGHTS = ('w_bins_lin', 'w_hist_lin', 'w_bins_log', 'w_hist_log')
MAX_BYTES = 16 * 1024 * 1024
INITIALIZED_TENSORS = ('smeft_coeffs','smeft_offset','measurements','err_theo','err_gauss',
                       'corr','corr_inv','bin_widths','norm_indices','norm_start')
INITIALIZED_SCALARS = ('corr_shrinkage','syst_rho','n_blocks_substituted')
INITIALIZED_MEANINGS = {'corr':'native_pre_shrinkage_correlation',
    'corr_inv':'native_effective_inverse_metric',
    'err_theo':'native_component_RFit_widths',
    'normalization':'native_multi_bin_width_weighted_ratio_singleton_absolute'}

def initialized_state(likelihood, parameters, origin):
    """Observe existing attributes only; no score, inversion or fit is evaluated."""
    document = {'schema_version':1,'kind':'sfitter_initialized_state',
        'parameters':list(likelihood.parameter_names),'dims_nuisance':likelihood.dims_nuisance,
        'native_origin':origin,
        'native_tensors':{name:array(getattr(likelihood,name).detach().cpu().numpy())
                          for name in INITIALIZED_TENSORS},
        'native_scalars':{name:(getattr(likelihood,name) if name=='n_blocks_substituted'
                            else scalar(getattr(likelihood,name))) for name in INITIALIZED_SCALARS},
        'tensor_meanings':INITIALIZED_MEANINGS.copy(),'physics_validated':False,
        'independent_consistency':'unknown'}
    validate_initialized_state(document,parameters,origin)
    return document

def validate_initialized_state(document, parameters, origin, *, bin_count=None, group_count=None):
    required={'schema_version','kind','parameters','dims_nuisance','native_origin','native_tensors',
              'native_scalars','tensor_meanings','physics_validated','independent_consistency'}
    if (type(document) is not dict or set(document)!=required or
        type(document['schema_version']) is not int or document['schema_version']!=1 or
        document['kind']!='sfitter_initialized_state' or document['parameters']!=parameters or
        type(document['dims_nuisance']) is not int or document['dims_nuisance']!=0 or
        document['native_origin']!=origin or document['physics_validated'] is not False or
        document['independent_consistency']!='unknown' or document['tensor_meanings']!=INITIALIZED_MEANINGS):
        raise ValueError('closed source-bound initialized native state required')
    tensors=document['native_tensors']; scalars=document['native_scalars']
    if (type(tensors) is not dict or set(tensors)!=set(INITIALIZED_TENSORS) or
        type(scalars) is not dict or set(scalars)!=set(INITIALIZED_SCALARS)):
        raise ValueError('whole initialized native tensor/scalar population required')
    total=sum(len(validate_array(value)) for value in tensors.values())
    for name in ('corr_shrinkage','syst_rho'):
        total+=len(validate_array(scalars[name]))
        if scalars[name]['shape']!=[] or scalars[name]['dtype']!='<f8':
            raise ValueError('exact native float64 correlation scalar required')
    blocks=scalars['n_blocks_substituted']
    if type(blocks) is not int or blocks<0 or group_count is not None and blocks>group_count:
        raise ValueError('native published-block count required')
    if total>MAX_BYTES:raise ValueError('initialized native state exceeds byte ceiling')
    if bin_count is not None:
        expected={'smeft_coeffs':[bin_count,len(parameters),len(parameters)+1],
          'smeft_offset':[bin_count],'measurements':[bin_count],'err_theo':[bin_count],
          'err_gauss':[bin_count],'corr':[bin_count,bin_count],'corr_inv':[bin_count,bin_count],
          'bin_widths':[bin_count],'norm_indices':[bin_count]}
        if any(tensors[key]['shape']!=shape for key,shape in expected.items()):
            raise ValueError('initialized native whole-bin geometry changed')
    if group_count is not None and tensors['norm_start']['shape']!=[group_count]:
        raise ValueError('initialized native whole-group geometry changed')
    return document

def array(value):
    """Canonical C-order bytes preserve dtype, shape, nonfinite bits and zeros."""
    dtype = value.dtype.str
    match = re.fullmatch(r'([<>=|])([fiu])(1|2|4|8)', dtype)
    if match is None or (match[2]=='f' and match[3]=='1'):
        raise ValueError('native export requires numeric non-object array dtype')
    shape = list(value.shape)
    if len(shape) > 4 or any(type(x) is not int or x < 0 for x in shape):
        raise ValueError('native array requires bounded integer dimensions')
    expected = math.prod(shape) * int(match[3])
    if expected > MAX_BYTES:
        raise ValueError('native array exceeds byte ceiling')
    raw = value.tobytes(order='C')
    if type(raw) is not bytes or len(raw) != expected:
        raise ValueError('native array shape/dtype/bytes disagree')
    return {'kind': 'numeric_array', 'dtype': dtype, 'shape': shape, 'order': 'C',
            'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'base64': base64.b64encode(raw).decode('ascii')}

def scalar(value):
    if hasattr(value, 'dtype') and hasattr(value, 'shape'):
        return array(value)
    if type(value) is not float:
        raise ValueError('native scalar requires float64 or numeric scalar array')
    raw = struct.pack('<d', value)
    return {'kind': 'numeric_array', 'dtype': '<f8', 'shape': [], 'order': 'C',
            'bytes': 8, 'sha256': hashlib.sha256(raw).hexdigest(),
            'base64': base64.b64encode(raw).decode('ascii')}

def validate_array(record):
    fields = {'kind','dtype','shape','order','bytes','sha256','base64'}
    if type(record) is not dict or set(record) != fields or record['kind'] != 'numeric_array' or record['order'] != 'C':
        raise ValueError('closed native array record required')
    match = re.fullmatch(r'([<>=|])([fiu])(1|2|4|8)', str(record['dtype']))
    shape = record['shape']
    if match is None or (match[2]=='f' and match[3]=='1') or type(shape) is not list or len(shape)>4 or any(type(v) is not int or v<0 for v in shape):
        raise ValueError('invalid native array dtype/shape')
    expected = math.prod(shape)*int(match[3])
    if type(record['bytes']) is not int or expected != record['bytes'] or expected > MAX_BYTES:
        raise ValueError('native array byte population changed')
    try: raw = base64.b64decode(record['base64'], validate=True)
    except (TypeError, ValueError) as exc: raise ValueError('native array encoding invalid') from exc
    if len(raw)!=expected or hashlib.sha256(raw).hexdigest()!=record['sha256']:
        raise ValueError('native array bytes changed')
    return raw

def fit_result(result, parameters, *, algorithm='flow', profile=None):
    if list(result.parameters) != parameters:
        raise ValueError('native returned parameter order differs from admitted basis')
    maps, total = {}, 0
    singles = set(parameters)
    pairs = {(parameters[i],parameters[j]) for i in range(len(parameters)) for j in range(i+1,len(parameters))}
    for name in ARRAY_MAPS:
        value = getattr(result,name)
        expected = pairs if name in ('marginal_2d','profile_2d') else singles
        if type(value) is not dict or set(value) != expected:
            raise ValueError('native result missing/extra full parameter or pair population: '+name)
        rows=[]
        for key, item in value.items():
            encoded=array(item);total+=encoded['bytes']
            rows.append({'key': list(key) if type(key) is tuple else key, 'array': encoded})
        maps[name]=rows
    weights={name:(None if algorithm in ('smc','craft') and getattr(result,name) is None else array(getattr(result,name))) for name in WEIGHTS}
    if algorithm in ('smc','craft') and any(value is not None for value in weights.values()):raise ValueError('SMC/CRAFT unavailable native weights cannot be fabricated')
    total += sum(row['bytes'] for row in weights.values() if row is not None)
    ess=scalar(result.marginal_effective_size);total+=ess['bytes']
    if total>MAX_BYTES:
        raise ValueError('whole native array export exceeds byte ceiling')
    document={'schema_version':1,'kind':'sfitter_native_arrays','parameters':parameters,
            'maps':maps,'weights':weights,'marginal_effective_size':ess,
            'numeric_bytes':total,'score_convention':'native_score=-Q; native_profile=exp(-Q)',
            'raw_log_scores':None,'raw_log_score_reason':'unchanged native FitResults stores exponentials, not lossless log scores',
            'profile_search_qualification':'unknown','interval_qualification':'unknown',
            'eft_applicability':'unknown','coverage_calibration':'unknown','physics_validated':False}
    if profile is not None:
        document.update(schema_version=2,algorithm=algorithm,profile=profile,
            score_convention=('native_score=-Q; native_profile=exp(-Q)' if profile in ('top','higgs') else 'native_diagnostic_log_likelihood; exponential_profile_not_physical_measurement'),
            inference='native_profile_and_marginal_measure_unqualified',
            unavailable_weights='native SMC/CRAFT producer has no flow weight histograms' if algorithm in ('smc','craft') else None,
            marginal_semantics=('unweighted_native_particle_histograms_log_weights_discarded_not_posterior' if algorithm in ('smc','craft') else 'native_flow_importance_weighted_histograms_not_qualified_posterior'),
            prior_semantics=('native_physical_log_prior_zero_no_proper_prior_support_claim' if profile in ('top','higgs') else 'original_diagnostic_log_prior_not_physical_inference'))
    validate_result(document,parameters)
    return document

def validate_result(document, parameters):
    required={'schema_version','kind','parameters','maps','weights','marginal_effective_size','numeric_bytes',
              'score_convention','raw_log_scores','raw_log_score_reason','profile_search_qualification',
              'interval_qualification','eft_applicability','coverage_calibration','physics_validated'}
    version=document.get('schema_version') if type(document) is dict else None
    if version==2:
        required|={'algorithm','profile','inference','unavailable_weights','marginal_semantics','prior_semantics'}
        if document.get('algorithm') not in ('flow','smc','craft') or document.get('profile') not in ('top','higgs','toy','spiral','five_point') or document.get('inference')!='native_profile_and_marginal_measure_unqualified':raise ValueError('exact algorithm/profile/inference scope required')
        reason='native SMC/CRAFT producer has no flow weight histograms' if document['algorithm'] in ('smc','craft') else None
        marginal=('unweighted_native_particle_histograms_log_weights_discarded_not_posterior' if document['algorithm'] in ('smc','craft') else 'native_flow_importance_weighted_histograms_not_qualified_posterior')
        prior=('native_physical_log_prior_zero_no_proper_prior_support_claim' if document['profile'] in ('top','higgs') else 'original_diagnostic_log_prior_not_physical_inference')
        if document['unavailable_weights']!=reason or document['marginal_semantics']!=marginal or document['prior_semantics']!=prior:raise ValueError('native availability/inferential meaning differs')
    if type(document) is not dict or set(document)!=required or type(version) is not int or version not in (1,2) or document['kind']!='sfitter_native_arrays' or document['parameters']!=parameters:
        raise ValueError('closed exact native result required')
    if document['physics_validated'] is not False or any(document[key]!='unknown' for key in ('profile_search_qualification','interval_qualification','eft_applicability','coverage_calibration')) or document['raw_log_scores'] is not None:
        raise ValueError('native export cannot acquire unobserved scientific authority')
    score=('native_diagnostic_log_likelihood; exponential_profile_not_physical_measurement' if version==2 and document['profile'] not in ('top','higgs') else 'native_score=-Q; native_profile=exp(-Q)')
    if document['score_convention']!=score or type(document['raw_log_score_reason']) is not str:
        raise ValueError('native score convention changed')
    if type(document['maps']) is not dict or set(document['maps'])!=set(ARRAY_MAPS) or type(document['weights']) is not dict or set(document['weights'])!=set(WEIGHTS):
        raise ValueError('native exported field population changed')
    singles=set(parameters);pairs={(parameters[i],parameters[j]) for i in range(len(parameters)) for j in range(i+1,len(parameters))}
    total=0
    for name,rows in document['maps'].items():
        expected=pairs if name in ('marginal_2d','profile_2d') else singles
        keys=[]
        if type(rows) is not list:raise ValueError('native map rows required')
        for row in rows:
            if type(row) is not dict or set(row)!={'key','array'}:raise ValueError('closed native map row required')
            key=tuple(row['key']) if type(row['key']) is list else row['key'];keys.append(key)
            total+=len(validate_array(row['array']))
        if len(keys)!=len(expected) or len(set(keys))!=len(keys) or set(keys)!=expected:raise ValueError('native map population changed')
    if version==2 and document['algorithm'] in ('smc','craft'):
        if any(row is not None for row in document['weights'].values()):raise ValueError('native unavailable weight population changed')
    else:total+=sum(len(validate_array(row)) for row in document['weights'].values())
    total+=len(validate_array(document['marginal_effective_size']))
    if type(document['numeric_bytes']) is not int or total!=document['numeric_bytes'] or total>MAX_BYTES:
        raise ValueError('native aggregate bytes changed')
    _geometry(document)
    return document


def _geometry(document):
    maps={name:{tuple(row['key']) if type(row['key']) is list else row['key']:row['array'] for row in rows} for name,rows in document['maps'].items()}
    for prefix in ('marginal','profile'):
        for name in document['parameters']:
            for dimension in ('1d','2d'):
                bins=maps[prefix+'_'+dimension+'_bins'][name]['shape']
                points=maps[prefix+'_'+dimension+'_points'][name]['shape']
                if len(bins)!=1 or bins[0]<2 or points!=[bins[0]-1]:raise ValueError('native bin/point geometry incomplete')
            if maps[prefix+'_1d'][name]['shape']!=maps[prefix+'_1d_points'][name]['shape']:raise ValueError('native 1D grid incomplete')
        for pair,array in maps[prefix+'_2d'].items():
            if array['shape']!=[maps[prefix+'_2d_points'][name]['shape'][0] for name in pair]:raise ValueError('native full pair grid incomplete')
    for kind in ('lin','log'):
        if document.get('algorithm') in ('smc','craft'):continue
        bins=document['weights']['w_bins_'+kind]['shape'];hist=document['weights']['w_hist_'+kind]['shape']
        if len(bins)!=1 or bins[0]<2 or hist!=[bins[0]-1]:raise ValueError('native weight histogram incomplete')
    if document['marginal_effective_size']['shape']!=[]:raise ValueError('native effective size scalar incomplete')

def complete_fit_result(result,parameters,algorithm,profile):
    return fit_result(result,parameters,algorithm=algorithm,profile=profile)

COMPLETE_TENSORS=INITIALIZED_TENSORS+('backgrounds','dist_mask','higgs_sm','decay',
    'decay_measurement_indices','err_pois','sig_mask','meas_back_diff')
HIGGS_TENSORS=('prediction.coeffs','prediction.gamma_prefactors','ewpo.data','ewpo.err_gauss',
    'ewpo.err_theo','ewpo.corr','ewpo.ewpo_coeffs')

def complete_initialized_state(native,contract,origin):
    physical=contract['profile'] in ('top','higgs');tensors={};encoding={}
    if physical:
        for key in COMPLETE_TENSORS+HIGGS_TENSORS:
            owner,name=key.split('.') if '.' in key else ('native',key)
            value=getattr({'native':native,'prediction':native.pred,'ewpo':native.ewpo}[owner],name).detach().cpu().numpy()
            if value.dtype.kind=='b':value=value.astype('uint8');encoding[key]='native_boolean_as_exact_uint8'
            else:encoding[key]='native_numeric_dtype'
            tensors[key]=array(value)
        scalars={name:(getattr(native,name) if name=='n_blocks_substituted' else scalar(getattr(native,name))) for name in INITIALIZED_SCALARS}
    else:scalars={}
    value={'schema_version':2,'kind':'sfitter_complete_initialized_state','profile':contract['profile'],
        'selection':contract['selection'],'native_parameters':list(native.parameter_names),
        'native_origin':origin,'native_tensors':tensors,'tensor_encoding':encoding,'native_scalars':scalars,
        'physical_profile':physical,'physics_validated':False,'independent_consistency':'unknown'}
    validate_complete_initialized_state(value,contract,origin);return value

def validate_complete_initialized_state(value,contract,origin):
    fields={'schema_version','kind','profile','selection','native_parameters','native_origin','native_tensors','tensor_encoding','native_scalars','physical_profile','physics_validated','independent_consistency'}
    physical=contract['profile'] in ('top','higgs')
    if (type(value) is not dict or set(value)!=fields or type(value['schema_version']) is not int or value['schema_version']!=2 or value['kind']!='sfitter_complete_initialized_state' or value['profile']!=contract['profile'] or value['selection']!=contract['selection'] or value['native_parameters']!=contract['selection']['full'] or value['native_origin']!=origin or value['physical_profile'] is not physical or value['physics_validated'] is not False or value['independent_consistency']!='unknown'):raise ValueError('exact full native initialization contract required')
    expected=set(COMPLETE_TENSORS+HIGGS_TENSORS) if physical else set()
    if set(value['native_tensors'])!=expected or set(value['tensor_encoding'])!=expected or set(value['native_scalars'])!=(set(INITIALIZED_SCALARS) if physical else set()):raise ValueError('full native initialized tensor population required')
    total=0
    for key,record in value['native_tensors'].items():
        raw=validate_array(record);total+=len(raw)
        encoding='native_boolean_as_exact_uint8' if key in ('dist_mask','sig_mask') else 'native_numeric_dtype'
        if value['tensor_encoding'][key]!=encoding or encoding.startswith('native_boolean') and (record['dtype']!='|u1' or any(b not in (0,1) for b in raw)):raise ValueError('lossless native tensor encoding required')
    if physical:
        n=contract['census']['bins'];full=len(contract['selection']['full']);t=value['native_tensors']
        expected_shapes={'smeft_coeffs':[n,full,full+1],'smeft_offset':[n],'measurements':[n],'backgrounds':[n],'err_theo':[n],'err_gauss':[n],'corr':[n,n],'corr_inv':[n,n],'bin_widths':[n],'norm_indices':[n],'norm_start':[contract['census']['observations']],'err_pois':[2,n],'dist_mask':[n],'sig_mask':[n],'meas_back_diff':[n],'prediction.coeffs':[9,21,21],'prediction.gamma_prefactors':[8],'ewpo.ewpo_coeffs':[15,21],'ewpo.data':[15],'ewpo.err_gauss':[15],'ewpo.err_theo':[15],'ewpo.corr':[15,15]}
        if any(t[k]['shape']!=v for k,v in expected_shapes.items()):raise ValueError('complete native physical tensor geometry differs')
        mixture=sum(len(row['decay']) for row in contract['census']['population'] if row['decay']!=[1.])
        mixture=max(1,mixture)
        if t['higgs_sm']['shape']!=[mixture,5] or t['decay']['shape']!=[mixture] or t['decay_measurement_indices']['shape']!=[mixture]:raise ValueError('complete native decay-to-measurement geometry differs')
        for key in ('corr_shrinkage','syst_rho'):
            total+=len(validate_array(value['native_scalars'][key]))
            if value['native_scalars'][key]['shape']!=[] or value['native_scalars'][key]['dtype']!='<f8':raise ValueError('native float64 correlation scalar required')
        count=value['native_scalars']['n_blocks_substituted']
        if type(count) is not int or not 0<=count<=contract['census']['observations']:raise ValueError('native correlation block population differs')
    if total>MAX_BYTES:raise ValueError('complete initialization export exceeds byte bound')
    return value
