"""Governed-step evidence accepted by the real protected store and obligation ledger."""
from copy import deepcopy
import json
import sys

import pytest

from ravel.controller import instructions, ledger
from ravel.controller.ledger.record import EVIDENCE_KEYS
from ravel.controller.ledger.state import load
from ravel.controller.store import RunStore
from ravel.controller.step import graph
from test_p04_support import (context, graphs, inert_worker, install_plan, make_step, run_env,
                              services_installed)

REAL_LEDGER = ledger
REAL_INSTRUCTIONS = instructions


@pytest.fixture
def instructed_env(contract_env, inert_worker, monkeypatch):
    """The real instruction service, with only the inert executable's packet parser adapted."""
    from ravel.workflow import toolbelt
    from ravel.paths import package_data_path
    monkeypatch.setitem(sys.modules, 'ravel.controller.instructions', REAL_INSTRUCTIONS)
    monkeypatch.setattr(toolbelt, 'output_schema', lambda card: json.loads(package_data_path(
        'roles', 'schema', 'outputs', card['output']['schema'] + '.json').read_text()))
    text = inert_worker.executable.read_text()
    text = text.replace("spec = json.loads(lines[lines.index('== Step specification (step.v1) ==') + 1])",
                        "spec = json.JSONDecoder().raw_decode(prompt.split("
                        "'== Step specification (step.v1) ==', 1)[1].lstrip())[0]")
    # The real packet declares outputs in the step specification.
    text = text.replace("scenario = {**scenario,", "declared = [r['path'] for r in spec['outputs']]\nscenario = {**scenario,")
    inert_worker.executable.write_text(text)
    # Refresh the probe after changing the inert executable's bytes, and qualify it again.
    from ravel.workflow import transport_registry as tr
    from test_p04_support import qualify
    qualify(contract_env.store, tr.probe('claude-cli-worker', executable=str(inert_worker.executable)))
    return contract_env


@pytest.fixture(autouse=True)
def _real_instruction_contract(instructed_env):
    return instructed_env


@pytest.mark.parametrize('damage', [None, 'missing', 'packet', 'session', 'unwritten'])
def test_instructed_rows_discharge_through_real_p03(instructed_env, inert_worker, graphs,
                                                   monkeypatch, damage):
    env = instructed_env
    original_observe = graph.observe

    def observe(state):
        result = original_observe(state)
        # The custody contract must exist before validation begins.
        sessions = env.store.scan('worker-session')
        assert sessions, 'no controller-observed worker session'
        if damage == 'packet':
            (env.run_dir / state['packet']['path']).write_text('changed after dispatch')
        return result
    monkeypatch.setattr(graph, 'observe', observe)
    if damage == 'missing':
        inert_worker.scenario(ack='omit_row')
    elif damage == 'unwritten':
        text = inert_worker.executable.read_text().replace(
            "'evidence': 'final_record#/kind'", "'evidence': 'outputs/unwritten.json#/value'")
        inert_worker.executable.write_text(text)
        # Refresh the probe after changing the inert executable's bytes, and qualify it again.
        from ravel.workflow import transport_registry as tr
        from test_p04_support import qualify
        qualify(env.store, tr.probe('claude-cli-worker', executable=str(inert_worker.executable)))
    elif damage == 'session':
        inert_worker.scenario(session='session-fixed')
        assert run_contract(env, make_step('s1'))['status'] == 'completed'
    outcome = run_contract(env, make_step('s1'), attempt=2 if damage == 'session' else 1)
    assert outcome['status'] == ('completed' if damage is None else 'failed'), outcome
    population = [i for i in load(env.store, full=True).instances.values()
                  if i.scope.get('seat') == 'producer' and i.scope.get('attempt') == (2 if damage == 'session' else 1)
                  and (i.id == 'ROLE-baseline-producer-purpose' or i.id.startswith('ROLE-baseline-producer-protocol-'))]
    assert population
    for instance in population:
        assert instance.status == ('satisfied' if damage is None else 'pending'), (instance.id, instance.status)
        if damage is None:
            completion = env.store.read('worker-completion', instance.evidence['ack'])['record']
            delivery = env.store.read('instruction-delivery', instance.evidence['instruction_receipt'])['record']
            session = env.store.read('worker-session', delivery['session'])
            assert completion['session'] == session['id'] != session['record']['session_id']
            assert completion['artifacts']
            for artifact in completion['artifacts']:
                assert env.store.path('instruction-artifacts', session['id'], *artifact['path'].split('/')).is_file()
    if damage is not None:
        assert not [r for r in env.store.scan('custody') if r['record']['attempt'] == (2 if damage == 'session' else 1)]
    assert all(r['record'].get('session') for r in env.store.scan('instruction-delivery'))
    projections = [r for r in env.store.scan('instruction-delivery')
                   if r['record'].get('kind') == 'instruction-delivery-session']
    assert projections


