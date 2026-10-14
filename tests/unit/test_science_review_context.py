"""Science role packets retain numerical evidence without producer headlines."""
import json

import pytest

from ravel.workflow import execution, physics_review as review, review_context as context, science
from ravel.workflow.state_io import atomic_json, read_json
from test_science_review_envelope import planned, token, checks


def _evidence(rd):
    proposal = science.verify_plan(rd, approved=True)
    stage, binding, _ = science._selected(rd, proposal)
    record = execution.begin_attempt(rd, 'science', binding, stage['log'])
    out = rd / 'outputs/attempt-1'
    result = {'schema_version': 1, 'kind': 'coupled_event_contrast', 'status': 'passed',
              'physics_validated': False, 'contrasts': [{'baseline': [1.], 'candidate': [2.],
                 'difference': [1.], 'covariance': [[.5]],
                 'precision': {'denominator': {'sumw': 10., 'precision_status': 'poorly_determined'}}}],
              'independent_witness_status': 'failed',
              'witness_receipts': {'C1': {'kind': 'numerical_witness_receipt', 'status': 'mismatch',
                 'arithmetic_verified': False, 'mismatches': ['/values/difference/0']}}}
    atomic_json(out / 'result.json', result)
    atomic_json(out / 'contrast-result.json', result)
    atomic_json(out / 'recipe.json', {'specification': science.execution_spec(rd),
        'input_snapshot': binding['input_snapshot'], 'sha256': execution.digest(science.execution_spec(rd))})
    atomic_json(out / 'verification.json', {'passed': True, 'physics_validated': False, 'expert_review': False,
        'scope': 'domain', 'result_sha256': execution.file_hash(out / 'result.json')})
    atomic_json(out / 'checkin2.json', {'schema_version': 1, 'kind': 'checkin2', 'sections': {
        'waypoint': {'scope': 'domain', 'status': 'passed', 'result': 'outputs/attempt-1/result.json'},
        'expectation': 'Explicit synthetic review projection fixture', 'ask': {'options': ['GO', 'ADJUST']}}})
    atomic_json(out / 'analysis-witness/verification.json', {'status': 'failed', 'physics_validated': False,
        'compared_events': 1, 'witnesses': [{'event_id': 'E1', 'node': 'selection', 'before': 0., 'after': 1.}]})
    atomic_json(out / 'analysis-witness/trace.json', {'event_id': 'E1', 'nodes': {
        'selection': {'status': 'defined', 'value': False}, 'mass': {'status': 'undefined', 'value': None}}})
    (rd / stage['log']).write_text('Synthetic retained arithmetic fixture\n')
    assert execution.finish_attempt(rd, record, 0) == 0
    return record, result


@pytest.mark.parametrize('role', ['critic', 'verifier', 'synthesizer'])
def test_science_packet_masks_proposal_and_aggregate_but_retains_negative_witness(planned, tmp_path, role):
    rd, _ = planned
    token(rd)
    record, original = _evidence(rd)
    checks(rd, record, 1, 'fail')
    review.open_cycle(rd, effective_settings=science.review_effective_settings(rd),
        stage_receipts=[record['attempt_record']], check_results='inputs/checks-1.json')
    out = tmp_path / ('packet-' + role)
    manifest = context.create(rd, role, out)
    values = {entry['source_path']: context.read_artifact(out, entry['id'], expected_manifest_sha256=manifest['sha256'])
              for entry in manifest['artifacts']}
    result = json.loads(values['outputs/attempt-1/result.json'])
    raw = json.loads(values['outputs/attempt-1/contrast-result.json'])
    recipe = json.loads(values['outputs/attempt-1/recipe.json'])
    assert json.loads(values[science.EXECUTION_TASK]) == read_json(rd / science.EXECUTION_TASK)
    if role == 'synthesizer':
        for path in context.SCIENCE_PRIVATE_INPUTS:
            assert values[path] == (rd / path).read_bytes()
        assert result == raw == original
        assert recipe == read_json(rd / 'outputs/attempt-1/recipe.json')
        return
    assert not context.SCIENCE_PRIVATE_INPUTS.intersection(values)
    assert 'status' not in result and 'status' not in raw
    assert result['contrasts'] == raw['contrasts'] == original['contrasts']
    assert result['independent_witness_status'] == 'failed'
    assert result['witness_receipts']['C1']['status'] == 'mismatch'
    assert result['physics_validated'] is False
    assert set(recipe['specification']) == {'schema_version', 'mode', 'task', 'assumptions'}
    # Scientific assumptions are source-bound inputs, not a producer verdict.
    assert recipe['specification']['assumptions'] == science.execution_spec(rd)['assumptions']
    assert recipe['specification']['assumptions'] == read_json(rd / science.SPEC)['assumptions']
    assert recipe['specification']['assumptions'] == ['No detector or independent physics validation is inferred']
    assert recipe['specification']['task'] == read_json(rd / science.EXECUTION_TASK)['task']
    assert recipe['input_snapshot'] == read_json(rd / 'outputs/attempt-1/recipe.json')['input_snapshot']
    witness = json.loads(values['outputs/attempt-1/analysis-witness/verification.json'])
    assert witness['status'] == 'failed' and witness['witnesses'][0]['after'] == 1.
    trace = json.loads(values['outputs/attempt-1/analysis-witness/trace.json'])
    assert trace['nodes']['selection']['status'] == 'defined'
    assert trace['nodes']['mass']['status'] == 'undefined'
    assert science.SPEC in {entry['source_path'] for entry in manifest['omissions']}


def test_model_probe_mask_retains_per_oracle_failure_and_applicability():
    report = {'schema_version': 1, 'domain': 'model-probe', 'status': 'failed', 'physics_validated': False,
              'details': {'checks_passed': False, 'checks': [
                  {'name': 'amplitude_reference', 'status': 'failed', 'max_relative_residual': .2},
                  {'name': 'ward_massless', 'status': 'not_applicable'}],
                  'rank': 1, 'execution': {'commands': [{'sha256': 'input identity'}]}}}
    projected, label = context._project_science_artifact(report, 'outputs/attempt-1/model-probe-result.json')
    assert 'status' not in projected and 'checks_passed' not in projected['details']
    assert projected['details']['checks'] == report['details']['checks']
    assert projected['details']['execution'] == report['details']['execution']
    assert 'aggregate producer' in label


def test_statistical_negative_identifiability_is_factual_evidence():
    report = {'schema_version': 1, 'kind': 'constructed_poisson_model', 'status': 'passed',
              'physics_validated': False, 'model_assessment': 'unidentified', 'inference': None,
              'local_identifiability': {'identified': False, 'rank': 1, 'null_directions': [[1., -1.]]},
              'independent_likelihood': {'passed': False, 'absolute_difference': .1}}
    projected, _ = context._project_science_artifact(report, 'outputs/attempt-1/statistical-model-result.json')
    assert 'status' not in projected
    for field in ('model_assessment', 'inference', 'local_identifiability', 'independent_likelihood'):
        assert projected[field] == report[field]
