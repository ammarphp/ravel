"""Request-bound planning facts cross adopted bytes, review and child pricing."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ravel.controller import graph, routes
from ravel.controller.engagement import facts, policy
from ravel.controller.engagement.records import digest
from ravel.controller.routes.research import loop_budget
from ravel.controller.store import RunStore
from test_p01_graph import controller, real_authority  # noqa: F401


REQUEST = 'Calculate a fictional scalar using its supplied law.'


def method(hours=0.5):
    value = json.loads((Path(__file__).parents[2] / 'fixtures/method_decisions/standard_table.json').read_text())
    value['request_digest'] = sha256(REQUEST.encode()).hexdigest()
    value['obligation_ids'] = ['value']
    value['cost_forecast']['cpu_hours'] = hours
    return value


def forecast(value):
    return {'schema_version': 1, 'kind': 'method-cost-forecast',
            'request_digest': value['request_digest'], 'method_sha256': digest(value),
            'cost_forecast': deepcopy(value['cost_forecast'])}


def child_request(hours=0.5):
    reading = {'deliverables': [{'id': 'value', 'artifact': {'kind': 'document'}}]}
    contract = {'prompt': REQUEST, 'deliverables': deepcopy(reading['deliverables'])}
    plan = routes.compile(routes.find('study'), reading, contract)
    value = method(hours)
    return {'id': 'scalar', 'route': 'study', 'reading': reading, 'contract': contract,
            'engagement_planning': {'plan': plan, 'method': value, 'cost': forecast(value)}}


def adopted(store, root, step, path, value):
    """A deterministic producer's protected accepted output and completed outcome."""
    raw = json.dumps(value).encode()
    destination = f'steps/{step["id"]}/{path}'
    target = root / destination
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    row = {'artifact': f'{step["id"]}:{path}', 'step_id': step['id'], 'attempt': 1,
           'destination': destination, 'path': path, 'sha256': sha256(raw).hexdigest(),
           'status': 'accepted', 'inputs': [], 'producer': {'kind': 'worker'}}
    store.append('custody', row)
    store.append('step-outcome', {'step_id': step['id'], 'attempt': 1, 'status': 'completed'})
    return row


@pytest.fixture
def root_run(tmp_path):
    root = tmp_path / 'run'
    root.mkdir()
    store = RunStore('planned-facts', root=tmp_path / 'store')
    reading = {'deliverables': [{'id': 'value', 'artifact': {'kind': 'document'}}]}
    contract = {'prompt': REQUEST}
    plan = routes.compile(routes.find('calculation'), reading, contract)
    store.append('plan', {'plan': plan, 'plan_sha256': plan['sha256']})
    store.append('route', {'route': 'calculation'})
    intake = store.append('intake', {'reading_blob': store.put_blob(json.dumps(reading).encode()),
        'contract_blob': store.put_blob(json.dumps(contract).encode()),
        'request_sha256': sha256(REQUEST.encode()).hexdigest(), 'supplied': []})
    state = {'request': {'intake_record_id': intake}, 'run': {'run_dir': str(root)}}
    return store, root, plan, state, reading, contract


def credit(store, plan, items, *, verdict='accept', covered=True):
    review = store.append('review', {'plan_sha256': plan['sha256'],
        'seats': {'plan-critic': {'credited': True, 'verdict': verdict}},
        'engagement_fact_sha256s': [i['subject_sha256'] for i in items] if covered else []})
    return facts.credit_reviewed_facts(store, plan, review)


@pytest.mark.parametrize('hours,tier', [(0.5, 'lean'), (500, 'standard'), (None, 'full')])
def test_request_only_preparation_supplies_reviewed_compute(root_run, hours, tier):
    store, root, plan, state, reading, contract = root_run
    outputs = [(step, output) for step in plan['steps'] for output in step['outputs']
               if output['kind'] in ('method-decision', 'method-cost-forecast')]
    assert {output['kind'] for _, output in outputs} == {'method-decision', 'method-cost-forecast'}
    value = method(hours)
    for step, output in outputs:
        adopted(store, root, step, output['path'], value if output['kind'] == 'method-decision' else forecast(value))
    found, reason = graph.adopted_method(state, store, plan=plan)
    assert reason is None and found == value
    assert graph.adopted_method(state, store, plan=plan) == (found, None)
    assert len(store.scan('engagement-method-adoption')) == 1
    items = facts.pin_inputs(store, plan, reading, contract, method=found, novelty='N0', parent='none')
    assert facts.collect(store, {}, policy.load_policy())[0]['compute']['value'] is None
    assert len(credit(store, plan, items)) == 2
    collected, _ = facts.collect(store, {}, policy.load_policy())
    assert policy.tier(collected, policy.load_policy())['tier'] == tier


@pytest.mark.parametrize('damage', ['changed', 'foreign', 'unadopted', 'incomplete', 'cost', 'missing_cost', 'scope'])
def test_planned_method_refuses_broken_custody(root_run, damage):
    store, root, plan, state, _, _ = root_run
    outputs = [(s, o) for s in plan['steps'] for o in s['outputs']
               if o['kind'] in ('method-decision', 'method-cost-forecast')]
    assert len(outputs) == 2
    value = method()
    if damage == 'foreign':
        value['request_digest'] = 'f' * 64
    elif damage == 'scope':
        value['obligation_ids'] = ['other-value']
    for step, output in outputs:
        if damage == 'missing_cost' and output['kind'] == 'method-cost-forecast':
            continue
        payload = value if output['kind'] == 'method-decision' else forecast(value)
        if damage == 'cost' and output['kind'] == 'method-cost-forecast':
            payload['cost_forecast']['cpu_hours'] = 0
        row = adopted(store, root, step, output['path'], payload)
        if damage == 'changed':
            (root / row['destination']).write_text('{}')
        elif damage == 'unadopted':
            store.append('custody', {**row, 'status': 'rejected'})
        elif damage == 'incomplete':
            store.append('step-outcome', {'step_id': step['id'], 'attempt': 1, 'status': 'failed'})
    assert graph.adopted_method(state, store, plan=plan)[0] is None


