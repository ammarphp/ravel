"""Synthetic policy and producer controls; no native physics tools execute."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ravel.physics import native_effective_config as effective
from ravel.physics import native_event_io as io
from ravel.physics import native_pipeline as pipeline
from ravel.physics import sa2json_native as converter

ROOT = Path(__file__).resolve().parents[2]


def test_exclusion_missing_both_choices_is_refused(tmp_path):
    config = tmp_path / 'config.toml'
    config.write_text('[ravel.native]\nstatistics = "mapped-likelihood"\n')
    with pytest.raises(ValueError) as error:
        pipeline.build_execution_plan(tmp_path, config)
    assert 'mc_stat' in str(error.value)
    assert not (tmp_path / 'output').exists()


def test_agreement_without_declared_detector_is_refused(tmp_path):
    (tmp_path / 'inputs').mkdir()
    (tmp_path / 'inputs/plan.json').write_text(json.dumps({'claims': [{'kind': 'agreement'}]}))
    config = tmp_path / 'config.toml'
    config.write_text('[ravel.native]\nstatistics = "yields"\n')
    with pytest.raises(ValueError, match='agreement.*delphes_card'):
        pipeline.build_execution_plan(tmp_path, config)
    assert not (tmp_path / 'output').exists()


def test_translated_shower_always_writes_seed(tmp_path):
    source = tmp_path / 'source.cfg'
    source.write_text('PartonLevel:MPI = on\n')
    text, receipt = effective.translate_shower({}, source, lhe='events.lhe', nevents=2)
    settings = effective.assignments(text)
    assert settings['Random:setSeed'] == 'on'
    assert int(settings['Random:seed']) > 0
    assert receipt['seed'] == int(settings['Random:seed'])


def test_shower_receipt_records_seed_for_both_storage_modes(tmp_path, monkeypatch):
    card = tmp_path / 'card.cfg'
    card.write_text('Random:setSeed = on\nRandom:seed = 23\n')
    payload = 'HepMC::Asciiv3-START_EVENT_LISTING\nE 0 0 0\nE 1 0 0\nHepMC::Asciiv3-END_EVENT_LISTING\n'
    def fake_run(command, **kwargs):
        Path(command[2]).write_text(payload)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(io.subprocess, 'run', fake_run)
    for encoding in ('plain', 'gzip'):
        output = tmp_path / encoding
        io.shower('inert-producer', card, output, 2, encoding=encoding)
        receipt = json.loads(Path(str(output) + '.shower.json').read_text())
        assert receipt['seed'] == 23
        assert receipt['returncode'] == 0
        assert receipt['hepmc']['events'] == 2
        if encoding == 'gzip':
            assert json.loads(Path(str(output) + '.storage.json').read_text())['seed'] == 23


def test_one_pdf_recommendation_across_data_and_docs():
    data = json.loads((ROOT / 'native/setup/pdf-sets.json').read_text())
    assert data['default'] == {'name': 'NNPDF30_nlo_as_0118', 'lhaid': 260000}
    assert sum(row['name'] == data['default']['name'] and row['lhaid'] == data['default']['lhaid'] for row in data['sets']) == 1
    for logical in ('docs/workflow/reference/native-pipeline.md',):
        text = (ROOT / logical).read_text()
        assert 'NNPDF30_nlo_as_0118' in text and '260000' in text
        assert 'cteq6l1` (default)' not in text and 'nn23lo1` (default)' not in text


def test_converter_refuses_missing_explicit_choices_before_io(capsys):
    with pytest.raises(SystemExit) as error:
        converter.main(['-i', 'absent.root', '-b', 'absent.json', '-o', 'absent-output.json',
                        '-n', 'signal', '-l', '2', '-c'])
    assert error.value.code == 2
    diagnostic = capsys.readouterr().err
    assert '--mc-stat' in diagnostic and '--compressed-signal-model' in diagnostic


@pytest.mark.parametrize('missing', ['mc_stat'])
def test_each_exclusion_choice_is_independently_required(tmp_path, missing):
    native = {'statistics': 'mapped-likelihood', 'mc_stat': 'none', 'compressed_signal_model': 'full'}
    del native[missing]
    with pytest.raises(ValueError, match=missing):
        pipeline.require_claim_inputs({'ravel': {'native': native}}, tmp_path, 'mapped-likelihood')


def test_yield_diagnostics_and_declared_choices_are_admitted(tmp_path):
    pipeline.require_claim_inputs({}, tmp_path, 'yields')
    native = {'mc_stat': 'none', 'compressed_signal_model': 'full', 'inputs': {'delphes_card': 'declared.tcl'}}
    (tmp_path / 'inputs').mkdir()
    (tmp_path / 'inputs/plan.json').write_text(json.dumps({'claims': [{'kind': 'agreement'}, {'kind': 'exclusion'}]}))
    pipeline.require_claim_inputs({'ravel': {'native': native}}, tmp_path, 'mapped-likelihood')


def test_late_agreement_claim_is_rechecked_on_plan_load(tmp_path):
    config = tmp_path / 'config.toml'
    config.write_text('[ravel.native]\nstatistics = "yields"\n')
    plan = {'rundir': str(tmp_path), 'config': str(config), 'sources': [],
            'capability': {'statistics_adapter': 'yields'}}
    plan['plan_sha256'] = pipeline.plan_hash(plan)
    saved = tmp_path / 'native-plan.json'
    saved.write_text(json.dumps(plan))
    assert pipeline.load_plan(saved) == plan
    (tmp_path / 'inputs').mkdir()
    (tmp_path / 'inputs/task_contract.json').write_text(json.dumps({'task_mode': 'reproduce'}))
    with pytest.raises(ValueError, match='agreement.*delphes_card'):
        pipeline.load_plan(saved)


def test_explicit_prepared_copy_adds_seed_without_editing_source(tmp_path):
    inputs = {}
    for name, content in (('param_card', '# synthetic parameters\n'), ('run_card', '2 = nevents\n'),
                          ('process_card', '# synthetic process\n'),
                          ('shower_card', 'Beams:frameType = 4\nBeams:LHEF = source.lhe\n')):
        path = tmp_path / name
        path.write_text(content)
        inputs[name] = str(path)
    cfg = {'madgraph': {'run': {'seed': 7}}}
    translation = effective.explicit_shower_controls(cfg, inputs['shower_card'])
    source_bytes = Path(inputs['shower_card']).read_bytes()
    plan = {'rundir': str(tmp_path), 'capability': {'preparation': 'explicit-cards'},
            'inputs': inputs, 'shower_translation': translation}
    card = effective.assignments(effective.expected_cards(plan)['shower.cfg'])
    assert effective.shower_seed(card) == 7
    assert Path(inputs['shower_card']).read_bytes() == source_bytes
    assert translation['dispositions'][0]['disposition'] == 'explicit_adapter_seed'


@pytest.mark.parametrize('seed', ['0', '-1', '900000001', '1.5'])
def test_non_reproducible_explicit_seed_refused_before_producer(tmp_path, monkeypatch, seed):
    card = tmp_path / 'card.cfg'
    card.write_text(f'Random:setSeed = on\nRandom:seed = {seed}\n')
    monkeypatch.setattr(io.subprocess, 'run', lambda *args, **kwargs: pytest.fail('producer started'))
    with pytest.raises(ValueError, match='Random:seed'):
        io.shower('inert-producer', card, tmp_path / 'events', 2)
    assert not (tmp_path / 'events.shower.json').exists()


def test_label_only_versions_are_exposed_without_runtime_authentication():
    labels = effective.tool_version_labels({'madgraph': {'version': 'declared-1'},
                                          'pythia': {'version': 'declared-2'},
                                          'delphes': {'version': 'declared-3'},
                                          'simpleanalysis': {'version': 'declared-4'}})
    assert len(labels) == 4
    assert [row['declared'] for row in labels.values()] == ['declared-1', 'declared-2', 'declared-3', 'declared-4']
    assert all(row['disposition'] == 'label_only_native_runtime_version_unverified' for row in labels.values())
    assert effective.tool_version_labels({}) == {}


def test_changed_shower_card_cannot_publish_seed_receipt(tmp_path, monkeypatch):
    card = tmp_path / 'card.cfg'
    card.write_text('Random:setSeed = on\nRandom:seed = 23\n')
    def mutate_card(command, **kwargs):
        card.write_text('Random:setSeed = on\nRandom:seed = 24\n')
    monkeypatch.setattr(io.subprocess, 'run', mutate_card)
    output = tmp_path / 'events'
    with pytest.raises(ValueError, match='card changed'):
        io.shower('inert-producer', card, output, 2)
    assert not output.exists()
    assert not Path(str(output) + '.shower.json').exists()
