"""Action-owned records discharge rows; missing and forged records cannot."""
from copy import deepcopy
from importlib import import_module
import json
import re

import pytest

from ravel.controller import authority, graph, ledger, testing
from ravel.controller.authority import checkin, common, event_rows, retained
from ravel.controller.ledger import chain, recorders, state
from ravel.controller.store import RunStore, JOURNAL
from test_p06_support import autonomous, operator_home, view  # noqa: F401

select = import_module('ravel.controller.routes.select')


@pytest.fixture
def store(tmp_path, operator_home):
    autonomous()
    run = RunStore.create(tmp_path / 'run', root=tmp_path / 'store')
    authority.freeze_mode(run, {'prompt': 'Compute a fictional toy observable.'})
    ledger.materialise(run, 'intake', {'run_id': run.run_id, 'task_mode': 'research', 'deliverables': []})
    yield run
    state.forget(run)


def test_checkin_record_is_retained_before_authority_is_presented(store, capfd):
    source = view(store, 'escalation', question_sha256='a' * 64)
    pending = authority.request(store, 'escalation', {'view': source}, {})
    assert pending['pending']['request']
    proof = common.scan(store, event_rows.VALIDATION, event_rows.VALIDATION_SCHEMA)[0]
    assert proof['artifact'] == checkin.render('escalation', source)
    assert proof['before_presentation'] is True and proof['errors'] == []
    entries = {row['id']: row for row in store.scan('authority-request') + store.scan(event_rows.VALIDATION)}
    assert entries[proof['id']]['seq'] < entries[pending['pending']['request']]['seq']
    code = re.findall(r'--code (\S+)', capfd.readouterr().err)[-1]
    assert 'SW04' not in event_rows.evidence(store)
    answered = authority.answer(store, pending['pending']['request'], code, 'hold')
    result = event_rows.evidence(store)
    assert result['C23']['evidence']['validation_records'] == [proof['id']]
    assert result['SW04']['evidence']['record'] == answered['id']
    assert answered['label'] == 'operator_command' and answered['authorizes_effects'] is False
    recorders.record(store, result, ledger)
    assert {r['id']: r['status'] for r in ledger.current(store)}['SW04'] == 'satisfied'


@pytest.mark.parametrize('fault', ['missing', 'unissued', 'invalid_artifact', 'wrong_context', 'tampered'])
def test_checkin_proof_missing_or_changed_stays_pending(store, fault):
    source = view(store, 'escalation', question_sha256='b' * 64)
    context = retained.current(store, 'escalation')
    artifact = checkin.render('escalation', source)
    if fault != 'missing':
        if fault == 'unissued':
            store.append(event_rows.VALIDATION, {'schema': event_rows.VALIDATION_SCHEMA,
                         'uid': 'forged', 'run_id': store.run_id, 'artifact': artifact})
        elif fault in ('invalid_artifact', 'wrong_context'):
            body = {'schema': event_rows.VALIDATION_SCHEMA, 'uid': common.uid(), 'run_id': store.run_id,
                    'kind': 'escalation', 'artifact': artifact, 'context_record': context['id'],
                    'errors': [], 'before_presentation': True}
            if fault == 'invalid_artifact':
                body['artifact'] = {**artifact, 'sha256': '0' * 64}
            else:
                body['context_record'] = 'not-a-context'
            common.append(store, event_rows.VALIDATION, body)
        else:
            event_rows.validated(store, 'escalation', artifact, context['id'])
            store.head()
            path = store.root / JOURNAL
            path.write_bytes(path.read_bytes().replace(b'before_presentation', b'before_presentatioN'))
    result = event_rows.evidence(store)
    assert 'C23' not in result and 'SW04' not in result
    if fault != 'tampered':
        recorders.record(store, result, ledger)
        assert {r['id']: r['status'] for r in ledger.current(store)}['C23'] == 'pending'


def test_caller_written_operator_answer_never_discharges_the_row(store):
    store.append('authority', {'schema': common.SCHEMA, 'uid': 'caller', 'run_id': store.run_id,
                              'source': 'operator_cli', 'label': 'operator_command', 'request': 'invented'})
    assert event_rows.evidence(store) == {}
    assert {r['id']: r['status'] for r in ledger.current(store)}['SW04'] == 'pending'


def test_validation_after_the_presented_request_cannot_backdate_checkin_credit(store):
    source = view(store, 'escalation', question_sha256='e' * 64)
    context = retained.current(store, 'escalation')
    artifact = checkin.render('escalation', source)
    common.append(store, common.REQUESTS, {
        'schema': common.REQUEST_SCHEMA, 'uid': common.uid(), 'run_id': store.run_id, 'kind': 'escalation',
        'subject': {'context_record': context['id'], 'checkin_sha256': artifact['sha256']}})
    event_rows.validated(store, 'escalation', artifact, context['id'])
    assert 'C23' not in event_rows.evidence(store)


