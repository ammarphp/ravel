"""Engagement execution: the controller's own producers feed the engagement monitor (P18) from real records.

Real governed-step (P04) records of a scripted inert worker reach the engagement envelope at the controller's wave
join (P01). Usage the transport metered with its cache split passes every floor. Unreported or zero usage, a seat
dispatched without its session, a packet the session did not take in, one session carrying the calls and model
requests the controller cannot attribute each fail their floor (H1-H5), raise engagement and hold every later wave.
Each trigger E1-E8 fires from the producer that observes it: the controller's join folding the governed step's
outcomes, credit and attempts, the judgment records and settlements it reads, its envelope check and the judgment
wave review. The tier never falls. The scripted worker calls no model and no native science runs.
"""
from __future__ import annotations

from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

import ravel.controller.judgment as REAL_JUDGMENT
from ravel.controller import graph, ledger as REAL_LEDGER
from ravel.controller.engagement.records import TIERS
from ravel.controller.judgment import graph as judgment_graph
import test_p04_support as support
from test_p04_support import FakeStore, context, graphs, install_plan, make_step, run_env, services_installed  # noqa: F401

_SPEC = spec_from_file_location('p18_execution_fakes', Path(__file__).parents[2] / 'fixtures/engagement/fakes.py')
p18 = module_from_spec(_SPEC)
_SPEC.loader.exec_module(p18)

# The scripted worker reports the usage its scenario names: the transport's split of the input it took in (uncached
# input, cache writes, cache reads), none at all, zeros, or less than its packet.
METERED = '''def metered(scenario, prompt):
    mode = scenario.get('usage', 'split')
    if mode == 'none':
        return {{}}
    if mode == 'zero':
        return {{'usage': {{'input_tokens': 0, 'output_tokens': 0}}}}
    if mode == 'under':
        return {{'usage': {{'input_tokens': 5, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0,
                          'output_tokens': 10}}}}
    return {{'usage': {{'input_tokens': 10, 'cache_creation_input_tokens': len(prompt) // 4 + 50,
                      'cache_read_input_tokens': 100, 'output_tokens': 30}}}}
'''
REPORTED = "'total_cost_usd': 0.0,\n    'usage': {{'input_tokens': 100, 'output_tokens': 20}},"


def _script():
    assert REPORTED in support.FAKE_CLAUDE, 'the scripted worker of the step support changed its usage report'
    body = support.FAKE_CLAUDE.replace(REPORTED, "'total_cost_usd': scenario.get('cost', 0.0),\n    "
                                                 "**metered(scenario, prompt),")
    head, tail = body.split("print(json.dumps({{'type': 'result'", 1)
    return head + METERED + "print(json.dumps({{'type': 'result'" + tail


@pytest.fixture
def worker(run_env, monkeypatch):
    """The scripted ``claude`` on a trusted test PATH, probed and qualified, with the step support's inert seams."""
    from ravel.workflow import agent_worker, sandbox, transport_registry as tr
    root, bin_dir = run_env.root, run_env.root / 'bin'
    monkeypatch.setenv('HOME', str(root / 'home'))
    monkeypatch.setenv('PATH', f'{bin_dir}:/usr/bin:/bin')
    monkeypatch.setenv('RAVEL_TEST_TRUSTED_BIN', str(bin_dir))
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(root / 'claude-login'))
    (bin_dir / 'help.txt').write_text('Usage\n' + '\n'.join(f'  {f} <x>' for f in support.FLAGS))
    executable = bin_dir / 'claude'
    executable.write_text(_script().format(python=sys.executable, model=support.MODEL))
    executable.chmod(0o755)

    def scenario(**values):
        (bin_dir / 'scenario.json').write_text(json.dumps(values))
    scenario()
    monkeypatch.setattr(sandbox, 'available', lambda: 'inert-test-seam')
    monkeypatch.setattr(sandbox, 'probe', lambda *a, **k: {'backend': 'inert-test-seam', 'confirmed': True})
    monkeypatch.setattr(sandbox, 'command', lambda ws, argv, **k: list(argv))
    record = tr.probe('claude-cli-worker', executable=str(executable))
    assert not record['unusable'], record
    support.qualify(run_env.store, record)
    real_popen = subprocess.Popen

    def popen(argv, **kwargs):
        if 'ravel.workflow.agent_worker' in argv and 'supervise' in argv:
            return support._Supervisor()
        return real_popen(argv, **kwargs)
    monkeypatch.setattr(agent_worker.subprocess, 'Popen', popen)
    real_wait = agent_worker._wait_for_completion

    def wait(run, spec, *, wait):
        if not agent_worker._record(run, spec['node_id'], spec['attempt'])['receipt']:
            agent_worker.supervise(run, spec['node_id'], spec['attempt'])
        return real_wait(run, spec, wait=wait)
    monkeypatch.setattr(agent_worker, '_wait_for_completion', wait)
    real_alive = agent_worker._group_alive
    monkeypatch.setattr(agent_worker, '_group_alive',
                        lambda pgid: False if pgid in (os.getpgrp(), support._Supervisor.pid) else real_alive(pgid))
    monkeypatch.setattr(agent_worker.signal, 'signal', lambda *a: None)
    return SimpleNamespace(scenario=scenario)


