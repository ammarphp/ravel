"""HEPData table map, reference YODA, booking checks and sample normalization classes."""
import json
import pytest
from ravel.physics import hepdata_table_map as tables, rivet_sample_checks as checks, yoda_text

RECORD = {'schema_version': 1, 'kind': 'hepdata-record', 'record': 'own-record', 'tables': [
    {'name': 'T1', 'description': 'Own pT', 'independent_variables': [
        {'header': {'name': 'pT', 'units': 'GeV'}, 'values': [{'low': 0, 'high': 10}, {'low': 10, 'high': 20}, {'low': 20, 'high': 50}]}],
     'dependent_variables': [
        {'header': {'name': 'dsig/dpT', 'units': 'fb/GeV'}, 'values': [
            {'value': 1.5, 'errors': [{'label': 'stat', 'asymerror': {'minus': -0.1, 'plus': 0.2}}]},
            {'value': 2.5, 'errors': [{'label': 'stat', 'symerror': 0.3}, {'label': 'sys', 'symerror': '0.2'}]},
            {'value': 0.5}]},
        {'header': {'name': 'ratio'}, 'values': [{'value': 1}, {'value': 1}, {'value': 1}]}]},
    {'name': 'T2', 'description': 'Own counts with a gap', 'headers': [{'name': 'm'}, {'name': 'N'}],
     'values': [{'x': [{'low': 1, 'high': 2}], 'y': [{'value': 3}]}, {'x': [{'low': 3, 'high': 4}], 'y': [{'value': 4}]}]},
    {'name': 'T3', 'description': 'Own 2-D', 'independent_variables': [
        {'header': {'name': 'x'}, 'values': [{'low': 0, 'high': 1}, {'low': 0, 'high': 1}]},
        {'header': {'name': 'y'}, 'values': [{'low': 0, 'high': 1}, {'low': 1, 'high': 2}]}],
     'dependent_variables': [{'header': {'name': 'z'}, 'values': [{'value': 1}, {'value': 2}]}]}]}


def test_map_identities_edges_and_upstream_shape():
    m = tables.build(RECORD)
    assert sorted(m['entries']) == ['d01-x01-y01', 'd01-x01-y02', 'd02-x01-y01', 'd03-x01-y01']
    first = m['entries']['d01-x01-y01']
    assert first['edges'] == [0.0, 10.0, 20.0, 50.0] and first['ylabel'] == 'dsig/dpT [fb/GeV]'
    assert first['errors'][1] == {'stat': [-0.3, 0.3], 'sys': [-0.2, 0.2]}
    assert m['entries']['d02-x01-y01']['edges'] is None              # gap: never invented
    assert m['entries']['d03-x01-y01']['dimension'] == 2 and m['entries']['d03-x01-y01']['bins'][1] == [[0, 1], [1, 2]]
    upstream = tables.upstream_map(m)
    assert upstream['d01-x01-y01']['bin_edges'] == [0.0, 10.0, 20.0, 50.0] and 'bin_edges' not in upstream['d02-x01-y01']
    with pytest.raises(ValueError):
        tables.build({'schema_version': 1, 'kind': 'other', 'tables': []})


def test_reference_yoda_round_trips_through_the_reader():
    text = tables.reference_yoda(tables.build(RECORD), 'OWN_2026_I1')
    objects = yoda_text.parse(text)
    assert sorted(objects) == ['/REF/OWN_2026_I1/d01-x01-y01', '/REF/OWN_2026_I1/d01-x01-y02']
    ref = objects['/REF/OWN_2026_I1/d01-x01-y01']
    assert ref['edges'] == [0.0, 10.0, 20.0, 50.0] and yoda_text.values(ref) == [1.5, 2.5, 0.5]
    assert ref['rows'][1] == [1.5, -0.1, 0.2, None, None]
    with pytest.raises(ValueError):
        tables.reference_yoda(tables.build(RECORD), 'bad-name')


def test_bookings_and_their_findings():
    source = '''
    void init() {
      book(_h["pt"], 1, 1, 1);           // table one
      book(_h["ratio"], "d01-x01-y02");
      book(_h["gap"], 2, 1, 1);
      book(_h["ghost"], 7, 1, 1);
      /* book(_h["commented"], 8, 1, 1); */
      book(_h["own"], "own_hist", 10, 0.0, 100.0);
      book(_h["pt2"], 1, 1, 1);
    }'''
    booked = tables.bookings(source)
    assert [b['kind'] for b in booked] == ['hepdata', 'hepdata', 'hepdata', 'hepdata', 'explicit', 'hepdata']
    assert booked[4]['uniform'] == {'n': '10', 'low': '0.0', 'high': '100.0'}
    found = tables.verify_bookings(tables.build(RECORD), booked, [
        {'name': 'pt', 'binning_source': 'HEPDATA', 'hepdata_id': 'd01-x01-y01'},
        {'name': 'mass', 'binning_source': 'HEPDATA', 'hepdata_id': 'd05-x01-y01'}])
    kinds = sorted((f['check'], f['object']) for f in found)
    assert kinds == [('booking_duplicate', 'd01-x01-y01'), ('booking_unknown_table', 'd07-x01-y01'),
                     ('booking_without_edges', 'd02-x01-y01'), ('declared_unknown_table', 'd05-x01-y01')]


