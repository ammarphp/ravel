"""An explicit inert controller for unit fixtures that model the worker dispatcher by hand.

Some fixtures write a worker receipt into the run tree and register it with the dispatcher's
label and actor, without a supervised launch. That registration alone is the former, too
lenient credit: independent credit also needs controller evidence of a separate context, a
RAVEL-built packet and confinement. The default resolver (``review_dispatch``) reads that
evidence from an actual supervised launch, which these fixtures do not perform.

A test whose fixture models a governed dispatch requests ``inert_dispatch``. The controller
vouches only for a receipt its fixture registered as transport-attested with an assigned
actor, still bound to the queried role, subject and unchanged output. It takes the context
from that registered session, the census from every other registration of the run, and
defers every other query to the default resolver. It never vouches for an unregistered,
self- or host-attested receipt, and it is never installed globally.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ravel.workflow import rdj_custody, review_dispatch, review_independence as ri

EXPOSURE = {'author_identity': 'permitted', 'author_rationale': 'withheld', 'reference_values': 'permitted',
            'peer_verdicts': 'withheld'}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _context(receipt, registration):
    actor = registration['actor']
    session = receipt.get('session_id') or actor['worker_session_id']
    if receipt.get('rdj'):
        # Every RDJ role call is its own dispatch, as on the graph route; the RDJ fixture names one
        # session per role, and RDJ's own session checks still see that shared name.
        session = '%s:%s' % (session, receipt.get('node_id') or actor['attempt_id'])
    return 'fixture-session:%s:%s' % (actor['transport_id'], session)


def controller(query):
    run = Path(query['run'])
    try:
        rows = [row['record'] for row in rdj_custody.rows(run, 'workers')]
    except (OSError, ValueError):
        rows = []
    mine = [row for row in rows if row.get('sha256') == query['receipt_sha256']]
    if not mine:
        return review_dispatch.lookup(query)
    registration = mine[-1]
    if registration.get('verified_label') != 'transport_attested' or not registration.get('actor'):
        return None
    path = run / registration['path']
    if _sha(path) != query['receipt_sha256']:
        return None
    receipt = json.loads(path.read_text())
    final = receipt.get('final_record') or {}
    subject = (receipt.get('review_subject') or {}).get('sha256') or (receipt.get('rdj') or {}).get('payload_sha256')
    if ((receipt.get('role') or {}).get('id') != query['role'] or final.get('sha256') != query['output_sha256']
            or subject != query['subject_sha256']):
        return None
    current = path.parent / str(final.get('path'))
    context = _context(receipt, registration)
    authors, others = [review_dispatch.PARENT + str(run)], []
    for row in rows:
        if row.get('sha256') == query['receipt_sha256'] or not row.get('actor'):
            continue
        try:
            other = json.loads((run / row['path']).read_text())
        except (OSError, ValueError):
            continue
        producer = (other.get('final_record') or {}).get('schema') == 'producer.v1'
        (authors if producer else others).append(_context(other, row))
    return {'binding': deepcopy(query), 'authority_boundary': 'controller_only',
            'dispatch_id': 'fixture-dispatch:' + query['receipt_sha256'], 'context_id': context,
            'author_context_ids': sorted(set(authors)), 'author_census_complete': True,
            'other_review_context_ids': sorted(set(others)), 'review_census_complete': True,
            'parent_transcript_supplied': False,
            'packet': {'builder': review_dispatch.PROJECTION, 'projection_verified': True, 'author_summary': False,
                       'sha256': ri.digest({'fixture_packet': query['subject_sha256']}),
                       'subject_sha256': query['subject_sha256']},
            'read_boundary': 'packet_only', 'read_boundary_verified': True,
            'exposure': dict(EXPOSURE), 'exposure_verified': True,
            'output_unmodified': current.is_file() and _sha(current) == query['output_sha256']}


@pytest.fixture
def inert_dispatch():
    """Install the inert controller for one test; the default resolver is restored afterwards."""
    with ri.authority_session(controller):
        yield controller
