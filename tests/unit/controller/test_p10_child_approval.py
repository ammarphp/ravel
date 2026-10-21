"""The ordinary child's own approval is recorded by its controller, only from the verified CHECK-IN 1 decision.

A study child's plan and specification bytes are pinned in the approved controller plan. Its own approval
receipt (scripted assent, the approval mode its specification declares) is written only after the authority
service returned and verified the approve_plan decision, quotes that decision, never rewrites an existing
approval and is never written for a child that needs a human approval.
"""
import hashlib
import json
from pathlib import Path

import pytest

from ravel.controller.routes.study import runtime
from ravel.workflow import science
from test_p04_support import FakeStore
from test_p10_runtime import env  # noqa: F401  (the inert runtime fixture)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def unapproved(env, monkeypatch):  # noqa: F811
    store, step, context, state, child, *_ = env
    store = FakeStore(store.root / 'controller', run_dir=Path(context['run_dir']))
    from ravel.workflow import review_independence
    monkeypatch.setattr(review_independence, 'controller_store', lambda root: store if Path(root) == child else None)
    inputs = Path(context['run_dir']) / 'inputs'
    inputs.mkdir()
    plan_raw = b'{"nodes": [], "edges": [], "claims": [{"id": "value", "kind": "agreement"}]}'
    (inputs / 'request_plan.json').write_bytes(plan_raw)
    contract = {'prompt': 'Compute a supplied quantity.', 'task_mode': 'calculation',
                'run_id': 'parent-only', 'delegated': True, 'agent_layer_epoch': 2,
                'request_plan': {'path': 'inputs/request_plan.json',
                                 'sha256': hashlib.sha256(plan_raw).hexdigest()}}
    raw = json.dumps(contract).encode()
    (inputs / 'task_contract.json').write_bytes(raw)
    store.append('intake', {'contract_blob': store.put_blob(raw)})
    context['contract'] = contract
    spec = {'max_seconds': 10, 'max_attempts': 1, 'approval_mode': 'scripted_yes'}
    (child / science.SPEC).write_text(json.dumps(spec))
    step['parameters']['ordinary']['specification_sha256'] = _sha(child / science.SPEC)
    context['authority_subject'] = {'view': {'summary': 'existing ordinary check-in',
                                             'pins': {'plan_sha256': context['plan_sha256']}}}
    events = []

    def verify_plan(path, approved):
        present = (Path(path) / science.APPROVAL).exists()
        events.append(('verify_plan', approved, present))
        if approved and not present:
            # The child's own gate reads its approval file: an absent one is an OSError, as in the real gate.
            raise FileNotFoundError(2, 'No such file or directory', str(Path(path) / science.APPROVAL))
        return {'existing': 'verified plan'}

    def approve(path, quote, *, scripted=False):
        events.append(('approve', quote, scripted, [row[0] for row in state['verified']]))
        target = Path(path) / science.APPROVAL
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({'quote': quote}))

    monkeypatch.setattr(science, 'verify_plan', verify_plan)
    monkeypatch.setattr(science, 'approve', approve)
    return store, step, context, state, child, events


def test_preflight_approves_a_scripted_child_only_after_the_verified_decision(unapproved):
    store, step, context, state, child, events = unapproved
    admitted = runtime.preflight(store, step, context)
    assert admitted['admission_id']
    assert events[:2] == [('verify_plan', True, False), ('verify_plan', False, False)], \
        'an unapproved child is refused by its own gate, then its plan is checked before any authority'
    approvals = [event for event in events if event[0] == 'approve']
    assert len(approvals) == 1
    _, quote, scripted, verified = approvals[0]
    assert verified == ['actual-authority'], 'the decision was verified before the child approval'
    assert scripted is True and 'actual-authority' in quote and context['plan_sha256'] in quote
    assert step['parameters']['ordinary']['plan_sha256'] in quote
    assert events[-1] == ('verify_plan', True, True)
    assert state['verified'] == [('actual-authority', 'approve_plan', {'plan_sha256': context['plan_sha256']})]
    rows = [row['record'] for row in store.scan('study-child-approval')]
    assert len(rows) == 1 and rows[0]['decision'] == 'actual-authority'
    assert rows[0]['approval_sha256'] == _sha(child / science.APPROVAL)
    assert 'machine' in rows[0]['authority'] and 'human' not in rows[0]['authority']


