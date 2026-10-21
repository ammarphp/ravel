"""Prepared scientific bindings retain exact declared source/output scope before approval."""
from copy import deepcopy
from importlib import import_module

import pytest

from ravel.controller.routes.analysis import common, execution
from ravel.controller.routes import compiler
from ravel.controller.routes.study import evidence


def bind(plan, source):
    return import_module('ravel.controller.routes.analysis.scientific').bind(plan, source)


@pytest.fixture
def scientific_plan():
    def step(identifier, *, phase='execute', parents=(), inputs=(), outputs=()):
        return {'id': identifier, 'kind': 'operate', 'rung': 'none', 'depends_on': list(parents),
                'inputs': [{'artifact': value} for value in inputs],
                'outputs': [{'path': path, 'required': True} for path in outputs],
                'parameters': {'phase': phase}}
    steps = [step('prepare', phase='prepare', outputs=['outputs/expected.json', 'outputs/recipe.json']),
             step('upstream', parents=['prepare'], outputs=['outputs/previous.json']),
             step('run.full', parents=['upstream'], inputs=['inputs/preserved.json'], outputs=['outputs/result.json'])]
    plan = {'schema_version': 1, 'steps': steps, 'route': {'id': 'analysis'}}
    plan['sha256'] = common.digest(plan)
    assert compiler.check_dag(steps) == []
    return plan


def source(row='P05', expected='prepare:outputs/expected.json', observed='run.full:outputs/result.json'):
    binding = {'row': row, 'expected': expected, 'validator': 'descriptor-continuity'}
    if observed is not None:
        binding['observed'] = observed
    return {'scientific_bindings': {'run.full': [binding]}}


def test_bind_scientific_adds_only_prepare_source_dependency_and_input_and_rehashes(scientific_plan):
    original = deepcopy(scientific_plan)
    declared = source()
    declared_original = deepcopy(declared)
    changed = bind(scientific_plan, declared)
    target = changed['steps'][-1]
    assert target['depends_on'] == ['upstream', 'prepare']
    assert target['inputs'] == [{'artifact': 'inputs/preserved.json'}, {'artifact': 'prepare:outputs/expected.json'}]
    assert evidence.requirements(target) == declared['scientific_bindings']['run.full']
    assert changed['sha256'] == common.digest({key: value for key, value in changed.items() if key != 'sha256'})
    assert changed['sha256'] != original['sha256']
    assert compiler.check_dag(changed['steps']) == []
    assert changed['steps'][:2] == original['steps'][:2]
    assert scientific_plan == original and declared == declared_original


def test_bind_scientific_preserves_existing_pinned_input_without_duplicates(scientific_plan):
    target = scientific_plan['steps'][-1]
    pinned = {'artifact': 'prepare:outputs/expected.json', 'sha256': 'a' * 64, 'required': True}
    target['inputs'].append(pinned)
    target['depends_on'].append('prepare')
    declared = source()
    declared['scientific_bindings']['run.full'].append({**declared['scientific_bindings']['run.full'][0], 'row': 'E07'})
    changed = bind(scientific_plan, declared)
    assert changed['steps'][-1]['inputs'] == target['inputs']
    assert changed['steps'][-1]['depends_on'] == target['depends_on']
    assert [row['row'] for row in evidence.requirements(changed['steps'][-1])] == ['P05', 'E07']


def test_bind_scientific_can_use_already_declared_nonprepare_ancestor_input(scientific_plan):
    scientific_plan['steps'][-1]['inputs'].append({'artifact': 'upstream:outputs/previous.json'})
    changed = bind(scientific_plan, source(expected='upstream:outputs/previous.json'))
    assert changed['steps'][-1]['inputs'] == scientific_plan['steps'][-1]['inputs']
    assert changed['steps'][-1]['depends_on'] == ['upstream']


