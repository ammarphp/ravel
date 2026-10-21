"""Root review populations preserve conditional policies and independent multiplicity."""
from copy import deepcopy
import json
import hashlib

import pytest

from ravel.controller import graph
from ravel.controller.routes import compiler
from ravel.controller.engagement import policy
from ravel.workflow import review_points, spawn_rows


REQUEST = {'nodes': [], 'edges': [], 'claims': [
    {'id': 'quantity', 'kind': 'prediction', 'absolute_yield': True,
     'deliverable': {'artifact': 'binned_values'}, 'basis_declared': ['unclassified']}]}


def conditional_plan(monkeypatch):
    monkeypatch.setattr('ravel.workflow.request_plan.draft', lambda *a: deepcopy(REQUEST))
    checkins = compiler._policy_checkins([
        {'id': 'checkin2', 'seats': list(graph.CI2_SEATS)},
        {'id': 'checkin3', 'seats': list(graph.CI3_SEATS)}], {}, {'agent_layer_epoch': 2}, waypoints=['derive'])
    return {'sha256': 'a' * 64, 'steps': [], 'checkins': checkins}


def test_root_compiler_retains_complete_conditional_policy_and_maximum_counts(monkeypatch):
    plan = conditional_plan(monkeypatch)
    waypoint = next(c for c in plan['checkins'] if c['id'] == 'checkin2')
    points = spawn_rows.derive({**REQUEST, 'agent_layer_epoch': 2, 'plan': REQUEST})
    expected = [p for p in points if p['gate'] == 'checkin2_accept'
                and p['mode'] in review_points.CONTROLLER_SEAT_MODES]
    assert expected
    for point in expected:
        assert point in waypoint['review_points']
        assert {r['role'] for r in point['roles']} <= set(waypoint['seats'])
    assert waypoint['seat_counts'] == {'re-deriver': 2}
    assert waypoint['seats'].count('re-deriver') == 1
    assert all(p['gate'] == 'checkin2_accept' for p in waypoint['review_points'])
    final = next(c for c in plan['checkins'] if c['id'] == 'checkin3')
    assert 'assumption-auditor' in final['seats']


def test_counted_engagement_descriptors_are_distinct_and_aliases_stay_unique(monkeypatch):
    plan = conditional_plan(monkeypatch)
    checkin = next(c for c in plan['checkins'] if c['id'] == 'checkin2')
    checkin['seats'] += ['re-deriver']
    descriptors = [s for s in policy.declared_seats(plan, policy.role_cards())
                   if s['category'] == 'checkin2' and s['role'] == 're-deriver']
    assert [s['key'] for s in descriptors] == ['checkin:checkin2:re-deriver', 'checkin:checkin2:re-deriver.2']
    assert [s['n'] for s in descriptors] == [1, 2]
    checkin.pop('seat_counts')
    assert len([s for s in policy.declared_seats(plan, policy.role_cards())
                if s['category'] == 'checkin2' and s['role'] == 're-deriver']) == 1


@pytest.mark.parametrize('purpose,checkpoint,expected_steps', [
    ('waypoint', 'checkin2', ['waypoint_review.re-deriver', 'waypoint_review.2.re-deriver']),
    ('final', 'checkin3', ['final_review', 'final_review.2']),
])
def test_root_run_seats_invokes_each_count_with_its_complete_policy(tmp_path, monkeypatch, purpose, checkpoint, expected_steps):
    plan = conditional_plan(monkeypatch)
    monkeypatch.setattr(graph, 'current_plan', lambda *a: plan)
    monkeypatch.setattr(graph, '_context', lambda *a, **kw: kw)
    calls = []
    def invoke(state, graph_id, view, segment):
        calls.append((deepcopy(view), deepcopy(segment)))
        return {'results': {'step': {'status': 'completed', 'review': {'credited': True, 'verdict': 'accept'}}}}
    monkeypatch.setattr(graph, '_invoke', invoke)
    class Store:
        def append(self, kind, record):
            self.record = record
            return 'review:1'
    store = Store()
    state = {'run': {'run_dir': str(tmp_path)}, 'reviews': {}}
    verdicts, attempt, record = graph._run_seats(state, store, ['re-deriver', 're-deriver'], purpose=purpose)
    assert len(calls) == 2
    assert [v['step']['id'] for v, _ in calls] == expected_steps
    assert len({json.dumps(segment, sort_keys=True) for _, segment in calls}) == 2
    assert len({v['step']['outputs'][0]['path'] for v, _ in calls}) == 2
    point = next(p for c in plan['checkins'] if c['id'] == checkpoint for p in c['review_points'] if p['row'] == 'K5')
    for n, (view, _) in enumerate(calls, 1):
        assert view['step']['parameters']['review_points'] == [
            {'point': point, 'n': n, 'sha256': review_points.jdigest(point)}]
    assert set(verdicts) == {'re-deriver', 're-deriver.2'}


