"""Synthetic method-study graph controls; no training or external tools."""
import copy
import json
import time

import numpy as np
import pytest

from ravel.physics import ml_exposure, ml_training
from ravel.workflow import effect_ledger, graph_nodes as n, graph_registry, graph_substrate as gs, machine_lease

ACTIVE = ('review_points', 'rdj', 'ceilings', 'research_protocol', 'raw_launch', 'executor')


class Validator:
    """Synthetic validator: recomputes each check from the evaluator's pinned artifact."""
    identity = {'implementation': 'synthetic-check-validator', 'version': 1}

    def validate(self, key, raw, context):
        return 'pass' if json.loads(raw)['computed'].get(key) is True else 'fail'


class Evaluator:
    identity = {'implementation': 'synthetic-staged-evaluator', 'version': 1}

    def __init__(self, root):
        self.root = root
        self.events = []
        self.active = 0
        self.peak = 0
        self.fail_arm = None
        self.bad_stage = None
        self.cpu = 1.0
        self.withheld_reads = 0

    def stage(self, stage, request, required):
        self.events.append(stage)
        path = self.root / 'evaluator' / f'{stage}.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({'computed': {key: stage != self.bad_stage for key in required}}))
        pin = ml_training.pin(path)
        return {'artifacts': {key: pin for key in required},
                **({'withheld_reads': self.withheld_reads} if stage == 'S15' else {}),
                **({'rdj': {'class': 'R3', 'claim_kind': 'method_performance', 'authority': 'machine'}}
                   if stage == 'S16' else {})}

    def binding(self, scope, item):
        return None  # marked pytest namespace only

    def train(self, request):
        assert 'confirm' not in request and 'population' not in request
        assert request['budget'] == request['spec']['budget']
        held = machine_lease.holder()
        assert held['node_id'] == request['key']
        assert held['wait_seconds'] == machine_lease.default_wait_seconds()
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            time.sleep(.005)
            if request['arm']['id'] == self.fail_arm:
                return {'status': 'failed', 'error': 'synthetic failed arm'}
            self.events.append('train:' + request['key'])
            return {'checkpoint': request['key'], 'validation_metric': 0.5, 'cpu_seconds': self.cpu}
        finally:
            self.active -= 1

    def select(self, request):
        self.events.append('select')
        arms = sorted(a for a in request['candidates'] if a != 'ceiling')
        path = self.root / 'evaluator' / 'query-ledger.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps([{'arm': arm, 'stage': 'select', 'population': 'select'} for arm in arms]))
        return {'selected': arms, 'queries': len(arms), 'query_ledger': ml_training.pin(path)}

    def confirm(self, request):
        self.events.append('confirm')
        assert confirm_reads() == 1
        assert request['selection_receipt']['sha256'] == ml_training.pin(request['selection_receipt']['path'])['sha256']
        return {'test_reads': 1, 'reported': request['selected'], 'verdict': 'inconclusive',
                'scores': {key: .5 for key in request['batch']}}

    def attribute(self, request):
        self.events.append('attribute:' + request['key'])
        assert 'confirm' not in request
        assert machine_lease.holder()['node_id'] == request['key']
        return {'verdict': 'inconclusive', 'source': 'joint-confirmation'}


def records():
    return [json.loads(p.read_text()) for p in ml_exposure.root().glob('*.json')]


def record(role):
    return next((r for r in records() if r['roles'] == [role]), None)


def confirm_reads():
    found = record('test_split')
    return 0 if found is None else len(found['reads'])


def _npz(path, events):
    np.savez(path, x=np.arange(2. * len(events)).reshape(len(events), 2), weight=np.ones(len(events)),
             event_id=np.array(events), group_id=np.array(['g' + e for e in events]))
    return ml_training.pin(path)


