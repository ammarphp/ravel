"""Small route/consumer joins with literal oracles and inert, generic inputs.

These controls exercise admission and artifact consumption. Dispatch-boundary
packets and executed graph populations have separate controls in this package.
No provider, network, event generator or scientific native job is invoked.
"""
from copy import deepcopy
import json
import math
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ravel.controller import routes, schema_errors
from ravel.controller.routes import study
from ravel.controller.routes.analysis import evidence
from ravel.controller.routes.manuscript import note
from ravel.controller.step import spec
from ravel.controller.step.services import StepHold
from ravel.workflow import method_selection
from statistics_records import inert_uncertainty
from p09_support import Store, adopt, adopt_prepare, compile_plan, context, contract, outcome, reading

ROOT = Path(__file__).resolve().parents[3]


def test_intake_reinterpretation_to_plan_keeps_exact_preparation_roles():
    """Route spec analysis v1: the six preparation states precede execution."""
    from ravel.cli import _draft_route
    from ravel.validation import validate_task_contract
    prompt = ('Reinterpret the published exclusion of a fictional scalar using a supplied signal template '
              'and return a 95% CLs signal-strength upper limit.')
    con, source, _ = _draft_route(prompt, None, None)
    assert validate_task_contract.validate(con) == []
    assert con['prompt'] == prompt and con['task_mode'] == 'reinterpret'
    assert routes.select(con, source, [])['route'] == 'analysis'
    plan = compile_plan('analysis', source, con)
    assert schema_errors(plan, 'plan.v1') == []
    assert routes.plan_errors(plan) == []
    assert [(s['id'], s['role']) for s in plan['steps'] if s.get('parameters', {}).get('phase') == 'prepare'] == [
        ('env', 'coordinator'), ('inputs.census', 'coordinator'),
        ('inputs.route', 'coordinator'), ('inputs.traps', 'coordinator'),
        ('inputs.figures', 'coordinator'), ('inputs.cost', 'coordinator')]
    assert plan['checkins'][0]['seats'] == ['plan-critic']
    assert [s['id'] for s in plan['steps'] if s['kind'] == 'operate'] == [
        'recast.smoke', 'visualize.waypoint', 'run.full', 'visualize.final']
    candidate = deepcopy(plan['steps'][0])
    del candidate['outputs']
    downstream = []
    with pytest.raises(StepHold) as refused:
        spec.check(candidate)
        downstream.append('execution')
    assert refused.value.reason == 'step_spec_invalid'
    assert downstream == []


def test_method_choice_handoff_reaches_launch_gate_and_refuses_wrong_type(tmp_path):
    """The statistical choice uses the declared likelihood ladder, with no native work."""
    decision = json.loads((ROOT / 'tests/fixtures/method_decisions/rough_estimate.json').read_text())
    # The schema and ladder are separate declared sources, rather than a decision
    # produced by the method selector being used as its own expected answer.
    decision.update(family='fit_measurement', required_output='A qualified interval for a fictional count.')
    decision['selected'] = {'method': 'supplied_result', 'rung': 0, 'operation': None}
    decision['alternatives'] = []
    path = tmp_path / method_selection.DECISION_PATH
    path.parent.mkdir()
    schema = json.loads((ROOT / 'src/ravel/data/methods/method-decision.schema.json').read_text())
    assert list(Draft202012Validator(schema).iter_errors(decision)) == []
    assert method_selection.validate_method_decision(decision) == []
    path.write_text(json.dumps(decision))
    assert method_selection.launch_errors(tmp_path, 'full') == []
    decision['selected']['rung'] = '0'
    path.write_text(json.dumps(decision))
    errors = method_selection.launch_errors(tmp_path, 'full')
    assert errors and any('rung' in error for error in errors)


def test_statistics_plan_selects_available_tool_and_typed_operation_executor():
    from ravel.workflow import tool_selection
    # A fictional census exercises the declared preference rules. The operation
    # contract below separately tests the installed statistics executor binding.
    census = {'needs': {'numeric-method': {'summary': 'A bounded supplied interval.', 'methods': [{
        'id': 'bounded-method', 'available': 'always', 'preference': 2,
        'operations': ['bounded-method'], 'roles': []}]}}, 'tools': [{
        'id': 'fixture-solver', 'title': 'Fixture solver', 'serves': [{
            'need': 'numeric-method', 'preference': 1, 'operations': ['solve-interval'],
            'roles': [], 'implies': True}]}]}
    needs = tool_selection.registry(census)
    candidate = {'steps': [{'id': 'fit', 'kind': 'operate', 'operation': 'solve-interval',
                            'needs': ['numeric-method']}]}
    availability = lambda identity: {'available': True, 'reason': None}
    selected, errors = tool_selection.check(candidate, profile={}, needs=needs, status=availability)
    assert errors == []
    row, = selected['needs']
    assert row['need'] == 'numeric-method' and row['best'] == 'fixture-solver'
    assert row['status'] == 'served'
    weaker = deepcopy(candidate)
    weaker['steps'][0]['operation'] = 'bounded-method'
    refused, errors = tool_selection.check(weaker, profile={}, needs=needs, status=availability)
    assert errors and refused['needs'][0]['status'] == 'unserved'
    specification = {'schema_version': 1, 'mode': 'statistical-model', 'source': 'Supplied fictional counts.',
        'assumptions': ['Finite supplied counting control.'], 'max_seconds': 10, 'approval_mode': 'physicist',
        'task': {'input': 'inputs/counts.json', 'profile_points': [0., 1.],
                 'comparison_points': [{'mu': 0.}, {'mu': 1.}]}}
    admitted = study.mode_admission(specification)
    assert admitted['operation'] == 'statistical-model' and admitted['role'] == 'inference'
    specification['task']['profile_points'] = 'two points'
    downstream = []
    with pytest.raises(ValueError):
        study.mode_admission(specification)
        downstream.append('inference')
    assert downstream == []


