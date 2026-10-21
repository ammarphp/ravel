"""Research route declarations and honest partial endings without live effects."""
import json
from copy import deepcopy
from pathlib import Path
import sys

import pytest

from ravel.controller.routes import research
from ravel.workflow import research_cycle as cycle
from ravel.workflow.graph_nodes import RecoveryHold

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_research_cycle import contract  # noqa: E402
from test_langgraph_research_orchestration import open_fixture  # noqa: E402
from ravel.workflow import research_coordinator_decisions as decisions, state_io  # noqa: E402

SPEC = Path(__file__).resolve().parents[3] / 'src/ravel/data/controller/routes/research.json'


def test_research_route_declares_loop_children_review_and_original_scope():
    spec = json.loads(SPEC.read_text())
    assert spec['match']['row'] == 5
    assert spec['match']['when']['in'] == ['research', 'method_study', 'anomaly_search']
    steps = {step['id']: step for step in spec['steps']}
    assert steps['campaign']['kind'] == 'subgraph' and steps['campaign']['graph']['id'] == 'research.loop'
    assert steps['children']['kind'] == 'route' and steps['children']['route'] == 'study'
    assert steps['children']['parameters']['own_checkin1']
    assert steps['meta-review']['depends_on'] == ['campaign', 'children']
    assert steps['integrity']['depends_on'] == ['meta-review']
    assert steps['parent-completion']['depends_on'] == ['campaign', 'integrity']
    assert {row['id'] for row in spec['checkins']} == {'checkin1', 'checkin2', 'checkin3'}
    assert len([row for row in steps['campaign']['obligations'] if row.startswith('STAGE-')]) == 9
    assert spec['deliverables'][0]['match'] != {'any': True}  # A prose report cannot silently replace a plot.


def test_research_children_preserve_contract_reading_and_supplied_inputs():
    child = {'id': 'child-one', 'reading': {'original': 'one'}, 'contract': {'original': 'two'}}
    parent = {'research_children': [child], 'original_obligations': ['retain-negative-results']}
    bound = research.parameters({}, {'deliverables': [{'id': 'quantity'}]}, parent, [{'kind': 'supplied'}])
    assert bound['research_children'] == [child]
    assert bound['research_request']['contract'] == parent
    bound['research_children'][0]['contract']['original'] = 'changed'
    assert child['contract']['original'] == 'two'
    with pytest.raises(ValueError, match='distinct'):
        research.parameters({}, {}, {'research_children': [child, child]}, [])


def test_unadopted_campaign_request_is_held_without_legacy_dispatch():
    errors = research.admit({'id': 'campaign'}, {})
    assert errors[0]['code'] == 'research_request_unbound'
    assert research.admit({'id': 'prepare'}, {}) == []


def prepared_route(tmp_path):
    request, _, _, own_contract = open_fixture(tmp_path)
    run = tmp_path / 'parent'
    prepared = run / 'steps' / 'prepare' / 'outputs'
    prepared.mkdir(parents=True)
    state_io.atomic_json(prepared / 'campaign-request.json', decisions.request(request))
    children = [{'id': identity, 'reading': {'source': 'original ' + identity},
                 'contract': {'original_obligations': ['quantity-' + identity]}}
                for identity in ('left', 'right')]
    state_io.atomic_json(prepared / 'child-requests.json', children)
    context = {'run_dir': str(run), 'contract': own_contract,
               'reading': {'original_request': 'Retain the original quantity.'},
               'state': {'steps': {'prepare': {'status': 'completed', 'outputs': [
                   cycle._pin(prepared / name) for name in ('campaign-request.json', 'child-requests.json')]}}}}
    plan = json.loads(SPEC.read_text())
    # The route template's parameter declarations become a mapping in a bound plan.
    plan['waypoints'] = []
    plan['parameters'] = research.parameters({}, context['reading'], {'research_children': children}, [])
    return plan, context, children


