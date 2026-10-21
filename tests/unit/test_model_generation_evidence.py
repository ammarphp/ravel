"""Inert admission, derivation and generation custody controls."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ravel.physics import model_admission as admission, model_derivation_bridge as derivation
from ravel.physics import model_events as events
from test_model_admission import ufo, mg5_runner
from test_model_events import config, texts, write, pin, tree
from model_validation_fixture import supplied_evidence


def configured(tmp_path):
    c = config(tmp_path / 'inputs')
    c['model_validation'] = supplied_evidence(tmp_path / 'evidence', Path(c['model_tree']['root']),
        texts(c)['process'], Path(c['cards']['parameter']['path']))
    return c


def consume(tmp_path, c):
    path = tmp_path / 'config.json'
    write(path, c)
    return events.inputs({'config': str(path)}, tmp_path)


def test_generation_requires_admission_and_width_evidence(tmp_path):
    c = config(tmp_path / 'inputs')
    c.pop('model_validation', None)
    with pytest.raises(ValueError, match='model_evidence_absent'):
        consume(tmp_path, c)


def test_supplied_model_provenance_is_qualified_and_bound_into_inputs(tmp_path):
    c = configured(tmp_path)
    files = consume(tmp_path, c)
    result = admission.generation_evidence(c['model_validation'], tmp_path,
        ufo=c['model_tree']['root'], process=texts(c)['process'], card=c['cards']['parameter']['path'])
    assert result['origin'] == 'external' and result['checked_here'] is False
    assert result['qualifications']
    assert set(map(Path, result['inputs'])) <= set(files)


@pytest.mark.parametrize('receipt', ['admission', 'widths'])
@pytest.mark.parametrize('defect,reason', [('absent', 'absent'), ('failed', 'failed'),
    ('model', 'foreign'), ('process', 'foreign'), ('card', 'foreign'), ('stale', 'stale')])
def test_inapplicable_receipts_refuse_with_reason_and_remedy(tmp_path, receipt, defect, reason):
    c = configured(tmp_path)
    evidence = c['model_validation']
    path = Path(evidence[receipt]['path'])
    record = json.loads(path.read_text())
    if defect == 'absent':
        del evidence[receipt]
    elif defect == 'stale':
        path.write_text(path.read_text() + ' ')
    else:
        if defect == 'failed': record['decision' if receipt == 'admission' else 'status'] = 'failed'
        elif defect == 'model': record['binding']['ufo_digest'] = 'a' * 64
        elif defect == 'process': record['binding']['process_commands'] = ['generate x x > y y']
        elif defect == 'card': record['binding']['parameter_card_sha256'] = 'b' * 64
        evidence[receipt] = write(path, record)
    with pytest.raises(ValueError, match='model_evidence_' + reason) as caught:
        consume(tmp_path, c)
    assert caught.value.reason == 'model_evidence_' + reason
    assert caught.value.remedy


def test_external_provenance_change_is_stale_even_with_current_receipt_pins(tmp_path):
    c = configured(tmp_path)
    record = json.loads(Path(c['model_validation']['admission']['path']).read_text())
    Path(record['provenance'][0]['path']).write_text('changed original validation\n')
    with pytest.raises(ValueError, match='model_evidence_stale'):
        consume(tmp_path, c)


def test_local_admission_binds_checks_to_the_explicit_card_and_definitions(tmp_path):
    model = ufo(tmp_path / 'model')
    card = tmp_path / 'param.dat'
    card.write_text(derivation.literal_external_card((model / 'parameters.py').read_text())[0])
    seen = []
    record = admission.admit(model, mg5='inert', process='beam beam > a a',
        definitions=['define beam = e+ e-'], parameter_card=card,
        workdir=tmp_path / 'checks', mg5_runner=mg5_runner({}, seen))
    assert record['decision'] == 'admitted'
    assert record['generation_binding'] == admission.generation_binding(model,
        'define beam = e+ e-\ngenerate beam beam > a a\n', card)
    assert all('define beam = e+ e-' in script for script in seen)
    assert all(str(card) not in script[-1] for script in seen)  # native checks use their private card copy
    assert all('param_card.dat' in script[-1] for script in seen)
    assert all(Path(script[-1].split()[2]).read_bytes() == card.read_bytes() for script in seen)


def test_failed_required_check_refuses_even_when_top_level_decision_claims_admitted(tmp_path):
    model = ufo(tmp_path / 'model')
    card = tmp_path / 'card.dat'
    card.write_text(derivation.literal_external_card((model / 'parameters.py').read_text())[0])
    record = admission.admit(model, mg5='inert', process='e+ e- > a a', parameter_card=card,
        workdir=tmp_path / 'checks', mg5_runner=mg5_runner({}))
    record['checks'][0]['status'] = 'fail'
    evidence = {'admission': write(tmp_path / 'admission.json', record),
                'widths': write(tmp_path / 'width.json', {})}
    with pytest.raises(ValueError, match='model_evidence_failed'):
        admission.generation_evidence(evidence, tmp_path, ufo=model,
            process='generate e+ e- > a a\n', card=card)


def local_chain(tmp_path):
    model = ufo(tmp_path / 'model')
    card = tmp_path / 'card.dat'
    card.write_text(derivation.literal_external_card((model / 'parameters.py').read_text())[0])
    process = 'generate e+ e- > a a\n'
    record = admission.admit(model, mg5='inert', process='e+ e- > a a', parameter_card=card,
        workdir=tmp_path / 'checks', mg5_runner=mg5_runner({}))
    manifest = write(tmp_path / 'ufo-source.json', events.bridge.source_tree(model))
    source = {'ufo': str(model), 'ufo_manifest': manifest, 'parameter_card': pin(card)}
    result = write(tmp_path / 'derivation.json', {'status': 'passed', 'handoff_eligible': True,
        'checks': {'passed': True}, 'exported_source': source})
    handoff = write(tmp_path / 'handoff.json', {**source, 'qualified_for_scoped_reuse': True,
        'accepted_review': {'claim_scope': 'model_source_derivation', 'attestation': 'fictional control'},
        'successful_derivation_attempt': {'id': 'attempt', **write(tmp_path / 'attempt.json', {})},
        'derivation_result': result})
    widths = derivation.generation_width_receipt(handoff['path'], record['generation_binding'])
    evidence = {'admission': write(tmp_path / 'admission.json', record),
                'widths': write(tmp_path / 'widths.json', widths)}
    return model, card, process, evidence, handoff


def test_accepted_local_chain_reaches_model_events_with_both_receipts(tmp_path):
    model, card, process, evidence, handoff = local_chain(tmp_path)
    c = config(tmp_path / 'inputs')
    c.update(model_tree={'root': str(model), 'manifest': write(tmp_path / 'manifest.json',
             events.bridge.source_tree(model))}, model_validation=evidence)
    c['cards']['parameter'] = pin(card)
    c['cards']['process'] = write(tmp_path / 'process.dat', process)
    files = consume(tmp_path, c)
    assert Path(handoff['path']) in files
    receipt = admission.generation_evidence(evidence, tmp_path, ufo=model, process=process, card=card)
    assert receipt['origin'] == 'local' and receipt['checked_here'] is True
    assert receipt['binding']['parameter_card_sha256'] == pin(card)['sha256']


@pytest.mark.parametrize('target', ['derivation', 'attempt', 'log', 'model', 'card'])
def test_local_chain_changed_sources_refuse(tmp_path, target):
    model, card, process, evidence, handoff = local_chain(tmp_path)
    doc = json.loads(Path(handoff['path']).read_text())
    if target == 'derivation': path = Path(doc['derivation_result']['path'])
    elif target == 'attempt': path = Path(doc['successful_derivation_attempt']['path'])
    elif target == 'log': path = next((tmp_path / 'checks').rglob('mg5.log'))
    elif target == 'model': path = model / 'couplings.py'
    else: path = card
    path.write_text(path.read_text() + '\n# changed\n' if target in ('model', 'card') else path.read_text() + ' ')
    with pytest.raises(admission.ModelEvidenceError) as caught:
        admission.generation_evidence(evidence, tmp_path, ufo=model, process=process, card=card)
    assert caught.value.reason in ('model_evidence_stale', 'model_evidence_foreign')


def test_width_receipt_cli_uses_the_accepted_derivation_and_admission(tmp_path):
    _, _, _, evidence, handoff = local_chain(tmp_path)
    output = tmp_path / 'cli-widths.json'
    assert derivation.main(['width-receipt', '--handoff', handoff['path'],
        '--admission', evidence['admission']['path'], '--out', str(output)]) == 0
    assert json.loads(output.read_text())['status'] == 'passed'


@pytest.mark.parametrize('defect', ['checks', 'status', 'card'])
def test_failed_or_foreign_derivation_widths_refuse(tmp_path, defect):
    _, _, _, evidence, handoff = local_chain(tmp_path)
    h = json.loads(Path(handoff['path']).read_text())
    result = json.loads(Path(h['derivation_result']['path']).read_text())
    if defect == 'checks': result['checks']['passed'] = False
    elif defect == 'status': result['status'] = 'failed'
    else: result['exported_source']['parameter_card']['sha256'] = 'c' * 64
    h['derivation_result'] = write(Path(h['derivation_result']['path']), result)
    new_handoff = write(Path(handoff['path']), h)
    record = json.loads(Path(evidence['admission']['path']).read_text())
    with pytest.raises(admission.ModelEvidenceError, match='failed|foreign'):
        derivation.generation_width_receipt(new_handoff['path'], record['generation_binding'])


def test_scoped_generation_retains_external_qualification_through_the_receipt(tmp_path):
    from test_scoped_generation_front_end import native, lepton_spec, plan, execute
    spec = lepton_spec(native(tmp_path))
    rd, proposal = plan(tmp_path, spec)
    assert proposal['model_validation']['single']['checked_here'] is False
    execute(rd)
    receipt = json.loads((rd / 'outputs/generation-receipt.json').read_text())
    assert receipt['model']['validation']['single']['origin'] == 'external'
    assert receipt['model']['validation']['single']['qualifications']


@pytest.mark.parametrize('defect,reason', [('absent', 'absent'), ('failed', 'failed'),
    ('process', 'foreign'), ('card', 'foreign'), ('model', 'foreign'), ('stale', 'stale')])
def test_scoped_consumer_refuses_inapplicable_evidence(tmp_path, defect, reason):
    from test_scoped_generation_front_end import native, lepton_spec, plan
    spec = lepton_spec(native(tmp_path))
    g = spec['generation']
    path = Path(g['model_validation']['admission']['path'])
    record = json.loads(path.read_text())
    if defect == 'absent': g.pop('model_validation')
    elif defect == 'stale': path.write_text(path.read_text() + ' ')
    else:
        if defect == 'failed': record['decision'] = 'refused'
        elif defect == 'process': record['binding']['process_commands'] = ['generate x x > y y']
        elif defect == 'model': record['binding']['ufo_digest'] = 'a' * 64
        else: record['binding']['parameter_card_sha256'] = 'b' * 64
        g['model_validation']['admission'] = write(path, record)
    with pytest.raises(admission.ModelEvidenceError, match='model_evidence_' + reason):
        plan(tmp_path, spec)


def test_reweight_point_requires_its_own_validated_card(tmp_path):
    from test_model_events import parameter_reweight
    c = configured(tmp_path)
    point = parameter_reweight(c, tmp_path)
    consume(tmp_path, c)
    del point['model_validation']
    with pytest.raises(admission.ModelEvidenceError, match='model_evidence_absent'):
        consume(tmp_path, c)


def test_native_generation_has_the_same_receipt_boundary(tmp_path, monkeypatch):
    from ravel.physics import native_pipeline
    from test_native_dispatch import configuration
    from model_validation_fixture import native_evidence
    config_path = configuration(tmp_path)
    build = tmp_path / 'build'
    native_evidence(config_path, build)
    c = native_pipeline.read_config(config_path)['ravel']['native']
    card = tmp_path / 'cards/param.dat'
    checked = native_pipeline.model_validation(c['model_validation'], base=tmp_path,
        process_card=tmp_path / 'cards/process.dat', parameter_text=card.read_text(), tools=build / 'tools')
    assert checked['origin'] == 'external'
    plan = {'rundir': str(tmp_path), 'inputs': {'process_card': str(tmp_path / 'cards/process.dat')},
            'model_validation': checked}
    out = tmp_path / 'output'
    out.mkdir(); (out / 'param_card.dat').write_bytes(card.read_bytes())
    monkeypatch.setattr(native_pipeline, 'native_build_root', lambda: build)
    assert native_pipeline.require_model_validation(plan) == checked
    (out / 'param_card.dat').write_text(card.read_text().replace('300', '301'))
    with pytest.raises(admission.ModelEvidenceError, match='model_evidence_foreign'):
        native_pipeline.require_model_validation(plan)
    del plan['model_validation']
    with pytest.raises(admission.ModelEvidenceError, match='model_evidence_absent'):
        native_pipeline.require_model_validation(plan)


@pytest.mark.parametrize('defect', ['missing', 'duplicate', 'false-summary', 'wrong-process', 'wrong-card', 'wrong-model', 'wrong-alias'])
def test_local_required_check_records_preserve_their_actual_scope(tmp_path, defect):
    model, card, process, evidence, _ = local_chain(tmp_path)
    path = Path(evidence['admission']['path'])
    record = json.loads(path.read_text())
    check = next(r for r in record['checks'] if r['id'] == 'mg5-check-gauge')
    if defect == 'missing': record['checks'].remove(check)
    elif defect == 'duplicate': record['checks'].append(deepcopy(check))
    elif defect == 'false-summary': check['status'] = 'error'
    elif defect == 'wrong-process': check['process'] = 'x x > y y'
    elif defect == 'wrong-card': check['parameter_card_sha256'] = 'b' * 64
    elif defect == 'wrong-model': check['ufo_digest'] = 'c' * 64
    else: check['definitions'] = ['define beam = x y']
    evidence['admission'] = write(path, record)
    with pytest.raises(admission.ModelEvidenceError):
        admission.generation_evidence(evidence, tmp_path, ufo=model, process=process, card=card)


def test_complete_process_population_is_checked_and_bound(tmp_path):
    model = ufo(tmp_path / 'model')
    card = tmp_path / 'card.dat'
    card.write_text(derivation.literal_external_card((model / 'parameters.py').read_text())[0])
    process = tmp_path / 'process.dat'
    process.write_text('define beam = e+ e-\ngenerate beam beam > a a\nadd process e+ e- > e+ e-\n')
    seen = []
    record = admission.admit(model, mg5='inert', process_card=process, parameter_card=card,
        workdir=tmp_path / 'checks', mg5_runner=mg5_runner({}, seen))
    assert record['decision'] == 'admitted' and len(seen) == 6
    assert all(len(row['cases']) == 2 for row in record['checks'] if row['id'].startswith('mg5-check-'))
    binding = admission.generation_binding(model, process.read_text(), card)
    files = []
    assert admission.accepted_admission(record, binding, tmp_path, files) == 'local'
    assert len(files) == 18  # log, command and exact private card for every native check


def test_supplied_widths_keep_their_origin_alongside_local_admission(tmp_path):
    model, card, process, evidence, _ = local_chain(tmp_path)
    external = supplied_evidence(tmp_path / 'external', model, process, card)
    evidence['widths'] = external['widths']
    result = admission.generation_evidence(evidence, tmp_path, ufo=model, process=process, card=card)
    assert result['origin'] == 'mixed' and result['checked_here'] is False
    assert result['admission_origin'] == 'local' and result['width_origin'] == 'external'


@pytest.mark.parametrize('missing', ['qualification', 'provenance'])
def test_supplied_model_requires_attributed_external_validation(tmp_path, missing):
    c = configured(tmp_path)
    path = Path(c['model_validation']['admission']['path'])
    record = json.loads(path.read_text())
    del record[missing]
    c['model_validation']['admission'] = write(path, record)
    with pytest.raises(admission.ModelEvidenceError, match='model_evidence_absent'):
        consume(tmp_path, c)


def test_graph_pins_receipts_and_ordinary_inputs_expand_the_original_provenance(tmp_path):
    from test_model_events import setup_request
    from ravel.workflow import model_event_plan
    request, c = setup_request(tmp_path)
    compact = model_event_plan.graph_inputs(request, tmp_path)
    expanded = model_event_plan.request_inputs(request, tmp_path)
    for pin_record in c['model_validation'].values():
        assert Path(pin_record['path']) in compact
    record = json.loads(Path(c['model_validation']['admission']['path']).read_text())
    proof = Path(record['provenance'][0]['path'])
    assert proof in expanded and proof not in compact


def test_generation_instruction_surface_and_directory_map_are_coherent():
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[2]
    done = subprocess.run([sys.executable, '-m', 'ravel.validation.check_agent_surface'],
        cwd=root, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr


def test_redefined_aliases_keep_their_chronological_native_meaning(tmp_path):
    model = ufo(tmp_path / 'model')
    card = tmp_path / 'card.dat'
    card.write_text(derivation.literal_external_card((model / 'parameters.py').read_text())[0])
    process = tmp_path / 'process.dat'
    setup = ['define original = e+ e-', 'define frozen = original', 'define original = a']
    process.write_text('\n'.join([*setup, 'generate frozen frozen > a a']) + '\n')
    seen = []
    result = admission.admit(model, mg5='inert', process_card=process, parameter_card=card,
        workdir=tmp_path / 'checks', mg5_runner=mg5_runner({}, seen))
    assert result['decision'] == 'admitted'
    assert all(script[-4:-1] == setup for script in seen)


def test_native_import_and_setup_match_the_selected_restriction(tmp_path):
    model = ufo(tmp_path / 'model')
    card = tmp_path / 'card.dat'
    card.write_text(derivation.literal_external_card((model / 'parameters.py').read_text())[0])
    process = tmp_path / 'process.dat'
    process.write_text('import model model\nset complex_mass_scheme True\ngenerate e+ e- > a a\n')
    seen = []
    result = admission.admit(model, mg5='inert', process_card=process, parameter_card=card,
        restriction='default', workdir=tmp_path / 'checks', mg5_runner=mg5_runner({}, seen))
    assert result['decision'] == 'admitted'
    assert all('set complex_mass_scheme True' in script for script in seen)
    assert all(next(line for line in script if line.startswith('import model ')).endswith('/model') for script in seen)
    with pytest.raises(admission.ModelEvidenceError, match='foreign'):
        admission.generation_binding(model, process.read_text(), card, restriction='full')


def test_historical_config_replay_preserves_the_actual_generation_prerequisite(tmp_path, monkeypatch):
    from test_source_successor import copied_request
    request = copied_request(tmp_path)
    request['config'].pop('model_validation')
    assert events.validate_config(request['config']) is request['config']
    request_path = tmp_path / 'request.json'
    write(request_path, request)
    monkeypatch.setattr(events, '_command', lambda *args: pytest.fail('native command reached before model admission'))
    with pytest.raises(admission.ModelEvidenceError, match='model_evidence_absent'):
        events.native_worker(request_path, tmp_path / 'out')
