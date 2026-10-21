"""Reasoned machine assumptions: the authority rule, the controller's request and proposal checks, conditions.

An unanswered question with no plan-declared default gets a governed judgment proposal in autonomous mode when the
operator delegated machine assumptions (``--machine-checkins ...,assumption``); the authority takes it as the
question's default, with the machine label and the assumption named, only under that delegation and only once
nobody answered within the wait bound. A physics-critical ambiguity is never taken as fact: the result is labelled
conditional on it, on the receipt and on every affected deliverable. Machine assumptions and machine-taken defaults
make the K8 assumption audit apply.
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from test_p06_support import autonomous, frozen_store, new_store, operator_home, view  # noqa: F401
from ravel.controller import graph
from ravel.controller.authority import common, operator, request

BOUNDS = {'rung': 'smoke', 'stages': ['derive'], 'budget': {'wall_seconds': 60}}
OPTIONS = [{'id': 'hold', 'text': 'hold the branch', 'effect': False},
           {'id': 'proceed', 'text': 'take the first fictional reading', 'effect': True, 'bounds': deepcopy(BOUNDS)}]
DELEGATED = list(operator.DEFAULT_MACHINE_CHECKINS) + ['assumption']


def _subject(store, *, option='proceed', record='rec-1', conditional=False, question='7'):
    state = dict(view(store, 'escalation', question_sha256=question * 64), options=deepcopy(OPTIONS))
    from test_p06_support import retain_view
    retain_view(store, 'escalation', state)
    return {'view': state, 'conservative_default': option,
            'machine_assumption': {'record': record, 'option': option, 'conditional': conditional,
                                   'alternatives': 2}}


def test_the_operator_vocabulary_offers_assumptions_without_delegating_them_by_default(operator_home):
    assert 'assumption' in operator.MACHINE_CHECKINS
    assert 'assumption' not in operator.DEFAULT_MACHINE_CHECKINS
    assert 'assumption' not in operator.default_config()['machine_checkins']


def test_a_machine_assumption_is_taken_only_under_the_operator_delegation(operator_home, tmp_path):
    autonomous(wait_bound_seconds=0, machine_checkins=DELEGATED)
    store = frozen_store(tmp_path)
    record = request(store, 'escalation', _subject(store), BOUNDS)
    assert 'pending' not in record, record
    assert record['decision'] == 'default' and record['option'] == 'proceed'
    assert record['label'] == common.MACHINE and record['human_identity_authenticated'] is False
    assert record['evidence']['machine_assumption'] == {'record': 'rec-1', 'option': 'proceed',
                                                        'conditional': False, 'alternatives': 2}


def test_without_the_delegation_the_question_waits_for_a_human(operator_home, tmp_path):
    autonomous(wait_bound_seconds=0)  # the default check-ins: no machine assumptions
    store = frozen_store(tmp_path)
    held = request(store, 'escalation', _subject(store), BOUNDS)
    assert 'pending' in held and held['pending']['kind'] == 'escalation', held
    assert [r for r in store.scan('authority') if r['record']['kind'] == 'escalation'] == []


def test_interactive_mode_never_takes_a_machine_assumption(operator_home, tmp_path):
    operator.init(mode='physicist-in-the-loop', machine_checkins=DELEGATED, wait_bound_seconds=0)
    store = frozen_store(tmp_path)
    assert 'pending' in request(store, 'escalation', _subject(store), BOUNDS)


def test_an_option_outside_the_operator_bounds_is_never_assumed(operator_home, tmp_path):
    autonomous(wait_bound_seconds=0, machine_checkins=DELEGATED)
    store = frozen_store(tmp_path)
    wide = {**BOUNDS, 'budget': {'wall_seconds': 10 ** 9}}
    subject = _subject(store)
    subject['view']['options'][1]['bounds'] = deepcopy(wide)
    from test_p06_support import retain_view
    retain_view(store, 'escalation', subject['view'])
    assert 'pending' in request(store, 'escalation', subject, wide)


def test_a_machine_assumption_names_the_default_it_takes_and_only_a_question_carries_one(operator_home, tmp_path):
    autonomous(wait_bound_seconds=0, machine_checkins=DELEGATED)
    store = frozen_store(tmp_path)
    subject = _subject(store)
    subject['machine_assumption']['option'] = 'hold'
    with pytest.raises(ValueError, match='machine assumption'):
        request(store, 'escalation', subject, BOUNDS)
    subject = _subject(store, question='8')
    del subject['machine_assumption']['alternatives']
    with pytest.raises(ValueError, match='machine assumption'):
        request(store, 'escalation', subject, BOUNDS)
    plan_view = view(store, 'approve_plan')
    with pytest.raises(ValueError, match='only a question'):
        request(store, 'approve_plan', {'view': plan_view, 'machine_assumption': _subject(store)['machine_assumption']},
                BOUNDS)


def test_the_controller_computes_physics_criticality_that_a_worker_cannot_lower():
    plain = {'id': 'q', 'kind': 'ask', 'parameters': {}}
    assert graph.step_physics_critical(plain) is False
    assert graph.step_physics_critical({**plain, 'parameters': {'effects': ['physics_critical']}}) is True
    assert graph.step_physics_critical({**plain, 'consequence_class': 'R3'}) is True
    assert graph.step_physics_critical({**plain, 'parameters': {'judgment': {'declared_class': 'R3'}}}) is True


def _row():
    return {'status': 'pending', 'escalation': 'ask', 'attempt': 1, 'question': 'Which fictional reading?',
            'options': [{'id': 'reading-a', 'text': 'the first reading'}, {'id': 'reading-b', 'text': 'the second'}]}


def _block(**changes):
    block = {'question_step': 'q', 'chosen': 'reading-a', 'physics_critical': False, 'alternative_branch': None,
             'rationale': 'the run evidence names the first reading',
             'alternatives': [{'option': 'reading-a', 'evidence': ['inputs/reading.json names it'],
                               'reasons': 'the reading the request cites', 'rejection': None},
                              {'option': 'reading-b', 'evidence': ['no input supports it'],
                               'reasons': 'possible but unsupported', 'rejection': 'no evidence supports it'}]}
    block.update(changes)
    return block


def test_a_proposal_names_its_question_an_offered_choice_and_every_alternative_with_evidence():
    assert graph.assumption_errors(_block(), 'q', _row()) == []
    assert graph.assumption_errors(None, 'q', _row()) == ['the judgment step returned no assumption block']
    errors = ' '.join(graph.assumption_errors(_block(question_step='other', chosen='reading-z'), 'q', _row()))
    assert 'another question' in errors and 'not one of the question' in errors
    bad = _block()
    bad['alternatives'][1].update(evidence=[], rejection=None, reasons='')
    errors = ' '.join(graph.assumption_errors(bad, 'q', _row()))
    for text in ('cites no evidence', 'states no reasons', 'no rejection reason'):
        assert text in errors, text
    assert 'physics-critical' in ' '.join(graph.assumption_errors(_block(physics_critical='yes'), 'q', _row()))


class _Store:
    """A minimal store for the controller's own assumption readers."""

    def __init__(self):
        self.rows = []

    def append(self, kind, record):
        identifier = f'{kind}-{len(self.rows)}'
        self.rows.append({'kind': kind, 'id': identifier, 'record': deepcopy(record), 'time_ns': len(self.rows)})
        return identifier

    def scan(self, kind):
        return [deepcopy(r) for r in self.rows if r['kind'] == kind]


