"""Synthetic recipe witnesses; no tool execution or scientific certification."""
import hashlib
import importlib
import json

import pytest


def ledger():
    return importlib.import_module('ravel.workflow.recipe_ledger')


def write(root, path, value):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value) if not isinstance(value, str) else value)
    return {'path': path, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}


def native(root, requested=9, effective=7):
    card = write(root, 'output/run_card.dat', f'{effective} = ptj\n-1 = dynamical_scale_choice\n')
    write(root, 'inputs/native_execution_plan.json', {
        'effective_controls': {'generation': {'ptj': requested}, 'statistics': {'mc_stat': 'none'}},
        'rendered': {'run_card.dat': f'{requested} = ptj\n-1 = dynamical_scale_choice\n'},
        'expected_masses_gev': {}, 'shower_translation': {'requested_overlays': {}},
        'sources': [], 'stages': []})
    write(root, 'output/native_effective_settings.json', {
        'cards': {'run_card.dat': card}, 'requested_controls': {'generation': {'ptj': requested},
            'tool_version_labels': {'engine': {'declared': '2.0', 'disposition': 'label_only'}}},
        'effective': {'generation': {'ptj': str(effective)}, 'statistics': {'mc_stat': 'none'}}})
    return card


def row(record, layer, field, node=None):
    return next(r for r in record['rows'] if r['layer'] == layer and r['field'] == field and r['node_id'] == node)


def test_unapplied_requested_option_is_deviated_before_full(tmp_path):
    native(tmp_path)
    record = ledger().build(tmp_path)
    value = row(record, 'generation', '/ptj')
    assert (value['status'], value['requested'], value['effective']) == ('deviated', 9, '7')
    assert any(value['id'] in e for e in ledger().before_full_errors(tmp_path))


def test_every_operation_critical_field_has_a_row(tmp_path, monkeypatch):
    from ravel.validation import validate_request_plan as rp
    monkeypatch.setattr(rp, 'signatures', lambda: {'synthetic-operation': {
        'critical_fields': ['/task/alpha', '/task/beta']}})
    write(tmp_path, 'inputs/plan.json', {'nodes': [{'id': 'N1', 'operation': 'synthetic-operation',
        'fields': [{'pointer': '/task/alpha', 'value': 3, 'authority': 'supplied', 'evidence': 'span:1'}]}]})
    record = ledger().build(tmp_path)
    assert {(r['node_id'], r['field']) for r in record['rows'] if r['layer'] == 'operation'} == {
        ('N1', '/task/alpha'), ('N1', '/task/beta')}
    assert row(record, 'operation', '/task/beta', 'N1')['status'] == 'unknown'


def observed(root, rel, data, layer='tool_versions', field='/engine', pointer='/engine', node=None):
    """A version probe written by a registered stage receipt from a RAVEL tool module."""
    from rdj_fixtures import Run
    run = Run.__new__(Run)
    run.root = root
    anchor = run.stage('probe-' + layer, rel, data)
    observation = {'layer': layer, 'field': field, 'node_id': node, 'pointer': pointer,
                   'receipt_id': anchor['binding']['receipt_id'],
                   'pin': {'path': rel, 'sha256': anchor['binding']['sha256']}}
    write(root, 'inputs/recipe_observations.json', {'observations': [observation]})
    return observation


def test_label_only_version_mismatch_is_deviated(tmp_path):
    native(tmp_path, requested=7)
    observed(tmp_path, 'output/versions.json', {'engine': '3.0'})
    value = row(ledger().build(tmp_path), 'tool_versions', '/engine')
    assert (value['status'], value['requested'], value['effective']) == ('deviated', '2.0', '3.0')


def test_unknown_is_in_checkin3_record(tmp_path):
    native(tmp_path, requested=7)
    document = {'schema_version': 1, 'kind': 'deck', 'sections': {'limitations': 'Synthetic study'}}
    rendered = ledger().with_checkin3_section(document, tmp_path)
    assert document['sections'] == {'limitations': 'Synthetic study'}
    section = rendered['sections']['recipe_ledger']
    assert row({'rows': section['unknown']}, 'tool_versions', '/engine')['status'] == 'unknown'
    assert section == ledger().checkin3_section(tmp_path)


