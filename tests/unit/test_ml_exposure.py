"""Study-wide exposure ledger: one study per withheld population, selection before reads."""
import json
import shutil

import pytest

import test_ml_crossfit as cfx
import test_ml_training as sup
from ravel.physics import ml_crossfit as cf
from ravel.physics import ml_exposure
from ravel.physics import ml_training as ml


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path/'state'))


def ledger(sha256):
    records=[json.loads(p.read_text()) for p in ml_exposure.root().glob('*.json')]
    return next(r for r in records if r['identity']['byte_sha256']==sha256 or r['sha256']==sha256)


def test_supervised_test_split_cannot_be_reread_from_a_copy(tmp_path):
    first=tmp_path/'first'; first.mkdir()
    task=sup.fixture(first)
    ml.run(task,first,first/'out')
    sha=task['splits']['files']['test']['sha256']
    record=ledger(sha)
    assert record['roles']==['test_split'] and len(record['reads'])==1
    selection=record['reads'][0]['selection']
    assert selection['path'].endswith('frozen.json')
    # A later round copies the same events elsewhere; the content is still spent.
    second=tmp_path/'second'; second.mkdir()
    for name in ('train','val','test'): shutil.copy(first/f'{name}.npz',second/f'{name}.npz')
    again=sup.fixture(second)
    assert again['splits']['files']['test']['sha256']==sha
    with pytest.raises(ValueError,match='another study'):
        ml.run(again,second,second/'out')


def test_crossfit_population_refused_for_a_second_study_before_training(tmp_path, monkeypatch):
    first=tmp_path/'first'; first.mkdir()
    t=cfx.fixture(first); t['inner_selection']['initializations']=1
    t['splits']['fold_salts']=['fixed']; t['splits']['split_sha256']=ml.split_digest(t['splits'])
    cfx.bind_plan(t,first); ml.run(t,first,first/'out')
    sha=t['dataset']['pins'][0]['sha256']
    record=ledger(sha)
    assert record['roles']==['crossfit_population']
    assert len(record['reads'])==3 and all(r['selection']['path'].endswith('.json') for r in record['reads'])
    second=tmp_path/'second'; second.mkdir()
    shutil.copy(first/'events.npz',second/'events.npz')
    other=cfx.fixture(second); other['seeds']=[4,5,6]; cfx.bind_plan(other,second)
    assert other['dataset']['pins'][0]['sha256']==sha
    monkeypatch.setattr(cf,'fit_model',lambda *a,**k: pytest.fail('trained on a spent population'))
    with pytest.raises(ValueError,match='another study'):
        ml.run(other,second,second/'out')


def test_evaluation_pool_and_reference_belong_to_one_study(tmp_path):
    first=tmp_path/'first'; first.mkdir()
    t=cfx.fixture(first); t['inner_selection']['initializations']=1
    t['splits']['fold_salts']=['fixed']; t['splits']['split_sha256']=ml.split_digest(t['splits'])
    pool=cfx.data(first/'signal.npz',n=200,seed=21,signal=True,prefix='signal')
    t['injection']={'signal_pool':pool,'partition':{'method':'group_hash','salt':'pool','injection_fraction':.5},
                    'strengths':[0,20],'samplings':3,'draw':'exact_count_by_weight','median_rule':'median_signal_efficiency'}
    t['checks']['reference']=cfx.data(first/'reference.npz',n=600,seed=33,prefix='reference')
    cfx.bind_plan(t,first); ml.run(t,first,first/'out')
    evaluation=ledger(pool['sha256'])
    assert evaluation['roles']==['injection_evaluation_pool'] and len(evaluation['reads'])==6
    for read in evaluation['reads']:
        frozen=json.loads(open(read['selection']['path']).read())
        assert frozen['selection'], 'evaluation read must name the frozen models first'
    reference=ledger(t['checks']['reference']['sha256'])
    assert reference['roles']==['background_reference'] and reference['reads']
    # A second study on a fresh population still cannot reuse the evaluation pool.
    second=tmp_path/'second'; second.mkdir()
    other=cfx.fixture(second,seed=14,prefix='second'); other['inner_selection']['initializations']=1
    other['splits']['fold_salts']=['fixed']; other['splits']['split_sha256']=ml.split_digest(other['splits'])
    other['injection']=t['injection']; cfx.bind_plan(other,second)
    with pytest.raises(ValueError,match='another study'):
        ml.run(other,second,second/'out')


