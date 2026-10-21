"""Thin scheduler/child admission paths; scripted processes only, zero models."""
from copy import deepcopy
import hashlib
import json
import time

import pytest

from ravel.controller import routes
from ravel.controller.confine import capability
from ravel.controller.routes.study import site
from ravel.controller.step import graph as step_graph, spec
from ravel.controller.step.services import StepHold
from ravel.controller.store import RunStore
from ravel.workflow import wms_site
from ravel.workflow.graphs import DeliveryRequired
from test_batch_jobs_standin import scheduler, _descriptor  # noqa: F401
from test_p04_support import (graphs, run_env, services_installed, make_step, run_step, records)  # noqa: F401


class OwnedStaffingGap(AssertionError):
    """Keep unrelated source/admission assertions outside the owned xfail."""


def test_one_batch_submission_returns_through_original_script_custody(tmp_path, scheduler):
    """One capability admission, one actual stand-in job, one original return."""
    store = RunStore('batch-path', root=tmp_path / 'protected')
    descriptor = _descriptor(tmp_path, 'unit', 'printf "generic return\\n" > result.txt')
    script = tmp_path / 'work/unit.sh'
    script.write_text('# properties = {"rule": "task_unit", "threads": 1}\n' + script.read_text())
    sha = hashlib.sha256(script.read_bytes()).hexdigest()
    token = capability.mint_capability(store, 'batch-unit', {
        'workflow_dir': str(script.parent), 'tasks': ['unit'], 'max_jobs': 1, 'jobscript_sha256': sha})
    submissions = []
    with site.trusted_launch(store, 'batch-unit', token, {'jobscript': {'path': str(script), 'sha256': sha}}):
        # Foreign bytes are rejected at the real hand-off, before the scheduler.
        foreign = tmp_path / 'work/foreign.sh'
        foreign.write_text(script.read_text() + '# different source\n')
        with pytest.raises(ValueError, match='script|digest|bytes'):
            site.require_capability(foreign)
            submissions.append(scheduler('condor_submit', '-terse', descriptor))
        assert submissions == [] and store.scan('wms-submission') == []
        authorized = site.require_capability(script)
        assert authorized['submissions'] == 1
        response = scheduler('condor_submit', '-terse', descriptor)
        job = response.stdout.split()[0].split('.')[0] + '.0'
        submissions.append(job)
        store.append('study-site-job', {'launch_id': 'batch-unit', 'job': job, 'scheduler': 'htcondor',
                                        'jobscript_sha256': sha})
        with pytest.raises(ValueError, match='all were submitted'):
            site.require_capability(script)
    assert len(submissions) == len(store.scan('wms-submission')) == 1
    deadline = time.monotonic() + 15
    observation = wms_site.observe_job(job)
    while observation['state'] in ('pending', 'running') and time.monotonic() < deadline:
        time.sleep(.05)
        observation = wms_site.observe_job(job)
    assert observation['state'] == 'exited' and observation['raw'].split()[:2] == ['4', '0'], observation
    assert (tmp_path / 'work/result.txt').read_text() == 'generic return\n'
    assert hashlib.sha256(script.read_bytes()).hexdigest() == sha
    scheduler_state = json.loads(scheduler.state.read_text())
    assert len(scheduler_state['jobs']) == 1


def test_batch_route_declares_only_the_expected_reconciliation_seats():
    plan = routes.compile(routes.find('study.site'), {'deliverables': [], 'constraints': [], 'facts': []},
                          {'task_mode': 'calculation'})
    assert [(s['id'], s.get('role'), (s.get('graph') or {}).get('id')) for s in plan['steps']] == [
        ('inspect', 'coordinator', None), ('specify', 'coordinator', None),
        ('prepare-child', 'coordinator', None), ('operate', 'analysis-author', None),
        ('reconcile', 'coordinator', None), ('operation-review', None, 'review.points'),
        ('synthesize', 'coordinator', None)]