def root_credit(tmp_path, monkeypatch, *, count=1):
    from test_review_point_seats import Seats
    from test_rdj_approval import canonical
    from ravel.controller.routes import plan_sha256
    seats = Seats(tmp_path, monkeypatch, claims=())
    request = {'nodes': [{'id': 'model', 'operation': 'model-sources', 'kind': 'operation'}],
               'claims': [], 'edges': []}
    seats.facts = {**seats.facts, **request, 'plan': request}
    point = next(p for p in spawn_rows.derive(seats.facts) if p['row'] == 'K10')
    # Real derived nonnumeric point; the multiplicity control explicitly strengthens its protected plan.
    if count > 1:
        point = {**deepcopy(point), 'roles': [{**point['roles'][0], 'count': count}]}
    plan = seats.install([], [])
    plan['checkins'] = [{'id': 'checkin3', 'seats': ['model-critic'], 'review_points': [point],
                         **({'seat_counts': {'model-critic': count}} if count > 1 else {})}]
    plan['sha256'] = plan_sha256(plan)
    seats.store.append('plan', {'plan_sha256': plan['sha256'], 'blob': seats.store.put_blob(canonical(plan)),
                               'source': 'judgment', 'revision': 1})
    seats.run.put('inputs/controller-plan.json', json.dumps(plan))
    subject = {'sha256': 'd' * 64, 'steps': [], 'artifacts': [], 'pins': {'steps_sha256': 'd' * 64}}
    pins = {'plan_sha256': plan['sha256'], 'steps_sha256': subject['sha256']}
    action = {'view_pins': pins, 'digest': review_points.jdigest(pins)}
    workers, verdicts, packets = [], {}, {}
    for n in range(1, count + 1):
        step = graph._seat_step('model-critic', purpose='final', plan=plan, n=n, subject=subject)
        seats.review(plan, 'model-critic', step_id=step['id'])
        packets[hashlib.sha256(f"receipt-{step['id']}-model-critic-1".encode()).hexdigest()] = deepcopy(seats.packets['model-critic'])
        workers.append({'run_id': seats.store.run_id, 'step': step['id'], 'attempt': 1,
                        'session_id': f"{step['id']}-model-critic-1", 'receipt_sha256': 'b' * 64,
                        'step_spec': step})
        seats.store.append('worker-session', workers[-1])
        verdicts[graph.review_seat_key('model-critic', n)] = {
            'step': step['id'], 'status': 'completed', 'credited': True, 'verdict': 'accept'}
    record = {'purpose': 'final', 'plan_sha256': plan['sha256'], 'attempt': 1,
              'seats': verdicts, 'subject': subject['pins'], 'subject_sha256': subject['sha256']}
    seats.store.append('review', record)
    from ravel.workflow import review_dispatch
    monkeypatch.setattr(review_dispatch, 'observed_projection',
                        lambda query: review_dispatch._manifest(packets.get(query['receipt_sha256'])))
    return seats, plan, point, action, workers, record


def test_conditional_credit_uses_real_independent_observed_sessions(tmp_path, monkeypatch):
    seats, plan, point, action, workers, record = root_credit(tmp_path, monkeypatch, count=2)
    missing, evidence = review_points._controller_missing(seats.root, [point], gate='final_task', action=action)
    assert missing == {point['id']: []}
    assert [r['n'] for r in evidence[point['id']]] == [1, 2]
    assert len({r['session'] for r in evidence[point['id']]}) == 2
    assert len({r['credit'] for r in evidence[point['id']]}) == 2


