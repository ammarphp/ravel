"""Protected expiry observations and acknowledged renewal at credential consumption."""
from __future__ import annotations

import hashlib
import os

from .authority import autonomy


def require_proxy(store, path=None):
    from ravel.workflow.credential_status import proxy_lifetime
    if store is not None:
        from .authority.mode import frozen
        frozen(store)
    observed = proxy_lifetime(path)
    if observed['status'] == 'unknown':
        raise ValueError('credential_status_unknown: obtain a current proxy lifetime from the credential client')
    subject = 'proxy:' + hashlib.sha256(os.fsencode(path if path is not None else 'default')).hexdigest()
    latest = None
    if store is not None:
        latest = next(((when, record) for when, _, record in reversed(autonomy._scan(store, autonomy.CONDITION))
                       if record.get('code') == 'proxy_expired' and record.get('subject') == subject), None)
    if observed['status'] == 'expired':
        if store is None:
            raise ValueError('proxy_expired: renew the proxy before submission')
        if latest is None or latest[1].get('phase') != 'open':
            autonomy.report_condition(store, 'proxy_expired', subject=subject, evidence=observed)
    elif (latest is not None and latest[1].get('phase') == 'open'
          and autonomy._acknowledged_ns(store) > latest[0]):
        autonomy.report_condition(store, 'proxy_expired', phase='cleared', subject=subject, evidence=observed)
    if store is not None:
        autonomy.admit(store, 'credential-using submission')
        autonomy.settle(store)
    return observed
