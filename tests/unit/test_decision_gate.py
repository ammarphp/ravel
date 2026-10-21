"""Pure provider and evidence refusal contracts, using inert synthetic runs."""
import importlib
from pathlib import Path
import pytest
from inert_dispatch import inert_dispatch  # noqa: F401
from test_review_points import run, write, receipt


def gate(): return importlib.import_module('ravel.workflow.decision_gate')



def test_missing_receipts_list_minimal_ids_without_writing(tmp_path):
    dg = gate()
    run(tmp_path, nodes=[{'id': 'N1', 'operation': 'literal-calculation'}])
    before = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    errors = dg.check(tmp_path, 'approve_plan', {'digest': 'a'*64})
    assert errors and all(e.pins for e in errors)
    assert any('plan-critic' in pin for e in errors for pin in e.pins)
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    with pytest.raises(ValueError): dg.check(tmp_path, 'invented_gate', {})


def test_required_absent_provider_refuses(tmp_path, monkeypatch):
    dg = gate()
    run(tmp_path)
    action = {'digest': 'a'*64, 'node_id': 'N1'}
    assert dg.check(tmp_path, 'unblind', action)
    real = dg.util.find_spec
    monkeypatch.setattr(dg.util, 'find_spec', lambda name, *a: None if name == 'ravel.workflow.rdj_loop' else real(name, *a))
    errors = dg.check(tmp_path, 'unblind', action)
    assert any(e.code == 'provider_inactive' and 'provider:rdj' in e.pins for e in errors)


def _with_provider(dg, monkeypatch, row, required=()):
    registry = dg._registry()
    registry['providers'].append(row)
    for gate_name in required:
        registry['required_providers'].setdefault(gate_name, []).append(row['id'])
    monkeypatch.setattr(dg, '_registry', lambda: registry)


@pytest.mark.parametrize('required', [True, False])
def test_installed_module_without_its_function_is_inactive_and_refuses(tmp_path, monkeypatch, required):
    dg = gate()
    run(tmp_path)
    row = {'id': 'synthetic', 'module': 'ravel.workflow.decision_gate', 'function': 'absent_gate_errors',
           'gates': ['unblind'], 'owner': 'synthetic', 'active': True}
    _with_provider(dg, monkeypatch, row, required=('unblind',) if required else ())
    listed = next(p for p in dg.providers('unblind') if p['id'] == 'synthetic')
    assert listed['active'] is False and 'function' in listed['reason']
    errors = [e for e in dg.check(tmp_path, 'unblind', {'digest': 'a'*64, 'node_id': 'N1'}) if e.provider == 'synthetic']
    assert errors and all(e.code == 'provider_inactive' for e in errors)


def test_unmapped_requirement_refused(tmp_path):
    dg = gate()
    run(tmp_path, claims=[])
    write(tmp_path/'inputs/task_contract.json', {'agent_layer_epoch': 2, 'request_plan': __import__('json').loads((tmp_path/'inputs/task_contract.json').read_text())['request_plan'], 'prompt': 'First. Second.',
          'task_requirements': {'obligations': [{'id': 'R1', 'evidence': [{'start': 0, 'end': 6, 'text': 'First.'}]},
                                             {'id': 'R2', 'evidence': [{'start': 7, 'end': 14, 'text': 'Second.'}]}]}})
    artifact = write(tmp_path/'outputs/first.json', {'value': 1})
    errors = dg.check(tmp_path, 'delivery', {'digest': 'a'*64, 'outputs': [{'id': 'O1', 'artifact': artifact, 'requirement_ids': ['R1']}]})
    missing = [e for e in errors if e.code == 'request_fidelity']
    assert len(missing) == 1 and missing[0].pins == ('requirement:R2',)


def test_calibration_missing_nonoverlap_and_receipt(tmp_path):
    dg = gate()
    run(tmp_path, nodes=[{'id': 'N1', 'tuning_to_observed': True}])
    errors = dg.check(tmp_path, 'checkin2_accept', {'digest': 'a'*64})
    assert any(e.code == 'calibration_separation_missing' for e in errors)
    assert any(e.code == 'rdj_receipt_missing' and e.provider == 'review_points' for e in errors)
    assert any('calibration' in pin for e in errors for pin in e.pins)


