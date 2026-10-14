"""Generic synthetic study controls; no experiment inputs or native tools."""
import copy
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from ravel.physics import ml_training as ml
from ravel.physics import ml_crossfit as cf
from ravel.workflow import execution_backend as eb


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path/'state'))


def data(path, n=600, seed=13, drift=0., signal=False, prefix='data'):
    rng = np.random.default_rng(seed)
    mass = -np.log1p(-rng.uniform(size=n)*(1-np.exp(-.15*6)))/.15 if not signal else np.clip(rng.normal(3, .12, n), 2, 4)
    x = rng.normal(size=(n, 2)) + (3 if signal else 0)
    x[:, 0] += drift * mass
    np.savez(path, x=x, region=mass, weight=np.ones(n),
             event_id=np.array([f'{prefix}-{i}' for i in range(n)]),
             group_id=np.array([f'{prefix}-{i}' for i in range(n)]))
    private=path.parent/'evaluator-private'; private.mkdir(exist_ok=True)
    np.savez(private/(path.stem+'.truth.npz'),event_id=np.array([f'{prefix}-{i}' for i in range(n)]),truth=np.full(n,int(signal)))
    return ml.pin(path)


def fixture(tmp_path, **kwargs):
    p = data(tmp_path/'events.npz', **kwargs)
    d = {'pins': [p], 'features': ['f1', 'f2'], 'weights': 'weight', 'id_column': 'event_id',
         'truth_column': 'truth', 'synthetic': True}
    d['truth_pin']=ml.pin(tmp_path/'evaluator-private/events.truth.npz')
    d['manifest_sha256'] = ml.digest(d)
    s = {'method': 'kfold_crossfit', 'k': 3, 'group_column': 'group_id', 'salt': 'fixed',
         'fold_salts': ['fixed', 'variation'], 'test_withheld': True}
    s['split_sha256'] = ml.split_digest(s)
    t = {'objective': 'method_study', 'dataset': d, 'splits': s,
         'supervision': {'kind': 'weak_region', 'region_variable': 'region', 'derived_features': [],
                         'regions': {'signal': [2., 4.], 'sidebands': [[0., 2.], [4., 6.]]},
                         'sideband_weighting': 'equal'},
         'preprocessing': {'kind': 'standardize', 'scope': 'train_folds'},
         'inner_selection': {'initializations': 2, 'criterion': 'validation_loss'},
         'scoring': {'map': 'rank_on_reference', 'reference': 'signal_region_test_events',
                     'aggregate': 'mean_over_rotations', 'rerank': True, 'working_points': [.5]},
         'baselines': [{'id': 'inclusive', 'kind': 'inclusive'}],
         'models': [{'id': 'method', 'kind': 'weak', 'architecture': 'mlp', 'backend': 'numpy',
                     'config': {'widths': [4, 3], 'learning_rate': .1}}],
         'seeds': [1, 2, 3],
         'budget': {'epochs': 3, 'patience': 2, 'wall_seconds': 5, 'max_trials': 1,
                    'equal_across_arms': True, 'ceiling_seconds': 1000,
                    'unit_seconds': .001, 'unit_timing': {'rung': 'smoke', 'trainings': 1,
                                                       'wall_seconds': .001, 'cpu_seconds': .001}},
         'statistics': {'region_counts': [200, 200, 200], 'min_selected_per_fold': 2,
                        'max_relative_error': .5, 'claim': 'synthetic_diagnostic'},
         'checks': {'permutations': 19, 'alpha': .05, 'sideband_bins': [0., 1., 2., 4., 5., 6.],
                    'max_spurious_z': 4., 'reference': None},
         'fit': {'family': 'log_linear', 'bins': [0., 1., 2., 3., 4., 5., 6.]},
         'injection': None, 'null_calibration': None,
         'calibration': {'derive_detector_correction': False},
         'placement': {'device': 'cpu', 'backend_plan': None}}
    with np.load(p['path']) as z:
        t['statistics']['region_counts']=np.bincount(cf.region_ids(z['region'],t['supervision']),minlength=3).tolist()
    timing=tmp_path/'smoke-timing.json'
    timing.write_text(json.dumps(t['budget']['unit_timing']))
    t['budget']['unit_timing']['source']=ml.pin(timing)
    return bind_plan(t, tmp_path)


def bind_plan(t, path):
    with np.load(t['dataset']['pins'][0]['path']) as z:
        t['statistics']['region_counts']=np.bincount(cf.region_ids(z['region'],t['supervision']),minlength=3).tolist()
    t['budget']['unit_timing']=cf.measure_smoke(t,path/'smoke-timing.json')
    t['budget']['unit_seconds']=t['budget']['unit_timing']['wall_seconds']/t['budget']['unit_timing']['trainings']
    sources=t['dataset']['pins']+[a['training_pool'] for a in t['baselines']+t['models'] if 'training_pool' in a]+([t['injection']['signal_pool']] if t['injection'] else [])+((t['null_calibration'] or {}).get('datasets',[]))+([t['checks']['reference']] if t['checks']['reference'] else [])
    labels={}
    for pin in sources:
        p=Path(pin['path']); truth=p.parent/'evaluator-private'/(p.stem+'.truth.npz')
        if truth.exists():
            with np.load(truth) as z: labels.update(zip(z['event_id'].astype(str),z['truth'].tolist()))
    private=path/'evaluator-private'; private.mkdir(exist_ok=True)
    truth=private/'all-truth.npz'; np.savez(truth,event_id=np.array(list(labels)),truth=np.array(list(labels.values())))
    t['dataset']['truth_pin']=ml.pin(truth)
    t['dataset']['manifest_sha256']=ml.digest({k:v for k,v in t['dataset'].items() if k!='manifest_sha256'})
    pins = t['dataset']['pins'][:] + [t['budget']['unit_timing']['source']] + [a['training_pool'] for a in t['baselines']+t['models'] if 'training_pool' in a]
    pins += [t['dataset']['truth_pin']]
    if t['injection']: pins += [t['injection']['signal_pool']]
    if t['null_calibration']: pins += t['null_calibration']['datasets']
    if t['checks']['reference']: pins += [t['checks']['reference']]
    plan = eb.prepare({'schema_version': 1, 'backend': 'native', 'stage': 'ml-training',
                       'argv': [sys.executable, '-m', 'ravel.physics.science_worker', str(path)],
                       'inputs': pins, 'outputs': [{'name': 'result.json', 'destination': 'outputs/result.json', 'kind': 'file'}],
                       'resources': {'cpus': 1, 'memory_mib': 256, 'wall_seconds': 100000}})
    p = path/'backend.json'; p.write_text(json.dumps(plan))
    t['placement']['backend_plan'] = ml.pin(p)
    return t


