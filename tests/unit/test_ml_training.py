"""Small synthetic controls for governed training, never physics certification."""

from method_decision_fixture import admit_method
from stage_evidence_fixture import stage_evidence
import copy
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from ravel.physics import ml_training as ml
from ravel.workflow import execution_backend as eb, science


def fixture(tmp_path):
    rng = np.random.default_rng(42)
    pins = {}; census = []
    for j, name in enumerate(('train', 'val', 'test')):
        x = rng.normal(size=(40, 2))
        y = (x[:, 0] + .4 * x[:, 1] > 0).astype(int)
        path = tmp_path / (name + '.npz')
        np.savez(path, x=x, y=y, weight=np.ones(40), event_id=np.arange(j*40, (j+1)*40), group_id=np.arange(j*40, (j+1)*40))
        pins[name] = ml.pin(path)
        census.extend({'event_id': str(i), 'group_id': str(i), 'partition': name} for i in range(j*40, (j+1)*40))
    index = tmp_path / 'population-index.json'; index.write_text(json.dumps(census))
    dataset = {'pins': list(pins.values()), 'features': ['a', 'b'], 'label': 'y',
               'weights': 'weight', 'id_column': 'event_id', 'population_index': ml.pin(index)}
    dataset['manifest_sha256'] = ml.digest(dataset)
    splits = {'method': 'explicit', 'seed': 17, 'fractions': {'train': .6, 'val': .2, 'test': .2},
              'files': pins, 'test_withheld': True}
    splits['split_sha256'] = ml.split_digest(splits)
    plan = eb.prepare({'schema_version': 1, 'backend': 'native', 'stage': 'ml-training',
                       'argv': [sys.executable, '-m', 'ravel.physics.science_worker', str(tmp_path)],
                       'inputs': list(pins.values()) + [dataset['population_index']], 'outputs': [{'name': 'result.json',
                        'destination': 'outputs/result.json', 'kind': 'file'}],
                       'resources': {'cpus': 1, 'memory_mib': 256, 'wall_seconds': 120}})
    p = tmp_path / 'backend.json'; p.write_text(json.dumps(plan))
    task = {'objective': 'classification', 'dataset': dataset, 'splits': splits,
            'baselines': [{'id': 'linear', 'architecture': 'logistic', 'backend': 'numpy',
                           'config': {'learning_rate': .1}}],
            'models': [{'id': 'nonlinear', 'architecture': 'mlp', 'backend': 'numpy',
                        'config': {'learning_rate': .1, 'hidden_units': 4}}],
            'seeds': [1, 2, 3],
            'budget': {'wall_seconds': 10, 'epochs': 8, 'max_trials': 1, 'equal_across_arms': True},
            'metrics': {'primary': 'background_rejection_at_signal_eff', 'operating_point': .5,
                        'secondary': ['roc_auc'], 'calibration': {'method': 'reliability', 'bins': 5,
                        'report': ['ece', 'brier']}, 'uncertainty': 'seed_spread'},
            'placement': {'backend_plan': ml.pin(p), 'device': 'cpu'}}
    return task


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))


def test_registration_and_input_inventory_never_decode_test(tmp_path, monkeypatch):
    t = fixture(tmp_path)
    monkeypatch.setattr(ml, 'load_split', lambda *a, **k: pytest.fail('planning decoded data'))
    assert science.adapter({'mode': 'ml-training'}) is ml
    assert science._new_capability({'mode': 'ml-training'})
    assert 'ml-training' in science.MODES
    assert len(ml.inputs(t, tmp_path)) >= 4
    assert ml.execution_seconds(t, tmp_path) <= 120


@pytest.mark.parametrize('change', [
    lambda t: t['seeds'].pop(),
    lambda t: t['seeds'].__setitem__(2, 1),
    lambda t: t['splits'].__setitem__('test_withheld', False),
    lambda t: t['budget'].__setitem__('equal_across_arms', False),
    lambda t: t['budget'].__setitem__('max_trials', 2),
    lambda t: t['models'][0].__setitem__('budget', {'epochs': 9}),
    lambda t: t['models'][0]['config'].__setitem__('search', [1, 2]),
    lambda t: t['models'][0].__setitem__('architecture', 'undeclared'),
    lambda t: t['placement'].__setitem__('device', 'cuda'),
    lambda t: t.__setitem__('peek_test', True),
])
def test_refuses_unfair_or_unbounded_studies(tmp_path, change):
    t = fixture(tmp_path); change(t)
    with pytest.raises(ValueError): ml.validate(t)


