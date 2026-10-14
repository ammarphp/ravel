"""Requested tools are selected from signatures; all fixtures are synthetic."""
from copy import deepcopy

import pytest

from ravel.validation import validate_request_plan as vp
from ravel.workflow import request_plan as planner, request_reading as reader
from request_plan_corpus import Reading

SIGNED_TOOLS = sorted({tool for sig in vp.signatures().values() for tool in sig['tools']})
PHRASINGS = ('Use {tool}{stage}.', 'Please run{stage} with {tool}.', 'For this study, employ {tool}{stage}.')


@pytest.mark.parametrize('tool', SIGNED_TOOLS)
@pytest.mark.parametrize('phrasing', PHRASINGS)
def test_every_signed_tool_drafts_a_registered_operation(tool, phrasing):
    signature = next(s for s in vp.signatures().values() if tool in s['tools'])
    stage = signature['stages'][0] if signature['stages'] else None
    prompt = phrasing.format(tool=tool, stage=' for '+stage if stage else '')
    case = Reading(prompt)
    case.constraint('requested_tool', {'tool': tool}, tool)
    if stage:
        case.constraint('requested_stage', {'stage': stage}, tool)
    plan = planner.draft(case.doc, case.contract(), catalogue=lambda _: False)
    nodes = [n for n in plan['nodes'] if n['operation'] and tool in vp.registry()[n['operation']]['tools']]
    assert nodes and all(n['status'] == 'available' for n in nodes)
    assert not any(n['status'] == 'held' for n in plan['nodes'])
    assert vp.check(case.doc, plan, obligations=case.obligations, catalogue=lambda _: False) == []


@pytest.mark.parametrize('prompt', [
    'Analyze the supplied events with Rivet and report the distributions.',
    'Use SimpleAnalysis to analyze our event sample and return the yields.',
    'Apply Rivet to the provided events and predict the spectrum.',
])
def test_template_stage_is_replaced_by_the_operation_running_the_tool(prompt):
    reading = reader.document(prompt)
    plan = planner.draft(reading, {'prompt': prompt}, catalogue=lambda _: False)
    analysis = [n for n in plan['nodes'] if n['status'] == 'available' and n['operation']
                and 'analysis' in vp.registry()[n['operation']]['stages']]
    assert analysis and all(n['operation'] == 'analyze' for n in analysis)
    assert not any(n['status'] == 'held' for n in plan['nodes'])
    assert vp.check(reading, plan, catalogue=lambda _: False) == []


@pytest.mark.parametrize('wording', PHRASINGS)
def test_unsigned_tool_is_held_with_a_concrete_integration_request(wording):
    prompt = wording.format(tool='SyntheticEngine', stage=' for shower')
    case = Reading(prompt)
    case.constraint('requested_tool', {'tool': 'SyntheticEngine'}, 'SyntheticEngine')
    case.constraint('requested_stage', {'stage': 'shower'}, 'SyntheticEngine')
    plan = planner.draft(case.doc, case.contract(), catalogue=lambda _: False)
    held = [n for n in plan['nodes'] if n['status'] == 'held']
    assert held and any('SyntheticEngine' in n['request'] for n in held)
    assert vp.check(case.doc, plan, obligations=case.obligations, catalogue=lambda _: False) == []


@pytest.mark.parametrize('prompt', [
    'Analyze the supplied events with Rivet; use pyhf for the upper limits.',
    'Analyze our event sample using SimpleAnalysis and set CLs limits with pyhf.',
    'Use Rivet for event analysis and pyhf for the exclusion.',
])
def test_chained_tool_substitution_preserves_typed_edges_and_unique_ids(prompt):
    reading = reader.document(prompt)
    plan = planner.draft(reading, {'prompt': prompt}, catalogue=lambda _: False)
    assert vp.check(reading, plan, catalogue=lambda _: False) == []
    assert len({e['id'] for e in plan['edges']}) == len(plan['edges'])
    assert all(n['status'] == 'available' for n in plan['nodes'])
    assert any(n['operation'] == 'analyze' for n in plan['nodes'])


def test_repeated_tool_requests_do_not_create_duplicate_fields():
    case = Reading('Use Rivet for analysis; use Rivet for analysis again.')
    for _ in range(2):
        case.constraint('requested_tool', {'tool': 'Rivet'}, 'Rivet')
        case.constraint('requested_stage', {'stage': 'analysis'}, 'Rivet')
    plan = planner.draft(case.doc, case.contract(), catalogue=lambda _: False)
    assert vp.check(case.doc, plan, obligations=case.obligations, catalogue=lambda _: False) == []


def test_negated_stage_cannot_be_added_by_a_requested_tool():
    case = Reading('Use Delphes for detector simulation; no shower.')
    case.constraint('requested_tool', {'tool': 'Delphes'}, 'Delphes')
    case.constraint('requested_stage', {'stage': 'detector'}, 'Delphes')
    case.constraint('negated_stage', {'stage': 'shower'}, 'no shower')
    plan = planner.draft(case.doc, case.contract(), catalogue=lambda _: False)
    assert vp.check(case.doc, plan, obligations=case.obligations, catalogue=lambda _: False) == []
    assert not any(n['status'] == 'available' and 'shower' in vp._stages(n, vp.registry()) for n in plan['nodes'])