@pytest.fixture
def applied(run_env, worker, graphs, monkeypatch):  # noqa: F811  (fixture)
    """A plan decided and applied by the installed engagement package, its view pinned beside the scientific plan;
    each step of the view runs through the installed governed step graph. Only instruction transport is inert."""
    from ravel.controller import engagement
    from ravel.controller.engagement import policy
    from test_p18_records import fakes as engagement_fakes
    monkeypatch.setattr(engagement, '_operator', lambda: {})
    monkeypatch.setattr(graph, '_BROKER_COUNTER', [], raising=False)
    seat_plan = policy.seat_plan

    def with_instructions(*args, **kwargs):
        kwargs.setdefault('instructions', graph.service('instructions'))
        return seat_plan(*args, **kwargs)
    monkeypatch.setattr(policy, 'seat_plan', with_instructions)

    class Run:
        def __init__(self, steps):
            self.store = run_env.store
            install_plan(self.store, steps)
            entry = self.store.scan('plan')[-1]
            plan = json.loads(self.store.get_blob(entry['record']['blob']))
            pins = {'sha256': plan['sha256'], 'blob': entry['record']['blob'], 'record_id': entry['id']}
            self.decision = engagement.decide(self.store, {'plan': plan})
            self.view = engagement.apply(plan, self.decision)
            self.pins = graph.install_applied_plan(self.store, pins, self.view)
            self.context = context(self.store, run_env.run_dir, plan['sha256'],
                                   applied_sha256=self.pins['applied_sha256'])

        def run(self, step_id, **scenario):
            from ravel.controller import step as governed
            worker.scenario(**scenario)
            step = next(s for s in self.view['steps'] if s['id'] == step_id)
            return governed.run(self.store, deepcopy(step), dict(self.context))

        def records(self, kind):
            return [{**row['record'], 'record_id': row['id']} for row in self.store.scan(kind)]

        def join(self, requests=None):
            """The controller's wave join on these records, under the installed ledger's composition."""
            monkeypatch.setitem(sys.modules, 'ravel.controller.ledger', REAL_LEDGER)
            if requests is not None:
                graph.register_broker_counter(lambda store: {'requests': requests})
            return graph.envelope_wave({}, self.store)

    with graph.services(instructions=engagement_fakes.FakeInstructions):
        yield Run


def _calls(run):
    return sum(r['usage']['turns'] for r in run.records('step-observation') if (r.get('usage') or {}).get('turns'))


# ---- floors on real governed-step records --------------------------------------------------------------------------

