"""Lesson store, do-not-learn gate, promotion lifecycle, serving gate, exclusions and outcomes.

Synthetic tools, facts, tickets and numbers only; no native execution and no network.
"""
import copy
import json
from pathlib import Path

import pytest

from ravel.validation import check_knowledge as ck
from ravel.workflow import lesson_store as ls
from ravel.workflow import lesson_store_exclusions as lx
from ravel.workflow import lesson_store_outcomes as lo

ROOT = Path(__file__).resolve().parents[2]
CHECK = 'check:validation.validate_run_state'
SHA = 'a' * 64


def no_rule(text, known_ids=()):
    return []


def receipt(name='r1', kind='check_result'):
    return {'path': f'receipts/{name}.json', 'sha256': SHA, 'kind': kind}


def origin(run='run-1'):
    return {'request_digest': 'b' * 64, 'run_id': run}


def lesson(**changes):
    row = {
        'id': 'lesson:pin-the-lookup',
        'trigger': {'all': [{'fact': 'failure_class', 'equals': 'stale-lookup'},
                            {'fact': 'tool', 'equals': 'tool-a'}]},
        'body': 'Re-run the lookup for the pinned tool version; do not copy a value between versions.',
        'evidence': {'ticket': {'id': 'ticket-1', 'facts': {'failure_class': 'stale-lookup', 'tool': 'tool-a'}},
                     'receipts': [receipt()], 'origin': origin()},
        'confirming_check': CHECK,
        'scope': {'tool': 'tool-a', 'tool_version': '1.2', 'ravel_version': '0.1'},
        'status': 'candidate',
        'impact': None,
    }
    row.update(changes)
    return row


FIRING = {'failure_class': 'stale-lookup', 'tool': 'tool-a'}
OTHER = [{'failure_class': 'other', 'tool': 'tool-b'}] * 9


def impact(with_score=0.8, without_score=0.6, tasks=('held-1', 'held-2')):
    return {'arm_with': {'id': 'arm-w', 'snapshot_sha256': 'c' * 64, 'scores': {'pass_rate': with_score, 'cost': 10}},
            'arm_without': {'id': 'arm-o', 'snapshot_sha256': 'd' * 64, 'scores': {'pass_rate': without_score, 'cost': 10}},
            'tasks': list(tasks), 'metric': {'pass_rate': 'higher', 'cost': 'lower'},
            'held_out': True, 'paired': True, 'receipts': [receipt('ab')]}


def reproduction():
    return {'pre_fix': {'check': CHECK, 'status': 'fail', 'receipt': receipt('pre')},
            'post_fix': {'check': CHECK, 'status': 'pass', 'receipt': receipt('post')},
            'control': {'check': CHECK, 'status': 'pass', 'receipt': receipt('ctl')}}


def trial_lesson(**changes):
    row = lesson(**changes)
    return ls.to_trial(row, tickets=[{'id': 'ticket-2', 'facts': FIRING, 'origin': origin('run-2')}])


def promoted_lesson(name='lesson:pin-the-lookup'):
    row = trial_lesson(id=name)
    row['evidence']['reproduction'] = reproduction()
    return ls.promote(row, impact())


def card(role_id='analysis-author', family='production', kind='producer', forbidden=()):
    return {'id': role_id, 'family': family, 'independence': {'kind': kind},
            'knowledge': {'forbidden': list(forbidden), 'derive': [], 'must_read': []},
            'sees': {'forbidden_inputs': list(forbidden)}}


# --- acceptance 1: a candidate never reaches a producer bundle ---

