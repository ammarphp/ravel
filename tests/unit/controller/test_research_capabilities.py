"""The capability catalogue deciding seats receive: complete over the registries, and recall by request facts.

Fictional intake records only; the registries are the installed ones. No worker, model or native call.
"""
import importlib
import json
from pathlib import Path
import sys

import pytest

from ravel.controller import capabilities
from ravel.workflow import toolbelt

ROOT = Path(__file__).resolve().parents[3]
select = importlib.import_module('ravel.controller.routes.select')


@pytest.fixture(scope='module')
def document():
    return capabilities.catalogue()


def test_the_catalogue_covers_every_registered_route_operation_and_tool_exactly_once(document):
    atlas = toolbelt.load_atlas()
    routes = [row['id'] for row in document['routes']]
    assert len(routes) == len(set(routes))
    assert set(routes) == {select.JUDGMENT} | {spec['id'] for spec in select.load_specs()}
    operations = [row['id'] for row in document['operations']]
    assert len(operations) == len(set(operations))
    assert {e['title'] for e in atlas['entries'] if e['kind'] == 'op'} <= set(operations)
    signatures = json.loads((ROOT / 'src/ravel/data/operation_signatures.json').read_text())['operations']
    assert set(signatures) <= set(operations), sorted(set(signatures) - set(operations))
    tools = [row['id'] for row in document['tools']]
    assert len(tools) == len(set(tools))
    assert set(tools) == {e['id'] for e in atlas['entries'] if e['kind'] == 'tool'}
    # Every operation a route spec runs is in the catalogue too.
    used = {op for row in document['routes'] for op in row['operations']}
    assert used <= set(operations), sorted(used - set(operations))


def test_the_catalogue_is_sealed_and_generated_identically(document):
    body = {k: v for k, v in document.items() if k != 'sha256'}
    assert document['sha256'] == capabilities.digest(body)
    assert capabilities.catalogue()['sha256'] == document['sha256']


def facts(task_mode='research', kinds=(), claims=(), tools=(), operation=None):
    contract = {'task_mode': task_mode, 'intake': {'kind': task_mode, **({'operation': operation} if operation else {})}}
    reading = {'deliverables': [{'id': f'd{i}', 'artifact': {'kind': kind}} for i, kind in enumerate(kinds)]
               + [{'id': f'c{i}', 'claim_kind': claim} for i, claim in enumerate(claims)],
               'constraints': [{'type': 'requested_tool', 'value': {'tool': tool}} for tool in tools]}
    return capabilities.request_facts(contract, reading)


def ids(rows):
    return {row['id'] for row in rows}


def an_operation_producing(document, kind):
    return next(row['id'] for row in document['operations'] if kind in row['output_kinds'])


def test_a_request_whose_facts_call_for_a_route_gets_it_and_one_that_does_not_does_not(document):
    research = capabilities.applicable(document, facts('research'))
    other = capabilities.applicable(document, facts('calculation'))
    assert 'research' in ids(research['routes'])
    assert 'research' not in ids(other['routes'])
    assert 'calculation' in ids(other['routes']) and 'calculation' not in ids(research['routes'])


def test_operations_are_recalled_by_requested_artifact_kind_and_never_without_it(document):
    kind = next(k for row in document['operations'] for k in row['output_kinds'] if k != 'document')
    wanted = an_operation_producing(document, kind)
    called = capabilities.applicable(document, facts(kinds=[kind]))
    assert wanted in ids(called['operations'])
    assert all(kind in next(r for r in document['operations'] if r['id'] == o['id'])['output_kinds']
               or 'claim' in o['because'] or 'named' in o['because'] for o in called['operations'])
    uncalled = capabilities.applicable(document, facts(kinds=[]))
    assert wanted not in ids(uncalled['operations'])


def test_capabilities_compose_across_sub_problems(document):
    kinds = sorted({k for row in document['operations'] for k in row['output_kinds'] if k != 'document'})[:2]
    assert len(kinds) == 2
    called = capabilities.applicable(document, facts(kinds=kinds))
    for kind in kinds:
        assert an_operation_producing(document, kind) in ids(called['operations'])


def test_a_named_tool_or_operation_is_recalled_only_when_named(document):
    tool = document['tools'][0]
    named = capabilities.applicable(document, facts(tools=[tool['name']]))
    assert tool['id'] in ids(named['tools'])
    assert tool['id'] not in ids(capabilities.applicable(document, facts())['tools'])
    operation = document['operations'][0]['id']
    assert operation in ids(capabilities.applicable(document, facts(operation=operation))['operations'])


def test_the_research_decision_seat_receives_the_catalogue_and_its_campaign_applicability(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from test_langgraph_research_orchestration import open_fixture
    from ravel.workflow import research_coordinator_decisions as decisions
    request, _, _, _ = open_fixture(tmp_path / 'run')
    shown = decisions.capability_view(decisions.request(request))
    assert shown['catalogue']['sha256'] == capabilities.catalogue()['sha256']
    assert shown['applicable']['catalogue_sha256'] == shown['catalogue']['sha256']
    assert {'routes', 'operations', 'tools'} <= set(shown['applicable'])