def test_changed_card_is_read_instead_of_cached_effective_values(tmp_path):
    native(tmp_path, requested=7)
    (tmp_path / 'output/run_card.dat').write_text('11 = ptj\n')
    record = ledger().build(tmp_path)
    assert row(record, 'generation', '/ptj')['effective'] == '11'
    assert row(record, 'generation', '/ptj')['status'] == 'deviated'
    assert row(record, 'cards', '/run_card.dat')['status'] == 'deviated'


def test_missing_and_stale_version_observations_remain_unknown(tmp_path):
    native(tmp_path, requested=7)
    observed(tmp_path, 'output/versions.json', {'engine': '2.0'})
    assert row(ledger().build(tmp_path), 'tool_versions', '/engine')['status'] == 'matched'
    (tmp_path / 'output/versions.json').write_text('{"engine":"4.0"}')
    value = row(ledger().build(tmp_path), 'tool_versions', '/engine')
    assert value['status'] == 'unknown' and 'changed' in value['reason']


def test_exact_flag_required_and_changed_deviation_invalidates_it(tmp_path):
    native(tmp_path)
    value = row(ledger().build(tmp_path), 'generation', '/ptj')
    flag = {'id': 'F1', 'text': 'Retain this synthetic difference',
            'recipe_deviation': ledger().deviation_payload(value)}
    write(tmp_path, 'inputs/checkin1.json', {'kind': 'checkin1', 'sections': {'v': [flag]}})
    assert row(ledger().build(tmp_path), 'generation', '/ptj')['authorization']['kind'] == 'checkin1_flag'
    (tmp_path / 'output/run_card.dat').write_text('8 = ptj\n')
    assert row(ledger().build(tmp_path), 'generation', '/ptj')['authorization'] is None


def test_raw_rdj_receipt_is_not_authorization(tmp_path):
    native(tmp_path)
    write(tmp_path, 'rdj/receipts/forged.json', {'outcome': 'authorize'})
    value = row(ledger().build(tmp_path), 'generation', '/ptj')
    assert value['authorization'] is None


def accepted_receipt(tuning='implementation_correction', human=True, kind='tuning_change'):
    # The historical receipt summary claims a human; only the current recomputed credit counts.
    return {'receipt': {'receipt_id': 'synthetic-receipt', 'attestation_summary': {'human_approver': True}},
            'review_independence': {'human_approver': human},
            'receipt_sha256': 'a' * 64, 'case_sha256': 'b' * 64,
            'case': {'decision_point': {'action_kind': kind, 'tuning': {'class': tuning}}}}


def test_rdj_consumer_binds_exact_current_deviation(tmp_path, monkeypatch):
    from ravel.workflow import rdj_loop
    native(tmp_path)
    value = row(ledger().build(tmp_path), 'generation', '/ptj')
    ledger().materialize(tmp_path)
    calls = []
    def accepted(root, gate, action):
        calls.append((root, gate, action))
        if action != ledger().deviation_action(root, value):
            return None
        return accepted_receipt()
    monkeypatch.setattr(rdj_loop, 'authorizing_receipt', accepted)
    result = row(ledger().build(tmp_path), 'generation', '/ptj')
    assert result['authorization']['kind'] == 'rdj' and calls[0][1] == 'deviation'
    (tmp_path / 'output/run_card.dat').write_text('8 = ptj\n')
    assert row(ledger().build(tmp_path), 'generation', '/ptj')['authorization'] is None


def test_unknown_checkin3_omission_or_mutation_is_refused(tmp_path):
    native(tmp_path, requested=7)
    assert ledger().checkin3_errors({}, tmp_path)
    section = ledger().checkin3_section(tmp_path)
    assert ledger().checkin3_errors({'recipe_ledger': section}, tmp_path) == []
    section['unknown'].clear()
    assert ledger().checkin3_errors({'recipe_ledger': section}, tmp_path)