@pytest.fixture
def contract_env(run_env, monkeypatch):
    monkeypatch.setitem(sys.modules, graph.module('ledger').__name__, REAL_LEDGER)
    run_env.store = RunStore('run-step-contract', root=run_env.root / 'protected')
    REAL_LEDGER.materialise(run_env.store, 'intake', {'run_id': run_env.store.run_id})
    return run_env


def run_contract(env, step, *, attempt=1, **extra):
    from ravel.controller.step import run
    pin = install_plan(env.store, [step], run_dir=env.run_dir)
    plan_record = env.store.scan('plan')[-1]['record']
    plan = json.loads(env.store.get_blob(plan_record['blob']))
    REAL_LEDGER.materialise(env.store, 'plan', {'plan': plan})
    # As the controller does when it binds a plan: the plan-bind rows are recorded, the governed step verifies them.
    from ravel.controller.step import binding
    binding.record_plan_rows(env.store, plan, contract_sha256=None, ledger=REAL_LEDGER)
    outcome = run(env.store, step, context(env.store, env.run_dir, pin, attempt=attempt, **extra))
    if outcome['status'] != 'completed':
        print(json.dumps(outcome, sort_keys=True))
    from ravel.workflow import effect_ledger
    receipts = effect_ledger.receipts(env.store.path('step-scopes', step['id'], str(attempt)))
    assert not outcome.get('interrupts'), json.dumps({'outcome': outcome, 'receipts': receipts}, sort_keys=True)
    return outcome