def test_size_refuses_unsized_uncosted_and_small(tmp_path):
    t = fixture(tmp_path)
    r = ml.size_study(t)
    assert r['admissible'] and r['trainings'] == 3 * 2 * 2 * 3 * 2
    for key in ('unit_seconds', 'unit_timing'):
        broken = copy.deepcopy(t); broken['budget'].pop(key)
        assert not ml.size_study(broken)['admissible']
    t['statistics']['region_counts'] = [2, 2, 2]
    assert not ml.size_study(t)['admissible']
    with pytest.raises(ValueError, match='statistics'):
        ml.validate(t)


def test_crossfit_group_leak_audit():
    groups = ['a', 'a', 'b', 'c', 'd', 'e']
    folds = cf.fold_map(groups, 3, 'salt')
    assert folds[0] == folds[1]
    row = {'test_groups': ['a'], 'train_groups': ['b'], 'validation_groups': ['c'],
           'preprocessing_groups': ['b']}
    assert cf.audit_models([row])['passed']
    for key in ('train_groups', 'validation_groups', 'preprocessing_groups'):
        bad = copy.deepcopy(row); bad[key].append('a')
        assert not cf.audit_models([bad])['passed']


def test_weak_labels_and_derived_features_refused(tmp_path):
    t = fixture(tmp_path)
    t['supervision']['derived_features'] = ['f1']
    with pytest.raises(ValueError, match='label|feature|leak'):
        ml.validate(t)


def test_end_to_end_one_exposure_inner_selection_truth_isolation(tmp_path, monkeypatch):
    t = fixture(tmp_path)
    calls = []
    original = cf.fit_model
    def spy(arm, train, val, *args, **kwargs):
        assert set(train) == {'x', 'y', 'weight'}
        assert set(val) == {'x', 'y', 'weight'}
        calls.append(len(train['x']))
        return original(arm, train, val, *args, **kwargs)
    monkeypatch.setattr(cf, 'fit_model', spy)
    r = ml.run(t, tmp_path, tmp_path/'out')
    receipt = json.loads((tmp_path/'out/ml/receipt.json').read_text())
    assert r['physics_validated'] is False
    assert receipt['crossfit_audit']['passed']
    assert len(calls) == ml.size_study(t)['trainings']
    assert all(e['test_reads'] == 1 for e in receipt['exposures'])
    assert len(receipt['exposures']) == 6
    assert receipt['effective_events']['groups'] == 600
    assert all(len(m['history']) >= 1 for m in receipt['models'])
    assert receipt['observed_statistic'] is None
    assert receipt['disposition'] == 'limited'
    with pytest.raises(ValueError, match='spent'):
        ml.run(t, tmp_path, tmp_path/'retry')


def test_equal_mixtures_unidentifiable(tmp_path):
    t = fixture(tmp_path)
    t['supervision'].update(kind='mixture', fractions=[.1, .1])
    ml.run(t, tmp_path, tmp_path/'out')
    r = json.loads((tmp_path/'out/ml/receipt.json').read_text())
    assert r['disposition'] == 'unidentifiable'
    assert r['performance'] is None


def test_drift_is_flagged(tmp_path):
    t = fixture(tmp_path, drift=4.); t['checks']['permutations']=199
    ml.run(t, tmp_path, tmp_path/'out')
    r = json.loads((tmp_path/'out/ml/receipt.json').read_text())
    assert r['checks']['check:ml-sideband-separability']['verdict'] == 'fail'
    assert r['disposition'] == 'assumption_violated'


def test_unblind_and_bespoke_gate_fail_closed(tmp_path, monkeypatch):
    t = fixture(tmp_path)
    t['calibration']['derive_detector_correction'] = True
    monkeypatch.setattr(cf, 'load_events', lambda *a, **k: pytest.fail('read before gate'))
    with pytest.raises(ValueError, match='bespoke_calibration'):
        ml.run(t, tmp_path, tmp_path/'out')


def test_null_p_failed_toys_resolution():
    assert cf.calibrated_p(3., [1., 2., None, 4.]) == .6
    with pytest.raises(ValueError, match='resolution'):
        cf.calibrated_p(3., [1., 2.], claim_below=.01)


def test_train_only_transform_contamination():
    x = np.array([[0., 1.], [1., 2.], [10., 11.], [11., 12.]])
    regions = np.array([0, 0, 1, 1])
    spec = {'kind': 'region_quantile', 'scope': 'train_folds', 'features': [0, 1], 'pool_features': True}
    a = cf.fit_transform(x, regions, spec)
    np.testing.assert_array_equal(cf.apply_transform(a, x, regions), cf.apply_transform(a, x, regions))
    polluted = x.copy(); polluted[2:] += 100
    b = cf.fit_transform(polluted, regions, spec)
    assert ml.digest(a) != ml.digest(b)


