"""Ledger evidence of the confinement admission, for the controller's recorder map (P05 imports no ledger).

``ledger_evidence(store)`` maps each intake row the admission proves to the evidence the controller
records: a pointer to the admission's ``code-identity`` record (``record``) and to the operator's
restricted-source pin (``policy_record``). The admission (``policy.admission``) proves them only when it
completed for installed or sealed, read-only code with no selector (``governed`` true) and the run holds
exactly one source-policy pin:

- SW23: ``RAVEL_ROOT``, ``RAVEL_ADDON_PATH``, ``RAVEL_NATIVE_BIN`` and the toolchain selectors redirect
  nothing the controller runs;
- SW29: the package data (gate providers, execution guard, transports) is installed or sealed and not
  writable;
- SW16: the installed launcher drops every clock override from a launch environment, so only the
  controller's clock stamps the store and the launch journal.

A development admission (labelled ``NOT GOVERNED``) or an admission that stopped before its source
pin proves none of them: those rows stay pending.
"""
from __future__ import annotations

from . import environment, identity, policy

ROWS = ('SW23', 'SW29', 'SW16')
CLOCKS = ('WORKFLOW_STATE_UTC', 'GATE_TIMESTAMP', 'RESOURCE_CENSUS_UTC', 'COST_PREFLIGHT_UTC',
          'PREFLIGHT_WATCHER_UTC')


def _entries(store, kind):
    return [row for row in store.scan(kind) if isinstance(row, dict) and isinstance(row.get('id'), str)
            and isinstance(row.get('record'), dict)]


def ledger_evidence(store):
    """``{row id: evidence}`` for the rows of ``ROWS`` the run's admission proves (empty when it proves none)."""
    identities, pins = _entries(store, 'code-identity'), _entries(store, policy.SOURCE_KIND)
    if not identities or len(pins) != 1:
        return {}
    admitted = identities[0]
    record = admitted['record']
    if (record.get('governed') is not True or record.get('label') or record.get('problems')
            or record.get('kind') not in identity.GOVERNED_KINDS or record.get('writable_by_controller_user') is not False
            or record.get('symlinks') or record.get('selectors')):
        return {}
    evidence = {'record': admitted['id'], 'policy_record': pins[0]['id'], 'mechanism': 'confine.policy.admission'}
    rows = {'SW23': dict(evidence), 'SW29': dict(evidence)}
    kept = environment.channels()
    if all(environment.forbidden(name, kept) for name in CLOCKS):
        rows['SW16'] = {**evidence, 'clocks_refused': list(CLOCKS)}
    return rows