def test_bind_scientific_retains_e09_dispatch_recipe_without_inventing_observed(scientific_plan):
    changed = bind(scientific_plan, source('E09', 'prepare:outputs/recipe.json', None))
    binding, = evidence.requirements(changed['steps'][-1])
    assert 'observed' not in binding and binding['row'] == 'E09'


def test_launch_binding_also_pins_scientific_requirements(scientific_plan):
    declared = {**source(), 'launches': {'run.full': {'argv': ['inert-command']}}}
    changed = execution.bind_launches(scientific_plan, declared)
    target = changed['steps'][-1]
    assert target['parameters']['launch'] == {'argv': ['inert-command']}
    assert evidence.requirements(target) == declared['scientific_bindings']['run.full']
    assert changed['sha256'] == common.digest({key: value for key, value in changed.items() if key != 'sha256'})


@pytest.mark.parametrize('field', ['entry_ids', 'review'])
def test_source_cannot_supply_controller_ledger_or_review_credit(scientific_plan, field):
    declared = source()
    declared['scientific_bindings']['run.full'][0][field] = [] if field == 'entry_ids' else {}
    with pytest.raises(ValueError):
        bind(scientific_plan, declared)


@pytest.mark.parametrize('identifier', ['unknown', 'prepare', 'run', 'run.full.point'])
def test_scientific_bindings_require_exact_nonprepare_target(scientific_plan, identifier):
    declared = {'scientific_bindings': {identifier: source()['scientific_bindings']['run.full']}}
    with pytest.raises(ValueError):
        bind(scientific_plan, declared)


@pytest.mark.parametrize('observed', ['outputs/result.json', '/tmp/result.json', 'upstream:outputs/previous.json',
                                     'run.full:outputs/missing.json', 'run.full:../escape.json', None])
def test_observed_is_exact_self_declared_output(scientific_plan, observed):
    with pytest.raises(ValueError):
        bind(scientific_plan, source(observed=observed))


@pytest.mark.parametrize('expected', ['inputs/arbitrary.json', '/tmp/reference.json', 'unknown:outputs/ref.json',
                                     'prepare:outputs/missing.json', 'run.full:outputs/result.json',
                                     'prepare:../escape.json', 'upstream:outputs/previous.json'])
def test_expected_reference_cannot_expand_nonprepare_or_undeclared_scope(scientific_plan, expected):
    with pytest.raises(ValueError):
        bind(scientific_plan, source(expected=expected))


def test_expected_input_also_requires_actual_ancestor_dependency(scientific_plan):
    scientific_plan['steps'][-1]['depends_on'] = []
    scientific_plan['steps'][-1]['inputs'].append({'artifact': 'upstream:outputs/previous.json'})
    with pytest.raises(ValueError):
        bind(scientific_plan, source(expected='upstream:outputs/previous.json'))


@pytest.mark.parametrize('existing', [False, True])
def test_known_scientific_row_cannot_be_duplicated(scientific_plan, existing):
    declared = source()
    if existing:
        scientific_plan['steps'][-1]['parameters']['evidence_requirements'] = deepcopy(
            declared['scientific_bindings']['run.full'] * 2)
    else:
        declared['scientific_bindings']['run.full'] *= 2
    with pytest.raises(ValueError):
        bind(scientific_plan, declared)


@pytest.mark.parametrize('binding', [None, [], {'row': 'unknown', 'expected': 'prepare:outputs/expected.json'},
                                    {'row': 'P05', 'expected': 'prepare:outputs/expected.json',
                                     'observed': 'run.full:outputs/result.json', 'foreign': True}])
def test_existing_requirements_schema_remains_authoritative(scientific_plan, binding):
    with pytest.raises(ValueError):
        bind(scientific_plan, {'scientific_bindings': {'run.full': [binding]}})


@pytest.mark.parametrize('bindings', [None, [], 'not-an-object'])
def test_scientific_binding_container_is_a_strict_object(scientific_plan, bindings):
    with pytest.raises(ValueError):
        bind(scientific_plan, {'scientific_bindings': bindings})