def test_injection_and_whole_procedure_null_freeze_order(tmp_path, monkeypatch):
    t = fixture(tmp_path)
    t['splits']['fold_salts']=['fixed']; t['splits']['split_sha256']=ml.split_digest(t['splits'])
    t['inner_selection']['initializations']=1
    t['models'][0].update(architecture='quadratic_logistic', config={'learning_rate': .1})
    t['budget'].update(epochs=8,patience=3)
    pool=data(tmp_path/'signal.npz',n=300,seed=21,signal=True,prefix='signal')
    t['injection']={'signal_pool':pool,'partition':{'method':'group_hash','salt':'pool','injection_fraction':.6},
                    'strengths':[0,1,40,100],'samplings':3,'draw':'exact_count_by_weight','median_rule':'median_signal_efficiency'}
    t['null_calibration']={'toys':2,'scope':'whole_procedure','datasets':[
        data(tmp_path/f'toy{i}.npz',seed=71+i,prefix=f'toy{i}') for i in range(2)], 'claim_below':None,'unblind':False}
    bind_plan(t,tmp_path)
    # Zero-strength injections equal nominal data; their inference must also be blinded.
    monkeypatch.setattr(cf,'_gate',lambda *a: pytest.fail('no observed request'))
    ml.run(t,tmp_path,tmp_path/'out')
    r=json.loads((tmp_path/'out/ml/receipt.json').read_text())
    assert len(r['injections'])==12 and len(r['null_toys'])==2
    assert r['observed_statistic'] is None
    assert all(row['statistic'] is None for row in r['injections'])
    assert r['cost_actuals']['completed_trainings']==ml.size_study(t)['trainings']
    assert all(row['evaluation_reads']==1 for row in r['injections'])
    assert all(not set(row['injection_groups'])&set(row['evaluation_groups']) for row in r['injections'])
    assert all(row['state']=='complete' for row in r['null_toys'])
    # Large signal should beat a zero-signal model on this declared, well-separated fixture.
    def median(strength):
        return np.median([m['signal_efficiency'] for row in r['injections'] if row['strength']==strength
                          for m in row['metrics'] if m['arm']=='method'])
    assert median(100)>median(0)


def install_gate_provider(monkeypatch):
    import types
    module=types.ModuleType('ravel.workflow.decision_gate'); calls=[]
    module.providers=lambda gate:[{'id':'local-test-provider','active':True}]
    def check(root,gate,action): calls.append(gate); return []
    module.check=check
    monkeypatch.setitem(sys.modules,'ravel.workflow.decision_gate',module)
    return calls


def test_failed_blocking_check_prevents_unblind_request(tmp_path, monkeypatch):
    t=fixture(tmp_path); t['inner_selection']['initializations']=1
    t['null_calibration']={'toys':1,'scope':'whole_procedure','datasets':[
        data(tmp_path/'null.npz',seed=50,prefix='null')], 'claim_below':None,'unblind':True}
    bind_plan(t,tmp_path); calls=install_gate_provider(monkeypatch)
    ml.run(t,tmp_path,tmp_path/'out')
    receipt=json.loads((tmp_path/'out/ml/receipt.json').read_text())
    assert receipt['observed_statistic'] is None and receipt['calibrated_p'] is None
    assert receipt['gates'][0]['verdict']=='blocked' and calls==[]
    ml.validate_receipt(receipt,t,tmp_path/'out/ml')


def test_receipt_detects_missing_models(tmp_path):
    t=fixture(tmp_path); ml.run(t,tmp_path,tmp_path/'out')
    r=json.loads((tmp_path/'out/ml/receipt.json').read_text()); r['models'].pop()
    with pytest.raises(ValueError,match='population|model'):
        ml.validate_receipt(r,t,tmp_path/'out/ml')


def test_projection_ceiling_routes_to_gate_before_data(tmp_path, monkeypatch):
    t=fixture(tmp_path); t['budget']['ceiling_seconds']=.001
    seen=[]
    def gate(base,name,digest,pins):
        seen.append(name); raise ValueError('spend_above_ceiling pending')
    monkeypatch.setattr(cf,'_gate',gate)
    monkeypatch.setattr(cf,'load_events',lambda *a: pytest.fail('data before ceiling approval'))
    with pytest.raises(ValueError,match='spend_above_ceiling'):
        ml.run(t,tmp_path,tmp_path/'out')
    assert seen==['spend_above_ceiling']


def test_evaluation_uses_one_test_fold_not_average_of_folds():
    t={'splits':{'k':3},'supervision':{'regions':{'signal':[2,4],'sidebands':[[0,2],[4,6]]}}}
    d={'region':np.array([1.,3.,5.]),'group_id':np.array(['a','b','c']),'x':np.ones((3,1))}
    fitted={'ensembles':[{'arm':'inclusive','seed':1,'salt':'s','fold':f,'ensemble':[],
                          'test_groups':{'training'},'kind':'inclusive'} for f in range(3)]}
    assert len(cf._evaluate_external(t,fitted,d))==1
    d['group_id'][0]='training'
    # NumPy fixed-width strings truncate; use an explicit full string array.
    d['group_id']=np.array(['training','b','c'])
    with pytest.raises(ValueError,match='overlap'):
        cf._evaluate_external(t,fitted,d)


