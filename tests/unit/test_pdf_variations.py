"""Portable independent rational, identity and source-custody controls; no LHAPDF import."""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import statistics
from types import SimpleNamespace

import pytest

from ravel.physics import pdf_variations as pdf


def document():
    digest = 'a'*64
    result = {'schema_version': 1, 'kind': 'pdf-fixed-parton-records', 'source': 'synthetic rational oracle only',
              'pdf': {'set': pdf.SET, 'data_version': 2, 'nominal_member': 0,
                      'members': list(range(101)), 'error_type': 'replicas'},
              'perturbative_contract': {'hard_order': 'LO', 'counterterms': 'none', 'operation': 'pdf_only',
                 'scale_source': 'explicit supplied factorization scale, not inferred SCALUP',
                 'alpha_s_policy': 'unchanged_all_members', 'response_policy': 'fixed_supplied',
                 'group_rule': 'independent_single_event', 'definition': 'Synthetic tree contract for arithmetic only.'},
              'normalization': {'nominal_weight_unit': 'supplied_integral_contribution', 'output_unit': 'expected_events',
                 'factor': 1, 'factor_policy': 'fixed_common_to_all_members', 'definition': 'Synthetic fixed factor one.'},
              'source_inputs': [{'path': 'synthetic-source.txt', 'sha256': digest}],
              'regions': [{'id': 'SR', 'channel': 'SR', 'bin': '0', 'definition': 'Synthetic fixed SR response'},
                          {'id': 'CR', 'channel': 'CR', 'bin': '0', 'definition': 'Synthetic fixed CR response'}], 'events': []}
    for i, (weight, sr, cr) in enumerate([(2, 1, 0), (-1, 0, 1), (3, .5, 1)]):
        result['events'].append({'id': digest+':'+str(i), 'input_sha256': digest, 'encounter_ordinal': i,
            'pdg1': 2, 'pdg2': -2, 'x1': .1, 'x2': .2, 'q_factorization_gev': 100,
            'nominal_weight': weight, 'response': {'SR': sr, 'CR': cr}})
    return result


def evaluated(doc):
    return {'schema_version': 1, 'set': pdf.SET, 'data_version': 2, 'member_ids': list(range(101)),
            'events': [{**{k: e[k] for k in ('id', 'pdg1', 'pdg2', 'x1', 'x2', 'q_factorization_gev')},
                        'xf1': [2] + [float(2*Fraction(100+m, 100)) for m in range(1, 101)],
                        'xf2': [4]*101, 'alpha_s': [.118]*101} for e in doc['events']]}


def test_independent_rational_oracle_signed_rates_and_joint_covariance():
    doc = document(); out = pdf.transport(doc, evaluated(doc))
    assert out['nominal_member_zero'] == [3.5, 2]
    assert out['replica_mean'] == pytest.approx([float(Fraction(2107, 400)), float(Fraction(301, 100))])
    # Independent closed-form variance of integers 1..100, divided by 100^2.
    variance = Fraction(101, 1200)
    expected = [[variance*Fraction(49,4), variance*7], [variance*7, variance*4]]
    for got, want in zip(out['pdf_covariance'], expected): assert got == pytest.approx([float(v) for v in want])
    assert out['pdf_correlation'][0] == pytest.approx([1, 1])
    assert out['nominal_mc_covariance'] == [[6.25, 4.5], [4.5, 10]]
    assert out['event_weights'][1]['named_weights']['nominal'] == -1
    assert out['event_weights'][1]['named_weights'][pdf.weight_names()[-1]] == -2
    assert len(out['weight_names']) == 101 and len(out['member_yields']) == 101
    assert out['physics_validated'] is False


def test_permutation_and_file_partition_do_not_destroy_named_correlations():
    d = document(); r = evaluated(d); expected = pdf.transport(d, r)
    d['events'].reverse(); r['events'] = r['events'][1:] + r['events'][:1]
    assert pdf.transport(d, r) == expected
    # An actual split keeps stable encounter identities; it does not mint new groups.
    assert {e['id'] for part in (d['events'][:1], d['events'][1:]) for e in part} == {e['id'] for e in d['events']}


