"""Present an already-served literature output in MCP and governed tool messages.

The broker socket supplies the trusted reply. This adapter reads only the
content-addressed output in that worker's workspace, checks its digest, and
returns the original bytes as text. It never queries a provider or reads broker
custody, original sources, an index or installation configuration.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import PurePosixPath
import re
import stat

from . import broker, literature_provider


def load_output(workspace, reply, operation, *, logical_workspace=None):
    """Authenticate a socket reply's literature output without supervisor access."""
    if (not isinstance(reply, dict) or reply.get('status') != 'ok'
            or not isinstance(reply.get('outputs'), list) or len(reply['outputs']) != 1
            or not isinstance(reply['outputs'][0], dict)):
        raise ValueError('one delivered literature output required')
    pin = reply['outputs'][0]
    sha = pin.get('sha256')
    if not isinstance(sha, str) or re.fullmatch(r'[0-9a-f]{64}', sha) is None:
        raise ValueError('literature output digest required')
    path = pin.get('path')
    if not isinstance(path, str):
        raise ValueError('literature output path required')
    root = broker.ordinary(workspace)
    # Worker MCP startup knows the standard node/attempt layout, without custody
    # access. Trusted embedding callers may supply another broker.logical mapping.
    prefix = logical_workspace if logical_workspace is not None else str(
        PurePosixPath(broker.WORK, root.parent.name, root.name))
    if (not isinstance(prefix, str) or not prefix
            or PurePosixPath(prefix).is_absolute() or '..' in PurePosixPath(prefix).parts
            or str(PurePosixPath(prefix)) != prefix
            or path != str(PurePosixPath(prefix, 'outputs', 'literature', sha + '.json'))):
        raise ValueError('content-addressed literature output required')
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(root, directory_flags)
    try:
        for name in ('outputs', 'literature'):
            following = os.open(name, directory_flags, dir_fd=fd)
            os.close(fd)
            fd = following
        leaf = os.open(sha + '.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    finally:
        os.close(fd)
    with os.fdopen(leaf, 'rb') as stream:
        observed = os.fstat(stream.fileno())
        if (not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1
                or not 0 < observed.st_size <= literature_provider.MAX_BYTES):
            raise ValueError('ordinary bounded literature output required')
        raw = stream.read(literature_provider.MAX_BYTES + 1)
    if len(raw) != observed.st_size or hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError('literature output differs from the broker pin')
    envelope = json.loads(raw)
    if not isinstance(envelope, dict) or envelope.get('operation') != operation:
        raise ValueError('literature output belongs to another operation')
    raw.decode('utf-8')
    return raw


def projector(workspace, *, logical_workspace=None):
    """Trusted MCP bootstrap callback; projection failure retains the broker reply."""
    def project(reply, operation):
        if not isinstance(reply, dict) or reply.get('status') != 'ok':
            return {'content': [], 'isError': True}
        try:
            raw = load_output(workspace, reply, operation, logical_workspace=logical_workspace)
        except (OSError, ValueError, TypeError, KeyError):
            # The caller retains the original structuredContent and its receipt.
            return {'content': [{'type': 'text', 'text': json.dumps({
                'code': 'literature_output_unavailable', 'receipt_id': reply.get('receipt_id')}, sort_keys=True)}],
                    'isError': True}
        return {'content': [{'type': 'text', 'text': raw.decode('utf-8')}], 'isError': False}
    return project