def test_child_approval_records_exact_derived_contract_and_review_population(unapproved):
    from ravel.workflow import review_points
    from ravel.workflow.graphs import review
    from ravel.controller.step import graph
    from ravel.controller.step.services import StepHold
    from test_review_subgraph_budget import review_step
    store, step, context, state, child, events = unapproved
    with pytest.raises(StepHold) as refused:
        graph._amounts(review_step(), None, 'subgraph', subgraph_root=child)
    assert refused.value.reason == 'subgraph_budget_unavailable'
    runtime.preflight(store, step, context)
    expected = {k: v for k, v in context['contract'].items()
                if k not in {'run_id', 'autonomy', 'delegated', 'delegation'}}
    raw = (child / 'inputs/task_contract.json').read_bytes()
    assert json.loads(raw) == expected
    assert (child / 'inputs/request_plan.json').read_bytes() == (
        Path(context['run_dir']) / 'inputs/request_plan.json').read_bytes()
    binding = store.scan('study-child-contract')[0]['record']
    assert store.get_blob(binding['files']['inputs/task_contract.json']) == raw
    assert binding['decision'] == 'actual-authority'
    assert binding['child_plan_sha256'] == step['parameters']['ordinary']['plan_sha256']
    assert binding['child_specification_sha256'] == step['parameters']['ordinary']['specification_sha256']
    assert store.scan('study-child-approval')[0]['record']['contract_record_id'] == store.scan('study-child-contract')[0]['id']
    assert science._research_contract_paths(child) == [
        str(child / 'inputs/task_contract.json'), str(child / 'inputs/request_plan.json')]
    facts = review_points._facts(child)
    points = review_points.derive(facts)
    assert {p['id'] for p in points if p['when']['at'] == 'checkin2:value'} == {
        'RP4:value:physics-critic', 'RP4:value:skeptical-verifier', 'RP4:value:physics-decider', 'RP7:value'}
    assert not [p for p in points if p['when']['at'] == 'checkin2']
    assert review.reservation_budget(child, {'at': 'checkin2', 'attempt': 1}) == {
        'wall_seconds': 86400, 'model_calls': 1440, 'children': 24}
    assert graph._amounts(review_step(), None, 'subgraph', subgraph_root=child)['model_calls'] == 1440


@pytest.mark.parametrize('tamper', ['contract', 'request_plan', 'unrecorded', 'link'])
def test_child_review_refuses_changed_or_unrecorded_contract(unapproved, tamper):
    from ravel.controller.step import graph
    from ravel.controller.step.services import StepHold
    from test_review_subgraph_budget import review_step
    store, step, context, state, child, events = unapproved
    if tamper == 'unrecorded':
        (child / 'inputs/task_contract.json').write_text('{"agent_layer_epoch": 2}')
        with pytest.raises(runtime.StudyHold, match='contract'):
            runtime.preflight(store, step, context)
        assert not (child / science.APPROVAL).exists()
        assert store.scan('study-child-approval') == []
        return
    runtime.preflight(store, step, context)
    path = child / ('inputs/request_plan.json' if tamper == 'request_plan' else 'inputs/task_contract.json')
    if tamper == 'link':
        raw = path.read_bytes()
        path.unlink()
        target = child.parent / 'same-bytes.json'
        target.write_bytes(raw)
        path.symlink_to(target)
    elif tamper == 'contract':
        document = json.loads(path.read_bytes())
        document['prompt'] = 'Changed request.'
        path.write_text(json.dumps(document))
    else:
        path.write_text('{"nodes": [], "edges": [], "claims": []}')
    with pytest.raises(StepHold) as refused:
        graph._amounts(review_step(), None, 'subgraph', subgraph_root=child)
    assert refused.value.reason == 'subgraph_budget_unavailable'


