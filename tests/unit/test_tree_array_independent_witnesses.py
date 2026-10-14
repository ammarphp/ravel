"""Independent original-source witnesses; actual product body, inert reader."""
from copy import deepcopy
from pathlib import Path
import hashlib
import numpy as np
import pytest
import test_tree_array_export as support
from ravel.physics import tree_array_export as a


def output(tmp_path, monkeypatch):
    task, request, roots = support.fixture(tmp_path)
    support.mock_runtime(monkeypatch)
    dest = tmp_path / 'out'
    return a.run(task, tmp_path, dest), dest


def test_authenticated_completion_buffer_not_separate_path_read(tmp_path, monkeypatch):
    result, dest = output(tmp_path, monkeypatch)
    commitment = Path(result['commitment']['path'])
    original = commitment.read_bytes()
    parsed = a._json(original)
    damaged = Path(result['arrays'][0]['artifact']['path'])
    damaged.write_bytes(b'SUBSTITUTED ARRAY; NOT THE COMMITTED NPY')
    substituted = deepcopy(parsed)
    substituted['artifacts'] = [p for p in parsed['artifacts'] if p['path'] != str(damaged)]
    b = a.encode(substituted)
    real_read = Path.read_bytes
    seen = []
    def other_buffer(path):
        if path == commitment:
            seen.append(str(path))
            return b
        return real_read(path)
    monkeypatch.setattr(Path, 'read_bytes', other_buffer)
    with pytest.raises((ValueError, OSError)):
        a.finalize(result, dest)
    assert seen and real_read(commitment) == original


def test_commitment_cannot_be_rebound_to_external_reduced_inventory(tmp_path, monkeypatch):
    result, dest = output(tmp_path, monkeypatch)
    original_commitment = Path(result['commitment']['path']).read_bytes()
    parsed = a._json(original_commitment)
    damaged = Path(result['arrays'][1]['artifact']['path'])
    damaged.write_bytes(b'WRONG ARRAY')
    parsed['artifacts'] = [p for p in parsed['artifacts'] if p['path'] != str(damaged)]
    foreign = tmp_path / 'foreign-completion.json'
    foreign.write_bytes(a.encode(parsed))
    result['commitment'] = a._pin(foreign)
    with pytest.raises((ValueError, OSError)):
        a.finalize(result, dest)
    assert (dest / 'completion.json').read_bytes() == original_commitment


def test_independent_tuple_and_scalar_oracle():
    b = support.branches()
    b['photon_pt'][2] = [101., 202., 303., 404., 505., 606., 707., 808.]
    b['photon_eta'][2] = [-1., -2., -3., -4., -5., -6., -7., -8.]
    b['photon_phi'][2] = [.11, .22, .33, .44, .55, .66, .77, .88]
    b['photon_isTightID'][2] = [0, 1, 0, 0, 0, 0, 0, 0]
    b['mcWeight'] = np.array([-13., 0., 17.])
    b['SumWeights'] = np.array([101., 102., 103.])
    b['XSection'] = np.array([.21, .22, .23])
    for i, name in enumerate(support.SCALARS[5:]): b[name] = np.array([i + 2.] * 3)
    array, info = a.convert(b, 3, np=np, ak=support.FakeAk, max_ram_mib=1,layout=support.migration_layout())
    np.testing.assert_array_equal(array[2, :6], [101., -1., .11, 202., -2., .22])
    np.testing.assert_array_equal(array[:, 32], [-13., 0., 17.])
    np.testing.assert_array_equal(array[:, 33], [101., 102., 103.])
    np.testing.assert_array_equal(array[:, 34], [.21, .22, .23])
    assert array[2, 35] == 0 and array[2, 36] == 1
    assert array.shape == (3, 46) and np.isnan(array[:, 44:]).all()
    assert len(info['nan_counts']) == 46


@pytest.mark.parametrize('number', [-(2**53 + 1), 2**63 - 1, 2**64 - 1])
def test_large_integer_source_value_refuses_loss(number):
    dtype = np.uint64 if number > 2**63 - 1 else np.int64
    with pytest.raises(ValueError): a._vector(np.array([number], dtype=dtype), np)


def test_no_false_missing_runtime_fallback(monkeypatch):
    called = []
    def missing(name):
        called.append(name)
        raise ImportError('Required reader unavailable in this inert control')
    monkeypatch.setattr(a.importlib, 'import_module', missing)
    with pytest.raises(ValueError, match='requires'): a._runtime()
    assert called == ['numpy']
