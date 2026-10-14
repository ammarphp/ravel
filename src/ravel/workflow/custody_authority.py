"""Who produced a run file, read from custody: the authority seam for decision controls.

A sha256 pin proves that bytes are unchanged. It does not prove who produced them, or that
they were approved. A decision control that treats a run file as authoritative asks this
module for the custody record that vouches for the exact bytes:

- ``stage_output``: an output listed, with this sha256, in a stage receipt that the stage
  supervisor registered and that is still current, produced by a recognized RAVEL module or
  native tool. An authored script, a model call or an unregistered stage is refused.
- ``registered_check``: a check result the check runner registered at this path and sha256.
- ``acquisition``: an input file the operator path fetched or the user uploaded.
- ``approved_checkin1``: the CHECK-IN 1 document whose live approval verifies.

Each function reads the existing ``rdj_custody``, ``rdj_anchor`` and approval records; this
module keeps no store of its own. A file the agent wrote inside the run is never authority.
Custody lives outside the run, but a process running as the same OS user can still write it;
separating the agent at the OS level is the worker sandbox's job.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

TOOL_PRODUCERS = ('module', 'native')


class AuthorityError(ValueError):
    """The file has no custody record that vouches for its exact bytes."""


def run_relative(rundir, value):
    """The run-relative POSIX name of a path inside the run, or None outside it.

    Both the run root and the path are resolved, so a symlinked or ``/tmp`` versus
    ``/private/tmp`` spelling of the same run gives the same name."""
    root = Path(rundir).resolve()
    raw = Path(value)
    path = (raw if raw.is_absolute() else root / raw).resolve()
    return path.relative_to(root).as_posix() if path.is_relative_to(root) and path != root else None


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage_output(rundir, receipt_id, rel, sha256, *, producers=TOOL_PRODUCERS, checked=False):
    """``{receipt_id, producer, path, sha256}`` when ``rel`` with ``sha256`` is a current output of
    the registered stage receipt ``stage:<name>:<attempt_id>`` from a recognized producer.
    ``checked``: the caller already hashed the current bytes, so they are not read again."""
    from . import rdj_anchor
    try:
        path, rel = rdj_anchor.inside(rundir, rel)
        record = rdj_anchor.stage_receipt(rundir, receipt_id)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise AuthorityError(f'{rel}: stage receipt {receipt_id} is not a registered, current receipt: {exc}') from None
    if not checked and _sha(path) != sha256:
        raise AuthorityError(f'{rel} differs from its pinned sha256')
    listed = False
    for key, entry in (record.get('output_snapshot') or {}).items():
        for row in entry.get('files', ()):
            candidate = Path(key) if row['name'] == '.' else Path(key) / row['name']
            if candidate.resolve() == path and row['sha256'] == sha256:
                listed = True
    if not listed:
        raise AuthorityError(f'stage receipt {receipt_id} does not list {rel} with this sha256')
    made_by = rdj_anchor.producer(rundir, record)
    if made_by is None or made_by[0] not in producers:
        raise AuthorityError(f'{rel} was not produced by a recognized RAVEL module or native tool')
    return {'receipt_id': receipt_id, 'producer': list(made_by), 'path': rel, 'sha256': sha256}


def registered_check(rundir, rel, sha256, check_id, *, producers=None):
    """The check-result value the check runner registered at ``rel`` with ``sha256`` under ``check_id``."""
    from . import rdj_custody
    found = None
    try:
        for row in rdj_custody.rows(rundir, 'checks'):
            record = row['record']
            if record['path'] == rel and record['sha256'] == sha256 and record['check_id'] == check_id:
                found = record
    except (OSError, ValueError) as exc:
        raise AuthorityError(f'check custody unreadable: {exc}') from None
    if found is None:
        raise AuthorityError(f'{rel} is not a registered {check_id} check result')
    path = Path(rundir).resolve() / rel
    if path.is_symlink() or not path.is_file() or _sha(path) != sha256:
        raise AuthorityError(f'check result {rel} differs from its registration')
    value = json.loads(path.read_text(encoding='utf-8'))
    if producers is not None and value.get('producer') not in producers:
        raise AuthorityError(f'check result {rel} comes from an unrecognized producer')
    return value


def acquisition(rundir, rel, sha256, *, checked=False):
    """The acquisition record (operator fetch or user upload) of exactly these bytes."""
    from . import rdj_custody
    try:
        rows = rdj_custody.rows(rundir, 'acquisitions')
    except (OSError, ValueError) as exc:
        raise AuthorityError(f'acquisition custody unreadable: {exc}') from None
    found = next((r['record'] for r in reversed(rows)
                  if r['record']['path'] == rel and r['record']['sha256'] == sha256), None)
    path = Path(rundir).resolve() / rel
    if found is None or path.is_symlink() or not path.is_file() or (not checked and _sha(path) != sha256):
        raise AuthorityError(f'{rel} is not a registered acquisition with these bytes')
    return found


def approved_checkin1(rundir):
    """The CHECK-IN 1 document whose live approval verifies, or raises."""
    from . import workflow_state
    errors = workflow_state.verify_approval(str(rundir))
    if errors:
        raise AuthorityError('CHECK-IN 1 approval does not verify: ' + '; '.join(errors))
    path = Path(rundir) / 'inputs/checkin1.json'
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise AuthorityError(f'approved CHECK-IN 1 unreadable: {exc}') from None
    if not isinstance(value, dict):
        raise AuthorityError('approved CHECK-IN 1 is not an object')
    return value
