"""P17: the ``ml.training`` route as typed stage steps, their R12 admission, and the route adapter.

The adapter reads only adopted artifacts (custody records and digests in a fake run store), spends the
withheld population in the exposure ledger of the test lock domain, and records its ending. No
controller core, model, provider or network is needed; the compile test runs when the core is merged.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from test_p06_support import operator_home  # noqa: F401

from ravel.controller.routes import ml
from ravel.controller.routes.ml import staged, training
from ravel.physics import ml_exposure
from ravel.workflow import ml_stages

import p17_support as support

PARAMS = {'python': '/opt/interpreter/bin/python3', 'dataset_path': '/data/fixture/table.npz', 'dataset_sha256': 'a' * 64}
DELIVERABLES = (('table', 'method_performance'), ('selection', None), (None, 'document'))
STEP_STAGE = {'t02-admit': 'admit', 't03-features': 'features', 't04-smoke': 'train', 't05-train': 'train',
              't06-evaluate': 'evaluate', 't07-card': 'card', 't08-review': 'review'}


def staged_plan(**params):
    return support.plan('ml.training', {**PARAMS, **params}, deliverables=DELIVERABLES)


def steps(found):
    return {s['id']: s for s in found['steps']}


def approved(found):
    return lambda kind, pins: {'id': kind} if kind == 'approve_plan' and pins == {'plan_sha256': found['sha256']} else None


def unblinded(found, step_id='t06-evaluate'):
    """CHECK-IN 1 plus the R3 unblind authority of the one withheld read, bound to its plan, step and operation."""
    def authority(kind, pins):
        if kind == 'approve_plan' and pins == {'plan_sha256': found['sha256']}:
            return {'id': kind}
        if kind == 'r3_action' and pins == {'plan_sha256': found['sha256'], 'step': step_id,
                                             'operation': 'ml-stage-evaluate'}:
            return {'id': kind}
        return None
    return authority


def admit(step, found, authority=None, **extra):
    return ml.admit(step, plan=found, authority=authority, signature_table=staged.signatures(),
                    executors={'operations': staged.executors()}, **extra)


def codes(errors):
    return [e['code'] for e in errors]


# ---- the route spec -----------------------------------------------------------------------------

def test_P17_training_route_is_the_typed_stage_plan():
    found = staged_plan()
    by_id = steps(found)
    assert list(by_id) == ['t01-spec', 't02-admit', 't03-features', 't04-smoke', 't05-train', 't06-evaluate',
                           't07-card', 't08-review', 't09-report']
    for step_id, stage in STEP_STAGE.items():
        step = by_id[step_id]
        assert step['kind'] == 'operate' and step['operation'] == f'ml-stage-{stage}' and step['role'] == 'ml-trainer'
        argv = step['parameters']['launch']['argv']
        assert argv[:5] == [PARAMS['python'], '-I', '-m', 'ravel.workflow.ml_stages', stage]
        assert int(argv[argv.index('--wall-seconds') + 1]) == step['budget']['wall_seconds']
        assert [o['path'] for o in step['outputs']] == [p for p, _ in ml_stages.OUTPUTS[stage]]
        named = [a.split('=', 1) for a in argv[argv.index('--root') + 2:] if '=' in a and not a.startswith('--')]
        assert [n for n, _ in named] == list(ml_stages.INPUTS[stage])
        # Every input the stage opens is a declared, custody-checked input of the step.
        declared = {f"steps/{i['artifact'].replace(':', '/', 1)}" for i in step['inputs']}
        assert {path for _, path in named} == declared
        assert step['budget']['attempts'] == 1
    assert by_id['t02-admit']['parameters']['launch']['reads'] == [PARAMS['dataset_path']]
    assert PARAMS['dataset_sha256'] in by_id['t02-admit']['parameters']['launch']['argv']
    assert [s for s in found['steps'] if training.reads_withheld(s)] == [by_id['t06-evaluate']]
    assert found['waypoints'] == ['t04-smoke'] and '--smoke' in by_id['t04-smoke']['parameters']['launch']['argv']
    assert {s['id'] for s in found['steps'] if (s.get('parameters') or {}).get('phase') == 'prepare'} == {
        't01-spec', 't02-admit', 't03-features'}
    assert training.staged_plan_errors(found) == []
    assert {r['id']: r['step'] for r in found['deliverables']} == {'D1': 't06-evaluate', 'D2': 't05-train',
                                                                    'D3': 't09-report'}


def test_P17_every_staged_step_is_admitted_with_its_full_contract():
    found = staged_plan()
    for step in found['steps']:
        prepared = (step.get('parameters') or {}).get('phase') == 'prepare'
        assert admit(step, found, None if prepared else unblinded(found)) == [], step['id']
        assert ml.governed(step) == ('ml-training' if step['id'] in STEP_STAGE else None)


def test_P17_signatures_and_executors_describe_every_stage():
    rows = staged.signatures()
    assert set(rows) == set(training.STAGED_OPERATIONS) == set(staged.executors())
    for stage in ml_stages.STAGES:
        row = rows[f'ml-stage-{stage}']
        assert row['implementation'] == {'kind': 'command', 'module': training.STAGE_MODULE}
        assert {p['kind'] for p in row['produces']} == {k for _, k in ml_stages.OUTPUTS[stage]}
    installed = ml.modes.signatures()
    registered = [op for op in training.STAGED_OPERATIONS if op in installed]
    for op in registered:  # once the integrator registers them, the registry carries these contracts
        assert installed[op] == rows[op]


def test_R12_staged_training_on_an_inference_route_refused():
    found = staged_plan()
    found['route'] = {'id': 'ml.inference', 'version': 1, 'spec_sha256': '0' * 64}
    assert 'ml_training_outside_training_route' in codes(admit(steps(found)['t05-train'], found, approved(found)))


def test_R12_staged_training_given_the_withheld_partition_refused():
    found = staged_plan()
    train = steps(found)['t05-train']
    train['inputs'].append({'artifact': 't02-admit:outputs/partitions/test.npz', 'kind': 'table'})
    assert 'ml_withheld_partition_read' in codes(admit(train, found, approved(found)))
    assert codes(training.staged_plan_errors(found)) == ['ml_withheld_partition_read']


def test_R12_full_training_without_a_smoke_waypoint_refused():
    found = staged_plan()
    train = steps(found)['t05-train']
    train['depends_on'].remove('t04-smoke')
    assert 'ml_training_without_smoke' in codes(admit(train, found, approved(found)))
    smoke = steps(staged_plan())['t04-smoke']
    smoke['waypoint'] = False
    assert 'ml_training_smoke_not_waypoint' in codes(training.staged_errors(smoke, staged_plan()))


def test_R12_a_second_read_of_the_withheld_partition_refused():
    found = staged_plan()
    again = deepcopy(steps(found)['t06-evaluate'])
    again['id'] = 't06-evaluate-again'
    found['steps'].append(again)
    assert codes(training.staged_plan_errors(found)) == ['ml_test_once_violated']


def test_R12_staged_launch_running_another_program_refused():
    found = staged_plan()
    train = steps(found)['t05-train']
    argv = train['parameters']['launch']['argv']
    argv[argv.index('ravel.workflow.ml_stages')] = 'ravel.physics.ml_training'
    assert 'ml_stage_launch_mismatch' in codes(admit(train, found, approved(found)))


def test_R12_dry_stages_run_before_checkin1_and_training_needs_it():
    found = staged_plan()
    by_id = steps(found)
    assert admit(by_id['t02-admit'], found, None) == []
    assert admit(by_id['t03-features'], found, None) == []
    assert 'mode_authority_missing' in codes(admit(by_id['t05-train'], found, lambda kind, pins: None))
    assert 'mode_authority_unavailable' in codes(admit(by_id['t06-evaluate'], found, None))
    wet = deepcopy(by_id['t02-admit'])
    wet['rung'] = 'full'
    assert 'ml_stage_rung' in codes(admit(wet, found, approved(found)))


def test_R12_the_withheld_read_needs_its_own_R3_unblind_authority():
    """Reading the withheld partition is unblinding (always R3); CHECK-IN 1 and the smoke GO do not cover it."""
    found = staged_plan()
    evaluate = steps(found)['t06-evaluate']
    assert evaluate['consequence_class'] == 'R3'
    assert codes(admit(evaluate, found, approved(found))) == ['ml_unblind_authority_missing']
    assert codes(admit(evaluate, found, unblinded(found, step_id='t05-train'))) == ['ml_unblind_authority_missing']
    assert admit(evaluate, found, unblinded(found)) == []
    # The full training launch reads no withheld data: an R2 launch after the smoke GO, no unblind authority.
    assert admit(steps(found)['t05-train'], found, approved(found)) == []
    lowered = deepcopy(evaluate)
    lowered['consequence_class'] = 'R2'
    assert 'ml_unblind_class_lowered' in codes(admit(lowered, found, unblinded(found)))


def test_R12_staged_training_holds_when_the_staged_executor_is_absent(monkeypatch):
    import importlib
    real = importlib.import_module

    def absent(name, *args, **kwargs):
        if name == training.PROVIDER:
            raise ImportError(f'No module named {name!r}')
        return real(name, *args, **kwargs)
    monkeypatch.setattr(importlib, 'import_module', absent)
    found = staged_plan()
    errors = admit(steps(found)['t05-train'], found, approved(found))
    assert codes(errors) == ['ml_training_prerequisites_unmet'] and errors[0]['hold'] == training.PREREQUISITE_HOLD
    assert admit(steps(found)['t06-evaluate'], found, unblinded(found)) == []  # evaluation trains nothing


def test_R12_installed_staged_executor_meets_the_prerequisite():
    assert training.prerequisites() == []


# ---- the adapter: parameters --------------------------------------------------------------------

def test_P17_parameters_bind_one_supplied_table():
    one = [{'kind': 'file', 'path': '/data/a.npz', 'sha256': 'b' * 64}, {'kind': 'model', 'path': '/m.slha', 'sha256': 'c' * 64}]
    bound = staged.parameters({}, {}, {}, one)
    assert bound['dataset_path'] == '/data/a.npz' and bound['dataset_sha256'] == 'b' * 64 and bound['python']
    two = one + [{'kind': 'measurement', 'path': '/data/b.csv', 'sha256': 'd' * 64}]
    assert 'dataset_path' not in staged.parameters({}, {}, {}, two)
    explicit = two + [{'kind': 'ml-table', 'path': '/data/c.root', 'sha256': 'e' * 64}]
    assert staged.parameters({}, {}, {}, explicit)['dataset_path'] == '/data/c.root'
    assert 'dataset_path' not in staged.parameters({}, {}, {}, [{'kind': 'directory', 'path': '/data/d.npz', 'sha256': None}])


# ---- the adapter: stage checks against adopted artifacts -------------------------------------------

class Run:
    """The stages run in-process; their outputs adopted under the plan's step ids with custody records."""

    def __init__(self, tmp_path, document=None, data=None):
        self.tmp = tmp_path
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.run_dir = tmp_path / 'run'
        self.store = support.Store(tmp_path / 'store')
        if data is None:
            data = tmp_path / 'table.npz'
            support.table(data)
        self.pipeline = support.Pipeline(tmp_path / 'stages', document or support.spec(), data=data,
                                         digest=support.sha(data))
        self.plan = support.plan('ml.training', {**PARAMS, 'dataset_path': str(data),
                                                 'dataset_sha256': support.sha(data)}, deliverables=DELIVERABLES)
        self.steps = steps(self.plan)
        target = self.pipeline.root / 'spec-step' / 'outputs' / 'ml_study_spec.json'
        target.parent.mkdir(parents=True)
        target.write_bytes((self.pipeline.root / 'spec.json').read_bytes())
        support.adopt(self.store, self.run_dir, 't01-spec', self.pipeline.root / 'spec-step', [staged.SPEC_OUTPUT])

    def context(self):
        return {'store': self.store, 'run_dir': self.run_dir, 'plan': self.plan, 'state': {}, 'reading': {},
                'contract': {}}

    def stage(self, step_id, **options):
        stage = STEP_STAGE[step_id]
        if step_id == 't04-smoke':
            from ravel.workflow import ml_stages as stages
            inputs = {n: self.pipeline.root / support.SOURCES[n] for n in support.STAGE_INPUTS['train']}
            receipt = stages.run_stage('train', inputs, {'smoke': True, 'wall_seconds': 1800}, self.pipeline.root / 'smoke')
            workdir = self.pipeline.root / 'smoke'
        else:
            receipt = self.pipeline.run(stage, **options)
            workdir = self.pipeline.root / stage
        support.adopt(self.store, self.run_dir, step_id, workdir,
                      [p for p, _ in ml_stages.OUTPUTS[stage]])
        return receipt

    def check(self, step_id):
        return staged.step(self.steps[step_id], {'status': 'completed'}, self.context())


