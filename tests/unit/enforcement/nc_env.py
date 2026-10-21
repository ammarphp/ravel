"""The environment one non-compliance case runs in: a private root, a patch context and counters.

The ``nc`` fixture builds one per test; the mutation-adequacy test builds its own and calls the
same case function under a disabled mechanism. Every path is under the case's own temporary root,
and the process environment is pinned so no host session, state directory or work root leaks in.
"""
from __future__ import annotations

import json
from pathlib import Path

from nc_effects import Effects

HOST_VARIABLES = ('RAVEL_STATE_DIR', 'RAVEL_WORK_ROOT', 'RAVEL_TRANSPORT_PATH', 'RAVEL_AGENT_TRIPWIRE',
                  'RAVEL_OPERATING_MODE', 'WORKFLOW_STATE_UTC', 'GATE_TIMESTAMP', 'RAVEL_RESTRICTED_SOURCES')


class Env:
    def __init__(self, root, monkeypatch):
        self.root = Path(root)
        self.patch = monkeypatch
        self.effects = Effects(self.root / 'effects')
        self.operator = None  # the operator channel of controller cases (nc_controller.operator)
        self.state = self.root / 'state'
        self.state.mkdir(parents=True, exist_ok=True)
        for name in HOST_VARIABLES:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv('RAVEL_STATE_DIR', str(self.state))

    def enter_domain(self):
        """A fresh machine-lease test domain for this environment (the operator's home lives there)."""
        from ravel.workflow import machine_lease
        path = self.root / 'lock-domain'
        path.mkdir(parents=True, exist_ok=True)
        (path / machine_lease.TEST_MARKER).write_text('test lock domain\n')
        grant = machine_lease.test_domain_grants().issue(path)
        self.patch.setattr(machine_lease, '_TEST_DOMAIN', str(path))
        self.patch.setenv(machine_lease.GRANT_ENV, grant)
        return path

    def path(self, *parts):
        path = self.root.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def write_json(self, relative, value):
        path = self.path(relative)
        path.write_text(json.dumps(value, indent=1, sort_keys=True))
        return path

    def close(self):
        self.effects.close()
