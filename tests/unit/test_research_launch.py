"""Research-protocol launch route: code-derived preregistration, resume migration and route applicability.

Synthetic run fixtures only; no physics, native or model process is started.
"""
import hashlib
import json
from pathlib import Path

import pytest
from ravel.workflow import research_evaluation

from ravel import cli
from ravel.workflow import (research_protocol as p, research_launch as launch, research_admission,
                            workflow_state, current_state)
from test_checkin2_gate import _write_inputs, CHECKIN1


def approve(rd, plan='smoke'):
    return workflow_state.main(['approve', '--rundir', str(rd), '--quote', 'Yes, run this exact plan.', '--plan', plan])


def approved(tmp_path, plan='smoke'):
    rd = tmp_path/'run'
    _write_inputs(rd, plan)
    assert approve(rd, plan) == 0
    return rd


def prereg(rd):
    return json.loads((rd/p.methodology_status(rd)['record']['preregistration']['path']).read_text())


# R1 -- CHECK-IN 1 approval produces the preregistration; launch keeps its gate.

def test_checkin1_approval_writes_code_derived_preregistration(tmp_path):
    rd = approved(tmp_path)
    value = prereg(rd)
    assert value['producer'] == launch.PRODUCER and value['authority'] == 'code_derived_from_approved_checkin1_plan'
    assert value['route'] == p.PLAIN_ROUTE and value['task_mode'] == 'reproduce'
    files = {row['path'] for row in value['plan_files']}
    assert {'inputs/task_contract.json', 'inputs/checkin1.json', 'inputs/cost_preflight.json'} <= files
    digest = hashlib.sha256((json.dumps(value['plan_files'], indent=2, sort_keys=True) + '\n').encode()).hexdigest()
    assert value['plan_digest'] == digest
    assert value['selection_policy']['kind'] == 'none'
    assert set(value['evaluator_pins']) | set(value['evaluator_not_applicable']) == {
        'limit_setter', 'likelihood_builder', 'cutflow_comparator'}
    for name, pin in value['evaluator_pins'].items():
        assert hashlib.sha256((rd/pin['path']).read_bytes()).hexdigest() == pin['sha256']
    assert workflow_state.verify_approval(str(rd), required_plan='smoke') == []


def test_cli_command_produces_the_same_record(tmp_path):
    rd = approved(tmp_path)
    before = p.methodology_status(rd)['record']['preregistration']
    assert cli.main(['research-preregister', '--rundir', str(rd)]) == 0
    assert p.methodology_status(rd)['record']['preregistration'] == before
    assert cli.main(['research-preregister', '--rundir', str(rd), '--check']) == 0


def test_cli_command_refuses_unapproved_plan(tmp_path):
    rd = tmp_path/'run'
    _write_inputs(rd, 'smoke')
    assert workflow_state.main(['init', '--rundir', str(rd)]) == 0
    assert cli.main(['research-preregister', '--rundir', str(rd)]) == 1
    assert p.methodology_status(rd)['record']['preregistration'] is None


def test_launch_gate_refuses_missing_preregistration(tmp_path):
    rd = approved(tmp_path)
    record = p.methodology_status(rd)['record']
    record.update(preregistration=None, evaluator_pins={})
    (rd/'research/protocol.json').write_text(json.dumps(record))
    errors = workflow_state.verify_approval(str(rd), required_plan='smoke')
    assert errors == ['prospective research preregistration and evaluator pins required']


def test_hand_written_preregistration_cannot_launch(tmp_path):
    """A model- or host-written record is refused even when it is well formed."""
    rd = approved(tmp_path)
    forged = {k: v for k, v in prereg(rd).items() if k != 'producer'}
    raw = json.dumps(forged).encode()
    (rd/'research/forged.json').write_bytes(raw)
    record = p.methodology_status(rd)['record']
    record['preregistration'] = {'path': 'research/forged.json', 'sha256': hashlib.sha256(raw).hexdigest()}
    (rd/'research/protocol.json').write_text(json.dumps(record))
    errors = workflow_state.verify_approval(str(rd), required_plan='smoke')
    assert errors and 'not produced from the approved plan' in errors[0]


