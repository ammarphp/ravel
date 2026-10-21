"""Operation admission by signature and executor role (TOOL-*, EXEC-*, R13), and the approved-plan binding (T03)."""
from __future__ import annotations

from copy import deepcopy
import json
import sys

import pytest

from ravel.controller.step import operations
from ravel.controller.step.services import StepHold
from ravel.workflow import production_executor

from test_p04_support import FakeStore, install_plan, make_step

SIGNATURES = operations.signatures()
EXECUTORS = production_executor.executors()


def _set(document, pointer, value):
    parts = pointer.lstrip('/').split('/')
    for part in parts[:-1]:
        document = document.setdefault(part, {})
        if type(document) is not dict:
            return
    document[parts[-1]] = value


def _conforming(name, signature):
    """A step the signature admits: declared artifact kinds, effects, a resolved ceiling and its implementation."""
    produced = [slot['kind'] for slot in signature['produces']]
    outputs = tuple((f'outputs/{index}.out', kind) for index, kind in enumerate(produced[:2]))
    task = {}
    cost = None
    for field in signature['critical_fields']:
        _set(task, field, 'approved')
    pointer = signature['cost'].get('ceiling_pointer')
    if pointer:
        _set(task, pointer, 10)
        cost = {'unit': signature['cost']['unit'], 'amount': 5}
    parameters = {'task': task, 'effects': list(signature['effects'])}
    if cost:
        parameters['cost'] = cost
    implementation = signature['implementation']
    if implementation['kind'] == 'command' and implementation.get('module'):
        parameters['launch'] = {'argv': [sys.executable, '-m', implementation['module']]}
    return make_step('s1', kind='operate', role=EXECUTORS['operations'].get(name), operation=name, outputs=outputs,
                     budget={'wall_seconds': 10 ** 6}, parameters=parameters)


@pytest.mark.parametrize('name', sorted(SIGNATURES), ids=[f'TOOL-{n}' for n in sorted(SIGNATURES)])
def test_TOOL_an_operation_is_admitted_only_within_its_signature(name):
    signature = SIGNATURES[name]
    step = _conforming(name, signature)
    assert operations.admission_errors(step, approved=step, signature=signature) == []
    undeclared = deepcopy(step)
    undeclared['outputs'].append({'path': 'outputs/extra.out', 'kind': 'undeclared-fixture-kind', 'required': True})
    assert [e['code'] for e in operations.admission_errors(undeclared, signature=signature)] == [
        'operation_artifact_undeclared']
    effect = deepcopy(step)
    effect['parameters']['effects'] = list(signature['effects']) + ['undeclared_fixture_effect']
    assert [e['code'] for e in operations.admission_errors(effect, signature=signature)] == [
        'operation_effect_undeclared']
    if signature['consumes']:
        foreign = [{'artifact': 's0:outputs/x', 'kind': 'undeclared-fixture-kind'}]
        assert operations.admission_errors(step, inputs_custody=foreign, signature=signature)[0]['code'] == \
            'operation_artifact_undeclared'
    if signature['cost'].get('ceiling_pointer'):
        above = deepcopy(step)
        above['parameters']['cost']['amount'] = 11
        assert [e['code'] for e in operations.admission_errors(above, signature=signature)] == [
            'operation_cost_above_ceiling']
        unbounded = deepcopy(step)
        unbounded['parameters']['task'] = {}
        assert 'operation_ceiling_unresolved' in [e['code'] for e in operations.admission_errors(
            unbounded, signature=signature)]
    for field in signature['critical_fields']:
        changed = deepcopy(step)
        _set(changed['parameters']['task'], field, 'changed after approval')
        assert 'operation_critical_field_changed' in [e['code'] for e in operations.admission_errors(
            changed, approved=step, signature=signature)]
    implementation = signature['implementation']
    if implementation['kind'] == 'command' and implementation.get('module'):
        other = deepcopy(step)
        other['parameters']['launch'] = {'argv': [sys.executable, '-c', 'pass']}
        assert [e['code'] for e in operations.admission_errors(other, signature=signature)] == [
            'operation_implementation_mismatch']


@pytest.mark.parametrize('name', sorted(EXECUTORS['operations']), ids=[f'EXEC-{n}' for n in sorted(EXECUTORS['operations'])])
def test_EXEC_a_compute_operation_runs_only_through_its_production_role(name):
    from ravel.workflow.operation_check_policy import executor
    # An adopted workflow's declared products refine its registered default (``operation_check_policy.executor``).
    required = executor(name, {}, EXECUTORS['operations'][name])
    signature = SIGNATURES.get(name)
    step = make_step('s1', kind='operate', role=required, operation=name)
    assert operations.executor_errors(step, signature, EXECUTORS) == []
    other = next(role for role in sorted(set(EXECUTORS['operations'].values())) if role != required)
    for named in (other, None):
        wrong = dict(step, role=named)
        assert operations.executor_errors(wrong, signature, EXECUTORS) == [
            {'code': 'executor_role_mismatch', 'operation': name, 'required': required, 'named': named}]