def test_metered_split_usage_passes_every_floor_and_holds_no_wave(applied):
    from ravel.controller import engagement
    from ravel.controller.step import graph as step_graph
    run = applied([make_step('s1')])
    outcome = run.run('s1', turns=3)
    assert outcome['status'] == 'completed', outcome
    [dispatched] = run.records('step-dispatch')
    [observed] = run.records('step-observation')
    [delivered] = [r for r in run.records('instruction-delivery') if r.get('kind') == 'instruction-delivery-session']
    # The governed step keeps the exact seat identity, the packet size and the transport's own meter split.
    identity = lambda row: (row['node_id'], row.get('seat'), row['attempt'])  # noqa: E731
    assert identity(dispatched) == identity(observed) == identity(delivered)
    assert dispatched['packet_tokens'] == observed['packet_tokens'] == delivered['packet_tokens'] > 0
    assert observed['meter']['split'] == 'complete' and observed['final_record_returned'] is True
    raw = observed['usage']['raw']
    assert set(raw) == {'input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'}
    assert sum(raw.values()) == observed['usage']['input_tokens'] >= dispatched['packet_tokens']
    assert step_graph._usage_row(observed, observed['record_id'])['EG07']['status'] == 'satisfied'
    check, raised = run.join(requests=_calls(run))
    assert all(check['floors'][f]['status'] == 'ok' for f in ('H1', 'H2', 'H3', 'H4', 'H5')), check['floors']
    assert check['broker']['available'] is True and not check['hold'] and not check['failures']
    assert raised == [] and graph.engagement_hold(run.store) is None
    assert engagement.tier(run.store) == run.decision['tier']


CASES = {'unreported': ('H1', 1), 'zero': ('H2', 1), 'under_read': ('H2', 1), 'one_call': ('H3', 1),
         'omitted_seat': ('H1', 1), 'concentration': ('H4', 4), 'surplus': ('H5', 1)}


@pytest.mark.parametrize('case', sorted(CASES))
def test_a_floor_breach_on_real_records_raises_engagement_and_holds_every_later_wave(applied, case):
    from ravel.controller import engagement
    from ravel.controller.step import graph as step_graph
    floor, count = CASES[case]
    run = applied([make_step(f's{i}') for i in range(1, count + 1)])
    scenario = {'unreported': {'usage': 'none'}, 'zero': {'usage': 'zero'}, 'under_read': {'usage': 'under'},
                'one_call': {'turns': 1}, 'concentration': {'turns': 40}}.get(case, {})
    run.run('s1', **{'turns': 3, **scenario})
    for i in range(2, count + 1):
        run.run(f's{i}', turns=2)
    if case == 'omitted_seat':
        # The census names a seat attempt the controller dispatched whose session was never observed.
        dispatched = run.records('step-dispatch')[-1]
        run.store.append('step-dispatch', {**{k: v for k, v in dispatched.items() if k != 'record_id'},
                                           'seat': 'step:s1:physics-critic', 'purpose': 'review',
                                           'node_id': dispatched['node_id'] + '.review', 'key': 'omitted'})
    observed = run.records('step-observation')[0]
    if case == 'unreported':
        assert observed['usage'].get('reported') is not True
        assert step_graph._usage_row(observed, observed['record_id'])['EG07']['status'] == 'violated'
    before = engagement.tier(run.store)
    check, raised = run.join(requests=_calls(run) + (3 if case == 'surplus' else 0))
    assert check['hold'] and check['floors'][floor]['status'] != 'ok', (case, check['floors'])
    reason = graph.engagement_hold(run.store)
    assert reason and reason.startswith(graph.ENGAGEMENT_HOLD + ':') and floor in reason, reason
    [escalation] = raised
    assert 'E4' in escalation['triggers'] and escalation['rereview'] is True
    assert escalation['old_tier'] == before and engagement.tier(run.store) == escalation['new_tier']
    assert TIERS.index(escalation['new_tier']) >= TIERS.index(before)
    # The breach is permanent evidence: a later wave join still holds.
    again, _ = run.join()
    assert again['hold'] and graph.engagement_hold(run.store)


def test_without_an_independent_broker_count_the_broker_floor_stays_unestablished(applied):
    run = applied([make_step('s1')])
    run.run('s1', turns=3)
    check, raised = run.join()
    assert check['broker'] == {'available': False} and check['floors']['H5']['status'] == 'ok'
    assert not check['hold'] and raised == []
    # The counter's own failure is an invalid count, never a missing one and never zero.
    graph.register_broker_counter(lambda store: (_ for _ in ()).throw(OSError('counter offline')))
    check, raised = graph.envelope_wave({}, run.store)
    assert check['floors']['H5']['status'] == 'unknown' and check['hold'] and raised