def exposure(sha):
    return ml_exposure._load(ml_exposure._record_path(sha))


def test_P17_adapter_accepts_every_completed_stage_and_spends_the_withheld_population_once(tmp_path):
    run = Run(tmp_path)
    for step_id in ('t02-admit', 't03-features'):
        run.stage(step_id)
        assert run.check(step_id) == []
    assert staged.gate('checkin1->execute', run.context()) == []
    run.stage('t04-smoke')
    assert run.check('t04-smoke') == []
    run.stage('t05-train')
    test_sha = json.loads((run.run_dir / 'steps/t02-admit/outputs/admission.json').read_text())[
        'partitions']['test']['identity_sha256']
    assert exposure(test_sha) is None  # nothing spent before the full training completes
    assert run.check('t05-train') == []
    spent = exposure(test_sha)
    assert spent['roles'] == ['test_split'] and [r['context'] for r in spent['reads']] == ['test']
    assert spent['state'] == 'claimed'
    for step_id in ('t06-evaluate', 't07-card', 't08-review'):
        run.stage(step_id)
        assert run.check(step_id) == [], step_id
    assert exposure(test_sha)['state'] == 'complete'
    stages = [r['record'] for r in run.store.scan(staged.STAGE_RECORD)]
    assert [r['step_id'] for r in stages] == ['t02-admit', 't03-features', 't04-smoke', 't05-train', 't06-evaluate',
                                              't07-card', 't08-review']
    assert all(r['accepted'] and r['status'] == 'completed' for r in stages)
    assert staged.gate('checkin3->deliver', run.context()) == []
    states = [r['record']['state'] for r in run.store.scan(staged.EXPOSURE_RECORD)]
    assert states == ['claiming', 'spent', 'complete']
    # A replayed check (a resumed controller) spends nothing twice.
    assert run.check('t05-train') == []
    assert len(exposure(test_sha)['reads']) == 1


