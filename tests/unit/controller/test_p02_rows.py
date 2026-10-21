"""P02 coverage rows, one test each: R05, G02 and the GATE rows P02 builds (approve_plan, launch, checkin2_accept,
correction, deviation). Each test applies the row's mutation and checks the refusal, with a positive control."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ravel.controller import ledger
from ravel.controller.ledger import state as state_module
from ravel.workflow import decision_gate, graph_nodes
from p02_support import (INTAKE, PLAN, RUN, FakeStore, fixture_catalogue, install_controller, satisfy,
                              use_catalogue)

ACTION = {'kind': 'controller.decision', 'digest': 'd' * 64, 'summary': 'fixture', 'pins': [], 'node_id': None}
PREREQUISITES = ('X-INTAKE', 'X-ROUTE', 'X-SEATDERIV', 'X-CI1', 'CHECKIN-1')


def k(row, **scope):
    return ledger.instance_key(row, RUN, scope)


@pytest.fixture
def run(tmp_path, monkeypatch):
    """A controller-owned run past CHECK-IN 1 over the fictional catalogue; providers isolated, epoch two."""
    use_catalogue(monkeypatch, fixture_catalogue())
    rundir = tmp_path / 'run'
    rundir.mkdir()
    install_controller(monkeypatch, {str(rundir): RUN}, tmp_path / 'store')
    store = FakeStore(RUN, root=tmp_path / 'store')
    ledger.materialise(store, 'intake', INTAKE)
    ledger.materialise(store, 'plan', {'plan': PLAN, 'route': 'analysis'})
    critic = ledger.materialise(store, 'review', {'step': 'plan_review', 'seat': 'plan-critic', 'attempt': 1})
    satisfy(store, critic + [key for key in ledger.pending(store) if key.split('@')[0] in PREREQUISITES])
    facts = {'agent_layer_epoch': 2}
    monkeypatch.setattr(decision_gate, '_facts', lambda rundir: dict(facts))
    monkeypatch.setattr(decision_gate, '_provider_errors', lambda *args: [])
    yield rundir, store, facts
    state_module.forget(store)


def reach_waypoint(store):
    maker = ledger.materialise(store, 'dispatch', {'step': 's1', 'seat': 'maker', 'attempt': 1, 'seat_kind': 'worker'})
    checker = ledger.materialise(store, 'review', {'step': 's1', 'seat': 'checker', 'attempt': 1})
    satisfy(store, maker + checker + [k('X-OP-alpha', step='s1'), k('X-STEPDOC', step='s1'),
                                      k('GATE-launch', step='s1'), k('CHECKIN-2', step='s1'), k('X-CI2', step='s1')])


def without_provider(monkeypatch, name):
    registry = decision_gate._registry()
    registry['providers'] = [p for p in registry['providers'] if p['id'] != name]
    for gate in list(registry['required_providers']):
        registry['required_providers'][gate] = [p for p in registry['required_providers'][gate] if p != name]
    monkeypatch.setattr(decision_gate, '_registry_bytes', lambda: json.dumps(registry).encode())


def approved(store):
    """The plan decision taken at CHECK-IN 1; every later edge requires it."""
    satisfy(store, [k('GATE-approve_plan')])


GATE_CASES = {
    'approve_plan': (dict(ACTION), lambda s: None, k('GATE-approve_plan')),
    'launch': ({**ACTION, 'node_id': 's1'}, approved, k('GATE-launch', step='s1')),
    'checkin2_accept': ({**ACTION, 'waypoint': 's1'}, lambda s: approved(s) or reach_waypoint(s),
                        k('GATE-checkin2_accept', step='s1')),
    'correction': ({**ACTION, 'event': 'c1'}, lambda s: None, k('GATE-correction', event='c1')),
    'deviation': ({**ACTION, 'event': 'd1'}, lambda s: approved(s) or ledger.materialise(
        s, 'event', {'kind': 'deviation', 'id': 'd1'}) and satisfy(s, [k('CHECKIN-deviation', event='d1')]),
                  k('GATE-deviation', event='d1')),
}


def gate_row_case(run, monkeypatch, gate):
    """Removed provider, permissive gate seam, epoch-one layout: each refused; then the positive control passes."""
    rundir, store, facts = run
    action, prepare, entry = GATE_CASES[gate]
    prepare(store)
    with monkeypatch.context() as patch:   # a provider removed from the installed registry
        without_provider(patch, 'review_points')
        assert [e.code for e in ledger.decide(store, rundir, gate, dict(action))] == ['provider_registry_unpinned']
    with graph_nodes.gate_checker(lambda *args, **kwargs: [], providers=lambda name: []):
        facts['agent_layer_epoch'] = 1     # an epoch-one layout, decided while an in-process seam approves all
        assert graph_nodes.check_gate(str(rundir), gate, dict(action)) == []      # the seam is active
        assert [e.code for e in ledger.decide(store, rundir, gate, dict(action))] == ['epoch_one_controller_run']
        facts['agent_layer_epoch'] = 2
    state = state_module.load(store, full=True)
    assert entry not in state.instances or state.instances[entry].status == 'pending'
    assert ledger.decide(store, rundir, gate, dict(action)) == []                 # positive control
    instance = state_module.load(store, full=True).instances[entry]
    assert instance.status == 'satisfied' and instance.evidence['mechanism'] == 'decision_gate.check'


def test_GATE_approve_plan_reads_installed_providers_and_refuses_seams_and_epoch_one(run, monkeypatch):
    gate_row_case(run, monkeypatch, 'approve_plan')


def test_GATE_launch_reads_installed_providers_and_refuses_seams_and_epoch_one(run, monkeypatch):
    gate_row_case(run, monkeypatch, 'launch')


def test_GATE_checkin2_accept_reads_installed_providers_and_refuses_seams_and_epoch_one(run, monkeypatch):
    gate_row_case(run, monkeypatch, 'checkin2_accept')


def test_GATE_correction_reads_installed_providers_and_refuses_seams_and_epoch_one(run, monkeypatch):
    gate_row_case(run, monkeypatch, 'correction')


def test_GATE_deviation_reads_installed_providers_and_refuses_seams_and_epoch_one(run, monkeypatch):
    gate_row_case(run, monkeypatch, 'deviation')


def test_GATE_rows_cannot_be_discharged_without_the_decision_gate(run):
    rundir, store, _ = run
    entry = k('GATE-approve_plan')
    with pytest.raises(ledger.LedgerError) as raised:
        ledger.record(store, entry, 'waived', {'authority': 'anything'})
    assert raised.value.code == 'waiver_refused'      # an inner-guard row nobody may waive
    report = {row['entry']: row for row in ledger.gate(store, 'deliver[accepted]')}
    assert report[entry]['consequence'] == 'diagnostic'


def test_G02_a_missing_required_provider_or_invalid_evidence_refuses(tmp_path, monkeypatch):
    use_catalogue(monkeypatch, fixture_catalogue())
    rundir = tmp_path / 'run'
    rundir.mkdir()
    install_controller(monkeypatch, {str(rundir): RUN}, tmp_path / 'store')
    monkeypatch.setattr(decision_gate, '_facts', lambda rundir: {'agent_layer_epoch': 2})
    registry = json.loads(decision_gate._registry_bytes())
    required = registry['required_providers']['launch']
    for row in registry['providers']:
        if row['id'] == required[0]:
            row['active'] = False                      # a required provider switched off
    errors = decision_gate._provider_errors(Path(rundir), 'launch', dict(ACTION), {'agent_layer_epoch': 2},
                                            registry, decision_gate._rows(registry, 'launch'))
    assert any(e.code == 'provider_inactive' and e.provider == required[0] for e in errors)
    # the same switch in the installed file refuses a controller decision before any provider runs
    monkeypatch.setattr(decision_gate, '_registry_bytes', lambda: json.dumps(registry).encode())
    assert [e.code for e in decision_gate.check(rundir, 'launch', dict(ACTION))] == ['provider_registry_unpinned']
    # invalid provider evidence is a refusal, not a pass
    bad = {'providers': [{'id': 'broken', 'module': 'ravel.workflow.decision_gate', 'function': 'registry_sha256',
                          'gates': ['launch'], 'owner': 'fixture', 'active': True}],
           'required_providers': {'launch': ['broken']}, 'required_scopes': []}
    errors = decision_gate._provider_errors(Path(rundir), 'launch', dict(ACTION), {'agent_layer_epoch': 2}, bad,
                                            decision_gate._rows(bad, 'launch'))
    assert [e.code for e in errors] == ['provider_evidence_invalid']


def test_R05_an_open_parent_conserves_every_original_obligation(run):
    _, store, _ = run
    child, sibling = k('X-KEEP', deliverable='D1'), k('X-KEEP', deliverable='D2')
    reach_waypoint(store)                             # the child step s1 completes
    with pytest.raises(ledger.LedgerError) as raised:  # the sibling has no covering child
        ledger.record(store, sibling, 'satisfied', {'covered_by': ['s1']})
    assert raised.value.code == 'cover_refused'
    with pytest.raises(ledger.LedgerError) as raised:
        ledger.record(store, sibling, 'not_applicable', {'reason': 'no longer needed'})
    assert raised.value.code == 'conservation_refused'
    satisfy(store, [k('GATE-checkin2_accept', step='s1')])
    assert ledger.parent_join(store) == [child]
    report = {row['entry']: row for row in ledger.gate(store, 'deliver[accepted]')}
    assert report[sibling]['consequence'] == 'qualified'        # the parent delivery stays qualified
    assert ledger.gate(store, 'deliver[qualified]') == []
    replan = {**PLAN, 'deliverables': [{'id': 'D1', 'steps': ['s1']}]}
    ledger.materialise(store, 'plan', {'plan': replan, 'route': 'analysis'})
    assert ('deliverable:D2', 'deliverable_not_declared') in [
        (row['entry'], row['reason']) for row in ledger.gate(store, 'plan→plan_review')]