@pytest.mark.parametrize('bindings', [None, {}, 'not-a-list'])
def test_each_step_binding_collection_is_a_list(scientific_plan, bindings):
    with pytest.raises(ValueError):
        bind(scientific_plan, {'scientific_bindings': {'run.full': bindings}})


def test_prepare_dependency_cannot_introduce_cycle(scientific_plan):
    scientific_plan['steps'][0]['depends_on'] = ['run.full']
    with pytest.raises(ValueError):
        bind(scientific_plan, source())


def test_source_without_bindings_preserves_plan(scientific_plan):
    changed = bind(scientific_plan, {})
    assert changed == scientific_plan and changed is not scientific_plan



def test_repeated_launch_scientific_binding_preserves_exact_approved_plan(scientific_plan):
    declared = {**source(), 'launches': {'run.full': {'argv': ['inert-command']}}}
    first = execution.bind_launches(scientific_plan, declared)
    original = deepcopy(first)
    second = execution.bind_launches(first, declared)
    assert second == first == original and second is not first
    assert second['sha256'] == first['sha256']


def test_rebinding_cannot_replace_an_existing_scientific_row(scientific_plan):
    declared = source()
    first = bind(scientific_plan, declared)
    original = deepcopy(first)
    changed = deepcopy(declared)
    changed['scientific_bindings']['run.full'][0]['expected_fields'] = {'basis': '/other_basis'}
    with pytest.raises(ValueError):
        bind(first, changed)
    assert first == original


