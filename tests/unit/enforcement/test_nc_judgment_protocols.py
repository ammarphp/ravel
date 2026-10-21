"""Judgment-protocol rows: a judgment call carries the evidence its triggers require, and plans stay typed.

The adversary is a scripted planner or worker: it declares a resource unavailable without walking the
source ladder, closes a stage failure without a recipe search, adopts a critical default without a
recorded justification, compares without basis manifests, escalates a method without accounting for
cheaper rungs, delivers without the three kill-the-result attacks, frames a question that drops a
deliverable, plans an untyped or inline step, or substitutes held scope. The cases drive the judgment
package's record, frame, plan and attack checks; positive controls supply the evidence or the well-formed document.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from nc_cases import CONTROLLER, case, require_controller
from nc_controller import controller_run
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register

RECORD_KIND = 'judgment-record'


def _record(step='s04', *, kind='plot_style', triggers=(), evidence=None, **changes):
    record = {'schema_version': 1, 'kind': 'judgment-record', 'id': f'j-{step}', 'step': step,
              'question': 'Which fictional option should the run take?',
              'options': [{'id': 'first', 'description': 'The first fictional option.',
                           'predicted_consequences': 'A narrower fictional result.'},
                          {'id': 'second', 'description': 'The second fictional option.',
                           'predicted_consequences': 'A broader fictional result.'}],
              'chosen': 'first', 'rationale': 'The request asks for the narrower result.',
              'action': {'summary': 'A fictional judgment call.', 'kind': kind}, 'triggers': list(triggers),
              'protocol_evidence': deepcopy(evidence or {}),
              'reversibility': {'kind': 'reversible', 'note': 'It can be redone.'},
              'budget_impact': {'note': 'Negligible.'}}
    record.update(changes)
    return record


def _refused_then_recorded(nc, bad, good):
    judgment = require_controller('judgment')
    store, _ = controller_run(nc)
    with pytest.raises(judgment.JudgmentRecordError) as refused:
        judgment.record_judgment(store, bad)
    assert store.scan(RECORD_KIND) == []
    judgment.record_judgment(store, good)  # positive control
    assert len(store.scan(RECORD_KIND)) == 1
    return refused.value.errors


LADDER_NAMES = {1: 'publication', 2: 'data_record', 3: 'public_code', 4: 'recast_database', 5: 'citing_work'}


@case('E03', binding=CONTROLLER)
def test_E03_an_unavailable_resource_claim_needs_the_walked_source_ladder(nc):
    walked = {'claim': 'unavailable',
              'rungs': [{'rung': n, 'name': name, 'status': 'ABSENT', 'evidence': f'fictional search {n}',
                         'reason': None} for n, name in LADDER_NAMES.items()]}
    skipped = deepcopy(walked)
    skipped['rungs'][2]['status'] = 'SKIPPED'
    errors = _refused_then_recorded(nc, _record(kind='resource_unavailable', evidence={'P6': skipped}),
                                    _record(kind='resource_unavailable', evidence={'P6': walked}))
    assert any('P6 rung 3' in e for e in errors), errors
    missing = _record(kind='resource_unavailable')
    judgment = require_controller('judgment')
    assert any('missing P6' in e for e in judgment.check_record(missing)), judgment.check_record(missing)


@case('E12', binding=CONTROLLER)
def test_E12_stage_recovery_needs_local_diagnosis_and_a_recipe_search_record(nc):
    recovery = {'failure': {'step': 's03', 'summary': 'The fictional generator stage exited with an error.'},
                'local_diagnosis': {'summary': 'A fictional input was malformed.', 'evidence': ['logs/fictional.log']},
                'recipe_search': {'path': 'inputs/recipe_search.json', 'sha256': 'a' * 64, 'hits': 0},
                'diagnosis_class': 'input'}
    hollow = deepcopy(recovery)
    hollow['local_diagnosis']['evidence'] = []
    errors = _refused_then_recorded(nc, _record(kind='stage_recovery', evidence={'recovery': hollow}),
                                    _record(kind='stage_recovery', evidence={'recovery': recovery}))
    assert any('local_diagnosis' in e or 'local diagnosis' in e for e in errors), errors
    judgment = require_controller('judgment')
    assert any('missing recovery' in e for e in judgment.check_record(_record(kind='stage_recovery')))


P7_DEFAULT = {'assumption': 'The fictional efficiency is flat.', 'default': 'flat efficiency',
              'alternatives': ['binned efficiency'], 'claim_type': 'exclusion', 'direction_established': False,
              'expected_sign': 'unknown', 'expected_size': 'about five percent', 'reversible_knob': 'efficiency model',
              'flag': {'checkin_flag': 1, 'deviation': 'deviation-1'}, 'physics_critical': True,
              'justification': {'kind': 'request_span', 'reference': 'request characters 10-40'}}


@case('C08', binding=CONTROLLER)
def test_C08_a_physics_critical_default_needs_its_justified_default_record(nc):
    unjustified = dict(P7_DEFAULT, justification=None)
    judgment = require_controller('judgment')
    bad = _record(triggers=['adopt_default'], evidence={'P7': unjustified})
    errors = judgment.check_record(bad)
    assert any('physics-critical default needs a justification' in e for e in errors), errors
    assert any('missing P7' in e for e in judgment.check_record(_record(triggers=['adopt_default'])))
    good = _record(triggers=['adopt_default'], evidence={'P7': P7_DEFAULT})
    good_errors = judgment.check_record(good)
    assert not [e for e in good_errors if 'P7' in e], good_errors  # positive control: the record's P7 is accepted


P2_MANIFEST = {'states_summed': 'all', 'order': 'leading', 'pdf': 'fictional-set', 'sample': 'inclusive',
               'column': 'observed', 'channel': 'combined', 'normalization': 'per bin'}


@case('E28', binding=CONTROLLER)
def test_E28_a_comparison_judgment_without_matching_basis_manifests_is_refused(nc):
    judgment = require_controller('judgment')
    left, right = dict(P2_MANIFEST, side='ours'), dict(P2_MANIFEST, side='reference')
    matched = {'manifests': [left, right], 'transformation': {'applied_to': None, 'description': 'none', 'result': None},
               'identity_check': {'kind': 'closure', 'expected': 1.0, 'measured': 1.0, 'tolerance': 0.01}}
    mismatched = deepcopy(matched)
    mismatched['manifests'][1]['order'] = 'next-to-leading'
    assert any('missing P2' in e for e in judgment.check_record(_record(triggers=['compare'])))
    errors = judgment.check_record(_record(triggers=['compare'], evidence={'P2': mismatched}))
    assert any('manifests still differ' in e for e in errors), errors
    assert judgment.check_record(_record(triggers=['compare'], evidence={'P2': matched})) == []  # positive


@case('C01', binding=CONTROLLER)
def test_C01_a_method_escalation_without_cheaper_rung_accounting_is_refused(nc):
    judgment = require_controller('judgment')
    escalation = _record(kind='method_escalation')
    assert any('missing method_ladder' in e for e in judgment.check_record(escalation))
    forged = _record(kind='method_escalation', evidence={'method_ladder': {'selected': 'top rung', 'reason': 'faster'}})
    assert judgment.check_record(forged), 'an unstructured ladder claim is not cheaper-rung accounting'
    assert judgment.check_record(_record(kind='method_choice')) == []  # positive control: a choice with no escalation


register(Mutation('M21', ('ravel.controller.judgment.protocols:check_required',),
                  lambda original: lambda *a, **k: [], ('E03', 'E28', 'C01'), binding=MUTATION_CONTROLLER,
                  why='protocol evidence is not required for a judgment call'))


ATTACKS = [{'axis': axis, 'attack': f'A fictional {axis} attack.', 'test': f'A fictional {axis} test.',
            'outcome': 'survives', 'evidence': [f'outputs/attack-{axis}.json']}
           for axis in ('basis', 'acceptance', 'statistics')]


@case('JR09', binding=CONTROLLER)
def test_JR09_delivery_needs_three_recorded_attacks_on_the_exact_draft(nc):
    judgment = require_controller('judgment')
    subject = {'plan_sha256': 'a' * 64, 'draft_sha256': 'b' * 64}
    complete = {'schema_version': 1, 'kind': 'judgment-attacks', 'subject': subject, 'attacks': deepcopy(ATTACKS)}
    assert judgment.check_attacks(complete, **subject) == []  # positive control
    two = dict(complete, attacks=deepcopy(ATTACKS[:2]))
    assert judgment.check_attacks(two, **subject)
    twice = dict(complete, attacks=[*deepcopy(ATTACKS[:2]), dict(ATTACKS[0])])
    assert judgment.check_attacks(twice, **subject)
    assert judgment.check_attacks(complete, plan_sha256='a' * 64, draft_sha256='c' * 64), 'a stale draft is not attacked'


register(Mutation('M11', ('ravel.controller.judgment.protocols:check_attacks', 'ravel.controller.judgment:check_attacks'),
                  lambda original: lambda *a, **k: [], ('JR09',), binding=MUTATION_CONTROLLER,
                  why='delivery proceeds without the kill-the-result attacks'))


def _frame(request_sha256, *, deliverables=('d1', 'd2'), boundaries=()):
    return {'schema_version': 1, 'kind': 'question-frame', 'request_sha256': request_sha256,
            'objective': 'Compute two fictional quantities of the toy model.',
            'deliverables': [{'id': f'D{n}', 'reading_ref': ref, 'description': f'fictional quantity {n}',
                              'acceptance': 'finite value with its uncertainty', 'statistic': 'none',
                              'units': 'fictional unit'} for n, ref in enumerate(deliverables, 1)],
            'constraints': [], 'unknowns': [],
            'assumptions': [{'number': 1, 'statement': 'The toy model has unit coupling.',
                             'basis': 'stated in the request', 'physics_critical': False}],
            'boundaries': [dict(b) for b in boundaries]}


def _reading(*, boundaries=()):
    return {'deliverables': [{'id': 'd1'}, {'id': 'd2'}], 'constraints': [], 'ambiguities': [],
            'boundaries': [dict(b) for b in boundaries]}


@case('JR02', binding=CONTROLLER)
def test_JR02_a_frame_that_drops_a_deliverable_or_misnumbers_assumptions_is_refused(nc):
    planning = require_controller('judgment.planning')
    sha = hashlib.sha256(b'fictional request').hexdigest()
    assert planning.check_frame(_frame(sha), _reading(), sha) == []  # positive control
    dropped = planning.check_frame(_frame(sha, deliverables=('d1',)), _reading(), sha)
    assert any('reading deliverable d2 is missing from the frame' in e for e in dropped), dropped
    misnumbered = _frame(sha)
    misnumbered['assumptions'][0]['number'] = 2
    assert any('numbered' in e for e in planning.check_frame(misnumbered, _reading(), sha))
    assert any('pinned request' in e for e in planning.check_frame(_frame('c' * 64), _reading(), sha))


def _step(step_id, kind='derive', **changes):
    step = {'id': step_id, 'kind': kind, 'purpose': f'fictional {kind} step', 'inputs': [],
            'outputs': [{'path': f'outputs/{step_id}.json', 'kind': 'result', 'required': True}], 'depends_on': [],
            'budget_share': {'fraction': 0.2}, 'protocols': [], 'review': [], 'obligations': []}
    step.update(changes)
    return step


def _plan(frame, steps):
    return {'schema_version': 1, 'kind': 'judgment-plan',
            'frame_sha256': hashlib.sha256(json.dumps(frame, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'steps': steps,
            'deliverables': [{'id': f'D{n}', 'status': 'planned', 'outputs': [{'step': s['id'], 'path': s['outputs'][0]['path']}]}
                             for n, s in enumerate(steps[:2], 1)]}


def _frame_digest_like_planning(planning, frame):
    digest = getattr(planning, 'frame_sha256', None) or getattr(planning, 'digest', None)
    return digest(frame) if callable(digest) else None


@case('JR03', binding=CONTROLLER)
def test_JR03_a_plan_step_of_unknown_kind_or_without_outputs_is_refused(nc):
    planning = require_controller('judgment.planning')
    sha = hashlib.sha256(b'fictional request').hexdigest()
    frame = _frame(sha)
    plan = _plan(frame, [_step('s1'), _step('s2')])
    found = _frame_digest_like_planning(planning, frame)
    if found is not None:
        plan['frame_sha256'] = found
    clean = planning.check_plan(plan, frame)
    assert clean == [], clean  # positive control
    unknown = deepcopy(plan)
    unknown['steps'][1]['kind'] = 'fictional-kind'
    assert planning.check_plan(unknown, frame)
    hollow = deepcopy(plan)
    hollow['steps'][0]['outputs'] = []
    assert planning.check_plan(hollow, frame)


@case('JR04', binding=CONTROLLER)
def test_JR04_a_planner_cannot_execute_a_step_inline(nc):
    planning = require_controller('judgment.planning')
    sha = hashlib.sha256(b'fictional request').hexdigest()
    frame = _frame(sha)
    plan = _plan(frame, [_step('s1'), _step('s2')])
    found = _frame_digest_like_planning(planning, frame)
    if found is not None:
        plan['frame_sha256'] = found
    assert planning.check_plan(plan, frame) == []  # positive control
    for field in ('command', 'script', 'argv', 'python'):
        inline = deepcopy(plan)
        inline['steps'][0][field] = ['python', '-c', 'print(1)'] if field == 'argv' else 'print(1)'
        problems = planning.check_plan(inline, frame)
        assert problems, f'an inline {field} field was admitted'


register(Mutation('M27', 'ravel.controller.judgment.planning:check_plan', lambda original: lambda *a, **k: [],
                  ('JR03', 'JR04'), binding=MUTATION_CONTROLLER, why='plans are not checked'))


@case('R10', binding=CONTROLLER)
def test_R10_held_scope_stays_a_boundary_and_is_never_silently_substituted(nc):
    planning = require_controller('judgment.planning')
    sha = hashlib.sha256(b'fictional request').hexdigest()
    boundary = {'id': 'b1', 'class': 'private_input', 'statement': 'The fictional private table is not supplied.'}
    held = {'id': 'B1', 'statement': 'The private table is not available.', 'holds': ['D2'],
            'would_make_possible': 'the physicist supplies the table', 'reading_ref': 'b1'}
    reading = _reading(boundaries=[boundary])
    dropped = planning.check_frame(_frame(sha), reading, sha)
    assert any('reading boundary b1' in e for e in dropped), dropped
    assert planning.check_frame(_frame(sha, boundaries=[held]), reading, sha) == []  # positive control
