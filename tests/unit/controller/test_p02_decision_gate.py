"""P02 decision gate: installed providers only, pinned for controller runs, no epoch one, and the ledger added."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import types

import pytest

from ravel.controller import ledger
from ravel.controller.ledger import state as state_module
from ravel.workflow import decision_gate
from p02_support import (INTAKE, PLAN, RUN, FakeStore, fixture_catalogue, install_controller, satisfy,
                              use_catalogue)

ACTION = {'kind': 'controller.approve_plan', 'digest': 'a' * 64, 'summary': 'fixture', 'pins': [], 'node_id': None}


def legacy_epoch_one(rundir: Path) -> Path:
    rundir.mkdir(parents=True, exist_ok=True)
    (rundir / 'task_contract.json').write_text(json.dumps({'agent_layer_epoch': 1}))
    return rundir


@pytest.fixture
def controller(tmp_path, monkeypatch):
    """A controller-owned run directory, its store, and the fictional catalogue (pinning the installed registry)."""
    use_catalogue(monkeypatch, fixture_catalogue())
    rundir = tmp_path / 'run'
    rundir.mkdir()
    install_controller(monkeypatch, {str(rundir): RUN}, tmp_path / 'store')
    store = FakeStore(RUN, root=tmp_path / 'store')
    yield rundir, store
    state_module.forget(store)


def codes(errors):
    return [e.code for e in errors]


# ---- providers come from the installed package only -----------------------------------------------------------

def test_p02_a_providers_file_written_into_a_run_tree_is_ignored(tmp_path, monkeypatch):
    installed = decision_gate._registry()
    digest = decision_gate.registry_sha256()
    listed = {gate: [p['id'] for p in decision_gate.providers(gate)] for gate in decision_gate.GATES}
    planted = {'schema_version': 1, 'providers': [{**p, 'active': False} for p in installed['providers']],
               'required_providers': {}, 'required_scopes': []}
    rundir = legacy_epoch_one(tmp_path / 'run')
    for relative in ('providers.json', 'data/gates/providers.json', 'src/ravel/data/gates/providers.json',
                     '.ravel/gates/providers.json', 'inputs/providers.json'):
        target = rundir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(planted))
    monkeypatch.chdir(rundir)
    for name in ('RAVEL_ROOT', 'RAVEL_STATE_DIR', 'RAVEL_WORK_ROOT', 'RAVEL_DATA_DIR', 'RAVEL_GATE_PROVIDERS'):
        monkeypatch.setenv(name, str(rundir))
    assert decision_gate._registry() == installed
    assert decision_gate.registry_sha256() == digest
    assert {gate: [p['id'] for p in decision_gate.providers(gate)] for gate in decision_gate.GATES} == listed
    assert all(p['active'] for p in decision_gate.providers('launch') if p['id'] in ('ceilings', 'executor'))


def test_p02_a_controller_run_refuses_a_registry_the_catalogue_does_not_pin(controller, monkeypatch):
    rundir, _ = controller
    registry = decision_gate._registry()
    registry['providers'] = [p for p in registry['providers'] if p['id'] != 'review_points']
    registry['required_providers']['*'] = [p for p in registry['required_providers']['*'] if p != 'review_points']
    monkeypatch.setattr(decision_gate, '_registry_bytes', lambda: json.dumps(registry).encode())
    for gate in ('approve_plan', 'launch', 'checkin2_accept', 'correction', 'deviation'):
        assert codes(decision_gate.check(rundir, gate, dict(ACTION))) == ['provider_registry_unpinned'], gate


def test_p02_the_same_registry_change_leaves_legacy_runs_on_their_existing_decisions(tmp_path, monkeypatch):
    registry = decision_gate._registry()
    registry['providers'] = [p for p in registry['providers'] if p['id'] != 'review_points']
    monkeypatch.setattr(decision_gate, '_registry_bytes', lambda: json.dumps(registry).encode())
    monkeypatch.setitem(sys.modules, 'ravel.controller.store', None)   # an install without the controller core
    rundir = legacy_epoch_one(tmp_path / 'run')
    assert decision_gate.check(rundir, 'approve_plan', dict(ACTION)) == []
    assert codes(decision_gate.check(rundir, 'unblind', dict(ACTION))) == ['epoch_gate_unsupported']


@pytest.mark.parametrize('gate', decision_gate.GATES)
def test_p02_a_controller_run_never_takes_an_epoch_one_decision(controller, gate):
    rundir, _ = controller
    legacy_epoch_one(rundir)
    assert codes(decision_gate.check(rundir, gate, dict(ACTION))) == ['epoch_one_controller_run']


def test_p02_unknown_controller_ownership_refuses_rather_than_falling_back(tmp_path, monkeypatch):
    module = types.ModuleType('ravel.controller.store')

    def controller_owned(run_dir):
        raise OSError('store index unreadable')
    module.controller_owned = controller_owned
    monkeypatch.setitem(sys.modules, 'ravel.controller.store', module)
    rundir = legacy_epoch_one(tmp_path / 'run')
    assert codes(decision_gate.check(rundir, 'approve_plan', dict(ACTION))) == ['controller_ownership_unknown']
    module.controller_owned = lambda run_dir: 7
    assert codes(decision_gate.check(rundir, 'approve_plan', dict(ACTION))) == ['controller_ownership_unknown']
    broken = types.ModuleType('ravel.controller.store')     # installed but unusable: never the legacy gate
    monkeypatch.setitem(sys.modules, 'ravel.controller.store', broken)
    assert codes(decision_gate.check(rundir, 'approve_plan', dict(ACTION))) == ['controller_ownership_unknown']
    monkeypatch.setitem(sys.modules, 'ravel.controller.store', None)   # not installed at all: legacy decisions
    assert decision_gate.check(rundir, 'approve_plan', dict(ACTION)) == []


# ---- the ledger joins every decision of a controller run --------------------------------------------------------

@pytest.fixture
def epoch_two(monkeypatch):
    """Typed epoch-two facts and providers isolated to a sentinel, so the ledger's share of a decision is visible."""
    monkeypatch.setattr(decision_gate, '_facts', lambda rundir: {'agent_layer_epoch': 2})
    sentinel = []
    monkeypatch.setattr(decision_gate, '_provider_errors', lambda *args: list(sentinel))
    return sentinel


