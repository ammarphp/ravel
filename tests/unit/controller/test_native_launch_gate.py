"""Native action identity and fresh admission checks, with external interfaces isolated."""
from copy import deepcopy
import importlib
from types import SimpleNamespace

import pytest

from ravel.controller import store as stores
from ravel.controller.confine import commitments
from ravel.controller.step import custody, operations, spec
from ravel.controller.step.services import digest


@pytest.fixture
def native(tmp_path, monkeypatch):
    gate = importlib.import_module('ravel.controller.step.launch_gate')
    step = {'id': 'measure', 'kind': 'operate', 'operation': 'toy-operation', 'role': 'calculation',
            'rung': 'smoke', 'depends_on': ['prepare'], 'inputs': [{'artifact': 'prepare:outputs/input.json'}],
            'outputs': [{'path': 'outputs/value.json', 'kind': 'document', 'required': True}], 'parameters': {}}
    plan = {'sha256': 'a' * 64, 'steps': [step], 'engagement': {'applied_sha256': 'd' * 64}}
    context = {'plan_sha256': plan['sha256'], 'attempt': 2}
    prepared = {'launch_sha256': 'b' * 64, 'budget': {'wall_seconds': 7, 'events': 0}}
    proof = {'mechanism': 'native-launch-preflight', 'step_id': step['id'], 'attempt': 2,
             'plan_sha256': plan['sha256'], 'step_sha256': spec.step_sha256(step),
             'launch_sha256': prepared['launch_sha256'], 'passed': True, 'budget': deepcopy(prepared['budget'])}
    faults, calls = {}, []

    class Store:
        run_id = 'run'
        run_dir = tmp_path

        def check_binding(self, directory=None):
            calls.append(('binding', directory))
            return ['copied run'] if faults.get('binding') else []

        def verify(self):
            calls.append(('verify',))
            return ['journal changed'] if faults.get('verify') else []

        def read(self, kind, identifier):
            assert (kind, identifier) == ('step-fact', 'preflight-2')
            if faults.get('record'):
                raise ValueError('missing protected fact')
            return {'id': identifier, 'record': deepcopy(proof)}

    store = Store()
    monkeypatch.setattr(stores, 'controller_owned', lambda directory: None if faults.get('owner') else 'run')
    monkeypatch.setattr(stores, 'RunStore', lambda run_id: store)

    def current_plan(actual_store, ctx):
        assert actual_store is store
        if ctx['plan_sha256'] != context['plan_sha256']:
            raise ValueError('no approved plan with the named digest')
        calls.append(('plan',))
        if faults.get('current_plan'):
            raise ValueError('applied view changed')
        return plan

    monkeypatch.setattr(operations, 'current_plan', current_plan)

    def committed(actual_store, actual_plan, approved, directory):
        assert actual_store is store and actual_plan == plan and approved == step and directory == tmp_path
        calls.append(('commitments',))
        if faults.get('commitments'):
            raise ValueError('approved source changed')
        return 'commitment-1'

    monkeypatch.setattr(commitments, 'verify', committed)
    found = [{'artifact': 'prepare:outputs/input.json', 'kind': 'document'}]

    def inputs(actual_store, approved, directory, **kwargs):
        assert actual_store is store and approved == step and directory == tmp_path
        calls.append(('inputs',))
        return ([{'code': 'input_changed'}] if faults.get('inputs') else [], found, [])

    def parents(actual_store, approved):
        assert actual_store is store and approved == step
        calls.append(('parents',))
        return [{'code': 'parent_incomplete'}] if faults.get('parents') else []

    def executor(approved):
        assert approved == step
        calls.append(('executor',))
        return [{'code': 'executor_role_mismatch'}] if faults.get('executor') else []

    def admission(actual_step, *, inputs_custody, **kwargs):
        assert actual_step == step and inputs_custody == found and kwargs.get('approved') == step
        calls.append(('admission',))
        return [{'code': 'operation_artifact_undeclared'}] if faults.get('admission') else []

    monkeypatch.setattr(custody, 'input_errors', inputs)
    monkeypatch.setattr(custody, 'parent_errors', parents)
    monkeypatch.setattr(operations, 'executor_errors', executor)
    monkeypatch.setattr(operations, 'admission_errors', admission)
    return SimpleNamespace(gate=gate, step=step, plan=plan, context=context, prepared=prepared,
                           proof=proof, store=store, faults=faults, calls=calls)


