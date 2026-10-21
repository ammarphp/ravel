"""Shared fixtures of the governed-step (P04) tests: interface fakes and an inert worker.

The fakes stand for the binding interfaces of the sibling packages (the run store, obligation
ledger, instruction delivery, authority, confinement and review independence) with the
signatures of PACKAGES.md section 0.2 and the record shapes those packages publish. They are
installed through the interpreter's module table for one test; the governed step itself offers
no substitution hook.

The inert worker is a fake ``claude`` executable that speaks the broker MCP: it reads the
instruction packet on standard input, starts the broker MCP server its configuration names,
calls the tools its scenario lists, and prints a CLI result envelope whose structured output
acknowledges the packet's duty units. The dispatcher's whole path runs (materialization, the
trusted launch descriptor, the supervisor, the broker, receipts); only the OS sandbox and the
supervisor's process boundary are inert seams. No model, provider, network or native tool runs.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import types

import pytest

from ravel.controller.step import services

RUN_ID = 'run-p04-fixture'
MODEL = 'claude-fixture-model'
PROMPT = 'Compute one fictional calculated quantity for the fixture model and report it with its uncertainty.'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


# ---- the run store ---------------------------------------------------------------------------

class FakeStore:
    """A ``RunStore`` with the published envelopes, files under a temporary store root."""

    def __init__(self, root, run_id=RUN_ID, run_dir=None):
        self.run_id = run_id
        self.store_root = Path(os.path.realpath(root))
        self.root = self.store_root / run_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.run_dir = Path(run_dir) if run_dir is not None else None
        self.entries = []
        self._seq = itertools.count(1)
        import threading
        self._lock = threading.Lock()

    def append(self, kind, record):
        json.dumps(record, allow_nan=False)
        with self._lock:
            prev = self.entries[-1]['digest'] if self.entries else '0' * 64
            body = {'schema_version': 1, 'seq': len(self.entries) + 1, 'kind': kind, 'time_ns': time.time_ns(),
                    'prev': prev, 'record': deepcopy(record)}
            entry = {**body, 'id': f"{kind}-{body['seq']:06d}-{digest(body)[:12]}"}
            entry['digest'] = digest(entry)
            self.entries.append(entry)
            return entry['id']

    def read(self, kind, record_id):
        for entry in self.entries:
            if entry['id'] == record_id and entry['kind'] == kind:
                return deepcopy(entry)
        raise ValueError(f'no {kind} record {record_id}')

    def scan(self, kind):
        with self._lock:
            return [deepcopy(e) for e in self.entries if e['kind'] == kind]

    def latest(self, kind):
        rows = self.scan(kind)
        return rows[-1] if rows else None

    def head(self):
        return {'seq': len(self.entries), 'digest': self.entries[-1]['digest'] if self.entries else '0' * 64}

    def path(self, *parts):
        target = self.root.joinpath(*parts)
        return target

    def put_blob(self, data):
        key = sha(data)
        target = self.root / 'blobs' / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return key

    def get_blob(self, key):
        data = (self.root / 'blobs' / key).read_bytes()
        assert sha(data) == key
        return data

    def records(self, kind):
        return [e['record'] for e in self.scan(kind)]


# ---- obligation ledger (P02 shape) -----------------------------------------------------------

class FakeLedger:
    def __init__(self):
        self.calls = []

    @staticmethod
    def key(row, run_id, scope):
        parts = [f'{row}@{run_id}'] + [f'{n}={scope[n]}' for n in ('step', 'point', 'seat', 'attempt')
                                       if scope.get(n) is not None]
        return '/'.join(parts)

    def materialise(self, store, stage, context):
        self.calls.append(('materialise', stage, deepcopy(context)))
        role = context.get('role')
        rows = ['B01', 'B02', 'I01', 'I08', 'CF01'] + ([f'ROLE-{role}-stop', f'ROLE-{role}-model'] if role else [])
        scope = {'step': context.get('step'), 'seat': context.get('seat'), 'attempt': context.get('attempt')}
        keys = [self.key(r, context.get('run_id'), scope) for r in rows]
        for key in keys:
            store.append('ledger', {'entry_id': key, 'status': 'pending', 'stage': stage})
        return keys

    def record(self, store, entry_id, status, evidence):
        assert status in ('pending', 'satisfied', 'violated', 'waived', 'not_applicable')
        known = {r['record']['entry_id'] for r in store.scan('ledger')}
        if entry_id not in known:
            raise KeyError(entry_id)
        self.calls.append(('record', entry_id, status))
        store.append('ledger', {'entry_id': entry_id, 'status': status, 'evidence': deepcopy(evidence)})

    def decide(self, store, rundir, gate_name, action):
        self.calls.append(('decide', gate_name, deepcopy(action)))
        return []

    def gate(self, store, transition):
        return []

    def current(self, store, *, node=None, stage=None, step=None):
        from importlib.resources import files
        catalogue = json.loads(files('ravel').joinpath('data/obligations/catalogue.json').read_bytes())
        nodes = {row['id']: row['node'] for row in catalogue['rows']}
        found = {}
        for envelope in store.scan('ledger'):
            record = envelope['record']
            key = record['entry_id']
            found[key] = {**found.get(key, {}), **record}
        result = []
        for key, record in found.items():
            row_id = key.split('@', 1)[0]
            row_node = nodes.get(row_id, '')
            if node is not None and node not in (row_node, row_node.split('[', 1)[0]):
                continue
            if stage is not None and record.get('stage') != stage:
                continue
            if step is not None and f'/step={step}/' not in key + '/':
                continue
            result.append({'entry': key, 'id': row_id, 'status': record['status'],
                           'evidence': deepcopy(record.get('evidence'))})
        return result

    def statuses(self, store):
        found = {}
        for row in store.scan('ledger'):
            found[row['record']['entry_id']] = row['record']['status']
        return found


# ---- instruction delivery (P03 shape) ---------------------------------------------------------

def output_schema(family, *, manifest_sha=None, duty=None, escalation=None):
    """The acknowledging schemas the tests pin (the instruction package's producer.v2 and findings.v3)."""
    ack = {'type': 'object', 'additionalProperties': False, 'required': ['manifest_sha256'],
           'properties': {'manifest_sha256': ({'const': manifest_sha} if manifest_sha else
                                              {'type': 'string', 'pattern': '^[0-9a-f]{64}$'})}}
    row = {'type': 'object', 'additionalProperties': False, 'required': ['unit', 'status', 'evidence', 'note'],
           'properties': {'unit': ({'enum': duty} if duty else {'type': 'string', 'minLength': 1}),
                          'status': {'enum': ['done', 'not_applicable', 'blocked']},
                          'evidence': {'type': ['string', 'null']}, 'note': {'type': ['string', 'null']},
                          'sha256': {'type': 'string'}}}
    item = {'type': 'object', 'additionalProperties': False, 'required': ['kind', 'statement', 'evidence'],
            'properties': {'kind': {'enum': escalation or ['checkin_flag', 'stop', 'new_experiment_required',
                                                           'decision_block']},
                           'statement': {'type': 'string', 'minLength': 1},
                           'evidence': {'type': 'array', 'items': {'type': 'string'}},
                           'options': {'type': 'array', 'items': {'type': 'string'}}}}
    common = {'instruction_ack': ack, 'checklist': {'type': 'array', 'items': row},
              'escalation': {'type': 'array', 'items': item},
              'handoff': {'anyOf': [{'type': 'null'}, {'type': 'object'}]}}
    if family == 'producer':
        return {'type': 'object', 'additionalProperties': False,
                'required': ['schema_version', 'kind', 'outputs', 'decisions', 'knowledge_used', 'handoff',
                             'instruction_ack', 'checklist', 'escalation'],
                'properties': {'schema_version': {'const': 2}, 'kind': {'const': 'producer-result'},
                               'outputs': {'type': 'array', 'minItems': 1, 'items': {'type': 'object'}},
                               'decisions': {'type': 'array'}, 'knowledge_used': {'type': 'array'}, **common}}
    return {'type': 'object', 'additionalProperties': False,
            'required': ['schema_version', 'kind', 'items', 'handoff', 'instruction_ack', 'checklist', 'escalation',
                         'item_verdicts'],
            'properties': {'schema_version': {'const': 3}, 'kind': {'const': 'findings'},
                           'items': {'type': 'array'}, 'item_verdicts': {'type': 'array'}, **common}}


class FakeInstructions:
    """``manifest``/``packet``/``check_packet``/``check_ack`` in the instruction package's formats."""

    def __init__(self, units=2):
        self.units = units
        self.calls = []
        self.alter_packet = False

    def manifest(self, step, card):
        units = [{'id': f"docs/fixture/{step['kind']}.md#duty/{n}", 'sha256': digest([step['kind'], n]),
                  'kind': 'duty'} for n in range(self.units)]
        units.append({'id': 'docs/fixture/context.md#context/0', 'sha256': digest('context'), 'kind': 'context'})
        body = {'step': step['id'], 'role': card['id'] if card else None, 'units': units, 'catalogue_sha256': '0' * 64}
        return {**body, 'sha256': digest(body)}

    def _schema(self, manifest, card):
        family = 'findings' if card['output']['schema'].startswith('findings') else 'producer'
        duty = [u['id'] for u in manifest['units'] if u['kind'] == 'duty']
        return ('findings.v3' if family == 'findings' else 'producer.v2',
                output_schema(family, manifest_sha=manifest['sha256'], duty=duty, escalation=list(card['escalation'])))

    def packet(self, manifest, card, step, inputs):
        self.calls.append(('packet', step['id']))
        schema_id, schema = self._schema(manifest, card)
        lines = ['ravel-instruction-packet-v1',
                 f"step: {step['id']}   role: {card['id']}   manifest sha256: {manifest['sha256']}",
                 '== Effective role card (every field) ==', json.dumps(card, sort_keys=True),
                 '== Step specification (step.v1) ==', json.dumps(step, sort_keys=True),
                 '== Inputs (by digest) =='] + [f'- {json.dumps(r, sort_keys=True)}' for r in inputs] + [
                 '== Output contract ==', f'schema: {schema_id}', json.dumps(schema, sort_keys=True),
                 '== Duty units (acknowledge each) ==']
        lines += [f"--- [{u['kind']}] {u['id']} sha256:{u['sha256']}\nDo the duty {u['id']}." for u in manifest['units']
                  if u['kind'] == 'duty']
        from ravel.workflow.capability_catalogue import for_seat
        capabilities = for_seat((step.get('parameters') or {}).get('seat_kind') or card['id'])
        lines.append('capability catalogue sha256: ' + capabilities['catalogue_sha256'])
        text = '\n'.join(lines) + '\n'
        return {'capability_context': capabilities, 'text': text, 'sha256': sha(text.encode()), 'schema': schema, 'schema_id': schema_id,
                'manifest_sha256': manifest['sha256'], 'catalogue_sha256': '0' * 64,
                'units': [u['id'] for u in manifest['units']], 'deferred': [], 'tokens': len(text) // 4}

    def check_packet(self, packet, manifest, card, step, inputs):
        return ['unit missing or altered in the packet: fixture'] if self.alter_packet else []

    def record_delivery(self, store, manifest, packet, *, session):
        """Record only a packet bound to the current fake worker-session observation."""
        from ravel.controller.step.services import unwrap
        observed = unwrap(store.read('worker-session', session))
        attempts = [unwrap(row) for row in store.scan('step-attempt')
                    if unwrap(row).get('step') == observed.get('step')]
        if (not attempts or attempts[-1].get('session') != session
                or any(observed.get(key) != value for key, value in {
                    'run_id': store.run_id, 'step': manifest.get('step'),
                    'manifest_sha256': manifest.get('sha256'),
                    'packet_sha256': packet.get('sha256')}.items())
                or observed.get('packet') != packet
                or self.check_packet(packet, manifest, observed.get('card'),
                                     observed.get('step_spec'), observed.get('inputs'))):
            raise ValueError('delivery is not bound to the current checked worker session')
        receipt = self.receipt(manifest, packet, session=session)
        receipt.update(run_id=observed['run_id'], attempt=observed['attempt'])
        return store.append('instruction-delivery', receipt)

    @staticmethod
    @contextmanager
    def observed_completion(store, *, session, completion_id=None):
        """Fake-only scope validating the stored active attempt and observed artifact bytes."""
        from ravel.controller.step.services import unwrap
        sessions = [unwrap(row) for row in store.scan('worker-session') if row['id'] == session]
        if len(sessions) != 1:
            raise ValueError('exactly one controller-observed worker session is required')
        observed = sessions[0]
        attempts = [unwrap(row) for row in store.scan('step-attempt')
                    if unwrap(row).get('step') == observed.get('step')]
        if not attempts or attempts[-1].get('session') != session:
            raise ValueError('worker session is not the active controller-observed attempt')
        active = attempts[-1]
        if any(observed.get(key) != value for key, value in {
                'run_id': store.run_id, 'step': active.get('step'), 'attempt': active.get('attempt'),
                'manifest_sha256': active.get('manifest_sha256'),
                'packet_sha256': active.get('packet_sha256')}.items()):
            raise ValueError('worker session differs from its active attempt binding')
        completions = [row for row in store.scan('worker-completion')
                       if unwrap(row).get('session') == session]
        if len(completions) != 1 or (completion_id is not None and completions[0]['id'] != completion_id):
            raise ValueError('exactly one matching controller-observed completion is required')
        envelope = completions[0]
        completion = unwrap(envelope)
        if (any(completion.get(key) != observed.get(key) for key in
                ('run_id', 'step', 'attempt', 'manifest_sha256', 'packet_sha256'))
                or not isinstance(completion.get('final_record'), dict)
                or not isinstance(completion.get('artifacts'), list)):
            raise ValueError('completion differs from its observed session binding')
        for artifact in completion['artifacts']:
            path = artifact.get('path') if isinstance(artifact, dict) else None
            if (not isinstance(path, str) or not path
                    or any(part in ('', '.', '..') for part in path.split('/'))):
                raise ValueError('invalid observed artifact path')
            target = store.path('instruction-artifacts', session, *path.split('/'))
            if (not target.is_file() or target.is_symlink()
                    or sha(target.read_bytes()) != artifact.get('sha256')):
                raise ValueError('observed artifact bytes differ from the completion record')
        yield types.SimpleNamespace(session=session, completion_id=envelope['id'],
                                    final_record=completion['final_record'],
                                    artifacts=completion['artifacts'],
                                    packet_sha256=completion['packet_sha256'])

    @staticmethod
    def obligations(manifest):
        result = {}
        for unit in manifest['units']:
            for row in unit.get('census', []):
                result.setdefault(row, []).append(unit['id'])
        return result

    def discharge(self, store, entries, manifest, *, receipt_id, ack_errors=None, record=None):
        """Recheck the stored completion; caller-supplied errors never grant instruction credit."""
        from ravel.controller.step.services import unwrap
        receipt = unwrap(store.read('instruction-delivery', receipt_id))
        session = receipt.get('session')
        if receipt_id not in [row['id'] for row in store.scan('instruction-delivery')]:
            raise ValueError('instruction delivery receipt is not in the run store')
        with self.observed_completion(store, session=session) as scope:
            if (receipt.get('manifest_sha256') != manifest.get('sha256')
                    or receipt.get('packet_sha256') != scope.packet_sha256):
                raise ValueError('delivery receipt differs from the manifest or completion')
            errors = self.check_ack(manifest, scope.final_record,
                                    [artifact['path'] for artifact in scope.artifacts])
            statuses = {}
            for row, entry_id in entries.items():
                status = 'violated' if errors else 'satisfied'
                evidence = {'instruction_receipt': receipt_id, 'ack': scope.completion_id}
                if errors:
                    evidence.update(reason='; '.join(errors), errors=errors)
                if record is not None:
                    record(store, entry_id, status, evidence)
                statuses[row] = status
            return statuses

    def check_ack(self, manifest, final_record, outputs):
        if not isinstance(final_record, dict):
            return ['manifest: the final record is not an object']
        errors = []
        ack = final_record.get('instruction_ack')
        if not isinstance(ack, dict) or ack.get('manifest_sha256') != manifest.get('sha256'):
            errors.append('manifest: instruction_ack.manifest_sha256 is not the delivered manifest digest')
        rows = final_record.get('checklist') if isinstance(final_record.get('checklist'), list) else []
        seen = set()
        units = {u['id']: u for u in manifest['units']}
        for row in rows:
            uid = row.get('unit') if isinstance(row, dict) else None
            if uid not in units:
                errors.append(f'unknown: {uid}: not a unit of the delivered manifest')
                continue
            seen.add(uid)
            if row.get('status') == 'blocked':
                errors.append(f"blocked: {uid}: {row.get('note') or 'blocked without a stated reason'}")
            elif row.get('status') == 'done' and not row.get('evidence'):
                errors.append(f'evidence: {uid}: no evidence')
        errors += [f'missing: {uid}: no checklist row for a duty unit' for uid, u in units.items()
                   if u['kind'] == 'duty' and uid not in seen]
        return errors

    def receipt(self, manifest, packet, *, session):
        return {'schema_version': 1, 'kind': 'instruction-delivery', 'step': manifest.get('step'),
                'role': manifest.get('role'), 'manifest_sha256': manifest['sha256'], 'packet_sha256': packet['sha256'],
                'schema_id': packet['schema_id'], 'units': [u['id'] for u in manifest['units']],
                'deferred': list(packet.get('deferred', [])), 'session': session}

    def reviewer_items(self, manifest, card):
        return [{'id': f'must_check:{c}', 'kind': 'must_check', 'check': c} for c in (card or {}).get('must_check', [])]

    def check_item_verdicts(self, items, record):
        rows = record.get('item_verdicts') if isinstance(record, dict) else None
        if not isinstance(rows, list):
            return ['item_verdicts[] is missing']
        wanted = {i['id'] for i in items}
        seen = {r.get('item') for r in rows if isinstance(r, dict)}
        return [f'missing: {i}: no verdict' for i in sorted(wanted - seen)]


# ---- authority (P06 shape) ------------------------------------------------------------------

class AuthorityRefused(ValueError):
    pass


class FakeAuthority:
    def operator_config(self):
        return {}

    def frozen(self, store, *, required=False):
        return None

    TERMINAL = 'physicist_terminal_response'
    MACHINE = 'operator_configured_machine'

    def __init__(self, budgets=None, *, stop='running', refuse=None, answers=None):
        self.budgets = {'wall_seconds': 100000, 'model_calls': 10000, 'tokens': 50_000_000, 'cost_usd': None,
                        'core_hours': 1000, 'events': 10_000_000, 'children': 1000, **(budgets or {})}
        self.stop = stop
        self.refuse = refuse
        self.answers = dict(answers or {})
        self.calls = []
        self.AuthorityRefused = AuthorityRefused
        from ravel.controller.authority.retained import view_items
        self.retained = types.SimpleNamespace(current=self.retained_current, capture=self.retained_capture,
                                              view_items=view_items)

    def retained_current(self, store, kind):
        raise AuthorityRefused('no retained check-in in the inert authority')

    def retained_capture(self, store, kind, *, plan, reading, view):
        self.calls.append(('retain', kind, deepcopy(plan), deepcopy(reading)))
        return {'view': deepcopy(view)}

    def stop_state(self, store):
        return self.stop

    def effective_bounds(self, store):
        return {'budgets': deepcopy(self.budgets), 'bounds': {'compute_plans': ['none', 'dry', 'smoke', 'pilot', 'full',
                                                                                'scan'], 'allowed_stages': ['*']}}

    def authorize_effect(self, store, effect):
        self.calls.append(('authorize_effect', deepcopy(effect)))
        if effect.get('rung') not in ('none', 'dry', 'smoke', 'pilot', 'full', 'scan'):
            raise ValueError('effect rung is one of none, dry, smoke, pilot, full, scan')
        if self.refuse and effect['rung'] in self.refuse:
            raise AuthorityRefused(f"{effect['rung']} refused: no current CHECK-IN 2 GO (fixture)")
        return {'approve_plan': 'authority-000001-fixture', 'go': None, 'labels': [self.MACHINE]}

    SUBJECT_KEYS = frozenset({'view', 'checkin', 'gate', 'change', 'policy', 'conservative_default', 'request_pins',
                              'inferred_critical_facts', 'obligations'})
    VIEW_KEYS = frozenset({'run_id', 'pins', 'sections', 'flags', 'items', 'options', 'required_sections', 'summary'})
    GENERATED = ('plan', 'flags', 'options', 'respond')

    def _check_subject(self, store, kind, subject, bounds):
        """The authority service's request contract: a run-state view it renders the typed check-in from."""
        if type(subject) is not dict or 'view' not in subject or set(subject) - self.SUBJECT_KEYS:
            raise ValueError(f'a {kind} request carries the run-state view it is decided on')
        view = subject['view']
        assert type(view) is dict and not set(view) - self.VIEW_KEYS
        if view.get('run_id') != store.run_id:
            raise AuthorityRefused('the check-in view names a different run')
        pins = view.get('pins')
        assert type(pins) is dict and pins and all(type(k) is str and type(v) is str and v for k, v in pins.items())
        sections = {row['id']: row for row in view.get('sections', [])}
        assert all(set(row) == {'id', 'title', 'lines'} and row['lines'] and row['id'] not in self.GENERATED
                   and all(type(line) is str and line.strip() for line in row['lines']) for row in sections.values())
        options = view.get('options') or []
        assert all(not set(o) - {'id', 'text', 'effect'} and type(o.get('effect', True)) is bool for o in options)
        if kind == 'r3_action':
            assert options and {'preamble', 'action'} <= set(sections)
        default = subject.get('conservative_default')
        assert default is None or any(o['id'] == default for o in options)
        assert type(bounds) is dict and not set(bounds) - {'rung', 'stages', 'budget', 'policy'}

    def request(self, store, kind, subject, bounds):
        self.calls.append(('request', kind, deepcopy(subject)))
        self._check_subject(store, kind, subject, bounds)
        answer = self.answers.get(kind, 'pending')
        if answer == 'pending':
            return {'pending': {'kind': kind, 'reason': 'waiting for a human (fixture)'}}
        decision, label, *option = answer
        record = {'kind': kind, 'decision': decision, 'option': option[0] if option else None, 'label': label,
                  'subject': deepcopy(subject), 'bounds': deepcopy(bounds)}
        record['id'] = store.append('authority', record)
        return record


# ---- confinement (P05 shape) ----------------------------------------------------------------

class LaunchHeld(ValueError):
    """The confinement package's typed hold (same name and fields): nothing was started."""
    launch_refused = True

    def __init__(self, reason, detail):
        super().__init__(f'launch held ({reason}): {detail}; nothing was started')
        self.reason, self.detail = reason, detail


class FakeConfine:
    """The confinement interface with its spec, limit and probe contracts checked; ``popen`` runs the
    approved argv unconfined (tests only). ``probe`` observes the admitted sets plus ``extra[kind]``."""
    SPEC_KEYS = frozenset({'argv', 'env', 'reads', 'writes', 'limits', 'backend', 'cwd', 'run_dir', 'stage',
                           'attempt_dir', 'withheld', 'channels', 'tcp_ports', 'input_digests', 'controller', 'label'})
    LIMIT_KEYS = frozenset({'cpus', 'memory_mib', 'processes', 'wall_seconds'})
    ADMITTED_KEYS = frozenset({'tools', 'writable', 'env_names', 'network', 'read_roots'})
    # The worker target keys the real probe reads (confine/probe.py ``_worker``), no others.
    WORKER_KEYS = frozenset({'workspace', 'read_paths', 'protected', 'home', 'network', 'env',
                             'tools', 'run_dir', 'admitted', 'writable', 'mcp_command', 'mcp_env'})
    # A worker's admitted capsule names all four fields; the real probe reports any it lacks.
    WORKER_ADMITTED = ('env_names', 'network', 'tools', 'writable')

    def __init__(self):
        self.launched = []
        self.probes = []
        self.finished = []
        self.extra = {}
        self.hold = None
        self.probe_error = None

    def _check_spec(self, spec):
        assert type(spec) is dict and not set(spec) - self.SPEC_KEYS, sorted(set(spec) - self.SPEC_KEYS)
        assert not set(spec.get('limits') or {}) - self.LIMIT_KEYS, spec.get('limits')
        assert all(Path(p).is_absolute() for p in [*spec.get('reads', []), *spec.get('writes', [])])
        for path, sha in (spec.get('input_digests') or {}).items():
            assert path in spec['reads'] and hashlib.sha256(Path(path).read_bytes()).hexdigest() == sha

    def popen(self, spec, **kwargs):
        self._check_spec(spec)
        if self.hold:
            raise LaunchHeld(self.hold, 'no qualified sandbox on this test host')
        self.launched.append(deepcopy(spec))
        env = {'PATH': '/usr/bin:/bin', **spec.get('env', {})}
        process = subprocess.Popen(spec['argv'], env=env, **kwargs)
        process.ravel_confinement = types.SimpleNamespace(record={'kind': 'confined', 'backend': 'inert-test-backend'})
        return process

    def finish(self, target):
        self.finished.append(getattr(target, 'returncode', None))
        return {'adopted': [], 'quarantined': [], 'errors': [], 'outputs': [],
                'exit_status': getattr(target, 'returncode', None)}

    def probe(self, kind, target):
        assert kind in ('worker', 'launch') and type(target) is dict
        admitted = target.get('admitted')
        assert type(admitted) is dict and not set(admitted) - self.ADMITTED_KEYS
        if kind == 'worker':
            assert not set(target) - self.WORKER_KEYS and Path(target['workspace']).is_dir(), \
                sorted(set(target) - self.WORKER_KEYS)
            mcp = target.get('mcp_command')
            assert mcp is None or (type(mcp) is list and mcp and all(type(v) is str for v in mcp)
                                   and Path(mcp[0]).is_absolute()), 'mcp_command is an absolute executable argv'
            assert all(type(k) is str and type(v) is str for k, v in (target.get('mcp_env') or {}).items())
        else:
            self._check_spec({k: v for k, v in target.items() if k not in ('admitted', 'tools')})
        self.probes.append((kind, deepcopy(target)))
        if self.probe_error:
            raise ValueError(self.probe_error)
        observed = {key: deepcopy(value) for key, value in admitted.items()}
        if kind == 'worker':
            observed['tools'] = sorted(target.get('tools') or [])
        for key, value in (self.extra.get(kind) or {}).items():
            observed[key] = sorted({*observed.get(key, []), *value}) if type(value) is list else value
        differences = [{'field': key, 'reason': 'missing admitted field'}
                       for key in self.WORKER_ADMITTED if kind == 'worker' and key not in admitted]
        for key, value in sorted(admitted.items()):
            seen = observed.get(key)
            if type(value) is list:
                if sorted(set(seen or []) - set(value)):
                    differences.append({'field': key, 'unadmitted': sorted(set(seen or []) - set(value))})
                if sorted(set(value) - set(seen or [])):
                    differences.append({'field': key, 'absent': sorted(set(value) - set(seen or []))})
            elif seen != value:
                differences.append({'field': key, 'admitted': value, 'observed': seen})
        return {**observed, 'kind': kind, 'equal': not differences, 'differences': differences}

    def backends(self):
        return {'bwrap': 'inert', 'sandbox-exec': 'inert', 'oci-local': 'inert'}


class FakeIndependence:
    def __init__(self, independent=True):
        self.independent = independent
        self.queries = []

    def decide(self, query):
        self.queries.append(deepcopy(query))
        if self.independent:
            return {'independent': True, 'advisory': None, 'dispatch_id': 'fixture-dispatch', 'context_id': 'ctx',
                    'exposure': {}}
        return {'independent': False, 'advisory': 'fixture_advice', 'dispatch_id': None, 'context_id': None,
                'exposure': None}

    def family_relation(self, models):
        return 'same'


def _module(name, obj):
    module = types.ModuleType(name)
    # Keep sibling imports available when the interface is a package.
    import importlib.util
    source = importlib.util.find_spec(name)
    if source is not None and source.submodule_search_locations is not None:
        module.__path__ = list(source.submodule_search_locations)
        module.__spec__ = source
    for attribute in dir(obj):
        if not attribute.startswith('_'):
            setattr(module, attribute, getattr(obj, attribute))
    return module


@pytest.fixture
def services_installed(monkeypatch):
    """Install fresh fakes for every consumed interface; returns them by name."""
    fakes = {'ledger': FakeLedger(), 'instructions': FakeInstructions(), 'authority': FakeAuthority(),
             'confine': FakeConfine(), 'independence': FakeIndependence()}
    install(monkeypatch, fakes)
    # This fixture declares package interfaces for an unowned FakeStore. The
    # genuine authority bridge's authenticated issuer/plan tests run separately.
    # Its native identity remains the actual closed action; this mints no assent.
    from ravel.controller.step import native_authority, launch_gate
    def prepare_native(store, step, context, preflight):
        assert isinstance(store, FakeStore), 'the fake native interface cannot cover a real RunStore'
        return {'action': launch_gate.action(step, context, preflight, preflight.get('native_preflight')),
                'class': 'R2'}
    monkeypatch.setattr(native_authority, 'prepare', prepare_native)
    return fakes


def install(monkeypatch, fakes):
    from ravel.controller.confine import commitments
    for name in ('ledger', 'instructions', 'authority', 'confine'):
        replacement = _module(services.INTERFACES[name], fakes[name])
        if name == 'confine':
            replacement.commitments = commitments
        monkeypatch.setitem(sys.modules, services.INTERFACES[name], replacement)
    monkeypatch.setitem(services.INTERFACES, 'independence', 'p04_fixture_independence')
    monkeypatch.setitem(sys.modules, 'p04_fixture_independence', _module('p04_fixture_independence',
                                                                         fakes['independence']))
    from ravel.workflow import toolbelt
    real = toolbelt.output_schema

    def schema(card):
        name = card['output']['schema']
        if name in ('producer.v2', 'findings.v3'):
            return output_schema('producer' if name.startswith('producer') else 'findings')
        return real(card)
    monkeypatch.setattr(toolbelt, 'output_schema', schema)


# ---- runs, plans and accepted artifacts ------------------------------------------------------

def task_contract(run_dir, prompt=PROMPT):
    """A minimal valid task contract for the run's run-level validators (a fictional request)."""
    from ravel.workflow.task_completion import initial_requirements
    document = {'schema_version': 1, 'prompt': prompt, 'task_mode': 'calculation', 'detector_mode': 'none',
                'stat_mode': 'TBD-judgment', 'required_user_inputs': [], 'assumptions': [], 'compute_plan': 'none',
                'approval_required': True, 'task_requirements': initial_requirements(prompt)}
    target = Path(run_dir) / 'inputs' / 'task_contract.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n')
    return document


def make_step(step_id, *, kind='author', role='baseline-producer', operation=None, depends_on=(), inputs=(),
              outputs=(('outputs/result.json', 'result'),), rung=None, budget=None, review=(), parameters=None,
              graph=None):
    step = {'id': step_id, 'kind': kind, 'role': role, 'operation': operation,
            'inputs': [dict(i) for i in inputs], 'depends_on': list(depends_on),
            'outputs': [{'path': p, 'kind': k, 'required': True} for p, k in outputs],
            'waypoint': False, 'rung': rung, 'budget': dict(budget or {}), 'protocols': [], 'review': list(review),
            'instruction_sources': [], 'obligations': [], 'parameters': dict(parameters or {})}
    if graph is not None:
        step['graph'] = graph
    return step


def toy_comparison_certificate(run_dir):
    """A live artifact-bound central-value comparison of two fixed toy points only."""
    from ravel.validation import certificates

    root = Path(run_dir)

    def write(relative, document):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n')

    def pin(relative):
        return {key: value for key, value in certificates.binding(root, relative).items() if key != 'mode'}

    comparison_context = {'analysis_id': 'toy-comparison', 'quantity': 'value', 'units': 'dimensionless',
                          'basis': {'process': 'toy-model', 'normalization': 'unit'}}
    model_path = 'inputs/toy-comparison/model.json'
    reference_path = 'inputs/toy-comparison/fixed-reference.json'
    plan_path = 'inputs/toy-comparison/r5-plan.json'
    subject_path = 'outputs/toy-comparison/served.json'
    certificate_path = 'outputs/toy-comparison/r5-certificate.json'
    write(model_path, {'model': 'two fixed toy values', 'predictions': [1., 2.], 'mass_gev': [100, 200]})
    references, comparisons = [], []
    for index, (mass, fixed_value) in enumerate([(100, 1.), (200, 2.)]):
        point = {**comparison_context, 'point_id': f'toy-mass-{mass}', 'parameters': {'mass_gev': mass},
                 'reference_id': f'fixed-toy-reference-{mass}'}
        # Fixed independent reference rows and separately recorded predictions; no fit to the references.
        references.append(certificates.measurement(point, fixed_value, quantity='value'))
        prediction_path = f'outputs/toy-comparison/prediction-{mass}.json'
        write(prediction_path, {'validation_point': certificates.measurement(
            point, [1., 2.][index], quantity='value')})
        comparisons.append({'point_id': point['point_id'], 'parameters': point['parameters'],
                            'reference_id': point['reference_id'],
                            'prediction': {'path': prediction_path, 'record_pointer': '/validation_point'},
                            'reference': {'path': reference_path, 'record_pointer': f'/points/{index}'}})
    write(reference_path, {'points': references})
    for comparison in comparisons:
        comparison['reference']['sha256'] = certificates.digest(root / reference_path)
    write(subject_path, {'analysis_id': 'toy-comparison', 'quantity': 'value', 'mass_gev': [100, 200],
                         'predictions': [1., 2.], 'scope': 'fixed toy central values only'})
    write(plan_path, {'schema_version': 1, 'kind': 'r5', **comparison_context,
                      'policy': {'claim': 'central-value', 'relative_tolerance': .01},
                      'dependencies': [pin(model_path)], 'subjects': [subject_path], 'comparisons': comparisons})
    contract_path = root / 'inputs/task_contract.json'
    contract = json.loads(contract_path.read_text())
    contract.setdefault('certification_plans', {})['r5'] = pin(plan_path)
    targets = contract.setdefault('targets', {})
    targets['analysis'] = list(dict.fromkeys([*targets.get('analysis', []), 'toy-comparison']))
    write('inputs/task_contract.json', contract)
    write('inputs/checkin1.json', {'schema_version': 1, 'kind': 'checkin1', 'sections': {
        'i': 'Compare two fixed toy values at masses 100 and 200; no scientific inference.',
        'i-b': 'Fixed toy reference rows and an explicit input model.',
        'ii': 'Static toy comparison subject only.',
        'iii': {'plan': 'No generation; compare the separately recorded toy predictions.',
                'waypoint': 'Both fixed reference comparisons must satisfy tolerance 0.01.'},
        'iv': 'Plan none; no generated events and zero compute walltime budget.',
        'v': [{'id': 'F1', 'text': 'Only fixed central values are compared; no detector or coverage claim.'}],
        'vi': ['answer', 'ask', 'propose']}})
    write('inputs/cost_preflight.json', {'schema_version': 1, 'generated_by': 'cost_preflight.py',
                                       'mode': 'none', 'walltime_h': [0, 0]})
    # The fixture's FakeAuthority replaces package imports in this process. The public CLI
    # records actual scripted assent with the real workflow implementation in a fresh interpreter.
    command = [sys.executable, str(Path(__file__).resolve().parents[3] / 'scripts/run.py'),
               'ravel.workflow.workflow_state', 'approve', '--rundir', str(root), '--plan', 'none',
               '--scripted', '--quote', 'Approved the fixed toy comparison only, with no event generation.']
    approved = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert approved.returncode == 0, approved.stdout + approved.stderr
    certificates.create_certificate(root, plan_path, certificate_path)
    report = certificates.validate_certificate(root, certificate_path, kind='r5', contract=contract,
                                               required_subjects=[subject_path], live=True)
    assert report['status'] == 'PASS', report
    return {'path': certificate_path, 'kind': 'r5', 'required_subjects': [subject_path]}


def install_plan(store, steps, *, revision=0, run_dir=None):
    certificate_check = 'check:validation.certificates.validate_certificate'
    needing_certificate = [step for step in steps
                           if ('integrity-auditor' in (step.get('review') or [])
                               or any(seat.get('role') == 'integrity-auditor' for seat in step.get('seats') or []))
                           and certificate_check not in ((step.get('parameters') or {}).get('check_inputs') or {})]
    if needing_certificate:
        binding = toy_comparison_certificate(run_dir if run_dir is not None else store.run_dir)
        for step in needing_certificate:
            # Mutate the actual dispatched step before copying/digesting the approved plan.
            step.setdefault('parameters', {}).setdefault('check_inputs', {})[certificate_check] = deepcopy(binding)
    plan = {'schema_version': 1, 'kind': 'controller-plan', 'revision': revision,
            'route': {'id': 'judgment', 'version': 1, 'spec_sha256': None}, 'parameters': {},
            'steps': deepcopy(steps), 'deliverables': [], 'waypoints': [], 'checkins': [], 'obligations': [],
            'open_obligations': [], 'instruction_sources': []}
    plan['sha256'] = digest({k: v for k, v in plan.items() if k != 'sha256'})
    blob = store.put_blob(json.dumps(plan, sort_keys=True).encode())
    store.append('plan', {'plan_sha256': plan['sha256'], 'blob': blob, 'source': 'fixture', 'revision': revision})
    # The operator fixture commits materialised operation sources at approval.
    # Invalid plans still reach the production preflight's own refusal checks.
    from ravel.controller.confine import commitments
    try:
        commitments.create(store, plan, run_dir if run_dir is not None else store.run_dir)
    except (OSError, ValueError, TypeError):
        pass
    return plan['sha256']


def context(store, run_dir, plan_sha, **extra):
    from ravel.controller.step import graph as step_graph  # noqa: F401  (the module the tests exercise)
    from ravel.workflow import role_registry
    value = {'run_id': store.run_id, 'run_dir': str(run_dir), 'store_root': str(store.store_root),
             'plan_sha256': plan_sha, 'attempt': 1, 'mode': {}, 'unattended': True,
             'registry_sha256': role_registry.registry_sha256(),
             'agent_preferences': {'schema_version': 1, 'kind': 'agent-preferences',
                                   'transport_preference': ['claude-cli-worker'],
                                   'tier_models': {tier: {'claude-cli-worker': MODEL}
                                                   for tier in ('judgment', 'agent', 'cheap')}}}
    value.update(extra)
    return value


def accepted_artifact(store, run_dir, step_id, path, data, *, kind='result', quantity=None, owner_role=None,
                      complete=True):
    """An artifact a completed predecessor step adopted and its validators accepted."""
    raw = data if isinstance(data, bytes) else json.dumps(data, sort_keys=True).encode()
    relative = f'steps/{step_id}/{path}'
    target = Path(run_dir) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    record = {'schema_version': 1, 'artifact': f'{step_id}:{path}', 'step_id': step_id, 'attempt': 1, 'path': path,
              'destination': relative, 'sha256': sha(raw), 'kind': kind, 'quantity': quantity,
              'owner_role': owner_role, 'producer': {'kind': 'fixture'}, 'inputs': [], 'rung': None,
              'status': 'accepted'}
    store.append('custody', record)
    if complete:
        store.append('step-outcome', {'schema_version': 1, 'step_id': step_id, 'attempt': 1, 'status': 'completed'})
    return {'artifact': record['artifact'], 'sha256': record['sha256']}


def owner_login_files(monkeypatch):
    """Simulate external owner setup before the runtime inspects an inert worker login."""
    from ravel.workflow import sandbox
    from ravel.workflow.transports import cli_worker
    original = cli_worker._cli_home
    def prepared(agent, document, ws):
        if agent == 'claude' and document['auth']['kind'] == 'login':
            private = sandbox.cli_home_for(ws) / 'claude'
            private.mkdir(parents=True, exist_ok=True, mode=0o700)
            login = private / '.credentials.json'
            if not login.exists():
                login.write_text('opaque-owner-fixture')
                login.chmod(0o600)
        return original(agent, document, ws)
    monkeypatch.setattr(cli_worker, '_cli_home', prepared)


@pytest.fixture
def run_env(tmp_path, monkeypatch, services_installed):
    """A run directory, its fake store, isolated custody state and the installed interface fakes."""
    root = Path(os.path.realpath(tmp_path))
    run_dir = root / 'run'
    (run_dir / 'inputs').mkdir(parents=True)
    for name in ('state', 'home', 'claude-login', 'bin'):
        (root / name).mkdir()
    monkeypatch.setenv('RAVEL_STATE_DIR', str(root / 'state'))
    monkeypatch.delenv('RAVEL_WORK_ROOT', raising=False)
    store = FakeStore(root / 'store', run_dir=run_dir)
    owner_login_files(monkeypatch)
    task_contract(run_dir)
    return types.SimpleNamespace(root=root, run_dir=run_dir, store=store, fakes=services_installed)


# ---- the inert worker ------------------------------------------------------------------------

def qualify(store, probe):
    """The operator-run qualification of the fixture transport for ``probe``: retained in the run's store, the only
    qualification a controller seat counts (the same-user file is written for the legacy readers)."""
    from ravel.workflow import transport_registry as tr
    document = tr.load('claude-cli-worker')
    target = tr.qualification_path('claude-cli-worker')
    record = {'schema_version': 1, 'kind': 'transport-qualification', 'transport_id': 'claude-cli-worker',
              'status': 'live_qualified', 'record_path': str(target), 'executable_path': probe['executable_path'],
              'executable_sha256': probe['executable_sha256'], 'declaration_sha256': tr.declaration_sha256(document),
              'probe_sha256': tr.digest(probe), 'receipt': {}, 'observed': {},
              'steps': [{'step': name, 'passed': True} for name in sorted(tr.QUALIFICATION_STEPS)],
              'rundir': 'fixture', 'qualified_utc': '2026-10-17T00:00:00Z'}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record))
    tr.record_qualification(store, record)
    return record