# ---- triggers from their producers; the tier never falls ------------------------------------------------------------

@pytest.fixture
def lean(tmp_path, monkeypatch):
    """A lean decision on facts pinned and credited in the store (the engagement fixtures' fictional study plan)."""
    from ravel.controller import engagement
    from ravel.controller.engagement import policy
    from ravel.controller.engagement.records import data, digest
    p18.install_fakes(monkeypatch, operator={})
    plan = p18.fictional_plan()
    installed = p18.policy_for(plan)
    monkeypatch.setattr(policy, 'load_policy', lambda: deepcopy(installed))
    monkeypatch.setattr(graph, '_BROKER_COUNTER', [], raising=False)
    store = FakeStore(tmp_path / 'store')
    store.append('plan', {'plan': plan, 'plan_sha256': plan['sha256']})
    store.append('route', {'route': 'study'})
    store.append('engagement-population', {'plan_sha256': plan['sha256'],
                                           'deliverable_ids': [d['id'] for d in plan['deliverables']]})
    method = json.loads((Path(__file__).parents[2] / 'fixtures/method_decisions/standard_table.json').read_text())
    for kind, body in (('engagement-method', {'method': method, 'scan_points': 1}),
                       ('engagement-novelty', {'value': 'N0'})):
        store.append(kind, body)
        store.append('engagement-fact-credit', {'credited': True, 'role': 'plan-critic', 'subject_sha256': digest(body),
                                                'plan_sha256': plan['sha256']})
    store.append('engagement-special', {'plan_sha256': plan['sha256'], 'complete': True, 'flags': []})
    expected = {'status': 'ready', 'floor': {'sessions': 1},
                'low': {'sessions': 1, 'calls': 1, 'input_tokens': 80, 'output_tokens': 0, 'cost_usd': 0},
                'high': {'sessions': 100, 'calls': 10000, 'input_tokens': 10 ** 6, 'output_tokens': 10 ** 6,
                         'cost_usd': 100}}
    envelopes = {'policy_sha256': installed['sha256'], 'calibration_sha256': digest(data('calibration.json')),
                 'routes': {'study': {t: deepcopy(expected) for t in ('lean', 'standard', 'full')}}}
    original = engagement.data
    monkeypatch.setattr(engagement, 'data', lambda name: deepcopy(envelopes) if name == 'envelopes.json'
                        else original(name))
    p18.projection_inputs(monkeypatch, engagement, installed)
    decision = engagement.decide(store, {'plan': plan})
    assert decision['tier'] == 'lean' and engagement.tier(store) == 'lean'
    return SimpleNamespace(store=store, plan=plan, decision=decision, monkeypatch=monkeypatch)


def _step(step_id, **extra):
    return {'id': step_id, 'kind': 'produce', 'depends_on': [], 'outputs': [], **extra}


def _fold(env, step, outcome, *, attempt=1, before=None):
    """The controller's join on one governed-step outcome: folded as the join folds it, then its trigger events."""
    state = {'steps': deepcopy(before or {}), 'mode': {}}
    row, folded, _ = graph.fold_outcome(state, env.store, None, step, attempt, {'results': {'step': outcome}},
                                        {'used': {}})
    events = graph.outcome_events(state, env.store, [{'step': step, 'attempt': attempt}], {step['id']: row},
                                  {step['id']: folded}, 'wave-result-fixture')
    return row, events, graph.observe_engagement(env.store, events)


def _outcome(step_id, status='completed', **extra):
    return {'step_id': step_id, 'attempt': extra.pop('attempt', 1), 'status': status, 'outputs': [], 'receipts': ['r'],
            'escalation': None, 'replan': None, 'budget': {}, 'judgments': [], 'review': {}, 'reason': None,
            'subject_sha256': 'b' * 64, **extra}


