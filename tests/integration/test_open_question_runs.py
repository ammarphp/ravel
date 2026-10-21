"""Open-question fixture runs as research parents through ``research.loop`` on stub transports.

Four structure-preserving synthetic siblings (an extended-scalar constraint question, a tagger
method study at equal budget, an interference measurement and a supplied-ntuple search) each run
end to end once per module (``open_question_harness.build``). The tests read those runs:

1. the roles of every stage are dispatched by code, with no host improvisation;
2. the board register replays;
3. strict and raw scores are recorded, and the ABC probes score 0;
4. the P01-P03, P07-P09 and P16 checks pass on each run, and a planted fault fails each one.

Synthetic records only: no provider, model call, native run or physics inference.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import open_question_grader as grader
import open_question_harness as h
from ravel.validation import check_research_board, check_research_protocol
from ravel.workflow import research_board as rb

LOOP_PENDING = ('awaits the research-loop fix: the research.loop idea calls cannot yet carry the typed register '
                'declaration that idea_adopt requires (research_coordinator_decisions.REGISTER_FIELDS)')
# The roles research.loop itself serves through the host: declaration, assessment, the two idea
# streams and the decider. Every protocol-stage role is a stage-graph node, never a host choice.
LOOP_HOST_ROLES = {'designer', 'critic', 'verifier', 'proposer'}


@pytest.fixture(scope='module', params=h.QUESTIONS)
def run(request, tmp_path_factory):
    mp = pytest.MonkeyPatch()
    tmp = tmp_path_factory.mktemp('oq-' + request.param)
    for key, sub in (('RAVEL_STATE_DIR', 'state'), ('RAVEL_WORK_ROOT', 'work'),
                     ('RAVEL_ML_TEST_NAMESPACE', 'ledger')):
        mp.setenv(key, str(tmp / sub))
    base = (tmp / 'run').resolve()
    base.mkdir()
    try:
        built = h.build(base, request.param, mp)
        from ravel.workflow import machine_lease
        built.machine_dir = Path(machine_lease.machine_dir())  # the module's test lock domain
        if built.blocked:
            pytest.xfail(built.blocked)
        yield built
    finally:
        mp.undo()


@pytest.fixture(autouse=True)
def retained_run_custody(request, lock_domain_at):
    if 'run' in request.fixturenames:
        lock_domain_at(request.getfixturevalue('run').machine_dir)


def stage_pin(run, stage):
    return next(r['artifact'] for r in h.stage_records(run.root) if r['id'] == stage)


def check(module, name, value, run):
    return module.validate('check:' + name, value, base_dir=run.root)


# ---- 1. roles by code ------------------------------------------------------------------------------

def test_each_question_routes_to_a_research_parent_bound_to_the_default_protocol(run):
    assert run.contract['task_mode'] == run.q['expected_task_mode']
    status = h.protocol.methodology_status(run.root)
    assert [r['id'] for r in status['record']['stages']] == list(h.STAGES)
    assert status['record']['preregistration'] is not None


def test_every_stage_completes_with_exactly_its_protocol_roles(run):
    records = h.stage_records(run.root)
    assert [(r['id'], r['status']) for r in records] == [(s, 'done') for s in h.STAGES]
    delivered = {}
    for row in run.deliveries:
        delivered.setdefault(row['stage'], []).append(row['role'])
    for record in records:
        expected = h.stage_roles(record['id'])
        assert record['roles'] == expected
        # One round per stage: each declared role was delivered once, and no other role.
        assert sorted(delivered[record['id']]) == sorted(expected), record['id']
    # The host served only the loop's own model roles; no stage role was improvised by the host.
    assert {i['role'] for i in run.host.items} <= LOOP_HOST_ROLES
    assert not run.host.errors


def test_the_loop_dispatches_every_stage_turn_by_code(run):
    if run.engine != 'graph':
        pytest.xfail(LOOP_PENDING)
    assert run.outcome['kind'] == 'research_bounded_synthesis'
    assert run.outcome['phase'] == 'budget_exhausted'
    assert run.outcome['parent_task_accepted'] is False and run.outcome['delivery_receipt'] is None
    snapshot = h.orch.parity_snapshot(run.root)
    effects = snapshot['coordinator_effects']
    assert [e['action'] for e in effects] == ['protocol-stage'] * len(h.LOOP_TURNS)
    # The unobserved validate turn is refused by the selection boundary and observed, not aborted.
    refused = effects[-1]['actual_effect']
    assert refused['status'] == 'action_failed' and refused['observation_not_falsification'] is True
    assert 'confirm_read_before_selection' in json.dumps(refused['failure'])
    assert h.receipts(run.root, 'started') == h.receipts(run.root, 'ambiguous') == []
    nodes = {r['identity']['node'] for r in h.receipts(run.root) if 'node' in r['identity']}
    assert h.LOOP_NODES <= nodes
    graph_stages = {d['stage'] for d in run.deliveries if '/turns/' in d['graph']}
    assert graph_stages == set(h.LOOP_TURNS[:-1])


def test_a_question_cannot_pass_validate_on_unobserved_stub_artifacts(tmp_path, monkeypatch):
    """The negative control for the stage boundary: synthetic validate records are refused."""
    monkeypatch.setenv('RAVEL_WORK_ROOT', str(tmp_path / 'work'))
    base = (tmp_path / 'run').resolve()
    base.mkdir()
    with h.inert_decision_provider(), h.goal_bound_stage_specs():
        run = h.prepare(base, h.question('interference'))
        try:
            for stage in h.LOOP_TURNS[:-1]:
                h.run_stage(run, stage, base / 'stages' / stage)
        except ValueError as exc:
            if h.blocker(exc) is None:
                raise
            pytest.xfail(h.blocker(exc))
        with pytest.raises(ValueError, match='confirm_read_before_selection'):
            h.run_stage(run, 'validate', base / 'stages/validate')
    assert h.protocol.methodology_status(run.root)['next_stage'] == 'validate'


def test_acceptance_records_the_absent_protocol_producers_before_it_runs(run):
    pending = set(run.producer_refusal.replace('producer_pending:', '').replace(' ', '').split(';'))
    assert {'P04', 'P06', 'P17'} <= pending
    assert not {'P01', 'P02', 'P03', 'P07', 'P08', 'P09', 'P16'} & pending


# ---- 2. the board register replays -------------------------------------------------------------------

def test_the_board_register_replays_and_the_stub_season_is_unsealed(run):
    value = {'season_root': h.SEASON_ROOT}
    for name in check_research_board.CHECKS:
        assert check(check_research_board, name, value, run) == {'valid': True, 'errors': []}, name
    view = rb.season(run.season, rundir=run.root)
    assert rb.register_bytes(view) == rb.register_bytes(rb.season(run.season, rundir=run.root))
    reveal = json.loads((run.root / (h.SEASON_ROOT + '.reveal.json')).read_text())
    assert reveal['sealing']['status'] == 'unsealed' and 'independence' not in json.dumps(reveal)
    statements = {row['statement'] for row in view['snapshot']['hypotheses']}
    assert statements == set(run.q['hypotheses'].values())


def test_a_byte_changed_board_journal_does_not_replay(run):
    journal = sorted(p for p in Path(run.season).rglob('*') if p.is_file() and p.suffix in {'.json', '.jsonl'})[0]
    original = journal.read_bytes()
    try:
        journal.write_bytes(original.replace(b'"', b"'", 1) if b'"' in original else original + b' ')
        assert check(check_research_board, 'board_replay', {'season_root': h.SEASON_ROOT}, run)['valid'] is False
    finally:
        journal.write_bytes(original)
    assert check(check_research_board, 'board_replay', {'season_root': h.SEASON_ROOT}, run)['valid'] is True


# ---- 3. strict and raw scores; ABC probes ---------------------------------------------------------------

def scores(run, answers, *, pinned=None):
    pinned = pinned or json.loads(Path(run.grading['path']).read_text())['sha256']
    committed = h.committed(run.root)
    return {k: grader.score(a, run.q, pinned_sha256=pinned, committed=committed, root=run.root)
            for k, a in answers.items()}


def test_strict_and_raw_scores_are_recorded_and_abc_probes_score_zero(run):
    probes = grader.probes(run.q)
    # A copied reference placed inside the run with a well-formed pin: still not run evidence.
    from test_research_cycle import write as pin
    planted = pin(run.base / 'planted-reference.json', {'value': run.q['grading']['reference']['value']})
    probes['copied_reference_with_pin'] = {**probes['copied_reference'], 'quantity': {
        **probes['copied_reference']['quantity'],
        'evidence': {'path': planted['path'], 'sha256': planted['sha256'], 'pointer': '/value'}}}
    record = scores(run, {'run': h.run_answer(run), **probes})
    path = run.base / 'scores.json'
    path.write_text(json.dumps(record, sort_keys=True))
    assert json.loads(path.read_text()) == record
    assert (record['run']['strict'], record['run']['raw']) == (1.0, 1.0)
    for name in probes:
        assert record[name]['strict'] == 0.0 and record[name]['strict_reasons'], name
    assert record['empty']['raw'] == record['format_only']['raw'] == 0.0
    # Raw scoring credits a copied reference; the strict score does not.
    assert record['copied_reference']['raw'] == 1.0
    assert record['copied_reference_with_pin']['strict_reasons'] == ['evidence_not_committed_by_run']


def test_a_tolerance_changed_after_the_pin_scores_zero(run):
    widened = {**run.q, 'grading': {**run.q['grading'], 'tolerance': {'absolute': 1e6}}}
    pinned = json.loads(Path(run.grading['path']).read_text())['sha256']
    result = grader.score(h.run_answer(run), widened, pinned_sha256=pinned, committed=h.committed(run.root),
                          root=run.root)
    assert result['strict'] == 0.0 and 'grading_declaration_changed_after_pin' in result['strict_reasons']


def test_a_wrong_or_unbacked_answer_scores_zero_strictly(run):
    answer = h.run_answer(run)
    wrong = {**answer, 'verdict': next(v for v in run.q['grading']['verdicts'] if v != answer['verdict'])}
    moved = {**answer, 'quantity': {**answer['quantity'], 'value': answer['quantity']['value'] + 10}}
    record = scores(run, {'wrong': wrong, 'moved': moved})
    assert record['wrong']['strict'] == 0.0 and record['wrong']['raw'] == 0.5
    assert record['moved']['strict'] == 0.0
    assert 'reported_value_differs_from_evidence' in record['moved']['strict_reasons']


# ---- 4. protocol checks P01-P03, P07-P09, P16 ------------------------------------------------------------

def obligations(run):
    quantity = run.q['quantity']['id']
    plan = {'required_outputs': [{'id': quantity, 'format': 'json', 'pointer': h.ANSWER_POINTER},
                                 {'id': 'claims', 'format': 'json', 'pointer': '/claims/0/verdict'}]}
    return plan, {quantity: stage_pin(run, 'baseline'), 'claims': stage_pin(run, 'acceptance')}


def test_p03_obligations_are_covered_and_a_missing_output_fails(run):
    plan, outputs = obligations(run)
    value = {'plan': plan, 'claims': [], 'outputs': outputs}
    assert check(check_research_protocol, 'obligation_coverage', value, run)['valid'] is True
    missing = {**value, 'outputs': {k: v for k, v in outputs.items() if k != 'claims'}}
    assert check(check_research_protocol, 'obligation_coverage', missing, run)['valid'] is False


def allocation(run):
    from ravel.workflow import experiment_allocator as allocator
    _, state = h.cycle._load(run.root)
    register = h.cycle.replay_register(state['events'], base_dir=run.base)
    live = sorted(k for k, v in register.items() if v['status'] in {'active', 'survived_test', 'weakened'})
    assert len(live) >= 2
    case = {'schema_version': 1, 'scope': 'synthetic ' + run.q['id'], 'prediction_basis': 'supplied_unvalidated',
            'budget': 5, 'horizon': 1,
            'actions': [{'id': a, 'cost': 1, 'outcomes': ['yes', 'no'], 'nominal_change': 0} for a in ('a', 'b')],
            'hypotheses': [{'id': hid, 'predictions': {'a': 'yes', 'b': ('yes', 'no')[i % 2]},
                            'provenance': ['board season'], 'reopening_trigger': 'new declared inputs'}
                           for i, hid in enumerate(live)]}
    policy = {'validation_reservation': 2, 'confirmation_reservation': 2, 'reserve_budget': 1, 'coverage': {},
              'starvation_rounds': 2, 'rounds_since_exploration': 2}
    item = {'allocator_recommendation': allocator.recommend(case)['input_digest'],
            'allocation': allocator.allocate(case, policy)}
    return case, policy, item


def test_p07_the_queue_item_carries_the_allocator_recommendation(run):
    case, policy, item = allocation(run)
    value = {'case': case, 'policy': policy, 'work_item': item}
    assert check(check_research_protocol, 'allocation', value, run)['valid'] is True
    bare = {**value, 'work_item': {'allocation': item['allocation']}}
    assert check(check_research_protocol, 'allocation', bare, run)['valid'] is False


def test_p08_both_idea_streams_dispatched_with_operators(run):
    ideas = json.loads(Path(stage_pin(run, 'ideas')['path']).read_text())
    assert check(check_research_protocol, 'seed_to_test', ideas, run)['valid'] is True
    untagged = json.loads(json.dumps(ideas))
    del untagged['ideas'][0]['operator']
    assert check(check_research_protocol, 'seed_to_test', untagged, run)['valid'] is False


def test_p09_the_campaign_register_replays_with_typed_signatures(run):
    _, state = h.cycle._load(run.root)
    assert check(check_research_protocol, 'excluded_has_signature', {'events': state['events']}, run)['valid']
    planted = json.loads(json.dumps(state['events']))
    row = next(e for e in planted if e['kind'] == 'hypothesis' or 'hypotheses' in e)
    target = row['hypothesis'] if 'hypothesis' in row else row['hypotheses'][0]
    target['reopening_trigger'] = 'whenever it seems right'
    assert check(check_research_protocol, 'excluded_has_signature', {'events': planted}, run)['valid'] is False


def test_p16_confirmation_is_separated_from_selection(run, monkeypatch, lock_domain_at):
    # The confirmation read is spent in the run's own machine ledger domain (conftest gives each
    # test a fresh one).
    lock_domain_at(run.machine_dir)
    report = h.protocol._method_json(run.selection['report'], run.root)
    pins = [r['result'] for r in report['selected_result_on_confirm']]
    receipt = h.protocol._method_json(run.selection['receipt'], run.root)
    value = {'selection_receipt': receipt, 'confirmation_pins': pins}
    assert check(check_research_protocol, 'confirmation_separation', value, run) == {'valid': True, 'errors': []}
    reused = {**value, 'confirmation_pins': [receipt['trials'][0]['result']]}
    assert check(check_research_protocol, 'confirmation_separation', reused, run)['valid'] is False


# ---- figure inputs for the open-question figures -------------------------------------------------------------------------------

def test_figure_inputs_are_synthetic_and_agree_with_the_declared_answer():
    for name in h.QUESTIONS:
        q = h.question(name)
        assert q['synthetic'] is True and q['answer'] == q['grading']['reference']
        figure = q['figure_inputs']
        assert figure['kind'] in {'poi_contour', 'method_comparison', 'measurement_overlay', 'poi_scan'}
        if figure['kind'] == 'measurement_overlay':
            assert figure['value'] == q['answer']['value']
        if figure['kind'] == 'method_comparison':
            assert figure['values'][0] / figure['values'][1] == pytest.approx(q['answer']['value'])
