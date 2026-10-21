"""Judgment rows: consequence classes come from code tables, and every judgment call has a record.

The adversary is a scripted planner or worker that labels a physics-critical action R1, invents
an unknown action kind, or takes a decision without a valid record. Oracles read the class the
controller stores and the store's judgment records; positive controls are ordinary R1 calls.
"""
from __future__ import annotations

import pytest

from nc_cases import CONTROLLER, case, require_controller
from nc_controller import checkin_view, controller_run
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register

RECORD_KIND = 'judgment-record'


def judgment_record(step='s04', *, kind='plot_style', declared=None, worker_class=None, **changes):
    """A complete fictional judgment record written by a worker."""
    action = {'summary': 'Choose how to present the fictional observable.', 'kind': kind}
    if declared is not None:
        action['declared_class'] = declared
    record = {'schema_version': 1, 'kind': 'judgment-record', 'id': f'j-{step}', 'step': step,
              'question': 'How should the fictional observable be presented?',
              'options': [{'id': 'table', 'description': 'A table of values.',
                           'predicted_consequences': 'Exact values; no visual comparison.'},
                          {'id': 'figure', 'description': 'A figure with uncertainty bands.',
                           'predicted_consequences': 'Visual comparison; values read from the figure.'}],
              'chosen': 'figure', 'rationale': 'The request asks for a comparison.', 'action': action,
              'triggers': [], 'protocol_evidence': {},
              'reversibility': {'kind': 'reversible', 'note': 'The presentation can be redone.'},
              'budget_impact': {'note': 'Negligible.'}}
    if worker_class is not None:
        record['class'] = worker_class
    record.update(changes)
    return record


@case('A05', binding=CONTROLLER)
def test_A05_a_physics_critical_ambiguity_labelled_R1_is_classified_R3_by_code(nc):
    judgment = require_controller('judgment')
    critical = {'summary': 'Pick a mass hypothesis the request leaves open.', 'kind': 'physics_critical_ambiguity',
                'declared_class': 'R1'}
    assert judgment.classify(critical) == 'R3'
    assert judgment.classify({'summary': 'An action kind no table knows.', 'kind': 'fictional_unknown_kind'}) == 'R3'
    assert judgment.classify({'summary': 'Nothing classifiable.'}) == 'R3'
    assert judgment.classify({'summary': 'Adopt a default left to the physicist.', 'effects': ['adopt_default_left_to_physicist'],
                              'declared_class': 'R0'}) == 'R3'
    # Positive control: an ordinary presentation choice stays R1, and a planner may raise it.
    assert judgment.classify({'summary': 'Plot style.', 'kind': 'plot_style'}) == 'R1'
    assert judgment.classify({'summary': 'Plot style.', 'kind': 'plot_style', 'declared_class': 'R2'}) == 'R2'


def _declared_wins(original):
    """The class follows the worker's declaration (a planner can lower it)."""
    def explain(action):
        found = original(action)
        declared = action.get('declared_class') if isinstance(action, dict) else None
        if declared in ('R0', 'R1', 'R2', 'R3'):
            return dict(found, **{'class': declared})
        return found
    return explain


register(Mutation('M21', 'ravel.controller.judgment.classes:explain', _declared_wins, ('A05', 'JR06'),
                  binding=MUTATION_CONTROLLER, why='the declared class replaces the computed one'))


@case('JR06', binding=CONTROLLER)
def test_JR06_an_R3_action_under_an_R1_record_is_recomputed_and_needs_authority(nc):
    judgment = require_controller('judgment')
    authority = require_controller('authority')
    store, _ = controller_run(nc, mode='autonomous')
    record_id = judgment.record_judgment(store, judgment_record(kind='physics_critical_ambiguity', declared='R1',
                                                                worker_class='R1'))
    stored = store.read(RECORD_KIND, record_id)
    body = stored.get('record', stored)
    assert body['class'] == 'R3' and body['reviewer_requirement'] == 'authority', body
    # The R3 action is not granted by machine authority inside an autonomous run: it escalates.
    subject = {'view': checkin_view(store, 'r3_action', action_sha256='f' * 64), 'gate': 'unblind'}
    result = authority.request(store, 'r3_action', subject, {})
    assert 'pending' in result, result
    # Positive control: an R1 call is stored as R1 and reported at the next check-in.
    ordinary = judgment.record_judgment(store, judgment_record('s05'))
    body = store.read(RECORD_KIND, ordinary).get('record', store.read(RECORD_KIND, ordinary))
    assert body['class'] == 'R1' and body['reviewer_requirement'] == 'report_at_next_checkin'


@case('JR05', binding=CONTROLLER)
def test_JR05_a_judgment_without_a_valid_record_is_refused_and_leaves_nothing(nc):
    judgment = require_controller('judgment')
    store, _ = controller_run(nc)
    head = store.head()
    broken = [judgment_record(options=[{'id': 'only', 'description': 'One option.',
                                        'predicted_consequences': 'Unknown.'}], chosen='only'),
              judgment_record(chosen='not-an-option'),
              {k: v for k, v in judgment_record().items() if k != 'rationale'}]
    for record in broken:
        with pytest.raises(ValueError):
            judgment.record_judgment(store, record)
    assert store.scan(RECORD_KIND) == [] and store.head() == head
    judgment.record_judgment(store, judgment_record())  # positive control
    assert len(store.scan(RECORD_KIND)) == 1


register(Mutation('M21', 'ravel.controller.judgment.records:check_record', lambda original: lambda *a, **k: [],
                  ('JR05',), binding=MUTATION_CONTROLLER, why='judgment records are stored without their checks'))
