"""Synthetic review routing controls; no scientific compute or model calls."""
from copy import deepcopy

import pytest

from ravel.workflow import agent_graph as graph, finding_routing as routing
from ravel.workflow import physics_review as review, role_registry as roles
from ravel.workflow import research_protocol, scientific_judgment
from ravel.workflow.state_io import read_json, atomic_json
from test_agent_graph import node, pin, spec
from test_role_registry import finding as role_finding
from test_physics_review import run as physics_run, opened, finding as journal_finding
from test_manuscript_claim_disposition import contract
from ravel.workflow import manuscript_claim_disposition as disposition


@pytest.fixture
def run(physics_run):
    root, _ = physics_run
    policy = read_json(root / review.POLICY)
    policy['claim_scopes']['reproduction']['claim_ids'] = ['universal']
    atomic_json(root / review.POLICY, policy)
    return physics_run


def classification(kind='defect', *, sha='a' * 64, target='produce', effect='bounds', bound='restricted scope', claim='universal'):
    if kind == 'defect':
        return {'kind': kind, 'artifact_sha256': sha, 'target': target,
                'rework_evidence': 'The located input check shows the output changes when the error is corrected.'}
    return {'kind': kind, 'artifact_sha256': sha,
            'claims': [{'claim_id': claim, 'effect': effect, 'bound': bound}]}


def classified(kind='defect', **kwargs):
    return {**role_finding(), 'classification': classification(kind, **kwargs)}


def document(item, version=2):
    return {'schema_version': version, 'kind': 'findings', 'items': [item], 'handoff': None}


def graph_fixture(tmp_path, reworks=2):
    source = tmp_path / 'input.json'; source.write_text('{"value": 1}')
    root = tmp_path / 'graph'
    graph.create(root, spec([node('produce', inputs=[pin(source)]), node('check', ['produce']),
                             node('deliver', ['check']), node('independent')], reworks=reworks))
    return root, pin(source)['sha256']


def test_legacy_documents_validate_unchanged_and_keep_prior_effect():
    old = document(role_finding(), 1)
    before = deepcopy(old)
    assert roles.validate_output('findings.v1', old) == []
    assert roles.validate_output('findings.v2', old) == []
    assert routing.kind(old['items'][0]) == 'unclassified'
    assert roles.finding_effect(old['items'][0], resolve=lambda _: 'code_check') == 'blocking'
    assert old == before


@pytest.mark.parametrize('kind', ['defect', 'limitation'])
def test_classified_documents_validate(kind):
    assert roles.validate_output('findings.v2', document(classified(kind))) == []


@pytest.mark.parametrize('fault', ['target', 'rework_evidence', 'digest', 'classification', 'claims', 'bound'])
def test_new_incomplete_findings_refused(fault):
    item = classified('limitation' if fault in ('claims', 'bound') else 'defect')
    if fault == 'digest': item['classification']['artifact_sha256'] = 'changed'
    elif fault == 'classification': del item['classification']
    elif fault == 'bound': del item['classification']['claims'][0]['bound']
    else: del item['classification'][fault]
    assert roles.validate_output('findings.v2', document(item))


def test_defect_invalidates_exact_target_and_descendants(tmp_path):
    root, sha = graph_fixture(tmp_path)
    state = graph.rework(root, reason='located defect', findings=[classified(sha=sha)])
    assert state['reworks'] == 1
    assert {k: n['generation'] for k, n in state['nodes'].items()} == {
        'produce': 1, 'check': 1, 'deliver': 1, 'independent': 0}
    assert state['usage']['calls'] == 0


@pytest.mark.parametrize('target', ['absent', 'independent'])
def test_caller_cannot_widen_or_replace_defect_target(tmp_path, target):
    root, sha = graph_fixture(tmp_path)
    with pytest.raises(graph.GraphError):
        graph.rework(root, [target], reason='wrong target', findings=[classified(sha=sha)])
    assert graph.status(root)['reworks'] == 0