def test_raw_generation_output_needs_bound_launch(tmp_path):
    dg = gate()
    run(tmp_path)
    output = tmp_path/'stages/one/events.lhe.gz'; output.parent.mkdir(parents=True); output.write_bytes(b'fixture')
    errors = dg.check(tmp_path, 'delivery', {})
    assert any(e.code == 'raw_launch' and 'stages/one/events.lhe.gz' in e.pins for e in errors)


def test_legacy_contract_unchanged(tmp_path):
    dg = gate()
    write(tmp_path/'inputs/task_contract.json', {'schema_version': 1})
    assert dg.check(tmp_path, 'approve_plan', {}) == []


@pytest.mark.parametrize('name', ['unblind', 'spend_above_ceiling'])
def test_legacy_contract_cannot_pass_gates_without_legacy_decision(tmp_path, name):
    dg = gate()
    write(tmp_path/'inputs/task_contract.json', {'schema_version': 1})
    errors = dg.check(tmp_path, name, {'digest': 'a'*64})
    assert [e.code for e in errors] == ['epoch_gate_unsupported'] and errors[0].pins
    assert dg.check(tmp_path/'absent', name, {'digest': 'a'*64})


def test_cli_observation_set_excludes_relay():
    from ravel.workflow.scientific_judgment import OBSERVATIONS
    assert 'transport_attested_cli' in OBSERVATIONS
    assert 'host_attested_external' not in OBSERVATIONS



def test_review_pending_cli_dispatches_to_owned_module(tmp_path, capsys):
    from ravel import cli
    run(tmp_path, claims=[{'id': 'C1', 'kind': 'prediction'}])
    assert cli.main(['review', 'pending', '--rundir', str(tmp_path), '--json']) == 0
    assert 'parallel_group' in capsys.readouterr().out


def test_output_name_without_artifact_cannot_cover_requirement(tmp_path):
    rp = importlib.import_module('ravel.workflow.review_points')
    data = {'contract': {'prompt': 'Result', 'task_requirements': {'obligations': [
        {'id': 'R1', 'evidence': [{'start': 0, 'end': 6, 'text': 'Result'}]}]}}}
    errors = rp._fidelity(data, {'outputs': [{'id': 'imagined', 'requirement_ids': ['R1']}]}, 'delivery')
    assert errors and errors[0].pins == ('requirement:R1',)


def test_final_worker_record_self_declared_findings_are_advisory(tmp_path):
    rp = importlib.import_module('ravel.workflow.review_points')
    run(tmp_path, claims=[{'id': 'C1', 'kind': 'prediction'}])
    point = next(p for p in rp.pending(tmp_path) if p['row'] == 4)
    role = point['roles'][0]['role']
    artifact = write(tmp_path/'agent-work'/f'{role}1'/'1/final.json', {
        'findings': [{'severity': 'A', 'code_check': {'id': 'check:closure', 'status': 'failed'}}]})
    receipt(tmp_path, point['id'], role, final_record={'path': 'final.json', 'sha256': artifact['sha256'], 'valid': True})
    errors = rp.gate_errors(tmp_path, 'checkin2_accept', {})
    assert not any(e.code == 'blocking_finding' for e in errors)



def test_unblind_requires_human_r3_even_without_declared_observed_node(tmp_path, monkeypatch):
    rp = importlib.import_module('ravel.workflow.review_points')
    run(tmp_path, nodes=[{'id': 'N1', 'operation': 'literal-calculation'}])
    errors = rp.gate_errors(tmp_path, 'unblind', {'digest': 'a'*64, 'node_id': 'N1'})
    assert any(e.code == 'rdj_receipt_missing' for e in errors)


@pytest.mark.parametrize('name', ['launch', 'export', 'delivery', 'checkin2_accept'])
def test_check_refuses_absent_contract(tmp_path, name):
    assert [e.code for e in gate().check(tmp_path, name, {})] == ['gate_inputs_invalid']


@pytest.mark.parametrize('epoch', ['2', 3, None, True])
def test_check_refuses_unknown_epoch(tmp_path, epoch):
    write(tmp_path/'inputs/task_contract.json', {'agent_layer_epoch': epoch})
    assert [e.code for e in gate().check(tmp_path, 'delivery', {})] == ['gate_inputs_invalid']