def make_action(native):
    return native.gate.action(native.step, native.context, native.prepared, 'preflight-2')


def test_native_admission_uses_its_verified_plan_and_store_context(native, monkeypatch):
    seen = []
    monkeypatch.setattr(operations, 'admission_errors',
                        lambda step, **kwargs: seen.append(kwargs.get('context')) or [])
    native.gate.load(native.store.run_dir, make_action(native))
    assert seen == [{'store': native.store, 'run_dir': native.store.run_dir, 'plan': native.plan}]


@pytest.mark.parametrize('rung,kind', [(None, 'dry_run'), ('none', 'dry_run'), ('dry', 'dry_run'),
    ('smoke', 'smoke_launch'), ('pilot', 'single_point_launch'), ('full', 'bulk_launch'), ('scan', 'scan_launch')])
def test_action_kind_comes_only_from_actual_rung_and_exact_pins(native, rung, kind):
    native.step['rung'] = rung
    native.step['parameters']['kind'] = 'dry_run'
    native.step['parameters']['facts'] = {'consequence': 'R0'}
    action = make_action(native)
    pins = {'plan_sha256': native.plan['sha256'], 'step_sha256': spec.step_sha256(native.step),
            'launch_sha256': native.prepared['launch_sha256'], 'attempt': '2', 'native_preflight': 'preflight-2'}
    assert action == {'kind': kind, 'step': 'measure', 'node_id': 'measure', 'rung': rung, 'floor': 'R0',
                      'view_pins': pins, 'digest': digest(pins), 'budget': native.prepared['budget']}
    action['budget']['wall_seconds'] = 100
    assert native.prepared['budget']['wall_seconds'] == 7


@pytest.mark.parametrize('fault', ['rung', 'attempt_zero', 'attempt_bool', 'attempt_string',
                                  'budget_missing', 'launch_hash', 'plan_hash', 'record_missing'])
def test_action_rejects_unresolved_identity(native, fault):
    if fault == 'rung': native.step['rung'] = 'unregistered'
    if fault == 'attempt_zero': native.context['attempt'] = 0
    if fault == 'attempt_bool': native.context['attempt'] = True
    if fault == 'attempt_string': native.context['attempt'] = '2'
    if fault == 'budget_missing': native.prepared.pop('budget')
    if fault == 'launch_hash': native.prepared['launch_sha256'] = ''
    if fault == 'plan_hash': native.context['plan_sha256'] = ''
    with pytest.raises(ValueError):
        native.gate.action(native.step, native.context, native.prepared,
                           None if fault == 'record_missing' else 'preflight-2')


def test_load_rechecks_protected_plan_fact_sources_and_current_admission(native):
    loaded = native.gate.load(native.store.run_dir, make_action(native))
    assert loaded == (native.store, native.plan, native.step, native.proof)
    assert {row[0] for row in native.calls} == {
        'binding', 'verify', 'plan', 'commitments', 'inputs', 'parents', 'executor', 'admission'}


@pytest.mark.parametrize('fault', ['kind', 'step', 'node', 'rung', 'digest', 'extra', 'pinextra',
    'pinplan', 'pinstep', 'pinlaunch', 'pinattempt', 'budget', 'mechanism', 'factstep', 'factattempt',
    'factplan', 'factstepsha', 'factlaunch', 'factpassed', 'factbudget', 'planstep', 'duplicate',
    'owner', 'binding', 'verify', 'record', 'current_plan', 'commitments', 'inputs', 'parents', 'executor', 'admission'])
