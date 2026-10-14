"""Synthetic census siblings: prospective ranks confer no execution authority."""
import importlib
import json


def synthetic_census():
    return {'schema_version': 1, 'kind': 'ravel-backend-census', 'analysis_catalog': {},
            'tools': [{'id': tool, 'status': status, 'requirement': 'required_for_profile',
                       'evidence_scope': 'Synthetic qualification only',
                       'doctor_checks': [{'kind': 'manifest', 'group': tool, 'check': 'synthetic'}]}
                      for tool, status in [('synthetic-a', 'qualified'), ('synthetic-b', 'not_installed')]],
            'backends': [{'id': tool, 'tool_id': tool, 'signal_bases': ['bsm'], 'families': ['search'],
                          'analysis_entries': [], 'assumptions': 'Synthetic basis', 'coverage_scope': 'Synthetic only',
                          'mapping_count': count, 'execution_count': None}
                         for tool, count in [('synthetic-a', 2), ('synthetic-b', 1)]]}


def test_census_mutation_changes_rank_deterministically(tmp_path):
    routes = importlib.import_module('ravel.workflow.recast_route')
    path = tmp_path / 'census.json'
    census = synthetic_census()
    path.write_text(json.dumps(census))
    first = routes.rank_routes(signal_basis='bsm', census_path=path)
    assert all(r['reasons'] for r in first['ranking'])
    census['backends'][0]['signal_bases'] = ['sm']
    path.write_text(json.dumps(census))
    second = routes.rank_routes(signal_basis='bsm', census_path=path)
    assert first['ranking'][0]['backend'] != second['ranking'][0]['backend']
    assert first['census_sha256'] != second['census_sha256']
    assert second == routes.rank_routes(signal_basis='bsm', census_path=path)
    assert second['cross_backend_combination'] is None and not second['execution_authorized']


def test_missing_tool_is_retained_with_not_ready_and_fix(tmp_path):
    routes = importlib.import_module('ravel.workflow.recast_route')
    path = tmp_path / 'census.json'; path.write_text(json.dumps(synthetic_census()))
    result = routes.rank_routes(signal_basis='bsm', census_path=path)
    row = next(r for r in result['ranking'] if r['backend'] == 'synthetic-b')
    assert row['label'] == 'not_ready'
    assert row['fix'] == 'bash scripts/setup/install.sh --only synthetic-b'
    assert row['reported_status'] == 'not_installed'
    assert len(result['ranking']) == 2


def test_doctor_observation_overrides_historical_readiness(tmp_path):
    routes = importlib.import_module('ravel.workflow.recast_route')
    path = tmp_path / 'census.json'; path.write_text(json.dumps(synthetic_census()))
    result = routes.rank_routes(signal_basis='bsm', census_path=path,
                               observations=[{'id': 'synthetic-a', 'readiness': 'missing'}])
    assert result['ranking'][0]['label'] == 'not_ready'
    assert result['ranking'][0]['reported_status'] == 'qualified'
    assert result['ranking'][0]['readiness_scope'] == 'supplied doctor observation'


def test_hold_doctor_row_is_visible_without_probing(tmp_path):
    from ravel.setup.doctor import Doctor
    from pathlib import Path
    doctor = Doctor(Path(__file__).resolve().parents[2], tmp_path, 'linux-x86_64',
                    {'groups': []}, {'sets': []}, environ={'PATH': str(tmp_path)},
                    run_probe=lambda *a, **kw: (_ for _ in ()).throw(AssertionError('No tool probe')))
    # Replace tool census projection; the reference seam must still be included.
    from unittest.mock import patch
    with patch('ravel.workflow.tool_census.doctor_report', return_value=[]):
        [row] = doctor.census_report()
    assert row['id'] == 'higgs-reference-tables'
    assert row['label'] == 'ready' and row['readiness'] == 'ready'
    assert row['hold_status'] == 'installed'
    assert row['would_make_possible'] and row['sources'] and row['expected_files']
    assert doctor.probes == []
    from ravel.setup.doctor import format_report
    text = format_report({'platform': 'synthetic', 'prefix': str(tmp_path), 'groups': [],
                          'conflicts': [], 'ready': False, 'tool_census': [row]})
    assert row['would_make_possible'] in text


def test_readiness_never_inferred_from_qualification_and_ties_are_stable(tmp_path):
    routes = importlib.import_module('ravel.workflow.recast_route')
    census = synthetic_census()
    census['tools'][1]['status'] = 'qualified'
    census['backends'][1]['mapping_count'] = 2
    path = tmp_path / 'census.json'; path.write_text(json.dumps(census))
    first = routes.rank_routes(signal_basis='bsm', census_path=path)
    assert all(row['label'] == 'readiness_unknown' for row in first['ranking'])
    census['tools'].reverse(); census['backends'].reverse()
    path.write_text(json.dumps(census))
    second = routes.rank_routes(signal_basis='bsm', census_path=path)
    assert first['ranking'] == second['ranking']


def test_readiness_observations_are_validated(tmp_path):
    import pytest
    routes = importlib.import_module('ravel.workflow.recast_route')
    path = tmp_path / 'census.json'; path.write_text(json.dumps(synthetic_census()))
    for observations in ([{'id': 'synthetic-unknown', 'readiness': 'ready'}],
                         [{'id': 'synthetic-a', 'readiness': 'synthetic-unknown'}],
                         [{'id': 'synthetic-a', 'readiness': 'ready'}] * 2):
        with pytest.raises(ValueError, match='unique census tool'):
            routes.rank_routes(signal_basis='bsm', census_path=path, observations=observations)


def test_excluded_route_remains_visible_and_not_executable(tmp_path):
    routes = importlib.import_module('ravel.workflow.recast_route')
    census = synthetic_census()
    census['tools'][0]['status'] = 'excluded'
    census['tools'][0]['requirement'] = 'excluded'
    census['tools'][0]['doctor_checks'] = [{'kind': 'excluded', 'reason': 'Synthetic exclusion'}]
    path = tmp_path / 'census.json'; path.write_text(json.dumps(census))
    result = routes.rank_routes(signal_basis='bsm', census_path=path)
    assert result['ranking'][-1]['label'] == 'excluded'
    assert result['ranking'][-1]['fix'] == 'No execution route; Synthetic exclusion'
    assert len(result['ranking']) == 2 and not result['execution_authorized']


def test_hold_atlas_row_is_source_pinned():
    from hashlib import sha256
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    atlas = json.loads((root / 'src/ravel/data/knowledge/atlas.json').read_text())
    row = next(r for r in atlas['entries'] if r['id'] == 'tool:higgs-reference-tables')
    assert row['kind'] == 'tool' and row['qualification_status'] == 'built_but_unqualified'
    assert row['hold_status'] == 'installed'
    assert row['would_make_possible'] and row['source_locator']
    assert row['source']['sha256'] == sha256((root / row['source']['path']).read_bytes()).hexdigest()
