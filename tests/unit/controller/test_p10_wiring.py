"""Trusted-boundary adapters with inert peer services and a scheduler counter."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from ravel.controller.routes import study
from ravel.controller.routes.study import evidence, runtime, site, remote
from ravel.workflow import wms_launch


@pytest.fixture
def submission(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    script = root / 'job.sh'
    script.write_text('inert workflow payload\n')
    frozen = root / 'protected' / 'frozen.sh'
    frozen.parent.mkdir(mode=0o700)
    frozen.write_bytes(script.read_bytes())
    frozen.chmod(0o400)
    sha = hashlib.sha256(script.read_bytes()).hexdigest()
    state = {'verifications': 0, 'effects': 0, 'last': None}
    store = SimpleNamespace(run_id='fictional-run')
    confine = ModuleType('ravel.controller.confine')
    from p07_support import package_path
    package_path(confine)  # the real confinement submodules still import
    def verify(token, path):
        state['verifications'] += 1
        if token != 'inert-capability' or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise ValueError('missing or changed capability')
        return {'snapshot_path': str(frozen), 'jobscript_sha256': sha}
    confine.verify_capability = verify
    monkeypatch.setitem(sys.modules, 'ravel.controller.confine', confine)
    import ravel.controller
    monkeypatch.setattr(ravel.controller, 'confine', confine, raising=False)
    def submit(path):
        state['effects'] += 1
        state['last'] = path
        return {'id': 'inert-job'}
    scope = {'jobscript': {'path': str(script), 'sha256': sha}, 'capability': {}}
    return store, script, frozen, state, submit, scope


def test_scheduler_boundary_requires_exact_script_capability(submission):
    store, script, frozen, state, submit, scope = submission
    with pytest.raises(ValueError, match='capability'):
        wms_launch.controller_submission(script, submit)
    assert state['effects'] == 0 and state['verifications'] == 0
    with site.trusted_launch(store, 'launch-a', 'inert-capability', scope):
        assert wms_launch.controller_submission(script, submit, run_id=store.run_id,
                                               launch_id='launch-a') == {'id': 'inert-job'}
    assert state['effects'] == 1 and state['verifications'] == 1
    assert state['last'] == frozen and state['last'] != script


def test_scheduler_wrong_launch_changed_script_or_snapshot_has_zero_effects(submission):
    store, script, frozen, state, submit, scope = submission
    with site.trusted_launch(store, 'launch-a', 'inert-capability', scope):
        with pytest.raises(ValueError, match='scope'):
            wms_launch.controller_submission(script, submit, launch_id='launch-b')
        original = script.read_bytes()
        script.write_bytes(b'changed payload\n')
        with pytest.raises(ValueError, match='exact bytes'):
            wms_launch.controller_submission(script, submit)
        script.write_bytes(original)
        frozen.chmod(0o600)
        frozen.write_bytes(b'changed frozen bytes\n')
        with pytest.raises(ValueError, match='frozen'):
            wms_launch.controller_submission(script, submit)
    assert state['effects'] == 0


def test_wms_controller_launch_requires_trusted_context_before_any_native_query(tmp_path, monkeypatch):
    workflow = tmp_path / 'workflow'
    workflow.mkdir()
    monkeypatch.setattr(wms_launch, '_workflow', lambda project: workflow)
    monkeypatch.setattr(wms_launch, '_read', lambda path: {'profile': 'local'})
    monkeypatch.setattr(wms_launch, '_parse_inputs', lambda *args: ({'rundir': str(tmp_path / 'run')}, b'', {}))
    monkeypatch.setattr(wms_launch, '_controller_owned', lambda path: 'fictional-run')
    seen = []
    def admitted(_):
        seen.append('after-boundary')
        raise RuntimeError('inert gate reached')
    monkeypatch.setattr(wms_launch.method_selection, 'require_launch', admitted)
    with pytest.raises(ValueError, match='trusted per-launch'):
        wms_launch.launch(tmp_path, 'task')
    assert seen == []
    store = SimpleNamespace(run_id='fictional-run')
    with site.trusted_launch(store, 'launch-a', 'inert-capability', {}):
        with pytest.raises(RuntimeError, match='inert gate'):
            wms_launch.launch(tmp_path, 'task')
    assert seen == ['after-boundary']
    monkeypatch.setattr(wms_launch, '_controller_owned', lambda path: None)
    with pytest.raises(RuntimeError, match='inert gate'):
        wms_launch.launch(tmp_path, 'task')
    assert seen == ['after-boundary', 'after-boundary']


def test_p01_packet_contains_serializable_current_route_context(tmp_path):
    context = {'store': object(), 'run_dir': tmp_path, 'run_id': 'fictional', 'store_root': tmp_path / 'private',
               'plan': {'sha256': 'a' * 64}, 'reading': {'deliverables': [{'id': 'd1'}]},
               'contract': {'task_mode': 'calculation'}, 'state': {'steps': {}}, 'attempt': 2,
               'launch_capability': 'secret-not-for-worker-packet', 'custom_service': object()}
    packet = runtime.packet_context(context)
    json.dumps(packet, allow_nan=False)
    assert packet['plan'] == context['plan'] and packet['reading'] == context['reading']
    assert packet['attempt'] == 2 and packet['run_dir'] == str(tmp_path)
    assert not {'store', 'launch_capability', 'custom_service'} & packet.keys()


def test_p13_review_binding_is_forwarded_without_schema_changes(monkeypatch):
    from ravel.workflow import review_independence
    query = {'run': '/fictional/run', 'role': 'physics-critic', 'subject_sha256': 'a' * 64,
             'receipt_sha256': 'b' * 64, 'output_sha256': 'c' * 64, 'packet_sha256': None}
    seen = []
    def decide(actual):
        assert set(actual) == set(query)
        seen.append(deepcopy(actual))
        return {'independent': True}
    monkeypatch.setattr(review_independence, 'decide', decide)
    assert evidence._review({'store': SimpleNamespace(run_id='fictional')}, query, 'a' * 64)['independent']
    assert seen == [query]


def test_pending_operation_review_cannot_reach_synthesis_or_final_delivery(tmp_path, monkeypatch):
    from ravel.workflow import science
    context = {'run_dir': str(tmp_path), 'plan': {'parameters': {'study_binding': {
        'mode': 'fictional-mode', 'child_rundir': 'children/study'}}}}
    packet = {'lifecycle_verdict': 'PENDING', 'execution': {'status': 'awaiting_review'}, 'errors': []}
    monkeypatch.setattr(science, 'packet', lambda root: deepcopy(packet))
    assert study.final_evidence(context)[0]['code'] == 'study_review_pending'
    packet['lifecycle_verdict'] = 'PASS'
    assert study.final_evidence(context) == []


class RemoteStore:
    def __init__(self):
        self.rows = []
    def append(self, kind, record):
        identifier = str(len(self.rows) + 1)
        self.rows.append({'id': identifier, 'kind': kind, 'record': deepcopy(record)})
        return identifier
    def scan(self, kind):
        return [deepcopy(row) for row in self.rows if row['kind'] == kind]


def test_site_reconciliation_uses_recorded_handle_and_actual_adoption_before_review(tmp_path, monkeypatch):
    store = RemoteStore()
    store.append('study-remote', {'launch_id': 'launch-a', 'plan': {}, 'handle': {}})
    context = {'store': store, 'run_dir': str(tmp_path)}
    calls = []
    authority = ModuleType('ravel.controller.authority')
    authority.stop_state = lambda store: 'running'
    monkeypatch.setitem(sys.modules, authority.__name__, authority)
    import ravel.controller
    monkeypatch.setattr(ravel.controller, 'authority', authority, raising=False)
    state = {'state': 'running'}
    def reconcile(actual, *, drain):
        assert actual is store and drain is False
        calls.append('observe')
        return {'attempts': [{'launch_id': 'launch-a', 'resolved': state['state'] in site.TERMINAL,
                             'observation': {'state': state['state']}}]}
    monkeypatch.setattr(site, 'reconcile', reconcile)
    def adopt(actual, launch_id, *, base):
        assert actual is store and launch_id == 'launch-a' and base == tmp_path
        calls.append('adopt')
        if not store.scan('study-adoption'):
            store.append('study-adoption', {'launch_id': launch_id, 'event': 'fetched',
                                           'receipt': {'outputs': [{'sha256': 'a' * 64}]}})
        return {'outputs': [{'sha256': 'a' * 64}]}
    monkeypatch.setattr(site, 'adopt', adopt)
    for value in ('running', 'unknown', 'failed', 'cancelled'):
        state['state'] = value
        assert study.step({'id': 'reconcile'}, {'outputs': ['forged-success']}, context)
        assert 'adopt' not in calls
    state['state'] = 'succeeded'
    assert study.step({'id': 'reconcile'}, {}, context) == []
    assert calls[-3:] == ['observe', 'adopt', 'adopt']
    assert store.scan('study-site-custody')[-1]['record']['scientific_acceptance_inferred'] is False
    before = calls.count('observe')
    assert remote.check(context) == []
    assert calls.count('observe') == before
    spec = json.loads((Path(study.__file__).resolve().parents[3] / 'data/controller/routes/study_site.json').read_text())
    nodes = {node['id']: node for node in spec['steps']}
    assert nodes['reconcile']['depends_on'] == ['operate']
    assert nodes['operation-review']['depends_on'] == ['operate', 'reconcile']


def test_site_delivery_checks_adopted_pins_and_preserves_uncertain_dispatch(tmp_path, monkeypatch):
    from ravel.workflow import science
    store = RemoteStore()
    context = {'store': store, 'run_dir': str(tmp_path), 'plan': {'route': 'study.site',
        'parameters': {'study_binding': {'mode': 'fictional-mode', 'child_rundir': 'children/study'}}}}
    monkeypatch.setattr(science, 'packet', lambda root: {'lifecycle_verdict': 'PASS'})
    store.append('study-site', {'event': 'dispatch_started', 'launch_id': 'uncertain-launch'})
    assert study.final_evidence(context) == [{'code': 'site_dispatch_uncertain', 'launch_id': 'uncertain-launch'}]
    store.append('study-site', {'event': 'outcome', 'launch_id': 'uncertain-launch'})
    store.append('study-remote', {'launch_id': 'launch-a'})
    assert study.final_evidence(context)[0]['code'] == 'site_adoption_pending'
    store.append('study-adoption', {'launch_id': 'launch-a', 'event': 'fetched', 'receipt': {}})
    def invalid(*args, **kwargs):
        raise ValueError('actual fetched bytes changed')
    monkeypatch.setattr(site, 'adopt', invalid)
    assert study.final_evidence(context)[0]['code'] == 'site_adoption_invalid'


def test_site_reconciliation_stops_before_observation_when_paused(tmp_path, monkeypatch):
    import ravel.controller
    authority = ModuleType('ravel.controller.authority')
    authority.stop_state = lambda store: 'pause_requested'
    monkeypatch.setitem(sys.modules, authority.__name__, authority)
    monkeypatch.setattr(ravel.controller, 'authority', authority, raising=False)
    monkeypatch.setattr(site, 'reconcile', lambda *args, **kwargs: pytest.fail('pause must prevent effects'))
    context = {'store': RemoteStore(), 'run_dir': str(tmp_path)}
    assert remote.complete(context)[0]['code'] == 'site_reconciliation_held'


def test_inspection_hook_reads_the_original_supplied_bytes(tmp_path):
    supplied = tmp_path / 'input.json'
    supplied.write_bytes(b'{"fictional_value":7}')
    store = RemoteStore()
    pin = {'path': supplied.name, 'sha256': hashlib.sha256(supplied.read_bytes()).hexdigest()}
    context = {'store': store, 'run_dir': str(tmp_path), 'supplied': [pin]}
    assert study.step({'id': 'inspect'}, {'outputs': ['author-inventory']}, context) == []
    assert store.scan('study-input-inventory')[-1]['record']['inputs'][0]['sha256'] == pin['sha256']
    supplied.write_bytes(b'{"fictional_value":8}')
    assert study.step({'id': 'inspect'}, {'outputs': ['author-inventory']}, context)[0]['code'] == 'study_input_invalid'


def test_inspection_hook_reads_the_compiled_request_pins_without_a_packet_field(tmp_path):
    # The shared route context carries the pinned plan but no separate supplied list;
    # the entry records supplied files by absolute real path and directories without a digest.
    outside = (tmp_path / 'supplied-elsewhere').resolve()
    (outside / 'tree').mkdir(parents=True)
    events = outside / 'events.json'
    events.write_bytes(b'{"fictional_value":7}')
    run = tmp_path / 'run'
    run.mkdir()
    pins = [{'kind': 'events', 'path': str(events), 'size': events.stat().st_size,
             'sha256': hashlib.sha256(events.read_bytes()).hexdigest()},
            {'kind': 'directory', 'path': str(outside / 'tree'), 'sha256': None, 'size': None}]
    store = RemoteStore()
    context = {'store': store, 'run_dir': str(run),
               'plan': {'parameters': {'study_request': {'supplied': deepcopy(pins)}}, 'steps': []}}
    assert study.step({'id': 'inspect'}, {}, context) == []
    inventory = store.scan('study-input-inventory')[-1]['record']['inputs']
    assert [(row['path'], row['sha256'], row['content_pinned']) for row in inventory] == [
        (str(events), pins[0]['sha256'], True), (str(outside / 'tree'), None, False)]
    events.write_bytes(b'{"fictional_value":8}')
    assert study.step({'id': 'inspect'}, {}, context)[0]['code'] == 'study_input_invalid'
    events.write_bytes(b'{"fictional_value":7}')
    link = outside / 'linked.json'
    link.symlink_to(events)
    linked = deepcopy(context)
    linked['plan']['parameters']['study_request']['supplied'][0]['path'] = str(link)
    assert study.step({'id': 'inspect'}, {}, linked)[0]['code'] == 'study_input_invalid'
    missing = deepcopy(context)
    missing['plan']['parameters']['study_request']['supplied'][1]['path'] = str(outside / 'absent')
    assert study.step({'id': 'inspect'}, {}, missing)[0]['code'] == 'study_input_invalid'
    escaping = deepcopy(context)
    escaping['plan']['parameters']['study_request']['supplied'][0]['path'] = str(outside / '..' / 'x')
    assert study.step({'id': 'inspect'}, {}, escaping)[0]['code'] == 'study_input_invalid'


def test_site_capture_uses_only_the_approved_ordinary_child_and_source_attempt(tmp_path, monkeypatch):
    from ravel.controller.routes.study import backend
    from ravel.workflow import execution, science
    child = tmp_path / 'children/study'
    (child / 'inputs').mkdir(parents=True)
    (child / science.SPEC).write_text(json.dumps({'execution': {'backend_plan': 'prepared-only'}}))
    operation = {'id': 'operate', 'parameters': {'ordinary': {'kind': 'science'}}}
    context = {'store': RemoteStore(), 'run_dir': str(tmp_path), 'plan': {'steps': [operation]}}
    # The capture inspects the child before approval, then re-reads its current approval for the placed attempt.
    monkeypatch.setattr(runtime, '_ordinary', lambda step, ctx, approved=True: ({'kind': 'science'}, child, science, {}))
    monkeypatch.setattr(execution, 'load_execution', lambda root: {'stages': {'science': {'attempt_id': 'current'}}})
    calls = []
    def track(store, launch_id, *, rundir, stage, plan_path):
        assert store is context['store'] and launch_id == 'operate'
        assert rundir == child and stage == 'science' and plan_path == child / 'inputs/backend-plan.json'
        calls.append('source-tracked')
    monkeypatch.setattr(backend, 'track', track)
    assert remote.capture(context) == []
    assert calls == ['source-tracked']
    def refuses(*args, **kwargs):
        raise ValueError('changed pinned source attempt')
    monkeypatch.setattr(backend, 'track', refuses)
    assert remote.capture(context)[0]['code'] == 'site_backend_binding_invalid'


@pytest.fixture
def step_boundary(tmp_path, monkeypatch):
    from ravel.controller.step import graph
    store = RemoteStore()
    checkpoint = object()
    store.checkpointer = lambda: checkpoint
    store_root = tmp_path / 'private'
    store_root.mkdir(mode=0o700)
    store.path = lambda *parts: store_root.joinpath(*parts)
    context = {'run_id': 'fictional-run', 'store_root': str(tmp_path / 'private'),
               'run_dir': str(tmp_path), 'attempt': 3, 'binding': {'value': 'trusted'}}
    acting = {'id': 'operate', 'kind': 'operate', 'outputs': [], 'review': [], 'depends_on': [],
              'parameters': {'adapter': 'ravel.controller.routes.study.runtime'}}
    state = {'context': context, 'step': acting, 'acting': acting, 'branch': 'launch',
        'reservation': {'key': 'reservation-a', 'amounts': {'wall_seconds': 17}},
        'preflight': {'capsule': {'capability': 'trusted-capability'}, 'output_root': str(tmp_path / 'out')},
        'launch': {'journal_id': 'launch-a'}, 'adoption': {'adopted': [{'artifact': 'result'}]}}
    handles = []
    def bind(handle):
        handles.append(handle)
        assert handle == {'run_id': context['run_id'], 'store_root': context['store_root']}
        return store
    monkeypatch.setattr(graph, 'store_for', bind)
    return SimpleNamespace(graph=graph, store=store, checkpoint=checkpoint, state=state,
                           context=context, root=tmp_path, handles=handles,
                           ledger_scope={'step': 'operate', 'point': None, 'seat': 'producer', 'attempt': 3})


def test_step_runtime_preflight_forwards_trusted_launch_inputs(step_boundary, monkeypatch):
    boundary = step_boundary
    found, inputs = [{'artifact': 'custody', 'pin': {'sha256': 'a' * 64}}], [{'artifact': 'input'}]
    calls = []
    result = {'capsule': {'capability': 'admitted'}}
    def preflight(store, acting, context):
        calls.append(context)
        assert store is boundary.store and acting is boundary.state['acting']
        assert context == {**boundary.context, 'run_dir': str(boundary.root), 'inputs_custody': found,
                           'run_inputs': inputs, 'reservation': boundary.state['reservation'], 'attempt': 3,
                           'ledger_scope': boundary.ledger_scope}
        assert context['inputs_custody'] is not found
        assert context['run_inputs'] is not inputs
        assert context['reservation'] is not boundary.state['reservation']
        return result
    monkeypatch.setattr(runtime, 'preflight', preflight)
    assert boundary.graph._launch_preflight(boundary.state, boundary.store, boundary.context,
        boundary.root, boundary.state['acting'], None, found, inputs, {}) is result
    assert len(calls) == 1


def test_step_runtime_dispatch_rechecks_authority_and_forwards_capsule(step_boundary, monkeypatch):
    boundary = step_boundary
    events = []
    identity = {'effect': 'launch-a', 'attempt': 3}
    def authorize(store, context, acting, amounts, **kwargs):
        assert store is boundary.store and context is boundary.context
        assert acting is boundary.state['acting'] and amounts == {'wall_seconds': 17}
        events.append('authorize')
    def dispatch(store, acting, context):
        assert events == ['authorize']
        assert store is boundary.store and acting is boundary.state['acting']
        assert context == {**boundary.context, 'run_dir': str(boundary.root), 'attempt': 3,
                           'launch_capsule': boundary.state['preflight']['capsule'],
                           'launch_preflight': boundary.state['preflight'], 'effect_identity': identity,
                           'ledger_scope': boundary.ledger_scope}
        assert context['launch_capsule'] is not boundary.state['preflight']['capsule']
        assert context['launch_preflight'] is not boundary.state['preflight']
        assert context['effect_identity'] is not identity
        events.append('dispatch')
        return {'journal_id': 'runtime-launch'}
    monkeypatch.setattr(boundary.graph, '_running', lambda store: None)
    monkeypatch.setattr(boundary.graph, 'module', lambda name: SimpleNamespace())
    monkeypatch.setattr(boundary.graph, '_authorize', authorize)
    monkeypatch.setattr(runtime, 'dispatch', dispatch)
    assert boundary.graph._launch(boundary.state, identity) == {'journal_id': 'runtime-launch'}
    assert events == ['authorize', 'dispatch'] and boundary.handles


@pytest.mark.parametrize('scientific_errors', [[], [{'code': 'source_pin_changed'}]])
def test_step_runtime_scientific_checks_precede_original_validators(step_boundary, monkeypatch, scientific_errors):
    boundary = step_boundary
    events = []
    card = {'id': 'fictional-role', 'must_check': ['artifact-check'], 'family': 'production',
            'independence': {'kind': 'producer'}}
    original_card = deepcopy(card)
    report = {'passed': True, 'results': [{'check_id': 'artifact-check', 'status': 'passed'}],
              'reviewer_items': []}
    def scientific(store, acting, launch, context):
        assert store is boundary.store and acting is boundary.state['acting']
        assert launch == boundary.state['launch'] and launch is not boundary.state['launch']
        assert context == {**boundary.context, 'run_dir': str(boundary.root), 'attempt': 3,
                           'allow_staged_evidence': True, 'ledger_scope': boundary.ledger_scope}
        events.append('scientific')
        return scientific_errors
    def validators(actual_card, acting, *, run_dir, scratch, subjects=None, exempt=None):
        assert subjects is None and exempt is None
        assert events == ['scientific']
        assert actual_card == card and actual_card is not card
        assert acting == {**boundary.state['acting'], 'check_inputs': {}}
        assert acting is not boundary.state['acting']
        assert run_dir == boundary.root
        assert scratch == boundary.root / 'steps/operate/attempts/3/validation'
        events.append('validators')
        return report
    def accept(store, adopted, verdict, *, evidence):
        assert store is boundary.store and adopted == boundary.state['adoption']['adopted']
        if scientific_errors:
            assert events == ['scientific'] and verdict == 'rejected'
            assert evidence == {'scientific_checks': scientific_errors}
        else:
            assert events == ['scientific', 'validators'] and verdict == 'accepted'
            assert evidence == {'validators': report['results']}
        events.append(verdict)
        return adopted
    monkeypatch.setattr(boundary.graph, '_card', lambda state: card)
    monkeypatch.setattr(boundary.graph, '_seat_roles', lambda *args: [])
    monkeypatch.setattr(runtime, 'validate_outcome', scientific)
    monkeypatch.setattr(boundary.graph.validate, 'run_validators', validators)
    monkeypatch.setattr(boundary.graph.custody, 'accept', accept)
    result = boundary.graph.checks(boundary.state)['checks']
    assert result['passed'] is (not scientific_errors)
    assert result['results'] == (scientific_errors or report['results'])
    assert result['accepted'] == ([] if scientific_errors else boundary.state['adoption']['adopted'])
    assert events == (['scientific', 'rejected'] if scientific_errors else ['scientific', 'validators', 'accepted'])
    assert card == original_card


@pytest.fixture
def child_boundary(step_boundary, monkeypatch):
    from ravel.workflow import graph_registry, graph_substrate
    boundary = step_boundary
    boundary.state['meta'] = {'scope_root': str(boundary.root), 'path': 'root',
                              'graph_id': 'controller.step', 'version': 1, 'instance': {}}
    boundary.state['preflight']['graph'] = {'id': 'intake.plan', 'instance': {'request': 'trusted'}}
    boundary.builds, boundary.invocations = [], []
    boundary.configs = []
    monkeypatch.setattr(graph_registry, 'get', lambda graph_id: {'version': 7, 'subgraphs': []})
    monkeypatch.setattr(graph_registry, 'check_instance', lambda row, instance: None)
    def build(graph_id, ctx, *, checkpointer):
        boundary.builds.append((graph_id, ctx, checkpointer))
        return compiled
    def invoke(state, *, config=None):
        boundary.invocations.append(state)
        boundary.configs.append(config)
        return {'status': {'phase': 'finish'}, 'results': {'receipt': 'trusted'}}
    compiled = SimpleNamespace(invoke=invoke)
    monkeypatch.setattr(graph_substrate, 'build', build)
    return boundary


def test_step_intake_subgraph_requires_typed_runner_hold(child_boundary):
    boundary = child_boundary
    with pytest.raises(boundary.graph.StepHold) as caught:
        boundary.graph.subgraph(boundary.state)
    assert caught.value.reason == 'intake_runner_unavailable'
    assert boundary.builds == [] and boundary.invocations == []


def test_step_intake_subgraph_forwards_runner_and_store_checkpointer(child_boundary):
    boundary = child_boundary
    runner = lambda *args: None
    result = boundary.graph.subgraph(boundary.state, node_runner=runner)
    graph_id, ctx, checkpointer = boundary.builds[0]
    assert graph_id == 'intake.plan' and ctx.extras['node_runner'] is runner
    assert checkpointer is boundary.checkpoint and boundary.handles
    assert ctx.instance == {'request': 'trusted'} and ctx.version == 7
    assert boundary.invocations[0]['meta']['scope_root'] == str(boundary.root)
    assert result['child']['outcome'] == 'ok'


def test_step_operation_review_subgraph_uses_ordinary_child_scope(child_boundary, monkeypatch):
    boundary = child_boundary
    boundary.state['preflight']['graph']['id'] = 'review.points'
    boundary.state['acting']['id'] = 'operation-review'
    boundary.state['acting']['depends_on'] = ['operate']
    boundary.state['acting']['parameters']['ordinary_review'] = True
    operation = {'id': 'operate', 'kind': 'operate', 'outputs': [],
                 'parameters': {'adapter': 'ravel.controller.routes.study.runtime', 'ordinary': {}, 'binding': 'trusted'}}
    boundary.context['plan'] = {'steps': [operation, boundary.state['acting']]}
    monkeypatch.setattr(boundary.graph.operations, 'current_plan', lambda store, context: boundary.context['plan'])
    child = boundary.root / 'ordinary-child'
    calls = []
    def ordinary(actual, context):
        assert actual is operation and context is boundary.context
        calls.append('ordinary')
        return {}, child, {}, {}
    monkeypatch.setattr(runtime, '_ordinary', ordinary)
    boundary.graph.subgraph(boundary.state)
    graph_id, ctx, checkpointer = boundary.builds[0]
    assert graph_id == 'review.points' and ctx.scope_root == child
    assert boundary.invocations[0]['meta']['scope_root'] == str(child)
    assert checkpointer is boundary.checkpoint and calls == ['ordinary']


def test_step_builder_forwards_extras_runner_into_subgraph(tmp_path, monkeypatch):
    from ravel.controller.step import graph
    from ravel.workflow import graph_substrate
    captured = {}
    runner = lambda *args: None
    ctx = graph_substrate.BuildContext(scope_root=tmp_path, graph_id='controller.step', version=1,
                                       instance={}, extras={'node_runner': runner})
    monkeypatch.setattr(graph, '_common', lambda builder, graph_id: lambda name, node: captured.update({name: node}))
    monkeypatch.setattr(graph_substrate, 'build', lambda *args, **kwargs: object())
    monkeypatch.setattr(graph.nodes, 'map_node', lambda *args, **kwargs: ('inert-edge', object()))
    calls = []
    def child(state, *, node_runner=None):
        calls.append((state, node_runner))
        return {'child': {'outcome': 'completed'}}
    monkeypatch.setattr(graph, 'subgraph', child)
    graph.build(ctx)
    state = {'binding': 'trusted'}
    assert captured['subgraph'].function(state) == {'child': {'outcome': 'completed'}}
    assert calls == [(state, runner)]



@pytest.mark.parametrize('defect', ['flag-false', 'flag-missing', 'no-predecessor', 'two-predecessors',
                                     'wrong-adapter', 'ordinary-missing'])
def test_step_ordinary_review_refuses_missing_or_ambiguous_approved_binding_before_build(
        child_boundary, monkeypatch, defect):
    boundary = child_boundary
    boundary.state['preflight']['graph']['id'] = 'review.points'
    acting = boundary.state['acting']
    acting['id'] = 'operation-review'
    acting['depends_on'] = ['operate']
    acting['parameters']['ordinary_review'] = True
    operation = {'id': 'operate', 'kind': 'operate', 'outputs': [],
                 'parameters': {'adapter': 'ravel.controller.routes.study.runtime', 'ordinary': {}}}
    plan = {'steps': [operation, acting]}
    if defect == 'flag-false':
        acting['parameters']['ordinary_review'] = False
    elif defect == 'flag-missing':
        del acting['parameters']['ordinary_review']
    elif defect == 'no-predecessor':
        acting['depends_on'] = []
    elif defect == 'two-predecessors':
        another = deepcopy(operation)
        another['id'] = 'second-operation'
        plan['steps'].append(another)
        acting['depends_on'].append(another['id'])
    elif defect == 'wrong-adapter':
        operation['parameters']['adapter'] = 'unrelated-adapter'
    else:
        del operation['parameters']['ordinary']
    boundary.context['plan'] = plan
    def current_plan(store, context):
        assert store is boundary.store and context is boundary.context
        return plan
    monkeypatch.setattr(boundary.graph.operations, 'current_plan', current_plan)
    resolutions = []
    def ordinary(*args):
        resolutions.append(args)
        raise AssertionError('an unbound ordinary child must not be resolved')
    monkeypatch.setattr(runtime, '_ordinary', ordinary)
    with pytest.raises(boundary.graph.StepHold) as caught:
        boundary.graph.subgraph(boundary.state)
    assert caught.value.reason == 'ordinary_review_binding_missing'
    assert resolutions == [] and boundary.builds == [] and boundary.invocations == []


@pytest.mark.parametrize('explicit_argument', [False, True])
def test_step_intake_json_runner_text_never_supplies_a_callable(child_boundary, explicit_argument):
    boundary = child_boundary
    boundary.context['node_runner'] = 'trusted-runner-name-from-json'
    kwargs = {'node_runner': boundary.context['node_runner']} if explicit_argument else {}
    with pytest.raises(boundary.graph.StepHold) as caught:
        boundary.graph.subgraph(boundary.state, **kwargs)
    assert caught.value.reason == 'intake_runner_unavailable'
    assert boundary.builds == [] and boundary.invocations == []


def test_step_other_allowlisted_subgraph_still_requires_its_service_binder(child_boundary):
    boundary = child_boundary
    identifier = 'rdj.case'
    assert identifier in boundary.graph.spec.SUBGRAPHS
    assert identifier not in boundary.graph.SUBGRAPH_BINDERS
    boundary.state['preflight']['graph']['id'] = identifier
    with pytest.raises(boundary.graph.StepHold) as caught:
        boundary.graph.subgraph(boundary.state, node_runner=lambda *args: None)
    assert caught.value.reason == 'subgraph_services_missing'
    assert boundary.builds == [] and boundary.invocations == []
