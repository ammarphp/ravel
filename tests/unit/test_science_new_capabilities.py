"""Actual supervised new-capability delivery with scoped human-review custody.

All inputs and reviewer votes here are explicit synthetic engineering controls.
These tests launch the real scientific worker, never a generator or native build.
Run only against a stable source tree because approval binds the whole package.
"""

from method_decision_fixture import admit_method
import pytest

from ravel import cli
from ravel.workflow import science, execution, physics_review as review
from ravel.workflow.state_io import atomic_json, read_json
from test_science_capability_integration import specification


@pytest.mark.parametrize('disposition,trigger', [('typed_compiler_refused', 'typed_compiler'),
    ('native_build_refused', 'native_compiler'), ('native_build_refused', None),
    ('event_mismatch', 'event_selection'), ('verified_on_supplied_events', None)])
def test_candidate_feedback_preserves_negative_and_limited_positive_outcomes(disposition, trigger):
    from ravel.physics.science_worker import diagnostic_presentation
    result = {'kind': 'routine-construction-feedback', 'status': 'passed',
              'candidate_disposition': disposition, 'failure_trigger': trigger,
              'physics_validated': False, 'execution_authorized': False,
              'source_scope': {'kind': 'supplied_object_port', 'unserved_obligations': ['detector response']},
              'source_dependency_review': {'complete': False}}
    fields, text = diagnostic_presentation('analyze', result)
    assert fields['candidate_disposition'] == disposition
    assert fields['source_scope']['unserved_obligations'] == ['detector response']
    assert fields['source_dependency_review']['complete'] is False
    assert fields['execution_authorized'] is False and fields['physics_validated'] is False
    assert disposition in text and 'does not approve' in text
    for key, value in [('execution_authorized', True), ('physics_validated', True),
                       ('candidate_disposition', 'accepted'), ('failure_trigger', 'unknown')]:
        with pytest.raises(ValueError, match='routine construction'):
            diagnostic_presentation('analyze', {**result, key: value})


def write_specification(tmp_path, mode):
    if mode == 'contrast':
        from test_event_contrasts import write_study
        task = write_study(tmp_path)
    else:
        from test_analysis_ir import program, contract, events
        for name, value in (('program.json', program()), ('objects.json', contract()), ('events.json', events())):
            atomic_json(tmp_path / name, value)
        task = {'backend': 'analysis-ir', 'program': 'program.json',
                'contract': 'objects.json', 'events': 'events.json'}
    spec = specification(mode, task)
    atomic_json(tmp_path / 'spec.json', spec)
    return tmp_path / 'run', tmp_path / 'spec.json'


@pytest.mark.parametrize('mode', ['contrast', 'analyze'])
def test_real_new_capability_pending_review_then_scoped_negative_acceptance(tmp_path, mode):
    rd, sp = write_specification(tmp_path, mode)
    assert cli.main(['plan', '--rundir', str(rd), '--spec', str(sp)]) == 0
    admit_method(rd)
    with pytest.raises((OSError, ValueError)):
        science.run(rd)
    science.approve(rd, 'Actual authorization for this bounded synthetic worker control', scripted=True)
    assert science.run(rd) == 0
    packet = science.packet(rd)
    assert packet['lifecycle_verdict'] == 'PENDING'
    assert 'review' in packet['next_required'].lower()
    record = execution.load_execution(rd)['stages']['science']
    assert record['status'] == 'succeeded'
    assert record['authorization_receipt']
    output = rd / 'outputs/attempt-1'
    result = read_json(output / 'result.json')
    assert result['status'] == 'passed' and result['physics_validated'] is False
    if mode == 'contrast':
        assert result['contrasts'][0]['difference'] == pytest.approx([-1 / 12, 1 / 6])
        assert result['independent_witness_status'] == 'verified'
    else:
        assert result['yields']['nominal'] == [1.0]
        assert result['independent_verification']['passed'] is True
        assert read_json(output / 'analysis-witness/trace.json')[-1]['event_id'] == 'rejected-zero'
    with pytest.raises(ValueError):
        science.run(rd, resume=True)

    # A negative scientific conclusion is legitimate diagnostic evidence when
    # integrity passed and this scope does not claim scientific agreement.
    checks = rd / 'inputs/control-checks.json'
    atomic_json(checks, {'schema_version': 1, 'checks': [
        {'id': name, 'status': status, 'attempt_ids': [record['attempt_id']],
         'evidence': [{'path': str(output / 'result.json'), 'location': '$'}]}
        for name, status in (('integrity', 'pass'), ('scientific', 'fail'))]})
    review.open_cycle(rd, effective_settings=science.review_effective_settings(rd),
                      stage_receipts=[record['attempt_record']], check_results=str(checks))
    for role, actor in (('physics_critic', 'critic'), ('skeptical_verifier', 'skeptic'), ('physics_decider', 'decider')):
        review.submit_review(rd, role=role, actor_id=actor, verdict='accept',
                             summary='Synthetic control verifies custody; the negative scientific check is retained',
                             claim_scope='diagnostic')
    assert science.packet(rd)['lifecycle_verdict'] == 'PASS'
    assert cli.main(['status', '--rundir', str(rd), '--write']) == 0
    assert read_json(rd / 'current_state.json')['lifecycle_verdict'] == 'PASS'
    before = execution.load_execution(rd)['stages']['science']['attempt_id']
    assert science.run(rd, resume=True) == 0
    assert execution.load_execution(rd)['stages']['science']['attempt_id'] == before


@pytest.mark.parametrize('mode', ['contrast', 'analyze'])
def test_new_execute_requires_prospective_v2_before_run_creation(tmp_path, mode):
    rd, sp = write_specification(tmp_path, mode)
    spec = read_json(sp)
    spec.update(schema_version=1)
    spec.pop('review_policy'); spec.pop('max_attempts')
    atomic_json(sp, spec)
    with pytest.raises(ValueError, match='version 2|v2|prospective'):
        science.plan(rd, sp)
    assert not rd.exists()
