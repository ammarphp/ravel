"""Typed sources reach real validators only through declared, byte-bound custody."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

import fakes
from ravel.controller import routes
from ravel.controller.routes import validator_inputs as bindings
from ravel.controller.step import custody, validate
from ravel.controller.store import RunStore
from ravel.workflow import review_independence, review_projection_checks as documents, run_validator_checks as runs
from test_p06_support import operator_home  # noqa: F401
from test_p04_support import (context, graphs, inert_worker, install_plan, make_step, run_env,
                              services_installed, task_contract)  # noqa: F401

CLOSURE = 'check:validation.input_closure.check'
CERTIFICATE = 'check:validation.certificates.validate_certificate'
CARD = {'id': 'isolated-closure', 'family': 'review', 'independence': {'kind': 'reviewer'},
        'must_check': [CLOSURE]}


@pytest.fixture(autouse=True)
def _operator_issuer(operator_home):
    """Launch adoption reads the operator's frozen ceilings through the issuer journal; an isolated issuer
    stands in for `ravel operator init` here. The tests never set a mode."""
    from ravel.controller.authority import issuer, operator
    issuer.initialize()
    if not operator._ledger_rows():
        operator.init(mode='physicist-in-the-loop')


def _frozen(store):
    """The run's operating mode, frozen at intake as every real run's is; launch adoption reads it."""
    from ravel.controller.authority import freeze_mode
    freeze_mode(store, {'prompt': 'Bind the validator inputs of the fictional study.'})
    return store


def _source(path='outputs/fit.json', kind='pin', **extra):
    return {'source': 'output', 'step': 'prepare', 'path': path, 'type': kind, **extra}


def test_review_subjects_preserve_accepted_producer_source_scope_without_mutating_plan(monkeypatch):
    from ravel.controller.step import graph

    producer = {'id': 'inspect', 'depends_on': ['prepare'],
                'inputs': [{'artifact': 'prepare:outputs/fit.json'},
                           {'artifact': 'prepare:outputs/reference.json'}],
                'outputs': [{'path': 'outputs/inspection.json'}],
                'parameters': {'check_inputs': {CLOSURE: {
                    'fit': _source(), 'reference': _source('outputs/reference.json')}}}}
    unaccepted = deepcopy(producer)
    unaccepted['id'] = 'unaccepted'
    plan = {'steps': [producer, unaccepted]}
    original = deepcopy(plan)
    store, ctx = object(), {'plan_sha256': 'approved-plan'}

    def current_plan(actual_store, actual_ctx):
        assert actual_store is store and actual_ctx is ctx
        return plan

    def custody_index(actual_store):
        assert actual_store is store
        return {
            'inspect:outputs/inspection.json': {
                'step_id': 'inspect', 'status': 'accepted', 'path': 'outputs/inspection.json',
                'destination': 'steps/inspect/attempts/1/outputs/inspection.json', 'sha256': 'a' * 64},
            'unaccepted:outputs/inspection.json': {
                'step_id': 'unaccepted', 'status': 'rejected', 'path': 'outputs/inspection.json',
                'destination': 'steps/unaccepted/attempts/1/outputs/inspection.json', 'sha256': 'b' * 64},
        }

    monkeypatch.setattr(graph.operations, 'current_plan', current_plan)
    monkeypatch.setattr(graph.custody, 'custody_index', custody_index)
    subjects = graph.review_subjects(store, ctx, {'id': 'review'}, CARD)
    assert subjects == {CLOSURE: [{'step': 'inspect',
                                   'parameters': producer['parameters']['check_inputs'][CLOSURE],
                                   'spec': producer}]}
    subject, = subjects[CLOSURE]
    assert subject['spec'] is not producer
    subject['spec']['depends_on'].append('foreign')
    subject['spec']['inputs'][0]['artifact'] = 'foreign:outputs/fit.json'
    subject['spec']['parameters']['check_inputs'][CLOSURE]['fit']['step'] = 'foreign'
    assert plan == original


def _steps():
    producer = fakes.make_step('prepare', role='coordinator',
                               outputs=['outputs/fit.json', 'outputs/reference.json', 'outputs/data.json'],
                               parameters={'validator_exports': {'outputs/data.json': {'/mode': 'string'}}})
    consumer = fakes.make_step('inspect', kind='compare', role='calculation', depends_on=['prepare'],
                              inputs=[{'artifact': 'prepare:' + row['path']} for row in producer['outputs']],
                              outputs=['outputs/inspection.json'], parameters={'check_inputs': {CLOSURE: {
                                  'fit': _source(), 'reference': _source('outputs/reference.json')}}})
    return [producer, consumer]


def _spec(steps):
    return fakes._spec('fixture-bindings', 7, {'field': 'task_mode', 'eq': 'calculation'}, steps,
                       [{'match': {'any': True}, 'step': 'inspect', 'output': 'outputs/inspection.json'}])


def _pin(run, relative):
    return {'path': relative, 'sha256': hashlib.sha256((run / relative).read_bytes()).hexdigest()}


def _write(run, relative, value):
    path = run / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))
    return _pin(run, relative)


def _adopt(store, pin, path, *, parents=()):
    row = {'schema_version': 1, 'artifact': 'prepare:' + path, 'step_id': 'prepare', 'attempt': 1,
           'path': path, 'destination': pin['path'], 'sha256': pin['sha256'], 'kind': 'artifact',
           'owner_role': 'coordinator', 'producer': {'kind': 'controller'}, 'inputs': list(parents),
           'status': 'accepted'}
    store.append(custody.CUSTODY, row)
    return row


@pytest.fixture
def adopted(tmp_path):
    run = tmp_path / 'run'
    store = _frozen(RunStore.create(run, root=tmp_path / 'store', run_id='run-bindings'))
    data = _write(run, 'steps/prepare/outputs/data.json', {'mode': 'fixed', 'value': 3})
    fit = _write(run, 'steps/prepare/outputs/fit.json', {'value': 2, 'inputs': [data]})
    reference = _write(run, 'steps/prepare/outputs/reference.json', {'value': 5})
    _adopt(store, data, 'outputs/data.json')
    _adopt(store, fit, 'outputs/fit.json', parents=['prepare:outputs/data.json'])
    _adopt(store, reference, 'outputs/reference.json')
    return run, store, {'fit': fit, 'reference': reference, 'data': data}


def test_missing_source_and_wrong_declared_type_are_distinct_refusals():
    steps = _steps()
    assert bindings.declaration_errors(steps[1], steps, [CLOSURE]) == []
    missing = deepcopy(steps)
    del missing[1]['parameters']['check_inputs'][CLOSURE]['fit']['source']
    problems = bindings.declaration_errors(missing[1], missing, [CLOSURE])
    assert len(problems) == 1 and problems[0][:2] == (CLOSURE, 'fit')
    assert problems[0][2].startswith('validator_source_missing:')
    wrong = deepcopy(steps)
    wrong[1]['parameters']['check_inputs'][CLOSURE]['fit']['type'] = 'path'
    problems = bindings.declaration_errors(wrong[1], wrong, [CLOSURE])
    assert len(problems) == 1 and problems[0][2].startswith('validator_source_type:')


@pytest.mark.parametrize('damage', ['dependency', 'input', 'output', 'optional', 'producer'])
def test_output_sources_require_a_required_output_input_and_dependency(damage):
    steps = _steps()
    if damage == 'dependency':
        steps[1]['depends_on'] = []
    elif damage == 'input':
        steps[1]['inputs'] = []
    elif damage == 'output':
        steps[0]['outputs'] = steps[0]['outputs'][1:]
    elif damage == 'optional':
        steps[0]['outputs'][0]['required'] = False
    else:
        steps[1]['parameters']['check_inputs'][CLOSURE]['fit']['step'] = 'absent'
    assert any(error.startswith('validator_source_missing:') for _, _, error in
               bindings.declaration_errors(steps[1], steps, [CLOSURE]))
    with pytest.raises(bindings.BindingError) as refusal:
        bindings.compile_inputs(steps, {})
    assert refusal.value.reason == 'validator_source_invalid'


def test_exported_json_fields_require_an_independent_matching_type():
    steps = _steps()
    steps[1]['parameters']['check_inputs'] = {CERTIFICATE: {
        'path': _source(kind='path'), 'kind': _source('outputs/data.json', 'string', field='/mode')}}
    assert bindings.declaration_errors(steps[1], steps, [CERTIFICATE]) == []
    steps[0]['parameters']['validator_exports']['outputs/data.json']['/mode'] = 'number'
    problems = bindings.declaration_errors(steps[1], steps, [CERTIFICATE])
    assert problems == [(CERTIFICATE, 'kind', 'validator_source_type: producer field export differs')]
    with pytest.raises(bindings.BindingError):
        bindings.compile_inputs(steps, {})


def test_contract_binding_uses_the_real_value_and_refuses_wrong_value_types():
    steps = _steps()
    source = {'source': 'contract', 'field': '/stat_mode', 'type': 'string'}
    steps[1]['parameters']['check_inputs'] = {CERTIFICATE: {'kind': source}}
    compiled = bindings.compile_inputs(deepcopy(steps), {'stat_mode': 'fixed'})
    assert compiled[1]['parameters']['check_inputs'][CERTIFICATE]['kind'] == 'fixed'
    assert steps[1]['parameters']['check_inputs'][CERTIFICATE]['kind'] == source
    with pytest.raises(bindings.BindingError) as refusal:
        bindings.compile_inputs(deepcopy(steps), {'stat_mode': ['fixed']})
    assert refusal.value.reason == 'validator_source_type'
    unresolved = bindings.compile_inputs(deepcopy(steps), {})[1]
    _, errors = bindings.resolve_inputs(unresolved['parameters']['check_inputs'], unresolved, run_dir='.')
    assert errors[CERTIFICATE]['reason'] == 'validator_source_unresolved'


@pytest.mark.parametrize('damage', ['no-store', 'no-custody', 'missing-field', 'unbound-contract'])
def test_unresolvable_sources_refuse_with_a_typed_reason(adopted, damage):
    run, store, _ = adopted
    step = _steps()[1]
    values = {CERTIFICATE: {'kind': _source('outputs/data.json', 'string', field='/mode')}}
    if damage == 'no-store':
        store = None
    elif damage == 'no-custody':
        values[CERTIFICATE]['kind']['path'] = 'outputs/absent.json'
        step['inputs'].append({'artifact': 'prepare:outputs/absent.json'})
    elif damage == 'missing-field':
        values[CERTIFICATE]['kind']['field'] = '/absent'
    else:
        values[CERTIFICATE]['kind'] = {'source': 'contract', 'field': '/stat_mode', 'type': 'string'}
    resolved, errors = bindings.resolve_inputs(values, step, run_dir=run, store=store)
    assert errors[CERTIFICATE]['reason'] == 'validator_source_unresolved'
    assert resolved[CERTIFICATE]['kind'] == values[CERTIFICATE]['kind']


def test_runtime_checks_the_resolved_field_type_even_when_its_export_claims_string(adopted):
    run, store, _ = adopted
    step = _steps()[1]
    values = {CERTIFICATE: {'kind': _source('outputs/data.json', 'string', field='/value')}}
    _, errors = bindings.resolve_inputs(values, step, run_dir=run, store=store)
    assert errors[CERTIFICATE]['reason'] == 'validator_source_type'


@pytest.mark.parametrize('changed', ['fit', 'data'])
def test_changed_source_or_transitive_custody_refuses(adopted, changed):
    run, store, pins = adopted
    step = _steps()[1]
    _write(run, pins[changed]['path'], {'changed': True})
    _, errors = bindings.resolve_inputs(step['parameters']['check_inputs'], step, run_dir=run, store=store)
    assert errors[CLOSURE]['reason'] == 'validator_source_changed'


def test_record_sources_are_closed_and_need_an_exact_observation(adopted):
    run, store, _ = adopted
    check = sorted(documents.ML_RESULT_CHECKS)[0]
    fields = {name: {'source': 'record', 'kind': documents.ML_OBSERVATION_KIND,
                      'field': name, 'type': kind} for name, kind in bindings.requirements(check).items()}
    step = _steps()[1]
    step['parameters']['check_inputs'] = {check: fields}
    assert bindings.declaration_errors(step, [step], [check]) == []
    _, errors = bindings.resolve_inputs({check: fields}, step, run_dir=run, store=store)
    assert errors[check]['reason'] == 'validator_source_unresolved'
    # This records a failed observation; resolving its identity does not manufacture a pass.
    refs = documents.record_ml_stage(store, spec={'value': 1}, stage='S1',
                                    result={'checks': {check: {'status': 'failed'}}})
    fields['record_id'] = refs[check]['record_id']
    resolved, errors = bindings.resolve_inputs({check: fields}, step, run_dir=run, store=store)
    assert errors == {} and resolved[check] == refs[check]
    fields['record_id'] = {'source': 'record', 'kind': documents.ML_OBSERVATION_KIND,
                           'field': 'record_id', 'type': 'string'}
    fields['subject_sha256']['kind'] = 'other-observation'
    assert bindings.declaration_errors(step, [step], [check]) == [
        (check, 'subject_sha256', 'validator_source_type: no matching controller record field')]


def test_composed_inert_plan_resolves_custody_into_the_real_closure_validator(adopted, tmp_path, monkeypatch):
    run, store, pins = adopted
    plan = routes.compile(_spec(_steps()), {}, {'task_mode': 'calculation'})
    assert routes.plan_errors(plan) == []
    step = plan['steps'][1]
    assert step['parameters']['check_inputs'][CLOSURE]['fit'] == _source()
    monkeypatch.setattr(review_independence, 'controller_store', lambda directory: store)
    result = validate.run_validators(CARD, step, run_dir=run, scratch=tmp_path / 'scratch')
    assert result['passed'] is True
    assert result['reviewer_items'] == []
    assert len(result['results']) == 1
    assert result['results'][0]['check_id'] == CLOSURE
    assert result['results'][0]['status'] == 'passed'
    assert len(result['results'][0]['result_sha256']) == 64
    # The real validator refuses a certifying reference reachable from the fit.
    dependent = deepcopy(step)
    dependent['parameters']['check_inputs'][CLOSURE]['reference'] = _source('outputs/data.json')
    refused = validate.run_validators(CARD, dependent, run_dir=run, scratch=tmp_path / 'scratch')
    assert refused['passed'] is False
    assert refused['results'][0]['status'] == 'failed'
    assert 'reference_in_input_closure' in refused['results'][0]['diagnostics']
    # Byte mutation refuses at the binding boundary before a validator can certify it.
    _write(run, pins['reference']['path'], {'value': 9})
    refused = validate.run_validators(CARD, step, run_dir=run, scratch=tmp_path / 'scratch')
    assert refused['passed'] is False
    assert refused['results'][0]['status'] == 'inconclusive'
    assert refused['results'][0]['reason'] == 'validator_source_changed'


def test_review_seat_requires_the_exact_reviewed_digest(adopted):
    run, store, pins = adopted
    step = _steps()[1]
    step['parameters']['seat_of'] = 'prepare'
    for item in step['inputs']:
        path = item['artifact'].split(':', 1)[1]
        item['sha256'] = next(pin['sha256'] for pin in pins.values() if pin['path'].endswith(path))
    resolved, errors = bindings.resolve_inputs(step['parameters']['check_inputs'], step, run_dir=run, store=store)
    assert errors == {} and resolved[CLOSURE] == {'fit': pins['fit'], 'reference': pins['reference']}
    replacement = _write(run, pins['fit']['path'], {'value': 7, 'inputs': [pins['data']]})
    _adopt(store, replacement, 'outputs/fit.json', parents=['prepare:outputs/data.json'])
    _, errors = bindings.resolve_inputs(step['parameters']['check_inputs'], step, run_dir=run, store=store)
    assert errors[CLOSURE]['reason'] == 'validator_source_changed'


def test_review_seat_refuses_unrelated_accepted_custody(adopted):
    run, store, pins = adopted
    seat = {'id': 'review', 'parameters': {'seat_of': 'prepare'}, 'depends_on': ['prepare'],
            'inputs': [{'artifact': 'prepare:outputs/fit.json', 'sha256': pins['fit']['sha256']}]}
    _, errors = bindings.resolve_inputs({CLOSURE: {'reference': _source('outputs/reference.json')}},
                                       seat, run_dir=run, store=store)
    assert errors[CLOSURE]['reason'] == 'validator_source_unresolved'


@pytest.fixture
def compiled_governed_plan(reference):
    paths = ['outputs/fit.json', 'outputs/reference.json', 'outputs/data.json']
    producer = make_step('prepare', outputs=[(path, 'result') for path in paths])
    consumer = make_step('inspect', role='calculation', depends_on=['prepare'],
                         outputs=[('outputs/inspection.json', 'result')],
                         inputs=[{'artifact': 'prepare:' + path} for path in paths],
                         parameters={'check_inputs': {CLOSURE: {
                             'fit': _source(), 'reference': _source('outputs/' + reference + '.json')}}})
    spec = _spec([producer, consumer])
    compiled = routes.compile(spec, {}, {'task_mode': 'calculation'})
    assert routes.plan_errors(compiled) == []
    return compiled


@pytest.fixture
def governed_env(compiled_governed_plan, run_env):
    run_env.store = RunStore('run-governed-bindings', root=run_env.root / 'protected')
    return run_env


@pytest.fixture
def governed_worker(governed_env, inert_worker):
    return inert_worker


@pytest.mark.parametrize('reference, expected', [('reference', 'completed'), ('data', 'failed')])
def test_governed_steps_adopt_sources_then_run_real_consumer_checks(
        compiled_governed_plan, governed_env, governed_worker, graphs, monkeypatch, reference, expected):
    from ravel.controller import step as governed
    env = governed_env
    compiled = compiled_governed_plan
    producer, consumer = compiled['steps']
    plan_sha = install_plan(env.store, compiled['steps'])
    monkeypatch.setattr(review_independence, 'controller_store', lambda directory: env.store)
    data = json.dumps({'value': 3}, sort_keys=True)
    values = {'outputs/data.json': data, 'outputs/reference.json': json.dumps({'value': 5}),
              'outputs/fit.json': json.dumps({'value': 2, 'inputs': [{
                  'path': 'steps/prepare/outputs/data.json',
                  'sha256': hashlib.sha256(data.encode()).hexdigest()}]})}
    governed_worker.scenario(writes=[{'path': path, 'content': content} for path, content in values.items()])
    first = governed.run(env.store, producer, context(env.store, env.run_dir, plan_sha))
    assert first['status'] == 'completed', first
    for path in values:
        history = [row['record'] for row in env.store.scan('custody')
                   if row['record']['artifact'] == 'prepare:' + path]
        assert [row['status'] for row in history] == ['staged', 'accepted']
        assert history[-1]['verdict_of']
        assert history[-1]['producer']['session_id']
        assert history[-1]['evidence']['validators']
        assert all(row['status'] == 'passed' for row in history[-1]['evidence']['validators'])
    governed_worker.scenario()
    second = governed.run(env.store, consumer, context(env.store, env.run_dir, plan_sha))
    assert second['status'] == expected, json.dumps({
        'outcome': second,
        'seats': [row['record'] for row in env.store.scan('step-outcome') if row['record'].get('seat')],
        'refusals': [row['record'] for row in env.store.scan('step-refusal')],
        'validation': [row['record'] for row in env.store.scan('step-validation')
                       if row['record'].get('seat')]}, sort_keys=True)
    reports = [row['record']['report'] for row in env.store.scan('step-validation')
               if row['record']['step_id'] == 'inspect' and row['record']['seat'] is None
               and 'report' in row['record']]
    assert len(reports) == 1
    actual = {row['check_id']: row for row in reports[0]['results']}
    assert set(actual) == {CLOSURE, 'check:validation.validate_task_contract.validate'}
    assert actual['check:validation.validate_task_contract.validate']['status'] == 'passed'
    assert actual[CLOSURE]['status'] == ('passed' if expected == 'completed' else 'failed')
    history = [row['record'] for row in env.store.scan('custody')
               if row['record']['artifact'] == 'inspect:outputs/inspection.json']
    assert [row['status'] for row in history] == ['staged', 'accepted' if expected == 'completed' else 'rejected']
    if expected == 'failed':
        assert second['reason'] == 'validators_failed'
        assert 'reference_in_input_closure' in actual[CLOSURE]['diagnostics']


def test_foreach_sources_bind_only_their_expanded_producers():
    producer = fakes.make_step('point', outputs=['outputs/fit.json', 'outputs/reference.json'],
                               foreach='coordinates', parameters={'check_inputs': {CLOSURE: {
                                   'fit': {**_source(), 'step': 'point'},
                                   'reference': {**_source('outputs/reference.json'), 'step': 'point'}}}})
    consumer = fakes.make_step('inspect', depends_on=['point'], outputs=['outputs/inspection.json'])
    spec = _spec([producer, consumer])
    spec['parameters'] = [{'name': 'coordinates', 'from': 'contract:coordinates', 'default': ['a', 'b']}]
    compiled = routes.compile(spec, {}, {})
    assert routes.plan_errors(compiled) == []
    left, right = compiled['steps'][:2]
    assert [left['id'], right['id']] == ['point.a', 'point.b']
    for step in (left, right):
        fields = step['parameters']['check_inputs'][CLOSURE]
        assert fields['fit']['step'] == fields['reference']['step'] == step['id']
        assert bindings.declaration_errors(step, compiled['steps'], [CLOSURE]) == []
    left['parameters']['check_inputs'][CLOSURE]['fit']['step'] = right['id']
    problems = bindings.declaration_errors(left, compiled['steps'], [CLOSURE])
    assert problems == [(CLOSURE, 'fit',
                         'validator_source_missing: output needs its declared input and dependency')]


@pytest.fixture
def bound_sweep(adopted, monkeypatch):
    run, store, _ = adopted
    task_contract(run)
    sweep = {'traps_checked': [f'T{i}' for i in range(1, 13)], 'traps_hit': [],
             'verdicts': [{'id': f'T{i}', 'hit': False, 'evidence': 'checked against the declared inputs'}
                          for i in range(1, 13)], 'escalations': []}
    pin = _write(run, 'steps/prepare/outputs/sweep.json', sweep)
    _adopt(store, pin, 'outputs/sweep.json')
    step = {'id': 'inspect', 'depends_on': ['prepare'],
            'inputs': [{'artifact': 'prepare:outputs/sweep.json'}],
            'parameters': {'check_inputs': {runs.TRAP_CHECK: {
                'sweep': _source('outputs/sweep.json', 'path')}}}}
    card = {**CARD, 'id': 'isolated-sweep', 'must_check': [runs.TRAP_CHECK,
                                                        'check:validation.validate_task_contract.validate']}
    monkeypatch.setattr(review_independence, 'controller_store', lambda directory: store)
    assert not (run / 'inputs/trap_sweep.json').exists()
    return run, store, step, card, sweep


def test_original_trap_validator_reads_the_custody_bound_output_without_a_canonical_file(bound_sweep, tmp_path):
    run, _, step, card, _ = bound_sweep
    report = validate.run_validators(card, step, run_dir=run, scratch=tmp_path / 'scratch')
    assert report['passed'] is True
    actual = {row['check_id']: row for row in report['results']}
    assert set(actual) == {runs.TRAP_CHECK, 'check:validation.validate_task_contract.validate'}
    assert all(row['status'] == 'passed' for row in actual.values())
    diagnostic = json.loads(actual[runs.TRAP_CHECK]['diagnostics'])
    assert diagnostic['path'] == 'steps/prepare/outputs/sweep.json'
    assert diagnostic['status'] == 'PASS'
    assert not (run / 'inputs/trap_sweep.json').exists()


def test_original_trap_validator_refuses_an_adopted_sweep_missing_one_trap(bound_sweep, tmp_path):
    run, store, step, card, sweep = bound_sweep
    sweep['traps_checked'].remove('T12')
    pin = _write(run, 'steps/prepare/outputs/sweep.json', sweep)
    _adopt(store, pin, 'outputs/sweep.json')
    report = validate.run_validators(card, step, run_dir=run, scratch=tmp_path / 'scratch')
    actual = {row['check_id']: row for row in report['results']}
    assert report['passed'] is False
    assert actual['check:validation.validate_task_contract.validate']['status'] == 'passed'
    assert actual[runs.TRAP_CHECK]['status'] == 'failed'
    assert 'T12' in actual[runs.TRAP_CHECK]['diagnostics']
    assert json.loads(actual[runs.TRAP_CHECK]['diagnostics'])['status'] == 'FAIL'


def test_trap_source_refuses_missing_and_changed_custody_before_the_validator(bound_sweep, tmp_path):
    run, _, step, card, sweep = bound_sweep
    missing = deepcopy(step)
    missing['inputs'] = [{'artifact': 'prepare:outputs/absent.json'}]
    missing['parameters']['check_inputs'][runs.TRAP_CHECK]['sweep']['path'] = 'outputs/absent.json'
    report = validate.run_validators(card, missing, run_dir=run, scratch=tmp_path / 'scratch')
    result = next(row for row in report['results'] if row['check_id'] == runs.TRAP_CHECK)
    assert report['passed'] is False and result['status'] == 'inconclusive'
    assert result['reason'] == 'validator_source_unresolved'
    sweep['traps_checked'].remove('T12')
    _write(run, 'steps/prepare/outputs/sweep.json', sweep)
    report = validate.run_validators(card, step, run_dir=run, scratch=tmp_path / 'scratch')
    result = next(row for row in report['results'] if row['check_id'] == runs.TRAP_CHECK)
    assert report['passed'] is False and result['status'] == 'inconclusive'
    assert result['reason'] == 'validator_source_changed'
    assert not (run / 'inputs/trap_sweep.json').exists()


@pytest.mark.parametrize('delivered, passed', [(1.0, True), (.5, False)])
def test_optional_normalization_yields_are_byte_bound_and_recomputed(adopted, tmp_path, monkeypatch, delivered, passed):
    run, store, _ = adopted
    check = 'check:physics.normalization_ledger.check'
    ledger = {'schema_version': 1, 'sample': 'unit-weight toy',
              'luminosity': {'value': 1., 'unit': 'pb^-1', 'source': 'declared toy'},
              'sigma': {'value': 2., 'unit': 'pb', 'order': 'LO', 'tool': 'toy',
                        'pdf': 'none', 'scales': 'none', 'process_basis': 'toy', 'source': 'declared toy'},
              'generated': {'sumw': 100., 'sumw2': 100.},
              'selected': {'X': {'sumw': [50.], 'sumw2': [50.]}}, 'bin_convention': 'per-bin'}
    for path, value in [('ledger.json', ledger), ('yields.json', {'X': [delivered]})]:
        pin = _write(run, 'steps/prepare/outputs/' + path, value)
        _adopt(store, pin, 'outputs/' + path)
    producer = {'id': 'prepare', 'outputs': [{'path': 'outputs/ledger.json'}, {'path': 'outputs/yields.json'}]}
    step = {'id': 'inspect', 'depends_on': ['prepare'],
            'inputs': [{'artifact': 'prepare:outputs/' + name} for name in ('ledger.json', 'yields.json')],
            'parameters': {'check_inputs': {check: {'ledger': _source('outputs/ledger.json', 'path'),
                                                   'delivered': _source('outputs/yields.json', 'path')}}}}
    assert bindings.declaration_errors(step, [producer, step], [check]) == []
    bindings.compile_inputs([producer, step], {})
    monkeypatch.setattr(review_independence, 'controller_store', lambda _: store)
    card = {'id': 'normalization-auditor', 'family': 'review', 'independence': {'kind': 'reviewer'},
            'must_check': [check]}
    report = validate.run_validators(card, step, run_dir=run, scratch=tmp_path / 'scratch')
    assert report['passed'] is passed
    assert report['results'][0]['status'] == ('passed' if passed else 'failed')
    bad = deepcopy(step); bad['parameters']['check_inputs'][check]['delivered']['type'] = 'number'
    with pytest.raises(bindings.BindingError) as error:
        bindings.compile_inputs([producer, bad], {})
    assert error.value.reason == 'validator_source_invalid'


@pytest.fixture
def retried_launch(tmp_path):
    """Adopt two real inventories through the dispatcher's immutable/logical wrapper."""
    from ravel.controller.step import cards, graph
    from ravel.workflow import role_registry

    run = tmp_path / 'retry-run'
    store = _frozen(RunStore.create(run, root=tmp_path / 'retry-store', run_id='retry-bindings'))
    producer = make_step('prepare', role='baseline-producer', outputs=[('outputs/data.json', 'result')],
                         parameters={'validator_exports': {'outputs/data.json': {'/mode': 'string'}}})
    card = role_registry.load('baseline-producer')
    adopted = []
    for attempt, mode in [(1, 'original'), (2, 'corrected')]:
        output_root = run / f'steps/prepare/attempts/{attempt}/outputs'
        pin = _write(run, (output_root / 'data.json').relative_to(run).as_posix(), {'mode': mode})
        adoption_store, physical = graph._adoption_scope(store, producer, attempt)
        rows = custody.launch_adoption(
            adoption_store, run_dir=run, step=physical, attempt=attempt, card=card,
            launch={'output_root': str(output_root), 'inventory': [
                {'path': 'data.json', 'sha256': pin['sha256']}], 'exit_status': 0},
            outputs=cards.declared_outputs(card, producer), inputs_custody=[])
        row, = rows
        assert row['step_id'] == 'prepare' and row['artifact'] == 'prepare:outputs/data.json'
        assert row['destination'] == custody.attempt_destination('prepare', 'outputs/data.json', attempt)
        assert row['status'] == 'staged'
        adopted.append(row)
        if attempt == 1:
            custody.accept(store, rows, 'accepted')
    values = {CERTIFICATE: {'kind': _source('outputs/data.json', 'string', field='/mode')},
              CLOSURE: {'fit': _source('outputs/data.json')}}
    return run, store, producer, values, adopted