def test_assumption_requests_come_only_from_a_delegated_autonomous_run(monkeypatch):
    store = _Store()
    plan = {'steps': [{'id': 'q', 'kind': 'ask', 'parameters': {'effects': ['physics_critical']}}]}
    state = {'escalations': {'q': _row()}, 'steps': {}}
    monkeypatch.setattr(graph, '_recovery_inputs', lambda store: ([{'name': 'a.json'}], ['op']))
    for mode, expected in (({'mode': 'autonomous', 'machine_checkins': DELEGATED}, True),
                           ({'mode': 'autonomous', 'machine_checkins': list(operator.DEFAULT_MACHINE_CHECKINS)}, False),
                           ({'mode': 'physicist-in-the-loop', 'machine_checkins': DELEGATED}, False)):
        monkeypatch.setattr(graph, '_authority_mode', lambda store, mode=mode: mode)
        found = graph.assumption_requests(state, store, plan)
        assert bool(found) is expected, mode
    monkeypatch.setattr(graph, '_authority_mode', lambda store: {'mode': 'autonomous', 'machine_checkins': DELEGATED})
    [request_] = graph.assumption_requests(state, store, plan).values()
    assert request_['kind'] == 'assumption' and request_['request']['assumption']['physics_critical'] is True
    # A question with a plan default, one already proposed, or one already tried for its attempt gets none.
    assert graph.assumption_requests({'escalations': {'q': {**_row(), 'default': 'reading-a'}}}, store, plan) == {}
    assert graph.assumption_requests({'escalations': {'q': {**_row(), 'assumption': {'record': 'r'}}}}, store,
                                     plan) == {}
    store.append('assumption', {'phase': 'refused', 'step': 'q', 'attempt': 1})
    assert graph.assumption_requests(state, store, plan) == {}


