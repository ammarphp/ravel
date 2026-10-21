"""Shared vocabulary of the sole sink: labels, digests, store reads and the packages it consumes.

The sink reads its evidence from the run's protected store (records the controller's own nodes
wrote) and from the actual bytes of the run directory. It consumes the obligation ledger, the
authority service and its issuer's description, confined execution, the engagement policy, the
host governance label, the review-independence decision and the route checks and ending records.
Each is imported when used, through the interpreter's module table only: an absent package is
reported as absent evidence (never as a pass), and nothing here installs a substitute.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
import json
import math
from pathlib import Path

RECEIPT_SCHEMA = 2  # the legacy run receipt is schema 1
RECEIPT_KIND = 'ravel-architecture-receipt'
STORE_RECEIPT = 'receipt'  # the controller graph and the entry summary read this store kind
STORE_ENDING = 'qualified-ending'
STORE_RESULTS = 'results-file'
ENDING_SYNTHESIS = 'ending-synthesis'  # route adapters' read-only record of unfinished work at an ending
# Store kinds the route adapters' ``ending`` hooks append before the sink's bounded ending, with the route
# that writes each (``None``: the record names its source). Pairs, read in this order.
ROUTE_ENDINGS = ((ENDING_SYNTHESIS, None), ('ml-stage-ending', 'ml.training'), ('manuscript-ending', 'manuscript'),
                 ('analysis-scan-population', 'analysis'), ('study-ending', 'study'),
                 ('study-ending-backend', 'study'), ('study-ending-remote', 'study'), ('research-ending', 'research'))
# Ending kinds that may name qualified artifacts, and the route interface that selects them again.
QUALIFYING_ENDINGS = (('manuscript-ending', 'manuscript_staged'),)
DELIVERY_TARGET = 'delivery-target'  # a trusted-side output named at intake (harness results file)
DELIVERY_DIR = 'delivery'

# Labels only the sink renders. Model prose cannot add, strip or override them.
NOT_GOVERNED = 'NOT GOVERNED'
REVIEW_INCOMPLETE = 'INDEPENDENT REVIEW INCOMPLETE'
UNCONFINED = 'UNCONFINED EXECUTION'
REVIEW_UNSANDBOXED = 'REVIEW WITHOUT OS SANDBOX (OPERATOR-CONFIGURED FALLBACK)'
QUALIFIED = 'QUALIFIED ENDING'
QUALIFIED_DELIVERY = 'QUALIFIED DELIVERY'
DIAGNOSTIC = 'DIAGNOSTIC DELIVERY'
USAGE_UNKNOWN = 'USAGE UNKNOWN'
UNVERIFIED = 'UNVERIFIED NUMBERS IN PROSE'
HOST_FINDINGS = 'HOST INTEGRITY FINDINGS'
GOVERNANCE_UNKNOWN = 'HOST GOVERNANCE UNKNOWN'
ENGAGEMENT_UNKNOWN = 'ENGAGEMENT UNKNOWN'
QUALIFIED_ARTIFACT = 'QUALIFIED ARTIFACT'
CUSTODY_BOUNDARY = 'custody boundary: same-user, sandboxed workers excluded'
DELIVERY_LABELS = ('accepted', 'qualified', 'diagnostic')

# Interface name -> module (pairs, so no mapping key reads as instruction text to the agent census).
INTERFACES = dict((
    ('store', 'ravel.controller.store'),
    ('ledger', 'ravel.controller.ledger'),
    ('authority', 'ravel.controller.authority'),
    ('issuer', 'ravel.controller.authority.issuer'),
    ('confine', 'ravel.controller.confine'),
    ('engagement', 'ravel.controller.engagement'),
    ('governance', 'ravel.workflow.host_governance'),
    ('independence', 'ravel.workflow.review_independence'),
    ('review_points', 'ravel.workflow.review_points'),
    ('fidelity', 'ravel.controller.routes.analysis.fidelity'),
    ('manuscript', 'ravel.controller.routes.manuscript'),
    ('manuscript_staged', 'ravel.controller.routes.manuscript.staged'),
    ('ml_staged', 'ravel.controller.routes.ml.staged'),
    ('claims', 'ravel.workflow.manuscript_claim_disposition'),
))
# Route delivery checks: ``delivery_errors_from_store(store, plan)`` of each installed route package, run on
# every delivery; a plan of the named route needs its check installed (an absent check is not a pass).
ROUTE_CHECKS = (('manuscript', 'manuscript', ('manuscript',)), ('ml', 'ml_staged', ('ml.training',)))

HASH_LIMIT = 64 * 1024 ** 2  # files outside adopted outputs above this size are listed, not hashed
TEXT_LIMIT = 4 * 1024 ** 2  # documents larger than this are not parsed for numbers (reported)


class SinkRefused(ValueError):
    """A delivery path refused to write; nothing was delivered by it."""


def _absent_names(target):
    parts = target.split('.')
    return {'.'.join(parts[:n]) for n in range(2, len(parts) + 1)}


def module(name):
    """The installed package for ``name``, or None when it is not installed (absent evidence)."""
    target = INTERFACES[name]
    try:
        return importlib.import_module(target)
    except ImportError as exc:
        if exc.name not in _absent_names(target):
            raise
        return None


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def plain(value, depth=0):
    """A JSON-safe copy: non-finite numbers become None, paths and foreign objects become text."""
    if depth > 200:
        return None
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): plain(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v, depth + 1) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((plain(v, depth + 1) for v in value), key=str)
    return str(value)


def records(store, kind):
    """Bodies of one store kind in append order; each carries its store ``_id``, ``_seq`` and ``_time_ns``."""
    rows = []
    for entry in store.scan(kind):
        if type(entry) is dict and type(entry.get('record')) is dict:
            body = deepcopy(entry['record'])
            body['_id'] = entry.get('id')
            body['_seq'] = entry.get('seq')
            body['_time_ns'] = entry.get('time_ns')
        else:
            body = deepcopy(entry) if type(entry) is dict else {'_malformed': True}
        rows.append(body)
    return rows


def body(row):
    """A store body without the sink's bookkeeping fields."""
    return {k: v for k, v in row.items() if not k.startswith('_')}


def run_dir(store):
    """The run directory bound to ``store`` (its first ``run`` record), or None."""
    getter = getattr(store, 'run_record', None)
    try:
        record = getter() if callable(getter) else None
    except (OSError, ValueError, KeyError):
        record = None
    if record is None:
        rows = [r for r in records(store, 'run') if r.get('run_dir')]
        record = rows[0] if rows else None
    value = (record or {}).get('run_dir')
    return Path(value) if type(value) is str and value else None


def inside(root, path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False
