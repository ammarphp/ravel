"""ordinary delivery, preregistration timing, migration custody and campaign producers.

Synthetic run fixtures only. The execution attempt is a trivial Python command, as
in the physics review controls; no physics, native or model process is started.
"""
import hashlib
import json

import pytest

from ravel import cli
from ravel.workflow import (current_state, physics_review as review, research_admission, research_cycle as c,
                            research_launch as launch, research_protocol as p, science, state_io, workflow_state)
from test_checkin2_gate import CHECKIN1, _write_inputs
from test_research_launch import approve, approved, prereg

PROMPT = 'Reproduce the published 95% CLs exclusion limit of a synthetic search for a heavy scalar decaying to two jets.'
ORDINARY = ('limitation_census', 'baseline', 'acceptance', 'meta_review', 'integrity')


def _pin(name, raw):
    return {'locator': name, 'sha256': hashlib.sha256(raw).hexdigest()}


def initiated(tmp_path):
    """Real intake, then the CHECK-IN 1 records an ordinary reproduction approves."""
    import intake_sidecar_fixtures as fx
    from ravel.validation import validate_checkin as vc
    rd = tmp_path/'run'
    assert cli.main(['initiate', '--prompt', PROMPT, '--out', str(rd)]) == 0
    contract = json.loads((rd/'inputs/task_contract.json').read_text())
    reference, noise = b'{"synthetic": "published limit table"}\n', b'{"synthetic": "noise model"}\n'
    (rd/'inputs/reference_table.json').write_bytes(reference)
    (rd/'inputs/noise.json').write_bytes(noise)
    lattice = [[100.0], [200.0]]
    target = {'claim_id': 'C1', 'reference': {'kind': 'published_result', 'locator': 'synthetic published table',
                                              'pins': [_pin('inputs/reference_table.json', reference)],
                                              'recipe_pins': [], 'claim_id': None},
              'quantity': {'result': {'name': 'mu95', 'basis': 'signal_strength', 'unit': '1'},
                           'reference': {'name': 'mu95', 'basis': 'signal_strength', 'unit': '1'}},
              'conversion': None, 'family': {'reference': 'observed'},
              'nodes': {'coordinates': ['m'], 'reference_lattice': lattice, 'compared': lattice},
              'tolerance_rule': {'metric': 'relative difference', 'threshold': 0.2, 'aggregation': 'per_node',
                                 'definition': '|r - ref| / ref at every compared node'},
              'noise_model': {'definition': 'synthetic spread', 'pin': _pin('inputs/noise.json', noise)}}
    (rd/'inputs/agreement_targets.json').write_text(json.dumps(
        {'schema_version': 1, 'kind': 'agreement-targets', 'targets': [target]}))
    deck = fx.checkin1(json.loads((rd/'inputs/plan.json').read_text()), json.loads((rd/'inputs/reading.json').read_text()),
                       **{k: CHECKIN1['sections'][k] for k in ('i-b', 'ii', 'iii')})
    deck['variant'] = 'reproduction'
    (rd/'inputs/checkin1.json').write_bytes(vc.checkin_bytes(deck, str(rd)))
    from method_decision_fixture import admit_method
    admit_method(rd, 'parameter_scan' if contract['compute_plan'] == 'scan' else 'rough_estimate')
    budget = {'schema_version': 1, 'generated_by': 'cost_preflight.py', 'mode': contract['compute_plan'],
              'walltime_h': [0.5, 1], 'points': 1, 'events_per_point': 10000, 'backend': 'native'}
    (rd/'inputs/cost_preflight.json').write_text(json.dumps(budget))
    return rd, contract