@pytest.mark.parametrize('change', [
    lambda d: d['pdf'].update(error_type='hessian'),
    lambda d: d['pdf']['members'].pop(),
    lambda d: d['pdf']['members'].reverse(),
    lambda d: d['pdf'].update(nominal_member=False),
    lambda d: d['perturbative_contract'].update(hard_order='NLO'),
    lambda d: d['perturbative_contract'].update(counterterms='present'),
    lambda d: d['perturbative_contract'].update(operation='pdf_and_alpha_s'),
    lambda d: d['perturbative_contract'].update(response_policy='new_detector_response'),
    lambda d: d['perturbative_contract'].update(group_rule='subtraction_subevents'),
    lambda d: d['normalization'].update(factor_policy='renormalize_each_member'),
    lambda d: d['normalization'].update(factor=-1),
    lambda d: d['events'][0].update(pdg1=0),
    lambda d: d['events'][0].update(q_factorization_gev=None),
    lambda d: d['events'][0].update(x1=1),
    lambda d: d['events'][0].update(nominal_weight=float('nan')),
    lambda d: d['events'][0]['response'].pop('CR'),
    lambda d: d['events'][0]['response'].update(CR=2),
    lambda d: d['events'].append(deepcopy(d['events'][0])),
    lambda d: d['events'][0].update(input_sha256='b'*64, id='b'*64+':0'),
    lambda d: d['regions'].append(deepcopy(d['regions'][0])),
])
def test_unsupported_or_incomplete_inputs_refuse(change):
    d = document(); change(d)
    with pytest.raises(ValueError): pdf.validate_records(d)


@pytest.mark.parametrize('change', [
    lambda r: r['events'][0]['xf1'].pop(),
    lambda r: r['events'][0]['xf2'].__setitem__(0, 0),
    lambda r: r['events'][0]['alpha_s'].__setitem__(1, .12),
    lambda r: r['events'][0]['xf1'].__setitem__(1, float('inf')),
    lambda r: r['events'][0].update(x1=.11),
    lambda r: r['events'][0].update(q_factorization_gev=101),
    lambda r: r['events'].append(deepcopy(r['events'][0])),
    lambda r: r['events'].__setitem__(1, deepcopy(r['events'][0])),
    lambda r: r['member_ids'].reverse(),
])
def test_native_missing_drift_zero_and_alpha_s_variation_refuse(change):
    d = document(); r = evaluated(d); change(r)
    with pytest.raises(ValueError): pdf.transport(d, r)


def test_negative_pdf_member_is_preserved_without_clipping():
    d = document(); r = evaluated(d)
    for row in r['events']: row['xf1'][1] = -2
    out = pdf.transport(d, r)
    assert out['member_yields'][1] == [-3.5, -2]


def test_zero_pdf_variance_is_explicit_undefined_correlation_not_fake_independence():
    d = document(); r = evaluated(d)
    for row in r['events']: row['xf1'] = [2]*101
    out = pdf.transport(d, r)
    assert out['pdf_covariance'] == [[0, 0], [0, 0]]
    assert out['pdf_correlation'] == [[None, None], [None, None]]


def make_grid(root):
    root.mkdir()
    (root/'lhapdf.conf').write_text('ForcePositive: 0\n')
    (root/'pdfsets.index').write_text('260000 '+pdf.SET+' 2\n')
    directory = root/pdf.SET; directory.mkdir()
    (directory/(pdf.SET+'.info')).write_text('NumMembers: 101\n')
    for i in range(101): (directory/(pdf.SET+'_%04d.dat'%i)).write_text(str(i))
    return pdf.data_census(root)