def test_P17_adapter_fails_a_refused_stage_with_its_typed_code(tmp_path):
    data = tmp_path / 'leaky.npz'
    support.table(data, leak=True)
    run = Run(tmp_path, data=data)
    run.stage('t02-admit')
    run.stage('t03-features')
    problems = run.check('t03-features')
    assert len(problems) == 1 and problems[0].startswith('ml_label_leakage: features stage refused')
    record = run.store.scan(staged.STAGE_RECORD)[-1]['record']
    assert record['accepted'] is False and record['codes'] == ['ml_label_leakage']


def test_P17_adapter_refuses_bytes_that_differ_from_custody(tmp_path):
    run = Run(tmp_path)
    run.stage('t02-admit')
    receipt = run.run_dir / 'steps/t02-admit' / ml_stages.RECEIPT
    receipt.write_text(receipt.read_text().replace('"completed"', '"completed" '))
    problems = run.check('t02-admit')
    assert problems and problems[0].startswith('ml_stage_receipt_missing')


def test_P17_checkin1_refuses_a_withheld_population_another_study_used(tmp_path):
    first = Run(tmp_path / 'first')
    for step_id in ('t02-admit', 't03-features', 't04-smoke', 't05-train'):
        first.stage(step_id)
        assert first.check(step_id) == []
    # A second run on the same table and split: the withheld population was already read.
    second = Run(tmp_path / 'second', data=first.pipeline.data)
    for step_id in ('t02-admit', 't03-features'):
        second.stage(step_id)
    errors = staged.gate('checkin1->execute', second.context())
    assert [e['code'] for e in errors] == ['ml_withheld_population_spent']
    for step_id in ('t04-smoke', 't05-train'):
        second.stage(step_id)
    assert second.check('t05-train')[0].startswith('ml_withheld_population_spent')