def proxy_data(path, seed, prefix, proxy=True, sr_only=False):
    p=data(path,n=1200,seed=seed,prefix=prefix)
    with np.load(path) as z: arrays={k:z[k] for k in z.files}
    if proxy:
        m=arrays['region']
        arrays['x'][:,0] += (np.abs(m-3)<1)*3 if sr_only else (m-3)**2/2
    np.savez(path,**arrays)
    return ml.pin(path)


def test_quadratic_proxy_and_reference_mismatch(tmp_path):
    t=fixture(tmp_path); t['splits']['fold_salts']=['fixed']; t['splits']['split_sha256']=ml.split_digest(t['splits'])
    t['models'][0].update(architecture='logistic',config={'learning_rate':.3})
    t['budget'].update(epochs=30,patience=10); t['inner_selection']['initializations']=1
    t['dataset']['pins']=[proxy_data(tmp_path/'proxy.npz',83,'proxy')]
    t['dataset']['manifest_sha256']=ml.digest({k:v for k,v in t['dataset'].items() if k!='manifest_sha256'})
    t['checks']['reference']=proxy_data(tmp_path/'reference.npz',87,'reference')
    bind_plan(t,tmp_path); ml.run(t,tmp_path,tmp_path/'out')
    r=json.loads((tmp_path/'out/ml/receipt.json').read_text())
    assert r['checks']['check:ml-spurious-signal']['verdict']=='fail'
    assert r['disposition']=='assumption_violated'
    mismatch=tmp_path/'mismatch'; mismatch.mkdir()
    # A second study needs its own population: the first study's events are spent.
    t['dataset']['pins']=[proxy_data(mismatch/'proxy.npz',84,'proxy-b')]
    t['dataset']['manifest_sha256']=ml.digest({k:v for k,v in t['dataset'].items() if k!='manifest_sha256'})
    t['checks']['reference']=proxy_data(mismatch/'reference.npz',89,'mismatch-reference',proxy=False)
    bind_plan(t,mismatch); ml.run(t,mismatch,mismatch/'out')
    r=json.loads((mismatch/'out/ml/receipt.json').read_text())
    assert r['checks']['check:ml-reference-fidelity']['verdict']=='fail'


def test_sr_only_shift_without_reference_cannot_be_supported(tmp_path):
    t=fixture(tmp_path)
    t['dataset']['pins']=[proxy_data(tmp_path/'sr-shift.npz',94,'shift',sr_only=True)]
    t['dataset']['manifest_sha256']=ml.digest({k:v for k,v in t['dataset'].items() if k!='manifest_sha256'})
    bind_plan(t,tmp_path); ml.run(t,tmp_path,tmp_path/'out')
    r=json.loads((tmp_path/'out/ml/receipt.json').read_text())
    assert r['disposition'] in ('limited','assumption_violated')


def test_merge_fragments_have_generic_schema_and_public_locators():
    root=Path(ml.__file__).parents[1]/'data/ml'
    traps=json.loads((root/'ml-traps.json').read_text())['premises']
    assert len(traps)==19 and len({r['id'] for r in traps})==19
    assert all(r['license']=='Apache-2.0' and r['obligations'] for r in traps)
    assert all(c['verification']=='bibliographic_locator_only' for r in traps for c in r['citation'])
    roles=json.loads((root/'role-cards.json').read_text())['roles']
    assert {r['id'] for r in roles}=={'ml-trainer','ml-reviewer'}


def test_whole_procedure_null_rate_independent_ensembles(tmp_path):
    """Preregistered seeds; 12 independent experiments, 19 toys each.

    A one-sided exact-binomial upper test has false-fail probability <= .001.
    This small software fixture can detect gross anti-conservatism; it cannot
    establish precise nominal coverage or validate an experimental null law.
    """
    import shutil
    from scipy.stats import binom
    t=fixture(tmp_path)
    t['models'][0].update(architecture='logistic',config={'learning_rate':.1})
    t['budget'].update(epochs=1,patience=1)
    t['inner_selection']['initializations']=1
    t['splits']['fold_salts']=['fixed']; t['splits']['split_sha256']=ml.split_digest(t['splits'])
    trials=12; toys=19; rejected=0
    for experiment in range(trials):
        stats=[]
        for draw in range(toys+1):
            path=tmp_path/'ensemble.npz'
            p=data(path,n=300,seed=91000+experiment*100+draw,prefix=f'e{experiment}-d{draw}')
            events=cf.load_events(p,tmp_path,2)
            out=tmp_path/'ensemble'
            fitted=cf._crossfit(t,events,out,f'synthetic-{experiment}-{draw}',lambda _:None,lambda:None)
            stats.append(cf._max_statistic(t,events,fitted))
            shutil.rmtree(out)
        rejected += cf.calibrated_p(stats[0],stats[1:])<=.05
    assert rejected <= int(binom.ppf(.999,trials,.05)), f'{rejected}/{trials}; fixed ensemble retained in seed formula'


def test_three_window_scan_counts_exposures_and_trials(tmp_path):
    t=fixture(tmp_path)
    t['supervision']['additional_windows']=[{'signal':[1.,2.],'sidebands':[[0.,1.],[2.,6.]]},
                                          {'signal':[4.,5.],'sidebands':[[0.,4.],[5.,6.]]}]
    t['splits']['k']=5
    t['splits']['fold_salts']=['fixed']; t['splits']['split_sha256']=ml.split_digest(t['splits'])
    t['inner_selection']['initializations']=2
    t['checks']['sideband_bins']=[0.,1.,2.,3.,4.,5.,6.]
    bind_plan(t,tmp_path); ml.run(t,tmp_path,tmp_path/'out')
    r=json.loads((tmp_path/'out/ml/receipt.json').read_text())
    assert r['preflight']['windows']==3
    assert len(r['models'])==3*5*4*2*3
    assert len(r['exposures'])==15 and r['checks']['check:ml-trials-accounting']['windows']==3
    assert set(r['summary']['ece']['method'])=={'0','1','2'}


