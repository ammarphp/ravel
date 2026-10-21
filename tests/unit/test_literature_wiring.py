"""Composed literature wiring across the shared surfaces; fictional inputs only."""
from copy import deepcopy
import json

import pytest

from ravel import cli
from ravel.workflow import broker_mcp, knowledge_bundles, literature_cli, literature_roles, literature_serving
from ravel.workflow import literature_settings
from ravel.workflow import role_registry, toolbelt
from test_literature_serving import args, base, bind, install, make_run, ROLE
from test_knowledge_bundles import sources


def test_presentation_fragments_are_integrated():
    # test_literature_mcp.py skips its presentation tests without these hooks;
    # the composed tree must have them, so that skip never reaches the gate.
    import inspect
    from ravel.workflow import tool_gate
    assert 'literature_output' in inspect.signature(broker_mcp.Server).parameters
    assert 'literature_output' in inspect.signature(tool_gate.Gate).parameters


def test_legacy_cli_retains_its_catalogue_owner():
    # The original module remains the catalogue owner for legacy subcommands.
    assert cli.FOCUSED_COMMANDS['literature'][0] == 'workflow.literature'


@pytest.mark.parametrize('command', ['search', 'get-paper', 'locate', 'list-papers',
                                      'compare-measurements', 'replay', 'audit'])
def test_public_cli_actually_dispatches_new_subcommands(monkeypatch, tmp_path, command):
    # The CLI passes the trusted serving explicitly; an unconfigured installation passes None.
    observed = []
    monkeypatch.setenv(literature_settings.SETTINGS_ENV, str(tmp_path / 'absent-settings.json'))
    monkeypatch.setattr(literature_cli, 'main', lambda argv, *, serving: observed.append((argv, serving)) or 0)
    assert cli.main(['literature', command, '--help']) == 0
    assert observed == [([command, '--help'], None)]


def test_legacy_mcp_tools_are_byte_identical_when_literature_is_opted_in():
    legacy = deepcopy(role_registry.load(ROLE))
    legacy['knowledge'].pop('literature_operations', None)
    legacy['tools']['ravel_actions'] = [a for a in legacy['tools']['ravel_actions']
                                       if a != literature_serving.ACTION]
    selected = deepcopy(legacy)
    selected['knowledge']['literature_operations'] = ['search', 'get_paper']
    selected['tools']['ravel_actions'].append(literature_serving.ACTION)
    old = broker_mcp.Server(toolbelt.build(legacy, max_tools=64)['tools'], None).listing()
    new = broker_mcp.Server(toolbelt.build(selected, max_tools=64)['tools'], None).listing()
    projected = [row for row in new if not row['name'].startswith('literature_')]
    assert json.dumps(old, sort_keys=True).encode() == json.dumps(projected, sort_keys=True).encode()


def test_legacy_literature_commands_remain_catalogued():
    atlas = toolbelt.load_atlas()
    ids = {row['id'] for row in atlas['entries']}
    assert {'cmd:literature', 'cmd:literature resolve-title', 'cmd:literature tier'} <= ids


def test_registered_scout_tools_reach_production_mcp_action():
    card = deepcopy(role_registry.load(ROLE))
    card['knowledge']['literature_operations'] = list(literature_serving.TOOL_NAMES)
    if literature_serving.ACTION not in card['tools']['ravel_actions']:
        card['tools']['ravel_actions'].append(literature_serving.ACTION)
    assert role_registry.validate_card(card) == []
    belt = toolbelt.build(card, max_tools=64)
    offered = {t['name']: t for t in belt['tools']}
    assert all('literature_' + op in offered for op in literature_roles.operations(card))
    assert not any(t['name'] == 'cmd_literature_query' for t in belt['tools'])
    assert 'literature_replay' not in offered
    assert all(offered['literature_' + op]['executes_through']['action'] == literature_serving.ACTION
               for op in literature_roles.operations(card))


def test_materializer_reserves_required_knowledge_and_writes_exact_packet(base, sources):
    installed = install(base)
    run = make_run(base)
    broker = bind(run, installed.serving)
    card, facts, binding = deepcopy(sources)
    card.update(id=ROLE, tools={'ravel_actions': [literature_serving.ACTION]}, requires={'tools': 'broker-readonly'})
    card['knowledge'].update(literature_operations=['search'], budget_tokens=100000)
    facts['node_id'] = broker.node_id
    binding.update(workspace=broker.workspace, literature_broker=broker,
                   literature_requests=[{'op': 'search', 'args': args('search')}])
    index = knowledge_bundles.materialize(card, facts, binding)
    assert index['literature']['served_ids']
    assert index['used_tokens'] <= index['budget_tokens']
    for row in index['literature']['requests']:
        raw = (broker.workspace / row['path']).read_bytes()
        assert raw == literature_serving.load(run, broker.verify_ledger()[-1]['reply'])
        envelope = json.loads(raw)
        assert all(row['physics_verified'] is False and row['execution_authorized'] is False
                   for row in envelope['results'] + envelope['metadata'])
    record = {'knowledge_used': [], 'literature_used': index['literature']['served_ids'][:1]}
    assert knowledge_bundles.validate_cited_ids(record, index, atlas_path=binding['atlas_path'],
                                                literature_broker=broker) == []
    followup = literature_serving.call(broker, 'get_paper', args('get_paper'))
    evidence = json.loads(literature_serving.load(run, followup))['results']
    fresh = next(row['id'] for row in evidence if row['id'] not in index['literature']['served_ids'])
    assert knowledge_bundles.validate_cited_ids({'knowledge_used': [], 'literature_used': [fresh]}, index,
                                                atlas_path=binding['atlas_path'],
                                                literature_broker=broker) == []


def test_research_step_uses_governed_action(base):
    from ravel.workflow import research_tools
    installed = install(base)
    broker = bind(make_run(base), installed.serving)
    reply, raw = research_tools.retrieve_literature(broker, 'search', args('search'))
    assert reply['status'] == 'ok'
    assert raw == literature_serving.load(broker.rundir, reply)
    assert broker.verify_ledger()[-1]['action'] == literature_serving.ACTION