def collection_review(tmp_path, monkeypatch, damage=None):
    """Protected store records for the composite membership validator's unit boundary."""
    import hashlib
    import json
    from ravel.controller.store import RunStore
    from ravel.workflow import review_independence

    run = tmp_path / 'collection-run'
    store = RunStore.create(run, root=tmp_path / 'collection-store', run_id='collection-review-test')
    descriptor = {'spectrum': {'toy-state': 100}, 'invisible_states': []}
    pins = {}
    for artifact, producer in [('prepare:outputs/expected.json', 'prepare'), ('produce:outputs/result.json', 'produce')]:
        path = 'steps/' + artifact.replace(':', '/')
        target = run / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(descriptor, sort_keys=True))
        pin = {'artifact': artifact, 'step_id': producer, 'path': artifact.partition(':')[2],
               'destination': path, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
               'attempt': 2, 'status': 'accepted'}
        if damage == 'stale-observed-attempt' and producer == 'produce':
            pin['attempt'] = 1
        store.append('custody', pin)
        pins[producer] = pin
    binding = {'row': 'E08', 'expected': 'prepare:outputs/expected.json',
               'observed': 'produce:outputs/result.json', 'validator': 'descriptor-continuity'}
    step = {'id': 'produce', 'parameters': {'evidence_requirements': [binding]}}
    query = {'run': str(run.resolve()), 'role': 'physics-critic', 'subject_sha256': 'c' * 64,
             'receipt_sha256': 'd' * 64, 'output_sha256': 'e' * 64, 'packet_sha256': None}
    member = {'artifact': binding['observed'], 'sha256': pins['produce']['sha256']}
    review = {'id': 'produce.review.physics-critic', 'kind': 'review', 'operation': None,
              'role': 'physics-critic', 'parameters': {'seat_of': 'produce', 'purpose': 'review'},
              'inputs': [deepcopy(member)]}
    session = {'run_id': store.run_id, 'step': review['id'], 'attempt': 2, 'seat': 'seat:physics-critic:1',
               'session_id': 'observed-child-session', 'receipt_sha256': 'f' * 64,
               'step_spec': review, 'card': {'id': 'physics-critic'}, 'inputs': [deepcopy(member)]}
    seat = {'seat': session['seat'], 'role': 'physics-critic', 'status': 'completed', 'verdict': 'accept',
            'attempt': 2, 'session_id': session['session_id'], 'receipt_sha256': session['receipt_sha256'],
            'subject_sha256': query['subject_sha256'], 'query': deepcopy(query), 'credited': True}
    credit = {'step_id': 'produce', 'attempt': 2, 'credited': True, 'seats': [seat], 'own': None}
    if damage == 'wrong-parent':
        credit['step_id'] = 'other-producer'
    elif damage == 'wrong-credit-attempt':
        credit['attempt'] = 1
    elif damage == 'wrong-artifact':
        review['inputs'][0]['artifact'] = 'produce:outputs/another.json'
    elif damage == 'wrong-sha':
        review['inputs'][0]['sha256'] = '0' * 64
    elif damage == 'wrong-session-input':
        session['inputs'][0]['sha256'] = '0' * 64
    elif damage == 'wrong-role':
        review['role'] = 'figure-critic'
    elif damage == 'wrong-card':
        session['card']['id'] = 'figure-critic'
    elif damage == 'wrong-query':
        seat['query']['subject_sha256'] = '0' * 64
    elif damage == 'wrong-query-run':
        query['run'] = str(tmp_path / 'unrelated-run')
    elif damage == 'wrong-session-run':
        session['run_id'] = 'unrelated-run'
    elif damage == 'wrong-session-attempt':
        session['attempt'] = 1
    elif damage == 'wrong-receipt':
        session['receipt_sha256'] = '0' * 64
    elif damage == 'wrong-seat':
        session['seat'] = 'seat:figure-critic:1'
    elif damage == 'wrong-review-parent':
        review['parameters']['seat_of'] = 'unrelated-producer'
    elif damage == 'executing-review':
        review['operation'] = 'native-operation'
    elif damage == 'revise':
        seat['verdict'] = 'revise'
    elif damage == 'uncredited':
        seat['credited'] = False
    elif damage == 'duplicate-seat':
        credit['seats'].append(deepcopy(seat))
    session_id = store.append('worker-session', session)
    if damage == 'duplicate-session':
        store.append('worker-session', session)
    credit_id = store.append('step-credit', credit)
    if damage == 'latest-refusal':
        store.append('step-credit', {**credit, 'credited': False})
    if damage == 'duplicate-credit-envelope':
        original_scan = store.scan
        def duplicate_scan(kind):
            entries = original_scan(kind)
            return entries + [deepcopy(entries[-1])] if kind == 'step-credit' else entries
        monkeypatch.setattr(store, 'scan', duplicate_scan)
    calls = []
    def decide(actual):
        calls.append(deepcopy(actual))
        assert actual == query  # authentic query is forwarded intact, including receipt convention
        return {'independent': damage != 'independence-revoked', 'label': 'unit-boundary'}
    monkeypatch.setattr(review_independence, 'decide', decide)
    context = {'store': store, 'run_dir': str(run), 'attempt': 2, 'review_queries': {'E08': query}}
    return store, step, context, query, credit_id, session_id, pins['produce'], calls


def test_collection_review_revalidates_exact_query_and_records_protected_member_scope(tmp_path, monkeypatch):
    store, step, context, query, credit_id, session_id, actual_pin, calls = collection_review(tmp_path, monkeypatch)
    assert query['subject_sha256'] != actual_pin['sha256']
    assert evidence.check(store, step, context, phase='review') == []
    record = store.scan('study-evidence')[-1]['record']
    assert record['status'] == 'satisfied'
    assert record['credit']['membership'] == {
        'credit': credit_id, 'session': session_id, 'producer_step': 'produce', 'attempt': 2,
        'artifact': 'produce:outputs/result.json', 'sha256': actual_pin['sha256'],
        'review_step': 'produce.review.physics-critic', 'seat': 'seat:physics-critic:1'}
    assert calls == [query]


@pytest.mark.parametrize('damage', [
    'wrong-parent', 'wrong-credit-attempt', 'stale-observed-attempt', 'wrong-artifact', 'wrong-sha',
    'wrong-session-input', 'wrong-role', 'wrong-card', 'wrong-query', 'wrong-query-run', 'wrong-session-run',
    'wrong-session-attempt', 'wrong-receipt', 'wrong-seat', 'wrong-review-parent', 'executing-review',
    'revise', 'uncredited', 'duplicate-seat', 'duplicate-session', 'duplicate-credit-envelope', 'latest-refusal',
    'independence-revoked'])
