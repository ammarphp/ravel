"""Bounded proxy lifetime metadata from the installed credential client."""
from __future__ import annotations

import os
import re
import shutil
import subprocess


def proxy_lifetime(path=None):
    """Return a typed lifetime observation; retain only the client's integer seconds."""
    command = shutil.which('voms-proxy-info')
    unknown = {'status': 'unknown', 'observer': 'voms-proxy-info', 'timeleft_seconds': None}
    if command is None:
        return unknown
    argv = [command, *(['--file', str(path)] if path is not None else []), '--timeleft']
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              text=True, timeout=10, check=False,
                              env={k: v for k, v in os.environ.items() if k != 'RAVEL_WMS_CAPABILITY'})
    except (OSError, subprocess.SubprocessError):
        return unknown
    raw = done.stdout.strip()
    if not re.fullmatch(r'-?\d{1,12}', raw):
        return unknown
    seconds = int(raw)
    if done.returncode != 0 and seconds > 0:
        return unknown
    return {'status': 'valid' if seconds > 0 else 'expired', 'observer': 'voms-proxy-info',
            'timeleft_seconds': seconds}