@pytest.mark.parametrize('mutation', ['missing_policy', 'changed_policy', 'old_round', 'old_subject', 'missing_worker'])
def test_conditional_credit_rejects_missing_or_stale_exact_policy(tmp_path, monkeypatch, mutation):
    seats, plan, point, action, workers, record = root_credit(tmp_path, monkeypatch)
    if mutation in ('missing_policy', 'changed_policy'):
        # A later observation of that worker cannot silently change the authenticated step spec.
        worker = deepcopy(workers[0])
        if mutation == 'missing_policy':
            worker['step_spec']['parameters'].pop('review_points')
        else:
            worker['step_spec']['parameters']['review_points'][0]['point']['roles'][0]['count'] = 2
        # A unique worker with malformed policy (rather than a duplicate observation) is tested via the read seam.
        scan = seats.store.scan
        monkeypatch.setattr(seats.store, 'scan', lambda kind: [{'record': worker}] if kind == 'worker-session' else scan(kind))
        from ravel.workflow import rdj_approval
        monkeypatch.setattr(rdj_approval, 'controller_plan', lambda root: (seats.store, plan))
    elif mutation == 'old_round':
        seats.store.append('review', {**record, 'attempt': 2})
    elif mutation == 'old_subject':
        action['view_pins']['steps_sha256'] = 'e' * 64
        action['digest'] = review_points.jdigest(action['view_pins'])
    else:
        scan = seats.store.scan
        monkeypatch.setattr(seats.store, 'scan', lambda kind: [] if kind == 'worker-session' else scan(kind))
        from ravel.workflow import rdj_approval
        monkeypatch.setattr(rdj_approval, 'controller_plan', lambda root: (seats.store, plan))
    missing, evidence = review_points._controller_missing(seats.root, [point], gate='final_task', action=action)
    assert missing[point['id']][0]['count'] == 1
    assert missing[point['id']][0]['reason']
    assert evidence[point['id']] == []


def test_one_credit_or_session_never_fills_two_conditional_occurrences(tmp_path, monkeypatch):
    from ravel.workflow import rdj_approval
    seats, plan, point, action, workers, record = root_credit(tmp_path, monkeypatch, count=2)
    missing, evidence = review_points._controller_missing(seats.root, [point], gate='final_task', action=action)
    assert not missing[point['id']]
    first = evidence[point['id']][0]
    # Even if an upstream lookup repeats an otherwise valid credit, the root cannot count it twice.
    original = rdj_approval.seat_review
    monkeypatch.setattr(rdj_approval, 'seat_review', lambda store, step, *a, **kw:
        ({k: v for k, v in first.items() if k not in ('step_id', 'n')}, None)
        if step.endswith('.2') else original(store, step, *a, **kw))
    missing, evidence = review_points._controller_missing(seats.root, [point], gate='final_task', action=action)
    assert missing[point['id']][0]['count'] == 1
    assert len(evidence[point['id']]) == 1


def test_numeric_conditional_review_stays_pending_without_a_comparison_join(tmp_path, monkeypatch):
    seats, plan, point, action, workers, record = root_credit(tmp_path, monkeypatch)
    point = {**point, 'comparison_required': True, 'tolerance_required': True}
    missing, evidence = review_points._controller_missing(seats.root, [point], gate='final_task', action=action)
    assert missing[point['id']][0]['code'] == 'comparison_evidence_required'
    assert evidence[point['id']] == []


@pytest.mark.parametrize('tier', ['lean', 'standard', 'full'])
def test_counted_mandatory_seats_keep_their_own_execution_at_every_tier(monkeypatch, tier):
    from test_p18_policy import fakes
    plan = conditional_plan(monkeypatch)
    plan.update(route={'id': 'judgment'}, deliverables=[])
    cards = policy.role_cards()
    rules = fakes.policy_for(plan, cards)
    result = policy.seat_plan(plan, tier, rules, cards=cards, instructions=fakes.FakeInstructions)
    for checkpoint in ('checkin2', 'checkin3'):
        for n in (1, 2):
            key = f'checkin:{checkpoint}:' + graph.review_seat_key('re-deriver', n)
            assert result['bindings'][key] == key
            [seat] = [s for s in result['seats'] if s['key'] == key]
            assert seat['n'] == n and seat['required_count'] == 2
            assert seat['folded_roles'] == []
            assert seat['step']['parameters']['review_points']