def test_preregistration_must_match_current_derivation(tmp_path):
    rd = approved(tmp_path)
    value = prereg(rd)
    value['approximations'] = ['an assumption nobody approved']
    raw = json.dumps(value).encode()
    (rd/'research/edited.json').write_bytes(raw)
    record = p.methodology_status(rd)['record']
    record['preregistration'] = {'path': 'research/edited.json', 'sha256': hashlib.sha256(raw).hexdigest()}
    (rd/'research/protocol.json').write_text(json.dumps(record))
    errors = workflow_state.verify_approval(str(rd), required_plan='smoke')
    assert errors and 'approximations' in errors[0]


def test_reapproval_supersedes_with_record_until_a_stage_consumes_it(tmp_path):
    rd = approved(tmp_path)
    first = p.methodology_status(rd)['record']['preregistration']
    checkin = json.loads(json.dumps(CHECKIN1))
    checkin['sections']['iv'] = 'revised budget prose'
    (rd/'inputs/checkin1.json').write_text(json.dumps(checkin))
    assert approve(rd) == 0
    second = p.methodology_status(rd)['record']['preregistration']
    assert second != first and prereg(rd)['supersedes'] == first
    assert prereg(rd)['superseded_after_execution'] is False and (rd/first['path']).is_file()
    (rd/'execution_state.json').write_text('{}')
    checkin['sections']['iv'] = 'a revision after execution'
    (rd/'inputs/checkin1.json').write_text(json.dumps(checkin))
    assert approve(rd) == 0
    third = p.methodology_status(rd)['record']['preregistration']
    assert prereg(rd)['supersedes'] == second and prereg(rd)['superseded_after_execution'] is True
    record = p.methodology_status(rd)['record']
    next(r for r in record['stages'] if r['id'] == 'limitation_census')['status'] = 'done'
    status = {'record': record}
    assert launch._stage_consumed(status)
    (rd/'research/protocol.json').write_text(json.dumps(record))
    checkin['sections']['iv'] = 'a revision after a completed stage'
    (rd/'inputs/checkin1.json').write_text(json.dumps(checkin))
    with pytest.raises(ValueError):
        launch.produce(rd)
    assert json.loads((rd/'research/protocol.json').read_text())['preregistration'] == third


# R2 -- existing runs bind on resume with a recorded migration receipt.

def unbound_existing(tmp_path, *, past_checkin2):
    rd = tmp_path/'old-run'
    _write_inputs(rd, 'smoke')
    (rd/'inputs/checkin1_approval.json').write_text(json.dumps({'fixture': 'pre-protocol approval'}))
    # Lifecycle state written before the protocol existed: no binding at init.
    contract = json.loads((rd/'inputs/task_contract.json').read_text())
    workflow_state.write_state(str(rd), workflow_state.new_state(str(rd), contract, str(rd/'inputs/task_contract.json'), ''))
    if past_checkin2:
        (rd/'inputs/checkin2.json').write_text(json.dumps({'fixture': 'pre-protocol waypoint'}))
    return rd


@pytest.mark.parametrize('past_checkin2,label', [(True, 'pre_protocol_capped'), (False, 'none_before_checkin2')])
def test_status_write_binds_existing_run_with_receipt(tmp_path, past_checkin2, label):
    rd = unbound_existing(tmp_path, past_checkin2=past_checkin2)
    assert research_admission.admission(rd, 'delivery') == ['protocol_unbound']
    packet = current_state.write_packet(rd)
    assert packet['research_protocol_migration']['status'] == 'migrated'
    receipt = json.loads((rd/launch.MIGRATION).read_text())
    assert receipt['old_binding'] is None and receipt['new_binding']['regime'] == 'open_exploratory'
    assert receipt['applied_by'] == 'machine' and 'not a human' in receipt['authority']
    assert receipt['utc'] and receipt['epoch']['protocol_version']
    assert receipt['prior_results']['label'] == label
    assert p.methodology_status(rd)['prior_results'] == label
    assert 'research_protocol_migration' not in current_state.write_packet(rd)


