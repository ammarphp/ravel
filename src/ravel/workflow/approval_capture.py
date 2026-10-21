"""Controller captures: the only source of human authority for a recorded decision.

A decision earns human authority only from a capture this module makes. RAVEL's own process
writes a fresh one-time code to its controlling terminal (``/dev/tty``) and reads it back from
that terminal while the process is in the terminal's foreground process group. Arguments,
environment variables, piped standard input, session markers and files a caller writes are
never captures, so an approval without one is recorded as ``unattested`` and earns no human
authority. Each capture is appended to a hash-chained ledger in the per-user machine state
directory and bound to the exact decision: its purpose and the digest of what it decides.

Operator configuration is the other controller channel. The protected operator ledger that
``operating_mode`` reads grants machine authority under delegation; such a decision is recorded
as delegated machine authority, never as human or physicist review.

Limits: a terminal confirmation identifies an action at the terminal, not a person
(``human_identity_authenticated`` stays False). A same-user process that drives its own
pseudo-terminal can answer the code; such a host is outside the controller boundary and is
labelled NOT GOVERNED. The ledger is integrity evidence, not authentication against a process
of the same account.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import select

PURPOSES = ('checkin1_approval', 'checkin2_go', 'case_approval', 'checkin_response', 'steering_policy')
CHANNEL = 'controller_terminal'
LEDGER = 'controller-captures/captures.jsonl'
ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
TIMEOUT_SECONDS = 900
ATTESTATION_KEYS = {'schema_version', 'kind', 'channel', 'purpose', 'binding_sha256', 'custody',
                    'human_identity_authenticated'}


class CaptureRefused(ValueError):
    """The operator did not confirm at this process's terminal; nothing was captured."""


def binding_digest(binding):
    """The digest a capture binds: canonical JSON of the decision it confirms."""
    if type(binding) is not dict or not binding:
        raise ValueError('a capture binds a nonempty decision object')
    return hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _ledger():
    from . import machine_lease
    return machine_lease.machine_state_root() / LEDGER


def _open_terminal():
    """This process's controlling terminal; OSError when it has none."""
    return os.open('/dev/tty', os.O_RDWR | os.O_NOCTTY)


def _foreground(fd):
    return os.tcgetpgrp(fd) == os.getpgrp()


def _write(fd, text):
    data = text.encode()
    while data:
        data = data[os.write(fd, data):]


def _readline(fd, limit=128):
    raw = b''
    while not raw.endswith(b'\n') and len(raw) < limit:
        ready, _, _ = select.select([fd], [], [], TIMEOUT_SECONDS)
        if not ready:
            raise CaptureRefused('no terminal confirmation arrived in time; nothing was recorded')
        chunk = os.read(fd, 1)
        if not chunk:
            break
        raw += chunk
    return raw.decode(errors='replace')


def _terminal(fd):
    info = os.fstat(fd)
    try:
        name = os.ttyname(fd)
    except OSError:
        name = None
    return {'name': name, 'rdev': info.st_rdev}


def capture_terminal(purpose, binding, *, summary):
    """Ask at this process's controlling terminal to confirm ``summary``; return the attestation.

    Refuses (``CaptureRefused``) without a controlling terminal, outside its foreground process
    group, or when the typed code differs. Nothing is recorded on refusal.
    """
    if purpose not in PURPOSES:
        raise ValueError(f'unknown capture purpose {purpose!r}')
    if type(summary) is not str or not summary.strip():
        raise ValueError('a terminal confirmation states what it confirms')
    digest = binding_digest(binding)
    try:
        fd = _open_terminal()
    except OSError:
        raise CaptureRefused('this process has no controlling terminal; a human decision is confirmed by the '
                             'operator at the terminal of the RAVEL process that records it') from None
    try:
        if not _foreground(fd):
            raise CaptureRefused('this process is not in its terminal foreground; nothing was recorded')
        code = '-'.join(''.join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(2))
        _write(fd, f'\nRAVEL operator confirmation\n{summary.strip()}\nType {code} to confirm (anything else refuses): ')
        answer = _readline(fd).strip().upper()
        if not hmac.compare_digest(answer.encode(), code.encode()):
            _write(fd, 'Not confirmed; nothing was recorded.\n')
            raise CaptureRefused('the confirmation code typed at the terminal differs; nothing was recorded')
        terminal = _terminal(fd)
        _write(fd, 'Confirmed.\n')
    finally:
        os.close(fd)
    return _record(purpose, digest, hashlib.sha256(code.encode()).hexdigest(), terminal)