def test_existing_core_credit_remains_supported_with_planned_point_metadata(tmp_path, monkeypatch):
    from test_review_point_seats import Seats
    from test_rdj_approval import canonical
    from ravel.controller.routes import plan_sha256
    seats = Seats(tmp_path, monkeypatch)
    point = next(p for p in review_points.derive(seats.facts) if p['row'] == 5)
    plan = seats.install([], [])
    plan['checkins'][0]['review_points'] = [point]
    plan['sha256'] = plan_sha256(plan)
    seats.store.append('plan', {'plan_sha256': plan['sha256'], 'blob': seats.store.put_blob(canonical(plan)),
                               'source': 'judgment', 'revision': 1})
    seats.run.put('inputs/controller-plan.json', json.dumps(plan))
    seats.review(plan, 'normalization-auditor', step_id='final_review')
    # Core observations keep their original contract: no new conditional worker/round format is required.
    missing, evidence = review_points._controller_missing(seats.root, [point], gate='final_task', action={})
    assert missing == {point['id']: []}
    assert len(evidence[point['id']]) == 1


def test_root_conditional_observation_preserves_launch_receipt_path(tmp_path, monkeypatch):
    from rdj_fixtures import Run
    from ravel.workflow import rdj_approval
    root = Run(tmp_path / 'run', snapshot=False).root
    request = {'nodes': [{'id': 'method', 'kind': 'operation', 'operation': 'literal-calculation',
                           'tool': 'symbolic', 'rung': 'smoke', 'authored': {'draft': 'draft.json'}}],
               'claims': [], 'edges': []}
    facts = {**request, 'plan': request, 'agent_layer_epoch': 2}
    monkeypatch.setattr(review_points, '_facts', lambda root: facts)
    monkeypatch.setattr(rdj_approval, 'applies', lambda root: True)
    calls = []
    def conditional(root, points, **kwargs):
        calls.extend(points)
        return {}, {}
    monkeypatch.setattr(review_points, '_controller_missing', conditional)
    report = spawn_rows.report(root, gate='launch', action={'node_id': 'method'})
    assert any(row['row'] == 'K1' for row in report)
    assert calls == []  # Launch consultations still inspect their ordinary independent receipts.


def test_root_final_gate_refuses_an_unfilled_conditional_waypoint_point(tmp_path, monkeypatch):
    seats, plan, point, action, workers, record = root_credit(tmp_path, monkeypatch)
    seats.store.append('review', {**record, 'attempt': 2})
    errors = spawn_rows.gate_errors(seats.root, 'final_task', action)
    assert len(errors) == 1
    assert errors[0].code == 'spawn_review_pending'
    assert errors[0].pins == (point['id'],)


def test_ordinary_receipt_final_gate_keeps_original_gate_scope(tmp_path, monkeypatch):
    from ravel.workflow import rdj_approval
    seats, plan, point, action, workers, record = root_credit(tmp_path, monkeypatch)
    monkeypatch.setattr(rdj_approval, 'applies', lambda root: False)
    assert spawn_rows.gate_errors(seats.root, 'final_task', action) == []


def test_k8_keeps_its_dedicated_assumption_audit(tmp_path, monkeypatch):
    from rdj_fixtures import Run
    from ravel.workflow import rdj_approval
    root = Run(tmp_path / 'run', snapshot=False).root
    request = {'nodes': [], 'claims': [{'id': 'value'}], 'edges': []}
    facts = {**request, 'plan': request, 'agent_layer_epoch': 2}
    monkeypatch.setattr(review_points, '_facts', lambda root: facts)
    monkeypatch.setattr(rdj_approval, 'applies', lambda root: True)
    def conditional(root, points, **kwargs):
        assert all(p['row'] != 'K8' for p in points)
        return {}, {}
    monkeypatch.setattr(review_points, '_controller_missing', conditional)
    monkeypatch.setattr(graph, 'delivery_assumption_evidence', lambda root: {'status': 'satisfied'})
    report = spawn_rows.report(root, gate='delivery', action={})
    [k8] = [row for row in report if row['row'] == 'K8']
    assert k8['pending'] is False and k8['roles'] == []