def test_train_freeze_then_read_test_once_all_arms(tmp_path, monkeypatch):
    t = fixture(tmp_path); seen = []
    original = ml.load_split
    def spy(task, base, name):
        seen.append(name)
        if name == 'test':
            assert len(list((tmp_path/'out/ml/checkpoints').glob('*.npz'))) == 6
        return original(task, base, name)
    monkeypatch.setattr(ml, 'load_split', spy)
    r = ml.run(t, tmp_path, tmp_path/'out')
    assert r['status'] == 'passed' and r['physics_validated'] is False
    assert seen == ['train', 'val', 'test']
    receipt = json.loads((tmp_path/'out/ml/receipt.json').read_text())
    assert receipt['test_reads'] == 1
    assert len(receipt['arms']) == 6
    assert all(a['epochs'] == 8 for a in receipt['arms'])
    assert all(0 <= a['metrics']['roc_auc'] <= 1 for a in receipt['arms'])
    assert set(receipt['summary']) == {'linear', 'nonlinear'}
    assert (tmp_path/'out/ml/RESULT.md').is_file()
    ml.validate_receipt(receipt, t, tmp_path/'out/ml')
    receipt['test_reads'] = 2
    with pytest.raises(ValueError): ml.validate_receipt(receipt, t, tmp_path/'out/ml')
    with pytest.raises(ValueError, match='spent|already'): ml.run(t, tmp_path, tmp_path/'other')


def test_pins_and_leakage(tmp_path):
    t = fixture(tmp_path)
    Path(t['splits']['files']['train']['path']).write_bytes(b'changed')
    with pytest.raises(ValueError, match='pin|sha256'): ml.inputs(t, tmp_path)


def test_overlapping_event_ids_refused_before_test(tmp_path, monkeypatch):
    t = fixture(tmp_path)
    original = ml.load_split
    def overlap(task, base, name):
        x, y, w, ids = original(task, base, name)
        if name == 'val': ids = np.arange(40).astype(str)
        if name == 'test': pytest.fail('test exposed before split check')
        return x, y, w, ids
    monkeypatch.setattr(ml, 'load_split', overlap)
    with pytest.raises(ValueError, match='overlap'): ml.run(t, tmp_path, tmp_path/'out')


def test_metrics_ties_weights_and_zero_background():
    m, rel, roc = ml.metrics(np.array([0, 1]), np.array([.5, .5]), np.ones(2), .5, 5)
    assert m['roc_auc'] == .5 and m['ece'] == 0 and m['brier'] == .25
    m, _, _ = ml.metrics(np.array([0, 1]), np.array([.1, .9]), np.ones(2), .5, 5)
    assert m['roc_auc'] == 1
    assert m['background_rejection_at_signal_eff'] is None
    assert m['background_efficiency'] == 0
    assert m['rejection_status'] == 'zero_background_observed'


def test_numpy_seed_determinism():
    from ravel.physics.ml_backends import fit, predict
    x = np.array([[-1., 1.], [1., -1.], [2., 0.], [-2., 0.]])
    y = np.array([0., 1., 1., 0.]); w = np.ones(4)
    arm = {'architecture': 'mlp', 'backend': 'numpy', 'config': {'hidden_units': 4, 'learning_rate': .1}}
    a = fit(arm, x, y, w, 7, 10, lambda: None)
    b = fit(arm, x, y, w, 7, 10, lambda: None)
    np.testing.assert_array_equal(predict(a, x), predict(b, x))
    assert predict(a, x)[2] > predict(a, x)[3]


def test_lease_refusal_precedes_data_read(tmp_path, monkeypatch):
    t = fixture(tmp_path)
    monkeypatch.setattr(ml, 'load_split', lambda *a: pytest.fail('data read while lease busy'))
    from ravel.workflow.machine_lease import LeaseBusy
    # A second job in the process that already holds the lease has its own refusal.
    refusal = 'this process already holds the lease of a native scientific job; a second job in one process is a second job'
    with eb.machine_lease('other'):
        with pytest.raises(LeaseBusy, match=refusal): ml.run(t, tmp_path, tmp_path/'out')