@pytest.mark.parametrize('operation', ['addition', 'deletion', 'bytes', 'alias'])
def test_complete_member_scope_detects_changes(tmp_path, operation):
    root = tmp_path/'grid'; before = make_grid(root)
    if operation == 'addition': (root/'unexpected.bin').write_bytes(b'new')
    if operation == 'deletion': (root/pdf.SET/(pdf.SET+'_0100.dat')).unlink()
    if operation == 'bytes': (root/'lhapdf.conf').write_text('ForcePositive: 1\n')
    if operation == 'alias': (root/'alias').symlink_to(root/'lhapdf.conf')
    if operation in ('addition', 'deletion', 'alias'):
        with pytest.raises(ValueError): pdf.data_census(root)
    else: assert pdf.data_census(root) != before


def test_runtime_pin_requires_actual_original_input_and_checks_membership(tmp_path):
    grid = tmp_path/'grid'; manifest = tmp_path/'grid.json'; manifest.write_text(json.dumps(make_grid(grid)))
    def pin(p): return {'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
    assert pdf._data({'root': str(grid), 'manifest': pin(manifest)}, '.') == (grid, manifest)
    (grid/'new-fixture.json').write_text('{}')
    with pytest.raises(ValueError, match='census'): pdf._data({'root': str(grid), 'manifest': pin(manifest)}, '.')


class FakePDF:
    def __init__(self, m, clipped=False, in_range=True):
        self.memberID=m; self.type='central' if m==0 else 'replica'; self.clipped=clipped; self.in_range=in_range
    def flavors(self): return pdf.FLAVORS
    def info(self):
        return SimpleNamespace(get_entry=lambda key: ('1' if self.clipped else '0') if key == 'ForcePositive' else None)
    def inRangeXQ(self, x, q): return self.in_range
    def xfxQ(self, pid, x, q): return 2 if self.memberID == 0 else 2*(1+self.memberID/100)
    def alphasQ(self, q): return .118


class FakeSet:
    name=pdf.SET; size=101; dataversion=2; errorType='replicas'
    def __init__(self, **kw): self.kw=kw
    def mkPDFs(self): return [FakePDF(i, **self.kw) for i in range(101)]
    def uncertainty(self, values, cl, alternative):
        assert cl == 68.268949 and alternative is False
        return SimpleNamespace(central=statistics.mean(values[1:]), errsymm=statistics.stdev(values[1:]))


def test_native_api_path_runs_through_complete_mocked_members_and_library_oracle():
    library=SimpleNamespace(version=lambda:'6.5.6', getPDFSet=lambda name:FakeSet())
    raw, result=pdf.evaluate(document(), library)
    assert raw['member_ids'] == list(range(101))
    assert len(result['native_uncertainties']) == 2


@pytest.mark.parametrize('kw', [{'clipped':True}, {'in_range':False}])
def test_native_clipping_or_extrapolation_refuses(kw):
    library=SimpleNamespace(version=lambda:'6.5.6', getPDFSet=lambda name:FakeSet(**kw))
    with pytest.raises(ValueError): pdf.evaluate(document(), library)


def test_actual_native_dispatch_denied_before_approval(tmp_path, monkeypatch):
    def forbidden(*a, **kw): raise AssertionError('native helper must not execute')
    from ravel.physics import reinterpret_db
    monkeypatch.setattr(reinterpret_db, 'execute_native', forbidden)
    with pytest.raises(ValueError, match='approved supervised'): pdf.run({'config':'absent.json'}, tmp_path, tmp_path)


def test_private_science_route_and_new_capability_review_gate():
    from ravel.workflow import science
    assert 'pdf-variations' in science.MODES
    spec={'mode':'pdf-variations', 'task':{'config':'x.json'}}
    assert science.adapter(spec) is pdf
    assert science._new_capability(spec) is True


@pytest.mark.parametrize('point', [(1e-300, 1e300), (1e300, 1e-300)])
def test_ratio_underflow_and_overflow_are_refusals(point):
    with pytest.raises(ValueError): pdf._ratio(*point)


def test_signed_cancellation_is_retained_and_never_clipped_to_poisson_yield():
    d = document(); d['events'][0]['nominal_weight'] = -2
    out = pdf.transport(d, evaluated(d))
    assert out['nominal_member_zero'][0] == -.5
    assert out['nominal_mc_covariance'][0][0] == 6.25


def test_distinct_region_replica_response_retains_negative_correlation():
    d = document(); d['events'] = d['events'][:2]
    d['events'][1]['nominal_weight'] = 1
    r = evaluated(d)
    r['events'][1]['xf1'] = [2] + [2*(1-m/200) for m in range(1,101)]
    out = pdf.transport(d, r)
    assert out['pdf_correlation'][0][1] == pytest.approx(-1)
    assert out['pdf_covariance'][0][1] < 0


def test_partition_recombine_all_member_templates_before_ensemble_reduction():
    d = document(); r = evaluated(d); entire = pdf.transport(d, r)
    left=deepcopy(d); left['events']=d['events'][:1]
    right=deepcopy(d); right['events']=d['events'][1:]
    a=pdf.transport(left, evaluated(left)); b=pdf.transport(right, evaluated(right))
    combined=[[math.fsum((a['member_yields'][i][j],b['member_yields'][i][j])) for j in range(2)] for i in range(101)]
    for got, want in zip(combined, entire['member_yields']): assert got == pytest.approx(want)
    # Adding marginal PDF variances would lose same-replica cross-file covariance.
    assert a['pdf_covariance'][0][0] + b['pdf_covariance'][0][0] != pytest.approx(entire['pdf_covariance'][0][0])


def test_native_library_alias_retarget_to_even_identical_bytes_is_refused(tmp_path):
    physical=tmp_path/'lib-one.dylib'; physical.write_bytes(b'frozen native bytes')
    other=tmp_path/'lib-two.dylib'; other.write_bytes(physical.read_bytes())
    alias=tmp_path/'load.dylib'; alias.symlink_to(physical.name)
    pin={'load_path':str(alias), 'path':str(physical), 'sha256':hashlib.sha256(physical.read_bytes()).hexdigest()}
    assert pdf._library(pin, '.') == physical
    alias.unlink(); alias.symlink_to(other.name)
    with pytest.raises(ValueError, match='alias'): pdf._library(pin, '.')


def test_portable_suite_does_not_import_native_scientific_module():
    import sys
    assert 'lhapdf' not in sys.modules


def bound_fixture(tmp_path):
    grid=tmp_path/'grid'; manifest=tmp_path/'grid.json'; manifest.write_text(json.dumps(make_grid(grid)))
    def pin(p): return {'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
    original=tmp_path/'synthetic-source.txt'; original.write_text('source-only synthetic event identity fixture\n')
    d=document(); old=d['source_inputs'][0]['sha256']; new=pin(original)['sha256']
    d['source_inputs']=[pin(original)]
    for e in d['events']:
        e['id']=e['id'].replace(old,new); e['input_sha256']=new
    records=tmp_path/'records.json'; records.write_text(json.dumps(d))
    executable=tmp_path/'fake-python'; executable.write_text('source fixture, never executed'); executable.chmod(0o700)
    support=tmp_path/'support.json'; support.write_text(json.dumps({'python_sha256':pin(executable)['sha256'], 'files':[pin(original)]}))
    library=tmp_path/'fake-library.dylib'; library.write_text('source fixture library, never loaded')
    c={'schema_version':1, 'source':'source fixture only', 'runtime':{'python':pin(executable),
        'python_manifest':pin(support), 'native_libraries':[dict(load_path=str(library), **pin(library))]},
        'pdf_data':{'root':str(grid), 'manifest':pin(manifest)}, 'records':pin(records), 'max_seconds':1, 'max_ram_mib':512}
    config=tmp_path/'config.json'; config.write_text(json.dumps(c))
    return {'config':str(config)}, c


@pytest.mark.parametrize('mutation', [None, 'source', 'addition', 'deletion', 'copied-grid', 'copied-record'])
def test_controller_mocked_dispatch_rechecks_original_and_copied_closed_inputs(tmp_path, monkeypatch, mutation):
    task,c=bound_fixture(tmp_path)
    # This is deliberately mocked authorization/execution, never a successful actual science receipt.
    monkeypatch.setattr(pdf, '_approved', lambda task,out:(tmp_path, {'max_seconds':1}))
    out=tmp_path/'outputs/attempt-1'; out.mkdir(parents=True)
    from ravel.physics import reinterpret_db
    def mock(command, out, config):
        req=json.loads((out/'native-input.json').read_text()); d=json.loads(Path(req['records']).read_text())
        raw=evaluated(d); result=pdf.transport(d,raw)
        result.update(config_sha256=req['config_sha256'],records_sha256=req['records_sha256'],
            imported_source_files=[{'path':str(Path(pdf.__file__).resolve()),'sha256':pdf._hash(pdf.__file__)}],
            native_libraries=[{'path':p['path'],'sha256':p['sha256']} for p in req['native_libraries']])
        pdf._write(out/'native-pdf-evaluations.json',raw); pdf._write(out/'pdf-variations.json',result)
        if mutation=='source': Path(d['source_inputs'][0]['path']).write_text('changed original')
        if mutation=='addition': (Path(config['pdf_data']['root'])/'new.json').write_text('{}')
        if mutation=='deletion': (Path(config['pdf_data']['root'])/pdf.SET/(pdf.SET+'_0100.dat')).unlink()
        if mutation=='copied-grid': (Path(req['grid_root'])/'lhapdf.conf').write_text('changed copy')
        if mutation=='copied-record': Path(req['records']).write_text('{}')
        return {'mocked':True, 'actual_native_execution':False}
    monkeypatch.setattr(reinterpret_db,'execute_native',mock)
    if mutation is None:
        result=pdf.run(task,tmp_path,out)
        assert result['physics_validated'] is False and result['native_execution']['actual_native_execution'] is False
    else:
        with pytest.raises(ValueError): pdf.run(task,tmp_path,out)


def test_native_configuration_paths_bind_before_verbosity_singleton(tmp_path):
    grid=tmp_path/'grid'; make_grid(grid)
    calls=[]
    class Paths:
        def setPaths(self, paths):
            calls.append(('paths',paths)); assert paths==[str(grid),'','']
        def paths(self): return [str(grid)]
        def findFile(self,name): return str(grid/name)
        def setVerbosity(self,value):
            assert calls[0][0]=='paths'; calls.append(('verbosity',value))
    pdf.bind_data_paths(Paths(),grid)
    assert calls[-1]==('verbosity',0)


def test_native_configuration_refuses_install_prefix_or_lookup_fallback(tmp_path):
    grid=tmp_path/'grid'; make_grid(grid)
    library=SimpleNamespace(setPaths=lambda paths:None,paths=lambda:[str(grid),'/ambient/install'],
        findFile=lambda name:str(grid/name), setVerbosity=lambda value:None)
    with pytest.raises(ValueError,match='fallback'): pdf.bind_data_paths(library,grid)
    library.paths=lambda:[str(grid)]
    library.findFile=lambda name:'/ambient/install/'+name
    with pytest.raises(ValueError,match='lookup'): pdf.bind_data_paths(library,grid)


def test_python_pdf_metadata_is_accessed_through_info_not_invented_member_method():
    # This reflects the wrapped PDF.info() -> PDFInfo(Info).get_entry surface.
    # The former fake direct PDF.get_entry incorrectly concealed the actual API failure.
    member=FakePDF(0)
    assert not hasattr(member, 'get_entry')
    assert member.info().get_entry('ForcePositive') == '0'
    assert FakePDF(0,clipped=True).info().get_entry('ForcePositive') == '1'


def test_each_mocked_member_metadata_accessor_is_observed(monkeypatch):
    seen=[]
    original=FakePDF.info
    def observed(self):
        seen.append(self.memberID)
        return original(self)
    monkeypatch.setattr(FakePDF,'info',observed)
    library=SimpleNamespace(version=lambda:'6.5.6',getPDFSet=lambda name:FakeSet())
    pdf.evaluate(document(),library)
    assert seen==list(range(101))