def manifest(tmp_path, prefix='', evidence='synthetic', confirm_ids=None):
    partitions = {}
    for name, count in (('train', 6), ('validation', 4), ('confirm', 4)):
        events = [f'{prefix}{name[0]}{i}' for i in range(count)]
        pin = _npz(tmp_path / f'{prefix}{name}.npz', events)
        listed = confirm_ids if name == 'confirm' and confirm_ids else events
        partitions[name] = {'pin': pin, 'event_ids': listed, 'group_ids': ['g' + e for e in listed]}
    path = tmp_path / f'{prefix}split-manifest.json'
    path.write_text(json.dumps({'kind': 'ml-split-manifest', 'method': 'explicit',
                                'provenance': {'class': evidence}, 'partitions': partitions}))
    return ml_training.pin(path), partitions['confirm']['pin']


def fixture(tmp_path, prefix='', evidence='synthetic'):
    split, confirm = manifest(tmp_path, prefix, evidence)
    return {'study_id': 'synthetic-family', 'synthetic': evidence == 'synthetic', 'claim_kind': 'method_performance',
            'task_class': 'method_study', 'metrics': {'primary': 'score'},
            'claims': [{'kind': 'performance', 'estimand': {'metric': 'score', 'population': 'synthetic',
                                                         'reference': 'reference', 'working_point': .5}}],
            'arms': [{'id': 'simple', 'role': 'baseline', 'components': []},
                     {'id': 'candidate', 'role': 'candidate', 'components': ['block']}],
            'seeds': [1, 2, 3, 4, 5], 'rung': 'claim',
            'budget': {'max_select_queries': 64, 'equal_across_arms': True, 'cpu_seconds_per_replicate': 10},
            'split_manifest': split, 'split_sha256': split['sha256'], 'confirm': confirm,
            'placement': {'local': True}, 'attribution': {'scope': 'joint_confirm', 'mode': 'fixed-configuration'}}


def role_factory(role, name):
    return n.effect(name, kind='model', run=lambda s, i: {'role': role, 'synthetic': True},
                    identity=lambda s: {'role': role, 'spec': {k: v for k, v in s['spec'].items() if k != 'confirm'}},
                    segment=lambda s: {'role': role, 'stage': name},
                    to_state=lambda s, r: {'results': {name: r}})


def context(tmp_path, evaluator=None, validator=None):
    row = graph_registry.get('ml.study')
    return gs.BuildContext(tmp_path, 'ml.study', 2, {'study': 'synthetic-family'}, row=row,
                           extras={'ml_executor': evaluator or Evaluator(tmp_path), 'ml_role_factory': role_factory,
                                   'ml_validators': validator or Validator()})


def start(ctx, spec):
    return {'spec': spec, 'meta': {'graph_id': 'ml.study', 'version': 2, 'instance': ctx.instance,
                                   'scope_root': str(ctx.scope_root), 'path': None}}


def invoke(tmp_path, spec, evaluator=None, *, gate=lambda *a: [], providers=lambda gate: {p: True for p in ACTIVE}):
    ctx = context(tmp_path, evaluator)
    app = gs.build('ml.study', ctx)
    with n.gate_checker(gate, providers=providers):
        result = app.invoke(start(ctx, spec), {'recursion_limit': 120, 'max_concurrency': 8})
    n.forget_handled()
    return result, ctx, app


def held(result, text):
    assert result['status']['terminal'] == 'hold', result['status']
    assert text in result['status']['reason'], result['status']


def test_second_confirm_read_is_hold(tmp_path):
    from ravel.workflow.graphs import ml_study as ms
    spec = fixture(tmp_path)
    result, ctx, _ = invoke(tmp_path, spec)
    with n.gate_checker(lambda *a: [], providers=lambda gate: {'review_points': True, 'rdj': True}):
        with pytest.raises(n.RecoveryHold, match='confirm.*spent'):
            ms.confirm_batch(ctx, result)
    assert confirm_reads() == 1