@pytest.mark.parametrize('damage', [None, 'ack', 'label', 'mutant'])
def test_producer_step_rows_are_accepted_by_the_real_ledger(contract_env, inert_worker, graphs,
                                                           monkeypatch, damage):
    env = contract_env
    if damage in ('ack', 'mutant'):
        inert_worker.scenario(ack='wrong_manifest')
    elif damage == 'label':
        inert_worker.scenario(knowledge_used=['unqueried-entry'])
    evaluated = {}
    update = graph.ledger_update

    def capture(state):
        evaluated.update(deepcopy(state.get('evaluations') or {}))
        return update(state)
    monkeypatch.setattr(graph, 'ledger_update', capture)
    record = REAL_LEDGER.record
    if damage == 'mutant':
        def drop_reason(store, key, status, evidence):
            evidence = deepcopy(evidence)
            if status == 'violated':
                evidence.pop('reason', None)
            return record(store, key, status, evidence)
        monkeypatch.setattr(REAL_LEDGER, 'record', drop_reason)
    outcome = run_contract(env, make_step('s1'))
    assert env.store.scan('step-ledger-unmaterialised') == [], outcome
    state = load(env.store, full=True)
    if damage == 'mutant':
        assert outcome['status'] == 'failed', outcome
        assert outcome['reason'] == 'ledger_refused:reason_missing', outcome
        assert outcome['ledger']['refused']
        assert any(r['code'] == 'reason_missing' and r['entry'].startswith('I01@')
                   for r in outcome['ledger']['refused'])
        return
    assert outcome['status'] == ('failed' if damage == 'ack' else 'completed'), outcome
    pending = set(REAL_LEDGER.pending(env.store, step='s1'))
    catalogue = REAL_LEDGER.load_catalogue()
    actual = {i.id: i for i in state.instances.values() if i.scope.get('step') == 's1'
              and (i.scope.get('seat') in (None, 'producer'))}
    from ravel.controller.step import binding
    for row, value in evaluated.items():
        if row not in actual:
            continue  # selectors exclude duties of other execution branches
        instance = actual[row]
        if catalogue.rows[row]['node'].split('[', 1)[0] in binding.PLAN_BIND_NODES:
            # Recorded by the controller when it bound the plan; the step verifies it and never writes it.
            assert instance.evidence['mechanism'] == binding.MECHANISM and instance.key not in pending, (row, instance)
            continue
        if catalogue.rows[row]['class'] == 'I':
            delivered = row == 'CF13' or (row.startswith('ROLE-') and (row.endswith(('-purpose', '-knowledge')) or '-protocol-' in row))
            expected_status = 'satisfied' if delivered and damage != 'ack' else 'pending'
            assert instance.status == expected_status
            assert (instance.key in pending) == (expected_status == 'pending')
            if expected_status == 'satisfied':
                assert instance.evidence['ack'] and instance.evidence['instruction_receipt']
            continue
        assert instance.status == value['status'], (row, instance.status, value)
        assert instance.key not in pending
        if instance.status == 'satisfied':
            assert any(instance.evidence.get(key) for key in EVIDENCE_KEYS), (row, instance.evidence)
        else:
            assert isinstance(instance.evidence.get('reason'), str) and instance.evidence['reason']
            if catalogue.rows[row]['class'] == 'L':
                assert instance.evidence.get('label')
    expected = {'B01': 'satisfied', 'B02': 'satisfied', 'G07': 'satisfied',
                'I02': 'violated' if damage == 'ack' else 'satisfied',
                'I01': 'violated' if damage == 'ack' else 'satisfied',
                'I07': 'violated' if damage == 'label' else 'satisfied'}
    assert {row: actual[row].status for row in expected} == expected
    pointers = {'B01': 'record', 'B02': 'record', 'G07': 'record', 'SW28': 'sha256',
                'I02': 'instruction_receipt', 'I01': 'instruction_receipt', 'I05': 'record',
                'I07': 'validator', 'G13': 'receipt', 'ROLE-baseline-producer-family': 'sha256'}
    for row, pointer in pointers.items():
        assert actual[row].evidence.get(pointer), (row, actual[row].evidence)
    for instance in actual.values():
        evidence = instance.evidence or {}
        if evidence.get('mechanism'):
            pointer = evidence.get('record') or evidence.get('ack')
            assert pointer, (instance.id, evidence)
            kind = pointer.rsplit('-', 2)[0]
            assert env.store.read(kind, pointer)['record']
    # No escalation occurred: CF01 and the escalation duties are never instantiated (they exist only on an occurrence).
    assert not [i for i in state.instances.values() if i.id == 'CF01' or '-escalation-' in i.id], outcome
    for instance in actual.values():
        if instance.id.startswith('ROLE-') and catalogue.rows[instance.id]['class'] == 'I':
            delivered = instance.id.endswith(('-purpose', '-knowledge')) or '-protocol-' in instance.id
            assert instance.status == ('satisfied' if delivered and damage != 'ack' else 'pending')


def test_materialisation_refusal_fails_the_attempt(contract_env, monkeypatch):
    from ravel.controller.step.services import bound
    env = contract_env
    step = make_step('s1')

    def refuse(store, stage, context):
        raise REAL_LEDGER.LedgerError('context_invalid', 'invalid seat binding')
    monkeypatch.setattr(REAL_LEDGER, 'materialise', refuse)
    state = {'step': step, 'acting': step, 'branch': 'worker',
             'context': context(env.store, env.run_dir, '0' * 64), 'evaluations': {}}
    with bound(env.store):
        result = graph.ledger_update(state)
    assert graph._status_of({**state, **result}) == ('failed', 'ledger_refused:context_invalid')
    assert result['ledger']['refused'][0]['stage'] == 'dispatch'
    assert env.store.scan('step-ledger-unmaterialised') == []


