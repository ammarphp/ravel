"""P13/P12 handoff: persist graph-observed ML checks, using bounded numerical artifacts.

The production graph remains owned by P12; apply its exact integration fragment to a
throwaway module. No training, graph launch, exposure, model call or external service.
"""
from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ravel.physics import ml_training  # noqa: E402
from ravel.workflow import broker, review_projection_checks as rpc  # noqa: E402
from test_ml_study_graph import context, fixture, start  # noqa: E402
from test_p13_review_independence import controller  # noqa: E402, F401

ROOT = Path(__file__).resolve().parents[3]
KEYS = ('check:ml-benchmark-localization', 'check:ml-statistics-sizing')


@pytest.fixture
def wired_graph(tmp_path, monkeypatch):
    """Load the actual P12 source after applying only the delivered integration patch."""
    destination = tmp_path / 'patched'
    source = destination / 'src/ravel/workflow/graphs/ml_study.py'
    source.parent.mkdir(parents=True)
    source.write_bytes((ROOT / 'src/ravel/workflow/graphs/ml_study.py').read_bytes())
    applied = subprocess.run(
        ['git', 'apply', str(ROOT / 'tests/fixtures/peer_contracts/training-stage.patch')],
        cwd=destination, text=True, capture_output=True, check=False)
    assert applied.returncode == 0, applied.stderr
    name = 'ravel.workflow.graphs._p13_ml_stage_wiring_test'
    module_spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(module_spec)
    monkeypatch.setitem(sys.modules, name, module)
    module_spec.loader.exec_module(module)
    return module


class NumericalValidator:
    """A trusted test plugin that computes from raw numbers, never a supplied verdict."""
    identity = {'implementation': 'bounded-numerical-observation-control', 'version': 1}

    def validate(self, key, raw, context):
        values = json.loads(raw)['observations']
        if not values or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            return 'unresolved'
        return 'pass' if min(values) >= 0 else 'fail'


class NumericalEvaluator:
    identity = {'implementation': 'bounded-pinned-observation-control', 'version': 1}

    def __init__(self, root, case):
        self.root, self.case = root, case

    def stage(self, stage, request, required):
        path = self.root / 'observations.json'
        path.write_text(json.dumps({'observations': [-1., 2.] if self.case == 'bad' else [1., 2.]}))
        pin = ml_training.pin(path)
        return {'artifacts': {} if self.case == 'missing' else {key: pin for key in required},
                # This untrusted statement cannot override either a defect or missing evidence.
                'checks': {key: {'verdict': 'pass'} for key in required}}


@pytest.mark.parametrize('case,verdict,status', [
    ('good', 'pass', 'passed'), ('bad', 'fail', 'failed'), ('missing', 'missing', 'inconclusive')])
def test_CF12_P12_stage_records_actual_numerical_outcomes_and_bindings(
        tmp_path, controller, wired_graph, case, verdict, status):
    store = controller(tmp_path)
    spec = fixture(tmp_path)
    ctx = context(tmp_path, NumericalEvaluator(tmp_path, case), NumericalValidator())
    actual = wired_graph._stage(ctx, start(ctx, spec), 'S2')
    metadata = actual['controller_checks']
    subject = {key: value for key, value in actual.items() if key != 'controller_checks'}
    assert set(metadata) == set(KEYS)
    assert bool(actual.get('blocking')) is (case != 'good')
    for key in KEYS:
        assert actual['checks'][key]['verdict'] == verdict
        binding = metadata[key]
        assert binding['subject_sha256'] == broker.digest(subject)
        assert binding['spec_sha256'] == broker.digest(spec)
        recorded = store.read(rpc.ML_OBSERVATION_KIND, binding['record_id'])
        assert recorded['check_id'] == key and recorded['stage'] == 'S2'
        assert recorded['check'] == actual['checks'][key]
        assert recorded['subject_sha256'] == binding['subject_sha256']
        assert recorded['spec_sha256'] == binding['spec_sha256']
        assert rpc.observed_ml_result(store, binding, check_id=key)['status'] == status
        forged = deepcopy(binding)
        forged['subject_sha256'] = 'f' * 64
        assert rpc.observed_ml_result(store, forged, check_id=key)['status'] == 'inconclusive'


def test_CF12_P12_legacy_stage_does_not_record_controller_observations(tmp_path, wired_graph, monkeypatch):
    from ravel.workflow import review_independence
    monkeypatch.setattr(review_independence, 'controller_store', lambda root: None)
    def unexpected(*args, **kwargs):
        raise AssertionError('legacy graph must not record a controller observation')
    monkeypatch.setattr(rpc, 'record_ml_stage', unexpected)
    spec = fixture(tmp_path)
    ctx = context(tmp_path, NumericalEvaluator(tmp_path, 'good'), NumericalValidator())
    actual = wired_graph._stage(ctx, start(ctx, spec), 'S2')
    assert 'controller_checks' not in actual
    assert all(actual['checks'][key]['verdict'] == 'pass' for key in KEYS)