def test_P17_checkin1_names_a_missing_backend(tmp_path, monkeypatch):
    from ravel.physics import ml_backends
    run = Run(tmp_path)
    run.stage('t02-admit')
    run.stage('t03-features')
    monkeypatch.setattr(ml_backends, 'available', lambda: {'numpy': False, 'sklearn': False, 'torch': False,
                                                             'torch-geometric': False})
    assert [e['code'] for e in staged.gate('checkin1->execute', run.context())] == ['ml_backend_unavailable'] * 2


def test_P17_ending_closes_a_spent_unevaluated_population_and_records_the_qualified_state(tmp_path):
    run = Run(tmp_path)
    for step_id in ('t02-admit', 't03-features', 't04-smoke', 't05-train'):
        run.stage(step_id)
        assert run.check(step_id) == []
    record = staged.ending('the evaluation launch failed', run.context())
    assert record['exposure'] == 'closed_failed' and record['accepted_label'] is False
    assert record['completed'] == ['t02-admit', 't03-features', 't04-smoke', 't05-train']
    assert record['unfinished'] == ['t06-evaluate', 't07-card', 't08-review']
    test_sha = run.store.scan(staged.EXPOSURE_RECORD)[-1]['record']['test_sha256']
    assert exposure(test_sha)['state'] == 'failed' and len(exposure(test_sha)['reads']) == 1
    assert run.store.scan(staged.ENDING_RECORD)[-1]['record'] == record


def test_P17_budget_exhausted_training_fails_the_step_and_ends_qualified(tmp_path):
    run = Run(tmp_path, document=support.spec(epochs=100000, wall=1))
    for step_id in ('t02-admit', 't03-features'):
        run.stage(step_id)
    run.stage('t05-train')
    problems = run.check('t05-train')
    assert problems and problems[0].startswith('ml_training_budget_exhausted')
    assert run.store.scan(staged.EXPOSURE_RECORD) == []  # nothing spent for an incomplete training
    record = staged.ending(problems[0], run.context())
    assert 't05-train' in record['unfinished'] and record['exposure'] is None


def test_P17_checkin_views_carry_the_stage_evidence(tmp_path):
    run = Run(tmp_path)
    for step_id in ('t02-admit', 't03-features'):
        run.stage(step_id)
    # The controller asks with the authority kind of the point and merges items, flags and pins.
    found = staged.checkin('approve_plan', run.context())
    first = found['ml_training']
    assert first['leakage']['verdict'] == 'pass' and first['partitions']['train']['rows'] > 0
    assert found['items']['ml_training'] and all(type(row) is str for row in found['items']['ml_training'])
    assert any(row.startswith('leakage: ') for row in found['items']['ml_training'])
    custody = staged.custody_index(run.store)  # pins name the adopted records the view was read from
    assert found['pins'] == {'ml_admission_sha256': custody['t02-admit:outputs/admission.json']['sha256'],
                             'ml_features_sha256': custody['t03-features:outputs/features.json']['sha256']}
    assert staged.checkin('checkin1', run.context())['ml_training'] == first
    run.stage('t04-smoke')
    second = staged.checkin('go', run.context())['ml_training']
    assert second['smoke']['status'] == 'completed' and second['full_training']['t05-train']['wall_seconds'] == 43200
    final = staged.checkin('final', run.context())
    assert 'unavailable' in final['ml_training'] and not final['items']
    assert [f['kind'] for f in final['flags']] == ['risk'] and 'unavailable' in final['flags'][0]['text']
    assert staged.checkin('r3_action', run.context()) == {}


def test_P17_delivery_gate_refuses_without_passed_reviewer_items(tmp_path):
    run = Run(tmp_path)
    errors = staged.gate('checkin3->deliver', run.context())
    assert [e['code'] for e in errors] == ['ml_review_failed']


# ---- with the controller core (P01) ----------------------------------------------------------------

def test_P17_training_route_compiles_with_the_controller_core():
    try:
        from ravel.controller.routes import compiler
        from importlib import import_module
        select = import_module('ravel.controller.routes.select')
    except ImportError as exc:
        pytest.skip(f'the controller core (P01) is not merged: {exc}')
    spec = support.route_spec('ml.training')
    assert select.spec_errors(spec) == []
    reading = {'facts': [], 'constraints': [], 'deliverables': [{'id': 'D1', 'artifact': {'kind': 'table'},
                                                                 'claim_kind': 'method_performance'}]}
    supplied = [{'kind': 'file', 'path': '/data/fixture/table.npz', 'sha256': 'f' * 64, 'size': 1}]
    bound = compiler.compile(spec, reading, {}, supplied=supplied)
    assert compiler.plan_errors(bound) == [] and bound['open_obligations'] == []
    admit_step = next(s for s in bound['steps'] if s['id'] == 't02-admit')
    assert '/data/fixture/table.npz' in admit_step['parameters']['launch']['argv']
    unbound = compiler.compile(spec, reading, {}, supplied=[])
    assert {row['id'] for row in unbound['open_obligations']} >= {'parameter:dataset_path', 'parameter:dataset_sha256'}