def test_candidate_never_reaches_a_producer_bundle():
    from jsonschema import Draft202012Validator
    lessons = [lesson(id='lesson:candidate'), trial_lesson(id='lesson:trial'), promoted_lesson('lesson:promoted')]
    bundle = ls.bundle_items(lessons, card=card(), facts=FIRING)
    index = {'schema_version': 1, 'kind': 'knowledge-bundle', 'card_id': 'analysis-author', 'card_sha256': SHA,
             'node_id': 'node-1', 'items': bundle['items'], 'omitted': bundle['omitted'], 'budget_tokens': 4000,
             'used_tokens': sum(i['tokens'] for i in bundle['items']), 'source_restriction_sha256': SHA,
             'bundle_sha256': SHA}
    schema = json.loads((ROOT / 'src/ravel/data/knowledge/schema/bundle.json').read_text())
    assert not list(Draft202012Validator(schema).iter_errors(index))
    assert [i['id'] for i in bundle['items']] == ['lesson:promoted']
    assert {'id': 'lesson:candidate', 'reason': 'withheld'} in bundle['omitted']
    assert {'id': 'lesson:trial', 'reason': 'withheld'} in bundle['omitted']
    assert set(bundle['records']) == {i['path'] for i in bundle['items']}


def test_candidates_reach_only_investigators_and_the_tools_consult():
    rows = [lesson(id='lesson:candidate')]
    served = lambda c: [r['id'] for r in ls.served_lessons(rows, card=c, facts=FIRING)['served']]
    assert served(card('rca-investigator', 'investigation', 'investigation')) == ['lesson:candidate']
    assert served(card('consult-tool-a', 'consult', 'advisory')) == ['lesson:candidate']
    assert served(card('consult-tool-b', 'consult', 'advisory')) == []
    assert served(card()) == []


def test_trial_lessons_appear_only_in_the_with_side_of_a_paired_arm():
    rows = [trial_lesson(id='lesson:trial')]
    gate = lambda arm: [r['id'] for r in ls.served_lessons(rows, card=card(), facts=FIRING, arm=arm)['served']]
    assert gate(None) == []
    assert gate({'side': 'without', 'paired_with': 'arm-w'}) == []
    assert gate({'side': 'with'}) == []
    assert gate({'side': 'with', 'paired_with': 'arm-o'}) == ['lesson:trial']


def test_at_most_three_promoted_lessons_per_node():
    rows = [promoted_lesson(f'lesson:p{i}') for i in range(5)]
    gate = ls.served_lessons(rows, card=card(), facts=FIRING)
    assert [r['id'] for r in gate['served']] == ['lesson:p0', 'lesson:p1', 'lesson:p2']
    assert gate['omitted'] == [{'id': 'lesson:p3', 'reason': 'procedural_cap'}, {'id': 'lesson:p4', 'reason': 'procedural_cap'}]


def test_non_firing_invalid_revoked_and_out_of_scope_lessons_are_not_served():
    good = promoted_lesson('lesson:p')
    forged = dict(lesson(id='lesson:forged'), status='promoted', impact=impact())
    gate = ls.served_lessons([good, forged], card=card(), facts=FIRING)
    assert [r['id'] for r in gate['served']] == ['lesson:p']
    assert {'id': 'lesson:forged', 'reason': 'withheld'} in gate['omitted']
    assert ls.served_lessons([good], card=card(), facts={'failure_class': 'other', 'tool': 'tool-a'})['served'] == []
    drifted = {'tools': {'tool-a': '2.0'}}
    assert ls.served_lessons([good], card=card(), facts=FIRING, versions=drifted)['served'] == []
    assert ls.apply_versions(good, drifted)['status'] == 'dormant'
    assert ls.apply_versions(good, {'tools': {'tool-a': '1.2'}, 'ravel_version': '0.1'}) is good


# --- acceptance 2: a reviewer card that reads lessons is refused ---

def test_reviewer_card_that_reads_lessons_is_refused_by_the_card_check():
    from ravel.workflow import role_registry
    reviewer = role_registry.load('physics-critic')
    before = set(role_registry.validate_card(reviewer))
    reading = copy.deepcopy(reviewer)
    reading['knowledge']['forbidden'].remove('lessons')
    reading['sees']['forbidden_inputs'] = [i for i in reading['sees']['forbidden_inputs'] if i != 'lessons']
    reading['knowledge']['derive'].append('lessons_for_failure')
    added = set(role_registry.validate_card(reading)) - before
    assert {'reviewer must forbid lessons', 'reviewer cannot derive or read lessons'} <= added


