"""MAC issuance and replay anchors outside all run trees and worker mounts.

The OS sandbox is the security boundary. File permissions do not isolate another
unconfined process with the operator's uid; the receipt explicitly records that risk.
No environment variable selects the issuer, and reads never create a key.
"""
from copy import deepcopy
import hashlib
import hmac
import json
import os
from pathlib import Path
import pwd
import secrets
import stat

from . import common


def home():
    """The issuer's private state directory for this user.

    The password database fixes it, so no environment value relocates it. A process inside a
    marked test lock domain (``machine_lease``) uses that domain instead, as the operator's
    controller home does, so test runs never write issuer records into the user's real home.
    """
    from ravel.workflow import machine_lease
    path, kind = machine_lease._resolve()
    if kind == 'test':
        return Path(path) / 'ravel-authority'
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / '.local/state/ravel-authority'


def _safe(path, *, directory=False):
    path = Path(path)
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise common.AuthorityRefused('issuer paths cannot contain symbolic links')
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise common.AuthorityRefused('issuer state must be private to the operator uid')
    if directory != stat.S_ISDIR(info.st_mode):
        raise common.AuthorityRefused('issuer state has the wrong file type')


def initialize():
    """Called only by operator init, before any configuration or run record is issued."""
    from .operator import _refuse_agent, private_dir
    _refuse_agent('ravel operator init')
    private_dir(home())
    path = home() / 'issuer.key'
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, secrets.token_bytes(32))
            os.fsync(fd)
        finally:
            os.close(fd)
    _key()


def _key():
    try:
        _safe(home(), directory=True)
        path = home() / 'issuer.key'
        _safe(path)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise common.AuthorityRefused('issuer key must be a private regular file')
            value = os.read(fd, 33)
        finally:
            os.close(fd)
        if len(value) != 32:
            raise common.AuthorityRefused('invalid issuer key')
        return value
    except OSError as exc:
        raise common.AuthorityRefused('operator issuer unavailable; run `ravel operator init` outside workers') from exc


def seal(body, context):
    body = deepcopy(body)
    if 'issuer' in body:
        raise common.AuthorityRefused('cannot issue a record with caller-supplied issuer evidence')
    key = _key()
    body['issuer'] = {'algorithm': 'hmac-sha256', 'key_id': hashlib.sha256(key).hexdigest(),
                      'mac': hmac.new(key, common.canonical([context, body]).encode(), hashlib.sha256).hexdigest()}
    return body


def authenticate(body, context):
    if not isinstance(body, dict):
        raise common.AuthorityRefused('issuer record is not an object')
    evidence = body.get('issuer')
    bare = {k: v for k, v in body.items() if k != 'issuer'}
    expected = seal(bare, context)['issuer']
    if (type(evidence) is not dict or set(evidence) != set(expected)
            or any(type(evidence[k]) is not str or not hmac.compare_digest(evidence[k], expected[k])
                   for k in expected)):
        raise common.AuthorityRefused('authority issuer authentication failed')


def context(store, kind):
    root = store.path().resolve()
    protected = home().resolve()
    if root == protected or root in protected.parents or protected in root.parents:
        raise common.AuthorityRefused('issuer state must be outside the run store')
    return {'store': str(root), 'run_id': common.run_id(store), 'kind': kind}


def journal_path(context):
    return home() / ('records-' + common.digest(context) + '.json')


def journal(context):
    path = journal_path(context)
    if not path.exists():
        _key()  # missing anchor must not bypass key availability
        return []
    _safe(path)
    value = json.loads(path.read_text())
    authenticate(value, ['journal', context])
    return value['entries']


def anchor(context, entries):
    path = journal_path(context)
    # Explicit private file mode even under a permissive umask.
    value = seal({'entries': entries}, ['journal', context])
    temporary = path.with_name(path.name + '.' + secrets.token_hex(8))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(common.canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def require_confined_spec(spec):
    """P05 pre-launch check: no mount may expose the issuer or any ancestor of it."""
    protected = home().resolve()
    if spec.get('backend') not in ('bwrap', 'sandbox-exec', 'oci-local'):
        raise common.AuthorityRefused('authority secrets require a confined launch')
    for entry in [*spec.get('reads', []), *spec.get('writes', [])]:
        path = Path(entry).resolve()
        if path == protected or path in protected.parents or protected in path.parents:
            raise common.AuthorityRefused('a worker mount exposes the operator issuer')
    return str(protected)


def receipt():
    return {'issuer_authentication': 'hmac-sha256', 'key_location': 'operator-only; outside run stores',
            'confinement_required': True, 'terminal_identity_attested': False,
            'same_user_risk': 'An unconfined process with the operator uid can read the key and issue authority. '
                              'Isolation from that attacker requires a separate OS identity or external issuer.',
            'confinement_qualification': 'requires the confined-launch owner denial probe'}