@pytest.mark.parametrize('tier', ['lean', 'standard', 'full'])
def test_singleton_conditional_point_keeps_its_actual_role_at_each_checkpoint(monkeypatch, tier):
    from test_p18_policy import fakes
    request = {'nodes': [{'id': 'model', 'operation': 'model-sources', 'kind': 'operation'}],
               'claims': [], 'edges': []}
    monkeypatch.setattr('ravel.workflow.request_plan.draft', lambda *a: deepcopy(request))
    plan = {'route': {'id': 'judgment'}, 'steps': [], 'deliverables': [],
            'checkins': compiler._policy_checkins([
                {'id': 'checkin2', 'seats': list(graph.CI2_SEATS)},
                {'id': 'checkin3', 'seats': list(graph.CI3_SEATS)}], {}, {'agent_layer_epoch': 2}, waypoints=['model'])}
    cards = policy.role_cards()
    rules = fakes.policy_for(plan, cards)
    result = policy.seat_plan(plan, tier, rules, cards=cards, instructions=fakes.FakeInstructions)
    for checkpoint in ('checkin2', 'checkin3'):
        key = f'checkin:{checkpoint}:model-critic'
        assert result['bindings'][key] == key
        [seat] = [s for s in result['seats'] if s['key'] == key]
        assert seat['role'] == 'model-critic'
        assert any(b['point']['row'] == 'K10' for b in seat['step']['parameters']['review_points'])


def test_applied_counted_review_roster_is_unique_without_losing_occurrences(monkeypatch):
    from ravel.controller import engagement
    from ravel.controller.engagement.records import digest
    from test_p18_policy import fakes
    plan = conditional_plan(monkeypatch)
    plan.update(route={'id': 'judgment'}, deliverables=[])
    plan['sha256'] = digest({k: v for k, v in plan.items() if k != 'sha256'})
    cards = policy.role_cards()
    installed = fakes.policy_for(plan, cards)
    monkeypatch.setattr(policy, 'load_policy', lambda: deepcopy(installed))
    roster = policy.seat_plan(plan, 'full', installed, cards=cards, instructions=fakes.FakeInstructions)
    assert not roster['errors']
    decision = {'policy_sha256': installed['sha256'], 'scientific_plan': plan,
                'scientific_plan_sha256': plan['sha256'], 'seat_plan': roster,
                'seat_plan_sha256': roster['sha256'], 'tier': 'full',
                'correction_bound': installed['correction_rounds']['full'],
                'packet_scope': installed['packet_scope']['full']}
    decision['sha256'] = digest(decision)
    applied = engagement.apply(plan, decision)
    for checkpoint in ('checkin2', 'checkin3'):
        row = next(c for c in applied['checkins'] if c['id'] == checkpoint)
        assert row['seats'].count('re-deriver') == 1
        assert row['seat_counts']['re-deriver'] == 2
        assert row['review_points'] == next(c for c in plan['checkins'] if c['id'] == checkpoint)['review_points']
        assert [s['n'] for s in row['engagement_seats'] if s['role'] == 're-deriver'] == [1, 2]