def test_conditions_label_the_receipt_and_each_affected_deliverable():
    from importlib import import_module
    deliver = import_module("ravel.controller.sink.deliver")
    store = _Store()
    proposed = store.append('assumption', {'phase': 'proposed', 'step': 'q', 'option': 'reading-a', 'conditional': True,
                                           'assumptions': [{'statement': 'CONDITIONAL RESULT: MACHINE ASSUMPTION ...'}]})
    store.append('assumption', {'phase': 'alternative', 'step': 'q', 'record': proposed, 'alternative_option':
                                'reading-b', 'added_steps': ['alt'], 'assumptions': [{'statement': 'ALTERNATIVE'}]})
    store.append('assumption', {'phase': 'proposed', 'step': 'other', 'option': 'x', 'conditional': False,
                                'assumptions': [{'statement': 'MACHINE ASSUMPTION ...'}]})
    from importlib import import_module
    [condition] = import_module('ravel.controller.sink.deliver').conditions(store)
    assert condition['record'] == proposed and condition['alternative']['phase'] == 'alternative'

    class Findings:
        def __init__(self):
            self.labels = []

        def label(self, label, *, row=None, artifact=None, text=None):
            self.labels.append((label, artifact))
    plan = {'steps': [{'id': 'q'}, {'id': 'main', 'depends_on': ['q']}, {'id': 'alt', 'depends_on': ['q']},
                      {'id': 'free', 'depends_on': []}]}
    classification = {'declared': [{'artifact': 'main:outputs/r.json', 'step': 'main'},
                                   {'artifact': 'alt:outputs/r.json', 'step': 'alt'},
                                   {'artifact': 'free:outputs/r.json', 'step': 'free'}]}
    findings = Findings()
    deliver.condition_labels(store, plan, classification, findings)
    assert (deliver.CONDITIONAL, None) in findings.labels and (deliver.ALTERNATIVE, None) in findings.labels
    assert (deliver.CONDITIONAL, 'main:outputs/r.json') in findings.labels
    assert (deliver.ALTERNATIVE, 'alt:outputs/r.json') in findings.labels
    assert not [label for label in findings.labels if label[1] == 'free:outputs/r.json']


def test_machine_assumptions_make_the_assumption_audit_apply_without_claims():
    from ravel.workflow import spawn_rows
    plan = {'nodes': [], 'claims': []}
    rows = lambda points: [p['row'] for p in points]  # noqa: E731
    assert 'K8' not in rows(spawn_rows.derive({'agent_layer_epoch': 2, 'plan': plan}))
    assert 'K8' in rows(spawn_rows.derive({'agent_layer_epoch': 2, 'plan': plan, 'machine_assumptions': 1}))


FACT = {'id': 'collision-energy', 'type': 'parameter', 'value': 'inferred from the request context'}