def test_arms_times_seeds_send_and_local_lease_serializes(tmp_path):
    from ravel.workflow.graphs import ml_study as ms
    evaluator = Evaluator(tmp_path)
    result, ctx, app = invoke(tmp_path, fixture(tmp_path), evaluator)
    edge = app.builder.branches['training_start']['route_map_train']
    packets = edge.path.invoke(result)
    from langgraph.types import Send
    assert all(isinstance(p, Send) for p in packets)
    assert len(packets) == len(ms.training_items(result['spec']))
    assert evaluator.peak == 1
    assert len([e for e in evaluator.events if e.startswith('train:')]) == len(packets)
    assert all('__split_' in p.arg['map_item'] for p in packets)


def test_selection_receipt_precedes_confirm_read(tmp_path):
    evaluator = Evaluator(tmp_path)
    result, _, _ = invoke(tmp_path, fixture(tmp_path), evaluator)
    assert evaluator.events.index('select') < evaluator.events.index('confirm')
    frozen = json.loads(open(record('test_split')['reads'][0]['selection']['path']).read())
    assert frozen['selection_receipt'] == result['results']['selection']['pin']
    assert frozen['ablation_arms'] and frozen['selected']


def test_method_study_fixture_runs_on_stubs(tmp_path):
    result, _, app = invoke(tmp_path, fixture(tmp_path))
    assert not result.get('status', {}).get('terminal'), result.get('status')
    assert all(f'S{i}' in app.builder.nodes for i in range(1, 17))
    assert result['results']['confirmation']['test_reads'] == 1
    assert result['results']['S16']['checks']['check:ml-acceptance-evidence']['verdict'] == 'pass'
    assert result['results']['report']['failures'] == []
    assert result['results']['report']['physics_validated'] is False


def test_missing_staged_executor_holds_without_exposure(tmp_path):
    ctx = context(tmp_path)
    ctx.extras.pop('ml_executor')
    app = gs.build('ml.study', ctx)
    result = app.invoke(start(ctx, fixture(tmp_path)))
    held(result, 'awaits the staged ML executor')
    assert not records()
    n.forget_handled()


def test_default_production_path_holds_before_worker_dispatch(tmp_path):
    ctx = gs.BuildContext(tmp_path, 'ml.study', 2, {'study': 'synthetic-family'},
                          row=graph_registry.get('ml.study'), extras={})
    app = gs.build('ml.study', ctx)
    result = app.invoke(start(ctx, fixture(tmp_path)))
    n.forget_handled()
    held(result, 'awaits the staged ML executor')
    assert 'planner' not in (result.get('results') or {})
    assert not (tmp_path / 'agent-work').exists()
    assert not records()


def test_real_provider_table_admits_the_launch(tmp_path):
    # providers=None: the registry rows decide, exactly as in production. The executor row
    # resolves to production_executor.gate_errors, so the launch is no longer refused for a
    # missing provider and training starts.
    from ravel.workflow import decision_gate
    row = next(r for r in decision_gate.providers('launch') if r['id'] == 'executor')
    assert row['active'] and (row['module'], row['function']) == ('ravel.workflow.production_executor', 'gate_errors'), row
    evaluator = Evaluator(tmp_path)
    result, _, _ = invoke(tmp_path, fixture(tmp_path), evaluator, providers=None)
    assert result['status'].get('terminal') != 'hold' or 'executor' not in result['status'].get('reason', ''), result['status']
    assert any(e.startswith('train:') for e in evaluator.events)


def test_validation_failure_reports_without_unblind(tmp_path):
    evaluator = Evaluator(tmp_path)
    evaluator.bad_stage = 'S11'
    result, _, _ = invoke(tmp_path, fixture(tmp_path), evaluator)
    assert 'report' in result['results']
    assert 'confirmation' not in result['results']
    assert 'unblind' not in result.get('gates', {})
    assert result['status']['terminal'] == 'hold'
    assert confirm_reads() == 0


