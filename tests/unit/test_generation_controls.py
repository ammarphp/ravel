"""Synthetic planning witnesses; no native generation, shower or installation."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

import production_fixtures as pf
from test_scoped_generation_front_end import native, lepton_spec
from ravel.physics import scoped as worker, simplified_spectrum as ss, pythia_cards, event_production as ep
from ravel.workflow import scoped, scoped_spec, execution_backend, machine_lease


def pin(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': path.stat().st_size}


def core_spec(tmp_path, cores=None, grant=None):
    spec = lepton_spec(native(tmp_path))
    if cores is not None:
        spec['generation']['nb_core'] = cores
    if grant is not None:
        spec['execution'] = {'backend_plan': {'backend': 'native', 'resources': {'cpus': grant, 'memory_mib': 4096}}}
    return spec


def prepared(tmp_path, spec, grant=1, name='run'):
    rd = tmp_path / name
    (rd / 'inputs').mkdir(parents=True)
    g = deepcopy(spec['generation'])
    inputs = []
    plan = scoped.prepare_generation(rd, g, tmp_path, inputs, lease_cpus=grant)
    return rd, g, plan, inputs


def test_multicore_plan_refuses_missing_or_insufficient_cpu_grant(tmp_path):
    spec = core_spec(tmp_path, 8)
    assert any('CPU grant' in e for e in scoped_spec.validate(spec))
    with pytest.raises(ValueError, match='CPU grant'):
        prepared(tmp_path, spec)
    spec['execution'] = {'backend_plan': {'backend': 'native', 'resources': {'cpus': 4, 'memory_mib': 4096}}}
    assert any('CPU grant' in e for e in scoped_spec.validate(spec))
    for key in ('nb_core', 'run_mode'):
        spec['generation']['run_settings'][key] = 8
        assert any('declared resources' in e for e in scoped_spec.validate(spec))
        del spec['generation']['run_settings'][key]


def test_multicore_plan_records_grant_and_renders_mg_commands(tmp_path):
    spec = core_spec(tmp_path, 8, 8)
    assert scoped_spec.validate(spec) == []
    rd, g, plan, _ = prepared(tmp_path, spec, grant=8)
    assert plan['generation_resources'] == {'nb_core': 8, 'run_mode': 2, 'lease_cpus': 8}
    assert worker.mg_commands(rd, g, rd / 'process')[:3] == [
        'set automatic_html_opening False', 'set nb_core 8', 'set run_mode 2']


def test_default_mg_command_bytes_and_plan_stay_unchanged(tmp_path):
    spec = core_spec(tmp_path)
    rd, g, plan, _ = prepared(tmp_path, spec)
    proc = rd / 'process'
    expected = ('set automatic_html_opening False\nset nb_core 1\nset run_mode 0\n'
                f"set lhapdf {g['runtime']['lhapdf_config']}\nimport model sm\ngenerate e+ u > e+ u\noutput {proc}\n"
                f'launch {proc}\nshower=OFF\ndetector=OFF\nanalysis=OFF\nmadspin=OFF\nreweight=OFF\ndone\n'
                'set ebeam1 6500\nset ebeam2 6500\nset lpp1 1\nset lpp2 1\nset pdlabel lhapdf\nset lhaid 82400\n'
                'set fixed_ren_scale False\nset fixed_fac_scale False\nset dynamical_scale_choice 4\nset scalefact 1\n'
                'set nevents 3\nset iseed 11\nset use_syst False\nset systematics_program none\nset ickkw 0\ndone\n')
    assert ('\n'.join(worker.mg_commands(rd, g, proc)) + '\n').encode() == expected.encode()
    assert 'generation_resources' not in plan


def test_worker_refuses_multicore_without_live_matching_lease(tmp_path, monkeypatch):
    g = {'nb_core': 8}
    monkeypatch.setattr(machine_lease, 'holder', lambda: None)
    with pytest.raises(ValueError, match='live one-native-job lease'):
        worker.require_core_lease(tmp_path, g)
    monkeypatch.setenv(machine_lease.ENV, 'synthetic-lease')
    held = {'lease_id': 'synthetic-lease', 'alive': True, 'rundir': str(tmp_path), 'binding': {
        'generation_resources': {'nb_core': 4, 'run_mode': 2, 'lease_cpus': 4}}}
    monkeypatch.setattr(machine_lease, 'holder', lambda: held)
    with pytest.raises(ValueError, match='CPU grant'):
        worker.require_core_lease(tmp_path, g)
    held['binding']['generation_resources'] = worker.generation_resources(g, 8)
    worker.require_core_lease(tmp_path, g)
    held['rundir'] = str(tmp_path / 'other')
    with pytest.raises(ValueError, match='another run'):
        worker.require_core_lease(tmp_path, g)


def test_approved_binding_carries_cpu_grant_without_changing_machine_lease_api(tmp_path, monkeypatch):
    grant = worker.generation_resources({'nb_core': 8}, 8)
    monkeypatch.setattr(execution_backend, 'verify_stage_binding', lambda b: b)
    monkeypatch.setattr(scoped, 'lease_resources', lambda rd: grant)
    binding = execution_backend.approved_binding(tmp_path, 'parton', 'checkin1', 'full')
    assert binding['generation_resources'] == grant


def test_forged_cpu_binding_refuses_and_test_domain_lease_records_grant(tmp_path, monkeypatch, lock_domain_at):
    from ravel.workflow import workflow_state
    grant = worker.generation_resources({'nb_core': 8}, 8)
    monkeypatch.setattr(workflow_state, 'verify_approval', lambda *a, **k: [])
    monkeypatch.setattr(scoped, 'lease_resources', lambda rd: grant)
    binding = execution_backend.approved_binding(tmp_path, 'parton', 'checkin1', 'full')
    forged = deepcopy(binding)
    forged['generation_resources']['lease_cpus'] = 16
    with pytest.raises(ValueError, match='CPU grant differs'):
        execution_backend.verify_stage_binding(forged)
    # No native process is started. The lease API itself is exercised in the test lock
    # domain the harness gives this test; synthetic process identity avoids sandbox ps access.
    directory = machine_lease.machine_dir()
    assert machine_lease.domain() == 'test'
    monkeypatch.delenv(machine_lease.ENV, raising=False)
    monkeypatch.setattr(machine_lease, '_identity', lambda pid: {'pid': pid, 'start': 'synthetic'})
    with machine_lease.held('synthetic-generation', rundir=str(tmp_path), node_id='parton', binding=binding):
        record = json.loads((directory / machine_lease.RECORD_NAME).read_text())
        assert record['binding']['generation_resources'] == grant
    assert not (directory / machine_lease.RECORD_NAME).exists()


def pdf_spec(tmp_path, installed=True):
    spec = core_spec(tmp_path)
    g = spec['generation']
    name = 'NNPDF23_lo_as_0130_qed'
    g.update(pdf_set=name, pdf_install_record='install/state/install-state.json')
    g['run_settings']['lhaid'] = 247000
    g['process'] = 'p p > n1 n1'
    data = tmp_path / 'lhapdf-data'
    (data / name).mkdir()
    (data / name / f'{name}.info').write_text('SetIndex: 247000\nNumMembers: 1\nFlavors: [-5,-4,-3,-2,-1,1,2,3,4,5,21,22]\n')
    (data / name / f'{name}_0000.dat').write_text('synthetic member\n')
    (data / 'pdfsets.index').write_text(f'247000 {name} 1\n')
    record = tmp_path / g['pdf_install_record']
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({'schema_version': 1, 'steps': {'lhapdf-sets/sets': {
        'status': 'done', 'detail': {'sets': [name] if installed else [], 'data_path': str(data)}}}}))
    return spec, record, data / name


def test_named_pdf_absent_from_install_record_refuses_with_install_command(tmp_path):
    spec, _, _ = pdf_spec(tmp_path, installed=False)
    with pytest.raises(ValueError, match='absent from the install record.*install.sh --only lhapdf-sets'):
        prepared(tmp_path, spec)


def test_named_lo_pdf_is_recorded_and_incomplete_set_is_refused(tmp_path):
    spec, record, folder = pdf_spec(tmp_path)
    _, g, plan, inputs = prepared(tmp_path, spec)
    assert plan['pdf']['name'] == spec['generation']['pdf_set']
    assert plan['pdf']['lhaid'] == 247000 and str(record) in inputs
    assert g['run_settings']['pdlabel'] == 'lhapdf'
    (folder / f'{folder.name}_0000.dat').unlink()
    with pytest.raises(ValueError, match='incomplete.*install.sh'):
        prepared(tmp_path, spec, name='incomplete')


def test_named_pdf_unknown_and_identifier_disagreement_refuse(tmp_path):
    spec = core_spec(tmp_path)
    spec['generation']['pdf_set'] = 'synthetic-absent'
    assert any('absent from native/setup/pdf-sets.json' in e for e in scoped_spec.validate(spec))
    spec['generation']['pdf_set'] = 'NNPDF23_lo_as_0130_qed'
    assert any('requires pdlabel lhapdf and lhaid 247000' in e for e in scoped_spec.validate(spec))


def spectrum(invisible=True):
    return {'schema_version': 1, 'modsel': {'1': 1}, 'masses': {'1000022': 170, '1000039': 1e-9},
            'decays': {'1000022': {'width_GeV': 0.01, 'channels': [{'br': 1, 'daughters': [22, 1000039]}]}},
            'produced': [1000022], 'invisible': [1000039] if invisible else [],
            'model_pdgs': [1000022, 22], 'source': 'Synthetic photon and invisible decay control'}


def ufo(path):
    path.mkdir()
    (path / 'particles.py').write_text('n = Particle(pdg_code=1000022)\na = Particle(pdg_code=22)\n')


def test_outside_model_without_stable_invisible_declaration_refuses():
    with pytest.raises(ValueError, match='stable and invisible'):
        ss.build(spectrum(invisible=False))


def test_outside_model_closure_census_and_generator_copy(tmp_path):
    doc = ss.parse_slha(ss.build(spectrum()))
    report = ss.check_card(doc, invisible=[1000039], produced=[1000022], sm_masses={}, model_pdgs=[1000022,22])
    assert report['passed'] and report['outside_model'] == report['invisible_census'] == [1000039]
    original = deepcopy(doc)
    generated = ss.generator_document(doc, report['outside_model'])
    assert '1000039' not in ss.write_slha(generated) and doc == original
    assert generated['decays'][1000022]['width'] == 0.01
    assert generated['decays'][1000022]['channels'] == []


def test_scoped_plan_records_outside_model_and_keeps_full_shower_slha(tmp_path):
    spec = core_spec(tmp_path)
    root = Path(spec['generation']['runtime']['madgraph']) / 'models/sm'
    (root / 'particles.py').write_text('n = Particle(pdg_code=1000022)\na = Particle(pdg_code=22)\n')
    full = tmp_path / 'spectrum.slha'
    full.write_text(ss.build(spectrum()))
    spec['generation'].update(parameter_card=str(full), process='p p > n1 n1',
                              decay_states={'stable': [1000039], 'invisible': [1000039], 'produced': [1000022]})
    rd, g, plan, inputs = prepared(tmp_path, spec)
    assert plan['decay_states']['outside_model'] == [1000039]
    assert '1000039' not in (rd / g['parameter_card']).read_text()
    assert (rd / plan['shower_slha']['path']).read_bytes() == full.read_bytes()
    assert plan['shower_slha']['path'] in inputs


def test_scoped_shower_plan_carries_tune_and_full_slha_without_a_native_probe(tmp_path, monkeypatch):
    from ravel.physics import scoped_shower
    spec = core_spec(tmp_path)
    g = spec['generation']
    g.pop('cross_section_only')
    g['observables'] = [{'id': 'met', 'kind': 'missing_et', 'pdg': [1000039], 'abs_pdg': True,
                        'bin_edges': [0, 20, 40], 'normalization': 'events'}]
    root = Path(g['runtime']['madgraph']) / 'models/sm'
    (root / 'particles.py').write_text('n = Particle(pdg_code=1000022)\na = Particle(pdg_code=22)\n')
    full = tmp_path / 'spectrum.slha'
    full.write_text(ss.build(spectrum()))
    g.update(parameter_card=str(full), process='p p > n1 n1',
             decay_states={'stable': [1000039], 'invisible': [1000039], 'produced': [1000022]},
             shower={'engine': 'pythia8', 'python': g['runtime']['python'], 'seed': 71,
                     'settings': [], 'tune': 'monash'})
    monkeypatch.setattr(scoped_shower, 'probe', lambda python: [])
    assert scoped_spec.validate(spec) == []
    rd, frozen, plan, inputs = prepared(tmp_path, spec)
    assert plan['shower_tune']['name'] == 'monash'
    assert f'SLHA:file = {rd / plan["shower_slha"]["path"]}' in frozen['shower']['settings']
    assert '1000039:mayDecay = off' in frozen['shower']['settings']
    assert '1000039:isVisible = off' in frozen['shower']['settings']
    assert scoped_shower.check(frozen['shower']) == []
    assert any(p.endswith('/data/shower/tunes.json') for p in inputs)


def test_production_census_passes_full_slha_to_shower_and_refuses_swapping_it(tmp_path):
    task = pf.production_task(tmp_path)
    full = tmp_path / 'full.slha'
    full.write_text(ss.build(spectrum()))
    ufo(tmp_path / 'ufo')
    task['model'].update(slha=str(full), produced=[1000022], invisible=[1000039], ufo='ufo')
    task['detector']['cards'][0]['fix_invisibles'] = True
    compiled = ep.compile_task(task, tmp_path)
    assert compiled['census']['outside_model'] == compiled['census']['invisible'] == [1000039]
    assert f'SLHA:file = {full}' in compiled['variants'][0]['commands']
    assert 'SLHA:readFrom = 2' in compiled['variants'][0]['commands']
    assert '1000039:mayDecay = off' in compiled['variants'][0]['commands']
    assert '1000039:isVisible = off' in compiled['variants'][0]['commands']
    task['shower']['variants'] = [{'name': 'swap', 'commands': ['SLHA:readFrom = 1']}]
    with pytest.raises(ValueError, match='retain the full outside-model'):
        ep.compile_task(task, tmp_path)
    task['shower']['variants'] = [{'name': 'unstable', 'commands': ['1000039:mayDecay = on']}]
    with pytest.raises(ValueError, match='decay setting conflicts'):
        ep.compile_task(task, tmp_path)


def test_unknown_tune_refuses_and_builtin_and_settings_presets_record_sources(tmp_path):
    with pytest.raises(ValueError, match='unknown shower tune'):
        pythia_cards.resolve_tune('synthetic-missing')
    default = pythia_cards.resolve_tune()
    assert default['name'] == 'monash' and default['index'] == 14
    assert default['commands'] == ['Tune:pp = 14'] and default['pdf_requirement']['name']
    derived = pythia_cards.resolve_tune('monash-no-reconnection')
    assert derived['kind'] == 'settings' and derived['source'].startswith('https://')
    task = pf.production_task(tmp_path)
    task['shower']['tune'] = 'monash-no-reconnection'
    compiled = ep.compile_task(task, tmp_path)
    assert compiled['tune']['name'] == 'monash-no-reconnection'
    assert any('# preset: monash-no-reconnection' in l for l in compiled['variants'][0]['commands'])
    assert pythia_cards.parse('\n'.join(compiled['variants'][0]['commands']))['settings']['colourreconnection:reconnect'] == 'off'


def test_tune_pdf_or_index_conflict_refuses_and_other_overrides_follow_preset():
    for command in ('Tune:pp = 1', 'PDF:pSet = synthetic-other'):
        with pytest.raises(ValueError, match='conflicts'):
            pythia_cards.tune_commands('monash', [command])
    commands, record = pythia_cards.tune_commands('monash-no-reconnection', ['ColourReconnection:reconnect = on'])
    assert commands[-1] == 'ColourReconnection:reconnect = on'
    assert record['overrides'] == ['colourreconnection:reconnect']


def mlm_receipt(tmp_path):
    task = pf.production_task(tmp_path, merged=True)
    matching = task['shower'].pop('merging')
    matching['settings']['JetMatching:nJetMax'] = 1
    process = tmp_path / 'process.dat'
    process.write_text('generate p p > n2 x1+\nadd process p p > n2 x1+ j\n')
    run = tmp_path / 'run.dat'
    run.write_text('1 = ickkw\n20 = xqcut\n')
    py = tmp_path / 'pythia.dat'
    py.write_text('\n'.join(f'{k} = {v}' for k,v in matching['settings'].items())+'\n')
    doc = {'status': 'passed', 'status_scope': 'source_bound_generated_event_delivery',
           'intended': {'generation': {'scheme': 'mlm', 'order': 'LO', 'jet_token': 'j',
                                      'jet_multiplicities': [0,1], 'run_settings': {'ickkw':1, 'xqcut':20}},
                        'shower': {'merging_scale_gev': 30}, 'cards': {'process': pin(process)}},
           'rendered_cards': {'run': pin(run), 'pythia': pin(py)},
           'generated_artifacts': [pin(tmp_path / 'events.lhe'), pin(run), pin(py)],
           'observed_settings': {'run': {'ickkw': '1', 'xqcut': '20'},
                                 'shower': pythia_cards.parse(py.read_text())['settings']}}
    path = tmp_path / 'model-events-native.json'
    path.write_text(json.dumps(doc))
    task['events']['generation_receipt'] = str(path)
    return task, doc, path, matching


def test_hand_typed_mlm_block_disagreeing_with_receipt_refuses(tmp_path):
    task, _, _, matching = mlm_receipt(tmp_path)
    task['shower']['merging'] = deepcopy(matching)
    task['shower']['merging']['settings']['JetMatching:nJetMax'] = 2
    with pytest.raises(ValueError, match='hand-typed MLM block disagrees'):
        ep.compile_task(task, tmp_path)
    task['shower']['merging']['settings']['JetMatching:nJetMax'] = 1
    task['shower']['merging']['settings']['JetMatching:qCut'] = 40
    with pytest.raises(ValueError, match='hand-typed MLM block disagrees'):
        ep.compile_task(task, tmp_path)


def test_mlm_receipt_fills_matching_block_and_pins_source_cards(tmp_path):
    task, _, _, matching = mlm_receipt(tmp_path)
    compiled = ep.compile_task(task, tmp_path)
    assert 'merging' not in task['shower']
    assert compiled['merging']['qcut'] == 30 and compiled['merging']['xqcut'] == 20
    assert compiled['merging']['njetmax'] == 1
    assert compiled['generation']['matching']['jet_multiplicities'] == [0,1]
    assert set(ep.MLM_REQUIRED) <= {l.split('=',1)[0].strip() for l in compiled['variants'][0]['commands']}
    assert {'process.dat','run.dat','pythia.dat','tunes.json'} <= {p.name for p in ep.inputs(task, tmp_path)}
    task['shower']['merging'] = matching
    assert ep.compile_task(task, tmp_path)['merging'] == compiled['merging']


@pytest.mark.parametrize('change, message', [
    (lambda d: d.update(status='failed'), 'passed model-events'),
    (lambda d: d['intended']['generation'].update(jet_multiplicities=[0,2]), 'jet population'),
    (lambda d: d['intended']['generation']['run_settings'].update(xqcut=25), 'run settings'),
    (lambda d: d['generated_artifacts'][0].update(sha256='0'*64), 'uniquely name'),
])
def test_mlm_receipt_failed_or_mismatched_generation_refuses(tmp_path, change, message):
    task, doc, path, _ = mlm_receipt(tmp_path)
    change(doc)
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match=message):
        ep.compile_task(task, tmp_path)


def test_mlm_receipt_changed_pinned_shower_card_refuses(tmp_path):
    task, _, _, _ = mlm_receipt(tmp_path)
    (tmp_path / 'pythia.dat').write_text('JetMatching:qCut = 100\n')
    with pytest.raises(ValueError, match='differs from the generation receipt'):
        ep.compile_task(task, tmp_path)


def test_mlm_receipt_uses_ending_card_pins_after_native_output_rewrite(tmp_path):
    task, doc, path, _ = mlm_receipt(tmp_path)
    py = tmp_path / 'pythia.dat'
    py.write_text(py.read_text() + 'HEPMCoutput:file = native-events.hepmc\n')
    doc['generated_artifacts'][-1] = pin(py)
    doc['observed_settings']['shower'] = pythia_cards.parse(py.read_text())['settings']
    path.write_text(json.dumps(doc))
    assert doc['rendered_cards']['pythia']['sha256'] != pin(py)['sha256']
    assert ep.compile_task(task, tmp_path)['merging']['qcut'] == 30


def test_mlm_receipt_missing_explicit_matching_setting_refuses(tmp_path):
    task, doc, path, _ = mlm_receipt(tmp_path)
    py = tmp_path / 'pythia.dat'
    py.write_text('\n'.join(l for l in py.read_text().splitlines() if not l.startswith('JetMatching:nQmatch'))+'\n')
    doc['generated_artifacts'][-1] = pin(py)
    doc['observed_settings']['shower'] = pythia_cards.parse(py.read_text())['settings']
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='explicit complete MLM'):
        ep.compile_task(task, tmp_path)