def test_second_staged_launch_binds_own_export_then_accepted_consumer_to_current_bytes(retried_launch):
    run, store, producer, values, (first, second) = retried_launch
    original = (run / first['destination']).read_bytes()
    assert json.loads(original) == {'mode': 'original'}
    assert second['destination'] != first['destination']
    assert second['sha256'] != first['sha256']
    resolved, errors = bindings.resolve_inputs(values, producer, run_dir=run, store=store)
    assert errors == {}
    pin = {'path': second['destination'], 'sha256': hashlib.sha256(
        (run / second['destination']).read_bytes()).hexdigest()}
    assert resolved == {CERTIFICATE: {'kind': 'corrected'}, CLOSURE: {'fit': pin}}
    consumer = make_step('inspect', depends_on=['prepare'], inputs=[{
        'artifact': second['artifact'], 'sha256': second['sha256']}])
    _, staged_errors = bindings.resolve_inputs(values, consumer, run_dir=run, store=store)
    assert {error['reason'] for error in staged_errors.values()} == {'validator_source_unresolved'}
    custody.accept(store, [second], 'accepted')
    resolved, errors = bindings.resolve_inputs(values, consumer, run_dir=run, store=store)
    assert errors == {} and resolved[CLOSURE]['fit'] == pin
    assert resolved[CERTIFICATE]['kind'] == 'corrected'
    input_errors, found, run_inputs = custody.input_errors(store, consumer, run)
    assert input_errors == [] and run_inputs == []
    assert len(found) == 1 and found[0]['sha256'] == pin['sha256']
    assert found[0]['destination'] == second['destination']
    assert (run / first['destination']).read_bytes() == original
    history = [row['record'] for row in store.scan(custody.CUSTODY)]
    assert [(row['attempt'], row['status']) for row in history] == [
        (1, 'staged'), (1, 'accepted'), (2, 'staged'), (2, 'accepted')]