def test_R13_a_compute_operation_without_a_registered_production_role_is_refused():
    name = next(n for n in sorted(EXECUTORS['operations']) if n in SIGNATURES)  # a release withholds some
    table = deepcopy(EXECUTORS)
    del table['operations'][name]
    errors = operations.executor_errors(make_step('s1', kind='operate', role='calculation', operation=name),
                                        SIGNATURES[name], table)
    assert errors == [{'code': 'executor_role_missing', 'operation': name}]
    assert operations.executor_errors(make_step('s1', kind='operate', operation='no-such-operation')) == [
        {'code': 'operation_unregistered', 'operation': 'no-such-operation'}]


def test_a_host_operation_needs_no_production_role():
    name = sorted(EXECUTORS['host_operations'])[0]
    assert operations.executor_errors(make_step('s1', kind='operate', role=None, operation=name)) == []


def _plan(tmp_path, steps):
    store = FakeStore(tmp_path / 'store')
    return store, install_plan(store, steps)


def test_T03_a_step_is_bound_to_the_exact_bytes_of_its_approved_plan(tmp_path):
    step = make_step('s1', parameters={'launch': {'argv': ['tool', '--points', '3']}})
    store, plan_sha = _plan(tmp_path, [step])
    approved, sha, binding = operations.plan_step(store, step, {'plan_sha256': plan_sha})
    assert approved == step and sha == plan_sha and binding == 'plan_step'
    changed = deepcopy(step)
    changed['parameters']['launch']['argv'][-1] = '4'
    with pytest.raises(StepHold) as refused:
        operations.plan_step(store, changed, {'plan_sha256': plan_sha})
    assert refused.value.reason == 'plan_step_changed'
    with pytest.raises(StepHold) as missing:
        operations.plan_step(store, make_step('s9'), {'plan_sha256': plan_sha})
    assert missing.value.reason == 'plan_step_missing'
    with pytest.raises(StepHold) as unbound:
        operations.plan_step(store, step, {'plan_sha256': '0' * 64})
    assert unbound.value.reason == 'plan_unbound'


def test_a_review_seat_the_controller_derives_is_bound_by_its_subject_plan(tmp_path):
    store, plan_sha = _plan(tmp_path, [make_step('s1')])
    seat = make_step('review:plan:plan-critic:0', kind='review', role='plan-critic',
                     parameters={'subject_plan_sha256': plan_sha, 'purpose': 'plan'})
    assert operations.plan_step(store, seat, {'plan_sha256': plan_sha})[2] == 'derived_review_seat'
    foreign = deepcopy(seat)
    foreign['parameters']['subject_plan_sha256'] = '1' * 64
    with pytest.raises(StepHold):
        operations.plan_step(store, foreign, {'plan_sha256': plan_sha})
    launching = deepcopy(seat)
    launching['parameters']['launch'] = {'argv': ['tool']}
    with pytest.raises(StepHold):
        operations.plan_step(store, launching, {'plan_sha256': plan_sha})


def test_the_launch_digest_binds_argv_environment_reads_and_outputs():
    step = make_step('s1', parameters={'launch': {'argv': ['tool'], 'env': {'A': '1'}, 'reads': ['inputs/x']}})
    base = operations.launch_digest(step)
    for change in ({'argv': ['tool', 'x']}, {'env': {'A': '2'}}, {'reads': []}):
        other = deepcopy(step)
        other['parameters']['launch'].update(change)
        assert operations.launch_digest(other) != base
    other = deepcopy(step)
    other['outputs'].append({'path': 'outputs/more.json', 'kind': 'result', 'required': True})
    assert operations.launch_digest(other) != base


@pytest.mark.parametrize('operation', ['lifecycle-routine-recast', 'analysis-lifecycle',
                                       'lifecycle-scan-aggregation', 'figure-comparison'])
def test_registered_analysis_task_uses_launch_branch_and_closed_allowlist(operation):
    from ravel.controller.step import spec
    signature = SIGNATURES[operation]
    policy = operations.ANALYSIS_LAUNCHES[operation]
    assert policy['implementation'] == signature['implementation']
    assert policy['role'] == EXECUTORS['operations'][operation]
    assert policy['argv'][:2] == ('python', '-m')
    step = _conforming(operation, signature)
    step['parameters'].pop('launch', None)
    assert spec.branch(step) == 'launch'
    # An operate step never falls back to a worker session: without a materialised launch it holds.
    step['operation'] = 'unregistered-operation'
    assert spec.branch(step) == 'launch'
    step['operation'] = operation
    step['parameters'].pop('task')
    assert spec.branch(step) == 'launch'