def test_CF12_P12_graph_owned_estimand_is_recorded_from_validated_spec(tmp_path, controller, wired_graph):
    store = controller(tmp_path)
    spec = fixture(tmp_path)
    ctx = context(tmp_path, NumericalEvaluator(tmp_path, 'bad'), NumericalValidator())
    actual = wired_graph._stage(ctx, start(ctx, spec), 'S1')
    key = 'check:ml-estimand-declared'
    assert actual['checks'][key] == {'verdict': 'pass', 'source': 'graph'}
    binding = actual['controller_checks'][key]
    recorded = store.read(rpc.ML_OBSERVATION_KIND, binding['record_id'])
    assert recorded['check'] == actual['checks'][key]
    assert rpc.observed_ml_result(store, binding, check_id=key)['status'] == 'passed'


def numerical_observations(root, store, spec, case):
    """Exercise observer custody for all ids with a trusted numerical test plugin.

    These are plugin-interface controls, not implementations of the scientific checks.
    The stock graph does not route injection-closure; its direct observer seam is covered
    here without changing that graph's requirement matrix or claiming physics acceptance.
    """
    validator = NumericalValidator()
    path = root / 'plugin-observations.json'
    path.write_text(json.dumps({'observations': {'good': [1., 2.], 'bad': [-1., 2.],
                                               'unresolved': []}[case]}))
    pin = ml_training.pin(path)
    raw = path.read_bytes()
    checks = {key: {'verdict': validator.validate(key, raw, {'spec': spec}),
                    'source': 'validator', 'validator': deepcopy(validator.identity), 'artifact': pin}
              for key in rpc.ML_RESULT_CHECKS}
    return rpc.record_ml_stage(store, spec=spec, stage='synthetic-plugin-control',
                               result={'checks': checks, 'scope': 'bounded numerical plugin control only'})


@pytest.mark.parametrize('case,status', [('good', 'passed'), ('bad', 'failed'),
                                        ('unresolved', 'inconclusive')])
@pytest.mark.parametrize('key', rpc.ML_RESULT_CHECKS)
def test_CF12_all_fifteen_controller_observation_ids_retain_computed_plugin_outcome(
        tmp_path, controller, case, status, key):
    store = controller(tmp_path)
    bindings = numerical_observations(tmp_path, store, fixture(tmp_path), case)
    assert set(bindings) == set(rpc.ML_RESULT_CHECKS)
    observed = rpc.observed_ml_result(store, bindings[key], check_id=key)
    assert observed['status'] == status
    assert observed['diagnostics']['check']['source'] == 'validator'
    # The same public verdict cannot grant computation credit without store custody.
    public = {'checks': {key: observed['diagnostics']['check']}}
    if case == 'good':
        assert rpc.ml_result(public, check_id=key)['status'] == 'inconclusive'


@pytest.mark.parametrize('case,expected', [('good', 'ok'), ('bad', 'failed'),
                                          ('unresolved', 'failed')])
def test_CF12_ml_trainer_materialize_broker_finish_requires_all_observed_self_checks(
        tmp_path, monkeypatch, controller, case, expected):
    """A computed worker receipt from inert numeric plugins, without training or physics claims."""
    from ravel.workflow import agent_worker, production_executor, role_registry
    from test_agent_worker import put, result as worker_result, setup, spec as worker_spec

    worker, run = setup(tmp_path, monkeypatch)
    store = controller(run)
    source = tmp_path / 'plugin-inputs'
    source.mkdir()
    bindings = numerical_observations(source, store, fixture(source), case)
    card = role_registry.load('ml-trainer')
    required = sorted(set(card['must_check']) | set(role_registry.self_checks('ml-trainer')))
    assert len(required) == 13 and set(required) <= set(rpc.ML_RESULT_CHECKS)
    order = {'kind': 'work-order', 'node_id': 'worker', 'role': 'ml-trainer',
             'self_check': required, 'check_inputs': {key: bindings[key] for key in required}}
    order_path = run / 'order.json'
    order_path.write_text(json.dumps(order, sort_keys=True))
    monkeypatch.setattr(production_executor, 'load_order', lambda rundir, node: deepcopy(order))
    value = worker_spec()
    value['role'] = {'id': 'ml-trainer', 'version': str(card['version']),
                     'card_sha256': role_registry.card_sha256('ml-trainer')}
    value['work_order'] = {'path': 'order.json', 'sha256': broker.sha(order_path)}
    value['parent']['map_id'] = worker.PRODUCTION_MAP + value['node_id']
    workspace = agent_worker.materialize(run, value)
    target = broker.Broker(run, workspace, node_id='worker', attempt=1,
                           allowed_actions=['check run'], max_calls=100)
    rpc.register(target, card)
    replies = [target.call({'call_id': f'observed-{index}', 'action': 'check run',
                            'args': {'check_id': key, 'paths': []}})
               for index, key in enumerate(required)]
    assert all(reply['status'] == ('ok' if case == 'good' else 'failed') for reply in replies), replies
    put(run, workspace, 'outputs/result.txt', 'Bounded numerical plugin controls completed.')
    receipt = worker.finish(run, value, final=worker_result(), execution={'exit_status': 0})
    assert receipt['status'] == expected
    assert receipt['outcome']['computed_checks']['self_checks'] is (case == 'good')
    assert receipt['outcome']['computed_checks']['declared_outputs'] is True
    assert receipt['outcome']['label_source'] == 'computed'