def test_p02_a_controller_decision_requires_its_ledger_transition(controller, epoch_two):
    rundir, store = controller
    errors = decision_gate.check(rundir, 'approve_plan', dict(ACTION))
    assert codes(errors) == ['ledger_stage_not_materialised']
    assert errors[0].provider == 'ledger' and errors[0].pins == ('ledger:stage:intake',)
    ledger.materialise(store, 'intake', INTAKE)
    ledger.materialise(store, 'plan', {'plan': PLAN, 'route': 'analysis'})
    errors = decision_gate.check(rundir, 'approve_plan', dict(ACTION))
    assert 'ledger_pending' in codes(errors) and 'ledger_review_missing' in codes(errors)
    assert all(e.fix.endswith('before checkin1→execute.') for e in errors)
    assert any(' at controller.intake' in e.fix for e in errors)
    assert not any('P99' in e.fix or 'P99' in e.message for e in errors)   # no build package label in the text
    critic = ledger.materialise(store, 'review', {'step': 'plan_review', 'seat': 'plan-critic', 'attempt': 1})
    satisfy(store, critic + [key for key in ledger.pending(store) if key.split('@')[0] in (
        'X-INTAKE', 'X-ROUTE', 'X-SEATDERIV', 'X-CI1', 'CHECKIN-1')])
    assert decision_gate.check(rundir, 'approve_plan', dict(ACTION)) == []
    epoch_two.append(decision_gate.GateError('rdj_receipt_missing', 'approve_plan', 'rdj', 'm', 'f', ('rdj:x',)))
    assert codes(decision_gate.check(rundir, 'approve_plan', dict(ACTION))) == ['rdj_receipt_missing']


def test_p02_a_controller_launch_waits_for_the_plan_decision_and_the_waypoint_go(controller, epoch_two):
    rundir, store = controller
    past_checkin1(store)
    errors = decision_gate.check(rundir, 'launch', {**ACTION, 'node_id': 's1'})
    assert [e.pins for e in errors] == [(f'ledger:{ledger.instance_key("GATE-approve_plan", RUN, {})}',)]
    assert ledger.decide(store, rundir, 'approve_plan', dict(ACTION)) == []
    assert decision_gate.check(rundir, 'launch', {**ACTION, 'node_id': 's1'}) == []
    pins = {e.pins[0] for e in decision_gate.check(rundir, 'launch', {**ACTION, 'node_id': 's2'})}
    assert pins == {f'ledger:{ledger.instance_key(r, RUN, {"step": "s1"})}'
                    for r in ('CHECKIN-2', 'GATE-checkin2_accept', 'X-CI2')}


def test_p02_a_decision_without_its_store_refuses(controller, epoch_two, monkeypatch):
    rundir, _ = controller

    def broken(run_id, **kwargs):
        raise OSError('store unavailable')
    monkeypatch.setattr(sys.modules['ravel.controller.store'], 'RunStore', broken)
    assert codes(decision_gate.check(rundir, 'approve_plan', dict(ACTION))) == ['ledger_unavailable']