def test_read_requires_existing_selection_and_unique_context(tmp_path):
    identity=ml_exposure.identity(cfx.data(tmp_path/'p.npz'),tmp_path)
    sha=identity['sha256']; study=ml_exposure.Study('spec-a')
    study.claim(identity,'test_split',schedule={sha:['test']})
    with pytest.raises(ValueError,match='selection'):
        study.read(sha,'test',{'path':str(tmp_path/'missing.json'),'sha256':'0'*64})
    frozen=tmp_path/'frozen.json'; frozen.write_text(json.dumps({'spec_sha256':'spec-a','models':[]}))
    study.read(sha,'test',ml.pin(frozen))
    with pytest.raises(ValueError,match='already read'): study.read(sha,'test',ml.pin(frozen))
    with pytest.raises(ValueError,match='not claimed'): study.read('cd'*32,'test',ml.pin(frozen))
    with pytest.raises(ValueError,match='already read'):
        ml_exposure.Study('spec-a').claim(identity,'test_split',schedule={sha:['test']})


def test_unread_claim_can_be_retried_by_the_same_study(tmp_path):
    identity=ml_exposure.identity(cfx.data(tmp_path/'p.npz'),tmp_path); sha=identity['sha256']
    first=ml_exposure.Study('spec-b'); first.claim(identity,'test_split',schedule={sha:['test']})
    first.close('failed')
    retry=ml_exposure.Study('spec-c'); retry.claim(identity,'test_split',schedule={sha:['test']})
    assert ledger(sha)['attempts']==2 and ledger(sha)['prior_unread'][0]['reads']==0
    with pytest.raises(ValueError,match='another active study'):
        ml_exposure.Study('spec-d').claim(identity,'test_split',schedule={sha:['test']})


def test_region_label_metrics_stay_blinded_until_unblind(tmp_path, monkeypatch):
    """Region-label Brier/ECE over signal-region scores measure the search itself."""
    t=cfx.fixture(tmp_path); t['inner_selection']['initializations']=1
    t['splits']['fold_salts']=['fixed']; t['splits']['split_sha256']=ml.split_digest(t['splits'])
    cfx.bind_plan(t,tmp_path); ml.run(t,tmp_path,tmp_path/'out')
    r=json.loads((tmp_path/'out/ml/receipt.json').read_text())
    assert r['observed_statistic'] is None
    assert all(a['calibration']['ece'] is None and a['calibration']['brier'] is None
               and a['calibration']['state']=='blinded' for a in r['arms'])
    assert all(row['scope']=='sidebands' for row in r['checks']['score_region_correlation']['rows'])
    assert r['summary']['ece']['method']['0']['mean'] is None
    ml.validate_receipt(r,t,tmp_path/'out/ml')
    r['arms'][0]['calibration'].update(ece=.1,brier=.2)
    with pytest.raises(ValueError,match='blind'):
        ml.validate_receipt(r,t,tmp_path/'out/ml')


def test_region_label_metrics_stay_blinded_without_authenticated_gate(tmp_path, monkeypatch):
    t=cfx.fixture(tmp_path); t['inner_selection']['initializations']=1
    t['splits']['fold_salts']=['fixed']; t['splits']['split_sha256']=ml.split_digest(t['splits'])
    t['null_calibration']={'toys':1,'scope':'whole_procedure','datasets':[
        cfx.data(tmp_path/'null.npz',seed=50,prefix='null')],'claim_below':None,'unblind':True}
    cfx.bind_plan(t,tmp_path)
    cfx.install_gate_provider(monkeypatch)
    ml.run(t,tmp_path,tmp_path/'out')
    r=json.loads((tmp_path/'out/ml/receipt.json').read_text())
    assert r['observed_statistic'] is None
    assert all(a['calibration']['ece'] is None and a['calibration']['state']=='blinded' for a in r['arms'])
    assert r['gates'][0]['verdict']=='blocked'