def test_P17_stage_receipt_must_be_declared_for_adoption():
    found = staged_plan()
    row = steps(found)['t05-train']
    row['outputs'] = [o for o in row['outputs'] if o['path'] != ml_stages.RECEIPT]
    assert 'ml_stage_receipt_undeclared' in codes(admit(row, found, approved(found)))


def test_P17_training_cannot_read_an_extra_raw_dataset():
    found = staged_plan()
    row = steps(found)['t05-train']
    row['parameters']['launch']['reads'] = ['/data/hidden-table.npz']
    assert 'ml_stage_excess_reads' in codes(admit(row, found, approved(found)))


def test_P17_no_training_program_before_the_declared_stage_module():
    found = staged_plan()
    row = steps(found)['t05-train']
    row['parameters']['launch']['argv'][1:1] = ['-c', 'raise RuntimeError()']
    assert 'ml_stage_launch_mismatch' in codes(admit(row, found, approved(found)))


def test_P17_later_refused_review_cannot_reuse_an_earlier_pass(tmp_path):
    run = Run(tmp_path)
    for accepted in (True, False):
        run.store.append(staged.STAGE_RECORD, {'step_id': 't08-review', 'stage': 'review', 'accepted': accepted,
                                              'plan_sha256': run.plan['sha256']})
    assert [e['code'] for e in staged.gate('checkin3->deliver', run.context())] == ['ml_review_failed']


def test_P17_custody_destination_cannot_escape_the_run(tmp_path):
    run = Run(tmp_path)
    run.stage('t02-admit')
    record = staged.custody_index(run.store)['t02-admit:' + ml_stages.RECEIPT]
    record['destination'] = '../outside.json'
    outside = run.run_dir.parent / 'outside.json'
    outside.write_text('{}')
    record['sha256'] = support.sha(outside)
    run.store.append('custody', record)
    assert run.check('t02-admit')[0].startswith('ml_stage_receipt_missing')


def test_P17_judgment_training_uses_the_same_sink_receipt_gate(tmp_path):
    run = Run(tmp_path)
    run.plan['route']['id'] = 'judgment'
    assert len(staged.delivery_errors_from_store(run.store, run.plan)) == 7
    for row in run.plan['steps']:
        if staged.stage_of(row):
            run.store.append(staged.STAGE_RECORD, {'step_id': row['id'], 'stage': staged.stage_of(row),
                'accepted': True, 'status': 'completed', 'plan_sha256': run.plan['sha256']})
    assert staged.delivery_errors_from_store(run.store, run.plan) == []
    run.store.append(staged.STAGE_RECORD, {'step_id': 't08-review', 'stage': 'review',
        'accepted': False, 'status': 'refused', 'plan_sha256': run.plan['sha256']})
    assert staged.delivery_errors_from_store(run.store, run.plan) == [
        {'code': 'ml_stage_unreceipted', 'step': 't08-review', 'stage': 'review'}]


@pytest.mark.parametrize('extra', [
    {'kind': 'file', 'path': '/data/other.csv', 'sha256': None},
    {'kind': 'ml-table', 'path': '/data/other.csv', 'sha256': 'not-a-digest'},
])
def test_training_table_does_not_hide_an_ambiguous_or_invalid_input(extra):
    supplied = [{'kind': 'file', 'path': '/data/table.npz', 'sha256': 'a' * 64}, extra]
    assert 'dataset_path' not in staged.parameters({}, {}, {}, supplied)


def test_unresolved_launch_parameter_cannot_be_admitted():
    plan = staged_plan()
    row = steps(plan)['t02-admit']
    row['parameters']['launch']['argv'][-1] = '{dataset_sha256}'
    assert 'mode_unresolved_placeholder' in codes(admit(row, plan))


@pytest.mark.parametrize('route', ['ml.training', 'judgment'])
@pytest.mark.parametrize('status', ['held', 'qualified', 'refused', 'completed'])
def test_next_stage_rechecks_predecessor_status_and_accepted_input_bytes(tmp_path, route, status):
    run = Run(tmp_path)
    run.plan['route']['id'] = route
    run.stage('t02-admit')
    assert run.check('t02-admit') == []
    if status != 'completed':
        receipt = json.loads((run.run_dir / 'steps/t02-admit' / staged.RECEIPT).read_text())
        receipt['status'] = status
        support.adopt(run.store, run.run_dir, 't02-admit', run.pipeline.root / 'admit', [])
        target = run.run_dir / 'steps/t02-admit' / staged.RECEIPT
        target.write_text(json.dumps(receipt))
        custody = staged.custody_index(run.store)['t02-admit:' + staged.RECEIPT]
        custody['sha256'] = support.sha(target)
        run.store.append('custody', custody)
        assert 'ml_stage_prerequisite_incomplete' in codes(staged.admit(run.steps['t03-features'], run.context()))
    else:
        assert staged.admit(run.steps['t03-features'], run.context()) == []
        custody = staged.custody_index(run.store)['t02-admit:outputs/partitions/train.npz']
        custody['status'] = 'rejected'
        run.store.append('custody', custody)
        assert 'ml_stage_input_custody_missing' in codes(staged.admit(run.steps['t03-features'], run.context()))