def test_load_refuses_changed_identity_or_current_boundary(native, fault):
    action = make_action(native)
    if fault == 'kind': action['kind'] = 'dry_run'
    if fault == 'step': action['step'] = 'foreign'
    if fault == 'node': action['node_id'] = 'foreign'
    if fault == 'rung': action['rung'] = 'full'
    if fault == 'digest': action['digest'] = 'c' * 64
    if fault == 'extra': action['facts'] = {'consequence': 'R0'}
    if fault == 'pinextra': action['view_pins']['other'] = 'unchecked'
    if fault == 'pinplan': action['view_pins']['plan_sha256'] = 'c' * 64
    if fault == 'pinstep': action['view_pins']['step_sha256'] = 'c' * 64
    if fault == 'pinlaunch': action['view_pins']['launch_sha256'] = 'c' * 64
    if fault == 'pinattempt': action['view_pins']['attempt'] = '1'
    if fault == 'budget': action['budget']['wall_seconds'] = 1
    if fault == 'mechanism': native.proof['mechanism'] = 'other'
    if fault == 'factstep': native.proof['step_id'] = 'foreign'
    if fault == 'factattempt': native.proof['attempt'] = 1
    if fault == 'factplan': native.proof['plan_sha256'] = 'c' * 64
    if fault == 'factstepsha': native.proof['step_sha256'] = 'c' * 64
    if fault == 'factlaunch': native.proof['launch_sha256'] = 'c' * 64
    if fault == 'factpassed': native.proof['passed'] = False
    if fault == 'factbudget': native.proof['budget']['wall_seconds'] = 1
    if fault == 'planstep': native.step['parameters']['changed'] = True
    if fault == 'duplicate': native.plan['steps'].append(deepcopy(native.step))
    if fault in ('owner', 'binding', 'verify', 'record', 'current_plan', 'commitments', 'inputs',
                 'parents', 'executor', 'admission'):
        native.faults[fault] = True
    if fault != 'digest': action['digest'] = digest(action['view_pins'])
    with pytest.raises(ValueError):
        native.gate.load(native.store.run_dir, action)


@pytest.fixture
def reviewed(native, monkeypatch):
    from ravel.controller import graph
    from ravel.controller.authority import mode, rdj, retained
    from ravel.workflow import physics_review, rdj_approval, rdj_loop, review_enforcement

    native.plan['waypoints'] = ['measure', 'other']
    native.proof.update(stage='analysis', capsule={'argv': ['fictional-native'],
        'reads': ['/fictional/input'], 'writes': ['/fictional/output'], 'cwd': str(native.store.run_dir)},
        log=str(native.store.run_dir / 'steps/measure/attempts/2/logs/stdout'),
        depends_on=deepcopy(native.step['depends_on']))
    records = {'review': [], 'step-launch': [], 'step-fact': [], 'step-review-findings': []}
    original_read = native.store.read

    def read(kind, identifier):
        if kind == 'step-fact' and identifier == 'preflight-2':
            return {'id': identifier, 'seq': 100, 'record': deepcopy(native.proof)}
        return next(row for row in records.get(kind, []) if row['id'] == identifier)

    monkeypatch.setattr(native.store, 'read', read)
    monkeypatch.setattr(native.store, 'scan', lambda kind: records.get(kind, []), raising=False)
    retained_record = {'id': 'approval-context', 'plan': native.plan,
                       'view': {'pins': {'plan_sha256': native.plan['sha256'], 'approve': 'exact'}}}
    monkeypatch.setattr(retained, 'current', lambda actual, kind: retained_record)
    frozen = {'budgets': {'max_redos': 2, 'review_rounds': 3}}
    monkeypatch.setattr(mode, 'frozen', lambda actual: frozen)
    monkeypatch.setattr(graph, 'service', lambda name: SimpleNamespace(bounds=lambda value: {}))
    result = {'class': 'R1', 'approval_errors': [], 'registered': False, 'legacy_result': None}
    calls = []

    def evaluate(directory, action):
        calls.append(('plan-review', deepcopy(action)))
        assert action == rdj.approval_action(retained_record['view']['pins'])
        return result['approval_errors'], {'mechanism': 'observed-plan-review', 'plan_sha256': native.plan['sha256']}

    def before_stage(*args, **kwargs):
        calls.append(('legacy', args, kwargs))
        if result.get('legacy_error'):
            raise ValueError('blocking legacy scientific review')
        return result['legacy_result']

    monkeypatch.setattr(rdj_approval, 'evaluate', evaluate)
    monkeypatch.setattr(rdj_loop, 'compute_class', lambda *args, **kwargs: (result['class'], []))
    monkeypatch.setattr(physics_review, 'registered', lambda directory: result['registered'])
    monkeypatch.setattr(review_enforcement, 'before_stage', before_stage)
    native.reviewed = SimpleNamespace(records=records, retained=retained_record, frozen=frozen,
                                      result=result, calls=calls, graph=graph)
    return native


