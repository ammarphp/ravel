"""Explicit controller admission policy and receipt evidence for integrator call sites.

These helpers never consult environment selectors for restricted sources or export ceilings.
A restricted-source pin identifies outside bytes; replacing or relocating those bytes refuses.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

from ravel.workflow.broker import ordinary
from ravel.workflow.state_io import file_lock

from . import identity, runs
from .launcher import UNCONFINED, UNCONFINED_LABEL

SOURCE_KIND = 'restricted-source-policy'
MAX_SOURCE_BYTES = 8 * 1024 * 1024


class SourcePolicyRefused(ValueError):
    """Missing, changed or invalid operator source policy; admission stays held."""


def _rows(store, kind):
    records = []
    for row in store.scan(kind):
        if not isinstance(row, dict):
            raise SourcePolicyRefused(f'{kind} store entry must be an object')
        record = row.get('record', row)
        if not isinstance(record, dict):
            raise SourcePolicyRefused(f'{kind} store record must be an object')
        records.append(record)
    return records


def _unique(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise SourcePolicyRefused('restricted-source policy has duplicate JSON keys')
        result[name] = value
    return result


def _validate_sources(raw):
    # This is the format consumed by check_generality._external_entries: a
    # restricted-sources object with fingerprints and/or SHA256 document records.
    from ravel.validation.check_generality import SHA, _compact
    try:
        document = json.loads(raw, object_pairs_hook=_unique)
    except (UnicodeError, ValueError) as exc:
        raise SourcePolicyRefused('restricted-source policy must be valid JSON') from exc
    if not isinstance(document, dict) or document.get('kind') != 'restricted-sources':
        raise SourcePolicyRefused('restricted-source policy must be a restricted-sources object')
    terms, documents = document.get('fingerprints', []), document.get('documents', [])
    if (not isinstance(terms, list) or any(not isinstance(term, str) for term in terms)
            or not isinstance(documents, list) or any(not isinstance(item, dict)
                or not isinstance(item.get('sha256'), str) or not SHA.fullmatch(item['sha256'].lower())
                for item in documents)):
        raise SourcePolicyRefused('restricted-source policy has invalid fingerprints or documents')
    useful_terms = [term for term in terms if term.strip() and not term.strip().startswith('#')
                    and len(_compact(term.strip())) >= 3]
    if not useful_terms and not documents:
        raise SourcePolicyRefused('restricted-source policy must name at least one effective restriction')


def _read_sources(store, path, run_dir=None):
    if not isinstance(path, (str, Path)) or not Path(path).is_absolute():
        raise SourcePolicyRefused('operator restricted_sources must name an absolute file')
    try:
        path = ordinary(path)
        package = Path(__file__).resolve().parents[2]
        protected = [ordinary(store.path()), package]
        checkout = identity._checkout(package)
        if checkout is not None:
            protected.append(checkout)
        if run_dir is not None:
            protected.append(ordinary(run_dir))
        if any(path.is_relative_to(root) for root in protected):
            raise SourcePolicyRefused('restricted-source policy must be outside store, package, checkout and run')
        before = path.stat()
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            opened = os.fstat(fd)
            if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                    or not 0 < opened.st_size <= MAX_SOURCE_BYTES):
                raise SourcePolicyRefused('restricted-source policy must be a bounded nonempty regular file without links')
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                raw = stream.read(MAX_SOURCE_BYTES + 1)
            after = os.fstat(fd)
        finally:
            os.close(fd)
        def stamp(value):
            return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
                    value.st_ctime_ns, value.st_mode, value.st_nlink)
        if (len(raw) != opened.st_size or any(stamp(value) != stamp(opened)
                for value in (before, after, path.stat())) or ordinary(path) != path):
            raise SourcePolicyRefused('restricted-source policy changed during its read')
    except (OSError, ValueError) as exc:
        if isinstance(exc, SourcePolicyRefused):
            raise
        raise SourcePolicyRefused('restricted-source policy is missing, linked or unreadable') from exc
    _validate_sources(raw)
    return {'schema_version': 1, 'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}, raw


def _source_pin(store, path, run_dir=None):
    return _read_sources(store, path, run_dir)[0]


def freeze_sources(store, path, *, run_dir=None):
    """Append the one immutable operator policy pin; identical repeated admission is idempotent."""
    with file_lock(store.path('restricted-source-policy.lock')):
        pin = _source_pin(store, path, run_dir)
        existing = _rows(store, SOURCE_KIND)
        if existing:
            if len(existing) != 1 or existing[0] != pin:
                raise SourcePolicyRefused('restricted-source policy is already pinned differently')
            return existing[0]
        store.append(SOURCE_KIND, pin)
        return pin


def _owned_sources(run_path):
    owned = runs.owner_of(Path(run_path))
    if owned is None:
        return None
    run_id, run_dir = owned
    store = runs.store(run_id)
    pins = _rows(store, SOURCE_KIND)
    if len(pins) != 1:
        raise SourcePolicyRefused('controller run requires exactly one restricted-source policy pin')
    pin = pins[0]
    current, raw = _read_sources(store, pin.get('path'), run_dir)
    if current != pin:
        raise SourcePolicyRefused('restricted-source policy bytes differ from the admission pin')
    return pin, raw


def restricted_sources(run_path):
    """Pinned source path for an owned run, None for a legacy run; no environment fallback."""
    found = _owned_sources(run_path)
    return found[0]['path'] if found is not None else None


def restricted_source_document(run_path):
    """Parse the exact bytes checked against the admission pin, without reopening the file."""
    found = _owned_sources(run_path)
    return json.loads(found[1]) if found is not None else None


def export_ceiling(run_path, default):
    """The owned run's operator export ceiling; None lets an unowned caller use its legacy route."""
    if runs.owner_of(Path(run_path)) is None:
        return None
    settings = runs.operator_settings()
    value = settings.get('procedure_byte_ceiling', default)
    if type(value) is not int or value < 0:
        raise ValueError('operator procedure_byte_ceiling must be a nonnegative integer')
    return value


def admission(store, *, development=False, run_dir=None):
    """Record code identity and pin mandatory operator policy, including in development mode."""
    admitted = dict(identity.require_governed_install(development=development))
    if development:
        admitted.update(label=identity.NOT_GOVERNED, governed=False)
    from ..execution_manifest import check_admission
    check_admission(store, admitted)
    store.append('code-identity', admitted)
    freeze_sources(store, runs.operator_settings().get('restricted_sources'), run_dir=run_dir)
    return admitted


def receipt_evidence(store):
    """Carry evidence and incomplete-architecture labels forward; never manufacture acceptance."""
    labels = set()
    for row in _rows(store, 'code-identity'):
        record = row.get('identity', row)
        if not isinstance(record, dict):
            raise ValueError('code identity evidence must be an object')
        if isinstance(record.get('label'), str) and record['label']:
            labels.add(record['label'])
        if record.get('governed') is False:
            labels.add(identity.NOT_GOVERNED)
    for record in _rows(store, 'confinement-launch'):
        nested = record.get('confinement')
        details = nested if isinstance(nested, dict) else record
        if (details.get('kind') == UNCONFINED or details.get('class') == UNCONFINED
                or record.get('unconfined') is True or nested == UNCONFINED
                or details.get('label_text') == UNCONFINED_LABEL):
            labels.add(UNCONFINED_LABEL)
    evidence = {'labels': sorted(labels), 'tool_inventory': _rows(store, 'tool-inventory')}
    if labels:
        evidence['architecture_complete'] = False
    return evidence