def test_adopted_research_binding_preserves_original_child_scope_and_dependencies(tmp_path):
    plan, context, children = prepared_route(tmp_path)
    before = deepcopy((plan, context, children))
    bound = research.bind(plan, context)
    assert (plan, context, children) == before
    request = bound['parameters']['research_request']
    value = decisions.request(request)  # Real source/handoff/runtime validation, without stubbing.
    assert bound['parameters']['research_children'] == children
    assert bound['parameters']['research_binding']['request'] == request
    rows = {row['id']: row for row in bound['steps']}
    assert 'children' not in rows
    assert rows['campaign']['parameters']['research_request'] == request
    assert rows['campaign']['parameters']['runtime'] == value['runtime']
    assert rows['campaign']['graph']['instance'] == {
        'campaign': value['campaign']['id'], 'request': request['sha256']}
    for child in children:
        row = rows['children.' + child['id']]
        assert row['kind'] == 'route' and row['route'] == 'study'
        assert row['depends_on'] == ['campaign']
        assert row['parameters'] == {'item': child, 'own_checkin1': True,
                                      'inherit_authority': True, 'inherit_budget': True}
        assert {'P03', 'C34', 'MODE-research-comparison'} <= set(row['obligations'])
    assert rows['meta-review']['depends_on'] == ['campaign', 'children.left', 'children.right']
    assert rows['integrity']['depends_on'] == ['meta-review']
    assert rows['parent-completion']['depends_on'] == ['campaign', 'integrity']
    assert bound['checkins'] == plan['checkins']
    assert bound['deliverables'] == plan['deliverables']
    assert bound['sha256'] == cycle.ce.digest({k: v for k, v in bound.items() if k != 'sha256'})
    assert research.admit(rows['campaign'], context) == []
    assert research.bind(bound, context) == bound


def rewrite_prepared_request(context, update):
    outputs = context['state']['steps']['prepare']['outputs']
    path = Path(outputs[0]['path'])
    value = state_io.read_json(path)
    update(value)
    state_io.atomic_json(path, value)
    outputs[0] = cycle._pin(path)


@pytest.mark.parametrize('damage', ['same_bytes_other_file', 'digest', 'size', 'missing_parent',
                                   'missing_own_file', 'context_contract'])
def test_binding_requires_this_runs_exact_contract_before_request_validation(tmp_path, monkeypatch, damage):
    plan, context, _ = prepared_route(tmp_path)
    own = Path(context['run_dir']) / 'inputs' / 'task_contract.json'
    if damage == 'same_bytes_other_file':
        other = tmp_path / 'other-task-contract.json'
        other.write_bytes(own.read_bytes())
        assert cycle._pin(other)['sha256'] == cycle._pin(own)['sha256']
        rewrite_prepared_request(context, lambda value: value.update(parent_contract=cycle._pin(other)))
    elif damage in ('digest', 'size'):
        def change(value):
            pin = value['parent_contract']
            pin['sha256' if damage == 'digest' else 'size'] = '0' * 64 if damage == 'digest' else pin['size'] + 1
        rewrite_prepared_request(context, change)
    elif damage == 'missing_parent':
        rewrite_prepared_request(context, lambda value: value.pop('parent_contract'))
    elif damage == 'missing_own_file':
        own.unlink()
    else:
        context['contract'] = {**context['contract'], 'substituted': True}
    before = deepcopy((plan, context))
    def forbidden(*args, **kwargs):
        pytest.fail('request validation or budget declaration ran before exact contract binding')
    monkeypatch.setattr(decisions, 'request', forbidden)
    from ravel.controller.routes.research import loop_budget
    monkeypatch.setattr(loop_budget, 'declare', forbidden)
    with pytest.raises(RecoveryHold) as held:
        research.bind(plan, context)
    assert held.value.reason == 'research_contract_mismatch'
    assert held.value.would_make_possible
    assert (plan, context) == before