# Pass 3: every role is governed by logical identities and a frozen schedule.
@pytest.mark.parametrize('variant', ['compressed', 'reordered', 'subset', 'renamed', 'values'])
def test_logical_population_reencoding_refused(tmp_path, variant):
    import numpy as np
    p=cfx.data(tmp_path/'population.npz')
    with np.load(p['path']) as z: arrays={k:z[k] for k in z.files}
    identity=ml_exposure.identity(p, tmp_path)
    study=ml_exposure.Study('a'*64)
    study.claim_all([(identity, 'crossfit_population')], schedule={identity['sha256']: ['nominal']})
    frozen=tmp_path/'freeze.json'; frozen.write_text(json.dumps({'spec_sha256':'a'*64,'models':[]}))
    study.read(identity['sha256'], 'nominal', ml.pin(frozen)); study.close('complete')
    if variant in ('reordered','subset'):
        arrays={k:v[::-1] if variant=='reordered' else v[:100] for k,v in arrays.items()}
    if variant in ('renamed','values'): arrays['group_id']=np.array([f'new-{i}' for i in range(len(arrays['x']))])
    if variant=='values': arrays['event_id']=arrays['group_id'].copy()
    (np.savez_compressed if variant=='compressed' else np.savez)(tmp_path/'copy.npz', **arrays)
    other=ml_exposure.identity(ml.pin(tmp_path/'copy.npz'), tmp_path)
    with pytest.raises(ValueError, match='already claimed'):
        ml_exposure.Study('b'*64).claim_all([(other, 'null_toy')], schedule={other['sha256']: ['toy']})


def test_read_unscheduled_context_and_after_close_refused(tmp_path):
    identity=ml_exposure.identity(cfx.data(tmp_path/'population.npz'),tmp_path)
    study=ml_exposure.Study('a'*64)
    study.claim_all([(identity,'null_toy')],schedule={identity['sha256']:['toy']})
    p=tmp_path/'freeze.json'; p.write_text(json.dumps({'spec_sha256':'a'*64,'models':[]}))
    with pytest.raises(ValueError,match='schedule'): study.read(identity['sha256'],'invented',ml.pin(p))
    study.close('failed')
    with pytest.raises(ValueError,match='closed'): study.read(identity['sha256'],'toy',ml.pin(p))


def test_spent_population_as_null_toy_refused_before_training(tmp_path, monkeypatch):
    a=tmp_path/'a'; a.mkdir(); t=cfx.fixture(a); ml.run(t,a,a/'out')
    b=tmp_path/'b'; b.mkdir(); other=cfx.fixture(b,prefix='fresh',seed=31)
    other['null_calibration']={'toys':1,'scope':'whole_procedure','datasets':t['dataset']['pins'], 'claim_below':None,'unblind':False}
    cfx.bind_plan(other,b)
    monkeypatch.setattr(cf,'fit_model',lambda *a,**kw:pytest.fail('trained on spent toy'))
    with pytest.raises(ValueError,match='already claimed'): ml.run(other,b,b/'out')


def test_reference_overlap_refused_before_any_read(tmp_path,monkeypatch):
    t=cfx.fixture(tmp_path); t['checks']['reference']=t['dataset']['pins'][0]; cfx.bind_plan(t,tmp_path)
    monkeypatch.setattr(cf,'fit_model',lambda *a,**kw:pytest.fail('trained before overlap check'))
    with pytest.raises(ValueError,match='overlap'): ml.run(t,tmp_path,tmp_path/'out')
    assert not list(ml_exposure.root().glob('*.json'))


@pytest.mark.parametrize('registry,refusal',[('absent','unblind: decision_gate provider unavailable'),
                                             ('inactive','unblind: no active decision provider')])
def test_unblind_without_provider_refused_before_claim(tmp_path,monkeypatch,registry,refusal):
    import sys
    from ravel.workflow import decision_gate
    t=cfx.fixture(tmp_path)
    t['null_calibration']={'toys':1,'scope':'whole_procedure','datasets':[cfx.data(tmp_path/'toy.npz',prefix='toy')], 'claim_below':None,'unblind':True}
    cfx.bind_plan(t,tmp_path)
    monkeypatch.setattr(cf,'fit_model',lambda *a,**kw:pytest.fail('trained before provider admission'))
    monkeypatch.setattr(cf,'load_events',lambda *a,**kw:pytest.fail('data read before provider admission'))
    # The decision gate registers providers for every gate, so the refused case is stated
    # here: the gate module is not installed, or its registry has no active unblind provider.
    assert any(p['active'] for p in decision_gate.providers('unblind'))
    if registry=='absent':
        monkeypatch.setitem(sys.modules,'ravel.workflow.decision_gate',None)
    else:
        registered=decision_gate.providers
        monkeypatch.setattr(decision_gate,'providers',lambda gate:[{**p,'active':False} for p in registered(gate)])
    with pytest.raises(ValueError,match=refusal): ml.run(t,tmp_path,tmp_path/'out')
    assert not list(ml_exposure.root().glob('*.json'))


