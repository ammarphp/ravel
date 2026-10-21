"""Record executed mechanisms without changing the ledger's admission rules."""
from __future__ import annotations

from . import chain

GATE_RECORD = 'gate-provider-check'
MECHANISMS = frozenset({
    'authority.checkin.validate_before_presentation', 'authority.answer', 'ledger.decide.providers',
    'routes.select.first_match', 'controller.qualified_worker_host_surface',
    'controller.executed_seam_refusal', 'controller.qualified_crosscheck_review'})


def decision(store, gate, action, providers, registry_sha256):
    """Called only after the real decision and provider-evidence readers passed."""
    return store.append(GATE_RECORD, {
        'schema_version': 1, 'run_id': store.run_id, 'gate': gate,
        'action': action, 'action_sha256': chain.digest(action),
        'providers': providers, 'registry_sha256': registry_sha256, 'passed': True})


def evidence(store):
    """G02 from a passed provider check and the exact decision row it discharged."""
    verify = getattr(store, 'verify', None)
    if not callable(verify) or verify():
        return {}
    try:
        return _decision_evidence(store)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, chain.LedgerError):
        return {}


def _decision_evidence(store):
    from . import current, load_catalogue
    rows = current(store)
    catalogue = load_catalogue()
    for entry in reversed(store.scan(GATE_RECORD)):
        body = entry['record']
        if (body.get('schema_version') != 1 or body.get('run_id') != store.run_id
                or body.get('passed') is not True or not isinstance(body.get('action'), dict)
                or body.get('action_sha256') != chain.digest(body['action'])
                or body.get('registry_sha256') != catalogue.gate_registry['sha256']):
            continue
        proof = next((row for row in rows if row['id'] == 'GATE-' + body['gate']
                      and row['status'] == 'satisfied' and (row.get('evidence') or {}).get('record') == entry['id']), None)
        found = (proof or {}).get('evidence') or {}
        if (proof is None or found.get('action_sha256') != body['action_sha256']
                or found.get('providers', {}) != body.get('providers')
                or found.get('registry_sha256') != body['registry_sha256']
                or found.get('mechanism') != 'decision_gate.check'):
            continue
        return {'G02': {'status': 'satisfied', 'evidence': {
            'record': entry['id'], 'gate': body['gate'], 'decision_entry': proof['entry'],
            'registry_sha256': body['registry_sha256'], 'mechanism': 'ledger.decide.providers'}}}
    return {}


def record(store, rows, ledger, *, revalidate=False):
    """Only pending instances, exact scoped proofs where supplied; refusals stay pending."""
    if not all(callable(getattr(ledger, name, None)) for name in ('current', 'record')):
        return {'recorded': [], 'pending': []}
    recorded, pending = [], []
    for instance in ledger.current(store):
        found = rows.get(instance['entry'], rows.get(instance['id']))
        # A run-wide assertion never closes a seat or conserved deliverable.
        if '/' in instance['entry'].split('@', 1)[-1] and instance['entry'] not in rows:
            continue
        prior = instance.get('evidence') or {}
        if instance['status'] != 'pending':
            if not revalidate or prior.get('mechanism') not in MECHANISMS:
                continue
            if found is None and instance['status'] in ('satisfied', 'not_applicable'):
                found = {'status': 'violated', 'evidence': {
                    'mechanism': prior['mechanism'], 'reason': 'the enforcing record no longer verifies',
                    'label': 'UNVERIFIED MECHANISM EVIDENCE', 'previous_record': prior.get('record')}}
            elif found is not None and instance['status'] == found['status'] == 'satisfied':
                if found['evidence'] == prior:
                    continue
            else:
                continue
        if found is None:
            continue
        try:
            ledger.record(store, instance['entry'], found['status'], found['evidence'])
            recorded.append(instance['entry'])
        except ledger.LedgerError:
            pending.append(instance['entry'])
    return {'recorded': recorded, 'pending': pending}
