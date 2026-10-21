"""Governed admission, engagement accounting and current-subject review controls."""
import json
from types import SimpleNamespace

import pytest

from test_p04_support import (context, digest, graphs, inert_worker, install_plan, make_step,
                              records, run_env, run_step, services_installed)


def test_engagement_dispatch_keeps_packet_and_raw_usage(run_env, inert_worker, graphs):
    outcome = run_step(run_env, make_step('produce'))
    assert outcome['status'] == 'completed', outcome
    dispatch = records(run_env.store, 'step-dispatch')[0]
    observation = records(run_env.store, 'step-observation')[0]
    assert dispatch['packet_tokens'] > 0
    assert dispatch['purpose'] == 'producer'
    assert dispatch['node_id'] == observation['node_id']
    assert observation['usage']['reported'] is True
    assert observation['usage']['input_tokens'] > 0
    assert outcome['model']['tier'] == 'judgment'
    assert outcome['model']['effort_requested'] == dispatch['selection']['effort']


@pytest.mark.parametrize('tokens, holds', [(100, True), (100000, False)])
def test_transport_observations_reach_the_engagement_floor(run_env, inert_worker, graphs, tokens, holds):
    from ravel.controller.engagement.envelope import evaluate
    executable = inert_worker.executable
    source = executable.read_text()
    assert "'input_tokens': 100," in source
    executable.write_text(source.replace("'input_tokens': 100,", f"'input_tokens': {tokens},", 1))
    # Refresh the probe after changing the inert executable's bytes, and qualify it again.
    from ravel.workflow import transport_registry as tr
    from test_p04_support import qualify
    qualify(run_env.store, tr.probe('claude-cli-worker', executable=str(executable)))
    outcome = run_step(run_env, make_step('produce'))
    assert outcome['status'] == 'completed', outcome
    store = run_env.store
    result = evaluate(records(store, 'step-dispatch'), records(store, 'step-observation'),
        [row for row in records(store, 'instruction-delivery') if row.get('kind') == 'instruction-delivery-session'],
        expected=None, stage='wave')
    assert result['hold'] is holds, result
    assert result['floors']['H2']['status'] == ('below_floor' if holds else 'ok')


def test_declared_review_seats_replace_the_unapplied_roster(run_env):
    from ravel.controller.step import graph
    parent = make_step('produce', review=['integrity-auditor'])
    parent['seats'] = [{'seat': 'producer', 'role': 'baseline-producer', 'kind': 'producer'},
                       {'seat': 'one', 'role': 'skeptical-verifier', 'kind': 'review'}]
    assert graph._seat_roles(run_env.store, parent, {'id': 'baseline-producer'}, {}) == ['skeptical-verifier']
    parent['seats'] = []
    assert graph._seat_roles(run_env.store, parent, {'id': 'baseline-producer'}, {}) == []


def test_declared_constraint_union_keeps_the_installed_card(run_env):
    from ravel.controller.step import cards, graph, services
    from ravel.workflow import role_registry
    pinned = role_registry.registry_sha256()
    card, card_sha, _ = cards.resolve('baseline-producer', {'registry_sha256': pinned})
    declared = {'items': [{'id': 'duty-one', 'text': 'Inspect every supplied value.'}],
                'constraints': {'fresh_session': True, 'distinct_actor_from': ['producer'],
                                'forbidden_inputs': ['private-answer'], 'required_inputs': ['public-input'],
                                'blind': True}}
    state = {'acting': make_step('inspect'), 'card': {'id': card['id'], 'sha256': card_sha,
                                                    'registry_sha256': pinned},
             'seat': {'declared': declared}}
    effective = graph._card(state)
    assert effective['requires']['blind'] is True
    assert 'producer' in effective['independence']['distinct_actor_from']
    assert 'private-answer' in effective['sees']['forbidden_inputs']
    assert 'public-input' in effective['sees']['required_inputs']
    assert cards.resolve(card['id'], {'registry_sha256': pinned})[0] == card


@pytest.mark.parametrize('route', ['inspect', 'legacy'])
def test_read_only_route_guard_runs_before_dispatch(run_env, inert_worker, graphs, route):
    from ravel.controller import step as governed
    step = make_step('produce')
    pin = install_plan(run_env.store, [step])
    result = governed.run(run_env.store, step, context(run_env.store, run_env.run_dir, pin, route=route))
    assert result['status'] == 'held', result
    assert result['reason'] == 'effectful_kind'
    assert records(run_env.store, 'step-dispatch') == []