def waypoint_round(native, *, attempt=7, seq=40):
    graph = native.reviewed.graph
    subject = {'waypoint:measure': 'e' * 64, 'waypoint:other': 'f' * 64}
    findings = {'id': 'findings', 'seq': seq - 1, 'digest': 'd' * 64, 'record': {
        'step_id': 'waypoint_review.physics-critic', 'verdict': 'revise',
        'subject_sha256': digest(subject)}}
    row = {'id': 'review-current', 'seq': seq, 'record': {'purpose': 'waypoint',
        'plan_sha256': native.plan['sha256'], 'attempt': attempt, 'subject': subject,
        'subject_sha256': digest(subject), 'seats': {'physics-critic': {'credited': True,
            'status': 'completed', 'verdict': 'revise', 'step': 'waypoint_review.physics-critic',
            'findings': ['findings']}}}}
    native.reviewed.records['step-review-findings'] = [findings]
    native.reviewed.records['review'] = [row]
    correction, problem = graph.review_correction(native.store, purpose='waypoint',
        verdicts=row['record']['seats'], subject_sha256=row['record']['subject_sha256'],
        attempt=attempt, done=0, bound=2)
    assert problem is None
    native.proof['correction'] = correction
    return row


def started_correction(native, *, producer='other', round_number=1, seq=20):
    identifier = 'earlier-' + producer + '-' + str(seq)
    fact = {'id': identifier, 'seq': seq - 1, 'record': {
        'mechanism': 'native-launch-preflight', 'step_id': producer, 'attempt': 1,
        'plan_sha256': native.plan['sha256'], 'step_sha256': 'e' * 64,
        'launch_sha256': 'f' * 64, 'passed': True,
        'correction': {'purpose': 'waypoint', 'round': round_number}}}
    launch = {'id': 'launch-' + identifier, 'seq': seq, 'record': {
        'phase': 'started', 'step_id': producer, 'attempt': 1,
        'launch_sha256': 'f' * 64, 'native_preflight': identifier}}
    native.reviewed.records['step-fact'].append(fact)
    native.reviewed.records['step-launch'].append(launch)


def test_initial_native_launch_still_requires_observed_plan_review(reviewed):
    missing, evidence = reviewed.gate.approval(reviewed.store.run_dir, make_action(reviewed))
    assert missing == [] and evidence is not None
    assert [call[0] for call in reviewed.reviewed.calls] == ['plan-review']


def test_missing_controller_plan_review_holds_without_legacy_registration(reviewed):
    reviewed.reviewed.result['approval_errors'] = ['no observed plan review']
    missing, evidence = reviewed.gate.approval(reviewed.store.run_dir, make_action(reviewed))
    assert missing and evidence is None


def test_first_correction_replays_exact_protected_findings_with_nonconsecutive_attempt(reviewed):
    waypoint_round(reviewed, attempt=7)
    missing, evidence = reviewed.gate.approval(reviewed.store.run_dir, make_action(reviewed))
    assert missing == [] and evidence is not None
    assert reviewed.proof['correction']['round'] == 1


def test_second_round_counts_distinct_started_rounds_across_producers(reviewed):
    row = waypoint_round(reviewed)
    started_correction(reviewed, producer='measure', seq=20)
    started_correction(reviewed, producer='other', seq=22)
    correction, problem = reviewed.reviewed.graph.review_correction(reviewed.store, purpose='waypoint',
        verdicts=row['record']['seats'], subject_sha256=row['record']['subject_sha256'],
        attempt=row['record']['attempt'], done=1, bound=2)
    assert problem is None
    reviewed.proof['correction'] = correction
    missing, evidence = reviewed.gate.approval(reviewed.store.run_dir, make_action(reviewed))
    assert missing == [] and evidence is not None


def test_other_producer_can_start_once_in_same_review_round(reviewed):
    waypoint_round(reviewed)
    started_correction(reviewed, producer='other', seq=45)
    missing, evidence = reviewed.gate.approval(reviewed.store.run_dir, make_action(reviewed))
    assert missing == [] and evidence is not None


@pytest.mark.parametrize('fault', ['not_waypoint', 'missingcorrection', 'wrongsubject', 'wrongfindings',
    'uncredited', 'exhausted', 'duplicateproducer', 'missingseq', 'wronglink', 'wronglaunchsha',
    'unordered', 'wrongapprovalplan', 'R3', 'legacyblocks', 'legacycorrection'])