def reviewed(tmp_path, *, reviewers=('physics_critic', 'skeptical_verifier', 'physics_decider')):
    """Intake, approval, admitted launch, one execution attempt, CHECK-IN 2 records and reviews."""
    from test_physics_review import make_attempt, check_packet
    rd, contract = initiated(tmp_path)
    assert workflow_state.verify_approval(str(rd), required_plan='smoke')
    assert cli.main(['approve', '--rundir', str(rd), '--quote', 'Yes, run this exact plan.',
                     '--plan', contract['compute_plan']]) == 0
    assert workflow_state.verify_approval(str(rd), required_plan='smoke') == []
    (rd/'inputs/settings.cfg').write_text('efficiency=0.8\n')
    (rd/'inputs/held-fixed.txt').write_text('fixed recipe\n')
    state_io.atomic_json(rd/'inputs/reference.json', {'reference': 1})
    record = make_attempt(rd)
    check_packet(rd, record)
    review.open_cycle(rd, effective_settings=['inputs/settings.cfg'], stage_receipts=[record['attempt_record']],
                      check_results='inputs/checks.json')
    actors = review._read(review._root(rd))[0]['policy']['actors']
    for role in reviewers:
        review.submit_review(rd, role=role, actor_id=actors[role], verdict='accept',
                             summary='Evidence supports the stated scope', claim_scope='reproduction')
    return rd


# D1 -- an ordinary reproduction that passes the ordinary gates is delivered.

def test_ordinary_reproduction_is_delivered_without_mocks(tmp_path):
    rd = reviewed(tmp_path)
    assert review.status(rd)['state'] == 'accepted'
    assert research_admission.admission(rd, 'delivery') == []
    assert review.gate_errors(rd, 'delivery') == []
    evidence = p.ordinary_stage_evidence(rd)
    assert {k for k, v in evidence.items() if v['status'] == 'satisfied'} == set(ORDINARY)
    for stage in ORDINARY:
        assert evidence[stage]['producer'] == p.ORDINARY_STAGE_PRODUCERS[stage] and evidence[stage]['evidence']
    for stage in ('ideas', 'screen', 'validate', 'critique_to_experiments'):
        assert evidence[stage]['status'] == 'stage_inapplicable' and evidence[stage]['reason']
    assert p.producer_pending(rd) == []
    assert {'cycle_id': review.status(rd)['cycle_id'], 'corrections_before_acceptance': 0} in evidence['baseline']['evidence']


def test_missing_review_record_blocks_delivery(tmp_path):
    rd = reviewed(tmp_path, reviewers=('physics_critic', 'skeptical_verifier'))
    errors = research_admission.admission(rd, 'delivery')
    assert any(e.startswith('required research stage incomplete: meta_review') for e in errors)
    assert any('acceptance' in e for e in errors) and review.gate_errors(rd, 'delivery')


def test_unreviewed_ordinary_run_names_its_missing_producers(tmp_path):
    rd = approved(tmp_path)
    errors = research_admission.admission(rd, 'delivery')
    assert errors == ['required research stage incomplete: ' + stage + ' (no CHECK-IN 2 physics review is registered)'
                      for stage in ORDINARY[1:]]


def test_ordinary_protocols_are_inapplicable_or_ordinary_produced(tmp_path):
    rd = approved(tmp_path)
    table = p.route_applicability(rd)['protocols']
    for pid in ('P06', 'P12', 'P15'):
        assert table[pid]['applicable'] is False and table[pid]['reason'].startswith('ordinary run')
    assert table['P11']['ordinary_producer'] == 'ravel.validation.normalization_ledger'
    assert table['P13']['ordinary_producer'] == 'ravel.validation.event_accounting'
    assert p.producer_pending(rd) == []


def test_event_protocols_do_not_apply_without_event_processing(tmp_path):
    rd = tmp_path/'run'
    _write_inputs(rd, 'smoke')
    contract = json.loads((rd/'inputs/task_contract.json').read_text())
    contract['compute_plan'] = 'none'
    (rd/'inputs/task_contract.json').write_text(json.dumps(contract))
    table = p.route_applicability(rd)['protocols']
    assert table['P11'] == {'applicable': False, 'reason': 'ordinary run: compute_plan=none processes no events'}
    assert table['P13']['applicable'] is False


def test_search_declared_only_in_the_request_plan_is_a_search_route(tmp_path):
    rd = tmp_path/'run'
    _write_inputs(rd, 'smoke')
    plan = {'claims': [{'id': 'C1', 'kind': 'method_performance'}]}
    (rd/'inputs/plan.json').write_text(json.dumps(plan))
    contract = json.loads((rd/'inputs/task_contract.json').read_text())
    contract['request_plan'] = {'path': 'inputs/plan.json',
                                'sha256': hashlib.sha256((rd/'inputs/plan.json').read_bytes()).hexdigest()}
    (rd/'inputs/task_contract.json').write_text(json.dumps(contract))
    assert p.route_applicability(rd)['route'] == p.SEARCH_ROUTE
    assert not p.stage_inapplicable('validate', rd)