def test_failed_baseline_arm_blocks_selection_and_is_reported(tmp_path):
    evaluator = Evaluator(tmp_path)
    evaluator.fail_arm = 'simple'
    spec = fixture(tmp_path)
    spec['claims'].append({'kind': 'comparison', 'margin': .01, 'estimand': spec['claims'][0]['estimand']})
    result, _, _ = invoke(tmp_path, spec, evaluator)
    assert result['status']['terminal'] == 'hold'
    assert 'selection' not in result['results'] and 'select' not in evaluator.events
    report = result['results']['report']
    assert len(report['failures']) == 5 and all(row['outcome'] == 'failed' for row in report['failures'])
    assert report['replicate_blocking'] == ['simple: 0 of 5 replicates']
    assert report['replicates']['candidate']['ok'] == 5
    assert confirm_reads() == 0


def test_partial_replicates_block_selection(tmp_path):
    evaluator = Evaluator(tmp_path)
    original = evaluator.train
    def flaky(request):
        if request['seed'] == 3 and request['arm']['id'] == 'candidate':
            return {'status': 'failed', 'error': 'synthetic replicate failure'}
        return original(request)
    evaluator.train = flaky
    result, _, _ = invoke(tmp_path, fixture(tmp_path), evaluator)
    assert result['results']['report']['replicate_blocking'] == ['candidate: 4 of 5 replicates']
    assert 'selection' not in result['results']


def test_cpu_above_declared_cap_blocks_selection(tmp_path):
    evaluator = Evaluator(tmp_path)
    evaluator.cpu = 11.0
    result, _, _ = invoke(tmp_path, fixture(tmp_path), evaluator)
    assert 'selection' not in result['results']
    assert result['results']['replicates']['per_arm']['simple']['failures'][0]['outcome'] == 'budget'


@pytest.mark.parametrize('choice, text', [
    (lambda keys, ledger: {'selected': [keys['candidate'][0]], 'queries': 1, 'query_ledger': ledger(['candidate'])},
     'whole candidate arms'),
    (lambda keys, ledger: {'selected': ['candidate'], 'queries': 1, 'query_ledger': ledger(['candidate'])},
     'every baseline arm'),
    (lambda keys, ledger: {'selected': ['candidate', 'simple'], 'queries': 5, 'query_ledger': ledger(['candidate'])},
     'equal its ledger'),
    (lambda keys, ledger: {'selected': ['candidate', 'simple'], 'queries': 2},
     'pinned query ledger'),
])
def test_selection_is_arm_level_with_baseline_and_ledger(tmp_path, choice, text):
    evaluator = Evaluator(tmp_path)
    def ledger(arms):
        path = tmp_path / 'ledger.json'
        path.write_text(json.dumps([{'arm': a, 'stage': 'select'} for a in arms]))
        return ml_training.pin(path)
    evaluator.select = lambda request: choice({a: sorted(v) for a, v in request['candidates'].items()}, ledger)
    result, _, _ = invoke(tmp_path, fixture(tmp_path), evaluator)
    held(result, text)
    assert confirm_reads() == 0


def test_literal_pass_without_artifact_blocks(tmp_path):
    evaluator = Evaluator(tmp_path)
    original = evaluator.stage
    def literal(stage, request, required):
        row = original(stage, request, required)
        if stage == 'S5':
            return {'checks': {key: {'verdict': 'pass'} for key in required}}
        return row
    evaluator.stage = literal
    result, _, _ = invoke(tmp_path, fixture(tmp_path), evaluator)
    assert result['results']['S5']['blocking'] == ['check:ml-baseline-set', 'check:ml-published-isolation']
    assert result['results']['S5']['checks']['check:ml-oracle-labelled']['verdict'] == 'not_applicable'
    assert 'confirmation' not in result['results'] and confirm_reads() == 0


