"""Synthetic controls: governed training and cross-fitting ask for capacity as a nested sub-stage."""
from contextlib import contextmanager

import pytest

from ravel.physics import ml_crossfit as cf
from ravel.physics import ml_training as ml

import test_ml_crossfit
import test_ml_training


class Reached(Exception):
    pass


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path/'state'))


def recorder(monkeypatch):
    calls = []

    @contextmanager
    def capacity(plan, holder, **kwargs):
        calls.append((holder, kwargs))
        raise Reached
        yield

    monkeypatch.setattr(ml.eb, 'capacity', capacity)
    return calls


def test_training_requests_capacity_as_a_nested_sub_stage(tmp_path, monkeypatch):
    calls = recorder(monkeypatch)
    with pytest.raises(Reached):
        ml.run(test_ml_training.fixture(tmp_path), tmp_path, tmp_path/'out')
    assert calls == [(f'{tmp_path}:ml-training', {'nested': True})]
    assert not (tmp_path/'ml-exposure').exists()


def test_cross_fitting_requests_capacity_as_a_nested_sub_stage(tmp_path, monkeypatch):
    calls = recorder(monkeypatch)
    with pytest.raises(Reached):
        cf.run(test_ml_crossfit.fixture(tmp_path), tmp_path, tmp_path/'out')
    assert calls == [(f'{tmp_path}:ml-crossfit', {'nested': True})]
    assert not (tmp_path/'ml-exposure').exists()
