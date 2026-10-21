"""Plan-bind rows of a step a route re-binds: a not-applicable row verifies only by re-evaluating its check."""
from __future__ import annotations

from copy import deepcopy

from ravel.controller.step import binding
from ravel.controller.step.services import digest


def subgraph_step(**extra):
    step = {'id': 'campaign', 'kind': 'subgraph', 'graph': {'id': 'research.loop', 'instance': {}}, 'inputs': [],
            'outputs': [], 'depends_on': [], 'review': [], 'parameters': {}, 'budget': {}}
    step.update(extra)
    return step


class Ledger:
    """The ledger's read interface over rows recorded for ``recorded`` (a step's earlier bytes)."""

    def __init__(self, recorded):
        self.rows = []
        checks = binding._checks(recorded, None, None, binding._derivation(recorded, None))
        for row_id in ('CF07', 'CF08', 'I05', 'R13', 'V01'):
            status, reason, _ = binding._evaluate_row(row_id, checks, recorded, None, binding._derivation(recorded, None),
                                                      None)
            self.rows.append({'entry': f'{row_id}@run/step=campaign', 'id': row_id, 'status': status,
                              'evidence': {'step_sha256': digest(recorded), 'reason': reason}})

    def current(self, store, *, node, step):
        return deepcopy(self.rows) if node == binding.PLAN_BIND_NODES[0] else []


def test_rebound_role_less_step_verifies_by_reevaluating_its_not_applicable_rows():
    before = subgraph_step()
    after = subgraph_step(parameters={'research_request': {'sha256': 'a' * 64}}, budget={'wall_seconds': 1800})
    ledger = Ledger(before)
    assert {row['status'] for row in ledger.rows} == {'not_applicable'}
    assert binding.unverified(ledger, None, before) == []
    assert digest(after) != digest(before)
    assert binding.unverified(ledger, None, after) == [], 'the same checks still do not apply to the new bytes'


def test_rebound_step_whose_check_now_applies_stays_unverified(monkeypatch):
    from ravel.controller.step import graph
    from ravel.workflow import role_registry
    monkeypatch.setattr(graph, 'registry_pin', lambda store, context: role_registry.registry_sha256())
    before = subgraph_step()
    ledger = Ledger(before)
    rebound = subgraph_step(kind='synthesize', role='coordinator', review=['physics-critic'])
    problems = binding.unverified(ledger, None, rebound)
    assert problems and {p['problem'] for p in problems} == {'recorded_for_other_step_bytes'}


def test_a_changed_not_applicable_reason_or_a_satisfied_row_is_not_reused():
    before = subgraph_step()
    ledger = Ledger(before)
    ledger.rows[0]['evidence']['reason'] = 'not_applicable:some_other_reason'
    after = subgraph_step(budget={'wall_seconds': 60})
    assert [p['entry'] for p in binding.unverified(ledger, None, after)] == ['CF07@run/step=campaign']
    ledger = Ledger(before)
    ledger.rows[2].update(status='satisfied')
    assert [p['entry'] for p in binding.unverified(ledger, None, after)] == ['I05@run/step=campaign']
