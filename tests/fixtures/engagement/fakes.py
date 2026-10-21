"""Inert, fictional binding doubles for the engagement contract tests."""
from copy import deepcopy
from pathlib import Path
from hashlib import sha256
import json
import math
import sys
from types import ModuleType

from ravel.controller.engagement.records import digest


class FakeRunStore:
    """Journal envelope custody with deterministic identities and hash chaining."""

    def __init__(self, run_id='fixture-run', *, root=None):
        self.run_id = run_id
        self.root = Path(root) if root is not None else None
        self.entries = []

    def append(self, kind, record):
        uid = f'record-{len(self.entries) + 1:04d}'
        envelope = {'id': uid, 'kind': kind, 'record': deepcopy(record),
                    'prev': self.entries[-1]['digest'] if self.entries else None}
        envelope['digest'] = digest(envelope)
        self.entries.append(envelope)
        return uid

    def read(self, kind, record_id):
        return deepcopy(next(e for e in self.entries if e['id'] == record_id and e['kind'] == kind))

    def scan(self, kind):
        return [deepcopy(e) for e in self.entries if e['kind'] == kind]

    def path(self, *parts):
        if self.root is None:
            raise ValueError('fixture store has no filesystem root')
        return self.root.joinpath(*parts)


class FakeInstructions:
    """Preserve every card duty and binding; only optional context is deferrable."""

    @staticmethod
    def _cards(card):
        yield card
        for folded in card.get('folded_cards', []):
            yield from FakeInstructions._cards(folded)

    @staticmethod
    def manifest(step, card):
        if step.get('role') not in (None, card['id']):
            raise ValueError('step and card roles differ')
        units = []
        for source in FakeInstructions._cards(card):
            role = source['id']
            for field in ('purpose', 'protocol', 'must_check', 'must_read'):
                values = source.get(field, [])
                values = values if isinstance(values, list) else [values]
                for i, value in enumerate(values):
                    units.append({'id': f'{role}:{field}:{i}', 'kind': 'duty',
                                  'source_role': role, 'source_binding': f'fixture:{role}#/{field}/{i}',
                                  'field': field, 'text': deepcopy(value)})
            units.extend([
                {'id': role + ':fixture-duty', 'kind': 'duty', 'source_role': role,
                 'source_binding': f'fixture:{role}#/duty', 'text': 'Check the stated result.'},
                {'id': role + ':fixture-context', 'kind': 'context', 'source_role': role,
                 'source_binding': f'fixture:{role}#/context', 'text': 'Fictional supporting context.'},
            ])
        result = {'step_id': step['id'], 'units': units, 'card_sha256': digest(card)}
        result['sha256'] = digest(result)
        return result

    @staticmethod
    def reviewer_items(manifest, card):
        return deepcopy([u for u in manifest['units'] if u['kind'] == 'duty'])

    @staticmethod
    def packet(manifest, card, step, inputs):
        if manifest != FakeInstructions.manifest(step, card):
            raise ValueError('manifest differs from complete effective card')
        inline = step.get('engagement', {}).get('inline_context_tokens', 120000)
        units = manifest['units']
        result = {'manifest_sha256': manifest['sha256'], 'card': deepcopy(card),
                  'must_read': [deepcopy(u) for u in units if u.get('field') == 'must_read'],
                  'units': deepcopy([u for u in units if inline or u['kind'] != 'context']),
                  'deferred_reads': deepcopy([u for u in units if not inline and u['kind'] == 'context']),
                  'inputs': deepcopy(inputs)}
        result['deferred'] = [u['id'] for u in result['deferred_reads']]
        result['schema'] = {}
        result['text'] = json.dumps(result, sort_keys=True, separators=(',', ':'))
        result['tokens'] = math.ceil(len(result['text']) / 4)
        result['sha256'] = sha256(result['text'].encode()).hexdigest()
        return result

    @staticmethod
    def check_packet(packet, manifest, card, step, inputs):
        expected = FakeInstructions.packet(manifest, card, step, inputs)
        return [] if packet == expected else ['instruction packet differs from rebuilt packet']