@pytest.mark.parametrize('approved', [False, True])
def test_mode_admission_uses_current_plan_chain(run_env, inert_worker, graphs, approved):
    from ravel.controller import graph as controller, step as governed
    from test_p12_modes import inference_plan
    plan, step = inference_plan()
    step['depends_on'] = []
    step['budget'] = {'wall_seconds': 60, 'events': 0}
    step.setdefault('parameters', {})['launch'] = {'argv': ['/bin/true']}
    plan['steps'] = [step]
    plan['deliverables'][0].update(step=step['id'], output=step['outputs'][0]['path'])
    pin = install_plan(run_env.store, [step])
    stored = records(run_env.store, 'plan')[-1]
    plan['sha256'] = digest({key: value for key, value in plan.items() if key != 'sha256'})
    pin = plan['sha256']
    stored['plan_sha256'] = pin
    stored['blob'] = run_env.store.put_blob(json.dumps(plan).encode())
    run_env.store.append('plan', stored)
    if approved:
        # The test replaces the installed plan; its approval commits these new bytes.
        from ravel.controller.confine import commitments
        commitments.create(run_env.store, plan, run_env.run_dir)
    asked = []
    def chain(store, pins):
        asked.append((store, pins))
        return ({'id': 'approval', 'subject': {'pins': {'plan_sha256': 'old'}}},
                {'id': 'amendment', 'subject': {'pins': pins}}) if approved else (None, None)
    authority = SimpleNamespace(plan_authority=chain, current=lambda *a, **k: None)
    with controller.services(authority=authority):
        outcome = governed.run(run_env.store, step, context(run_env.store, run_env.run_dir, pin))
    assert asked and asked[0][1] == {'plan_sha256': pin}
    if approved:
        assert outcome['reason'] != 'mode_authority_missing', outcome
        assert records(run_env.store, 'step-launch') and run_env.fakes['confine'].launched
        assert records(run_env.store, 'step-dispatch') == []
    else:
        assert outcome['status'] == 'held' and outcome['reason'] == 'mode_authority_missing', outcome
        assert records(run_env.store, 'step-dispatch') == []

    assert bool(run_env.fakes['confine'].launched) is approved


@pytest.mark.parametrize('valid', [True, False])
def test_decide_requires_a_stored_judgment_before_adoption(run_env, inert_worker, graphs, valid):
    from test_p08_fakes import record
    step = make_step('choose', kind='decide', outputs=[('outputs/choice.json', 'judgment-record')])
    step['consequence_class'] = 'R2'
    body = record('choose') if valid else {'step': 'choose'}
    inert_worker.scenario(writes=[{'path': 'outputs/choice.json', 'content': json.dumps(body)}])
    outcome = run_step(run_env, step)
    if valid:
        assert outcome['status'] == 'completed', outcome
        assert len(outcome['judgments']) == 1
        stored = run_env.store.read('judgment-record', outcome['judgments'][0])['record']
        assert stored['step'] == 'choose' and stored['class'] == 'R2'
    else:
        assert outcome['status'] == 'failed' and 'judgment_record' in outcome['reason'], outcome
        assert outcome['judgments'] == []
        assert records(run_env.store, 'custody') == []


def test_decide_without_a_judgment_output_cannot_complete(run_env, inert_worker, graphs):
    outcome = run_step(run_env, make_step('choose', kind='decide'))
    assert outcome['status'] == 'failed' and 'judgment_record_missing' in outcome['reason'], outcome
    assert records(run_env.store, 'custody') == []


def test_author_can_deliver_a_claim_map(run_env, inert_worker, graphs):
    outcome = run_step(run_env, make_step('claims', outputs=[('outputs/claims.json', 'claim_map')]))
    assert outcome['status'] == 'completed', outcome
    assert any(row['artifact'] == 'claims:outputs/claims.json' for row in outcome['outputs'])


def test_protected_observations_govern_the_reviewer_verdict():
    from ravel.controller.step import graph
    assert graph._verdict({'items': []}, [], [{'status': 'failed'}]) == 'revise'
    assert graph._verdict({'items': []}, [], [{'status': 'inconclusive'}]) == 'unresolved'
    assert graph._verdict({'items': []}, [], [{'status': 'passed'}]) == 'accept'


