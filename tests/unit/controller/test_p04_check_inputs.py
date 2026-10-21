"""The validator parameters a plan approves with a step (``parameters.check_inputs``) reach the step's checks.

A pin naming the step's own declared output is bound to the bytes adopted for it in that attempt; every other pin is
passed as the plan states it, and the validator checks the bytes. The validator itself is never relaxed: an output
that was not adopted, a reference inside the fit's input closure or a missing declaration never passes.
"""
from __future__ import annotations

import hashlib
import json

from ravel.controller.step import graph, validate
from ravel.workflow import role_registry

from test_p04_support import make_step

CLOSURE = 'check:validation.input_closure.check'


def _pin(run, path):
    return {'path': path.relative_to(run).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def _write(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, sort_keys=True))
    return path


def _closure(run, scratch, step, adopted):
    report = validate.run_validators(role_registry.load('calculation'),
                                     {**step, 'check_inputs': graph._bound_check_inputs(step, adopted)},
                                     run_dir=run, scratch=scratch)
    return next(r for r in report['results'] if r['check_id'] == CLOSURE)


def test_a_step_check_input_naming_its_own_output_is_bound_to_the_adopted_bytes(tmp_path):
    run, scratch = tmp_path / 'run', tmp_path / 'scratch'
    reading = _write(run / 'inputs' / 'reading.json', {'deliverables': ['D1']})
    reference = _write(run / 'inputs' / 'reference.json', {'value': 2.0})
    result = _write(run / 'steps' / 's1' / 'outputs' / 'result.json', {'value': 1.0, 'inputs': [_pin(run, reading)]})
    adopted = [{'path': 'outputs/result.json', 'destination': 'steps/s1/outputs/result.json',
                'sha256': _pin(run, result)['sha256']}]
    step = make_step('s1', parameters={'check_inputs': {CLOSURE: {'fit': {'output': 'outputs/result.json'},
                                                                  'reference': _pin(run, reference)}}})
    bound = graph._bound_check_inputs(step, adopted)
    assert bound[CLOSURE]['fit'] == {'path': 'steps/s1/outputs/result.json', 'sha256': adopted[0]['sha256']}
    assert bound[CLOSURE]['reference'] == _pin(run, reference)
    assert _closure(run, scratch, step, adopted)['status'] == 'passed'
    # The same output never adopted in this attempt stays as declared: the validator refuses it.
    assert graph._bound_check_inputs(step, [])[CLOSURE]['fit'] == {'output': 'outputs/result.json'}
    assert _closure(run, scratch, step, [])['status'] == 'failed'


def test_a_reference_inside_the_fit_input_closure_still_refuses(tmp_path):
    run, scratch = tmp_path / 'run', tmp_path / 'scratch'
    reference = _write(run / 'inputs' / 'reference.json', {'value': 2.0})
    result = _write(run / 'steps' / 's1' / 'outputs' / 'result.json', {'value': 1.0, 'inputs': [_pin(run, reference)]})
    adopted = [{'path': 'outputs/result.json', 'destination': 'steps/s1/outputs/result.json',
                'sha256': _pin(run, result)['sha256']}]
    step = make_step('s1', parameters={'check_inputs': {CLOSURE: {'fit': {'output': 'outputs/result.json'},
                                                                  'reference': _pin(run, reference)}}})
    found = _closure(run, scratch, step, adopted)
    assert found['status'] == 'failed' and 'reference_in_input_closure' in found['diagnostics']


def test_a_step_without_approved_check_inputs_stays_inconclusive(tmp_path):
    run, scratch = tmp_path / 'run', tmp_path / 'scratch'
    for parameters in ({}, {'check_inputs': ['fit', 'reference']}):
        step = make_step('s1', parameters=parameters)
        assert graph._bound_check_inputs(step, []) == {}
        assert _closure(run, scratch, step, [])['status'] == 'inconclusive'


def _seat(parent, adopted, role='skeptical-verifier'):
    seat = {'key': f'seat:{role}:1', 'purpose': 'review', 'role': role, 'n': 1,
            'subject': graph._subject(adopted), 'items': [], 'trigger': None}
    return graph.seat_step(parent, seat)


def _seat_closure(run, scratch, seat):
    # A seat's own adoption is its findings; the checks bind the seat's declared parameters as for any step.
    report = validate.run_validators(role_registry.load('skeptical-verifier'),
                                     {**seat, 'check_inputs': graph._bound_check_inputs(seat, [])},
                                     run_dir=run, scratch=scratch)
    return next(r for r in report['results'] if r['check_id'] == CLOSURE)


def test_a_review_seat_checks_the_parent_bindings_against_the_reviewed_attempt(tmp_path):
    run, scratch = tmp_path / 'run', tmp_path / 'scratch'
    reading = _write(run / 'inputs' / 'reading.json', {'deliverables': ['D1']})
    reference = _write(run / 'inputs' / 'reference.json', {'value': 2.0})
    result = _write(run / 'steps' / 's1' / 'outputs' / 'result.json', {'value': 1.0, 'inputs': [_pin(run, reading)]})
    adopted = [{'artifact': 's1:outputs/result.json', 'path': 'outputs/result.json', 'attempt': 2,
                'destination': 'steps/s1/outputs/result.json', 'sha256': _pin(run, result)['sha256']}]
    parent = make_step('s1', parameters={'check_inputs': {CLOSURE: {'fit': {'output': 'outputs/result.json'},
                                                                    'reference': _pin(run, reference)}}})
    seat = _seat(parent, adopted)
    bound = seat['parameters']['check_inputs'][CLOSURE]
    assert bound['fit'] == {'path': 'steps/s1/outputs/result.json', 'sha256': adopted[0]['sha256']}
    assert bound['reference'] == _pin(run, reference)
    assert _seat_closure(run, scratch, seat)['status'] == 'passed'
    # The seat's own declared output never captures the parent's pin.
    assert all(output['path'] != 'outputs/result.json' for output in seat['outputs'])
    # The bytes changed after the reviewed attempt: the inherited pin names the reviewed digest and refuses them.
    _write(run / 'steps' / 's1' / 'outputs' / 'result.json', {'value': 3.0, 'inputs': [_pin(run, reading)]})
    assert _seat_closure(run, scratch, seat)['status'] == 'failed'


def test_a_review_seat_never_binds_an_output_outside_its_subject(tmp_path):
    run, scratch = tmp_path / 'run', tmp_path / 'scratch'
    reference = _write(run / 'inputs' / 'reference.json', {'value': 2.0})
    parent = make_step('s1', parameters={'check_inputs': {CLOSURE: {'fit': {'output': 'outputs/result.json'},
                                                                    'reference': _pin(run, reference)}}})
    seat = _seat(parent, [])
    assert seat['parameters']['check_inputs'][CLOSURE]['fit'] == {'output': 'outputs/result.json', 'step': 's1'}
    assert graph._bound_check_inputs(seat, [{'path': 'outputs/result.json', 'destination': 'x', 'sha256': '0' * 64}]
                                     )[CLOSURE]['fit'] == {'output': 'outputs/result.json', 'step': 's1'}
    assert _seat_closure(run, scratch, seat)['status'] != 'passed'
    # A parent without an approved parameter object gives its seat none: the validator stays inconclusive.
    bare = _seat(make_step('s1'), [])
    assert 'check_inputs' not in bare['parameters']
    assert _seat_closure(run, scratch, bare)['status'] == 'inconclusive'
