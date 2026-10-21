"""Metadata-only worker login admission and redacted CLI diagnostics."""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import re
import shlex
import stat
import subprocess

from ..execution_backend import redact


class LoginRefused(ValueError):
    def __init__(self, message, code='worker_login_required'):
        super().__init__(message)
        self.code = code


def safe_error(text):
    text = redact(text)
    field = (r'[A-Za-z0-9_-]*(?:token|secret|password|passwd|api[_-]?key|credential|authorization)'
             r'[A-Za-z0-9_-]*')
    value = r'(?:"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[^\s,}]+)'
    text = re.sub(r'(?i)(["\']?' + field + r'["\']?\s*[:=]\s*)' + value,
                  r'\1[redacted]', text)
    return re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[redacted]', text)


def remedy(source, *, config=None, agent='claude'):
    directory = shlex.quote(str(source))
    command = (f'CLAUDE_CONFIG_DIR={directory} claude, then /login' if agent == 'claude'
               else f'CODEX_HOME={directory} codex login')
    target = Path(config or source) / ('.credentials.json' if agent == 'claude' else 'auth.json')
    return (f'Run {command}. Use your own setup step to make the file-backed login available '
            f'to the worker at {target}.')


def require_file(path, source, *, agent='claude'):
    """Admit owner-private regular login files through filesystem metadata."""
    path = Path(path)
    try:
        info = path.lstat()
        parent = path.parent.lstat()
    except FileNotFoundError:
        raise LoginRefused('A file-backed worker login is required. ' + remedy(source, config=path.parent, agent=agent),
                           'worker_login_file_required') from None
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or parent.st_mode & 0o077
            or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or not info.st_mode & 0o400 or info.st_size == 0):
        raise LoginRefused('An owner-private regular login file is required. '
                           + remedy(source, config=path.parent, agent=agent), 'worker_login_file_unsafe')
    return {'status': 'present', 'kind': 'owner-private-regular-file'}


def preflight(executable, source, *, config=None, environment=None, run_probe=None, agent='claude'):
    """Require a file-backed login and a prompt-free CLI authentication observation."""
    source, config = Path(source), Path(config or source)
    filename = '.credentials.json' if agent == 'claude' else 'auth.json'
    require_file(config / filename, source, agent=agent)
    environment = dict(os.environ if environment is None else environment)
    environment = {key: value for key, value in environment.items()
                   if not re.search(r'TOKEN|SECRET|PASSW|CREDENTIAL|API_?KEY|PRIVATE_?KEY|AUTH', key, re.I)
                   and not key.startswith('CLAUDE_CODE_USE_') and key != 'RAVEL_WMS_CAPABILITY'}
    environment['CLAUDE_CONFIG_DIR' if agent == 'claude' else 'CODEX_HOME'] = str(config)
    environment['USER'] = environment['LOGNAME'] = pwd.getpwuid(os.getuid()).pw_name
    argv = [str(executable), *(['auth', 'status', '--json'] if agent == 'claude' else ['login', 'status'])]
    if run_probe is not None:
        code, output = run_probe(argv, env=environment, timeout=15)
    else:
        try:
            result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                    errors='replace', env=environment, timeout=15, check=False)
            code, output = result.returncode, result.stdout + result.stderr
        except (OSError, subprocess.TimeoutExpired):
            raise LoginRefused('Login inspection requires attention. ' + remedy(source, config=config, agent=agent),
                               'worker_login_status_unknown') from None
    try:
        status = json.loads(output)
        logged_in = (status.get('loggedIn') is True
                     and status.get('authMethod') == ('claude.ai' if agent == 'claude' else 'chatgpt'))
    except (ValueError, AttributeError):
        logged_in = agent == 'codex' and output.strip() == 'Logged in using ChatGPT'
    if code or not logged_in:
        detail = safe_error('\n'.join(output[-8192:].splitlines()[-20:]))
        raise LoginRefused((detail or 'The worker login requires renewal.') + '\n'
                           + remedy(source, config=config, agent=agent), 'worker_login_unauthenticated')
    return {'status': 'authenticated', 'mechanism': 'cli-status', 'login_file': 'owner-provided'}