def _session(store, step_id, *, cost, packet=100, calls=2, observe=True, seat=None,
             parent_step=None, purpose='producer'):
    """A governed-step attempt as the step graph records it: its dispatch, instruction delivery and observation."""
    node = f'ctl.{step_id}'
    identity = {'step_id': step_id, 'node_id': node, 'seat': seat, 'attempt': 1}
    delivery = store.append('instruction-delivery', {'kind': 'instruction-delivery', 'duty_units': 4,
                                                     'packet_sha256': 'c' * 64})
    store.append('step-dispatch', {**identity, 'key': node, 'purpose': purpose, 'parent_step': parent_step,
                                   'packet_sha256': 'c' * 64,
                                   'packet_tokens': packet})
    store.append('instruction-delivery', {**identity, 'kind': 'instruction-delivery-session', 'delivery': delivery,
                                          'session': f'session-{step_id}', 'packet_sha256': 'c' * 64,
                                          'packet_tokens': packet})
    if observe:
        store.append('step-observation', {**identity, 'session_id': f'session-{step_id}', 'status': 'ok',
                                          'final_record_returned': True,
                                          'usage': {'reported': True, 'turns': calls, 'input_tokens': 2 * packet,
                                                    'output_tokens': 50, 'cost_usd': cost}})


def _triggers(raised):
    return sorted({t for record in raised for t in record['triggers']})


def test_E1_a_failure_past_its_retries_raises_engagement(lean):
    row, events, raised = _fold(lean, _step('s1'), _outcome('s1', 'failed', reason='validators_failed'))
    assert row['status'] == 'failed' and _triggers(raised) == ['E1']
    assert raised[0]['old_tier'] == 'lean' and raised[0]['new_tier'] == 'standard' and raised[0]['scope'] == 'run'


def test_E2_a_revise_or_uncredited_review_raises_engagement_and_counts_a_correction(lean):
    review = {'credited': True, 'verdict': 'revise', 'seats': [{'seat': 'seat:physics-critic:1', 'credited': True,
                                                                'verdict': 'revise'}], 'findings': []}
    row, _, raised = _fold(lean, _step('s1'), _outcome('s1', review=review))
    assert 'E2' in _triggers(raised) and raised[0]['correction_count'] == 1 and raised[0]['new_tier'] == 'standard'
    _, _, uncredited = _fold(lean, _step('s2'), _outcome('s2', 'revise', review={'credited': False, 'seats': []}))
    assert 'E2' in _triggers(uncredited) and uncredited[0]['new_tier'] == 'full'


def test_E3_a_discrepancy_from_the_judgment_wave_review_raises_engagement(lean):
    plan = {'steps': [{'id': 's1', 'class': 'R0'}]}
    event = {'event': 'flag', 'step': 's1', 'text': 'comparison outside tolerance; P5 decomposition opened',
             'replan_request': {'reason': 'discrepancy', 'step': 's1'}}
    raised = judgment_graph._engagement_event(lean.store, plan, event, 'control-0001')
    assert raised['triggers'] == ['E3'] and raised['new_tier'] == 'standard'
    anchor = dict(event, text='an anchor ratio outside its regime opened P5')
    assert judgment_graph._engagement_event(lean.store, plan, anchor, 'control-0002')['triggers'] == ['E3']
    assert judgment_graph._engagement_event(lean.store, plan, {'event': 'step_state', 'step': 's1',
                                                               'status': 'closed'}, 'control-0003') is None


@pytest.mark.parametrize('outcome,expected', [
    (dict(escalation='decision_block'), 'E4'),
    (dict(escalation='new_experiment_required', replan={'reason': 'fixture'}), 'E4'),
    (dict(status='held', reason='route_dispatch_refused'), 'E4')])
def test_E4_an_anomaly_on_a_branch_raises_engagement(lean, outcome, expected):
    outcome = dict(outcome)
    status = outcome.pop('status', 'completed')
    _, events, raised = _fold(lean, _step('s1'), _outcome('s1', status, **outcome))
    assert _triggers(raised) == [expected] and raised[0]['new_tier'] == 'standard'


