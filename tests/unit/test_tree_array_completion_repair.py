"""V2 delivery/representation controls; inert readers, no actual ROOT data."""
from copy import deepcopy
from pathlib import Path
import numpy as np
import pytest
import test_tree_array_export as support
from ravel.physics import tree_array_export as a


def output(tmp_path, monkeypatch):
    task, _, _ = support.fixture(tmp_path)
    support.mock_runtime(monkeypatch)
    root = tmp_path / 'out'
    return a.run(task, tmp_path, root), root


def rewrite(result, root, mutate):
    cp = root / 'completion.json'
    commitment = a._json(cp.read_bytes())
    mutate(commitment)
    cp.write_bytes(a.encode(commitment))
    result['commitment'] = a._pin(cp)


@pytest.mark.parametrize('kind', ['missing-array', 'reordered-artifacts', 'extra-artifact',
                                  'missing-member', 'missing-directory', 'missing-input', 'missing-ancestor'])
def test_canonical_completion_cannot_replace_complete_original_roster(tmp_path, monkeypatch, kind):
    result, root = output(tmp_path, monkeypatch)
    def mutate(c):
        if kind == 'missing-array': c['artifacts'].pop(0)
        elif kind == 'reordered-artifacts': c['artifacts'].reverse()
        elif kind == 'extra-artifact': c['artifacts'].append(deepcopy(c['artifacts'][0]))
        elif kind == 'missing-member': c['members'].remove(support.OUTPUTS[1])
        elif kind == 'missing-directory': c['directories'].pop(str(root / 'arrays'))
        elif kind == 'missing-input': c['inputs'].pop()
        elif kind == 'missing-ancestor': c['ancestors'].pop(next(iter(c['ancestors'])))
    rewrite(result, root, mutate)
    with pytest.raises((ValueError, OSError)):
        a.finalize(result, root)


@pytest.mark.parametrize('kind', ['array-identity', 'file-id', 'handoff', 'column'])
def test_same_result_digest_does_not_override_original_array_correspondence(tmp_path, monkeypatch, kind):
    result, root = output(tmp_path, monkeypatch)
    if kind == 'array-identity': result['arrays'][0]['artifact'] = deepcopy(result['arrays'][1]['artifact'])
    elif kind == 'file-id': result['arrays'][0]['file_id'] = result['arrays'][1]['file_id']
    elif kind == 'handoff': result['filename_handoff'].reverse()
    else: result['columns'].reverse()
    stripped = {k: v for k, v in result.items() if k != 'commitment'}
    (root / 'delivery.json').write_bytes(a.encode(stripped))
    def mutate(c):
        c['result_sha256'] = a.hashlib.sha256(a.encode(stripped)).hexdigest()
        c['artifacts'][-1] = a._pin(root / 'delivery.json')
    rewrite(result, root, mutate)
    with pytest.raises((ValueError, OSError)):
        a.finalize(result, root)


def test_complete_external_copy_is_not_original_completion(tmp_path, monkeypatch):
    result, root = output(tmp_path, monkeypatch)
    foreign = tmp_path / 'complete-external.json'
    foreign.write_bytes((root / 'completion.json').read_bytes())
    result['commitment'] = a._pin(foreign)
    with pytest.raises(ValueError, match='canonical completion'):
        a.finalize(result, root)


def test_completion_change_after_consumed_buffer_refuses(tmp_path, monkeypatch):
    result, root = output(tmp_path, monkeypatch)
    cp = root / 'completion.json'
    real = Path.read_bytes
    observed = []
    def read(path):
        raw = real(path)
        if path == cp:
            observed.append(True)
            cp.write_bytes(raw + b' ')
        return raw
    monkeypatch.setattr(Path, 'read_bytes', read)
    with pytest.raises((ValueError, OSError)):
        a.finalize(result, root)
    assert observed


@pytest.mark.parametrize('number,dtype', [(-(2**63), np.int64), (2**63 - 1024, np.int64),
                                         (2**63, np.uint64), (2**64 - 2048, np.uint64),
                                         (2**53, np.int64), (0, np.uint64)])
def test_exact_large_integer_values_remain_supported(number, dtype):
    values = a._vector(np.array([number], dtype=dtype), np)
    assert values.dtype == np.float64 and int(values[0]) == number


@pytest.mark.parametrize('number,dtype', [(2**63 - 2, np.int64), (2**64 - 2, np.uint64),
                                         (2**53 + 1, np.uint64)])
def test_near_extrema_cannot_hide_integer_rounding(number, dtype):
    with pytest.raises(ValueError, match='representable'):
        a._vector(np.array([number], dtype=dtype), np)


def test_actual_full_conversion_refuses_nonrepresentable_raw_mcweight(tmp_path, monkeypatch):
    task, _, _ = support.fixture(tmp_path)
    values = support.branches()
    values['mcWeight'] = np.array([2**63 - 1, 0, -2], dtype=np.int64)
    support.mock_runtime(monkeypatch, values=values)
    with pytest.raises(ValueError, match='representable'):
        a.run(task, tmp_path, tmp_path / 'out')
    assert not (tmp_path / 'out' / 'completion.json').exists()