def test_native_review_admission_refuses_unmapped_or_unbounded_work(reviewed, fault):
    row = waypoint_round(reviewed)
    if fault == 'not_waypoint': reviewed.plan['waypoints'].remove('measure')
    if fault == 'missingcorrection': reviewed.proof.pop('correction')
    if fault == 'wrongsubject': reviewed.proof['correction']['subject_sha256'] = '0' * 64
    if fault == 'wrongfindings': reviewed.proof['correction']['findings'][0]['digest'] = '0' * 64
    if fault == 'uncredited': row['record']['seats']['physics-critic']['credited'] = False
    if fault == 'exhausted':
        started_correction(reviewed, round_number=1, seq=20)
        started_correction(reviewed, round_number=2, seq=22)
    if fault == 'duplicateproducer': started_correction(reviewed, producer='measure', seq=45)
    if fault == 'missingseq': row.pop('seq')
    if fault in ('wronglink', 'wronglaunchsha'):
        started_correction(reviewed)
        launch = reviewed.reviewed.records['step-launch'][0]['record']
        launch['native_preflight' if fault == 'wronglink' else 'launch_sha256'] = 'foreign'
    if fault == 'unordered':
        started_correction(reviewed, seq=22); started_correction(reviewed, seq=20)
    if fault == 'wrongapprovalplan': reviewed.reviewed.retained['view']['pins']['plan_sha256'] = '0' * 64
    if fault == 'R3': reviewed.reviewed.result['class'] = 'R3'
    if fault in ('legacyblocks', 'legacycorrection'):
        reviewed.reviewed.result['registered'] = True
        reviewed.reviewed.result['legacy_error'] = fault == 'legacyblocks'
        reviewed.reviewed.result['legacy_result'] = 'legacy-correction' if fault == 'legacycorrection' else None
    missing, evidence = reviewed.gate.approval(reviewed.store.run_dir, make_action(reviewed))
    assert missing and evidence is None


def test_registered_legacy_review_reads_actual_protected_capsule(reviewed):
    reviewed.reviewed.result['registered'] = True
    missing, evidence = reviewed.gate.approval(reviewed.store.run_dir, make_action(reviewed))
    assert missing == [] and evidence is not None
    legacy, = [call for call in reviewed.reviewed.calls if call[0] == 'legacy']
    capsule = reviewed.proof['capsule']
    assert legacy[1] == (reviewed.store.run_dir, reviewed.proof['stage'], capsule['argv'], capsule['reads'],
                         capsule['writes'], reviewed.step['depends_on'], capsule['cwd'], reviewed.proof['log'])


@pytest.fixture
def providers(reviewed, monkeypatch):
    from ravel.workflow import production_executor, rdj_approval, rdj_loop
    monkeypatch.setattr(rdj_approval, 'controller_plan', lambda root: (reviewed.store, reviewed.plan))
    monkeypatch.setattr(rdj_loop.custody, 'rows', lambda *args: [])
    monkeypatch.setattr(rdj_loop.anchor_check, 'policy_pin', lambda: {'sha256': 'e' * 64})

    def forbidden(*args, **kwargs):
        raise AssertionError('selected native action reached the legacy executor/host path')

    monkeypatch.setattr(production_executor, 'load_order', forbidden)
    monkeypatch.setattr(production_executor, 'waiver_errors', forbidden)
    monkeypatch.setattr(production_executor, 'worker_receipt', forbidden)
    reviewed.providers = SimpleNamespace(executor=production_executor, rdj=rdj_loop)
    return reviewed


@pytest.mark.parametrize('markers', ['present', 'stripped', 'allpinsstripped'])
def test_native_selector_uses_protected_step_even_when_markers_are_removed(providers, markers):
    value = make_action(providers)
    if markers != 'present':
        value.pop('step'); value['view_pins'].pop('native_preflight')
    if markers == 'allpinsstripped': value.pop('view_pins')
    assert providers.gate.selected(providers.store.run_dir, value) is True


def test_explicit_malformed_native_marker_never_falls_back_when_run_is_unowned(providers):
    providers.faults['owner'] = True
    value = {'step': 'foreign', 'view_pins': {'native_preflight': None}}
    assert providers.gate.selected(providers.store.run_dir, value) is True
    errors = providers.providers.executor.gate_errors(providers.store.run_dir, 'launch', value)
    assert errors and errors[0].code == 'executor_native_invalid'


@pytest.mark.parametrize('fault', ['binding', 'verify', 'current_plan'])
def test_native_selector_refuses_unverifiable_controller_plan(providers, fault):
    value = {'kind': 'smoke_launch', 'node_id': 'measure', 'rung': 'smoke'}
    providers.faults[fault] = True
    with pytest.raises(ValueError):
        providers.gate.selected(providers.store.run_dir, value)