@pytest.mark.parametrize('arm_id',['oracle','nominal','reference'])
def test_oracle_ceiling_trains_on_independent_labelled_pool(tmp_path,arm_id):
    t=fixture(tmp_path)
    p0=data(tmp_path/'labelled-background.npz',n=600,seed=108,prefix='labelled-bg')
    p1=data(tmp_path/'labelled-signal.npz',n=300,seed=109,prefix='labelled-sig',signal=True)
    with np.load(p0['path']) as a, np.load(p1['path']) as b:
        arrays={k:np.concatenate((a[k],b[k])) for k in a.files}
    path=tmp_path/'labelled.npz'; np.savez(path,**arrays)
    np.savez(tmp_path/'evaluator-private/labelled.truth.npz',event_id=arrays['event_id'],truth=np.r_[np.zeros(600),np.ones(300)])
    t['baselines'].append({'id':arm_id,'kind':'supervised_oracle','architecture':'logistic','backend':'numpy',
                           'config':{'learning_rate':.1},'training_pool':ml.pin(path)})
    bind_plan(t,tmp_path); ml.run(t,tmp_path,tmp_path/'out')
    r=json.loads((tmp_path/'out/ml/receipt.json').read_text())
    assert all('ceiling' in a['information_role'] and 'unavailable' in a['information_role'] for a in r['arms'] if a['id']==arm_id)
    assert all(set(cf.model_scope(m)['train_groups']).isdisjoint(cf.model_scope(m)['test_groups']) for m in r['models'])
    next(a for a in r['arms'] if a['id']==arm_id)['information_role']='available method'
    with pytest.raises(ValueError,match='oracle'):
        ml.validate_receipt(r,t,tmp_path/'out/ml')


def test_weighted_exact_draw_and_disjoint_groups():
    pool={'x':np.zeros((4,1)),'region':np.ones(4),'weight':np.array([1.,2.,3.,100.]),
          'event_id':np.array(['a','b','c','d']),'group_id':np.array(['a','b','c','d'])}
    drawn=cf._signal_draw(pool,3,np.random.default_rng(400))
    assert len(drawn['x'])==3 and len(set(drawn['group_id']))==3
    with pytest.raises(ValueError,match='exceeds'):
        cf._signal_draw(pool,5,np.random.default_rng(400))


def test_injection_closure_uses_sampling_not_seed_denominator():
    policy={'estimand':'conditional_fixed_background','alpha':.05,'false_fail_probability':.01,
            'min_power_gain':.3,'max_null_rejection':.2}
    rows=[{'strength':strength,'statistic':value} for strength,value in [(0,0.),(10,10.)] for _ in range(100)]
    result=cf.injection_closure(rows,[1.]*20,policy)
    assert result['verdict']=='pass'
    assert all(r['samplings']==100 for r in result['cells'])
    assert cf.injection_closure(rows[:1]+rows[-1:],[1.]*20,policy)['verdict']=='unresolved'


def test_worker_gate_context_is_run_root_not_external_spec_dir(tmp_path, monkeypatch):
    spec_dir=tmp_path/'spec'; spec_dir.mkdir(); t=fixture(spec_dir)
    rd=tmp_path/'run'; (rd/'inputs').mkdir(parents=True)
    (rd/'inputs/science-plan.json').write_text(json.dumps({'mode':'ml-training','base_dir':str(spec_dir)}))
    (rd/'execution_attempt.json').write_text(json.dumps({'attempt':1}))
    captured=[]
    def stub(task,base,out,*,rundir):
        captured.append((base,out,rundir)); return {'status':'passed'}
    monkeypatch.setattr(cf,'run',stub)
    out=rd/'outputs/attempt-1'
    ml.run_in_worker(t,spec_dir,out,worker_started=0.)
    assert captured==[(spec_dir,out,rd)]
    with pytest.raises(ValueError,match='context'):
        ml.run_in_worker(t,spec_dir,rd/'outputs/attempt-2',worker_started=0.)

@pytest.mark.parametrize('field', ['checks','calibrated_p','observed_statistic','null_toys','fold_maps'])
def test_forged_receipt_science_refused(tmp_path,field):
    t=fixture(tmp_path); ml.run(t,tmp_path,tmp_path/'out')
    r=json.loads((tmp_path/'out/ml/receipt.json').read_text())
    if field=='checks':
        for check in r['checks'].values(): check['verdict']='pass'
        r['disposition']='supported_synthetic'
    elif field=='null_toys': r[field]=[{'toy':0,'state':'complete','statistic':1.}]
    elif field=='fold_maps':
        r[field][0]['folds']=[0]*len(r[field][0]['folds']); r['fold_map_digest']=ml.digest(r[field])
    else: r[field]=.01
    with pytest.raises(ValueError): ml.validate_receipt(r,t,tmp_path/'out/ml')


def test_blinded_run_has_no_sr_scores_or_checkpoints_on_disk(tmp_path):
    t=fixture(tmp_path); ml.run(t,tmp_path,tmp_path/'out')
    for path in (tmp_path/'out').rglob('*.npz'):
        with np.load(path) as z:
            assert 'scores' not in z.files and 'coef' not in z.files, path
    r=json.loads((tmp_path/'out/ml/receipt.json').read_text())
    assert not r['rank_references']
    assert all(a['truth_auc_evaluator_only'] is None for a in r['arms'])


def test_truth_supervised_search_refused(tmp_path):
    t=fixture(tmp_path); t['supervision']['kind']='truth'; t['objective']='anomaly_search'
    with pytest.raises(ValueError,match='truth'): ml.validate(t)


