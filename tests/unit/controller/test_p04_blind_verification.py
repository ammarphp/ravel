"""A blind verifier that may not see the producer's result verifies blind; the controller compares the values.

The reviewer stays blind: its projection is the step's governed inputs, never the producer's headline output. It
writes its own value of the quantity the approved plan names (``parameters.verification``), and the controller
compares that value with the producer's result within the approved tolerance. Agreement credits the seat; a
disagreement, or a comparison that cannot be made, escalates the step and never passes silently. A step that
declares no verification gets no verification seat: the blind card reviews only what it may see.
"""
from __future__ import annotations

import json

import pytest

from ravel.controller.step.services import digest
from test_p04_support import (graphs, inert_worker, make_step, records, run_env, run_step,  # noqa: F401
                              services_installed)

VERIFIER = 'skeptical-verifier'
DECLARED = {'output': 'outputs/result.json', 'pointer': '/value', 'unit': '1', 'relative_tolerance': 0.05}


@pytest.fixture
def blind_transport(monkeypatch):
    """Stand in for the qualified blind-capable restricted CLI worker (as the other blind seat tests do)."""
    from ravel.workflow import transport_registry as tr
    monkeypatch.setattr(tr, 'blind_admissible', lambda document, capabilities=None: True)


def _step(**parameters):
    return make_step('s1', review=[VERIFIER], outputs=(('outputs/result.json', 'result'),), parameters=parameters)


def _seat_writes(value):
    return {'seats': {VERIFIER: {'writes': [
        {'path': f'outputs/review-{VERIFIER}-1.json', 'content': json.dumps({'value': value})},
        {'path': f'outputs/independent-{VERIFIER}-1.json', 'content': json.dumps({'value': value})}]}}}


def test_an_agreeing_blind_verification_credits_the_seat_and_the_step_completes(run_env, inert_worker, graphs,
                                                                               blind_transport):
    outcome = run_step(run_env, _step(verification=DECLARED))
    assert outcome['status'] == 'completed', outcome
    [verified] = records(run_env.store, 'step-verification')
    assert verified['outcome'] == 'agree' and verified['comparison']['passed'] is True, verified
    assert verified['declared'] == DECLARED and verified['seat'] == f'seat:{VERIFIER}:1'
    kept = run_env.run_dir / verified['independent']['path']
    assert kept.is_file() and json.loads(kept.read_text())['value'] == 1
    seat = next(r for r in outcome['review']['seats'] if r['seat'] == f'seat:{VERIFIER}:1')
    assert seat['credited'] is True and seat['verification']['outcome'] == 'agree', seat
    # The verifier reviewed the step's governed inputs (none here), never the producer's adopted result.
    assert seat['query']['subject_sha256'] == digest([]), seat


def test_a_disagreeing_blind_verification_escalates_the_step(run_env, inert_worker, graphs, blind_transport):
    inert_worker.scenario(**_seat_writes(2))
    outcome = run_step(run_env, _step(verification=DECLARED))
    assert outcome['status'] == 'escalated' and outcome['escalation'] == 'stop', outcome
    [verified] = records(run_env.store, 'step-verification')
    assert verified['outcome'] == 'mismatch' and verified['comparison']['passed'] is False, verified
    escalation = [r for r in records(run_env.store, 'step-escalation') if r['seat'] == f'seat:{VERIFIER}:1']
    assert escalation and escalation[0]['kind'] == 'stop' and escalation[0]['action'] == 'halt_and_notify'
    assert len(escalation[0]['evidence']) == 1 and 'mismatch' in escalation[0]['statement'], escalation


def test_a_step_that_declares_no_verification_gets_no_verification_seat(run_env, inert_worker, graphs,
                                                                       blind_transport):
    # Seats follow declared obligations: without an approved verification the blind card keeps its declared review
    # of what it may see (the governed inputs and the step's other outputs), writes no independent value, and the
    # controller compares nothing. The producer's headline is never one of its subjects.
    step = make_step('s1', review=[VERIFIER],
                     outputs=(('outputs/result.json', 'result'), ('outputs/table.json', 'result')))
    outcome = run_step(run_env, step)
    assert outcome['status'] == 'completed', outcome
    assert records(run_env.store, 'step-verification') == []
    seat = next(r for r in outcome['review']['seats'] if r['seat'] == f'seat:{VERIFIER}:1')
    assert seat['credited'] is True and 'verification' not in seat, seat
    # A blind card shown the headline result as a subject is refused by its projection (``subject_forbidden``), so
    # the credited seat reviewed only what it may see.
    from ravel.controller.step import custody
    index = custody.custody_index(run_env.store)
    assert index['s1:outputs/result.json']['status'] == index['s1:outputs/table.json']['status'] == 'accepted'
    assert not list(run_env.run_dir.rglob(f'independent-{VERIFIER}-1.json'))


def test_a_reviewer_that_is_not_blind_reviews_the_result_as_before(run_env, inert_worker, graphs):
    # This card keeps producer headlines out of the files it browses, but its profile is not blind: its review
    # subjects are shown as they are, so it reviews the result itself and the controller compares nothing.
    step = make_step('s1', review=['integrity-auditor'], outputs=(('outputs/result.json', 'result'),),
                     parameters={'verification': DECLARED})
    outcome = run_step(run_env, step)
    assert outcome['status'] == 'completed', outcome
    seat = next(r for r in outcome['review']['seats'] if r['seat'] == 'seat:integrity-auditor:1')
    assert seat['credited'] is True and 'verification' not in seat, seat
    assert records(run_env.store, 'step-verification') == []


def test_a_result_the_blind_card_may_see_is_reviewed_as_before(run_env, inert_worker, graphs, blind_transport):
    step = make_step('s1', review=[VERIFIER], outputs=(('outputs/table.json', 'result'),),
                     parameters={'verification': {**DECLARED, 'output': 'outputs/table.json'}})
    run_step(run_env, step)
    assert records(run_env.store, 'step-verification') == []
