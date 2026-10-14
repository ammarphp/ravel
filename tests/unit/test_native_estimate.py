"""Closed native estimate transport, without a native runtime or event replay."""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import pytest
from ravel.physics.native_estimate import NativeEstimateError, transport, validate_request

NAME = '/RAVEL_SYN_9051_I1325/d01-x01-y01'
NUM = '/RAW/RAVEL_SYN_9051_I1325/TMP/trijet'
DEN = '/RAW/RAVEL_SYN_9051_I1325/TMP/dijet'
EDGES = [0.2, 0.4, 0.9]


def estimate(name, rows, labels=('',), edges=EDGES):
    columns = ['value']
    for i, label in enumerate(labels, 1):
        columns += ['totalDn', 'totalUp'] if label == '' else [f'errDn({i})', f'errUp({i})']
    labels_line = 'ErrorLabels: ' + json.dumps(list(labels)) + '\n' if labels else ''
    return (f'BEGIN YODA_ESTIMATE1D_V3 {name}\nPath: {name}\nTitle: declared native quotient\n---\n'
            + 'Edges(A1): ' + json.dumps(edges) + '\n' + labels_line
            + '# ' + ' '.join(columns) + '\n' + '\n'.join(rows)
            + '\nEND YODA_ESTIMATE1D_V3\n\n')


def histogram(name, rows=None, edges=EDGES):
    rows = rows or ['0 0 0 0 0', '2 6 .6 .18 4', '-1 5 -.5 -.25 3', '0 0 0 0 1']
    return (f'BEGIN YODA_HISTO1D_V3 {name}\nPath: {name}\n---\nEdges(A1): '
            + json.dumps(edges) + '\n# sumW sumW2 sumW(A1) sumW2(A1) numEntries\n'
            + '\n'.join(rows) + '\nEND YODA_HISTO1D_V3\n\n')