def test_selected_native_providers_recompute_admission_and_return_actual_mapping(providers):
    value = make_action(providers)
    errors, receipt = providers.providers.rdj._gate_decision(providers.store.run_dir, 'launch', value)
    assert errors == [] and receipt is None
    evidence = providers.providers.rdj.gate_evidence(providers.store.run_dir, 'launch', value)
    assert evidence['mechanism'] == 'controller.native_launch.mapping'
    assert evidence['native_preflight'] == 'preflight-2'
    assert providers.providers.executor.gate_errors(providers.store.run_dir, 'launch', value) == []
    assert sum(call[0] == 'commitments' for call in providers.calls) >= 3


@pytest.mark.parametrize('provider', ['rdj', 'executor'])
@pytest.mark.parametrize('fault', ['markersstripped', 'digest', 'node', 'stepchanged', 'commitments'])
def test_selected_malformed_native_actions_refuse_without_legacy_fallback(providers, provider, fault):
    value = make_action(providers)
    if fault == 'markersstripped': value.pop('step'); value['view_pins'].pop('native_preflight')
    if fault == 'digest': value['digest'] = '0' * 64
    if fault == 'node': value['node_id'] = 'foreign'
    if fault == 'stepchanged': providers.step['parameters']['changed'] = True
    if fault == 'commitments': providers.faults['commitments'] = True
    if provider == 'rdj':
        errors, receipt = providers.providers.rdj._gate_decision(providers.store.run_dir, 'launch', value)
        assert receipt is None
        assert errors and errors[0].code == 'rdj_native_invalid'
        assert providers.providers.rdj.gate_evidence(providers.store.run_dir, 'launch', value) is None
    else:
        errors = providers.providers.executor.gate_errors(providers.store.run_dir, 'launch', value)
        assert errors and errors[0].code == 'executor_native_invalid'


def test_R3_native_action_keeps_existing_exact_receipt_requirement(providers, monkeypatch):
    providers.reviewed.result['class'] = 'R3'

    def forbidden(*args, **kwargs):
        raise AssertionError('R3 native action used the lower-class approval mapping')

    monkeypatch.setattr(providers.gate, 'approval', forbidden)
    errors, receipt = providers.providers.rdj._gate_decision(providers.store.run_dir, 'launch', make_action(providers))
    assert receipt is None
    assert errors and errors[0].code == 'rdj_receipt_missing'
    assert providers.providers.rdj.gate_evidence(providers.store.run_dir, 'launch', make_action(providers)) is None


def test_existing_nonnative_executor_path_remains_unchanged(providers, monkeypatch):
    providers.step.update(kind='derive', operation=None)
    value = {'kind': 'bulk_launch', 'node_id': 'measure', 'rung': 'full'}
    assert providers.gate.selected(providers.store.run_dir, value) is False
    calls = []
    monkeypatch.setattr(providers.providers.executor, 'load_order',
                        lambda *args: calls.append('order') or {'executor': 'worker', 'role': 'calculation'})
    monkeypatch.setattr(providers.providers.executor, 'worker_receipt', lambda *args: {'status': 'ok'})
    assert providers.providers.executor.gate_errors(providers.store.run_dir, 'launch', value) == []
    assert calls == ['order']


@pytest.mark.parametrize('provider', ['rdj', 'executor'])
def test_native_marker_on_controller_worker_deliberately_refuses_instead_of_legacy_fallback(providers, provider):
    providers.step.update(kind='derive', operation=None)
    value = {'kind': 'bulk_launch', 'node_id': 'measure', 'step': 'measure', 'rung': 'full'}
    assert providers.gate.selected(providers.store.run_dir, value) is True
    if provider == 'rdj':
        errors, receipt = providers.providers.rdj._gate_decision(providers.store.run_dir, 'launch', value)
        assert receipt is None
        assert errors and errors[0].code == 'rdj_native_invalid'
    else:
        errors = providers.providers.executor.gate_errors(providers.store.run_dir, 'launch', value)
        assert errors and errors[0].code == 'executor_native_invalid'


@pytest.mark.parametrize('declared', ['R0', 'R1', 'R2', 'R3'])
def test_native_action_floor_is_the_actual_declared_step_class(native, declared):
    native.step['consequence_class'] = declared
    native.step['parameters']['consequence_class'] = 'R0'
    native.proof['step_sha256'] = spec.step_sha256(native.step)
    action = make_action(native)
    assert action['floor'] == declared
    assert native.gate.load(native.store.run_dir, action)[2] == native.step