def test_task_only_author_steps_keep_the_worker_branch_and_operate_steps_take_the_launch_branch():
    from ravel.controller.step import spec
    assert spec.branch(make_step('a', kind='author', role='analysis-author', parameters={'task': {}})) == 'worker'
    assert spec.branch(make_step('a', kind='operate', operation='unregistered-operation',
                                 parameters={'task': {}})) == 'launch'


@pytest.fixture
def applied_plan(tmp_path, monkeypatch):
    from ravel.controller import engagement, graph as controller
    from ravel.controller.engagement import policy
    from test_p18_records import fakes
    monkeypatch.setattr(engagement, '_operator', lambda: {})
    # The fixture store carries no frozen operating mode record (no issuer home): decide reads none.
    from ravel.controller import authority
    monkeypatch.setattr(authority, 'frozen', lambda store, required=False: None)
    step = make_step('s1', inputs=[{'artifact': 'inputs/source.json'}],
                     parameters={'scope': {'quantity': 'supplied'}})
    store, pin = _plan(tmp_path, [step])
    plan = json.loads(store.get_blob(store.records('plan')[-1]['blob']))
    seat_plan = policy.seat_plan
    def with_instructions(*args, **kwargs):
        kwargs.setdefault('instructions', controller.service('instructions'))
        return seat_plan(*args, **kwargs)
    monkeypatch.setattr(policy, 'seat_plan', with_instructions)
    # The current catalogue lacks the check-in selectors; only instruction transport is inert.
    with controller.services(instructions=fakes.FakeInstructions):
        decision = engagement.decide(store, {'plan': plan})
        applied = engagement.apply(plan, decision)
        assert engagement.check_applied(applied, decision) == []
        assert applied['sha256'] == pin and applied != plan
        original = store.records('plan')[-1]
        store.append('plan', {**original, 'applied_blob': store.put_blob(json.dumps(applied).encode()),
                              'applied_sha256': applied['engagement']['applied_sha256']})
        yield store, plan, decision, applied


def test_t03_binding_accepts_only_a_valid_applied_view(applied_plan):
    from ravel.controller import engagement
    store, scientific, decision, applied = applied_plan
    ctx = {'plan_sha256': scientific['sha256'], 'plan': applied}
    approved, pin, binding = operations.plan_step(store, applied['steps'][0], ctx)
    assert approved == applied['steps'][0] and pin == scientific['sha256'] and binding == 'plan_step'
    assert operations.plan_step(store, applied['steps'][0], {'plan_sha256': pin})[0] == approved
    # Full byte identity still applies to the complete validated view, including policy fields.
    changed = deepcopy(applied['steps'][0])
    changed['parameters']['scope']['quantity'] = 'changed'
    with pytest.raises(StepHold) as refused:
        operations.plan_step(store, changed, ctx)
    assert refused.value.reason == 'plan_step_changed'
    # An applied plan may be the pinned blob itself; its scientific digest remains immutable.
    store.append('plan', {'plan_sha256': pin, 'blob': store.put_blob(json.dumps(applied).encode())})
    assert operations.plan_step(store, applied['steps'][0], {'plan_sha256': pin})[0] == approved
    assert engagement.check_applied(applied, decision) == []


@pytest.mark.parametrize('defect', ['operation', 'input', 'scope', 'seat', 'stale', 'view_digest'])
def test_t03_applied_view_refuses_scientific_or_engagement_changes(applied_plan, defect):
    from ravel.controller import engagement
    store, scientific, decision, applied = applied_plan
    changed = deepcopy(applied)
    if defect == 'operation':
        changed['steps'][0]['operation'] = 'changed-operation'
    elif defect == 'input':
        changed['steps'][0]['inputs'][0]['artifact'] = 'inputs/other.json'
    elif defect == 'scope':
        changed['steps'][0]['parameters']['scope']['quantity'] = 'changed'
    elif defect == 'seat':
        changed['steps'][0]['seats'].append({'seat': 'extra', 'role': 'plan-critic', 'kind': 'review'})
    elif defect == 'view_digest':
        changed['engagement']['applied_sha256'] = '0' * 64
    else:
        # A new, valid protected decision makes an otherwise byte-exact old view stale.
        engagement.append(store, engagement.DECISION,
            {key: value for key, value in decision.items() if key not in ('schema', 'sha256', 'record_id')})
    if defect not in ('view_digest', 'stale'):
        changed['engagement'].pop('applied_sha256')
        changed['engagement']['applied_sha256'] = engagement.digest(changed)
    with pytest.raises(StepHold) as refused:
        operations.plan_step(store, changed['steps'][0], {'plan_sha256': scientific['sha256'], 'plan': changed})
    assert refused.value.reason in ('plan_digest_mismatch', 'engagement_view_invalid')


