"""Actual ordinary science and CI3 transport, without review authority seams."""
from pathlib import Path
import json

from ravel.workflow import physics_review as review, science, scientific_judgment as judgment
from ravel.workflow import ordinary_review_observations as observations
from test_research_cycle import specification, write
from test_research_full_cycle_transport import InertReviewHost
from test_autonomy_final_results import package
from method_decision_fixture import admit_method


def _roles(root, out):
    actors = review._read(root)[0]['policy']['actors']
    bindings = []
    for role, declared in (('critic', 'physics_critic'), ('verifier', 'skeptical_verifier'),
                           ('synthesizer', 'physics_decider')):
        binding = judgment.prepare_role(root, out/role, role=role, actor_id=actors[declared],
            model='control', reasoning_effort='high', max_output_tokens=2048,
            max_wall_seconds=30, claim_scope='supplied_math_diagnostic', allow_control=True)
        assert judgment.execute_role(binding, InertReviewHost())['complete']
        judgment.consume(root, binding, allow_control=True)
        bindings.append(binding)
    assert review.status(root)['state'] == 'accepted'
    return bindings


def final_triads(tmp_path):
    source = specification(tmp_path, 'paired', grouped=True)
    root = tmp_path/'ordinary'
    science.plan(root, Path(source['path']))
    admit_method(root)
    science.approve(root, 'Approve the exact supplied arithmetic control.', scripted=True)
    assert science.run(root) == 0
    record = science.execution.load_execution(root)['stages']['science']
    write(root/'inputs/checks.json', {'schema_version': 1, 'checks': [
        {'id': identity, 'status': 'pass', 'evidence': [{'path': 'outputs/attempt-1/result.json',
         'location': '$.quantities'}], 'attempt_ids': [record['attempt_id']]}
        for identity in ('integrity', 'math')]})
    review.open_cycle(root, effective_settings=science.review_effective_settings(root),
        stage_receipts=[record['attempt_record']], check_results='inputs/checks.json')
    ci2 = _roles(root, root/'ci2')
    predecessor = review._view(*review._read(root))['cycle']
    manifest, _ = package(root, predecessor)
    judgment.open_final_cycle(root, manifest=manifest, check_results='inputs/checks-final.json')
    ci3 = _roles(root, root/'ci3')
    return root, ci2, ci3


def test_genuine_final_triad_has_unique_current_role_observations(tmp_path):
    root, _, bindings = final_triads(tmp_path)
    actual = observations.final_roles(root)
    assert actual['status'] == 'observed', actual
    assert {row['role'] for row in actual['roles']} == {
        'physics-critic', 'skeptical-verifier', 'physics-decider'}
    assert {row['request']['sha256'] for row in actual['roles']} == {
        binding['request']['sha256'] for binding in bindings}
    assert len({row['request_id'] for row in actual['roles']}) == 3
    # The original pre-case request is also pinned as a public case anchor.
    # It must not make the current bound-request selection ambiguous, and it
    # remains live evidence even though it is not the selected vote subject.
    binding = bindings[0]
    bound = Path(binding['request']['path'])
    pre_case = bound.with_name('request.json')
    assert pre_case != bound and pre_case.is_file()
    assert json.loads(pre_case.read_text())['role'] == 'critic'
    saved = pre_case.read_bytes()
    pre_case.write_bytes(saved+b'\n')
    refused = observations.final_roles(root)
    assert refused['status'] == 'unknown' and refused['errors']
    pre_case.write_bytes(saved)
    assert observations.final_roles(root)['status'] == 'observed'
    # A remaining same-role pre-case document cannot substitute for the exact
    # displayed current request if that bound source is missing or replaced.
    saved = bound.read_bytes()
    bound.unlink()
    refused = observations.final_roles(root)
    assert refused['status'] == 'unknown' and refused['errors']
    bound.write_bytes(saved)
    forged = json.loads(saved)
    forged['cycle_sha256'] = '0'*64
    bound.write_text(json.dumps(forged))
    refused = observations.final_roles(root)
    assert refused['status'] == 'unknown' and refused['errors']
    bound.write_bytes(saved)
    assert observations.final_roles(root)['status'] == 'observed'