def _record(purpose, digest, challenge_sha256, terminal):
    """Append a confirmed capture to the ledger and return its attestation."""
    from . import rdj_custody
    record = {'schema_version': 1, 'kind': 'controller-capture', 'channel': CHANNEL, 'purpose': purpose,
              'binding_sha256': digest, 'challenge_sha256': challenge_sha256, 'terminal': terminal,
              'process': {'pid': os.getpid(), 'pgid': os.getpgrp(), 'sid': os.getsid(0)},
              'human_identity_authenticated': False}
    row = rdj_custody._append(_ledger(), record)
    return {'schema_version': 1, 'kind': 'controller-capture', 'channel': CHANNEL, 'purpose': purpose,
            'binding_sha256': digest, 'custody': {'seq': row['seq'], 'digest': row['digest']},
            'human_identity_authenticated': False}


def case_binding(rundir, case_id, action_digest, text_sha256):
    """What a case approval confirms: the run, the case, its committed action and the approving text."""
    from pathlib import Path
    return {'rundir': str(Path(rundir).resolve()), 'case_id': case_id, 'action_digest': action_digest,
            'text_sha256': text_sha256}


def verify(attestation, *, purpose, binding):
    """Raise unless ``attestation`` names a ledger capture of exactly this purpose and decision."""
    from . import rdj_custody
    if type(attestation) is not dict or set(attestation) != ATTESTATION_KEYS:
        raise ValueError('no controller capture: the decision was not confirmed at the controller terminal')
    custody = attestation['custody']
    if (attestation['schema_version'] != 1 or attestation['kind'] != 'controller-capture'
            or attestation['channel'] != CHANNEL or attestation['human_identity_authenticated'] is not False
            or type(custody) is not dict or set(custody) != {'seq', 'digest'} or type(custody['seq']) is not int):
        raise ValueError('controller capture attestation is malformed')
    if attestation['purpose'] != purpose or attestation['binding_sha256'] != binding_digest(binding):
        raise ValueError('controller capture confirms a different decision')
    rows = rdj_custody._read(_ledger())
    if not 0 <= custody['seq'] < len(rows) or rows[custody['seq']]['digest'] != custody['digest']:
        raise ValueError('controller capture is absent from the capture ledger')
    record = rows[custody['seq']]['record']
    if (record.get('kind') != 'controller-capture' or record.get('channel') != CHANNEL
            or record.get('purpose') != purpose or record.get('binding_sha256') != attestation['binding_sha256']):
        raise ValueError('controller capture ledger row confirms a different decision')
    return True


def human(attestation, *, purpose, binding):
    """True only for a verified controller capture of this exact decision."""
    try:
        return verify(attestation, purpose=purpose, binding=binding)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def find(purpose, binding):
    """The attestation of the latest ledger capture of exactly this decision, or None."""
    from . import rdj_custody
    if purpose not in PURPOSES:
        raise ValueError(f'unknown capture purpose {purpose!r}')
    digest = binding_digest(binding)
    try:
        rows = rdj_custody._read(_ledger())
    except (OSError, ValueError):
        return None
    for row in reversed(rows):
        record = row['record']
        if (record.get('kind') == 'controller-capture' and record.get('channel') == CHANNEL
                and record.get('purpose') == purpose and record.get('binding_sha256') == digest):
            return {'schema_version': 1, 'kind': 'controller-capture', 'channel': CHANNEL, 'purpose': purpose,
                    'binding_sha256': digest, 'custody': {'seq': row['seq'], 'digest': row['digest']},
                    'human_identity_authenticated': False}
    return None