FAKE_CLAUDE = r'''#!{python} -B
import json, os, re, subprocess, sys, uuid
from pathlib import Path
here = Path(__file__).resolve().parent
args = sys.argv[1:]
if args == ['--version']:
    print('fake-cli 9.9.9'); sys.exit(0)
if '--help' in args:
    sys.stdout.write((here / 'help.txt').read_text()); sys.exit(0)
if args == ['auth', 'status', '--json']:
    sys.stdout.write(json.dumps({{'loggedIn': True, 'authMethod': 'claude.ai'}})); sys.exit(0)
scenario = json.loads((here / 'scenario.json').read_text())
prompt = sys.stdin.read()
Path('scratch/prompt.txt').write_text(prompt)
manifest = re.search(r'manifest sha256: ([0-9a-f]{{64}})', prompt).group(1)
duties = re.findall(r'^--- \[duty\] (\S+) (?:sha256:[0-9a-f]{{64}}|index:[0-9]+)$', prompt, re.M)
family = 'findings' if 'schema: findings.v3' in prompt else 'producer'
declared = re.findall(r'^- (outputs/\S+) \(', prompt, re.M)
lines = prompt.splitlines()
spec = json.loads(lines[lines.index('== Step specification (step.v1) ==') + 1])
scenario = {{**scenario, **(scenario.get('seats') or {{}}).get(spec.get('role'), {{}})}}
owed = (spec.get('parameters') or {{}}).get('reviewer_items') or []
entry = json.loads(Path(args[args.index('--mcp-config') + 1]).read_text())['mcpServers']['ravel']
server = subprocess.Popen([entry['command'], *entry['args']], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
def rpc(n, method, params):
    server.stdin.write(json.dumps({{'jsonrpc': '2.0', 'id': n, 'method': method, 'params': params}}) + '\n')
    server.stdin.flush()
    return json.loads(server.stdout.readline())
rpc(1, 'initialize', {{}})
names = [t['name'] for t in rpc(2, 'tools/list', {{}})['result']['tools']]
Path('scratch/tools.json').write_text(json.dumps(names))
n = 10
for call in scenario.get('calls', []):
    n += 1
    reply = rpc(n, 'tools/call', {{'name': call['name'], 'arguments': call.get('arguments', {{}})}})
    with open('scratch/calls.jsonl', 'a') as stream:
        stream.write(json.dumps(reply) + '\n')
writes = scenario.get('writes')
if writes is None:
    writes = [{{'path': p, 'content': json.dumps({{'value': 1, 'path': p}})}} for p in declared]
for item in writes:
    n += 1
    rpc(n, 'tools/call', {{'name': 'ws_write', 'arguments': {{'path': item['path'], 'content': item['content']}}}})
for item in scenario.get('native_writes', []):
    Path(item['path']).parent.mkdir(parents=True, exist_ok=True)
    Path(item['path']).write_text(item['content'])
server.stdin.close(); server.wait()
checklist = [{{'unit': u, 'status': 'done', 'evidence': 'final_record#/kind', 'note': None}} for u in duties]
if scenario.get('ack') == 'omit_row' and checklist:
    checklist = checklist[1:]
if scenario.get('ack') == 'blocked' and checklist:
    checklist[0] = {{'unit': checklist[0]['unit'], 'status': 'blocked', 'evidence': None, 'note': 'input absent'}}
ack = {{'manifest_sha256': manifest if scenario.get('ack') != 'wrong_manifest' else '0' * 64}}
if family == 'findings':
    final = {{'schema_version': 3, 'kind': 'findings', 'items': scenario.get('items', []), 'handoff': None,
             'instruction_ack': ack, 'checklist': checklist,
             'escalation': scenario.get('findings_escalation', scenario.get('escalation', [])),
             'item_verdicts': scenario.get('item_verdicts', [{{'item': i['id'], 'verdict': 'pass',
                                                             'evidence': ['final_record#/kind'], 'note': None}}
                                                            for i in owed])}}
else:
    final = {{'schema_version': 2, 'kind': 'producer-result',
             'outputs': [{{'path': p, 'kind': 'result'}} for p in (declared or ['outputs/none'])],
             'decisions': [], 'knowledge_used': scenario.get('knowledge_used', []), 'handoff': None,
             'instruction_ack': ack, 'checklist': checklist, 'escalation': scenario.get('escalation', [])}}
for key in scenario.get('drop', []):
    final.pop(key, None)
if scenario.get('kill'):
    import signal
    os.kill(os.getpid(), signal.SIGKILL)
session = scenario.get('session') or ('sess-' + uuid.uuid4().hex)
model = scenario.get('model') or '{model}'
print(json.dumps({{'type': 'result', 'subtype': 'success', 'is_error': False, 'result': '',
    'session_id': session, 'num_turns': scenario.get('turns', 3), 'total_cost_usd': 0.0,
    'usage': {{'input_tokens': 100, 'output_tokens': 20}}, 'modelUsage': {{model: {{'outputTokens': 20}}}},
    'structured_output': final}}))
sys.exit(scenario.get('exit', 0))
'''

