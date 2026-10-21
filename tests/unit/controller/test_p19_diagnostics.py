"""Synthetic diagnostics controls using only binding peer signatures and local records."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import socket
import sqlite3

import pytest

from ravel.controller import diagnostics as d
from ravel.controller.diagnostics import cli
from ravel.controller.diagnostics.canary import FAULTS
from ravel.controller.diagnostics.records import digest, seal


class Store:
    """Binding RunStore fake: envelopes, global sequence, append/read/scan/path."""
    def __init__(self, run_id='example-run', *, root):
        self.run_id = run_id
        self.root = Path(root) / run_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.events = []

    def append(self, kind, record):
        # Exercise JSON safety instead of retaining a Python object alias.
        value = json.loads(json.dumps(record, allow_nan=False))
        seq = len(self.events) + 1
        identifier = f'{kind}-{seq:06d}'
        self.events.append({'id': identifier, 'kind': kind, 'seq': seq, 'time_ns': seq,
                            'record': value})
        return identifier

    def read(self, kind, record_id):
        return deepcopy(next(e for e in self.events if e['kind'] == kind and e['id'] == record_id))

    def scan(self, kind):
        return deepcopy([e for e in self.events if e['kind'] == kind])

    def path(self, *parts):
        if any(p in ('..', '.') or '/' in p or '\\' in p for p in parts):
            raise ValueError('invalid store path')
        target = self.root.joinpath(*parts)
        if not target.resolve().is_relative_to(self.root.resolve()):
            raise ValueError('store path escapes')
        return target


class Instructions:
    @staticmethod
    def manifest(step, card):
        units = [{'id': 'duty:' + card['id'], 'sha256': digest(card), 'kind': 'duty'},
                 {'id': 'context', 'sha256': digest('context'), 'kind': 'context'}]
        return seal({'units': units, 'role': card['id'], 'step': step['id']})

    @staticmethod
    def packet(manifest, card, step, inputs):
        return {'text': 'local packet', 'sha256': digest(manifest), 'schema': {}}

    @staticmethod
    def check_ack(manifest, final_record, outputs):
        problems = []
        if (final_record.get('instruction_ack') or {}).get('manifest_sha256') != manifest['sha256']:
            problems.append('manifest pin missing or different')
        acknowledged = {row['unit']: row for row in final_record.get('checklist', [])}
        for unit in manifest['units']:
            if unit['kind'] == 'duty' and acknowledged.get(unit['id'], {}).get('sha256') != unit['sha256']:
                problems.append('duty missing: ' + unit['id'])
        return problems


def inputs():
    route = {'id': 'inspect', 'steps': ['make', 'wait']}
    plan = {'route': {'id': 'inspect'}, 'steps': [
        {'id': 'make', 'kind': 'author', 'role': 'producer-role', 'outputs': [{'path': 'outputs/result.txt'}]},
        {'id': 'wait', 'kind': 'ask'}], 'deliverables': [{'id': 'result', 'step': 'make'}],
        'checkins': [{'id': 'checkin1', 'seats': ['review-role']}], 'waypoints': []}
    plan['sha256'] = digest(plan)
    review = {'key': 'checkin:checkin1:review-role', 'step_id': 'checkin1', 'role': 'review-role',
              'category': 'checkin1', 'step': {'id': 'checkin1', 'kind': 'review', 'role': 'review-role'}}
    engagement = {'scientific_plan_sha256': plan['sha256'], 'tier': 'standard',
                  'seat_plan': {'seats': [review], 'bindings': {}, 'errors': []},
                  'projected_envelope': {'status': 'ready', 'floor': {'sessions': 2},
                                         'low': {'calls': 2}, 'high': {'calls': 20}}}
    cards = {role: {'id': role} for role in ('producer-role', 'review-role', 'rdj-edge-reviewer',
                                           'rdj-critic', 'rdj-verifier')}
    obligation_rows = [{'key': 'ROW@run', 'row': 'ROW', 'discharge_node': 'delivery', 'stage': 'deliver'}]
    return route, plan, engagement, cards, obligation_rows


def expected(**changes):
    route, plan, engagement, cards, rows = inputs()
    return d.build_expected(changes.get('route', route), changes.get('plan', plan),
                            changes.get('engagement', engagement),
                            obligation_rows=changes.get('rows', rows), instructions=Instructions,
                            cards=cards, classify=changes.get('classify', lambda step: 'R0'))


@pytest.fixture
def store(tmp_path):
    return Store(root=tmp_path)


def complete_seat(store, seat, *, attempt=1, role=None, ack=True):
    identity = {'step_id': seat['node_id'], 'seat': seat['seat'], 'role': role or seat['role'],
                'attempt': attempt, 'node_id': f"worker-{seat['id']}-{attempt}"}
    packet_sha = digest('packet:' + seat['id'])
    store.append('step-dispatch', {**identity, 'packet_sha256': packet_sha})
    store.append('instruction-delivery', {**identity, 'kind': 'instruction-delivery',
                                          'manifest_sha256': seat['manifest']['sha256'],
                                          'packet_sha256': packet_sha,
                                          'units': [u['id'] for u in seat['instruction_units']]})
    store.append('step-observation', {**identity, 'session_id': identity['node_id'], 'status': 'completed',
                                     'usage': {'reported': True, 'turns': 2}, 'calls': {'broker_calls': 0}})
    if ack:
        final = {'instruction_ack': {'manifest_sha256': seat['manifest']['sha256']},
                 'checklist': [{'unit': u['id'], 'sha256': u['sha256'], 'status': 'done', 'evidence': 'final_record#/result'}
                               for u in seat['instruction_units'] if u['kind'] == 'duty']}
        final['result'] = 'inert completion'
        store.append('worker-completion', {**identity, 'session': identity['node_id'],
                                          'final_record': final, 'artifacts': []})
    return identity


def test_P19_01_expected_deterministic_and_pinned_before_first_effect(store):
    a, b = expected(), expected()
    assert a == b and a['sha256'] == digest({k: v for k, v in a.items() if k != 'sha256'})
    assert a['route'] == 'inspect' and len(a['nodes']) == 3 and len(a['seats']) == 2
    assert a['obligations'][0]['discharge_node'] == 'delivery'
    assert a['seats'][0]['acknowledge'] == ['duty:producer-role']
    identifier = d.pin_expected(store, a)
    d.require_expected(store, a['plan_sha256'])
    complete_seat(store, a['seats'][0])
    assert store.read('diagnostics-expected', identifier)['seq'] < store.scan('step-dispatch')[0]['seq']
    assert d.pin_expected(store, b) == identifier
    assert len(store.scan('diagnostics-expected')) == 1


@pytest.mark.parametrize('kind', ['step-dispatch', 'step-observation', 'step-outcome', 'step-launch', 'broker-call'])
def test_P19_01_refuses_late_pin(store, kind):
    store.append(kind, {'status': 'started'})
    with pytest.raises(d.DiagnosticsRefused, match='before the first effect'):
        d.pin_expected(store, expected())


def test_expected_pin_tampering_and_replacement_refused(store):
    value = expected()
    value['route'] = 'different'
    with pytest.raises(d.DiagnosticsRefused, match='digest'):
        d.pin_expected(store, value)
    d.pin_expected(store, expected())
    other = expected()
    other['route'] = 'different'
    with pytest.raises(d.DiagnosticsRefused, match='already pinned'):
        d.pin_expected(store, seal({k: v for k, v in other.items() if k != 'sha256'}))
    with pytest.raises(d.DiagnosticsRefused, match='plan differs'):
        d.require_expected(store, 'different')


@pytest.mark.parametrize('mutation', ['route', 'tier', 'plan-pin', 'duplicate-step', 'row-node', 'missing-envelope'])
def test_expected_incomplete_inputs_refused(mutation):
    route, plan, engagement, cards, rows = inputs()
    if mutation == 'route': route['id'] = 'other'
    elif mutation == 'tier': engagement['tier'] = 'unknown'
    elif mutation == 'plan-pin': engagement['scientific_plan_sha256'] = 'other'
    elif mutation == 'duplicate-step': plan['steps'].append(deepcopy(plan['steps'][0]))
    elif mutation == 'row-node': rows[0].pop('discharge_node')
    elif mutation == 'missing-envelope': engagement.pop('projected_envelope')
    with pytest.raises(d.DiagnosticsRefused):
        d.build_expected(route, plan, engagement, obligation_rows=rows, cards=cards,
                         instructions=Instructions, classify=lambda s: 'R0')


@pytest.mark.parametrize('consequence', ['R2', 'R3', 'unknown'])
def test_consequence_class_expected_review_cases(consequence):
    _, plan, engagement, _, _ = inputs()
    plan['steps'][0]['kind'] = 'decide'
    value = expected(plan=plan, engagement=engagement, classify=lambda s: consequence)
    case = value['rdj_cases'][0]
    assert case['consequence_class'] == ('R2' if consequence == 'R2' else 'R3')
    assert case['authority_required'] is (consequence != 'R2')
    assert case['before_effect'] and case['requirements']['roles'] == ['edge_reviewer', 'critic', 'verifier']
    assert len([s for s in value['seats'] if s['category'] == 'rdj']) == 3


def test_P19_02_exact_skipped_extra_held_diff_rows(store):
    value = expected()
    d.pin_expected(store, value)
    complete_seat(store, value['seats'][0])
    store.append('step-outcome', {'step_id': 'make', 'status': 'completed'})
    store.append('step-outcome', {'step_id': 'wait', 'status': 'held',
                                  'reason': {'code': 'authority_pending', 'message': 'Waiting for an answer.'}})
    store.append('authority', {'step_id': 'checkin1', 'decision': 'approve', 'authorizes_effects': True})
    extra = store.append('broker-evidence', {'node_id': 'unknown-worker', 'attempt': 1,
                                           'action': 'local inspect', 'status': 'ok'})
    store.append('ending', {'reason': 'qualified'})
    result = d.report(store, instructions=Instructions)
    bad = [(r['id'], r['status']) for r in result['rows'] if r['status'] != 'ran-as-designed']
    assert bad == [('wait', 'held'), ('checkin:checkin1:review-role', 'skipped'), ('extra:' + extra, 'extra')]
    assert next(r for r in result['rows'] if r['id'] == 'wait')['reason']['code'] == 'authority_pending'
    assert result['counts']['expected_seats'] == 2
    assert result['counts']['dispatched_seats'] == 1
    assert result['counts']['broker_tool_calls'] == 1
    assert result['counts']['tool_counts_equal'] is False
    assert result['counts']['model_counts_equal'] is None
    assert Path(result['artifacts']['json']).is_file()
    saved = json.loads(Path(result['artifacts']['json']).read_text())
    assert saved['rows'] == result['rows']
    text = Path(result['artifacts']['markdown']).read_text()
    assert text.startswith(result['summary']) and 'authority_pending' in text
    assert result['artifacts']['json'].removesuffix('.json') == result['artifacts']['markdown'].removesuffix('.md')


@pytest.mark.parametrize('difference', ['wrong-role', 'missing-ack', 'retry', 'missing-session', 'wrong-packet'])
def test_seat_differences_are_not_success(store, difference):
    value = expected()
    d.pin_expected(store, value)
    complete_seat(store, value['seats'][0], role='other-role' if difference == 'wrong-role' else None,
                  ack=difference != 'missing-ack')
    if difference == 'retry': complete_seat(store, value['seats'][0], attempt=2)
    elif difference == 'missing-session': store.events = [e for e in store.events if e['kind'] != 'step-observation']
    elif difference == 'wrong-packet':
        next(e for e in store.events if e['kind'] == 'instruction-delivery')['record']['packet_sha256'] = 'other'
    result = d.report(store, instructions=Instructions, write=False)
    row = next(r for r in result['rows'] if r['id'] == value['seats'][0]['id'])
    assert row['status'] == 'ran-differently' and row['differences']


def test_obligation_pending_violated_waived_evidence(store):
    rows = [{'key': f'ROW-{i}@run', 'row': f'ROW-{i}', 'discharge_node': 'node'} for i in range(4)]
    d.pin_expected(store, expected(rows=rows))
    store.append('ledger', {'body': {'event': 'materialise', 'instances':
                                    [{'key': r['key'], 'id': r['row']} for r in rows[:3]]}})
    evidence = {'authority': 'authority-receipt', 'why': 'bounded waiver'}
    store.append('ledger', {'body': {'event': 'status', 'changes': [
        {'key': rows[0]['key'], 'to': 'satisfied', 'evidence': {'artifact': 'bytes'}},
        {'key': rows[1]['key'], 'to': 'violated', 'evidence': {'code': 'missing_output'}},
        {'key': rows[2]['key'], 'to': 'waived', 'evidence': evidence}]}})
    result = d.report(store, instructions=Instructions, write=False)
    assert [r['status'] for r in result['obligations']] == ['satisfied', 'violated', 'waived', 'pending']
    assert result['obligations'][2]['evidence'] == evidence
    assert result['obligations'][3]['materialised'] is False


def test_P19_03_transcripts_off_by_default_and_canary_only(store):
    assert d.capture_transcript(store, {}, 'private worker text') is None
    assert d.receipt_section(store)['transcript_capture'] is False
    assert not store.path('diagnostics', 'transcripts').exists()
    with pytest.raises(d.DiagnosticsRefused, match='canary'):
        d.configure(store, capture_transcripts=True)
    with pytest.raises(d.DiagnosticsRefused, match='canary'):
        d.configure(store, faults=['missing-input'])
    with pytest.raises(d.DiagnosticsRefused, match='opt-in'):
        d.inject_fault(store, 'missing-input', {}, exercise=lambda s: None)


def test_canary_transcript_private_receipted_and_idempotent(store):
    d.configure(store, canary=True, capture_transcripts=True)
    d.pin_expected(store, expected())
    identity = {'step_id': 'make', 'seat': 'producer', 'role': 'producer-role', 'attempt': 1}
    record_id = d.capture_transcript(store, identity, 'private worker text\n')
    assert d.capture_transcript(store, identity, 'private worker text\n') == record_id
    record = store.read('diagnostics-transcript', record_id)['record']
    path = store.path(*record['path_parts'])
    assert path.read_text() == 'private worker text\n'
    assert path.stat().st_mode & 0o777 == 0o600
    assert record['sha256'] == sha256(path.read_bytes()).hexdigest()
    receipt = d.receipt_section(store)
    assert receipt['canary'] and receipt['transcript_capture'] and receipt['transcript_record_ids'] == [record_id]
    assert 'private worker text' not in d.markdown(d.report(store, instructions=Instructions, write=False))


def test_configuration_cannot_be_enabled_late_or_changed(store):
    d.configure(store)
    with pytest.raises(d.DiagnosticsRefused, match='frozen'):
        d.configure(store, canary=True, capture_transcripts=True)
    other = Store('other-run', root=store.root.parent)
    other.append('step-dispatch', {})
    with pytest.raises(d.DiagnosticsRefused, match='before the first effect'):
        d.configure(other, canary=True)


@pytest.mark.parametrize('fault', list(FAULTS))
def test_P19_04_each_fault_detected_with_expected_response(store, fault):
    d.configure(store, canary=True, faults=[fault])
    d.pin_expected(store, expected())
    identity = {'step_id': 'make', 'seat': 'producer', 'role': 'producer-role', 'attempt': 1}
    # An inert boundary fake records the same typed outcome as the guarded peer.
    def boundary(spec):
        request = spec['request']
        # Independent fake policy inspects the attempted action; it does not echo
        # the diagnostic's expected response or list of acceptable reason codes.
        operation = request['operation']
        if operation == 'worker_write':
            assert request['target'] not in request['declared_outputs']
            status, code = 'held', 'output_scope'
        elif operation == 'consume_input':
            assert not store.path(request['artifact']).exists()
            status, code = 'held', 'missing_input'
        elif operation == 'acquire_source':
            assert request['source_class'] == 'forbidden'
            status, code = 'held', 'forbidden_source'
        else:
            assert operation == 'tool_call' and request['deadline_seconds'] == 0
            status, code = 'escalated', 'tool_timeout'
        record_id = store.append('step-outcome', {**identity, 'status': status, 'reason': {'code': code}})
        return {'kind': 'step-outcome', 'record_id': record_id}
    result_id = d.inject_fault(store, fault, identity, exercise=boundary)
    result = d.report(store, instructions=Instructions, write=False)
    assert len(result['faults']) == 1
    row = result['faults'][0]
    assert row['detected'] is True and row['observed_response'] == FAULTS[fault]['responses'][0]['status']
    assert d.receipt_section(store)['fault_result_ids'] == [result_id]
    assert store.scan('diagnostics-fault')[0]['seq'] < store.scan('step-outcome')[0]['seq']


@pytest.mark.parametrize('bad_response', ['assertion', 'old-response', 'wrong-step', 'wrong-code', 'wrong-status', 'exception'])
def test_fault_never_credits_unrecorded_or_unrelated_responses(store, bad_response):
    d.configure(store, canary=True, faults=['missing-input'])
    d.pin_expected(store, expected())
    identity = {'step_id': 'make', 'seat': 'producer', 'role': 'producer-role', 'attempt': 1}
    old = store.append('step-outcome', {**identity, 'status': 'held', 'reason': {'code': 'missing_input'}})
    def boundary(spec):
        if bad_response == 'exception': raise RuntimeError('inert failure')
        if bad_response == 'assertion': return {'detected': True, 'status': 'held'}
        if bad_response == 'old-response': return {'kind': 'step-outcome', 'record_id': old}
        row = {**identity, 'status': 'held', 'reason': {'code': 'missing_input'}}
        if bad_response == 'wrong-step': row['step_id'] = 'other'
        elif bad_response == 'wrong-code': row['reason']['code'] = 'unrelated'
        elif bad_response == 'wrong-status': row['status'] = 'completed'
        return {'kind': 'step-outcome', 'record_id': store.append('step-outcome', row)}
    d.inject_fault(store, 'missing-input', identity, exercise=boundary)
    assert d.report(store, instructions=Instructions, write=False)['faults'][0]['detected'] is False


def test_P19_05_only_own_records_and_checkpoint_history(store, tmp_path):
    d.pin_expected(store, expected())
    framework = store.path('graph', 'framework')
    framework.mkdir(parents=True)
    (framework / 'events.jsonl').write_text(json.dumps({'node': 'make', 'type': 'updates'}) + '\n')
    with sqlite3.connect(framework / 'graphs.sqlite') as connection:
        connection.execute('CREATE TABLE checkpoints (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, checkpoint, metadata)')
        connection.execute('INSERT INTO checkpoints VALUES (?, ?, ?, ?, ?, ?)', ('thread', '', 'cp-1', None, b'opaque bytes', b'{}'))
    unrelated = tmp_path / 'run-tree'
    unrelated.mkdir()
    (unrelated / 'forged-observation.json').write_text(json.dumps({'step_id': 'make', 'status': 'completed'}))
    observed = d.observe(store)
    assert len(observed['checkpoints']) == 1 and observed['checkpoints'][0]['checkpoint_id'] == 'cp-1'
    assert observed['graph_events'][0]['node'] == 'make'
    assert len(observed['timeline']) == 1
    assert not observed['gaps']


def test_projection_uses_disposable_binding_store_and_preserves_live_journal(store):
    class Ledger:
        @staticmethod
        def materialise(shadow, stage, context):
            key = context['key']
            shadow.append('ledger', {'body': {'event': 'materialise', 'stage': stage,
                                             'instances': [{'key': key, 'id': 'ROW', 'scope': context}]}})
            return [key]
    before = deepcopy(store.events)
    contexts = [{'stage': 'plan', 'context': {'key': 'ROW@run'}}]
    rows = d.project_obligations(store, contexts, ledger=Ledger, store_factory=Store,
                                catalogue={'rows': [{'id': 'ROW', 'node': 'step.review'}]})
    assert store.events == before
    assert rows == [{'key': 'ROW@run', 'row': 'ROW', 'scope': {'key': 'ROW@run'},
                     'stage': 'plan', 'discharge_node': 'step.review'}]
    assert rows == d.project_obligations(store, contexts, ledger=Ledger, store_factory=Store,
                                       catalogue={'rows': [{'id': 'ROW', 'node': 'step.review'}]})


def test_stale_envelope_never_looks_current(store):
    d.pin_expected(store, expected())
    store.append('envelope-check', {'status': 'ok', 'usage_sha256': 'old-census'})
    result = d.report(store, instructions=Instructions, write=False)
    assert result['envelope']['status'] == 'unknown' and result['envelope']['recorded_status'] == 'ok'


def test_report_cli_uses_local_store_and_handles_missing_pin(store, monkeypatch, capsys):
    monkeypatch.setattr(cli, 'open_store', lambda run_id: store)
    monkeypatch.setattr(cli, 'policy_refusal', lambda argv: None)
    assert cli.main(['report', '--run', store.run_id]) == 2
    assert 'expected-run pin' in capsys.readouterr().err
    d.pin_expected(store, expected())
    monkeypatch.setattr(cli, 'report', lambda target: d.report(target, instructions=Instructions))
    assert cli.main(['report', '--run', store.run_id, '--json']) == 0
    value = json.loads(capsys.readouterr().out)
    assert value['run_id'] == store.run_id


def test_P19_06_no_network_anywhere(store, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('network access attempted')
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    d.configure(store, canary=True, capture_transcripts=True, faults=['stalled-tool'])
    d.pin_expected(store, expected())
    identity = {'step_id': 'make', 'seat': 'producer', 'role': 'producer-role', 'attempt': 1}
    d.capture_transcript(store, identity, 'local transcript')
    def boundary(spec):
        identifier = store.append('step-outcome', {**identity, 'status': 'escalated', 'reason': {'code': 'tool_timeout'}})
        return {'kind': 'step-outcome', 'record_id': identifier}
    d.inject_fault(store, 'stalled-tool', identity, exercise=boundary)
    result = d.report(store, instructions=Instructions)
    assert result['faults'][0]['detected'] is True


def test_attributed_surplus_broker_call_has_its_own_extra_row(store):
    value = expected()
    d.pin_expected(store, value)
    identity = complete_seat(store, value['seats'][0])
    extra = store.append('broker-evidence', {**identity, 'action': 'local inspect', 'status': 'ok'})
    result = d.report(store, instructions=Instructions, write=False)
    assert next(r for r in result['rows'] if r['id'] == 'extra:' + extra)['status'] == 'extra'


def test_graph_record_corruption_is_an_explicit_gap(store):
    d.pin_expected(store, expected())
    folder = store.path('graph', 'framework')
    folder.mkdir(parents=True)
    (folder / 'graphs.sqlite').write_bytes(b'invalid database')
    (folder / 'events.jsonl').write_text('unfinished JSON\n')
    result = d.report(store, instructions=Instructions, write=False)
    assert len(result['evidence_gaps']) == 2
    assert result['envelope']['status'] == 'unknown'


def test_new_plan_and_engagement_raise_are_visible(store):
    d.pin_expected(store, expected())
    changed = store.append('plan', {'plan_sha256': 'different-plan'})
    raised = store.append('engagement-escalation', {'new_tier': 'full', 'scope': 'run'})
    result = d.report(store, instructions=Instructions, write=False)
    assert next(r for r in result['rows'] if r['id'] == 'plan:' + changed)['status'] == 'ran-differently'
    assert next(r for r in result['rows'] if r['id'] == 'engagement:' + raised)['status'] == 'ran-differently'


def test_expected_p19_records_detect_late_forged_pin(store):
    store.append('step-dispatch', {})
    store.append('diagnostics-expected', expected())
    with pytest.raises(d.DiagnosticsRefused, match='follows an execution effect'):
        d.report(store, instructions=Instructions, write=False)


def test_p19_report_repeated_reads_are_stable_and_do_not_append(store):
    d.pin_expected(store, expected())
    before = deepcopy(store.events)
    first = d.report(store, instructions=Instructions)
    second = d.report(store, instructions=Instructions)
    assert first == second and store.events == before


def test_held_parent_explains_why_its_worker_seat_did_not_start(store):
    value = expected()
    d.pin_expected(store, value)
    store.append('step-outcome', {'step_id': 'make', 'status': 'held', 'reason': {'code': 'missing_input'}})
    result = d.report(store, instructions=Instructions, write=False)
    row = next(r for r in result['rows'] if r['id'] == value['seats'][0]['id'])
    assert row['status'] == 'held' and row['reason']['code'] == 'missing_input'


def test_reused_sessions_and_unmatched_observations_are_visible(store):
    value = expected()
    d.pin_expected(store, value)
    for seat in value['seats']:
        complete_seat(store, seat)
    observations = [e for e in store.events if e['kind'] == 'step-observation']
    observations[1]['record']['session_id'] = observations[0]['record']['session_id']
    extra = store.append('step-observation', {'step_id': 'unknown-node', 'node_id': 'unknown-worker', 'seat': None})
    result = d.report(store, instructions=Instructions, write=False)
    assert any('reused' in detail for row in result['rows'] for detail in row['differences'])
    assert next(r for r in result['rows'] if r['id'] == 'extra:' + extra)['status'] == 'extra'


def test_current_envelope_matches_the_actual_usage_census(store):
    value = expected()
    d.pin_expected(store, value)
    complete_seat(store, value['seats'][0])
    census = {'dispatches': [{**e['record'], 'record_id': e['id']} for e in store.scan('step-dispatch')],
              'observations': [{**e['record'], 'record_id': e['id']} for e in store.scan('step-observation')],
              'deliveries': [], 'settlements': []}
    store.append('envelope-check', {'status': 'ok', 'usage_sha256': digest(census)})
    assert d.report(store, instructions=Instructions, write=False)['envelope']['status'] == 'ok'
    store.append('step-dispatch', {'step_id': 'new-node'})
    assert d.report(store, instructions=Instructions, write=False)['envelope']['status'] == 'unknown'


def test_rdj_case_recorded_after_execution_is_a_difference(store):
    _, plan, engagement, _, _ = inputs()
    plan['steps'][0]['kind'] = 'decide'
    value = expected(plan=plan, engagement=engagement, classify=lambda s: 'R2')
    d.pin_expected(store, value)
    store.append('step-outcome', {'step_id': 'make', 'status': 'completed'})
    case = value['rdj_cases'][0]
    store.append('rdj-receipt', {'step_id': 'make', 'credited': True, 'subject_sha256': case['subject_sha256']})
    result = d.report(store, instructions=Instructions, write=False)
    row = next(r for r in result['rows'] if r['id'] == case['id'])
    assert row['status'] == 'ran-differently'
    assert any('after' in detail for detail in row['differences'])


def test_broker_model_counts_are_separate_from_tool_counts(store):
    value = expected()
    d.pin_expected(store, value)
    identity = complete_seat(store, value['seats'][0])
    for _ in range(2):
        store.append('broker-model-call', {**identity, 'status': 'ok'})
    result = d.report(store, instructions=Instructions, write=False)
    assert result['counts']['model_counts_equal'] is True
    assert result['counts']['tool_counts_equal'] is True
    assert result['counts']['broker_tool_calls'] == 0


def test_action_classifier_receives_normalized_action_not_step_kind():
    seen = []
    def classify(action):
        seen.append(action)
        assert 'step_kind' in action and 'kind' not in action
        return 'R0'
    expected(classify=classify)
    assert {a['step_kind'] for a in seen} == {'author', 'ask'}


@pytest.mark.parametrize('kind', ['broker-evidence', 'broker-model-call', 'worker-session', 'worker-completion'])
def test_prior_broker_or_worker_evidence_also_refuses_first_pin(store, kind):
    store.append(kind, {})
    with pytest.raises(d.DiagnosticsRefused, match='before the first effect'):
        d.pin_expected(store, expected())


def test_observation_uses_one_journal_prefix_during_concurrent_append(store):
    d.pin_expected(store, expected())
    original_scan = store.scan
    started = []
    def scan(kind):
        result = original_scan(kind)
        if kind == 'step-dispatch' and not started:
            started.append(True)
            store.append('step-dispatch', {'step_id': 'make', 'node_id': 'worker', 'seat': None})
            store.append('step-observation', {'step_id': 'make', 'node_id': 'worker', 'seat': None})
        return result
    store.scan = scan
    observed = d.observe(store)
    assert len(observed['records']['step-dispatch']) == 1
    assert len(observed['records']['step-observation']) == 1
    assert all(e['seq'] <= observed['journal_cutoff_seq'] for values in observed['records'].values() for e in values)


def test_high_consequence_operation_has_a_case_without_explicit_effect_list():
    _, plan, engagement, _, _ = inputs()
    plan['steps'][0]['kind'] = 'operate'
    value = expected(plan=plan, engagement=engagement, classify=lambda action: 'R2')
    assert [case['node_id'] for case in value['rdj_cases']] == ['make']


def test_unavailable_envelope_is_refused_before_pin():
    _, _, engagement, _, _ = inputs()
    engagement['projected_envelope'] = {'status': 'unavailable'}
    with pytest.raises(d.DiagnosticsRefused, match='envelope bounds missing'):
        expected(engagement=engagement)


def step_review_expected():
    """A producer step with one step-review seat, in the engagement seat-plan shape."""
    route, plan, engagement, cards, rows = inputs()
    review = {'key': 'step:make:review-role', 'step_id': 'make', 'role': 'review-role', 'category': 'step',
              'step': {'id': 'make', 'kind': 'review', 'role': 'review-role'}}
    engagement['seat_plan']['seats'] = [review]
    return d.build_expected(route, plan, engagement, obligation_rows=rows, instructions=Instructions,
                            cards=cards, classify=lambda action: 'R0')


def step_controller_worker(store, seat, *, parent, seat_key, acting, node_id, session, status='completed'):
    """Dispatch, delivery, observation and completion with the governed step controller's identities.

    The dispatch names the parent step; delivery and observation name the acting (derived seat)
    step; dispatch and observation share the worker node id.
    """
    packet = digest('packet:' + node_id)
    store.append('step-dispatch', {'key': 'key-' + node_id, 'step_id': parent, 'seat': seat_key,
                                   'node_id': node_id, 'attempt': 1, 'packet_sha256': packet,
                                   'role': seat['role'], 'diagnostics_node_id': parent,
                                   'diagnostics_seat_id': seat['id'] if seat_key else None})
    store.append('instruction-delivery', {'kind': 'instruction-delivery', 'manifest_sha256': seat['manifest']['sha256'],
                                          'packet_sha256': packet, 'units': [u['id'] for u in seat['instruction_units']],
                                          'step_id': acting, 'attempt': 1, 'seat': seat_key})
    store.append('step-observation', {'step_id': acting, 'seat': seat_key, 'attempt': 1, 'node_id': node_id,
                                      'status': status, 'session_id': session, 'role': seat['role'],
                                      'diagnostics_node_id': parent,
                                      'diagnostics_seat_id': seat['id'] if seat_key else None,
                                      'usage': {'reported': True, 'turns': 1}, 'calls': {'broker_calls': 0}})
    final = {'instruction_ack': {'manifest_sha256': seat['manifest']['sha256']},
             'checklist': [{'unit': u['id'], 'sha256': u['sha256']} for u in seat['instruction_units']
                           if u['kind'] == 'duty']}
    store.append('worker-completion', {'session': session, 'final_record': final, 'artifacts': []})


def test_step_controller_review_seat_identities_and_typed_hold_codes(store):
    value = step_review_expected()
    producer, review = value['seats']
    d.pin_expected(store, value)
    step_controller_worker(store, producer, parent='make', seat_key=None, acting='make',
                           node_id='ctl.make', session='session-1')
    store.append('step-outcome', {'step_id': 'make', 'attempt': 1, 'status': 'completed', 'reason': None})
    step_controller_worker(store, review, parent='make', seat_key='seat:review-role:1',
                           acting='make:review:review-role:1', node_id='ctl.make.seat_review-role_1',
                           session='session-2')
    store.append('step-outcome', {'step_id': 'make:review:review-role:1', 'attempt': 1, 'status': 'completed',
                                  'seat': 'seat:review-role:1', 'reason': None})
    # A typed hold is a reason code with its detail beside it.
    store.append('step-outcome', {'step_id': 'wait', 'attempt': 1, 'status': 'held', 'reason': 'awaiting_authority',
                                  'detail': 'Waiting for an answer.'})
    result = d.report(store, instructions=Instructions, write=False)
    rows = {r['id']: r for r in result['rows']}
    assert rows[producer['id']]['status'] == 'ran-as-designed', rows[producer['id']]
    assert rows[review['id']]['status'] == 'ran-as-designed', rows[review['id']]
    assert rows['make']['status'] == 'ran-as-designed'
    assert rows['wait']['status'] == 'held'
    assert rows['wait']['reason'] == {'code': 'awaiting_authority', 'message': 'Waiting for an answer.'}
    assert not [r for r in result['rows'] if r['status'] == 'extra']


def test_step_controller_seat_holds_apply_to_their_seat(store):
    value = step_review_expected()
    producer, review = value['seats']
    d.pin_expected(store, value)
    step_controller_worker(store, producer, parent='make', seat_key=None, acting='make',
                           node_id='ctl.make', session='session-1')
    store.append('step-outcome', {'step_id': 'make', 'attempt': 1, 'status': 'completed', 'reason': None})
    step_controller_worker(store, review, parent='make', seat_key='seat:review-role:1',
                           acting='make:review:review-role:1', node_id='ctl.make.seat_review-role_1',
                           session='session-2')
    # A completed session whose verdict was not credited is a held seat, not a seat that ran as designed.
    held = store.append('step-outcome', {'step_id': 'make:review:review-role:1', 'attempt': 1, 'status': 'held',
                                         'seat': 'seat:review-role:1', 'reason': 'review_uncredited'})
    result = d.report(store, instructions=Instructions, write=False)
    row = next(r for r in result['rows'] if r['id'] == review['id'])
    assert row['status'] == 'held' and row['reason']['code'] == 'review_uncredited' and held in row['evidence']
    assert not [r for r in result['rows'] if r['status'] == 'extra']


def test_step_controller_seat_hold_before_dispatch_and_unmatched_seat_outcome(store):
    value = step_review_expected()
    review = value['seats'][1]
    d.pin_expected(store, value)
    store.append('step-outcome', {'step_id': 'make:seat:review-role:1', 'attempt': 1, 'status': 'held',
                                  'seat': 'seat:review-role:1', 'reason': 'instruction_packet_refused',
                                  'detail': 'packet refused'})
    stray = store.append('step-outcome', {'step_id': 'make:seat:other-role:1', 'attempt': 1, 'status': 'completed',
                                          'seat': 'seat:other-role:1', 'reason': None})
    result = d.report(store, instructions=Instructions, write=False)
    row = next(r for r in result['rows'] if r['id'] == review['id'])
    assert row['status'] == 'held' and row['reason']['code'] == 'instruction_packet_refused'
    assert next(r for r in result['rows'] if r['id'] == 'extra:' + stray)['status'] == 'extra'


def test_decide_step_rung_is_not_a_classification_input():
    """The judgment classifier ignores a decide step's rung; an operate step's rung counts."""
    _, plan, engagement, _, _ = inputs()
    plan['steps'][0].update(kind='operate', rung='full')
    plan['steps'][1].update(kind='decide', rung='full')
    plan['sha256'] = digest({k: v for k, v in plan.items() if k != 'sha256'})
    engagement['scientific_plan_sha256'] = plan['sha256']
    value = expected(plan=plan, engagement=engagement,
                     classify=lambda action: 'R2' if action.get('rung') == 'full' else 'R1')
    assert [case['node_id'] for case in value['rdj_cases']] == ['make']


def test_report_command_applies_the_command_policy_before_opening_a_store(store, monkeypatch, capsys):
    opened = []
    monkeypatch.setattr(cli, 'open_store', lambda run_id: opened.append(run_id) or store)
    monkeypatch.setattr(cli, 'policy_refusal', lambda argv: 'refused for a controller-owned run')
    assert cli.main(['report', '--run', store.run_id]) == 2
    assert 'refused for a controller-owned run' in capsys.readouterr().err and opened == []
    d.pin_expected(store, expected())
    seen = []
    monkeypatch.setattr(cli, 'policy_refusal', lambda argv: seen.append(argv))
    monkeypatch.setattr(cli, 'report', lambda target: d.report(target, instructions=Instructions))
    assert cli.main(['report', '--run', store.run_id, '--json']) == 0
    assert seen == [['diagnostics', 'report', '--run', store.run_id, '--json']] and opened == [store.run_id]


def test_step_controller_records_without_logical_identity_still_link_by_worker_node(store):
    """Before the identity fields are recorded, a seat's session still links to its dispatch."""
    value = step_review_expected()
    review = value['seats'][1]
    d.pin_expected(store, value)
    step_controller_worker(store, review, parent='make', seat_key='seat:review-role:1',
                           acting='make:review:review-role:1', node_id='ctl.make.seat_review-role_1',
                           session='session-2')
    for event in store.events:
        if event['kind'] in ('step-dispatch', 'step-observation'):
            for field in ('diagnostics_node_id', 'diagnostics_seat_id', 'role'):
                event['record'].pop(field, None)
    result = d.report(store, instructions=Instructions, write=False)
    row = next(r for r in result['rows'] if r['id'] == review['id'])
    assert row['differences'] == ['Observed role differs or was not recorded: None',
                                  'Role differs or was not recorded: None']
    assert not [r for r in result['rows'] if r['status'] == 'extra']


