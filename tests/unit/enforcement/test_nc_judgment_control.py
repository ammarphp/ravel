"""Judgment-route control rows: the replan loop and an unanswered question end by code, never by the planner.

The adversary is a planner whose every wave review asks for another replan, and a question nobody
answers. The oracle is the judgment route's own decision function over the recorded events
(``control.fold`` and ``control.next_phase``): a bounded ending once the replan bound is reached,
the waiting branch held while every other branch keeps running, and a conservative default that
closes only its own option. Positive controls show the same view replanning below the bound and
running a ready branch.
"""
from __future__ import annotations

from nc_cases import CONTROLLER, case, require_controller
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register

CONTROL = 'ravel.controller.judgment.control'
FRAME, COMPILED = 'f' * 64, 'c' * 64


def _accepted_plan(steps):
    """Events of a frame accepted by its credited review and a compiled plan adopted at CHECK-IN 1."""
    return [{'event': 'frame', 'round': 1, 'status': 'written', 'frame_sha256': FRAME, 'frame_record': 'frame-1'},
            {'event': 'frame_review', 'frame_sha256': FRAME, 'credited': True, 'verdict': 'pass', 'findings': []},
            {'event': 'classified', 'compiled_sha256': COMPILED, 'planner_plan_sha256': 'p' * 64, 'revision': 0,
             'steps': steps, 'deliverables': []},
            {'event': 'adopted', 'compiled_sha256': COMPILED}]


def _step(step_id, kind='derive', cls='R0', depends_on=()):
    return {'id': step_id, 'kind': kind, 'class': cls, 'spec_sha256': step_id[-1] * 64, 'depends_on': list(depends_on)}


def _replan_loop(rounds):
    """A planner whose every wave review asks for one more replan."""
    events = []
    for number in range(1, rounds + 1):
        events += [{'event': 'wave_ran', 'number': number},
                   {'event': 'wave_review', 'number': number, 'replan_request': {'reason': 'fictional: try again'}},
                   {'event': 'replan', 'number': number, 'status': 'written'},
                   {'event': 'adopted', 'compiled_sha256': f'{number}' * 64}]
    return events + [{'event': 'wave_ran', 'number': rounds + 1},
                     {'event': 'wave_review', 'number': rounds + 1, 'replan_request': {'reason': 'fictional: again'}}]


@case('JR07', binding=CONTROLLER)
def test_JR07_an_unbounded_replan_loop_ends_in_a_bounded_ending_at_the_replan_limit(nc):
    control = require_controller('judgment.control')
    bound = control.bounds(None)
    limit = bound['replans']
    base = _accepted_plan([_step('s1')])
    below = control.fold(base + _replan_loop(limit - 1), bound)
    assert control.next_phase(below, bound, now=0.0)['phase'] == 'replan'  # positive control: below the bound
    at_limit = control.fold(base + _replan_loop(limit), bound)
    decided = control.next_phase(at_limit, bound, now=0.0)
    assert decided['phase'] == 'bounded_end' and 'replan bound' in decided['reason'], decided
    # The operator's lower bound, frozen in the mode, ends the loop sooner; the planner cannot raise it.
    lowered = control.bounds({'bounds': {'replans': 1}})
    assert lowered['replans'] == 1
    assert control.next_phase(control.fold(base + _replan_loop(1), lowered), lowered, now=0.0)['phase'] == 'bounded_end'


register(Mutation('M17', f'{CONTROL}:bounds', lambda original: lambda mode: dict(original(mode), replans=10 ** 6),
                  ('JR07',), binding=MUTATION_CONTROLLER, why='the replan loop has no bound'))


@case('JR08', binding=CONTROLLER)
def test_JR08_an_unanswered_question_holds_only_its_branch_and_a_default_closes_only_its_own_option(nc):
    control = require_controller('judgment.control')
    bound = control.bounds(None)
    steps = [_step('s1', 'ask', cls='R1'), _step('s2'), _step('s3', depends_on=['s1'])]
    pending = {'event': 'authority', 'step': 's1', 'subject_sha256': steps[0]['spec_sha256'], 'state': 'pending',
               'since': 1000.0, 'wait_bound': 60}
    view = control.fold(_accepted_plan(steps) + [pending], bound)
    found = control.schedule(view, bound)
    assert [w['step'] for w in found['waiting']] == ['s1'] and found['ready'] == ['s2'], found
    assert [b['step'] for b in found['blocked']] == ['s3']
    # Within the wait bound the other branch runs; after it, the open question is reported expired.
    assert control.next_phase(view, bound, now=1010.0)['phase'] == 'execute'
    finished = control.fold(_accepted_plan(steps) + [pending, {'event': 'step_state', 'step': 's2', 'status': 'closed'}],
                            bound)
    waiting = control.next_phase(finished, bound, now=1010.0)
    assert waiting['phase'] == 'ask' and waiting['detail'].get('wait'), waiting
    expired = control.next_phase(finished, bound, now=1100.0)
    assert expired['phase'] == 'ask' and [e['step'] for e in expired['detail'].get('expired') or []] == ['s1'], expired
    # A recorded conservative default closes the question; for an R3 call it authorizes only its own option.
    defaulted = dict(pending, state='defaulted', answer='hold')
    assert control.status(steps[0], control.fold(_accepted_plan(steps) + [defaulted], bound), bound) == 'closed'
    subject = 'r' * 64
    assert control.answer({'subject_sha256': subject, 'state': 'defaulted', 'answer': 'hold'}, subject, 'hold') == 'granted'
    assert control.answer({'subject_sha256': subject, 'state': 'defaulted', 'answer': 'hold'}, subject, 'proceed') == 'held'
    assert control.answer({'subject_sha256': subject, 'state': 'pending'}, subject, 'proceed') is None


def _defaults_grant_everything(original):
    def answer(authority, subject, chosen):
        found = original(authority, subject, chosen)
        return 'granted' if (authority or {}).get('state') == 'defaulted' else found
    return answer


register(Mutation('M21', f'{CONTROL}:answer', _defaults_grant_everything, ('JR08',), binding=MUTATION_CONTROLLER,
                  why='a conservative default authorizes whatever option the call had chosen'),
         Mutation('M18', f'{CONTROL}:_authority_wait', lambda original: lambda *a, **k: True, ('JR08',),
                  binding=MUTATION_CONTROLLER, why='an unanswered question waits forever'))