def test_flatness_unresolvable_resolution_marked_unresolved(tmp_path):
    t=fixture(tmp_path); ml.run(t,tmp_path,tmp_path/'out')
    r=json.loads((tmp_path/'out/ml/receipt.json').read_text())
    assert r['checks']['check:ml-selection-flatness']['verdict']=='unresolved'


def test_single_fold_drift_fails_separability(tmp_path,monkeypatch):
    t=fixture(tmp_path); t['checks']['permutations']=999; events=cf.load_events(t['dataset']['pins'][0],tmp_path,2)
    folds=cf.fold_map(events['group_id'],3,'fixed')
    values=iter([.001,1.,1.]); monkeypatch.setattr(cf,'_permutation_p',lambda *args:next(values))
    row={'arm':'method','kind':'weak','seed':1,'salt':'fixed','folds':folds,'scores':np.ones(600)}
    checks=cf.sculpting_checks(t,events,{'scores':[row]})
    assert checks['check:ml-sideband-separability']['verdict']=='fail'


def test_single_toy_null_calibration_unresolved(tmp_path):
    t=fixture(tmp_path)
    t['null_calibration']={'toys':1,'scope':'whole_procedure','datasets':[data(tmp_path/'toy.npz',prefix='toy',seed=67)],'claim_below':None,'unblind':False}
    bind_plan(t,tmp_path); ml.run(t,tmp_path,tmp_path/'out')
    r=json.loads((tmp_path/'out/ml/receipt.json').read_text())
    assert r['checks']['check:ml-null-calibration']['verdict']=='unresolved'


def test_region_counts_mismatch_refused(tmp_path):
    t=fixture(tmp_path); t['statistics']['region_counts']=[400,400,400]
    with pytest.raises(ValueError,match='region_counts'): ml.run(t,tmp_path,tmp_path/'out')


def test_handwritten_timing_refused(tmp_path):
    t=fixture(tmp_path)
    timing=t['budget']['unit_timing']; p=tmp_path/'fake-timing.json'
    p.write_text(json.dumps({k:timing[k] for k in ('rung','trainings','wall_seconds','cpu_seconds')}))
    timing['source']=ml.pin(p)
    with pytest.raises(ValueError,match='smoke receipt'): cf.inputs(t,tmp_path)


def test_method_performance_claim_refused_without_or1_record(tmp_path):
    t=fixture(tmp_path); t['claim_kind']='method_performance'
    with pytest.raises(ValueError,match='claim contract'): ml.validate(t)


def test_constant_scores_zero_selection_unresolved(tmp_path):
    t=fixture(tmp_path); t['scoring']['working_points']=[.1]
    d=cf.load_events(t['dataset']['pins'][0],tmp_path,2)
    row={'arm':'method','kind':'weak','seed':1,'salt':'fixed','scores':np.full(600,.5),'folds':cf.fold_map(d['group_id'],3,'fixed')}
    assert cf.achieved_sizing(t,d,{'scores':[row]})['verdict']=='unresolved'


def test_unequal_group_sizes_reduce_effective_n():
    d={'weight':np.ones(10),'group_id':np.array(['large']*9+['small'])}
    assert cf.effective_n(d)==pytest.approx(100/82)


def test_unequal_actual_epochs_fail_equal_budget():
    rows=[{'arm':name,'epochs':epochs,'wall_seconds':1.,'cpu_seconds':.8} for name,epochs in [('one',3),('two',1)]]
    assert cf.equal_budget(rows)['verdict']=='fail'


def test_truth_proxy_canary_detected():
    truth=np.tile([0.,1.],20)
    d={'x':np.column_stack((truth,np.arange(40)))}
    assert cf.leakage_check(d,truth)['verdict']=='fail'


def test_audit_failure_propagates_to_check_verdict(tmp_path,monkeypatch):
    t=fixture(tmp_path); d=cf.load_events(t['dataset']['pins'][0],tmp_path,2)
    monkeypatch.setattr(cf,'audit_models',lambda rows:{'passed':False,'errors':['leak'],'models':0})
    checks=cf.additional_checks(t,d,{'models':[],'scores':[]})
    assert checks['check:ml-crossfit-audit']['verdict']=='fail'


def test_multiwindow_medians_kept_separate():
    rows=[{'strength':1,'metrics':[{'arm':'a','kind':'weak','window':w,'data_efficiency':.1,'signal_efficiency':eff} for w,eff in [(0,.2),(1,.8)]]}]
    assert [(r['window'],r['median_signal_efficiency']) for r in cf.injection_medians(rows)]==[(0,.2),(1,.8)]


def test_sic_uses_signal_window_background(tmp_path,monkeypatch):
    t=fixture(tmp_path)
    ref={'region':np.array([1.,3.,3.,5.]),'weight':np.ones(4),'group_id':np.array(['a','b','c','d'])}
    signal={'region':np.array([3.,3.]),'weight':np.ones(2),'group_id':np.array(['s','t'])}
    def evaluate(t,f,d): return {('a',1,'s'):np.array([1.,1.,0.,1.]) if d is ref else np.ones(2)}
    monkeypatch.setattr(cf,'_evaluate_external',evaluate)
    rows=cf.injection_metrics(t,{'scores':[{'arm':'a','seed':1,'salt':'s','kind':'weak'}]},signal,ref)
    assert rows[0]['background_efficiency']==.5
    assert rows[0]['significance_improvement']==pytest.approx(2**.5)


