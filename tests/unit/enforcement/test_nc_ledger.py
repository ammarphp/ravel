"""Ledger rows: transitions, conservation and population equality are decided by the obligation ledger.

The adversary marks a parent obligation satisfied by a child that does not cover it, launches
before CHECK-IN 1, or claims a scan's coverage with a point deleted. Oracles are the ledger's own
refusals and unmet rows (read through ``ledger.gate`` and ``ledger.summary``); positive controls
take the same edge or status change with its evidence.
"""
from __future__ import annotations

import pytest

from nc_cases import CONTROLLER, case, require_controller
from nc_controller import checkin_view, controller_run
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register

PLAN = {'steps': [{'id': 's1', 'kind': 'derive', 'role': 'calculation'},
                  {'id': 's2', 'kind': 'derive', 'role': 'calculation'}],
        'deliverables': {'d1': ['s1'], 'd2': ['s2']}}


def _materialised(nc, *, mode='autonomous'):
    ledger = require_controller('ledger')
    require_controller('graph').compose_services()
    store, run_dir = controller_run(nc, mode=mode)
    intake = ledger.materialise(store, 'intake', {'run_id': store.run_id, 'task_mode': 'calculation',
                                                  'route': 'judgment', 'deliverables': ['d1', 'd2']})
    planned = ledger.materialise(store, 'plan', {'plan': PLAN})
    return ledger, store, run_dir, intake, planned


def _conservation_key(keys, deliverable):
    found = [k for k in keys if f'@{deliverable}' in k or f':{deliverable}' in k or k.endswith(deliverable)]
    assert found, f'no conservation instance for {deliverable} among {len(keys)} plan instances'
    return found[0]


@case('R05', binding=CONTROLLER)
def test_R05_a_parent_obligation_cannot_be_satisfied_by_a_child_that_does_not_cover_it(nc):
    ledger, store, _, intake, planned = _materialised(nc)
    key = _conservation_key(planned, 'd2')
    for evidence in ({'covered_by': ['s1']}, {'covered_by': ['s2']}, {'mechanism': 'fictional'}):
        with pytest.raises(ledger.LedgerError):
            ledger.record(store, key, 'satisfied', evidence)
    pending = {e if isinstance(e, str) else e.get('key') for e in ledger.pending(store)}
    assert key in pending, 'the conserved obligation stays open'
    assert ledger.gate(store, 'deliver[accepted]'), 'no accepted delivery while an obligation is uncovered'
    # Positive control: a run-level row with mechanism evidence is recorded; the bounded ending stays open.
    plain = next(k for k in intake if k.split('@', 1)[0] in ('A04', 'CT04', 'R01'))
    ledger.record(store, plain, 'satisfied', {'mechanism': 'M03', 'record': 'fictional-mode-record'})
    assert ledger.gate(store, 'deliver[qualified]') == []


@case('A01', binding=CONTROLLER)
def test_A01_no_smoke_launch_before_the_current_check_in_1_authority(nc):
    authority = require_controller('authority')
    ledger, store, _, _, _ = _materialised(nc)
    smoke = {'id': 'nc-smoke', 'rung': 'smoke', 'pins': {'plan_sha256': 'a' * 64}, 'go_pins': {}, 'requires_go': False}
    with pytest.raises(authority.AuthorityRefused):
        authority.authorize_effect(store, smoke)
    unmet = ledger.gate(store, 'checkin1→execute')
    assert unmet, 'the execute edge is closed before CHECK-IN 1'
    assert ledger.gate(store, 'launch[s1]'), 'no launch edge before CHECK-IN 1'
    # Positive control: the operator-configured CHECK-IN 1 record authorizes the smoke effect.
    granted = authority.request(store, 'approve_plan',
                                {'view': checkin_view(store, 'approve_plan', plan_sha256='a' * 64)},
                                {'rung': 'smoke'})
    assert granted.get('decision') == 'approve', granted
    authority.authorize_effect(store, smoke)


register(Mutation('M01', ('ravel.controller.ledger:gate', 'ravel.controller.ledger.gates:unmet'),
                  lambda original: lambda *a, **k: [], ('A01', 'R05'), binding=MUTATION_CONTROLLER,
                  why='every transition is open whatever the ledger holds'))


@case('E24', binding=CONTROLLER)
def test_E24_a_deleted_scan_point_stays_a_visible_hole_in_the_original_domain(nc):
    ledger = require_controller('ledger')
    grid = ['p-0100-010', 'p-0100-020', 'p-0200-010', 'p-0200-020', 'p-0300-offgrid']
    harvested = ['p-0100-010', 'p-0100-020', 'p-0200-010', 'p-0200-020']
    assert ledger.population_equality(grid, harvested) == ['p-0300-offgrid']
    duplicated = ['p-0100-010', 'p-0100-010', 'p-0100-020', 'p-0200-010', 'p-0200-020']
    assert ledger.population_equality(grid, duplicated) == ['p-0300-offgrid']
    renamed = [*harvested, 'p-0300-ongrid']
    assert ledger.population_equality(grid, renamed) == ['p-0300-offgrid']
    assert ledger.population_equality(grid, list(reversed(grid))) == []  # positive control


register(Mutation('M27', 'ravel.controller.ledger:population_equality', lambda original: lambda *a, **k: [],
                  ('E24',), binding=MUTATION_CONTROLLER, why='population holes are never reported'))