def test_not_applicable_comes_only_from_the_matrix(tmp_path):
    from ravel.workflow.graphs import ml_study as ms
    evaluator = Evaluator(tmp_path)
    original = evaluator.stage
    def waive(stage, request, required):
        row = original(stage, request, required)
        if stage == 'S10':
            row['artifacts'].pop('check:ml-calibration-scope')
            row['checks'] = {'check:ml-calibration-scope': {'verdict': 'not_applicable', 'reason': 'n/a'}}
        return row
    evaluator.stage = waive
    result, _, _ = invoke(tmp_path, fixture(tmp_path), evaluator)
    s10 = result['results']['S10']
    assert s10['blocking'] == ['check:ml-calibration-scope']
    assert s10['matrix_version'] == ms.MATRIX_VERSION
    assert s10['checks']['check:ml-null-execution'] == {
        'verdict': 'not_applicable', 'source': ms.MATRIX_VERSION,
        'reason': 'task class method_study has no search, null or sculpting estimand'}
    assert 'confirmation' not in result['results']


def test_missing_validator_blocks(tmp_path):
    ctx = context(tmp_path)
    ctx.extras.pop('ml_validators')
    app = gs.build('ml.study', ctx)
    with n.gate_checker(lambda *a: [], providers=lambda gate: {p: True for p in ACTIVE}):
        result = app.invoke(start(ctx, fixture(tmp_path)), {'recursion_limit': 120})
    n.forget_handled()
    assert result['results']['S2']['checks']['check:ml-sample-provenance']['verdict'] == 'missing'
    assert 'S3' not in result['results'] and records() == []


def test_single_exposure_includes_generated_ablations(tmp_path):
    from ravel.workflow.graphs import ml_study as ms
    evaluator = Evaluator(tmp_path)
    spec = fixture(tmp_path)
    spec['arms'][1]['components'] = ['block', 'penalty']
    spec['arms'][1]['component_groups'] = [['block', 'penalty']]
    spec['arms'][1]['add_one'] = True
    result, _, _ = invoke(tmp_path, spec, evaluator)
    generated = ms.generated_ablations(spec)
    assert {a['contrast'] for a in generated} == {'remove-one', 'controls-only', 'remove-set', 'add-one'}
    freeze = json.loads(open(result['results']['confirmation']['freeze']['path']).read())
    assert freeze['ablation_arms'] == generated
    assert len(freeze['checkpoints']) == (len(spec['arms']) + len(generated)) * len(spec['seeds'])
    assert evaluator.events.index('confirm') > max(i for i, e in enumerate(evaluator.events) if e.startswith('train:'))
    assert confirm_reads() == 1


def test_confirm_batch_is_the_selection_and_ablations_with_a_closed_schema(tmp_path):
    spec = fixture(tmp_path)
    spec['arms'].append({'id': 'ceiling', 'role': 'ceiling', 'components': []})
    result, _, _ = invoke(tmp_path, spec)
    scores = result['results']['confirmation']['scores']
    assert not any(key.startswith('ceiling__') for key in scores)
    assert {key.split('__')[0] for key in scores} == {'simple', 'candidate', 'candidate_ab0', 'candidate_ab1'}
    # Ledger files are named by population digest, so the listing order is not the study order.
    first = record('test_split')
    assert first['state'] == 'complete'
    other = tmp_path / 'other'; other.mkdir()
    evaluator = Evaluator(other)
    original = evaluator.confirm
    evaluator.confirm = lambda request: {**original(request), 'unselected_scores': {'ceiling': .9}}
    result, _, _ = invoke(other, fixture(other, prefix='o'), evaluator)
    held(result, 'exactly the frozen batch')
    withheld = {r['sha256']: r for r in records() if r['roles'] == ['test_split']}
    assert withheld.pop(first['sha256']) == first
    [refused] = withheld.values()
    assert refused['state'] == 'failed' and len(refused['reads']) == 1


