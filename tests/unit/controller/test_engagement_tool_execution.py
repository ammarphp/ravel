"""Applied tiers preserve the required native invocation and leave spare tools idle."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from ravel.controller import engagement, graph, routes
from ravel.controller.engagement import facts, policy
from ravel.controller.engagement.records import digest
from ravel.controller.ledger import population_equality
from ravel.controller.step import operations, services
from test_p04_graph import _launch_step, _launch_tool, _signature
from test_p04_support import context, graphs, install_plan, records, run_env, services_installed  # noqa: F401


@pytest.mark.parametrize('tier', ['lean', 'standard', 'full'])
@pytest.mark.parametrize('needed', [True, False])
def test_only_the_needed_tool_executes_under_each_applied_tier(run_env, graphs, monkeypatch, tier, needed):
    from ravel.controller import step as governed
    monkeypatch.setattr(operations, 'signatures', lambda: {'fixture-operation': _signature()})
    seat_plan = policy.seat_plan

    def with_instructions(*args, **kwargs):
        kwargs.setdefault('instructions', run_env.fakes['instructions'])
        return seat_plan(*args, **kwargs)

    monkeypatch.setattr(policy, 'seat_plan', with_instructions)
    original = _launch_step(_launch_tool(run_env.root))
    spare = run_env.root / 'tools' / 'spare_tool.py'
    spare.write_text('raise RuntimeError("spare tool was invoked")\n')
    install_plan(run_env.store, [original] if needed else [])
    pin = run_env.store.scan('plan')[-1]
    plan = json.loads(run_env.store.get_blob(pin['record']['blob']))
    plan['route']['id'] = 'study'
    plan['sha256'] = digest({k: v for k, v in plan.items() if k != 'sha256'})
    blob = run_env.store.put_blob(json.dumps(plan).encode())
    record = run_env.store.append('plan', {'plan_sha256': plan['sha256'], 'blob': blob})
    checked = {name: facts.fact(value, 'declared inert contract', 'code:tool-control') for name, value in
               {'route': 'study', 'deliverables': 0, 'consequence': 'R0', 'compute': 'C1',
                'novelty': 'N0', 'special': []}.items()}
    decision = engagement.assemble(run_env.store, checked, plan,
        {'engagement': {'minimum_tier': tier}}, {}, installed=policy.load_policy())
    assert decision['computed_tier'] == 'lean' and decision['tier'] == tier
    view = engagement.apply(plan, decision)
    from ravel.controller.confine import commitments
    commitments.create(run_env.store, view, run_env.run_dir)
    assert len(view['steps']) == int(needed)
    if needed:
        assert view['steps'][0]['parameters']['launch'] == original['parameters']['launch']
    pins = graph.install_applied_plan(run_env.store,
        {'sha256': plan['sha256'], 'blob': blob, 'record_id': record}, view)
    ctx = context(run_env.store, run_env.run_dir, plan['sha256'], applied_sha256=pins['applied_sha256'])
    for step in view['steps']:
        result = governed.run(run_env.store, deepcopy(step), ctx)
        assert result['status'] == 'completed', result
    launched = run_env.fakes['confine'].launched
    assert len(launched) == int(needed)
    assert all('spare_tool' not in ' '.join(row['argv']) for row in launched)
    assert len([row for row in records(run_env.store, 'step-launch') if row['phase'] == 'finished']) == int(needed)
    if needed:
        assert json.loads((run_env.run_dir / 'steps/g1/grid.json').read_text()) == {'points': 3}


@pytest.mark.parametrize('hours,tier', [(0.5, 'lean'), (500, 'standard')])
@pytest.mark.parametrize('lineage', ['root', 'child'])
def test_checked_facts_select_the_tier_of_the_charged_native_operation(
        run_env, graphs, monkeypatch, hours, tier, lineage):
    import fakes
    from ravel.controller import step as governed
    from ravel.controller.confine import commitments
    from ravel.controller.engagement import planning
    from ravel.controller.routes.research import child_engagement, loop_budget
    from test_p04_support import FakeStore
    from test_planned_engagement_facts import adopted, credit, forecast, method

    monkeypatch.setattr(services.module('ledger'), 'population_equality', population_equality, raising=False)
    monkeypatch.setattr(operations, 'signatures', lambda: {'fixture-operation': _signature()})
    seat_plan = policy.seat_plan

    def with_instructions(*args, **kwargs):
        kwargs.setdefault('instructions', run_env.fakes['instructions'])
        return seat_plan(*args, **kwargs)

    monkeypatch.setattr(policy, 'seat_plan', with_instructions)
    native = _launch_step(_launch_tool(run_env.root))
    native['depends_on'] = ['specify']
    preparation = fakes.make_step('specify', kind='author', role='coordinator', parameters={'phase': 'prepare'})
    spec = fakes._spec('study', 9, {'field': 'task_mode', 'eq': 'calculation'}, [preparation, native],
                       [{'match': {'any': True}, 'step': native['id'], 'output': 'grid.json'}])
    contract_path = run_env.run_dir / 'inputs/task_contract.json'
    contract = json.loads(contract_path.read_text())
    reading = {'deliverables': [{'id': 'grid', 'artifact': {'kind': 'table'}}]}
    value = method(hours)
    value['request_digest'] = sha256(contract['prompt'].encode()).hexdigest()
    value['obligation_ids'] = ['grid']
    value['selected']['operation'] = native['operation']

    def pin(store, plan):
        blob = store.put_blob(json.dumps(plan).encode())
        record = store.append('plan', {'plan_sha256': plan['sha256'], 'blob': blob})
        return {'sha256': plan['sha256'], 'blob': blob, 'record_id': record}

    def prepare(store, root, plan):
        step = next(s for s in plan['steps'] if s['id'] == 'specify')
        for output in step['outputs']:
            if output['kind'] in ('method-decision', 'method-cost-forecast'):
                adopted(store, root, step, output['path'], value if output['kind'] == 'method-decision' else forecast(value))

    with routes.registered(spec, only=True):
        plan = routes.compile(spec, reading, contract)
        store, root = run_env.store, run_env.run_dir
        if lineage == 'root':
            pins = pin(store, plan)
            store.append('route', {'route': 'study'})
            intake = store.append('intake', {'reading_blob': store.put_blob(json.dumps(reading).encode()),
                'contract_blob': store.put_blob(json.dumps(contract).encode()),
                'request_sha256': value['request_digest'], 'supplied': []})
            state = {'request': {'intake_record_id': intake}, 'run': {'run_dir': str(root)}}
            prepare(store, root, plan)
            selected, reason = graph.adopted_method(state, store, plan=plan)
            assert reason is None and selected['selected']['operation'] == native['operation']
            items = facts.pin_inputs(store, plan, reading, contract, method=selected,
                                     novelty=graph.plan_novelty(plan)[0], parent='none')
            assert credit(store, plan, items)
            checked, _ = facts.collect(store, {}, policy.load_policy())
            decision = engagement.assemble(store, checked, plan, {}, {}, installed=policy.load_policy())
            view = engagement.apply(plan, decision)
        else:
            child = {'id': 'native-child', 'route': 'study', 'reading': reading, 'contract': contract,
                     'engagement_planning': {'plan': plan, 'method': value, 'cost': forecast(value)}}
            parent = deepcopy(plan)
            parent['parameters']['research_children'] = [child]
            source = next(s for s in parent['steps'] if s['id'] == 'specify')
            source['outputs'].append({'path': 'outputs/child-requests.json', 'kind': 'document', 'required': True})
            parent['sha256'] = routes.plan_sha256(parent)
            pin(store, parent)
            prepare(store, root, parent)
            adopted(store, root, source, 'outputs/child-requests.json', [child])
            planning.pin_children({'store': store, 'run_dir': str(root), 'plan': parent}, [child],
                                  'specify:outputs/child-requests.json')
            assert credit(store, parent, facts.review_items(store, parent))
            loop = loop_budget.declare({'max_decisions': 1,
                'campaign': {'max_experiments': 1, 'budget': {}}}, [child], store=store)
            child_root = root / 'children/native-child'
            (child_root / 'inputs').mkdir(parents=True)
            (child_root / 'inputs/task_contract.json').write_bytes(contract_path.read_bytes())
            execution_store = FakeStore(run_env.root / 'child-store', run_id='native-child', run_dir=child_root)
            # The source collector and child policy stay installed; this store exposes native accounting records.
            monkeypatch.setattr(child_engagement, 'child_store', lambda *_: execution_store)
            child_store, decision, view = child_engagement.prepare(store, child, plan, loop,
                'children.native-child', frozen_mode={})
            assert loop_budget.committed(store, loop)['children'] == 1
            [reservation] = records(store, loop_budget.RESERVATION)
            assert reservation['projection']['tier'] == tier
            assert reservation['projected_high_usd'] > 0
            store, root = child_store, child_root
            pins = pin(store, plan)
            prepare(store, root, plan)

        assert decision['computed_tier'] == decision['tier'] == tier
        assert decision['facts']['compute']['value'] == ('C1' if tier == 'lean' else 'C2')
        assert decision['facts']['compute']['checker'].startswith('code')
        commitments.create(store, view, root)
        pins = graph.install_applied_plan(store, pins, view)
        acting = next(s for s in view['steps'] if s['id'] == native['id'])
        assert acting['operation'] == value['selected']['operation']
        ctx = context(store, root, plan['sha256'], applied_sha256=pins['applied_sha256'])
        result = governed.run(store, deepcopy(acting), ctx)
        assert result['status'] == 'completed', result
        assert json.loads((root / 'steps/g1/grid.json').read_text()) == {'points': 3}
        assert len(run_env.fakes['confine'].launched) == 1
        [reserved] = records(store, 'budget-reservation')
        [settled] = records(store, 'budget-settlement')
        assert reserved['amounts']['children'] == settled['charged']['children'] == 1
        assert settled['status'] == 'settled' and settled['charged']['wall_seconds'] > 0
        assert [r['phase'] for r in records(store, 'step-launch')] == ['started', 'finished']