def test_limitation_routes_after_budget_exhaustion_without_any_invalidation(tmp_path):
    root, sha = graph_fixture(tmp_path, reworks=0)
    state = graph.rework(root, ['produce'], reason='scope disclosure', findings=[classified('limitation', sha=sha)])
    assert state['reworks'] == 0 and all(n['generation'] == 0 for n in state['nodes'].values())
    assert state['limitation_census'][0]['disposition'] == 'qualified'
    assert roles.finding_effect(classified('limitation'), resolve=lambda _: 'code_check') == 'claim_disposition'


def test_same_finding_on_unchanged_digest_is_not_reworked_even_with_new_reviewer_id(tmp_path):
    root, sha = graph_fixture(tmp_path, reworks=1)
    item = classified(sha=sha)
    first = graph.rework(root, findings=[item], reason='repair')
    item['id'] = 'second-review'
    item['statement'] = 'The same missing observation, restated by another reviewer.'
    second = graph.rework(root, findings=[item], reason='same objection')
    assert second['reworks'] == first['reworks'] == 1
    assert second['nodes'] == first['nodes']
    assert len(second['finding_reworks']) == 1


def test_changed_artifact_allows_fresh_repair(tmp_path):
    root, sha = graph_fixture(tmp_path, reworks=3)
    graph.rework(root, findings=[classified(sha=sha)], reason='repair')
    source = tmp_path / 'input.json'; source.write_text('{"value": 2}')
    plan = read_json(root / graph.SPEC)
    plan['nodes'][0]['inputs'] = [pin(source)]
    graph.revise(root, plan, reason='new artifact')
    state = graph.rework(root, findings=[classified(sha=pin(source)['sha256'])], reason='changed bytes')
    assert state['reworks'] == 3


def test_unbound_artifact_cannot_request_rework(tmp_path):
    root, _ = graph_fixture(tmp_path)
    with pytest.raises(graph.GraphError, match='artifact digest'):
        graph.rework(root, findings=[classified()], reason='unbound claim')
    assert graph.status(root)['reworks'] == 0


def test_reclassification_keeps_original_and_requires_decider_reason():
    original = classified('limitation')
    changed = routing.reclassify(original, classification(), actor_id='decider', decider_id='decider',
                                 reason='The approximation was applied outside its declared domain due to an input error.')
    assert changed['classification'] == original['classification']
    assert routing.kind(changed) == 'defect' and routing.kind(original) == 'limitation'
    assert changed['reclassifications'][0]['reason']
    with pytest.raises(ValueError):
        routing.reclassify(original, classification(), actor_id='critic', decider_id='decider', reason='override')
    with pytest.raises(ValueError):
        routing.reclassify(original, classification(), actor_id='decider', decider_id='decider', reason=' ')
    with pytest.raises(ValueError):
        routing.reclassify(original, classification(sha='b' * 64), actor_id='decider', decider_id='decider', reason='replace evidence')


@pytest.mark.parametrize('effect,bound,expected', [('bounds','restricted scope','qualified'),
    ('invalidates','claim fails','withdrawn'), ('bounds','unbounded','withdrawn')])
def test_affected_claim_must_be_qualified_or_withdrawn_in_final_prose(effect, bound, expected):
    plan, rows, value, evidence = contract()
    item = classified('limitation', effect=effect, bound=bound)
    rows[0].update(disposition=expected, reason=bound)
    value['paragraphs'][0]['text'] += ' ' + bound
    result = disposition.validate(plan, rows, value, evidence, final=True, review_findings=[item])
    assert result[0]['disposition'] == expected
    rows[0]['disposition'] = 'retained'
    with pytest.raises(ValueError, match='limitation'):
        disposition.validate(plan, rows, value, evidence, final=True, review_findings=[item])


def journal_classified(root, kind, **kwargs):
    item = journal_finding()
    if kind == 'limitation':
        policy = read_json(root / review.POLICY)
        kwargs.setdefault('claim', policy['claim_scopes']['reproduction'].get('claim_ids', ['reproduction'])[0])
    item['classification'] = classification(kind, sha=review.execution.file_hash(root / 'outputs/produced.json'),
                                            target='detector', **kwargs)
    if kind == 'limitation': item.update(required_paths=[], required_stages=[])
    return item


