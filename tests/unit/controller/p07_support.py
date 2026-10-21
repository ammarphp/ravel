"""Fakes and fictional runs for the sole-sink tests (P07). No model, provider, network or native tool.

The fakes keep the published shapes and refusal rules of the packages the sink consumes, so a
test cannot pass on evidence the real packages would refuse:

- ``FakeStore``: the run store's record envelopes, blobs, binding and chain checks (P01).
- ``FakeLedger``: the obligation ledger's materialisation, evidence rules (R rows need a credit,
  L violations a label, waivers an authority record that names the row), the delivery decisions
  and the ``deliver[accepted]`` gate over every current instance (P02).
- ``FakeAuthority`` (P06) and ``ISSUER_RECEIPT`` (its issuer's own description), ``FakeConfine`` (P05
  code identity), ``fake_store_module`` (ownership).
- ``FakeEngagement``: the engagement policy's decision, delivery-stage envelope check over the
  dispatch census (one observation, session and reported usage per dispatch, the instruction
  packet delivered to that session, the input and call floors) and the receipt section that allows
  acceptance only for a current passing check (P18).
- ``Run.governance_label``: host governance's label over the store's ownership claim (P14).

``Run`` builds a fictional controller run: its directory and marker, the store records the
controller's nodes write (request, intake, mode, engagement decision, plan, custody, launches with
their probe qualification, worker sessions, validations, credits, review rounds, budgets) and the
adopted bytes. ``Run.complete()`` adds the evidence of a fully governed run; tests then remove or
alter exactly one piece.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import itertools
import json
import os
from pathlib import Path
import sys
import time
import types
from urllib.parse import quote

import pytest

RUN_ID = 'run-fixture-p07'
PROMPT = ('Estimate the yield of a fictional widget process in a toy model and report the value with '
          'its uncertainty, and a summary report.')
CLASSES = {'A12': 'E', 'T10': 'E', 'B03': 'E', 'B04': 'L', 'C06': 'L', 'C22': 'E', 'C27': 'E', 'C33': 'E',
           'D01': 'L', 'D02': 'L', 'D03': 'R', 'D05': 'E', 'D06': 'E', 'D07': 'E', 'D08': 'E', 'E11': 'L', 'E15': 'L',
           'E19': 'L', 'E20': 'L', 'E25': 'E', 'E26': 'E', 'E27': 'E', 'GATE-delivery': 'E', 'GATE-final_task': 'E',
           'GATE-report_integrity': 'E', 'GATE-export': 'E', 'JR10': 'E', 'X-UPSTREAM': 'E', 'X-REVIEW': 'R'}
DELIVER_RUN = ('A12', 'B04', 'C06', 'C33', 'E11', 'E15', 'E19', 'E27', 'GATE-delivery', 'GATE-final_task', 'T10')
DELIVER_ARTIFACT = ('C22', 'C27', 'D01', 'D02', 'D03', 'D05', 'D06', 'D07', 'D08', 'E20', 'E25', 'E26')
INTAKE_ROWS = ('B03', 'JR10', 'X-UPSTREAM')
NODES = {'B03': 'controller.bounded_end', 'JR10': 'controller.bounded_end'}
WAIVABLE = ('D02',)
EVIDENCE_KEYS = ('receipt', 'artifact', 'sha256', 'validator', 'credit', 'authority', 'instruction_receipt', 'ack',
                 'mechanism', 'covered_by', 'gate', 'probe', 'record')
ALLOWED = {'pending': ('satisfied', 'violated', 'waived', 'not_applicable'), 'satisfied': ('satisfied', 'violated'),
           'waived': ('violated',), 'not_applicable': ('violated',), 'violated': ()}
SCOPE_FIELDS = ('step', 'point', 'seat', 'attempt', 'deliverable', 'artifact', 'claim', 'event')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


# ---- the run store (P01 shape) -----------------------------------------------------------------

class FakeStore:
    def __init__(self, root, run_id=RUN_ID):
        self.run_id = run_id
        self.store_root = Path(os.path.realpath(root))
        self.root = self.store_root / run_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.entries = []
        self.tampered = []

    def append(self, kind, record):
        json.dumps(record, allow_nan=False)
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
        return [deepcopy(e) for e in self.entries if e['kind'] == kind]

    def latest(self, kind):
        rows = self.scan(kind)
        return rows[-1] if rows else None

    def head(self):
        return {'seq': len(self.entries), 'digest': self.entries[-1]['digest'] if self.entries else '0' * 64}

    def path(self, *parts):
        return self.root.joinpath(*parts)

    def put_blob(self, data):
        key = sha(data)
        target = self.root / 'blobs' / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return key

    def get_blob(self, key):
        data = (self.root / 'blobs' / key).read_bytes()
        if sha(data) != key:
            raise ValueError(f'blob {key} was altered')
        return data

    def run_record(self):
        rows = self.scan('run')
        return rows[0]['record'] if rows else None

    @property
    def run_dir(self):
        record = self.run_record()
        return Path(record['run_dir']) if record else None

    def check_binding(self, run_dir=None):
        record = self.run_record()
        if record is None:
            return ['no binding record']
        bound = Path(record['run_dir'])
        if not bound.is_dir() or bound.is_symlink():
            return [f'the run directory {bound} is missing']
        marker = bound / 'controller-run.json'
        try:
            claim = json.loads(marker.read_text())
        except (OSError, ValueError):
            claim = None
        if type(claim) is not dict or claim.get('run_id') != self.run_id:
            return ['the run directory marker is missing or names another run']
        return []

    def verify(self):
        return list(self.tampered)


def fake_store_module(owned):
    """``ravel.controller.store`` with ``controller_owned`` over ``{run directory: store}``."""
    module = types.ModuleType('ravel.controller.store')

    class StoreError(ValueError):
        pass

    def controller_owned(path):
        target = Path(os.path.realpath(Path(path)))
        for run_dir, store in owned.items():
            root = Path(os.path.realpath(run_dir))
            if target == root or root in target.parents:
                return store.run_id
        return None

    def store_for(run_dir):
        target = Path(os.path.realpath(Path(run_dir)))
        for root, store in owned.items():
            if Path(os.path.realpath(root)) == target:
                return store
        raise StoreError(f'{run_dir} carries no controller-run marker')

    module.controller_owned = controller_owned
    module.store_for = store_for
    module.StoreError = StoreError
    return module


# ---- the obligation ledger (P02 shape and rules) ----------------------------------------------------

class LedgerError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class FakeLedger:
    """The ledger rules the sink depends on, kept as strict as the real package."""

    def __init__(self, store, deliverables=()):
        self.store = store
        self.instances = {}
        self.order = []
        self.deliver_keys = []
        self.expected = list(deliverables)
        self.covered = set()
        self.refuse = {}
        self.calls = []
        self.events = 0

    @staticmethod
    def instance_key(row, run_id, scope):
        parts = [f'{row}@{quote(run_id, safe="-_.~:+#")}']
        for name in SCOPE_FIELDS:
            if scope.get(name) is not None:
                parts.append(f'{name}={quote(str(scope[name]), safe="-_.~:+#")}')
        return '/'.join(parts)

    def _add(self, row, scope, stage):
        key = self.instance_key(row, self.store.run_id, scope)
        if key not in self.instances:
            self.instances[key] = {'key': key, 'id': row, 'scope': scope, 'stage': stage, 'status': 'pending',
                                   'evidence': None}
            self.order.append(key)
        return key

    def materialise(self, store, stage, context):
        self.calls.append(('materialise', stage, deepcopy(context)))
        if stage == 'intake':
            return [self._add(row, {}, 'intake') for row in INTAKE_ROWS]
        if stage == 'deliver':
            for artifact in context.get('artifacts') or []:
                if type(artifact) is not str or not artifact:
                    raise LedgerError('context_invalid', 'artifact must be a non-empty string')
            keys = [self._add(row, {}, 'deliver') for row in DELIVER_RUN]
            for artifact in context.get('artifacts') or []:
                keys += [self._add(row, {'artifact': artifact}, 'deliver') for row in DELIVER_ARTIFACT]
            self.deliver_keys = keys
            self.events += 1
            return list(keys)
        if stage == 'event':
            row = {'report_integrity': 'GATE-report_integrity', 'export': 'GATE-export'}[context['kind']]
            return [self._add(row, {'event': context['id']}, 'event')]
        raise LedgerError('stage_unknown', stage)

    def check(self, key, status, evidence):
        instance = self.instances.get(key)
        if instance is None:
            raise LedgerError('entry_unknown', f'ledger entry {key} was never materialised')
        cls = CLASSES[instance['id']]
        if status not in ALLOWED[instance['status']]:
            raise LedgerError('transition_refused', f"{key} cannot go from {instance['status']} to {status}")
        if type(evidence) is not dict:
            raise LedgerError('evidence_invalid', 'evidence must be an object')
        json.dumps(evidence, allow_nan=False)
        present = lambda k: evidence.get(k) not in (None, '', [], {}, False)  # noqa: E731
        if status == 'satisfied':
            if not any(present(k) for k in EVIDENCE_KEYS):
                raise LedgerError('evidence_missing', f'{key}: satisfied needs evidence')
            if cls == 'R' and not present('credit'):
                raise LedgerError('credit_missing', f'{key}: a review-gated row needs a credit')
        elif status == 'violated':
            if not str(evidence.get('reason') or '').strip():
                raise LedgerError('reason_missing', f'{key}: a violation needs a reason')
            if cls == 'L' and not str(evidence.get('label') or '').strip():
                raise LedgerError('label_missing', f'{key}: a labelled row records its label')
        elif status == 'not_applicable':
            if not str(evidence.get('reason') or '').strip():
                raise LedgerError('reason_missing', f'{key}: not applicable needs a reason')
            if cls == 'R' and not present('credit'):
                raise LedgerError('credit_missing', f'{key}: the reason an R row does not apply is reviewed')
        elif status == 'waived':
            if instance['id'] not in WAIVABLE:
                raise LedgerError('waiver_refused', f"{instance['id']}: nobody may waive it")
            authority = evidence.get('authority')
            found = [r['record'] for r in self.store.scan('authority') if r['record'].get('uid') == authority]
            if not found or found[-1].get('label') not in ('physicist_terminal_response', 'operator_command') or \
                    instance['id'] not in (found[-1].get('subject') or {}).get('obligations', []):
                raise LedgerError('waiver_refused', f'{key}: no authority record waives it')

    def record(self, store, entry_id, status, evidence):
        self.check(entry_id, status, evidence)
        self.instances[entry_id].update(status=status, evidence=deepcopy(evidence))
        self.calls.append(('record', entry_id, status))

    def record_many(self, store, changes):
        changes = list(changes)
        for key, status, evidence in changes:
            self.check(key, status, evidence)
        for key, status, evidence in changes:
            self.instances[key].update(status=status, evidence=deepcopy(evidence))
            self.calls.append(('record', key, status))

    def pending(self, store, *, node=None, stage=None, **_):
        return [k for k in self.order if self.instances[k]['status'] == 'pending'
                and (node is None or NODES.get(self.instances[k]['id']) == node)
                and (stage is None or self.instances[k]['stage'] == stage)]

    @staticmethod
    def met(instance):
        cls, status, evidence = CLASSES[instance['id']], instance['status'], instance['evidence'] or {}
        if status == 'satisfied':
            return not (cls == 'R' and not evidence.get('credit'))
        if status == 'not_applicable':
            return not (cls == 'R' and not evidence.get('credit'))
        if status == 'waived':
            return instance['id'] in WAIVABLE
        if status == 'violated':
            return cls == 'L' and bool(evidence.get('label'))
        return False

    def unmet(self, *, exclude=()):
        out = []
        for key in self.order:
            instance = self.instances[key]
            if instance['id'] in exclude or self.met(instance):
                continue
            out.append({'entry': key, 'id': instance['id'], 'status': instance['status'],
                        'reason': instance['status'], 'consequence': 'qualified' if instance['id'] in WAIVABLE
                        else 'diagnostic', 'message': f"{instance['id']} is {instance['status']}"})
        for deliverable in self.expected:
            if deliverable not in self.covered:
                out.append({'entry': f'deliverable:{deliverable}', 'id': None, 'status': 'absent',
                            'reason': 'deliverable_not_covered', 'consequence': 'qualified',
                            'message': f'original obligation {deliverable} is not covered'})
        return out

    def gate(self, store, transition):
        self.calls.append(('gate', transition))
        name = transition.replace('->', '→')
        if name in ('deliver[qualified]', 'deliver[diagnostic]', 'bounded_end→deliver'):
            return []
        if name == 'deliver[accepted]':
            if not self.deliver_keys:
                return [{'entry': 'stage:deliver', 'reason': 'stage_not_materialised', 'consequence': 'qualified',
                         'message': 'deliver was never materialised'}]
            return self.unmet()
        raise ValueError(f'unknown transition {transition}')

    def decide(self, store, rundir, gate_name, action):
        self.calls.append(('decide', gate_name, deepcopy(action)))
        own = ('GATE-delivery', 'GATE-final_task', 'GATE-report_integrity', 'GATE-export')
        if action.get('event'):  # the occurrence is materialised before the gate is asked
            self.materialise(store, 'event', {'kind': gate_name, 'id': action['event']})
        if gate_name in self.refuse:
            return list(self.refuse[gate_name])
        unmet = self.unmet(exclude=own)
        if unmet:
            return [{'code': 'ledger_' + u['reason'], 'provider': 'ledger', 'message': u['message']} for u in unmet[:5]]
        row = f'GATE-{gate_name}'
        for key in self.order:
            instance = self.instances[key]
            if instance['id'] == row and instance['status'] == 'pending' and \
                    (instance['scope'].get('event') == action.get('event')):
                self.record(store, key, 'satisfied', {'gate': gate_name, 'mechanism': 'decision_gate.check'})
        return []

    def summary(self, store):
        counts = {s: 0 for s in ALLOWED}
        by_class = {}
        violations, waivers = [], []
        for key in self.order:
            instance = self.instances[key]
            counts[instance['status']] += 1
            cls = CLASSES[instance['id']]
            by_class.setdefault(cls, {s: 0 for s in ALLOWED})[instance['status']] += 1
            if instance['status'] == 'violated':
                violations.append({'entry': key, 'id': instance['id'], 'class': cls,
                                   'label': (instance['evidence'] or {}).get('label'),
                                   'reason': (instance['evidence'] or {}).get('reason')})
            if instance['status'] == 'waived':
                waivers.append({'entry': key, 'id': instance['id'], 'authority': instance['evidence'].get('authority')})
        return {'schema': 'ledger-summary.v1', 'run_id': store.run_id, 'head': digest(self.instances),
                'events': len(self.calls), 'chain': {'verified': True, 'error': None}, 'instances': len(self.order),
                'by_status': counts, 'by_class': by_class, 'by_ledger_class': {}, 'refusals': 0,
                'refusal_events': [], 'waivers': waivers, 'violations': violations, 'not_applicable': [],
                'deliverables': {'expected': list(self.expected),
                                 'open': [d for d in self.expected if d not in self.covered]}}

    def instances_listing(self, store):
        return [{'id': i['id'], 'key': k, 'status': i['status'], 'scope': i['scope'],
                 'reason': (i['evidence'] or {}).get('reason')} for k, i in self.instances.items()]

    @staticmethod
    def population_equality(expected, actual):
        """The holes: members of ``expected`` that ``actual`` lacks, with multiplicity, in expected order."""
        for values in (expected, actual):
            if not isinstance(values, (list, tuple)) or not all(isinstance(v, str) for v in values):
                raise TypeError('populations must be lists of strings')
        available, holes = {}, []
        for member in actual:
            available[member] = available.get(member, 0) + 1
        for member in expected:
            if available.get(member, 0) > 0:
                available[member] -= 1
            else:
                holes.append(member)
        return holes


def ledger_module(ledger, *, listing=True):
    module = types.ModuleType('ravel.controller.ledger')
    for name in ('materialise', 'record', 'record_many', 'pending', 'gate', 'decide', 'summary', 'instance_key',
                 'population_equality'):
        setattr(module, name, getattr(ledger, name))
    if listing:
        module.instances = ledger.instances_listing
    module.LedgerError = LedgerError
    return module


# ---- authority (P06 shape) and code identity (P05 shape) ---------------------------------------

class FakeAuthority:
    def __init__(self):
        self.notified = []
        self.stop = 'running'

    def records(self, store):
        return [{k: e['record'].get(k) for k in ('uid', 'kind', 'decision', 'option', 'label', 'source', 'time_ns',
                                                 'authorizes_effects', 'request')} | {'id': e['record'].get('uid')}
                for e in store.scan('authority')]

    def disposition(self, store, record_id, *, kind, subject):
        """Authenticate current controller-held fictional authority and plan pins."""
        if not isinstance(record_id, str) or not record_id:
            raise ValueError('no authority identity')
        rows = store.scan('authority')
        matches = [e for e in rows if record_id in (e['id'], e['record'].get('uid'))]
        if len(matches) != 1:
            raise ValueError('authority identity is not unique in the controller store')
        entry, = matches
        body = entry['record']
        current = [e for e in rows if e['record'].get('kind') == kind]
        if not current or current[-1]['id'] != entry['id'] or body.get('kind') != kind:
            raise ValueError('authority is stale or names another kind')
        if body.get('run_id') != store.run_id:
            raise ValueError('authority belongs to another run')
        if body.get('label') not in ('operator_configured_machine', 'delegated_machine', 'operator_command'):
            raise ValueError('terminal or unattested authority authorizes nothing')
        if self.stop != 'running':
            raise ValueError('authority is stopped or revoked')
        plans = [e['record'] for e in store.scan('plan')
                 if e['record'].get('source') != 'judgment-planning']
        if not isinstance(subject, dict) or not plans or not subject.get('plan_sha256') or \
                plans[-1].get('plan_sha256') != subject['plan_sha256']:
            raise ValueError('authority does not bind the current delivered plan')
        pins = (body.get('subject') or {}).get('pins') or {}
        if any(pins.get(name) != value for name, value in subject.items()):
            raise ValueError('authority subject pins changed')
        return {**deepcopy(body), 'id': body['uid']}

    def verify(self, store, record_id, *, kind, subject=None):
        body = self.disposition(store, record_id, kind=kind, subject=subject)
        if body.get('authorizes_effects') is not True or body.get('decision') != 'approve':
            raise ValueError('authority does not approve effects')
        return body

    def frozen(self, store, *, required=True):
        rows = store.scan('mode')
        if not rows:
            if required:
                raise ValueError('no mode')
            return None
        body = deepcopy(rows[-1]['record'])
        return {**body, 'id': body['uid']}

    def effective_bounds(self, store):
        mode = self.frozen(store)
        return {'budgets': deepcopy(mode.get('budgets') or {}), 'bounds': deepcopy(mode.get('bounds') or {})}

    def deviations(self, store):
        return [{'id': e['record']['uid'], 'decision': e['record']['decision'], 'label': e['record']['label'],
                 'change': (e['record'].get('subject') or {}).get('change')}
                for e in store.scan('authority') if e['record'].get('kind') == 'deviation']

    def stop_state(self, store):
        return self.stop

    def notify(self, store, message):
        self.notified.append(message)
        return {'status': 'sent'}

    def operator_config(self):
        return {'mode': 'autonomous', 'procedure_byte_ceiling': 2048}


ISSUER_RECEIPT = {'issuer_authentication': 'hmac-sha256', 'key_location': 'operator-only; outside run stores',
                  'confinement_required': True, 'terminal_identity_attested': False,
                  'same_user_risk': 'An unconfined process with the operator uid can read the key and issue authority. '
                                    'Isolation from that attacker requires a separate OS identity or external issuer.',
                  'confinement_qualification': 'requires the confined-launch owner denial probe'}


class FakeEngagement:
    """The engagement policy's records and rules the sink depends on (P18 shape)."""

    DECISION, CHECK, ESCALATION = 'engagement-decision', 'envelope-check', 'engagement-escalation'
    PACKET_FRACTION = 0.8
    COMPLETED = ('completed', 'succeeded', 'ok')

    def __init__(self):
        self.stages = []

    @staticmethod
    def rows(store, kind):
        return [{**deepcopy(e['record']), 'record_id': e['id']} for e in store.scan(kind)]

    def append(self, store, kind, body):
        body = deepcopy(body)
        body['schema'] = kind + '.v1'
        body['sha256'] = digest(body)
        body['record_id'] = store.append(kind, {k: v for k, v in body.items() if k != 'record_id'})
        return body

    @staticmethod
    def verify(record):
        if record.get('sha256') != digest({k: v for k, v in record.items() if k not in ('sha256', 'record_id')}):
            raise ValueError('engagement record digest mismatch')

    def decide(self, store, *, tier='standard', expected=None):
        expected = expected if expected is not None else {'status': 'ready', 'floor': {'sessions': 0}}
        return self.append(store, self.DECISION, {'tier': tier, 'policy_sha256': 'e' * 64, 'facts': {}, 'reasons': [],
                                                  'seat_plan_sha256': digest({'tier': tier}),
                                                  'envelopes': {tier: expected}})

    def tier(self, store):
        decisions = self.rows(store, self.DECISION)
        return decisions[-1]['tier'] if decisions else 'full'

    @staticmethod
    def identity(row):
        return (row.get('node_id') or row.get('step_id'), row.get('seat'), row.get('attempt'))

    def census(self, store):
        return {'dispatches': self.rows(store, 'step-dispatch'), 'observations': self.rows(store, 'step-observation'),
                'deliveries': [r for r in self.rows(store, 'instruction-delivery')
                               if r.get('kind') == 'instruction-delivery-session'],
                'settlements': self.rows(store, 'budget-settlement')}

    def check_envelope(self, store, stage, broker=None):
        if stage not in ('wave', 'deliver'):
            raise ValueError('envelope stage must be wave or deliver')
        self.stages.append(stage)
        census = self.census(store)
        decisions = self.rows(store, self.DECISION)
        decision = decisions[-1] if decisions else None
        expected = ((decision or {}).get('envelopes') or {}).get(self.tier(store))
        failures, unknown, keys, sessions = [], [], set(), set()
        for dispatched in census['dispatches']:
            key = self.identity(dispatched)
            found = [o for o in census['observations'] if self.identity(o) == key]
            if key in keys or len(found) != 1:
                failures.append(f'{key}: duplicate dispatch or not exactly one session observation')
                keys.add(key)
                continue
            keys.add(key)
            observation, usage = found[0], found[0].get('usage') or {}
            session = observation.get('session_id')
            if not session or session in sessions:
                failures.append(f'{key}: missing or reused session identity')
                continue
            sessions.add(session)
            if usage.get('reported') is not True or not all(type(usage.get(k)) is int and usage[k] >= 0
                                                            for k in ('turns', 'input_tokens', 'output_tokens')):
                unknown.append(f'{key}: transport usage unreported or invalid')
                continue
            packets = [d for d in census['deliveries'] if self.identity(d) == key and d.get('session', session) == session]
            tokens = dispatched.get('packet_tokens')
            if type(tokens) is not int and len(packets) == 1:
                tokens = packets[0].get('packet_tokens')
            if len(packets) != 1 or packets[0].get('packet_sha256') != dispatched.get('packet_sha256') \
                    or type(tokens) is not int or tokens <= 0:
                unknown.append(f'{key}: missing or inconsistent instruction delivery')
                continue
            if usage['input_tokens'] < self.PACKET_FRACTION * tokens:
                failures.append(f'{key}: input below packet floor')
            producer = dispatched.get('purpose', 'producer' if dispatched.get('seat') in (None, 'producer')
                                      else 'review') == 'producer'
            if usage['turns'] < (2 if producer and observation.get('status') in self.COMPLETED else 1):
                failures.append(f'{key}: fewer model calls than the floor')
        failures += [f'{self.identity(o)}: observation has no dispatch' for o in census['observations']
                     if self.identity(o) not in keys]
        if (expected or {}).get('status') != 'ready':
            unknown.append('envelope unavailable')
        elif stage == 'deliver' and len(sessions) < expected['floor']['sessions']:
            failures.append('fewer observed sessions than the seat floor')
        if not census['dispatches'] and (not expected or expected.get('floor', {}).get('sessions', 1) > 0):
            failures.append('dispatch census empty')
        labels = (['ENGAGEMENT BELOW FLOOR'] if failures else []) + (['USAGE UNKNOWN'] if unknown else [])
        return self.append(store, self.CHECK, {
            'stage': stage, 'status': 'below_floor' if failures else 'unknown' if unknown else 'ok',
            'failures': failures, 'unknown': unknown, 'labels': labels, 'accepted_allowed': not (failures or unknown),
            'tier': self.tier(store), 'decision_id': (decision or {}).get('record_id'),
            'usage_sha256': digest(census), 'escalation_sha256': digest(self.rows(store, self.ESCALATION))})

    def receipt_section(self, store):
        decisions = self.rows(store, self.DECISION)
        decision = decisions[-1] if decisions else None
        escalations, checks = self.rows(store, self.ESCALATION), self.rows(store, self.CHECK)
        for record in ([decision] if decision else []) + escalations + checks:
            self.verify(record)
        last = checks[-1] if checks else None
        delivery = last if last and last['stage'] == 'deliver' else None
        if delivery and (delivery['usage_sha256'] != digest(self.census(store))
                         or delivery['escalation_sha256'] != digest(escalations)
                         or delivery['decision_id'] != (decision or {}).get('record_id')
                         or delivery['tier'] != self.tier(store)):
            delivery = None
        labels = sorted({label for check in checks for label in check['labels']})
        if not delivery:
            labels = sorted(set(labels) | {'USAGE UNKNOWN'})
        allowed = bool(decision and delivery and delivery['accepted_allowed'])
        return {'tier': self.tier(store), 'decision_id': (decision or {}).get('record_id'),
                'policy_sha256': (decision or {}).get('policy_sha256'), 'facts': (decision or {}).get('facts', {}),
                'reasons': (decision or {}).get('reasons', []),
                'seat_plan_sha256': (decision or {}).get('seat_plan_sha256'), 'escalations': escalations,
                'envelope_checks': checks, 'envelope_status': last['status'] if last else 'unknown', 'labels': labels,
                'accepted_allowed': allowed, 'architecture_complete_allowed': allowed}