def cards():
    roles = ('generator', 'plan-critic', 'physics-critic', 'skeptical-verifier',
             'physics-decider', 'integrity-auditor', 'figure-critic', 'trap-auditor',
             'object-selection-mapper', 'synthesizer')
    result = {role: {'id': role, 'purpose': f'Perform the fictional {role} duty.',
                     'protocol': [f'{role}: inspect supplied evidence'],
                     'must_check': [f'{role}: trace the claim'],
                     'must_read': [f'inputs/{role}.json'], 'reviewed_by': [],
                     'independence': {}, 'sees': {}, 'knowledge': {}} for role in roles}
    result['generator']['reviewed_by'] = ['physics-critic', 'object-selection-mapper']
    return result


def fictional_plan(route='study', claims=2):
    plan = {'id': 'fictional', 'route': {'id': route}, 'instruction_sources': [],
            'steps': [
                {'id': 's1', 'kind': 'produce', 'role': 'generator', 'review': ['figure-critic'],
                 'rung': 'reuse', 'waypoint': True},
                {'id': 's2', 'kind': 'produce', 'role': 'generator', 'review': [], 'rung': 'reuse'},
            ],
            'deliverables': [{'id': f'claim-{i + 1}', 'step': 's2', 'status': 'mapped'} for i in range(claims)],
            'checkins': [{'id': 'checkin1', 'seats': ['plan-critic']},
                         {'id': 'checkin2', 'seats': ['physics-critic']},
                         {'id': 'checkin3', 'seats': ['physics-critic', 'skeptical-verifier', 'physics-decider']}],
            'open_obligations': []}
    plan['sha256'] = digest(plan)
    return plan


def checked_facts(**overrides):
    values = dict(route='analysis', deliverables=2, consequence='R0', compute='C0', novelty='N0', special=[])
    values.update(overrides)
    return {key: {'value': deepcopy(value), 'source': f'fixture:{key}', 'checker': 'code:fixture'}
            for key, value in values.items()}


def install_fakes(monkeypatch, *, cards_override=None, operator=None):
    from ravel.controller.engagement import policy
    instructions = ModuleType('ravel.controller.instructions')
    for name in ('manifest', 'packet', 'reviewer_items', 'check_packet'):
        setattr(instructions, name, getattr(FakeInstructions, name))
    authority = ModuleType('ravel.controller.authority')
    authority.operator_config = lambda: deepcopy(operator or {})
    authority.frozen = lambda store, required=False: None
    judgment = ModuleType('ravel.controller.judgment')
    judgment.classify = lambda action: action.get('consequence', 'R0')
    for module in (instructions, authority, judgment):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    import ravel.controller as controller
    monkeypatch.setattr(controller, 'instructions', instructions, raising=False)
    monkeypatch.setattr(controller, 'authority', authority, raising=False)
    monkeypatch.setattr(controller, 'judgment', judgment, raising=False)
    monkeypatch.setattr(policy, 'role_cards', lambda: deepcopy(cards_override if cards_override is not None else cards()))
    return instructions


def projection_inputs(monkeypatch, engagement, installed):
    """Supply a sealed fictional projection through the real installed-source validator."""
    from ravel.controller.engagement import envelope
    read = envelope.data
    original = deepcopy(read('envelopes.json'))

    def source(name):
        if name == 'policy.json':
            return deepcopy(installed)
        if name == 'envelopes.json':
            body = {**deepcopy(original), **deepcopy(engagement.data(name))}
            body['sha256'] = digest({k: v for k, v in body.items() if k != 'sha256'})
            return body
        return read(name)

    monkeypatch.setattr(envelope, 'data', source)


def policy_for(plan, cards=None):
    """Explicit fixture seat rules; installed policy data is never mutated."""
    from ravel.controller.engagement import policy
    installed = deepcopy(policy.load_policy())
    role_cards = globals()['cards']() if cards is None else cards
    rules = installed['seat_plans'].setdefault(plan['route']['id'], {})
    for seat in policy.declared_seats(plan, role_cards):
        rules[seat['key']] = {'lean': 'tiered', 'standard': 'tiered', 'full': 'keep'}
    installed['sha256'] = digest({k: v for k, v in installed.items() if k != 'sha256'})
    return installed