@pytest.mark.parametrize('hours,tier', [(0.5, 'lean'), (500, 'standard')])
def test_child_installed_collector_has_reviewed_own_tier(root_run, hours, tier):
    from ravel.controller.engagement import planning
    store, root, parent, _, _, _ = root_run
    child = child_request(hours)
    source_step = next(s for s in parent['steps'] if s['kind'] == 'author')
    source_step['outputs'].append({'path': 'outputs/child-requests.json', 'kind': 'document', 'required': True})
    parent['parameters']['research_children'] = [child]
    parent['sha256'] = digest({k: v for k, v in parent.items() if k != 'sha256'})
    store.append('plan', {'plan': parent, 'plan_sha256': parent['sha256']})
    adopted(store, root, source_step, 'outputs/child-requests.json', [child])
    context = {'store': store, 'run_dir': str(root), 'plan': parent}
    planning.pin_children(context, [child], f'{source_step["id"]}:outputs/child-requests.json')
    installed, _, rules = loop_budget._installed()
    priced = loop_budget.child_projection(child, installed, rules, store=store)
    assert priced['tier'] == tier
    assert policy.tier(loop_budget.child_facts(child, store=store, reviewed=True), rules)['tier'] == 'full'
    items = facts.review_items(store, parent)
    assert any(i['id'] == 'engagement-child-input' for i in items)
    assert credit(store, parent, items)
    checked = loop_budget.child_facts(child, store=store, reviewed=True)
    assert policy.tier(checked, rules)['tier'] == tier
    assert digest(checked) == priced['facts_sha256']
    budget = loop_budget.declare({'max_decisions': 1, 'campaign': {'max_experiments': 1, 'budget': {}}},
                                 [child], store=store)
    reservation = loop_budget.admit(store, budget, 'child', 'scalar', child=child)
    assert reservation['projection'] == priced
    assert loop_budget.admit(store, budget, 'child', 'scalar', child=child) == reservation
    assert len(store.scan(loop_budget.RESERVATION)) == 1
    from ravel.controller.routes.research import child_engagement
    child_store, decision, applied = child_engagement.prepare(store, child,
        child['engagement_planning']['plan'], budget, 'scalar', frozen_mode={})
    assert decision['tier'] == applied['engagement']['tier'] == tier
    assert child_store.run_id != store.run_id
    assert decision['facts']['parent_context']['value']['tier'] == 'full'
    changed = deepcopy(child)
    changed['engagement_planning']['method']['cost_forecast']['cpu_hours'] += 1
    with pytest.raises(loop_budget.LoopBudgetExhausted):
        loop_budget.admit(store, budget, 'child', 'scalar', child=changed)


def test_inline_unreviewed_child_claims_keep_full():
    child = child_request()
    assert policy.tier(loop_budget.child_facts(child), policy.load_policy())['tier'] == 'full'


@pytest.mark.parametrize('hours,tier', [(0.5, 'lean'), (500, 'standard')])
def test_request_only_controller_reviews_planned_facts(controller, real_authority, capfd, monkeypatch, hours, tier):
    import fakes
    import test_composition_tiers as composition
    original_spec = composition.calculation_spec

    def specification():
        spec = original_spec()
        prepare = fakes.make_step('specify', kind='author', role='coordinator',
                                  parameters={'phase': 'prepare'})
        spec['steps'].insert(0, prepare)
        spec['steps'][1]['depends_on'] = ['specify']
        return spec

    original_run = fakes.step_run

    def produce(store, step, context):
        outcome = original_run(store, step, context)
        if step['id'] == 'specify':
            value = composition.method_decision(composition.SIMPLE, cpu_hours=hours)
            value['obligation_ids'] = ['D1']
            for output in step['outputs']:
                payload = value if output['kind'] == 'method-decision' else forecast(value)
                adopted(store, Path(context['run_dir']), step, output['path'], payload)
        return outcome

    monkeypatch.setattr(composition, 'calculation_spec', specification)
    monkeypatch.setattr(fakes, 'step_run', produce)
    store, observation, _, _ = composition._drive_tier(controller, real_authority, capfd, monkeypatch)
    decision = composition._decision(store)
    assert decision['computed_tier'] == decision['tier'] == tier, decision['reasons']
    composition._assert_credited(store)
    composition._assert_rendered(store, tier)
    composition._assert_honest_end(store, observation)
    assert not store.scan('supplied') or not store.scan('supplied')[-1]['record'].get('inputs')


@pytest.mark.parametrize('command', [
    ['scripts/run.py', 'ravel.validation.check_agent_surface'],
    ['scripts/run.py', 'ravel.validation.check_agent_paths', 'check', '--gate', 'G8', '--mode', 'block_new'],
    ['scripts/maintenance/build_instruction_catalogue.py', '--check'],
    ['scripts/maintenance/sync_instruction_bundle.py', '--check'],
])
def test_current_source_agent_surface(command):
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[3]
    checked = subprocess.run([sys.executable, *command],
                             cwd=root, capture_output=True, text=True, timeout=180)
    assert checked.returncode == 0, checked.stdout + checked.stderr
