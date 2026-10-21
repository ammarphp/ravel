"""CF12: the exact P04 validation fragment reads protected computation observations."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import subprocess
import sys
import types

import pytest

from ravel.workflow import broker, review_projection_checks as rpc, role_registry
from test_p13_review_independence import controller  # noqa: F401
from test_p13_ml_stage_wiring import numerical_observations

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def validators(tmp_path, monkeypatch):
    patch = ROOT / 'tests/fixtures/peer_contracts/stage-validation.patch'
    lines = patch.read_text().splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith('@@')) + 1
    # The fragment includes the entire peer file as context, so the test applies
    # exactly the delivered change without requiring that peer's worktree.
    before = ''.join(line[1:] for line in lines[start:] if line.startswith((' ', '-')))
    copied = tmp_path / 'copy'
    path = copied / 'src/ravel/controller/step/validate.py'
    path.parent.mkdir(parents=True)
    path.write_text(before)
    applied = subprocess.run(['git', 'apply', str(patch)], cwd=copied, capture_output=True, text=True)
    assert applied.returncode == 0, applied.stderr
    package = types.ModuleType('_p13_peer')
    package.__path__ = []
    services = types.ModuleType('_p13_peer.services')
    services.StepHold = RuntimeError
    services.digest = broker.digest
    monkeypatch.setitem(sys.modules, package.__name__, package)
    monkeypatch.setitem(sys.modules, services.__name__, services)
    spec = importlib.util.spec_from_file_location('_p13_peer.validate', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('case,status', [('good', 'passed'), ('bad', 'failed'),
                                        ('unresolved', 'inconclusive')])
def test_CF12_governed_validate_uses_every_bound_trainer_computation(
        tmp_path, controller, validators, case, status):
    store = controller(tmp_path)
    bindings = numerical_observations(tmp_path, store, {'scope': 'numeric plugin control'}, case)
    card = role_registry.load('ml-trainer')
    checks, reviewer_items = validators.validator_ids(card)
    assert len(checks) == 13 and reviewer_items == []
    actual = validators.run_validators(card, {'check_inputs': bindings},
                                       run_dir=tmp_path, scratch=tmp_path / 'scratch')
    assert actual['passed'] is (case == 'good')
    assert {row['check_id'] for row in actual['results']} == set(checks)
    assert {row['status'] for row in actual['results']} == {status}


@pytest.mark.parametrize('mutation', ['missing', 'subject', 'spec', 'record', 'other_check', 'public_document'])
def test_CF12_governed_validate_refuses_rebound_or_public_ml_evidence(
        tmp_path, controller, validators, mutation):
    store = controller(tmp_path)
    bindings = numerical_observations(tmp_path, store, {'scope': 'numeric plugin control'}, 'good')
    key = 'check:ml-crossfit-audit'
    if mutation == 'missing':
        del bindings[key]
    elif mutation == 'public_document':
        public = tmp_path / 'declared.json'
        public.write_text('{"checks":{"check:ml-crossfit-audit":{"verdict":"pass"}}}')
        bindings[key] = {'document': public.name}
    else:
        field = {'subject': 'subject_sha256', 'spec': 'spec_sha256', 'record': 'record_id',
                 'other_check': 'record_id'}[mutation]
        bindings[key][field] = (bindings['check:ml-equal-budget']['record_id'] if mutation == 'other_check'
                                else 'f' * 64)
    actual = validators.run_validators(role_registry.load('ml-trainer'), {'check_inputs': bindings},
                                       run_dir=tmp_path, scratch=tmp_path / 'scratch')
    assert actual['passed'] is False
    assert next(r for r in actual['results'] if r['check_id'] == key)['status'] == 'inconclusive'


@pytest.mark.parametrize('check', [
    {'verdict': 'pass', 'source': 'worker'},
    {'verdict': 'pass', 'source': 'graph'},
    {'verdict': 'pass', 'source': 'validator', 'validator': {}, 'artifact': {'path': 'x', 'sha256': 'a' * 64}},
    {'verdict': 'pass', 'source': 'validator', 'validator': {'implementation': 'numeric'}, 'artifact': {}},
    {'verdict': 'asserted_by_construction', 'source': 'validator', 'validator': {'implementation': 'numeric'},
     'artifact': {'path': 'x', 'sha256': 'a' * 64}},
])
def test_CF12_controller_observation_does_not_promote_unexecuted_or_asserted_success(tmp_path, controller, check):
    store = controller(tmp_path)
    key = 'check:ml-crossfit-audit'
    binding = rpc.record_ml_stage(store, spec={}, stage='S7', result={'checks': {key: deepcopy(check)}})[key]
    assert rpc.observed_ml_result(store, binding, check_id=key)['status'] == 'inconclusive'


def test_CF12_reviewer_items_remain_noncomputing_in_governed_validation(validators):
    card = role_registry.load('ml-planner')
    _, reviewer_only = validators.validator_ids(card)
    assert set(rpc.ML_REVIEWER_ITEMS) <= set(reviewer_only)