FLAGS = ['-p', '--output-format', '--model', '--effort', '--json-schema', '--setting-sources', '--restricted',
         '--strict-mcp-config', '--no-session-persistence', '--tools', '--allowedTools', '--max-budget-usd',
         '--mcp-config']


class _Supervisor:
    pid = 2 ** 22 + 11

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


@pytest.fixture
def inert_worker(run_env, monkeypatch):
    """The fake ``claude`` on a trusted test PATH, probed and qualified, with inert sandbox seams."""
    from ravel.workflow import agent_worker, sandbox, transport_registry as tr
    root = run_env.root
    bin_dir = root / 'bin'
    monkeypatch.setenv('HOME', str(root / 'home'))
    monkeypatch.setenv('PATH', f'{bin_dir}:/usr/bin:/bin')
    monkeypatch.setenv('RAVEL_TEST_TRUSTED_BIN', str(bin_dir))
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(root / 'claude-login'))
    (bin_dir / 'help.txt').write_text('Usage\n' + '\n'.join(f'  {f} <x>' for f in FLAGS))
    executable = bin_dir / 'claude'
    executable.write_text(FAKE_CLAUDE.format(python=sys.executable, model=MODEL))
    executable.chmod(0o755)
    scenario = {}

    def set_scenario(**values):
        scenario.clear()
        scenario.update(values)
        (bin_dir / 'scenario.json').write_text(json.dumps(scenario))
    set_scenario()
    monkeypatch.setattr(sandbox, 'available', lambda: 'inert-test-seam')
    monkeypatch.setattr(sandbox, 'probe', lambda *a, **k: {'backend': 'inert-test-seam', 'confirmed': True})
    monkeypatch.setattr(sandbox, 'command', lambda ws, argv, **k: list(argv))
    record = tr.probe('claude-cli-worker', executable=str(executable))
    assert not record['unusable'], record
    qualify(run_env.store, record)
    real_popen = subprocess.Popen

    def popen(argv, **kwargs):
        if 'ravel.workflow.agent_worker' in argv and 'supervise' in argv:
            return _Supervisor()
        return real_popen(argv, **kwargs)
    monkeypatch.setattr(agent_worker.subprocess, 'Popen', popen)
    real_wait = agent_worker._wait_for_completion

    def wait(run, spec, *, wait):
        if not agent_worker._record(run, spec['node_id'], spec['attempt'])['receipt']:
            agent_worker.supervise(run, spec['node_id'], spec['attempt'])
        return real_wait(run, spec, wait=wait)
    monkeypatch.setattr(agent_worker, '_wait_for_completion', wait)
    real_alive = agent_worker._group_alive
    monkeypatch.setattr(agent_worker, '_group_alive',
                        lambda pgid: False if pgid in (os.getpgrp(), _Supervisor.pid) else real_alive(pgid))
    monkeypatch.setattr(agent_worker.signal, 'signal', lambda *a: None)
    return types.SimpleNamespace(scenario=set_scenario, executable=executable, probe=record, bin=bin_dir)


