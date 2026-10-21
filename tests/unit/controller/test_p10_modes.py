"""Exhaustive inert interface conformance; no mode receives scientific qualification.

Mode identifiers come from the installed descriptor source. Every adapter,
authority and process below is fictional; this exercises real controller
admission and ordinary-file pin checks without claiming native mode support.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

from ravel import evidence_layout
from ravel.controller.routes import study
from ravel.controller.routes.study import runtime
from ravel.workflow import science

DATA = Path(study.__file__).resolve().parents[3] / 'data'
# Frozen exact MODE row population extracted from the controller coverage census.
CENSUS_MODES = ('amplitude-crosscheck', 'amplitude-integration', 'amplitude-predictions', 'analyze', 'asimov-sensitivity', 'authored-analysis', 'background-discrete-profile', 'chargino-decay-table', 'checkmate-events', 'columnar-analysis', 'continuous-fit', 'contrast', 'contur-companion', 'contur-import', 'contur-yoda', 'cosmic-evolution', 'cosmology-solver', 'coupling-morphing', 'cr-signal-qualification', 'cross-section', 'dataset-query-quantities', 'derived-quantities', 'diagram-analysis', 'diagrammatica-code', 'differential-likelihood', 'domain', 'eft-convention-transport', 'eft-functions', 'eft-toolchain', 'event-production', 'feyn-graph', 'feynarts-amplitude', 'figure-comparison', 'finite-integrals', 'finite-mc', 'full-auxiliary-calibration', 'generated-spectrum', 'generation-reconciliation', 'group-composition', 'group-normalization', 'hs3-likelihood', 'initialized-settings-qualification', 'initialized-settings-retained', 'joint-fit', 'joint-qualification', 'joint-score', 'lhe-transform', 'likelihood-candidate-check', 'likelihood-parity', 'likelihood-profile-probe', 'likelihood-step-refinement', 'literal-calculation', 'ma5-pad', 'ma5-saf', 'mass-width-grid', 'mc-closure', 'mc-expected-construction', 'measurement', 'model-authoring', 'model-derivation-bridge', 'model-events', 'model-inputs', 'model-portfolio', 'model-provider-bridge', 'model-sources', 'model-tool-bridge', 'model-ward', 'mpi-observer', 'mpi-paired-effect', 'mssm-observable-map', 'native-group-acquisition', 'native-likelihood', 'native-statistical-construction', 'nmssm-yukawa-map', 'normalized-measurement', 'ntuple-inventory', 'numerical-reference-check', 'parameter-space-sampling', 'pdf-variations', 'prescribed-statistic', 'published-model', 'published-summary', 'quantitative-predictive', 'quantities', 'ratio-measurement', 'reco-ntuple-routine', 'resonance-lineshape', 'resonance-width', 'retained-shower', 'root-stream', 'scientific-delivery', 'search-statistics', 'sfitter-native-fit', 'sfitter-observed-events', 'signal-template', 'simplified-spectrum', 'source-tables', 'statistical-model', 'stau-events', 'svj-recipe', 'symbolic-evaluation', 'task-completion-context', 'tree-array-export', 'weighted-events', 'width-inputs', 'workspace-combination-study')
DESCRIBED_MODES = json.loads((DATA / 'mode_descriptors.json').read_text())['modes']
MODES = tuple(sorted(mode for mode in DESCRIBED_MODES if mode in CENSUS_MODES))
if evidence_layout.is_public_tree(DATA.parents[2]):
    # A release describes the modes it ships and withholds the rest of the frozen source population.
    assert MODES and set(MODES) <= set(CENSUS_MODES)
else:
    assert len(MODES) == 106 and set(MODES) == set(CENSUS_MODES)


class Store:
    def __init__(self, root):
        self.root = root
        self.root.mkdir()
        self.run_id = 'fictional-mode-run'
        self.rows = []

    def append(self, kind, record):
        value = json.loads(json.dumps(record, allow_nan=False))
        identifier = str(len(self.rows) + 1)
        self.rows.append({'id': identifier, 'kind': kind, 'record': value})
        return identifier

    def scan(self, kind):
        return deepcopy([r for r in self.rows if r['kind'] == kind])

    def read(self, kind, identifier):
        return next(r for r in self.scan(kind) if r['id'] == identifier)

    def path(self, *parts):
        return self.root.joinpath(*parts)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize('mode', MODES, ids=lambda mode: 'MODE-' + mode)
def test_MODE_typed_operation_admission(mode, tmp_path, monkeypatch):
    import ravel.controller as controller
    run = tmp_path / 'run'
    run.mkdir()
    store = Store(tmp_path / 'protected-store')
    child = run / 'children' / 'study'
    calls = {'validate': 0, 'verify': 0, 'popen': 0, 'request': 0}
    state = {'pending': False, 'decision': 'approve'}
    adapter = ModuleType('ravel.physics.fictional_mode_adapter')
    def validate_task(task):
        if task != {'finite_inputs': [2, 7], 'units': 'fictional_unit',
                    'evidence_contract': {'kind': 'fictional descriptor', 'version': 1}}:
            raise ValueError('complete fictional typed task and evidence contract required')
    adapter.validate = validate_task
    def validate_spec(spec):
        calls['validate'] += 1
        if spec.get('mode') != mode or spec.get('max_seconds') != 10:
            raise ValueError('exact fictional operation and ceiling required')
        adapter.validate(spec.get('task'))
        return spec
    if mode not in (*science.MODES, *science.PROVIDER_MODES):
        monkeypatch.setattr(science, 'MODES', (*science.MODES, mode))
    monkeypatch.setattr(science, 'validate', validate_spec)
    monkeypatch.setattr(science, 'adapter', lambda spec: adapter)
    signatures = {mode: {'implementation': {'kind': 'science-mode', 'mode': mode,
                                          'module': adapter.__name__}}}
    executors = {mode: 'calculation'}
    monkeypatch.setattr(study, '_tables', lambda: (signatures, executors))
    spec = {'schema_version': 2, 'mode': mode, 'max_seconds': 10, 'max_attempts': 1,
            'task': {'finite_inputs': [2, 7], 'units': 'fictional_unit',
                     'evidence_contract': {'kind': 'fictional descriptor', 'version': 1}}}
    proposal = {'kind': 'fictional-ordinary-plan', 'mode': mode, 'inputs': deepcopy(spec['task'])}
    plan_sha = write_json(child / science.PLAN, proposal)
    spec_sha = write_json(child / science.SPEC, spec)
    def verify_plan(path, approved=False):
        calls['verify'] += 1
        assert Path(path) == child and approved is True
        assert json.loads((Path(path) / science.PLAN).read_text()) == proposal
        return deepcopy(proposal)
    monkeypatch.setattr(science, 'verify_plan', verify_plan)
    authority = ModuleType('ravel.controller.authority')
    authority.stop_state = lambda store: 'running'
    def request(store, kind, subject, bounds):
        calls['request'] += 1
        assert kind == 'approve_plan'
        assert subject['view']['mode'] == mode
        assert bounds['budget']['wall_seconds'] == 10
        return {'pending': True} if state['pending'] else {'id': 'fictional-authority-record', 'decision': state['decision'],
            'authorizes_effects': state['decision'] == 'approve'}
    authority.request = request
    def verify(store, record_id, *, kind, subject=None):
        assert record_id == 'fictional-authority-record' and kind == 'approve_plan'
        # The authority compares the decision's pins with the current check-in pins (the view's pins).
        assert subject == {'plan_sha256': 'a' * 64}
        assert not state['pending'] and state['decision'] == 'approve'
        return {'id': record_id, 'decision': 'approve', 'authorizes_effects': True}
    authority.verify = verify
    ledger = ModuleType('ravel.controller.ledger')
    ledger.gate = lambda store, transition: []
    confine = ModuleType('ravel.controller.confine')
    from p07_support import package_path
    package_path(confine)  # the real confinement submodules still import
    confine.probe = lambda kind, capsule: {'equal': True}
    class Process:
        returncode = 0
        def communicate(self, timeout=None):
            assert timeout == 10
            return 'fictional standard output', ''
    def popen(capsule, **kwargs):
        calls['popen'] += 1
        assert capsule['limits']['wall_seconds'] == 10
        assert capsule['argv'][:3] == [sys.executable, '-m', runtime.ADAPTER]
        assert str(child) in capsule['argv']
        return Process()
    confine.popen = popen
    for name, module in [('authority', authority), ('ledger', ledger), ('confine', confine)]:
        monkeypatch.setitem(sys.modules, module.__name__, module)
        monkeypatch.setattr(controller, name, module, raising=False)
    base = {'id': 'operate-positive', 'kind': 'operate', 'role': 'calculation', 'operation': mode,
            'budget': {'wall_seconds': 10}, 'outputs': [],
            'parameters': {'adapter': runtime.ADAPTER, 'ordinary': {'kind': 'science',
                'child_rundir': 'children/study', 'plan_sha256': plan_sha,
                'specification_sha256': spec_sha}}}
    context = {'run_dir': str(run), 'plan_sha256': 'a' * 64, 'attempt': 1,
               'authority_subject': {'view': {'mode': mode, 'pins': {'plan_sha256': 'a' * 64}}}}
    admitted = study.mode_admission(deepcopy(spec))
    assert admitted['operation'] == mode and admitted['role'] == 'calculation'
    outcome = runtime.dispatch(store, deepcopy(base), context)
    assert outcome['exit_status'] == 0 and outcome['timed_out'] is False
    assert calls['popen'] == 1
    assert calls['verify'] >= 1 and calls['validate'] >= 2
    assert store.scan('study-operation-admission')
    assert any('outcome' in r['record'] for r in store.scan('study-operation'))

    def refuses(step, reason):
        step['id'] = 'operate-' + reason
        before = calls['popen']
        with pytest.raises((runtime.StudyHold, ValueError, TypeError, KeyError)):
            runtime.dispatch(store, step, context)
        assert calls['popen'] == before
        assert not [r for r in store.scan('study-operation')
                    if r['record'].get('key') == step['id'] + ':1']

    def updated_spec(value):
        changed = deepcopy(base)
        changed['parameters']['ordinary']['specification_sha256'] = write_json(child / science.SPEC, value)
        return changed

    # Missing task is rejected by real mode_admission and by real runtime dispatch.
    missing_task = {k: v for k, v in spec.items() if k != 'task'}
    with pytest.raises(ValueError, match='typed task'):
        study.mode_admission(missing_task)
    refuses(updated_spec(missing_task), 'missing-typed-task')
    write_json(child / science.SPEC, spec)

    # The complete typed task must also retain its declared evidence contract.
    absent_contract = deepcopy(spec)
    absent_contract['task'].pop('evidence_contract')
    with pytest.raises(ValueError, match='evidence contract'):
        study.mode_admission(absent_contract)
    refuses(updated_spec(absent_contract), 'missing-evidence-contract')
    write_json(child / science.SPEC, spec)

    wrong_role = deepcopy(base)
    wrong_role['role'] = 'unregistered-fictional-role'
    refuses(wrong_role, 'wrong-production-role')
    executors[mode] = 'other-fictional-executor'
    refuses(deepcopy(base), 'wrong-executor-binding')
    executors[mode] = 'calculation'
    executors.clear()
    with pytest.raises(ValueError, match='production role'):
        study.mode_admission(spec)
    refuses(deepcopy(base), 'missing-executor')
    executors[mode] = 'calculation'

    state['pending'] = True
    refuses(deepcopy(base), 'pending-authority')
    state['pending'] = False
    state['decision'] = 'reject'
    refuses(deepcopy(base), 'rejected-authority')
    state['decision'] = 'approve'
    saved_signature = signatures.pop(mode)
    with pytest.raises(ValueError, match='operation signature'):
        study.mode_admission(spec)
    refuses(deepcopy(base), 'missing-signature')
    signatures[mode] = saved_signature

    # Registration cannot redirect to a different implementation module.
    signatures[mode]['implementation']['module'] = 'ravel.physics.different_fictional_adapter'
    with pytest.raises(ValueError, match='implementation differs'):
        study.mode_admission(spec)
    refuses(deepcopy(base), 'wrong-adapter-module')
    signatures[mode]['implementation']['module'] = adapter.__name__

    required_recipe = deepcopy(base)
    required_recipe['parameters']['evidence_requirements'] = [
        {'row': 'E09', 'expected': 'source:absent-recipe.json'}]
    refuses(required_recipe, 'unresolved-required-evidence')
    record = store.scan('study-evidence')[-1]['record']
    assert record['row'] == 'E09' and record['status'] == 'violated'

    # Keep _ordinary real: changed input bytes fail even when adapter/authority fakes approve.
    (child / science.PLAN).write_text('{}')
    refuses(deepcopy(base), 'changed-plan-bytes')
    assert calls['popen'] == 1
