"""Counterexamples to unsupported contours and mis-scoped scan comparisons."""
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from ravel.plotting.scan_contour import (
    _smooth_field, comparison_data, read_limit_grid, excluded_intervals,
    atlas_dm_reach, MissingLimitColumn,
)


def test_linear_contour_cannot_invent_exclusion():
    # All sampled log10(mu95) values are positive: no interpolation may imply mu95<1.
    x, y = np.meshgrid([100, 125, 150], [1, 10, 100])
    _, _, field = _smooth_field(x.ravel(), y.ravel(), [0.001, 4, .02, 3, .003, 2, 1, .001, 2])
    assert field.min() >= .001 - 1e-12
    assert field.max() <= 4 + 1e-12


def test_missing_or_flagged_interior_point_is_not_bridged():
    x, y = np.meshgrid([100, 125, 150], [1, 10, 100])
    values = np.ones(9)
    values[4] = np.nan
    _, _, field = _smooth_field(x.ravel(), y.ravel(), values, nx=101, ny=101)
    assert field.mask[50, 50]
    # Removing the missing point entirely must have the same unsupported center.
    _, _, removed = _smooth_field(np.delete(x.ravel(), 4), np.delete(y.ravel(), 4),
                                  np.delete(values, 4), nx=101, ny=101)
    assert removed.mask[50, 50]


def test_disconnected_exclusions_and_nan_gaps():
    assert excluded_intervals([1, 2, 3, 4, 5], [.5, 2, 2, 2, .5]) == pytest.approx([(1, 4/3), (14/3, 5)])
    assert excluded_intervals([1, 2, 3, 4], [.5, .5, np.nan, .5]) == [(1, 2)]


def test_reference_reach_has_no_nearest_mass_fallback():
    contour = [('observed', 'unused', [100, 200], [10, 30], 'mass', 'Delta m')]
    assert atlas_dm_reach(contour, 150) == 20
    assert atlas_dm_reach(contour, 220) is None


def point(mass=100, **updates):
    return dict(tag=str(mass), m_parent=mass, dm=10, mu95_obs=2, sigma_ref_fb=5, **updates)


def test_comparison_denominator_retains_missing_bounds_and_unmatched():
    points = [point(), point(150, quality='capped'), point(200), point(250)]
    points[-1]['mu95_obs'] = float('nan')
    report = comparison_data({'points': points, 'n_planned': 6}, ([100, 150], [10, 10], [8, 10]))
    assert report['counts'] == dict(matched=1, quality_flag=1, invalid_input=1, unmatched_reference=1)
    assert report['missing_scan_points'] == 2
    assert report['matched_fraction_of_plan'] == 1/6
    assert report['median_absolute_residual'] == .25
    assert report['records'][2]['status'] == 'unmatched_reference'
    json.dumps(report, allow_nan=False)


def test_duplicate_coordinates_refused():
    with pytest.raises(ValueError, match='duplicate'):
        comparison_data({'points': [point(), point()]}, ([100], [10], [8]))


def grid(units='pb', name='Observed limit'):
    return {'independent_variables': [
        {'header': {'name': 'Parent mass', 'units': 'GeV'}, 'values': [{'value': 100}]},
        {'header': {'name': 'LSP mass', 'units': 'GeV'}, 'values': [{'value': 90}]}],
        'dependent_variables': [{'header': {'name': name, 'units': units}, 'values': [{'value': .01}]}]}


def write_grid(tmp_path, doc):
    import yaml
    path = tmp_path / 'reference.yaml'
    path.write_text(yaml.safe_dump(doc))
    return path


def test_mass_mass_reference_is_converted_and_units_respected(tmp_path):
    m, dm, limit = read_limit_grid(write_grid(tmp_path, grid()))
    assert (m[0], dm[0], limit[0]) == (100, 10, 10)


@pytest.mark.parametrize('units,name', [('', 'Observed limit'), ('nb', 'Observed limit'), ('fb', 'Limit')])
def test_unknown_normalization_or_column_refused(tmp_path, units, name):
    with pytest.raises((SystemExit, MissingLimitColumn)):
        read_limit_grid(write_grid(tmp_path, grid(units, name)))


def test_malformed_reference_lengths_refused(tmp_path):
    doc = grid()
    doc['independent_variables'][0]['values'] *= 2
    with pytest.raises(SystemExit, match='equal'):
        read_limit_grid(write_grid(tmp_path, doc))


@pytest.mark.parametrize('spec', sorted((ROOT / 'benchmarks/specs').glob('*.json')), ids=lambda p: p.stem)
def test_active_scan_definition_dry_plan_uses_real_template(spec, tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/run.py'),
                             'ravel.workflow.scan_orchestrator', 'plan', str(spec), '--dry-run'],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '[DRY-RUN]' in result.stdout
    assert not list(tmp_path.iterdir())


def test_expected_only_grid_cannot_be_mistaken_for_observed(tmp_path):
    path = write_grid(tmp_path, grid('fb', 'Expected limit'))
    assert read_limit_grid(path, kind='expected')[2][0] == .01
    with pytest.raises(MissingLimitColumn):
        read_limit_grid(path, kind='observed')


def test_malformed_expected_grid_is_not_treated_as_absent(tmp_path):
    with pytest.raises(SystemExit, match='units'):
        read_limit_grid(write_grid(tmp_path, grid('nb', 'Expected limit')), kind='expected')