def test_binding_accepts_exact_retained_contract_without_optional_context_copy(tmp_path):
    plan, context, _ = prepared_route(tmp_path)
    del context['contract']
    bound = research.bind(plan, context)
    campaign = next(row for row in bound['steps'] if row['id'] == 'campaign')
    assert research.admit(campaign, context) == []


@pytest.mark.parametrize('damage', ['same_bytes_other_run', 'changed_own_bytes', 'context_contract',
                                   'missing_own_file', 'changed_request_digest', 'same_bytes_other_file'])
def test_bound_campaign_rechecks_contract_before_inert_dispatch(tmp_path, monkeypatch, damage):
    plan, context, _ = prepared_route(tmp_path)
    bound = research.bind(plan, context)
    campaign = next(row for row in bound['steps'] if row['id'] == 'campaign')
    assert research.admit(campaign, context) == []
    own = Path(context['run_dir']) / 'inputs' / 'task_contract.json'
    if damage == 'same_bytes_other_run':
        other = tmp_path / 'substituted-run'
        (other / 'inputs').mkdir(parents=True)
        (other / 'inputs' / 'task_contract.json').write_bytes(own.read_bytes())
        context['run_dir'] = str(other)
    elif damage == 'changed_own_bytes':
        own.write_bytes(own.read_bytes() + b'\n')
    elif damage == 'missing_own_file':
        own.unlink()
    elif damage == 'context_contract':
        context['contract'] = {**context['contract'], 'substituted': True}
    elif damage == 'changed_request_digest':
        request = campaign['parameters']['research_request']
        value = state_io.read_json(request['path'])
        value['parent_contract']['sha256'] = '0' * 64
        state_io.atomic_json(request['path'], value)
        campaign['parameters']['research_request'] = cycle._pin(request['path'])
    else:
        other = tmp_path / 'other-task-contract.json'
        other.write_bytes(own.read_bytes())
        rewrite_prepared_request(context, lambda value: value.update(parent_contract=cycle._pin(other)))
        campaign['parameters']['research_request'] = context['state']['steps']['prepare']['outputs'][0]
    calls = []
    def forbidden(*args, **kwargs):
        pytest.fail('request validation ran before contract revalidation')
    monkeypatch.setattr(decisions, 'request', forbidden)
    # Compose real binding and current campaign admission with an inert effect seam.
    # A previously bound step carries no authority after its own contract changes.
    errors = research.admit(campaign, context)
    if not errors:
        calls.append('dispatch')
    assert calls == []
    assert errors[0]['code'] == 'research_contract_mismatch'
    assert errors[0]['message']


@pytest.mark.parametrize('damage', ['changed_request', 'changed_children', 'missing', 'duplicate',
                                   'invalid_request', 'invalid_handoff', 'duplicate_children'])
def test_binding_refuses_changed_ambiguous_or_invalid_adopted_records(tmp_path, damage):
    plan, context, children = prepared_route(tmp_path)
    outputs = context['state']['steps']['prepare']['outputs']
    request_path, children_path = [Path(row['path']) for row in outputs]
    if damage == 'changed_request':
        request_path.write_text('{}')
    elif damage == 'changed_children':
        children_path.write_text('[]')
    elif damage == 'missing':
        outputs.pop()
    elif damage == 'duplicate':
        outputs.append(deepcopy(outputs[0]))
    elif damage == 'duplicate_children':
        state_io.atomic_json(children_path, [children[0], children[0]])
        outputs[1] = cycle._pin(children_path)
    else:
        value = state_io.read_json(request_path)
        if damage == 'invalid_request':
            value['kind'] = 'unvalidated-prose'
        else:
            value['handoff']['original_request'] = 'Substituted assignment'
        state_io.atomic_json(request_path, value)
        outputs[0] = cycle._pin(request_path)
    before = deepcopy((plan, context))
    with pytest.raises(ValueError):
        research.bind(plan, context)
    assert (plan, context) == before