def test_amended_plan_cannot_reuse_old_stage_acceptance(tmp_path):
    run = Run(tmp_path)
    run.stage('t02-admit')
    assert run.check('t02-admit') == []
    run.plan['sha256'] = 'f' * 64
    assert 'ml_stage_prerequisite_incomplete' in codes(staged.admit(run.steps['t03-features'], run.context()))
    ending = staged.ending('plan changed', run.context())
    assert 't02-admit' in ending['unfinished']


def test_runtime_mode_admission_covers_child_plans(tmp_path):
    run = Run(tmp_path)
    row = run.steps['t03-features']
    assert 'ml_stage_prerequisite_incomplete' in codes(admit(row, run.plan, context=run.context()))
    run.stage('t02-admit')
    assert run.check('t02-admit') == []
    assert admit(row, run.plan, context=run.context()) == []


def test_parent_requests_and_verifies_the_exact_unblind_action(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from ravel.controller.authority import retained
    run = Run(tmp_path)
    for step_id in ('t02-admit', 't03-features', 't04-smoke', 't05-train'):
        run.stage(step_id)
        assert run.check(step_id) == []
    requested, verified = [], []
    granted = {}
    def current(store, kind, pins):
        return granted.get(json.dumps(pins, sort_keys=True)) if kind == 'r3_action' else None
    def request(store, kind, subject, bounds):
        requested.append((kind, subject, bounds))
        return {'pending': {'reason': 'operator answer required'}}
    def verify(store, record_id, *, kind, subject):
        verified.append((record_id, kind, subject))
        return {'id': record_id, 'kind': kind, 'subject': {'gate': 'unblind', 'pins': subject}}
    service = SimpleNamespace(current=current, request=request, verify=verify)
    monkeypatch.setattr(staged, 'authority_service', lambda: service)
    captured = []
    monkeypatch.setattr(retained, 'capture', lambda *args, **kwargs: captured.append(kwargs))
    context = run.context()
    evaluate = run.steps['t06-evaluate']
    assert 'ml_unblind_authority_missing' in codes(staged.admit(evaluate, context))
    kind, subject, bounds = requested[-1]
    assert kind == 'r3_action' and subject['gate'] == 'unblind'
    pins = subject['view']['pins']
    assert captured[-1]['view'] == subject['view'] and captured[-1]['plan'] == run.plan
    assert pins['plan_sha256'] == run.plan['sha256'] and pins['step'] == evaluate['id']
    assert pins['operation'] == evaluate['operation'] and pins['ml_training_sha256']
    assert all(not option['effect'] for option in subject['view']['options'] if option['id'] == subject['conservative_default'])
    granted[json.dumps(pins, sort_keys=True)] = {'id': 'exact-action'}
    assert staged.admit(evaluate, context) == []
    assert verified[-1] == ('exact-action', 'r3_action', pins)
    run.plan['sha256'] = 'e' * 64
    assert staged.admit(evaluate, run.context())


def test_manuscript_cannot_hide_an_unreceipted_result_outside_reads(tmp_path):
    from ravel.controller.routes.manuscript import staged as manuscript
    run = Run(tmp_path)
    plan = support.plan('manuscript', {'python': PARAMS['python'], 'tex': '',
        'result_path': '/data/result.json', 'result_sha256': 'a' * 64}, deliverables=((None, 'document'),))
    row = next(row for row in plan['steps'] if manuscript.stage_of(row) == 'sources')
    row['parameters']['launch']['reads'] = []
    context = {**run.context(), 'plan': plan}
    assert 'manuscript_result_custody_missing' in codes(manuscript.admit(row, context))


def test_unblind_request_is_accepted_by_the_real_authority_contract(tmp_path, monkeypatch, operator_home, capfd):
    import re
    from ravel.controller import authority
    from ravel.controller.authority import common
    from test_p06_support import autonomous, frozen_store
    autonomous()
    store = frozen_store(tmp_path / 'authority')
    plan = staged_plan()
    evaluate = steps(plan)['t06-evaluate']
    context = {'store': store, 'run_dir': tmp_path / 'run', 'plan': plan, 'reading': {}}
    # Custody of the frozen training is an explicit double; the authority service and its
    # retained snapshot, challenge, operator answer and current-pin verification are real.
    monkeypatch.setattr(staged, 'adopted', lambda *a, **k: (b'{}', tmp_path / 'training.json', {'sha256': 'b' * 64}))
    identity = {'test': {'sha256': 'c' * 64}}
    assert codes(staged.unblind_errors(evaluate, context, 'd' * 64, identity)) == ['ml_unblind_authority_missing']
    requests = common.scan(store, common.REQUESTS, common.REQUEST_SCHEMA)
    assert len(requests) == 1 and requests[0]['subject']['gate'] == 'unblind'
    nonce = re.search(r'--code (\S+)', capfd.readouterr().err).group(1)
    answer = authority.answer(store, requests[0]['id'], nonce, 'unblind')
    assert answer['authorizes_effects'] is True
    assert staged.unblind_errors(evaluate, context, 'd' * 64, identity) == []
    plan['sha256'] = 'e' * 64
    assert staged.unblind_errors(evaluate, context, 'd' * 64, identity)


def test_context_admission_retains_every_scope_pin():
    plan = staged_plan()
    row = steps(plan)['t05-train']
    seen = []
    def current(kind, pins):
        seen.append((kind, pins))
        return {'id': 'plan-approval'}
    context = {'plan': plan, 'authority': current, 'scope_pins': {'scope_sha256': 'c' * 64}}
    # An earlier static failure still exercises the scoped authority resolver without runtime effects.
    row['parameters']['launch']['argv'][-1] = '{missing_input}'
    assert 'mode_unresolved_placeholder' in codes(admit(row, plan, context=context))
    assert seen == [('approve_plan', {'scope_sha256': 'c' * 64, 'plan_sha256': plan['sha256']})]
    context['scope_pins']['plan_sha256'] = 'd' * 64
    assert 'mode_authority_unavailable' in codes(admit(row, plan, context=context))


def test_registered_prepared_stage_dispatches_through_the_governed_interface(tmp_path, monkeypatch):
    import sys
    from types import ModuleType
    from ravel.workflow import ml_executor
    run = Run(tmp_path)
    dispatched = []
    interface = ModuleType('ravel.controller.step')
    def execute(store, row, context):
        dispatched.append(row['id'])
        assert context['plan_sha256'] == run.plan['sha256']
        run.stage(row['id'])
        outcome = {'step_id': row['id'], 'status': 'completed'}
        store.append('step-outcome', outcome)
        return outcome
    interface.run = execute
    monkeypatch.setitem(sys.modules, interface.__name__, interface)
    context = {**run.context(), 'plan_sha256': run.plan['sha256']}
    outcome = ml_executor.run_step(run.store, run.steps['t02-admit'], context)
    assert outcome['status'] == 'completed' and dispatched == ['t02-admit']
    assert staged.records(run.store, staged.STAGE_RECORD)[-1]['accepted'] is True


@pytest.mark.parametrize('status', ['held', 'qualified', 'completed'])
def test_zero_exit_stage_ending_controls_the_governed_outcome(tmp_path, status):
    run = Run(tmp_path)
    run.stage('t02-admit')
    target = run.run_dir / 'steps/t02-admit' / staged.RECEIPT
    receipt = json.loads(target.read_text())
    receipt['status'] = status
    target.write_text(json.dumps(receipt))
    row = staged.custody_index(run.store)['t02-admit:' + staged.RECEIPT]
    row['sha256'] = support.sha(target)
    run.store.append('custody', row)
    outcome = ml.modes.observe(run.steps['t02-admit'], {'status': 'completed'}, run.context())
    assert outcome['status'] == ('completed' if status == 'completed' else 'failed')
    accepted = staged.records(run.store, staged.STAGE_RECORD)[-1]
    assert accepted['accepted'] is (status == 'completed')


def test_malformed_output_mapping_is_a_typed_stage_failure(tmp_path):
    run = Run(tmp_path)
    run.stage('t02-admit')
    target = run.run_dir / 'steps/t02-admit' / staged.RECEIPT
    receipt = json.loads(target.read_text())
    receipt['outputs'] = ['invalid']
    target.write_text(json.dumps(receipt))
    row = staged.custody_index(run.store)['t02-admit:' + staged.RECEIPT]
    row['sha256'] = support.sha(target)
    run.store.append('custody', row)
    assert run.check('t02-admit')[0].startswith('ml_stage_receipt_invalid:')


def test_manuscript_consumes_only_the_exact_accepted_result(tmp_path):
    from ravel.controller.routes.manuscript import staged as manuscript
    run = Run(tmp_path)
    author = tmp_path / 'author'
    (author / 'outputs').mkdir(parents=True)
    (author / 'outputs/claim_map.json').write_text('{}')
    (author / 'outputs/note.md').write_text('Fictional supplied text.')
    (author / 'outputs/trap_sweep.json').write_text(json.dumps({
        'traps_checked': ['T' + str(i) for i in range(1, 13)], 'traps_hit': [], 'verdicts': [], 'escalations': []}))
    support.adopt(run.store, run.run_dir, 'm01-author', author,
                  ['outputs/claim_map.json', 'outputs/note.md', 'outputs/trap_sweep.json'])
    imported = tmp_path / 'imported'
    (imported / 'outputs').mkdir(parents=True)
    (imported / 'outputs/result.json').write_text('{"metric": 0.75}')
    support.adopt(run.store, run.run_dir, 'import-result', imported, ['outputs/result.json'])
    _, target, custody = staged.adopted(run.store, run.run_dir, 'import-result', 'outputs/result.json')
    plan = support.plan('manuscript', {'python': PARAMS['python'], 'tex': '',
        'result_path': str(target), 'result_sha256': custody['sha256']}, deliverables=((None, 'document'),))
    row = next(row for row in plan['steps'] if manuscript.stage_of(row) == 'sources')
    context = {**run.context(), 'plan': plan}
    assert manuscript.admit(row, context) == []
    custody['status'] = 'rejected'
    run.store.append('custody', custody)
    assert 'manuscript_result_custody_missing' in codes(manuscript.admit(row, context))


def test_governed_preflight_checks_runtime_admission_before_dispatch(tmp_path):
    # The installed step preflight, not a patched copy: its route admission is the context-aware ML admission.
    import ast
    from types import SimpleNamespace
    from ravel.controller.step import graph as step_graph, operations as step_operations, spec
    from ravel.controller.step.services import StepHold
    target = Path(step_graph.__file__)
    tree = ast.parse(target.read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'preflight')
    run = Run(tmp_path / 'runtime')
    row = run.steps['t03-features']
    calls = []
    operations = SimpleNamespace(plan_step=lambda *a: (row, run.plan['sha256'], 'plan_step'),
        current_plan=lambda *a: run.plan, executor_errors=lambda *a: [], admission_errors=lambda *a, **k: [],
        signatures=staged.signatures, executors=step_operations.executors, route_errors=step_operations.route_errors,
        route_context=lambda store, context: {**context, 'store': store, 'plan': run.plan})
    custody = SimpleNamespace(parent_errors=lambda *a: [], OUTCOME='step-outcome',
        input_errors=lambda *a, **k: ([], [], []))
    def dispatch(*args):
        calls.append(row['id'])
        output_root = run.run_dir / 'steps' / row['id'] / 'attempts/1/outputs'
        return {'dispatched': True, 'output_root': str(output_root), 'launch_sha256': 'a' * 64,
                'stage': 'derive', 'capsule': {'argv': ['inert-feature-operation'], 'reads': [],
                    'writes': [str(output_root)], 'cwd': str(output_root),
                    'limits': {'wall_seconds': 1, 'cpus': 1}}}
    def fact(state, mechanism, **fields):
        record = run.store.append('step-fact', {'step_id': row['id'], 'attempt': 1,
                                               'mechanism': mechanism, **deepcopy(fields)})
        return {'record': record}
    scope = {'step': row['id'], 'point': None, 'seat': 'producer', 'attempt': 1}
    ledger_context = {**scope, 'run_id': run.store.run_id, 'role': None, 'seat_kind': 'launch',
                      'review_kind': None, 'step_kind': row['kind']}
    materialised, recorded = [], []
    entry = 'I01@' + run.store.run_id + '/step=' + row['id'] + '/seat=producer/attempt=1'
    def binding(actual):
        assert actual['step']['id'] == actual['acting']['id'] == row['id']
        return 'dispatch', deepcopy(ledger_context), {'step': row['id']}, deepcopy(scope)
    def materialise(store, stage, actual_context):
        assert store is run.store and stage == 'dispatch' and actual_context == ledger_context
        materialised.append((stage, deepcopy(actual_context)))
        return [entry]
    def record(store, key, status, evidence):
        assert store is run.store and key == entry and status == 'not_applicable'
        matches = [row for row in store.scan('step-fact') if row['id'] == evidence['record']]
        assert len(matches) == 1
        actual = matches[0]['record']
        assert actual['mechanism'] == 'native-instruction-packet-absence'
        assert actual['step_id'] == row['id'] and actual['attempt'] == 1
        recorded.append(key)
    ledger = SimpleNamespace(materialise=materialise, current=lambda store: [], record=record)
    namespace = {'__name__': step_graph.__name__, '__package__': step_graph.__package__,
        '_ctx': lambda s: {'plan_sha256': run.plan['sha256']}, '_store': lambda s: run.store,
        '_run_dir': lambda s: run.run_dir, '_attempt': lambda s: 1, '_running': lambda *a: None,
        '_card': lambda s: None, '_seat': lambda s: None, '_seat_roles': lambda *a: [],
        '_fact': fact, 'records': lambda *a: [], 'operations': operations,
        'deepcopy': deepcopy, 'Path': Path,
        'custody': custody, 'spec': spec, 'StepHold': StepHold, '_launch_preflight': dispatch,
        '_subject': step_graph._subject, 'module': lambda name: ledger if name == 'ledger' else None,
        '_ledger_binding': binding, 'native_rows': step_graph.native_rows,
        # The plan-bind rows have their own real-ledger controls; this case checks the staged admission.
        'plan_binding': SimpleNamespace(unverified=lambda *a: [])}
    absence = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_native_instruction_absence')
    exec(compile(ast.Module(body=[absence, function], type_ignores=[]), str(target), 'exec'), namespace)
    state = {'step': row, 'acting': row, 'branch': 'launch', 'packet': {'kind': 'launch'},
             'reservation': {'record_id': run.store.append('budget-reservation', {'step_id': row['id']}),
                             'amounts': {'wall_seconds': 1}}}
    with pytest.raises(StepHold) as held:
        namespace['preflight'](state)
    assert held.value.reason == 'ml_stage_prerequisite_incomplete' and calls == []
    run.stage('t02-admit')
    assert run.check('t02-admit') == []
    assert namespace['preflight'](state)['preflight']['dispatched'] is True
    assert calls == ['t03-features']
    assert materialised == [('dispatch', ledger_context)] and recorded == [entry]


def test_child_graph_positive_control_with_exact_authority_fixture(tmp_path, monkeypatch):
    # The graph test file carries the exact withheld-read authority fixture; its training graph is run here.
    import importlib.util
    target = Path(__file__).resolve().parent / 'test_p17_graphs.py'
    spec = importlib.util.spec_from_file_location('_governed_graph_control', target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.test_P17_training_graph_runs_every_planned_stage_through_step_interface(tmp_path, monkeypatch)