class FakeConfine:
    def __init__(self, kind='installed'):
        self.kind = kind

    def code_identity(self, *, digest=True):
        return {'package_dir': '/fictional/site-packages/ravel', 'kind': self.kind, 'version': '1.3.0',
                'checkout': None, 'writable_by_controller_user': False, 'selectors': {},
                'digest': 'record:' + '1' * 64}

    def require_governed_install(self, *, development=False, identity=None):
        identity = dict(identity or self.code_identity())
        problems = [] if identity['kind'] == 'installed' else [f"RAVEL runs from {identity['kind']} code"]
        identity.update(governed=not problems, label='NOT GOVERNED' if problems else None, problems=problems)
        return identity


def module_of(name, obj, attributes):
    """A stand-in for module ``name`` exposing ``attributes`` of ``obj``. A stand-in for a package keeps the
    real package's search path, so the production submodules it owns (for example the resource mechanisms
    under the confinement package) still import from their real files."""
    module = types.ModuleType(name)
    package_path(module)
    for attribute in attributes:
        setattr(module, attribute, getattr(obj, attribute))
    return module


def package_path(module):
    """Give a stand-in module the real package's ``__path__`` when the real import target is a package."""
    import importlib
    try:
        real = importlib.import_module(module.__name__)
    except ImportError:
        return module
    if hasattr(real, '__path__'):
        module.__path__ = list(real.__path__)
    return module


