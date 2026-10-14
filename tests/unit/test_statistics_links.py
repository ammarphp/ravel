"""Small synthetic workspace fits and shared-yield handoff controls."""
from copy import deepcopy
import json
from pathlib import Path

import jsonpatch
import pytest

FIXTURES = Path(__file__).parents[1] / 'fixtures/statistics-core'


def workspace():
    background = json.loads((FIXTURES / 'background.json').read_text())
    patches = json.loads((FIXTURES / 'patchset.json').read_text())
    return jsonpatch.apply_patch(background, patches['patches'][0]['patch'])


def test_nonfinite_profile_coordinates_are_refused():
    from ravel.physics.statistics_links import profile_likelihood
    with pytest.raises(ValueError, match='finite'):
        profile_likelihood(workspace(), poi_values=[float('nan')])


def test_profile_record_from_workspace_without_native_tool(monkeypatch):
    from ravel.physics.statistics_links import profile_likelihood
    import subprocess
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('native process'))
    result = profile_likelihood(workspace(), poi_values=[0,1,2])
    assert result['kind'] == 'profile-likelihood'
    assert result['status'] == 'passed'
    assert result['physics_validated'] is False
    assert result['poi']['name'] == 'strength'
    assert abs(result['best_fit']['parameters'][result['poi']['index']]) < 1e-4
    assert [row['poi'] for row in result['profiles']] == [0,1,2]
    assert result['profiles'][0]['delta_twice_nll'] == pytest.approx(0, abs=1e-6)
    assert result['profiles'][2]['delta_twice_nll'] > result['profiles'][1]['delta_twice_nll'] > 0
    json.dumps(result, allow_nan=False)


def test_fit_failure_cannot_be_a_successful_record(monkeypatch):
    from ravel.physics.statistics_links import profile_likelihood
    import pyhf
    def fail(*a, **k): raise RuntimeError('planted optimizer failure')
    monkeypatch.setattr(pyhf.infer.mle, 'fit', fail)
    with pytest.raises(RuntimeError, match='planted'):
        profile_likelihood(workspace(), poi_values=[0])


def yields():
    from ravel.physics.binned_values import build
    return build(axes=[{'name':'coordinate','unit':''}], bins=[{'low':[0],'high':[1],'value':3,'sumw2':2}, {'low':[1],'high':[2],'value':4,'sumw2':5}], unit='events', normalization={'kind':'absolute'}, provenance={'bin_ids':['a','b']}, covariance=[[2,1],[1,5]])


def test_correlated_yields_not_silently_diagonalized_for_search():
    from ravel.physics.statistics_links import search_yields
    with pytest.raises(ValueError, match='correlat'):
        search_yields(yields())


def test_measurement_link_preserves_bin_identity_units_and_covariance():
    from ravel.physics.statistics_links import measurement_prediction
    source = yields()
    result = measurement_prediction(source)
    assert result['prediction'] == {'bin_ids':['a','b'],'unit':'events','values':[3,4]}
    assert result['covariance']['matrix'] == [[2,1],[1,5]]
    assert result['covariance']['unit'] == '(events)^2'
    assert source == yields()


def test_search_link_requires_absolute_integrated_moments():
    from ravel.physics.statistics_links import search_yields
    source = yields(); source['covariance'] = [[2,0],[0,5]]
    assert search_yields(source) == {'values':[3,4], 'sumw2':[2,5]}
    source['normalization']['kind'] = 'shape'
    with pytest.raises(ValueError, match='absolute'):
        search_yields(source)


def test_actual_yield_hub_projection_preserves_already_scaled_moments():
    from ravel.physics.binned_values import from_quantity
    from ravel.physics.quantities import calculate
    from ravel.physics.statistics_links import search_yields, measurement_prediction
    contract = {'schema_version':1, 'axes':[{'name':'coordinate','unit':'1'}],
                'bins':[{'id':'a','low':[0],'high':[1]}], 'weight_names':['nominal'],
                'input_weight_unit':'events', 'representation':'integrated',
                'normalization':{'kind':'absolute','scale':2,'unit':'events'}}
    quantity = calculate(contract, [{'event_id':'e', 'group_id':'g', 'shard_id':'s',
                                     'fills':[[0.5]], 'weights':{'nominal':3}}])
    doc = from_quantity(quantity, 'nominal')
    assert search_yields(doc) == {'values':[6.], 'sumw2':[36.]}
    assert measurement_prediction(doc)['covariance']['matrix'] == [[36.]]


def test_profile_requires_patch_parity_when_source_contract_supplied():
    from ravel.physics.statistics_links import profile_likelihood
    source = {'background':json.loads((FIXTURES/'background.json').read_text()), 'patchset':json.loads((FIXTURES/'patchset.json').read_text()), 'patch_name':'nominal', 'record_id':'7'}
    model = workspace(); model['channels'][1]['samples'].pop()
    with pytest.raises(ValueError, match='region_b'):
        profile_likelihood(model, poi_values=[0], released=source)


def test_profile_restores_callers_pyhf_backend():
    from ravel.physics.statistics_links import profile_likelihood
    import pyhf
    before = pyhf.get_backend()
    profile_likelihood(workspace(), poi_values=[1])
    assert pyhf.get_backend() == before


def test_profile_fits_use_the_guarded_optimizer(monkeypatch):
    from ravel.physics.statistics_links import profile_likelihood
    from ravel.physics import pyhf_exclude as engine
    import pyhf
    seen = []
    original = pyhf.infer.mle.fixed_poi_fit
    def spy(*a, **k):
        seen.append(type(pyhf.get_backend()[1]))
        return original(*a, **k)
    monkeypatch.setattr(pyhf.infer.mle, 'fixed_poi_fit', spy)
    result = profile_likelihood(workspace(), poi_values=[1])
    assert seen and all(issubclass(kind, engine.robust_optimizer) for kind in seen)
    assert result['optimizer']['name'] == 'robust_optimizer'
    assert result['optimizer']['n_minimizations'] >= 2
    assert result['optimizer']['escalated'] is False