def test_failing_diagnostics_never_replace_primary_refusal(tmp_path, monkeypatch):
    rp = importlib.import_module('ravel.workflow.review_points')
    def boom(*args): raise RuntimeError('diagnostic defect')
    monkeypatch.setattr(rp, 'invalid_input_diagnostics', boom)
    write(tmp_path/'inputs/task_contract.json', {'agent_layer_epoch': '2'})
    assert [e.code for e in gate().check(tmp_path, 'delivery', {})] == ['gate_inputs_invalid']


def test_epoch_downgrade_against_run_init_snapshot_refused(tmp_path):
    from ravel.workflow import rdj_custody
    run(tmp_path)
    rdj_custody.record_input_snapshot(tmp_path, 'run_init')
    write(tmp_path/'inputs/task_contract.json', {})
    assert [e.code for e in gate().check(tmp_path, 'delivery', {})] == ['gate_inputs_invalid']


def test_legacy_contract_without_snapshot_keeps_legacy_decision(tmp_path):
    write(tmp_path/'inputs/task_contract.json', {})
    assert gate().check(tmp_path, 'delivery', {}) == []


def test_epoch_two_without_request_plan_pin_refused(tmp_path):
    run(tmp_path)
    write(tmp_path/'inputs/task_contract.json', {'agent_layer_epoch': 2})
    assert [e.code for e in gate().check(tmp_path, 'delivery', {})] == ['gate_inputs_invalid']


def test_node_id_cannot_exclude_row16_at_checkin2(tmp_path):
    run(tmp_path, nodes=[{'id': 'N1', 'tuning_to_observed': True}, {'id': 'N2'}])
    errors = gate().check(tmp_path, 'checkin2_accept', {'node_id': 'N2'})
    assert any(e.code == 'rdj_receipt_missing' and e.provider == 'review_points' for e in errors)


def test_node_id_naming_no_plan_node_refused_at_claim_gate(tmp_path):
    run(tmp_path)
    assert 'action_scope_invalid' in [e.code for e in gate().check(tmp_path, 'checkin2_accept', {'node_id': 'N9'})]


def test_delivery_rechecks_calibration_row16(tmp_path):
    run(tmp_path, nodes=[{'id': 'N1', 'tuning_to_observed': True}])
    errors = gate().check(tmp_path, 'delivery', {})
    assert any(e.code == 'calibration_separation_missing' for e in errors)
    assert any(e.code == 'rdj_receipt_missing' and e.provider == 'review_points' for e in errors)


def test_comparison_required_point_pending_without_comparison_record(tmp_path):
    run(tmp_path, claims=[{'id': 'C1', 'basis_declared': ['authored_code']}])
    errors = gate().check(tmp_path, 'checkin2_accept', {'kind': 'tuning_change', 'floor': 'R2'})
    assert any(e.code == 'comparison_missing' and e.provider == 'comparison' for e in errors)


def test_executor_provider_code(tmp_path):
    run(tmp_path)
    assert [e.code for e in gate().check(tmp_path, 'launch', {}) if e.provider == 'executor'] == []
    full = {'digest': 'a'*64, 'rung': 'full', 'node_id': None}
    assert [e.code for e in gate().check(tmp_path, 'launch', full) if e.provider == 'executor'] == ['executor_node_missing']


@pytest.mark.parametrize('mutation', ['add_calibration', 'remove_calibration', 'strip_non_overlap'])
def test_plan_edit_after_approve_changes_derived_digest_refused(tmp_path, mutation):
    from ravel.workflow import review_points as rp
    nodes = [{'id': 'N1', 'tuning_to_observed': True, 'calibration': {'non_overlap': {'regions': ['a', 'b']}}}]
    run(tmp_path, nodes=nodes)
    rp.approve(tmp_path)
    if mutation == 'add_calibration': nodes.append({'id': 'N2', 'tuning_to_observed': True})
    elif mutation == 'remove_calibration': nodes[0].pop('tuning_to_observed')
    else: nodes[0]['calibration'].clear()
    run(tmp_path, nodes=nodes)
    assert 'obligations_changed' in [e.code for e in rp.gate_errors(tmp_path, 'delivery', {})]