def disposition_package(root, item, *, chosen=None):
    plan, rows, value, evidence = contract()
    affected = item['classification']['claims'][0]
    identity = affected['claim_id']
    plan['claim_map'][0]['id'] = identity
    rows[0]['planned_claim_id'] = identity; rows[0]['original']['id'] = identity
    rows[0]['disposition'] = chosen or ('withdrawn' if affected['effect'] == 'invalidates'
                                       or affected['bound'] == 'unbounded' else 'qualified')
    rows[0]['reason'] = affected['bound']
    value['paragraphs'][0]['text'] += ' ' + affected['bound']
    path = root / 'inputs/claim-disposition.json'
    atomic_json(path, {'plan': plan, 'rows': rows, 'value': value, 'evidence': evidence})
    return {'path': 'inputs/claim-disposition.json', 'sha256': review.execution.file_hash(path)}


def test_headline_invalidated_without_rework_or_endless_delivery_loop(run):
    root, _ = run; opened(run)
    item = journal_classified(root, 'limitation', effect='invalidates', bound='claim fails')
    review.submit_review(root, role='physics_critic', actor_id='critic', verdict='send_back',
                         summary='Withdraw the headline claim', findings=[item])
    assert review.status(root)['state'] == 'awaiting_review'
    with pytest.raises(ValueError, match='correction'):
        review.authorize_correction(root, actor_id='physicist', changed_paths=[], stages=['detector'], recheck_checks=['agreement'])
    for role, actor in [('skeptical_verifier', 'skeptic'), ('physics_decider', 'physicist')]:
        review.submit_review(root, role=role, actor_id=actor, verdict='accept', summary='Deliver the scoped negative result', claim_scope='diagnostic',
                             **({'supporting_artifacts': [disposition_package(root, item)]} if role == 'physics_decider' else {}))
    state = review.status(root)
    assert state['state'] == 'accepted' and state['redos_used'] == 0
    assert state['limitation_census'][0]['disposition'] == 'withdrawn'
    assert research_protocol.review_limitation_census(root) == state['limitation_census']
    assert review.gate_errors(root, 'delivery') == []
    plan, rows, value, evidence = contract(); rows[0].update(disposition='withdrawn', reason='claim fails')
    value['paragraphs'][0]['text'] += ' claim fails'
    assert disposition.validate(plan, rows, value, evidence, final=True, review_findings=[item])[0]['disposition'] == 'withdrawn'


def test_journal_decider_reclassification_is_durable_and_original_is_preserved(run):
    root, _ = run; opened(run)
    item = journal_classified(root, 'defect')
    original = review.submit_review(root, role='physics_critic', actor_id='critic', verdict='send_back',
                                   summary='Review error', findings=[item])
    replacement = classification('limitation', sha=item['classification']['artifact_sha256'])
    with pytest.raises(ValueError, match='decider'):
        review.reclassify_finding(root, item['id'], replacement, actor_id='critic', reason='Override')
    event = review.reclassify_finding(root, item['id'], replacement, actor_id='physicist', reason='The residual is a declared bounded approximation.')
    assert event['event'] == 'finding_reclassified'
    reg, events = review._read(root)
    assert next(e for e in events if e['event'] == 'review') == original
    assert review._view(reg, events)['findings'] == []
    assert review._view(reg, events)['limitation_census'][0]['finding']['classification']['kind'] == 'defect'
    assert review.status(root)['redos_used'] == 0
    assert review.validate_snapshot({'schema_version': 1, 'registration': reg, 'events': events,
        'checkpoint': read_json(root / review.HEAD), 'action': 'history', 'stage': None}, require_admission=False) == []


def test_scientific_output_accepts_classified_limitation_and_legacy_findings():
    from jsonschema import Draft202012Validator
    schema = scientific_judgment.output_schema()['properties']['findings']['items']
    old = journal_finding()
    assert not list(Draft202012Validator(schema).iter_errors(old))
    old.update(classification=classification('limitation'), required_stages=[], required_paths=[])
    assert not list(Draft202012Validator(schema).iter_errors(old))