def test_statistics_result_to_consumer_preserves_qualification_and_rejects_missing_record(tmp_path, monkeypatch):
    from ravel.physics.inference import situations
    from ravel.physics import pyhf_exclude
    from scipy.optimize import brentq
    from scipy.stats import norm
    counts = {'name': 'region', 'n': 2., 'b': 2., 'db': 0., 's': 2.}
    model, data = pyhf_exclude.model_from_counting(counts)
    backend, optimizer = pyhf_exclude.pyhf.get_backend()
    try:
        pyhf_exclude.pyhf.set_backend('numpy', pyhf_exclude.robust_optimizer())
        inferred = pyhf_exclude.compute(model, data, n_curve=3)
    finally:
        pyhf_exclude.pyhf.set_backend(backend, optimizer)
    assert inferred['limits']['observed']['status'] == 'resolved'
    assert [row['status'] for row in inferred['limits']['expected']] == ['resolved'] * 5
    # Independent fixed-background Asimov oracle: q_mu = 4(mu-log(1+mu));
    # CLs = 2*Phi(-sqrt(q_mu)) for n=b=2, s=2. The median and observed
    # roots therefore equal the solution at Phi^-1(.975)^2.
    expected = brentq(lambda mu: 4 * (mu - math.log1p(mu)) - norm.isf(.025) ** 2, 0., 10.)
    assert inferred['limits']['observed']['value'] == pytest.approx(expected, rel=2e-4)
    assert inferred['limits']['expected'][2]['value'] == pytest.approx(expected, rel=2e-4)
    facts = situations.make_facts(deliverables=['exclusion'], model_origin='counting', bins=[{
        'channel': 'region', 'bin': 0, 'observed': 2., 'background': 2., 'background_uncertainty': 0.}])
    availability = {
        'toy-cls': {'available': False, 'reason': 'budget: zero calibration operations'},
        'exact-count-calibration': {'available': False, 'reason': 'budget: zero calibration operations'}}
    record = situations.record(facts, {'limits': {'observed': 'resolved', 'median': 'resolved'},
        'budget_refusals': [{'method': method, 'status': 'not_run', 'reason': 'budget'}
                            for method in ('toy-cls', 'exact-count-calibration')]},
        availability=availability, decision=situations.decide(situations.assess(facts, availability=availability)))
    assert situations.audit(record) == []
    assert record['validity']['outcome'] == 'qualified'
    document = {**deepcopy(inferred), 'statistic': 'CLs', 'confidence_level': .95,
        'detector_mode': 'simpleanalysis-delphes-native', 'statistics': record,
        'uncertainty': inert_uncertainty(document=inferred), 'limitations': list(situations.labels(record))}
    store = Store()
    read, con = reading(), contract('reinterpret')
    plan = compile_plan('analysis', read, con)
    states = adopt_prepare(store, tmp_path, plan)
    ctx = context(store, tmp_path, plan, read, con, states)
    step = next(s for s in plan['steps'] if s['id'] == 'run.full')
    assert step['role'] == 'analysis-author' and step['operation'] == 'analysis-lifecycle'
    adopt(store, tmp_path, step['id'], 'outputs/limits.json', document)
    assert evidence.check(step, outcome(step), ctx) == []
    accepted_document = deepcopy(document)
    del document['statistics']
    adopt(store, tmp_path, step['id'], 'outputs/limits.json', document)
    errors = evidence.check(step, outcome(step), ctx)
    assert 'statistics_record_missing' in {e['code'] for e in errors}
    assert all(e['row'] == 'STEP-07-exclude' for e in errors)
    # Carry the admitted bytes through the actual qualified sink. The trusted
    # compiler/custody seam is the existing non-compliance harness; its ending
    # retains the fixture's uncertainty and original open obligations.
    monkeypatch.syspath_prepend(str(ROOT / 'tests/unit/enforcement'))
    from nc_env import Env
    from nc_controller import controller_run
    from nc_route_entry import Entry
    from ravel.controller import ledger, sink
    env = Env(tmp_path / 'delivery-control', monkeypatch)
    try:
        env.enter_domain()
        delivery_store, root = controller_run(env, 'qualified-limit')
        entry = Entry(env, delivery_store, root, {})
        entry.plan['steps'][0]['outputs'] = [{'path': 'outputs/limits.json', 'kind': 'inference', 'required': True}]
        entry.plan['deliverables'][0]['output'] = 'outputs/limits.json'
        entry.adopt('effect:outputs/limits.json', accepted_document)
        entry.pin()
        delivery_store.append('step-outcome', {'step_id': 'effect', 'attempt': 1, 'status': 'completed',
                                              'observation_scope': 'qualified fixture result'})
        ledger.materialise(delivery_store, 'intake', {'run_id': delivery_store.run_id, 'task_mode': 'calculation',
            'route': 'judgment', 'deliverables': ['result']})
        ledger.materialise(delivery_store, 'plan', {'plan': entry.plan, 'route': 'judgment', 'task_mode': 'calculation'})
        receipt = sink.bounded_end(delivery_store, 'Supplied interval retained with its statistical qualification.')
        assert receipt['qualified'] is True and receipt['accepted'] is False
        delivered = root / 'delivery/artifacts/effect/outputs/limits.json'
        assert json.loads(delivered.read_text()) == accepted_document
        assert json.loads(delivered.read_text())['limitations'] == list(situations.labels(record))
        assert sink.receipt(delivery_store)['verification']['delivery_intact'] is True
    finally:
        env.close()