def test_the_lesson_gate_serves_nothing_to_a_reviewer():
    rows = [lesson(id='lesson:candidate'), promoted_lesson('lesson:promoted')]
    for reviewer in (card('critic', 'governance', 'voting'), card('auditor', 'specialist-review', 'specialist'),
                     card('investigator', 'investigation', 'investigation', forbidden=['lessons'])):
        gate = ls.served_lessons(rows, card=reviewer, facts=FIRING)
        assert gate['reader'] == 'reviewer' and gate['served'] == []
        assert {o['reason'] for o in gate['omitted']} == {'forbidden'}


def test_an_unknown_or_missing_independence_kind_is_served_as_a_reviewer():
    rows = [lesson(id='lesson:candidate'), promoted_lesson('lesson:promoted')]
    unknown = card('blind-checker', 'production', 'blind-review')
    missing = card('unlabelled', 'production'); del missing['independence']
    for reader in (unknown, missing):
        gate = ls.served_lessons(rows, card=reader, facts=FIRING)
        assert gate['reader'] == 'reviewer' and gate['served'] == []


def test_a_producer_kind_card_never_receives_a_candidate_whatever_its_family():
    rows = [lesson(id='lesson:candidate')]
    for family in ('investigation', 'consult'):
        producer = card('consult-' + rows[0]['scope']['tool'], family, 'producer')
        gate = ls.served_lessons(rows, card=producer, facts=FIRING)
        assert gate['reader'] == 'producer' and gate['served'] == []


def test_lesson_distiller_card_passes_the_role_card_check():
    from ravel.workflow import role_registry
    distiller = json.loads((ROOT / 'src/ravel/data/lessons/lesson-distiller.card.json').read_text())
    assert role_registry.validate_card(distiller) == []
    assert ls.reader_class(distiller) == 'investigator'


# --- acceptance 3: promotion without trial and impact records fails ---

def test_promotion_without_trial_and_impact_records_fails(tmp_path):
    with pytest.raises(ValueError, match='only a trial lesson'):
        ls.promote(lesson(), impact())
    store = tmp_path / 'src/ravel/data/knowledge/lessons'
    store.mkdir(parents=True)
    no_trial = dict(lesson(id='lesson:no-trial'), status='promoted', impact=impact())
    no_trial['evidence']['reproduction'] = reproduction()
    no_impact = promoted_lesson('lesson:no-impact')
    no_impact['impact'] = {k: v for k, v in impact().items() if k not in ('held_out', 'paired')}
    good = promoted_lesson('lesson:good')
    for row in (no_trial, no_impact, good):
        (store / (row['id'].split(':')[1] + '.json')).write_text(json.dumps(row))
    errors = ck.lesson_store_errors(tmp_path, {CHECK})
    assert any('lesson:no-trial' in e and 'no trial record' in e for e in errors)
    assert any('lesson:no-impact' in e and 'held-out paired' in e for e in errors)
    assert not any('lesson:good' in e for e in errors)


def test_trial_needs_recurrence_or_a_reviewed_ticket():
    with pytest.raises(ValueError, match='recurrence'):
        ls.to_trial(lesson())
    with pytest.raises(ValueError, match='recurrence'):  # same run twice is not recurrence
        ls.to_trial(lesson(), tickets=[{'id': 'ticket-2', 'facts': FIRING, 'origin': origin('run-1')}])
    with pytest.raises(ValueError, match='recurrence'):  # a non-firing ticket does not count
        ls.to_trial(lesson(), tickets=[{'id': 't', 'facts': {'tool': 'tool-a'}, 'origin': origin('run-2')}])
    reviewed = ls.to_trial(lesson(), review={'ticket_id': 'ticket-1', 'reviewer': 'rca-review',
                                             'verdict': 'reviewed', 'receipt': receipt('review')})
    assert reviewed['status'] == 'trial' and reviewed['lifecycle'][0]['basis'] == 'reviewed_ticket'
    assert trial_lesson()['lifecycle'][0] == {'to': 'trial', 'basis': 'recurrence', 'runs': ['run-1', 'run-2']}


