"""Synthetic energy-only collections, numerical refusals and read diagnostics."""
import math
from types import SimpleNamespace

import awkward as ak
import numpy as np
import pytest
import uproot

from ravel import toolkit
from ravel.physics.columnar import expressions, formats


def _descriptor(mass=None, *, extra=None, variations=None):
    fields = {'pt': 'obj_pt_NOSYS', 'eta': 'obj_eta', 'phi': 'obj_phi'}
    if mass is not None:
        fields['mass'] = mass
    fields.update(extra or {})
    return formats.Descriptor({
        'schema_version': 1, 'kind': 'columnar-format', 'name': 'synthetic energy input',
        'source': 'synthetic fixture', 'format': 'root', 'tree': 'events',
        'collections': {'objects': {'fields': fields}}, 'variations': variations or {},
    })


def _write(path, data):
    arrays = {name: value if isinstance(value, ak.Array) else ak.Array(value) for name, value in data.items()}
    with uproot.recreate(path) as root:
        root.mktree('events', {name: value.type for name, value in arrays.items()})
        root['events'].extend(arrays)
    return path


def _mass_fixture(path):
    # Two opposite jets at eta=0: M = sqrt(50^2 + 30^2) + sqrt(50^2 + 40^2).
    return _write(path, {'obj_pt_NOSYS': [[50., 50.], [], [12.]], 'obj_eta': [[0., 0.], [], [.5]],
                         'obj_phi': [[0., math.pi], [], [1.]],
                         'obj_e_NOSYS': [[math.hypot(50, 30), math.hypot(50, 40)], [],
                                         [math.hypot(12 * math.cosh(.5), 5)]]})


def _chunks(source, path, **kwargs):
    return list(source.read(path, collections=['objects'], event_fields=[], step=2, **kwargs))


def test_energy_only_without_mass_is_refused():
    with pytest.raises(ValueError, match='objects.*mass'):
        _descriptor(extra={'energy': 'obj_e_NOSYS'})


def test_fixed_zero_mass_records_invariant_mass_bias(tmp_path):
    source = _descriptor({'fixed': 0., 'source': 'synthetic massless approximation'})
    objects = source.view(_chunks(source, _mass_fixture(tmp_path / 'objects.root'))[0]).collections['objects']
    measured = toolkit.invariant_mass(objects.pt, objects.eta, objects.phi, objects.mass)[0]
    expected = math.hypot(50, 30) + math.hypot(50, 40)
    assert measured == pytest.approx(100.)
    assert expected - measured == pytest.approx(22.34076032378151)


@pytest.mark.parametrize('energy', ['obj_e_NOSYS', 'energy', {'branch': 'obj_e_NOSYS', 'scale': 1.}])
def test_from_energy_matches_analytic_mass(tmp_path, energy):
    source = _descriptor({'from_energy': energy}, extra={'energy': 'obj_e_NOSYS'})
    path = _mass_fixture(tmp_path / 'objects.root')
    assert 'obj_e_NOSYS' in source.check_file(path)['branches']
    views = [source.view(chunk) for chunk in _chunks(source, path)]
    objects = views[0].collections['objects']
    assert toolkit.invariant_mass(objects.pt, objects.eta, objects.phi, objects.mass)[0] == pytest.approx(
        math.hypot(50, 30) + math.hypot(50, 40), rel=1e-9)
    assert objects.mass.tolist() == [[pytest.approx(30.), pytest.approx(40.)], []]
    assert views[1].collections['objects'].mass.tolist() == [[pytest.approx(5.)]]


def test_negative_mass_squared_is_counted_per_chunk_and_read(tmp_path):
    path = _write(tmp_path / 'rounding.root', {
        'obj_pt_NOSYS': [[10.], [], [20., 30.]], 'obj_eta': [[0.], [], [0., 0.]],
        'obj_phi': [[0.], [], [0., 0.]], 'obj_e_NOSYS': [[10. * (1 - 1e-8)], [], [20., 30. * (1 - 1e-8)]],
    })
    source = _descriptor({'from_energy': 'obj_e_NOSYS', 'tolerance': 1e-7})
    summary = {}
    chunks = _chunks(source, path, summary=summary)
    views = [source.view(chunk) for chunk in chunks]
    assert [v.summary['negative_mass_squared'] for v in views] == [{'objects': 1}, {'objects': 1}]
    assert [c.extra['negative_mass_squared'] for c in chunks] == [{'objects': 1}, {'objects': 1}]
    assert summary['negative_mass_squared'] == {'objects': 2}
    assert views[0].collections['objects'].mass.tolist() == [[0.], []]
    source.view(chunks[0])  # Repeated evaluation must not inflate a read diagnostic.
    assert summary['negative_mass_squared'] == {'objects': 2}