def test_failed_classified_correction_cannot_spend_another_redo_on_same_bytes(run):
    from test_physics_review import correct
    root, _ = run; opened(run)
    item = journal_classified(root, 'defect')
    review.submit_review(root, role='physics_critic', actor_id='critic', verdict='send_back', summary='Repair the input', findings=[item])
    first = correct(root)
    review.fail_correction(root, correction_id=first['correction_id'], reason='Synthetic failed repair')
    with pytest.raises(ValueError, match='unchanged finding'):
        review.authorize_correction(root, actor_id='physicist', changed_paths=['inputs/settings.cfg'],
                                    stages=['detector'], recheck_checks=['agreement'])
    assert review.status(root)['redos_used'] == 1


def test_research_census_cannot_drop_review_limitations(run):
    root, _ = run; opened(run)
    item = journal_classified(root, 'limitation')
    review.submit_review(root, role='physics_critic', actor_id='critic', verdict='send_back', summary='Scope disclosure', findings=[item])
    value = {'limitations': [{'id': 'scope', 'subject': 'Declared domain', 'flaw': 'Finite approximation',
        'consequence': 'Restricted claim', 'opportunity': 'Report the bound',
        'testable_signature': 'A supplied check', 'evidence': ['located record']}]}
    original = deepcopy(value)
    current = research_protocol.current_limitation_census(root, value)
    assert value == original
    assert current['review_limitations'] == research_protocol.review_limitation_census(root)
    assert current['review_limitations'][0]['disposition'] == 'qualified'


@pytest.mark.parametrize('kind', ['unclassified', 'defect', 'limitation', 'reclassified'])
def test_hosted_transport_accepts_exact_legacy_and_classified_variants(kind):
    from ravel.workflow import agent_host
    old = journal_finding()
    if kind != 'unclassified':
        old['classification'] = classification('limitation' if kind in ('limitation', 'reclassified') else 'defect')
    if kind == 'reclassified':
        old = routing.reclassify(old, classification(), actor_id='decider', decider_id='decider', reason='Located input error')
    schema = scientific_judgment.output_schema()['properties']['findings']['items']
    wrapper = {'type': 'object', 'properties': {'finding': schema}, 'required': ['finding'], 'additionalProperties': False}
    assert agent_host.validate_public_result({'finding': old}, wrapper)['finding'] == old
    old['unexpected'] = 'field'
    with pytest.raises(agent_host.HostFailure):
        agent_host.validate_public_result({'finding': old}, wrapper)


def test_fresh_defect_on_changed_bytes_can_repair_without_recharging_inherited_finding(run):
    from test_physics_review import correct, make_attempt, check_packet
    root, _ = run; opened(run)
    first_finding = journal_classified(root, 'defect')
    review.submit_review(root, role='physics_critic', actor_id='critic', verdict='send_back', summary='First defect', findings=[first_finding])
    first = correct(root)
    attempt = make_attempt(root, value=2); check_packet(root, attempt)
    opened((root, attempt), correction_id=first['correction_id'])
    second_finding = journal_classified(root, 'defect'); second_finding['id'] = 'F2'
    review.submit_review(root, role='physics_critic', actor_id='critic', verdict='send_back', summary='Changed artifact defect', findings=[second_finding])
    (root/'inputs/settings.cfg').write_text('efficiency=0.9\n')
    second = review.authorize_correction(root, actor_id='physicist', changed_paths=['inputs/settings.cfg'],
                                         stages=['detector'], recheck_checks=['agreement'])
    assert len(second['finding_reworks']) == 1
    assert not set(first['finding_reworks']) & set(second['finding_reworks'])
    assert review.status(root)['redos_used'] == 2
    assert review._view(*review._read(root))['cycle']['inherited_findings'][0]['id'] == 'F1'