def test_E4_an_envelope_floor_breach_on_a_completed_session_raises_engagement_and_holds(lean):
    _session(lean.store, 's1', cost=0.01)
    _session(lean.store, 's2', cost=0.01, observe=False)  # dispatched, never observed
    check, raised = graph.envelope_wave({}, lean.store)
    assert check['hold'] and check['floors']['H1']['status'] == 'below_floor'
    assert _triggers(raised) == ['E4'] and raised[0]['new_tier'] == 'standard'
    assert graph.engagement_hold(lean.store).startswith(graph.ENGAGEMENT_HOLD)


@pytest.mark.parametrize('found,trigger,tier', [('R2', 'E5', 'standard'), ('R3', 'E6', 'full')])
def test_E5_E6_a_decision_recorded_above_its_planned_class_raises_engagement(lean, found, trigger, tier):
    # The judgment service's stored record of the decision (its class is the judgment package's classification).
    lean.monkeypatch.setitem(sys.modules, 'ravel.controller.judgment', REAL_JUDGMENT)
    judged = lean.store.append(REAL_JUDGMENT.records.KIND, {'step': 's1', 'class': found, 'record_sha256': 'd' * 64})
    _, _, raised = _fold(lean, _step('s1', kind='decide', consequence_class='R0'),
                         _outcome('s1', judgments=[judged]))
    assert _triggers(raised) == [trigger] and raised[0]['new_tier'] == tier
    assert raised[0]['requires_rdj'] is (trigger == 'E5') and raised[0]['requires_authority'] is (trigger == 'E6')
    # The judgment route's wave review classifies its decisions the same way (one hook, its own record event).
    record = {'event': 'record', 'step': 's2', 'class': found, 'judgment_id': 'j2', 'record_sha256': 'e' * 64}
    hooked = judgment_graph._engagement_event(lean.store, {'steps': [{'id': 's2', 'class': 'R1'}]}, record, 'c-1')
    assert hooked['triggers'] == [trigger]
    planned = judgment_graph._engagement_event(lean.store, {'steps': [{'id': 's3', 'class': found}]},
                                               dict(record, step='s3'), 'c-2')
    assert planned is None  # a class the plan already declared is not a new call


def test_E7_a_mechanical_retry_that_passes_is_recorded_and_a_second_rereviews_its_step(lean):
    before = {'s1': {'status': 'running', 'attempts': 2, 'reason': 'final_record_schema,instruction_ack'}}
    _, _, first = _fold(lean, _step('s1'), _outcome('s1', attempt=2), attempt=2, before=before)
    assert _triggers(first) == ['E7'] and first[0]['scope'] == 'step' and first[0]['new_tier'] == 'lean'
    _, _, second = _fold(lean, _step('s1'), _outcome('s1', attempt=3, subject_sha256='f' * 64), attempt=3,
                         before={'s1': {**before['s1'], 'attempts': 3}})
    assert _triggers(second) == ['E7'] and second[0]['rereview'] is True and second[0]['new_tier'] == 'standard'
    from ravel.controller import engagement
    assert engagement.tier(lean.store) == 'lean'  # a step-scoped re-review raises no run tier


def test_E8_a_session_above_twice_its_envelope_is_recorded_and_notified_only(lean):
    from ravel.controller import engagement
    _session(lean.store, 's1', cost=1000.0)
    _session(lean.store, 's2', cost=0.0001)
    events = graph.cost_events(lean.store, [{'step': _step('s1'), 'attempt': 1}, {'step': _step('s2'), 'attempt': 1}])
    assert [e['step_id'] for e in events] == ['s1'] and events[0]['cost_usd'] > 2 * events[0]['expected_cost_usd']
    raised = graph.observe_engagement(lean.store, events)
    assert _triggers(raised) == ['E8'] and raised[0]['notify'] is True and raised[0]['new_tier'] == 'lean'
    assert engagement.tier(lean.store) == 'lean'