def test_promotion_needs_held_out_gain_no_harm_and_a_reproduction():
    row = trial_lesson()
    with pytest.raises(ValueError, match='reproduction'):
        ls.promote(row, impact())
    row['evidence']['reproduction'] = reproduction()
    with pytest.raises(ValueError, match='held out'):
        ls.promote(row, impact(tasks=('run-2',)))
    with pytest.raises(ValueError, match='stays in trial'):
        ls.promote(row, impact(with_score=0.6))
    revoked = ls.promote(row, impact(with_score=0.5))
    assert revoked['status'] == 'revoked' and revoked['lifecycle'][-1]['to'] == 'revoked'
    harm_elsewhere = impact(); harm_elsewhere['arm_with']['scores']['cost'] = 12
    assert ls.promote(row, harm_elsewhere)['status'] == 'revoked'
    promoted = ls.promote(row, impact())
    assert promoted['status'] == 'promoted' and ls.promotion_errors(promoted) == []
    assert ls.revoke(promoted, impact(with_score=0.4))['status'] == 'revoked'
    with pytest.raises(ValueError):
        ls.revoke(promoted, impact())


# --- acceptance 4: negative knowledge semantics ---

def signature(**changes):
    value = {'manipulation': 'raise the merging scale', 'held_inputs': ['model', 'detector'],
             'comparator': {'name': 'fixed-scale arm', 'receipt': receipt('cmp')},
             'sensitivity': {'power': 0.9, 'receipt': receipt('pow')}, 'statistic': 'yield ratio',
             'domain': {'mass': [100, 400]}, 'counterexample': {'receipt': receipt('cex')}}
    value.update(changes)
    return value


REOPEN = {'all': [{'fact': 'tool_version', 'in': ['2.0']}]}
MISMATCH = {'kind': 'scoped_prediction_mismatch', 'action_id': 'a1', 'predicted_outcome': 'up',
            'observed_outcome': 'down', 'evidence_digest': SHA}


def test_a_mismatch_without_comparator_and_sensitivity_cannot_become_an_exclusion():
    for sig in (None, signature(comparator=None), signature(sensitivity={'power': 0.9}),
                signature(counterexample={'note': 'no pin'})):
        record = lx.negative_record(hypothesis_id='h1', origin=origin(), reopening_trigger=REOPEN,
                                    mismatch=MISMATCH, signature=sig)
        assert record['kind'] == 'prediction_mismatch'
        with pytest.raises(ValueError, match='not a rejection'):
            lx.exclude(record)
    record = lx.negative_record(hypothesis_id='h1', origin=origin(), reopening_trigger=REOPEN,
                                mismatch=MISMATCH, signature=signature())
    assert record['kind'] == 'rejected_in_scope'
    assert lx.exclude(record)['status'] == 'excluded'
    forged = dict(record, signature=signature(comparator=None))
    with pytest.raises(ValueError, match='complete signature'):
        lx.exclude(forged)


def test_a_failed_execution_produces_no_exclusion():
    record = lx.negative_record(hypothesis_id='h1', origin=origin(), reopening_trigger=REOPEN, mismatch=MISMATCH,
                                signature=signature(), execution={'status': 'failed', 'receipt': receipt('log', 'stage_log')})
    assert record['kind'] == 'execution_failure'
    with pytest.raises(ValueError, match='failed execution'):
        lx.exclude(record)
    with pytest.raises(ValueError, match='failed execution'):
        lx.exclude(dict(record, kind='rejected_in_scope'))
    untested = lx.negative_record(hypothesis_id='h1', origin=origin(), reopening_trigger=REOPEN)
    assert untested['kind'] == 'untested'
    with pytest.raises(ValueError):
        lx.exclude(untested)


