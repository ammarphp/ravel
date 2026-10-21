"""Inert confined ordinary-operation launches and custody-bound result checks."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

from ravel.controller.routes.study import evidence, runtime
from ravel.controller import ledger as real_ledger
from p02_support import (INTAKE, PLAN, RUN, fixture_store, satisfy)  # noqa: F401


class Store:
    run_id = 'runtime-fixture'

    def __init__(self, root):
        self.root = root
        root.mkdir()
        self.rows = []

    def path(self, *parts):
        return self.root.joinpath(*parts)

    def append(self, kind, value):
        identifier = str(len(self.rows) + 1)
        self.rows.append({'id': identifier, 'kind': kind,
                          'record': json.loads(json.dumps(value, allow_nan=False))})
        return identifier

    def scan(self, kind):
        return deepcopy([r for r in self.rows if r['kind'] == kind])


class Process:
    pid = None

    def __init__(self, timeout=False):
        self.returncode = None
        self.timeout = timeout
        self.calls = []

    def communicate(self, timeout):
        self.calls.append(('communicate', timeout))
        if self.timeout and not any(c[0] == 'terminate' for c in self.calls):
            raise subprocess.TimeoutExpired('inert', timeout)
        self.returncode = -15 if self.timeout else 0
        return 'source stdout', ''

    def terminate(self):
        self.calls.append(('terminate',))

    def kill(self):
        self.calls.append(('kill',))


@pytest.fixture
def env(tmp_path, monkeypatch):
    from ravel.workflow import science
    import ravel.controller
    import ravel.controller.routes.study as study
    run = tmp_path / 'run'
    child = run / 'children' / 'ordinary'
    (child / 'inputs').mkdir(parents=True)
    store = Store(tmp_path / 'protected-store')
    spec = {'max_seconds': 10, 'max_attempts': 1}
    (child / science.SPEC).parent.mkdir(parents=True, exist_ok=True)
    (child / science.SPEC).write_text(json.dumps(spec))
    (child / science.PLAN).parent.mkdir(parents=True, exist_ok=True)
    (child / science.PLAN).write_text('{"source_plan": true}')
    pin = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    ordinary = {'kind': 'science', 'child_rundir': 'children/ordinary',
                'plan_sha256': pin(child / science.PLAN),
                'specification_sha256': pin(child / science.SPEC)}
    step = {'id': 'calculate', 'operation': 'calculation', 'role': 'calculator',
            'budget': {'wall_seconds': 2}, 'parameters': {'ordinary': ordinary}, 'outputs': []}
    context = {'run_dir': str(run), 'plan_sha256': 'a' * 64,
               'authority_subject': {'view': {'summary': 'existing ordinary check-in',
                                             'pins': {'plan_sha256': 'a' * 64}}},
               'contract': {'task_mode': 'calculation'}}
    state = {'stop': 'running', 'gate': [], 'decision': {'id': 'actual-authority', 'decision': 'approve',
             'authorizes_effects': True}, 'verified': [],
             'launches': [], 'probes': [], 'requests': [], 'process': Process()}
    authority = ModuleType('ravel.controller.authority')
    authority.stop_state = lambda store: state['stop']
    def request(store, action, subject, bounds):
        state['requests'].append((action, subject, bounds))
        return state['decision']
    authority.request = request
    def verify(store, record_id, *, kind, subject=None):
        state['verified'].append((record_id, kind, deepcopy(subject)))
        if state.get('verification_refused'):
            raise ValueError('authority attestation refused')
        return deepcopy(state['decision'])
    authority.verify = verify
    ledger = ModuleType('ravel.controller.ledger')
    ledger.gate = lambda store, gate: state['gate']
    confine = ModuleType('ravel.controller.confine')
    from p07_support import package_path
    package_path(confine)  # the real confinement submodules still import
    def probe(action, capsule):
        state['probes'].append((action, deepcopy(capsule)))
        return {'equal': True}
    def popen(capsule, **kwargs):
        state['launches'].append((deepcopy(capsule), kwargs))
        return state['process']
    confine.probe, confine.popen = probe, popen
    for name, module in [('authority', authority), ('ledger', ledger), ('confine', confine)]:
        monkeypatch.setitem(sys.modules, 'ravel.controller.' + name, module)
        monkeypatch.setattr(ravel.controller, name, module, raising=False)
    monkeypatch.setattr(science, 'verify_plan', lambda child, approved: {'existing': 'verified plan'})
    monkeypatch.setattr(study, 'mode_admission', lambda spec: {'operation': 'calculation', 'role': 'calculator'})
    return store, step, context, state, child, authority, confine


def adopt(env, artifact, value):
    store, _, context, *_ = env
    destination = 'adopted/' + artifact.replace(':', '/')
    path = Path(context['run_dir']) / destination
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True).encode()
    path.write_bytes(raw)
    store.append('custody', {'artifact': artifact, 'destination': destination,
        'sha256': hashlib.sha256(raw).hexdigest(), 'status': 'accepted'})
    return path


def test_launch_uses_real_ledger_waypoint_and_clean_step_holds(env, fixture_store, monkeypatch):
    import ravel.controller
    store, step, context, state, *_ = env
    monkeypatch.setattr(ravel.controller, 'ledger', real_ledger)
    satisfy(fixture_store, real_ledger.materialise(fixture_store, 'intake', INTAKE))
    real_ledger.materialise(fixture_store, 'plan', {'plan': PLAN, 'route': 'analysis'})
    # Close plan review and CI1 while retaining the ancestor waypoint's pending GO.
    review = real_ledger.materialise(fixture_store, 'review',
        {'step': 'plan_review', 'seat': 'plan-critic', 'attempt': 1})
    satisfy(fixture_store, review)
    from ravel.controller.ledger.state import load
    current = load(fixture_store)
    satisfy(fixture_store, [k for k in current.plan_keys
        if current.instances[k].scope.get('step') != 's1'])
    step['id'] = 's2'
    holds = real_ledger.gate(fixture_store, 'launch[s2]')
    assert holds and any(r['id'] == 'CHECKIN-2' for r in holds)
    with pytest.raises(runtime.StudyHold, match='unmet ledger obligations') as held:
        runtime.preflight(fixture_store, step, context)
    assert str(holds) in str(held.value)
    assert state['launches'] == []
    satisfy(fixture_store, [k for k in current.plan_keys
        if current.instances[k].scope.get('step') == 's1'])
    assert real_ledger.gate(fixture_store, 'launch[s2]') == []
    assert runtime.preflight(fixture_store, step, context)['admission_id']
    # The authority compares the decision's pins with the current check-in pins (the view's pins).
    assert state['verified'] == [('actual-authority', 'approve_plan', context['authority_subject']['view']['pins'])]


def test_preparation_real_ledger_requires_materialised_plan_before_ci1(env, fixture_store, monkeypatch):
    import ravel.controller
    _, step, context, state, *_ = env
    monkeypatch.setattr(ravel.controller, 'ledger', real_ledger)
    satisfy(fixture_store, real_ledger.materialise(fixture_store, 'intake', INTAKE))
    step.update(rung='dry', parameters={'action': 'prepare'})
    context.update(phase='prepare', plan={'route': 'study'})
    adopt(env, 'specify:outputs/specification.json', {'max_seconds': 10})
    adopt(env, 'specify:outputs/scope.json', {'child_rundir': 'children/prepared'})
    for row in env[0].rows:
        fixture_store.append(row['kind'], row['record'])
    with pytest.raises(runtime.StudyHold, match='preparation has unmet'):
        runtime.preflight(fixture_store, step, context)
    real_ledger.materialise(fixture_store, 'plan', {'plan': PLAN, 'route': 'study'})
    assert real_ledger.gate(fixture_store, 'plan->plan_review') == []
    assert real_ledger.gate(fixture_store, 'checkin1->execute')
    assert runtime.preflight(fixture_store, step, context)['capsule']['argv'][3] == 'prepare'
    assert state['requests'] == [] and state['launches'] == []


@pytest.mark.parametrize('invalid', ['unattested', 'unverified'])
def test_approval_requires_effect_authorization_and_current_attestation(env, invalid):
    store, step, context, state, *_ = env
    if invalid == 'unattested':
        state['decision']['authorizes_effects'] = False
    else:
        state['verification_refused'] = True
    with pytest.raises(ValueError):
        runtime.dispatch(store, step, context)
    assert state['launches'] == []


def test_confined_adapter_uses_installed_module_and_never_exposes_store(env):
    store, step, context, state, child, *_ = env
    assert runtime._ordinary(step, context)[1] == child
    result = runtime.dispatch(store, step, context)
    assert result['exit_status'] == 0 and not result['timed_out']
    capsule, kwargs = state['launches'][0]
    assert capsule['argv'][:4] == [sys.executable, '-m', runtime.ADAPTER, 'run']
    assert capsule['argv'][4:8] == ['--kind', 'science', '--rundir', str(child)]
    assert str(store.root) not in json.dumps(capsule)
    # Only the child's declared persistent state root (its lease, custody and steering records across
    # launches), beside the child under the run's children; never the store or a secret.
    state_root = runtime.launch_state_root(Path(context['run_dir']).absolute(), Path('children/ordinary'))
    assert capsule['env'] == {'RAVEL_LAUNCH_STATE': str(state_root)}
    assert state_root.parent == Path(context['run_dir']).absolute() / 'children'
    assert kwargs['start_new_session'] is True
    assert state['requests'][0][0] == 'approve_plan'


@pytest.mark.parametrize('action', ['run', 'prepare'])
def test_preflight_declares_only_plan_outputs_and_receipt_inside_single_output_root(env, action):
    store, step, context, state, *_ = env
    filename = 'preparation.json' if action == 'prepare' else 'result.json'
    step['outputs'] = [{'path': 'outputs/' + filename, 'kind': 'result'},
                       {'path': 'outputs/optional.json', 'kind': 'table', 'required': False}]
    if action == 'prepare':
        step.update(rung='dry', parameters={'action': 'prepare'})
        context.update(phase='prepare', plan={'route': 'study'})
        adopt(env, 'specify:outputs/specification.json', {'max_seconds': 10})
        adopt(env, 'specify:outputs/scope.json', {'child_rundir': 'children/prepared'})
    prepared = runtime.preflight(store, step, context)
    root = Path(prepared['output_root'])
    argv = prepared['capsule']['argv']
    assert Path(argv[argv.index('--receipt') + 1]) == root / filename
    assert prepared['outputs'] == [
        {'path': 'outputs/' + filename, 'plan_path': 'outputs/' + filename,
         'kind': 'result', 'required': True},
        {'path': 'outputs/optional.json', 'plan_path': 'outputs/optional.json',
         'kind': 'table', 'required': False}]
    assert state['launches'] == []


def test_dispatch_finishes_confinement_before_inventory_and_preserves_actual_boundary_facts(env):
    store, step, context, state, _, _, confine = env
    process = state['process']
    process.ravel_backend = 'observed-confined-backend'
    raw = b'{"actual": "receipt bytes"}\n'
    finished = []
    def finish(observed):
        assert observed is process and process.returncode == 0
        root = Path(state['launches'][0][1]['cwd'])
        (root / 'result.json').write_bytes(raw)
        (root / 'ignored-link.json').symlink_to(root / 'result.json')
        finished.append(True)
        return {'errors': ['actual confinement error'], 'quarantined': ['undeclared.txt']}
    confine.finish = finish
    result = runtime.dispatch(store, step, context)
    assert finished == [True]
    assert result['inventory'] == [{'path': 'result.json',
        'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}]
    assert result['confinement_probe'] == {'equal': True}
    assert result['backend'] == 'observed-confined-backend'
    assert result['confinement_errors'] == ['actual confinement error']
    assert result['quarantined'] == ['undeclared.txt']
    journaled = [r['record']['outcome'] for r in store.scan('study-operation')
                 if r['record']['event'] == 'outcome']
    assert journaled == [result]


def test_dispatch_without_finish_reports_file_inventory_and_observed_plan_backend(env):
    from types import SimpleNamespace
    store, step, context, state, *_ = env
    state['process'].ravel_confinement = SimpleNamespace(record={'backend': 'observed-plan-backend'})
    result = runtime.dispatch(store, step, context)
    assert result['inventory'] == []
    assert result['backend'] == 'observed-plan-backend'
    assert result['confinement_errors'] == [] and result['quarantined'] == []


def test_credited_nonexecuting_review_closes_only_execution_rows_with_bound_credit(env):
    store, *_ = env
    step = {'id': 'review', 'kind': 'review', 'operation': None, 'parameters': {}}
    credit_id = store.append('step-credit', {'step_id': step['id'], 'credited': True,
        'own': {'credited': True}})
    rows = runtime.review_rows(store, step, credit_id=credit_id)
    assert set(rows) == {'E02', 'E06', 'E07', 'E08', 'E10', 'E13', 'E14', 'E17', 'E18'}
    step_sha256 = hashlib.sha256(json.dumps(step, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    for row in rows.values():
        assert row == {'status': 'not_applicable', 'evidence': {
            'credit': credit_id, 'step_sha256': step_sha256,
            'reason': 'not_applicable:credited_review_executes_no_scientific_operation'}}
    assert store.scan('step-credit')[0]['id'] == credit_id


@pytest.mark.parametrize('defect', ['absent_credit', 'wrong_step', 'uncredited', 'own_uncredited',
                                  'own_missing', 'operation', 'non_review', 'unprotected_record'])
def test_review_execution_rows_remain_owed_without_matching_credited_nonexecuting_review(env, defect):
    store, *_ = env
    step = {'id': 'review', 'kind': 'review', 'operation': None, 'parameters': {}}
    credit = {'step_id': step['id'], 'credited': True, 'own': {'credited': True}}
    if defect == 'wrong_step':
        credit['step_id'] = 'other-review'
    elif defect == 'uncredited':
        credit['credited'] = False
    elif defect == 'own_uncredited':
        credit['own']['credited'] = False
    elif defect == 'own_missing':
        credit.pop('own')
    elif defect == 'operation':
        step['operation'] = 'calculation'
    elif defect == 'non_review':
        step['kind'] = 'author'
    credit_id = store.append('host-authored-review' if defect == 'unprotected_record' else 'step-credit', credit)
    if defect == 'absent_credit':
        credit_id = 'missing-credit'
    assert runtime.review_rows(store, step, credit_id=credit_id) == {}


def test_review_explicit_evidence_binding_is_never_closed_as_not_applicable(env):
    store, *_ = env
    step = {'id': 'review', 'kind': 'review', 'operation': None, 'parameters': {
        'evidence_requirements': [{'row': 'E07', 'expected': 'inputs:expected',
                                   'observed': 'review:outputs/observed.json'}]}}
    credit_id = store.append('step-credit', {'step_id': step['id'], 'credited': True,
        'own': {'credited': True}})
    rows = runtime.review_rows(store, step, credit_id=credit_id)
    assert 'E07' not in rows
    assert set(rows) == {'E02', 'E06', 'E08', 'E10', 'E13', 'E14', 'E17', 'E18'}
    assert all(row['evidence']['credit'] == credit_id for row in rows.values())


@pytest.mark.parametrize('materialized', [True, False])
def test_scientific_checks_binds_only_exact_current_scope_and_removes_authored_entry_ids(env, monkeypatch,
                                                                                       materialized):
    from ravel.controller import ledger
    from ravel.controller.ledger.state import instance_key
    store, step, context, *_ = env
    scope = {'step': step['id'], 'point': 'p1', 'seat': 'producer', 'attempt': 2}
    context['ledger_scope'] = scope
    step['parameters']['evidence_requirements'] = [{'row': 'E07', 'expected': 'inputs:expected',
        'observed': 'outputs:observed', 'entry_ids': ['authored-foreign-id']}]
    original = deepcopy(step)
    exact = instance_key('E07', store.run_id, scope)
    present = [instance_key('E07', store.run_id, {**scope, 'attempt': 1}),
               instance_key('E07', store.run_id, {**scope, 'seat': 'reviewer'}),
               instance_key('E07', store.run_id, {**scope, 'step': 'other-step'}),
               instance_key('E07', 'other-run', scope)]
    if materialized:
        present.append(exact)
    lookups, checks = [], []
    def current(observed_store, *, step):
        lookups.append((observed_store, step))
        return [{'entry': key} for key in present]
    monkeypatch.setattr(ledger, 'current', current, raising=False)
    sentinel = [{'code': 'original-validator-finding'}]
    def check(observed_store, bound, observed_context, *, phase):
        checks.append((observed_store, bound, observed_context, phase))
        return sentinel
    monkeypatch.setattr(evidence, 'check', check)
    assert runtime.scientific_checks(store, step, context, phase='review') is sentinel
    assert lookups == [(store, scope['step'])]
    assert len(checks) == 1
    observed_store, bound, observed_context, phase = checks[0]
    assert observed_store is store and observed_context is context and phase == 'review'
    assert bound['parameters']['evidence_requirements'][0]['entry_ids'] == ([exact] if materialized else [])
    assert step == original and bound is not step


def test_scientific_checks_without_ledger_scope_preserves_original_package_bindings(env, monkeypatch):
    from ravel.controller import ledger
    store, step, context, *_ = env
    step['parameters']['evidence_requirements'] = [{'row': 'E07', 'expected': 'inputs:expected',
        'observed': 'outputs:observed', 'entry_ids': ['package-owned-id']}]
    original = deepcopy(step)
    monkeypatch.setattr(ledger, 'current', lambda *a, **k: pytest.fail('scope-less checks do not rebind'),
                        raising=False)
    calls = []
    def check(observed_store, bound, observed_context, *, phase):
        calls.append((observed_store, bound, observed_context, phase))
        return []
    monkeypatch.setattr(evidence, 'check', check)
    assert runtime.scientific_checks(store, step, context, phase='adopt') == []
    assert len(calls) == 1
    observed_store, bound, observed_context, phase = calls[0]
    assert observed_store is store and observed_context is context and phase == 'adopt'
    assert bound == original and step == original


@pytest.mark.parametrize('defect', ['missing', 'changed'])
def test_scientific_checks_still_runs_descriptor_validator_without_materialized_row(env, monkeypatch, defect):
    from ravel.controller import ledger
    store, step, context, *_ = env
    context['ledger_scope'] = {'step': step['id'], 'attempt': 2}
    expected = {'pdf_member': 'approved-pdf', 'generation_settings': {'seed': 17}}
    adopt(env, 'inputs:expected', expected)
    if defect == 'changed':
        adopt(env, 'outputs:observed', {**expected, 'pdf_member': 'changed-pdf'})
    step['parameters']['evidence_requirements'] = [{'row': 'E07', 'expected': 'inputs:expected',
        'observed': 'outputs:observed', 'entry_ids': ['authored-foreign-id'],
        'validator': 'descriptor-continuity'}]
    monkeypatch.setattr(ledger, 'current', lambda observed_store, *, step: [], raising=False)
    monkeypatch.setattr(ledger, 'record', lambda *a, **k: pytest.fail('no exact row was materialized'),
                        raising=False)
    findings = runtime.scientific_checks(store, step, context, phase='adopt')
    assert len(findings) == 1
    assert findings[0]['code'] == 'scientific_evidence_unresolved' and findings[0]['row'] == 'E07'
    recorded = store.scan('study-evidence')[-1]['record']
    assert recorded['status'] == 'violated' and recorded['findings']


@pytest.mark.parametrize('block', ['authority', 'denied', 'ledger', 'attempts', 'stop'])
def test_unmet_boundaries_have_zero_launches(env, block):
    store, step, context, state, *_ = env
    if block == 'authority':
        state['decision'] = {'pending': 'operator'}
    elif block == 'denied':
        state['decision'] = {'id': 'denied-authority', 'decision': 'deny'}
    elif block == 'ledger':
        state['gate'] = ['unmet']
    elif block == 'attempts':
        context['attempt'] = 2
    else:
        state['stop'] = 'stop_requested'
    with pytest.raises(runtime.StudyHold):
        runtime.dispatch(store, step, context)
    assert state['launches'] == []


@pytest.mark.parametrize('which', ['PLAN', 'SPEC'])
def test_changed_plan_pin_refuses_before_process(env, which):
    from ravel.workflow import science
    store, step, context, state, child, *_ = env
    (child / getattr(science, which)).write_text('{}')
    with pytest.raises(runtime.StudyHold, match='changed'):
        runtime.dispatch(store, step, context)
    assert state['launches'] == []


def test_cached_outcome_and_interrupted_restart_never_duplicate_process(env):
    store, step, context, state, *_ = env
    first = runtime.dispatch(store, step, context)
    assert runtime.dispatch(store, step, context) == first
    assert len(state['launches']) == 1
    store.rows = [r for r in store.rows if not (r['kind'] == 'study-operation' and
                                              r['record']['event'] == 'outcome')]
    with pytest.raises(runtime.StudyHold, match='do not resubmit'):
        runtime.dispatch(store, step, context)
    assert len(state['launches']) == 1


def test_timeout_terminates_and_reaps_inert_process(env):
    store, step, context, state, *_ = env
    state['process'] = Process(timeout=True)
    result = runtime.dispatch(store, step, context)
    assert result['timed_out'] and result['exit_status'] == -15
    assert state['process'].calls == [('communicate', 2), ('terminate',), ('communicate', 2)]


def test_stop_between_preflight_and_effect_has_zero_launches(env):
    store, step, context, state, _, authority, _ = env
    answers = iter(['running', 'stop_requested'])
    authority.stop_state = lambda store: next(answers)
    with pytest.raises(runtime.StudyHold, match='before'):
        runtime.dispatch(store, step, context)
    assert state['launches'] == []


def test_E09_missing_recipe_sources_refuse_before_launch(env):
    store, step, context, state, *_ = env
    adopt(env, 'inputs:recipe', {'kind': 'external-generation-recipe', 'schema_version': 1,
        'operation': 'calculation', 'instructions': 'retained source recipe', 'sources': ['inputs:missing-source']})
    step['parameters']['evidence_requirements'] = [{'row': 'E09', 'expected': 'inputs:recipe'}]
    with pytest.raises(runtime.StudyHold, match='recipe'):
        runtime.dispatch(store, step, context)
    assert state['launches'] == []
    adopt(env, 'inputs:missing-source', {'source': 'inert adopted source'})
    assert runtime.preflight(store, step, context)['admission_id']
    assert state['launches'] == []


def test_literal_quantity_descriptors_and_receipt_custody(env):
    store, step, context, state, *_ = env
    expected = {'units': 'GeV', 'statistic': 'supplied quadratic form'}
    adopt(env, 'inputs:quantity', expected)
    observed = adopt(env, 'outputs:receipt', expected)
    step['parameters']['evidence_requirements'] = [{'row': 'R08', 'expected': 'inputs:quantity',
        'observed': 'outputs:receipt', 'validator': 'descriptor-continuity'}]
    assert evidence.check(store, step, context, phase='review') == []
    for field in ['units', 'statistic']:
        adopt(env, 'outputs:receipt', {**expected, field: 'changed'})
        assert evidence.check(store, step, context, phase='review')
    observed = adopt(env, 'outputs:receipt', expected)
    observed.write_text('{}')
    assert evidence.check(store, step, context, phase='review')
    assert state['launches'] == []


@pytest.mark.parametrize('kind', ['science', 'scoped'])
def test_owned_child_entry_calls_source_engine_and_serializes_only_source_packet(env, monkeypatch, kind):
    from ravel.workflow import science, scoped
    _, _, context, state, child, *_ = env
    calls = []
    module = science if kind == 'science' else scoped
    packet = {'source_fact': 'inert measured result', 'open_obligations': ['source obligation'],
              'lifecycle_verdict': 'PASS'}
    products = {'result': {'value': 17, 'units': 'GeV'}, 'artifacts': [{'path': 'source-product', 'sha256': 'b' * 64}],
                'packet': packet}
    monkeypatch.setattr(module, 'controller_products', lambda path: deepcopy(products))
    def run(path):
        calls.append(('run', path))
        return 0
    monkeypatch.setattr(module, 'run', run)
    if kind == 'science':
        monkeypatch.setattr(science, 'packet', lambda path: deepcopy(packet))
    else:
        (child / 'inputs/task_contract.json').write_text('{"source_contract": true}')
        def evaluate(path, contract):
            assert contract == {'source_contract': True}
            return deepcopy(packet)
        monkeypatch.setattr(scoped, 'evaluate', evaluate)
    receipt = Path(context['run_dir']) / ('receipt-' + kind + '.json')
    assert runtime.main(['run', '--kind', kind, '--rundir', str(child), '--receipt', str(receipt)]) == 0
    assert calls == [('run', child)]
    assert json.loads(receipt.read_text()) == {'kind': 'ordinary-study-receipt', 'exit_status': 0, **products}
    assert state['launches'] == [] and state['requests'] == []


@pytest.mark.parametrize('kind', ['science', 'scoped'])
def test_prepare_calls_source_plan_without_approval_or_execution(env, monkeypatch, kind):
    from ravel.workflow import science, scoped
    _, _, context, state, child, *_ = env
    module = science if kind == 'science' else scoped
    child = Path(context['run_dir']) / 'children' / ('prepared-' + kind)
    spec = Path(context['run_dir']) / 'prepare-spec.json'
    spec.write_text('{"source_spec": true}')
    calls = []
    def plan(path, specification):
        calls.append(('plan', path, specification))
        (path / 'inputs').mkdir(parents=True, exist_ok=True)
        (path / module.PLAN).write_text('{"source_plan": true}')
        (path / module.SPEC).write_bytes(spec.read_bytes())
        return {'source_proposal': 'requires actual authority'}
    monkeypatch.setattr(module, 'plan', plan)
    monkeypatch.setattr(module, 'run', lambda *a, **k: pytest.fail('preparation cannot execute'))
    receipt = Path(context['run_dir']) / ('prepared-' + kind + '.json')
    args = ['prepare', '--kind', kind, '--rundir', str(child), '--receipt', str(receipt),
            '--spec', str(spec), '--child-relative', 'children/ordinary']
    if kind == 'scoped':
        contract = Path(context['run_dir']) / 'original-contract.json'
        contract.write_bytes(b'{"original_contract": true}\n')
        args.extend(['--contract', str(contract)])
    runtime.main(args)
    if kind == 'scoped':
        assert (child / 'inputs/task_contract.json').read_bytes() == contract.read_bytes()
    assert calls == [('plan', child, spec)]
    packet = json.loads(receipt.read_text())
    assert packet['kind'] == 'ordinary-study-preparation'
    assert packet['proposal'] == {'source_proposal': 'requires actual authority'}
    assert packet['ordinary']['kind'] == kind
    assert packet['ordinary']['child_rundir'] == 'children/ordinary'
    assert packet['ordinary']['plan_sha256'] == hashlib.sha256((child / module.PLAN).read_bytes()).hexdigest()
    assert packet['ordinary']['specification_sha256'] == hashlib.sha256((child / module.SPEC).read_bytes()).hexdigest()
    assert state['requests'] == [] and state['launches'] == []


def test_correction_delegates_source_arguments_then_source_run_and_packet(env, monkeypatch):
    from ravel.workflow import science
    _, _, context, state, child, *_ = env
    document = {'actor_id': 'source-corrector', 'changed_paths': ['work/source.py'],
                'recheck_checks': ['source-check'], 'max_seconds': 2,
                'supporting_artifacts': ['inputs/source.json']}
    correction = Path(context['run_dir']) / 'correction.json'
    correction.write_text(json.dumps(document))
    calls = []
    def correct(path, **kwargs):
        calls.append(('correct', path, kwargs))
        return {'source_correction': 'recorded'}
    def run(path):
        calls.append(('run', path))
        return 0
    monkeypatch.setattr(science, 'correct', correct)
    monkeypatch.setattr(science, 'run', run)
    packet = {'source_result': 'unchanged engine packet', 'lifecycle_verdict': 'PASS'}
    monkeypatch.setattr(science, 'packet', lambda path: deepcopy(packet))
    monkeypatch.setattr(science, 'controller_products', lambda path: {'result': {'value': 29}, 'artifacts': [], 'packet': deepcopy(packet)})
    receipt = Path(context['run_dir']) / 'corrected.json'
    assert runtime.main(['correct', '--kind', 'science', '--rundir', str(child), '--receipt', str(receipt),
                         '--correction', str(correction)]) == 0
    assert calls == [('correct', child, document), ('run', child)]
    assert json.loads(receipt.read_text())['packet'] == packet
    assert json.loads(receipt.read_text())['result'] == {'value': 29}
    assert state['requests'] == [] and state['launches'] == []


def test_failed_source_correction_never_runs_or_creates_receipt(env, monkeypatch):
    from ravel.workflow import science
    _, _, context, state, child, *_ = env
    document = {'actor_id': 'source-corrector', 'changed_paths': ['work/source.py'],
                'recheck_checks': ['source-check'], 'max_seconds': 2, 'supporting_artifacts': []}
    correction = Path(context['run_dir']) / 'failed-correction.json'
    correction.write_text(json.dumps(document))
    def refused(*args, **kwargs):
        raise ValueError('source correction refused')
    monkeypatch.setattr(science, 'correct', refused)
    monkeypatch.setattr(science, 'run', lambda *a: pytest.fail('refused correction cannot run'))
    receipt = Path(context['run_dir']) / 'refused.json'
    with pytest.raises(ValueError, match='source correction refused'):
        runtime.main(['correct', '--kind', 'science', '--rundir', str(child), '--receipt', str(receipt),
                      '--correction', str(correction)])
    assert not receipt.exists()
    assert state['requests'] == [] and state['launches'] == []



@pytest.mark.parametrize('kind', ['science', 'scoped'])
def test_source_controller_products_select_current_result_and_pin_real_files(env, monkeypatch, kind):
    from ravel.workflow import science, scoped
    _, _, _, _, child, *_ = env
    module = science if kind == 'science' else scoped
    state = {'lifecycle_verdict': 'PASS'} if kind == 'science' else {'verdict': 'PASS'}
    if kind == 'science':
        monkeypatch.setattr(science, 'packet', lambda path: deepcopy(state))
        monkeypatch.setattr(science, 'verify_plan', lambda path, approved: {'schema_version': 2})
        monkeypatch.setattr(science, '_selected', lambda path, proposal: ({'outputs': ['outputs/selected-2']}, 2))
        stale = child / 'outputs/stale-1'
        stale.mkdir(parents=True)
        (stale / 'result.json').write_text('{"value": -1}')
        folder = child / 'outputs/selected-2'
    else:
        (child / 'inputs/task_contract.json').write_text('{"source_contract": true}')
        monkeypatch.setattr(scoped, 'evaluate', lambda path, contract: deepcopy(state))
        monkeypatch.setattr(scoped, 'verify_plan', lambda path, require_approval: {'source_plan': True})
        folder = child / 'outputs'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'result.json').write_text('{"value": 37, "units": "GeV"}')
    (folder / 'auxiliary.txt').write_bytes(b'actual source product')
    products = module.controller_products(child)
    assert products['result'] == {'value': 37, 'units': 'GeV'}
    assert products['packet'] == state
    assert {Path(pin['path']).name for pin in products['artifacts']} == {'result.json', 'auxiliary.txt'}
    for pin in products['artifacts']:
        content = Path(pin['path']).read_bytes()
        assert pin['sha256'] == hashlib.sha256(content).hexdigest()
        assert pin['size'] == len(content)
    state[next(iter(state))] = 'FAIL'
    with pytest.raises(ValueError, match='incomplete'):
        module.controller_products(child)


def test_pending_review_products_require_explicit_opt_in_and_exact_clean_state(env, monkeypatch):
    from ravel.workflow import science
    _, _, _, _, child, *_ = env
    state = {'lifecycle_verdict': 'PENDING', 'execution': {'status': 'awaiting_review'}, 'errors': []}
    monkeypatch.setattr(science, 'packet', lambda path: deepcopy(state))
    monkeypatch.setattr(science, 'verify_plan', lambda path, approved: {'stages': [{'outputs': ['outputs/candidate']} ]})
    folder = child / 'outputs/candidate'
    folder.mkdir(parents=True)
    (folder / 'result.json').write_text('{"value": 43, "units": "GeV"}')
    with pytest.raises(ValueError, match='incomplete'):
        science.controller_products(child)
    candidate = science.controller_products(child, allow_pending_review=True)
    assert candidate['review_pending'] is True
    assert candidate['result'] == {'value': 43, 'units': 'GeV'}
    assert candidate['packet']['lifecycle_verdict'] == 'PENDING'
    assert 'accepted' not in candidate and 'qualified' not in candidate
    for changed in [
        {'lifecycle_verdict': 'PENDING', 'execution': {'status': 'awaiting_review'}, 'errors': ['source error']},
        {'lifecycle_verdict': 'PENDING', 'execution': {'status': 'awaiting_review'}},
        {'lifecycle_verdict': 'PENDING', 'execution': {'status': 'running'}, 'errors': []},
    ]:
        state.clear()
        state.update(changed)
        with pytest.raises(ValueError, match='incomplete'):
            science.controller_products(child, allow_pending_review=True)


def test_pending_candidate_receipt_preserves_numeric_output_without_final_acceptance(env, monkeypatch):
    from ravel.workflow import science
    _, _, context, state, child, *_ = env
    packet = {'lifecycle_verdict': 'PENDING', 'execution': {'status': 'awaiting_review'}, 'errors': []}
    calls = []
    monkeypatch.setattr(science, 'run', lambda path: 0)
    monkeypatch.setattr(science, 'packet', lambda path: deepcopy(packet))
    def products(path, *, allow_pending_review=False):
        calls.append(allow_pending_review)
        return {'result': {'value': 47, 'units': 'GeV'}, 'artifacts': [],
                'packet': deepcopy(packet), 'review_pending': True}
    monkeypatch.setattr(science, 'controller_products', products)
    receipt = Path(context['run_dir']) / 'candidate.json'
    assert runtime.main(['run', '--kind', 'science', '--rundir', str(child), '--receipt', str(receipt)]) == 0
    candidate = json.loads(receipt.read_text())
    assert calls == [True] and candidate['review_pending'] is True
    assert candidate['result'] == {'value': 47, 'units': 'GeV'}
    assert candidate['packet']['lifecycle_verdict'] == 'PENDING'
    assert 'accepted' not in candidate and 'qualified' not in candidate
    assert state['requests'] == [] and state['launches'] == []


def _credited_child(store, defect=None, *, bound=False):
    parent = {'id': 'generate', 'kind': 'operate', 'operation': 'lifecycle-routine-recast'}
    seat = 'seat:object-selection-mapper:1'
    step = {'id': 'generate.review', 'kind': 'review', 'operation': None,
            'role': 'object-selection-mapper',
            'parameters': {'seat_of': parent['id'], 'purpose': 'review'}}
    if bound:
        step['parameters']['evidence_requirements'] = [{'row': 'E07', 'expected': 'input:expected',
                                                        'observed': 'result:observed'}]
    session = {'run_id': store.run_id, 'step': step['id'], 'step_spec': step,
               'seat': seat, 'attempt': 2, 'session_id': 'observed-session', 'receipt_sha256': 'a' * 64}
    row = {'seat': seat, 'role': step['role'], 'credited': True, 'status': 'completed',
           'session_id': session['session_id'], 'receipt_sha256': session['receipt_sha256'], 'attempt': 2}
    credit = {'step_id': parent['id'], 'attempt': 2, 'credited': True, 'own': None, 'seats': [row]}
    if defect == 'parent': credit['step_id'] = 'other'
    elif defect == 'credit': credit['credited'] = False
    elif defect == 'seat_credit': row['credited'] = False
    elif defect == 'role': row['role'] = 'other-role'
    elif defect == 'attempt': row['attempt'] = 1
    elif defect == 'receipt': row['receipt_sha256'] = 'b' * 64
    elif defect == 'run': session['run_id'] = 'other-run'
    elif defect == 'seat': session['seat'] = 'other-seat'
    elif defect == 'operation': step['operation'] = 'calculation'
    elif defect == 'purpose': step['parameters']['purpose'] = 'consult'
    elif defect == 'seat_of': step['parameters']['seat_of'] = 'other-parent'
    if defect != 'missing_session':
        session_id = store.append('worker-session', session)
        if defect == 'duplicate_session': store.append('worker-session', session)
    else:
        session_id = None
    credit_id = store.append('step-credit', credit)
    return parent, seat, step, session_id, credit_id


def test_child_review_execution_absence_joins_its_actual_session_and_parent_credit(tmp_path):
    store = Store(tmp_path / 'store')
    parent, seat, step, session_id, credit_id = _credited_child(store)
    rows = runtime.child_review_rows(store, parent, credit_id=credit_id, seat_key=seat)
    assert set(rows) == {'E02', 'E06', 'E07', 'E08', 'E10', 'E13', 'E14', 'E17', 'E18'}
    for row in rows.values():
        assert row['status'] == 'not_applicable'
        assert row['evidence']['session'] == session_id
        assert row['evidence']['credit'] == credit_id
        assert row['evidence']['step_sha256'] == runtime.digest(step)
        assert row['evidence']['reason'] == 'not_applicable:credited_review_executes_no_scientific_operation'
    # The parent's generating operation remains distinct from its nonexecuting seat.
    assert runtime.review_rows(store, parent, credit_id=credit_id) == {}


@pytest.mark.parametrize('defect', ['parent', 'credit', 'seat_credit', 'role', 'attempt', 'receipt', 'run',
                                  'seat', 'operation', 'purpose', 'seat_of', 'missing_session', 'duplicate_session'])
def test_child_review_execution_absence_refuses_unmatched_or_effectful_sources(tmp_path, defect):
    store = Store(tmp_path / 'store')
    parent, seat, _, _, credit_id = _credited_child(store, defect)
    assert runtime.child_review_rows(store, parent, credit_id=credit_id, seat_key=seat) == {}


def test_child_review_explicit_scientific_binding_stays_owed(tmp_path):
    store = Store(tmp_path / 'store')
    parent, seat, _, _, credit_id = _credited_child(store, bound=True)
    rows = runtime.child_review_rows(store, parent, credit_id=credit_id, seat_key=seat)
    assert 'E07' not in rows and 'E06' in rows