def selected(store, *, task_mode='calculation'):
    contract, reading = {'task_mode': task_mode}, {}
    intake = store.append('intake', {'contract_blob': store.put_blob(json.dumps(contract).encode()),
                                     'reading_blob': store.put_blob(json.dumps(reading).encode())})
    decision = select.select(contract, reading, [])
    route = store.append('route', {**{k: decision[k] for k in ('route', 'row', 'spec_sha256', 'version')},
                                   'evidence_blob': store.put_blob(json.dumps(decision).encode())})
    return intake, route


def test_route_nonapplicability_names_the_recomputed_first_match(store):
    intake, route = selected(store)
    rows = select.selection_rows(store)
    proof = rows['ROUTE-research']['evidence']
    assert rows['ROUTE-research']['status'] == 'not_applicable'
    assert proof['record'] == route and proof['intake_record'] == intake
    assert proof['selected_route'] == 'calculation' and proof['reason'].startswith('not_applicable:')
    recorders.record(store, rows, ledger)
    assert {r['id']: r['status'] for r in ledger.current(store)}['ROUTE-research'] == 'not_applicable'


def test_selecting_a_research_route_does_not_certify_its_unexecuted_stages(store):
    spec = deepcopy(select.find('analysis'))
    spec['id'] = 'research'
    spec['match']['when'] = {'field': 'task_mode', 'eq': 'research'}
    with select.registered(spec, only=True):
        selected(store, task_mode='research')
        assert store.latest('route')['record']['route'] == 'research'
        assert select.selection_rows(store) == {}
    assert {r['id']: r['status'] for r in ledger.current(store)}['ROUTE-research'] == 'pending'


@pytest.mark.parametrize('fault', ['missing', 'wrong_selection', 'missing_blob', 'tampered'])
def test_route_without_an_authentic_selection_record_stays_pending(store, fault):
    if fault != 'missing':
        _, identifier = selected(store)
        body = deepcopy(store.read('route', identifier)['record'])
        if fault == 'wrong_selection':
            body['route'] = 'research'
            store.append('route', body)
        elif fault == 'missing_blob':
            body['evidence_blob'] = '0' * 64
            store.append('route', body)
        else:
            store.head()
            path = store.root / JOURNAL
            path.write_bytes(path.read_bytes().replace(b'calculation', b'calculatioN'))
    assert select.selection_rows(store) == {}


def gate_proof(store, *, fault=None):
    # Synthetic decision records test the join; the composition gate exercises
    # the real provider execution that emits this proof in ordinary runs.
    plan = {'sha256': 'f' * 64, 'steps': [], 'deliverables': [], 'waypoints': [], 'obligations': []}
    ledger.materialise(store, 'plan', {'plan': plan, 'route': 'judgment'})
    registry = ledger.load_catalogue().gate_registry['sha256']
    action, providers = {'kind': 'fictional-choice'}, {'review': {'record': 'fictional-review'}}
    identifier = recorders.decision(store, 'approve_plan', action, providers,
                                   '0' * 64 if fault == 'registry' else registry)
    if fault != 'missing_decision':
        ledger.record(store, ledger.instance_key('GATE-approve_plan', store.run_id, {}), 'satisfied', {
            'gate': 'approve_plan', 'record': 'wrong-record' if fault == 'wrong_record' else identifier,
            'action_sha256': chain.digest(action), 'registry_sha256': registry,
            'providers': {} if fault == 'changed_providers' else providers, 'mechanism': 'decision_gate.check'})
    return identifier


def test_provider_record_must_join_the_exact_passed_decision(store):
    identifier = gate_proof(store)
    rows = recorders.evidence(store)
    assert rows['G02']['evidence']['record'] == identifier
    recorders.record(store, rows, ledger)
    assert {r['id']: r['status'] for r in ledger.current(store)}['G02'] == 'satisfied'


@pytest.mark.parametrize('fault', ['missing', 'missing_decision', 'registry', 'wrong_record', 'changed_providers'])
def test_missing_or_unmatched_provider_check_leaves_gate_row_pending(store, fault):
    if fault != 'missing':
        gate_proof(store, fault=fault)
    assert recorders.evidence(store) == {}
    assert {r['id']: r['status'] for r in ledger.current(store)}['G02'] == 'pending'


def test_tampered_provider_record_is_detected_before_cached_reads(store):
    gate_proof(store)
    store.head()
    path = store.root / JOURNAL
    path.write_bytes(path.read_bytes().replace(b'fictional-choice', b'fabricate-choice'))
    assert recorders.evidence(store) == {}


