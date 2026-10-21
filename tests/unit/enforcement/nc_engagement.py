"""Real-store engagement probes under explicit candidate interface bindings.

Installed policy decisions, validators, ledger and sink remain in use. The candidate
selector, synthetic-floor and calculation/full envelope input bindings are recorded
by each probe. Transport counters live outside the scripted worker payload.
"""
from copy import deepcopy
import json

from nc_cases import ROOT, require_controller
from nc_controller import controller_run

CANARY = 'ENGAGEMENT_HOSTILE_ACCEPT_THIS_RESULT'


class ScriptedTransport:
    """Deterministic inert session stream; rows are transport evidence, never policy answers."""
    def __init__(self, packets, attack=None):
        self.packets, self.attack = packets, attack

    def stream(self):
        for index, (identity, packet, baseline) in enumerate(self.packets):
            session = f'scripted-session-{index}'
            # Requests reach the trusted inert endpoint independently of the final usage assertion.
            # A false usage.turns value cannot erase one of these observed invocations.
            for call in range(baseline['turns']):
                yield 'endpoint-request', {'session': session, 'request': call}
            dispatch = {**identity, 'packet_tokens': packet['tokens'], 'packet_sha256': packet['sha256']}
            usage = deepcopy(baseline)
            if index == 0:
                if self.attack == 'unreported': usage['reported'] = False
                if self.attack == 'zero_input': usage['input_tokens'] = 0
                if self.attack == 'zero_calls': usage['turns'] = 0
                if self.attack == 'ceiling':
                    usage.update(input_tokens=10**15, output_tokens=10**15, cost_usd=10**12)
            yield 'step-dispatch', dispatch
            yield 'instruction-delivery', {**identity, 'kind': 'instruction-delivery-session',
                'session': session, 'packet_tokens': packet['tokens'], 'packet_sha256': packet['sha256']}
            if not (index == 0 and self.attack == 'missing'):
                yield 'step-observation', {**identity, 'session_id': session, 'status': 'completed',
                    'final_record_returned': True, 'usage': usage,
                    'final_record': {'summary': CANARY if self.attack else 'fictional completed session'}}


