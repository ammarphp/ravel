"""Complex amplitude recombination and immutable block controls, without MCFM."""
import numpy as np
import pytest

from ravel.physics import amplitude_store as store

SKILL = 'mcfm-amplitudes'


def test_record_lists_tested_blocks(handbook):
    assert handbook.listed(SKILL) == ['recombine-amplitudes', 'read-completed-block']


def test_recombination_keeps_relative_phase_and_interference(handbook):
    recombine = handbook.load(SKILL, 'recombine-amplitudes')['recombine']
    amplitudes = np.array([[[1., 1j]], [[1., -1j]]], dtype=complex)
    coefficients = np.array([[1., 1j], [1., 1j]])
    gram, weights = recombine(amplitudes, coefficients)
    assert weights.tolist() == pytest.approx([0., 4.])
    independent = np.sum(np.abs(np.einsum('nhk,nk->nh', amplitudes, coefficients))**2, axis=1)
    np.testing.assert_allclose(weights, independent)
    assert np.allclose(gram, np.conj(gram.swapaxes(-1, -2)))


def test_nonfinite_capture_is_refused(handbook):
    recombine = handbook.load(SKILL, 'recombine-amplitudes')['recombine']
    with pytest.raises(ValueError, match='finite'):
        recombine(np.array([[[np.nan]]]), np.array([[1.]]))


def test_completed_block_needs_digest_and_completion_marker(handbook, tmp_path):
    read = handbook.load(SKILL, 'read-completed-block')['read_completed_block']
    path = tmp_path / 'block.bin'
    with store.BlockWriter(path, {'basis': ['first'], 'observables': [], 'factor_unit': 'pb'}) as writer:
        writer.append(gram=np.array([[[1.]]]), factor=np.array([2.]))
        writer.finish({'attempted': 2, 'accepted': 1, 'rejected': 1, 'failed': 0})
    block = read(path)
    assert len(block['factor']) == 1
    path.write_bytes(path.read_bytes() + b'changed')
    with pytest.raises(ValueError, match='sha256'):
        read(path)
    store.marker_path(path).unlink()
    with pytest.raises(FileNotFoundError):
        read(path)