def ordinary_receipts(seats, point, roles, monkeypatch):
    """Existing dispatcher-owned receipt custody plus real controller-observed independent sessions."""
    from ravel.workflow import rdj_custody, review_dispatch, review_independence, review_projection
    from test_rdj_approval import EXPOSURE
    packets = {}
    original_projection = review_dispatch.observed_projection
    for number, role in enumerate(roles, 1):
        node = f'ordinary-{role}-{number}'
        work = seats.root / 'agent-work' / node / '1'
        work.mkdir(parents=True)
        final = work / 'final.json'
        final.write_text('{"findings": []}')
        actor = rdj_custody.actor_record('synthetic-cli', 'synthetic-model', node, f'{node}/1', family='synthetic')
        receipt = {'schema_version': 2, 'kind': 'agent-worker-receipt', 'node_id': node, 'attempt': 1,
                   'review_point_id': point['id'], 'role': {'id': role}, 'status': 'ok', 'session_id': node,
                   'actor_id': actor['actor_id'], 'transport': {'id': 'synthetic-cli'},
                   'model': {'family': 'synthetic'}, 'execution_mode': 'transport_attested_cli',
                   'review_subject': review_points.review_subject(seats.facts, point),
                   'run_tree': {'modified': False}, 'final_record': {'valid': True, 'path': 'final.json',
                   'sha256': hashlib.sha256(final.read_bytes()).hexdigest()}}
        path = work / 'receipt.json'
        path.write_text(json.dumps(receipt))
        rdj_custody.register_worker_receipt(seats.root, path.relative_to(seats.root).as_posix(),
                                          verified_label='transport_attested', actor=actor)
        query = review_independence.worker_query(seats.root, receipt, hashlib.sha256(path.read_bytes()).hexdigest(),
                         subject_sha256=review_points.review_subject(seats.facts, point)['sha256'])
        packet = review_projection.project(seats.root, role, key=node, subjects=['inputs/controller-plan.json'])
        packets[query['receipt_sha256']] = packet
        session = f'worker-session:synthetic-cli:{node}'
        review_dispatch.record_session(seats.store, {'session_id': session, 'seat': node, 'step_id': node,
            'role': role, 'card_id': role, 'role_kind': 'reviewer', 'actor_id': actor['actor_id'],
            'model': 'synthetic-model', 'transport_id': 'synthetic-cli', 'transport_kind': 'cli-worker',
            'fresh': True, 'parent_transcript_supplied': False})
        review_dispatch.record_review(seats.store, {'binding': query, 'seat': node, 'session_id': session,
            'dispatch_id': node, 'packet': {'builder': review_dispatch.PROJECTION, 'projection_verified': True,
            'author_summary': False, 'sha256': packet['manifest_sha256'], 'subject_sha256': query['subject_sha256']},
            'read_boundary': 'packet_only', 'read_boundary_verified': True,
            'exposure': EXPOSURE, 'exposure_verified': True, 'output_unmodified': True})
    monkeypatch.setattr(review_dispatch, 'observed_projection', lambda query:
        review_dispatch._manifest(packets[query['receipt_sha256']])
        if query['receipt_sha256'] in packets else original_projection(query))
    # The fixture proves actual ordinary custody and independence before report chooses a coverage path.
    for path in (seats.root / 'agent-work').glob('ordinary-*/*/receipt.json'):
        receipt = json.loads(path.read_text())
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        assert rdj_custody.worker_row(seats.root, path.relative_to(seats.root).as_posix(), sha) is not None
        assert review_independence.decide(review_independence.worker_query(seats.root, receipt, sha,
               subject_sha256=review_points.review_subject(seats.facts, point)['sha256']))['independent'] is True


def test_complete_ordinary_numeric_receipts_survive_controller_root_observation(tmp_path, monkeypatch):
    seats, plan, _, action, workers, record = root_credit(tmp_path, monkeypatch)
    seats.facts = {**seats.facts, **REQUEST, 'plan': REQUEST}
    point = next(p for p in spawn_rows.derive(seats.facts) if p['row'] == 'K5')
    ordinary_receipts(seats, point, ['re-deriver', 're-deriver', 'normalization-auditor'], monkeypatch)
    [observed] = [p for p in spawn_rows.report(seats.root, gate='final_task', action=action) if p['id'] == point['id']]
    assert observed['roles'] == [] and observed['pending'] is False


def test_incomplete_ordinary_receipts_do_not_reduce_required_root_occurrences(tmp_path, monkeypatch):
    seats, plan, _, action, workers, record = root_credit(tmp_path, monkeypatch)
    seats.facts = {**seats.facts, **REQUEST, 'plan': REQUEST}
    point = next(p for p in spawn_rows.derive(seats.facts) if p['row'] == 'K5')
    ordinary_receipts(seats, point, ['re-deriver', 'normalization-auditor'], monkeypatch)
    [observed] = [p for p in spawn_rows.report(seats.root, gate='final_task', action=action) if p['id'] == point['id']]
    assert observed['pending'] is True
    assert {r['role']: r['count'] for r in observed['roles']} == {'re-deriver': 2, 'normalization-auditor': 1}
    assert all(r['code'] == 'comparison_evidence_required' for r in observed['roles'])