def test_a_free_string_reopening_trigger_is_refused():
    for trigger in ('when a newer tool version exists', {'all': []}, {'all': [{'fact': 'mood', 'equals': 'x'}]},
                    {'any': [{'fact': 'tool', 'equals': 'tool-a'}]}):
        with pytest.raises(ValueError, match='reopening'):
            lx.negative_record(hypothesis_id='h1', origin=origin(), reopening_trigger=trigger,
                               mismatch=MISMATCH, signature=signature())
    record = lx.exclude(lx.negative_record(hypothesis_id='h1', origin=origin(), reopening_trigger=REOPEN,
                                           mismatch=MISMATCH, signature=signature()))
    assert any('typed predicate' in e for e in lx.exclusion_errors(dict(record, reopening_trigger='later')))


def test_reproposal_and_reopening_are_receipt_bound():
    excluded = lx.exclude(lx.negative_record(hypothesis_id='h1', origin=origin(), reopening_trigger=REOPEN,
                                             mismatch=MISMATCH, signature=signature()))
    assert lx.reproposal_errors(excluded, {}) != []
    assert lx.reproposal_errors(excluded, {'what_is_new': {'statistic': 'yield ratio'}}) == [
        're-proposal repeats the excluded signature']
    assert lx.reproposal_errors(excluded, {'what_is_new': {'statistic': 'shape test'}}) == []
    with pytest.raises(ValueError, match='does not satisfy'):
        lx.reopen(excluded, facts={'tool_version': '1.2'}, receipt=receipt('new'))
    with pytest.raises(ValueError, match='receipt'):
        lx.reopen(excluded, facts={'tool_version': '2.0'}, receipt={'path': 'x'})
    request = lx.reopen(excluded, facts={'tool_version': '2.0'}, receipt=receipt('new'))
    assert request['kind'] == 'reopening-request' and request['support'] is None


def test_allocator_mismatches_are_recorded_as_mismatches_only():
    from ravel.workflow import experiment_allocator as ea
    case = {'schema_version': 1, 'scope': 'synthetic', 'prediction_basis': 'hypothetical', 'budget': 2, 'horizon': 1,
            'actions': [{'id': 'a1', 'cost': 1, 'outcomes': ['up', 'down'], 'nominal_change': 1.0}],
            'hypotheses': [{'id': 'h1', 'predictions': {'a1': 'up'}, 'provenance': ['p'], 'reopening_trigger': 'later'},
                           {'id': 'h2', 'predictions': {'a1': 'down'}, 'provenance': ['p'], 'reopening_trigger': 'later'}]}
    refutation = ea.update(case, [{'action_id': 'a1', 'outcome': 'down', 'evidence_digest': SHA}])['refutations'][0]
    with pytest.raises(ValueError, match='typed predicate'):
        lx.negative_record(hypothesis_id='h1', origin=origin(), reopening_trigger=refutation['reopening_trigger'],
                           mismatch=refutation)
    record = lx.negative_record(hypothesis_id='h1', origin=origin(), reopening_trigger=REOPEN, mismatch=refutation)
    assert record['kind'] == 'prediction_mismatch'


# --- acceptance 5: a planted suppression lesson is refused (do-not-learn rule) ---

def test_planted_skip_a_check_lesson_is_refused(tmp_path):
    planted = lesson(id='lesson:planted', body=f'Skip {CHECK} when the stale-lookup failure recurs; it is too strict.')
    errors = ls.gate_errors(planted, retained_facts=OTHER, check_ids={CHECK})
    assert any('do-not-learn' in e for e in errors)
    with pytest.raises(ValueError, match='do-not-learn'):
        ls.write_candidate(tmp_path, planted, retained_facts=OTHER, check_ids={CHECK})
    assert ls.gate_errors(lesson(), retained_facts=OTHER, check_ids={CHECK}) == []


def test_the_gate_fails_closed_without_the_do_not_learn_rule(monkeypatch):
    monkeypatch.setattr(ls, '_do_not_learn', lambda: None)
    assert any('do-not-learn rule unavailable' in e for e in ls.gate_errors(lesson(), retained_facts=OTHER))
    assert ls.gate_errors(lesson(), retained_facts=OTHER, do_not_learn=no_rule) == []
    hit = ls.gate_errors(lesson(), retained_facts=OTHER, do_not_learn=lambda t, known_ids=(): ['Skip it.'])
    assert any('do-not-learn' in e for e in hit)