def test_research_child_missing_handoff_field_refuses_before_any_child(run_env, graphs):
    candidate = make_step('research-child-unit', kind='route', role=None,
                          parameters={'own_checkin1': True}, outputs=())
    candidate['route'] = 'study'
    del candidate['inputs']
    with pytest.raises(StepHold) as refused:
        spec.check(candidate)
    assert refused.value.reason == 'step_spec_invalid'
    assert records(run_env.store, 'step-dispatch') == []
    assert records(run_env.store, 'step-launch') == []


@pytest.mark.xfail(strict=True, raises=DeliveryRequired,
                   reason='CHILDREN #16: adaptive research consumer rejects the production routed outcome')
def test_research_child_route_runs_ordinary_consumer_before_return(tmp_path, run_env, graphs, record_property):
    """A valid approved child reaches its bridge with the real step's typed return."""
    from ravel.controller import step as governed
    from ravel.workflow import research_controller as bridge, science
    from p11_fakes import FakeStep, installed_step
    from test_p11_mode import setup, approve
    from test_p04_support import install_plan, context
    child_root = tmp_path / 'child-control'
    child_root.mkdir()
    root, child, experiment, store, parent_context, source = setup(child_root)
    approve(child, experiment['study'])
    assert science.verify_plan(child, approved=True)
    original_run = governed.run
    peer = FakeStep()
    received = []

    def actual_route_outcome(parent_store, prepared, child_context):
        assert prepared['kind'] == 'route' and prepared['route'] == 'study'
        assert prepared['parameters']['own_checkin1'] is True
        assert prepared['parameters']['specification'] == source
        # Give the governed-step interface its own approved one-step plan. The
        # bridge has already verified its derived applied view in the parent.
        scientific = deepcopy(prepared)
        for key in spec.APPLIED_STEP_KEYS:
            scientific.pop(key, None)
        sha = install_plan(run_env.store, [scientific], run_dir=run_env.run_dir)
        result = original_run(run_env.store, scientific, context(run_env.store, run_env.run_dir, sha))
        received.append(deepcopy(result))
        record_property('research_child_actual', json.dumps(result, sort_keys=True))
        return result

    peer.run = actual_route_outcome
    with installed_step(peer), bridge.bound(store, parent_context):
        try:
            code = bridge.run_child(root, experiment)
        except DeliveryRequired:
            # Only the known missing consumer is expected; fixture/admission
            # errors remain ordinary failures under this strict marker.
            assert len(received) == 1 and received[0]['status'] == 'escalated'
            assert received[0]['reason'] == 'route'
            raise
    assert code == 0
    assert science.execution.load_execution(child)['stages']['science']['status'] == 'succeeded'


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason='CHILDREN #111: literature.scout lacks its original-campaign controller service binder')
def test_literature_controller_handoff_has_an_original_campaign_consumer():
    # Pure binder census only: the actual literature graph's inert scout/cards
    # path is exercised separately, without repeating a sandbox survey.
    assert 'literature.scout' in step_graph.SUBGRAPH_BINDERS


def test_primary_derivation_review_dispatches_its_required_rederiver(tmp_path):
    from ravel.workflow.graphs import review
    request = {'agent_layer_epoch': 2,
        'nodes': [{'id': 'derive', 'kind': 'operation', 'operation': 'resonance-width'}],
        'claims': [{'id': 'claim', 'primary': True, 'inherits': ['derive']}], 'inputs': [], 'edges': []}
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    raw = (json.dumps(request, sort_keys=True) + '\n').encode()
    (inputs / 'plan.json').write_bytes(raw)
    (inputs / 'task_contract.json').write_text(json.dumps({'agent_layer_epoch': 2, 'request_plan': {
        'path': 'inputs/plan.json', 'sha256': hashlib.sha256(raw).hexdigest()}}))
    from ravel.workflow import spawn_rows
    selected = [p for p in spawn_rows.derive(request) if p['row'] == 'K7']
    assert len(selected) == 1 and [s['role'] for s in selected[0]['roles']] == ['re-deriver']
    population = review.derive(tmp_path, selected[0]['when']['at'], 1)
    roles = [i['role'] for i in population['items'] if i['point_id'] == selected[0]['id']]
    if roles != ['re-deriver']:
        raise OwnedStaffingGap('CHILDREN #113: expected re-deriver, observed ' + repr(roles))