def test_repeated_defect_on_unchanged_bytes_stays_visible_and_cannot_be_reworked_again(run):
    from test_physics_review import accept, check_packet, correct, make_attempt
    root, _ = run; opened(run)
    unchanged = review.execution.file_hash(root / 'inputs/held-fixed.txt')
    first = journal_finding(); first['classification'] = classification(sha=unchanged, target='detector')
    review.submit_review(root, role='physics_critic', actor_id='critic', verdict='send_back', summary='Repair', findings=[first])
    amendment = correct(root)
    fresh = make_attempt(root, value=2); check_packet(root, fresh)
    opened((root, fresh), correction_id=amendment['correction_id'])
    accept(root, closes=['F1'])
    later = make_attempt(root, value=3); check_packet(root, later)
    opened((root, later), checkpoint=True)
    repeated = deepcopy(first); repeated['id'] = 'F2'
    review.submit_review(root, role='physics_critic', actor_id='critic', verdict='send_back', summary='Same objection', findings=[repeated])
    state = review.status(root)
    assert state['state'] == 'send_back' and [f['id'] for f in state['unresolved_findings']] == ['F2']
    with pytest.raises(ValueError, match='rejected cycle'):
        review.submit_review(root, role='skeptical_verifier', actor_id='skeptic', verdict='accept', summary='Accept', claim_scope='reproduction')
    with pytest.raises(ValueError, match='unchanged finding'):
        correct(root)
    assert review.status(root)['redos_used'] == 1


def test_decider_cannot_send_back_limitations_without_an_actionable_defect(run):
    root, _ = run; opened(run)
    item = journal_classified(root, 'limitation')
    with pytest.raises(ValueError, match='decider'):
        review.submit_review(root, role='physics_decider', actor_id='physicist', verdict='send_back',
                             summary='Scope disclosure', findings=[item])
    assert review.status(root)['state'] == 'awaiting_review'
    review.submit_review(root, role='physics_decider', actor_id='physicist', verdict='accept',
                         summary='Deliver the qualified scope', findings=[item], claim_scope='diagnostic',
                         supporting_artifacts=[disposition_package(root, item)])
    assert review.status(root)['limitation_census'][0]['finding_id'] == item['id']


def test_reclassification_cannot_strand_a_decider_rejection_or_hide_a_defect_in_an_acceptance(run):
    root, _ = run; opened(run)
    defect = journal_classified(root, 'defect')
    review.submit_review(root, role='physics_decider', actor_id='physicist', verdict='send_back', summary='Repair', findings=[defect])
    sha = defect['classification']['artifact_sha256']
    with pytest.raises(ValueError, match='actionable defect'):
        review.reclassify_finding(root, defect['id'], classification('limitation', sha=sha), actor_id='physicist', reason='Scope only.')
    assert review.status(root)['state'] == 'send_back'


def test_reclassified_limitation_in_an_acceptance_cannot_become_an_ignored_defect(run):
    root, _ = run; opened(run)
    item = journal_classified(root, 'limitation')
    review.submit_review(root, role='physics_critic', actor_id='critic', verdict='accept', summary='Qualified',
                         findings=[item], claim_scope='diagnostic')
    sha = item['classification']['artifact_sha256']
    with pytest.raises(ValueError, match='acceptance'):
        review.reclassify_finding(root, item['id'], classification(sha=sha, target='detector'), actor_id='physicist', reason='Input error.')
    assert review.status(root)['limitation_census'][0]['finding_id'] == item['id']


def test_submitted_defect_target_must_be_an_allowed_owning_stage(run):
    root, _ = run; opened(run)
    item = journal_classified(root, 'defect')
    item['classification']['target'] = 'absent-stage'
    with pytest.raises(ValueError, match='owning stage'):
        review.submit_review(root, role='physics_critic', actor_id='critic', verdict='send_back',
                             summary='Located defect', findings=[item])


def test_nonmanuscript_delivery_cannot_ignore_an_invalidated_accepted_scope(run):
    root, _ = run; opened(run)
    item = journal_classified(root, 'limitation', effect='invalidates', bound='claim fails')
    review.submit_review(root, role='physics_critic', actor_id='critic', verdict='send_back',
                         summary='Withdraw the result claim', findings=[item])
    review.submit_review(root, role='skeptical_verifier', actor_id='skeptic', verdict='accept', summary='Scoped result', claim_scope='reproduction')
    with pytest.raises(ValueError, match='withdrawn'):
        review.submit_review(root, role='physics_decider', actor_id='physicist', verdict='accept', summary='Scoped result',
                             claim_scope='reproduction', supporting_artifacts=[disposition_package(root, item)])
    assert review.gate_errors(root, 'delivery')