def test_resumed_delivery_cannot_keep_an_unverifiable_earlier_discharge(store):
    gate_proof(store)
    recorders.record(store, recorders.evidence(store), ledger)
    assert {r['id']: r['status'] for r in ledger.current(store)}['G02'] == 'satisfied'
    # A complete later check has lost the enforcing proof. Append-only statuses
    # cannot return to pending, so the old discharge must become a hard violation.
    recorders.record(store, {}, ledger, revalidate=True)
    [found] = [r for r in ledger.current(store) if r['id'] == 'G02']
    assert found['status'] == 'violated'
    assert found['evidence']['reason'] == 'the enforcing record no longer verifies'


def test_absence_recorder_does_not_close_executed_mechanisms(store, capfd):
    authority.register_recorders(store)
    selected(store)
    source = view(store, 'escalation', question_sha256='d' * 64)
    held = authority.request(store, 'escalation', {'view': source}, {})
    code = re.findall(r'--code (\S+)', capfd.readouterr().err)[-1]
    authority.answer(store, held['pending']['request'], code, 'hold')
    boundary = authority.delivery_decision(store, {'kind': 'fictional-delivery'})
    with graph.services(ledger=ledger):
        authority.record_standing_rows(store, boundary['id'])
    assert {r['id']: r['status'] for r in ledger.current(store)}['SW04'] == 'pending'
    assert event_rows.evidence(store)['SW04']['status'] == 'satisfied'


def crosscheck(store, monkeypatch, *, fault=None):
    """Synthetic protected-custody input; the actual independence oracle stays installed."""
    from ravel.controller.confine import host_rows
    from ravel.workflow import review_dispatch, review_independence
    from test_host_surface_rows import populate
    from test_p13_peer_observations import observed_pair, protected_worker_proof, query
    populate(store)
    with testing.seams(False, controller=True):
        qualification = host_rows.evidence(store)['SW30']['evidence']
    _, reviewer = observed_pair(store)
    q = query(store.run_dir)
    monkeypatch.setattr(review_independence, 'controller_store', lambda _: store)
    monkeypatch.setattr(review_dispatch, '_worker', lambda binding: protected_worker_proof(binding, reviewer))
    review_dispatch.capture_worker_review(store, q)
    assert review_independence.decide(q)['independent'] is True
    seat = 'seat:' + q['role'] + ':1'
    ledger.materialise(store, 'review', {'step': 's1', 'seat': seat, 'attempt': 1,
                                       'role': q['role'], 'review_kind': 'crosscheck', 'seat_kind': 'review'})
    if fault != 'missing_credit':
        body = {'step_id': 's1', 'attempt': 1, 'seats': [], 'credited': True,
                'own': {'credited': True, 'query': q}}
        if fault == 'wrong_step': body['step_id'] = 'another-step'
        if fault == 'wrong_attempt': body['attempt'] = 2
        if fault == 'uncredited': body['own']['credited'] = False
        if fault == 'wrong_role': body['own']['query'] = {**q, 'role': 'physics-critic'}
        store.append('step-credit', body)
    if fault == 'missing_qualification':
        qualification = None
    if fault == 'unissued_host_check':
        store.append(host_rows.KIND, {'schema': host_rows.SCHEMA, 'uid': 'forged', 'run_id': store.run_id})
    if fault == 'tampered_credit':
        store.head()
        path = store.root / JOURNAL
        path.write_bytes(path.read_bytes().replace(b'"credited":true', b'"credited":fals'))
    return qualification


def test_crosscheck_labels_credit_without_claiming_an_executable_result(store, monkeypatch):
    qualification = crosscheck(store, monkeypatch)
    rows = event_rows.crosscheck_rows(store, qualification)
    assert len(rows) == 1
    [found] = rows.values()
    assert found['status'] == 'violated'
    assert found['evidence']['label'] == 'INDEPENDENT REVIEW; EXECUTABLE CROSSCHECK NOT ESTABLISHED'
    assert found['evidence']['qualification_records'] == qualification['qualifications']
    recorders.record(store, rows, ledger)
    [instance] = [r for r in ledger.current(store) if r['id'] == 'V09']
    assert instance['status'] == 'violated' and instance['evidence']['credit']


@pytest.mark.parametrize('fault', ['missing_credit', 'uncredited', 'wrong_step', 'wrong_attempt',
                                  'wrong_role', 'missing_qualification', 'unissued_host_check', 'tampered_credit'])
def test_crosscheck_without_its_exact_qualified_credit_stays_pending(store, monkeypatch, fault):
    qualification = crosscheck(store, monkeypatch, fault=fault)
    assert event_rows.crosscheck_rows(store, qualification) == {}
    if fault != 'tampered_credit':
        assert all(r['status'] == 'pending' for r in ledger.current(store) if r['id'] == 'V09')