# ---- a fictional controller run --------------------------------------------------------------------

READING = {'deliverables': [{'id': 'd-value', 'claim_kind': 'estimate', 'artifact': {'kind': 'number'}},
                            {'id': 'd-report', 'claim_kind': None, 'artifact': {'kind': 'document'}}],
           'constraints': [], 'facts': [], 'boundaries': []}
CONTRACT = {'task_mode': 'calculation', 'prompt': PROMPT}
VALUE = {'value': 41.7, 'uncertainty': 2.3, 'units': 'events', 'statistic': 'central value with standard error'}
REPORT = ('# Widget yield\n\nThe estimated yield is 41.7 events with an uncertainty of 2.3 events.\n\n'
          '| Quantity | Value |\n|---|---|\n| yield | 41.7 |\n| uncertainty | 2.3 |\n')


class Run:
    """A fictional controller run with every record the controller's nodes write."""

    def __init__(self, tmp_path, monkeypatch, *, reading=None, identity='installed', listing=True):
        self.tmp = Path(tmp_path)
        self.dir = self.tmp / 'runs' / RUN_ID
        self.dir.mkdir(parents=True)
        (self.dir / 'controller-run.json').write_text(json.dumps({'run_id': RUN_ID, 'kind': 'controller-run-marker'}))
        self.store = FakeStore(self.tmp / 'controller-store')
        self.reading = deepcopy(reading if reading is not None else READING)
        self.ledger = FakeLedger(self.store, [d['id'] for d in self.reading['deliverables']])
        self.authority = FakeAuthority()
        self.confine = FakeConfine(identity)
        self.engagement = FakeEngagement()
        self.host_findings, self.host_events = [], []
        self.uids = itertools.count(1)
        self.steps = []
        self.deliverables = []
        self.plan_doc = None
        self.install(monkeypatch, listing=listing)
        self.store.append('run', {'schema_version': 1, 'kind': 'controller-run', 'run_id': RUN_ID,
                                  'run_dir': str(self.dir), 'store_root': str(self.store.store_root)})
        request = self.store.put_blob(PROMPT.encode())
        self.store.append('request', {'sha256': request, 'channel': 'terminal', 'bytes': len(PROMPT),
                                      'unattended': False})
        contract = dict(CONTRACT)
        self.store.append('intake', {'request_sha256': request, 'channel': 'terminal',
                                     'contract_blob': self.store.put_blob(json.dumps(contract).encode()),
                                     'reading_blob': self.store.put_blob(json.dumps(self.reading).encode()),
                                     'task_mode': contract['task_mode']})
        self.store.append('mode', {'schema': 'operating-mode.v1', 'uid': self.uid(), 'run_id': RUN_ID,
                                   'mode': 'autonomous', 'delegation': 'operator_configured',
                                   'operator_source': 'operator_ledger', 'allow_unconfined': False})
        self.engagement.decide(self.store)
        self.ledger.materialise(self.store, 'intake', {'run_id': RUN_ID})

    def install(self, monkeypatch, *, listing=True):
        monkeypatch.setitem(sys.modules, 'ravel.controller.ledger', ledger_module(self.ledger, listing=listing))
        monkeypatch.setitem(sys.modules, 'ravel.controller.authority', module_of(
            'ravel.controller.authority', self.authority,
            ('records', 'verify', 'disposition', 'frozen', 'effective_bounds', 'deviations', 'stop_state', 'notify', 'operator_config')))
        issuer = types.ModuleType('ravel.controller.authority.issuer')
        issuer.receipt = lambda: deepcopy(ISSUER_RECEIPT)
        monkeypatch.setitem(sys.modules, 'ravel.controller.authority.issuer', issuer)
        monkeypatch.setitem(sys.modules, 'ravel.controller.confine', module_of(
            'ravel.controller.confine', self.confine, ('code_identity', 'require_governed_install')))
        monkeypatch.setitem(sys.modules, 'ravel.controller.engagement', module_of(
            'ravel.controller.engagement', self.engagement, ('check_envelope', 'receipt_section', 'tier')))
        monkeypatch.setitem(sys.modules, 'ravel.controller.store', fake_store_module({self.dir: self.store}))
        from ravel.workflow import host_governance
        monkeypatch.setattr(host_governance, 'governance_label', self.governance_label, raising=False)
        for absent in ('ravel.controller.step.budget', 'ravel.controller.routes.analysis.fidelity',
                       'ravel.controller.routes.manuscript', 'ravel.controller.routes.manuscript.staged',
                       'ravel.controller.routes.ml.staged'):
            monkeypatch.setitem(sys.modules, absent, None)

    def governance_label(self, rundir, project=None, environ=None):
        """Host governance's object (P14 shape): NOT GOVERNED unless the store module says the controller owns it."""
        store_module = sys.modules.get('ravel.controller.store')
        owner = store_module.controller_owned(Path(rundir)) if store_module is not None else None
        reasons = [] if owner else ['unrestricted_host']
        recorded = {c for e in self.host_events if e['kind'] == 'observed' for c in e.get('codes') or ()}
        recorded |= {e['kind'] for e in self.host_events if e['kind'] != 'observed'}
        reasons += sorted({f['code'] for f in self.host_findings} | recorded)
        return {'label': None if owner else 'NOT GOVERNED', 'controller_run': owner, 'reasons': reasons,
                'host_findings': deepcopy(self.host_findings), 'host_events': deepcopy(self.host_events)}

    def uid(self):
        return f'uid-{next(self.uids):04d}'

    # -- plan, steps and adoption --

    def add_step(self, step_id, outputs, *, kind='operate', inputs=(), deliverables=(), parameters=None):
        step = {'id': step_id, 'kind': kind, 'inputs': [{'artifact': a, 'sha256': None} for a in inputs],
                'outputs': [{'path': p, 'kind': 'artifact', 'required': True} for p in outputs],
                'depends_on': sorted({a.split(':', 1)[0] for a in inputs if ':' in a}), 'waypoint': False,
                'rung': None, 'budget': {}, 'protocols': [], 'review': [], 'instruction_sources': [],
                'obligations': [], 'parameters': parameters or {}}
        self.steps.append(step)
        for deliverable, output in deliverables:
            self.deliverables.append({'id': deliverable, 'status': 'mapped', 'step': step_id, 'output': output,
                                      'claim_kind': next((d.get('claim_kind') for d in self.reading['deliverables']
                                                          if d['id'] == deliverable), None),
                                      'artifact_kind': None})
        return step

    def pin_plan(self, *, extra_open=()):
        plan = {'schema_version': 1, 'kind': 'controller-plan', 'revision': 0,
                'route': {'id': 'judgment', 'version': 1, 'spec_sha256': None}, 'parameters': {},
                'steps': deepcopy(self.steps),
                'deliverables': deepcopy(self.deliverables) + [{'id': d, 'status': 'open', 'step': None,
                                                                 'output': None, 'reason': 'no step produces it'}
                                                                for d in extra_open],
                'waypoints': [], 'checkins': [], 'obligations': [], 'open_obligations': [], 'instruction_sources': []}
        plan['sha256'] = digest({k: v for k, v in plan.items() if k != 'sha256'})
        blob = self.store.put_blob(json.dumps(plan, sort_keys=True).encode())
        self.store.append('plan', {'plan_sha256': plan['sha256'], 'blob': blob, 'source': 'compile', 'revision': 0,
                                   'route': 'judgment'})
        self.plan_doc = plan
        return plan

    def write(self, relative, data):
        path = self.dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if type(data) is bytes else data.encode())
        return path

    def worker_instructions(self, step_id, attempt, path, raw, kind, *, seat=None):
        """Record a fictional completion through the real instruction custody API."""
        from ravel.controller import instructions
        step = next((deepcopy(s) for s in self.steps if s['id'] == step_id),
                    {'id': step_id, 'kind': 'operate',
                     'outputs': [{'path': path, 'kind': kind, 'required': True}],
                     'instruction_sources': [], 'protocols': []})
        manifest = instructions.manifest(step, None)
        packet = instructions.packet(manifest, None, step, [])
        session_id = f'session-{step_id}-{attempt}'
        binding = {'run_id': self.store.run_id, 'step': step_id, 'attempt': attempt,
                   'seat': seat, 'manifest_sha256': manifest['sha256'], 'packet_sha256': packet['sha256']}
        session = self.store.append('worker-session', {
            **binding, 'session_id': session_id, 'packet': packet, 'card': None,
            'step_spec': step, 'inputs': []})
        self.store.append('step-attempt', {**binding, 'session': session})
        delivery = instructions.record_delivery(self.store, manifest, packet, session=session)
        target = self.store.path('instruction-artifacts', session, *path.split('/'))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        final = {'schema_version': 2, 'kind': 'producer-result',
                 'outputs': [{'path': path, 'kind': kind}], 'decisions': [],
                 'knowledge_used': [], 'handoff': None, 'escalation': [],
                 'instruction_ack': {'manifest_sha256': manifest['sha256']},
                 'checklist': [{'unit': unit['id'], 'status': 'not_applicable', 'evidence': None,
                                'note': 'Fictional custody control with supplied bytes; no scientific execution.'}
                               for unit in manifest['units'] if unit['kind'] == 'duty']}
        self.store.append('worker-completion', {
            **binding, 'session': session, 'final_record': final,
            'artifacts': [{'path': path, 'sha256': sha(raw)}]})
        return session_id, manifest, packet, delivery

    def adopt(self, step_id, path, data, *, kind='artifact', producer='launch', inputs=(), status='accepted',
              attempt=1, outcome='completed', inventory=True, unconfined=False, measured=True):
        raw = data if type(data) is bytes else (json.dumps(data, sort_keys=True) if type(data) is dict else data).encode()
        destination = f'steps/{step_id}/{path}'
        self.write(destination, raw)
        if producer == 'launch':
            started = self.store.append('step-launch', {'schema_version': 1, 'phase': 'started', 'step_id': step_id,
                                                        'attempt': attempt, 'launch_sha256': 'a' * 64,
                                                        'argv_sha256': 'b' * 64, 'writes': [destination]})
            plan = ({'kind': 'unconfined', 'label_text': 'UNCONFINED EXECUTION', 'backend': None} if unconfined
                    else {'kind': 'confined', 'backend': 'linux', 'argv_sha256': 'b' * 64, 'qualification': {
                        'backend': 'linux', 'confirmed': True, 'checks': {'write_governed_record': 'denied',
                                                                          'connect_host_port': 'denied'}}})
            self.store.append('step-launch', {'schema_version': 1, 'phase': 'finished', 'started': started,
                                              'step_id': step_id, 'attempt': attempt, 'exit_status': 0,
                                              'timed_out': False, 'wall_seconds': 1.5, 'inventory': [],
                                              'backend': None if unconfined else 'linux',
                                              'confinement': {'errors': []}, 'plan': plan})
            source = {'kind': 'launch', 'journal_id': started, 'exit_status': 0, 'launch_sha256': 'a' * 64,
                      'backend': None if unconfined else 'linux'}
        else:
            node = f'controller:{step_id}'
            receipt_sha = sha(f'{step_id}:{attempt}'.encode())
            session_id, manifest, packet, delivery = self.worker_instructions(step_id, attempt, path, raw, kind)
            self.store.append('step-dispatch', {'schema_version': 1, 'key': digest([node, attempt]), 'step_id': step_id,
                                                'seat': None, 'node_id': node, 'attempt': attempt,
                                                'packet_sha256': packet['sha256'], 'packet_tokens': packet['tokens'],
                                                'admitted_tools': ['read_input']})
            self.store.append('step-observation', {
                'schema_version': 1, 'step_id': step_id, 'seat': None, 'attempt': attempt, 'node_id': node,
                'receipt_sha256': receipt_sha, 'status': 'ok', 'session_id': session_id,
                'model': {'id': 'fictional-model'},
                'usage': {'reported': True, 'turns': 2, 'input_tokens': packet['tokens'] + 20, 'output_tokens': 5},
                'transport': 'claude-cli-worker',
                'tool_inventory': {'tools': ['read_input'], 'network': 'model endpoint'} if inventory else None})
            self.store.append('instruction-delivery', {'schema_version': 1, 'kind': 'instruction-delivery-session',
                                                       'delivery': delivery, 'manifest_sha256': manifest['sha256'],
                                                       'packet_sha256': packet['sha256'], 'packet_tokens': packet['tokens'],
                                                       'session': session_id, 'node_id': node,
                                                       'step_id': step_id, 'attempt': attempt, 'seat': None})
            self.store.append('step-validation', {'schema_version': 1, 'step_id': step_id, 'seat': None,
                                                  'attempt': attempt, 'receipt_sha256': receipt_sha, 'errors': [],
                                                  'held': [], 'labels': [], 'escalations': []})
            source = {'kind': 'worker', 'node_id': node, 'attempt': attempt, 'receipt_sha256': receipt_sha,
                      'session_id': session_id, 'role': 'baseline-producer'}
        record = {'schema_version': 1, 'artifact': f'{step_id}:{path}', 'step_id': step_id, 'attempt': attempt,
                  'path': path, 'destination': destination, 'sha256': sha(raw), 'kind': kind, 'quantity': None,
                  'owner_role': None, 'producer': source, 'inputs': sorted(inputs), 'rung': None, 'status': 'staged'}
        staged = self.store.append('custody', record)
        if status != 'staged':
            self.store.append('custody', {**record, 'status': status, 'verdict_of': staged, 'evidence': None})
        if outcome is not None:
            self.store.append('step-outcome', {'schema_version': 1, 'step_id': step_id, 'attempt': attempt,
                                               'status': outcome})
        key = f'{step_id}/{attempt}/producer'
        amounts = {'wall_seconds': 60, 'model_calls': 4, 'tokens': 1000, 'cost_usd': None, 'core_hours': 1,
                   'events': 0, 'children': 1}
        if not any(r['record']['key'] == key for r in self.store.scan('budget-reservation')):
            self.store.append('budget-reservation', {'schema_version': 1, 'kind': 'budget-reservation', 'key': key,
                                                     'step_id': step_id, 'attempt': attempt, 'amounts': amounts})
            observed = {'wall_seconds': 2, 'model_calls': 1, 'tokens': 15, 'cost_usd': 0.01, 'core_hours': 0,
                        'events': 0, 'children': 1} if measured else {d: None for d in amounts}
            self.store.append('budget-settlement', {'schema_version': 1, 'kind': 'budget-settlement', 'key': key,
                                                    'status': 'settled', 'measured': observed, 'charged': observed})
        return self.dir / destination

    # -- authority, review and the ledger --

    def authority_record(self, kind, decision, *, label='operator_configured_machine', obligations=(), option=None,
                         authorizes=True):
        body = {'schema': 'authority-record.v1', 'schema_version': 1, 'uid': self.uid(), 'run_id': RUN_ID,
                'kind': kind, 'decision': decision, 'option': option, 'comment': None,
                'subject': {'pins': {'plan_sha256': (self.plan_doc or {}).get('sha256', 'x')},
                            'obligations': list(obligations)},
                'label': label, 'source': 'operator_default', 'authorizes_effects': authorizes,
                'time_ns': time.time_ns()}
        self.store.append('authority', body)
        return body['uid']

    def review_round(self, purpose, seats, *, family='same', boundary='controller_store'):
        step_id = {'plan': 'plan_review', 'final': 'final_review', 'attacks': 'kill_the_result'}[purpose]
        verdicts = {}
        for role, (credited, verdict) in seats.items():
            verdicts[role] = {'status': 'completed', 'credited': credited, 'verdict': verdict, 'receipts': []}
            label = {'same': 'separate session, same model family',
                     'different': 'separate session, different model family'}.get(family,
                                                                                  'separate session, model family unknown')
            self.store.append('step-credit', {'schema_version': 1, 'step_id': step_id, 'attempt': 1, 'seats': [],
                                              'own': {'credited': credited, 'verdict': verdict,
                                                      'family_relation': family,
                                                      'decision': {'independent': credited, 'label': label,
                                                                   'evidence_boundary': boundary,
                                                                   'family_relation': family}},
                                              'credited': credited})
        self.store.append('review', {'purpose': purpose, 'plan_sha256': self.plan_doc['sha256'], 'attempt': 1,
                                     'seats': verdicts})

    def complete(self, *, value=None, report=None):
        """A fully governed run: two deliverables, launch and worker producers, credited reviews, authority."""
        self.add_step('s1', ['outputs/value.json'], deliverables=[('d-value', 'outputs/value.json')])
        self.add_step('s2', ['outputs/report.md'], kind='synthesize', inputs=['s1:outputs/value.json'],
                      deliverables=[('d-report', 'outputs/report.md')])
        self.pin_plan()
        self.adopt('s1', 'outputs/value.json', value if value is not None else VALUE, kind='result')
        self.adopt('s2', 'outputs/report.md', report if report is not None else REPORT, kind='document',
                   producer='worker', inputs=['s1:outputs/value.json'])
        self.authority_record('approve_plan', 'approve')
        self.authority_record('final', 'accept', authorizes=False)
        self.review_round('plan', {'plan-critic': (True, 'accept')})
        self.review_round('final', {'physics-critic': (True, 'accept'), 'skeptical-verifier': (True, 'accept'),
                                    'physics-decider': (True, 'accept')})
        self.satisfy_upstream()
        return self

    def satisfy_upstream(self):
        for key in list(self.ledger.order):
            if self.ledger.instances[key]['id'] == 'X-UPSTREAM':
                self.ledger.record(self.store, key, 'satisfied', {'mechanism': 'fixture'})
        self.ledger.covered = set(self.ledger.expected)

    def deliver(self, **options):
        from ravel.controller import sink
        return sink.deliver(self.store, self.plan_doc, **options)

    def delivered(self, relative):
        return (self.dir / 'delivery' / relative)


@pytest.fixture
def run(tmp_path, monkeypatch):
    return Run(tmp_path, monkeypatch)


def statuses(run_, row_id):
    return {i['scope'].get('artifact'): (i['status'], i['evidence']) for i in run_.ledger.instances.values()
            if i['id'] == row_id}
