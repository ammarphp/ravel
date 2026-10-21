"""Explicit peer fakes for cases authored before controller integration.

Only missing peer interfaces are faked. A case's component probe switches to its real adapter
as soon as the controller is installed; adapter/import failures never trigger fallback. The
ledger and sink here are contract observers, not evidence of production architecture acceptance.
They never read an expected verdict, a coverage-row identifier or an adversary's claimed credit.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time

import nc_cases
from nc_env import Env


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class FakeRunStore:
    """Local run-store fake, used while the shared ``tests/unit/controller/fakes.py`` is absent."""

    def __init__(self, run_id: str, *, root: Path | None = None):
        self.run_id = run_id
        self.root = Path(root) / run_id if root is not None else Path('/nonexistent-peer-store') / run_id
        self.entries = []
        if root is not None:
            self.root.mkdir(parents=True, mode=0o700, exist_ok=False)
            self.root.chmod(0o700)

    def append(self, kind: str, record: dict) -> str:
        body = {'kind': kind, 'record': deepcopy(record), 'seq': len(self.entries) + 1,
                'time_ns': time.time_ns(), 'prev': self.entries[-1]['digest'] if self.entries else '0' * 64}
        record_id = f'{kind}-{body["seq"]:06d}-{_digest(body)[:12]}'
        entry = dict(body, id=record_id)
        entry['digest'] = _digest(entry)
        self.entries.append(entry)
        return record_id

    def read(self, kind: str, record_id: str) -> dict:
        for entry in self.scan(kind):
            if entry['id'] == record_id:
                return entry
        raise ValueError(f'no {kind} record {record_id}')

    def scan(self, kind: str) -> list[dict]:
        return [deepcopy(row) for row in self.entries if row['kind'] == kind]

    def checkpointer(self):
        from langgraph.checkpoint.sqlite import SqliteSaver
        import sqlite3
        return SqliteSaver(sqlite3.connect(self.path('checkpoint.sqlite')))

    def path(self, *parts: str) -> Path:
        target = self.root.joinpath(*parts)
        if not target.resolve().is_relative_to(self.root.resolve()):
            raise ValueError('store path escapes private root')
        return target


class FakeLedger:
    """Ledger interface fake, deriving gate state from append-only transitions."""

    def materialise(self, store: FakeRunStore, stage: str, context: dict) -> list[str]:
        keys = list(context.get('rows') or ['component'])
        for key in keys:
            store.append('ledger', {'entry_id': key, 'stage': stage, 'status': 'pending', 'evidence': {}})
        return keys

    def record(self, store: FakeRunStore, entry_id: str, status: str, evidence: dict) -> None:
        if status not in ('pending', 'satisfied', 'violated', 'waived', 'not_applicable'):
            raise ValueError('unknown ledger status')
        store.append('ledger', {'entry_id': entry_id, 'status': status, 'evidence': deepcopy(evidence)})

    def gate(self, store: FakeRunStore, transition: str) -> list[dict]:
        latest = {row['record']['entry_id']: row['record'] for row in store.scan('ledger')}
        return [row for row in latest.values() if row['status'] not in ('satisfied', 'waived', 'not_applicable')]

    @staticmethod
    def population_equality(expected: list[str], actual: list[str]) -> list[str]:
        return sorted(set(expected) - set(actual))

    def summary(self, store: FakeRunStore) -> dict:
        return {'unmet': self.gate(store, 'deliver'), 'events': [row['record'] for row in store.scan('ledger')]}


def _codes(value, field):
    values = value.get(field, [])
    if type(values) is not list or any(type(item) is not str or not item for item in values):
        raise ValueError(f'component probe {field} must be nonempty strings in a list')
    return values


class FakeStep:
    """Step entry fake; admission happens before the independent effect observer is advanced."""

    def __init__(self, probe, env, ledger, observe):
        self.probe, self.env, self.ledger, self.observe = probe, env, ledger, observe

    def run(self, store: FakeRunStore, step: dict, context: dict) -> dict:
        result = self.probe(self.env, deepcopy(context['payload']))
        if type(result) is not dict:
            raise ValueError('component probe must return a record')
        errors, notices = _codes(result, 'errors'), _codes(result, 'notices')
        disclosures = _codes(result, 'disclosures')
        self.ledger.record(store, 'component', 'violated' if errors else 'satisfied',
                           {'errors': errors, 'notices': notices, 'disclosures': disclosures})
        allowed = not self.ledger.gate(store, 'dispatch')
        if allowed:
            self.observe()
        outcome = {'step_id': step['id'], 'status': 'completed' if allowed else 'held', 'errors': errors,
                   'notices': notices, 'disclosures': disclosures, 'diagnostics': result.get('diagnostics', {})}
        store.append('step-outcome', outcome)
        return outcome


class FakeSink:
    """Peer sink; it renders controller observations, never worker-supplied labels."""

    def deliver(self, store: FakeRunStore, plan: dict) -> dict:
        row = store.scan('step-outcome')[-1]['record']
        reasons = row['errors'] or row['notices']
        receipt = {'reason': reasons[0] if reasons else None, 'reasons': reasons,
                   'label': 'QUALIFIED' if reasons else 'CONTRACT VALIDATED',
                   'disclosures': row['disclosures'], 'evidence_scope': 'peer-contract'}
        store.append('delivery', receipt)
        return receipt

    def bounded_end(self, store: FakeRunStore, reason: str) -> dict:
        receipt = {'reason': reason, 'reasons': [reason], 'label': 'QUALIFIED',
                   'disclosures': [], 'evidence_scope': 'peer-contract'}
        store.append('delivery', receipt)
        return receipt

    def receipt(self, store: FakeRunStore) -> dict:
        return store.scan('delivery')[-1]['record']


@dataclass
class Outcome:
    allowed: bool
    errors: tuple
    notices: tuple
    ledger: list
    receipt: dict
    sink: bytes
    effects: int
    backend: str
    published: dict
    diagnostics: dict


class ContractHarness:
    """The same case fixture drives a component fake now and the installed component later."""

    def __init__(self, nc, *, fake, real):
        self.nc, self.fake, self.real = nc, fake, real
        self.sequence = 0

    def run(self, payload):
        self.sequence += 1
        root = self.nc.root / f'peer-{self.sequence}'
        env = Env(root, self.nc.patch)
        backend = 'real-component' if nc_cases.controller_installed() else 'peer-fake'
        probe = self.real if backend == 'real-component' else self.fake
        observer = root / 'observer' / 'effects.json'
        observer.parent.mkdir(parents=True)
        observer.write_text('[]')
        store = FakeRunStore('run-one', root=root / 'private-store')
        ledger, sink = FakeLedger(), FakeSink()
        ledger.materialise(store, 'dispatch', {'rows': ['component']})

        def observe():
            values = json.loads(observer.read_text())
            values.append('admitted-effect')
            observer.write_text(json.dumps(values))

        try:
            step = FakeStep(probe, env, ledger, observe)
            result = step.run(store, {'id': 'component-step'}, {'payload': payload})
            # The adversary emits a result even after denial. The sink reads the trusted outcome,
            # and never adopts this unreceipted fallback as a successful delivery.
            adversary = root / 'adversary' / 'fallback.txt'
            adversary.parent.mkdir()
            adversary.write_bytes(b'worker claims complete\n')
            receipt = sink.deliver(store, {'steps': [{'id': 'component-step'}]})
            reasons = result['errors'] or result['notices']
            content = b'QUALIFIED: ' + ','.join(reasons).encode() + b'\n' if reasons else b'fictional result\n'
            target = root / 'delivery' / 'result.txt'
            target.parent.mkdir()
            target.write_bytes(content)
            store.append('publication', {'path': 'result.txt', 'sha256': hashlib.sha256(content).hexdigest()})
            # Read all observations back independently of the probe return value.
            return Outcome(not bool(ledger.gate(store, 'dispatch')), tuple(result['errors']), tuple(result['notices']),
                           ledger.summary(store)['events'], sink.receipt(store), target.read_bytes(),
                           len(json.loads(observer.read_text())), backend, {'result.txt': target.read_bytes()},
                           deepcopy(result['diagnostics']))
        finally:
            env.close()
