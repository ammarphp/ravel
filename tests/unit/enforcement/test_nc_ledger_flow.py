"""Ledger-flow rows: a waiver exists only as an authority record that names the waived row.

The adversary writes waiver files into the run tree, cites an authority id that does not exist, asks
the machine to approve a plan that waives an obligation, and reuses a valid waiver for a row nobody may
waive. Oracles are the ledger's own refusals and its pending and summary views; the positive control
waives the row with the operator's answered record.
"""
from __future__ import annotations

import json

import pytest

from nc_cases import CONTROLLER, case, require_controller
from nc_controller import checkin_view
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register


def _keys_of(ledger, keys, waivable):
    """Instance keys whose catalogue row may (or may not) be waived by authority."""
    catalogue = ledger.catalogue.load()
    return [k for k in keys if (catalogue.row(k.split('@', 1)[0])['waivability'] == 'authority') is waivable]


def _pending_keys(ledger, store):
    return {e if isinstance(e, str) else e.get('key') for e in ledger.pending(store)}


@case('I10', binding=CONTROLLER)
def test_I10_run_tree_waivers_are_ignored_and_a_waiver_is_only_an_authority_record_that_names_the_row(nc):
    authority = require_controller('authority')
    from test_nc_ledger import _materialised
    from test_nc_authority_flow import _escalated, _operator_shell
    ledger, store, run_dir, intake, _ = _materialised(nc)
    waivable = _keys_of(ledger, intake, True)[0]
    never = _keys_of(ledger, intake, False)[0]
    row = waivable.split('@', 1)[0]
    # Host-authored waiver files in the run tree.
    (run_dir / 'inputs').mkdir(exist_ok=True)
    for path in (run_dir / 'inputs' / 'waivers.json', run_dir / 'ledger-waivers.json'):
        path.write_text(json.dumps({waivable: {'status': 'waived', 'by': 'physicist'}, never: 'waived'}))
    assert waivable in _pending_keys(ledger, store) and ledger.summary(store)['waivers'] == []
    with pytest.raises(ledger.LedgerError):
        ledger.record(store, waivable, 'waived', {'authority': 'forged-waiver-record'})
    # A plan approval that waives the row never resolves by machine: it waits for the operator.
    subject = {'view': checkin_view(store, 'approve_plan', plan_sha256='a' * 64), 'obligations': [row]}
    pending, code = _escalated(authority, store, 'approve_plan', subject, {'rung': 'full'})
    assert 'waiving ledger obligations' in pending['reason'], pending
    # Positive control: the operator's answer is the waiver, for the row it names only.
    _operator_shell(nc)
    answered = authority.answer(store, pending['request'], code, 'approve')
    ledger.record(store, waivable, 'waived', {'authority': answered['id']})
    assert [w['entry'] for w in ledger.summary(store)['waivers']] == [waivable]
    with pytest.raises(ledger.LedgerError):
        ledger.record(store, never, 'waived', {'authority': answered['id']})
    assert never in _pending_keys(ledger, store)


register(Mutation('M04', 'ravel.controller.ledger.record:_authority', lambda original: lambda *a, **k: None,
                  ('I10',), binding=MUTATION_CONTROLLER, why='a waiver is recorded without its authority record'))