def test_unblind_gate_sees_freeze_and_scope_and_refusal_does_not_spend(tmp_path):
    evaluator = Evaluator(tmp_path)
    seen = []
    def gate(scope, name, action):
        seen.append(name)
        if name == 'unblind':
            assert (tmp_path / 'research/ml/spec-freeze.json').is_file()
            assert action['observed'] is False and action['selected'] == ['candidate', 'simple']
            assert action['validation'] and action['spec_sha256'] and action['unblinded_scope']
            return [{'code': 'synthetic_refusal', 'provider': 'rdj'}]
        return []
    result, _, _ = invoke(tmp_path, fixture(tmp_path), evaluator, gate=gate)
    assert result['status']['terminal'] == 'hold'
    assert confirm_reads() == 0
    assert 'confirm' not in evaluator.events
    assert 'unblind' in seen


def test_confirm_crash_spends_attempt_and_new_run_holds(tmp_path):
    evaluator = Evaluator(tmp_path)
    def crash(request):
        raise RuntimeError('synthetic evaluator crash after exposure')
    evaluator.confirm = crash
    spec = fixture(tmp_path)
    invoke(tmp_path, spec, evaluator)
    assert record('test_split')['state'] == 'failed' and confirm_reads() == 1
    sibling = tmp_path / 'sibling'
    sibling.mkdir()
    sibling_evaluator = Evaluator(sibling)
    result, _, _ = invoke(sibling, spec, sibling_evaluator)
    held(result, 'confirm population spent')
    assert not any(e.startswith('train:') for e in sibling_evaluator.events)


@pytest.mark.parametrize('change, reason', [
    (lambda s: s['seeds'].pop(), 'paired replicates'),
    (lambda s: s['budget'].__setitem__('equal_across_arms', False), 'equal budgets'),
    (lambda s: s['claims'][0].__setitem__('kind', 'coverage'), 'coverage claim'),
    (lambda s: s['claims'][0]['estimand'].pop('reference'), 'working-point reference'),
    (lambda s: s['arms'][1].__setitem__('budget', {'epochs_cap': 1000}), 'arm-level budgets are refused'),
    (lambda s: s['placement'].__setitem__('local', False), 'where remote work runs'),
    (lambda s: s.pop('metrics'), 'exactly one primary metric'),
    (lambda s: s.__setitem__('task_class', 'unlisted'), 'requirement-matrix row'),
    (lambda s: s['budget'].pop('cpu_seconds_per_replicate'), 'per-replicate CPU cap'),
    (lambda s: s.__setitem__('split_sha256', 'b' * 64), 'pin the split manifest'),
    (lambda s: s.__setitem__('synthetic', False), 'differs from the split manifest provenance'),
    (lambda s: s['attribution'].__setitem__('scope', 'reserved_sample'), 'reserved attribution samples'),
    (lambda s: s['claims'].append({'kind': 'mechanism', 'margin': .1, 'estimand': s['claims'][0]['estimand']})
     or s.pop('attribution'), 'mechanism claim requires attribution'),
])
def test_bad_contract_holds_before_training(tmp_path, change, reason):
    evaluator = Evaluator(tmp_path)
    spec = fixture(tmp_path)
    change(spec)
    result, _, _ = invoke(tmp_path, spec, evaluator)
    held(result, reason)
    assert not any(e.startswith('train:') for e in evaluator.events)
    assert not records()


def test_remote_placement_names_the_open_owner_question(tmp_path):
    spec = fixture(tmp_path)
    spec['placement']['local'] = False
    result, _, _ = invoke(tmp_path, spec)
    held(result, 'where remote work runs')


def test_confirm_partition_must_match_the_manifest(tmp_path):
    spec = fixture(tmp_path)
    spec['confirm'] = _npz(tmp_path / 'elsewhere.npz', ['z0', 'z1'])
    result, _, _ = invoke(tmp_path, spec)
    held(result, 'pinned split manifest')
    assert not records()


