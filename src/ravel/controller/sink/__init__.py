"""The sole sink of a controller run: the only path by which its results are delivered.

Only the sink delivers. It enumerates the bytes actually present in the run directory (never a
worker's list), fixes the delivered population from the approved plan and the store's custody
records, traces every table and figure number to an accepted artifact and labels unmatched prose
numbers, compares the delivered statistic and fidelity with the intake pins, validates claim
packages, runs the route packages' delivery checks, renders every label itself (``NOT GOVERNED``
and the other host governance findings, ``INDEPENDENT REVIEW INCOMPLETE``, ``UNCONFINED
EXECUTION``, ``QUALIFIED ENDING``, the review family labels, unknown usage, the engagement labels
and every labelled violation), records each delivery obligation in the ledger, takes the delivery
decisions through it, and computes the architecture receipt from controller evidence, deriving
``architecture_complete``. A bounded ending is a qualified delivery that states every obligation's
status, renders the routes' ending records, delivers only route-selected artifacts it verified
again (labelled ``QUALIFIED ARTIFACT``) and adopts no claim.

Binding interface of the controller packages::

    deliver(store, plan) -> dict          # delivery receipt, with the store record ``id``
    bounded_end(store, reason) -> dict    # qualified delivery receipt; never raises
    receipt(store) -> dict                # the latest receipt, its delivered bytes checked again
    trace_presentation(store, plan) -> dict  # Tier A tracing of the final presentation, before acceptance (read only)

Additions: ``deliver(..., results_file=...)`` (a trusted-side results file, filled only for an
accepted delivery), ``observe(run_dir)`` (the read-only receipt of a controller-owned run
directory), ``refuse_controller_owned(path, writer)`` and ``stage(name)`` (legacy writers refuse
controller-owned runs unless the sink runs them), ``SinkRefused`` and the label constants.
"""
from __future__ import annotations

from .common import (CUSTODY_BOUNDARY, DELIVERY_DIR, DELIVERY_LABELS, DIAGNOSTIC, ENGAGEMENT_UNKNOWN,
                     GOVERNANCE_UNKNOWN, HOST_FINDINGS, NOT_GOVERNED, QUALIFIED, QUALIFIED_ARTIFACT, QUALIFIED_DELIVERY,
                     REVIEW_INCOMPLETE, UNCONFINED, UNVERIFIED, USAGE_UNKNOWN, SinkRefused)
from .deliver import bounded_end, deliver, observe, observe_store, receipt, trace_presentation
from .legacy import owner, refuse_controller_owned, stage

__all__ = ['CUSTODY_BOUNDARY', 'DELIVERY_DIR', 'DELIVERY_LABELS', 'DIAGNOSTIC', 'ENGAGEMENT_UNKNOWN',
           'GOVERNANCE_UNKNOWN', 'HOST_FINDINGS', 'NOT_GOVERNED', 'QUALIFIED', 'QUALIFIED_ARTIFACT',
           'QUALIFIED_DELIVERY', 'REVIEW_INCOMPLETE', 'UNCONFINED', 'UNVERIFIED', 'USAGE_UNKNOWN', 'SinkRefused',
           'bounded_end', 'deliver', 'observe', 'observe_store', 'owner', 'receipt', 'refuse_controller_owned', 'stage',
           'trace_presentation']