# D2 -- a preregistration written after execution is post hoc.

def pre_protocol_approved(tmp_path):
    """An approved run whose research records predate the protocol, then executed."""
    import shutil
    rd = approved(tmp_path)
    shutil.rmtree(rd/'research')
    (rd/'execution_state.json').write_text('{}')
    return rd


def test_post_hoc_preregistration_is_labelled_and_never_prospective(tmp_path):
    rd = pre_protocol_approved(tmp_path)
    assert cli.main(['research-preregister', '--rundir', str(rd)]) == 0
    value = prereg(rd)
    assert value['post_hoc'] is True and {r['path'] for r in value['execution_pins']} >= {'execution_state.json'}
    status = p.methodology_status(rd)
    assert 'post_hoc_preregistration' in status['claim_cap'] and status['prospective'] is False


def test_post_hoc_preregistration_refuses_a_research_launch(tmp_path, monkeypatch):
    import shutil
    rd = tmp_path/'run'
    _write_inputs(rd, 'smoke')
    # The run declares a search from the start, so every read computes the search route.
    monkeypatch.setattr(p, '_search_declared', lambda contract, plan: True)
    assert approve(rd) == 0 and p.route_applicability(rd)['route'] == p.SEARCH_ROUTE
    shutil.rmtree(rd/'research')
    (rd/'execution_state.json').write_text('{}')
    assert cli.main(['research-preregister', '--rundir', str(rd)]) == 0
    assert prereg(rd)['post_hoc'] is True
    assert any('after execution' in e for e in launch.verify(rd))
    assert workflow_state.verify_approval(str(rd), required_plan='smoke')
    assert 'research claim capped: post_hoc_preregistration' in research_admission.admission(rd, 'delivery')


# D3/D4 -- migration custody, crash safety and execution-derived labels.

def unbound_existing(tmp_path, *, executed=False, past_checkin2=False):
    rd = tmp_path/'old-run'
    _write_inputs(rd, 'smoke')
    (rd/'inputs/checkin1_approval.json').write_text(json.dumps({'fixture': 'pre-protocol approval'}))
    contract = json.loads((rd/'inputs/task_contract.json').read_text())
    workflow_state.write_state(str(rd), workflow_state.new_state(str(rd), contract, str(rd/'inputs/task_contract.json'), ''))
    if executed:
        (rd/'execution_state.json').write_text('{"stages": {}}')
    if past_checkin2:
        (rd/'inputs/checkin2.json').write_text(json.dumps({'fixture': 'pre-protocol waypoint'}))
    return rd


def test_run_executed_before_checkin2_is_labelled_from_execution_records(tmp_path):
    rd = unbound_existing(tmp_path, executed=True)
    receipt = launch.migrate(rd)
    assert receipt['prior_results']['label'] == 'pre_protocol_executed'
    assert 'execution_state.json' in {r['path'] for r in receipt['prior_results']['pins']}
    status = p.methodology_status(rd)
    assert status['prior_results'] == 'pre_protocol_executed'
    assert 'prior_results:pre_protocol_executed' in status['claim_cap']


def test_deleting_the_migration_pin_cannot_uncap(tmp_path):
    rd = unbound_existing(tmp_path, past_checkin2=True)
    launch.migrate(rd)
    record = json.loads((rd/'research/protocol.json').read_text())
    del record['migration']
    (rd/'research/protocol.json').write_text(json.dumps(record))
    with pytest.raises(ValueError, match='migration receipt'):
        p.methodology_status(rd)
    binding = json.loads((rd/'research/binding.json').read_text())
    binding['origin'] = 'intake'
    (rd/'research/binding.json').write_text(json.dumps(binding))
    with pytest.raises(ValueError):
        p.methodology_status(rd)