def test_failed_test_open_spends_attempt_and_no_receipt(tmp_path, monkeypatch):
    t = fixture(tmp_path); original = ml.load_split
    def crash(task, base, name):
        if name == 'test': raise ValueError('synthetic decode failure')
        return original(task,base,name)
    monkeypatch.setattr(ml, 'load_split', crash)
    with pytest.raises(ValueError, match='synthetic'): ml.run(t,tmp_path,tmp_path/'out')
    exposure=json.loads(next((tmp_path/'ml-exposure').glob('*.json')).read_text())
    assert exposure['test_reads']==1 and exposure['state']=='failed'
    assert not (tmp_path/'out/ml/receipt.json').exists()
    t['splits']['seed']+=1; t['splits']['split_sha256']=ml.split_digest(t['splits'])
    with pytest.raises(ValueError, match='spent'): ml.run(t,tmp_path,tmp_path/'retry')


def test_wall_exhaustion_never_exposes_test(tmp_path, monkeypatch):
    t = fixture(tmp_path)
    def exhausted(*args): raise ValueError('training wall budget exhausted')
    monkeypatch.setattr(ml.ml_backends,'fit',exhausted)
    with pytest.raises(ValueError,match='wall budget'): ml.run(t,tmp_path,tmp_path/'out')
    exposure=json.loads(next((tmp_path/'ml-exposure').glob('*.json')).read_text())
    assert exposure['test_reads']==0


def test_explicit_labels_signed_weights_and_duplicate_ids_refused(tmp_path):
    t = fixture(tmp_path)
    for field, value in [('weight', np.full(40,-1)), ('y', np.full(40,2)), ('event_id', np.zeros(40,dtype=int))]:
        p=Path(t['splits']['files']['train']['path'])
        with np.load(p) as raw: data={k:raw[k] for k in raw.files}
        data[field]=value; np.savez(p,**data)
        t['splits']['files']['train']=ml.pin(p)
        with pytest.raises(ValueError): ml.load_split(t,tmp_path,'train')
        t=fixture(tmp_path)


def test_hash_shards_checked_and_deterministic(tmp_path):
    t=fixture(tmp_path); t['splits']['method']='hash'
    for name in ('train','val','test'):
        ids=np.array([i for i in range(10000) if ml.hash_partition(str(i),17,t['splits']['fractions'])==name][:40])
        p=Path(t['splits']['files'][name]['path'])
        with np.load(p) as d: arrays={k:d[k] for k in d.files}
        arrays['event_id']=ids; arrays['group_id']=ids; np.savez(p,**arrays); t['splits']['files'][name]=ml.pin(p)
        assert len(ml.load_split(t,tmp_path,name)[0])==40
    t['splits']['seed']=18
    with pytest.raises(ValueError,match='hash split'): ml.load_split(t,tmp_path,'train')


def test_backend_plan_resources_and_pins_cannot_be_substituted(tmp_path):
    t=fixture(tmp_path); p=Path(t['placement']['backend_plan']['path']); plan=json.loads(p.read_text())
    plan['spec']['resources']['wall_seconds']=1
    plan['plan_sha256']=ml.digest({k:v for k,v in plan.items() if k!='plan_sha256'})
    p.write_text(json.dumps(plan)); t['placement']['backend_plan']=ml.pin(p)
    with pytest.raises(ValueError,match='ceiling'): ml.inputs(t,tmp_path)


def test_weighted_auc_matches_pairwise_reference():
    y=np.array([0,1,0,1,0,1]); s=np.array([.1,.2,.2,.2,.8,.9]); w=np.array([1,2,3,4,5,6])
    numerator=sum(w[i]*w[j]*((s[i]>s[j])+.5*(s[i]==s[j])) for i in range(6) for j in range(6) if y[i]==1 and y[j]==0)
    expected=numerator/(w[y==1].sum()*w[y==0].sum())
    m,_,_=ml.metrics(y,s,w,.5,5)
    assert m['roc_auc']==pytest.approx(expected)


def test_ordinary_scope_and_figures_registration(tmp_path):
    t=fixture(tmp_path)
    spec={'schema_version':1,'mode':'ml-training','source':'Synthetic classification',
          'assumptions':['Engineering control only'], 'max_seconds':120,
          'approval_mode':'scripted_yes','task':t}
    science.validate(spec)
    assert len(science.task_inputs(spec,tmp_path))>=4
    r=ml.run(t,tmp_path,tmp_path/'out')
    from ravel.plotting.science_figures import render
    f=render(spec,r,tmp_path,tmp_path/'out')
    assert len(f['figures'])==2
    assert all((tmp_path/'out'/p).is_file() for row in f['figures'] for p in row['files'])


