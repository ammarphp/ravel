"""Bounded sub-question custody, strict derivation and qualified completion."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from p11_fakes import FakeRunStore
from test_langgraph_research_orchestration import open_fixture
from ravel.controller.step import custody
from ravel.workflow import research_controller as bridge, research_coordinator_decisions as decisions
from ravel.workflow import research_cycle as cycle, state_io


@pytest.fixture
def bounded(tmp_path):
    request, _, _, _ = open_fixture(tmp_path / 'run')
    parent = decisions.request(request)['parent_contract']
    run = tmp_path / 'run'
    store = FakeRunStore('bounded-step', root=tmp_path / 'protected')
    blobs = {}
    def put(raw):
        key = hashlib.sha256(raw).hexdigest()
        blobs[key] = raw
        return key
    store.get_blob = blobs.__getitem__
    store.put_blob = put
    raw = Path(parent['path']).read_bytes()
    reading = json.dumps({'original_request': 'Retain the original question.'}).encode()
    store.append('intake', {'contract_blob': put(raw), 'reading_blob': put(reading)})
    # The run's intake copies, as the controller's intake writes them beside the run's other inputs.
    (run / 'inputs').mkdir(parents=True, exist_ok=True)
    (run / 'inputs/task_contract.json').write_bytes(raw)
    (run / 'inputs/reading.json').write_bytes(reading)
    from ravel.controller.routes.research import loop_budget
    # A feasible positive uses the installed projection, not an invented allowance.
    projected = loop_budget.declare({'max_decisions': 1, 'campaign': {'max_experiments': 0,
        'budget': {'calls': 1, 'output_tokens': 2048, 'wall_seconds': 240, 'native_attempts': 0}}},
        [], tier='lean')['cost_ceiling_usd']
    step = bridge._step('method', 'subgraph', outputs=['outputs/method.json'],
                        budget={'wall_seconds': 240, 'tokens': 2048, 'broker_calls': 8, 'cost_usd': projected})
    step.update(description='Compare two bounded estimators.', graph={'id': 'research.loop', 'instance': {}})
    context = {'run_dir': str(run), 'plan_sha256': 'a' * 64}
    return store, step, context


def test_unbound_step_derives_one_lean_cycle_with_exact_provenance(bounded):
    from ravel.workflow import bounded_research
    store, step, context = bounded
    pin, budget = bounded_research.bind(store, step, context)
    value = decisions.request(pin)
    assert value['max_decisions'] == budget['max_cycles'] == 1
    assert value['campaign']['max_experiments'] == budget['max_children'] == 0
    assert budget['tier'] == 'lean'
    assert value['runtime']['max_wall_seconds'] <= step['budget']['wall_seconds']
    assert budget['cost_ceiling_usd'] <= step['budget']['cost_usd']
    origin = cycle._read(value['bounded_step'], context['run_dir'])
    assert origin['step'] == step and origin['plan_sha256'] == context['plan_sha256']
    assert origin['question'] == step['description'] and origin['outputs'] == step['outputs']
    assert bounded_research.bind(store, step, context) == (pin, budget)


@pytest.mark.parametrize('field', ['max_decisions', 'campaign', 'runtime', 'bounded_step'])
def test_tampered_derived_request_refused_even_with_a_fresh_pin(bounded, field):
    from ravel.workflow import bounded_research
    store, step, context = bounded
    pin, _ = bounded_research.bind(store, step, context)
    value = decisions.request(pin)
    if field == 'max_decisions':
        value[field] = 2
    elif field == 'campaign':
        value[field]['max_experiments'] = 1
    elif field == 'runtime':
        value[field]['max_wall_seconds'] += 1
    else:
        value[field]['sha256'] = '0' * 64
    state_io.atomic_json(pin['path'], value)
    with pytest.raises(ValueError):
        decisions.request(cycle._pin(pin['path']))
    with pytest.raises(ValueError):
        bounded_research.bind(store, step, context)


def test_derived_binding_cannot_move_to_a_different_plan(bounded):
    from ravel.workflow import bounded_research
    store, step, context = bounded
    pin, _ = bounded_research.bind(store, step, context)
    with pytest.raises(ValueError, match='approved plan changed'):
        bounded_research.bound_record(store, step, pin, {**context, 'plan_sha256': 'b' * 64})


@pytest.mark.parametrize('bad_pin', [None, {}, {'path': 'absent'}])
def test_malformed_explicit_pin_never_falls_back_to_derivation(bounded, bad_pin):
    from ravel.workflow import bounded_research
    store, step, context = bounded
    step['parameters'] = {'research_request': bad_pin}
    with pytest.raises(ValueError, match='adopted source-bound request pin'):
        bridge.invoke(store, step, context)
    assert not store.scan(bounded_research.BINDING)


def test_bounded_synthesis_completes_declared_output_and_ordinary_custody(bounded, monkeypatch):
    from ravel.workflow import bounded_research
    store, step, context = bounded
    pin, _ = bounded_research.bind(store, step, context)
    request = decisions.request(pin)
    root = Path(context['run_dir']) / 'campaign'
    from ravel.workflow import research_orchestrator as orch
    plan = orch._open_plan(root, pin, root / 'coordinator', host=bridge.GovernedHost(store, context))
    assert plan['value'] == request
    pending = __import__('ravel.workflow.research_protocol', fromlist=['methodology_status']).methodology_status(root)
    result = cycle.bounded_synthesis(root, 'One bounded decision completed.')
    monkeypatch.setattr(bridge, '_service', lambda name: pytest.fail('sub-question must not end its parent'))
    final = bridge._finish(store, step, context, root, store.path('research'), pin, {}, result)
    assert final['controller_outcome']['status'] == 'completed'
    assert final['labels'] == ['BOUNDED SUB-QUESTION']
    assert final['scientific_acceptance'] is False and pending['pending']
    child = {'outcome': 'ok', 'graph_id': 'research.loop', 'results_sha256': cycle.ce.digest(final),
             'outputs': final['controller_outcome']['outputs']}
    [row] = custody.subgraph_adoption(store, run_dir=context['run_dir'], step=step, attempt=1,
                                     card=None, child=child, inputs_custody=[])
    assert row['path'] == 'outputs/method.json'
    assert state_io.read_json(Path(context['run_dir']) / row['destination'])['labels'] == final['labels']
    from ravel.controller.sink.deliver import condition_labels
    from ravel.controller.sink.checks import Findings
    findings = Findings()
    condition_labels(store, {'steps': [step]}, {}, findings)
    assert [row['label'] for row in findings.labels] == ['BOUNDED SUB-QUESTION']


def test_unbound_step_runs_exactly_one_governed_decision_and_keeps_protocol_duties(bounded):
    from p11_fakes import FakeStep, InertReviewHost, installed_step
    store, step, context = bounded
    def progress(node, presented):
        assert node['parameters']['output_schema']['properties']['action']['enum'] == ['progress']
        return {'kind': 'research-action', 'action': 'progress', 'reason': 'One bounded progress decision.',
                'information_gain': {'decision': 'stop', 'expected_gain': 'The bounded comparison is complete.',
                    'cost_justification': 'Further work exceeds this completed sub-question.',
                    'evidence_input_ids': ['scientific-core']},
                'arguments_json': json.dumps({'reason': 'Bounded work is complete.'})}
    peer = FakeStep(InertReviewHost(progress))
    with installed_step(peer):
        final = bridge.invoke(store, step, context)
    diagnostics = {'result': final, 'step_outcomes': store.scan('research-step-outcome'), 'calls': len(peer.calls)}
    if final['controller_outcome']['status'] != 'completed':
        from ravel.workflow import graph_substrate
        last = store.scan('research-subgraph')[-1]['record']
        snapshot = graph_substrate._pending(last['scope'], 'research.loop', final['checkpoint']['instance'])[2]
        diagnostics['failures'] = snapshot.values.get('failures')
    assert final['controller_outcome']['status'] == 'completed', json.dumps(diagnostics, sort_keys=True)
    assert final['labels'] == ['BOUNDED SUB-QUESTION']
    assert len(peer.calls) == 1 and len(store.scan('research-call')) == 1, json.dumps(diagnostics, sort_keys=True)
    assert final['qualification']['pending_protocol_stages']
    assert final['scientific_acceptance'] is False and final['parent_task_accepted'] is False
    assert not store.scan('research-bounded-delivery')


def test_adopted_whole_goal_request_retains_existing_sink_ending(bounded, monkeypatch):
    store, step, context = bounded
    calls = []
    class Sink:
        def bounded_end(self, supplied, reason):
            calls.append(reason)
            return {'qualified': True}
    monkeypatch.setattr(bridge, '_service', lambda name: Sink())
    result = {'kind': 'research_bounded_synthesis', 'phase': 'budget_exhausted', 'reason': 'Original ceiling.'}
    final = bridge._finish(store, step, context, Path(context['run_dir']) / 'campaign',
                           store.path('research'), {}, {}, deepcopy(result))
    assert final['controller_outcome']['status'] == 'budget_exhausted'
    assert calls == ['Original ceiling.']


def test_declared_cost_share_below_projection_refuses_before_the_coordinator_call(bounded):
    from p11_fakes import FakeStep, installed_step
    store, step, context = bounded
    step['budget']['cost_usd'] = 0
    peer = FakeStep()
    with installed_step(peer):
        final = bridge.invoke(store, step, context)
    assert not peer.calls and not store.scan('research-call')
    assert final['controller_outcome']['status'] == 'completed'
    assert final['boundary']['kind'] == 'research_loop_budget'
    assert final['scientific_acceptance'] is False
    assert final['qualification']['pending_protocol_stages']
    assert not store.scan('research-bounded-delivery')


def test_inner_steps_of_a_bounded_sub_question_bind_to_its_approved_parent(bounded):
    from p11_fakes import FakeStep, InertReviewHost, installed_step
    from ravel.controller.step import operations
    from ravel.controller.step.services import StepHold
    store, step, context = bounded
    def progress(node, presented):
        return {'kind': 'research-action', 'action': 'progress', 'reason': 'One bounded progress decision.',
                'information_gain': {'decision': 'stop', 'expected_gain': 'The bounded comparison is complete.',
                    'cost_justification': 'Further work exceeds this completed sub-question.',
                    'evidence_input_ids': ['scientific-core']},
                'arguments_json': json.dumps({'reason': 'Bounded work is complete.'})}
    with installed_step(FakeStep(InertReviewHost(progress))):
        bridge.invoke(store, step, context)
    derived = [row.get('record', row) for row in store.scan('research-derived-step')]
    assert derived
    plan = {'sha256': context['plan_sha256'], 'steps': [step]}
    for row in derived:
        bound, plan_sha, basis = operations._research_derived_step(store, row['step'], plan, context)
        assert (bound, plan_sha, basis) == (row['step'], context['plan_sha256'], 'derived_research_step')
    # A different approved parent step (or plan) never inherits the bounded binding.
    changed = {**plan, 'steps': [{**step, 'description': 'Another question.'}]}
    with pytest.raises(StepHold) as held:
        operations._research_derived_step(store, derived[0]['step'], changed, context)
    assert held.value.reason == 'research_derived_step_unbound'