@pytest.mark.parametrize('crash_at', ['protocol', 'custody', 'binding'])
def test_interrupted_migration_is_rolled_back_and_redone_with_its_receipt(tmp_path, monkeypatch, crash_at):
    rd = unbound_existing(tmp_path, past_checkin2=True)
    real_json, real_custody, real_replace = state_io.atomic_json, p.custody_append, __import__('os').replace

    def boom(*a, **k):
        raise OSError('simulated crash')
    if crash_at == 'protocol':
        monkeypatch.setattr(state_io, 'atomic_json', lambda path, *a, **k: boom() if str(path).endswith('protocol.json')
                            else real_json(path, *a, **k))
    elif crash_at == 'custody':
        monkeypatch.setattr(p, 'custody_append', boom)
    else:
        monkeypatch.setattr('os.replace', lambda src, dst: boom() if str(dst).endswith('binding.json') else real_replace(src, dst))
    with pytest.raises(OSError):
        launch.migrate(rd)
    monkeypatch.undo()
    assert not (rd/'research/binding.json').exists()
    assert research_admission.admission(rd, 'delivery') == ['protocol_unbound']
    assert research_admission.admission(rd, 'approve_plan', bind=True) == []
    assert p.methodology_status(rd)['prior_results'] == 'pre_protocol_capped'
    assert (rd/launch.MIGRATION).is_file()


def test_intake_bind_crash_leaves_no_lone_binding_and_recovers(tmp_path, monkeypatch):
    rd = tmp_path/'run'
    _write_inputs(rd, 'smoke')
    real_replace = __import__('os').replace
    monkeypatch.setattr('os.replace', lambda src, dst: (_ for _ in ()).throw(OSError('crash'))
                        if str(dst).endswith('binding.json') else real_replace(src, dst))
    with pytest.raises(OSError):
        p.bind_default(rd)
    monkeypatch.undo()
    assert (rd/'research/protocol.json').exists() and not (rd/'research/binding.json').exists()
    assert workflow_state.main(['init', '--rundir', str(rd)]) == 0
    assert p.methodology_status(rd)['prior_results'] == 'protocol_bound_from_intake'


def test_science_packet_reports_a_refused_migration(tmp_path, monkeypatch):
    rd = tmp_path/'run'
    rd.mkdir()
    monkeypatch.setattr(launch, 'migrate', lambda root: (_ for _ in ()).throw(ValueError('restore the binding')))
    result = science.packet(rd, write=True)
    assert result['lifecycle_verdict'] == 'FAIL' and 'restore the binding' in result['errors'][0]
    assert json.loads((rd/'current_state.json').read_text())['research_protocol_migration']['status'] == 'refused'


# D5 -- the supersession chain is verified and a revision after results is capped.

def revised_after_execution(tmp_path):
    rd = approved(tmp_path)
    checkin = json.loads(json.dumps(CHECKIN1))
    (rd/'execution_state.json').write_text('{}')
    checkin['sections']['iv'] = 'a revision after execution'
    (rd/'inputs/checkin1.json').write_text(json.dumps(checkin))
    assert approve(rd) == 0
    return rd


def test_plan_revised_after_results_is_capped(tmp_path):
    rd = revised_after_execution(tmp_path)
    assert prereg(rd)['superseded_after_execution'] is True
    assert 'plan_revised_after_execution' in p.methodology_status(rd)['claim_cap']
    assert launch.verify(rd) == []


def test_supersession_flags_cannot_be_rewritten(tmp_path):
    rd = revised_after_execution(tmp_path)
    value = prereg(rd)
    value['superseded_after_execution'] = False
    value.pop('supersedes')
    raw = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
    (rd/'research/forged.json').write_bytes(raw)
    record = json.loads((rd/'research/protocol.json').read_text())
    record['preregistration'] = {'path': 'research/forged.json', 'sha256': hashlib.sha256(raw).hexdigest()}
    record.pop('preregistration_history')
    (rd/'research/protocol.json').write_text(json.dumps(record))
    errors = launch.verify(rd)
    assert any('custody' in e for e in errors)
    assert 'plan_revised_after_execution' in p.methodology_status(rd)['claim_cap']


# D6/D7 -- campaigns: code-produced preregistration, no supplied CLI record, no omission bypass.

