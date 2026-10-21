"""An open question completes the real nine-stage loop through the step interface."""
from copy import deepcopy
from contextlib import ExitStack
import json
from pathlib import Path

from ravel.workflow import research_controller as bridge
from p11_fakes import FakeRunStore, FakeStep, installed_step
from test_p11_question import register_question
from test_research_full_cycle_outer import outer_cycle


class Driver:
    def __init__(self, store, context, peer, monkeypatch):
        self.store, self.context, self.peer, self.monkeypatch = store, context, peer, monkeypatch
        self.step = None
        self.judgment_seen = {}
        self.scopes = None

    def run(self, root, request, host):
        self.peer.host = host
        self.step = bridge._step('campaign', 'subgraph', outputs=['outputs/progress.json'])
        from ravel.controller.routes.research import loop_budget
        from ravel.workflow import research_coordinator_decisions as decisions
        # The loop budget the research route binds before CHECK-IN 1 (adaptive children only here).
        self.step.update(graph={'id': 'research.loop', 'instance': {}}, parameters={
            'research_request': deepcopy(request), 'campaign': str(root),
            'research_loop_budget': loop_budget.declare(decisions.request(request), [], tier='full')})
        plan = {'steps': [self.step], 'deliverables': [], 'waypoints': []}
        plan['sha256'] = bridge.cycle.ce.digest(plan)
        with register_question(self.monkeypatch, Path(self.context['run_dir']), plan, self.judgment_seen):
            actual = bridge.question_plan(self.store, {'original_question':
                'Compare the supplied laws through three prospective studies and all declared stages.'}, self.context)
        self.step = actual['steps'][0]
        # The controller scope that resolves the loop's ordinary effects carries the approved step's loop budget.
        self.context.update(plan_sha256=actual['sha256'], research_campaign=str(root),
                            research_loop_budget=deepcopy(self.step['parameters']['research_loop_budget']))
        # Model the parent adopting P08's sealed plan before any inner work.
        self.scopes.enter_context(bridge.bound(self.store, self.context))
        return bridge.invoke(self.store, self.step, self.context)

    def respond(self, root, request, responses, host):
        self.peer.host = host
        return bridge.invoke(self.store, self.step, {**self.context, 'responses': responses})


def run_composition(tmp_path, monkeypatch, record_property):
    store = FakeRunStore('open-question-control', root=tmp_path.parent / (tmp_path.name + '-controller-store'))
    context = {'run_dir': str(tmp_path), 'research_max_wall_seconds': 900}
    peer = FakeStep()
    driver = Driver(store, context, peer, monkeypatch)
    with installed_step(peer), ExitStack() as scopes:
        driver.scopes = scopes
        scopes.enter_context(bridge.bound(store, context))
        outer_cycle(tmp_path, monkeypatch, record_property, driver=driver)
    assert len(store.scan('research-question-plan')) == 1
    assert driver.judgment_seen['input']['request']['original_question'].startswith('Compare the supplied laws')
    assert len([row for row in peer.calls if row['step']['kind'] == 'route']) == 3
    assert all(row['step']['parameters']['own_checkin1'] for row in peer.calls if row['step']['kind'] == 'route')
    calls = store.scan('research-call')
    derived = store.scan('research-derived-step')
    assert len(derived) == len(peer.calls)
    assert {row['record']['step_sha256'] for row in derived} == {
        bridge.cycle.ce.digest(row['step']) for row in peer.calls}
    assert all(row['record']['parent_plan_sha256'] == driver.context['plan_sha256'] for row in derived)
    assert calls and len(calls) == len([row for row in peer.calls if row['step']['kind'] != 'route'])
    receipts = store.scan('research-subgraph')
    assert receipts[-1]['record']['status'] == 'completed'
    assert all(Path(row['record']['scope']).is_relative_to(store.root) for row in receipts)
    # Every coordinator cycle and every child was admitted against the approved loop budget, and every cycle's
    # decision recorded its stated reason with the projection it was shown.
    from ravel.controller.routes.research import loop_budget
    admitted = [row['record'] for row in store.scan(loop_budget.RESERVATION)]
    decided = [row['record'] for row in store.scan(loop_budget.DECISION)]
    cycles = [row for row in admitted if row['kind'] == 'cycle']
    assert cycles and len(decided) == len(cycles)
    assert all(row['reason'] and row['projected_high_usd'] > 0 and row['action'] for row in decided)
    assert len([row for row in admitted if row['kind'] == 'child']) == 3
    assert not store.scan('research-budget-boundary')
    record_property('research_loop_cycles', len(cycles))
    record_property('governed_step_calls', len(peer.calls))
    record_property('governed_role_calls', len(calls))
    assert store.checkpointer().get_tuple({'configurable': {'thread_id': store.run_id + ':research-question'}})


def test_R06_P01_P02_P03_V05_V08_C34_ROUTE_research_ROUTE_anomaly_search_MODE_research_comparison_GATE_research_choice_STAGE_limitation_census_STAGE_ideas_STAGE_baseline_STAGE_screen_STAGE_validate_STAGE_critique_to_experiments_STAGE_acceptance_STAGE_meta_review_STAGE_integrity_open_question(tmp_path, monkeypatch, record_property):
    return run_composition(tmp_path, monkeypatch, record_property)