def run_step(env, step, plan_steps=None, **extra):
    """Install the plan, then run one attempt of ``step`` through ``step.run``."""
    from ravel.controller import step as governed
    plan_sha = install_plan(env.store, plan_steps if plan_steps is not None else [step])
    ctx = context(env.store, env.run_dir, plan_sha, **extra)
    return governed.run(env.store, step, ctx)


def records(store, kind):
    return store.records(kind)


@contextmanager
def registered_graphs():
    """The controller.step and controller.seat rows: the installed fragment, or registered for the block."""
    from ravel.workflow import graph_registry
    rows = json.loads((Path(__file__).resolve().parents[3] / 'src/ravel/data/graphs/registration/controller.step.json')
                      .read_text())['graphs']
    missing = []
    for row in rows:
        try:
            graph_registry.get(row['id'])
        except graph_registry.RegistryError:
            missing.append(row)
    if not missing:
        yield rows
        return
    with graph_registry.registered(*missing):
        yield rows


@pytest.fixture
def graphs():
    with registered_graphs() as rows:
        yield rows


def test_support_fakes_keep_the_binding_signatures():
    import inspect
    assert list(inspect.signature(FakeLedger.materialise).parameters) == ['self', 'store', 'stage', 'context']
    assert list(inspect.signature(FakeLedger.record).parameters) == ['self', 'store', 'entry_id', 'status', 'evidence']
    assert list(inspect.signature(FakeInstructions.packet).parameters) == ['self', 'manifest', 'card', 'step', 'inputs']
    assert list(inspect.signature(FakeInstructions.check_ack).parameters) == ['self', 'manifest', 'final_record',
                                                                              'outputs']
    assert list(inspect.signature(FakeAuthority.request).parameters) == ['self', 'store', 'kind', 'subject', 'bounds']
    assert list(inspect.signature(FakeConfine.popen).parameters) == ['self', 'spec', 'kwargs']
    assert re.fullmatch(r'[a-z][a-z0-9-]{2,63}', RUN_ID)