def test_consult_and_producer_have_separate_observed_instruction_receipts(instructed_env, graphs, monkeypatch):
    env = instructed_env
    original = graph.cards.consult_triggers
    monkeypatch.setattr(graph.cards, 'consult_triggers', lambda card, step, facts: (
        [{'role': 'consult-inference', 'when': 'contested_node'}] if card['id'] == 'baseline-producer'
        else original(card, step, facts)))
    outcome = run_contract(env, make_step('s1'))
    assert outcome['status'] == 'completed', outcome
    sessions = [r for r in env.store.scan('worker-session')]
    assert {r['record']['seat'] for r in sessions} == {None, 'consult:consult-inference:1'}
    for session in sessions:
        assert session['record']['session_id'] != session['id']
        completion = next(r for r in env.store.scan('worker-completion') if r['record']['session'] == session['id'])
        population = [i for i in load(env.store, full=True).instances.values()
                      if i.scope.get('seat') == (session['record']['seat'] or 'producer')
                      and (i.id.endswith('-purpose') or '-protocol-' in i.id) and i.id.startswith('ROLE-')]
        assert population
        assert all(i.status == 'satisfied' and i.evidence['ack'] == completion['id']
                   and i.evidence['instruction_receipt'] for i in population)


def test_two_review_seats_discharge_their_own_rows(contract_env, inert_worker, graphs, monkeypatch):
    env = contract_env
    roles = ['integrity-auditor', 'model-critic']
    from test_p13_validator_adapters import UFO, CHARGES, GAUGE, ufo, zprime, gauge_record
    documents = {UFO: ('ufo', ufo()), CHARGES: ('charges', zprime()), GAUGE: ('gauge', gauge_record())}
    checks = {}
    for check, (name, document) in documents.items():
        relative = 'inputs/model-critic/' + name + '.json'
        target = env.run_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(document, indent=2) + '\n')
        checks[check] = {'document': relative}
    step = make_step('s1', review=roles, parameters={'check_inputs': checks})
    snapshots = {}
    launched = set()
    update = graph.ledger_update
    facts = graph._controller_facts

    def before_dispatch(state):
        if state.get('seat'):
            seat = state['seat']['key']
            attempt = state['context']['attempt']
            population = [i for i in load(env.store, full=True).instances.values() if i.scope == {
                'step': 's1', 'point': 'point-one', 'seat': seat, 'attempt': attempt}]
            assert population and all(i.status == 'pending' for i in population)
            launched.add((seat, attempt))
        return facts(state)
    monkeypatch.setattr(graph, '_controller_facts', before_dispatch)

    # The parent's credit decision closes a credited seat's review rows that the seat's own update left open.
    closures = {}

    def capture(state):
        if state.get('seat'):
            snapshots[(state['seat']['key'], state['context']['attempt'])] = deepcopy(state)
        elif (state.get('credit') or {}).get('seat_closures') is not None:
            closures[state['context']['attempt']] = deepcopy(state['credit']['seat_closures'])
        return update(state)

    def closed(seat, attempt, row):
        return ((closures.get(attempt) or {}).get(seat) or {}).get(row)
    monkeypatch.setattr(graph, 'ledger_update', capture)
    inert_worker.scenario(seats={roles[1]: {'ack': 'omit_row'}})
    first = run_contract(env, step, point='point-one')
    state = load(env.store, full=True)
    current = set(state.current_keys())
    expected_by_attempt = {}
    for role in roles:
        seat = 'seat:' + role + ':1'
        population = {i.id: i for i in state.instances.values()
                      if i.scope == {'step': 's1', 'point': 'point-one', 'seat': seat, 'attempt': 1}}
        assert population, (role, first)  # baseline has no seat materialisation at all
        observed = snapshots[(seat, 1)]
        ctx = {'step': 's1', 'seat': seat, 'role': role, 'attempt': 1, 'point': 'point-one',
               'seat_kind': 'review', 'review_kind': 'critic', 'step_kind': 'review'}
        expected = set(REAL_LEDGER.materialise(env.store, 'review', ctx))
        assert {i.key for i in population.values()} == expected
        expected_by_attempt[seat] = expected
        for row, instance in population.items():
            evaluated = observed.get('evaluations', {}).get(row) or closed(seat, 1, row)
            cls = REAL_LEDGER.load_catalogue().rows[row]['class']
            delivered = row == 'CF13' or (row.startswith('ROLE-') and (row.endswith(('-purpose', '-knowledge')) or '-protocol-' in row))
            expected_status = ('satisfied' if delivered and role == roles[0] else 'pending') if cls == 'I' else (
                evaluated['status'] if evaluated else 'pending')
            assert instance.status == expected_status, (seat, row, instance.status, evaluated)
            assert instance.key in current
        assert population['I01'].status == ('violated' if role == roles[1] else 'satisfied')
        assert population['B01'].evidence['record'] != next(
            i.evidence['record'] for i in state.instances.values() if i.id == 'B01'
            and i.scope.get('seat') == 'producer')
    assert first['status'] == 'held' and first['reason'] == 'review_uncredited', first
    # Only the credited seat's rows were closed by the parent, each with the parent's credit decision or projection.
    assert set(closures[1]) == {'seat:' + roles[0] + ':1'} and closures[1]['seat:' + roles[0] + ':1']
    credit_ids = {r['id'] for r in env.store.scan('step-credit')}
    for row, value in closures[1]['seat:' + roles[0] + ':1'].items():
        assert value['evidence'].get('credit') in credit_ids or value['evidence'].get('sha256'), (row, value)
    # The plan's ownership row was recorded by the controller when it bound the plan (the step only verifies it).
    plan_ownership = next(i for i in state.instances.values() if i.id == 'CF07')
    assert plan_ownership.status == 'satisfied' and plan_ownership.evidence['mechanism'] == 'controller.plan_bind'
    fact = env.store.read('step-plan-bind', plan_ownership.evidence['record'])['record']
    assert fact['step_id'] == 's1' and fact['checks']['ownership']['status'] == 'satisfied'
    broken = next(i for i in state.instances.values() if i.id == 'I01'
                  and i.scope.get('seat') == 'seat:' + roles[1] + ':1')
    with pytest.raises(REAL_LEDGER.LedgerError) as refused:
        REAL_LEDGER.record(env.store, broken.key, 'satisfied', {'validator': 'late-repair'})
    assert refused.value.code == 'transition_refused'
    inert_worker.scenario()
    second = run_contract(env, step, attempt=2, point='point-one')
    assert second['status'] == 'completed', second
    state = load(env.store, full=True)
    current = set(state.current_keys())
    assert state.instances[broken.key].status == 'violated' and broken.key not in current
    for role in roles:
        seat = 'seat:' + role + ':1'
        population = {i.id: i for i in state.instances.values() if i.scope == {
            'step': 's1', 'point': 'point-one', 'seat': seat, 'attempt': 2}}
        assert population['I01'].status == 'satisfied'
        expected = set(REAL_LEDGER.materialise(env.store, 'review', {
            'step': 's1', 'seat': seat, 'role': role, 'attempt': 2, 'point': 'point-one',
            'seat_kind': 'review', 'review_kind': 'critic', 'step_kind': 'review'}))
        assert {i.key for i in population.values()} == expected
        assert expected <= current and not expected_by_attempt[seat] & current
        observed = snapshots[(seat, 2)]
        for row, instance in population.items():
            evaluated = observed.get('evaluations', {}).get(row) or closed(seat, 2, row)
            cls = REAL_LEDGER.load_catalogue().rows[row]['class']
            delivered = row == 'CF13' or (row.startswith('ROLE-') and (row.endswith(('-purpose', '-knowledge')) or '-protocol-' in row))
            assert instance.status == (('satisfied' if delivered else 'pending') if cls == 'I' else (
                evaluated['status'] if evaluated else 'pending'))
    assert env.store.scan('step-ledger-unmaterialised') == []
    assert launched == {(f'seat:{role}:1', attempt) for role in roles for attempt in (1, 2)}


