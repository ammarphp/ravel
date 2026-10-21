"""P17: the staged ML executor's six stages and their executable reviewer items, on fictional fixture data.

No model, provider, network or native scientific tool: the stages are the installed RAVEL module run
in-process (``ml_stages.run_stage``) or as the command line a confined launch runs.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

from ravel.workflow import ml_checks, ml_stages

import p17_support as support


@pytest.fixture
def fixture_data(tmp_path):
    data = tmp_path / 'table.npz'
    return data, support.table(data)


def pipeline(tmp_path, document, data=None, digest=None):
    if data is None:
        data = tmp_path / 'table.npz'
        digest = support.table(data)
    return support.Pipeline(tmp_path / 'stages', document, data=data, digest=digest)


def test_P17_stages_complete_on_fixture_data_with_every_stage_receipted(tmp_path, fixture_data):
    run = pipeline(tmp_path, support.spec(), *fixture_data)
    assert run.all() is None
    for stage in ml_stages.STAGES:
        receipt = run.receipts[stage]
        assert receipt['status'] == 'completed', (stage, receipt)
        assert receipt['operation'] == f'ml-stage-{stage}' and receipt['placeholders'] == []
        assert receipt['physics_validated'] is False
        assert set(receipt['outputs']) == {p for p, _ in ml_stages.OUTPUTS[stage] if p != ml_stages.RECEIPT}
        assert (run.root / stage / ml_stages.RECEIPT).is_file()
    evaluation = run.record('evaluate', 'evaluation.json')
    assert evaluation['test_reads'] == 1 and evaluation['primary_arm'] == 'network'
    assert evaluation['summary']['network']['roc_auc']['seeds'] == 3
    assert evaluation['summary']['cut']['roc_auc']['spread'] is None  # one untrained replicate: no spread
    assert 0.6 < evaluation['summary']['network']['roc_auc']['mean'] < 1.0
    review = run.record('review', 'review.json')
    assert review['passed'] is True and set(r['id'] for r in review['items']) == set(ml_checks.ITEMS)
    card = (run.root / 'card' / 'outputs' / 'model_card.md').read_text()
    assert 'Primary arm: `network`' in card and 'physics' in card.lower()


def test_P17_training_never_reads_the_withheld_partition(tmp_path, fixture_data):
    run = pipeline(tmp_path, support.spec(), *fixture_data)
    for stage in ('admit', 'features'):
        assert run.run(stage)['status'] == 'completed'
    receipt = run.run('train', extra=['test'])
    assert receipt['status'] == 'refused' and receipt['codes'] == ['ml_withheld_partition_in_training']
    assert set(receipt['placeholders']) == {p for p, _ in ml_stages.OUTPUTS['train'] if p != ml_stages.RECEIPT}
    assert 'test' in receipt['inputs']  # recorded, never opened: no model was written
    with np.load(run.root / 'train' / 'outputs' / 'models.npz') as found:
        assert found.files == ['placeholder']
    for stage in ('features', 'card', 'review'):
        assert ml_stages.run_stage(stage, {'test': run.root / support.SOURCES['test']}, {},
                                   tmp_path / f'w-{stage}')['codes'] == ['ml_withheld_partition_read']


def test_P17_leaky_feature_refused_before_training(tmp_path):
    data = tmp_path / 'leaky.npz'
    digest = support.table(data, leak=True)
    run = pipeline(tmp_path, support.spec(), data, digest)
    receipt = run.all()
    assert receipt['stage'] == 'features' and receipt['status'] == 'refused'
    assert receipt['codes'] == ['ml_label_leakage']
    item = receipt['evidence']['item']
    assert item['id'] == 'check:ml-label-leakage' and item['evidence']['failing'] == ['f3']
    assert 'train' not in run.receipts  # nothing was trained
    downstream = run.run('train')
    assert downstream['status'] == 'refused' and downstream['codes'] == ['ml_input_chain_broken']


def test_P17_declared_separating_feature_cannot_clear_leakage_by_assertion(tmp_path):
    data = tmp_path / 'leaky.npz'
    digest = support.table(data, leak=True)
    document = support.spec(checks={'separating_features': [
        {'feature': 'f3', 'justification': 'a fictional detector quantity that separates the classes by design'}]})
    run = pipeline(tmp_path, document, data, digest)
    assert run.run('admit')['status'] == 'completed'
    assert run.run('features')['status'] == 'refused'
    leakage = run.record('features', 'features.json')['items'][0]
    assert leakage['verdict'] == 'unresolved' and leakage['evidence']['declared'] == ['f3']
    assert 'acknowledgement' in leakage['note']
    with pytest.raises(ValueError, match='justification'):
        ml_checks.thresholds({'checks': {'separating_features': [{'feature': 'f3', 'justification': 'short'}]}})


def test_P17_overtrained_fixture_refused_by_the_review(tmp_path):
    data = tmp_path / 'small.npz'
    digest = support.table(data, n=300, seed=5, noise=36)
    run = pipeline(tmp_path, support.overtrain_spec(), data, digest)
    receipt = run.all()
    assert receipt['stage'] == 'review' and receipt['status'] == 'refused'
    assert receipt['codes'] == ['ml_overtraining']
    evaluation = run.record('evaluate', 'evaluation.json')
    assert evaluation['overtraining']['verdict'] == 'fail'
    network = [r for r in evaluation['overtraining']['evidence']['replicates'] if r['replicate'].startswith('network')]
    assert network and all(r['auc_train'] > 0.99 and r['auc_gap'] > 0.2 for r in network)
    review = run.record('review', 'review.json')
    assert 'check:ml-overtraining' in review['failing'] and review['passed'] is False


def test_P17_rows_copied_across_the_split_refused_at_admission(tmp_path):
    data = tmp_path / 'copied.npz'
    digest = support.table(data, n=1200, copy_rows=300)
    run = pipeline(tmp_path, support.spec(), data, digest)
    receipt = run.run('admit')
    assert receipt['status'] == 'refused' and receipt['codes'] == ['ml_duplicate_rows']
    admission = run.record('admit', 'admission.json')
    assert admission['status'] == 'refused'
    assert {r['id']: r['verdict'] for r in admission['items']}['check:ml-duplicate-rows'] == 'fail'


def test_P17_explicit_split_sharing_a_group_refused(tmp_path):
    n = 900
    names = np.array(['train'] * 600 + ['validation'] * 150 + ['test'] * 150)
    data = tmp_path / 'explicit.npz'
    support.table(data, n=n, partition=names)
    arrays = dict(np.load(data))
    arrays['group_id'] = arrays['group_id'].copy()
    arrays['group_id'][-1] = arrays['group_id'][0]  # one group in both train and test
    with open(data, 'wb') as stream:
        np.savez(stream, **arrays)
    document = support.spec()
    document['split'] = {'method': 'explicit'}
    document['dataset']['columns']['partition'] = 'partition'
    run = pipeline(tmp_path, document, data, support.sha(data))
    receipt = run.run('admit')
    assert receipt['status'] == 'refused' and receipt['codes'] == ['ml_split_overlap']


def test_P17_budget_exhaustion_is_typed_and_keeps_completed_replicates(tmp_path, fixture_data):
    document = support.spec(epochs=100000, wall=1)
    run = pipeline(tmp_path, document, *fixture_data)
    for stage in ('admit', 'features'):
        assert run.run(stage)['status'] == 'completed'
    receipt = run.run('train')
    assert receipt['status'] == 'budget_exhausted' and receipt['codes'] == ['ml_training_budget_exhausted']
    training = run.record('train', 'training.json')
    states = {r['key']: r['status'] for r in training['replicates']}
    assert states['cut__seed_0'] == 'completed'
    assert 'budget_exhausted' in states.values() and 'not_started' in states.values()
    manifest, models = ml_stages.load_models(run.root / 'train' / 'outputs' / 'models.npz')
    assert manifest['replicates'] == ['cut__seed_0'] and set(models) == {'cut__seed_0'}
    assert run.run('evaluate')['codes'] == ['ml_input_chain_broken']


def test_P17_budget_above_the_approved_step_refused(tmp_path, fixture_data):
    run = pipeline(tmp_path, support.spec(wall=7200), *fixture_data)
    for stage in ('admit', 'features'):
        run.run(stage)
    receipt = run.run('train', wall_seconds=3600)
    assert receipt['status'] == 'refused' and receipt['codes'] == ['ml_budget_exceeds_step']


def test_P17_missing_backend_holds_with_its_typed_reason(tmp_path, fixture_data, monkeypatch):
    from ravel.physics import ml_backends
    run = pipeline(tmp_path, support.spec(), *fixture_data)
    for stage in ('admit', 'features'):
        run.run(stage)
    monkeypatch.setattr(ml_backends, 'available', lambda: {'numpy': False, 'sklearn': False, 'torch': False,
                                                             'torch-geometric': False})
    receipt = run.run('train')
    assert receipt['status'] == 'held' and receipt['codes'] == ['ml_backend_unavailable']


def test_P17_unavailable_accelerator_holds(tmp_path, fixture_data, monkeypatch):
    from ravel.physics import ml_backends
    document = support.spec(device='cuda:0')
    document['arms'][2].update(backend='torch')
    run = pipeline(tmp_path, document, *fixture_data)
    for stage in ('admit', 'features'):
        run.run(stage)
    monkeypatch.setattr(ml_backends, 'available', lambda: {'numpy': True, 'sklearn': False, 'torch': True,
                                                             'torch-geometric': False})
    try:
        import torch
        monkeypatch.setattr(torch.cuda, 'is_available', lambda: False)
    except ImportError:
        pass
    receipt = run.run('train')
    assert receipt['status'] == 'held' and receipt['codes'] == ['ml_device_unavailable']


def test_P17_changed_dataset_refused_against_its_intake_digest(tmp_path, fixture_data):
    data, digest = fixture_data
    run = pipeline(tmp_path, support.spec(), data, 'e' * 64)
    receipt = run.run('admit')
    assert receipt['status'] == 'refused' and receipt['codes'] == ['ml_dataset_changed']
    assert set(receipt['placeholders']) == {p for p, _ in ml_stages.OUTPUTS['admit'] if p != ml_stages.RECEIPT}


@pytest.mark.parametrize('change, text', [
    (lambda s: s.__setitem__('arms', [dict(s['arms'][2], id='other'), s['arms'][2]]), 'baseline'),
    (lambda s: s.__setitem__('primary_arm', 'cut'), 'primary_arm'),
    (lambda s: s.__setitem__('seeds', [1, 2]), 'seeds'),
    (lambda s: s['arms'][1].__setitem__('budget', {'epochs': 5}), 'arm-level budgets'),
    (lambda s: s['arms'][1].__setitem__('backend', 'unlisted'), 'allowlist'),
    (lambda s: s['split']['fractions'].__setitem__('test', 0.5), 'sum to one'),
    (lambda s: s.__setitem__('checks', {'leakage_auc_max': 0.5}), 'leakage_auc_max'),
    (lambda s: s.__setitem__('device', 'tpu'), 'device'),
])
def test_P17_invalid_specification_refused(tmp_path, fixture_data, change, text):
    document = support.spec()
    change(document)
    receipt = pipeline(tmp_path, document, *fixture_data).run('admit')
    assert receipt['status'] == 'refused' and receipt['codes'] == ['ml_spec_invalid']
    assert text in receipt['reason']


def test_P17_smoke_rung_trains_one_seed_briefly_and_never_feeds_the_evaluation(tmp_path, fixture_data):
    run = pipeline(tmp_path, support.spec(epochs=200), *fixture_data)
    for stage in ('admit', 'features'):
        run.run(stage)
    receipt = run.run('train', smoke=True, wall_seconds=1800)
    assert receipt['status'] == 'completed'
    training = run.record('train', 'training.json')
    assert training['mode'] == 'smoke' and training['seeds'] == [1]
    assert training['budget']['epochs'] == ml_stages.SMOKE['epochs']
    assert run.run('evaluate')['codes'] == ['ml_input_chain_broken']


def test_P17_csv_table_admits_the_same_partitions_as_npz(tmp_path, fixture_data):
    data, digest = fixture_data
    arrays = dict(np.load(data))
    csv_path = tmp_path / 'table.csv'
    names = [f'f{i}' for i in range(4)]
    with open(csv_path, 'w') as stream:
        stream.write(','.join([*names, 'y', 'weight', 'event_id', 'group_id']) + '\n')
        for i in range(len(arrays['y'])):
            row = [repr(float(v)) for v in arrays['x'][i]] + [repr(float(arrays['y'][i])), repr(float(arrays['weight'][i])),
                                                            str(arrays['event_id'][i]), str(arrays['group_id'][i])]
            stream.write(','.join(row) + '\n')
    first = pipeline(tmp_path / 'a', support.spec(), data, digest)
    document = support.spec()
    document['dataset']['format'] = 'csv'
    second = pipeline(tmp_path / 'b', document, csv_path, support.sha(csv_path))
    assert first.run('admit')['status'] == second.run('admit')['status'] == 'completed'
    one, two = first.record('admit', 'admission.json'), second.record('admit', 'admission.json')
    assert {p: v['identity_sha256'] for p, v in one['partitions'].items()} == {
        p: v['identity_sha256'] for p, v in two['partitions'].items()}


def test_P17_stage_command_line_runs_the_launch_layout(tmp_path, fixture_data):
    data, digest = fixture_data
    run_dir = tmp_path / 'run'
    spec_path = run_dir / 'steps' / 't01-spec' / 'outputs' / 'ml_study_spec.json'
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text(json.dumps(support.spec()))
    step = {'id': 't02-admit', 'parameters': {'launch': {'argv': [
        'python', '-I', '-m', 'ravel.workflow.ml_stages', 'admit', '--root', '../../../../..',
        '--input', 'spec=steps/t01-spec/outputs/ml_study_spec.json', '--dataset', str(data), '--dataset-sha256', digest,
        '--wall-seconds', '1800', '--threads=1']}}}
    found, workdir = support.launch(run_dir, step)
    assert found.returncode == 0, found.stderr[-2000:]
    assert json.loads(found.stdout.strip().splitlines()[-1]) == {'stage': 'admit', 'status': 'completed', 'codes': []}
    for path, _ in ml_stages.OUTPUTS['admit']:
        assert (workdir / path).is_file()
    receipt = json.loads((workdir / ml_stages.RECEIPT).read_text())
    assert receipt['inputs']['spec']['sha256'] == support.sha(spec_path)


def test_P17_a_crashing_stage_is_a_typed_failure_not_a_refusal(tmp_path):
    run_dir = tmp_path / 'run'
    spec_path = run_dir / 'steps' / 't01-spec' / 'outputs' / 'ml_study_spec.json'
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text('{not json')
    step = {'id': 't02-admit', 'parameters': {'launch': {'argv': [
        'python', '-I', '-m', 'ravel.workflow.ml_stages', 'admit', '--root', '../../../../..',
        '--input', 'spec=steps/t01-spec/outputs/ml_study_spec.json', '--wall-seconds', '60']}}}
    found, workdir = support.launch(run_dir, step)
    assert found.returncode == 1
    receipt = json.loads((workdir / ml_stages.RECEIPT).read_text())
    assert receipt['status'] == 'failed' and receipt['codes'] == ['ml_stage_exception']
    assert 'JSONDecodeError' in receipt['reason']


def test_P17_inputs_outside_the_run_root_are_refused():
    with pytest.raises(SystemExit):
        ml_stages._inputs(['spec=/etc/hosts'], '/run')
    with pytest.raises(SystemExit):
        ml_stages._inputs(['spec=../outside.json'], '/run')
    with pytest.raises(SystemExit):
        ml_stages._inputs(['spec=a.json', 'spec=b.json'], '/run')


# ---- the statistics behind the reviewer items ---------------------------------------------------

def test_P17_weighted_auc_reference_values():
    y = np.array([0, 0, 1, 1.0])
    w = np.ones(4)
    assert ml_checks.roc_auc(y, np.array([0.1, 0.2, 0.8, 0.9]), w) == 1.0
    assert ml_checks.roc_auc(y, np.array([0.9, 0.8, 0.2, 0.1]), w) == 0.0
    assert ml_checks.roc_auc(y, np.full(4, 0.5), w) == 0.5
    assert ml_checks.roc_auc(np.zeros(4), np.arange(4.0), w) is None
    # A weight doubles one background event's vote: the area is the weighted pair fraction.
    assert math.isclose(ml_checks.roc_auc(y, np.array([0.3, 0.6, 0.5, 0.9]), np.array([2.0, 1, 1, 1])), 5 / 6)


def test_P17_weighted_ks_reference_values():
    rng = np.random.default_rng(1)
    a = rng.normal(size=4000)
    same = ml_checks.ks_weighted(a, np.ones_like(a), a, np.ones_like(a))
    assert same['distance'] == 0 and same['p_value'] == 1.0
    apart = ml_checks.ks_weighted(a, np.ones_like(a), a + 10, np.ones_like(a))
    assert apart['distance'] == 1.0 and apart['p_value'] < 1.e-12
    assert math.isclose(ml_checks.kolmogorov_sf(1.3581), 0.05, abs_tol=5.e-4)
    weighted = ml_checks.ks_weighted(a, np.r_[np.ones(2000), np.zeros(2000)], a, np.ones_like(a))
    assert weighted['effective_counts'][0] == 2000.0


def test_P17_threshold_bounds_are_refused_not_clipped():
    assert ml_checks.thresholds({})['leakage_auc_max'] == 0.999
    for bad in ({'overtraining_auc_gap_max': 0.9}, {'min_class_count': 0}, {'unknown': 1},
                {'overtraining_ks_pvalue_min': True}):
        with pytest.raises(ValueError):
            ml_checks.thresholds({'checks': bad})


def test_P17_effective_statistics_cannot_be_replaced_by_raw_row_count():
    limits = ml_checks.thresholds({})
    counts = {'train': {'signal': 100, 'background': 100, 'signal_effective': 1.1, 'background_effective': 100}}
    result = ml_checks.statistics_sizing(counts, limits)
    assert result['verdict'] == 'fail' and result['evidence']['short'][0]['effective'] == 1.1


def test_P17_partition_column_is_a_reserved_leakage_feature():
    limits = ml_checks.thresholds({})
    result = ml_checks.label_leakage(np.array([[0.], [1.], [0.], [1.]]), np.array([0., 1., 1., 0.]),
                                    np.ones(4), ['split_name'], {'partition': 'split_name'}, limits)
    assert result['verdict'] == 'fail'


def test_P17_completed_replicate_checkpoint_is_digest_bound(tmp_path, fixture_data):
    run = pipeline(tmp_path, support.spec(), *fixture_data)
    for stage in ('admit', 'features', 'train'):
        assert run.run(stage)['status'] == 'completed'
    checkpoint = run.record('train', 'checkpoint.json')
    models = run.root / 'train/outputs/checkpoint.npz'
    assert checkpoint['status'] == 'partial'
    assert checkpoint['models_sha256'] == support.sha(models)
    assert len(checkpoint['completed']) == 7
    assert checkpoint['spec_sha256'] == ml_stages.digest(support.spec())