@pytest.mark.parametrize(('fault', 'kind', 'response', 'detected'), [
    # The tool broker refuses a write that escapes the workspace and a forbidden source.
    ('outside-output', 'broker-evidence', {'status': 'refused', 'error': 'write_outside_workspace'}, True),
    ('forbidden-source', 'broker-evidence', {'status': 'refused', 'error': 'forbidden_source'}, True),
    # The step controller holds a step whose input has no receipted producer or is absent.
    ('missing-input', 'step-outcome', {'status': 'held', 'reason': 'predecessor_unreceipted', 'detail': 'x'}, True),
    ('missing-input', 'step-outcome', {'status': 'held', 'reason': 'run_input_missing', 'detail': 'x'}, True),
    ('outside-output', 'broker-evidence', {'status': 'refused', 'error': 'forbidden_source'}, False),
    ('forbidden-source', 'broker-evidence', {'status': 'ok', 'error': None}, False),
    ('missing-input', 'step-outcome', {'status': 'refused', 'reason': 'run_input_missing'}, False),
])
def test_fault_detection_accepts_the_boundaries_typed_responses(store, fault, kind, response, detected):
    d.configure(store, canary=True, faults=[fault])
    d.pin_expected(store, expected())
    identity = {'step_id': 'make', 'seat': 'producer', 'role': 'producer-role', 'attempt': 1}
    def boundary(spec):
        row = {'step_id': 'make', 'attempt': 1, 'node_id': 'ctl.make', **response}
        return {'kind': kind, 'record_id': store.append(kind, row)}
    d.inject_fault(store, fault, identity, exercise=boundary)
    row = d.report(store, instructions=Instructions, write=False)['faults'][0]
    assert row['detected'] is detected
    assert row['observed_response'] == response['status']
