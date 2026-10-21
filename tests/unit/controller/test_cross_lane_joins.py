"""Joins between the controller graph (P01), the governed step (P04), engagement (P18) and the study route (P10).

Each package proves its own side against a stand-in for its peer; these cases run the installed peers together:
a credited ``revise`` from the real governed step becomes the controller's bounded correction of its producer; one
applied engagement view is pinned by the controller and bound by the governed step under both plan identities; a
site step runs once, inside the controller's own substrate invocation, through the study route's real dispatcher.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import types
from types import SimpleNamespace

import pytest

import fakes
from ravel.controller import graph, routes
from ravel.controller.step import operations
from ravel.controller.step.services import StepHold
from ravel.workflow import graph_nodes

from test_p01_graph import ANALYSIS_REQUEST, _dispatched, _site_spec, controller  # noqa: F401  (fixture)
from test_p04_support import (FakeStore, graphs, inert_worker, install_plan, make_step, run_env, run_step,  # noqa: F401
                              services_installed)


# ---- producer -> credited revise -> correction ---------------------------------------------------------------------

def _rounds(n):
    """The judgment policy's review rounds for the run's mode (the first review is a round)."""
    return SimpleNamespace(bounds=lambda mode: {"review_rounds": n})


def test_a_credited_revise_of_the_governed_step_is_corrected_by_the_controller_within_its_bound(
        run_env, inert_worker, graphs):
    step = make_step('produce', review=['integrity-auditor'])
    inert_worker.scenario(seats={'integrity-auditor': {'items': [{'severity': 'A', 'summary': 'value needs repair'}]}})
    first = run_step(run_env, step)
    assert first['status'] == 'revise' and first['review']['credited'] is True, first
    [finding] = first['review']['findings']
    stored = run_env.store.read(graph.FINDINGS, finding)
    # The controller folds the step's own outcome: a correction round that pins the step's protected findings.
    with graph.services(judgment=_rounds(2)):
        row, _, hold = graph.fold_outcome({'mode': {}, 'steps': {}}, run_env.store, None, step, 1,
                                          {'results': {'step': first}}, {})
    assert hold is None and row['status'] == graph.CORRECT and row['corrections'] == 1, row
    correction = row['correction']
    assert (correction['round'], correction['rounds'], correction['verdict']) == (1, 1, 'revise')
    assert correction['findings'] == [{'record': finding, 'kind': graph.FINDINGS, 'digest': stored['digest'],
                                       'verdict': 'revise', 'subject_sha256': stored['record'].get('subject_sha256')}]
    # Past the bound the same revise holds; it never completes the step.
    with graph.services(judgment=_rounds(2)):
        row2, _, hold2 = graph.fold_outcome({'mode': {}, 'steps': {'produce': {'corrections': 1}}}, run_env.store,
                                            None, step, 2, {'results': {'step': first}}, {})
    assert row2['status'] == 'held' and hold2['reason'] == 'review_rounds_exhausted', (row2, hold2)
    # The corrected attempt runs with the round pinned, its review accepts, and the controller completes the step.
    # The producer writes the corrected value; the reviewer seat writes its own declared outputs and finds nothing.
    inert_worker.scenario(writes=[{'path': 'outputs/result.json', 'content': '{"value": 2}'}],
                          seats={'integrity-auditor': {'writes': None}})
    second = run_step(run_env, step, attempt=2, correction=correction)
    assert second['status'] == 'completed' and second['review']['verdict'] == 'accept', (
        second['status'], second.get('reason'), second.get('review'))
    with graph.services(judgment=_rounds(2)):
        row3, _, hold3 = graph.fold_outcome({'mode': {}, 'steps': {'produce': {'corrections': 1}}}, run_env.store,
                                            None, step, 2, {'results': {'step': second}}, {})
    assert hold3 is None and row3['status'] == 'completed' and row3['corrections'] == 1, row3


# ---- applied-view identity: P01 pins it, P18 checks it, P04 binds it -----------------------------------------------

@pytest.fixture
def scientific(tmp_path, monkeypatch):
    from ravel.controller import engagement
    from ravel.controller.engagement import policy
    from test_p18_records import fakes as engagement_fakes
    monkeypatch.setattr(engagement, '_operator', lambda: {})
    # The fixture store carries no frozen operating mode record (no issuer home): decide reads none.
    from ravel.controller import authority
    monkeypatch.setattr(authority, 'frozen', lambda store, required=False: None)
    store = FakeStore(tmp_path / 'store')
    step = make_step('s1', inputs=[{'artifact': 'inputs/source.json'}], parameters={'scope': {'quantity': 'supplied'}})
    install_plan(store, [step])
    entry = store.scan('plan')[-1]
    plan = json.loads(store.get_blob(entry['record']['blob']))
    seat_plan = policy.seat_plan

    def with_instructions(*args, **kwargs):
        kwargs.setdefault('instructions', graph.service('instructions'))
        return seat_plan(*args, **kwargs)
    monkeypatch.setattr(policy, 'seat_plan', with_instructions)
    pins = {'sha256': plan['sha256'], 'blob': entry['record']['blob'], 'record_id': entry['id']}
    # Only instruction transport is inert (the catalogue's check-in selectors are the instruction owner's).
    with graph.services(instructions=engagement_fakes.FakeInstructions):
        decision = engagement.decide(store, {'plan': plan})
        yield store, plan, pins, decision, engagement.apply(plan, decision)


def test_the_applied_view_the_controller_pins_is_the_one_the_governed_step_binds(scientific):
    from ravel.controller import engagement
    store, plan, pins, decision, applied = scientific
    assert engagement.check_applied(applied, decision) == [] and applied['sha256'] == plan['sha256']
    assert applied != plan
    pinned = graph.install_applied_plan(store, pins, applied)
    assert pinned['sha256'] == plan['sha256'] and pinned['blob'] == pins['blob']
    assert pinned['applied_sha256'] == applied['engagement']['applied_sha256']
    # The controller reads the view under both identities; the scientific plan keeps its own bytes.
    assert graph.current_plan({'plan': pinned}, store) == applied
    assert graph.scientific_plan({'plan': pinned}, store) == plan
    # The governed step binds a step of the same view, under the scientific digest and the view's own digest.
    context = {'plan_sha256': plan['sha256'], 'applied_sha256': pinned['applied_sha256']}
    assert operations.current_plan(store, context) == applied
    step = deepcopy(applied['steps'][0])
    approved, sha, binding = operations.plan_step(store, step, context)
    assert approved == step and sha == plan['sha256'] and binding == 'plan_step'
    # A stale view digest in the step context refuses.
    with pytest.raises(StepHold) as stale:
        operations.current_plan(store, {**context, 'applied_sha256': '0' * 64})
    assert stale.value.reason == 'engagement_view_invalid'


def test_a_changed_applied_view_is_refused_by_the_controller_and_the_governed_step(scientific):
    store, plan, pins, decision, applied = scientific
    changed = deepcopy(applied)
    changed['steps'][0].setdefault('parameters', {})['scope'] = {'quantity': 'changed'}
    with pytest.raises(graph.nodes.RecoveryHold) as refused:
        graph.install_applied_plan(store, pins, changed)
    assert refused.value.reason == 'applied_plan_mismatch'
    # Pinned behind the controller's back, the changed view is refused where the governed step reads it.
    record = deepcopy(store.read('plan', pins['record_id'])['record'])
    record.update(applied_blob=store.put_blob(json.dumps(changed).encode()),
                  applied_sha256=changed['engagement']['applied_sha256'])
    store.append('plan', record)
    with pytest.raises(StepHold) as held:
        operations.current_plan(store, {'plan_sha256': plan['sha256'],
                                        'applied_sha256': changed['engagement']['applied_sha256']})
    assert held.value.reason == 'engagement_view_invalid'


# ---- a site operate step through the substrate's own invocation and the study route's dispatcher ------------------

JOBSCRIPT = b'#!/bin/sh\n# inert site payload: never submitted to a scheduler here\n'


def _site_join(monkeypatch, tokens):
    """The study route's real dispatcher behind a fixture route adapter, the confinement capability and operator stop
    boundaries stood in (their own tests prove minting and stop state; this fixture run is running), and every
    substrate child invocation recorded with the capability it ran under."""
    from ravel.controller import authority, confine
    monkeypatch.setattr(authority, 'stop_state', lambda store: 'running')
    from ravel.controller.routes import study
    from ravel.controller.routes.study import site

    def mint(store, launch_id, scope):
        token = 'inert-token-' + launch_id
        if token in tokens:
            raise ValueError('launch already minted')
        tokens[token] = deepcopy(scope)
        return token
    monkeypatch.setattr(confine, 'mint_capability', mint, raising=False)

    def dispatch(step, context, invoke):
        if step['id'] != 'operate':
            return invoke()
        path = Path(context['run_dir']) / step['parameters']['launch']['jobscript']['path']
        if not path.exists():  # the approved jobscript is a pinned input of the run
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(JOBSCRIPT)
        return site.dispatch(context['store'], step, context, invoke)

    module = types.ModuleType('ravel.controller.routes.fixture_adapter')
    module.packet_context, module.dispatch = study.packet_context, dispatch
    monkeypatch.setitem(sys.modules, 'ravel.controller.routes.fixture_adapter', module)
    invocations = []
    real = graph_nodes._invoke_child

    def invoke_child(compiled, child_input, key):
        step = child_input.get('step') or {}
        bound = site._launch.get()
        invocations.append({'step': step.get('id'), 'key': key,
                            'capability': bound['launch_id'] if bound else None})
        return real(compiled, child_input, key)
    monkeypatch.setattr(graph_nodes, '_invoke_child', invoke_child)
    return invocations


def _join_spec(jobscript=True):
    spec = _site_spec(jobscript=False)
    operate = spec['steps'][0]
    operate['parameters'] = {'wms_scope': {'workflow_dir': 'inputs/site'}, 'launch': {}}
    if jobscript:
        operate['parameters']['launch']['jobscript'] = {'path': 'inputs/site/job.sh',
                                                        'sha256': hashlib.sha256(JOBSCRIPT).hexdigest()}
    return spec


def test_a_site_operate_step_runs_once_inside_the_substrate_invocation_under_its_capability(controller, monkeypatch):
    tokens = {}
    invocations = _site_join(monkeypatch, tokens)
    with routes.registered(_join_spec(), only=True), fakes.installed():
        store, observation = fakes.drive_request(controller, ANALYSIS_REQUEST)
    values = fakes.final_state(store)
    assert values['steps']['operate']['status'] == 'completed', values['steps']['operate']
    # One capability minted for the approved scope; the step ran once, within the parent's own child invocation of
    # its map item, while the study dispatcher held that capability.
    assert list(tokens) == ['inert-token-operate'] and tokens['inert-token-operate']['max_jobs'] == 1
    [site] = [i for i in invocations if i['step'] == 'operate']
    assert site['key'] == 'operate@1' and site['capability'] == 'operate', invocations
    assert _dispatched().count('operate') == 1
    events = [r['record']['event'] for r in store.scan('study-site') if r['record'].get('launch_id') == 'operate']
    assert events == ['reserved', 'dispatch_started', 'outcome'], events
    # The other step went through the same hook without a capability.
    assert [i['capability'] for i in invocations if i['step'] == 's1'] == [None]


def test_a_site_operate_step_without_its_jobscript_pin_is_refused_before_any_invocation(controller, monkeypatch):
    tokens = {}
    invocations = _site_join(monkeypatch, tokens)
    with routes.registered(_join_spec(jobscript=False), only=True), fakes.installed():
        store, observation = fakes.drive_request(controller, ANALYSIS_REQUEST)
    values = fakes.final_state(store)
    assert values['steps']['operate']['status'] == 'held', values['steps']['operate']
    assert values['holds']['operate']['reason'] == 'route_dispatch_refused', values['holds']['operate']
    assert 'operate' not in [i['step'] for i in invocations] and 'operate' not in _dispatched()
    assert tokens == {} and store.scan('study-site') == []