def test_limitation_claim_alias_must_be_explicitly_mapped_before_submission(run):
    root, _ = run; opened(run)
    item = journal_classified(root, 'limitation', claim='unrelated-claim')
    head = (root / review.HEAD).read_bytes()
    with pytest.raises(ValueError, match='policy claim scope'):
        review.submit_review(root, role='physics_critic', actor_id='critic', verdict='send_back',
                             summary='Unbound alias', findings=[item])
    assert (root / review.HEAD).read_bytes() == head


def test_reclassified_limitation_cannot_introduce_an_unbound_claim_alias(run):
    root, _ = run; opened(run)
    item = journal_classified(root, 'defect')
    review.submit_review(root, role='physics_critic', actor_id='critic', verdict='send_back',
                         summary='Located defect', findings=[item])
    replacement = classification('limitation', sha=item['classification']['artifact_sha256'], claim='unrelated-claim')
    with pytest.raises(ValueError, match='policy claim scope'):
        review.reclassify_finding(root, item['id'], replacement, actor_id='physicist', reason='Bounded claim')


def test_bounded_claim_scope_can_deliver_with_visible_witnessed_qualification(run):
    root, _ = run; opened(run)
    item = journal_classified(root, 'limitation', bound='restricted supplied domain')
    review.submit_review(root, role='physics_critic', actor_id='critic', verdict='send_back',
                         summary='Qualification required', findings=[item])
    review.submit_review(root, role='skeptical_verifier', actor_id='skeptic', verdict='accept',
                         summary='Qualified scope', claim_scope='reproduction')
    with pytest.raises(ValueError, match='disposition package'):
        review.submit_review(root, role='physics_decider', actor_id='physicist', verdict='accept',
                             summary='Missing witness', claim_scope='reproduction')
    proof = disposition_package(root, item)
    decision = review.submit_review(root, role='physics_decider', actor_id='physicist', verdict='accept',
        summary='Witnessed qualification', claim_scope='reproduction', supporting_artifacts=[proof])
    assert decision['limitation_disposition']['sha256'] == proof['sha256']
    assert review.gate_errors(root, 'delivery') == []
    assert review.validate_snapshot(review.snapshot(root, action='delivery')) == []
    assert review.status(root)['redos_used'] == 0
    (root / proof['path']).write_text('{}')
    assert review.gate_errors(root, 'delivery')


def legacy_limitation_acceptance(root, item):
    """Seed the exact former acceptance shape to exercise current historical gates."""
    for role, actor in [('physics_critic', 'critic'), ('skeptical_verifier', 'skeptic'), ('physics_decider', 'physicist')]:
        reg, events = review._read(root)
        review._append(root, reg, events, {'event': 'review', 'cycle_id': review._view(reg, events)['cycle']['cycle_id'],
            'role': role, 'actor_id': actor, 'verdict': 'accept', 'summary': 'Historical scoped result',
            'findings': [item] if role == 'physics_critic' else [], 'closes': [], 'claim_scope': 'diagnostic',
            'attestation': review.ATTESTATION})


@pytest.mark.parametrize('claim', ['universal', 'unrelated-claim'])
def test_historical_limitation_stays_readable_but_cannot_escape_live_or_detached_delivery(run, claim):
    root, _ = run; opened(run)
    item = journal_classified(root, 'limitation', claim=claim)
    legacy_limitation_acceptance(root, item)
    assert review.status(root)['state'] == 'accepted'
    reg, events = review._read(root)
    history = {'schema_version': 1, 'registration': reg, 'events': events,
               'checkpoint': read_json(root / review.HEAD), 'action': 'delivery', 'stage': None}
    assert review.validate_snapshot(history, require_admission=False) == []
    assert review.validate_snapshot(history)
    assert review.gate_errors(root, 'delivery')
    assert review.gate_errors(root, 'final_task')


def test_explicit_claim_mapping_preserves_old_policy_shape_and_requires_unique_claims():
    from test_physics_review import policy
    old = policy(); assert review.validate_policy(old) == []
    current = deepcopy(old); current['claim_scopes']['reproduction']['claim_ids'] = ['universal']
    assert review.validate_policy(current) == []
    for claims in ([], ['universal', 'universal'], 'universal'):
        current['claim_scopes']['reproduction']['claim_ids'] = claims
        assert review.validate_policy(current)