@pytest.mark.parametrize('scope', ['own-staged', 'accepted-consumer'])
@pytest.mark.parametrize('damage', ['first-destination', 'arbitrary-destination', 'changed-bytes', 'rejected'])
def test_retry_binding_refuses_wrong_destination_changed_bytes_and_rejected_status(retried_launch, scope, damage):
    run, store, producer, values, (first, second) = retried_launch
    step = producer
    if scope == 'accepted-consumer':
        custody.accept(store, [second], 'accepted')
        step = make_step('inspect', depends_on=['prepare'], inputs=[{
            'artifact': second['artifact'], 'sha256': second['sha256']}])
    if damage == 'changed-bytes':
        _write(run, second['destination'], {'mode': 'tampered'})
    else:
        record = deepcopy(custody.custody_index(store)[second['artifact']])
        if damage == 'first-destination':
            record['destination'] = first['destination']
            record['sha256'] = first['sha256']  # correct hash and real bytes, wrong attempt namespace
        elif damage == 'arbitrary-destination':
            raw = (run / second['destination']).read_bytes()
            arbitrary = run / 'inputs/copied-current.json'
            arbitrary.parent.mkdir(exist_ok=True)
            arbitrary.write_bytes(raw)
            record['destination'] = arbitrary.relative_to(run).as_posix()
            assert hashlib.sha256(raw).hexdigest() == record['sha256']
        else:
            record['status'] = 'rejected'
        store.append(custody.CUSTODY, record)
    resolved, errors = bindings.resolve_inputs(values, step, run_dir=run, store=store)
    expected = 'validator_source_changed' if damage == 'changed-bytes' else 'validator_source_unresolved'
    assert set(errors) == {CERTIFICATE, CLOSURE}
    assert {error['reason'] for error in errors.values()} == {expected}
    assert resolved == values
    assert json.loads((run / first['destination']).read_text()) == {'mode': 'original'}