@pytest.mark.parametrize('tolerance', [None, 1e-7])
def test_unphysical_energy_is_refused_with_collection_name(tmp_path, tolerance):
    path = _write(tmp_path / 'unphysical.root', {'obj_pt_NOSYS': [[10.]], 'obj_eta': [[0.]],
                                               'obj_phi': [[0.]], 'obj_e_NOSYS': [[9.]]})
    spec = {'from_energy': 'obj_e_NOSYS'}
    if tolerance is not None:
        spec['tolerance'] = tolerance
    source = _descriptor(spec)
    with pytest.raises(ValueError, match='objects.*negative mass squared'):
        source.view(_chunks(source, path)[0])


def test_roundoff_requires_declared_tolerance(tmp_path):
    path = _write(tmp_path / 'rounding.root', {'obj_pt_NOSYS': [[10.]], 'obj_eta': [[0.]],
                                            'obj_phi': [[0.]], 'obj_e_NOSYS': [[10. * (1 - 1e-12)]]})
    source = _descriptor({'from_energy': 'obj_e_NOSYS'})
    with pytest.raises(ValueError, match='objects.*negative mass squared'):
        source.view(_chunks(source, path)[0])


@pytest.mark.parametrize('tolerance', [-1., 1., True, 'small', float('inf'), float('nan')])
def test_invalid_tolerance_is_refused(tolerance):
    with pytest.raises(ValueError, match='tolerance'):
        _descriptor({'from_energy': 'obj_e_NOSYS', 'tolerance': tolerance})


@pytest.mark.parametrize('rule', [{'replace': ['_NOSYS', '_UP']},
                                  {'branches': {'obj_pt_NOSYS': 'obj_pt_UP', 'obj_e_NOSYS': 'obj_e_UP'}}])
def test_energy_scaling_and_variations(tmp_path, rule):
    path = _write(tmp_path / 'scaled.root', {'obj_pt_NOSYS': [[50000.]], 'obj_pt_UP': [[60000.]],
                                          'obj_eta': [[.5]], 'obj_phi': [[0.]],
                                          'obj_e_NOSYS': [[1000 * math.hypot(50 * math.cosh(.5), 30)]],
                                          'obj_e_UP': [[1000 * math.hypot(60 * math.cosh(.5), 40)]]})
    source = _descriptor({'from_energy': {'branch': 'obj_e_NOSYS', 'scale': .001}}, variations={'up': rule})
    doc = source.doc
    doc['collections']['objects']['fields']['pt'] = {'branch': 'obj_pt_NOSYS', 'scale': .001}
    source = formats.Descriptor(doc)
    assert source.check_file(path, variations=['up'])['variations']['up']['obj_e_NOSYS'] == 'obj_e_UP'
    chunk = _chunks(source, path, variations=['up'])[0]
    assert source.view(chunk).collections['objects'].mass[0, 0] == pytest.approx(30.)
    assert source.view(chunk, 'up').collections['objects'].mass[0, 0] == pytest.approx(40.)


@pytest.mark.parametrize('dtype', ['i1', 'i4', '?'])
def test_per_object_flag_reads_as_boolean_mask(tmp_path, dtype):
    flag = ak.unflatten(np.array([1, 0, 1], dtype=dtype), [2, 0, 1])
    path = _write(tmp_path / 'flags.root', {'obj_pt_NOSYS': [[10., 20.], [], [30.]],
                                         'obj_eta': [[0., 0.], [], [0.]], 'obj_phi': [[0., 0.], [], [0.]],
                                         'obj_select_loose': flag})
    source = _descriptor({'fixed': 0., 'source': 'synthetic'}, extra={'select_loose': 'obj_select_loose'})
    source.check_file(path)
    objects = source.view(_chunks(source, path)[0]).collections['objects']
    mask = expressions.compile_expression('select_loose != 0', allowed={'select_loose'}).evaluate_cut(
        {'select_loose': objects.select_loose})
    assert mask.tolist() == [[True, False], []]
    assert objects[mask].pt.tolist() == [[10.], []]
    if dtype == '?':
        assert ak.to_numpy(ak.flatten(objects.select_loose)).dtype == np.dtype(bool)