def test_capped_results_cannot_be_relabelled(tmp_path):
    rd = unbound_existing(tmp_path, past_checkin2=True)
    current_state.write_packet(rd)
    receipt = json.loads((rd/launch.MIGRATION).read_text())
    receipt['prior_results']['label'] = 'protocol_bound_from_intake'
    (rd/launch.MIGRATION).write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match='changed'):
        p.methodology_status(rd)


def test_existing_run_never_binds_silently(tmp_path):
    rd = unbound_existing(tmp_path, past_checkin2=False)
    research_admission.admission(rd, 'approve_plan', bind=True)
    assert (rd/launch.MIGRATION).is_file()


def test_fresh_intake_binding_has_no_migration(tmp_path):
    rd = tmp_path/'run'
    _write_inputs(rd, 'smoke')
    assert workflow_state.main(['init', '--rundir', str(rd)]) == 0
    assert not (rd/launch.MIGRATION).exists()
    assert p.methodology_status(rd)['prior_results'] == 'protocol_bound_from_intake'


# R3 -- code-computed applicability per route; producers block only applicable protocols.

def test_plain_reproduction_applicability_table(tmp_path):
    rd = approved(tmp_path)
    table = p.route_applicability(rd)
    assert table['route'] == p.PLAIN_ROUTE
    inapplicable = {k for k, v in table['stages'].items() if not v['applicable']}
    assert inapplicable == {'ideas', 'screen', 'validate', 'critique_to_experiments'}
    assert all(table['stages'][k]['reason'] for k in inapplicable)
    for stage in ('limitation_census', 'baseline', 'acceptance', 'meta_review', 'integrity'):
        assert table['stages'][stage] == {'applicable': True, 'reason': None}
    assert table['protocols']['P16'] == {'applicable': False, 'reason': 'no selection: no confirmation separation'}
    assert table['protocols']['P10']['applicable'] and table['protocols']['P13']['applicable']
    rows = {r['id']: r for r in p.methodology_status(rd)['record']['stages']}
    assert rows['validate']['status'] == 'not_applicable' and rows['validate']['applicability'] == 'computed'
    assert rows['integrity']['status'] == 'pending' and rows['meta_review']['status'] == 'pending'


def test_declared_selection_makes_every_stage_applicable(tmp_path):
    rd = tmp_path/'run'
    _write_inputs(rd, 'smoke')
    contract = json.loads((rd/'inputs/task_contract.json').read_text())
    contract['selection'] = {'rule': 'declared'}
    (rd/'inputs/task_contract.json').write_text(json.dumps(contract))
    table = p.route_applicability(rd)
    assert table['route'] == p.SEARCH_ROUTE
    assert all(v['applicable'] for v in [*table['stages'].values(), *table['protocols'].values()])


def test_computed_not_applicable_is_rechecked(tmp_path):
    rd = approved(tmp_path)
    record = p.methodology_status(rd)['record']
    for row in record['stages']:
        if row['id'] == 'integrity':
            row.update(status='not_applicable', reason='claimed', applicability='computed')
    (rd/'research/protocol.json').write_text(json.dumps(record))
    with pytest.raises(ValueError, match='computed applicability'):
        p.methodology_status(rd)