def test_real_exhaustion_produces_read_only_complete_progress(tmp_path):
    definition = contract(tmp_path)
    root = tmp_path / 'campaign'
    state = cycle.create(root, definition, base_dir=tmp_path, evaluation_harness=True)
    head = (root / 'head.json').read_bytes()
    bounded = cycle.bounded_synthesis(root, 'Original call reservation exhausted.')
    assert bounded['phase'] == 'budget_exhausted'
    assert bounded['delivery_receipt'] is None
    assert bounded['parent_task_accepted'] is False and bounded['scientific_acceptance'] is False
    progress = bounded['progress']
    assert progress['required_experiments'] == definition['required_experiments']
    assert [row['request'] for row in progress['requested_quantity_census']] == state['context']['requested_quantities']
    assert progress['all_experiments'][0]['id'] == 'paired'
    assert progress['all_experiments'][0]['status'] == 'not_designed'
    assert (root / 'head.json').read_bytes() == head


def test_incomplete_ending_records_unavailable_progress_without_acceptance(tmp_path):
    class Store:
        def __init__(self):
            self.rows = []

        def append(self, kind, record):
            self.rows.append((kind, record))
            return str(len(self.rows))

    store = Store()
    research.ending('Original bound reached.', {'run_dir': str(tmp_path), 'store': store,
        'plan': {'open_obligations': [{'id': 'original-quantity'}]}, 'state': {'steps': {}}})
    kind, row = store.rows[0]
    assert kind == 'research-ending' and row['open_obligations'] == [{'id': 'original-quantity'}]
    assert row['scientific_acceptance_inferred'] is False and row['unavailable_synthesis']


def test_research_template_compiles_on_integrated_controller_spine():
    compiler = pytest.importorskip('ravel.controller.routes.compiler', reason='controller spine not in package base')
    spec = json.loads(SPEC.read_text())
    reading = {'deliverables': [{'id': 'report', 'artifact': {'kind': 'document'}},
                                {'id': 'figure', 'artifact': {'kind': 'plot'}}]}
    plan = compiler.compile(spec, reading, {'task_mode': 'research'})
    assert {row['id'] for row in plan['deliverables']} == {'report', 'figure'}
    assert next(row for row in plan['deliverables'] if row['id'] == 'figure')['status'] == 'open'


def governed_campaign(tmp_path):
    definition = contract(tmp_path)
    definition['research_protocol_required'] = True
    run = tmp_path / 'run'
    run.mkdir()
    cycle.create(run / 'campaign', definition, base_dir=tmp_path, evaluation_harness=True)
    return run


@pytest.mark.parametrize('transition', ['checkin3->deliver', 'deliver', 'checkin3'])
def test_delivery_gate_refuses_pending_research_stages_on_the_controller_transition(tmp_path, transition):
    from p11_fakes import FakeRunStore
    run = governed_campaign(tmp_path)
    context = {'run_dir': str(run), 'store': FakeRunStore('gate-control', root=tmp_path / 'protected'),
               'plan': {'parameters': {'research_children': []}}}
    errors = research.gate(transition, context)
    assert 'required research stage incomplete: limitation_census' in errors
    # Earlier controller gates are not delivery: pending stages are expected there.
    assert research.gate('checkin1->execute', context) == []
    assert research.gate('checkin2->execute[first]', context) == []


def test_delivery_gate_passes_complete_research_evidence(tmp_path, monkeypatch):
    from p11_fakes import FakeRunStore
    from ravel.workflow import research_protocol
    run = governed_campaign(tmp_path)
    actual = research_protocol.methodology_status
    # Model a campaign whose every declared stage is complete; all other checks stay real.
    monkeypatch.setattr(research_protocol, 'methodology_status', lambda root: {**actual(root), 'pending': []})
    context = {'run_dir': str(run), 'store': FakeRunStore('gate-control', root=tmp_path / 'protected'),
               'plan': {'parameters': {'research_children': []}}}
    assert research.gate('checkin3->deliver', context) == []