def test_actual_r3_step_retains_r3_through_real_launch_classifier(native, monkeypatch):
    from ravel.workflow import rdj_loop
    native.step['consequence_class'] = 'R3'
    native.proof['step_sha256'] = spec.step_sha256(native.step)
    monkeypatch.setattr(rdj_loop, '_cost_facts', lambda _: {'points': 0, 'walltime_hours': 0})
    action = make_action(native)
    assert native.gate.load(native.store.run_dir, action)[2]['consequence_class'] == 'R3'
    required, factors = rdj_loop.compute_class(native.store.run_dir, 'launch', action)
    assert required == 'R3' and factors['floor'] == 'R3'


@pytest.mark.parametrize('fault', ['lowered', 'missing'])
def test_protected_declared_floor_cannot_be_lowered_or_stripped(native, fault):
    native.step['consequence_class'] = 'R3'
    native.proof['step_sha256'] = spec.step_sha256(native.step)
    action = make_action(native)
    if fault == 'lowered':
        action['floor'] = 'R0'
    else:
        action.pop('floor', None)
    with pytest.raises(ValueError):
        native.gate.load(native.store.run_dir, action)


@pytest.mark.parametrize('declared', [None, 'R4', 'r3', 3, True, [], {}])
def test_invalid_actual_declared_class_is_refused(native, declared):
    native.step['consequence_class'] = declared
    with pytest.raises(ValueError):
        make_action(native)


@pytest.fixture
def preparation(reviewed, monkeypatch):
    from ravel.controller.authority import common as authority_records, mode, retained, service
    from ravel.controller.routes.analysis import execution
    native = reviewed
    # Isolate issuer-backed record reads of this fake store; the production effect
    # checker, stop logic, effective bounds and numeric ceilings still run.
    monkeypatch.setattr(authority_records, 'scan', lambda actual, kind, schema=None: [])
    native.step.update(kind='acquire', operation='acquire-published', rung='none',
                       budget={'events': 0, 'wall_seconds': 7})
    native.step['parameters'] = {'phase': 'prepare', 'task': {'max_bytes': 4096},
        'launch': {'argv': ['python', '-m', 'ravel.workflow.resource_census', '--reading', 'input.json',
                            '--controller-output', 'census.json']}}
    native.proof['step_sha256'] = spec.step_sha256(native.step)
    native.proof['preparation_implementation'] = execution.acquisition_implementation(native.step)
    native.reviewed.frozen.update(id='mode-preparation', run_id=native.store.run_id,
        bounds={'rungs': ['none', 'dry'], 'allowed_stages': ['*']})
    native.reviewed.frozen['budgets'].update(events=0, wall_seconds=60)
    monkeypatch.setattr(mode, 'frozen', lambda actual, **kwargs: native.reviewed.frozen)
    monkeypatch.setattr(commitments, 'verify', lambda *a: pytest.fail('preparation used approval-time commitment'))
    monkeypatch.setattr(retained, 'current', lambda *a: pytest.fail('preparation claimed CHECK-IN 1 approval'))
    effect = {'id': native.step['id'], 'rung': 'none', 'plan': 'none',
              'pins': {'plan_sha256': native.plan['sha256']}, 'go_pins': {}, 'requires_go': True,
              'stage': native.proof['stage'], 'budget': deepcopy(native.proof['budget']), 'started_ns': 1}
    actual = service.authorize_effect(native.store, effect)
    row = {'id': 'preparation-authority', 'seq': 101, 'record': {
        'step_id': native.step['id'], 'attempt': native.context['attempt'],
        'plan_sha256': native.plan['sha256'], 'effect': effect, 'authority': actual}}
    native.reviewed.records['step-authority'] = [row]
    native.preparation_authority = row
    return native


def test_bounded_preparation_uses_real_fresh_authority_without_claiming_approval(preparation):
    n = preparation
    missing, evidence = n.gate.approval(n.store.run_dir, make_action(n))
    assert missing == [] and evidence['mechanism'] == 'controller.native_preparation.mapping'
    assert evidence['preparation_authority'] == 'preparation-authority'
    assert evidence['mode_record'] == 'mode-preparation'
    assert evidence['preparation_implementation'] == n.proof['preparation_implementation']
    assert 'approval_context' not in evidence and 'approval' not in evidence
    assert evidence['scientific_review']['mechanism'] == 'controller.native-review-admission'
    assert n.reviewed.calls == []