def test_reviewer_receives_all_same_spec_observations(run_env, tmp_path):
    from ravel.controller.step import graph, services
    from ravel.workflow import broker, review_projection, review_projection_checks as rpc, role_registry
    artifact = {'path': 'inputs/check.json', 'sha256': broker.digest({})}
    checks = {'check:ml-estimand-declared': {'source': 'graph', 'verdict': 'fail'},
              'check:ml-statistics-sizing': {'source': 'validator', 'verdict': 'fail',
                  'validator': {'implementation': 'bounded-control'}, 'artifact': artifact},
              'check:ml-claim-scope': {'source': 'validator', 'verdict': 'pass',
                  'validator': {'implementation': 'bounded-control'}, 'artifact': artifact}}
    bindings = rpc.record_ml_stage(run_env.store, spec={'scope': 'bounded'}, stage='S1', result={'checks': checks})
    state = {'context': {'run_id': run_env.store.run_id}, 'step': {},
             'acting': {'role': 'ml-reviewer', 'check_inputs': {'check:ml-claim-scope': bindings['check:ml-claim-scope']}}}
    with services.bound(run_env.store):
        observed = graph._ml_observations(state)
    assert sorted(row['status'] for row in observed) == ['failed', 'failed', 'passed']
    assert len({row['binding']['record_id'] for row in observed}) == 3
    for row in observed:
        assert row['result_sha256'] == broker.digest(rpc.observed_ml_result(
            run_env.store, row['binding'], check_id=row['check_id']))
    _, files = review_projection.build(tmp_path, role_registry.load('ml-reviewer'),
                                       item={'role': 'ml-reviewer', 'findings': observed})
    projected = json.loads(next(raw for path, raw in files if path.endswith('/item.json')))
    assert projected['findings'] == observed


def test_reviewer_without_bound_observations_stays_unresolved(run_env):
    from ravel.controller.step import graph, services
    state = {'context': {'run_id': run_env.store.run_id}, 'step': {}, 'acting': {'role': 'ml-reviewer'}}
    with services.bound(run_env.store):
        observed = graph._ml_observations(state)
    assert len(observed) == 1 and observed[0]['status'] == 'inconclusive'
    assert graph._verdict({'items': []}, [], observed) == 'unresolved'


def test_review_dispatch_retains_a_seat_outcome(run_env, inert_worker, graphs):
    outcome = run_step(run_env, make_step('produce', review=['integrity-auditor']))
    seats = outcome.get('review', {}).get('seats') or []
    assert len(seats) == 1 and seats[0]['status'] is not None, json.dumps({
        'outcome': outcome, 'refusals': records(run_env.store, 'step-refusal'),
        'outcomes': records(run_env.store, 'step-outcome'),
        'validations': records(run_env.store, 'step-validation')}, indent=2)


@pytest.mark.parametrize('verdict, status', [('revise', 'revise'), ('unresolved', 'held'), ('accept', 'completed')])
def test_credited_revise_is_not_completed(run_env, verdict, status):
    from ravel.controller.step import budget, graph, services
    step = make_step('produce')
    pin = install_plan(run_env.store, [step])
    findings = run_env.store.append('step-review-findings', {'verdict': verdict, 'record': {'items': []}})
    reservation = budget.reserve(run_env.store, step_id=step['id'], attempt=1,
        amounts={key: 1 if key == 'children' else 0 for key in budget.DIMENSIONS},
        ceilings={key: 10 for key in budget.DIMENSIONS})
    state = {'step': step, 'acting': step, 'branch': 'worker', 'validation': {'passed': True},
             'context': context(run_env.store, run_env.run_dir, pin), 'reservation': reservation,
             'credit': {'credited': True, 'verdict': verdict, 'findings': [findings],
                        'seats': [{'role': 'integrity-auditor', 'credited': True}]}}
    before = budget.totals(run_env.store)
    assert graph._status_of(state)[0] == status
    with services.bound(run_env.store):
        outcome = graph.finish(state)['outcome']
    assert outcome['status'] == status
    assert outcome['review']['verdict'] == verdict
    assert outcome['review']['findings'] == [findings]
    assert outcome['reservation_key'] == reservation['key']
    assert budget.totals(run_env.store) == before
    if verdict != 'accept':
        assert findings in outcome['reason']


def test_dispatched_revise_keeps_the_findings_record(run_env, inert_worker, graphs):
    inert_worker.scenario(seats={'integrity-auditor': {'items': [{'severity': 'A', 'summary': 'value needs repair'}]}})
    outcome = run_step(run_env, make_step('produce', review=['integrity-auditor']))
    assert outcome['review']['credited'] is True, outcome
    assert outcome['status'] == 'revise' and outcome['review']['verdict'] == 'revise', outcome
    assert outcome['review']['findings']
    found = run_env.store.read('step-review-findings', outcome['review']['findings'][0])['record']
    assert found['record']['items'][0]['severity'] == 'A'
    assert outcome['review']['findings'][0] in outcome['reason']