def test_retry_review_requires_current_subject_sha_instead_of_immutable_first_attempt(retried_launch):
    run, store, _, values, (first, second) = retried_launch
    custody.accept(store, [second], 'accepted')
    seat = make_step('review', kind='review', depends_on=['prepare'],
                     parameters={'seat_of': 'prepare'}, inputs=[{
                         'artifact': second['artifact'], 'sha256': first['sha256']}])
    _, errors = bindings.resolve_inputs(values, seat, run_dir=run, store=store)
    assert set(errors) == {CERTIFICATE, CLOSURE}
    assert {error['reason'] for error in errors.values()} == {'validator_source_changed'}
    seat['inputs'][0]['sha256'] = second['sha256']
    resolved, errors = bindings.resolve_inputs(values, seat, run_dir=run, store=store)
    assert errors == {} and resolved[CERTIFICATE]['kind'] == 'corrected'
    assert resolved[CLOSURE]['fit'] == {'path': second['destination'], 'sha256': second['sha256']}


@pytest.mark.parametrize('attempt', [True, False, 0, -1])
def test_adoption_attempt_helpers_reject_nonpositive_or_boolean_attempts(attempt):
    with pytest.raises(ValueError, match='positive integer'):
        custody.attempt_step_id('prepare', attempt)
    with pytest.raises(ValueError, match='positive integer'):
        custody.attempt_destination('prepare', 'outputs/data.json', attempt)


def test_adoption_attempt_namespace_preserves_first_and_disambiguates_truncated_ids():
    from ravel.controller.step.services import digest

    prefix = 'p' * 80
    left, right = prefix + 'left', prefix + 'right'
    assert custody.attempt_step_id(left, 1) == left
    for logical in [left, right]:
        expected = prefix + '.attempt-2.' + digest(logical)[:12]
        assert custody.attempt_step_id(logical, 2) == expected
        assert custody.attempt_destination(logical, 'outputs/data.json', 2) == f'steps/{expected}/outputs/data.json'
    assert custody.attempt_step_id(left, 2) != custody.attempt_step_id(right, 2)
    assert custody.attempt_step_id(left, 2) != custody.attempt_step_id(left, 3)