def test_a_derived_review_cost_is_attributed_to_its_parent_wave(lean):
    _session(lean.store, 's1.review.one', parent_step='s1', purpose='review',
             seat='seat:integrity-auditor:1', cost=1000.0)
    events = graph.cost_events(lean.store, [{'step': _step('s1'), 'attempt': 1}])
    assert len(events) == 1
    assert events[0]['step_id'] == 's1'
    assert events[0]['cost_usd'] > 2 * events[0]['expected_cost_usd']
    assert graph.cost_events(lean.store, [{'step': _step('s2'), 'attempt': 1}]) == []


def test_the_tier_never_falls_across_every_producer(lean):
    from ravel.controller import engagement
    tiers = [engagement.tier(lean.store)]
    plan = {'steps': [{'id': 's9', 'class': 'R0'}]}
    producers = [
        lambda: _fold(lean, _step('s1'), _outcome('s1', attempt=2), attempt=2,
                      before={'s1': {'status': 'running', 'reason': 'card_output_schema'}})[2],
        lambda: graph.observe_engagement(lean.store, graph.cost_events(lean.store, [{'step': _step('s1'), 'attempt': 1}])),
        lambda: _fold(lean, _step('s2'), _outcome('s2', 'failed', reason='validators_failed'))[2],
        lambda: [judgment_graph._engagement_event(lean.store, plan, {'event': 'step_state', 'step': 's9',
                                                                     'status': 'held'}, 'c-9')],
        lambda: graph.envelope_wave({}, lean.store)[1],
        lambda: _fold(lean, _step('s3'), _outcome('s3', escalation='stop'))[2],
    ]
    _session(lean.store, 's1', cost=1000.0)
    for produce in producers:
        for record in [r for r in produce() if r]:
            assert TIERS.index(record['new_tier']) >= TIERS.index(record['old_tier'])
        tiers.append(engagement.tier(lean.store))
    assert all(TIERS.index(b) >= TIERS.index(a) for a, b in zip(tiers, tiers[1:])), tiers
    assert tiers[0] == 'lean' and tiers[-1] == 'full'
    # Rendering the decision again changes nothing: the run's tier does not fall.
    engagement.decide(lean.store, {'plan': lean.plan})
    assert engagement.tier(lean.store) == 'full'


# ---- the decision at CHECK-IN 1 and its applied view --------------------------------------------------------------

def test_the_checkin_decision_is_shown_and_its_applied_view_pinned_once_with_its_rows(lean):
    from ravel.controller import engagement
    store, plan = lean.store, lean.plan
    blob = graph._put_json(store, plan)
    record = store.append('plan', {'plan_sha256': plan['sha256'], 'blob': blob, 'source': 'fixture', 'revision': 0,
                                   'route': 'study'})
    REAL_LEDGER.materialise(store, 'intake', {'run_id': store.run_id, 'route': 'study'})
    REAL_LEDGER.materialise(store, 'plan', {'plan': plan, 'route': 'study'})
    pins = {'sha256': plan['sha256'], 'blob': blob, 'record_id': record}
    pinned = graph.engage({'plan': pins}, store)
    decision = graph.engagement_decision(store, plan['sha256'])
    assert decision['record_id'] == lean.decision['record_id'] and decision['tier'] == 'lean'
    assert pinned['sha256'] == plan['sha256'] and pinned['blob'] == blob and pinned['applied_sha256']
    assert graph.current_plan({'plan': pinned}, store) == engagement.apply(plan, engagement.effective_decision(store))
    plans = len(store.scan('plan'))
    assert graph.engage({'plan': pinned}, store) == pinned and len(store.scan('plan')) == plans  # once
    rows = {r['entry'].split('@', 1)[0]: r for node in graph.ENGAGEMENT_ROWS
            for r in REAL_LEDGER.current(store, node=node)}
    assert {k for k, r in rows.items() if r['status'] == 'satisfied'} >= {'EG01', 'EG02', 'EG03', 'EG06'}, rows
    assert rows['EG03']['evidence']['record'] == pinned['record_id']
    section = graph.engagement_section(decision)
    text = '\n'.join(section['lines'])
    assert section['id'] == 'engagement' and 'Tier lean' in text and 'Projected usage at lean' in text
    for reason in decision['reasons']:
        assert f"Fact {reason['fact']}:" in text and str(reason['source']) in text