def test_receipt_rejects_environment_drift_and_fake_metric(tmp_path):
    t=fixture(tmp_path); ml.run(t,tmp_path,tmp_path/'out')
    output=tmp_path/'out/ml'; r=json.loads((output/'receipt.json').read_text())
    tampered=copy.deepcopy(r); tampered['arms'][0]['metrics']['ece']=-1
    tampered['summary']=ml._summary(tampered['arms'])
    with pytest.raises(ValueError): ml.validate_receipt(tampered,t,output)
    (output/'environment.json').write_text('{}')
    with pytest.raises(ValueError,match='environment'): ml.validate_receipt(r,t,output)


def test_version_one_cannot_launch_new_training_mode(tmp_path):
    t=fixture(tmp_path)
    p=tmp_path/'spec.json'
    p.write_text(json.dumps({'schema_version':1,'mode':'ml-training','source':'Synthetic classification',
        'assumptions':['Engineering only'],'max_seconds':120,'approval_mode':'scripted_yes','task':t}))
    with pytest.raises(ValueError,match='version 2'): science.plan(tmp_path/'run',p)


def test_ordinary_supervised_worker(tmp_path):
    import os
    from ravel.workflow.execution import process_identity
    if process_identity(os.getpid()) is None:
        pytest.skip('sandbox denies process identity; native supervisor qualification needs coordinator queue')
    from test_physics_review import policy
    t=fixture(tmp_path); p=policy()
    p.update(max_redos=0,allowed_stages=['science'],allowed_changed_paths=[])
    spec={'schema_version':2,'mode':'ml-training','source':'Synthetic classification',
          'assumptions':['Engineering control only'],'max_seconds':120,'max_attempts':1,
          'approval_mode':'scripted_yes','task':t,
          'review_policy':{'schema_version':1,'policy':p,
                           'correction_contract':{'task_fields':[],'input_slots':[]}}}
    source=tmp_path/'spec.json'; source.write_text(json.dumps(spec)); rd=tmp_path/'run'
    science.plan(rd,source); admit_method(rd)
    with pytest.raises((ValueError, OSError)): science.run(rd)
    science.approve(rd,'Approved synthetic tiny CPU training control',scripted=True)
    code=science.run(rd)
    assert code==0, stage_evidence(rd)
    out=rd/'outputs/attempt-1'
    assert json.loads((out/'ml/receipt.json').read_text())['test_reads']==1
    assert (out/'RESULT.md').is_file() and (out/'figures.json').is_file()


def test_science_worker_dispatch_with_explicit_admission_stub(tmp_path, monkeypatch):
    """Real adapter/publications; admission stub proves dispatch, not authorization."""
    from ravel.physics import science_worker
    t=fixture(tmp_path); rd=tmp_path/'worker-run'; rd.mkdir()
    spec={'schema_version':2,'mode':'ml-training','task':t,'assumptions':['Synthetic dispatch control']}
    monkeypatch.setattr(science,'prepare_readonly_worker',lambda *a,**k:None)
    monkeypatch.setattr(science_worker,'verify_worker',lambda *a:{'base_dir':str(tmp_path),
        'output_directory':'outputs/attempt-1','stage_binding':{'input_snapshot':{}}})
    monkeypatch.setattr(science_worker,'execution_spec',lambda *a:spec)
    assert science_worker.main([str(rd)])==0
    output=rd/'outputs/attempt-1'
    assert json.loads((output/'ml/receipt.json').read_text())['test_reads']==1
    assert json.loads((output/'verification.json').read_text())['physics_validated'] is False
    assert (output/'RESULT.md').is_file() and (output/'ml/roc.pdf').is_file()


@pytest.mark.parametrize('backend', ['sklearn','torch'])
def test_missing_optional_backend_refuses_before_exposure(tmp_path, monkeypatch, backend):
    t=fixture(tmp_path); t['baselines'][0]['backend']=backend
    monkeypatch.setattr(ml.ml_backends,'available',lambda:{'numpy':True,'sklearn':False,'torch':False})
    with pytest.raises(ValueError,match='not installed'): ml.run(t,tmp_path,tmp_path/'out')
    assert not (tmp_path/'ml-exposure').exists()


def graph_task(tmp_path):
    t=fixture(tmp_path)
    t['models'][0].update(backend='torch-geometric',architecture='gnn',
        config={'learning_rate':.1,'hidden_units':4,'nodes':2,'edge_index':[[0,1],[1,0]]})
    for name,pin in t['splits']['files'].items():
        path=Path(pin['path'])
        with np.load(path) as d: arrays={k:d[k] for k in d.files}
        arrays['x']=np.stack([arrays['x'],arrays['x']*.5],axis=1)
        np.savez(path,**arrays); t['splits']['files'][name]=ml.pin(path)
    t['dataset']['pins']=list(t['splits']['files'].values())
    t['dataset']['manifest_sha256']=ml.digest({k:v for k,v in t['dataset'].items() if k!='manifest_sha256'})
    t['splits']['split_sha256']=ml.split_digest(t['splits'])
    return t