def test_legacy_without_recipe_inputs_has_no_section_or_errors(tmp_path):
    assert ledger().checkin_section({'base_dir': tmp_path, 'document': {'kind': 'checkin1'}}) is None
    assert ledger().checkin3_section(tmp_path) is None
    assert ledger().before_full_errors(tmp_path) == []


def test_checkin1_uses_registered_seam_and_blocks_unflagged_deviation(tmp_path):
    from ravel.validation import validate_checkin as vc
    native(tmp_path)
    document = {'kind': 'checkin1', 'sections': {'v': []}}
    rendered = json.loads(vc.checkin_bytes(document, tmp_path))
    assert row(rendered['sections']['recipe_ledger'], 'generation', '/ptj')['status'] == 'deviated'
    assert any('recipe' in e for e in vc.registered_section_errors(rendered, tmp_path))


def test_plan_only_critical_fields_cannot_be_matched_by_self_declaration(tmp_path, monkeypatch):
    from ravel.validation import validate_request_plan as rp
    monkeypatch.setattr(rp, 'signatures', lambda: {'synthetic-operation': {'critical_fields': ['/task/alpha']}})
    write(tmp_path, 'inputs/plan.json', {'nodes': [{'id': 'N1', 'operation': 'synthetic-operation',
        'fields': [{'pointer': '/task/alpha', 'value': 3}]}]})
    assert row(ledger().build(tmp_path), 'operation', '/task/alpha', 'N1')['status'] == 'unknown'


def test_schema_rejects_bad_status_and_unbound_deviation(tmp_path):
    from jsonschema import Draft202012Validator
    native(tmp_path)
    record = ledger().build(tmp_path)
    validator = Draft202012Validator(ledger().schema())
    assert list(validator.iter_errors(record)) == []
    record['rows'][0]['status'] = 'certified'
    assert list(validator.iter_errors(record))


def test_delivery_validator_requires_unknown_rows_through_one_call_seam(tmp_path):
    from ravel.workflow import completion_claims
    native(tmp_path, requested=7)
    assert any('recipe' in e for e in completion_claims.checkin_errors({}, tmp_path, kind='deck'))
    sections = {'recipe_ledger': ledger().checkin3_section(tmp_path)}
    assert not any('recipe' in e for e in completion_claims.checkin_errors(sections, tmp_path, kind='deck'))


def test_launch_provider_is_registered_and_deviations_refuse(tmp_path):
    from ravel.workflow import decision_gate
    native(tmp_path)
    provider = next(p for p in decision_gate.providers('launch') if p['id'] == 'recipe_ledger')
    assert provider['active']
    assert ledger().gate_errors(tmp_path, 'launch', {'rung': 'full'})
    assert ledger().gate_errors(tmp_path, 'delivery', {}) == []


def test_inherited_run_card_settings_are_compared_and_removal_deviates(tmp_path):
    native(tmp_path, requested=7)
    (tmp_path / 'output/run_card.dat').write_text('7 = ptj\n')
    value = row(ledger().build(tmp_path), 'generation', '/dynamical_scale_choice')
    assert value['requested'] == '-1' and value['status'] == 'deviated'
    assert value['effective'] is None and value['effective_present']


def test_patch_metadata_overrides_prepared_statistics_declaration(tmp_path):
    native(tmp_path, requested=7)
    write(tmp_path, 'output/signal_model.json', {'mc_stat_policy': 'shapesys'})
    value = row(ledger().build(tmp_path), 'statistics', '/mc_stat')
    assert (value['requested'], value['effective'], value['status']) == ('none', 'shapesys', 'deviated')