def test_vector_char_typename_is_accepted(monkeypatch):
    branches = [SimpleNamespace(name=name, typename='vector<char>' if name.endswith('select_loose') else 'vector<double>')
                for name in ('obj_pt_NOSYS', 'obj_eta', 'obj_phi', 'obj_select_loose')]
    tree = SimpleNamespace(num_entries=1, values=lambda **kwargs: branches)

    class File:
        def __enter__(self):
            return {'events': tree}

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(uproot, 'open', lambda path: File())
    source = _descriptor({'fixed': 0., 'source': 'synthetic'}, extra={'select_loose': 'obj_select_loose'})
    assert source.check_file('synthetic.root')['branches']['obj_select_loose'] == 'vector<char>'
    arrays = {name: ak.Array([[10., 20.]]) for name in ('obj_pt_NOSYS', 'obj_eta', 'obj_phi')}
    arrays['obj_select_loose'] = ak.unflatten(np.array([1, 0], dtype='i1'), [2])
    objects = source.view(formats.Chunk(0, 1, arrays, extra={'collections': ['objects']})).collections['objects']
    mask = expressions.compile_expression('select_loose != 0', allowed={'select_loose'}).evaluate_cut(
        {'select_loose': objects.select_loose})
    assert mask.tolist() == [[True, False]]
    assert objects[mask].pt.tolist() == [[10.]]


@pytest.mark.parametrize('energy', [float('nan'), float('inf'), -10.])
def test_nonfinite_or_negative_energy_is_refused(tmp_path, energy):
    path = _write(tmp_path / 'invalid.root', {'obj_pt_NOSYS': [[10.]], 'obj_eta': [[0.]],
                                           'obj_phi': [[0.]], 'obj_e_NOSYS': [[energy]]})
    source = _descriptor({'from_energy': 'obj_e_NOSYS'})
    with pytest.raises(ValueError, match='objects.*finite nonnegative'):
        source.view(_chunks(source, path)[0])


def test_energy_shape_mismatch_is_refused_instead_of_broadcast(tmp_path):
    path = _write(tmp_path / 'mismatch.root', {'obj_pt_NOSYS': [[10., 20.]], 'obj_eta': [[0., 0.]],
                                            'obj_phi': [[0., 0.]], 'obj_e_NOSYS': [[30.]]})
    source = _descriptor({'from_energy': 'obj_e_NOSYS'})
    source.check_file(path)
    with pytest.raises(ValueError, match='objects.*different lengths'):
        source.view(_chunks(source, path)[0])


def test_missing_energy_branch_is_named(tmp_path):
    source = _descriptor({'from_energy': 'missing_energy'})
    with pytest.raises(ValueError, match='objects.mass.*missing_energy'):
        source.check_file(_mass_fixture(tmp_path / 'objects.root'))


def test_mass_cannot_reference_itself():
    with pytest.raises(ValueError, match='objects.mass.*itself'):
        _descriptor({'from_energy': 'mass'})


def test_variation_counts_are_retained_once_per_evaluated_view(tmp_path):
    path = _write(tmp_path / 'rounding.root', {'obj_pt_NOSYS': [[10., 20.]], 'obj_eta': [[0., 0.]],
                                            'obj_phi': [[0., 0.]], 'obj_e_NOSYS': [[10., 20.]],
                                            'obj_e_UP': [[10. * (1 - 1e-8), 20.]]})
    source = _descriptor({'from_energy': 'obj_e_NOSYS', 'tolerance': 1e-7},
                         variations={'up': {'replace': ['_NOSYS', '_UP']}})
    summary = {}
    chunk = _chunks(source, path, variations=['up'], summary=summary)[0]
    assert source.view(chunk).summary['negative_mass_squared'] == {'objects': 0}
    assert source.view(chunk, 'up').summary['negative_mass_squared'] == {'objects': 1}
    source.view(chunk, 'up')
    assert chunk.extra['negative_mass_squared'] == {'objects': 1}
    assert summary['negative_mass_squared'] == {'objects': 1}


def test_energy_branch_can_supply_shape_when_other_fields_are_fixed(tmp_path):
    path = _write(tmp_path / 'fixed.root', {'obj_e': [[5., 10.], []]})
    doc = {'schema_version': 1, 'kind': 'columnar-format', 'name': 'synthetic fixed momentum',
           'source': 'synthetic fixture', 'format': 'root', 'tree': 'events',
           'collections': {'objects': {'fields': {
               key: {'fixed': 0., 'source': 'synthetic rest frame'} for key in ('pt', 'eta', 'phi')}}}}
    doc['collections']['objects']['fields']['mass'] = {'from_energy': 'obj_e'}
    source = formats.Descriptor(doc)
    assert source.view(_chunks(source, path)[0]).collections['objects'].mass.tolist() == [[5., 10.], []]


@pytest.mark.parametrize('energy', [{'fixed': 50., 'source': 'synthetic'}, 'energy'])
def test_fixed_energy_input_is_refused(energy):
    extra = {'energy': {'fixed': 50., 'source': 'synthetic'}}
    with pytest.raises(ValueError, match='objects.mass.*branch'):
        _descriptor({'from_energy': energy}, extra=extra)