def test_graph_schema_requires_explicit_topology_and_tensor_shape(tmp_path):
    t=graph_task(tmp_path); ml.validate(t)
    assert ml.load_split(t,tmp_path,'train')[0].shape==(40,2,2)
    t['models'][0]['config']['edge_index']=[[0,2],[1,0]]
    with pytest.raises(ValueError): ml.validate(t)


def test_graph_library_dispatch_uses_the_small_backend_interface(monkeypatch):
    from ravel.physics import ml_backends as backends
    arm={'backend':'torch-geometric','architecture':'gnn','config':{}}
    monkeypatch.setattr(backends,'available',lambda:{'torch-geometric':True})
    seen=[]
    monkeypatch.setattr(backends,'_fit_graph',lambda *args:seen.append(args) or {'graph_nodes':np.array(2)})
    x=np.zeros((4,2,2)); y=np.array([0.,1.,0.,1.]); w=np.ones(4)
    state=backends.fit(arm,x,y,w,3,2,lambda:None)
    assert len(seen)==1 and seen[0][1] is x
    monkeypatch.setattr(backends,'_predict_graph',lambda state,x:np.full(len(x),.5))
    np.testing.assert_array_equal(backends.predict(state,x),np.full(4,.5))


@pytest.mark.parametrize('backend,architecture', [('sklearn','logistic'),('torch','mlp'),('torch-geometric','gnn')])
def test_installed_backend_seed_replay(backend, architecture):
    """Runs only on an installed optional runtime; retained for installer queue."""
    from ravel.physics import ml_backends as backends
    if not backends.available()[backend]: pytest.skip(f'{backend} is not installed')
    config={'learning_rate':.1}
    if architecture in ('mlp','gnn'): config['hidden_units']=4
    if architecture=='gnn': config.update(nodes=2,edge_index=[[0,1],[1,0]])
    arm={'backend':backend,'architecture':architecture,'config':config}
    x=np.array([[-2.,-.5],[-1.,.5],[1.,-.5],[2.,.5]])
    if architecture=='gnn': x=np.stack([x,x*.5],axis=1)
    y=np.array([0.,0.,1.,1.]); weights=np.array([1.,2.,1.,2.])
    first=backends.fit(arm,x,y,weights,3,20,lambda:None)
    second=backends.fit(arm,x,y,weights,3,20,lambda:None)
    score=backends.predict(first,x)
    np.testing.assert_array_equal(score,backends.predict(second,x))
    assert np.isfinite(score).all() and np.all((score>=0)&(score<=1))


def test_dense_reference_can_train_graph_tensor_baselines():
    from ravel.physics import ml_backends as backends
    x=np.array([[[-1.],[-2.]],[[1.],[2.]],[[-2.],[-1.]],[[2.],[1.]]])
    arm={'architecture':'logistic','backend':'numpy','config':{'learning_rate':.1}}
    model=backends.fit(arm,x,np.array([0.,1.,0.,1.]),np.ones(4),5,20,lambda:None)
    assert backends.predict(model,x)[1] > backends.predict(model,x)[0]


def test_routing_catalogue_lists_ml_training_mode():
    """The routing catalogue reads MODES as a source literal, so the mode must be in it."""
    from ravel.workflow import capability_routing as cr
    rows = {row['mode']: row for row in cr.catalogue()['operations']}
    assert 'ml-training' in rows
    assert rows['ml-training']['module'] == 'ravel.physics.ml_training'


def test_supervised_forged_auc_and_roc_rejected(tmp_path):
    t=fixture(tmp_path); ml.run(t,tmp_path,tmp_path/'out')
    r=json.loads((tmp_path/'out/ml/receipt.json').read_text())
    r['arms'][0]['metrics']['roc_auc']=.123
    r['arms'][0]['roc']['true_positive_rate']=[0.,1.]
    r['summary']=ml._summary(r['arms'])
    r['summary_by_metric']={metric:{arm:values[metric] for arm,values in r['summary'].items()} for metric in ('roc_auc','background_rejection_at_signal_eff','ece','brier')}
    with pytest.raises(ValueError,match='recomput|receipt'): ml.validate_receipt(r,t,tmp_path/'out/ml')