def test_p02_decide_discharges_the_decision_row_only_when_the_gate_passes(controller, epoch_two):
    rundir, store = controller
    ledger.materialise(store, 'intake', INTAKE)
    ledger.materialise(store, 'plan', {'plan': PLAN, 'route': 'analysis'})
    entry = ledger.instance_key('GATE-approve_plan', RUN, {})
    assert ledger.decide(store, rundir, 'approve_plan', dict(ACTION))           # refused: nothing recorded
    assert state_module.load(store, full=True).instances[entry].status == 'pending'
    critic = ledger.materialise(store, 'review', {'step': 'plan_review', 'seat': 'plan-critic', 'attempt': 1})
    satisfy(store, critic + [key for key in ledger.pending(store) if key.split('@')[0] in (
        'X-INTAKE', 'X-ROUTE', 'X-SEATDERIV', 'X-CI1', 'CHECKIN-1')])
    assert ledger.decide(store, rundir, 'approve_plan', dict(ACTION)) == []
    instance = state_module.load(store, full=True).instances[entry]
    assert instance.status == 'satisfied' and instance.evidence['gate'] == 'approve_plan'
    assert instance.evidence['registry_sha256'] == decision_gate.registry_sha256()
    deviation = {**ACTION, 'event': 'd1'}
    refused = ledger.decide(store, rundir, 'deviation', deviation)   # the occurrence exists; its check-in does not
    checkin = ledger.instance_key('CHECKIN-deviation', RUN, {'event': 'd1'})
    assert [e.pins for e in refused] == [(f'ledger:{checkin}',)]
    satisfy(store, [checkin])
    assert ledger.decide(store, rundir, 'deviation', deviation) == []
    occurrence = ledger.instance_key('GATE-deviation', RUN, {'event': 'd1'})
    assert state_module.load(store, full=True).instances[occurrence].status == 'satisfied'


def test_p02_decide_records_the_evidence_the_decision_providers_name(controller, epoch_two, monkeypatch):
    from ravel.workflow import rdj_loop
    rundir, store = controller
    past_checkin1(store)
    named = {'mechanism': 'rdj_approval.mapping', 'reviews': [{'credit': 'step-credit-000001'}]}
    monkeypatch.setattr(rdj_loop, 'gate_evidence', lambda directory, gate, action: dict(named))
    assert ledger.decide(store, rundir, 'approve_plan', dict(ACTION)) == []
    instance = state_module.load(store, full=True).instances[ledger.instance_key('GATE-approve_plan', RUN, {})]
    assert instance.evidence['providers'] == {'rdj': named} and instance.evidence['mechanism'] == 'decision_gate.check'


def test_p02_a_passed_decision_whose_provider_evidence_cannot_be_read_records_nothing(controller, epoch_two,
                                                                                       monkeypatch):
    from ravel.workflow import rdj_loop
    rundir, store = controller
    past_checkin1(store)

    def unreadable(directory, gate, action):
        raise ValueError('the evidence store is unreadable')
    monkeypatch.setattr(rdj_loop, 'gate_evidence', unreadable)
    errors = ledger.decide(store, rundir, 'approve_plan', dict(ACTION))
    assert codes(errors) == ['provider_evidence_invalid'] and 'unreadable' in errors[0].message
    entry = ledger.instance_key('GATE-approve_plan', RUN, {})
    assert state_module.load(store, full=True).instances[entry].status == 'pending'


def past_checkin1(store):
    ledger.materialise(store, 'intake', INTAKE)
    ledger.materialise(store, 'plan', {'plan': PLAN, 'route': 'analysis'})
    critic = ledger.materialise(store, 'review', {'step': 'plan_review', 'seat': 'plan-critic', 'attempt': 1})
    satisfy(store, critic + [key for key in ledger.pending(store) if key.split('@')[0] in (
        'X-INTAKE', 'X-ROUTE', 'X-SEATDERIV', 'X-CI1', 'CHECKIN-1')])


def test_p02_decide_refuses_a_run_directory_its_ledger_run_does_not_own(controller, epoch_two, tmp_path,
                                                                         monkeypatch):
    rundir, store = controller
    past_checkin1(store)
    entry = ledger.instance_key('GATE-approve_plan', RUN, {})
    legacy = legacy_epoch_one(tmp_path / 'legacy')
    other = tmp_path / 'other'
    other.mkdir()
    install_controller(monkeypatch, {str(rundir): RUN, str(other): 'run-two'}, tmp_path / 'store')
    assert decision_gate.check(legacy, 'approve_plan', dict(ACTION)) == []   # the legacy gate would pass it
    for directory in (legacy, other):
        errors = ledger.decide(store, directory, 'approve_plan', dict(ACTION))
        assert codes(errors) == ['ledger_run_mismatch'] and errors[0].pins == ('ledger:run',)
    assert state_module.load(store, full=True).instances[entry].status == 'pending'
    assert ledger.decide(store, rundir, 'approve_plan', dict(ACTION)) == []   # positive control
    assert state_module.load(store, full=True).instances[entry].status == 'satisfied'


def test_p02_decide_discharges_the_gate_row_of_the_step_its_transition_checked(controller, epoch_two):
    rundir, store = controller
    past_checkin1(store)
    assert ledger.decide(store, rundir, 'approve_plan', dict(ACTION)) == []
    assert decision_gate.check(rundir, 'launch', {**ACTION, 'node_id': 's2'})       # s2 waits for the waypoint GO
    assert ledger.decide(store, rundir, 'launch', {**ACTION, 'node_id': 's1', 'waypoint': 's2'}) == []
    instances = state_module.load(store, full=True).instances
    assert instances[ledger.instance_key('GATE-launch', RUN, {'step': 's1'})].status == 'satisfied'
    assert instances[ledger.instance_key('GATE-launch', RUN, {'step': 's2'})].status == 'pending'
