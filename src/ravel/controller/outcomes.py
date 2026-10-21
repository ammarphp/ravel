"""Public work-command outcomes; process completion alone never implies delivery."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import traceback

EXIT_CODES = {'delivered_accepted': 0, 'qualified': 10, 'held': 11, 'refused': 2, 'failed': 1}


def outcome(*, delivery=None, terminal=None, run_id=None, evidence=None, error=None, code=0):
    delivery, terminal = delivery or {}, terminal or {}
    status = terminal.get('status')
    if error is not None or code:
        state = 'refused' if code == 2 else 'failed'
    elif status in ('failed', 'error'):
        state = 'failed'
    elif status in ('refused', 'rejected'):
        state = 'refused'
    elif status in ('hold', 'held', 'waiting', 'escalated', 'decision_required', 'budget_exhausted', 'stopped', 'paused'):
        state = 'held'
    elif delivery.get('accepted') is True and delivery.get('label') == 'accepted' and delivery.get('delivery_dir'):
        state = 'delivered_accepted'
    elif delivery.get('qualified') is True and delivery.get('delivery_dir'):
        state = 'qualified'
    else:
        state = 'held'
    reason = (str(error) if error else terminal.get('reason') or delivery.get('reason') or
              (f'command_exit_{code}' if code else None) or
              ('delivery_receipt_recorded' if state in ('delivered_accepted', 'qualified') else
               'no_completed_delivery_receipt'))
    remedy = getattr(error, 'remedy', None) if error else None
    if not remedy:
        remedy = (f'ravel status --run {run_id}' if run_id else
                  'inspect the command output and satisfy its reported prerequisites before retrying')
    return {'schema_version': 1, 'status': state, 'reason': reason,
            'reason_code': getattr(error, 'code', None) or (type(error).__name__ if error else reason),
            'run_id': run_id, 'evidence': evidence, 'next_action': remedy,
            'require_complete_exit_code': EXIT_CODES[state]}


def diagnostic(error, store=None):
    """Preserve the traceback privately; public diagnostics contain only its locator."""
    from .store import _private_dir, _write_private
    if store is not None:
        root = _private_dir(store.root / 'diagnostics')
    else:
        root = Path(tempfile.mkdtemp(prefix='ravel-diagnostic-'))
    import secrets
    path = root / (secrets.token_hex(8) + '.txt')
    _write_private(path, ''.join(traceback.format_exception(error)).encode(), exclusive=True)
    return str(path)


def error_result(command, error, *, store=None):
    import sys
    refused = isinstance(error, (ValueError, OSError)) or getattr(error, 'launch_refused', False)
    code = 2 if refused else 1
    try:
        evidence = diagnostic(error, store)
    except (OSError, ValueError):
        evidence = None
    result = outcome(error=error, code=code, run_id=store.run_id if store else None, evidence=evidence)
    if store is None and not getattr(error, 'remedy', None):
        result['next_action'] = (f'inspect private diagnostic: {evidence}; ' if evidence else '') + \
                                f'ravel {command} --help'
    print(json.dumps({'outcome': result}, indent=2, sort_keys=True))
    print(f'ravel {command}: {type(error).__name__}: {error}' +
          (f'; diagnostic: {evidence}' if evidence else ''), file=sys.stderr)
    return code


class _Tee(io.TextIOBase):
    """Bound output retention so streamed native logs do not grow controller memory."""
    def __init__(self, target):
        self.target, self.parts, self.size, self.overflow = target, [], 0, False

    def write(self, text):
        result = self.target.write(text)
        self.size += len(text)
        if self.size <= 1024 * 1024:
            self.parts.append(text)
        else:
            self.parts.clear()
            self.overflow = True
        return result

    def flush(self):
        self.target.flush()

    def fileno(self):
        return self.target.fileno()

    def isatty(self):
        return self.target.isatty()

    @property
    def buffer(self):
        return self.target.buffer


def dispatch(arguments, entry):
    """Opt-in outcome contract for every registered public command, including legacy work.

    Without the two explicit global options, existing output/exit behavior is
    preserved. Controller drive/ask always emit their own structured outcome.
    """
    import sys
    require, destination, clean = False, None, []
    index = 0
    while index < len(arguments):
        arg = arguments[index]
        if arg == '--':
            clean.extend(arguments[index:])
            break
        if arg == '--require-complete':
            require = True
        elif arg == '--outcome-file' or arg.startswith('--outcome-file='):
            if arg == '--outcome-file':
                index += 1
                if index >= len(arguments):
                    return error_result('outcome', ValueError('--outcome-file requires a path'))
                destination = arguments[index]
            else:
                destination = arg.partition('=')[2]
        else:
            clean.append(arg)
        index += 1
    if not require and destination is None:
        try:
            return entry(clean)
        except Exception as exc:
            return error_result(clean[0] if clean else '', exc)
    if destination is not None:
        from .store import controller_owned
        try:
            if not destination or controller_owned(destination):
                raise ValueError('--outcome-file must name a file outside controller runs and stores')
            target = Path(destination).expanduser().absolute()
            if target.exists() or target.is_symlink() or not target.parent.is_dir():
                raise ValueError('--outcome-file requires a new file in an existing directory')
        except (OSError, ValueError) as exc:
            return error_result('outcome', exc)
    captured = _Tee(sys.stdout)
    projected_error = False
    try:
        with contextlib.redirect_stdout(captured):
            code = entry(clean)
    except SystemExit as exc:
        code = exc.code if type(exc.code) is int else 2
    except Exception as exc:
        projected_error = True
        with contextlib.redirect_stdout(captured):
            code = error_result(clean[0] if clean else '', exc)
    try:
        value = json.loads(''.join(captured.parts)) if not captured.overflow else {}
    except ValueError:
        value = {}
    value = value if type(value) is dict else {}
    authoritative = clean[:1] == ['ask'] or (clean[:1] == ['drive'] and
                     any(arg in ('--resume', '--request-file') or arg.startswith(('--resume=', '--request-file='))
                         for arg in clean))
    result = (value.get('outcome') if authoritative or projected_error else None) or outcome(code=code or 0, run_id=value.get('run_id'),
                                           terminal=value.get('terminal'))
    # Only controller entries produce authoritative receipt-backed completion.
    if destination is not None:
        from .store import _write_private
        try:
            _write_private(target, (json.dumps(result, indent=2, sort_keys=True) + '\n').encode(), exclusive=True)
        except (OSError, ValueError) as exc:
            return error_result('outcome', exc)
    elif require and 'outcome' not in value:
        print(json.dumps({'outcome': result}, sort_keys=True))
    return (code if code == 130 else EXIT_CODES[result['status']]) if require else code