def test_changed_attempt_has_fresh_artifact_identity_and_keeps_prior_budget(run_env, inert_worker, graphs):
    from ravel.controller.step import budget
    step = make_step('produce')
    first = run_step(run_env, step)
    assert first['status'] == 'completed', first
    charged = budget.totals(run_env.store)['children']['charged']
    original = records(run_env.store, 'budget-reservation')[0]
    original_bytes = (run_env.run_dir / 'steps/produce/outputs/result.json').read_bytes()
    inert_worker.scenario(writes=[{'path': 'outputs/result.json', 'content': '{"value": 2}'}])
    second = run_step(run_env, step, attempt=2)
    assert second['status'] == 'completed', second
    old = next(row for row in first['outputs'] if row['path'] == 'outputs/result.json')
    new = next(row for row in second['outputs'] if row['path'] == 'outputs/result.json')
    assert old['artifact_id'] != new['artifact_id'] and old['sha256'] != new['sha256']
    assert (run_env.run_dir / 'steps/produce/outputs/result.json').read_bytes() == original_bytes
    assert records(run_env.store, 'budget-reservation')[0]['key'] == original['key'] == first['reservation_key']
    assert budget.totals(run_env.store)['children']['charged'] == charged + 1


def test_old_credit_cannot_accept_a_changed_subject(run_env, inert_worker, graphs):
    step = make_step('produce', review=['integrity-auditor'])
    first = run_step(run_env, step)
    assert first['status'] == 'completed' and first['review']['credited'] is True, first
    run_env.fakes['independence'].independent = False
    inert_worker.scenario(writes=[{'path': 'outputs/result.json', 'content': '{"value": 2}'}])
    second = run_step(run_env, step, attempt=2)
    assert second['status'] == 'held' and second['reason'] == 'review_uncredited', second
    assert second['review']['credited'] is False
    assert second['subject_sha256'] != first['subject_sha256']
    observations = records(run_env.store, 'step-observation')
    assert len({row['session_id'] for row in observations}) == 4


@pytest.mark.parametrize('kind', ['ask', 'route'])
def test_parent_requests_hold_until_the_outcome_contract_is_available(run_env, inert_worker, graphs, kind):
    outcome = run_step(run_env, make_step('request', kind=kind, role=None, outputs=()))
    assert outcome['status'] == 'escalated' and outcome['escalation'] == kind, outcome
    assert outcome['request']['kind'] == kind
    assert outcome['request']['status'] == 'escalated' and outcome['request']['escalation'] == kind
    assert records(run_env.store, 'step-dispatch') == []


def test_dispatched_reviewer_projects_failed_computation_findings(run_env, inert_worker, graphs):
    from ravel.workflow import agent_worker, review_projection, review_projection_checks as rpc
    from test_p13_validator_adapters import audit
    checks = {'check:ml-estimand-declared': {'verdict': 'fail', 'source': 'graph'}}
    bindings = rpc.record_ml_stage(run_env.store, spec={'scope': 'bounded'}, stage='S1', result={'checks': checks})
    step = make_step('inspect', kind='review', role='assumption-auditor',
                     outputs=[('outputs/findings.json', 'findings')])
    (run_env.run_dir / 'inputs/audit.json').write_text(json.dumps(audit()))
    step['parameters']['check_inputs'] = {**bindings,
        'check:validation.assumption_audit.check': {'document': 'inputs/audit.json'}}
    outcome = run_step(run_env, step)
    assert outcome['status'] == 'revise' and outcome['review']['credited'] is True, outcome
    dispatch = records(run_env.store, 'step-dispatch')[0]
    packet = agent_worker._record(run_env.run_dir, dispatch['node_id'], 1)['packet']
    assert packet is not None
    _, artifacts = review_projection.load(packet)
    item = json.loads(artifacts['review/packets'])
    assert [row['status'] for row in item['findings']] == ['failed']
    assert item['findings'][0]['binding'] == bindings['check:ml-estimand-declared']


def test_structural_admission_cannot_replace_staged_runtime_checks():
    from ravel.controller.step import operations, services
    step = make_step('train', kind='operate', role='ml-trainer', operation='ml-stage-train')
    with pytest.raises(services.StepHold) as raised:
        operations._legacy_route_errors(step, {})
    assert raised.value.reason == 'mode_context_admission_unavailable'