def test_checkin2_accept_scoped_to_named_claim(tmp_path, inert_dispatch):
    from ravel.workflow import review_points as rp
    run(tmp_path, claims=[{'id': 'C1'}, {'id': 'C2'}])
    for p in rp.derive(rp._facts(tmp_path)):
        if p.get('claim_id') == 'C1': receipt(tmp_path, p['id'], p['roles'][0]['role'])
    assert rp.gate_errors(tmp_path, 'checkin2_accept', {'claim_id': 'C1'}) == []
    assert any(e.code == 'review_point_pending' for e in rp.gate_errors(tmp_path, 'checkin2_accept', {}))
    assert any('C2' in pin for e in rp.gate_errors(tmp_path, 'delivery', {'claim_id': 'C1'}) for pin in e.pins)


def test_intake_stamps_epoch_two(tmp_path):
    from ravel import cli
    import json
    root = tmp_path/'intake'
    assert cli.main(['initiate', '--prompt', 'Summarize published ATLAS limits.', '--out', str(root)]) == 0
    assert json.loads((root/'inputs/task_contract.json').read_text())['agent_layer_epoch'] == 2


def test_floor_raises_rdj_class_at_research_choice(tmp_path):
    from rdj_fixtures import Run, Roles, PROPOSER, add, node
    from ravel.workflow import rdj_loop, review_points as rp, rdj_custody
    r = Run(tmp_path/'run', snapshot=False, cost={'mode': 'smoke', 'points': 1, 'walltime_h': [0.1, 0.2]})
    pin = r.put('inputs/plan.json', {'nodes': [], 'claims': [], 'edges': [],
                                  'decisions': [{'id': 'D1', 'gate': 'research_choice', 'risk_class': 'R2'}]})
    contract = __import__('json').loads((r.root/'inputs/task_contract.json').read_text())
    r.put('inputs/task_contract.json', {**contract, 'request_plan': pin})
    rdj_custody.record_input_snapshot(r.root, 'run_init')
    a = r.action('analysis_choice')
    cid = rdj_loop.open_case(r.root, 'research_choice', a, PROPOSER)
    add(r, cid, 'action', node('A', 'The request preserves binning', anchors=[r.prompt_span('keep the approved binning')]))
    rdj_loop.run_roles(r.root, cid, Roles())
    value = rdj_loop.authorize(r.root, cid)
    assert value['class'] == 'R1'
    assert any(e.code == 'rdj_receipt_missing' for e in rp.gate_errors(r.root, 'research_choice', a))


def test_registered_stage_receipt_finding_blocks(tmp_path):
    from rdj_fixtures import Run
    from ravel.workflow import review_points as rp
    r = Run(tmp_path/'run')
    anchor = r.stage('stage', 'outputs/value.json', {'x': 1})
    assert rp.blocking_finding(r.root, {'materiality': 'A', 'evidence_class': 'new_receipt',
                                      'evidence_locators': [anchor['binding']['receipt_id']]})


def test_role_cards_use_m12_registry_api(tmp_path, monkeypatch):
    from ravel.workflow import review_points as rp, role_registry, transport_registry
    names = ['spec-author', 'card-author', 'model-author', 'statistical-model-author', 'refutation-verifier']
    resolved = role_registry.resolve_names(names)
    assert set(resolved) == set(names)
    seen = []
    real_load = role_registry.load
    def load(name, **kwargs):
        seen.append(name)
        return real_load(name, **kwargs)
    monkeypatch.setattr(role_registry, 'load', load)
    monkeypatch.setattr(transport_registry, 'select', lambda card, *a, **kw: {'role': card['id']})
    points = [{'blocking': True, 'attestation_min': 'transport', 'roles': [{'role': name}]} for name in names]
    assert rp.dispatchability(tmp_path, points) == []
    assert seen == names
    assert all(real_load(name)['id'] == resolved[name] for name in names)


@pytest.mark.parametrize('allow_control', [False, True])
def test_host_attested_external_never_admitted_by_control_switch(tmp_path, monkeypatch, allow_control):
    from test_scientific_judgment import prepare, FakeHost
    from test_physics_review import opened
    from ravel.workflow import scientific_judgment as j, agent_graph
    # Use the real review/Graph records; vary only the observed transport label.
    from test_physics_review import run as run_fixture
    fixture = run_fixture.__wrapped__(tmp_path, monkeypatch)
    opened(fixture)
    binding = prepare(fixture[0], tmp_path/'roles', 'critic')
    j.execute_role(binding, FakeHost())
    actual = agent_graph.role_receipt
    def relay(*args, **kwargs):
        return {**actual(*args, **kwargs), 'execution_observation': 'host_attested_external', 'attestation': 'self_attested'}
    monkeypatch.setattr(agent_graph, 'role_receipt', relay)
    with pytest.raises(ValueError, match='self-attested|fresh observed'):
        j.verify_binding(binding, allow_control=allow_control)