def test_reference_recipe_layers_preserve_target_identity(tmp_path, monkeypatch):
    from ravel.validation import agreement_target
    native(tmp_path, requested=7)
    pin = write(tmp_path, 'inputs/reference-recipe.json', {'layers': {'generation': {'ptj': 13}}})
    write(tmp_path, 'inputs/agreement_targets.json', {'targets': []})
    monkeypatch.setattr(agreement_target, 'targets', lambda root: {'C1': {
        'reference': {'recipe_pins': [{'locator': pin['path'], 'sha256': pin['sha256']}]}}})
    value = row(ledger().build(tmp_path), 'generation', '/recipes/0/ptj')
    assert value['claim_id'] == 'C1' and value['status'] == 'deviated'


def test_contract_execution_plan_path_is_consumed(tmp_path):
    native(tmp_path)
    plan = json.loads((tmp_path / 'inputs/native_execution_plan.json').read_text())
    plan['effective_controls']['generation']['ptj'] = 13
    (tmp_path / 'inputs/native_execution_plan.json').unlink()
    pin = write(tmp_path, 'inputs/derivative-plan.json', plan)
    write(tmp_path, 'inputs/task_contract.json', {'execution_plan': pin})
    assert row(ledger().build(tmp_path), 'generation', '/ptj')['requested'] == 13


def test_stale_contract_plan_pin_is_refused(tmp_path):
    native(tmp_path)
    plan = json.loads((tmp_path / 'inputs/native_execution_plan.json').read_text())
    pin = write(tmp_path, 'inputs/derivative-plan.json', plan)
    write(tmp_path, 'inputs/task_contract.json', {'execution_plan': pin})
    write(tmp_path, 'inputs/derivative-plan.json', {**plan, 'changed': True})
    with pytest.raises(ValueError, match='hash'):
        ledger().build(tmp_path)


def test_rendered_widths_have_requested_and_current_rows(tmp_path):
    native(tmp_path, requested=7)
    plan = json.loads((tmp_path / 'inputs/native_execution_plan.json').read_text())
    plan['rendered']['param_card.dat'] = 'Block MASS\n 123 20\nDECAY 123 0.4\n'
    write(tmp_path, 'inputs/native_execution_plan.json', plan)
    write(tmp_path, 'output/param_card.dat', 'Block MASS\n 123 20\nDECAY 123 0.7\n')
    value = row(ledger().build(tmp_path), 'widths', '/123')
    assert (value['requested'], value['effective'], value['status']) == ('0.4', '0.7', 'deviated')


def test_plan_observation_cannot_self_ground_an_effective_field(tmp_path, monkeypatch):
    from ravel.validation import validate_request_plan as rp
    monkeypatch.setattr(rp, 'signatures', lambda: {'synthetic-operation': {'critical_fields': ['/task/alpha']}})
    pin = write(tmp_path, 'inputs/plan.json', {'nodes': [{'id': 'N1', 'operation': 'synthetic-operation',
        'fields': [{'pointer': '/task/alpha', 'value': 3}]}]})
    write(tmp_path, 'inputs/recipe_observations.json', {'observations': [
        {'layer': 'operation', 'node_id': 'N1', 'field': '/task/alpha', 'pin': pin, 'pointer': '/nodes/0/fields/0/value'}]})
    assert row(ledger().build(tmp_path), 'operation', '/task/alpha', 'N1')['status'] == 'unknown'


def test_revised_deviation_materialization_preserves_original_bytes(tmp_path):
    native(tmp_path)
    ledger().materialize(tmp_path)
    original = {p: p.read_bytes() for p in (tmp_path / 'outputs/recipe-deviations').glob('*.json')}
    (tmp_path / 'output/run_card.dat').write_text('8 = ptj\n')
    ledger().materialize(tmp_path)
    assert all(p.read_bytes() == raw for p, raw in original.items())
    assert len(list((tmp_path / 'outputs/recipe-deviations').glob('*.json'))) > len(original)