def test_t03_scientific_blob_is_rehashed_and_extra_review_seats_refuse(applied_plan):
    store, scientific, decision, applied = applied_plan
    seat = make_step('extra-review', kind='review', role='baseline-producer',
        parameters={'subject_plan_sha256': scientific['sha256'], 'purpose': 'final'})
    with pytest.raises(StepHold) as refused:
        operations.plan_step(store, seat, {'plan_sha256': scientific['sha256'], 'plan': applied})
    assert refused.value.reason == 'engagement_view_invalid'
    changed = deepcopy(scientific)
    changed['parameters']['scope'] = 'changed'
    store.append('plan', {'plan_sha256': scientific['sha256'],
                          'blob': store.put_blob(json.dumps(changed).encode())})
    with pytest.raises(StepHold) as refused:
        operations.plan_step(store, scientific['steps'][0], {'plan_sha256': scientific['sha256']})
    assert refused.value.reason == 'plan_digest_mismatch'


def test_t03_projection_pin_and_declared_review_seat_are_checked(applied_plan):
    store, scientific, decision, applied = applied_plan
    ctx = {'plan_sha256': scientific['sha256']}
    seat = make_step('plan-review', kind='review', role='plan-critic',
        parameters={'subject_plan_sha256': scientific['sha256'], 'purpose': 'plan'})
    assert operations.plan_step(store, seat, ctx)[2] == 'derived_review_seat'
    with pytest.raises(StepHold) as refused:
        operations.plan_step(store, applied['steps'][0], {**ctx, 'applied_sha256': '0' * 64})
    assert refused.value.reason == 'engagement_view_invalid'
    record = store.records('plan')[-1]
    store.append('plan', {**record, 'applied_sha256': '0' * 64})
    with pytest.raises(StepHold) as refused:
        operations.plan_step(store, applied['steps'][0], ctx)
    assert refused.value.reason == 'engagement_view_invalid'


def test_t03_preflight_records_both_plan_identities(applied_plan, tmp_path, monkeypatch):
    from ravel.controller.step import graph
    from ravel.controller.step.services import bound
    store, scientific, decision, applied = applied_plan
    run = tmp_path / 'run'
    (run / 'inputs').mkdir(parents=True)
    (run / 'inputs/source.json').write_text('{}')
    step = deepcopy(applied['steps'][0])
    state = {'step': step, 'acting': step, 'branch': 'parent',
             'context': {'run_id': store.run_id, 'run_dir': str(run), 'plan_sha256': scientific['sha256'],
                         'plan': applied, 'attempt': 1}}
    monkeypatch.setattr(graph, '_running', lambda store: None)
    monkeypatch.setattr(graph, '_seat_roles', lambda *args: [])
    # The plan-bind rows have their own real-ledger controls; this case checks the T03 plan identities.
    monkeypatch.setattr(graph.plan_binding, 'unverified', lambda *args: [])
    from types import SimpleNamespace
    scope = {'step': step['id'], 'point': None, 'seat': 'producer', 'attempt': 1}
    context = {**scope, 'run_id': store.run_id, 'role': None, 'seat_kind': 'parent',
               'review_kind': None, 'step_kind': step['kind']}
    materialised = []
    def binding(actual):
        assert actual is state and actual['context']['attempt'] == 1
        assert actual['step']['id'] == actual['acting']['id'] == step['id']
        return 'dispatch', deepcopy(context), {'step': step['id']}, deepcopy(scope)
    def materialise(actual_store, stage, actual_context):
        assert actual_store is store and stage == 'dispatch' and actual_context == context
        materialised.append((stage, deepcopy(actual_context)))
        return ['T03@' + store.run_id + '/step=' + step['id']]
    original_module = graph.module
    monkeypatch.setattr(graph, '_ledger_binding', binding)
    monkeypatch.setattr(graph, 'module', lambda name: SimpleNamespace(materialise=materialise)
                        if name == 'ledger' else original_module(name))
    with bound(store):
        result = graph.preflight(state)
    assert materialised == [('dispatch', context)]
    evidence = result['evaluations']['T03']['evidence']
    assert evidence['scientific_sha256'] == scientific['sha256']
    assert evidence['applied_sha256'] == applied['engagement']['applied_sha256']
    assert evidence['decision_id'] == decision['record_id']
    assert result['evaluations']['T03']['status'] == 'satisfied'