def test_inferred_critical_facts_hold_a_plan_approval_without_the_delegation(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    held = request(store, 'ci1', {'view': view(store, 'approve_plan', plan_sha256='c' * 64),
                                  'inferred_critical_facts': [FACT]}, {'rung': 'smoke'})
    assert 'pending' in held and 'inferred critical facts' in held['pending']['reason']


def test_a_delegated_plan_approval_proceeds_conditional_on_inferred_critical_facts(operator_home, tmp_path):
    autonomous(machine_checkins=DELEGATED)
    store = frozen_store(tmp_path)
    record = request(store, 'ci1', {'view': view(store, 'approve_plan', plan_sha256='c' * 64),
                                    'inferred_critical_facts': [FACT]}, {'rung': 'smoke'})
    assert 'pending' not in record, record
    assert record['label'] == common.MACHINE and record['human_identity_authenticated'] is False
    assert record['evidence']['conditional_on'] == [FACT]  # named as the condition, never approved as fact


def _ci1_store(tmp_path, name, facts):
    """A controller RunStore whose CHECK-IN 1 the real authority service decided; returns it and the run state."""
    from ravel.controller.authority import freeze_mode
    from ravel.controller.store import RunStore
    store = RunStore.create(tmp_path / 'runs' / name, root=tmp_path / 'store')
    freeze_mode(store, {'prompt': 'Compute the fictional observable for the toy model.'})
    subject = {'view': view(store, 'approve_plan', plan_sha256='c' * 64)}
    if facts:
        subject['inferred_critical_facts'] = deepcopy(facts)
    record = request(store, 'ci1', subject, {'rung': 'smoke'})
    assert 'pending' not in record, record
    return store, {'authority': {'approve_plan': [record['id']]}}


def test_a_conditional_approval_is_recorded_once_and_conditions_every_deliverable(operator_home, tmp_path):
    from importlib import import_module
    deliver = import_module("ravel.controller.sink.deliver")
    autonomous(machine_checkins=DELEGATED)
    store, state = _ci1_store(tmp_path, 'conditional', [FACT])
    # The controller reads the approval through the authority service's own authenticated records view.
    first = graph.record_conditional_approval(state, store)
    assert first is not None and graph.record_conditional_approval(state, store) is None  # once per approval
    [row] = store.scan('assumption')
    assert row['id'] == first and row['record']['phase'] == 'conditional_approval'
    assert row['record']['record'] == state['authority']['approve_plan'][-1] and row['record']['facts'] == [FACT]
    assert row['record']['assumptions'][0]['statement'].startswith('CONDITIONAL RESULT')
    [condition] = deliver.conditions(store)
    assert condition['step'] is None and condition['record'] == first

    class Findings:
        def __init__(self):
            self.labels = []

        def label(self, label, *, row=None, artifact=None, text=None):
            self.labels.append((label, artifact))
    plan = {'steps': [{'id': 'a'}, {'id': 'b', 'depends_on': ['a']}]}
    classification = {'declared': [{'artifact': 'a:outputs/r.json', 'step': 'a'},
                                   {'artifact': 'b:outputs/r.json', 'step': 'b'}]}
    findings = Findings()
    deliver.condition_labels(store, plan, classification, findings)
    assert {(deliver.CONDITIONAL, 'a:outputs/r.json'), (deliver.CONDITIONAL, 'b:outputs/r.json'),
            (deliver.CONDITIONAL, None)} <= set(findings.labels)
    # An approval without inferred facts conditions nothing.
    plain, plain_state = _ci1_store(tmp_path, 'plain', [])
    assert graph.record_conditional_approval(plain_state, plain) is None
    assert plain.scan('assumption') == [] and deliver.conditions(plain) == []


def test_an_unreadable_approval_after_its_gate_holds_and_never_drops_its_conditions(operator_home, tmp_path):
    import json
    from ravel.controller.store import JOURNAL
    from ravel.workflow.graph_nodes import RecoveryHold
    autonomous(machine_checkins=DELEGATED)
    store, state = _ci1_store(tmp_path, 'unreadable', [FACT])
    journal = store.root / JOURNAL
    lines = journal.read_text(encoding='utf-8').splitlines()
    at = next(i for i, line in enumerate(lines) if json.loads(line)['kind'] == 'authority'
              and json.loads(line)['record'].get('kind') == 'approve_plan')
    edited = json.loads(lines[at])
    edited['record']['evidence']['conditional_on'] = []
    lines[at] = json.dumps(edited, sort_keys=True, separators=(',', ':'))
    journal.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    with pytest.raises(RecoveryHold) as held:
        graph.record_conditional_approval(state, store)
    assert held.value.reason == 'authority_refused'