def test_toy_overlapping_reference_refused_before_training(tmp_path,monkeypatch):
    t=cfx.fixture(tmp_path); reference=cfx.data(tmp_path/'reference.npz',seed=83,prefix='reference')
    t['checks']['reference']=reference
    t['null_calibration']={'toys':1,'scope':'whole_procedure','datasets':[reference],'claim_below':None,'unblind':False}
    cfx.bind_plan(t,tmp_path)
    monkeypatch.setattr(cf,'fit_model',lambda *a,**kw:pytest.fail('trained before full overlap matrix'))
    with pytest.raises(ValueError,match='overlap'): ml.run(t,tmp_path,tmp_path/'out')


def test_reference_overlapping_oracle_pool_refused(tmp_path):
    t=cfx.fixture(tmp_path); reference=cfx.data(tmp_path/'reference.npz',seed=83,prefix='reference')
    t['checks']['reference']=reference
    t['baselines'].append({'id':'oracle','kind':'supervised_oracle','architecture':'logistic','backend':'numpy','config':{'learning_rate':.1},'training_pool':reference})
    cfx.bind_plan(t,tmp_path)
    with pytest.raises(ValueError,match='overlap'): ml.run(t,tmp_path,tmp_path/'out')


def test_supervised_shared_group_across_splits_refused(tmp_path):
    import numpy as np
    t=sup.fixture(tmp_path); p=t['splits']['files']['val']
    with np.load(p['path']) as z: arrays={k:z[k] for k in z.files}
    arrays['group_id'][0]=0; np.savez(p['path'],**arrays)
    t['splits']['files']['val']=ml.pin(p['path']); t['splits']['split_sha256']=ml.split_digest(t['splits'])
    t['dataset']['pins']=list(t['splits']['files'].values()); t['dataset']['manifest_sha256']=ml.digest({k:v for k,v in t['dataset'].items() if k!='manifest_sha256'})
    plan=json.loads(open(t['placement']['backend_plan']['path']).read()); plan['inputs']=t['dataset']['pins']+[t['dataset']['population_index']]; plan['spec']['inputs']=plan['inputs']
    plan['plan_sha256']=ml.digest({k:v for k,v in plan.items() if k!='plan_sha256'})
    path=tmp_path/'backend.json'; path.write_text(json.dumps(plan)); t['placement']['backend_plan']=ml.pin(path)
    with pytest.raises(ValueError,match='overlap'): ml.run(t,tmp_path,tmp_path/'out')


def test_supervised_test_file_missing_partition_events_refused(tmp_path):
    import numpy as np
    t=sup.fixture(tmp_path); t['splits']['method']='hash'; census=[]
    for name in ('train','val','test'):
        ids=[str(i) for i in range(10000) if ml.hash_partition(str(i),17,t['splits']['fractions'])==name][:41]
        census.extend({'event_id':i,'group_id':i} for i in ids)
        p=t['splits']['files'][name]
        with np.load(p['path']) as z: arrays={k:z[k] for k in z.files}
        arrays.update(event_id=np.array(ids[:40]),group_id=np.array(ids[:40])); np.savez(p['path'],**arrays)
        t['splits']['files'][name]=ml.pin(p['path'])
    path=tmp_path/'census.json'; path.write_text(json.dumps(census)); t['dataset']['population_index']=ml.pin(path)
    t['splits']['split_sha256']=ml.split_digest(t['splits']); t['dataset']['pins']=list(t['splits']['files'].values())
    t['dataset']['manifest_sha256']=ml.digest({k:v for k,v in t['dataset'].items() if k!='manifest_sha256'})
    plan=ml.eb.prepare({'schema_version':1,'backend':'native','stage':'ml-training','argv':[__import__('sys').executable,'-m','ravel.physics.science_worker',str(tmp_path)],'inputs':t['dataset']['pins']+[t['dataset']['population_index']],
        'outputs':[{'name':'result.json','destination':'outputs/result.json','kind':'file'}], 'resources':{'cpus':1,'memory_mib':256,'wall_seconds':120}})
    path=tmp_path/'backend.json'; path.write_text(json.dumps(plan)); t['placement']['backend_plan']=ml.pin(path)
    with pytest.raises(ValueError,match='incomplete hash partition'): ml.run(t,tmp_path,tmp_path/'out')


