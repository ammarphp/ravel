"""Pass-one review regressions on synthetic data."""
import json
from pathlib import Path
import numpy as np
import pytest
from test_ml_training import fixture, state
from ravel.physics import ml_training as ml


def test_retry_after_training_only_failure_is_admitted(tmp_path, monkeypatch):
    # No evaluation read occurred and the spec is unchanged, so the retry runs.
    from ravel.physics import ml_exposure
    task = fixture(tmp_path)
    fit = ml.ml_backends.fit
    def failed(*args):
        raise ValueError('before test')
    monkeypatch.setattr(ml.ml_backends, 'fit', failed)
    with pytest.raises(ValueError, match='before test'):
        ml.run(task, tmp_path, tmp_path/'failed')
    monkeypatch.setattr(ml.ml_backends, 'fit', fit)
    assert ml.run(task, tmp_path, tmp_path/'retry')['status'] == 'passed'
    record = json.loads(next((tmp_path/'ml-exposure').glob('*.json')).read_text())
    assert record['test_reads'] == 1 and record['state'] == 'complete'
    ledger = [json.loads(p.read_text()) for p in ml_exposure.root().glob('*.json')]
    train = next(r for r in ledger if r['roles'] == ['train_split'])
    assert train['prior_unread'][0]['class'] == 'adaptive_reuse'
    with pytest.raises(ValueError, match='already.*spent'):
        ml.run(task, tmp_path, tmp_path/'again')


def test_cut_baseline_never_trains(tmp_path, monkeypatch):
    task = fixture(tmp_path)
    task['baselines'] = [{'id': 'cut', 'kind': 'cut_based',
                          'spec': {'feature': 'a', 'threshold': 0., 'direction': 'above'}}]
    fit = ml.ml_backends.fit
    calls = []
    def spy(arm, *args):
        calls.append(arm['id'])
        return fit(arm, *args)
    monkeypatch.setattr(ml.ml_backends, 'fit', spy)
    ml.run(task, tmp_path, tmp_path/'out')
    receipt = json.loads((tmp_path/'out/ml/receipt.json').read_text())
    assert calls == ['nonlinear'] * 3
    assert all(a['epochs'] == 0 for a in receipt['arms'] if a['id'] == 'cut')


def test_figure_lint_and_curve_frame(tmp_path, monkeypatch):
    from ravel.plotting import mplhep_style as house
    calls = []
    original = house.lint_figure
    def spy(fig, *args, **kwargs):
        calls.append(fig)
        assert all(line.get_zorder() > 2.5 and not line.get_clip_on()
                   for ax in fig.axes for line in ax.lines)
        return original(fig, *args, **kwargs)
    monkeypatch.setattr(house, 'lint_figure', spy)
    ml.run(fixture(tmp_path), tmp_path, tmp_path/'out')
    assert len(calls) == 2


def test_pinned_model_config_and_relative_backend_inputs(tmp_path, monkeypatch):
    task=fixture(tmp_path)
    config=tmp_path/'model-config.json'; config.write_text(json.dumps(task['models'][0]['config']))
    task['models'][0]['config']=ml.pin(config)
    task['models'][0]['code']=ml.pin(ml.ml_backends.__file__)
    p=Path(task['placement']['backend_plan']['path']); plan=json.loads(p.read_text())
    for row in plan['inputs']: row['path']=Path(row['path']).name
    plan['plan_sha256']=ml.digest({k:v for k,v in plan.items() if k!='plan_sha256'})
    p.write_text(json.dumps(plan)); task['placement']['backend_plan']=ml.pin(p)
    monkeypatch.chdir(tmp_path.parent)
    assert config in ml.inputs(task,tmp_path)
    ml.run(task,tmp_path,tmp_path/'out')
    config.write_text('{}')
    with pytest.raises(ValueError,match='pin|sha256'):
        ml.inputs(task,tmp_path)
