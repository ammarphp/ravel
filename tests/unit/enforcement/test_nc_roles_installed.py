"""Role rows against the installed registry: what a card's operations reach, and which card a dispatch pins.

Both cases take their rows from the effective role registry (``nc_cases.dimension_rows``), so a role or an
operation added to a card is covered the day it is installed. The adversaries are inert: a scripted worker
speaking MCP to an in-process broker built over the card's toolbelt, and a dispatch specification that pins a
card digest the registry does not hold. Oracles are written here (refusal codes and messages, the tool names a
probe may list, the effects a refused call leaves); none is computed by the mechanism under test.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from nc_adversary import InProcessWorker
from nc_cases import INSTALLED, dimension_case, dimension_rows, role_row
from nc_mutations import Mutation, register

DATA = '{"fictional": 1}'
UNGRANTED = 'fictional_unregistered_effect'
NOT_ON_ALLOWLIST = 'not in the role allowlist or registry'
NOT_IN_TOOLBELT = 'is outside the card toolbelt'
# The argument shape the broker itself accepts for each executable action: the shape a tool of the card
# resolves to. The raw operation name is attacked with exactly these arguments, so only the name is wrong.
BROKER_SHAPES = {'read': {'path': 'inputs/data.json'},
                 'write': {'path': 'scratch/fictional.txt', 'content': 'fictional'},
                 'knowledge query': {'op': 'find', 'args': {'text': 'fictional query', 'limit': 0}}}
# Per listed tool the broker action it reaches, a call with changed arguments (refused at the toolbelt guard)
# and a valid call (admitted).
REACHES = {'knowledge_find': 'knowledge query', 'ws_read': 'read'}
CHANGED = {'knowledge_find': {'op': 'show', 'id': 'fictional'},
           'ws_read': {'path': 'inputs/data.json', 'fictional_extra': 1}}
VALID = {'knowledge_find': {'text': 'fictional query', 'limit': 0}, 'ws_read': {'path': 'inputs/data.json'}}


# ---------------------------------------------------------------- operations: the card toolbelt is the reach

@dimension_case('ROLE', 'operations', binding=INSTALLED)
@pytest.mark.parametrize('row', dimension_rows('ROLE', ('operations',)), ids=str)
def test_role_operations_reach_only_the_card_toolbelt(nc, row):
    from ravel.workflow import toolbelt
    card, field, index = role_row(row)
    assert field == 'operations'
    operation = card['operations'][index]
    worker = InProcessWorker(nc, card)
    (worker.workspace / 'inputs' / 'data.json').write_text(DATA)
    offered = sorted(t['name'] for t in worker.tools if t['executes_through']['action'] is not None)
    assert operation not in offered, 'the attack names an operation, which must not also be a tool name'
    attacks = [name for name in CHANGED if name in offered]
    controls = [name for name in VALID if name in offered]
    calls = [{'op': 'call', 'name': operation, 'arguments': deepcopy(BROKER_SHAPES.get(operation, {}))},
             {'op': 'call', 'name': 'tool:' + operation, 'arguments': {}},
             {'op': 'call', 'name': UNGRANTED, 'arguments': {}}]
    calls += [{'op': 'call', 'name': name, 'arguments': deepcopy(CHANGED[name])} for name in attacks]
    calls += [{'op': 'call', 'name': name, 'arguments': deepcopy(VALID[name])} for name in controls]
    log = worker.play({'actions': [{'op': 'list'}, *calls]})

    # The probed tool inventory is the card's toolbelt: every tool that executes, and nothing else.
    listing = log[0]
    assert listing['ok'] and sorted(listing['result']['names']) == offered, (card['id'], listing)
    # No offered tool reaches an action the broker has no handler for.
    unhandled = {t['executes_through']['action'] for t in worker.tools} - {None} - set(worker.broker.actions)
    assert unhandled == set(), (card['id'], sorted(unhandled))
    # The operation is in the worker's reach as a tool only when the broker can execute it and the card
    # asks for tools at all; a card that requires none is offered none.
    reach = [t['name'] for t in worker.tools if t['executes_through']['action'] == operation]
    if card['requires']['tools'] == 'none':
        assert offered == [] and reach == [], (card['id'], offered)
    elif operation in toolbelt.EXECUTABLE_ACTIONS:
        assert reach, f'{card["id"]} grants {operation!r} and requires tools, but no offered tool executes through it'
    else:
        assert reach == [], f'{card["id"]}: {reach} execute through {operation!r}, which the broker cannot execute'

    rows = worker.ledger()
    assert len(rows) == len(calls), [(r['action'], r['status']) for r in rows]
    # The raw operation name, the prefixed name and an action no card grants are each refused before invocation.
    for found, action in zip(rows[:3], ('tool:' + operation, 'tool:tool:' + operation, 'tool:' + UNGRANTED)):
        error = found['reply']['error'] or {}  # an admitted call has no error, and fails below on its status
        assert (found['action'], found['status'], error.get('code')) == (action, 'refused', 'not_allowlisted'), found
        assert NOT_ON_ALLOWLIST in error.get('message', '') and found['reply']['outputs'] == [], found
    # A listed tool called with changed arguments is refused at the toolbelt guard, not by the tool.
    for name, found in zip(attacks, rows[3:3 + len(attacks)]):
        error = found['reply']['error'] or {}
        assert (found['action'], found['status']) == (REACHES[name], 'refused'), (name, found)
        assert error.get('code') == 'not_allowlisted', (name, error)
        assert NOT_IN_TOOLBELT in error.get('message', '') and found['reply']['outputs'] == [], (name, found)
    # Positive control: the same tools, called as listed, are admitted and do their work.
    admitted = rows[3 + len(attacks):]
    for name, found in zip(controls, admitted):
        assert (found['action'], found['status'], found['reply']['error']) == (REACHES[name], 'ok', None), name
    if 'ws_read' in controls:
        assert admitted[controls.index('ws_read')]['reply']['stdout_tail'] == DATA
    if not controls:
        # Neither listed tool exists, so no valid call can be made: the card must be one that requires no tools.
        assert card['requires']['tools'] == 'none' and offered == [], (card['id'], offered)
    assert list((worker.workspace / 'outputs').iterdir()) == []  # nothing a refused call tried was written


def _match_by_action_only(original):
    """Toolbelt membership by action alone: a listed action is admitted with any arguments."""
    def match(tools, action, args):
        return next((t for t in tools if t['executes_through']['action'] == action), None)
    return match


register(Mutation('M07', 'ravel.workflow.toolbelt:match', _match_by_action_only,
                  ('test_role_operations_reach_only_the_card_toolbelt[ROLE-ablation-critic-operations-0]',),
                  why='the broker guard admits a listed action with any arguments'))


# ---------------------------------------------------------------- id, identity, family: the pinned effective card

def _digest(value):
    """The canonical-JSON SHA-256 a dispatch pins for a card, computed here and not by the registry."""
    canonical = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _spec(role, version, digest):
    return {'role': {'id': role, 'version': version, 'card_sha256': digest}}


@dimension_case('ROLE', 'id', 'identity', 'family', binding=INSTALLED)
@pytest.mark.parametrize('row', dimension_rows('ROLE', ('id', 'identity', 'family')), ids=str)
def test_role_identity_is_the_pinned_effective_card(nc, row):
    from ravel.workflow import role_registry
    from ravel.workflow.transports import cli_worker
    card, field, _ = role_row(row)
    role = card['id']
    repointed = deepcopy(card)
    if field == 'id':
        repointed['id'] = role + '-repointed'
    elif field == 'family':
        repointed['family'] = 'fictional-family'
    else:
        assert field == 'identity'
        repointed['purpose'] = 'fictional purpose'
    assert repointed != card, 'the attack must change the card it pins'
    # Positive control: the digest of the effective card (computed here) is the one the registry holds, and a
    # dispatch that pins it resolves to exactly that card.
    pinned = role_registry.card_sha256(role)
    assert pinned == _digest(card)
    assert cli_worker._card(_spec(role, card['version'], pinned), None) == role_registry.load(role)
    # A dispatch naming the role but pinning the digest of a repointed card is refused before anything starts.
    with pytest.raises(cli_worker.LaunchRefused) as refused:
        cli_worker._card(_spec(role, card['version'], _digest(repointed)), None)
    assert refused.value.missing == ['role_card:changed'] and refused.value.not_dispatched is True
    assert str(refused.value) == 'cli worker refused: role_card:changed'


def _card_digest_not_compared(original):
    """A dispatch that loads the named role's card and never compares it with the pinned digest."""
    def card(spec, supplied):
        from ravel.workflow import role_registry
        return role_registry.load(spec['role']['id']) if supplied is None else supplied
    return card


register(Mutation('M06', 'ravel.workflow.transports.cli_worker:_card', _card_digest_not_compared,
                  ('test_role_identity_is_the_pinned_effective_card[ROLE-ablation-critic-id]',),
                  why='a dispatch accepts any card digest'))