def test_collection_review_refuses_stale_unrelated_ambiguous_or_unaccepted_membership(tmp_path, monkeypatch, damage):
    store, step, context, _, _, _, _, calls = collection_review(tmp_path, monkeypatch, damage)
    errors = evidence.check(store, step, context, phase='review')
    assert errors and errors[0]['row'] == 'E08'
    record = store.scan('study-evidence')[-1]['record']
    assert record['status'] == 'violated'
    assert 'exact executed evidence digest or credited collection membership' in record['findings'][0]
    assert len(calls) == (1 if damage == 'independence-revoked' else 0)


def test_runtime_discovers_only_latest_accepting_current_attempt_query(tmp_path, monkeypatch):
    from ravel.controller.routes.study import runtime
    store, step, context, query, _, _, _, calls = collection_review(tmp_path, monkeypatch)
    assert runtime.scientific_review_queries(store, step, attempt=2) == {'E08': query}
    assert runtime.scientific_review_queries(store, step, attempt=1) == {}
    latest = store.scan('step-credit')[-1]['record']
    store.append('step-credit', {**latest, 'credited': False})
    assert runtime.scientific_review_queries(store, step, attempt=2) == {}
    assert calls == []  # discovery supplies a query; only evidence validation grants credit



@pytest.mark.parametrize('reverse', [False, True])
def test_runtime_selects_canonical_role_for_two_reviews_of_same_collection(tmp_path, monkeypatch, reverse):
    from ravel.controller.routes.study import runtime
    store, step, _, _, _, _, _, calls = collection_review(tmp_path, monkeypatch)
    latest = store.scan('step-credit')[-1]['record']
    second = deepcopy(latest['seats'][0])
    second.update(role='figure-critic', seat='seat:figure-critic:1', session_id='observed-figure-session',
                  receipt_sha256='3' * 64)
    second['query'].update(role='figure-critic', receipt_sha256='1' * 64, output_sha256='2' * 64)
    session = store.scan('worker-session')[-1]['record']
    session.update(seat=second['seat'], session_id=second['session_id'], receipt_sha256=second['receipt_sha256'])
    session['step_spec'].update(id='produce.review.figure-critic', role='figure-critic')
    session.update(step=session['step_spec']['id'], card={'id': 'figure-critic'})
    store.append('worker-session', session)
    latest['seats'].append(second)
    if reverse:
        latest['seats'].reverse()
    store.append('step-credit', latest)
    assert runtime.scientific_review_queries(store, step, attempt=2) == {'E08': second['query']}
    assert calls == []


@pytest.mark.parametrize('damage', ['different-collection', 'duplicate-seat', 'subject-mismatch', 'attempt-mismatch'])
def test_runtime_refuses_ambiguous_or_mismatched_collection_queries(tmp_path, monkeypatch, damage):
    from ravel.controller.routes.study import runtime
    store, step, _, _, _, _, _, calls = collection_review(tmp_path, monkeypatch)
    latest = store.scan('step-credit')[-1]['record']
    second = deepcopy(latest['seats'][0])
    if damage != 'duplicate-seat':
        second.update(role='figure-critic', seat='seat:figure-critic:1')
        second['query']['role'] = 'figure-critic'
    if damage == 'different-collection':
        second['subject_sha256'] = second['query']['subject_sha256'] = '0' * 64
    elif damage == 'subject-mismatch':
        second['subject_sha256'] = '0' * 64
    elif damage == 'attempt-mismatch':
        second['attempt'] = 1
    latest['seats'].append(second)
    store.append('step-credit', latest)
    assert runtime.scientific_review_queries(store, step, attempt=2) == {}
    assert calls == []
