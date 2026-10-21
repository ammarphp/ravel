"""Toolbelt: generated per card from the atlas; allowlist enforced by the broker guard.
Synthetic requests and cards only."""
from copy import deepcopy
import json

import pytest

from ravel.workflow import role_registry, tool_gate, toolbelt
from ravel.workflow.broker import Broker, work_root


@pytest.fixture(scope='module')
def atlas():
    return toolbelt.load_atlas()


@pytest.fixture(scope='module')
def cards():
    return role_registry.all_cards()


def make_broker(tmp_path, monkeypatch, tools, card, *, max_calls=20):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    run = tmp_path / 'run'
    run.mkdir(exist_ok=True)
    workspace = work_root(run) / 'worker' / '1'
    for name in ('inputs', 'outputs', 'scratch', 'calls'):
        (workspace / name).mkdir(parents=True, exist_ok=True)
    broker = Broker(run, workspace, node_id='worker', attempt=1, allowed_actions=card['tools']['ravel_actions'] + ['read', 'write'],
                    max_calls=max_calls, guards=[tool_gate.broker_guard(tools, rundir=run)])
    toolbelt.register_actions(broker, card)
    return broker


def synthetic_card(**changes):
    card = role_registry.load('ablation-critic')
    card = deepcopy(card)
    for path, value in changes.items():
        target = card
        keys = path.split('.')
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = value
    return card


# ---- acceptance 1: every registered card yields a valid toolbelt; every tool maps to an atlas id

def test_every_registered_card_yields_a_valid_toolbelt_mapped_to_the_atlas(atlas, cards):
    from jsonschema import Draft202012Validator
    ids = {row['id']: row for row in atlas['entries']}
    assert len(cards) == len(role_registry.registry_document()['roles'])
    for card in cards:
        belt = toolbelt.build(card, atlas=atlas)
        names = [t['name'] for t in belt['tools']]
        assert names[0] == 'submit_final' and len(names) == len(set(names)) <= toolbelt.MAX_TOOLS, card['id']
        for tool in belt['tools']:
            assert toolbelt.NAME.fullmatch(tool['name']), tool['name']
            assert tool['atlas_id'] in ids, (card['id'], tool['name'])
            assert tool['atlas_sha256'] == toolbelt.digest(ids[tool['atlas_id']])
            Draft202012Validator.check_schema(tool['args_schema'])
            assert set(tool) == {'name', 'atlas_id', 'atlas_sha256', 'description', 'args_schema', 'derivation',
                                 'cost_class', 'native', 'consequential', 'effects', 'executes_through'}
            action = tool['executes_through']['action']
            assert action is None or action in toolbelt.EXECUTABLE_ACTIONS
            assert action is None or action in card['tools']['ravel_actions'] + ['read', 'write']
        for row in belt['omitted'] + belt['absent']:
            assert row['atlas_id'] is None or row['atlas_id'] in ids
        assert belt['manifest_sha256'] == toolbelt.manifest_sha256(belt)


def test_tools_none_card_gets_only_its_structured_output(atlas, cards):
    card = next(c for c in cards if c['requires']['tools'] == 'none')
    assert [t['name'] for t in toolbelt.for_card(card, atlas=atlas)] == ['submit_final']


def test_readonly_card_has_no_write_tool_and_work_order_narrows_checks(atlas):
    card = synthetic_card()
    assert card['requires']['tools'] == 'broker-readonly'
    names = {t['name'] for t in toolbelt.for_card(card, atlas=atlas)}
    assert 'ws_read' in names and 'ws_write' not in names
    everything = toolbelt.build(card, atlas=atlas, executable=toolbelt.EXECUTABLE_ACTIONS + ('check run',))
    narrowed = toolbelt.build(card, {'must_check': []}, atlas=atlas,
                              executable=toolbelt.EXECUTABLE_ACTIONS + ('check run',))
    assert any(t['name'].startswith('check_') for t in everything['tools'])
    assert not any(t['name'].startswith('check_') for t in narrowed['tools'])


def test_working_set_is_bounded_with_an_omission_census(atlas):
    card = synthetic_card(**{'knowledge.may_query': list(toolbelt.KNOWLEDGE_ARGS)})
    belt = toolbelt.build(card, atlas=atlas, max_tools=4)
    assert len(belt['tools']) == 4
    assert belt['omitted'] and all(r['reason'] == 'working_set' and r['reachable_through'] == 'knowledge_find'
                                   for r in belt['omitted'])


