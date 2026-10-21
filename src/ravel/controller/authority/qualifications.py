"""Operator-run transport qualifications that every later controller run adopts at intake.

A controller run counts a CLI worker's live qualification only from its own protected store (SW09). An
unattended run started by ``ravel drive --unattended`` cannot be qualified into before it exists, so the
operator qualifies once, from their own terminal, with ``ravel transport qualify <id> --rundir <empty dir>
--model <model> --for-operator``. The passed record is appended to a hash-chained file in the operator area
of the controller home, MACed by the operator's issuer key exactly as the operator ledger is, and its digest
is registered in the operator's qualification register.

At intake (``entry.start``) the controller adopts each such record into the new run's store as a
``transport-qualification`` record, with an adoption record naming its provenance (the operator-area row
and the record digest), only while the record authenticates, is still registered, and still matches the
current declaration digest and the current executable sha256 (the probe digest is matched again at seat
selection against the current probe). Nothing is ever
adopted from the run tree or from the worker state directory. A run whose configured transport has no
adoptable qualification holds at seat selection with the operator's remedy.
"""
from __future__ import annotations

from copy import deepcopy

from . import common

RECORDS = 'operator/transport-qualifications.records.jsonl'
REGISTER = 'operator/transport-qualifications.jsonl'
ADOPTION = 'transport-qualification-adoption'
REMEDY = 'ravel transport qualify {transport} --rundir <empty dir> --model <model> --for-operator'


def _paths():
    from .operator import controller_home
    home = controller_home()
    return home / RECORDS, home / REGISTER


def _context(path):
    return ['operator-qualification', str(path.resolve())]


def rows():
    """Every operator-area qualification row, authenticated against the issuer key and its append anchor."""
    from ravel.workflow import rdj_custody
    from . import issuer
    path, _ = _paths()
    if path.is_symlink():
        raise common.AuthorityRefused('the operator qualification records must not be a symbolic link')
    try:
        found = rdj_custody._read(path)
    except rdj_custody.CustodyError as exc:
        raise common.AuthorityRefused(f'the operator qualification records do not verify: {exc}') from None
    if not found:
        return []
    context = _context(path)
    for row in found:
        issuer.authenticate(row['record'], context)
    anchors = issuer.journal(context)
    if [common.digest(row) for row in found] != [a['sha256'] for a in anchors]:
        raise common.AuthorityRefused('operator qualification records differ from issuer history')
    return found


def record(qualification):
    """Retain a passed live qualification in the operator area and register its digest (operator only)."""
    import os
    from ravel.workflow import rdj_custody, transport_registry as tr
    from ravel.workflow.state_io import file_lock
    from . import issuer
    from .operator import _refuse_agent, private_dir
    _refuse_agent('ravel transport qualify --for-operator')
    if not tr._store_qualification_valid(qualification):
        raise ValueError('only a passed live qualification record is retained for the operator')
    path, register = _paths()
    private_dir(path.parent)
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
    context = _context(path)
    sealed = issuer.seal({'schema_version': 1, 'kind': 'operator-transport-qualification',
                          'qualification': deepcopy(qualification), 'record_sha256': tr.digest(qualification),
                          'operator_uid': os.getuid()}, context)
    with file_lock(issuer.journal_path(context).with_suffix('.lock')):
        existing = rows()
        row = rdj_custody._append(path, sealed)
        issuer.anchor(context, [{'sha256': common.digest(r)} for r in [*existing, row]])
    os.chmod(path, 0o600)
    tr.register_qualification(qualification, register)
    return {'row': row['digest'], 'seq': row['seq'], 'record_sha256': tr.digest(qualification)}


def adoptable(transport_id=None):
    """``[(row, qualification)]`` the controller may adopt now: authenticated, registered and current."""
    from ravel.workflow import transport_registry as tr
    _, register = _paths()
    registered = tr.registered_qualifications(register)
    found = []
    for row in rows():
        qualification = row['record'].get('qualification')
        sha = tr.digest(qualification) if type(qualification) is dict else None
        if sha is None or sha not in registered or row['record'].get('record_sha256') != sha:
            continue
        if transport_id is not None and qualification.get('transport_id') != transport_id:
            continue
        try:
            document = tr.load(qualification['transport_id'])
            executable_sha = (tr.loop_identity(document)['executable_sha256']
                              if document['transport_kind'] == 'ravel-loop'
                              else tr.resolve_executable(document)[1])
        except (KeyError, OSError, ValueError, TypeError):
            continue
        # The declaration and the executable as they are now; the probe digest is matched again at seat selection
        # against a fresh probe (``read_qualification``), never against a probe file in worker state.
        if (executable_sha != qualification.get('executable_sha256')
                or tr.declaration_sha256(document) != qualification.get('declaration_sha256')):
            continue
        found.append((row, qualification))
    return found


def adopt(store):
    """Adopt every current operator qualification into the run's store once; returns the adoption records."""
    from ravel.workflow import transport_registry as tr
    try:
        candidates = adoptable()
    except common.AuthorityRefused as exc:
        store.append(ADOPTION, {'schema_version': 1, 'status': 'refused', 'reason': str(exc)[:500]})
        return []
    present = set(tr.store_qualifications(store))
    adopted = []
    for row, qualification in candidates:
        sha = tr.digest(qualification)
        if sha in present:
            continue
        stored = tr.record_qualification(store, deepcopy(qualification))
        adopted.append({'schema_version': 1, 'status': 'adopted', 'transport_id': qualification['transport_id'],
                        'record_sha256': sha, 'store_record': stored,
                        'provenance': {'source': 'operator_area', 'row_digest': row['digest'], 'row_seq': row['seq']}})
        store.append(ADOPTION, adopted[-1])
        present.add(sha)
    return adopted