@pytest.mark.parametrize('refusal', ['pending', 'negative', 'unverified'])
def test_no_child_approval_without_an_authorizing_verified_decision(unapproved, refusal):
    store, step, context, state, child, events = unapproved
    if refusal == 'pending':
        state['decision'] = {'pending': 'operator answer outstanding'}
        match = 'ordinary child authority is pending'
    elif refusal == 'negative':
        state['decision'] = {'id': 'actual-authority', 'decision': 'reject', 'authorizes_effects': False}
        match = 'ordinary child authority is pending'
    else:
        state['verification_refused'] = True
        match = 'authority attestation refused'
    with pytest.raises((runtime.StudyHold, ValueError), match=match):
        runtime.preflight(store, step, context)
    assert not [event for event in events if event[0] == 'approve']
    assert not (child / science.APPROVAL).exists() and store.scan('study-child-approval') == []
    assert state['launches'] == []


def test_a_child_that_needs_human_approval_is_held_not_approved(unapproved):
    store, step, context, state, child, events = unapproved
    spec = json.loads((child / science.SPEC).read_text())
    spec['approval_mode'] = 'expert'
    (child / science.SPEC).write_text(json.dumps(spec))
    step['parameters']['ordinary']['specification_sha256'] = _sha(child / science.SPEC)
    with pytest.raises(runtime.StudyHold, match='needs its own approval'):
        runtime.preflight(store, step, context)
    assert not [event for event in events if event[0] == 'approve'] and not (child / science.APPROVAL).exists()


def test_an_existing_child_approval_is_verified_as_it_stands(unapproved):
    store, step, context, state, child, events = unapproved
    existing = child / science.APPROVAL
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text('{"existing": "approval"}')
    before = existing.read_bytes()
    runtime.preflight(store, step, context)
    assert not [event for event in events if event[0] == 'approve'] and existing.read_bytes() == before
    assert store.scan('study-child-approval') == []
    assert events[-1] == ('verify_plan', True, True)


def test_the_approval_writer_refuses_an_unverified_shape_and_leaves_scoped_children_alone(unapproved):
    store, step, context, state, child, events = unapproved
    ordinary = step['parameters']['ordinary']
    for decision in ({'id': 'x', 'decision': 'approve'}, {'decision': 'approve', 'authorizes_effects': True},
                     {'id': 'x', 'decision': 'answer', 'authorizes_effects': True}):
        with pytest.raises(runtime.StudyHold, match='verified CHECK-IN 1 decision'):
            runtime.approve_ordinary_child(store, step, child, ordinary, decision, context)
    assert runtime.approve_ordinary_child(store, step, child, {**ordinary, 'kind': 'scoped'},
                                          {'id': 'x', 'decision': 'approve', 'authorizes_effects': True}, context) is None
    assert not [event for event in events if event[0] == 'approve']