# --- the rest of the do-not-learn gate ---

def test_gate_refuses_opinion_only_withheld_generic_and_unoriginated_lessons():
    gate = lambda row, **kw: ls.gate_errors(row, retained_facts=kw.pop('facts', OTHER), do_not_learn=no_rule, **kw)
    opinion = lesson(); opinion['evidence']['receipts'] = [receipt('v', 'reviewer_verdict'), receipt('p', 'model_prose')]
    assert any('reviewer verdict or model prose alone' in e for e in gate(opinion))
    untyped = lesson(); untyped['evidence']['receipts'] = [{'path': 'r', 'sha256': SHA}]
    assert any('needs a kind' in e for e in gate(untyped))
    numbered = lesson(body='Expect a ratio of 0.731 after the fix.')
    assert any('withheld source' in e for e in gate(numbered, withheld={'numbers': [0.731]}))
    assert gate(numbered, withheld={'numbers': [0.732]}) == []
    named = lesson(body='Seen first on synthetic-task-17.')
    assert any('withheld identifier' in e for e in gate(named, withheld={'ids': ['SYNTHETIC-TASK-17']}))
    assert any('limit 30%' in e for e in gate(lesson(), facts=[FIRING] * 4 + OTHER[:6]))
    assert gate(lesson(), facts=[FIRING] * 3 + OTHER[:7]) == []
    unoriginated = lesson(); del unoriginated['evidence']['origin']
    assert any('origin' in e for e in gate(unoriginated))
    assert any('retained run facts' in e for e in ls.gate_errors(lesson(), retained_facts=None, do_not_learn=no_rule))


def test_writer_records_candidates_only_and_keeps_ids_stable(tmp_path):
    path = ls.write_candidate(tmp_path, lesson(), retained_facts=OTHER, do_not_learn=no_rule)
    assert path == tmp_path / '.ravel/knowledge/lessons/lesson_pin-the-lookup.json'
    assert ls.write_candidate(tmp_path, lesson(), retained_facts=OTHER, do_not_learn=no_rule) == path
    with pytest.raises(ValueError, match='different lesson'):
        ls.write_candidate(tmp_path, lesson(body='Another body.'), retained_facts=OTHER, do_not_learn=no_rule)
    for row in (dict(lesson(), status='promoted', impact=impact()), trial_lesson()):
        with pytest.raises(ValueError, match='new candidates only'):
            ls.write_candidate(tmp_path, row, retained_facts=OTHER, do_not_learn=no_rule)
    ls.update_lesson(tmp_path, trial_lesson())
    with pytest.raises(ValueError, match='rewritten'):
        ls.update_lesson(tmp_path, lesson())
    fresh = tmp_path / 'fresh'
    ls.write_candidate(fresh, lesson(), retained_facts=OTHER, do_not_learn=no_rule)
    with pytest.raises(ValueError, match='no trial record'):
        ls.update_lesson(fresh, dict(lesson(), status='trial'))


def test_a_lifecycle_update_cannot_change_the_gated_lesson_content(tmp_path):
    ls.write_candidate(tmp_path, lesson(), retained_facts=OTHER, do_not_learn=no_rule)
    planted = trial_lesson()
    # Broadened after the write-time generality check: fires for every tool.
    planted['trigger'] = {'all': [{'fact': 'failure_class', 'equals': 'stale-lookup'}]}
    with pytest.raises(ValueError, match='lifecycle update changes'):
        ls.update_lesson(tmp_path, planted)
    assert ls.update_lesson(tmp_path, trial_lesson())


# --- Delta-Wa3: provenance, frozen or disabled stores, snapshot exclusion list ---