def test_closure_precision_unreachable_refused_at_plan(tmp_path):
    t=fixture(tmp_path); p=data(tmp_path/'signal.npz',signal=True,prefix='signal')
    t['injection']={'signal_pool':p,'partition':{'method':'group_hash','salt':'p','injection_fraction':.5},'strengths':[0,20],'samplings':32,'draw':'exact_count_by_weight','median_rule':'median_signal_efficiency',
       'closure':{'estimand':'conditional_fixed_background','alpha':.05,'false_fail_probability':.01,'min_power_gain':.3,'max_null_rejection':.05}}
    with pytest.raises(ValueError,match='117 samplings'): ml.validate(t)


def test_eight_variant_arms_counted_as_trials(tmp_path):
    t=fixture(tmp_path); t['models']=[{**t['models'][0],'id':f'variant{i}'} for i in range(8)]
    with pytest.raises(ValueError,match='family.*max_trials'): ml.validate(t)


def test_spurious_threshold_above_declared_bound_refused(tmp_path):
    t=fixture(tmp_path); t['checks']['max_spurious_z']=10
    with pytest.raises(ValueError): ml.validate(t)


def test_self_raised_ceiling_without_record_refused(tmp_path):
    t=fixture(tmp_path); t['budget']['ceiling_seconds']=864000
    with pytest.raises(ValueError,match='spend_above_ceiling'): cf.authoritative_ceiling(t,tmp_path)


def test_truth_arm_excluded_from_search_max(tmp_path):
    t=fixture(tmp_path); t['supervision']['kind']='truth'
    with pytest.raises(ValueError,match='truth'): cf._max_statistic(t,{}, {'scores':[]})


def test_flatness_detects_full_sideband_sculpting(tmp_path):
    t=fixture(tmp_path); t['checks']['permutations']=1999
    d=cf.load_events(t['dataset']['pins'][0],tmp_path,2)
    row={'arm':'method','kind':'weak','seed':1,'salt':'fixed','scores':(d['region']<2).astype(float),'folds':cf.fold_map(d['group_id'],3,'fixed')}
    assert cf.sculpting_checks(t,d,{'scores':[row]})['check:ml-selection-flatness']['verdict']=='fail'


def test_nondefault_namespace_receipt_records_authority(tmp_path):
    t=fixture(tmp_path); ml.run(t,tmp_path,tmp_path/'out')
    r=json.loads((tmp_path/'out/ml/receipt.json').read_text())
    from ravel.workflow import machine_lease
    assert r['exposure_ledger']['root']==str((machine_lease.machine_dir()/'ml-exposure').resolve())
    assert r['exposure_ledger']['ledger_digest'] and r['exposure_ledger']['test_namespace']


def test_truth_column_in_feature_file_refused(tmp_path):
    t=fixture(tmp_path); p=t['dataset']['pins'][0]
    with np.load(p['path']) as z: arrays={k:z[k] for k in z.files}
    np.savez(p['path'],**arrays,truth=np.zeros(len(arrays['x'])))
    with pytest.raises(ValueError,match='schema'): cf.load_events(ml.pin(p['path']),tmp_path,2)


def test_weighted_population_refusal_names_route(tmp_path):
    p=data(tmp_path/'weighted.npz')
    with np.load(p['path']) as z: arrays={k:z[k] for k in z.files}
    arrays['weight'][0]=2; np.savez(p['path'],**arrays)
    with pytest.raises(ValueError,match='weighted permutation/inference qualification route'): cf.load_events(ml.pin(p['path']),tmp_path,2)


def test_resume_after_ceiling_timeout_counts_same_read(tmp_path,monkeypatch):
    from ravel.physics import ml_exposure
    t=fixture(tmp_path); original=cf._single_crossfit
    def timed_out(*args,**kwargs):
        original(*args,**kwargs)
        raise ValueError('study wall ceiling exhausted')
    monkeypatch.setattr(cf,'_single_crossfit',timed_out)
    with pytest.raises(ValueError,match='ceiling'): ml.run(t,tmp_path,tmp_path/'out')
    records=[json.loads(p.read_text()) for p in ml_exposure.root().glob('*.json')]
    before=sum(len(r['reads']) for r in records)
    monkeypatch.setattr(cf,'fit_model',lambda *a,**k:pytest.fail('resume retrained'))
    resumed=cf.resume_frozen(t,tmp_path,tmp_path/'out')
    records=[json.loads(p.read_text()) for p in ml_exposure.root().glob('*.json')]
    assert sum(len(r['reads']) for r in records)==before==resumed['test_reads']
    assert sum(len(r.get('replays',[])) for r in records)==before
    assert resumed['status']=='partial'


def test_forged_unblind_gate_dict_rejected(tmp_path):
    t=fixture(tmp_path); ml.run(t,tmp_path,tmp_path/'out')
    r=json.loads((tmp_path/'out/ml/receipt.json').read_text())
    r['observed_statistic']=5.; r['calibrated_p']=.01
    r['gates']=[{'gate':'unblind','digest':ml.digest(t),'verdict':'passed'}]
    for a in r['arms']: a['calibration'].update(state='unblinded',ece=.1,brier=.1)
    with pytest.raises(ValueError,match='authenticated'): ml.validate_receipt(r,t,tmp_path/'out/ml')


def test_one_failed_toy_does_not_disable_completeness(tmp_path):
    t=fixture(tmp_path); ml.run(t,tmp_path,tmp_path/'out')
    r=json.loads((tmp_path/'out/ml/receipt.json').read_text()); r['models'].pop()
    r['cost_actuals']['completed_trainings']=len(r['models'])
    r['null_toys']=[{'toy':0,'state':'failed_extreme','statistic':None,'training_records':[]}]
    with pytest.raises(ValueError,match='population'): ml.validate_receipt(r,t,tmp_path/'out/ml')