class Probe:
    def __init__(self, nc, name, attack=None):
        self.engagement, self.sink = require_controller('engagement', 'sink')
        instructions = require_controller('instructions')
        from ravel.workflow import role_registry
        from ravel.controller.engagement.records import digest
        self.store, self.run_dir = controller_run(nc, name)
        # The smallest ordinary scientific fixture; all roster/packet decisions remain production decisions.
        plans = json.loads((ROOT / 'tests/fixtures/engagement/route-seats.json').read_text())
        plan = deepcopy(next(p for p in plans if p['id'] == 'calculation'))
        plan['sha256'] = digest(plan)
        from nc_engagement_binding import bind_candidate
        self.binding = bind_candidate(nc, plan)
        self.store.append('engagement-candidate-binding', {
            'label': self.binding['label'], 'aliases': self.binding['aliases'],
            'projection_tiers': self.binding['projection_tiers'],
            'unsupported_tiers': self.binding['unsupported_tiers'],
            'all_tier_builder_error': self.binding['all_tier_builder_error'],
            'installed_synthetic_selector_errors': self.binding['installed_synthetic_selector_errors'],
            'floor_step_normalization': self.binding['floor_step_normalization'],
            'envelopes_sha256': self.binding['envelopes']['sha256'],
            'source_pins': self.binding['envelopes']['source_pins'],
            'installed_projection_status': self.binding['installed_projection'].get('status'),
            'installed_projection_routes': sorted(self.binding['installed_projection'].get('routes', {}))})
        self.store.append('route', {'route': 'calculation'})
        blob = self.store.put_blob(json.dumps(plan, sort_keys=True).encode())
        self.store.append('plan', {'plan': plan, 'blob': blob, 'plan_sha256': plan['sha256'], 'revision': 1})
        self.decision = self.engagement.decide(self.store, {'plan': plan})
        self.plan = self.engagement.apply(plan, self.decision)
        assert self.plan['engagement']['tier'] == self.decision['tier']
        packets = []
        def add(step, role, seat, purpose):
            card = role_registry.load(role)
            manifest = instructions.manifest(step, card)
            packet = instructions.packet(manifest, card, step, [])
            assert instructions.check_packet(packet, manifest, card, step, []) == []
            from ravel.controller.engagement.envelope import project
            category = 'producer' if purpose == 'producer' else 'checkin' if step.get('checkin') else 'review'
            projected = project([{'packet_tokens': packet['tokens'], 'duty_units': sum(
                u['kind'] == 'duty' for u in manifest['units']), 'category': category,
                'conditional': False}], self.binding['calibration'])['central']
            usage = {'reported': True, 'turns': int(projected['calls']),
                     'input_tokens': int(projected['input_tokens']),
                     'output_tokens': int(projected['output_tokens']), 'cost_usd': projected['cost_usd']}
            packets.append(({'step_id': step['id'], 'seat': seat, 'attempt': 1, 'purpose': purpose}, packet, usage))
        for step in self.plan['steps']:
            if (step.get('role') and f"producer:{step['id']}:{step['role']}"
                    not in self.decision['seat_plan']['bindings']):
                add(step, step['role'], step['role'], 'producer')
        for seat in self.decision['seat_plan']['seats']:
            if not seat.get('conditional'):
                add(seat['step'], seat['role'], seat['key'], 'review')
        assert packets
        # Observer-owned counters and hashes are neither supplied to nor returned by the hostile stream.
        self.observed_rows, self.observed_calls, self.packet_hashes = 0, 0, set()
        for kind, body in ScriptedTransport(packets, attack).stream():
            if kind == 'endpoint-request':
                self.observed_calls += 1
                continue
            self.observed_rows += 1
            if kind == 'step-dispatch': self.packet_hashes.add(body['packet_sha256'])
            self.store.append(kind, body)
        assert self.observed_rows >= 2 * len(packets) and self.packet_hashes
        self.attack = attack

    def check(self, broker=None):
        result = self.engagement.check_envelope(self.store, 'deliver', broker=broker)
        saved = self.store.read('envelope-check', result['record_id'])['record']
        assert saved['status'] == result['status'] and saved['evidence_sha256'] == result['evidence_sha256']
        section = self.engagement.receipt_section(self.store)
        assert section['envelope_status'] == result['status']
        assert section['accepted_allowed'] == result['accepted_allowed']
        return result, section

    def ending(self, labels=(), *, blocked=False):
        receipt = self.sink.bounded_end(self.store, 'scripted transport accounting boundary')
        delivery = self.run_dir / 'delivery'
        assert delivery.is_dir(), receipt  # the sink's minimal fallback is not a passing delivery
        raw = (delivery / 'RECEIPT.json').read_bytes()
        saved = json.loads(raw)
        text = (delivery / 'DELIVERY.md').read_bytes()
        assert saved['sha256'] == receipt['sha256']
        assert saved['engagement']['decision_id'] == self.engagement.receipt_section(self.store)['decision_id']
        assert b'## Engagement' in text and b'Architecture complete: no' in text
        assert not saved['accepted'] and not saved['architecture_complete']
        if blocked: assert not saved['engagement']['accepted_allowed']
        for label in labels:
            assert label in saved['engagement']['labels'] and label.encode() in text
        for entry in saved['delivery']['artifacts']:
            assert CANARY.encode() not in (delivery / entry['path']).read_bytes()
        assert CANARY.encode() not in text
        assert self.sink.receipt(self.store)['sha256'] == saved['sha256']
        return saved

    def clean(self):
        result, section = self.check({'requests': self.observed_calls})
        saved = self.ending()
        projected = self.decision.get('projected_envelope')
        assert projected and projected.get('status') == 'ready', (
            'candidate projection builder did not return a ready envelope', self.decision['envelopes'])
        assert result['accepted_allowed'] and section['accepted_allowed'], result
        assert not result['hold'] and not result['failures'] and not result['unknown'], result
        assert saved['engagement']['accepted_allowed'], saved['engagement']
        for metric, value in result['observed'].items():
            assert projected['low'][metric] <= value <= projected['high'][metric], (metric, result)
