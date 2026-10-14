"""The comparison and certificate producer and its fail-closed R2/R3 consumer (B4 R2/R3 item 5)."""
import json

import pytest

from ravel.workflow import decision_gate, rdj_custody
from executor_fixtures import plan, run_root, write


def comparison():
    from ravel.workflow import comparison as module
    return module


DIVERGENCE = 'RP6:C1:divergence'
R2 = {'kind': 'tuning_change', 'floor': 'R2', 'digest': 'b' * 64, 'claim_id': 'C1'}


@pytest.fixture
def root(tmp_path):
    root = run_root(tmp_path)
    plan(root, claims=[{'id': 'C1', 'kind': 'agreement', 'basis_declared': ['authored_code']}])
    write(root / 'outputs/impl-a.json', {'yield_sr1': 10.0, 'yield_sr2': 4.0})
    write(root / 'outputs/impl-b.json', {'yield_sr1': 10.2, 'yield_sr2': 4.0})
    return root


def codes(root, action=R2):
    return [e.code for e in decision_gate.check(root, 'checkin2_accept', action) if e.provider == 'comparison']


def test_r2_acceptance_without_a_comparison_record_fails_closed(root):
    assert 'comparison_missing' in codes(root)


def test_below_r2_the_consumer_defers_to_the_ordinary_checkin2_providers(root, monkeypatch):
    from ravel.workflow import rdj_loop
    monkeypatch.setattr(rdj_loop, 'compute_class', lambda *a, **k: ('R1', {}))
    assert comparison().gate_errors(root, 'checkin2_accept', R2) == []
    monkeypatch.setattr(rdj_loop, 'compute_class', lambda *a, **k: ('R3', {}))
    assert [e.code for e in comparison().gate_errors(root, 'checkin2_accept', R2)] == ['comparison_missing']


def test_a_registered_comparison_within_tolerance_clears_the_point(root):
    pin = comparison().produce_comparison(root, DIVERGENCE, left='outputs/impl-a.json', right='outputs/impl-b.json',
                                          tolerance=0.05)
    assert pin['check_id'] == comparison().check_id('comparison', DIVERGENCE)
    record = rdj_custody.check_result(root, pin['check_id'])
    assert record['passed'] is True and record['scientific_acceptance'] is False
    assert 'comparison_missing' not in codes(root) and 'comparison_failed' not in codes(root)


def test_a_disagreement_beyond_tolerance_refuses(root):
    comparison().produce_comparison(root, DIVERGENCE, left='outputs/impl-a.json', right='outputs/impl-b.json',
                                    tolerance=0.001)
    assert 'comparison_failed' in codes(root)


def test_an_operand_changed_after_the_comparison_refuses(root):
    comparison().produce_comparison(root, DIVERGENCE, left='outputs/impl-a.json', right='outputs/impl-b.json',
                                    tolerance=0.05)
    write(root / 'outputs/impl-b.json', {'yield_sr1': 99.0, 'yield_sr2': 4.0})
    assert 'comparison_missing' in codes(root)


def test_an_unregistered_record_file_is_not_a_comparison(root):
    identity = comparison().check_id('comparison', DIVERGENCE)
    write(root / f'checks/comparison/{identity}.json', {'schema_version': 1, 'kind': 'ravel-check-result',
                                                        'check_id': identity, 'passed': True, 'operands': []})
    assert 'comparison_missing' in codes(root)


def test_operands_must_be_named_finite_numbers(root):
    write(root / 'outputs/bad.json', {'yield_sr1': 'many'})
    with pytest.raises(ValueError, match='finite number'):
        comparison().produce_comparison(root, DIVERGENCE, left='outputs/impl-a.json', right='outputs/bad.json',
                                        tolerance=0.1)
    with pytest.raises(ValueError, match='tolerance'):
        comparison().produce_comparison(root, DIVERGENCE, left='outputs/impl-a.json', right='outputs/impl-b.json',
                                        tolerance=-1)


def test_a_certificate_point_without_its_registered_certificate_refuses(root):
    point = {'id': 'RP5:C1', 'requires_certificate': True, 'claim_id': 'C1'}
    errors = comparison()._point_errors(root, 'checkin2_accept', point)
    assert [e.code for e in errors] == ['certificate_missing']
    assert errors[0].pins == ('check:' + comparison().check_id('certificate', 'C1'),)