def test_zero_strength_injection_inputs_not_on_disk(tmp_path):
    t=fixture(tmp_path); pool=data(tmp_path/'signal.npz',signal=True,prefix='signal')
    t['inner_selection']['initializations']=1
    t['injection']={'signal_pool':pool,'partition':{'method':'group_hash','salt':'pool','injection_fraction':.5},'strengths':[0],'samplings':3,'draw':'exact_count_by_weight','median_rule':'median_signal_efficiency'}
    bind_plan(t,tmp_path); ml.run(t,tmp_path,tmp_path/'out')
    assert not list((tmp_path/'out').rglob('*.npz'))


def test_truth_auc_withheld_before_unblind(tmp_path):
    t=fixture(tmp_path); pin=t['dataset']['truth_pin']
    with np.load(pin['path']) as z: ids=z['event_id']
    np.savez(pin['path'],event_id=ids,truth=np.arange(len(ids))%2)
    t['dataset']['truth_pin']=ml.pin(pin['path'])
    t['dataset']['manifest_sha256']=ml.digest({k:v for k,v in t['dataset'].items() if k!='manifest_sha256'})
    plan=json.loads(Path(t['placement']['backend_plan']['path']).read_text())
    for row in plan['inputs']+plan['spec']['inputs']:
        if row['path']==pin['path']: row['sha256']=t['dataset']['truth_pin']['sha256']
    plan['plan_sha256']=ml.digest({k:v for k,v in plan.items() if k!='plan_sha256'})
    Path(t['placement']['backend_plan']['path']).write_text(json.dumps(plan)); t['placement']['backend_plan']=ml.pin(t['placement']['backend_plan']['path'])
    ml.run(t,tmp_path,tmp_path/'out')
    r=json.loads((tmp_path/'out/ml/receipt.json').read_text())
    assert all(a['truth_auc_evaluator_only'] is None for a in r['arms'])


def test_strength_above_pool_refused_at_plan(tmp_path):
    t=fixture(tmp_path); pool=data(tmp_path/'signal.npz',n=30,signal=True,prefix='signal')
    t['injection']={'signal_pool':pool,'partition':{'method':'group_hash','salt':'pool','injection_fraction':.5},'strengths':[100],'samplings':3,'draw':'exact_count_by_weight','median_rule':'median_signal_efficiency'}
    bind_plan(t,tmp_path)
    with pytest.raises(ValueError,match='exceeds independent pool'): cf.inputs(t,tmp_path)


def test_spurious_row_maximum_is_trial_calibrated():
    checks={'check:ml-spurious-signal':{'verdict':'unresolved','rows':[{'signed_residual':2.},{'signed_residual':3.}]}}
    toy_checks=[{'check:ml-spurious-signal':{'rows':[{'signed_residual':1.},{'signed_residual':2.}]}} for _ in range(20)]
    result=cf.calibrate_spurious(checks,toy_checks,.05)
    assert result['check:ml-spurious-signal']['toy_maximum_p']==1/21
    assert result['check:ml-spurious-signal']['verdict']=='fail'


def test_blinded_seed_spread_is_not_an_acceptance_pass(tmp_path):
    t=fixture(tmp_path); ml.run(t,tmp_path,tmp_path/'out')
    r=json.loads((tmp_path/'out/ml/receipt.json').read_text())
    assert r['checks']['check:ml-seed-spread']['verdict']=='unresolved'


def test_oracle_injection_rotation_checked_before_exposure(tmp_path):
    t=fixture(tmp_path)
    pool=data(tmp_path/'oracle.npz',n=120,seed=710,prefix='oracle')
    with np.load(pool['path']) as z: ids=z['group_id']
    nominal=cf.fold_map(ids,3,'fixed'); variation=cf.fold_map(ids,3,'variation')
    shifted=cf.fold_map(ids,3,'fixed:injection-0-0'); truth=np.zeros(len(ids))
    for fold in range(3):
        chosen=np.flatnonzero((nominal==fold)&(variation==fold)&(shifted!=2))[0]
        truth[chosen]=1
    np.savez(tmp_path/'evaluator-private/oracle.truth.npz',event_id=ids,truth=truth)
    t['baselines'].append({'id':'oracle','kind':'supervised_oracle','architecture':'logistic','backend':'numpy','config':{'learning_rate':.1},'training_pool':pool})
    signal=data(tmp_path/'signal.npz',n=60,signal=True,prefix='signal')
    t['injection']={'signal_pool':signal,'partition':{'method':'group_hash','salt':'pool','injection_fraction':.5},'strengths':[0],'samplings':3,'draw':'exact_count_by_weight','median_rule':'median_signal_efficiency'}
    bind_plan(t,tmp_path)
    with pytest.raises(ValueError,match='oracle.*both classes'): cf.inputs(t,tmp_path)


def test_resume_refuses_rewritten_frozen_history(tmp_path,monkeypatch):
    t=fixture(tmp_path); original=cf._single_crossfit
    def interrupted(*args,**kwargs):
        original(*args,**kwargs); raise ValueError('interrupted after freeze')
    monkeypatch.setattr(cf,'_single_crossfit',interrupted)
    with pytest.raises(ValueError,match='interrupted'): ml.run(t,tmp_path,tmp_path/'out')
    freeze=json.loads(next((tmp_path/'out/ml/nominal').glob('freeze-*.json')).read_text())
    for path in (tmp_path/'out/ml/nominal').glob('*.history.json'):
        row=json.loads(path.read_text())
        if row['checkpoint']==freeze['models'][0]:
            row['validation_loss']+=1; path.write_text(json.dumps(row)); break
    with pytest.raises(ValueError,match='pin.*changed'): cf.resume_frozen(t,tmp_path,tmp_path/'out')