def test_campaign_created_without_protocol_fields_is_bound(tmp_path):
    from test_research_cycle import contract
    value = contract(tmp_path)
    assert 'research_protocol_required' not in value and 'goal_binding' not in value
    state = c.create(tmp_path/'cycle', value, base_dir=tmp_path)
    assert state['methodology'] is not None and state['contract']['research_protocol_required'] is True
    assert (tmp_path/'cycle/research/binding.json').is_file()


def design_record(tmp_path):
    from test_research_cycle import write
    return write(tmp_path/'design.json', {
        'selection_rule': {'direction': 'maximize', 'metric': 'response', 'k': 1, 'alpha': .05},
        'stop_rule': {'successes': 1, 'max_rounds': 2, 'budget': 3, 'coverage_floor': 1, 'families': ['f0']},
        'approximations': ['synthetic response surface']})


def test_campaign_preregistration_is_code_derived_and_reverified(tmp_path):
    from test_research_cycle import contract
    root = tmp_path/'cycle'
    c.create(root, contract(tmp_path), base_dir=tmp_path)
    status = launch.produce_campaign(root, design_record(tmp_path))
    value = p._method_json(status['record']['preregistration'], root)
    assert value['producer'] == launch.PRODUCER and value['authority'] == 'code_derived_from_campaign_contract_and_design'
    assert launch.verify(root) == []
    value['approximations'] = ['an approximation nobody designed']
    raw = json.dumps(value).encode()
    (root/'research/edited.json').write_bytes(raw)
    record = json.loads((root/'research/protocol.json').read_text())
    record['preregistration'] = {'path': 'research/edited.json', 'sha256': hashlib.sha256(raw).hexdigest()}
    (root/'research/protocol.json').write_text(json.dumps(record))
    # The journal pins the protocol record, so the edit is refused before re-derivation.
    assert launch.verify(root)
    assert research_admission.admission(root, 'launch')


def test_supplied_preregistration_is_refused_outside_the_evaluation_harness(tmp_path):
    from test_research_cycle import contract, write
    root = tmp_path/'cycle'
    c.create(root, contract(tmp_path), base_dir=tmp_path)
    supplied = write(tmp_path/'supplied.json', {'schema_version': 1, 'kind': 'research-preregistration',
        'approximations': [], 'expected_effect': {'statement': 'synthetic'},
        'selection_rule': {'direction': 'maximize', 'metric': 'response', 'k': 1, 'alpha': .05},
        'stop_rule': {'successes': 1, 'max_rounds': 2, 'budget': 3, 'coverage_floor': 1, 'families': ['f0']},
        'evaluator_not_applicable': {k: 'synthetic' for k in ('limit_setter', 'likelihood_builder', 'cutflow_comparator')}})
    with pytest.raises(ValueError, match='evaluation_harness set'):
        p.preregister(root, supplied, {})
    request = tmp_path/'request.json'
    request.write_text(json.dumps({'preregistration': supplied, 'evaluator_pins': {}}))
    with pytest.raises(ValueError):
        p.main(['preregister', '--cycle', str(root), '--request', str(request)])
    assert p.methodology_status(root)['record']['preregistration'] is None


# D21 -- a science approval receipt without plan digests approves nothing.

def test_science_preregistration_needs_approval_digests(tmp_path):
    rd = tmp_path/'run'
    (rd/'inputs').mkdir(parents=True)
    (rd/'inputs/science-plan.json').write_text('{}')
    (rd/'inputs/science-approval.json').write_text('{}')
    with pytest.raises(ValueError, match='plan digests'):
        launch.verify_approved(rd)


# D19 -- a deterministic confirmation criterion with k > 1 needs a declared exact measurement.

def test_deterministic_criterion_for_several_confirmations_needs_an_exact_measurement(tmp_path):
    from test_research_protocol_followup import selection
    request = selection(tmp_path)
    request['rule'].update(k=2, confirmation_criterion={'op': 'ge', 'value': 0.5})
    with pytest.raises(ValueError, match='Holm'):
        p.selection_receipt(request, base_dir=tmp_path)
    request['rule']['confirmation_criterion']['exact'] = True
    try:
        p.selection_receipt(request, base_dir=tmp_path)
    except ValueError as exc:
        assert 'Holm' not in str(exc)