def test_producer_pending_blocks_only_applicable_protocols(tmp_path, monkeypatch):
    rd = approved(tmp_path)
    missing = [{'id': 'P16', 'component': 'research evaluation / ML exposure', 'producers': ['x'], 'checks': []},
               {'id': 'P10', 'component': 'decision gate / request fidelity', 'producers': [], 'checks': ['check:y']}]
    monkeypatch.setattr(p, 'protocol_producers_present', lambda **k: {'missing': missing, 'contracts': []})
    # The ordinary producer for P10 is absent in this control, so P10 stays pending.
    monkeypatch.setitem(p.ORDINARY_PROTOCOL_PRODUCERS, 'P10', ('ravel.workflow.absent_decision_gate', None))
    assert p.producer_pending(rd) == ['producer_pending:P10']
    assert p.producer_pending() == ['producer_pending:P16', 'producer_pending:P10']
    errors = research_admission.admission(rd, 'delivery')
    assert 'producer_pending:P10' in errors and 'producer_pending:P16' not in errors
    assert not any(stage in e for e in errors for stage in ('validate', 'screen', 'ideas'))


def test_protocol_producers_check_names_missing_components():
    from ravel.validation import check_research_protocol as check
    report = check.validate('check:protocol_producers_present', None, base_dir='.')
    assert report['missing_components'] == sorted({row['component'] for row in report['missing']})
    for row in report['missing']:
        assert row['component'] == p.PRODUCER_OWNERS[row['id']] and (row['producers'] or row['checks'])


# R4 -- the ordinary reproduction through delivery, with no mocks, is in test_research_delivery.py.


def rebind_rdj(root, name, row):
    """Re-issue the synthetic RDJ receipt for an edited decision row (fixture authority only)."""
    from test_research_default_protocol import write as pin_write
    payload = {k: v for k, v in row.items() if k != 'rdj_receipt'}
    receipt = json.loads((root/('rdj/' + name + '.json')).read_text())
    receipt['action_digest'] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                                         ensure_ascii=False).encode()).hexdigest()
    row['rdj_receipt'] = pin_write(root, 'rdj/' + name + '.json', receipt)