@pytest.mark.parametrize('refuse', [False, True])
def test_a_review_seat_escalation_instantiates_only_its_roles_escalation_duties(contract_env, inert_worker, graphs,
                                                                               monkeypatch, refuse):
    env = contract_env
    if refuse:
        materialise = REAL_LEDGER.materialise

        def refuse_event(store, stage, context):
            if stage == 'event':
                raise REAL_LEDGER.LedgerError('context_invalid', 'escalation occurrence refused')
            return materialise(store, stage, context)
        monkeypatch.setattr(REAL_LEDGER, 'materialise', refuse_event)
    inert_worker.scenario(findings_escalation=[{'kind': 'checkin_flag', 'statement': 'a fixture review condition',
                                                'evidence': ['final_record#/kind']}])
    outcome = run_contract(env, make_step('s1', review=['integrity-auditor']))
    duties = [i for i in load(env.store, full=True).instances.values() if i.id == 'CF01' or '-escalation-' in i.id]
    if refuse:
        # The occurrence could not be stated: the attempt fails, it never continues without the duties.
        assert (outcome['status'], outcome['reason']) == ('failed', 'ledger_refused:context_invalid'), outcome
        assert duties == [] and env.store.scan('step-ledger-refused')[-1]['record']['rows'][0]['stage'] == 'event'
        return
    assert outcome['status'] == 'completed' and outcome['escalation'] == 'checkin_flag', outcome
    assert 'CF01' in {i.id for i in duties}
    for instance in duties:  # the escalating seat's role only, bound to this occurrence, and never satisfied here
        assert instance.id == 'CF01' or instance.id.startswith('ROLE-integrity-auditor-escalation-'), instance.id
        assert instance.scope == {'event': 'escalation:s1:seat:integrity-auditor:1:1'} and instance.status == 'pending'


