"""Columnar population and rendering choices are supplied independently."""
from copy import deepcopy
from pathlib import Path
import pytest
from ravel.physics import dataset_query_quantities_core as core
from ravel.plotting.science_figures import render
from test_supplied_columnar_contracts import supplied


def test_population_is_supplied():
    root = Path(__file__).parents[2]
    assert not (root / 'src/ravel/data/iris/original-population.json').exists()


def test_missing_presentation_is_typed(tmp_path):
    _, analysis, _, _ = supplied(tmp_path, 'ANA-0001', 1, None, False)
    analysis.pop('presentation', None)
    with pytest.raises(core.MissingColumnarInput, match='presentation'): core.contract(analysis)


def test_two_contracts_change_identity_grid_population_and_output(tmp_path):
    for index, (count, prefix, components, formats) in enumerate([(1, None, False, ['png']), (2, 2, True, ['pdf'])]):
        case = tmp_path / str(index)
        case.mkdir()
        ds, analysis, returned, events = supplied(case, 'ANA-000' + str(index + 1), count, prefix, components)
        analysis['presentation'] = {'plot_kind': 'histogram', 'formats': formats}
        delivery = core.analyze(analysis, ds, returned, events, max_rows=100, max_products=1000)
        assert delivery['plot_kind'] == 'histogram'  # grouping never chooses the plot
        assert delivery['plot_formats'] == formats
        assert len(delivery['observables']) == count
        assert delivery['source_prefix_events'] == (4 if prefix is None else prefix)
        result = {'status': 'passed', 'task_id': analysis['task_id'], 'operation': 'analyze_returned_native_files',
                  'delivery': delivery, 'remote': None, 'limitations': ['Synthetic only'], 'physics_validated': False}
        output = case / 'report'
        receipt = render({'mode': 'dataset-query-quantities', 'task': {}}, result, case, output)
        assert len(receipt['figures']) == count
        assert all(Path(name).suffix == '.' + formats[0] for row in receipt['figures'] for name in row['files'])


def test_component_and_prefix_migration_preserves_numbers(tmp_path):
    from test_iris_completion_v2 import component_case
    ds, analysis, returned, rows = component_case(tmp_path)
    analysis['presentation'] = {'plot_kind': 'dataset_stack', 'formats': ['png', 'pdf']}
    result = core.analyze(analysis, ds, returned, rows, max_rows=100, max_products=1000)
    assert result['plot_kind'] == 'dataset_stack'
    assert result['observables']['mass']['values']['nominal'] == [0, -3]
    assert result['dataset_components']['observables']['mass']['aggregation_roundoff_residual']['nominal'] == [0, 0]