def test_default_protocol_runs_every_stage_past_validate(tmp_path, monkeypatch):
    """Observed selection, dispatched confirmation and every later stage on a real campaign journal.

    The decision provider and role graphs are inert synthetic seams; no review is claimed.
    """
    from copy import deepcopy
    from ravel.workflow import research_cycle as c, agent_graph, role_registry
    from test_research_protocol_enforcement import observed
    from test_research_default_protocol import synthetic_artifacts, write as pin_write, STAGES
    from test_research_cycle import write
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path/'ledger'))
    monkeypatch.setenv('RAVEL_ML_TEST_NAMESPACE', str(tmp_path/'ledger'))
    monkeypatch.setattr(p, 'decision_errors', lambda *a, **k: [])
    # Two actual idea calls add 2*30 seconds and 2*2048 output tokens to
    # the original fixture allocation, before the campaign is created.
    root, state = observed(tmp_path, monkeypatch, measured=1, max_rounds=1,
                           budget={'wall_seconds': 660, 'output_tokens': 4096})
    # Commit selection on the observed trial, then dispatch and observe one confirmation.
    request = {'rule': {'direction': 'maximize', 'metric': 'response', 'k': 1, 'alpha': .05},
               'regime': 'closed_scored',
               'trials': [{'id': 'e0', 'candidate': 'c0', 'result': state['experiments'][0]['observation']['result']}]}
    receipt = p.commit_selection(root, write(root/'select.json', request))
    _, state = c._load(root)
    population = write(tmp_path/'hidden.json', {'ids': ['new-data']})
    e = deepcopy(state['experiments'][0]); e.update(id='confirm', observation=None)
    rd = tmp_path/'confirm-run'; e['rundir'] = str(rd); e['input_pins'] = [population]
    e['evaluation'].update(purpose='confirm', cells=['confirm'], seeds=[31], generation='g1', population_pins=[population])
    write(rd/'attempt.json', {'status': 'succeeded', 'wall_seconds': 1})
    write(rd/'outputs/attempt-1/result.json', {'metric': 1, 'p': .001, 'decision': 'better'})
    state['experiments'].append(e)
    state = c._commit(root, state, 'fixture_confirmation_prepared')
    research_evaluation.prepare_dispatch_action(root, 'confirm')
    p.record_confirmation_dispatch(root, state, 'confirm')
    c.observe(root, 'confirm')
    report = p.produce_selection_report(root)
    artifacts = synthetic_artifacts(root)
    selected = pin_write(root, 'committed-selection.json', receipt)
    validate = p.validation_trace(root)
    validate.update(withheld_cells=['confirm'], selection={**artifacts['validate']['selection'],
        'receipt': selected, 'confirmation_pins': [r['result'] for r in p._method_json(report, root)['selected_result_on_confirm']]})
    artifacts['validate'] = validate
    claim = artifacts['acceptance']['claims'][0]
    claim.update(N=receipt['N'], selection_receipt=selected, selection_report=report)
    for name, row in (('selection', validate['selection']), ('claim', claim)):
        rebind_rdj(root, name, row)
    actual_reservation = c.validate_graph_reservation
    actual_result = c._graph_result
    actual_receipt = agent_graph.role_receipt
    monkeypatch.setattr(c, 'validate_graph_reservation', lambda state, root, spec:
        actual_reservation(state, root, spec) if spec['graph_id'].startswith('actual-idea-stream-') else None)
    # Producers mocked present; acceptance otherwise refuses with producer_pending.
    present = p.protocol_producers_present()
    monkeypatch.setattr(p, 'protocol_producers_present', lambda **k: {**present, 'missing': [], 'valid': True})
    for stage in STAGES:
        if stage == 'ideas':
            from test_research_full_cycle_ideas import actual_ideas
            artifacts[stage] = actual_ideas(root, artifacts[stage], root/'actual-ideas')
        artifact = pin_write(root, stage + '.json', artifacts[stage])
        roles = next(row['roles'] for row in p.default_protocol()['stages'] if row['id'] == stage)
        def model(role):
            return 'gpt-5' if role_registry.load(role)['independence']['kind'] == 'producer' else 'claude-x'
        prepared = p.prepare_stage(root, stage, artifact, root/('review-' + stage), model='gpt-5',
            role_models={role: {'model': model(role)} for role in roles})
        def receipt_for(graph_root, node_id, **kwargs):
            if node_id == 'ideas':
                return actual_receipt(graph_root, node_id, **kwargs)
            stage = Path(graph_root).name[len('graph-'):]
            manifest = json.loads((root/('review-' + stage)/node_id/'packet/manifest.json').read_text())
            # Each synthetic seat is its own observed actor, session and packet.
            seat = 'synthetic-' + stage + '-' + node_id
            return {'context_transport_separated': True, 'execution_observation': 'host_attested_external',
                    'transport': {'observed_model': model(node_id), 'actor_id': seat, 'invocation_id': seat},
                    'context_manifest_sha256': manifest['sha256'],
                    'presented_subject_sha256s': [r['sha256'] for r in manifest['artifacts']], 'synthetic_stub': True}
        monkeypatch.setattr(agent_graph, 'role_receipt', receipt_for)
        def result(graph_root, node_id, stage=stage, prepared=prepared):
            if node_id == 'ideas':
                return actual_result(graph_root, node_id)
            return {'value': {'value': {'stage': stage, 'role_id': node_id, 'subject_sha256': prepared['subject']['sha256'],
                                        'verdict': 'accept', 'findings': [], 'attributed_claim_ids': ['K1']}}}
        monkeypatch.setattr(c, '_graph_result', result)
        status = p.complete_stage(root, prepared, root/('graph-' + stage))
        assert next(r for r in status['record']['stages'] if r['id'] == stage)['status'] == 'done'
    assert status['complete'] and not status['scientific_acceptance']
    assert [s for s in STAGES if STAGES.index(s) > STAGES.index('validate')] == [
        'critique_to_experiments', 'acceptance', 'meta_review', 'integrity']