@pytest.mark.parametrize('purpose', ['review', 'consult'])
def test_seat_binding_retains_the_complete_review_context(purpose):
    step = make_step('s1', kind='review' if purpose == 'review' else 'author')
    seat = None if purpose == 'review' else {'key': 'consult:role:1', 'purpose': purpose,
                                            'review_kind': purpose}
    state = {'step': step, 'acting': step, 'branch': 'worker', 'seat': seat,
             'card': {'id': 'baseline-producer'},
             'context': {'run_id': 'run-binding', 'attempt': 2, 'point': 'point-one'}}
    stage, context, step_scope, seat_scope = graph._ledger_binding(state)
    assert stage == 'review'
    assert context == {'run_id': 'run-binding', 'step': 's1', 'point': 'point-one',
                       'seat': 'producer' if seat is None else seat['key'], 'attempt': 2,
                       'role': 'baseline-producer', 'seat_kind': purpose,
                       'review_kind': 'critic' if purpose == 'review' else 'consult',
                       'step_kind': step['kind']}
    assert step_scope == {'step': 's1'} and seat_scope['point'] == 'point-one'


def test_seat_materialisation_refusal_prevents_launch_and_releases_reservation(contract_env, inert_worker,
                                                                               graphs, monkeypatch):
    env = contract_env
    materialise = REAL_LEDGER.materialise

    def refuse_seat(store, stage, context):
        if stage == 'review':
            raise REAL_LEDGER.LedgerError('context_invalid', 'review seat binding refused')
        return materialise(store, stage, context)
    monkeypatch.setattr(REAL_LEDGER, 'materialise', refuse_seat)
    outcome = run_contract(env, make_step('s1', review=['integrity-auditor']))
    assert outcome['status'] == 'held' and outcome['reason'] == 'review_uncredited'
    assert [e['record']['seat'] for e in env.store.scan('step-dispatch')] == [None]
    seat = 'seat:integrity-auditor:1'
    reservation = next(e['record'] for e in env.store.scan('budget-reservation') if e['record']['seat'] == seat)
    settlement = [e['record'] for e in env.store.scan('budget-settlement')
                  if e['record']['key'] == reservation['key']]
    assert len(settlement) == 1 and settlement[0]['status'] == 'released'
    failed = [e['record'] for e in env.store.scan('step-outcome') if e['record'].get('seat') == seat]
    assert failed[-1]['reason'] == 'ledger_refused:context_invalid'
    assert env.store.scan('step-ledger-unmaterialised') == []


