"""Installing and driving the inert adversaries.

``InstalledWorker`` puts ``fake_worker.py`` on the real worker path: a trusted test bin directory
holds it as the ``claude`` executable of the restricted CLI worker transport, probed and qualified
under the case's own state directory, and ``agent_worker.dispatch`` runs it in the OS sandbox
through the broker MCP face, exactly as it would run the real CLI. ``InProcessWorker`` runs the
same scenario against an in-process broker MCP session (no sandbox, no subprocess) for broker
decisions on hosts without confinement.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

import nc_cases

HERE = Path(__file__).resolve().parent
FAKE_WORKER = HERE / 'fake_worker.py'
FIXTURE_MODEL = 'claude-fixture-model'
CLAUDE_FLAGS = ('-p', '--output-format', '--model', '--effort', '--json-schema', '--setting-sources', '--restricted',
                '--safe-mode', '--strict-mcp-config', '--no-session-persistence', '--tools', '--allowedTools',
                '--max-budget-usd', '--mcp-config')


def fake_worker_module():
    spec = importlib.util.spec_from_file_location('nc_fake_worker', FAKE_WORKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sandbox_or_skip(env):
    """Skip with the declared reason when this host has no working OS confinement."""
    from ravel.workflow import sandbox
    if sandbox.available() is None:
        pytest.skip(f'{nc_cases.SANDBOX_BLOCKED} no OS sandbox backend on this host')
    ws = env.root / 'sandbox-check'
    for name in ('inputs', 'outputs', 'scratch'):
        (ws / name).mkdir(parents=True, exist_ok=True)
    (env.root / 'sandbox-private').write_text('protected')
    try:
        sandbox.probe(ws, forbidden=env.root / 'sandbox-private', read_paths=sandbox.runtime_paths([sys.executable]))
    except sandbox.SandboxUnavailable as exc:
        pytest.skip(f'{nc_cases.SANDBOX_BLOCKED} {exc}')
    except sandbox.SandboxProbeFailed as exc:
        if hasattr(exc, 'checks'):
            raise  # the probe ran and a denial was not confirmed: a real failure
        pytest.skip(f'{nc_cases.SANDBOX_BLOCKED} the sandbox probe launcher failed: {exc}')


class InstalledWorker:
    """The fake worker as the CLI executable of ``transport`` on the governed dispatch path."""

    def __init__(self, env, *, transport='claude-cli-worker', launcher='claude', qualified=True):
        from ravel.workflow import transport_registry as tr
        self.env = env
        self.transport = transport
        self.bin = env.root / 'bin'
        self.run = env.root / 'run'
        for path in (self.bin, env.root / 'home', env.root / 'claude-login', self.run / 'inputs'):
            path.mkdir(parents=True, exist_ok=True)
        (env.root / 'claude-login').chmod(0o700)
        login = env.root / 'claude-login/.credentials.json'
        login.write_text('opaque-owner-fixture')
        login.chmod(0o600)
        env.patch.setenv('HOME', str(env.root / 'home'))
        env.patch.setenv('PATH', f'{self.bin}:/usr/bin:/bin')
        env.patch.setenv('RAVEL_TEST_TRUSTED_BIN', str(self.bin))
        env.patch.setenv('CLAUDE_CONFIG_DIR', str(env.root / 'claude-login'))
        env.patch.delenv('RAVEL_WORK_ROOT', raising=False)
        from ravel.workflow.transports import cli_worker
        original_home = cli_worker._cli_home
        def owner_files(agent, document, ws):
            if agent == 'claude' and document['auth']['kind'] == 'login':
                from ravel.workflow import sandbox
                target = sandbox.cli_home_for(ws) / 'claude/.credentials.json'
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                if not target.exists():
                    target.write_text('opaque-owner-fixture')
                    target.chmod(0o600)
            return original_home(agent, document, ws)
        env.patch.setattr(cli_worker, '_cli_home', owner_files)
        (self.bin / 'help.txt').write_text('Usage\n' + '\n'.join(f'  {flag} <x>' for flag in CLAUDE_FLAGS) + '\n')
        (self.bin / 'version.txt').write_text('fake-cli 9.9.9\n')
        self.scenario({})
        executable = self.bin / launcher
        executable.write_text(f'#!{sys.executable} -B\n' + FAKE_WORKER.read_text())
        executable.chmod(0o755)
        self.probe = tr.probe(transport, executable=str(executable))
        assert not self.probe['unusable'], self.probe
        if qualified:
            self._qualify()
        self.env.write_json('run/inputs/agent_preferences.json', {
            'schema_version': 1, 'kind': 'agent-preferences', 'families': {},
            'tier_models': {tier: {transport: FIXTURE_MODEL} for tier in tr.TIERS}})

    def _qualify(self):
        """Explicitly synthetic legacy fixture record, never valid operator qualification.

        Transport-selection positive controls use real cli_worker.qualify instead.
        This legacy shape remains only for unrelated pre-existing worker fixtures.
        """
        from ravel.workflow import transport_registry as tr
        document = tr.load(self.transport)
        path = tr.qualification_path(self.transport)
        assert Path(path).is_relative_to(self.env.state)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({
            'schema_version': 1, 'kind': 'transport-qualification', 'transport_id': self.transport,
            'status': 'live_qualified', 'record_path': str(path), 'executable_path': self.probe['executable_path'],
            'executable_sha256': self.probe['executable_sha256'], 'declaration_sha256': tr.declaration_sha256(document),
            'probe_sha256': tr.digest(self.probe), 'receipt': {}, 'observed': {}, 'steps': [], 'rundir': 'synthetic',
            'qualified_utc': '2026-10-11T00:00:00Z'}))

    def scenario(self, scenario):
        (self.bin / 'scenario.json').write_text(json.dumps(scenario))

    def write_input(self, relative, text):
        path = self.run / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def spec(self, *, role='analysis-author', node_id='nc.worker', attempt=1, inputs=(), outputs=('outputs/result.txt',),
             schema='producer.v1', budgets=None):
        from ravel.workflow import broker, role_registry
        pins = []
        for relative in inputs:
            pins.append({'pin': {'path': relative, 'sha256': broker.sha(self.run / relative)}, 'as': relative})
        return {'schema_version': 1, 'kind': 'agent-worker-spec', 'node_id': node_id, 'attempt': attempt,
                'role': {'id': role, 'version': role_registry.load(role)['version'],
                         'card_sha256': role_registry.card_sha256(role)},
                'transport_preference': [self.transport], 'inputs': pins,
                'declared_outputs': [{'path': p, 'kind': 'text', 'required': True} for p in outputs],
                'budgets': budgets or {'max_turns': 8, 'max_wall_seconds': 60, 'max_broker_calls': 12,
                                       'max_cost_usd': None},
                'final_record_schema': schema, 'work_order': None, 'rdj_challenges': None,
                'parent': {'review_point_id': None, 'map_id': None, 'rca_ticket': None}}

    def dispatch(self, spec):
        from ravel.workflow import agent_worker
        return agent_worker.dispatch(self.run, spec)

    def workspace(self, spec):
        from ravel.workflow import agent_worker
        return agent_worker.workspace(self.run, spec['node_id'], spec['attempt'])

    def broker_calls(self):
        from ravel.workflow import broker
        return [broker.verify_broker_receipt(self.run, {'path': r['record']['path'], 'sha256': r['record']['sha256']},
                                             verify_outputs=False)
                for r in broker.ledger(self.run, 'broker')]

    def adversary_log(self, spec):
        path = self.workspace(spec) / 'scratch' / 'adversary.json'
        return json.loads(path.read_text()) if path.is_file() else None


class InProcessWorker:
    """The scenario against an in-process broker MCP session over ``card``'s toolbelt."""

    def __init__(self, env, card, *, max_calls=20, node_facts=None):
        from ravel.workflow import broker_mcp, tool_gate, toolbelt
        from ravel.workflow.broker import Broker, work_root
        self.env = env
        self.card = card
        self.tools = toolbelt.for_card(card, node_facts)
        self.run = env.root / 'run'
        self.run.mkdir(parents=True, exist_ok=True)
        self.workspace = work_root(self.run) / 'worker' / '1'
        for name in ('inputs', 'outputs', 'scratch', 'calls'):
            (self.workspace / name).mkdir(parents=True, exist_ok=True)
        self.broker = Broker(self.run, self.workspace, node_id='worker', attempt=1,
                             allowed_actions=toolbelt.allowed_actions(self.tools), max_calls=max_calls,
                             guards=[tool_gate.broker_guard(self.tools, rundir=self.run)])
        toolbelt.register_actions(self.broker, card)
        self.server = broker_mcp.Server(self.tools, self.broker.call)
        self._ids = iter(range(1, 1_000_000))

    def rpc(self, method, params):
        return self.server.handle({'jsonrpc': '2.0', 'id': next(self._ids), 'method': method, 'params': params})

    def play(self, scenario):
        cwd = Path.cwd()
        os.chdir(self.workspace)
        try:
            return fake_worker_module().run(scenario, self.rpc, self.workspace)
        finally:
            os.chdir(cwd)

    def ledger(self):
        return self.broker.verify_ledger()
