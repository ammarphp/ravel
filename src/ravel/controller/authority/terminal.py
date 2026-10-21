"""The physicist's answer, read at the controller's own controlling terminal.

``ravel drive``, started by the physicist, opens its controlling terminal (``/dev/tty``) itself.
It discards any type-ahead, shows the typed check-in rendered from run state with a fresh
per-prompt code, and reads one answer line. The response is recorded only when it quotes that code and
names an offered decision. It remains unattested and grants no effects. Workers and governed launches start in their own sessions with no
controlling terminal and no standard input, so they cannot reach this prompt; arguments,
environment variables, piped input and files are never answers.

Limits: the answer identifies an action at the controller's terminal, not a person. An automated PTY is indistinguishable from human input here; all responses remain unattested.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import select
import termios
import threading
import time

from . import common

MAX_LINE = 4096
ATTEMPTS = 3
# One prompt at a time: concurrent branches never interleave on the terminal.
_LOCK = threading.Lock()


class TerminalUnavailable(common.AuthorityRefused):
    """The controller has no usable controlling terminal; nothing was asked."""


class TerminalRefused(common.AuthorityRefused):
    """No valid answer arrived at the terminal; nothing was recorded."""


def _open_terminal():
    try:
        return os.open('/dev/tty', os.O_RDWR | os.O_NOCTTY | getattr(os, 'O_CLOEXEC', 0))
    except OSError as exc:
        raise TerminalUnavailable('the controller has no controlling terminal: interactive authority is read only '
                                  'at the terminal of the `ravel drive` process the physicist started') from exc


def _foreground(fd):
    try:
        return os.tcgetpgrp(fd) == os.getpgrp()
    except OSError:
        return False


def _write(fd, text):
    data = text.encode('utf-8', errors='replace')
    while data:
        data = data[os.write(fd, data):]


def _readline(fd, deadline):
    raw = b''
    while not raw.endswith(b'\n'):
        if len(raw) > MAX_LINE:
            raise TerminalRefused('the terminal answer is too long; nothing was recorded')
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            raise TerminalRefused('no answer arrived at the terminal within the wait bound; nothing was recorded')
        ready, _, _ = select.select([fd], [], [], remaining)
        if not ready:
            continue
        chunk = os.read(fd, 1)
        if not chunk:
            raise TerminalRefused('the terminal closed before an answer; nothing was recorded')
        raw += chunk
    return raw.decode('utf-8', errors='replace').rstrip('\r\n')


def _device(fd):
    info = os.fstat(fd)
    try:
        name = os.ttyname(fd)
    except OSError:
        name = None
    return {'name': name, 'rdev': info.st_rdev}


def footer(code, decisions):
    return (f'\nReply on one line: {code} <decision> [your text]\n'
            f'Decisions: {" | ".join(decisions)}. Anything after the decision is recorded verbatim '
            '(clarifying answers, alterations, conditions).\n> ')


def ask(text, *, decisions, timeout=None):
    """Show ``text`` at the controlling terminal and return the validated answer.

    Returns ``decision``, ``comment``, ``response_sha256``, ``prompt_sha256`` (of everything
    shown, code included), ``nonce_sha256``, ``device`` and ``attempts``. Each attempt shows a
    new code; a wrong code or an unoffered decision is re-asked, up to ``ATTEMPTS`` times.
    """
    if not decisions or any(type(d) is not str or not d for d in decisions):
        raise ValueError('a terminal question offers named decisions')
    offered = {d.lower(): d for d in decisions}
    with _LOCK:
        fd = _open_terminal()
        try:
            if not _foreground(fd):
                raise TerminalUnavailable('the controller is not in its terminal foreground; nothing was asked')
            deadline = None if timeout is None else time.monotonic() + timeout
            note = ''
            for attempt in range(1, ATTEMPTS + 1):
                code = common.nonce()
                try:
                    termios.tcflush(fd, termios.TCIFLUSH)  # discard type-ahead typed before this prompt
                except termios.error:
                    pass
                shown = note + text.rstrip('\n') + '\n' + footer(code, decisions)
                _write(fd, shown)
                line = _readline(fd, deadline)
                parts = line.strip().split(None, 2)
                if len(parts) < 2 or not hmac.compare_digest(parts[0].upper().encode(), code.encode()):
                    note = 'That answer did not start with the code shown; nothing was recorded. Asking again.\n'
                    continue
                decision = offered.get(parts[1].lower())
                if decision is None:
                    note = f'{parts[1]!r} is not an offered decision; nothing was recorded. Asking again.\n'
                    continue
                _write(fd, f'Recorded: {decision}.\n')
                return {'decision': decision, 'comment': parts[2] if len(parts) > 2 else '',
                        'response_sha256': hashlib.sha256(line.encode('utf-8')).hexdigest(),
                        'prompt_sha256': hashlib.sha256(shown.encode('utf-8')).hexdigest(),
                        'nonce_sha256': hashlib.sha256(code.encode()).hexdigest(),
                        'device': _device(fd), 'attempts': attempt,
                        'attestation': common.LEGACY_TERMINAL, 'human_identity_authenticated': False}
            _write(fd, 'No valid answer; nothing was recorded.\n')
            raise TerminalRefused('no valid answer at the terminal after repeated prompts; nothing was recorded')
        finally:
            os.close(fd)


def available():
    """Whether this process can ask at a controlling terminal in its foreground (no prompt is shown)."""
    try:
        fd = _open_terminal()
    except TerminalUnavailable:
        return False
    try:
        return _foreground(fd)
    finally:
        os.close(fd)