def test_unexecutable_affordances_are_absent_rows_naming_their_owner(atlas):
    belt = toolbelt.build(synthetic_card(), atlas=atlas)
    absent = {r['tool']: r for r in belt['absent']}
    assert absent['check_validation_validate_task_contract_validate']['owner'].startswith('broker')
    assert not any(t['name'].startswith('check_') for t in belt['tools'])


def test_affordance_census_regenerates_byte_identically():
    from ravel.paths import package_data_path
    saved = package_data_path('agents', 'affordances.json').read_bytes()
    assert toolbelt.encode(toolbelt.census()) == saved
    rows = json.loads(saved)['rows']
    assert {r['status'] for r in rows} <= {'typed', 'generic', 'absent'}
    assert all(r.get('owner') for r in rows if r['status'] == 'absent')


# ---- acceptance 2: a tool outside the allowlist is absent and refused by name with a receipt

def test_tool_outside_the_allowlist_is_absent_and_refused_by_name_with_a_receipt(tmp_path, monkeypatch, atlas):
    card = synthetic_card()
    tools = toolbelt.for_card(card, atlas=atlas)
    assert 'ws_write' not in toolbelt.by_name(tools)
    broker = make_broker(tmp_path, monkeypatch, tools, card)
    reply = broker.call(toolbelt.to_request(tools, 'ws_write', {'path': 'outputs/x', 'content': 'y'}, 'c1'))
    assert reply['status'] == 'refused' and reply['error']['code'] == 'not_allowlisted'
    receipt = json.loads((broker.workspace / 'calls/1.json').read_text())
    assert receipt['action'] == 'tool:ws_write' and receipt['status'] == 'refused'
    assert receipt['reply']['error']['code'] == 'not_allowlisted'
    assert broker.verify_ledger()[0]['receipt_id'] == reply['receipt_id']


def test_card_action_cannot_bypass_the_toolbelt_narrowing(tmp_path, monkeypatch, atlas):
    """The broker allows ``write`` and ``knowledge query``; the guard still refuses calls no tool makes."""
    card = synthetic_card(**{'knowledge.may_query': ['find']})
    tools = toolbelt.for_card(card, atlas=atlas)
    broker = make_broker(tmp_path, monkeypatch, tools, card)
    for n, request in enumerate([{'action': 'write', 'args': {'path': 'outputs/x', 'content': 'y'}},
                                 {'action': 'knowledge query', 'args': {'op': 'show', 'args': {'id': 'cmd:work'}}},
                                 {'action': 'knowledge query', 'args': {'op': 'find', 'args': {'text': 'x', 'extra': 1}}},
                                 {'action': 'knowledge query', 'args': {'op': 'find', 'text': 'x'}},
                                 {'action': 'tool:ws_read', 'args': {'path': 'inputs/x'}}]):
        reply = broker.call({'call_id': f'b{n}', **request})
        assert reply['status'] == 'refused' and reply['error']['code'] == 'not_allowlisted', request
    assert len(broker.verify_ledger()) == 5


def test_knowledge_tools_and_the_handler_share_one_argument_shape(atlas):
    tools = toolbelt.for_card(synthetic_card(**{'knowledge.may_query': ['find', 'show']}), atlas=atlas)
    request = toolbelt.to_request(tools, 'knowledge_find', {'text': 'x', 'limit': 2}, 'k1')
    assert request == {'call_id': 'k1', 'action': 'knowledge query', 'args': {'op': 'find', 'args': {'text': 'x', 'limit': 2}}}
    assert toolbelt.match(tools, request['action'], request['args'])['name'] == 'knowledge_find'
    assert toolbelt.match(tools, 'knowledge query', {'op': 'find', 'text': 'x'}) is None
    assert toolbelt.knowledge_ops(tools) == ['find', 'show']


def test_unlisted_tool_names_never_alias_an_allowed_action(atlas):
    tools = toolbelt.for_card(synthetic_card(), atlas=atlas)
    for name in ('read', 'write', 'knowledge query', 'submit_final'):
        request = toolbelt.to_request(tools, name, {'path': 'inputs/x'}, 'c')
        assert request['action'] == 'tool:' + name and toolbelt.match(tools, request['action'], request['args']) is None


