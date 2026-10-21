"""The run's environment profile: the host the controller plans for, observed once at intake.

``observe(store, run_dir=...)`` runs the existing doctor-census, batch, sandbox and resource probes through
``ravel.setup.environment_profile`` and appends one ``environment-profile`` record; a run that already has one
keeps it, so a resumed run plans against the host it was admitted on. The operator's saved site profile
(``ravel site init``) supplies what cannot be probed (the site's network policy, mirror, credential
requirements and scheduler) and is pinned by digest in the record. An unreadable site profile is recorded as a
probe error, never silently replaced.

Inside a test lock domain the network is not probed unless the saved site profile states a policy: an inert
test process opens no outbound connection.
"""
from __future__ import annotations

RECORD = 'environment-profile'


def _not_probed(**_):
    return {'egress': 'unknown', 'source': 'not-probed', 'checks': [], 'reason': 'test lock domain'}


def observe(store, *, run_dir=None):
    """The run's ``environment-profile`` record (``{'id', 'record'}``), observing and appending it when absent."""
    found = store.latest(RECORD)
    if found is not None:
        return found
    from ravel.setup import environment_profile as ep
    from ravel.workflow import machine_lease
    site, problem = None, None
    try:
        document, pin = ep.load_site_profile()
        site = (document, pin) if document is not None else None
    except ValueError as exc:
        problem = str(exc)[:300]
    probes = {}
    declared = ((site[0].get('network') or {}).get('policy') if site else None)
    if machine_lease.domain() == 'test' and declared in (None, 'auto'):
        probes['network'] = _not_probed
    profile = ep.observe(run_dir=run_dir, store_root=str(getattr(store, 'store_root', '') or '') or None,
                         site=site, probes=probes)
    if problem is not None:
        profile['probe_errors'].append({'probe': 'site_profile', 'error': problem})
    record_id = store.append(RECORD, profile)
    return store.read(RECORD, record_id)