@pytest.mark.parametrize('full_root', [False, True])
def test_incomplete_ordinary_and_root_paths_do_not_blindly_union_sessions(tmp_path, monkeypatch, full_root):
    from ravel.workflow import rdj_approval
    seats, plan, point, action, workers, record = root_credit(tmp_path, monkeypatch, count=2)
    monkeypatch.setattr(spawn_rows, 'derive', lambda facts: [point])
    ordinary_receipts(seats, point, ['model-critic'], monkeypatch)
    if not full_root:
        scan = seats.store.scan
        monkeypatch.setattr(seats.store, 'scan', lambda kind: scan(kind) if kind != 'worker-session' else
                            [r for r in scan(kind) if r['record']['step'] != 'final_review.2'])
        monkeypatch.setattr(rdj_approval, 'controller_plan', lambda root: (seats.store, plan))
    [observed] = spawn_rows.report(seats.root, gate='final_task', action=action)
    assert observed['pending'] is (not full_root)
    assert [r['count'] for r in observed['roles']] == ([] if full_root else [1])


@pytest.mark.parametrize('row,valid', [(9, True), ('K10', True), (True, False), ({}, False), (1.5, False)])
def test_review_point_row_schema_accepts_only_integer_core_or_string_conditional_rows(row, valid):
    from ravel.controller import schema
    from ravel.validation.validate_task_contract import _schema_errors
    point_schema = schema('plan.v1')['properties']['checkins']['items']['properties']['review_points']['items']
    errors = _schema_errors(row, point_schema['properties']['row'], '$.row')
    assert bool(errors) is (not valid)


def test_actual_route_compilation_validates_core_and_conditional_point_metadata(monkeypatch):
    import fakes
    from ravel.controller import schema_errors
    monkeypatch.setattr('ravel.workflow.request_plan.draft', lambda *a: deepcopy(REQUEST))
    route = fakes._spec('analysis', 6, {'field': 'task_mode', 'eq': 'calculate'},
                        [fakes.make_step('s1', waypoint=True, outputs=['outputs/result.json'])], [])
    plan = compiler.compile(route, {}, {'agent_layer_epoch': 2})
    assert schema_errors(plan, 'plan.v1') == []
    points = [point for checkpoint in plan['checkins'] for point in checkpoint.get('review_points', [])]
    assert any(type(point['row']) is int for point in points)
    assert any(type(point['row']) is str for point in points)


@pytest.mark.parametrize('declared,canonical,first', [
    (['synthesizer', 'physics-decider', 'synthesizer'], 'physics-decider', 'synthesizer'),
    (['physics-decider', 'synthesizer', 'physics-decider'], 'physics-decider', 'physics-decider'),
    (['model-author', 'model-builder', 'model-author'], 'model-builder', 'model-author'),
    (['model-builder', 'model-author', 'model-builder'], 'model-builder', 'model-builder'),
])
@pytest.mark.parametrize('count', [1, 2])
def test_review_descriptor_key_preserves_first_alias_spelling_but_canonical_identity(declared, canonical, first, count):
    point = {'id': 'K-alias:run', 'row': 'K-alias', 'mode': 'specialist', 'blocking': True,
             'gate': 'delivery', 'roles': [{'role': canonical, 'count': count}]}
    plan = {'steps': [], 'checkins': [{'id': 'checkin3', 'seats': declared,
              'review_points': [point], **({'seat_counts': {canonical: count}} if count > 1 else {})}]}
    descriptors = policy.declared_seats(plan, policy.role_cards())
    assert [s['key'] for s in descriptors] == [
        f'checkin:checkin3:{first}' + (f'.{n}' if n > 1 else '') for n in range(1, count + 1)]
    assert [s['role'] for s in descriptors] == [canonical] * count
    assert [s['step']['role'] for s in descriptors] == [canonical] * count
    assert [s.get('n', 1) for s in descriptors] == list(range(1, count + 1))
    for n, seat in enumerate(descriptors, 1):
        assert seat['step']['parameters']['review_points'] == [
            {'point': point, 'n': n, 'sha256': review_points.jdigest(point)}]