def outcome(run='run-1', key=SHA):
    pins = [{'path': 'results/limits.json', 'sha256': SHA}]
    return lo.outcome_row(run_id=run, request_digest='b' * 64, operation='op:synthetic-limit',
                          analysis='synthetic-analysis', implementation='impl-a', basis='simulated_acceptance',
                          certification_tier='unit_tested', structural_key=key, result_pins=pins,
                          discrepancies=[{'quantity': 'yield', 'ratio': 1.1, 'receipt': 'results/limits.json'}],
                          metrics={'mu95': {'value': 0.8, 'receipt': 'results/limits.json'}}, receipts=pins)


def test_store_modes_snapshot_exclusions_and_run_record(tmp_path):
    shipped = tmp_path / 'shipped'
    ls.write_candidate(tmp_path, lesson(), retained_facts=OTHER, do_not_learn=no_rule)
    second = lesson(id='lesson:second'); second['evidence']['origin'] = origin('run-9')
    ls.write_candidate(tmp_path, second, retained_facts=OTHER, do_not_learn=no_rule)
    lo.write_outcome(tmp_path, outcome('run-9'))
    live = ls.load_lessons(tmp_path, shipped=shipped)
    assert live['lesson_ids'] == ['lesson:pin-the-lookup', 'lesson:second']
    assert ls.load_lessons(tmp_path, mode='disabled', shipped=shipped)['lesson_ids'] == []
    snapshot = ls.export_snapshot(tmp_path, exclusions=['run-9'])
    assert snapshot['excluded'] == sorted(['lesson:second', outcome('run-9')['id']])
    assert [r['id'] for r in snapshot['lessons']] == ['lesson:pin-the-lookup'] and snapshot['outcomes'] == []
    frozen = ls.load_lessons(tmp_path, mode='frozen', snapshot=snapshot, shipped=shipped)
    assert frozen['lesson_ids'] == ['lesson:pin-the-lookup']
    assert frozen['snapshot_sha256'] == snapshot['snapshot_sha256']
    with pytest.raises(ValueError, match='valid store snapshot'):
        ls.load_lessons(tmp_path, mode='frozen', snapshot=dict(snapshot, lessons=[]), shipped=shipped)
    state = json.loads(ls.record_store_state(tmp_path / 'run', frozen).read_text())
    assert state['mode'] == 'frozen' and state['snapshot_sha256'] == snapshot['snapshot_sha256']
    with pytest.raises(ValueError):
        ls.load_lessons(tmp_path, mode='warm')


# --- outcome library ---

def test_outcome_rows_come_from_receipts_and_prior_outcomes_returns_them(tmp_path):
    row = outcome()
    assert lo.outcome_errors(row) == []
    lo.write_outcome(tmp_path, row)
    lo.write_outcome(tmp_path, outcome(key='e' * 64))
    assert lo.prior_outcomes(tmp_path, SHA) == [row]
    assert lo.prior_outcomes(tmp_path, SHA, exclusions=['run-1']) == []
    tampered = copy.deepcopy(row); tampered['metrics']['mu95']['receipt'] = 'elsewhere.json'
    assert any('id does not match' in e or 'row receipt' in e for e in lo.outcome_errors(tampered))
    unpinned = copy.deepcopy(row); unpinned['result']['pins'] = [{'path': 'other.json', 'sha256': SHA}]
    assert any('result pin' in e for e in lo.outcome_errors(unpinned))
    novel = copy.deepcopy(row); novel['result']['novelty'] = 'new model'
    assert any('novelty' in e for e in lo.outcome_errors(novel))
    with pytest.raises(ValueError, match='origin'):
        lo.write_outcome(tmp_path, lo.outcome_row(**{**_args(row), 'request_digest': 'short'}))


def _args(row):
    return {'run_id': row['run']['id'], 'request_digest': row['run']['request_digest'], 'operation': row['operation'],
            'analysis': row['result']['analysis'], 'implementation': row['result']['implementation'],
            'basis': row['result']['basis'], 'certification_tier': row['result']['certification_tier'],
            'structural_key': row['result']['structural_key'], 'result_pins': row['result']['pins'],
            'discrepancies': row['result']['discrepancies'], 'metrics': row['metrics'], 'receipts': row['receipts']}
