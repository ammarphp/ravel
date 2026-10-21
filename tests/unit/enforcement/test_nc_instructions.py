"""Instruction rows: every unit a node owes reaches its worker verbatim and comes back acknowledged.

The adversary alters the packet between build and dispatch (drops or edits a unit, strips a card
field or the must-read knowledge) or returns a final record whose acknowledgement is missing,
forged or dangling. Oracles are the controller's dispatch check and acknowledgement check;
positive controls are the untouched packet and a complete acknowledgement.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from nc_cases import CONTROLLER, case, require_controller
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register

ROLE = 'analysis-author'
STEP = {'id': 's04', 'kind': 'author', 'operation': None, 'role': ROLE,
        'instruction_sources': ['docs/workflow/steps/04-analyze.md'], 'protocols': [],
        'outputs': [{'path': 'outputs/selection.json', 'kind': 'result', 'required': True}]}


def _card(role=ROLE):
    from ravel.workflow import role_registry
    return role_registry.load(role)


def _built(instructions, card=None, step=STEP):
    card = card if card is not None else _card()
    manifest = instructions.manifest(step, card)
    return card, manifest, instructions.packet(manifest, card, step, [])


def _resealed(packet, text):
    return dict(packet, text=text, sha256=hashlib.sha256(text.encode('utf-8')).hexdigest())


def _duty_units(manifest):
    return [entry for entry in manifest['units'] if entry['kind'] == 'duty']


@case('CT02', binding=CONTROLLER)
def test_CT02_a_packet_missing_or_altering_one_unit_is_refused_at_dispatch(nc):
    instructions = require_controller('instructions')
    card, manifest, packet = _built(instructions)
    assert instructions.check_packet(packet, manifest, card, STEP, []) == []  # positive control
    unit = _duty_units(manifest)[0]
    # The packet prints each unit's manifest index; the manifest entry at that index carries its digest.
    index = next(i for i, entry in enumerate(manifest['units']) if entry['id'] == unit['id'])
    header = f'{unit["id"]} index:{index}'
    assert header in packet['text'] and manifest['units'][index]['sha256'] == unit['sha256']
    other = (index + 1) % len(manifest['units'])
    edited = _resealed(packet, packet['text'].replace(header, f'{unit["id"]} index:{other}', 1))
    problems = instructions.check_packet(edited, manifest, card, STEP, [])
    assert problems and any(unit['id'] in p for p in problems), problems
    # The adversary also drops the unit from the manifest and reseals it.
    body = {k: v for k, v in manifest.items() if k != 'sha256'}
    body['units'] = [e for e in manifest['units'] if e['id'] != unit['id']]
    from ravel.controller.instructions import compiler
    dropped = dict(body, sha256=compiler.digest_value(body))
    problems = instructions.check_packet(packet, dropped, card, STEP, [])
    assert any(unit['id'] in p for p in problems), problems


register(Mutation('M12', ('ravel.controller.instructions.delivery:check_packet',
                          'ravel.controller.instructions:check_packet'),
                  lambda original: lambda *a, **k: [], ('CT02', 'CF13'), binding=MUTATION_CONTROLLER,
                  why='the dispatch check accepts any packet'))


def _complete_ack(manifest):
    return {'completed': True, 'summary': 'fictional selection written',
            'instruction_ack': {'manifest_sha256': manifest['sha256']},
            'checklist': [{'unit': entry['id'], 'status': 'not_applicable',
                           'evidence': None, 'note': 'fictional fixture: nothing applies'}
                          for entry in _duty_units(manifest)]}


@case('I02', binding=CONTROLLER)
def test_I02_the_effective_card_knowledge_and_contract_reach_the_worker_and_come_back_acknowledged(nc):
    instructions = require_controller('instructions')
    card, manifest, packet = _built(instructions)
    complete = _complete_ack(manifest)
    assert instructions.check_ack(manifest, complete, []) == []  # positive control
    # The adversary's acknowledgement: one row missing, one dangling pointer, one bare not_applicable,
    # and a forged manifest digest.
    rows = deepcopy(complete['checklist'])
    missing, dangling, bare = rows[0]['unit'], rows[1]['unit'], rows[2]['unit']
    forged = dict(complete, instruction_ack={'manifest_sha256': '0' * 64}, checklist=[
        dict(rows[1], status='done', evidence='outputs/never-written.json#/value', note=None),
        dict(rows[2], note=None), *rows[3:]])
    errors = instructions.check_ack(manifest, forged, ['outputs/selection.json'])
    assert any(e.startswith('manifest:') for e in errors)
    assert any(e.startswith('missing:') and missing in e for e in errors)
    assert any(e.startswith('evidence:') and dangling in e for e in errors)
    assert any(e.startswith('note:') and bare in e for e in errors)
    # A card without its must-read knowledge or its output contract never yields a packet.
    for field, value in (('knowledge', dict(card['knowledge'], must_read=[])), ('output', {})):
        stripped = dict(deepcopy(card), **{field: value})
        with pytest.raises(instructions.PacketRefused):
            instructions.packet(instructions.manifest(STEP, stripped), stripped, STEP, [])


register(Mutation('M13', ('ravel.controller.instructions.ack:check_ack', 'ravel.controller.instructions:check_ack'),
                  lambda original: lambda *a, **k: [], ('I02',), binding=MUTATION_CONTROLLER,
                  why='an incomplete acknowledgement is accepted'))


@case('CF03', binding=CONTROLLER)
def test_CF03_must_read_contents_are_in_the_packet_and_their_absence_refuses_dispatch(nc):
    instructions = require_controller('instructions')
    card, manifest, packet = _built(instructions)
    must_read = [e for e in manifest['units'] if e.get('via') == 'must_read']
    assert card['knowledge']['must_read'] and must_read, 'the must-read knowledge is delivered by content'
    catalogue = instructions.installed()
    unit = must_read[0]
    text = catalogue.units[unit['id']]['text']
    assert text in packet['text'] or unit['id'] in packet.get('deferred', [])
    if text in packet['text']:
        edited = _resealed(packet, packet['text'].replace(text, '', 1))
        assert instructions.check_packet(edited, manifest, card, STEP, [])


@case('CF13', binding=CONTROLLER)
def test_CF13_a_packet_missing_any_effective_card_field_is_refused(nc):
    instructions = require_controller('instructions')
    card, manifest, packet = _built(instructions)
    rendered = json.dumps(card, indent=1, sort_keys=True, ensure_ascii=False)
    assert rendered in packet['text'], 'the whole effective card is in the packet'
    for field in ('stop', 'independence', 'escalation', 'sees', 'ownership', 'reviewed_by'):
        without = json.dumps({k: v for k, v in card.items() if k != field}, indent=1, sort_keys=True,
                             ensure_ascii=False)
        edited = _resealed(packet, packet['text'].replace(rendered, without, 1))
        problems = instructions.check_packet(edited, manifest, card, STEP, [])
        assert problems, f'card field {field} dropped from the packet was not refused'