def test_population_identities_come_from_the_manifest_and_are_claimed_before_training(tmp_path, monkeypatch):
    monkeypatch.setattr(ml_exposure, 'identity', lambda *a: pytest.fail('a partition file was decoded for its identity'))
    evaluator = Evaluator(tmp_path)
    original_train = evaluator.train
    def train(request):
        claimed = record('test_split')
        assert claimed and claimed['state'] == 'claimed' and claimed['reads'] == []
        assert [r['context'] for r in record('train_split')['reads']] == ['train']
        return original_train(request)
    evaluator.train = train
    original_verify = ml_exposure.verify_identifiers
    def verify(*args):
        assert confirm_reads() == 1, 'confirm identifiers decoded before the charged read'
        return original_verify(*args)
    monkeypatch.setattr(ml_exposure, 'verify_identifiers', verify)
    result, _, _ = invoke(tmp_path, fixture(tmp_path), evaluator)
    assert result['results']['confirmation']['test_reads'] == 1


def test_confirm_file_differing_from_the_manifest_fails_after_the_charge(tmp_path):
    spec = fixture(tmp_path)
    split, confirm = manifest(tmp_path, 'm', confirm_ids=['x0', 'x1', 'x2', 'x3'])
    spec.update(split_manifest=split, split_sha256=split['sha256'], confirm=confirm)
    evaluator = Evaluator(tmp_path)
    result, _, _ = invoke(tmp_path, spec, evaluator)
    assert 'confirm' not in evaluator.events
    assert record('test_split')['state'] == 'failed' and confirm_reads() == 1


def test_ledger_entries_on_every_graph_path(tmp_path):
    from ravel.workflow.graphs import ml_study as ms
    evaluator = Evaluator(tmp_path)
    evaluator.withheld_reads = 2
    result, ctx, _ = invoke(tmp_path, fixture(tmp_path), evaluator)
    counts = {r['roles'][0]: (len(r['reads']), len(r.get('replays', []))) for r in records()}
    assert counts == {'train_split': (1, 0), 'validation_split': (1, 0), 'test_split': (1, 2)}
    with n.gate_checker(lambda *a: [], providers=lambda gate: {'review_points': True, 'rdj': True}):
        with pytest.raises(n.RecoveryHold):
            ms.confirm_batch(ctx, result)
    again, _, _ = invoke(tmp_path, fixture(tmp_path), evaluator)
    assert {r['roles'][0]: (len(r['reads']), len(r.get('replays', []))) for r in records()} == counts


def test_family_record_carries_earlier_specifications(tmp_path):
    first = tmp_path / 'first'; first.mkdir()
    spec = fixture(first)
    invoke(first, spec)
    second = tmp_path / 'second'; second.mkdir()
    rerun = fixture(second, prefix='r')
    rerun['seeds'] = [6, 7, 8, 9, 10]
    result, _, _ = invoke(second, rerun)
    assert result['results']['training_start']['family_prior_specs'] == [effect_ledger.digest(spec)]


def test_stale_unread_claim_is_resumed_by_the_same_study(tmp_path):
    from ravel.workflow.graphs import ml_study as ms
    spec = fixture(tmp_path)
    ctx = context(tmp_path)
    ms._claim(ctx, {'spec': spec}, resume=False)  # a process killed after its claim
    result, _, _ = invoke(tmp_path, spec)
    assert result['results']['confirmation']['test_reads'] == 1
    assert confirm_reads() == 1


def test_role_doubles_refused_outside_the_test_domain(tmp_path, monkeypatch):
    # Outside the test lock domain a graph scope needs its steering journal, as the substrate
    # records it when it creates a scope; the refusal under test is the role double's.
    from ravel.workflow import gate_wiring
    gate_wiring.initialize_steering(tmp_path, route='graph-scope')
    monkeypatch.setattr(machine_lease, 'domain', lambda: 'production')
    evaluator = Evaluator(tmp_path)
    result, _, _ = invoke(tmp_path, fixture(tmp_path), evaluator)
    held(result, 'role doubles are test-only')
    assert evaluator.events == []


