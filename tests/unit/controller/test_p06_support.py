"""Support for the P06 authority tests: a local store with P01's binding signatures.

``FakeRunStore`` implements ``RunStore`` (append-only, hash-chained, controller clock) until the
controller core lands; it scans bare bodies, the least informative shape the interface allows,
so the issuer journal must retain the canonical IDs returned by append. The views build typed check-ins
from fictional generic run state.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import pytest

from ravel.controller.authority import common
from ravel.workflow.state_io import file_lock


class FakeRunStore:
    def __init__(self, run_id, *, root=None):
        self.run_id = run_id
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _file(self, kind):
        return self.root / f'{kind}.jsonl'

    def _entries(self, kind):
        path = self._file(kind)
        if not path.exists():
            return []
        rows, previous = [], None
        for seq, line in enumerate(path.read_text().splitlines()):
            row = json.loads(line)
            body = {k: v for k, v in row.items() if k != 'digest'}
            if row['seq'] != seq or row['prev'] != previous or _digest(body) != row['digest']:
                raise ValueError(f'store chain {kind} does not verify at {seq}')
            previous = row['digest']
            rows.append(row)
        return rows

    def append(self, kind, record):
        with file_lock(self.root / f'{kind}.lock'):
            rows = self._entries(kind)
            entry = {'seq': len(rows), 'prev': rows[-1]['digest'] if rows else None, 'ns': time.time_ns(),
                     'id': f'{kind}-{len(rows):06d}', 'record': record}
            entry['digest'] = _digest(entry)
            with self._file(kind).open('a') as stream:
                stream.write(json.dumps(entry, sort_keys=True) + '\n')
            return entry['id']

    def read(self, kind, record_id):
        for row in self._entries(kind):
            if row['id'] == record_id:
                return row['record']
        raise KeyError(record_id)

    def scan(self, kind):
        return [row['record'] for row in self._entries(kind)]

    def checkpointer(self):
        raise NotImplementedError('the authority tests use no checkpointer')

    def path(self, *parts):
        return self.root.joinpath(*parts)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def new_store(tmp_path, run_id='run-0001'):
    return FakeRunStore(run_id, root=tmp_path / 'store' / run_id)


def view(store, kind, **pins):
    """A complete fictional run-state view for one check-in kind."""
    sections = {
        'approve_plan': [{'id': 'preamble', 'title': 'Plain-language preamble',
                          'lines': ['Compute the fictional observable for the toy model at one point.']}],
        'go': [{'id': 'preamble', 'title': 'Preamble', 'lines': ['The waypoint ran.']},
               {'id': 'waypoint', 'title': 'Waypoint evidence', 'lines': ['Smoke yields within tolerance.']}],
        'deviation': [{'id': 'preamble', 'title': 'Preamble', 'lines': ['An approved input changed.']},
                      {'id': 'change', 'title': 'Change', 'lines': ['tolerance 0.10 -> 0.05']}],
        'final': [{'id': 'preamble', 'title': 'Preamble', 'lines': ['Results are ready.']},
                  {'id': 'results', 'title': 'Results', 'lines': ['Observable value 1.0 +- 0.1 (fictional).']}],
        'escalation': [{'id': 'preamble', 'title': 'Preamble', 'lines': ['A worker escalated.']},
                       {'id': 'question', 'title': 'Question', 'lines': ['Which binning should be used?']}],
        'r3_action': [{'id': 'preamble', 'title': 'Preamble', 'lines': ['An R3 action is proposed.']},
                      {'id': 'action', 'title': 'Action', 'lines': ['Open the blinded region.']}],
        'steering': [{'id': 'preamble', 'title': 'Preamble', 'lines': ['A steering policy is proposed.']},
                     {'id': 'policy', 'title': 'Policy', 'lines': ['events ceiling 1000']}],
    }[kind]
    base = {'run_id': common.run_id(store), 'pins': pins or {'plan_sha256': 'a' * 64}, 'sections': sections,
            'flags': [{'kind': 'assumption', 'text': 'The toy model has unit coupling.'},
                      {'kind': 'question', 'text': 'Is one point enough?'}],
            'items': {'steps': ['s01 derive the observable'], 'deliverables': ['one number with uncertainty'],
                      'boundaries': ['one model point only']}}
    if kind in ('escalation', 'r3_action'):
        base['options'] = [{'id': 'hold', 'text': 'keep the region blinded', 'effect': False},
                           {'id': 'proceed', 'text': 'open the region', 'effect': True}]
    retain_view(store, kind, base)
    return base


def retain_view(store, kind, source, *, request_pins=None, facts=None):
    from ravel.controller.authority import retained
    plan = {'sha256': source['pins'].get('plan_sha256'),
            **{k: source.get('items', {}).get(k, []) for k in ('steps', 'deliverables', 'boundaries')}}
    reading = {'flags': source.get('flags', []), 'items': {
        k: v for k, v in source.get('items', {}).items() if k not in ('steps', 'deliverables', 'boundaries')},
        'request_pins': request_pins or {}, 'inferred_critical_facts': facts or []}
    return retained.capture(store, kind, plan=plan, reading=reading, view=source)


@pytest.fixture
def operator_home(tmp_path, monkeypatch):
    """Isolate the controller home inside the test lock domain and clear agent markers."""
    from ravel.workflow.approval_authority import AGENT_MARKERS
    for name in AGENT_MARKERS:
        monkeypatch.delenv(name, raising=False)
    from ravel.controller.authority import operator, issuer
    monkeypatch.setattr(issuer, 'home', lambda: operator.controller_home() / 'issuer')
    return operator.controller_home()


def test_fake_store_keeps_an_append_only_chain(tmp_path):
    store = new_store(tmp_path)
    first = store.append('authority', {'schema': 'x', 'uid': 'u1'})
    store.append('authority', {'schema': 'x', 'uid': 'u2'})
    assert store.read('authority', first) == {'schema': 'x', 'uid': 'u1'}
    assert [r['uid'] for r in store.scan('authority')] == ['u1', 'u2']
    path = store.path('authority.jsonl')
    lines = path.read_text().splitlines()
    path.write_text('\n'.join([lines[1].replace('u2', 'u3'), lines[0]]) + '\n')
    with pytest.raises(ValueError):
        store.scan('authority')


class Ownership:
    """Stand-in for P01's ``controller_owned`` and ``RunStore`` lookup: registered runs only."""

    def __init__(self, monkeypatch):
        self.runs = {}
        monkeypatch.setattr(common, 'owned_run', self.owned)
        monkeypatch.setattr(common, 'open_store', self.store)

    def register(self, run_dir, store):
        self.runs[str(Path(run_dir).resolve())] = store
        return store

    def owned(self, run_dir):
        store = self.runs.get(str(Path(run_dir).resolve()))
        return store.run_id if store is not None else None

    def store(self, identifier):
        for store in self.runs.values():
            if store.run_id == identifier:
                return store
        raise common.AuthorityRefused(f'no controller run {identifier!r}')


@pytest.fixture
def ownership(monkeypatch):
    return Ownership(monkeypatch)


def autonomous(**changes):
    """Write an autonomous operator ledger (fictional generous bounds) and return the config."""
    from ravel.controller.authority import operator
    config = operator.init(mode='autonomous', r3_policy=changes.pop('r3_policy', 'escalate_and_wait'),
                           wait_bound_seconds=changes.pop('wait_bound_seconds', 3600),
                           notify_command=changes.pop('notify_command', None),
                           allow_request_delegation=changes.pop('allow_request_delegation', False))
    if changes:
        config = operator.set_values(changes)
    return config


def frozen_store(tmp_path, contract=None, run_id='run-0001'):
    from ravel.controller.authority import freeze_mode, operator
    if not operator._ledger_rows():
        operator.init(mode='physicist-in-the-loop')
    store = new_store(tmp_path, run_id)
    freeze_mode(store, contract or {'prompt': 'Compute the fictional observable for the toy model.'})
    return store
