"""Report writing for a complete delivery and for one partition's public record.

Pure synthetic moments; no ROOT, site or native operation.
"""
from ravel.physics import root_stream as s
from ravel.workflow.state_io import read_json
from root_stream_fixture import population, accumulate


def moments(tmp_path):
    ds, a, cfg, _, _ = population(tmp_path / 'source')
    return accumulate(ds, a, cfg['limits'], 2)


def test_complete_delivery_report_projects_each_simulated_weight(tmp_path):
    full = moments(tmp_path)
    result = {'status': 'passed', 'limitations': ['Synthetic software control'],
              'delivery': {**full, 'kind': 'root-stream-public-moments'}}
    out = tmp_path / 'report'; out.mkdir()
    tables = s.write_report(result, out)
    assert tables[0]['files'] == ['root-stream-report.md', 'root-stream-report.json']
    projected = sorted(p.name for p in (out / 'binned-values').iterdir())
    # Two simulated samples, one quantity, two named weights; the data sample is not projected.
    assert projected == [f'sample-{i}-quantity-0-weight-{k}.json' for i in (0, 1) for k in (0, 1)]
    first = read_json(out / 'binned-values' / projected[0])
    assert first['provenance']['sample'] == 'background' and first['provenance']['quantity'] == 'regions'


def test_partition_record_report_has_no_projection_of_partial_moments(tmp_path):
    full = moments(tmp_path)
    rows = [{'id': row['id'], 'kind': 'data', 'visibility': 'partition_machine_record_only_no_DATA_counts'}
            if row['kind'] == 'data' else
            {'id': row['id'], 'kind': row['kind'], 'dsid': row['dsid'], 'raw_quantities': row['quantities'],
             'normalization_applied': False} for row in full['samples']]
    delivery = {'schema_version': 1, 'kind': 'root-stream-public-partition', 'master_sha256': '0' * 64,
                'partition_id': 'synthetic-partition', 'samples': rows, 'complete_original_study': False,
                'normalization_applied': False, 'physics_validated': False}
    result = {'status': 'passed', 'limitations': ['Synthetic software control'], 'delivery': delivery}
    out = tmp_path / 'report'; out.mkdir()
    tables = s.write_report(result, out)
    assert tables[0]['files'] == ['root-stream-report.md', 'root-stream-report.json']
    assert read_json(out / 'root-stream-report.json')['delivery'] == delivery
    assert sorted(p.name for p in out.iterdir()) == ['root-stream-report.json', 'root-stream-report.md']