def test_fetch_directory_record_order(tmp_path):
    (tmp_path / 'tables').mkdir()
    rows = []
    for k, name in enumerate(['b', 'a']):
        (tmp_path / 'tables' / f'{name}_data.json').write_text(json.dumps(RECORD['tables'][1]))
        rows.append({'name': name, 'file': f'tables/{name}_data.json'})
    (tmp_path / 'manifest.json').write_text(json.dumps({'table_files': rows, 'inspire': 'ins1'}))
    record = tables.load_fetch_directory(tmp_path)
    assert record['record'] == 'ins1' and len(tables.build(record)['entries']) == 2


def _objects(final_values, raw_rows, *, edges=(0.0, 1.0, 2.0), events=10.0, xsec=2.0):
    rows = '\n'.join(' '.join(str(v) for v in row) for row in raw_rows)
    finals = '\n'.join(['nan', *[str(v) for v in final_values], 'nan'])
    edge_text = ', '.join(str(e) for e in edges)
    text = f'''BEGIN YODA_COUNTER_V3 /RAW/_EVTCOUNT
---
{events} {events} {events}
END YODA_COUNTER_V3
BEGIN YODA_ESTIMATE0D_V3 /RAW/_XSEC
---
{xsec} 0 0
END YODA_ESTIMATE0D_V3
BEGIN YODA_HISTO1D_V3 /RAW/R/h
---
Edges(A1): [{edge_text}]
{rows}
END YODA_HISTO1D_V3
BEGIN YODA_ESTIMATE1D_V3 /R/h
---
Edges(A1): [{edge_text}]
{finals}
END YODA_ESTIMATE1D_V3
'''
    return yoda_text.parse(text)


RAW = [[0, 0, 0, 0, 0], [5, 5, 2, 1, 5], [5, 5, 7, 9, 5], [0, 0, 0, 0, 0]]


@pytest.mark.parametrize('factor,label', [(1.0, None), (1000.0, 'unit'), (2.0, 'factor 2'), (0.5, 'factor 1/2'),
                                          (3.7, 'unclassified constant')])
def test_xsec_normalization_ratio_classes(factor, label):
    # sigma/sumW = 0.2 -> final area 2.0 in pb; values are densities (unit bin widths).
    objects = _objects([1.0 * factor, 1.0 * factor], RAW)
    rows = checks.validate_contract([{'object': 'h', 'basis': 'xsec', 'unit': 'pb'}])
    found = [f for f in checks.findings(objects, 'R', contract=rows) if f['check'] == 'normalization']
    assert len(found) == 1
    if label is None:
        assert found[0]['severity'] == 'pass'
    else:
        assert found[0]['severity'] == 'error' and label in found[0]['message']


def test_slice_width_and_unit_area_contracts():
    objects = _objects([1.0, 1.0], RAW)
    slice_rows = checks.validate_contract([{'object': 'h', 'basis': 'bin_width_area_2D', 'unit': 'pb',
                                            'slice': {'variable': 'y', 'low': 0.0, 'high': 4.0}}])
    found = [f for f in checks.findings(objects, 'R', contract=slice_rows) if f['check'] == 'normalization'][0]
    assert found['severity'] == 'error' and 'slice width' in found['message']
    unit = checks.validate_contract([{'object': 'h', 'basis': 'in_range_N'}])
    good = _objects([0.05, 0.05], RAW)
    assert [f['severity'] for f in checks.findings(good, 'R', contract=unit) if f['check'] == 'normalization'] == ['error']
    good = _objects([0.5, 0.5], RAW)
    assert [f['severity'] for f in checks.findings(good, 'R', contract=unit) if f['check'] == 'normalization'] == ['pass']
    with pytest.raises(ValueError):
        checks.validate_contract([{'object': 'h', 'basis': 'xsec'}])          # unit required
    with pytest.raises(ValueError):
        checks.validate_contract([{'object': 'h', 'basis': 'bin_width_area_2D', 'unit': 'fb'}])


def test_double_fill_empty_and_non_finite_findings():
    objects = _objects(['nan', 1.0], [[0, 0, 0, 0, 0], [5, 5, 2, 1, 15], [5, 5, 7, 9, 5], [0, 0, 0, 0, 0]])
    found = {f['check'] for f in checks.findings(objects, 'R', booked=[{'kind': 'hepdata', 'id': 'd09-x01-y01'}])}
    assert {'multiple_fills_per_event', 'non_finite', 'output_missing'} <= found
    empty = _objects([0, 0], [[0, 0, 0, 0, 0]] * 4)
    assert 'empty' in {f['check'] for f in checks.findings(empty, 'R')}


def test_contract_from_specification_histograms():
    spec = {'schema_version': 1, 'kind': 'typed-analysis-spec', 'items': [
        {'id': 'met', 'role': 'histogram', 'fields': {
            'normalization_basis': {'value': 'bin_width_area_2D', 'status': 'explicit'},
            'hepdata_id': {'value': 'd04-x01-y01', 'status': 'explicit'},
            'cross_section_unit': {'value': 'fb', 'status': 'inferred', 'note': 'table header'},
            'slice': {'value': {'variable': 'y', 'low': 0, 'high': 2}, 'status': 'explicit'}}},
        {'id': 'cut', 'role': 'cut', 'fields': {}}]}
    rows = checks.contract_from_spec(spec)
    assert rows == [{'object': 'd04-x01-y01', 'basis': 'bin_width_area_2D', 'unit': 'fb',
                     'slice': {'variable': 'y', 'low': 0, 'high': 2}, 'source': 'analysis_spec:met'}]