def test_a_review_seat_records_its_dispatch_validate_and_adopt_rows_from_their_own_actions(contract_env, inert_worker,
                                                                                         graphs):
    """SW39 at the seat's dispatch (its parent's work of this attempt is adopted and checked), CF05 at its validate node
    (its credited outputs are the ones its spec declares), I09 and the must_check rows from the producer's validator
    run (the producer's check union includes explicitly declared reviewer checks), and G08 and I10 from the seat's own adopt node, which adopts and accepts its outputs under the seat
    step's sealed spec digest."""
    from pathlib import Path
    from ravel.workflow import role_registry
    env = contract_env
    outcome = run_contract(env, make_step('s1', review=['integrity-auditor']))
    assert outcome['status'] == 'completed', outcome
    state = load(env.store, full=True)
    seat = {i.id: i for i in state.instances.values()
            if i.scope.get('seat') == 'seat:integrity-auditor:1' and i.scope.get('attempt') == 1}
    for row in ('SW39', 'CF05', 'G08', 'I10'):
        assert seat[row].status == 'satisfied', (row, seat[row].evidence)
    assert seat['SW39'].evidence['mechanism'] == 'parent-adopted-and-checked'
    assert seat['I09'].status == 'satisfied', seat['I09'].evidence
    validation_id = seat['I09'].evidence['validator']
    producer = env.store.read('step-validation', validation_id)['record']
    assert producer['step_id'] == 's1' and producer['seat'] is None and producer['attempt'] == 1
    assert producer['report']['passed'] is True
    passed = {result['check_id'] for result in producer['report']['results'] if result['status'] == 'passed'}
    card = role_registry.load('integrity-auditor')
    runnable, _ = graph.validate.validator_ids(card)
    assert set(runnable) <= passed and set(seat['I09'].evidence['checks']) == set(runnable)
    for index, check in enumerate(card['must_check']):
        row = seat[f'ROLE-integrity-auditor-must_check-{index}']
        assert row.status == 'satisfied' and row.evidence['validator'] == validation_id, row.evidence
        assert check in passed
    adopted = [r['record'] for r in env.store.scan('custody')
               if str(r['record'].get('step_id')).startswith('s1.review.') and r['record']['status'] == 'accepted']
    assert {Path(r['path']).name for r in adopted} == {'review-integrity-auditor-1.json', 'final-record.json'}



@pytest.mark.parametrize('damage', ['absent', 'missing-results', 'failed-results'])
def test_review_seat_self_checks_refuse_absent_or_failed_current_parent_results(contract_env, damage):
    from ravel.workflow import role_registry
    env = contract_env
    card = role_registry.load('integrity-auditor')
    runnable, _ = graph.validate.validator_ids(card)
    assert runnable
    parent = make_step('s1')
    acting = make_step('s1.review.integrity-auditor', kind='review', role=card['id'])
    seat_key = 'seat:integrity-auditor:1'
    state = {'step': parent, 'acting': acting, 'branch': 'worker',
             'seat': {'key': seat_key, 'purpose': 'review', 'role': card['id']},
             'context': context(env.store, env.run_dir, 'a' * 64, attempt=2),
             'preflight': {'outputs': [{'path': 'outputs/review.json', 'required': True}]}}
    receipt = {'credited_outputs': [{'path': 'outputs/review.json'}]}
    seat_validation = env.store.append('step-validation', {
        'step_id': acting['id'], 'seat': seat_key, 'attempt': 2, 'errors': []})
    producer_validation = None
    if damage != 'absent':
        results = ([{'check_id': check, 'status': 'failed', 'reason': 'planted-parent-failure'}
                    for check in runnable] if damage == 'failed-results' else [])
        producer_validation = env.store.append('step-validation', {
            'step_id': parent['id'], 'seat': None, 'attempt': 2,
            'report': {'passed': False, 'results': results, 'reviewer_items': []}})
    rows = graph._seat_validate_rows(state, env.store, card, receipt, {}, seat_validation)
    assert rows['CF05']['status'] == 'satisfied'
    assert rows['I09']['status'] == 'violated'
    reason = {'absent': 'producer_checks_missing', 'missing-results': 'reviewer_self_checks_not_performed',
              'failed-results': 'reviewer_self_checks_failed'}[damage]
    assert rows['I09']['evidence']['reason'] == reason
    if producer_validation:
        assert rows['I09']['evidence']['validator'] == producer_validation
    else:
        assert rows['I09']['evidence']['seat_validation'] == seat_validation
    for index, check in enumerate(card['must_check']):
        row = rows[f"ROLE-{card['id']}-must_check-{index}"]
        assert row['status'] == 'violated' and row['evidence']['reason']
        if producer_validation:
            assert row['evidence']['validator'] == producer_validation