def test_model_to_generation_admission_requires_original_card_bytes(tmp_path):
    from test_model_events import config, texts
    from ravel.physics import model_events
    value = config(tmp_path / 'model')
    assert model_events.validate_config(value) is value
    assert int(model_events.check_cards(value, texts(value))['run']['iseed']) == 19
    # The generation admission consumes a pinned configuration, and validates
    # its cards before any upstream process can execute.
    config_path = tmp_path / 'configuration.json'
    config_path.write_text(json.dumps(value))
    task = {'config': str(config_path)}
    assert model_events.inputs(task, tmp_path)
    run_card = Path(value['cards']['run']['path'])
    run_card.write_text(run_card.read_text().replace('19 = iseed', '20 = iseed'))
    downstream = []
    with pytest.raises(ValueError):
        model_events.inputs(task, tmp_path)
        downstream.append('generator')
    assert downstream == []


def test_analysis_to_cutflow_consumer_refuses_missing_measurement(tmp_path, monkeypatch):
    from test_cutflow_input_formats import measured_cutflow, run_json
    good = tmp_path / 'good'
    good.mkdir()
    status, report, _, _ = run_json(good, monkeypatch, measured_cutflow())
    assert status in (0, None)
    assert report['verdict'] == 'PASS'
    assert report['comparison_counts'] == {'requested': 1, 'evaluated': 1, 'missing': 0}
    assert [(r['mine'], r['pub'], r['ratio']) for r in report['rows']] == [(.5, .5, 1.)]
    bad = measured_cutflow()
    del bad['regions'][0]['cuts'][-1]['sumw2']
    rejected = tmp_path / 'bad'
    rejected.mkdir()
    status, report, _, _ = run_json(rejected, monkeypatch, bad)
    assert status == 2 and report['reason'] == 'cutflow_input_invalid'
    assert report['status'] == 'refused' and report['verdict'] == 'FAIL'
    assert not report.get('rows')


@pytest.mark.parametrize('damage', ['missing-field', 'wrong-type', 'foreign-provenance'])
def test_delivered_result_to_manuscript_sources_refuses_at_the_claim_handoff(tmp_path, monkeypatch, damage):
    from test_p17_note import fixture
    inputs, result, claim_path = fixture(tmp_path / 'good')
    claim_map = json.loads(claim_path.read_text())
    assert note.validate_claim_map(claim_map) == claim_map
    good = note.run_stage('sources', inputs, {}, tmp_path / 'source-output')
    assert good['status'] == 'completed'
    bundle = json.loads((tmp_path / 'source-output/outputs/bundle.json').read_text())
    assert bundle
    inputs, result, claim_path = fixture(tmp_path / 'bad')
    document = json.loads(claim_path.read_text())
    if damage == 'missing-field':
        del document['claims'][0]['result']
    elif damage == 'wrong-type':
        document['claims'] = {}
    else:
        document['results']['measurement']['sha256'] = '0' * 64
    claim_path.write_text(json.dumps(document))
    output = tmp_path / 'refused-output'
    refused = note.run_stage('sources', inputs, {}, output)
    assert refused['status'] == 'refused'
    assert refused['codes'] == [('manuscript_integrity_failed' if damage == 'foreign-provenance'
                                 else 'manuscript_claim_map_invalid')]
    # The declared outputs retain explicit refusal placeholders/diagnostics.
    # The actual next consumer must refuse them before selecting any TeX engine.
    monkeypatch.setattr(note, '_tex_engine', lambda *args: pytest.fail('refused sources reached rendering'))
    rendered = note.run_stage('pdf', {'sources': output / 'outputs/sources.tar',
        'bundle': output / 'outputs/bundle.json'}, {}, tmp_path / 'refused-rendering')
    assert rendered['status'] == 'refused' and rendered['codes'] == ['manuscript_sources_refused']
    assert not (tmp_path / 'refused-rendering/outputs/manuscript.pdf').exists()