@pytest.mark.parametrize('fault', ['argv', 'operation', 'kind', 'phase', 'rung', 'events', 'budget_events',
    'max_bytes', 'implementation_missing', 'implementation_stale', 'authority_absent', 'authority_step',
    'authority_attempt', 'authority_plan', 'authority_older', 'authority_budget', 'authority_stage',
    'authority_pins', 'authority_rung', 'mode', 'bounds', 'R2', 'R3', 'legacy_blocker', 'waypoint_blocker'])
def test_preparation_never_substitutes_for_missing_current_evidence(preparation, monkeypatch, fault):
    n = preparation
    row = n.preparation_authority; body = row['record']; effect = body['effect']
    if fault == 'argv': n.step['parameters']['launch']['argv'] = ['arbitrary-native']
    if fault == 'operation': n.step['operation'] = 'toy-operation'
    if fault == 'kind': n.step['kind'] = 'operate'
    if fault == 'phase': n.step['parameters']['phase'] = 'execute'
    if fault == 'rung': n.step['rung'] = 'smoke'
    if fault == 'events': n.step['budget']['events'] = 1
    if fault == 'budget_events': n.proof['budget']['events'] = 1; n.prepared['budget']['events'] = 1
    if fault == 'max_bytes': n.step['parameters']['task']['max_bytes'] = True
    if fault == 'implementation_missing': n.proof.pop('preparation_implementation')
    if fault == 'implementation_stale': n.proof['preparation_implementation']['code']['changed'] = '0' * 64
    if fault == 'authority_absent': n.reviewed.records['step-authority'] = []
    if fault == 'authority_step': body['step_id'] = 'other'
    if fault == 'authority_attempt': body['attempt'] += 1
    if fault == 'authority_plan': body['plan_sha256'] = 'c' * 64
    if fault == 'authority_older': row['seq'] = 99
    if fault == 'authority_budget': effect['budget']['wall_seconds'] = 0
    if fault == 'authority_stage': effect['stage'] = 'other'
    if fault == 'authority_pins': effect['pins']['plan_sha256'] = 'c' * 64
    if fault == 'authority_rung': effect['rung'] = effect['plan'] = 'dry'
    if fault == 'mode': body['authority']['mode_record'] = 'superseded-mode'
    if fault == 'bounds': n.reviewed.frozen['bounds']['allowed_stages'] = []
    if fault in ('R2', 'R3'): n.reviewed.result['class'] = fault
    if fault == 'legacy_blocker': n.reviewed.result.update(registered=True, legacy_error=True)
    if fault == 'waypoint_blocker': waypoint_round(n); n.plan['waypoints'] = ['other']
    n.proof['step_sha256'] = spec.step_sha256(n.step)
    missing, evidence = n.gate.approval(n.store.run_dir, make_action(n))
    assert missing and evidence is None


def test_preparation_rechecks_current_operator_bounds_on_every_provider_read(preparation):
    n = preparation
    assert n.gate.approval(n.store.run_dir, make_action(n))[0] == []
    n.reviewed.frozen['budgets']['wall_seconds'] = 0
    missing, evidence = n.gate.approval(n.store.run_dir, make_action(n))
    assert missing and evidence is None


from test_p04_support import graphs, run_env, services_installed  # noqa: E402,F401


@pytest.mark.parametrize('error', [ValueError, TypeError, KeyError, OSError])
def test_preflight_translates_preparation_capability_failure_to_typed_hold(run_env, graphs, monkeypatch, error):
    from ravel.controller.step import launch_gate
    from test_p04_graph import _launch_step, _launch_tool, _signature
    from test_p04_support import records, run_step
    monkeypatch.setattr(operations, 'signatures', lambda: {'fixture-operation': _signature()})
    def refused(step):
        raise error('invalid preparation capability')
    monkeypatch.setattr(launch_gate, 'preparation_implementation', refused)
    step = _launch_step(_launch_tool(run_env.root))
    step['parameters']['phase'] = 'prepare'
    result = run_step(run_env, step)
    assert result['status'] == 'held' and result['reason'] == 'native_preparation_refused', result
    assert records(run_env.store, 'step-launch') == [] and run_env.fakes['confine'].launched == []