def test_typed_tools_execute_through_the_broker(tmp_path, monkeypatch, atlas):
    card = synthetic_card()
    tools = toolbelt.for_card(card, atlas=atlas)
    broker = make_broker(tmp_path, monkeypatch, tools, card)
    (broker.workspace / 'inputs/data.txt').write_text('synthetic')
    read = broker.call(toolbelt.to_request(tools, 'ws_read', {'path': 'inputs/data.txt'}, 'r1'))
    assert read['status'] == 'ok' and read['stdout_tail'] == 'synthetic'
    found = broker.call(toolbelt.to_request(tools, 'knowledge_find', {'text': 'knowledge atlas query', 'limit': 0}, 'k1'))
    assert found['status'] == 'ok' and json.loads(found['stdout_tail'])['kind'] == 'knowledge-result'
    receipt = json.loads((broker.workspace / 'calls/2.json').read_text())
    assert receipt['derivation'] == 'retrieval' and receipt['source']['uri'].startswith('ravel-atlas:')


def test_fixed_arguments_cannot_be_overridden_and_malformed_calls_get_receipts(tmp_path, monkeypatch, atlas):
    card = synthetic_card()
    tools = toolbelt.for_card(card, atlas=atlas)
    broker = make_broker(tmp_path, monkeypatch, tools, card)
    calls = [('knowledge_find', {'op': 'show', 'text': 'x'}, 'not_allowlisted'),
             ('ws_read', ['inputs/x'], 'invalid_call'), (None, {}, 'invalid_call')]
    for n, (name, args, code) in enumerate(calls):
        reply = broker.call(toolbelt.to_request(tools, name, args, f'm{n}'))
        assert reply['status'] == 'refused' and reply['error']['code'] == code, name
    assert [r['status'] for r in broker.verify_ledger()] == ['refused'] * 3


# ---- acceptance 5: cards with evidence_budget > 0 declare requires.tools

def test_registered_cards_with_an_evidence_budget_declare_tools(cards):
    for card in cards:
        assert card['requires']['tools'] in ('none', 'broker-readonly', 'broker-full'), card['id']
        if card['stop'].get('evidence_budget', 0) > 0:
            assert card['requires']['tools'] != 'none', card['id']
    assert role_registry.validate_registry() == []


def test_evidence_budget_without_tools_is_refused(atlas):
    card = synthetic_card(**{'stop.evidence_budget': 2, 'requires.tools': 'none'})
    with pytest.raises(toolbelt.ToolbeltError, match='evidence_budget'):
        toolbelt.build(card, atlas=atlas)
    assert any('positive evidence budget' in e for e in role_registry.validate_card(card))
    missing = synthetic_card(**{'stop.evidence_budget': 2})
    del missing['requires']['tools']
    with pytest.raises(toolbelt.ToolbeltError, match='requires.tools'):
        toolbelt.build(missing, atlas=atlas)
    assert role_registry.validate_card(missing)


def test_final_records_validate_as_text_json():
    card = synthetic_card()
    record, errors = toolbelt.validate_final(card, 'not json')
    assert record is None and errors
    record, errors = toolbelt.validate_final(card, json.dumps({'handoff': None, 'unexpected': 1}))
    assert record is None and errors


@pytest.mark.parametrize('arguments', [
    {'path': 'inputs/data.json'}, {'artifact_id': 'a0000', 'path': '/private'},
    {'artifact_id': 'a0000', 'offset': -1}, {'artifact_id': 'a0000', 'max_bytes': 65537},
    {'section': 'artifacts', 'max_bytes': 1}, {'section': 'outside'}, {'query': 'x' * 257},
])
def test_review_reader_refuses_unbound_shapes_at_the_toolbelt(tmp_path, monkeypatch, atlas, arguments):
    card = synthetic_card()
    tools = toolbelt.for_card(card, atlas=atlas)
    reader = next(t for t in tools if t['executes_through']['action'] == toolbelt.REVIEW_ACTION)
    broker = make_broker(tmp_path, monkeypatch, tools, card)
    reply = broker.call(toolbelt.to_request(tools, reader['name'], arguments, 'review-shape'))
    assert reply['status'] == 'refused' and reply['error']['code'] == 'not_allowlisted'
    assert reply['outputs'] == [] and list((broker.workspace / 'outputs').iterdir()) == []


@pytest.mark.parametrize('arguments', [
    {}, {'section': 'omissions', 'offset': 0, 'max_bytes': 1024, 'query': ''},
    {'artifact_id': 'a0000', 'offset': 0, 'max_bytes': 1},
])
def test_review_reader_declares_each_bounded_page_shape(atlas, arguments):
    tools = toolbelt.for_card(synthetic_card(), atlas=atlas)
    assert toolbelt.match(tools, toolbelt.REVIEW_ACTION, arguments) is not None