@pytest.fixture
def sample(tmp_path):
    source = tmp_path / 'source.cc'
    source.write_text('void finalize() {\n  divide(trijet, dijet, r32);\n}\n')
    request = {'path': NAME, 'axes': [{'name': 'HT', 'unit': 'TeV'}],
               'representation': 'native', 'normalization': 'absolute', 'unit': '1',
               'quantity_kind': 'native_derived_estimate', 'native_derived': {
                   'operation': 'ratio', 'source': {'path': str(source),
                       'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                       'first_line': 2, 'last_line': 2, 'text': '  divide(trijet, dijet, r32);'},
                   'native_error_semantics': 'Source-native uncorrelated marginal divide errors; no shared-group covariance.',
                   'raw_estimate_path': '/RAW' + NAME,
                   'operands': [{'id': 'N', 'role': 'numerator', 'path': NUM},
                                {'id': 'D', 'role': 'denominator', 'path': DEN}],
                   'flow_policy': 'retain_all', 'group_covariance': 'not_supplied'}}
    text = (estimate(NAME, ['nan nan nan', '.75 -.11 .12', '0 -0 +0', '-nan --- ---'])
            + estimate('/RAW' + NAME, ['nan nan nan', '.75 -.11 .12', '0 -0 +0', '-nan --- ---'])
            + histogram(NUM) + histogram(DEN)
            + 'BEGIN YODA_COUNTER_V3 /RAW/_EVTCOUNT\n# sumW sumW2 numEntries\n18 30 17\nEND YODA_COUNTER_V3\n')
    path = tmp_path / 'native.yoda'; path.write_text(text)
    return path, request


def test_complete_ratio_and_no_density_or_variance_conversion(sample):
    path, request = sample; r = transport(path, request)
    assert [b['value'] for b in r['bins']] == [.75, 0]
    assert r['bins'][0]['error_low'] == .11 and r['bins'][0]['error_high'] == .12
    assert [b['high'][0] - b['low'][0] for b in r['bins']] == pytest.approx([.2, .5])
    assert all(b['variance'] is None and b['integrated_sumw'] is None and b['entries'] is None for b in r['bins'])
    assert r['covariance'] is None and not r['physics_validated']
    assert len(r['all_native_bins']) == 4 and len(r['raw_estimate']['bins']) == 4
    assert len(r['raw_operands']) == 2 and all(len(o['object']['bins']) == 4 for o in r['raw_operands'])
    assert '/RAW/_EVTCOUNT' in r['all_object_paths']
    assert r['yoda_text_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_undefined_signed_and_zero_tokens_and_raw_moments(sample):
    path, req = sample; r = transport(path, req)
    assert r['all_native_bins'][0]['status'] == 'undefined_value'
    assert r['all_native_bins'][-1]['value_token'] == '-nan'
    assert r['all_native_bins'][-1]['native_errors'][0]['down_token'] == '---'
    assert r['bins'][1]['native_errors'][0]['down_token'] == '-0'
    bins = r['raw_operands'][0]['object']['bins']
    assert bins[2]['sumw'] == -1 and bins[2]['sumw2'] == 5
    assert bins[2]['coordinate_squared_sumw'] == -.25 # signed weighted x², not w²x²
    assert bins[-1]['entries'] == 1 and bins[-1]['sumw2'] == 0
    assert r['all_native_bins'][0]['low'] == [None] and r['all_native_bins'][-1]['high'] == [None]
    assert 'Title: declared native quotient' in r['native_finalized']['native_text']


def test_literal_multiple_label_order_and_missing_errors(sample):
    path, req = sample
    text = path.read_text(); start = text.index('BEGIN YODA_ESTIMATE1D_V3 /RAW')
    path.write_text(estimate(NAME, ['nan nan nan --- ---', '.75 -.1 .1 -.2 .2', '0 -0 0 --- ---', 'nan nan nan nan nan'], ('', 'scale')) + text[start:])
    r = transport(path, req)
    assert r['native_finalized']['columns'] == ['value', 'totalDn', 'totalUp', 'errDn(2)', 'errUp(2)']
    assert r['bins'][0]['error_low'] == .1 # explicit total, not quadrature of two labels
    assert r['bins'][1]['status'] == 'undefined_native_errors' and r['bins'][1]['error_low'] == 0
    assert r['bins'][0]['native_errors'][1]['label'] == 'scale'


def test_no_error_labels_and_no_inferred_summary(sample):
    path, req = sample; text = path.read_text(); start = text.index('BEGIN YODA_ESTIMATE1D_V3 /RAW')
    path.write_text(estimate(NAME, ['nan', '.75', '0', 'nan'], ()) + text[start:])
    r = transport(path, req)
    assert r['bins'][0]['status'] == 'undefined_native_errors'
    assert r['bins'][0]['error_low'] is None and r['bins'][0]['native_errors'] == []


def test_unfilled_persistent_raw_estimate_separate_from_final_ratio(sample):
    """Rivet finalization mutates a separate final copy of a booked estimate."""
    path, req = sample
    path.write_text(estimate(NAME, ['nan nan nan', '.75 -.11 .12', '0 -0 +0', 'nan nan nan'], ('stats',))
                    + estimate('/RAW' + NAME, ['nan', 'nan', '-nan', 'nan'], ())
                    + histogram(NUM) + histogram(DEN))
    result = transport(path, req)
    assert result['native_finalized']['error_labels'] == ['stats']
    assert result['bins'][0]['value'] == .75
    assert result['raw_estimate']['columns'] == ['value']
    assert result['raw_estimate']['error_labels'] == []
    assert all(b['status'] == 'undefined_value' and b['native_errors'] == []
               for b in result['raw_estimate']['bins'])
    assert result['raw_estimate']['bins'][2]['value_token'] == '-nan'
    assert result['covariance'] is None


def test_multiple_labels_without_total_do_not_fabricate_aggregate(sample):
    path, req = sample; text = path.read_text(); start = text.index('BEGIN YODA_ESTIMATE1D_V3 /RAW')
    path.write_text(estimate(NAME, ['nan nan nan nan nan', '.75 -.1 .1 -.2 .2', '0 -0 0 -0 0', 'nan nan nan nan nan'], ('stats', 'scale')) + text[start:])
    r = transport(path, req)
    assert r['bins'][0]['error_low'] is None and r['bins'][0]['marginal_summary'] == 'no_total_reported_multiple_labels'


def test_asymmetry_signed_value_is_not_efficiency_reinterpreted(sample):
    path, req = sample; req['native_derived']['operation'] = 'asymmetry'
    req['native_derived']['operands'][0]['role'] = 'left'; req['native_derived']['operands'][1]['role'] = 'right'
    path.write_text(path.read_text().replace('.75 -.11 .12', '-.75 -.11 .12'))
    assert transport(path, req)['bins'][0]['value'] == -.75


def test_gzip_retained_file_hash(sample):
    path, req = sample; compressed = path.with_suffix('.yoda.gz'); compressed.write_bytes(gzip.compress(path.read_bytes()))
    r = transport(compressed, req)
    assert r['bins'] == transport(path, req)['bins']
    assert r['yoda_text_sha256'] == hashlib.sha256(compressed.read_bytes()).hexdigest()


@pytest.mark.parametrize('mutate', [
    lambda r: r.update(representation='differential'),
    lambda r: r.update(normalization='normalized'),
    lambda r: r.update(unit='pb'),
    lambda r: r.update(axes=r['axes'] * 2),
    lambda r: r['native_derived'].update(group_covariance='independent'),
    lambda r: r['native_derived'].update(flow_policy='drop_empty'),
    lambda r: r['native_derived']['operands'][0].update(role='denominator'),
    lambda r: r['native_derived']['operands'][0].update(path='/TMP/N'),
    lambda r: r['native_derived'].update(raw_estimate_path=NAME),
])
def test_contract_refusals(sample, mutate):
    _, req = sample; mutate(req)
    with pytest.raises(NativeEstimateError): validate_request(req)


@pytest.mark.parametrize('mutation,match', [
    (lambda s: s.replace('.75 -.11 .12', '.75 +.11 .12', 1), 'directions'),
    (lambda s: s.replace('.75 -.11 .12', '.75 --- .12', 1), 'partial'),
    (lambda s: s.replace('.75 -.11 .12', 'inf -.11 .12', 1), 'decimal'),
    (lambda s: s.replace('2 6 .6 .18 4', '2 -6 .6 .18 4', 1), 'second moment'),
    (lambda s: s.replace('Edges(A1): [0.2, 0.4, 0.9]', 'Edges(A1): [0.2, 0.5, 0.9]', 1), 'geometry'),
    (lambda s: s.replace('0 -0 +0\n', '', 1), 'census'),
    (lambda s: s.replace('ErrorLabels: [""]', 'ErrorLabels: ["stats", "stats"]', 1), 'unique'),
    (lambda s: s.replace('totalDn totalUp', 'errDn(1) errUp(1)', 1), 'order'),
    (lambda s: s.replace('END YODA_ESTIMATE1D_V3', 'END YODA_HISTO1D_V3', 1), 'close'),
    (lambda s: s + histogram(NUM), 'duplicate'),
    (lambda s: s.replace(NUM, '/RAW/not-requested'), 'missing'),
])
def test_whole_source_adverse_controls(sample, mutation, match):
    path, req = sample; path.write_text(mutation(path.read_text()))
    with pytest.raises(NativeEstimateError, match=match): transport(path, req)


def test_source_hash_excerpt_and_symlink_refused(sample):
    path, req = sample; wrong = copy.deepcopy(req); wrong['native_derived']['source']['text'] = 'divide(other, other, other);'
    with pytest.raises(NativeEstimateError, match='excerpt'): transport(path, wrong)
    Path(req['native_derived']['source']['path']).write_text('changed source\n')
    with pytest.raises(NativeEstimateError, match='hash'): transport(path, req)
    alias = path.with_name('alias.yoda'); alias.symlink_to(path)
    # Restore source to reach retained text admission.
    source = Path(req['native_derived']['source']['path']); source.write_text('void finalize() {\n  divide(trijet, dijet, r32);\n}\n')
    with pytest.raises(NativeEstimateError, match='regular'): transport(alias, req)


# Integrated public parser/intake/report lifecycle; no native runtime.
import sys
import types
def task(request):
    return {'backend':'rivet-built','routine':'RAVEL_SYN_9051_I1325',
            'events':'events.hepmc','metadata':'metadata.json','build_plan':'build-plan.json',
            'build_receipt':'build-receipt.json','runtime':{'python':'python','version':'4.1.3'},
            'options':{},'observables':[request],'seed':1}


def test_real_transport_export_route_and_closed_version(sample,monkeypatch):
    path,request=sample
    # No native/YODA call: namespace exposure only; actual parsing remains real.
    names=[NAME,'/RAW'+NAME,NUM,DEN,'/RAW/_EVTCOUNT']
    counter=types.SimpleNamespace(sumW=lambda:18,sumW2=lambda:30,numEntries=lambda:17)
    objects={n:object() for n in names};objects['/RAW/_EVTCOUNT']=counter
    yoda=types.SimpleNamespace(__version__='2.1.3',read=lambda p:objects)
    monkeypatch.setitem(sys.modules,'yoda',yoda)
    exporter=__import__('ravel.physics.rivet_export',fromlist=['export']);r=exporter.export(path,[request])
    assert r['observables'][NAME]['bins'][0]['value']==.75
    assert r['observables'][NAME]['all_native_bins'][-1]['value_token']=='-nan'
    assert r['event_counters']['/RAW/_EVTCOUNT']=={'sumw':18.,'sumw2':30.,'entries':17.}
    yoda.__version__='2.1.4'
    with pytest.raises(ValueError,match='2.1.3'): exporter.export(path,[request])


def test_source_and_implementation_auto_pins_are_real(sample,monkeypatch):
    _,request=sample;t=task(request);adapter=__import__('ravel.physics.existing_events',fromlist=['validate'])
    adapter.validate(t)
    monkeypatch.setattr(adapter,'_built_inputs',lambda *_:[])
    paths=adapter.inputs(t,Path(request['native_derived']['source']['path']).parent)
    assert Path(request['native_derived']['source']['path']) in paths
    assert any(p.name=='native_estimate.py' for p in paths)
    assert any(p.name=='rivet_export.py' for p in paths)
    source=Path(request['native_derived']['source']['path']);source.write_text('changed source\n')
    with pytest.raises(ValueError,match='hash'): adapter.inputs(t,source.parent)


def test_duplicate_output_admission(sample):
    _,request=sample; t=task(request); t['observables'].append(request)
    with pytest.raises(ValueError,match='duplicate'):__import__('ravel.physics.existing_events',fromlist=['validate']).validate(t)


@pytest.mark.parametrize('backend',['rivet','rivet-built'])
def test_all_flow_undefined_render_without_matplotlib(sample,tmp_path,monkeypatch,backend):
    from ravel.physics.native_estimate import transport
    path,request=sample;obj=transport(path,request);output=tmp_path/'output';output.mkdir()
    (output/'observables.json').write_text(json.dumps({'observables':{NAME:obj}}))
    monkeypatch.setitem(sys.modules,'matplotlib',None)
    t=task(request);t['backend']=backend
    result=__import__('ravel.plotting.science_figures',fromlist=['render']).render({'mode':'analyze','task':t},{},tmp_path,output)
    assert result['status']=='passed' and result['figures']==[]
    report=json.loads((output/'native-derived-estimates.json').read_text())
    assert report['estimates'][0]['observable']==obj
    table=(output/'native-derived-estimates.md').read_text()
    assert 'underflow' in table and 'overflow' in table and '-nan' in table and '---' in table
    assert len([line for line in table.splitlines() if line.startswith('| /RAVEL_')])==4
    assert report['covariance'] is None and report['physics_validated'] is False