def test_inspection_does_not_write_or_execute(tmp_path, monkeypatch):
    import subprocess
    native(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('recipe inspection executed a tool'))
    ledger().build(tmp_path)
    ledger().before_full_errors(tmp_path)
    ledger().checkin3_section(tmp_path)
    assert before == {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_checkin3_input_error_is_a_refusal_not_a_traceback(tmp_path):
    write(tmp_path, 'inputs/plan.json', 'malformed')
    assert ledger().checkin3_errors({}, tmp_path)


def test_cached_manifest_without_card_evidence_cannot_match(tmp_path):
    native(tmp_path, requested=7)
    (tmp_path / 'output/run_card.dat').unlink()
    manifest = json.loads((tmp_path / 'output/native_effective_settings.json').read_text())
    manifest['cards'] = {}
    write(tmp_path, 'output/native_effective_settings.json', manifest)
    plan = json.loads((tmp_path / 'inputs/native_execution_plan.json').read_text())
    plan['rendered'] = {}
    write(tmp_path, 'inputs/native_execution_plan.json', plan)
    assert row(ledger().build(tmp_path), 'generation', '/ptj')['status'] == 'unknown'


def test_cli_returns_ledger_and_refuses_unaccepted_full(tmp_path, capsys):
    native(tmp_path)
    assert ledger().main(['--rundir', str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)['kind'] == 'recipe-ledger'
    assert ledger().main(['--rundir', str(tmp_path), '--check-full']) == 1
    assert 'recipe deviation' in capsys.readouterr().err


def test_legacy_native_checkin_bytes_keep_automatic_identity(tmp_path):
    from ravel.validation import validate_checkin as vc
    native(tmp_path)
    write(tmp_path, 'inputs/task_contract.json', {'schema_version': 1, 'agent_layer_epoch': 1})
    document = {'kind': 'checkin1', 'sections': {'v': []}}
    rendered = json.loads(vc.checkin_bytes(document, tmp_path))
    assert 'recipe_ledger' not in rendered['sections']
    assert ledger().checkin3_errors({}, tmp_path) == []
    assert row(ledger().build(tmp_path), 'generation', '/ptj')['status'] == 'deviated'


def test_epoch_two_ledger_cannot_be_omitted(tmp_path):
    from ravel.validation import validate_checkin as vc
    native(tmp_path)
    write(tmp_path, 'inputs/task_contract.json', {'schema_version': 1, 'agent_layer_epoch': 2})
    document = {'kind': 'checkin1', 'sections': {'v': []}}
    assert any('recipe' in e for e in vc.registered_section_errors(document, tmp_path))


def test_duplicate_observation_json_keys_are_refused(tmp_path):
    native(tmp_path)
    write(tmp_path, 'inputs/recipe_observations.json', '{"observations":[],"observations":[]}')
    with pytest.raises(ValueError, match='duplicate'):
        ledger().build(tmp_path)


def test_context_cannot_downgrade_current_epoch_two_contract(tmp_path):
    from ravel.validation import validate_checkin as vc
    native(tmp_path)
    write(tmp_path, 'inputs/task_contract.json', {'agent_layer_epoch': 2})
    document = {'kind': 'checkin1', 'sections': {'v': []}}
    errors = vc.registered_section_errors(document, tmp_path,
                                          context={'contract': {'agent_layer_epoch': 1}})
    assert any('recipe' in e for e in errors)


def test_dot_dot_plan_path_cannot_self_ground_an_effective_field(tmp_path, monkeypatch):
    from ravel.validation import validate_request_plan as rp
    monkeypatch.setattr(rp, 'signatures', lambda: {'synthetic-operation': {'critical_fields': ['/task/alpha']}})
    pin = write(tmp_path, 'inputs/plan.json', {'nodes': [{'id': 'N1', 'operation': 'synthetic-operation',
        'fields': [{'pointer': '/task/alpha', 'value': 3}]}]})
    (tmp_path / 'output').mkdir()
    pin['path'] = 'output/../inputs/plan.json'
    write(tmp_path, 'inputs/recipe_observations.json', {'observations': [
        {'layer': 'operation', 'node_id': 'N1', 'field': '/task/alpha', 'pin': pin, 'pointer': '/nodes/0/fields/0/value'}]})
    assert row(ledger().build(tmp_path), 'operation', '/task/alpha', 'N1')['status'] == 'unknown'


# ---- producer custody, translation, approval progress, authorization scope, run-relative evidence

def test_agent_written_observation_cannot_hide_a_version_mismatch(tmp_path):
    native(tmp_path, requested=7)
    pin = write(tmp_path, 'scratch/notes.json', {'v': '2.0'})
    write(tmp_path, 'inputs/recipe_observations.json', {'observations': [
        {'layer': 'tool_versions', 'field': '/engine', 'node_id': None, 'pin': pin, 'pointer': '/v'}]})
    value = row(ledger().build(tmp_path), 'tool_versions', '/engine')
    assert value['status'] == 'unknown' and 'receipt' in value['reason']
    observation = observed(tmp_path, 'output/versions.json', {'engine': '3.0'})
    observation.update(pin=pin, pointer='/v')
    write(tmp_path, 'inputs/recipe_observations.json', {'observations': [observation]})
    assert row(ledger().build(tmp_path), 'tool_versions', '/engine')['status'] == 'unknown'


def test_plan_copy_cannot_ground_an_operation_field(tmp_path, monkeypatch):
    from ravel.validation import validate_request_plan as rp
    monkeypatch.setattr(rp, 'signatures', lambda: {'synthetic-operation': {'critical_fields': ['/task/alpha']}})
    plan = {'nodes': [{'id': 'N1', 'operation': 'synthetic-operation', 'fields': [{'pointer': '/task/alpha', 'value': 3}]}]}
    write(tmp_path, 'inputs/plan.json', plan)
    copy = write(tmp_path, 'inputs/plan-copy.json', plan)
    observation = observed(tmp_path, 'output/alpha.json', {'alpha': 3}, layer='operation', field='/task/alpha',
                           pointer='/alpha', node='N1')
    assert row(ledger().build(tmp_path), 'operation', '/task/alpha', 'N1')['status'] == 'matched'
    observation.update(pin=copy, pointer='/nodes/0/fields/0/value')
    write(tmp_path, 'inputs/recipe_observations.json', {'observations': [observation]})
    assert row(ledger().build(tmp_path), 'operation', '/task/alpha', 'N1')['status'] == 'unknown'


def test_dropped_requested_option_is_deviated_and_blocks_full(tmp_path):
    native(tmp_path, requested=7, effective=7)
    write(tmp_path, 'inputs/plan.json', {'nodes': [{'id': 'N1', 'operation': 'synthetic-operation', 'fields': [
        {'pointer': '/generation/run_settings', 'value': {'ptj': 7, 'ptj1min': 150}}]}]})
    record = ledger().build(tmp_path)
    dropped = row(record, 'translation', '/generation/ptj1min', 'N1')
    assert (dropped['status'], dropped['requested'], dropped['effective']) == ('deviated', 150, None)
    assert row(record, 'translation', '/generation/ptj', 'N1')['status'] == 'matched'
    assert any(dropped['id'] in e for e in ledger().before_full_errors(tmp_path))
    (tmp_path / 'output/run_card.dat').unlink()
    assert row(ledger().build(tmp_path), 'translation', '/generation/ptj1min', 'N1')['status'] == 'deviated'


def test_null_requested_control_does_not_match_an_absent_setting(tmp_path):
    native(tmp_path, requested=7)
    plan = json.loads((tmp_path / 'inputs/native_execution_plan.json').read_text())
    plan['effective_controls']['generation']['xqcut'] = None
    write(tmp_path, 'inputs/native_execution_plan.json', plan)
    assert row(ledger().build(tmp_path), 'generation', '/xqcut')['status'] == 'deviated'


def test_correct_evidence_after_checkin1_keeps_the_approved_ledger(tmp_path):
    native(tmp_path, requested=7)
    context = {'base_dir': tmp_path, 'document': {'kind': 'checkin1', 'sections': {'v': []}}}
    approved = ledger().checkin_section(context)
    assert row(approved, 'tool_versions', '/engine')['status'] == 'unknown'
    observed(tmp_path, 'output/versions.json', {'engine': '2.0'})
    assert row(ledger().build(tmp_path), 'tool_versions', '/engine')['status'] == 'matched'
    assert ledger().section_errors(approved, context) == []
    edited = json.loads(json.dumps(approved))
    row(edited, 'generation', '/ptj')['requested'] = 8
    assert ledger().section_errors(edited, context)
    edited = json.loads(json.dumps(approved))
    edited['rows'] = [r for r in edited['rows'] if r['layer'] != 'tool_versions']
    assert ledger().section_errors(edited, context)


@pytest.mark.parametrize('tuning,human,kind', [('implementation_correction', False, 'tuning_change'),
                                               ('calibration', True, 'tuning_change'),
                                               ('implementation_correction', True, 'promotion')])
def test_rdj_receipt_authorizes_only_within_its_class_and_with_human_approval(tmp_path, monkeypatch, tuning,
                                                                             human, kind):
    from ravel.workflow import rdj_loop
    native(tmp_path)
    ledger().materialize(tmp_path)
    monkeypatch.setattr(rdj_loop, 'authorizing_receipt', lambda root, gate, action: accepted_receipt(tuning, human, kind))
    assert row(ledger().build(tmp_path), 'generation', '/ptj')['authorization'] is None
    assert ledger().before_full_errors(tmp_path)


def test_flag_survives_a_symlinked_or_moved_run(tmp_path):
    import shutil
    run = tmp_path / 'run'
    native(run)
    value = row(ledger().build(run), 'generation', '/ptj')
    assert all(not p['path'].startswith('/') for p in value['evidence'])
    write(run, 'inputs/checkin1.json', {'kind': 'checkin1', 'sections': {'v': [
        {'id': 'F1', 'text': 'Retain this synthetic difference', 'recipe_deviation': ledger().deviation_payload(value)}]}})
    alias = tmp_path / 'alias'
    alias.symlink_to(run)
    assert row(ledger().build(alias), 'generation', '/ptj')['authorization']['kind'] == 'checkin1_flag'
    shutil.copytree(run, tmp_path / 'moved')
    assert row(ledger().build(tmp_path / 'moved'), 'generation', '/ptj')['authorization']['kind'] == 'checkin1_flag'


def test_checkin3_refuses_a_disclosed_but_unauthorized_deviation(tmp_path):
    native(tmp_path)
    section = ledger().checkin3_section(tmp_path)
    assert section['deviated']
    assert any('needs an accepted' in e for e in ledger().checkin3_errors({'recipe_ledger': section}, tmp_path))


def test_epoch_two_launch_refuses_an_unpinned_native_plan(tmp_path):
    native(tmp_path, requested=7)
    write(tmp_path, 'inputs/task_contract.json', {'agent_layer_epoch': 2})
    assert any('execution plan' in e for e in ledger().before_full_errors(tmp_path))


def test_malformed_plan_is_a_typed_gate_refusal(tmp_path):
    native(tmp_path)
    plan = json.loads((tmp_path / 'inputs/native_execution_plan.json').read_text())
    plan['effective_controls'] = ['not', 'a', 'map']
    write(tmp_path, 'inputs/native_execution_plan.json', plan)
    errors = ledger().gate_errors(tmp_path, 'launch', {'rung': 'full'})
    assert errors and 'unreadable' in errors[0].message


def test_schema_admits_producer_evidence_and_translation_rows(tmp_path):
    from jsonschema import Draft202012Validator
    native(tmp_path, requested=7)
    write(tmp_path, 'inputs/plan.json', {'nodes': [{'id': 'N1', 'operation': 'synthetic-operation', 'fields': [
        {'pointer': '/generation/run_settings', 'value': {'ptj1min': 150}}]}]})
    observed(tmp_path, 'output/versions.json', {'engine': '2.0'})
    assert list(Draft202012Validator(ledger().schema()).iter_errors(ledger().build(tmp_path))) == []
