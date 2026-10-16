"""A requested tool whose signed operation yields a different artifact keeps a composition gap.

The tool here runs the amplitude-integration operation. All fixtures are synthetic."""
from ravel.validation import validate_request_plan as vp
from ravel.workflow import request_plan as planner
from request_plan_corpus import Reading


def test_signed_tool_with_different_outputs_keeps_a_separate_composition_gap():
    prompt = 'Generate an event sample with MCFM.'
    case = Reading(prompt)
    case.constraint('requested_tool', {'tool': 'MCFM'}, 'MCFM')
    case.constraint('requested_stage', {'stage': 'generation'}, 'MCFM')
    case.deliverable('event_sample', 'prediction', ['original-request'])
    plan = planner.draft(case.doc, case.contract(), catalogue=lambda _: False)
    assert any(n['operation'] == 'amplitude-integration' and n['status'] == 'available' for n in plan['nodes'])
    gaps = [n for n in plan['nodes'] if n['status'] == 'held']
    assert gaps and all(n['held_by'] == 'plan-composition' for n in gaps)
    assert not any(n['operation'] == 'generate' and n['status'] == 'available' for n in plan['nodes'])
    assert vp.check(case.doc, plan, obligations=case.obligations, catalogue=lambda _: False) == []