def test_receipt_bytes_differ_from_ledger_pin_rejected(tmp_path):
    t=cfx.fixture(tmp_path); ml.run(t,tmp_path,tmp_path/'out'); path=tmp_path/'out/ml/receipt.json'
    r=json.loads(path.read_text()); r['scope']='forged scope'; path.write_text(json.dumps(r))
    with pytest.raises(ValueError,match='ledger pin'): ml.validate_receipt(r,t,path.parent)


def test_sealed_artifacts_missing_refuses_validation(tmp_path,monkeypatch):
    from ravel.physics import ml_custody
    t=cfx.fixture(tmp_path); ml.run(t,tmp_path,tmp_path/'out')
    r=json.loads((tmp_path/'out/ml/receipt.json').read_text())
    monkeypatch.setattr(ml_custody,'_STORE',{})
    with pytest.raises(ValueError,match='sealed artifacts unavailable'): ml.validate_receipt(r,t,tmp_path/'out/ml')


@pytest.mark.parametrize('family', ['crossfit', 'supervised'])
def test_forged_receipt_without_written_file_rejected(tmp_path, family):
    t=cfx.fixture(tmp_path) if family=='crossfit' else sup.fixture(tmp_path)
    ml.run(t,tmp_path,tmp_path/'out'); path=tmp_path/'out/ml/receipt.json'
    r=json.loads(path.read_text()); r['scope' if family=='crossfit' else 'device']='forged'; path.unlink()
    with pytest.raises(ValueError,match='ledger'): ml.validate_receipt(r,t,path.parent)


def _ids(prefix, n=4):
    events=[f'{prefix}{i}' for i in range(n)]
    return ml_exposure.manifest_identity({'event_ids':events,'group_ids':[e+'g' for e in events]},'0'*64)


def _freeze(tmp_path, spec, name='freeze.json'):
    path=tmp_path/name; path.write_text(json.dumps({'spec_sha256':spec,'models':[]})); return ml.pin(path)


def test_withheld_split_takes_one_read_across_contexts(tmp_path):
    test=_ids('t')
    with pytest.raises(ValueError,match='exactly one scheduled read'):
        ml_exposure.Study('a'*64).claim(test,'test_split',schedule={test['sha256']:['confirm','attribution']})
    assert not list(ml_exposure.root().glob('*.json'))


def test_independent_events_with_equal_values_are_not_overlap(tmp_path):
    import numpy as np
    common=dict(x=np.array([[1.,2.],[3.,4.]]),weight=np.ones(2))
    np.savez(tmp_path/'a.npz',event_id=np.array(['a0','a1']),group_id=np.array(['ga0','ga1']),**common)
    np.savez(tmp_path/'b.npz',event_id=np.array(['b0','b1','b2']),group_id=np.array(['gb0','gb1','gb2']),
             x=np.array([[1.,2.],[5.,6.],[7.,8.]]),weight=np.ones(3))
    a=ml_exposure.identity(ml.pin(tmp_path/'a.npz'),tmp_path); b=ml_exposure.identity(ml.pin(tmp_path/'b.npz'),tmp_path)
    ml_exposure.Study('a'*64).claim(a,'test_split',schedule={a['sha256']:['test']})
    ml_exposure.Study('b'*64).claim(b,'test_split',schedule={b['sha256']:['test']})
    assert ledger(b['sha256'])['value_collisions']==[{'sha256':a['sha256'],'values':1}]


def test_adaptive_reuse_is_admitted_and_withheld_reuse_refused(tmp_path):
    train=_ids('r'); first=ml_exposure.Study('a'*64)
    first.claim(train,'train_split',schedule={train['sha256']:['train']})
    first.read(train['sha256'],'train',_freeze(tmp_path,'a'*64)); first.close('failed')
    retry=ml_exposure.Study('a'*64)
    retry.claim(train,'train_split',schedule={train['sha256']:['train']})
    assert ledger(train['sha256'])['prior_unread'][0]['class']=='adaptive_reuse'
    retry.read(train['sha256'],'train',_freeze(tmp_path,'a'*64,'second.json')); retry.close('complete')
    with pytest.raises(ValueError,match='already'):
        ml_exposure.Study('b'*64).claim(train,'test_split',schedule={train['sha256']:['test']})