def test_performance_only_study_needs_no_attribution(tmp_path):
    spec = fixture(tmp_path)
    spec.pop('attribution')
    result, _, _ = invoke(tmp_path, spec)
    assert not result.get('status', {}).get('terminal'), result.get('status')
    s13 = result['results']['S13']['checks']
    assert s13['check:ml-attribution']['verdict'] == 'not_applicable'


def test_completed_graph_reuses_receipts_without_second_read(tmp_path):
    evaluator = Evaluator(tmp_path)
    spec = fixture(tmp_path)
    first, _, _ = invoke(tmp_path, spec, evaluator)
    events = list(evaluator.events)
    again, _, _ = invoke(tmp_path, spec, evaluator)
    assert again['results'] == first['results']
    assert evaluator.events == events
    assert confirm_reads() == 1


def test_real_rdj_graph_seam():
    assert callable(graph_registry.builder(graph_registry.get('rdj.case')))


def test_observed_data_needs_a_human_r3_receipt(tmp_path):
    spec = fixture(tmp_path, evidence='observed')
    result, _, _ = invoke(tmp_path, spec)
    assert result['status']['terminal'] == 'hold'
    assert result['results']['S16']['blocking'] == ['check:ml-acceptance-evidence']


def test_stage_missing_artifact_never_opens_confirmation(tmp_path):
    evaluator = Evaluator(tmp_path)
    original = evaluator.stage
    def incomplete(stage, request, required):
        row = original(stage, request, required)
        if stage == 'S10':
            row['artifacts'].pop(required[0])
        return row
    evaluator.stage = incomplete
    result, _, _ = invoke(tmp_path, fixture(tmp_path), evaluator)
    assert result['status']['terminal'] == 'hold'
    assert 'confirmation' not in result['results']
    assert 'unblind' not in result.get('gates', {})


def test_planner_ablation_addition_does_not_drop_generated_arms(tmp_path):
    from ravel.workflow.graphs import ml_study as ms
    spec = fixture(tmp_path)
    spec['arms'].append({'id': 'additional_control', 'role': 'ablation', 'parent': 'candidate'})
    result, _, _ = invoke(tmp_path, spec)
    assert result['results']['selection']['ablation_arms'] == ms.ablation_arms(spec)
    assert 'attribution_additional_control' in result['results']


def test_confirm_is_claimed_before_training_so_a_peek_or_rival_claim_collides(tmp_path):
    from ravel.workflow.graphs import ml_study as ms
    spec = fixture(tmp_path)
    confirm = ms.split_manifest(tmp_path, spec)['identities']['confirm']
    evaluator = Evaluator(tmp_path)
    refusals = []
    original = evaluator.train
    def train(request):
        try:
            ml_exposure.Study('f' * 64).claim(confirm, 'train_split', schedule={confirm['sha256']: ['train']})
        except ValueError as exc:
            refusals.append(str(exc))
        return original(request)
    evaluator.train = train
    result, _, _ = invoke(tmp_path, spec, evaluator)
    assert refusals and all('already claimed by another active study' in r for r in refusals)
    assert result['results']['confirmation']['test_reads'] == 1


def test_resume_after_unblind_refusal_confirms_once(tmp_path):
    evaluator = Evaluator(tmp_path)
    spec = fixture(tmp_path)
    refuse = lambda scope, name, action: [{'code': 'synthetic_refusal', 'provider': 'rdj'}] if name == 'unblind' else []
    first, _, _ = invoke(tmp_path, spec, evaluator, gate=refuse)
    assert first['status']['terminal'] == 'hold' and confirm_reads() == 0
    second, _, _ = invoke(tmp_path, spec, evaluator)
    assert second['results']['confirmation']['test_reads'] == 1
    assert evaluator.events.count('confirm') == 1 and confirm_reads() == 1
