"""Covariance diagnostics are public JSON: plain Python numbers, never NumPy scalars."""
import numpy as np
import pytest
from ravel.physics import derived_quantities as dq
from ravel.workflow import langchain_service as service


@pytest.mark.parametrize('matrix', [[[1.]], [[2., .5], [.5, 3.]], [[0., 0.], [0., 0.]]])
def test_matrix_diagnostics_hold_only_actual_json_types(matrix):
    covariance, diagnostics = dq._matrix(matrix, len(matrix))
    assert covariance.tolist() == matrix
    assert {key: type(value) for key, value in diagnostics.items()} == {
        'minimum_eigenvalue': float, 'roundoff_tolerance': float, 'matrix_repaired': bool}
    scale = max(max(abs(v) for row in matrix for v in row), np.finfo(float).tiny)
    assert diagnostics['roundoff_tolerance'] == 64 * float(np.finfo(float).eps) * len(matrix) * scale
    assert diagnostics['matrix_repaired'] is False
    # The charged service refuses any value that is not an actual JSON type.
    service._json({'value': diagnostics})
    with pytest.raises(service.ServiceError, match='actual JSON types'):
        service._json({'value': {'roundoff_tolerance': np.float64(diagnostics['roundoff_tolerance'])}})
