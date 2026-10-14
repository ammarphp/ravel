"""Bounded cross-fitted method studies on pinned columnar inputs.

The executor owns the arrays. Each fit receives only train/validation features,
method labels and weights. Truth is decoded by evaluator functions after freezing.
Null datasets are supplied independent toys: no background law is invented here.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
import re
import time
import zipfile

import numpy as np
from . import ml_training as ml, ml_backends, ml_exposure, ml_custody
from ravel.workflow.state_io import atomic_json


def fold_map(groups, k, salt):
    return np.array([int(hashlib.sha256(f'{salt}:{g}'.encode()).hexdigest(), 16) % k
                     for g in groups], dtype=int)


def model_scope(row):
    if 'group_scope' not in row: return row
    return {**row, **json.loads(ml._bytes(row['group_scope'],Path.cwd()))}


def audit_models(rows):
    errors = []
    for i, row in enumerate(rows):
        row=model_scope(row)
        test = set(row['test_groups'])
        train, val, prep = (set(row[k]) for k in ('train_groups', 'validation_groups', 'preprocessing_groups'))
        if test & (train | val | prep): errors.append(f'model {i}: test group leakage')
        if train & val: errors.append(f'model {i}: validation group leakage')
        if not prep <= train: errors.append(f'model {i}: preprocessing outside train folds')
    return {'passed': not errors, 'errors': errors, 'models': len(rows)}


def smoke_signature(t):
    return {'arms':[{k:a[k] for k in ('kind','backend','architecture','config') if k in a}
                    for a in t['models']+t['baselines'] if 'architecture' in a],
            'features':len(t['dataset']['features']),'epochs':t['budget']['epochs'],
            'patience':t['budget']['patience'],'backend_code':ml.pin(ml_backends.__file__)}


def measure_smoke(t,path):
    """Measure a bounded computational pilot on explicit synthetic feature arrays.

    This creates no event population or physics result. The receipt is registered
    in the evaluator authority namespace so a handwritten timing is not evidence.
    """
    signature=smoke_signature(t)
    rng=np.random.default_rng(402)
    x=rng.normal(size=(64,signature['features'])); y=np.tile([0.,1.],32)
    batch={'x':x,'y':y,'weight':np.ones(64)}
    began=time.monotonic(); cpu=time.process_time(); rows=[]
    def deadline():
        if time.monotonic()-began>30: raise ValueError('smoke pilot exceeded 30 seconds')
    for arm in t['models']+t['baselines']:
        if 'architecture' not in arm: continue
        _,history,_=fit_model(ml.resolve_arm(arm,Path(path).parent),batch,batch,71,t['budget'],deadline)
        rows.append({'arm':arm['id'],'epochs':len(history)})
    receipt={'schema_version':1,'kind':'ml-smoke-receipt','signature':signature,'rung':'smoke',
             'trainings':len(rows),'wall_seconds':time.monotonic()-began,'cpu_seconds':time.process_time()-cpu,'rows':rows,
             'scope':'64 synthetic rows; compute calibration only; production scaling still needs matched data sizes'}
    atomic_json(Path(path),receipt)
    authority=ml_exposure.root()/'smoke'; authority.mkdir(parents=True,exist_ok=True)
    atomic_json(authority/(ml.digest(receipt)+'.json'),receipt)
    return {k:receipt[k] for k in ('rung','trainings','wall_seconds','cpu_seconds')} | {'source':ml.pin(path)}


def validate_smoke(t,base):
    timing=t['budget']['unit_timing']; receipt=json.loads(ml._bytes(timing['source'],base))
    authority=ml_exposure.root()/'smoke'/(ml.digest(receipt)+'.json')
    if receipt.get('kind')!='ml-smoke-receipt' or receipt.get('signature')!=smoke_signature(t) or not authority.is_file():
        raise ValueError('cost requires an executor smoke receipt bound to this backend/configuration/epochs')
    if json.loads(authority.read_text())!=receipt or any(receipt.get(k)!=timing[k] for k in ('rung','trainings','wall_seconds','cpu_seconds')):
        raise ValueError('executor smoke receipt differs from timing/authority')
    return receipt


def authoritative_ceiling(t,rundir):
    try:
        from ravel.workflow.run_ceilings import resolve
    except ImportError:
        ceiling=2700.  # producer default, not a spec override.
    else:
        ceiling=resolve(Path(rundir))['worker_wall_seconds']['producer']
    ml._number(ceiling,.001,864000)
    if t['budget']['ceiling_seconds']>ceiling:
        _providers('spend_above_ceiling')
        raise ValueError('spend_above_ceiling requires a pinned approved ceiling change; the specification cannot raise its own ceiling')
    return ceiling


def size_study(spec):
    """Return counts, precision, training/CPU/wall estimates and refusal reasons.

    Pure plan-time function: counts and a measured smoke timing must be supplied.
    Counts are independent effective groups, never multiplied by replicate seeds.
    Execution rechecks the actual group counts against the same precision floor.
    """
    t = spec.get('task', spec)
    errors, cells = [], []
    try:
        k = t['splits']['k']; ml._integer(k, 3, 10)
        seeds = len(t['seeds']); salts = len(t['splits'].get('fold_salts', [t['splits']['salt']]))
        ninit = t['inner_selection']['initializations']; ml._integer(ninit, 1, 32)
        windows = 1 + len(t['supervision'].get('additional_windows', []))
        training_arms = sum(a.get('kind') not in ('inclusive', 'inclusive_bump_hunt', 'cut_based')
                            for a in t['models'] + t['baselines'])
        inj = t.get('injection') or {}; null = t.get('null_calibration') or {}
        injections = len(inj.get('strengths', [])) * inj.get('samplings', 0)
        toys = null.get('toys', 0)
        trainings_per_arm = windows*k*(k-1)*ninit*(1+injections+toys)*seeds*salts
        trainings = trainings_per_arm * training_arms
        b = t['budget']; timing = b['unit_timing']; unit = b['unit_seconds']
        ml._number(unit, 1.e-9, 86400)
        ml._pin(timing['source'])
        if (timing['rung'] != 'smoke' or timing['trainings'] <= 0
                or not math.isclose(unit, timing['wall_seconds']/timing['trainings'], rel_tol=1.e-8)):
            errors.append('cost requires measured smoke unit time')
        cpu_unit = timing['cpu_seconds']/timing['trainings']; ml._number(cpu_unit, 0, 86400)
        wall = trainings*unit
        if wall > b['ceiling_seconds']: errors.append('spend_above_ceiling decision required')
        st = t['statistics']
        ml._number(st['max_relative_error'], 1.e-4, 1.)
        ml._integer(st['min_selected_per_fold'], 1, 100000)
        for region, count in enumerate(st['region_counts']):
            ml._number(count, 0, 100000)
            for eff in t['scoring']['working_points']:
                ml._number(eff, .0001, 1.)
                n = count/k
                required = max(st['min_selected_per_fold']/eff,
                               (1-eff)/(eff*st['max_relative_error']**2))
                rel = math.sqrt((1-eff)/(n*eff)) if n else None
                cells.append({'region': region, 'per_test_fold': n, 'per_validation_fold': n,
                              'per_training_rotation': n*(k-2), 'data_efficiency': eff,
                              'expected_selected': n*eff, 'relative_binomial_error': rel,
                              'required_independent_groups_per_region': math.ceil(k*required)})
                if n < required: errors.append(f'statistics below precision/count floor in region {region}')
        if len(st['region_counts']) != 3: errors.append('statistics needs signal and two sideband counts')
        if not st.get('claim'): errors.append('statistics needs a narrowed or full claim')
        return {'admissible': not errors, 'refusal_reasons': sorted(set(errors)), 'cells': cells,
                'trainings': trainings, 'trainings_per_arm': trainings_per_arm, 'training_arms': training_arms,
                'injection_points': injections, 'toys': toys, 'windows': windows, 'fold_salts': salts,
                'projected_wall_seconds': wall, 'projected_cpu_seconds': trainings*cpu_unit,
                'independence': 'Independent group counts; repetitions do not add events.',
                'cost_scope': 'Measured training projection; hard stage ceiling also covers scoring, checks and I/O.'}
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        return {'admissible': False, 'refusal_reasons': [f'unsized or uncosted study: {exc}'], 'cells': cells}


def _ranges(supervision):
    result = [supervision['regions']['signal'], *supervision['regions']['sidebands']]
    if len(result) != 3: raise ValueError('one signal region and two sidebands required')
    for lo, hi in result:
        ml._number(lo, -1.e100, 1.e100); ml._number(hi, -1.e100, 1.e100)
        if lo >= hi: raise ValueError('region edges must increase')
    for i, a in enumerate(result):
        if any(max(a[0], b[0]) < min(a[1], b[1]) for b in result[:i]):
            raise ValueError('overlapping regions')
    return result


def validate(t):
    if t.get('claim_kind')=='method_performance':
        raise ValueError('method_performance requires the research-protocol claim contract with dev/select/confirm and paired intervals')
    required = {'objective', 'dataset', 'splits', 'supervision', 'preprocessing', 'inner_selection',
                'scoring', 'baselines', 'models', 'seeds', 'budget', 'statistics', 'checks', 'fit',
                'injection', 'null_calibration', 'calibration', 'placement'}
    ml._keys(t, required | ({'claim_kind'} if 'claim_kind' in t else set()))
    if t.get('claim_kind','diagnostic')!='diagnostic': raise ValueError('claim kind not admitted before the research-protocol claim contract exists')
    if t['objective'] not in ('classification', 'anomaly_search', 'method_study'):
        raise ValueError('unsupported cross-fit objective')
    d = t['dataset']; ml._keys(d, ('pins', 'features', 'weights', 'id_column', 'truth_column', 'synthetic', 'manifest_sha256') + (('truth_pin',) if 'truth_pin' in d else ()))
    if len(d['pins']) != 1: raise ValueError('one bounded population pin required')
    for p in d['pins']: ml._pin(p)
    if d['manifest_sha256'] != ml.digest({k:v for k,v in d.items() if k!='manifest_sha256'}):
        raise ValueError('dataset manifest changed')
    if not 1 <= len(d['features']) <= 64 or len(set(d['features'])) != len(d['features']):
        raise ValueError('unique bounded feature list required')
    if any(not isinstance(v,str) or not v for v in d['features']): raise ValueError('feature names required')
    if (d['weights'], d['id_column']) != ('weight', 'event_id') or d['truth_column'] not in (None, 'truth'):
        raise ValueError('columnar schema requires weight, event_id, evaluator-only truth')
    if d['truth_column'] is not None and 'truth_pin' not in d: raise ValueError('separate evaluator-only truth_pin required')
    if 'truth_pin' in d: ml._pin(d['truth_pin'])
    if type(d['synthetic']) is not bool: raise ValueError('synthetic provenance declaration required')
    s = t['splits']; ml._keys(s, ('method','k','group_column','salt','fold_salts','test_withheld','split_sha256'))
    ml._integer(s['k'], 3, 10)
    if s['group_column']!='group_id' or s['test_withheld'] is not True: raise ValueError('withheld grouped folds required')
    if s['split_sha256'] != ml.split_digest(s): raise ValueError('split sha256 changed')
    if not isinstance(s['salt'],str) or not s['salt']: raise ValueError('fold salt required')
    if (not 1 <= len(s['fold_salts']) <= 8 or s['salt'] != s['fold_salts'][0]
            or len(set(s['fold_salts'])) != len(s['fold_salts'])
            or any(not isinstance(v,str) or not v for v in s['fold_salts'])):
        raise ValueError('distinct fold salts required; first salt is nominal')
    sup=t['supervision']
    ml._keys(sup, ('kind','region_variable','derived_features','regions','sideband_weighting') +
             (('fractions',) if sup.get('kind')=='mixture' else ()) + (('additional_windows',) if 'additional_windows' in sup else ()))
    if sup['kind'] not in ('truth','weak_region','mixture') or sup['region_variable']!='region':
        raise ValueError('truth, weak_region or mixture supervision with region variable required')
    if sup['kind']=='truth' and t['null_calibration']: raise ValueError('truth-trained study cannot calibrate a search statistic')
    if sup['kind']=='truth' and t['objective']=='anomaly_search': raise ValueError('truth-trained arms cannot be search methods')
    if sup['kind']=='truth' and d['truth_column'] is None:
        raise ValueError('truth supervision needs an explicit truth column')
    _ranges(sup)
    if 'additional_windows' in sup:
        if not 1<=len(sup['additional_windows'])<=8: raise ValueError('bounded additional windows required')
        for window in sup['additional_windows']:
            ml._keys(window, ('signal','sidebands'))
            _ranges({**sup,'regions':window})
    if sup['sideband_weighting'] not in ('equal','population'): raise ValueError('sideband weighting required')
    forbidden = {sup['region_variable'], d['truth_column'], d['id_column'], s['group_column'], 'weight', *sup['derived_features']}
    if forbidden & set(d['features']): raise ValueError('label leakage: forbidden label variable or derived feature')
    if sup['kind']=='mixture':
        if len(sup['fractions'])!=2: raise ValueError('two mixture fractions required')
        for f in sup['fractions']: ml._number(f, 0, 1)
    ml._keys(t['inner_selection'], ('initializations','criterion'))
    ml._integer(t['inner_selection']['initializations'], 1, 32)
    if t['inner_selection']['criterion']!='validation_loss': raise ValueError('validation-only selection required')
    if not 3 <= len(t['seeds']) <= 32 or len(set(t['seeds']))!=len(t['seeds']):
        raise ValueError('three distinct outer replicate seeds required')
    for seed in t['seeds']: ml._integer(seed, 0, 2**32-1)
    b=t['budget']; ml._keys(b, ('epochs','patience','wall_seconds','max_trials','equal_across_arms',
                               'ceiling_seconds','unit_seconds','unit_timing'))
    ml._integer(b['epochs'],1,10000); ml._integer(b['patience'],1,b['epochs'])
    ml._number(b['wall_seconds'],.001,86400); ml._number(b['ceiling_seconds'],.001,864000)
    if type(b['max_trials']) is not int or b['max_trials']!=1 or b['equal_across_arms'] is not True:
        raise ValueError('equal budgets and max_trials=1 required; no hyperparameter search')
    if not 1<=len(t['models'])<=8 or not 1<=len(t['baselines'])<=8: raise ValueError('model and baseline required')
    ids=set()
    for arm in t['baselines']+t['models']:
        if not re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,39}',arm['id']) or arm['id'] in ids:
            raise ValueError('unique safe arm id required')
        ids.add(arm['id'])
        if arm['kind'] in ('inclusive','inclusive_bump_hunt'):
            ml._keys(arm, ('id','kind')); continue
        if arm['kind'] not in ('weak','supervised_oracle','idealized_anomaly'):
            raise ValueError('unsupported study arm kind')
        ml._keys(arm, ('id','kind','architecture','backend','config') + (('code',) if 'code' in arm else ()) + (('training_pool',) if 'training_pool' in arm else ()) + (('family',) if 'family' in arm else ()))
        if 'training_pool' in arm:
            if arm['kind']!='supervised_oracle': raise ValueError('external labelled pool is only for oracle ceiling')
            ml._pin(arm['training_pool'])
        if arm['kind'] in ('supervised_oracle','idealized_anomaly') and not d['synthetic']:
            raise ValueError('truth-information ceilings require synthetic data')
        if arm['backend']!='numpy' or arm['architecture'] not in ('mlp','logistic','quadratic_logistic'):
            raise ValueError('cross-fit reference supports NumPy logistic, quadratic logistic, ReLU MLP')
        if 'code' in arm: ml._pin(arm['code'])
        if ml.is_config_pin(arm):
            ml._pin(arm['config']); continue
        config=arm['config']; ml._keys(config, ('learning_rate','widths') if arm['architecture']=='mlp' else ('learning_rate',))
        ml._number(config['learning_rate'],1.e-8,1)
        if arm['architecture']=='mlp':
            if not 1<=len(config['widths'])<=4: raise ValueError('MLP depth bounded at four')
            for w in config['widths']: ml._integer(w,1,128)
    families={}
    for a in t['models']+t['baselines']:
        if 'architecture' in a:
            family=a.get('family',a['architecture'])
            if not isinstance(family,str) or not family: raise ValueError('arm family required')
            families[family]=families.get(family,0)+1
    if any(n>b['max_trials'] for n in families.values()): raise ValueError('configurations per family exceed max_trials')
    p=t['preprocessing']
    ml._keys(p, ('kind','scope','features','pool_features') if p.get('kind')=='region_quantile' else ('kind','scope'))
    if p['kind'] not in ('standardize','region_quantile') or p['scope']!='train_folds':
        raise ValueError('train_folds preprocessing required')
    if p['kind']=='region_quantile':
        if not p['features'] or len(set(p['features']))!=len(p['features']): raise ValueError('transform feature set required')
        for f in p['features']: ml._integer(f,0,len(d['features'])-1)
        if type(p['pool_features']) is not bool: raise ValueError('pool_features declaration required')
    score=t['scoring']; ml._keys(score, ('map','reference','aggregate','rerank','working_points'))
    if (score['map'],score['reference'],score['aggregate'],score['rerank']) != (
        'rank_on_reference','signal_region_test_events','mean_over_rotations',True):
        raise ValueError('declared signal-region rank references and rotation averaging required')
    if not 1<=len(score['working_points'])<=16 or len(set(score['working_points']))!=len(score['working_points']):
        raise ValueError('distinct bounded global data efficiencies required')
    for e in score['working_points']: ml._number(e,.0001,1)
    ml._keys(t['checks'], ('permutations','alpha','sideband_bins','max_spurious_z','reference'))
    ml._integer(t['checks']['permutations'],19,9999); ml._number(t['checks']['alpha'],.001,.2)
    ml._number(t['checks']['max_spurious_z'],0.1,4.)
    ml._keys(t['fit'], ('family','bins'))
    if t['fit']['family']!='log_linear': raise ValueError('only declared log_linear count fits supported')
    for edges in (t['fit']['bins'], t['checks']['sideband_bins']):
        if not 4<=len(edges)<=101 or any(not math.isfinite(v) for v in edges) or any(a>=b for a,b in zip(edges,edges[1:])):
            raise ValueError('bounded increasing inference/check bin edges required')
        if any(v not in edges for window in [sup['regions']]+sup.get('additional_windows',[])
               for pair in _ranges({**sup,'regions':window}) for v in pair):
            raise ValueError('bin edges must include all window region edges')
        for window in [sup['regions']]+sup.get('additional_windows',[]):
            ranges=_ranges({**sup,'regions':window})
            if edges[0]!=min(a for a,b in ranges) or edges[-1]!=max(b for a,b in ranges):
                raise ValueError('fit/check bins must span exactly the declared regions')
            if any(not any(lo<=a and b<=hi for lo,hi in ranges) for a,b in zip(edges,edges[1:])):
                raise ValueError('unmodelled gap in fit/check range')
    ml._keys(t['calibration'], ('derive_detector_correction',))
    if type(t['calibration']['derive_detector_correction']) is not bool: raise ValueError('calibration decision required')
    if t['checks']['reference'] is not None: ml._pin(t['checks']['reference'])
    injection=t['injection']
    if injection is not None:
        ml._keys(injection, ('signal_pool','partition','strengths','samplings','draw','median_rule') + (('closure',) if 'closure' in injection else ()) + (('localization_min',) if 'localization_min' in injection else ()))
        ml._number(injection.get('localization_min',.95),.5,1.)
        ml._pin(injection['signal_pool'])
        ml._keys(injection['partition'], ('method','salt','injection_fraction'))
        if injection['partition']['method']!='group_hash': raise ValueError('disjoint group_hash signal partitions required')
        ml._number(injection['partition']['injection_fraction'],.1,.9)
        if not isinstance(injection['partition']['salt'],str): raise ValueError('injection partition salt required')
        ml._integer(injection['samplings'],3,1024)
        if not 1<=len(injection['strengths'])<=16 or len(set(injection['strengths']))!=len(injection['strengths']):
            raise ValueError('distinct bounded injection strengths required')
        for strength in injection['strengths']: ml._integer(strength,0,100000)
        if injection['draw']!='exact_count_by_weight' or injection['median_rule']!='median_signal_efficiency':
            raise ValueError('declared exact-count draw and median_signal_efficiency required')
    if injection and 'closure' in injection:
        closure=injection['closure']
        ml._keys(closure, ('estimand','alpha','false_fail_probability','min_power_gain','max_null_rejection'))
        if closure['estimand']!='conditional_fixed_background':
            raise ValueError('injection closure currently supports conditional_fixed_background only')
        for key in ('alpha','false_fail_probability'): ml._number(closure[key],.0001,.2)
        for key in ('min_power_gain','max_null_rejection'): ml._number(closure[key],0,1)
        tail=closure['false_fail_probability']/(2*len(injection['strengths']))
        if closure['max_null_rejection']<=0: raise ValueError('closure precision requires infinite samplings')
        required=math.ceil(math.log(tail)/math.log1p(-closure['max_null_rejection'])) if closure['max_null_rejection']<1 else 3
        # Even perfect separation needs both interval tails to leave the requested gain.
        if closure['min_power_gain']>=1: raise ValueError('closure precision requires infinite samplings')
        required=max(required,math.ceil(math.log(tail)/math.log((1+closure['min_power_gain'])/2)))
        if required>1024 or injection['samplings']<required: raise ValueError(f'closure precision requires at least {required} samplings')
        if not t['null_calibration'] or t['null_calibration']['toys']<math.ceil(1/closure['alpha']): raise ValueError('closure needs toys >= 1/alpha')
        if 0 not in injection['strengths']: raise ValueError('closure needs a zero-strength control')
    null=t['null_calibration']
    if null is not None:
        ml._keys(null, ('toys','scope','datasets','claim_below','unblind'))
        ml._integer(null['toys'],1,10000)
        if null['scope']!='whole_procedure' or len(null['datasets'])!=null['toys']:
            raise ValueError('one independent dataset for every whole-procedure null toy required')
        if len({p['sha256'] for p in null['datasets']})!=null['toys']: raise ValueError('duplicate null toys')
        for pin in null['datasets']: ml._pin(pin)
        if null['claim_below'] is not None:
            ml._number(null['claim_below'],1/(null['toys']+1),1.)
        if type(null['unblind']) is not bool: raise ValueError('unblind decision required')
    ml._keys(t['placement'], ('backend_plan','device')); ml._pin(t['placement']['backend_plan'])
    if t['placement']['device']!='cpu': raise ValueError('CPU reference only')
    sizing=size_study(t)
    if not sizing['admissible']: raise ValueError('; '.join(sizing['refusal_reasons']))
    return t


def input_pins(t):
    result=t['dataset']['pins'][:]+[t['budget']['unit_timing']['source']]
    if t['dataset'].get('truth_pin'): result.append(t['dataset']['truth_pin'])
    if t['injection']: result.append(t['injection']['signal_pool'])
    if t['null_calibration']: result.extend(t['null_calibration']['datasets'])
    if t['checks']['reference']: result.append(t['checks']['reference'])
    for arm in t['baselines']+t['models']:
        if ml.is_config_pin(arm): result.append(arm['config'])
        if 'code' in arm: result.append(arm['code'])
        if 'training_pool' in arm: result.append(arm['training_pool'])
    return result


def inputs(t, base):
    validate(t)
    validate(ml.resolved_task(t,base))
    validate_smoke(t,base)
    timing=t['budget']['unit_timing']
    measured=json.loads(ml._bytes(timing['source'],base))
    if any(measured.get(k)!=timing[k] for k in ('rung','trainings','wall_seconds','cpu_seconds')):
        raise ValueError('measured smoke timing differs from pinned source')
    plan=ml.eb.check_plan(json.loads(ml._bytes(t['placement']['backend_plan'],base)))
    if plan['spec']['backend']!='native' or plan['spec']['stage']!='ml-training':
        raise ValueError('native ml-training backend required')
    declared={(str(ml._path(p,base).resolve()),p['sha256']) for p in plan['inputs']}
    if not {(str(ml._path(p,base).resolve()),p['sha256']) for p in input_pins(t)} <= declared:
        raise ValueError('backend must bind all study inputs')
    if plan['spec']['resources']['wall_seconds'] < execution_seconds(t):
        raise ValueError('backend wall ceiling below study budget')
    paths=[]
    for p in input_pins(t)+[t['placement']['backend_plan']]:
        ml._bytes(p,base); paths.append(ml._path(p,base))
    preflight_populations(t,base)
    return paths+[Path(__file__),Path(ml.__file__),Path(ml_backends.__file__),Path(ml_exposure.__file__),Path(ml_custody.__file__)]


def execution_seconds(t):
    return t['budget']['ceiling_seconds']+30


def load_events(p, base, features, *, allow_sampling_weights=False):
    raw=ml._bytes(p,base)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if sum(i.file_size for i in z.infolist())>ml.MAX_BYTES: raise ValueError('expanded population exceeds 64 MiB')
    with np.load(io.BytesIO(raw),allow_pickle=False) as z:
        if not {'x','region','weight','event_id','group_id'} <= set(z.files) or set(z.files)-{'x','region','weight','event_id','group_id'}:
            raise ValueError('columnar population schema mismatch')
        # Truth must be in a separate evaluator-only file.
        d={k:z[k] for k in ('x','region','weight','event_id','group_id')}
    n=len(d['x'])
    if not 3<=n<=100000 or d['x'].shape!=(n,features): raise ValueError('bounded feature matrix required')
    if any(d[k].shape!=(n,) for k in ('region','weight','event_id','group_id')): raise ValueError('column lengths differ')
    if any(d[k].dtype.kind not in 'fiu' or not np.all(np.isfinite(d[k])) for k in ('x','region','weight')):
        raise ValueError('finite numeric arrays required')
    if np.any(d['weight']<=0): raise ValueError('positive weights required; signed/zero weights refused')
    # Unequal weights need weighted permutation and inference calibration, not an ESS substitution.
    if not allow_sampling_weights and not np.all(d['weight']==d['weight'][0]): raise ValueError('weighted training unqualified; use the weighted permutation/inference qualification route; reference requires equal positive weights')
    for key in ('group_id','event_id'):
        if d[key].dtype.kind not in 'iuUS': raise ValueError('string or integer identities required')
        d[key]=d[key].astype(str)
    if len(set(d['event_id']))!=n: raise ValueError('duplicate event identity')
    return d


def region_ids(values, sup):
    result=np.full(len(values),-1,dtype=int)
    for j,(lo,hi) in enumerate(_ranges(sup)):
        result[(values>=lo)&(values<hi)]=j
    if np.any(result<0): raise ValueError('events outside declared regions')
    return result


def fit_transform(x, regions, spec):
    if spec['kind']=='standardize':
        scale=np.std(x,axis=0); scale=np.where(scale>1.e-12,scale,1.)
        return {'kind':'standardize','mean':np.mean(x,axis=0).tolist(),'scale':scale.tolist()}
    references={}
    for region in np.unique(regions):
        part=x[regions==region]
        for feature in spec['features']:
            v=part[:,spec['features']].reshape(-1) if spec['pool_features'] else part[:,feature]
            references[f'{region}:{feature}']=np.sort(v).tolist()
    return {'kind':'region_quantile','features':spec['features'],'references':references}


def apply_transform(transform, x, regions):
    if transform['kind']=='standardize': return (x-transform['mean'])/transform['scale']
    z=x.copy()
    for region in np.unique(regions):
        for f in transform['features']:
            ref=np.asarray(transform['references'][f'{region}:{f}'])
            z[regions==region,f]=(np.searchsorted(ref,x[regions==region,f],side='left')+.5)/(len(ref)+1)
    return z


def fit_model(arm, train, val, seed, budget, deadline):
    return ml_backends.fit_selected(arm, train, val, seed, budget, deadline)


def _gate(base, gate, spec_digest, pins):
    try:
        from ravel.workflow.decision_gate import check, providers
    except ImportError as exc:
        raise ValueError(f'{gate}: decision_gate provider unavailable; coordinator integration required') from exc
    if not any(p.get('active') for p in providers(gate)):
        raise ValueError(f'{gate}: no active decision provider')
    action={'kind':'ml-training','digest':spec_digest,'summary':f'ML {gate}', 'pins':pins,
            'node_id':None,'rung':None,'scope':'whole_procedure'}
    errors=check(Path(base),gate,action)
    if errors: raise ValueError(f'{gate}: ' + '; '.join(str(e) for e in errors))
    return {'gate':gate,'digest':spec_digest,'verdict':'passed'}


def calibrated_p(observed, toys, claim_below=None):
    resolution=1/(len(toys)+1)
    if claim_below is not None and claim_below<resolution: raise ValueError('claim below null ensemble resolution')
    return (1+sum(v is None or not math.isfinite(v) or v>=observed for v in toys))/(len(toys)+1)


def _truth(p, base, ids):
    with np.load(io.BytesIO(ml._bytes(p,base)),allow_pickle=False) as z:
        if set(z.files)!={'truth','event_id'}: raise ValueError('separate truth file schema required')
        truth=z['truth']; source_ids=z['event_id'].astype(str)
        if len(set(source_ids))!=len(source_ids): raise ValueError('duplicate truth identities')
    if truth.shape!=source_ids.shape or not set(truth.tolist()) <= {0,1}: raise ValueError('binary evaluator truth required')
    lookup=dict(zip(source_ids,truth))
    if not set(ids)<=lookup.keys(): raise ValueError('truth identity mismatch')
    return np.array([lookup[i] for i in ids])


def _subset(data, mask):
    return {key:value[mask] for key,value in data.items()}


def _rank(scores, reference):
    if not len(reference): raise ValueError('empty signal-region rank reference')
    ref=np.sort(reference)
    # Midranks avoid ordering ties by event identity. Thresholds include whole ties.
    return (np.searchsorted(ref,scores,'left')+np.searchsorted(ref,scores,'right'))/(2*len(ref))


def _weights(data, regions, sup):
    result=data['weight'].copy().astype(float)
    if sup['sideband_weighting']=='equal':
        for j in (1,2):
            mask=regions==j
            if not np.any(mask): raise ValueError('empty training/validation sideband')
            result[mask] /= result[mask].sum()
        # Give combined sidebands and signal region their original total balance.
        result[regions>0] *= data['weight'][regions>0].sum()/2
    return result


def _actual_sizing(t, data, folds, regions):
    st=t['statistics']; cells=[]
    for fold in range(t['splits']['k']):
        for region in range(3):
            mask=(folds==fold)&(regions==region)
            groups=np.unique(data['group_id'][mask]); n=effective_n(data,mask)
            for eff in t['scoring']['working_points']:
                rel=math.sqrt((1-eff)/(n*eff)) if n else float('inf')
                if n*eff<st['min_selected_per_fold'] or rel>st['max_relative_error']:
                    raise ValueError(f'actual statistics below floor: fold {fold} region {region}')
                cells.append({'fold':fold,'region':region,'groups':n,'efficiency':eff,'relative_error':rel})
    return cells


def _single_crossfit(t, data, output, context, spend, deadline, truth=None, base=None):
    """Train every test-fold ensemble, freeze, then score that fold exactly once.

    The same test array supplies all frozen arms/replicates/rotations in this one
    evaluation exposure. Each event has one final ensemble score per arm and
    replicate; separate salts test fold-assignment sensitivity.
    """
    output.mkdir(parents=True,exist_ok=False)
    if len(data['x'])*len(t['seeds'])*len(t['splits']['fold_salts'])*(len(t['models'])+len(t['baselines']))>4_000_000:
        raise ValueError('ensemble score matrix exceeds reference memory bound')
    regions=region_ids(data['region'],t['supervision'])
    models=[]; scores=[]; exposures=[]; rank_refs=[]; maps=[]; ensembles=[]; sizing=[]
    oracle_pools={}
    for arm in t['baselines']+t['models']:
        if 'training_pool' in arm:
            pool=load_events(arm['training_pool'],base,len(t['dataset']['features']))
            if set(pool['group_id'])&set(data['group_id']): raise ValueError('oracle training groups overlap study')
            labels=_truth(t['dataset']['truth_pin'],base,pool['event_id'])
            oracle_pools[arm['id']]=(pool,labels)
    for salt_id, declared_salt in enumerate(t['splits']['fold_salts']):
        salt=f'{declared_salt}:{context}' if context!='nominal' else declared_salt
        folds=fold_map(data['group_id'],t['splits']['k'],salt)
        sizing.extend(_actual_sizing(t,data,folds,regions))
        maps.append({'context':context,'salt':salt,'event_ids':data['event_id'].tolist(),
                     'group_ids':data['group_id'].tolist(),'folds':folds.tolist(),
                     'sha256':ml.digest(list(zip(data['event_id'].tolist(),folds.tolist())))})
        arm_scores={(a['id'],seed):np.empty(len(regions)) for a in t['baselines']+t['models'] for seed in t['seeds']}
        raw_scores={key:np.empty(len(regions)) for key in arm_scores}
        for test_fold in range(t['splits']['k']):
            test=folds==test_fold
            pending=[]
            for arm in t['baselines']+t['models']:
                for seed in t['seeds']:
                    if arm['kind'] in ('inclusive','inclusive_bump_hunt'):
                        pending.append((arm,seed,[])); continue
                    selected=[]
                    for rotation in range(t['splits']['k']):
                        if rotation==test_fold: continue
                        train=(folds!=test_fold)&(folds!=rotation); val=folds==rotation
                        train_data=_subset(data,train); val_data=_subset(data,val)
                        oracle=oracle_pools.get(arm['id'])
                        pool_scope=None
                        if oracle is not None:
                            source,labels=oracle; source_folds=fold_map(source['group_id'],t['splits']['k'],salt)
                            tr_mask=(source_folds!=test_fold)&(source_folds!=rotation); va_mask=source_folds==rotation
                            train_data=_subset(source,tr_mask); val_data=_subset(source,va_mask)
                            train_y=labels[tr_mask]; val_y=labels[va_mask]
                            pool_scope={'pin':ml.pin(ml._path(arm['training_pool'],base)),'group_ids':source['group_id'].tolist(),
                                        'folds':source_folds.tolist(),'scope':'Independent labelled ceiling training pool'}
                        elif arm['kind']=='supervised_oracle' or t['supervision']['kind']=='truth':
                            if truth is None: raise ValueError('oracle requires isolated evaluator truth access')
                            train_y=truth[train]; val_y=truth[val]
                        elif arm['kind']=='idealized_anomaly':
                            if truth is None: raise ValueError('idealized reference requires synthetic truth')
                            keep_train=(regions[train]==0)|(truth[train]==0)
                            keep_val=(regions[val]==0)|(truth[val]==0)
                            train_data=_subset(train_data,keep_train); val_data=_subset(val_data,keep_val)
                            train_y=(region_ids(train_data['region'],t['supervision'])==0).astype(float)
                            val_y=(region_ids(val_data['region'],t['supervision'])==0).astype(float)
                        else:
                            train_y=(regions[train]==0).astype(float); val_y=(regions[val]==0).astype(float)
                        train_regions=region_ids(train_data['region'],t['supervision'])
                        val_regions=region_ids(val_data['region'],t['supervision'])
                        transform=fit_transform(train_data['x'],train_regions,t['preprocessing'])
                        train_x=apply_transform(transform,train_data['x'],train_regions)
                        val_x=apply_transform(transform,val_data['x'],val_regions)
                        tr={'x':train_x,'y':train_y,'weight':_weights(train_data,region_ids(train_data['region'],t['supervision']),t['supervision'])}
                        va={'x':val_x,'y':val_y,'weight':_weights(val_data,region_ids(val_data['region'],t['supervision']),t['supervision'])}
                        if any(len(np.unique(batch['y']))<2 for batch in (tr,va)):
                            raise ValueError('training and validation need both method-label classes')
                        candidates=[]
                        for init in range(t['inner_selection']['initializations']):
                            began=time.monotonic(); cpu=time.process_time()
                            def bounded():
                                deadline()
                                if time.monotonic()-began>t['budget']['wall_seconds']: raise ValueError('per-training wall exhausted')
                            # Seeds vary init only; changing the salt varies folds separately.
                            model_seed=int(ml.digest([seed,test_fold,rotation,init])[:8],16)
                            checkpoint,history,loss=fit_model(ml.resolve_arm(arm,base or output),tr,va,model_seed,t['budget'],bounded)
                            path=output/f'{salt_id}-{test_fold}-{arm["id"]}-{seed}-{rotation}-{init}.npz'
                            checkpoint_pin=ml_custody.put(checkpoint,arrays=True)
                            transform_pin=ml_custody.put(transform)
                            row={'context':context,'arm':arm['id'],'arm_kind':arm['kind'],'seed':seed,'salt':salt,'fold':test_fold,
                                 'rotation':rotation,'initialization':init,'history':history,'validation_loss':loss,
                                 'checkpoint':checkpoint_pin,'transform':transform_pin,'selected':False,
                                 'train_groups':sorted(set(train_data['group_id'])),
                                 'validation_groups':sorted(set(val_data['group_id'])),
                                 'preprocessing_groups':sorted(set(train_data['group_id'])),
                                 'training_pool_scope':pool_scope,
                                 'test_groups':sorted(set(data['group_id'][test])),
                                 'transform_scope':'train_folds','wall_seconds':time.monotonic()-began,
                                 'cpu_seconds':time.process_time()-cpu,'epochs':len(history)}
                            scope={key:row.pop(key) for key in ('train_groups','validation_groups','preprocessing_groups','test_groups')}
                            scope_path=output/(ml.digest(scope)+'.scope.json')
                            if not scope_path.exists(): ml._write_new(scope_path,scope)
                            row['group_scope']=ml.pin(scope_path)
                            history_path=path.with_suffix('.history.json')
                            ml._write_new(history_path,row)
                            row['history_pin']=ml.pin(history_path)
                            models.append(row); candidates.append(row)
                        chosen=min(candidates,key=lambda c:(c['validation_loss'],c['initialization']))
                        chosen['selected']=True; selected.append(chosen)
                    pending.append((arm,seed,selected))
            audit=audit_models(models)
            if not audit['passed']: raise ValueError('crossfit audit: '+ '; '.join(audit['errors']))
            freeze=output/f'freeze-{salt_id}-{test_fold}.json'
            ml._write_new(freeze,{'spec_sha256':getattr(spend,'spec_digest',ml.digest(t)),'models':[m['checkpoint'] for _,_,rows in pending for m in rows],
                                  'histories':[m['history_pin'] for _,_,rows in pending for m in rows]})
            exposure={'context':context,'salt':salt,'fold':test_fold,'test_reads':1,'freeze':ml.pin(freeze)}
            spend(exposure); exposures.append(exposure)
            for arm,seed,selected in pending:
                if not selected:
                    score=np.ones(int(test.sum())); raw=score.copy(); ensemble=[]
                else:
                    mapped=[]; raw_predictions=[]; ensemble=[]
                    for row in selected:
                        with np.load(io.BytesIO(ml._bytes(row['checkpoint'],output)),allow_pickle=False) as z:
                            model={key:z[key] for key in z.files}
                        transform=json.loads(ml._bytes(row['transform'],output))
                        prob=ml_backends.predict_selected(model,apply_transform(transform,data['x'][test],regions[test]))
                        reference=prob[regions[test]==0]
                        mapped.append(_rank(prob,reference)); raw_predictions.append(prob)
                        rank_refs.append({'checkpoint':row['checkpoint'],'event_ids':data['event_id'][test&(regions==0)].tolist(),
                                          'reference':np.sort(reference).tolist(),'fold':test_fold,'salt':salt})
                        ensemble.append((model,transform,np.sort(reference)))
                    average=np.mean(mapped,axis=0); ref=np.sort(average[regions[test]==0])
                    score=_rank(average,ref); raw=np.mean(raw_predictions,axis=0)
                    ensemble.append(ref)
                arm_scores[(arm['id'],seed)][test]=score
                raw_scores[(arm['id'],seed)][test]=raw
                ensembles.append({'arm':arm['id'],'kind':arm['kind'],'seed':seed,'salt':salt,'fold':test_fold,
                                  'ensemble':ensemble,'supervision':t['supervision'],'test_groups':set(data['group_id'][test])})
        for arm in t['baselines']+t['models']:
            for seed in t['seeds']:
                scores.append({'arm':arm['id'],'kind':arm['kind'],'seed':seed,'salt':salt,'declared_salt':declared_salt,
                               'supervision':t['supervision'],
                               'scores':arm_scores[(arm['id'],seed)],'probabilities':raw_scores[(arm['id'],seed)],
                               'folds':folds})
    return {'models':models,'scores':scores,'exposures':exposures,'rank_references':rank_refs,
            'fold_maps':maps,'ensembles':ensembles,'actual_sizing':sizing}


def _crossfit(t, data, output, context, spend, deadline, truth=None, base=None):
    windows=[t['supervision']['regions']]+t['supervision'].get('additional_windows',[])
    if len(data['x'])*len(t['seeds'])*len(t['splits']['fold_salts'])*len(windows)*(len(t['models'])+len(t['baselines']))>4_000_000:
        raise ValueError('combined ensemble score matrix exceeds reference memory bound')
    if len(windows)==1:
        return _single_crossfit(t,data,output,context,spend,deadline,truth,base)
    result={k:[] for k in ('models','scores','exposures','rank_references','fold_maps','ensembles','actual_sizing')}
    for index,window in enumerate(windows):
        local=json.loads(json.dumps(t)); local['supervision'].pop('additional_windows',None)
        local['supervision']['regions']=window
        fitted=_single_crossfit(local,data,output/f'window-{index}',f'{context}-window-{index}',spend,deadline,truth,base)
        for key,rows in fitted.items():
            for row in rows: row['window']=index
            result[key].extend(rows)
    return result


def _evaluate_external(t, fitted, data):
    result={}
    population=set(data['group_id'])
    if any(population & item['test_groups'] for item in fitted['ensembles']):
        raise ValueError('evaluation groups overlap training population')
    for item in fitted['ensembles']:
        regions=region_ids(data['region'],item.get('supervision',t['supervision']))
        key=(item['arm'],item['seed'],item['salt'])
        mask=fold_map(data['group_id'],t['splits']['k'],item['salt'])==item['fold']
        if not item['ensemble']: mapped=np.ones(int(mask.sum()))
        else:
            mapped=[]
            for model,transform,ref in item['ensemble'][:-1]:
                p=ml_backends.predict_selected(model,apply_transform(transform,data['x'][mask],regions[mask]))
                mapped.append(_rank(p,ref))
            mapped=_rank(np.mean(mapped,axis=0),item['ensemble'][-1])
        result.setdefault(key,np.empty(len(regions)))[mask]=mapped
    return result


def _permutation_p(x, labels, permutations, seed):
    """Mean and quadratic-moment two-sample diagnostic, declared bounded permutations."""
    if len(np.unique(labels))!=2: return None
    z=np.column_stack((x,x*x)); scale=np.std(z,axis=0); z=z/np.where(scale>1.e-12,scale,1)
    def statistic(y): return float(np.max(np.abs(np.mean(z[y==0],axis=0)-np.mean(z[y==1],axis=0))))
    observed=statistic(labels); rng=np.random.default_rng(seed)
    return (1+sum(statistic(rng.permutation(labels))>=observed for _ in range(permutations)))/(permutations+1)


def _flatness_p(selected, bins, permutations, seed):
    if len(np.unique(bins))<2: return None
    unique=np.unique(bins)
    def statistic(s): return float(np.max([abs(np.mean(s[bins==b])-np.mean(s)) for b in unique]))
    observed=statistic(selected); rng=np.random.default_rng(seed)
    return (1+sum(statistic(rng.permutation(selected))>=observed for _ in range(permutations)))/(permutations+1)


def bump_statistic(mass, selected, t):
    """Sideband Poisson log-linear fit, SR Pearson residual with fit variance.

    This diagnostic is not itself a calibrated significance. The whole-procedure
    toy distribution calibrates the maximum statistic over the declared trials.
    """
    from scipy.optimize import minimize
    edges=np.array(t['fit']['bins']); centers=(edges[:-1]+edges[1:])/2
    widths=np.diff(edges); counts=np.histogram(mass[selected],bins=edges)[0]
    lo,hi=t['supervision']['regions']['signal']; sr=(edges[:-1]>=lo)&(edges[1:]<=hi)
    sb=~sr
    if np.sum(counts[sb])<3 or np.count_nonzero(sb)<2: raise ValueError('insufficient sideband counts for fit')
    mid=float(np.mean(centers)); scale=float(np.ptp(centers)); x=(centers-mid)/scale
    # Exact bin integral of exp(a + b*(mass-mid)/scale).
    def expectation(theta):
        a,b=theta
        factor=np.sinh(b*widths/(2*scale))/(b*widths/(2*scale)) if abs(b)>1.e-7 else np.ones(len(widths))
        return np.exp(np.clip(a+b*x,-50,50))*widths*factor
    def objective(theta):
        mu=expectation(theta)[sb]
        return float(np.sum(mu-counts[sb]*np.log(mu)))
    fit=minimize(objective,[math.log(max(np.sum(counts[sb])/np.sum(widths[sb]),1.e-6)),0.],method='BFGS')
    if not fit.success and np.linalg.norm(fit.jac)>1.e-3: raise ValueError('sideband fit failed')
    mu=expectation(fit.x); expected=float(mu[sr].sum())
    h=1.e-4
    grad=np.array([(expectation(fit.x+np.eye(2)[j]*h)[sr].sum()-expectation(fit.x-np.eye(2)[j]*h)[sr].sum())/(2*h) for j in range(2)])
    jac=np.column_stack([(expectation(fit.x+np.eye(2)[j]*h)-expectation(fit.x-np.eye(2)[j]*h))/(2*h) for j in range(2)])
    information=jac[sb].T@(jac[sb]/mu[sb,None])
    cov=np.linalg.inv(information); variance=float(grad@cov@grad)
    residual=(float(counts[sr].sum())-expected)/math.sqrt(expected+variance)
    deviance=float(2*np.sum(np.where(counts[sb]>0, counts[sb]*np.log(np.maximum(counts[sb],1)/mu[sb]),0)-counts[sb]+mu[sb]))
    return {'statistic':max(0.,residual),'signed_residual':residual,'expected':expected,
            'fit_variance':variance,'sideband_deviance':deviance,'sideband_dof':int(sb.sum())-2,
            'calibrated_significance':False}


def _check(verdict, **detail):
    return {'verdict':verdict, **detail}


def sculpting_checks(t, data, fitted, reference=None):
    windows=t['supervision'].get('additional_windows',[])
    if windows:
        outputs=[]
        for index,window in enumerate([t['supervision']['regions']]+windows):
            local=json.loads(json.dumps(t)); local['supervision'].pop('additional_windows')
            local['supervision']['regions']=window
            scoped={key:[r for r in rows if r.get('window')==index] for key,rows in fitted.items()}
            outputs.append(sculpting_checks(local,data,scoped,reference))
        return {key:_check('fail' if any(r[key]['verdict']=='fail' for r in outputs) else
                           'unresolved' if any(r[key]['verdict']=='unresolved' for r in outputs) else outputs[0][key]['verdict'],
                           windows=[r[key] for r in outputs]) for key in outputs[0]}
    from scipy.stats import chi2
    c=t['checks']; regions=region_ids(data['region'],t['supervision']); side=regions>0
    alpha=c['alpha']; permutations=c['permutations']
    sep=[]
    nominal=fitted['scores'][0]['folds']
    # Group-level exchangeability is required for these permutation diagnostics.
    if len(set(data['group_id']))!=len(data['group_id']):
        return {k:_check('unresolved',reason='permutation diagnostics require one independent row per group')
                for k in ('check:ml-sideband-separability','check:ml-selection-flatness',
                          'check:ml-reference-fidelity','check:ml-spurious-signal','check:ml-fit-adequacy')}
    for fold in range(t['splits']['k']):
        mask=side&(nominal==fold)
        sep.append(_permutation_p(data['x'][mask],regions[mask]-1,permutations,100+fold))
    sep_p=min(1.,len(sep)*min(sep)) if all(v is not None for v in sep) else None
    if t['splits']['k']/(permutations+1)>alpha: sep_p=None
    checks={'check:ml-sideband-separability':_check('unresolved' if sep_p is None else 'fail' if sep_p<=alpha else 'pass',
                                                  per_fold_p=sep, conservative_p=sep_p,
                                                  scope='Mean and quadratic feature moments; not a universal independence test')}
    bins=np.digitize(data['region'],c['sideband_bins'])
    flat=[]; correlations=[]; spurious=[]; adequacy=[]
    external=_evaluate_external(t,fitted,reference) if reference is not None else None
    for row in fitted['scores']:
        if row['kind'] in ('supervised_oracle','idealized_anomaly'): continue
        # Sidebands only: a signal-region correlation would inspect the search region before unblind.
        correlations.append({'arm':row['arm'],'seed':row['seed'],'salt':row['salt'],'scope':'sidebands',
                             'correlation':float(np.corrcoef(row['scores'][side],data['region'][side])[0,1])
                             if np.std(row['scores'][side]) else None,'diagnostic_only':True})
        efficiencies=[1.] if row['kind'] in ('inclusive','inclusive_bump_hunt') else t['scoring']['working_points']
        for eff in efficiencies:
            selected=row['scores']>=1-eff
            ps=[]
            for fold in range(t['splits']['k']):
                mask=side&(row['folds']==fold)
                ps.append(_flatness_p(selected[mask],bins[mask],permutations,200+fold))
            p=min(1.,len(ps)*min(ps)) if all(v is not None for v in ps) else None
            flat.append({'arm':row['arm'],'efficiency':eff,'per_fold_p':ps,'p':p})
            if external is not None:
                chosen=external[(row['arm'],row['seed'],row['salt'])]>=1-eff
                try:
                    fit=bump_statistic(reference['region'],chosen,t)
                    spurious.append({'arm':row['arm'],'efficiency':eff,**fit})
                    dof=fit['sideband_dof']
                    adequacy.append(float(chi2.sf(fit['sideband_deviance'],dof)) if dof>0 else None)
                except (ValueError,np.linalg.LinAlgError) as exc:
                    spurious.append({'arm':row['arm'],'efficiency':eff,'error':str(exc)})
                    adequacy.append(None)
    # Bonferroni across folds and declared arm/seed/salt/working-point rows.
    valid=[row['p'] for row in flat if row['p'] is not None]
    merged=min(1.,min(valid)*len(flat)) if len(valid)==len(flat) and flat else None
    if len(flat)*t['splits']['k']/(permutations+1)>alpha: merged=None
    checks['check:ml-selection-flatness']=_check('unresolved' if merged is None else 'fail' if merged<=alpha else 'pass',
                                                rows=flat,corrected_p=merged)
    checks['score_region_correlation']=_check('diagnostic',rows=correlations)
    checks['check:ml-spurious-signal']=_check('unresolved' if not spurious or any('error' in r for r in spurious)
        else 'fail' if any(abs(r['signed_residual'])>max(c['max_spurious_z'],float(__import__('scipy').stats.norm.isf(alpha/(2*len(spurious))))) for r in spurious) else 'unresolved',rows=spurious,
        scope='Trial-corrected Gaussian diagnostic alarm only; acceptance requires calibrated whole-procedure toy maximum')
    checks['check:ml-fit-adequacy']=_check('unresolved' if not adequacy or any(v is None for v in adequacy)
        else 'fail' if min(adequacy)*len(adequacy)<=alpha else 'pass',p_values=adequacy,
        scope='Sideband deviance diagnostic on independent background; whole-procedure toys calibrate claims')
    fidelity=None
    if reference is not None:
        rside=region_ids(reference['region'],t['supervision'])>0
        # Include feature-mass interactions to detect mismatched proxy dependence.
        x=np.column_stack((data['x'][side],data['region'][side],data['x'][side]*data['region'][side,None]))
        y=np.column_stack((reference['x'][rside],reference['region'][rside],reference['x'][rside]*reference['region'][rside,None]))
        fidelity=_permutation_p(np.vstack((x,y)),np.r_[np.zeros(len(x)),np.ones(len(y))],permutations,311)
    checks['check:ml-reference-fidelity']=_check('unresolved' if fidelity is None else 'fail' if fidelity<=alpha else 'pass',p=fidelity)
    return checks


def calibrate_spurious(checks,toy_checks,alpha):
    """Calibrate the maximum absolute reference residual over all declared rows."""
    def maximum(row):
        if row is None: return None
        if 'windows' in row:
            values=[maximum(w) for w in row['windows']]
        else:
            values=[abs(r['signed_residual']) if 'signed_residual' in r else None for r in row.get('rows',[])]
        return max(values) if values and all(v is not None for v in values) else None
    result=json.loads(json.dumps(checks)); row=result['check:ml-spurious-signal']
    observed=maximum(row)
    toys=[maximum(c.get('check:ml-spurious-signal')) if c is not None else None for c in toy_checks]
    p=calibrated_p(observed,toys) if observed is not None and toys else None
    resolved=len(toys)>=math.ceil(1/alpha)
    row.update(toy_maximum_p=p,toy_maxima=toys,reference_maximum=observed,
               toy_scope='Maximum across folds, arms, seeds, salts, windows and working points; toy-law acceptance remains external')
    if row['verdict']!='fail': row['verdict']='fail' if resolved and p is not None and p<=alpha else 'unresolved'
    return result


def _max_statistic(t, data, fitted):
    if t['supervision']['kind']=='truth': raise ValueError('truth-trained study has no search statistic')
    values=[]
    for row in fitted['scores']:
        if row['kind'] in ('supervised_oracle','idealized_anomaly'): continue
        effs=[1.] if row['kind'] in ('inclusive','inclusive_bump_hunt') else t['scoring']['working_points']
        for eff in effs:
            local={**t,'supervision':row.get('supervision',t['supervision'])}
            values.append(bump_statistic(data['region'],row['scores']>=1-eff,local)['statistic'])
    return max(values)


def _signal_partition(pool, declaration):
    fraction=declaration['injection_fraction']; salt=declaration['salt']
    mask=np.array([int(hashlib.sha256(f'{salt}:{g}'.encode()).hexdigest(),16)/2**256<fraction for g in pool['group_id']])
    if not mask.any() or mask.all(): raise ValueError('empty injection/evaluation partition')
    return _subset(pool,mask),_subset(pool,~mask)


def _signal_draw(pool, count, rng):
    if len(set(pool['group_id']))!=len(pool['group_id']):
        raise ValueError('exact-count injection requires one independent event per group')
    if count>len(pool['x']): raise ValueError('injection count exceeds independent pool; no replacement')
    indices=rng.choice(len(pool['x']),size=count,replace=False,p=pool['weight']/pool['weight'].sum())
    return _subset(pool,indices)


def _concatenate(a,b):
    return {key:np.concatenate((a[key],b[key])) for key in a}


def injection_closure(injections, toy_statistics, policy):
    """Exact-binomial Monte Carlo intervals conditional on the supplied populations.

    Samplings, not seeds, are the trials. The estimand conditions on the one
    background dataset and finite signal pool, not a population of experiments.
    A union bound controls false declarations over all strength cells.
    """
    from scipy.stats import beta
    if any(r['statistic'] is None for r in injections):
        return _check('unresolved',reason='Injection statistics remain blinded')
    if len(toy_statistics)<math.ceil(1/policy['alpha']):
        return _check('unresolved',reason='Null ensemble cannot resolve requested closure alpha')
    strengths=sorted({r['strength'] for r in injections}); cells=[]
    tail=policy['false_fail_probability']/(2*len(strengths))
    for strength in strengths:
        rows=[r for r in injections if r['strength']==strength]
        ps=[calibrated_p(r['statistic'],toy_statistics) for r in rows]
        count=sum(p<=policy['alpha'] for p in ps); n=len(rows)
        lo=0. if count==0 else float(beta.ppf(tail,count,n-count+1))
        hi=1. if count==n else float(beta.ppf(1-tail,count+1,n-count))
        cells.append({'strength':strength,'samplings':n,'rejections':count,'power':count/n,
                      'interval':[lo,hi],'p_values':ps})
    zero=next(c for c in cells if c['strength']==0); high=cells[-1]
    lower_gain=high['interval'][0]-zero['interval'][1]
    upper_gain=high['interval'][1]-zero['interval'][0]
    verdict='pass' if lower_gain>=policy['min_power_gain'] and zero['interval'][1]<=policy['max_null_rejection'] else (
        'fail' if upper_gain<policy['min_power_gain'] or zero['interval'][0]>policy['max_null_rejection'] else 'unresolved')
    return _check(verdict,estimand=policy['estimand'],cells=cells,
                  power_gain_interval=[lower_gain,upper_gain],false_fail_probability=policy['false_fail_probability'],
                  scope='Conditional on fixed background, signal pool AND supplied toy ensemble; intervals do not include toy-law or threshold uncertainty')


def _disposition(t, checks, equal_mixture):
    if equal_mixture: return 'unidentifiable'
    if any(c['verdict']=='fail' for key,c in checks.items() if key!='score_region_correlation'):
        return 'assumption_violated'
    needed=('check:ml-sideband-separability','check:ml-selection-flatness','check:ml-spurious-signal',
            'check:ml-reference-fidelity','check:ml-injection-closure','check:ml-null-calibration','check:ml-fit-adequacy')
    if t['dataset']['synthetic'] and all(v['verdict'] in ('pass','diagnostic') for k,v in checks.items() if k!='check:ml-claim-scope') and all(checks.get(k,{}).get('verdict')=='pass' for k in needed):
        return 'supported_synthetic'
    return 'limited'


def effective_n(data, mask=None):
    mask=np.ones(len(data['weight']),dtype=bool) if mask is None else mask
    _,inverse=np.unique(data['group_id'][mask],return_inverse=True)
    weights=np.bincount(inverse,weights=data['weight'][mask])
    return float(weights.sum()**2/np.square(weights).sum()) if weights.size and weights.sum() else 0.


def achieved_sizing(t,data,fitted):
    cells=[]
    for row in fitted['scores']:
        local=row.get('supervision',t['supervision']); regions=region_ids(data['region'],local)
        for fold in range(t['splits']['k']):
            for region in (1,2):
                mask=(row['folds']==fold)&(regions==region)
                for eff in ([1.] if row['kind'] in ('inclusive','inclusive_bump_hunt') else t['scoring']['working_points']):
                    selected=mask&(row['scores']>=1-eff)
                    n=effective_n(data,mask); count=effective_n(data,selected)
                    actual=float(data['weight'][selected].sum()/data['weight'][mask].sum()) if n else 0.
                    rel=math.sqrt((1-actual)/(n*actual)) if actual and n else None
                    cells.append({'arm':row['arm'],'seed':row['seed'],'salt':row['salt'],'fold':fold,'region':region,
                                  'efficiency':eff,'selected_effective_n':count,'relative_error':rel,
                                  'sufficient':count>=t['statistics']['min_selected_per_fold'] and rel is not None and rel<=t['statistics']['max_relative_error']})
    return _check('pass' if cells and all(c['sufficient'] for c in cells) else 'unresolved',cells=cells,scope='Achieved sideband selections; SR precision withheld')


def equal_budget(models):
    groups={}
    for row in models:
        g=groups.setdefault(row['arm'],{'trainings':0,'epochs':0,'wall_seconds':0.,'cpu_seconds':0.})
        for key,value in [('trainings',1),('epochs',row['epochs']),('wall_seconds',row['wall_seconds']),('cpu_seconds',row['cpu_seconds'])]: g[key]+=value
    equal=len({(r['trainings'],r['epochs']) for r in groups.values()})<=1
    return _check('pass' if equal and groups else 'fail',actuals=groups,
                  definition='Equal measured trainings and epochs; wall and CPU costs reported, not assumed equal')


def leakage_check(data,truth):
    if truth is None or len(np.unique(truth))<2: return _check('unresolved',reason='No two-class evaluator canary; feature provenance needs review')
    correlations=[abs(float(np.corrcoef(data['x'][:,j],truth)[0,1])) if np.std(data['x'][:,j]) else 0. for j in range(data['x'].shape[1])]
    return _check('fail' if max(correlations,default=0.)>=.995 else 'unresolved',
                  absolute_correlations=correlations,threshold=.995,scope='Near-exact truth proxy alarm; absence is not a leakage certificate')


def additional_checks(t,data,fitted,truth=None):
    audit=audit_models(fitted['models'])
    families={}
    for a in t['models']+t['baselines']:
        if a['kind'] not in ('inclusive','inclusive_bump_hunt'):
            family=a.get('family',a['architecture']); families[family]=families.get(family,0)+1
    return {'check:ml-crossfit-audit':_check('pass' if audit['passed'] else 'fail',**audit),
            'check:ml-label-leakage':_check('asserted_by_construction',guard='ml_crossfit.validate: forbidden features; _single_crossfit: trainer dictionaries'),
            'check:ml-noise-ceiling':leakage_check(data,truth),
            'check:ml-statistics-sizing':achieved_sizing(t,data,fitted),
            'check:ml-equal-budget':equal_budget(fitted['models']),
            'check:ml-trials-accounting':_check('pass' if all(n<=t['budget']['max_trials'] for n in families.values()) else 'fail',
                families=families,windows=size_study(t)['windows'],working_points=t['scoring']['working_points'],
                rule='Maximum over every non-truth arm, seed, salt, window and working point')}


def injection_metrics(t,campaign,evaluation,reference):
    evaluated=_evaluate_external(t,campaign,evaluation)
    background_scores=_evaluate_external(t,campaign,reference) if reference is not None else None
    metrics=[]
    for row in campaign['scores']:
        key=(row['arm'],row['seed'],row['salt']); window=row.get('window',0)
        # Evaluate the signal and background on the same declared reconstructed window.
        sup=row.get('supervision',t['supervision']); sr=region_ids(evaluation['region'],sup)==0
        for eff in ([1.] if row['kind'] in ('inclusive','inclusive_bump_hunt') else t['scoring']['working_points']):
            efficiency=float(np.average(evaluated[key][sr]>=1-eff,weights=evaluation['weight'][sr])) if sr.any() else None
            background=None; tail_n=0.
            if background_scores is not None:
                rsr=region_ids(reference['region'],sup)==0; selected=rsr&(background_scores[key]>=1-eff)
                background=float(np.average(background_scores[key][rsr]>=1-eff,weights=reference['weight'][rsr])) if rsr.any() else None
                tail_n=effective_n(reference,selected)
            selected_signal=sr&(evaluated[key]>=1-eff); signal_n=effective_n(evaluation,selected_signal)
            sn=effective_n(evaluation,sr)
            signal_error=math.sqrt((1-efficiency)/(sn*efficiency)) if efficiency and sn else None
            bn=effective_n(reference,rsr) if reference is not None else 0.
            background_error=math.sqrt((1-background)/(bn*background)) if background and bn else None
            metrics.append({'arm':row['arm'],'kind':row['kind'],'seed':row['seed'],'salt':row['salt'],'window':window,
                            'data_efficiency':eff,'signal_efficiency':efficiency,'background_efficiency':background,
                            'significance_improvement':efficiency/math.sqrt(background) if background and efficiency is not None else None,
                            'signal_selected_effective_n':signal_n,'reference_tail_effective_n':tail_n,
                            'signal_relative_error':signal_error,'background_relative_error':background_error,
                            'precision_status':'sufficient' if min(signal_n,tail_n)>=t['statistics']['min_selected_per_fold'] and signal_error is not None and background_error is not None and max(signal_error,background_error)<=t['statistics']['max_relative_error'] else 'unresolved',
                            'status':'zero_acceptance' if efficiency==0 else 'finite' if efficiency is not None else 'unresolved'})
    return metrics


def evaluation_sizing(injections):
    rows=[m for r in injections for m in r['metrics']]
    return _check('pass' if rows and all(r['precision_status']=='sufficient' for r in rows) else 'unresolved',
                  insufficient=sum(r['precision_status']!='sufficient' for r in rows),cells=len(rows),scope='Achieved signal and reference-window tails')


def injection_medians(injections):
    groups={}
    for row in injections:
        for m in row['metrics']:
            key=(row['strength'],m['arm'],m['kind'],m['window'],m['data_efficiency'])
            groups.setdefault(key,[]).append(m['signal_efficiency'])
    return [dict(strength=k[0],arm=k[1],kind=k[2],window=k[3],data_efficiency=k[4],
                 median_signal_efficiency=float(np.median(v)) if all(x is not None for x in v) else None,
                 spread_scope='Correlated samplings, seeds and salts; no independent-data confidence interval') for k,v in sorted(groups.items())]


def replay_campaign(t,data,models,context):
    """Re-score frozen checkpoints; never fit, tune, select anew or add a test read."""
    result={'models':[r for r in models if r['context']==context or r['context'].startswith(context+'-window-')], 'scores':[], 'ensembles':[]}
    windows=[t['supervision']['regions']]+t['supervision'].get('additional_windows',[])
    for wi,window in enumerate(windows):
        sup={**t['supervision'],'regions':window}; sup.pop('additional_windows',None)
        ctx=context if len(windows)==1 else f'{context}-window-{wi}'
        regions=region_ids(data['region'],sup)
        for declared_salt in t['splits']['fold_salts']:
            salt=declared_salt if ctx=='nominal' else f'{declared_salt}:{ctx}'
            folds=fold_map(data['group_id'],t['splits']['k'],salt)
            for arm in t['baselines']+t['models']:
                for seed in t['seeds']:
                    score=np.ones(len(regions)); raw=score.copy()
                    for fold in range(t['splits']['k']):
                        test=folds==fold
                        rows=sorted([r for r in models if r['context']==ctx and r['salt']==salt and r['arm']==arm['id'] and r['seed']==seed and r['fold']==fold and r['selected']],key=lambda r:r['rotation'])
                        ensemble=[]; mapped=[]; probabilities=[]
                        if arm['kind'] not in ('inclusive','inclusive_bump_hunt') and len(rows)!=t['splits']['k']-1:
                            raise ValueError('replay model population incomplete, including failed toys')
                        for row in rows:
                            with np.load(io.BytesIO(ml._bytes(row['checkpoint'],Path.cwd())),allow_pickle=False) as z: model={k:z[k] for k in z.files}
                            transform=json.loads(ml._bytes(row['transform'],Path.cwd()))
                            prob=ml_backends.predict_selected(model,apply_transform(transform,data['x'][test],regions[test]))
                            ref=np.sort(prob[regions[test]==0]); mapped.append(_rank(prob,ref)); probabilities.append(prob)
                            ensemble.append((model,transform,ref))
                        if mapped:
                            average=np.mean(mapped,axis=0); ref=np.sort(average[regions[test]==0])
                            score[test]=_rank(average,ref); raw[test]=np.mean(probabilities,axis=0); ensemble.append(ref)
                        result['ensembles'].append({'arm':arm['id'],'kind':arm['kind'],'seed':seed,'salt':salt,'fold':fold,
                            'ensemble':ensemble,'supervision':sup,'test_groups':set(data['group_id'][test]),'window':wi})
                    result['scores'].append({'arm':arm['id'],'kind':arm['kind'],'seed':seed,'salt':salt,'declared_salt':declared_salt,
                        'supervision':sup,'scores':score,'probabilities':raw,'folds':folds,'window':wi})
    return result


def verify_science(receipt,t,output,pending=False):
    """Recompute scientific fields from pinned inputs and frozen model artifacts."""
    base=Path(receipt['input_base'])
    data=load_events(t['dataset']['pins'][0],base,len(t['dataset']['features']))
    reference=load_events(t['checks']['reference'],base,len(t['dataset']['features'])) if t['checks']['reference'] else None
    def check_maps(events,context):
        windows=[t['supervision']['regions']]+t['supervision'].get('additional_windows',[])
        expected=[]
        for wi in range(len(windows)):
            ctx=context if len(windows)==1 else f'{context}-window-{wi}'
            for declared in t['splits']['fold_salts']:
                salt=declared if ctx=='nominal' else f'{declared}:{ctx}'
                folds=fold_map(events['group_id'],t['splits']['k'],salt).tolist()
                row={'context':ctx,'salt':salt,'event_ids':events['event_id'].tolist(),'group_ids':events['group_id'].tolist(),'folds':folds,'sha256':ml.digest(list(zip(events['event_id'].tolist(),folds)))}
                if len(windows)>1: row['window']=wi
                expected.append(row)
        actual=[m for m in receipt['fold_maps'] if m['context']==context or m['context'].startswith(context+'-window-')]
        if actual!=expected: raise ValueError('fold map identities differ from pinned input replay')
    check_maps(data,'nominal')
    fitted=replay_campaign(t,data,receipt['models'],'nominal')
    with np.load(io.BytesIO(ml._bytes(receipt['score_artifact'],output)),allow_pickle=False) as z:
        if not np.array_equal(z['event_id'],data['event_id']) or not np.array_equal(z['scores'],np.array([r['scores'] for r in fitted['scores']])):
            raise ValueError('nominal scores differ from checkpoint replay')
    truth=_truth(t['dataset']['truth_pin'],base,data['event_id']) if t['dataset']['truth_column'] else None
    checks=sculpting_checks(t,data,fitted,reference)
    checks.update(additional_checks(t,data,fitted,_truth(t['dataset']['truth_pin'],base,data['event_id']) if t['dataset']['truth_column'] else None))
    injections=[]
    if t['injection']:
        inj=t['injection']; pool=load_events(inj['signal_pool'],base,len(t['dataset']['features']),allow_sampling_weights=True)
        injected,evaluation=_signal_partition(pool,inj['partition']); sr=t['supervision']['regions']['signal']
        localized=float(np.mean((pool['region']>=sr[0])&(pool['region']<sr[1])))
        checks['check:ml-benchmark-localization']=_check('pass' if localized>=inj.get('localization_min',.95) else 'fail',fraction_in_signal_region=localized,
            criterion='Declared localization fraction in the frozen reconstructed window',minimum=inj.get('localization_min',.95),source='Operational policy parameter; not a physics constant')
        for strength in inj['strengths']:
            for sampling in range(inj['samplings']):
                context=f'injection-{strength}-{sampling}'
                draw=_signal_draw(injected,strength,np.random.default_rng(int(ml.digest(context)[:8],16)))
                draw['weight']=np.full(len(draw['weight']),data['weight'][0]); sample=_concatenate(data,draw)
                check_maps(sample,context)
                campaign=replay_campaign(t,sample,receipt['models'],context)
                injections.append({'strength':strength,'sampling':sampling,'context':context,
                    'injection_groups':draw['group_id'].tolist(),'evaluation_groups':evaluation['group_id'].tolist(),
                    'evaluation_reads':1,'evaluation_effective_n':effective_n(evaluation),
                    'draw_rule':'Sequential weighted draw without replacement; sampled events have unit relative training weight',
                    'metrics':injection_metrics(t,campaign,evaluation,reference),'statistic':None})
        checks['check:ml-injection-closure']=_check('unresolved',reason='Disjoint retraining executed; power/coverage needs declared ensemble acceptance',model_sets=len(injections))
    else:
        checks['check:ml-benchmark-localization']=_check('unresolved',reason='No supplied signal pool')
        checks['check:ml-injection-closure']=_check('unresolved',reason='No injection campaign')
    checks['check:ml-evaluation-sizing']=evaluation_sizing(injections)
    expected_maps=size_study(t)['windows']*len(t['splits']['fold_salts'])*(1+size_study(t)['injection_points']+size_study(t)['toys'])
    if len(receipt['fold_maps'])!=expected_maps: raise ValueError('fold map population incomplete')
    null=t['null_calibration']; declared=(null or {}).get('datasets',[])
    if len(receipt['null_toys'])!=len(declared): raise ValueError('null toy population differs from declaration')
    toy_diagnostics=[]
    for index,(pin,row) in enumerate(zip(declared,receipt['null_toys'])):
        if row['pin']!=pin or row['toy']!=index: raise ValueError('null toy identity changed')
        toy=load_events(pin,base,len(t['dataset']['features']))
        check_maps(toy,f'null-{index}')
        campaign=replay_campaign(t,toy,receipt['models'],f'null-{index}')
        toy_checks=sculpting_checks(t,toy,campaign,reference)
        failed=any(c['verdict']=='fail' for c in toy_checks.values())
        toy_diagnostics.append(None if failed else toy_checks)
        expected=None if failed else _max_statistic(t,toy,campaign)
        if row['state']!=('failed_extreme' if failed else 'complete') or row['statistic']!=expected:
            raise ValueError('null statistic or disposition differs from checkpoint replay')
        if failed and not row.get('training_records'): raise ValueError('failed toy requires complete training records')
    if null:
        checks['check:ml-null-execution']=_check('pass' if all(r['state']=='complete' for r in receipt['null_toys']) else 'unresolved',
            toys=len(declared),failed=sum(r['state']!='complete' for r in receipt['null_toys']),resolution=1/(len(declared)+1),
            scope='Whole supplied-null procedure; supplied toy-law fidelity remains a premise')
    checks['check:ml-null-calibration']=_check('unresolved',reason='Pinned toy-law provenance and exchangeability acceptance required',toys=len(declared),minimum_toys=math.ceil(1/t['checks']['alpha']))
    checks=calibrate_spurious(checks,toy_diagnostics,t['checks']['alpha'])
    checks['check:ml-test-once']=_check('pass',exposures=len(receipt['exposures']))
    expected_gates=[]
    if null and null['unblind']:
        blockers=[k for k,v in checks.items() if v['verdict'] in ('fail','unresolved')]
        expected_gates=[{'gate':'unblind','verdict':'blocked','reasons':blockers or ['Authenticated decision-gate record required']}]
    if receipt['gates']!=expected_gates: raise ValueError('gate record differs from authenticated/blocked state')
    checks['check:ml-seed-spread']=_check('diagnostic' if t['supervision']['kind']=='truth' else 'unresolved',scope='Seed and fold-salt spreads reported separately; no confidence interpretation')
    equal=t['supervision']['kind']=='mixture' and len(set(t['supervision']['fractions']))==1
    disposition=_disposition(t,checks,equal)
    checks['check:ml-claim-scope']=_check('unresolved',disposition=disposition,physics_validated=False,reason='Diagnostic only; research-protocol claim acceptance required')
    if receipt['checks']!=checks or receipt['disposition']!=disposition: raise ValueError('checks/disposition differ from recomputation')
    expected_injections=[] if equal else injections
    if receipt['injections']!=expected_injections or receipt['injection_medians']!=([] if equal else injection_medians(injections)) or receipt['performance']!=(None if equal else injections):
        raise ValueError('injection performance differs from recomputation')
    for a,row in zip(receipt['arms'],fitted['scores']):
        if a['id']!=row['arm'] or a['seed']!=row['seed'] or a['salt']!=row['salt']: raise ValueError('arm ordering differs from replay')
        if a['truth_auc_evaluator_only'] is not None: raise ValueError('truth AUC unavailable before authenticated unblind')
        if t['supervision']['kind']=='truth' and not equal:
            m=ml.metrics(truth,row['probabilities'],data['weight'],.5,10)[0]
            if any(a['calibration'][k]!=m[k] for k in ('ece','brier')): raise ValueError('truth metric differs from recomputation')
    if t['supervision']['kind']=='truth' and not equal:
        expected_summary={}
        for arm in t['baselines']+t['models']:
            for wi in range(size_study(t)['windows']):
                subset=[r for r in receipt['arms'] if r['id']==arm['id'] and r['window']==wi]
                for metric in ('ece','brier'):
                    values=[r['calibration'][metric] for r in subset if r['declared_salt']==t['splits']['salt']]
                    salt_means=[np.mean([r['calibration'][metric] for r in subset if r['declared_salt']==salt]) for salt in t['splits']['fold_salts']]
                    expected_summary.setdefault(metric,{}).setdefault(arm['id'],{})[str(wi)]={'mean':float(np.mean(values)),'initialization_seed_spread':float(np.std(values,ddof=1)),'fold_salt_spread':float(np.std(salt_means,ddof=1)) if len(salt_means)>1 else None}
        if receipt['summary']!=expected_summary: raise ValueError('truth summary differs from recomputation')
    if equal and receipt['summary']: raise ValueError('unidentifiable summary must be suppressed')
    if t['supervision']['kind']!='truth' and not equal:
        expected_summary={metric:{arm['id']:{str(w):{'mean':None,'initialization_seed_spread':None,'fold_salt_spread':None,'state':'blinded'} for w in range(size_study(t)['windows'])} for arm in t['baselines']+t['models']} for metric in ('ece','brier')}
        if receipt['summary']!=expected_summary: raise ValueError('blinded summary differs from recomputation')
    if receipt.get('claim_kind')!=t.get('claim_kind','diagnostic'): raise ValueError('claim kind changed')
    if not pending: ml_exposure.verify_receipt(receipt,Path(output)/'receipt.json')


def validate_receipt(receipt,t,output,*,pending=False):
    validate(t)
    if receipt.get('spec_sha256')!=ml.digest(t) or receipt.get('task')!=t: raise ValueError('receipt specification changed')
    if receipt.get('kind')!='ml-crossfit-receipt' or type(receipt.get('schema_version')) is not int or receipt['schema_version']!=2:
        raise ValueError('cross-fit receipt schema 2 required')
    declared={a['id']:a for a in t['baselines']+t['models']}
    expected_arms={(arm,seed,salt,window) for arm in declared for seed in t['seeds']
                   for salt in t['splits']['fold_salts'] for window in range(size_study(t)['windows'])}
    actual_arms={(r['id'],r['seed'],r['declared_salt'],r['window']) for r in receipt['arms']}
    if actual_arms!=expected_arms or len(receipt['arms'])!=len(expected_arms):
        raise ValueError('receipt arm/seed/salt/window population changed')
    for row in receipt['arms']:
        kind=declared[row['id']]['kind']
        role=('labelled ceiling; unavailable to a real search' if kind=='supervised_oracle' or (t['supervision']['kind']=='truth' and kind not in ('inclusive','inclusive_bump_hunt'))
              else 'synthetic truth-reference' if kind=='idealized_anomaly' else 'available method')
        if row['kind']!=kind or row['information_role']!=role:
            raise ValueError('receipt oracle/information role changed')
        blinded=t['supervision']['kind']!='truth' and receipt.get('observed_statistic') is None
        if row['calibration'].get('state')!=('blinded' if blinded else 'unblinded' if t['supervision']['kind']!='truth' else 'truth_labels'):
            raise ValueError('receipt calibration blind state changed')
        for metric in ('ece','brier'):
            if blinded:
                if row['calibration'][metric] is not None: raise ValueError('region-label metric reported before unblind')
            else: ml._number(row['calibration'][metric],0,1)
        if row['truth_auc_evaluator_only'] is not None: ml._number(row['truth_auc_evaluator_only'],0,1)
    environment=json.loads((Path(output)/'environment.json').read_text())
    if receipt.get('environment_sha256')!=ml.digest(environment): raise ValueError('receipt environment changed')
    for code_pin in environment['code'].values(): ml._bytes(code_pin,output)
    if not audit_models(receipt['models'])['passed'] or not receipt['crossfit_audit']['passed']:
        raise ValueError('crossfit receipt contains group leakage')
    expected=size_study(t)['trainings']
    failures=sum(r['state']!='complete' for r in receipt['null_toys'])
    if len(receipt['models'])!=expected:
        raise ValueError('receipt model population incomplete')
    if len(receipt['models'])!=receipt['cost_actuals']['completed_trainings']:
        raise ValueError('receipt completed model count changed')
    if receipt['fold_map_digest']!=ml.digest(receipt['fold_maps']): raise ValueError('fold map digest changed')
    for mapping in receipt['fold_maps']:
        expected_folds=fold_map(mapping['group_ids'],t['splits']['k'],mapping['salt']).tolist()
        if mapping['folds']!=expected_folds: raise ValueError('fold map differs from recomputed group hash')
    maps={(m['context'],m['salt']):m for m in receipt['fold_maps']}
    model_keys=set(); rotations={}
    for row in receipt['models']:
        row=model_scope(row)
        key=tuple(row[k] for k in ('context','arm','seed','salt','fold','rotation','initialization'))
        if key in model_keys: raise ValueError('duplicate model row')
        model_keys.add(key)
        mapping=maps[(row['context'],row['salt'])]
        f=np.asarray(mapping['folds']); groups=np.asarray(mapping['group_ids'])
        expected_sets={'test_groups':set(groups[f==row['fold']]),
                       'validation_groups':set(groups[f==row['rotation']]),
                       'train_groups':set(groups[(f!=row['fold'])&(f!=row['rotation'])])}
        if row.get('training_pool_scope'):
            pool=row['training_pool_scope']; pf=np.asarray(pool['folds']); pg=np.asarray(pool['group_ids'])
            ml._bytes(pool['pin'],output)
            expected_sets['train_groups']=set(pg[(pf!=row['fold'])&(pf!=row['rotation'])])
            expected_sets['validation_groups']=set(pg[pf==row['rotation']])
        expected_sets['preprocessing_groups']=expected_sets['train_groups']
        if row['arm_kind']=='idealized_anomaly':
            if any(not set(row[k])<=v for k,v in expected_sets.items()): raise ValueError('idealized model group scope exceeds fold map')
        elif any(set(row[k])!=v for k,v in expected_sets.items()): raise ValueError('model group scope differs from fold map')
        rotations.setdefault(key[:-1],[]).append(row)
    for rows in rotations.values():
        if len(rows)!=t['inner_selection']['initializations'] or sum(r['selected'] for r in rows)!=1:
            raise ValueError('model initialization population/selection changed')
        if not min(rows,key=lambda r:(r['validation_loss'],r['initialization']))['selected']:
            raise ValueError('model selection did not use minimum validation loss')
    with np.load(io.BytesIO(ml._bytes(receipt['score_artifact'],output)),allow_pickle=False) as z:
        score_rows=size_study(t)['windows']*len(t['splits']['fold_salts'])*len(t['seeds'])*(len(t['models'])+len(t['baselines']))
        if z['scores'].shape!=(score_rows,len(z['event_id'])) or len(set(z['event_id']))!=len(z['event_id']):
            raise ValueError('event score population differs from declared ensembles')
        if not np.all(np.isfinite(z['scores'])) or np.any((z['scores']<0)|(z['scores']>1)):
            raise ValueError('invalid final ensemble scores')
    keys=set()
    for row in receipt['exposures']:
        key=(row['context'],row['salt'],row['fold'])
        if row['test_reads']!=1 or key in keys: raise ValueError('exactly one exposure per fold required')
        keys.add(key); ml._bytes(row['freeze'],output)
    if len(keys)!=size_study(t)['windows']*len(t['splits']['fold_salts'])*t['splits']['k']*(1+size_study(t)['injection_points']+size_study(t)['toys']):
        raise ValueError('receipt exposure population incomplete')
    for row in receipt['models']:
        ml._bytes(row['checkpoint'],output); ml._bytes(row['transform'],output)
        recorded=json.loads(ml._bytes(row['history_pin'],output))
        if recorded['history']!=row['history'] or recorded['validation_loss']!=row['validation_loss']:
            raise ValueError('initialization history changed')
        if not row['history'] or len(row['history'])>t['budget']['epochs']:
            raise ValueError('model history outside budget')
    for row in receipt['injections']:
        if row['evaluation_reads']!=1 or set(row['injection_groups'])&set(row['evaluation_groups']):
            raise ValueError('injection/evaluation isolation failed')
    if receipt['observed_statistic'] is not None: raise ValueError('authenticated unblind decision record required')
    if receipt.get('calibrated_p') is not None: raise ValueError('calibrated p without authenticated unblind')
    if receipt['observed_statistic'] is not None and not any(g['gate']=='unblind' and g['verdict']=='passed' for g in receipt['gates']):
        raise ValueError('observed statistic without unblind gate')
    verify_science(receipt,t,output,pending)
    return receipt


def _providers(gate):
    try:
        from ravel.workflow.decision_gate import providers
        active=[p for p in providers(gate) if p.get('active')]
    except (ImportError, ValueError) as exc:
        raise ValueError(f'{gate}: decision_gate provider unavailable') from exc
    if not active: raise ValueError(f'{gate}: no active decision provider')
    return active


def preflight_populations(t, base):
    """Evaluator admission: schema, all-role identity matrix and pool checks."""
    if not t['dataset']['synthetic']: raise ValueError('real-data custody requires enforced evaluator read-path isolation')
    if t['dataset'].get('truth_pin'):
        path=ml._path(t['dataset']['truth_pin'],base).resolve()
        if 'inputs' in path.parts: raise ValueError('truth_pin must be outside producer-readable inputs/')
    entries=[(t['dataset']['pins'][0], 'crossfit_population', 'nominal')]
    if t['injection']: entries.append((t['injection']['signal_pool'],'injection_evaluation_pool','signal'))
    if t['checks']['reference']: entries.append((t['checks']['reference'],'background_reference','reference'))
    entries.extend((p,'null_toy',f'null-{i}') for i,p in enumerate((t['null_calibration'] or {}).get('datasets',[])))
    entries.extend((a['training_pool'],'oracle_training_pool',f"oracle:{a['id']}") for a in t['baselines']+t['models'] if 'training_pool' in a)
    loaded={}; identities={}; claims=[]
    for pin,role,name in entries:
        ident=ml_exposure.identity(pin,base)
        if any(ml_exposure.overlaps(ident,other) for other,_ in claims):
            raise ValueError(f'{role}: population overlap before exposure')
        data=load_events(pin,base,len(t['dataset']['features']),allow_sampling_weights=role=='injection_evaluation_pool')
        for window in [t['supervision']['regions']]+t['supervision'].get('additional_windows',[]):
            region_ids(data['region'],{**t['supervision'],'regions':window})
        if role in ('background_reference','null_toy') and t['dataset']['truth_column']:
            if np.any(_truth(t['dataset']['truth_pin'],base,data['event_id'])): raise ValueError(f'{role} must be background-only')
        if role=='injection_evaluation_pool':
            if not np.all(_truth(t['dataset']['truth_pin'],base,data['event_id'])==1): raise ValueError('injection pool must be pure signal')
            pool,_=_signal_partition(data,t['injection']['partition'])
            if max(t['injection']['strengths'])>len(pool['x']): raise ValueError('injection count exceeds independent pool before exposure')
            sr=t['supervision']['regions']['signal']
            if np.mean((data['region']>=sr[0])&(data['region']<sr[1]))<t['injection'].get('localization_min',.95):
                raise ValueError('injection pool not localized before exposure')
        if role=='oracle_training_pool':
            labels=_truth(t['dataset']['truth_pin'],base,data['event_id'])
            for salt in t['splits']['fold_salts']:
                folds=fold_map(data['group_id'],t['splits']['k'],salt)
                for fold in range(t['splits']['k']):
                    if len(np.unique(labels[folds==fold]))<2: raise ValueError('oracle pool fold lacks both classes before exposure')
        loaded[name]=data; identities[name]=ident; claims.append((ident,role))
    contexts=['nominal']+[f'injection-{n}-{i}' for n in (t['injection'] or {}).get('strengths',[]) for i in range(t['injection']['samplings'])]
    schedule={p['sha256']:[] for p,_ in claims}
    def fold_contexts(context):
        result=[]
        for w in range(size_study(t)['windows']):
            c=context if size_study(t)['windows']==1 else f'{context}-window-{w}'
            for salt in t['splits']['fold_salts']:
                scoped=salt if c=='nominal' else f'{salt}:{c}'
                result.extend(f'{c}:{scoped}:{f}' for f in range(t['splits']['k']))
        return result
    schedule[identities['nominal']['sha256']]=[c for ctx in contexts for c in fold_contexts(ctx)]
    for pin,role,name in entries:
        key=identities[name]['sha256']
        if role=='null_toy': schedule[key]=fold_contexts(name)
        if role=='background_reference': schedule[key]=contexts+[name for _,role,name in entries if role=='null_toy']
        if role=='injection_evaluation_pool': schedule[key]=contexts[1:]
        if role=='oracle_training_pool': schedule[key]=['training']
    actual=np.bincount(region_ids(loaded['nominal']['region'],t['supervision']),minlength=3).tolist()
    if t['statistics']['region_counts']!=actual: raise ValueError(f'region_counts differ: actual {actual}')
    def campaigns():
        yield 'nominal',loaded['nominal']
        yield from ((name,d) for name,d in loaded.items() if name.startswith('null-'))
        if t['injection']:
            pool,_=_signal_partition(loaded['signal'],t['injection']['partition'])
            for strength in t['injection']['strengths']:
                for sampling in range(t['injection']['samplings']):
                    context=f'injection-{strength}-{sampling}'
                    draw=_signal_draw(pool,strength,np.random.default_rng(int(ml.digest(context)[:8],16)))
                    draw['weight']=np.full(len(draw['weight']),loaded['nominal']['weight'][0])
                    yield context,_concatenate(loaded['nominal'],draw)
    windows=[t['supervision']['regions']]+t['supervision'].get('additional_windows',[])
    for context,data in campaigns():
        for wi,window in enumerate(windows):
            local={**t,'supervision':{**t['supervision'],'regions':window}}
            ctx=context if len(windows)==1 else f'{context}-window-{wi}'
            for salt in t['splits']['fold_salts']:
                folds=fold_map(data['group_id'],t['splits']['k'],salt if ctx=='nominal' else f'{salt}:{ctx}')
                _actual_sizing(local,data,folds,region_ids(data['region'],local['supervision']))
                for arm in t['baselines']+t['models']:
                    if 'training_pool' not in arm: continue
                    source=loaded[f"oracle:{arm['id']}"]
                    labels=_truth(t['dataset']['truth_pin'],base,source['event_id'])
                    oracle_folds=fold_map(source['group_id'],t['splits']['k'],salt if ctx=='nominal' else f'{salt}:{ctx}')
                    for fold in range(t['splits']['k']):
                        if len(np.unique(labels[oracle_folds==fold]))<2:
                            raise ValueError(f'oracle pool {ctx} fold lacks both classes before exposure')
    return loaded,identities,claims,schedule


def run(t, base, output_dir, *, rundir=None):
    gate_root=Path(rundir) if rundir is not None else Path(base)
    sizing=size_study(t)
    if sizing['refusal_reasons']==['spend_above_ceiling decision required']:
        _gate(gate_root,'spend_above_ceiling',ml.digest(t),input_pins(t))
        raise ValueError('spend_above_ceiling approved: amend and freeze the authorized ceiling before launch')
    validate(t); base=Path(base)
    if t['null_calibration'] and t['null_calibration']['unblind']: _providers('unblind')
    if t['calibration']['derive_detector_correction']: _providers('bespoke_calibration')
    inputs(t,base)
    authoritative_ceiling(t,gate_root)
    plan=ml.eb.check_plan(json.loads(ml._bytes(t['placement']['backend_plan'],base)))
    output=Path(output_dir).absolute()/'ml'; spec_digest=ml.digest(t); gates=[]
    if output.exists(): raise ValueError('output directory already exists; use sealed replay')
    if any(p.is_symlink() for p in (output,*output.parents,base/'ml-exposure')):
        raise ValueError('output and exposure paths must not traverse symlinks')
    preflight=size_study(t)
    print(json.dumps({'ml_preflight':preflight},sort_keys=True),flush=True)
    if t['calibration']['derive_detector_correction']:
        gates.append(_gate(gate_root,'bespoke_calibration',spec_digest,input_pins(t)))
        raise ValueError('bespoke_calibration confirmed: derive and pin correction in a separate calibrated operation')
    loaded,identities,claims,schedule=preflight_populations(t,base)
    with ml.eb.capacity(plan,f'{base}:ml-crossfit',nested=True):
        state=base/'ml-exposure'; state.mkdir(exist_ok=True)
        exposure_path=state/(identities['nominal']['sha256']+'.crossfit.json')
        ledger={'spec_sha256':spec_digest,'state':'reserved','test_reads':0,'exposures':[]}
        try: ml._write_new(exposure_path,ledger)
        except FileExistsError as exc:
            prior=json.loads(exposure_path.read_text())
            if prior.get('state') not in ('failed','reserved') or type(prior.get('test_reads')) is not int or prior.get('test_reads')!=0 :
                raise ValueError('crossfit test population already spent or unresolved') from exc
            ledger['prior_failure']=prior; atomic_json(exposure_path,ledger)
        # One study owns each withheld population across directories and rounds.
        study=ml_exposure.Study(spec_digest)
        population=t['dataset']['pins'][0]['sha256']
        study.claim_all(claims,schedule=schedule)
        ledger['exposure_ledger']=study.provenance()
        atomic_json(exposure_path,ledger)
        def read_reference(context, selection):
            if t['checks']['reference']: study.read(t['checks']['reference']['sha256'],context,selection)
        def frozen_selection(path, exposures):
            ml._write_new(path,{'spec_sha256':spec_digest,'selection':[e['freeze'] for e in exposures]})
            return ml.pin(path)
        output.mkdir(parents=True,exist_ok=False)
        started=time.monotonic(); cpu=time.process_time()
        def deadline():
            if time.monotonic()-started>t['budget']['ceiling_seconds']: raise ValueError('study wall ceiling exhausted')
        def spend(row):
            deadline()
            key=(row['context'],row['salt'],row['fold'])
            if any((r['context'],r['salt'],r['fold'])==key for r in ledger['exposures']):
                raise ValueError('fold exposure already spent')
            name=row['context'].split('-window-')[0]
            source=identities[name]['sha256'] if name.startswith('null-') else population
            study.read(source,f"{row['context']}:{row['salt']}:{row['fold']}",row['freeze'])
            ledger['exposures'].append(row); ledger['test_reads']+=1
            atomic_json(exposure_path,ledger)
        spend.spec_digest=spec_digest
        try:
            oracle_freeze=output/'oracle-selection.json'
            ml._write_new(oracle_freeze,{'spec_sha256':spec_digest,'selection':[]})
            for ident,role in claims:
                if role=='oracle_training_pool': study.read(ident['sha256'],'training',ml.pin(oracle_freeze))
            environment={'python':ml.sys.version,'numpy':np.__version__,
                         'scipy':ml.importlib.metadata.version('scipy'),
                         'code':{'executor':ml.pin(__file__),'training':ml.pin(ml.__file__),'backend':ml.pin(ml_backends.__file__),'exposure':ml.pin(ml_exposure.__file__),'custody':ml.pin(ml_custody.__file__)}}
            ml._write_new(output/'environment.json',environment)
            ml._write_new(output/'spec-freeze.json',{'spec_sha256':spec_digest,'task':t,'preflight':preflight})
            data=load_events(t['dataset']['pins'][0],base,len(t['dataset']['features']))
            region_ids(data['region'],t['supervision'])
            equal=t['supervision']['kind']=='mixture' and len(set(t['supervision']['fractions']))==1
            # Truth-information arms are explicit ceilings with a separate input policy.
            needs_truth=any(a['kind']=='idealized_anomaly' or (a['kind']=='supervised_oracle' and 'training_pool' not in a) for a in t['baselines']+t['models']) or t['supervision']['kind']=='truth'
            truth=_truth(t['dataset']['truth_pin'],base,data['event_id']) if needs_truth else None
            fitted=_crossfit(t,data,output/'nominal','nominal',spend,deadline,truth,base)
            all_models=fitted['models'][:]; all_maps=fitted['fold_maps'][:]; all_refs=fitted['rank_references'][:]
            reference=None
            if t['checks']['reference']:
                reference=load_events(t['checks']['reference'],base,len(t['dataset']['features']))
                if set(data['group_id'])&set(reference['group_id']): raise ValueError('reference groups overlap study')
                if t['dataset']['synthetic'] and np.any(_truth(t['dataset']['truth_pin'],base,reference['event_id'])):
                    raise ValueError('spurious signal reference must be background-only')
                read_reference('nominal',frozen_selection(output/'nominal-selection.json',fitted['exposures']))
            checks=sculpting_checks(t,data,fitted,reference)
            checks.update(additional_checks(t,data,fitted,_truth(t['dataset']['truth_pin'],base,data['event_id']) if t['dataset']['truth_column'] else None))
            injections=[]; null_rows=[]; injection_statistics=[]; toy_diagnostics={}
            if t['injection']:
                inj=t['injection']; pool=load_events(inj['signal_pool'],base,len(t['dataset']['features']),allow_sampling_weights=True)
                if set(pool['group_id'])&set(data['group_id']): raise ValueError('signal pool overlaps study')
                for model in fitted['models']:
                    if model.get('training_pool_scope') and set(pool['group_id'])&set(model['training_pool_scope']['group_ids']):
                        raise ValueError('signal evaluation pool overlaps oracle training pool')
                if not np.all(_truth(t['dataset']['truth_pin'],base,pool['event_id'])==1): raise ValueError('injection pool must be pure signal')
                injected,evaluation=_signal_partition(pool,inj['partition'])
                sr=t['supervision']['regions']['signal']
                localized=float(np.mean((pool['region']>=sr[0])&(pool['region']<sr[1])))
                checks['check:ml-benchmark-localization']=_check('pass' if localized>=inj.get('localization_min',.95) else 'fail',fraction_in_signal_region=localized,
                                                               criterion='Declared localization fraction in the frozen reconstructed window',minimum=inj.get('localization_min',.95),source='Operational policy parameter; not a physics constant')
                if localized<inj.get('localization_min',.95): raise ValueError('injection benchmark not localized in reconstructed region')
                for strength in inj['strengths']:
                    for sampling in range(inj['samplings']):
                        context=f'injection-{strength}-{sampling}'
                        draw=_signal_draw(injected,strength,np.random.default_rng(int(ml.digest(context)[:8],16)))
                        # Sampling already incorporates signal weights; do not weight twice in fit.
                        draw['weight']=np.full(len(draw['weight']),data['weight'][0])
                        sample=_concatenate(data,draw)
                        labels=np.r_[truth,np.ones(strength)] if truth is not None else None
                        campaign=_crossfit(t,sample,output/context,context,spend,deadline,labels,base)
                        all_models.extend(campaign['models']); all_maps.extend(campaign['fold_maps']); all_refs.extend(campaign['rank_references'])
                        # Evaluation access is reserved after every checkpoint in this model set freezes.
                        evaluation_record={'context':context,'evaluation_reads':1,'pool':inj['signal_pool'],
                                           'evaluation_groups':sorted(set(evaluation['group_id'])),
                                           'spec_sha256':spec_digest,'selection':[e['freeze'] for e in campaign['exposures']]}
                        ml._write_new(output/f'{context}-evaluation.json',evaluation_record)
                        selection=ml.pin(output/f'{context}-evaluation.json')
                        study.read(inj['signal_pool']['sha256'],context,selection)
                        evaluated=_evaluate_external(t,campaign,evaluation)
                        # An independent background reference is required for S/sqrt(B); read it once per model set.
                        external_background=None
                        if reference is not None:
                            read_reference(context,selection)
                            external_background=_evaluate_external(t,campaign,reference)
                        metrics=injection_metrics(t,campaign,evaluation,reference)
                        injections.append({'strength':strength,'sampling':sampling,'context':context,
                                           'injection_groups':draw['group_id'].tolist(),'evaluation_groups':evaluation['group_id'].tolist(),
                                           'evaluation_reads':1,'evaluation_effective_n':effective_n(evaluation),
                                           'draw_rule':'Sequential weighted draw without replacement; sampled events have unit relative training weight',
                                           'metrics':metrics,
                                           'statistic':None})
                        # Keep frozen inference inputs on disk, not live model sets or an early statistic.
                        stat_pin=ml_custody.put({'region':sample['region'],'scores':np.array([r['scores'] for r in campaign['scores']]),
                                 'kinds':np.array([r['kind'] for r in campaign['scores']])},arrays=True)
                        injection_statistics.append({'pin':stat_pin,'supervisions':[r['supervision'] for r in campaign['scores']]})
                checks['check:ml-injection-closure']=_check('unresolved',reason='Disjoint retraining executed; power/coverage needs declared ensemble acceptance',
                                                          model_sets=len(injections))
            else:
                checks['check:ml-benchmark-localization']=_check('unresolved',reason='No supplied signal pool')
                checks['check:ml-injection-closure']=_check('unresolved',reason='No injection campaign')
            checks['check:ml-evaluation-sizing']=evaluation_sizing(injections)
            if t['null_calibration']:
                null=t['null_calibration']; known=set(data['group_id'])
                for index,p in enumerate(null['datasets']):
                    context=f'null-{index}'
                    try:
                        toy=load_events(p,base,len(t['dataset']['features']))
                        if known&set(toy['group_id']): raise ValueError('null toy groups not independent')
                        known.update(toy['group_id'])
                        evaluator_toy_truth=_truth(t['dataset']['truth_pin'],base,toy['event_id']) if t['dataset']['truth_column'] else None
                        if evaluator_toy_truth is not None and np.any(evaluator_toy_truth):
                            raise ValueError('declared null toy contains evaluator signal')
                        toy_truth=evaluator_toy_truth if needs_truth else None
                        campaign=_crossfit(t,toy,output/context,context,spend,deadline,toy_truth,base)
                        if reference is not None:
                            read_reference(context,frozen_selection(output/context/'selection.json',campaign['exposures']))
                        all_models.extend(campaign['models']); all_maps.extend(campaign['fold_maps']); all_refs.extend(campaign['rank_references'])
                        toy_checks=sculpting_checks(t,toy,campaign,reference)
                        toy_diagnostics[index]=toy_checks
                        ml._write_new(output/context/'checks.json',toy_checks)
                        if any(c['verdict']=='fail' for c in toy_checks.values()):
                            raise ValueError('whole-procedure null control failed')
                        statistic=_max_statistic(t,toy,campaign)
                        null_rows.append({'toy':index,'statistic':statistic,'state':'complete','pin':p})
                    except (ValueError,np.linalg.LinAlgError) as exc:
                        null_rows.append({'toy':index,'statistic':None,'state':'failed_extreme','error':str(exc),'pin':p,
                                          'training_records':[ml.pin(path) for path in sorted((output/context).rglob('*.history.json'))]})
                        atomic_json(output/'null-progress.json',{'toys':null_rows})
                    deadline()
                checks['check:ml-null-execution']=_check('pass' if all(r['state']=='complete' for r in null_rows) else 'unresolved',
                    toys=len(null_rows),failed=sum(r['state']!='complete' for r in null_rows),resolution=1/(len(null_rows)+1),
                    scope='Whole supplied-null procedure; supplied toy-law fidelity remains a premise')
            checks['check:ml-null-calibration']=_check('unresolved',reason='Pinned toy-law provenance and exchangeability acceptance required',
                toys=len(null_rows), minimum_toys=math.ceil(1/t['checks']['alpha']))
            checks=calibrate_spurious(checks,[toy_diagnostics.get(i) if row['state']=='complete' else None for i,row in enumerate(null_rows)],t['checks']['alpha'])
            # No nominal SR statistic has been calculated anywhere above this line.
            medians=injection_medians(injections)
            checks['check:ml-test-once']=_check('pass',exposures=len(ledger['exposures']))
            ml._write_new(output/'validation-before-unblind.json',checks)
            observed=None; pvalue=None
            if t['null_calibration'] and t['null_calibration']['unblind']:
                blockers=[k for k,v in checks.items() if v['verdict'] in ('fail','unresolved')]
                # The read-only provider contract supplies no authenticated record writer.
                gates.append({'gate':'unblind','verdict':'blocked','reasons':blockers or ['Authenticated decision-gate record required']})
            # Evaluator-only truth metrics: never added to a weak trainer's input dictionaries.
            evaluator_truth=_truth(t['dataset']['truth_pin'],base,data['event_id']) if t['dataset']['truth_column'] else None
            arms=[]
            # Region-label Brier/ECE over signal-region scores measure the search itself: blinded until unblind.
            blinded=t['supervision']['kind']!='truth' and observed is None
            for row in fitted['scores']:
                labels=evaluator_truth if t['supervision']['kind']=='truth' else (region_ids(data['region'],row['supervision'])==0).astype(float)
                m=({'ece':None,'brier':None} if blinded else
                   ml.metrics(labels,row['probabilities'],data['weight'],.5,10)[0])
                truth_auc=None
                if observed is not None and t['dataset']['synthetic'] and evaluator_truth is not None and len(np.unique(evaluator_truth))==2:
                    truth_auc=ml.metrics(evaluator_truth,row['scores'],data['weight'],.5,10)[0]['roc_auc']
                arms.append({'id':row['arm'],'kind':row['kind'],'seed':row['seed'],'salt':row['salt'],
                             'declared_salt':row['declared_salt'],'window':row.get('window',0),
                             'calibration':{'target':'truth label' if t['supervision']['kind']=='truth' else 'region label','ece':m['ece'],'brier':m['brier'],
                                             'state':'blinded' if blinded else 'unblinded' if t['supervision']['kind']!='truth' else 'truth_labels'},
                             'truth_auc_evaluator_only':truth_auc,
                             'information_role':'labelled ceiling; unavailable to a real search' if row['kind']=='supervised_oracle' or (t['supervision']['kind']=='truth' and row['kind'] not in ('inclusive','inclusive_bump_hunt'))
                                 else 'synthetic truth-reference' if row['kind']=='idealized_anomaly' else 'available method',
                             'independent_events':len(set(data['group_id']))})
            summary={}
            for arm in t['baselines']+t['models']:
                for window in range(size_study(t)['windows']):
                    subset=[r for r in arms if r['id']==arm['id'] and r['window']==window]
                    for metric in ('ece','brier'):
                        seed_values=[r['calibration'][metric] for r in subset if r['declared_salt']==t['splits']['salt']]
                        if blinded:
                            summary.setdefault(metric,{}).setdefault(arm['id'],{})[str(window)]={'mean':None,
                                'initialization_seed_spread':None,'fold_salt_spread':None,'state':'blinded'}
                            continue
                        salt_means=[np.mean([r['calibration'][metric] for r in subset if r['declared_salt']==salt]) for salt in t['splits']['fold_salts']]
                        summary.setdefault(metric,{}).setdefault(arm['id'],{})[str(window)]={'mean':float(np.mean(seed_values)),
                            'initialization_seed_spread':float(np.std(seed_values,ddof=1)),
                            'fold_salt_spread':float(np.std(salt_means,ddof=1)) if len(salt_means)>1 else None}
            checks['check:ml-seed-spread']=_check('diagnostic' if t['supervision']['kind']=='truth' else 'unresolved',
                                                 scope='Seed and fold-salt spreads reported separately; no confidence interpretation')
            disposition=_disposition(t,checks,equal)
            checks['check:ml-claim-scope']=_check('unresolved',disposition=disposition,physics_validated=False,reason='Diagnostic only; research-protocol claim acceptance required')
            score_pin=ml_custody.put({'event_id':data['event_id'],'group_id':data['group_id'],
                     'scores':np.array([r['scores'] for r in fitted['scores']]),
                     'folds':np.array([r['folds'] for r in fitted['scores']])},arrays=True)
            if equal:
                injections=[]; medians=[]; summary={}
                for a in arms: a['truth_auc_evaluator_only']=None; a['calibration'].update(ece=None,brier=None)
            receipt={'schema_version':2,'kind':'ml-crossfit-receipt','claim_kind':t.get('claim_kind','diagnostic'),'spec_sha256':spec_digest,'task':t,'input_base':str(base.resolve()),
                     'models':all_models,'arms':arms,'score_artifact':score_pin,
                     'environment_sha256':ml.digest(environment),'backend_plan':t['placement']['backend_plan'],'device':'cpu','summary':summary,'fold_maps':all_maps,
                     'fold_map_digest':ml.digest(all_maps),'rank_references':[],
                     'crossfit_audit':{**audit_models(all_models),'event_scores_per_arm_seed_salt_window':1},
                     'effective_events':{'rows':len(data['x']),'groups':len(set(data['group_id'])),
                                         'weight_effective_n':effective_n(data)},
                     'exposures':ledger['exposures'],'injections':injections,'injection_medians':medians,'null_toys':null_rows,
                     'frozen_injection_inference':injection_statistics,
                     'checks':checks,'preflight':preflight,'gates':gates,'observed_statistic':observed,
                     'calibrated_p':pvalue,'disposition':disposition,'performance':None if equal else injections,
                     'cost_actuals':{'wall_seconds':time.monotonic()-started,'cpu_seconds':time.process_time()-cpu,
                                     'completed_trainings':len(all_models),
                                     'failed_toy_completed_trainings':sum(len(r.get('training_records',[])) for r in null_rows)},
                     'exposure_ledger':study.provenance(),
                     'scope':'Supplied-population method diagnostics; finite checks cannot exclude a signal-region-only background shift.'}
            try:
                validate_receipt(receipt,t,output,pending=True)
            except ValueError as exc:
                ml._write_new(output/'receipt-unverified.json',{'validation':'refused','reason':str(exc),'receipt':receipt})
                raise
            ml._write_new(output/'receipt.json',receipt)
            report=['# Cross-fitted ML study','',f'Disposition: {disposition}.', '', receipt['scope'],'',
                    'All null, failed-toy, zero-acceptance and insensitive outcomes remain in receipt.json.',
                    'ECE and Brier calibrate region labels and stay blinded until the unblind gate. Oracle rows are labelled ceilings, unavailable to a real search.',
                    'Seed spread and fold-salt spread measure training variation; repeated trainings add no independent data.',
                    f'Observed statistic: {observed}. Calibrated p: {pvalue}.', '', '## Checks','']
            report.extend(f"- {key}: {value['verdict']}" for key,value in checks.items())
            (output/'RESULT.md').write_text('\n'.join(report)+'\n')
            result={'status':'passed','physics_validated':False,'receipt':ml.pin(output/'receipt.json'),
                    'summary':summary,'disposition':disposition,'scope':receipt['scope'],'figures':[]}
            ml._write_new(output/'result.json',result)
            final_state='complete_blinded' if observed is None else 'complete'
            ledger.update(state=final_state,receipt=ml.pin(output/'receipt.json')); atomic_json(exposure_path,ledger)
            study.close(final_state,ml.pin(output/'receipt.json'))
            return result
        except BaseException as exc:
            ledger.update(state='failed',error=str(exc)); atomic_json(exposure_path,ledger)
            study.close('failed')
            raise


def resume_frozen(t,base,output_dir):
    """Replay completed freezes after interruption; never refit or repeat a read.

    Unfinished folds remain unresolved. Process-local sealed checkpoints must
    still exist; restart recovery requires durable evaluator custody.
    """
    base=Path(base); output=Path(output_dir)/'ml'
    frozen=json.loads((output/'spec-freeze.json').read_text())
    if frozen['spec_sha256']!=ml.digest(t) or frozen['task']!=t: raise ValueError('resume specification changed')
    for pin in input_pins(t): ml._bytes(pin,base)
    environment=json.loads((output/'environment.json').read_text())
    for pin in environment['code'].values(): ml._bytes(pin,base)
    identity=ml_exposure.identity(t['dataset']['pins'][0],base)
    ledger=json.loads((base/'ml-exposure'/(identity['sha256']+'.crossfit.json')).read_text())
    if ledger['spec_sha256']!=ml.digest(t): raise ValueError('resume ledger specification changed')
    result=[]
    for exposure in ledger['exposures']:
        freeze=json.loads(ml._bytes(exposure['freeze'],base)); ctx=exposure['context'].split('-window-')[0]
        if ctx=='nominal': data=load_events(t['dataset']['pins'][0],base,len(t['dataset']['features']))
        elif ctx.startswith('null-'):
            data=load_events(t['null_calibration']['datasets'][int(ctx.split('-')[1])],base,len(t['dataset']['features']))
        else:
            _,strength,sampling=ctx.split('-'); data=load_events(t['dataset']['pins'][0],base,len(t['dataset']['features']))
            pool=load_events(t['injection']['signal_pool'],base,len(t['dataset']['features']),allow_sampling_weights=True)
            pool,_=_signal_partition(pool,t['injection']['partition'])
            draw=_signal_draw(pool,int(strength),np.random.default_rng(int(ml.digest(ctx)[:8],16)))
            draw['weight']=np.full(len(draw['weight']),data['weight'][0]); data=_concatenate(data,draw)
        windows=[t['supervision']['regions']]+t['supervision'].get('additional_windows',[])
        wi=int(exposure['context'].split('-window-')[1]) if '-window-' in exposure['context'] else 0
        sup={**t['supervision'],'regions':windows[wi]}; regions=region_ids(data['region'],sup)
        mask=fold_map(data['group_id'],t['splits']['k'],exposure['salt'])==exposure['fold']
        if 'histories' not in freeze: raise ValueError('legacy freeze lacks authenticated histories; resume refused')
        histories=[json.loads(ml._bytes(pin,base)) for pin in freeze['histories']]
        rows=[r for r in histories if r['checkpoint'] in freeze['models']]
        if len(rows)!=len(freeze['models']): raise ValueError('resume frozen checkpoint history incomplete')
        scores=[]
        for arm in t['baselines']+t['models']:
            for seed in t['seeds']:
                selected=[r for r in rows if r['arm']==arm['id'] and r['seed']==seed]; mapped=[]
                for row in sorted(selected,key=lambda r:r['rotation']):
                    with np.load(io.BytesIO(ml._bytes(row['checkpoint'],base)),allow_pickle=False) as z: model={k:z[k] for k in z.files}
                    transform=json.loads(ml._bytes(row['transform'],base))
                    prob=ml_backends.predict_selected(model,apply_transform(transform,data['x'][mask],regions[mask]))
                    mapped.append(_rank(prob,prob[regions[mask]==0]))
                average=np.mean(mapped,axis=0) if mapped else np.ones(mask.sum())
                scores.append(_rank(average,average[regions[mask]==0]) if mapped else average)
        context=f"{exposure['context']}:{exposure['salt']}:{exposure['fold']}"
        ml_exposure.record_replay(ledger['exposure_ledger'],ml.digest(t),context,exposure['freeze'])
        result.append({'context':context,'scores':ml_custody.put({'scores':np.array(scores),'event_id':data['event_id'][mask]},arrays=True),'class':'replay'})
    return {'kind':'ml-sealed-replay','spec_sha256':ml.digest(t),'test_reads':ledger['test_reads'],
            'exposures':result,'status':'partial' if ledger['state']=='failed' else 'complete',
            'claim':'No new claim; unfinished folds remain unresolved'}