def test_real_science_approval_binds_controller_child_inputs_and_retained_bytes(tmp_path, monkeypatch):
    from ravel.workflow import execution, launch_authorization, physics_review, review_independence
    from ravel.controller.routes.study import child_contract
    from ravel.workflow.state_io import atomic_json
    from method_decision_fixture import admit_method
    from test_science_review_envelope import specification, token
    for key in execution.RUNTIME_ENVIRONMENT_KEYS:
        monkeypatch.delenv(key, raising=False)
    parent = tmp_path / 'parent'
    (parent / 'inputs').mkdir(parents=True)
    child = parent / 'children' / 'ordinary'
    source = tmp_path / 'spec.json'
    atomic_json(source, specification(tmp_path))
    science.plan(child, source)
    admit_method(child)
    raw = b'{"nodes": [], "edges": [], "claims": [{"id": "value", "kind": "agreement"}]}'
    (parent / 'inputs/request_plan.json').write_bytes(raw)
    contract = {'prompt': 'Compute a supplied quantity.', 'agent_layer_epoch': 2,
                'request_plan': {'path': 'inputs/request_plan.json', 'sha256': hashlib.sha256(raw).hexdigest()}}
    atomic_json(parent / 'inputs/task_contract.json', contract)
    store = FakeStore(tmp_path / 'store', run_dir=parent)
    store.append('intake', {'contract_blob': store.put_blob((parent / 'inputs/task_contract.json').read_bytes())})
    monkeypatch.setattr(review_independence, 'controller_store', lambda root: store if Path(root) == child else None)
    ordinary = {'kind': 'science', 'child_rundir': 'children/ordinary',
                'plan_sha256': _sha(child / science.PLAN), 'specification_sha256': _sha(child / science.SPEC)}
    runtime.approve_ordinary_child(store, {'id': 'operate'}, child, ordinary,
                                  {'id': 'verified-decision', 'decision': 'approve', 'authorizes_effects': True},
                                  {'run_dir': str(parent), 'plan_sha256': 'a' * 64, 'contract': contract})
    assert science.verify_approval_envelope(child) == []
    assert set(science._research_contract_paths(child)) <= set(science.approval_input_paths(child))
    token(child)
    proposal = science.verify_plan(child, approved=True)
    stage, binding, seconds = science._selected(child, proposal)
    context = {'kind': 'science-stage', 'stage': 'science', 'review_action': 'bulk', 'max_seconds': seconds,
               'events': 0, 'plan_sha256': execution.file_hash(child / science.PLAN),
               'stage_spec': physics_review._stage_spec(child, {**stage, 'inputs': binding['inputs']})}
    with pytest.raises(ValueError, match='initial science attempt cannot run after a review cycle has opened'):
        launch_authorization._capture(child, 'science', command=stage['command'], context=context)
    sources = {path: Path(path).read_bytes() for path in science.approval_input_paths(child)}
    assert child_contract.paths(child, sources=sources) == science._research_contract_paths(child)
    path = str(child / 'inputs/task_contract.json')
    sources[path] = sources[path].replace(b'supplied quantity', b'changed quantity')
    with pytest.raises(ValueError, match='retained child contract input differs'):
        child_contract.paths(child, sources=sources)


def test_compute_child_keeps_parent_approval_bounds_and_reserved_resources(unapproved, monkeypatch):
    from copy import deepcopy
    from ravel.controller import authority
    from ravel.controller.routes.compiler import plan_sha256
    store, step, context, state, child, _ = unapproved
    step['rung'] = 'smoke'
    step['kind'] = 'operate'
    reserved = {'wall_seconds': 2, 'model_calls': 0, 'tokens': 0, 'core_hours': 0.1,
                'events': 0, 'children': 1}
    context['reservation'] = {'amounts': deepcopy(reserved)}
    plan = {'steps': [deepcopy(step), {'id': 'continued', 'kind': 'compose', 'rung': 'full',
                                      'budget': {'wall_seconds': 3}}]}
    plan['sha256'] = plan_sha256(plan)
    context['plan_sha256'] = plan['sha256']
    context['authority_subject']['view']['pins']['plan_sha256'] = plan['sha256']
    store.append('plan', {'plan_sha256': plan['sha256'],
                         'blob': store.put_blob(json.dumps(plan).encode())})
    requested = authority.request

    def request(store, kind, subject, bounds):
        result = requested(store, kind, subject, bounds)
        state['decision']['bounds'] = deepcopy(bounds)
        return {**result, 'bounds': deepcopy(bounds)}

    effects = []

    def authorize(store, effect):
        effects.append(deepcopy(effect))
        assert effect['budget'] == reserved
        assert effect['rung'] == 'smoke' and effect['requires_go'] is True
        return {'approve_plan': 'actual-authority', 'go': None}

    monkeypatch.setattr(authority, 'request', request)
    monkeypatch.setattr(authority, 'authorize_effect', authorize, raising=False)
    admitted = runtime.preflight(store, step, context)
    assert admitted['admission_id'] and effects
    bounds = state['requests'][-1][2]
    assert bounds['rung'] == 'full' and bounds['budget']['wall_seconds'] == 5
    assert set(bounds['stages']) >= {'calculation', 'compose'}
    binding = json.loads((child / 'inputs/controller-compute-approval.json').read_text())
    assert binding['required_plan'] == 'smoke'
