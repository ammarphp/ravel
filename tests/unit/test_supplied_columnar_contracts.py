"""Fictional contracts exercise one code path with different supplied inputs."""
from copy import deepcopy
import pytest
from ravel.physics import dataset_query_quantities_core as core
from test_dataset_query_quantities import population_fixture


def supplied(tmp_path, name, count, prefix, components):
    ds, analysis, returned, events = population_fixture(tmp_path)
    analysis['task_id'] = name
    analysis['observables'] = analysis['observables'][:count]
    for event in events:
        event['fills'] = {k: v for k, v in event['fills'].items()
                          if k in {o['id'] for o in analysis['observables']}}
    ds['datasets'][0]['did'] = name + ':dataset'
    if components:
        members = ds['datasets'][0]['members']
        ds['datasets'] = [{'did': name + ':left', 'members': members[:1]},
                          {'did': name + ':right', 'members': members[1:]}]
    for observable in analysis['observables']:
        observable['quantity']['axes'][0]['name'] = name + '-coordinate'
        observable['quantity']['bins'] = ([{'id': 'wide', 'low': [0], 'high': [8]}] if not components
            else [{'id': 'a', 'low': [0], 'high': [1]}, {'id': 'b', 'low': [1], 'high': [2]},
                  {'id': 'c', 'low': [2], 'high': [4]}])
    ds['prefix'] = None if prefix is None else {'events': prefix, 'source': analysis['source_question']}
    analysis['event_domain'] = {'datasets': [d['did'] for d in ds['datasets']], 'prefix': deepcopy(ds['prefix'])}
    analysis['dataset_components'] = components
    analysis['presentation'] = {'plot_kind': 'dataset_stack' if components else 'histogram', 'formats': ['pdf', 'png']}
    returned['source_dataset_sha256'] = core.digest(ds)
    return ds, analysis, returned, events


@pytest.mark.parametrize('name,count,prefix,components', [
    ('fictional-amber', 1, None, False), ('fictional-violet', 2, 2, True)])
def test_supplied_identity_observables_domain_and_presentation(tmp_path, name, count, prefix, components):
    ds, analysis, returned, events = supplied(tmp_path, name, count, prefix, components)
    result = core.analyze(analysis, ds, returned, events, max_rows=100, max_products=1000)
    assert len(result['observables']) == count
    assert result['source_prefix_events'] == (4 if prefix is None else prefix)
    assert (result['dataset_components'] is not None) == components
    assert result['plot_kind'] == ('dataset_stack' if components else 'histogram')
    assert result['observables']['mass']['values']['nominal'] == ([0, 0, 0] if components else [3])
    if components:assert len(result['dataset_components']['did_order']) == 2
    renamed = deepcopy(analysis)
    renamed['task_id'] = 'fictional-unrelated'
    assert core.analyze(renamed, ds, returned, events, max_rows=100, max_products=1000) == result


@pytest.mark.parametrize('field', ['event_domain', 'dataset_components', 'source_question'])
def test_missing_supplied_contract_is_typed(tmp_path, field):
    _, analysis, _, _ = supplied(tmp_path, 'fictional-amber', 1, None, False)
    del analysis[field]
    with pytest.raises(core.MissingColumnarInput, match=field):
        core.contract(analysis)


def test_declared_population_cannot_be_narrowed(tmp_path):
    ds, analysis, _, _ = supplied(tmp_path, 'fictional-amber', 1, None, False)
    analysis['event_domain']['datasets'].append('fictional-missing')
    with pytest.raises(ValueError, match='declared dataset'):
        core.original_domain(analysis, ds)