def test_resumed_claim_reuses_its_persisted_token(tmp_path):
    test=_ids('s'); token='ab'*16
    ml_exposure.Study('a'*64,token=token).claim(test,'test_split',schedule={test['sha256']:['confirm']})
    resumed=ml_exposure.Study('a'*64,token=token)
    resumed.claim(test,'test_split',schedule={test['sha256']:['confirm']})
    resumed.read(test['sha256'],'confirm',_freeze(tmp_path,'a'*64))
    assert len(ledger(test['sha256'])['reads'])==1
    with pytest.raises(ValueError,match='already'):
        ml_exposure.Study('a'*64,token='cd'*16).claim(test,'test_split',schedule={test['sha256']:['confirm']})


def _entries(sha):
    record=ledger(sha)
    return len(record['reads']),len(record.get('replays',[]))


def test_supervised_test_identity_comes_from_the_index_before_any_test_decode(tmp_path, monkeypatch):
    t=sup.fixture(tmp_path); test_sha=t['splits']['files']['test']['sha256']
    decoded=[]
    original_identity=ml_exposure.identity
    monkeypatch.setattr(ml_exposure,'identity',lambda pin,base: decoded.append(pin['sha256']) or original_identity(pin,base))
    original_load=ml.load_split
    def load(task,base,name):
        if name=='test':
            assert (tmp_path/'out/ml/frozen.json').is_file()
            assert _entries(test_sha)==(1,0)
        return original_load(task,base,name)
    monkeypatch.setattr(ml,'load_split',load)
    ml.run(t,tmp_path,tmp_path/'out')
    assert test_sha not in decoded


def test_supervised_ledger_counts_one_charge_per_read_on_every_path(tmp_path, monkeypatch):
    # A training-only failure charges the adaptive reads and leaves the test unread.
    failed=tmp_path/'failed'; failed.mkdir(); u=sup.fixture(failed); files=u['splits']['files']
    def exhausted(*a): raise ValueError('training wall budget exhausted')
    with monkeypatch.context() as patch:
        patch.setattr(ml.ml_backends,'fit',exhausted)
        with pytest.raises(ValueError,match='wall budget'): ml.run(u,failed,failed/'out')
    assert [_entries(files[n]['sha256']) for n in ('train','val','test')]==[(1,0),(1,0),(0,0)]
    # The retry rereads the adaptive splits under a new claim and charges the test once.
    t=sup.fixture(tmp_path); files=t['splits']['files']
    ml.run(t,tmp_path,tmp_path/'out')
    assert [_entries(files[n]['sha256']) for n in ('train','val','test')]==[(1,0),(1,0),(1,0)]
    receipt=json.loads((tmp_path/'out/ml/receipt.json').read_text())
    ml.validate_receipt(receipt,t,tmp_path/'out/ml')
    ml.validate_receipt(receipt,t,tmp_path/'out/ml')
    assert _entries(files['test']['sha256'])==(1,2)
    assert [_entries(files[n]['sha256']) for n in ('train','val')]==[(1,0),(1,0)]


def test_supervised_test_file_differing_from_the_index_fails_after_the_charge(tmp_path):
    import numpy as np
    t=sup.fixture(tmp_path); p=t['splits']['files']['test']
    with np.load(p['path']) as z: arrays={k:z[k] for k in z.files}
    arrays['event_id']=arrays['event_id']+1000; arrays['group_id']=arrays['group_id']+1000
    np.savez(p['path'],**arrays); t['splits']['files']['test']=ml.pin(p['path'])
    t['splits']['split_sha256']=ml.split_digest(t['splits']); t['dataset']['pins']=list(t['splits']['files'].values())
    t['dataset']['manifest_sha256']=ml.digest({k:v for k,v in t['dataset'].items() if k!='manifest_sha256'})
    plan=json.loads(open(t['placement']['backend_plan']['path']).read())
    plan['inputs']=t['dataset']['pins']+[t['dataset']['population_index']]; plan['spec']['inputs']=plan['inputs']
    plan['plan_sha256']=ml.digest({k:v for k,v in plan.items() if k!='plan_sha256'})
    path=tmp_path/'backend.json'; path.write_text(json.dumps(plan)); t['placement']['backend_plan']=ml.pin(path)
    with pytest.raises(ValueError,match='differ from the population index'): ml.run(t,tmp_path,tmp_path/'out')
    record=ledger(t['splits']['files']['test']['sha256'])
    assert record['state']=='failed' and len(record['reads'])==1