def test_approval_writer_records_and_fingerprints_derived_points(tmp_path, monkeypatch):
    from argparse import Namespace
    from ravel.workflow import workflow_state as ws, review_points as rp
    run(tmp_path, claims=[{'id': 'C1'}])
    # The ordinary CHECK-IN validator has separate unit coverage. Observe the
    # writer's fingerprint inputs at that boundary, without substituting RDJ.
    seen = []
    monkeypatch.setattr(ws, 'verify_approval', lambda root, record: seen.append(ws.approval_input_paths(root)) or [])
    from method_decision_fixture import admit_method
    admit_method(tmp_path)
    assert ws.cmd_approve(Namespace(rundir=str(tmp_path), plan='full', quote='approve', scripted=True)) == 0
    path = tmp_path/'inputs/review_points_approval.json'
    assert path.is_file()
    assert str(path) in seen[0]
    assert __import__('json').loads(path.read_text())['derived_points_sha256'] == rp.jdigest(rp.derive(rp._facts(tmp_path)))


def test_older_calibration_receipt_does_not_satisfy_current_action(tmp_path, inert_dispatch):
    from rdj_fixtures import Run, authorize_tuning_case
    from ravel.workflow import rdj_loop as rdj, review_points as rp
    r = Run(tmp_path/'run')
    older = authorize_tuning_case(r, gate='checkin2_accept')
    newer = authorize_tuning_case(r, gate='checkin2_accept', tuning='implementation_correction')
    case = __import__('json').loads((r.root/older['case']['path']).read_text())
    support = next(a['binding']['output_path'] for a in case['anchors'] if a['kind'] == 'tool_output')
    r.put(support, {'changed': True})  # Keep the old case pin intact; invalidate its support.
    a = r.action('tuning_change')
    assert rdj.authorizing_receipt(r.root, 'checkin2_accept', a)['receipt']['receipt_id'] == newer['receipt_id']
    point = {'id': 'RP16:N1', 'node_id': 'N1', 'rdj_class': 'R2', 'gate': 'checkin2_accept',
             'receipt_gate': 'checkin2_accept', 'decision_class': 'calibration'}
    assert [e.code for e in rp._rdj_errors(r.root, point, 'checkin2_accept', a)] == ['rdj_receipt_missing']


def test_run_init_snapshot_without_contract_does_not_vouch_later_contract(tmp_path):
    from ravel.workflow import rdj_custody
    rdj_custody.record_input_snapshot(tmp_path, 'run_init')
    write(tmp_path/'inputs/task_contract.json', {})
    assert [e.code for e in gate().check(tmp_path, 'delivery', {})] == ['gate_inputs_invalid']


def test_invalid_comparison_action_refuses_without_raising(tmp_path):
    run(tmp_path, claims=[{'id': 'C1', 'basis_declared': ['authored_code']}])
    errors = gate().check(tmp_path, 'checkin2_accept', {'floor': 'not-a-class'})
    assert errors and all(e.pins for e in errors)


def test_comparison_not_required_on_r0_r1_wiring(tmp_path):
    run(tmp_path, claims=[{'id': 'C1', 'basis_declared': ['authored_code']}])
    from ravel.workflow import rdj_loop
    a = {'kind': 'dry_run', 'rung': 'dry'}
    assert rdj_loop.compute_class(tmp_path, 'launch', a)[0] == 'R0'
    errors = gate().check(tmp_path, 'launch', a)
    assert not any(e.provider == 'comparison' for e in errors)


def test_pending_exposes_advisory_role_transport(tmp_path):
    from ravel.workflow import review_points as rp
    run(tmp_path, delegated=False, nodes=[{'id': 'N1', 'operation': 'literal-calculation'}])
    point = next(p for p in rp.pending(tmp_path) if p['row'] == 1)
    assert point['transport_advisories'] == [{'code': 'review_transport_advisory', 'role': 'plan-critic', 'blocking': False}]
