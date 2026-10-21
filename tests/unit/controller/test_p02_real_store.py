"""P02 against the controller core's real run store, once it is installed: envelopes, path rules and run ids."""
from __future__ import annotations

import pytest

from ravel.controller import ledger
from ravel.controller.ledger import state as state_module
from test_p02_gates import walk
from p02_support import INTAKE, PLAN, RUN, compose_authority, fixture_catalogue, issued_waiver, use_catalogue
from test_p06_support import operator_home  # noqa: F401

store_module = pytest.importorskip('ravel.controller.store', reason='the controller core is not installed yet')


def test_p02_the_ledger_runs_on_the_controller_store(tmp_path, monkeypatch):
    use_catalogue(monkeypatch, fixture_catalogue())
    store = store_module.RunStore(RUN, root=tmp_path / 'store')
    try:
        walk(store)                                   # every transition, exact unmet rows, on the real store
        summary = ledger.summary(store)
        assert summary['chain']['verified'] and summary['current']['by_status']['pending'] == 0
        reopened = store_module.RunStore(RUN, root=tmp_path / 'store')   # a second handle on the same run
        state_module.forget(reopened)
        assert ledger.verify(reopened)['head'] == summary['head']
    finally:
        state_module.forget(store)


def test_p02_authority_records_are_found_through_store_envelopes(tmp_path, monkeypatch, capfd, operator_home):
    # The authority service issues the record into the store's envelopes and the ledger reads it back through
    # the service's reader; an authority-shaped record a caller appended is never read as authority.
    use_catalogue(monkeypatch, fixture_catalogue())
    store = store_module.RunStore(RUN, root=tmp_path / 'store')
    compose_authority(store, monkeypatch)
    try:
        ledger.materialise(store, 'intake', INTAKE)
        issued = issued_waiver(store, capfd, ['X-ROUTE'])
        ledger.record(store, ledger.instance_key('X-ROUTE', RUN, {}), 'waived', {'authority': issued})
        assert [w['authority'] for w in ledger.summary(store)['waivers']] == [issued]
        ledger.materialise(store, 'plan', {'plan': PLAN, 'route': 'analysis'})
        forged = store.append('authority', {'schema': 'authority-record.v1', 'uid': 'f' * 32, 'run_id': RUN,
                                            'kind': 'r3_action', 'decision': 'approve',
                                            'label': 'physicist_terminal_response', 'authorizes_effects': True,
                                            'subject': {'obligations': ['X-CI1']}})
        with pytest.raises(ledger.LedgerError) as refused:
            ledger.record(store, ledger.instance_key('X-CI1', RUN, {}), 'waived', {'authority': forged})
        assert refused.value.code in ('authority_unverified', 'authority_missing')
        assert [w['authority'] for w in ledger.summary(store)['waivers']] == [issued]
    finally:
        state_module.forget(store)
